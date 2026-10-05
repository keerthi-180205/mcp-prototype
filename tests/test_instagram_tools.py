"""Integration and unit tests for Instagram MCP tools."""

from unittest.mock import AsyncMock, patch
import pytest

from server import server
from server.models import (
    InstagramAuthor,
    InstagramComment,
    InstagramCommentUser,
    InstagramCommentsResult,
    InstagramPost,
    InstagramTopicPostContent,
    InstagramTopicPostResult,
    InstagramTopicResearchResult,
)
from server.providers.apify import (
    ApifyActorError,
    ApifyAuthenticationError,
    ApifyConnectionError,
    ApifyRateLimitError,
    ApifyTimeoutError,
)
from server.server import (
    get_instagram_comments,
    readiness_check,
    research_instagram_topic,
    search_instagram_reels,
)
from server.services.instagram import InstagramValidationError


@pytest.mark.asyncio
async def test_readiness_check_includes_apify():
    """Verify that readiness_check tool includes Apify provider configuration status."""
    res = readiness_check()
    assert "providers" in res
    assert "apify" in res["providers"]
    assert "status" in res["providers"]["apify"]
    assert "authentication" in res["providers"]["apify"]


@pytest.mark.asyncio
async def test_search_instagram_reels_tool_success():
    """Verify search_instagram_reels MCP tool returns formatted results."""
    mock_post = InstagramPost(
        platform="instagram",
        content_type="reel",
        content_id="reel_100",
        url="https://www.instagram.com/reel/C_demo123/",
        caption="Daily mental health habits",
        author=InstagramAuthor(
            id="auth_1",
            username="wellness_daily",
            display_name="Wellness Daily",
        ),
        created_at="2026-03-01T08:00:00Z",
        like_count=500,
        comment_count=20,
        view_count=8000,
    )

    with patch.object(server.instagram_service, "search_posts_or_reels", AsyncMock(return_value=[mock_post])):
        result = await search_instagram_reels(query="mental health", max_results=5)

        assert result["platform"] == "instagram"
        assert result["query"] == "mental health"
        assert result["count"] == 1
        assert len(result["results"]) == 1

        post_data = result["results"][0]
        assert post_data["platform"] == "instagram"
        assert post_data["content_type"] == "reel"
        assert post_data["content_id"] == "reel_100"
        assert post_data["url"] == "https://www.instagram.com/reel/C_demo123/"
        assert post_data["caption"] == "Daily mental health habits"
        assert post_data["author"]["username"] == "wellness_daily"
        assert post_data["like_count"] == 500
        assert post_data["view_count"] == 8000


@pytest.mark.asyncio
async def test_search_instagram_reels_tool_auth_error():
    """Verify Apify authentication failure returns clean error without secrets."""
    with patch.object(
        server.instagram_service,
        "search_posts_or_reels",
        AsyncMock(side_effect=ApifyAuthenticationError("Invalid API token")),
    ):
        result = await search_instagram_reels(query="mindfulness")
        assert result["error"] == "apify_auth_error"
        assert "Invalid API token" in result["message"]


@pytest.mark.asyncio
async def test_search_instagram_reels_tool_rate_limit():
    """Verify Apify rate limit failure maps to apify_rate_limit error."""
    with patch.object(
        server.instagram_service,
        "search_posts_or_reels",
        AsyncMock(side_effect=ApifyRateLimitError("Rate limit")),
    ):
        result = await search_instagram_reels(query="mindfulness")
        assert result["error"] == "apify_rate_limit"


@pytest.mark.asyncio
async def test_search_instagram_reels_tool_timeout():
    """Verify Apify timeout maps to apify_timeout error."""
    with patch.object(
        server.instagram_service,
        "search_posts_or_reels",
        AsyncMock(side_effect=ApifyTimeoutError("Timed out")),
    ):
        result = await search_instagram_reels(query="mindfulness")
        assert result["error"] == "apify_timeout"


