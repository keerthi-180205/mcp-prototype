"""Unit and integration tests for MMTF MCP Server (Phases 1, 3, 4 & 5)."""

import json
from unittest.mock import AsyncMock, patch
import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from server import server
from server.models import DatasetCandidate, DatasetMetadata, RepositoryCandidate
from server.providers.github import (
    GitHubAuthenticationError,
    GitHubConnectionError,
    GitHubRateLimitError,
    GitHubTimeoutError,
)
from server.providers.huggingface import HuggingFaceNotFoundError
from server.server import (
    analyze_dataset_relevance,
    generate_dataset_report,
    health_check,
    inspect_repository_resources,
    mcp,
    readiness_check,
    resolve_dataset_metadata,

    search_mental_health_repositories,
    summarize_dataset,
    validate_dataset,
    search_instagram_reels,
    get_instagram_comments,
    research_instagram_topic,
)


SAMPLE_CANDIDATE = RepositoryCandidate(
    id=101,
    name="mental-health-nlp",
    full_name="research-org/mental-health-nlp",
    owner="research-org",
    owner_type="Organization",
    description="A curated NLP dataset for psychological distress and therapy conversations",
    html_url="https://github.com/research-org/mental-health-nlp",
    api_url="https://api.github.com/repos/research-org/mental-health-nlp",
    language="Python",
    topics=["mental-health", "nlp"],
    stars=250,
    forks=45,
    open_issues=3,
    created_at="2025-02-10T12:00:00Z",
    updated_at="2026-02-15T09:30:00Z",
    pushed_at="2026-02-15T09:30:00Z",
    license="Apache-2.0",
    default_branch="main",
    archived=False,
    fork=False,
    source="github",
)

SAMPLE_DATASET = DatasetCandidate(
    name="Therapy Conversations Dataset",
    description="Referenced dataset link on Hugging Face",
    data_type="conversation",
    source_repository="research-org/mental-health-nlp",
    source_repository_url="https://github.com/research-org/mental-health-nlp",
    dataset_url="https://huggingface.co/datasets/mental-nlp/therapy-dialogues",
    source_platform="Hugging Face",
    license="CC-BY-4.0",
    access_method="external_link",
    discovered_from="README",
    privacy_status="explicitly_anonymized",
    confidence="high",
    notes="Extracted from README link",
)

SAMPLE_METADATA = DatasetMetadata(
    name="mental-nlp/therapy-dialogues",
    description="Multi-turn therapy dialogue transcripts.",
    source_platform="Hugging Face",
    source_url="https://huggingface.co/datasets/mental-nlp/therapy-dialogues",
    identifier="mental-nlp/therapy-dialogues",
    data_type="conversation",
    license="apache-2.0",
    language="en",
    download_available=True,
    size_bytes=1500000,
    tags=["mental-health", "therapy"],
    explicitly_anonymized=True,
)


def test_server_instance_and_tool_exists():
    """Verify the server module imports successfully and exposes all registered tools."""
    assert mcp is not None
    assert mcp.name == "mmtf-client-discovery"
    assert callable(health_check)
    assert callable(readiness_check)
    assert callable(search_mental_health_repositories)

    assert callable(inspect_repository_resources)
    assert callable(resolve_dataset_metadata)
    assert callable(validate_dataset)
    assert callable(summarize_dataset)
    assert callable(analyze_dataset_relevance)
    assert callable(generate_dataset_report)
    assert callable(search_instagram_reels)
    assert callable(get_instagram_comments)
    assert callable(research_instagram_topic)


def test_health_check_response():
    """Verify that health_check returns the expected structured JSON-compatible response."""
    response = health_check()
    assert isinstance(response, dict)
    assert response.get("status") == "ok"
    assert response.get("service") == "mmtf-client-discovery"
    assert response.get("message") == "MCP server is running successfully"


