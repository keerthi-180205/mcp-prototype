"""Verification tests for Instagram username and comment fetching improvements."""

import pytest
from unittest.mock import AsyncMock

from server.collection.collectors.instagram import InstagramCollector, _extract_shortcode, _post_key
from server.collection.collectors.serp import SerpDiscoveryBackend, SerpResult
from server.collection.collectors.truescrape import unified_comment_row
from server.collection.models import PostCandidate
from server.services.instagram import (
    InstagramService,
    normalize_comment_data,
    normalize_post_data,
    validate_instagram_url,
)


def test_validate_instagram_url_with_username_path():
    """Verify URLs containing usernames in path pass validation."""
    url1 = "https://www.instagram.com/justbrandi_/reel/DdpXHDRTwsE/"
    url2 = "https://www.instagram.com/yesha_sagar/p/DeRfW05I2aJ/"
    assert validate_instagram_url(url1) == url1
    assert validate_instagram_url(url2) == url2


def test_normalize_post_data_extracts_author_from_url():
    """Verify that if author_username is not in the JSON metadata, it is extracted from the URL."""
    raw = {
        "url": "https://www.instagram.com/justbrandi_/reel/DdpXHDRTwsE/",
        "caption": "Morning walk",
    }
    post = normalize_post_data(raw)
    assert post.author is not None
    assert post.author.username == "justbrandi_"


def test_serp_extracts_author_username_from_multiple_sources():
    """Verify SerpDiscoveryBackend extracts author username from URL, source, title, or snippet."""
    backend = SerpDiscoveryBackend("instagram")

    # 1. From URL
    r1 = SerpResult(rank=1, url="https://www.instagram.com/cricketer_pro/reel/ABC123xyz/", title="Great match")
    c1 = backend._candidate(r1)
    assert c1 is not None and c1.author_username == "cricketer_pro"

    # 2. From title with (@handle)
    r2 = SerpResult(rank=2, url="https://www.instagram.com/reel/ABC123xyz/", title="Virat Kohli (@virat.kohli) on Instagram")
    c2 = backend._candidate(r2)
    assert c2 is not None and c2.author_username == "virat.kohli"

    # 3. From snippet with likes/comments
    r3 = SerpResult(rank=3, url="https://www.instagram.com/p/ABC123xyz/", snippet="4.5K likes, 32 comments - my_cool_handle on October 10: 'Hello world'")
    c3 = backend._candidate(r3)
    assert c3 is not None and c3.author_username == "my_cool_handle"

    # 4. From source
    r4 = SerpResult(rank=4, url="https://www.instagram.com/p/ABC123xyz/", source="Instagram - fitness_coach")
    c4 = backend._candidate(r4)
    assert c4 is not None and c4.author_username == "fitness_coach"


@pytest.mark.asyncio
async def test_apify_shortcode_matching_p_vs_reel():
    """Verify comments are mapped correctly when post URL has /p/ but Apify returns /reel/."""
    class FakeApifyProv:
        async def get_comments_batch(self, post_urls, comments_per_post, max_items=None, max_total_charge_usd=None):
            return [
                {
                    "postUrl": "https://www.instagram.com/reel/DeRfW05I2aJ/",
                    "id": "c1",
                    "text": "Great post!",
                    "ownerUsername": "fan_user",
                    "owner": {"id": "12345"},
                    "likesCount": 5,
                }
            ]

    collector = InstagramCollector(provider=FakeApifyProv())
    post = PostCandidate(
        platform="instagram",
        post_id="DeRfW05I2aJ",
        url="https://www.instagram.com/p/DeRfW05I2aJ/",
    )
    result = await collector.fetch_comments([post], {post.url: 10})
    assert post.url in result
    assert len(result[post.url]) == 1
    assert result[post.url][0].username == "fan_user"
    assert result[post.url][0].comment == "Great post!"


def test_unified_comment_row_username_fallbacks():
    """Verify unified_comment_row populates username with fallback to user_id or anonymous."""
    # Username from authorHandle
    r1 = unified_comment_row({"text": "hello", "authorHandle": "user1"}, "instagram", "https://ig.com/p/1", "ts")
    assert r1 is not None and r1.username == "user1"

    # Username missing, fallback to authorId
    r2 = unified_comment_row({"text": "hello", "authorId": "99999"}, "instagram", "https://ig.com/p/1", "ts")
    assert r2 is not None and r2.username == "user_99999"


@pytest.mark.asyncio
async def test_instagram_service_fallback_to_apify_on_empty_primary():
    """Verify InstagramService.get_post_comments falls back to Apify when primary returns empty."""
    mock_primary = AsyncMock()
    mock_primary.get_post_comments = AsyncMock(return_value=[])  # Primary returns no comments (or fails)
    mock_primary.is_available = lambda: True

    mock_apify = AsyncMock()
    mock_apify.get_post_comments = AsyncMock(return_value=[
        {"id": "ap1", "text": "Comment from Apify", "ownerUsername": "apify_fan"}
    ])
    mock_apify.is_available = lambda: True

    service = InstagramService(provider=mock_primary)
    service.apify_provider = mock_apify

    res = await service.get_post_comments("https://www.instagram.com/p/ABC123xyz/", max_comments=5)
    assert len(res.comments) == 1
    assert res.comments[0].text == "Comment from Apify"
    assert res.comments[0].user.username == "apify_fan"
