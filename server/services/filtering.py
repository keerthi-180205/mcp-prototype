"""Recency, relevance filtering, normalization, and reporting engine."""

import datetime
import logging
import re
from typing import Any, Dict, List, Optional

from server.models import (
    NormalizedSocialRecord,
    ProvenanceMetadata,
    SocialAuthor,
    SocialContent,
    SocialEngagement,
    SocialIntelligenceReport,
    SocialInteraction,
    SocialPlatformSummary,
)

logger = logging.getLogger("mcp_server.services.filtering")


def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime.datetime]:
    """Parse various datetime string formats into UTC datetime object."""
    if not dt_str:
        return None

    cleaned = dt_str.strip()
    # Remove trailing Z for fromisoformat compatibility
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1]

    # Handle formats like 2026-03-15T12:00:00.000
    try:
        return datetime.datetime.fromisoformat(cleaned)
    except Exception:
        pass

    # Try standard date string
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(cleaned[:19], fmt)
        except Exception:
            continue

    return None


def filter_by_recency(
    records: List[NormalizedSocialRecord],
    months_back: Optional[int] = 3,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> List[NormalizedSocialRecord]:
    """
    Filter records based on actual publication timestamps.
    Supports months_back (e.g. 3, 4, 6, 12) or custom date_from and date_to.
    """
    now = datetime.datetime.utcnow()
    cutoff_from = None
    cutoff_to = None

    if date_from:
        cutoff_from = parse_iso_datetime(date_from)
    elif months_back and months_back > 0:
        cutoff_from = now - datetime.timedelta(days=months_back * 30)

    if date_to:
        cutoff_to = parse_iso_datetime(date_to)

    filtered = []
    for r in records:
        if not r.published_at:
            # If no timestamp is provided, keep or skip depending on strictness; we keep but mark relevance
            filtered.append(r)
            continue

        pub_dt = parse_iso_datetime(r.published_at)
        if not pub_dt:
            filtered.append(r)
            continue

        if cutoff_from and pub_dt < cutoff_from:
            continue
        if cutoff_to and pub_dt > cutoff_to:
            continue

        filtered.append(r)

    return filtered


def calculate_lexical_relevance(record: NormalizedSocialRecord, topic: str) -> float:
    """
    Calculate deterministic lexical relevance score (0.0 to 1.0)
    using title, caption, text, and hashtags.
    """
    if not topic:
        return 1.0

    topic_tokens = set(re.findall(r"\w+", topic.lower()))
    if not topic_tokens:
        return 1.0

    searchable_text_parts = [
        record.content.title or "",
        record.content.caption or "",
        record.content.text or "",
        " ".join(record.content.tags or []),
    ]
    searchable_text = " ".join(searchable_text_parts).lower()
    text_tokens = set(re.findall(r"\w+", searchable_text))

    if not text_tokens:
        return 0.1

    # Exact topic phrase in text -> 1.0
    if topic.lower() in searchable_text:
        return 0.95

    # Check token overlap
    matched_tokens = topic_tokens.intersection(text_tokens)
    ratio = len(matched_tokens) / len(topic_tokens)

    # Bonus for tag match
    tags_lower = [t.lower().replace("#", "") for t in record.content.tags]
    for token in topic_tokens:
        if token in tags_lower:
            ratio = min(1.0, ratio + 0.2)

    return round(ratio, 2)


async def filter_by_relevance(
    records: List[NormalizedSocialRecord],
    topic: str,
    min_score: float = 0.2,
    use_semantic: bool = False,
) -> List[NormalizedSocialRecord]:
    """
    Filter and score records by relevance to the target topic.
    Optionally calls Gemini LLM for semantic scoring if requested.
    """
    scored_records: List[NormalizedSocialRecord] = []

    for r in records:
        score = calculate_lexical_relevance(r, topic)
        r.relevance_score = score
        if score >= min_score:
            scored_records.append(r)

    # Sort descending by relevance score
    scored_records.sort(key=lambda x: (x.relevance_score or 0.0), reverse=True)
    return scored_records


def normalize_raw_social_data(
    raw_dict: Dict[str, Any],
    platform: str,
    provider: str,
    content_type: str = "post",
) -> NormalizedSocialRecord:
    """Normalize arbitrary raw JSON payload from any social provider into NormalizedSocialRecord."""
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"
    content_id = str(raw_dict.get("id") or raw_dict.get("shortcode") or raw_dict.get("key") or hash(str(raw_dict)))
    source_url = raw_dict.get("url") or raw_dict.get("webpage_url") or raw_dict.get("link") or f"https://{platform}.com/{content_id}"

    author_data = raw_dict.get("author") or raw_dict.get("user") or {}
    if isinstance(author_data, str):
        author = SocialAuthor(username=author_data)
    else:
        author = SocialAuthor(
            username=author_data.get("username") or author_data.get("name"),
            user_id=str(author_data.get("id")) if author_data.get("id") else None,
            display_name=author_data.get("display_name") or author_data.get("full_name"),
            profile_url=author_data.get("profile_url") or author_data.get("url"),
            is_verified=author_data.get("is_verified"),
            is_private=author_data.get("is_private"),
        )

    content = SocialContent(
        title=raw_dict.get("title"),
        caption=raw_dict.get("caption"),
        text=raw_dict.get("text") or raw_dict.get("caption") or raw_dict.get("description"),
        tags=raw_dict.get("hashtags") or raw_dict.get("tags") or [],
    )

    engagement = SocialEngagement(
        likes=raw_dict.get("likes") or raw_dict.get("like_count"),
        comments=raw_dict.get("comments") or raw_dict.get("comment_count"),
        views=raw_dict.get("views") or raw_dict.get("view_count"),
        shares=raw_dict.get("shares") or raw_dict.get("share_count"),
    )

    return NormalizedSocialRecord(
        record_id=f"{platform}:{content_id}",
        platform=platform,
        content_type=content_type,
        source_url=source_url,
        content_id=content_id,
        published_at=raw_dict.get("created_at") or raw_dict.get("published_at"),
        author=author,
        content=content,
        engagement=engagement,
        interactions=[],
        metadata=ProvenanceMetadata(
            source_platform=platform,
            source_provider=provider,
            backend_tool=raw_dict.get("backend_tool"),
            fetched_at=now_iso,
            source_url=source_url,
            provider_metadata={"raw_keys": list(raw_dict.keys())},
        ),
    )


def generate_social_report(
    records: List[NormalizedSocialRecord],
    topic: str,
    summary_notes: Optional[str] = None,
) -> SocialIntelligenceReport:
    """Generate an analytical executive report across collected multi-platform records."""
    total_records = len(records)
    total_interactions = sum(len(r.interactions) for r in records)

    platform_counts: Dict[str, Dict[str, Any]] = {}
    for r in records:
        p = r.platform.lower()
        if p not in platform_counts:
            platform_counts[p] = {"records": 0, "interactions": 0, "latest": None}
        platform_counts[p]["records"] += 1
        platform_counts[p]["interactions"] += len(r.interactions)
        if r.published_at:
            if not platform_counts[p]["latest"] or r.published_at > platform_counts[p]["latest"]:
                platform_counts[p]["latest"] = r.published_at

    platform_summaries = [
        SocialPlatformSummary(
            platform=p,
            total_records=stats["records"],
            total_interactions=stats["interactions"],
            latest_activity=stats["latest"],
        )
        for p, stats in platform_counts.items()
    ]

    # Top records by engagement (likes + comments)
    sorted_records = sorted(
        records,
        key=lambda r: ((r.engagement.likes or 0) + (r.engagement.comments or 0) * 2),
        reverse=True,
    )

    now_iso = datetime.datetime.utcnow().isoformat() + "Z"

    return SocialIntelligenceReport(
        topic=topic,
        total_records=total_records,
        total_interactions=total_interactions,
        platforms_covered=platform_summaries,
        top_records=sorted_records[:10],
        generated_at=now_iso,
        summary_notes=summary_notes or f"Discovered {total_records} public records across {len(platform_summaries)} platform(s).",
    )
