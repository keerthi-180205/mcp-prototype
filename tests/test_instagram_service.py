"""Unit tests for InstagramService and data normalization."""

from unittest.mock import AsyncMock
import pytest

from server.models import InstagramPost, InstagramComment
from server.services.instagram import (
    InstagramService,
    InstagramValidationError,
    normalize_comment_data,
    normalize_post_data,
    validate_instagram_url,
)


def test_validate_instagram_url_valid():
    """Verify standard public Instagram post and reel URLs pass validation."""
    valid_urls = [
        "https://www.instagram.com/reel/C123abc/",
        "https://www.instagram.com/p/B456xyz/",
        "https://instagram.com/reel/D789mno",
        "https://instagram.com/p/E012pqr",
        "https://www.instagram.com/reels/F345stu/",
    ]
    for url in valid_urls:
        assert validate_instagram_url(url) == url.strip()


def test_validate_instagram_url_invalid():
    """Verify invalid or non-Instagram URLs raise InstagramValidationError."""
    invalid_urls = [
        "",
        "   ",
        "https://twitter.com/user/status/12345",
        "https://www.facebook.com/watch/?v=12345",
        "not_a_valid_url",
        "https://www.instagram.com/some_user/",  # Profile URL, not a post/reel
    ]
    for url in invalid_urls:
        with pytest.raises(InstagramValidationError):
            validate_instagram_url(url)


def test_normalize_post_data_full():
    """Verify post normalization with full fields."""
    raw = {
        "id": "reel_12345",
        "shortCode": "C99abc",
        "url": "https://www.instagram.com/reel/C99abc/",
        "type": "Video",
        "caption": "Practicing mindfulness every morning #mentalhealth",
        "ownerId": "user_789",
        "ownerUsername": "mindful_living",
        "ownerFullName": "Mindful Living",
        "timestamp": "2026-03-01T10:00:00Z",
        "likesCount": 1500,
        "commentsCount": 45,
        "videoViews": 25000,
    }

    post = normalize_post_data(raw)
    assert isinstance(post, InstagramPost)
    assert post.platform == "instagram"
    assert post.content_type == "reel"
    assert post.content_id == "reel_12345"
    assert post.url == "https://www.instagram.com/reel/C99abc/"
    assert post.caption == "Practicing mindfulness every morning #mentalhealth"
    assert post.author is not None
    assert post.author.id == "user_789"
    assert post.author.username == "mindful_living"
    assert post.author.display_name == "Mindful Living"
    assert post.created_at == "2026-03-01T10:00:00Z"
    assert post.like_count == 1500
    assert post.comment_count == 45
    assert post.view_count == 25000


def test_normalize_post_data_missing_fields_safe():
    """Verify post normalization does not crash when fields are missing or null."""
    raw = {
        "shortCode": "XYZ789",
        # No url, no caption, no owner, no counts
    }

    post = normalize_post_data(raw)
    assert isinstance(post, InstagramPost)
    assert post.platform == "instagram"
    assert post.content_type == "reel"
    assert post.content_id == "XYZ789"
    assert post.url == "https://www.instagram.com/reel/XYZ789/"
    assert post.caption is None
    assert post.author is None
    assert post.like_count == 0
    assert post.comment_count == 0
    assert post.view_count == 0


def test_normalize_comment_data_full():
    """Verify comment normalization with full fields."""
    raw = {
        "id": "comment_456",
        "text": "This helped me so much today, thank you!",
        "timestamp": "2026-03-01T11:00:00Z",
        "likesCount": 12,
        "replyCount": 2,
        "user": {
            "id": "u_101",
            "username": "grateful_soul",
            "full_name": "Alex Smith",
            "is_verified": False,
            "is_private": False,
            "profile_pic_url": "https://cdn.instagram.com/avatar101.jpg",
        },
    }

    comment = normalize_comment_data(raw)
    assert isinstance(comment, InstagramComment)
    assert comment.comment_id == "comment_456"
    assert comment.text == "This helped me so much today, thank you!"
    assert comment.like_count == 12
    assert comment.reply_count == 2
    assert comment.created_at == "2026-03-01T11:00:00Z"
    assert comment.user is not None
    assert comment.user.id == "u_101"
    assert comment.user.username == "grateful_soul"
    assert comment.user.display_name == "Alex Smith"
    assert comment.user.is_verified is False
    assert comment.user.is_private is False
    assert comment.user.profile_picture_url == "https://cdn.instagram.com/avatar101.jpg"


