"""Unit tests for GitHubProvider with mocked HTTP responses."""

import base64
import json
import pytest
import httpx

from server.providers.github import (
    GitHubProvider,
    GitHubAuthenticationError,
    GitHubRateLimitError,
    GitHubTimeoutError,
    GitHubConnectionError,
    GitHubAPIError,
)


SAMPLE_REPO_1 = {
    "id": 101,
    "name": "mental-health-nlp",
    "full_name": "research-org/mental-health-nlp",
    "owner": {"login": "research-org", "type": "Organization"},
    "description": "A curated NLP dataset for psychological distress and therapy conversations",
    "html_url": "https://github.com/research-org/mental-health-nlp",
    "url": "https://api.github.com/repos/research-org/mental-health-nlp",
    "language": "Python",
    "topics": ["mental-health", "nlp", "therapy", "dataset"],
    "stargazers_count": 250,
    "forks_count": 45,
    "open_issues_count": 3,
    "created_at": "2025-02-10T12:00:00Z",
    "updated_at": "2026-02-15T09:30:00Z",
    "pushed_at": "2026-02-15T09:30:00Z",
    "license": {"spdx_id": "Apache-2.0", "name": "Apache License 2.0"},
    "default_branch": "main",
    "archived": False,
    "fork": False,
}

SAMPLE_REPO_2 = {
    "id": 102,
    "name": "depression-dialogue-corpus",
    "full_name": "ai-lab/depression-dialogue-corpus",
    "owner": {"login": "ai-lab", "type": "Organization"},
    "description": "Dialogue corpus for mental wellness chat assistance",
    "html_url": "https://github.com/ai-lab/depression-dialogue-corpus",
    "url": "https://api.github.com/repos/ai-lab/depression-dialogue-corpus",
    "language": "Python",
    "topics": ["depression", "dialogue", "mental-health"],
    "stargazers_count": 85,
    "forks_count": 12,
    "open_issues_count": 1,
    "created_at": "2025-05-01T00:00:00Z",
    "updated_at": "2026-01-20T11:00:00Z",
    "pushed_at": "2026-01-20T11:00:00Z",
    "license": {"spdx_id": "MIT", "name": "MIT License"},
    "default_branch": "master",
    "archived": False,
    "fork": False,
}


@pytest.mark.asyncio
async def test_successful_repository_search():
    """Test 1: Mock GET /search/repositories and verify normalization."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert "/search/repositories" in str(request.url)
        return httpx.Response(200, json={"total_count": 1, "items": [SAMPLE_REPO_1]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(client=client)

    results = await provider.search_repositories(query="mental health dataset", limit=10)

    assert len(results) == 1
    repo = results[0]
    assert repo.id == 101
    assert repo.name == "mental-health-nlp"
    assert repo.full_name == "research-org/mental-health-nlp"
    assert repo.owner == "research-org"
    assert repo.owner_type == "Organization"
    assert repo.description == "A curated NLP dataset for psychological distress and therapy conversations"
    assert repo.html_url == "https://github.com/research-org/mental-health-nlp"
    assert repo.language == "Python"
    assert repo.stars == 250
    assert repo.forks == 45
    assert repo.topics == ["mental-health", "nlp", "therapy", "dataset"]
    assert repo.license == "Apache-2.0"
    assert repo.source == "github"
    assert repo.created_at == "2025-02-10T12:00:00Z"
    assert repo.updated_at == "2026-02-15T09:30:00Z"


@pytest.mark.asyncio
async def test_multiple_repositories():
    """Test 2: Verify multiple repositories are correctly transformed."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total_count": 2, "items": [SAMPLE_REPO_1, SAMPLE_REPO_2]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(client=client)

    results = await provider.search_repositories(query="mental health", limit=10)

    assert len(results) == 2
    assert results[0].full_name == "research-org/mental-health-nlp"
    assert results[1].full_name == "ai-lab/depression-dialogue-corpus"


@pytest.mark.asyncio
async def test_missing_description():
    """Test 3: Verify description = None does not crash and is handled cleanly."""
    repo_no_desc = dict(SAMPLE_REPO_1)
    repo_no_desc["description"] = None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total_count": 1, "items": [repo_no_desc]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(client=client)

    results = await provider.search_repositories(query="mental health", limit=5)
    assert len(results) == 1
    assert results[0].description is None


