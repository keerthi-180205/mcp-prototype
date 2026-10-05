"""Gemini client and structured interpretation layer for MMTF dataset discovery."""

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, Optional, Type, TypeVar
from pydantic import BaseModel, ValidationError

try:
    from google import genai
    from google.genai import errors as genai_errors
    from google.genai import types as genai_types
except ImportError:
    genai = None
    genai_errors = None
    genai_types = None


from server.llm.prompts import (
    build_classification_prompt,
    build_relevance_prompt,
    build_report_prompt,
    build_summary_prompt,
)
from server.models import (
    DatasetCategoryClassification,
    DatasetMetadata,
    DatasetRelevance,
    DatasetReport,
    DatasetSummary,
    DatasetValidationResult,
)
from server.config import Settings, get_settings
from server.logging_config import async_timed_operation, get_logger
from server.resilience import retry_async_operation

logger = get_logger(__name__)


T = TypeVar("T", bound=BaseModel)

ALLOWED_CATEGORIES = {
    "conversation",
    "text",
    "survey",
    "emotion",
    "sentiment",
    "mental_health_assessment",
    "research_data",
    "multimodal",
    "other",
    "unknown",
}


class GeminiError(Exception):
    """Base exception for all Gemini LLM provider errors."""


class GeminiConfigurationError(GeminiError):
    """Raised when GEMINI_API_KEY or configuration is missing or invalid."""


class GeminiAuthenticationError(GeminiError):
    """Raised when Gemini API authentication or permissions fail."""


class GeminiRateLimitError(GeminiError):
    """Raised when Gemini quota or rate limits are exceeded."""


class GeminiTimeoutError(GeminiError):
    """Raised when Gemini API request times out."""


class GeminiConnectionError(GeminiError):
    """Raised when network connectivity to Gemini API fails."""


class GeminiInvalidResponseError(GeminiError):
    """Raised when Gemini produces unparseable or schema-violating responses."""