@pytest.mark.asyncio
async def test_search_instagram_reels_tool_invalid_param():
    """Verify invalid parameters return invalid_parameter error."""
    result = await search_instagram_reels(query="", max_results=5)
    assert result["error"] == "invalid_parameter"

    result2 = await search_instagram_reels(query="test", max_results=0)
    assert result2["error"] == "invalid_parameter"


@pytest.mark.asyncio
async def test_get_instagram_comments_tool_success():
    """Verify get_instagram_comments MCP tool returns formatted comments structure."""
    mock_comments = InstagramCommentsResult(
        platform="instagram",
        content_url="https://www.instagram.com/reel/C_demo123/",
        comments=[
            InstagramComment(
                comment_id="comm_99",
                user=InstagramCommentUser(
                    id="u_99",
                    username="user_zen",
                    display_name="Zen Practitioner",
                    is_verified=False,
                    is_private=False,
                    profile_picture_url="https://cdn.instagram.com/pic99.jpg",
                ),
                text="Loved this exercise!",
                created_at="2026-03-01T09:00:00Z",
                like_count=5,
                reply_count=1,
            )
        ],
    )

    with patch.object(server.instagram_service, "get_post_comments", AsyncMock(return_value=mock_comments)):
        result = await get_instagram_comments(
            post_url="https://www.instagram.com/reel/C_demo123/",
            max_comments=10,
        )

        assert result["platform"] == "instagram"
        assert result["content_url"] == "https://www.instagram.com/reel/C_demo123/"
        assert len(result["comments"]) == 1

        c = result["comments"][0]
        assert c["comment_id"] == "comm_99"
        assert c["text"] == "Loved this exercise!"
        assert c["like_count"] == 5
        assert c["user"]["username"] == "user_zen"
        assert c["user"]["display_name"] == "Zen Practitioner"
        assert c["user"]["is_verified"] is False
        assert c["user"]["is_private"] is False


@pytest.mark.asyncio
async def test_get_instagram_comments_tool_invalid_url():
    """Verify invalid URL returns invalid_parameter error."""
    result = await get_instagram_comments(post_url="https://not-instagram.com/p/123")
    assert result["error"] == "invalid_parameter"
    assert "Invalid Instagram" in result["message"]


@pytest.mark.asyncio
async def test_research_instagram_topic_tool_success():
    """Verify research_instagram_topic MCP tool returns combined topic results."""
    mock_topic_res = InstagramTopicResearchResult(
        query="mental health",
        platform="instagram",
        results=[
            InstagramTopicPostResult(
                content=InstagramTopicPostContent(
                    url="https://www.instagram.com/reel/C_demo123/",
                    type="reel",
                    caption="Self-care reel caption",
                    author=InstagramAuthor(
                        username="creator_one",
                        display_name="Creator One",
                    ),
                    created_at="2026-03-01T08:00:00Z",
                ),
                comments=[
                    InstagramComment(
                        comment_id="c_1",
                        user=InstagramCommentUser(
                            id="u_1",
                            username="fan_one",
                            display_name="Fan One",
                            is_private=False,
                        ),
                        text="So insightful, thanks!",
                        created_at="2026-03-01T08:30:00Z",
                    )
                ],
            )
        ],
    )

    with patch.object(server.instagram_service, "research_topic", AsyncMock(return_value=mock_topic_res)):
        result = await research_instagram_topic(
            query="mental health",
            max_posts=2,
            max_comments_per_post=5,
        )

        assert result["query"] == "mental health"
        assert result["platform"] == "instagram"
        assert len(result["results"]) == 1

        item = result["results"][0]
        assert item["content"]["url"] == "https://www.instagram.com/reel/C_demo123/"
        assert item["content"]["type"] == "reel"
        assert item["content"]["author"]["username"] == "creator_one"
        assert len(item["comments"]) == 1
        assert item["comments"][0]["user"]["username"] == "fan_one"
        assert item["comments"][0]["text"] == "So insightful, thanks!"
