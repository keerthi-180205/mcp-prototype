"""Unit tests for the Universal Social Intelligence & Outreach Data Platform."""

import datetime
import os
import tempfile
import pytest

from server.models import (
    NormalizedSocialRecord,
    ProvenanceMetadata,
    SocialAuthor,
    SocialContent,
    SocialEngagement,
    SocialInteraction,
)
from server.providers.social.base import SocialDataProvider
from server.providers.social.registry import SocialProviderRegistry
from server.services.filtering import (
    filter_by_recency,
    filter_by_relevance,
    generate_social_report,
    normalize_raw_social_data,
    parse_iso_datetime,
)
from server.storage.sqlite import (
    get_social_records,
    get_social_stats,
    init_db,
    save_social_records,
)


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database path for isolated testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def sample_records():
    """Generate realistic test records across multiple platforms and recency ranges."""
    now = datetime.datetime.utcnow()
    one_month_ago = (now - datetime.timedelta(days=30)).isoformat() + "Z"
    five_months_ago = (now - datetime.timedelta(days=150)).isoformat() + "Z"

    r1 = NormalizedSocialRecord(
        record_id="instagram:reel_123",
        platform="instagram",
        content_type="reel",
        source_url="https://www.instagram.com/reel/reel_123/",
        content_id="reel_123",
        published_at=one_month_ago,
        author=SocialAuthor(username="fitness_guru", display_name="Fitness Coach"),
        content=SocialContent(
            title="Morning Workout Routine",
            caption="Best fitness tips for beginners #fitness #health",
            text="Best fitness tips for beginners #fitness #health",
            tags=["fitness", "health"],
        ),
        engagement=SocialEngagement(likes=1200, comments=45, views=15000),
        interactions=[
            SocialInteraction(
                interaction_id="c_1",
                type="comment",
                text="This workout changed my routine!",
                author=SocialAuthor(username="user_a"),
                created_at=one_month_ago,
                likes=12,
            )
        ],
        metadata=ProvenanceMetadata(
            source_platform="instagram",
            source_provider="apify",
            backend_tool="instagram-scraper",
            fetched_at=now.isoformat() + "Z",
            source_url="https://www.instagram.com/reel/reel_123/",
        ),
    )

    r2 = NormalizedSocialRecord(
        record_id="youtube:vid_456",
        platform="youtube",
        content_type="video",
        source_url="https://www.youtube.com/watch?v=vid_456",
        content_id="vid_456",
        published_at=five_months_ago,
        author=SocialAuthor(username="AI_Insights", display_name="AI Insights Channel"),
        content=SocialContent(
            title="Building AI Tools in 2026",
            caption="Comprehensive guide to AI tools and automation",
            text="Comprehensive guide to AI tools and automation",
            tags=["ai", "technology"],
        ),
        engagement=SocialEngagement(likes=5400, comments=310, views=85000),
        interactions=[],
        metadata=ProvenanceMetadata(
            source_platform="youtube",
            source_provider="agent-reach",
            backend_tool="yt-dlp",
            fetched_at=now.isoformat() + "Z",
            source_url="https://www.youtube.com/watch?v=vid_456",
        ),
    )

    return [r1, r2]


# ==============================================================================
# Model & Schema Tests
# ==============================================================================


def test_normalized_social_record_creation(sample_records):
    """Verify NormalizedSocialRecord instantiation and field accessibility."""
    record = sample_records[0]
    assert record.platform == "instagram"
    assert record.content_id == "reel_123"
    assert record.author.username == "fitness_guru"
    assert record.engagement.likes == 1200
    assert len(record.interactions) == 1
    assert record.interactions[0].author.username == "user_a"
    assert record.metadata.source_provider == "apify"


# ==============================================================================
# Storage & Deduplication Tests
# ==============================================================================