class GeminiClient:
    """Client for structured interpretation over dataset metadata and validation findings."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        cfg = settings or get_settings()
        if api_key is not None:
            self.api_key = api_key or None
        else:
            self.api_key = cfg.gemini_api_key

        self.model = model or cfg.gemini_model
        try:
            self.timeout = float(timeout if timeout is not None else cfg.gemini_timeout)
        except (ValueError, TypeError):
            self.timeout = 90.0

        self._genai_client = None


    def _get_genai_client(self):
        """Instantiate or return the underlying google.genai.Client instance."""
        if not self.api_key:
            raise GeminiConfigurationError(
                "GEMINI_API_KEY environment variable is not configured. "
                "Provide an API key via environment variable or client parameter."
            )
        if genai is None:
            raise GeminiConfigurationError(
                "google-genai SDK is not installed. Please install 'google-genai' package."
            )
        if self._genai_client is None:
            self._genai_client = genai.Client(api_key=self.api_key)
        return self._genai_client

    @staticmethod
    def build_structured_payload(
        metadata: DatasetMetadata,
        validation: Optional[DatasetValidationResult] = None,
    ) -> Dict[str, Any]:
        """Convert DatasetMetadata and DatasetValidationResult into sanitized structured input.

        Guarantees that no authentication credentials, tokens, or raw contents are passed.
        """
        payload: Dict[str, Any] = {
            "dataset": {
                "name": metadata.name,
                "identifier": metadata.identifier,
                "source_platform": metadata.source_platform,
                "source_url": metadata.source_url,
                "description": metadata.description,
                "data_type": metadata.data_type,
                "license": metadata.license,
                "language": metadata.language,
                "tags": metadata.tags,
                "download_available": metadata.download_available,
                "access_method": metadata.access_method,
            }
        }

        if validation:
            payload["validation"] = {
                "validation_status": validation.validation_status,
                "license_status": validation.license_status,
                "license_name": validation.license_name,
                "privacy_status": validation.privacy_status,
                "explicitly_deidentified": validation.explicitly_deidentified,
                "explicitly_anonymized": validation.explicitly_anonymized,
                "contains_sensitive_data_warning": validation.contains_sensitive_data_warning,
                "provenance_status": validation.provenance_status,
                "access_status": validation.access_status,
                "documentation_available": validation.documentation_available,
                "warnings": validation.warnings,
                "missing_information": validation.missing_information,
            }
            if validation.provenance:
                payload["provenance"] = {
                    "discovered_from": validation.provenance.discovered_from,
                    "source_repository": validation.provenance.source_repository,
                    "source_url": validation.provenance.source_url,
                    "provider": validation.provenance.provider,
                    "access_method": validation.provenance.access_method,
                    "retrieved_at": validation.provenance.retrieved_at,
                }

        return payload

    @staticmethod
    def _extract_json_text(raw_text: str) -> str:
        """Strip markdown fences (e.g. ```json ... ```) and extract clean JSON."""
        cleaned = raw_text.strip()
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.I)
        if match:
            return match.group(1).strip()
        return cleaned

    async def _generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
    ) -> T:
        """Execute Gemini request with timeout, error handling, and Pydantic validation."""
        client = self._get_genai_client()

        gen_config = None
        if genai_types and hasattr(genai_types, "GenerateContentConfig") and hasattr(genai_types, "AutomaticFunctionCallingConfig"):
            gen_config = genai_types.GenerateContentConfig(
                automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(disable=True)
            )

        async def _call_gemini():
            try:
                logger.info("[GEMINI] Calling Gemini model '%s' for structured interpretation", self.model)
                kwargs: Dict[str, Any] = {"model": self.model, "contents": prompt}
                if gen_config is not None:
                    kwargs["config"] = gen_config

                return await asyncio.wait_for(
                    client.aio.models.generate_content(**kwargs),
                    timeout=self.timeout,
                )
            except asyncio.TimeoutError as exc:
                logger.warning("[GEMINI] Request timed out after %.1fs", self.timeout)
                raise GeminiTimeoutError(f"Gemini API request timed out after {self.timeout}s") from exc
            except Exception as exc:
                self._translate_exception(exc)

        async with async_timed_operation(logger, component="gemini", operation="interpret", model=self.model):
            response = await retry_async_operation(
                _call_gemini,
                retryable_exceptions=(GeminiRateLimitError, GeminiConnectionError, GeminiTimeoutError),
                operation_name="gemini_request",
                max_retries=2,
                initial_delay=1.0,
            )



        raw_text = getattr(response, "text", "") or ""
        if not raw_text.strip():
            raise GeminiInvalidResponseError("Gemini returned an empty response.")

        clean_json = self._extract_json_text(raw_text)

        try:
            parsed_data = json.loads(clean_json)
        except json.JSONDecodeError as exc:
            logger.error("[GEMINI] Failed to parse JSON from response: %s", raw_text)
            raise GeminiInvalidResponseError(
                f"Gemini output could not be parsed as JSON: {exc}"
            ) from exc

        try:
            return response_model.model_validate(parsed_data)
        except ValidationError as exc:
            logger.error("[GEMINI] Response failed Pydantic validation: %s", exc)
            raise GeminiInvalidResponseError(
                f"Gemini output does not conform to expected schema {response_model.__name__}: {exc}"
            ) from exc

    def _translate_exception(self, exc: Exception) -> None:
        """Map SDK and network exceptions to domain-specific GeminiError types."""
        err_str = str(exc).lower()

        # Check for google.genai errors if available
        if genai_errors and isinstance(exc, genai_errors.APIError):
            code = getattr(exc, "code", None)
            if code in (401, 403) or "unauthenticated" in err_str or "api_key" in err_str or "permission" in err_str:
                raise GeminiAuthenticationError(f"Gemini authentication failed: {exc}") from exc
            if code == 429 or "resource_exhausted" in err_str or "quota" in err_str or "rate limit" in err_str:
                raise GeminiRateLimitError(f"Gemini rate limit exceeded: {exc}") from exc
            if code in (503, 504) or "timeout" in err_str or "deadline" in err_str:
                raise GeminiTimeoutError(f"Gemini request timed out: {exc}") from exc
            raise GeminiError(f"Gemini API error ({code}): {exc}") from exc

        if "api key" in err_str or "unauthenticated" in err_str or "401" in err_str or "403" in err_str:
            raise GeminiAuthenticationError(f"Gemini authentication failed: {exc}") from exc
        if "quota" in err_str or "rate limit" in err_str or "429" in err_str or "resource exhausted" in err_str:
            raise GeminiRateLimitError(f"Gemini rate limit exceeded: {exc}") from exc
        if "timeout" in err_str or "timed out" in err_str:
            raise GeminiTimeoutError(f"Gemini connection timed out: {exc}") from exc
        if "connection" in err_str or "connect" in err_str or "network" in err_str:
            raise GeminiConnectionError(f"Failed to connect to Gemini API: {exc}") from exc

        raise GeminiError(f"Unexpected error communicating with Gemini API: {exc}") from exc

    async def summarize_dataset(
        self,
        metadata: DatasetMetadata,
        validation: DatasetValidationResult,
    ) -> DatasetSummary:
        """Produce an objective, structured summary of a dataset based strictly on documented facts."""
        payload = self.build_structured_payload(metadata, validation)
        prompt = build_summary_prompt(payload)
        summary = await self._generate_structured(prompt, DatasetSummary)
        logger.info("[GEMINI] Generated summary for dataset '%s'", metadata.name)
        return summary

    async def classify_dataset(
        self,
        metadata: DatasetMetadata,
        validation: Optional[DatasetValidationResult] = None,
    ) -> DatasetCategoryClassification:
        """Classify dataset category based on metadata while preserving original deterministic type."""
        payload = self.build_structured_payload(metadata, validation)
        prompt = build_classification_prompt(payload)
        classification = await self._generate_structured(prompt, DatasetCategoryClassification)

        # Enforce deterministic type preservation
        classification.deterministic_type = metadata.data_type

        # Validate category within allowed taxonomy
        if classification.gemini_category not in ALLOWED_CATEGORIES:
            classification.gemini_category = "other"

        logger.info(
            "[GEMINI] Classified dataset '%s' as category '%s' (Deterministic: %s)",
            metadata.name,
            classification.gemini_category,
            classification.deterministic_type,
        )
        return classification

    async def assess_relevance(
        self,
        metadata: DatasetMetadata,
        validation: Optional[DatasetValidationResult] = None,
    ) -> DatasetRelevance:
        """Assess dataset relevance for mental-health and emotional NLP research (NOT a safety or legal score)."""
        payload = self.build_structured_payload(metadata, validation)
        prompt = build_relevance_prompt(payload)
        relevance = await self._generate_structured(prompt, DatasetRelevance)

        # Ensure relevance is one of the allowed levels
        if relevance.relevance.lower() not in {"high", "medium", "low", "unknown"}:
            relevance.relevance = "unknown"

        logger.info(
            "[GEMINI] Assessed relevance for '%s': %s (Confidence: %.2f)",
            metadata.name,
            relevance.relevance,
            relevance.confidence,
        )
        return relevance

    async def generate_dataset_report(
        self,
        metadata: DatasetMetadata,
        validation: DatasetValidationResult,
    ) -> DatasetReport:
        """Generate a complete structured human-readable dataset report combining facts and synthesis."""
        payload = self.build_structured_payload(metadata, validation)
        prompt = build_report_prompt(payload)
        report = await self._generate_structured(prompt, DatasetReport)
        logger.info("[GEMINI] Generated complete report for dataset '%s'", metadata.name)
        return report