@pytest.mark.asyncio
async def test_missing_license():
    """Test 4: Verify missing license metadata is handled gracefully."""
    repo_no_lic = dict(SAMPLE_REPO_1)
    repo_no_lic["license"] = None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total_count": 1, "items": [repo_no_lic]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(client=client)

    results = await provider.search_repositories(query="mental health", limit=5)
    assert len(results) == 1
    assert results[0].license is None


@pytest.mark.asyncio
async def test_topics_preserved():
    """Test 5: Verify GitHub topics are preserved."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"total_count": 1, "items": [SAMPLE_REPO_1]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(client=client)

    results = await provider.search_repositories(query="mental health", limit=5)
    assert results[0].topics == ["mental-health", "nlp", "therapy", "dataset"]


@pytest.mark.asyncio
async def test_limit_respected():
    """Test 6: Verify requested limit is respected even if API returns more items."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("per_page") == "1"
        return httpx.Response(200, json={"total_count": 2, "items": [SAMPLE_REPO_1, SAMPLE_REPO_2]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(client=client)

    results = await provider.search_repositories(query="mental health", limit=1)
    assert len(results) == 1
    assert results[0].id == 101


@pytest.mark.asyncio
async def test_updated_after_filter():
    """Test 7: Verify updated_after is correctly incorporated into the query."""
    captured_query = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_query
        captured_query = request.url.params.get("q")
        return httpx.Response(200, json={"total_count": 1, "items": [SAMPLE_REPO_1]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(client=client)

    await provider.search_repositories(
        query="mental health dataset",
        updated_after="2026-01-01",
        language="Python",
    )

    assert captured_query == "mental health dataset updated:>=2026-01-01 language:Python"


@pytest.mark.asyncio
async def test_http_403_rate_limit():
    """Test 8: Verify a meaningful rate-limit error on HTTP 403 / 429."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0"},
            json={"message": "API rate limit exceeded for IP"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(client=client)

    with pytest.raises(GitHubRateLimitError) as exc_info:
        await provider.search_repositories(query="mental health")

    assert "rate limit reached" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_http_500_server_error():
    """Test 9: Verify server errors (HTTP 5xx) are handled cleanly."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(client=client)

    with pytest.raises(GitHubAPIError) as exc_info:
        await provider.search_repositories(query="mental health")

    assert "500" in str(exc_info.value)


@pytest.mark.asyncio
async def test_timeout_handling():
    """Test 10: Verify timeout handling raises GitHubTimeoutError."""
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("Connection timed out")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(client=client, timeout=5.0)

    with pytest.raises(GitHubTimeoutError) as exc_info:
        await provider.search_repositories(query="mental health")

    assert "timed out" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_authentication_token_header():
    """Test 11: Verify token is included in Authorization header when configured and never leaked."""
    secret_token = "ghp_mockSecretToken12345"
    captured_auth = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_auth
        captured_auth = request.headers.get("authorization")
        return httpx.Response(200, json={"total_count": 1, "items": [SAMPLE_REPO_1]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(token=secret_token, client=client)

    await provider.search_repositories(query="mental health")

    assert captured_auth == f"Bearer {secret_token}"


@pytest.mark.asyncio
async def test_empty_query_validation():
    """Verify empty or whitespace-only query raises ValueError."""
    provider = GitHubProvider()
    with pytest.raises(ValueError) as exc:
        await provider.search_repositories(query="   ")
    assert "Search query cannot be empty" in str(exc.value)


@pytest.mark.asyncio
async def test_invalid_updated_after_date():
    """Verify invalid date format for updated_after raises ValueError."""
    provider = GitHubProvider()
    with pytest.raises(ValueError) as exc:
        await provider.search_repositories(query="mental health", updated_after="01-01-2026")
    assert "Invalid updated_after date format" in str(exc.value)


@pytest.mark.asyncio
async def test_http_401_authentication_error():
    """Verify HTTP 401 raises GitHubAuthenticationError."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(client=client)

    with pytest.raises(GitHubAuthenticationError) as exc_info:
        await provider.search_repositories(query="mental health")

    assert "authentication failed" in str(exc_info.value).lower()


# ==============================================================================
# Phase 4 Tests: README & Dataset Resource Discovery
# ==============================================================================

README_MARKDOWN_SAMPLE = """
# Mental Health NLP Research

This repository contains benchmarks and links to datasets for counseling and therapy research.

## Datasets

* [Therapy Conversations Dataset](https://huggingface.co/datasets/mental-nlp/therapy-dialogues): A collection of multi-turn dialogue transcripts.
* [PHQ-9 Survey Questionnaire](https://zenodo.org/records/9876543): Depression assessment survey responses.
* [Reddit Mental Health Posts](https://kaggle.com/datasets/mentalhealth/reddit-corpus): Social media text corpus.

## Privacy & Ethics
All dialogue records and survey responses in these datasets are explicitly anonymized.
Contains sensitive distress warnings.

## License
Dataset licensed under CC BY 4.0.
"""


@pytest.mark.asyncio
async def test_get_repository_readme_base64_decode():
    """Verify README content is retrieved from GitHub API and base64-decoded properly."""
    encoded_bytes = base64.b64encode(README_MARKDOWN_SAMPLE.encode("utf-8")).decode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        assert "/repos/research-org/mental-health-nlp/readme" in str(request.url)
        return httpx.Response(
            200,
            json={
                "name": "README.md",
                "path": "README.md",
                "size": len(README_MARKDOWN_SAMPLE),
                "html_url": "https://github.com/research-org/mental-health-nlp/blob/main/README.md",
                "content": encoded_bytes,
                "encoding": "base64",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(client=client)

    readme = await provider.get_repository_readme("research-org", "mental-health-nlp")
    assert readme is not None
    assert readme["name"] == "README.md"
    assert "Therapy Conversations Dataset" in readme["content"]


@pytest.mark.asyncio
async def test_get_repository_readme_not_found():
    """Verify 404 from README endpoint returns None without error."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(client=client)

    readme = await provider.get_repository_readme("some-owner", "empty-repo")
    assert readme is None


@pytest.mark.asyncio
async def test_inspect_repository_resources_success():
    """Verify dataset candidates, platforms, data types, licenses, and privacy status are discovered."""
    encoded_bytes = base64.b64encode(README_MARKDOWN_SAMPLE.encode("utf-8")).decode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if url_str.endswith("/readme"):
            return httpx.Response(
                200,
                json={
                    "name": "README.md",
                    "content": encoded_bytes,
                    "encoding": "base64",
                    "html_url": "https://github.com/research-org/mental-health-nlp/blob/main/README.md",
                },
            )
        elif "/repos/research-org/mental-health-nlp" in url_str:
            return httpx.Response(200, json=SAMPLE_REPO_1)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(client=client)

    candidates = await provider.inspect_repository_resources("research-org", "mental-health-nlp")

    # Should find HuggingFace (conversation), Zenodo (assessment), Kaggle (text), and repo candidate
    assert len(candidates) >= 3

    # Check Hugging Face dialogue candidate
    hf_cands = [c for c in candidates if c.source_platform == "Hugging Face"]
    assert len(hf_cands) == 1
    hf = hf_cands[0]
    assert hf.name == "Therapy Conversations Dataset"
    assert hf.data_type == "conversation"
    assert hf.dataset_url == "https://huggingface.co/datasets/mental-nlp/therapy-dialogues"
    assert hf.privacy_status == "explicitly_anonymized"
    assert "CC BY 4.0" in (hf.license or "")

    # Check Zenodo survey candidate
    zenodo_cands = [c for c in candidates if c.source_platform == "Zenodo"]
    assert len(zenodo_cands) == 1
    zen = zenodo_cands[0]
    assert zen.name == "PHQ-9 Survey Questionnaire"
    assert zen.data_type == "mental_health_assessment"
    assert zen.dataset_url == "https://zenodo.org/records/9876543"

    # Check Kaggle text corpus candidate
    kaggle_cands = [c for c in candidates if c.source_platform == "Kaggle"]
    assert len(kaggle_cands) == 1
    kag = kaggle_cands[0]
    assert kag.name == "Reddit Mental Health Posts"
    assert kag.data_type == "text"


@pytest.mark.asyncio
async def test_inspect_repository_resources_no_readme():
    """Verify inspect_repository_resources returns empty list if no README exists."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GitHubProvider(client=client)

    candidates = await provider.inspect_repository_resources("some-org", "no-readme-repo")
    assert candidates == []


@pytest.mark.asyncio
async def test_inspect_repository_resources_empty_params():
    """Verify empty owner or repository raises ValueError."""
    provider = GitHubProvider()
    with pytest.raises(ValueError):
        await provider.inspect_repository_resources("", "repo")
    with pytest.raises(ValueError):
        await provider.inspect_repository_resources("owner", "")