def test_sqlite_storage_and_deduplication(temp_db, sample_records):
    """Verify SQLite persistence, unique index deduplication, and interaction tracking."""
    init_db(temp_db)

    # First insert
    stats = save_social_records(sample_records, db_path=temp_db)
    assert stats["inserted"] == 2
    assert stats["updated"] == 0
    assert stats["interactions_saved"] == 1

    # Query records back
    stored = get_social_records(db_path=temp_db)
    assert len(stored) == 2

    # Verify fields on retrieved record
    insta_rec = next(r for r in stored if r.platform == "instagram")
    assert insta_rec.content_id == "reel_123"
    assert len(insta_rec.interactions) == 1
    assert insta_rec.interactions[0].text == "This workout changed my routine!"

    # Second insert with updated engagement (should deduplicate and update)
    sample_records[0].engagement.likes = 2500
    stats2 = save_social_records(sample_records, db_path=temp_db)
    assert stats2["inserted"] == 0
    assert stats2["updated"] == 2

    # Verify updated values in db
    stored_after_update = get_social_records(platform="instagram", db_path=temp_db)
    assert len(stored_after_update) == 1
    assert stored_after_update[0].engagement.likes == 2500

    # Aggregated stats
    db_stats = get_social_stats(temp_db)
    assert db_stats["total_records"] == 2
    assert "instagram" in db_stats["platforms"]
    assert "youtube" in db_stats["platforms"]


# ==============================================================================
# Recency & Relevance Filtering Tests
# ==============================================================================


def test_recency_filtering(sample_records):
    """Verify recency filter with months_back and custom date boundaries."""
    # Last 3 months: should keep record 1 (1 month ago), exclude record 2 (5 months ago)
    recent_3m = filter_by_recency(sample_records, months_back=3)
    assert len(recent_3m) == 1
    assert recent_3m[0].content_id == "reel_123"

    # Last 6 months: should include both records
    recent_6m = filter_by_recency(sample_records, months_back=6)
    assert len(recent_6m) == 2


@pytest.mark.asyncio
async def test_relevance_filtering(sample_records):
    """Verify lexical relevance calculation and threshold filtering."""
    # Target topic: "fitness"
    fitness_results = await filter_by_relevance(sample_records, topic="fitness", min_score=0.2)
    assert len(fitness_results) == 1
    assert fitness_results[0].content_id == "reel_123"
    assert fitness_results[0].relevance_score > 0.5

    # Target topic: "AI tools"
    ai_results = await filter_by_relevance(sample_records, topic="AI tools", min_score=0.2)
    assert len(ai_results) == 1
    assert ai_results[0].content_id == "vid_456"


def test_normalize_raw_social_data():
    """Verify raw JSON normalization into the universal schema."""
    raw = {
        "id": "tweet_999",
        "url": "https://x.com/tech_user/status/tweet_999",
        "text": "Excited to launch our new ebook selling guide! Check it out.",
        "author": {"username": "tech_user", "name": "Tech Enthusiast"},
        "likes": 50,
        "comments": 8,
    }
    normalized = normalize_raw_social_data(
        raw_dict=raw, platform="x", provider="x_adapter", content_type="tweet"
    )
    assert normalized.platform == "x"
    assert normalized.content_id == "tweet_999"
    assert normalized.author.username == "tech_user"
    assert normalized.engagement.likes == 50
    assert normalized.metadata.source_provider == "x_adapter"


def test_generate_social_report(sample_records):
    """Verify analytical summary report generation across platforms."""
    report = generate_social_report(sample_records, topic="Health and Tech")
    assert report.topic == "Health and Tech"
    assert report.total_records == 2
    assert report.total_interactions == 1
    assert len(report.platforms_covered) == 2
    assert len(report.top_records) == 2


# ==============================================================================
# Provider Registry & Fallback Tests
# ==============================================================================


class MockSocialProvider(SocialDataProvider):
    platform_name = "test_platform"
    provider_name = "mock_primary"

    def __init__(self, available: bool = True):
        self._avail = available

    def is_available(self) -> bool:
        return self._avail

    async def search_content(self, query: str, limit: int = 10, **kwargs):
        return []

    async def get_content(self, content_url_or_id: str):
        return None

    async def get_comments(self, content_url_or_id: str, limit: int = 20):
        return []

    async def get_profile(self, identifier: str):
        return SocialAuthor(username="test_user")


def test_provider_registry_fallback():
    """Verify fallback routing to secondary provider when primary is unavailable."""
    registry = SocialProviderRegistry()
    primary = MockSocialProvider(available=False)
    secondary = MockSocialProvider(available=True)
    secondary.provider_name = "mock_secondary"

    registry.register_provider(primary, is_primary=True)
    registry.register_provider(secondary, is_primary=False)

    chosen = registry.get_provider("test_platform")
    assert chosen is not None
    assert chosen.provider_name == "mock_secondary"


