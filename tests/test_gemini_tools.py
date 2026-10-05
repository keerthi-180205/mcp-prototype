"""Unit tests for Phase 7 Gemini MCP tools (summarize_dataset, analyze_dataset_relevance, generate_dataset_report)."""

from unittest.mock import AsyncMock, patch
import pytest

from server import server
from server.llm.gemini import (
    GeminiAuthenticationError,
    GeminiRateLimitError,
)
from server.models import (
    DatasetCategoryClassification,
    DatasetMetadata,
    DatasetRelevance,
    DatasetReport,
    DatasetSummary,
    DatasetValidationResult,
)
from server.server import (
    analyze_dataset_relevance,
    generate_dataset_report,
    summarize_dataset,
)

SAMPLE_METADATA = DatasetMetadata(
    name="dair-ai/emotion",
    identifier="dair-ai/emotion",
    source_platform="Hugging Face",
    source_url="https://huggingface.co/datasets/dair-ai/emotion",
    description="Emotion dataset with labeled Twitter messages.",
    data_type="text",
    license="other",
    language="en",
    download_available=True,
    access_method="official_api",
)

SAMPLE_SUMMARY = DatasetSummary(
    summary="Text dataset labeled with six basic emotions.",
    data_type="text",
    purpose="Emotion classification NLP.",
    likely_category="emotion",
    language="en",
    source="Hugging Face",
    documented_privacy="No explicit statement found.",
    documented_license="other",
    limitations=["License listed as other"],
)

SAMPLE_RELEVANCE = DatasetRelevance(
    relevance="medium",
    confidence=0.88,
    reason="Emotion classification is relevant to affective computing and mental-health sentiment.",
)

SAMPLE_CLASSIFICATION = DatasetCategoryClassification(
    deterministic_type="text",
    gemini_category="emotion",
    confidence=0.92,
    reason="Labeled emotion texts.",
)

SAMPLE_REPORT = DatasetReport(
    dataset_name="dair-ai/emotion",
    source_platform="Hugging Face",
    purpose="Emotion classification.",
    data_type="text",
    language="en",
    license="other",
    privacy_documentation="No explicit dataset-level de-identification statement was found.",
    access_method="public_metadata",
    provenance="Hugging Face Hub API",
    warnings=["License is other"],
    missing_information=["Explicit privacy documentation"],
    relevance="Medium relevance to emotional state analysis.",
    notes="None",
    formatted_report="=== Dataset Report ===\nDataset: dair-ai/emotion",
)


@pytest.mark.asyncio
async def test_summarize_dataset_tool_success():
    """Verify summarize_dataset fetches metadata, validates, and invokes GeminiClient."""
    mock_get_meta = AsyncMock(return_value=SAMPLE_METADATA)
    mock_summarize = AsyncMock(return_value=SAMPLE_SUMMARY)

    with patch.object(server.huggingface_provider, "get_dataset_metadata", mock_get_meta), \
         patch.object(server.gemini_client, "summarize_dataset", mock_summarize):

        res = await summarize_dataset("https://huggingface.co/datasets/dair-ai/emotion")
        assert res["status"] == "success"
        assert res["dataset"] == "dair-ai/emotion"
        assert res["provider"] == "huggingface"
        assert "Text dataset labeled" in res["summary"]["summary"]
        assert res["summary"]["data_type"] == "text"


@pytest.mark.asyncio
async def test_summarize_dataset_tool_unsupported_url():
    """Verify summarize_dataset rejects unsupported URLs."""
    res = await summarize_dataset("https://unsupported-site.com/dataset/1")
    assert res["status"] == "unsupported_provider"
    assert "not correspond to a supported platform" in res["message"]


@pytest.mark.asyncio
async def test_summarize_dataset_tool_empty_url():
    """Verify summarize_dataset validates empty input URL."""
    res = await summarize_dataset("   ")
    assert res["status"] == "error"
    assert res["error"] == "invalid_parameter"


@pytest.mark.asyncio
async def test_summarize_dataset_tool_gemini_auth_error():
    """Verify Gemini auth error is translated to structured MCP error response."""
    mock_get_meta = AsyncMock(return_value=SAMPLE_METADATA)
    mock_summarize = AsyncMock(side_effect=GeminiAuthenticationError("Invalid API key provided"))

    with patch.object(server.huggingface_provider, "get_dataset_metadata", mock_get_meta), \
         patch.object(server.gemini_client, "summarize_dataset", mock_summarize):

        res = await summarize_dataset("https://huggingface.co/datasets/dair-ai/emotion")
        assert res["status"] == "error"
        assert res["provider"] == "gemini"
        assert res["error_type"] == "auth_error"
        assert "Invalid API key" in res["message"]


@pytest.mark.asyncio
async def test_summarize_dataset_tool_gemini_rate_limit():
    """Verify Gemini rate limit error is translated to structured MCP error response."""
    mock_get_meta = AsyncMock(return_value=SAMPLE_METADATA)
    mock_summarize = AsyncMock(side_effect=GeminiRateLimitError("Quota exceeded"))

    with patch.object(server.huggingface_provider, "get_dataset_metadata", mock_get_meta), \
         patch.object(server.gemini_client, "summarize_dataset", mock_summarize):

        res = await summarize_dataset("https://huggingface.co/datasets/dair-ai/emotion")
        assert res["status"] == "error"
        assert res["provider"] == "gemini"
        assert res["error_type"] == "rate_limit"


@pytest.mark.asyncio
async def test_analyze_dataset_relevance_tool_success():
    """Verify analyze_dataset_relevance returns relevance and categorization."""
    mock_get_meta = AsyncMock(return_value=SAMPLE_METADATA)
    mock_assess = AsyncMock(return_value=SAMPLE_RELEVANCE)
    mock_classify = AsyncMock(return_value=SAMPLE_CLASSIFICATION)

    with patch.object(server.huggingface_provider, "get_dataset_metadata", mock_get_meta), \
         patch.object(server.gemini_client, "assess_relevance", mock_assess), \
         patch.object(server.gemini_client, "classify_dataset", mock_classify):

        res = await analyze_dataset_relevance("https://huggingface.co/datasets/dair-ai/emotion")
        assert res["status"] == "success"
        assert res["dataset"] == "dair-ai/emotion"
        assert res["relevance"]["relevance"] == "medium"
        assert res["category_classification"]["gemini_category"] == "emotion"
        assert res["category_classification"]["deterministic_type"] == "text"


@pytest.mark.asyncio
async def test_generate_dataset_report_tool_success():
    """Verify generate_dataset_report returns complete structured report."""
    mock_get_meta = AsyncMock(return_value=SAMPLE_METADATA)
    mock_report = AsyncMock(return_value=SAMPLE_REPORT)

    with patch.object(server.huggingface_provider, "get_dataset_metadata", mock_get_meta), \
         patch.object(server.gemini_client, "generate_dataset_report", mock_report):

        res = await generate_dataset_report("https://huggingface.co/datasets/dair-ai/emotion")
        assert res["status"] == "success"
        assert res["dataset"] == "dair-ai/emotion"
        assert "formatted_report" in res["report"]
        assert "=== Dataset Report ===" in res["report"]["formatted_report"]