@pytest.mark.asyncio
async def test_tools_registered_on_server():
    """Verify that all 4 MCP tools are registered."""
    tools = await mcp.list_tools()
    tool_names = [tool.name for tool in tools]
    assert "health_check" in tool_names
    assert "search_mental_health_repositories" in tool_names
    assert "inspect_repository_resources" in tool_names
    assert "resolve_dataset_metadata" in tool_names
    assert "validate_dataset" in tool_names
    assert "summarize_dataset" in tool_names
    assert "analyze_dataset_relevance" in tool_names
    assert "generate_dataset_report" in tool_names
    assert "search_instagram_reels" in tool_names
    assert "get_instagram_comments" in tool_names
    assert "research_instagram_topic" in tool_names


@pytest.mark.asyncio
async def test_search_mental_health_repositories_success():
    """Verify search tool invokes GitHub provider with correct arguments and serializes results."""
    mock_search = AsyncMock(return_value=[SAMPLE_CANDIDATE])

    with patch.object(server.github_provider, "search_repositories", mock_search):
        result = await search_mental_health_repositories(
            query="mental health dataset",
            limit=10,
            updated_after="2026-01-01",
            language="Python",
        )

        mock_search.assert_awaited_once_with(
            query="mental health dataset",
            limit=10,
            updated_after="2026-01-01",
            language="Python",
        )

        assert result["query"] == "mental health dataset"
        assert result["count"] == 1
        assert len(result["repositories"]) == 1
        repo = result["repositories"][0]
        assert repo["name"] == "mental-health-nlp"
        assert repo["full_name"] == "research-org/mental-health-nlp"
        assert repo["stars"] == 250
        assert repo["source"] == "github"


@pytest.mark.asyncio
async def test_search_mental_health_repositories_empty():
    """Verify search tool handles empty results cleanly without crashing."""
    mock_search = AsyncMock(return_value=[])

    with patch.object(server.github_provider, "search_repositories", mock_search):
        result = await search_mental_health_repositories(query="nonexistent term 12345")

        assert result["query"] == "nonexistent term 12345"
        assert result["count"] == 0
        assert result["repositories"] == []


@pytest.mark.asyncio
async def test_search_mental_health_repositories_rate_limit_error():
    """Verify GitHub rate limit errors are translated to structured MCP error responses."""
    mock_search = AsyncMock(side_effect=GitHubRateLimitError("Rate limit exceeded"))

    with patch.object(server.github_provider, "search_repositories", mock_search):
        result = await search_mental_health_repositories(query="mental health")
        assert result == {
            "error": "github_rate_limit",
            "message": "GitHub API rate limit reached",
        }


@pytest.mark.asyncio
async def test_search_mental_health_repositories_auth_error():
    """Verify authentication errors are translated to structured MCP error responses."""
    mock_search = AsyncMock(side_effect=GitHubAuthenticationError("Bad credentials"))

    with patch.object(server.github_provider, "search_repositories", mock_search):
        result = await search_mental_health_repositories(query="mental health")
        assert result == {
            "error": "github_auth_error",
            "message": "GitHub API authentication failed",
        }


@pytest.mark.asyncio
async def test_search_mental_health_repositories_timeout_error():
    """Verify timeout errors are translated to structured MCP error responses."""
    mock_search = AsyncMock(side_effect=GitHubTimeoutError("Request timed out"))

    with patch.object(server.github_provider, "search_repositories", mock_search):
        result = await search_mental_health_repositories(query="mental health")
        assert result == {
            "error": "github_timeout",
            "message": "GitHub API request timed out",
        }


@pytest.mark.asyncio
async def test_search_mental_health_repositories_connection_error():
    """Verify connection errors are translated to structured MCP error responses."""
    mock_search = AsyncMock(side_effect=GitHubConnectionError("Network unreachable"))

    with patch.object(server.github_provider, "search_repositories", mock_search):
        result = await search_mental_health_repositories(query="mental health")
        assert result == {
            "error": "github_connection_error",
            "message": "Failed to connect to GitHub API",
        }


@pytest.mark.asyncio
async def test_search_mental_health_repositories_validation_error():
    """Verify validation errors return invalid_parameter error."""
    mock_search = AsyncMock(side_effect=ValueError("Search query cannot be empty."))

    with patch.object(server.github_provider, "search_repositories", mock_search):
        result = await search_mental_health_repositories(query="  ")
        assert result == {
            "error": "invalid_parameter",
            "message": "Search query cannot be empty.",
        }


