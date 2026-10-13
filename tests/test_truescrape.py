"""Tests for TrueScrape client and Instagram provider integration."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from server.config import Settings
from server.providers.truescrape.client import (
    TrueScrapeClient,
    TrueScrapeError,
    TrueScrapeAuthenticationError,
    TrueScrapeRateLimitError,
    TrueScrapeTimeoutError,
    TrueScrapeConnectionError,
)
from server.providers.truescrape.instagram import TrueScrapeInstagramProvider
from server.providers.social.truescrape_instagram import TrueScrapeInstagramSocialProvider
from server.providers.social.registry import SocialProviderRegistry


@pytest.mark.asyncio
async def test_truescrape_client_not_configured():
    settings = Settings(truescrape_api_key=None)
    client = TrueScrapeClient(api_key=None, settings=settings)
    assert not client.is_configured
    with pytest.raises(TrueScrapeAuthenticationError):
        await client.get("/v1/instagram/popular-search")


@pytest.mark.asyncio
async def test_truescrape_client_auth_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"

    mock_http = AsyncMock()
    mock_http.is_closed = False
    mock_http.get.return_value = mock_resp

    client = TrueScrapeClient(api_key="test_key", client=mock_http)
    with pytest.raises(TrueScrapeAuthenticationError):
        await client.get("/v1/instagram/popular-search")


@pytest.mark.asyncio
async def test_truescrape_client_rate_limit():
    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = "Rate limit reached"

    mock_http = AsyncMock()
    mock_http.is_closed = False
    mock_http.get.return_value = mock_resp

    client = TrueScrapeClient(api_key="test_key", client=mock_http)
    with pytest.raises(TrueScrapeRateLimitError):
        await client.get("/v1/instagram/popular-search")


@pytest.mark.asyncio
async def test_truescrape_client_timeout():
    mock_http = AsyncMock()
    mock_http.is_closed = False
    mock_http.get.side_effect = httpx.TimeoutException("Timeout")

    client = TrueScrapeClient(api_key="test_key", client=mock_http)
    with pytest.raises(TrueScrapeTimeoutError):
        await client.get("/v1/instagram/popular-search")


@pytest.mark.asyncio
async def test_truescrape_instagram_provider_search():
    client = MagicMock()
    client.is_configured = True
    client.get = AsyncMock(return_value={
        "success": True,
        "data": {
            "items": [
                {
                    "id": "reel123",
                    "type": "reel",
                    "url": "https://www.instagram.com/reel/reel123/",
                    "text": "Amazing AI reel #ai #agent",
                    "authorId": "user123",
                    "authorHandle": "techguru",
                    "authorName": "Tech Guru",
                    "likeCount": 1500,
                    "commentCount": 42,
                    "viewCount": 20000,
                    "publishedAt": "2026-10-01T12:00:00Z"
                }
            ]
        }
    })

    provider = TrueScrapeInstagramProvider(client=client)
    posts = await provider.search_posts_or_reels("ai", max_results=5)
    assert len(posts) == 1
    post = posts[0]
    assert post["id"] == "reel123"
    assert post["ownerUsername"] == "techguru"
    assert post["likesCount"] == 1500
    assert post["commentsCount"] == 42


@pytest.mark.asyncio
async def test_truescrape_instagram_provider_comments():
    client = MagicMock()
    client.is_configured = True
    client.get = AsyncMock(return_value={
        "success": True,
        "data": {
            "items": [
                {
                    "id": "comm1",
                    "text": "Great tutorial!",
                    "authorId": "u456",
                    "authorHandle": "learner",
                    "likeCount": 10,
                    "replyCount": 1,
                    "createdAt": "2026-10-02T10:00:00Z"
                }
            ]
        }
    })

    provider = TrueScrapeInstagramProvider(client=client)
    comments = await provider.get_post_comments("https://www.instagram.com/reel/reel123/", max_comments=5)
    assert len(comments) == 1
    c = comments[0]
    assert c["id"] == "comm1"
    assert c["text"] == "Great tutorial!"
    assert c["user"]["username"] == "learner"
    assert c["likesCount"] == 10


@pytest.mark.asyncio
async def test_truescrape_social_provider_registry():
    settings = Settings(truescrape_api_key="test_key", apify_api_token=None)
    social_provider = TrueScrapeInstagramSocialProvider()
    social_provider.settings = settings
    assert social_provider.platform_name == "instagram"
    assert social_provider.provider_name == "truescrape"
    assert social_provider.is_available() is True

    # Test registry prioritizes TrueScrape when available
    registry = SocialProviderRegistry()
    active_provider = registry.get_provider("instagram")
    assert active_provider is not None
    assert active_provider.platform_name == "instagram"
    # When TRUESCRAPE_API_KEY is in environment, TrueScrape is the active primary provider
    assert active_provider.provider_name == "truescrape"

    # Verify YouTube still uses Agent Reach (yt-dlp)
    yt_provider = registry.get_provider("youtube")
    assert yt_provider is not None
    assert yt_provider.platform_name == "youtube"
    assert yt_provider.provider_name == "agent-reach"
