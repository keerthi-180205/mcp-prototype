"""Unit tests for Phase 5 external dataset connectors (Hugging Face, Kaggle, Zenodo) and URL resolver."""

import pytest
import httpx

from server.models import DatasetMetadata
from server.providers.huggingface import (
    HuggingFaceProvider,
    HuggingFaceNotFoundError,
    HuggingFaceAuthenticationError,
    HuggingFaceRateLimitError,
    HuggingFaceTimeoutError,
)
from server.providers.kaggle import (
    KaggleProvider,
    KaggleAuthenticationError,
    KaggleNotFoundError,
)
from server.providers.resolver import resolve_dataset_provider
from server.providers.zenodo import (
    ZenodoProvider,
    ZenodoNotFoundError,
)


# ==============================================================================
# URL Resolver Tests
# ==============================================================================

def test_resolve_dataset_provider_huggingface():
    """Verify Hugging Face dataset URLs resolve properly."""
    plat, ident = resolve_dataset_provider("https://huggingface.co/datasets/mental-nlp/therapy-dialogues")
    assert plat == "huggingface"
    assert ident == "mental-nlp/therapy-dialogues"

    plat2, ident2 = resolve_dataset_provider("https://hf.co/datasets/emotion-benchmark")
    assert plat2 == "huggingface"
    assert ident2 == "emotion-benchmark"


def test_resolve_dataset_provider_kaggle():
    """Verify Kaggle dataset URLs resolve properly."""
    plat, ident = resolve_dataset_provider("https://www.kaggle.com/datasets/mentalhealth/reddit-depression")
    assert plat == "kaggle"
    assert ident == "mentalhealth/reddit-depression"


def test_resolve_dataset_provider_zenodo():
    """Verify Zenodo dataset URLs resolve properly."""
    plat, ident = resolve_dataset_provider("https://zenodo.org/records/1234567")
    assert plat == "zenodo"
    assert ident == "1234567"

    plat2, ident2 = resolve_dataset_provider("https://zenodo.org/record/7654321")
    assert plat2 == "zenodo"
    assert ident2 == "7654321"

    plat3, ident3 = resolve_dataset_provider("https://doi.org/10.5281/zenodo.998877")
    assert plat3 == "zenodo"
    assert ident3 == "998877"


def test_resolve_dataset_provider_unknown():
    """Verify unsupported domains return unknown."""
    plat, ident = resolve_dataset_provider("https://example.com/arbitrary/path")
    assert plat == "unknown"
    assert ident is None

    plat2, ident2 = resolve_dataset_provider("")
    assert plat2 == "unknown"
    assert ident2 is None


# ==============================================================================
# Hugging Face Connector Tests
# ==============================================================================

SAMPLE_HF_RESPONSE = {
    "_id": "64abcdef",
    "id": "mental-nlp/therapy-dialogues",
    "description": "Multi-turn therapy dialogue transcripts. All conversations are explicitly anonymized.",
    "createdAt": "2025-01-10T12:00:00.000Z",
    "lastModified": "2026-02-15T08:00:00.000Z",
    "tags": ["mental-health", "therapy", "license:apache-2.0", "language:en", "format:parquet"],
    "cardData": {
        "license": "apache-2.0",
        "language": ["en"],
    },
    "private": False,
    "gated": False,
    "siblings": [{"rfilename": "train.parquet", "size": 1500000}],
}


@pytest.mark.asyncio
async def test_huggingface_get_metadata_success():
    """Verify Hugging Face metadata normalization."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/datasets/mental-nlp/therapy-dialogues" in str(request.url)
        return httpx.Response(200, json=SAMPLE_HF_RESPONSE)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = HuggingFaceProvider(client=client)

    metadata = await provider.get_dataset_metadata("mental-nlp/therapy-dialogues")

    assert isinstance(metadata, DatasetMetadata)
    assert metadata.name == "mental-nlp/therapy-dialogues"
    assert metadata.source_platform == "Hugging Face"
    assert metadata.license == "apache-2.0"
    assert metadata.language == "en"
    assert metadata.data_type == "conversation"
    assert metadata.explicitly_anonymized is True
    assert metadata.download_available is True
    assert metadata.size_bytes == 1500000


@pytest.mark.asyncio
async def test_huggingface_not_found():
    """Verify 404 raises HuggingFaceNotFoundError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "Entry not found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = HuggingFaceProvider(client=client)

    with pytest.raises(HuggingFaceNotFoundError):
        await provider.get_dataset_metadata("nonexistent/dataset")