# ==============================================================================
# MCP Tool Invocation Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_mcp_social_tools():
    """Verify end-to-end execution of newly exposed social MCP tools."""
    from server import server

    # 1. normalize_social_data tool
    raw_sample = {
        "id": "post_789",
        "url": "https://example.com/post/789",
        "title": "Universal Social Data Guide",
        "caption": "How to build generic data platforms",
        "author": {"username": "architect_dev"},
    }
    norm_res = server.normalize_social_data(
        raw_data=raw_sample,
        platform="web",
        provider="custom_scraper",
        content_type="article",
    )
    assert norm_res["status"] == "success"
    assert norm_res["record"]["platform"] == "web"
    assert norm_res["record"]["content_id"] == "post_789"

    # 2. filter_relevant_content tool
    rec = norm_res["record"]
    filter_res = server.filter_relevant_content(
        records=[rec],
        topic="social data",
        min_relevance=0.2,
    )
    assert filter_res["status"] == "success"
    assert filter_res["filtered_count"] == 1

    # 3. store_social_records tool
    store_res = server.store_social_records(records=[rec])
    assert store_res["status"] == "success"
    assert "storage_stats" in store_res

    # 4. generate_social_report tool
    report_res = server.generate_social_report(records=[rec], topic="social data")
    assert report_res["status"] == "success"
    assert report_res["report"]["total_records"] == 1
    assert report_res["report"]["topic"] == "social data"


@pytest.mark.asyncio
async def test_instagram_provider_abstraction_and_query_discovery():
    """Phase 3 & Phase 4 test: InstagramProvider abstraction and natural language query discovery without URL."""
    from unittest.mock import AsyncMock
    from server.providers.social.instagram import InstagramSocialProvider
    from server.models import InstagramPost, InstagramAuthor as IGAuthor
    from server.services.instagram import InstagramValidationError

    mock_service = AsyncMock()
    # Simulate discovery results for natural language query "Virat"
    mock_service.search_posts_or_reels.return_value = [
        InstagramPost(
            platform="instagram",
            content_type="reel",
            content_id="reel_virat_01",
            url="https://www.instagram.com/reel/reel_virat_01/",
            caption="Match winning innings highlights! #virat #cricket",
            author=IGAuthor(username="virat.kohli", display_name="Virat Kohli", is_verified=True),
            created_at="2026-09-01T10:00:00Z",
            like_count=500000,
            comment_count=12000,
            view_count=2500000,
        )
    ]

    provider = InstagramSocialProvider(service=mock_service)
    assert provider.platform_name == "instagram"
    assert provider.provider_name == "apify"

    # Natural language query with NO URL provided
    results = await provider.search_content(query="Virat", limit=20)
    mock_service.search_posts_or_reels.assert_called_once_with(query="Virat", max_results=20)

    assert len(results) == 1
    rec = results[0]
    assert rec.platform == "instagram"
    assert rec.content_id == "reel_virat_01"
    assert rec.author.username == "virat.kohli"
    assert rec.author.is_verified is True
    assert rec.engagement.likes == 500000
    assert rec.metadata.source_provider == "apify"

    # Validation: query cannot be empty
    from server.services.instagram import InstagramService
    real_service = InstagramService(provider=AsyncMock())
    with pytest.raises(InstagramValidationError):
        await real_service.search_posts_or_reels(query="   ", max_results=20)


def test_rank_social_candidates():
    """Verify deterministic candidate ranking on textual, profile, engagement, and recency signals."""
    from server.services.filtering import rank_social_candidates
    now = datetime.datetime.utcnow().isoformat() + "Z"

    # Candidate A: strong textual match, official username match, high engagement
    rec_a = NormalizedSocialRecord(
        record_id="instagram:a",
        platform="instagram",
        content_type="reel",
        source_url="https://www.instagram.com/reel/a/",
        content_id="a",
        published_at=now,
        author=SocialAuthor(username="virat.kohli", display_name="Virat Kohli"),
        content=SocialContent(caption="Preparation for the big match! #virat #cricket"),
        engagement=SocialEngagement(likes=100000, comments=5000),
        metadata=ProvenanceMetadata(source_platform="instagram", source_provider="apify", source_url="https://www.instagram.com/reel/a/", fetched_at=now),
    )

    # Candidate B: low relevance, completely different topic
    rec_b = NormalizedSocialRecord(
        record_id="instagram:b",
        platform="instagram",
        content_type="post",
        source_url="https://www.instagram.com/p/b/",
        content_id="b",
        published_at=now,
        author=SocialAuthor(username="random_cook", display_name="Baking Daily"),
        content=SocialContent(caption="How to bake sourdough bread step by step #bread"),
        engagement=SocialEngagement(likes=50, comments=2),
        metadata=ProvenanceMetadata(source_platform="instagram", source_provider="apify", source_url="https://www.instagram.com/p/b/", fetched_at=now),
    )

    ranked = rank_social_candidates([rec_b, rec_a], query="Virat")
    assert ranked[0].content_id == "a"
    assert ranked[1].content_id == "b"
    assert (ranked[0].relevance_score or 0) > (ranked[1].relevance_score or 0)