def test_normalize_comment_data_missing_fields_safe():
    """Verify comment normalization handles empty/missing fields gracefully."""
    raw = {
        "id": "c_1",
        # user missing
    }

    comment = normalize_comment_data(raw)
    assert isinstance(comment, InstagramComment)
    assert comment.comment_id == "c_1"
    assert comment.user is None
    assert comment.text is None
    assert comment.like_count == 0
    assert comment.reply_count == 0


@pytest.mark.asyncio
async def test_search_posts_or_reels_validation():
    """Verify validation on empty query or invalid max_results."""
    service = InstagramService(provider=AsyncMock())

    with pytest.raises(InstagramValidationError, match="cannot be empty"):
        await service.search_posts_or_reels(query="")

    with pytest.raises(InstagramValidationError, match="positive integer"):
        await service.search_posts_or_reels(query="test", max_results=0)


@pytest.mark.asyncio
async def test_get_post_comments_validation():
    """Verify validation on invalid URL or non-positive max_comments."""
    service = InstagramService(provider=AsyncMock())

    with pytest.raises(InstagramValidationError, match="Invalid Instagram"):
        await service.get_post_comments(post_url="https://youtube.com/watch?v=123")

    with pytest.raises(InstagramValidationError, match="positive integer"):
        await service.get_post_comments(
            post_url="https://www.instagram.com/reel/C123abc/",
            max_comments=-1,
        )


@pytest.mark.asyncio
async def test_research_topic_workflow():
    """Verify end-to-end research flow calls provider and constructs structured response."""
    mock_provider = AsyncMock()
    mock_provider.search_posts_or_reels = AsyncMock(return_value=[
        {
            "id": "reel_1",
            "url": "https://www.instagram.com/reel/C111/",
            "caption": "Post 1 caption",
            "ownerUsername": "author1",
            "ownerFullName": "Author One",
            "timestamp": "2026-03-01T00:00:00Z",
        },
        {
            "id": "reel_2",
            "url": "https://www.instagram.com/reel/C222/",
            "caption": "Post 2 caption",
            "ownerUsername": "author2",
            "ownerFullName": "Author Two",
            "timestamp": "2026-03-02T00:00:00Z",
        },
    ])

    mock_provider.get_post_comments = AsyncMock(return_value=[
        {
            "id": "comm_1",
            "text": "Great perspective",
            "user": {"username": "commenter1", "is_private": False},
            "timestamp": "2026-03-01T01:00:00Z",
        }
    ])

    service = InstagramService(provider=mock_provider)
    result = await service.research_topic(
        query="mental health",
        max_posts=2,
        max_comments_per_post=5,
    )

    assert result.query == "mental health"
    assert result.platform == "instagram"
    assert len(result.results) == 2

    # Check post 1
    post1_res = result.results[0]
    assert post1_res.content.url == "https://www.instagram.com/reel/C111/"
    assert post1_res.content.caption == "Post 1 caption"
    assert post1_res.content.author.username == "author1"
    assert len(post1_res.comments) == 1
    assert post1_res.comments[0].text == "Great perspective"
    assert post1_res.comments[0].user.username == "commenter1"
    assert post1_res.comments[0].user.is_private is False


@pytest.mark.asyncio
async def test_research_topic_resilience_on_comment_failure():
    """Verify that if comment retrieval fails on one post, other posts still process."""
    mock_provider = AsyncMock()
    mock_provider.search_posts_or_reels = AsyncMock(return_value=[
        {"id": "p1", "url": "https://www.instagram.com/reel/P1/"},
        {"id": "p2", "url": "https://www.instagram.com/reel/P2/"},
    ])

    # First post comment call fails, second post succeeds
    mock_provider.get_post_comments = AsyncMock(side_effect=[
        Exception("Comments disabled for this post"),
        [{"id": "c2", "text": "Helpful"}],
    ])

    service = InstagramService(provider=mock_provider)
    result = await service.research_topic(query="therapy", max_posts=2, max_comments_per_post=5)

    assert len(result.results) == 2
    assert result.results[0].comments == []
    assert len(result.results[1].comments) == 1
    assert result.results[1].comments[0].text == "Helpful"