@pytest.mark.asyncio
async def test_huggingface_auth_error():
    """Verify 401 raises HuggingFaceAuthenticationError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Unauthorized"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = HuggingFaceProvider(client=client)

    with pytest.raises(HuggingFaceAuthenticationError):
        await provider.get_dataset_metadata("private/gated-dataset")


# ==============================================================================
# Kaggle Connector Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_kaggle_unauthenticated_error():
    """Verify Kaggle raises authentication error when credentials are not configured."""
    provider = KaggleProvider(username=None, key=None)
    with pytest.raises(KaggleAuthenticationError) as exc_info:
        await provider.get_dataset_metadata("owner/dataset-name")
    assert "authentication unavailable" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_kaggle_authenticated_success():
    """Verify Kaggle metadata retrieval when credentials are provided."""
    sample_kaggle_data = {
        "title": "Reddit Mental Health Posts",
        "description": "Depression and anxiety social media corpus.",
        "licenseName": "CC-BY-4.0",
        "totalBytes": 8500000,
        "lastUpdated": "2026-01-20T10:00:00Z",
        "keywords": [{"name": "mental-health"}, {"name": "depression"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "Authorization" in request.headers
        assert "/api/v1/datasets/view/mentalhealth/reddit-depression" in str(request.url)
        return httpx.Response(200, json=sample_kaggle_data)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = KaggleProvider(username="mock_user", key="mock_key", client=client)

    metadata = await provider.get_dataset_metadata("mentalhealth/reddit-depression")

    assert metadata.name == "Reddit Mental Health Posts"
    assert metadata.source_platform == "Kaggle"
    assert metadata.license == "CC-BY-4.0"
    assert metadata.size_bytes == 8500000
    assert metadata.data_type == "text"


# ==============================================================================
# Zenodo Connector Tests
# ==============================================================================

SAMPLE_ZENODO_RESPONSE = {
    "id": 1234567,
    "doi": "10.5281/zenodo.1234567",
    "created": "2025-06-01T12:00:00Z",
    "modified": "2026-01-15T09:00:00Z",
    "metadata": {
        "title": "PHQ-9 Depression Assessment Survey Dataset",
        "description": "De-identified survey responses assessing depressive symptoms.",
        "license": {"id": "CC-BY-4.0"},
        "keywords": ["mental health", "phq-9", "depression"],
        "creators": [{"name": "Smith, Jane"}, {"name": "Doe, John"}],
        "doi": "10.5281/zenodo.1234567",
    },
    "files": [{"key": "survey_data.csv", "size": 450000}],
}


@pytest.mark.asyncio
async def test_zenodo_get_metadata_success():
    """Verify Zenodo public metadata retrieval without authentication."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/api/records/1234567" in str(request.url)
        return httpx.Response(200, json=SAMPLE_ZENODO_RESPONSE)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ZenodoProvider(client=client)

    metadata = await provider.get_dataset_metadata("1234567")

    assert metadata.name == "PHQ-9 Depression Assessment Survey Dataset"
    assert metadata.source_platform == "Zenodo"
    assert metadata.license == "CC-BY-4.0"
    assert metadata.data_type == "mental_health_assessment"
    assert metadata.explicitly_deidentified is True
    assert metadata.size_bytes == 450000
    assert "Smith, Jane" in (metadata.provenance or "")


@pytest.mark.asyncio
async def test_zenodo_not_found():
    """Verify 404 raises ZenodoNotFoundError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "PID does not exist"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = ZenodoProvider(client=client)

    with pytest.raises(ZenodoNotFoundError):
        await provider.get_dataset_metadata("999999999")