@pytest.mark.asyncio
async def test_inspect_repository_resources_tool_success():
    """Verify inspect_repository_resources tool calls provider and formats candidate results."""
    mock_inspect = AsyncMock(return_value=[SAMPLE_DATASET])

    with patch.object(server.github_provider, "inspect_repository_resources", mock_inspect):
        result = await inspect_repository_resources(owner="research-org", repository="mental-health-nlp")

        mock_inspect.assert_awaited_once_with(owner="research-org", repository="mental-health-nlp")
        assert result["repository"] == "research-org/mental-health-nlp"
        assert result["dataset_candidates_count"] == 1
        assert len(result["dataset_candidates"]) == 1

        cand = result["dataset_candidates"][0]
        assert cand["name"] == "Therapy Conversations Dataset"
        assert cand["data_type"] == "conversation"
        assert cand["source_platform"] == "Hugging Face"
        assert cand["privacy_status"] == "explicitly_anonymized"
        assert cand["discovered_from"] == "README"


@pytest.mark.asyncio
async def test_inspect_repository_resources_tool_empty():
    """Verify inspect tool returns zero candidates gracefully when none are discovered."""
    mock_inspect = AsyncMock(return_value=[])

    with patch.object(server.github_provider, "inspect_repository_resources", mock_inspect):
        result = await inspect_repository_resources(owner="generic-org", repository="app-only-repo")

        assert result["repository"] == "generic-org/app-only-repo"
        assert result["dataset_candidates_count"] == 0
        assert result["dataset_candidates"] == []


@pytest.mark.asyncio
async def test_inspect_repository_resources_tool_rate_limit():
    """Verify rate limit errors in inspect tool are converted to structured responses."""
    mock_inspect = AsyncMock(side_effect=GitHubRateLimitError("Rate limit reached"))

    with patch.object(server.github_provider, "inspect_repository_resources", mock_inspect):
        result = await inspect_repository_resources(owner="org", repository="repo")
        assert result == {
            "error": "github_rate_limit",
            "message": "GitHub API rate limit reached",
        }


@pytest.mark.asyncio
async def test_inspect_repository_resources_tool_validation_error():
    """Verify validation errors (empty owner/repo) return invalid_parameter."""
    mock_inspect = AsyncMock(side_effect=ValueError("Owner and repository must be specified."))

    with patch.object(server.github_provider, "inspect_repository_resources", mock_inspect):
        result = await inspect_repository_resources(owner="", repository="")
        assert result == {
            "error": "invalid_parameter",
            "message": "Owner and repository must be specified.",
        }


# ==============================================================================
# Phase 5 Tests: resolve_dataset_metadata Tool
# ==============================================================================

@pytest.mark.asyncio
async def test_resolve_dataset_metadata_tool_success():
    """Verify resolve_dataset_metadata tool identifies platform and returns normalized metadata."""
    mock_get = AsyncMock(return_value=SAMPLE_METADATA)

    with patch.object(server.huggingface_provider, "get_dataset_metadata", mock_get):
        result = await resolve_dataset_metadata(
            "https://huggingface.co/datasets/mental-nlp/therapy-dialogues"
        )
        assert result["status"] == "success"
        assert result["provider"] == "huggingface"
        assert result["dataset"]["name"] == "mental-nlp/therapy-dialogues"
        assert result["dataset"]["source_platform"] == "Hugging Face"
        assert result["dataset"]["data_type"] == "conversation"
        mock_get.assert_awaited_once_with("mental-nlp/therapy-dialogues")


@pytest.mark.asyncio
async def test_resolve_dataset_metadata_tool_unsupported_url():
    """Verify unsupported URLs return unsupported_provider status."""
    result = await resolve_dataset_metadata("https://randomwebsite.org/files/dataset.zip")
    assert result["status"] == "unsupported_provider"
    assert "not correspond to a supported platform" in result["message"]