def test_filter_by_recency_days_back():
    """Verify filter_by_recency supports days_back filtering."""
    now = datetime.datetime.utcnow()
    recent = (now - datetime.timedelta(days=5)).isoformat() + "Z"
    old = (now - datetime.timedelta(days=40)).isoformat() + "Z"

    r_recent = NormalizedSocialRecord(
        record_id="r1", platform="instagram", content_type="reel",
        source_url="https://instagram.com/r1", content_id="r1", published_at=recent,
        metadata=ProvenanceMetadata(source_platform="instagram", source_provider="apify", source_url="https://instagram.com/r1", fetched_at=recent),
    )
    r_old = NormalizedSocialRecord(
        record_id="r2", platform="instagram", content_type="reel",
        source_url="https://instagram.com/r2", content_id="r2", published_at=old,
        metadata=ProvenanceMetadata(source_platform="instagram", source_provider="apify", source_url="https://instagram.com/r2", fetched_at=old),
    )

    filtered = filter_by_recency([r_recent, r_old], days_back=10)
    assert len(filtered) == 1
    assert filtered[0].content_id == "r1"


@pytest.mark.asyncio
async def test_search_social_topic_end_to_end():
    """Verify search_social_topic end-to-end orchestration, comment extraction, deduplication, and schema."""
    from unittest.mock import AsyncMock, MagicMock
    from server.services.social_intelligence import SocialIntelligenceService
    from server.models import SocialInteraction

    mock_provider = AsyncMock()
    mock_provider.is_available = MagicMock(return_value=True)

    # 1. Mock search candidates (including a duplicate ID to test deduplication)
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"
    cand_1 = NormalizedSocialRecord(
        record_id="instagram:post_100",
        platform="instagram",
        content_type="reel",
        source_url="https://www.instagram.com/reel/post_100/",
        content_id="post_100",
        published_at=now_iso,
        author=SocialAuthor(username="virat.kohli", user_id="1818", display_name="Virat Kohli", profile_url="https://www.instagram.com/virat.kohli/"),
        content=SocialContent(caption="Training day! Consistency is key #virat"),
        engagement=SocialEngagement(likes=250000, comments=1500),
        metadata=ProvenanceMetadata(source_platform="instagram", source_provider="apify", source_url="https://www.instagram.com/reel/post_100/", fetched_at=now_iso),
    )
    cand_dup = cand_1.model_copy()

    mock_provider.search_content.return_value = [cand_1, cand_dup]

    # 2. Mock comments
    mock_provider.get_comments.return_value = [
        SocialInteraction(
            interaction_id="c_99",
            type="comment",
            text="Incredible dedication!",
            author=SocialAuthor(username="fan_girl_01", user_id="888", display_name="Ananya", profile_url="https://www.instagram.com/fan_girl_01/"),
            created_at=now_iso,
            likes=42,
        ),
        # Duplicate comment to test comment deduplication
        SocialInteraction(
            interaction_id="c_99",
            type="comment",
            text="Incredible dedication!",
            author=SocialAuthor(username="fan_girl_01", user_id="888"),
            created_at=now_iso,
            likes=42,
        ),
    ]

    mock_registry = MagicMock()
    mock_registry.get_provider.return_value = mock_provider

    service = SocialIntelligenceService(registry=mock_registry)
    result = await service.search_social_topic(
        query="Virat",
        platform="instagram",
        top_n=5,
        comments_per_content=5,
        auto_store=False,
    )

    assert result["status"] == "success"
    assert result["query"] == "Virat"
    assert result["platform"] == "instagram"
    assert result["total_found"] == 1  # Deduplicated from 2 to 1
    assert len(result["results"]) == 1

    post_res = result["results"][0]
    assert post_res["rank"] == 1
    assert post_res["content_id"] == "post_100"
    assert post_res["author"]["username"] == "virat.kohli"
    assert post_res["author"]["user_id"] == "1818"
    assert post_res["author"]["profile_url"] == "https://www.instagram.com/virat.kohli/"
    assert post_res["engagement"]["likes"] == 250000
    assert post_res["source"]["provider"] == "apify"
    assert post_res["source"]["query"] == "Virat"

    # Verify comments normalization and deduplication
    assert len(post_res["comments"]) == 1  # Deduplicated from 2 to 1
    comm = post_res["comments"][0]
    assert comm["comment_id"] == "c_99"
    assert comm["text"] == "Incredible dedication!"
    assert comm["author"]["username"] == "fan_girl_01"
    assert comm["author"]["user_id"] == "888"
    assert comm["author"]["profile_url"] == "https://www.instagram.com/fan_girl_01/"
    assert comm["likes"] == 42


