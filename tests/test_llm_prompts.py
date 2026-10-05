"""Tests for Gemini prompt construction and guardrail enforcement."""

from server.llm.prompts import (
    SYSTEM_GUARDRAILS,
    build_classification_prompt,
    build_relevance_prompt,
    build_report_prompt,
    build_summary_prompt,
)


def _sample_payload():
    return {
        "dataset": {
            "name": "empathy-mental-health",
            "identifier": "behavioral-data/Empathy-Mental-Health",
            "source_platform": "Hugging Face",
            "source_url": "https://huggingface.co/datasets/behavioral-data/Empathy-Mental-Health",
            "description": "Dialogue dataset for empathetic mental-health counseling.",
            "data_type": "conversation",
            "license": "CC-BY-4.0",
            "language": "en",
            "tags": ["mental-health", "empathy"],
            "download_available": True,
            "access_method": "official_api",
        },
        "validation": {
            "validation_status": "documented",
            "license_status": "documented",
            "license_name": "CC-BY-4.0",
            "privacy_status": "no_statement_found",
            "explicitly_deidentified": None,
            "explicitly_anonymized": None,
            "contains_sensitive_data_warning": None,
            "provenance_status": "documented",
            "access_status": "public_metadata",
            "documentation_available": True,
            "warnings": [
                "No explicit dataset-level de-identification statement was found."
            ],
            "missing_information": [
                "Explicit privacy/de-identification statement"
            ],
        },
    }


def test_system_guardrails_contain_critical_rules():
    """Verify guardrails mandate no hallucination, no legal decisions, and strict privacy grounding."""
    assert "rely strictly and exclusively on the supplied json" in SYSTEM_GUARDRAILS.lower()
    assert "no speculative privacy inferences" in SYSTEM_GUARDRAILS.lower()
    assert "no legal or ethical approval decisions" in SYSTEM_GUARDRAILS.lower()
    assert "keep documented facts distinct from analytical interpretations" in SYSTEM_GUARDRAILS.lower()


def test_build_summary_prompt():
    """Verify summary prompt embeds structured payload and enforces JSON schema."""
    payload = _sample_payload()
    prompt = build_summary_prompt(payload)

    assert "empathy-mental-health" in prompt
    assert "documented_privacy" in prompt
    assert "documented_license" in prompt
    assert "limitations" in prompt
    assert "Respond ONLY with valid JSON" in prompt


def test_build_classification_prompt():
    """Verify classification prompt preserves deterministic type and lists allowed categories."""
    payload = _sample_payload()
    prompt = build_classification_prompt(payload)

    assert "conversation" in prompt
    assert "deterministic_type" in prompt
    assert "gemini_category" in prompt
    assert "mental_health_assessment" in prompt


def test_build_relevance_prompt():
    """Verify relevance prompt contains allowed rating levels and clarifies non-legal scope."""
    payload = _sample_payload()
    prompt = build_relevance_prompt(payload)

    assert "high | medium | low | unknown" in prompt
    assert "NOT a safety, ethical, or legal score" in prompt


def test_build_report_prompt():
    """Verify report prompt enforces explicit unknown reporting."""
    payload = _sample_payload()
    prompt = build_report_prompt(payload)

    assert "formatted_report" in prompt
    assert "Never claim a dataset is anonymized or safe" in prompt
