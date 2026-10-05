"""Unit tests for GeminiClient with mocked API responses (no live credentials required)."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from server.llm.gemini import (
    GeminiAuthenticationError,
    GeminiClient,
    GeminiConfigurationError,
    GeminiInvalidResponseError,
    GeminiRateLimitError,
    GeminiTimeoutError,
)
from server.models import (
    DatasetCategoryClassification,
    DatasetMetadata,
    DatasetRelevance,
    DatasetReport,
    DatasetSummary,
    DatasetValidationResult,
    EvidenceRecord,
    ProvenanceRecord,
)


@pytest.fixture
def sample_metadata() -> DatasetMetadata:
    return DatasetMetadata(
        name="empathy-mental-health",
        identifier="behavioral-data/Empathy-Mental-Health",
        source_platform="Hugging Face",
        source_url="https://huggingface.co/datasets/behavioral-data/Empathy-Mental-Health",
        description="Dataset of empathetic dialogues for mental health support.",
        data_type="conversation",
        license="CC-BY-4.0",
        language="en",
        tags=["mental-health", "empathy"],
        download_available=True,
        access_method="official_api",
    )


@pytest.fixture
def sample_validation() -> DatasetValidationResult:
    return DatasetValidationResult(
        dataset_name="empathy-mental-health",
        source_platform="Hugging Face",
        source_url="https://huggingface.co/datasets/behavioral-data/Empathy-Mental-Health",
        validation_status="documented",
        license_status="documented",
        license_name="CC-BY-4.0",
        privacy_status="no_statement_found",
        provenance_status="documented",
        provenance=ProvenanceRecord(
            discovered_from="GitHub README",
            source_repository="owner/repo",
            source_url="https://huggingface.co/datasets/behavioral-data/Empathy-Mental-Health",
            provider="Hugging Face",
            access_method="official_api",
            retrieved_at="2026-10-02T12:00:00Z",
        ),
        access_status="public_metadata",
        documentation_available=True,
        evidence=[
            EvidenceRecord(
                field="license",
                value="CC-BY-4.0",
                source="https://huggingface.co/datasets/behavioral-data/Empathy-Mental-Health",
                evidence_type="platform_license_metadata",
            )
        ],
        warnings=["No explicit dataset-level de-identification statement was found in documented metadata."],
        missing_information=["Explicit privacy/de-identification statement"],
    )


def _mock_response(text: str):
    resp = MagicMock()
    resp.text = text
    return resp


@pytest.mark.asyncio
async def test_summarize_dataset_success(sample_metadata, sample_validation):
    """Verify GeminiClient parses valid JSON into DatasetSummary."""
    client = GeminiClient(api_key="test-fake-key")

    mock_json = {
        "summary": "This dataset provides empathy-labeled dialogues for counseling research.",
        "data_type": "conversation",
        "purpose": "Study empathetic interactions in psychological support.",
        "likely_category": "conversation",
        "language": "en",
        "source": "Hugging Face",
        "documented_privacy": "No explicit dataset-level de-identification statement was found in documented metadata.",
        "documented_license": "CC-BY-4.0",
        "limitations": ["Lacks explicit de-identification statement"],
    }

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=_mock_response(json.dumps(mock_json)))
    client._genai_client = mock_client

    summary = await client.summarize_dataset(sample_metadata, sample_validation)

    assert isinstance(summary, DatasetSummary)
    assert summary.data_type == "conversation"
    assert "empathy-labeled dialogues" in summary.summary
    assert "CC-BY-4.0" in summary.documented_license
    assert "No explicit dataset-level de-identification" in summary.documented_privacy


@pytest.mark.asyncio
async def test_summarize_dataset_markdown_fences(sample_metadata, sample_validation):
    """Verify markdown fences (```json ... ```) are stripped safely."""
    client = GeminiClient(api_key="test-fake-key")

    mock_json = {
        "summary": "Fenced summary test.",
        "data_type": "conversation",
        "purpose": "Research.",
        "likely_category": "conversation",
        "language": "en",
        "source": "Hugging Face",
        "documented_privacy": "None documented.",
        "documented_license": "MIT",
        "limitations": [],
    }
    raw_text = f"```json\n{json.dumps(mock_json)}\n```"

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=_mock_response(raw_text))
    client._genai_client = mock_client

    summary = await client.summarize_dataset(sample_metadata, sample_validation)
    assert summary.summary == "Fenced summary test."


@pytest.mark.asyncio
async def test_summarize_dataset_malformed_json(sample_metadata, sample_validation):
    """Verify malformed JSON raises GeminiInvalidResponseError."""
    client = GeminiClient(api_key="test-fake-key")

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=_mock_response("Not a JSON response"))
    client._genai_client = mock_client

    with pytest.raises(GeminiInvalidResponseError) as exc_info:
        await client.summarize_dataset(sample_metadata, sample_validation)
    assert "could not be parsed as JSON" in str(exc_info.value)


@pytest.mark.asyncio
async def test_summarize_dataset_timeout(sample_metadata, sample_validation):
    """Verify timeout raises GeminiTimeoutError."""
    client = GeminiClient(api_key="test-fake-key", timeout=0.01)

    async def _slow_call(*args, **kwargs):
        await asyncio.sleep(0.1)
        return _mock_response("{}")

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(side_effect=_slow_call)
    client._genai_client = mock_client

    with pytest.raises(GeminiTimeoutError):
        await client.summarize_dataset(sample_metadata, sample_validation)


@pytest.mark.asyncio
async def test_summarize_dataset_auth_failure(sample_metadata, sample_validation):
    """Verify auth errors raise GeminiAuthenticationError."""
    client = GeminiClient(api_key="test-fake-key")

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=Exception("API key not valid. Please pass a valid API key.")
    )
    client._genai_client = mock_client

    with pytest.raises(GeminiAuthenticationError):
        await client.summarize_dataset(sample_metadata, sample_validation)


@pytest.mark.asyncio
async def test_summarize_dataset_rate_limit(sample_metadata, sample_validation):
    """Verify rate limit errors raise GeminiRateLimitError."""
    client = GeminiClient(api_key="test-fake-key")

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(
        side_effect=Exception("Resource has been exhausted (e.g. check quota).")
    )
    client._genai_client = mock_client

    with pytest.raises(GeminiRateLimitError):
        await client.summarize_dataset(sample_metadata, sample_validation)


@pytest.mark.asyncio
async def test_classify_dataset_success(sample_metadata):
    """Verify category classification succeeds and preserves deterministic data_type."""
    client = GeminiClient(api_key="test-fake-key")

    mock_json = {
        "deterministic_type": "conversation",
        "gemini_category": "conversation",
        "confidence": 0.95,
        "reason": "Explicitly contains dialogue exchanges between counselors and clients.",
    }

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=_mock_response(json.dumps(mock_json)))
    client._genai_client = mock_client

    classification = await client.classify_dataset(sample_metadata)

    assert isinstance(classification, DatasetCategoryClassification)
    assert classification.deterministic_type == "conversation"
    assert classification.gemini_category == "conversation"
    assert classification.confidence == 0.95


@pytest.mark.asyncio
async def test_classify_dataset_invalid_category_fallback(sample_metadata):
    """Verify out-of-taxonomy category is safely normalized to 'other'."""
    client = GeminiClient(api_key="test-fake-key")

    mock_json = {
        "deterministic_type": "conversation",
        "gemini_category": "unsupported_wild_category",
        "confidence": 0.50,
        "reason": "Testing fallback.",
    }

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=_mock_response(json.dumps(mock_json)))
    client._genai_client = mock_client

    classification = await client.classify_dataset(sample_metadata)
    assert classification.gemini_category == "other"
    assert classification.deterministic_type == "conversation"


@pytest.mark.asyncio
async def test_assess_relevance_high(sample_metadata):
    """Verify high relevance assessment parsing."""
    client = GeminiClient(api_key="test-fake-key")

    mock_json = {
        "relevance": "high",
        "confidence": 0.92,
        "reason": "Directly targets mental-health counseling dialogues.",
    }

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=_mock_response(json.dumps(mock_json)))
    client._genai_client = mock_client

    relevance = await client.assess_relevance(sample_metadata)
    assert isinstance(relevance, DatasetRelevance)
    assert relevance.relevance == "high"
    assert relevance.confidence == 0.92


@pytest.mark.asyncio
async def test_assess_relevance_levels(sample_metadata):
    """Verify medium, low, and unknown relevance levels."""
    client = GeminiClient(api_key="test-fake-key")
    mock_client = MagicMock()
    client._genai_client = mock_client

    for level in ["medium", "low", "unknown"]:
        mock_json = {
            "relevance": level,
            "confidence": 0.80,
            "reason": f"Testing {level} level.",
        }
        mock_client.aio.models.generate_content = AsyncMock(return_value=_mock_response(json.dumps(mock_json)))
        rel = await client.assess_relevance(sample_metadata)
        assert rel.relevance == level


@pytest.mark.asyncio
async def test_generate_dataset_report_success(sample_metadata, sample_validation):
    """Verify human-readable dataset report generation."""
    client = GeminiClient(api_key="test-fake-key")

    mock_json = {
        "dataset_name": "empathy-mental-health",
        "source_platform": "Hugging Face",
        "purpose": "Counseling empathy research.",
        "data_type": "conversation",
        "language": "en",
        "license": "CC-BY-4.0",
        "privacy_documentation": "No explicit dataset-level de-identification statement was found.",
        "access_method": "public_metadata",
        "provenance": "Hugging Face Hub API",
        "warnings": ["Missing privacy statement"],
        "missing_information": ["De-identification documentation"],
        "relevance": "High topical relevance to mental-health dialogue processing.",
        "notes": "None",
        "formatted_report": "Dataset: empathy-mental-health\nSource: Hugging Face\nPurpose: Counseling empathy research.",
    }

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=_mock_response(json.dumps(mock_json)))
    client._genai_client = mock_client

    report = await client.generate_dataset_report(sample_metadata, sample_validation)
    assert isinstance(report, DatasetReport)
    assert report.dataset_name == "empathy-mental-health"
    assert "Dataset: empathy-mental-health" in report.formatted_report


def test_missing_api_key_raises_configuration_error():
    """Verify that calling an API operation without an API key raises GeminiConfigurationError."""
    with patch.dict("os.environ", {}, clear=True):
        client = GeminiClient(api_key="")
        with pytest.raises(GeminiConfigurationError):
            client._get_genai_client()


def test_payload_sanitization_no_credentials(sample_metadata, sample_validation):
    """Verify structured payload contains ONLY clean metadata and validation without tokens."""
    payload = GeminiClient.build_structured_payload(sample_metadata, sample_validation)

    payload_str = json.dumps(payload).lower()
    assert "token" not in payload_str
    assert "secret" not in payload_str
    assert "password" not in payload_str
    assert "api_key" not in payload_str
    assert payload["dataset"]["name"] == "empathy-mental-health"
    assert payload["validation"]["license_name"] == "CC-BY-4.0"