@pytest.mark.asyncio
async def test_resolve_dataset_metadata_tool_empty_url():
    """Verify empty URL returns invalid_parameter error."""
    result = await resolve_dataset_metadata("   ")
    assert result["status"] == "error"
    assert result["error"] == "invalid_parameter"


@pytest.mark.asyncio
async def test_resolve_dataset_metadata_tool_not_found():
    """Verify 404 from connector returns structured not_found error."""
    mock_get = AsyncMock(side_effect=HuggingFaceNotFoundError("Dataset does not exist"))

    with patch.object(server.huggingface_provider, "get_dataset_metadata", mock_get):
        result = await resolve_dataset_metadata("https://huggingface.co/datasets/missing/dataset")
        assert result["status"] == "error"
        assert result["error"] == "not_found"
        assert "Dataset does not exist" in result["message"]


@pytest.mark.asyncio
async def test_validate_dataset_tool_success():
    """Verify validate_dataset calls provider and executes deterministic validation."""
    mock_get = AsyncMock(return_value=SAMPLE_METADATA)

    with patch.object(server.huggingface_provider, "get_dataset_metadata", mock_get):
        result = await validate_dataset("https://huggingface.co/datasets/mental-nlp/therapy-dialogues")
        assert result["status"] == "success"
        assert result["dataset"] == "mental-nlp/therapy-dialogues"
        assert result["provider"] == "huggingface"

        val = result["validation"]
        assert val["dataset_name"] == "mental-nlp/therapy-dialogues"
        assert val["license_status"] == "documented"
        assert val["license_name"] == "apache-2.0"
        assert val["explicitly_anonymized"] is True
        assert val["provenance_status"] == "documented"
        assert len(val["evidence"]) >= 1


@pytest.mark.asyncio
async def test_validate_dataset_tool_unsupported_url():
    """Verify unsupported URL returns unsupported_provider status."""
    result = await validate_dataset("https://unknown-domain.com/datasets/123")
    assert result["status"] == "unsupported_provider"
    assert "not correspond to a supported platform" in result["message"]


@pytest.mark.asyncio
async def test_validate_dataset_tool_empty_url():
    """Verify empty URL returns invalid_parameter error."""
    result = await validate_dataset("")
    assert result["status"] == "error"
    assert result["error"] == "invalid_parameter"


@pytest.mark.asyncio
async def test_validate_dataset_tool_not_found():
    """Verify 404 from connector returns structured not_found error."""
    mock_get = AsyncMock(side_effect=HuggingFaceNotFoundError("Dataset does not exist"))

    with patch.object(server.huggingface_provider, "get_dataset_metadata", mock_get):
        result = await validate_dataset("https://huggingface.co/datasets/missing/dataset")
        assert result["status"] == "error"
        assert result["error"] == "not_found"


@pytest.mark.asyncio
async def test_mcp_client_stdio_session_all_tools():
    """Verify that an MCP client can connect via stdio and list all 5 tools."""
    server_params = StdioServerParameters(
        command="python3",
        args=["-m", "server.server"],
        env=None,
    )
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tool_list = await session.list_tools()
            tool_names = [t.name for t in tool_list.tools]
            assert "health_check" in tool_names
            assert "search_mental_health_repositories" in tool_names
            assert "inspect_repository_resources" in tool_names
            assert "resolve_dataset_metadata" in tool_names
            assert "validate_dataset" in tool_names
            assert "summarize_dataset" in tool_names
            assert "analyze_dataset_relevance" in tool_names
            assert "generate_dataset_report" in tool_names
            assert "search_instagram_reels" in tool_names
            assert "get_instagram_comments" in tool_names
            assert "research_instagram_topic" in tool_names

            # Test health_check call
            result = await session.call_tool("health_check", {})
            assert not result.is_error
            assert len(result.content) > 0

            payload = json.loads(result.content[0].text)
            assert payload["status"] == "ok"
            assert payload["service"] == "mmtf-client-discovery"
            assert payload["message"] == "MCP server is running successfully"