@pytest.mark.asyncio
async def test_search_social_topic_validation_and_error_handling():
    """Verify clean error handling for empty query, unavailable provider, and rate limiting."""
    from unittest.mock import AsyncMock, MagicMock
    from server.services.social_intelligence import SocialIntelligenceService
    from server.providers.apify import ApifyRateLimitError

    service = SocialIntelligenceService()

    # 1. Empty query
    res_empty = await service.search_social_topic(query="   ", platform="instagram")
    assert res_empty["status"] == "error"
    assert res_empty["error_type"] == "invalid_query"

    # 2. Unknown platform
    res_unknown = await service.search_social_topic(query="fitness", platform="unknown_platform")
    assert res_unknown["status"] == "error"
    assert res_unknown["error_type"] == "provider_unavailable"

    # 3. Rate limiting error
    mock_provider = AsyncMock()
    mock_provider.is_available = MagicMock(return_value=True)
    mock_provider.search_content.side_effect = ApifyRateLimitError("Rate limit exceeded on Apify Actor")

    mock_registry = MagicMock()
    mock_registry.get_provider.return_value = mock_provider

    service_with_mock = SocialIntelligenceService(registry=mock_registry)
    res_rate_limit = await service_with_mock.search_social_topic(query="fitness", platform="instagram")
    assert res_rate_limit["status"] == "error"
    assert res_rate_limit["error_type"] == "rate_limited"


@pytest.mark.asyncio
async def test_search_social_topic_mcp_tool_invocation():
    """Verify the search_social_topic tool registered on the FastMCP server works properly."""
    from unittest.mock import AsyncMock, patch
    import server.server as server

    mock_res = {
        "status": "success",
        "query": "mental health",
        "platform": "instagram",
        "total_found": 1,
        "results": [],
    }

    with patch.object(server.social_service, "search_social_topic", new=AsyncMock(return_value=mock_res)):
        out = await server.search_social_topic(
            query="mental health",
            platform="instagram",
            top_n=10,
        )
        assert out["status"] == "success"
        assert out["query"] == "mental health"


@pytest.mark.asyncio
async def test_youtube_social_provider_mocked():
    """Verify YouTubeSocialProvider search and comments parsing."""
    import json
    from unittest.mock import AsyncMock, patch
    from server.providers.social.youtube import YouTubeSocialProvider

    provider = YouTubeSocialProvider()
    fake_search_output = (
        '{"id": "yt_123", "title": "Fitness Guide", "uploader": "Coach Sam", "channel_id": "c_1", "webpage_url": "https://youtube.com/watch?v=yt_123", "view_count": 50000}\n'
    )
    fake_comments_output = json.dumps({
        "comments": [
            {
                "id": "c_yt_1",
                "author": "@fitness_fan",
                "author_id": "u_1",
                "author_url": "https://youtube.com/@fitness_fan",
                "text": "Great advice on workout routines!",
                "like_count": 15,
                "timestamp": 1720000000,
            }
        ]
    })

    with patch.object(provider, "_run_yt_dlp", new=AsyncMock(side_effect=[fake_search_output, fake_comments_output])):
        records = await provider.search_content("fitness", limit=5)
        assert len(records) == 1
        assert records[0].platform == "youtube"
        assert records[0].content_id == "yt_123"
        assert records[0].author.username == "Coach Sam"
        assert records[0].engagement.views == 50000

        comments = await provider.get_comments("yt_123", limit=5)
        assert len(comments) == 1
        assert comments[0].interaction_id == "c_yt_1"
        assert comments[0].author.username == "@fitness_fan"
        assert comments[0].likes == 15



