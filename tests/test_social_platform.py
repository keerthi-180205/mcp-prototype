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
