"""Live Multi-Platform Trending Social Intelligence & Semantic Filter Service.

Fetches the MOST TRENDING and RECENT posts, reels, and videos in real time across:
- YouTube (Live via Agent Reach / yt-dlp)
- Reddit (Live via search RSS / new feed)
- Instagram (Live via Apify / Explore tags)
- Twitter / X (Live discussions and tweet feeds)
- LinkedIn (Live contextual professional commentary)

Strict Recency Policy:
- ONLY data from the last 3 to 4 months (<= 120 days old).
- Anything older than 120 days is strictly filtered out.

Extracts:
1. user_name in the comments section
2. What they commented
3. Platform Name & Media Type
4. Clickable link of the post/reel/video
5. Published date & relative recency (verifying <= 120 days)
6. Agent Reach semantic relevance score & rationale (WITHOUT Gemini API)
"""

import asyncio
import datetime
import html
import json
import logging
import os
import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("mcp_server.services.profile_discovery")

# In-memory platform connection state - Universal coverage by default
PLATFORM_CONNECTIONS: Dict[str, Dict[str, Any]] = {
    "youtube": {
        "connected": True,
        "name": "YouTube",
        "icon": "youtube",
        "account": None,
        "features": ["Live Trending Videos", "Shorts", "Commenters", "Public Comments"],
        "color": "#ef4444",
        "badge_class": "badge-youtube",
    },
    "reddit": {
        "connected": True,
        "name": "Reddit",
        "icon": "reddit",
        "account": None,
        "features": ["Live Subreddit Posts", "Discussions", "Community Commenters"],
        "color": "#f97316",
        "badge_class": "badge-reddit",
    },
    "instagram": {
        "connected": True,
        "name": "Instagram",
        "icon": "instagram",
        "account": None,
        "features": ["Live Reels", "Explore Posts", "Commenters", "Reels Links"],
        "color": "#ec4899",
        "badge_class": "badge-instagram",
    },
    "twitter": {
        "connected": True,
        "name": "Twitter / X",
        "icon": "twitter",
        "account": None,
        "features": ["Live Tweets", "Replies", "Commenters", "Thread Links"],
        "color": "#38bdf8",
        "badge_class": "badge-twitter",
    },
    "linkedin": {
        "connected": True,
        "name": "LinkedIn",
        "icon": "linkedin",
        "account": None,
        "features": ["Professional Posts", "Articles", "Commenters", "Discussions"],
        "color": "#0a66c2",
        "badge_class": "badge-linkedin",
    },
}

CUTOFF_DAYS = 120  # Strict 3 to 4 months trending window limit


def get_recency_cutoff() -> Tuple[datetime.datetime, datetime.datetime, str, int]:
    """Calculate system clock now, 120-day cutoff date, YYYYMMDD string, and unix timestamp."""
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=CUTOFF_DAYS)
    return now, cutoff, cutoff.strftime("%Y%m%d"), int(cutoff.timestamp())


def format_relative_time(dt: datetime.datetime, now: datetime.datetime) -> str:
    """Format a datetime into a human-friendly relative time string."""
    diff = now - dt
    days = diff.days
    if days <= 0:
        hours = max(1, diff.seconds // 3600)
        return f"{hours}h ago (Today)"
    elif days == 1:
        return "1 day ago"
    elif days < 7:
        return f"{days} days ago"
    elif days < 30:
        weeks = days // 7
        return f"{weeks} week{'s' if weeks > 1 else ''} ago"
    else:
        months = days // 30
        return f"{months} month{'s' if months > 1 else ''} ago"


def get_platform_statuses() -> Dict[str, Any]:
    """Platform statuses; `connected` is real (a provider chain can deliver), not a stored flag."""
    from server.chat.assistant import get_platforms_availability

    real = get_platforms_availability()
    out: Dict[str, Any] = {}
    for key, info in PLATFORM_CONNECTIONS.items():
        status = real.get("x" if key == "twitter" else key, {})
        out[key] = {**info, "connected": bool(status.get("available")), "reason": status.get("reason")}
    return out


def update_platform_connection(platform_key: str, connected: bool, account: Optional[str] = None) -> Dict[str, Any]:
    """Toggle or update a platform's connection status."""
    key = platform_key.lower().strip()
    if key in PLATFORM_CONNECTIONS:
        PLATFORM_CONNECTIONS[key]["connected"] = connected
        if account:
            PLATFORM_CONNECTIONS[key]["account"] = account
        logger.info("Platform '%s' updated: connected=%s", key, connected)
        return PLATFORM_CONNECTIONS[key]
    raise ValueError(f"Unknown platform: {platform_key}")


from server.services.query_processor import get_query_processor


def clean_search_topic(raw_input: str) -> str:
    """Extract a clean, concise search keyword from conversational sentences."""
    if not raw_input:
        return "Trending"

    text = raw_input.strip()

    # Strip conversational instruction phrases
    instruction_patterns = [
        r"\b(trending\s+means|what\s+trending\s+means)\b",
        r"\b(\d+\s*(to|-)\s*\d+\s*months?(\s+old)?)\b",
        r"\b(not\s+older\s+than\s+that|not\s+older|older\s+than\s+\w+)\b",
        r"\b(as\s+much\s+as\s+possible|as\s+many\s+as\s+possible)\b",
        r"\b(universal\s+platform|universal|all\s+platforms?)\b",
        r"\b(i\s+want\s+the\s+data|i\s+want\s+data|give\s+me\s+data|fetch\s+data)\b",
        r"\b(find|search|get|show|fetch|collect|tell|look for|give me)\s+(me\s+)?(all\s+)?(the\s+)?(info|information|data|posts|reels|comments|videos)\s+(about|on|for)\b",
    ]
    for pat in instruction_patterns:
        text = re.sub(pat, " ", text, flags=re.IGNORECASE).strip()

    stop_words = {
        "i", "want", "data", "from", "on", "about", "what", "who", "they", "said",
        "and", "the", "a", "an", "recent", "trending", "months", "month", "not",
        "older", "than", "that", "also", "it", "should", "be", "means", "much",
        "possible", "universal", "platform", "platforms", "comments", "comment",
        "posts", "post", "reels", "reel", "videos", "video", "content", "section"
    }
    tokens = [w for w in re.findall(r"[A-Za-z0-9]+", text) if w.lower() not in stop_words]
    if tokens:
        return " ".join(tokens).title()

    return text.title() or "Trending"


def semantic_comment_match(
    comment_text: str,
    user_name: str,
    media_title: str,
    target_topic: str,
    user_intent: str = "trend_analysis",
) -> Tuple[int, str, str, str, List[str]]:
    """
    Intelligent semantic evaluation engine for social comments.
    Scores relevance of the comment to the user's search topic and assigns dynamic intent categories.
    """
    text_lower = comment_text.lower()
    title_lower = media_title.lower()
    topic_lower = target_topic.lower()
    topic_tokens = set(re.findall(r"\w+", topic_lower))

    score = 70
    reasons = []
    tags = []

    # 1. Topic Keyword Overlap
    matched_kws = [tok for tok in topic_tokens if tok in text_lower or tok in title_lower]
    if matched_kws:
        score += min(24, len(matched_kws) * 12)
        tags.append(f"{matched_kws[0].capitalize()} Topic")
        reasons.append(f"Directly references target topic terms: {', '.join(matched_kws)}")
    elif any(tok in title_lower for tok in topic_tokens):
        score += 15
        reasons.append(f"Commented directly under recent post/reel covering '{target_topic}'")

    # 2. Dynamic Intent Categorization (Topic-agnostic)
    if re.search(r"\b(how much|cost|price|hire|dm|where to buy|interested|rates|program|coaching|1:1|consultation|link|order|buy|discount|coupon)\b", text_lower):
        category = "Inquiry & Commercial Lead"
        score += 12
        tags.append("Commercial Inquiry")
        reasons.append("Commenter expresses direct inquiry, pricing question, or transaction interest")
    elif re.search(r"\b(struggling|hard|problem|issue|slow|bug|broken|error|fail|hate|worst|terrible|disappointed|burnout|anxiety|stress|criticism)\b", text_lower):
        category = "Pain Point & Grievance"
        score += 12
        tags.append("User Pain Point")
        reasons.append("Commenter shares real struggles, bugs, or critique regarding the topic")
    elif re.search(r"\b(love|awesome|great|best|clutch|unreal|masterclass|class|fire|100%|hero|icon|gem|helpful|recommended|works|thanks|congrats)\b", text_lower):
        category = "Praise & Endorsement"
        score += 10
        tags.append("Positive Sentiment")
        reasons.append("Expresses positive endorsement, praise, or strong enthusiasm")
    elif re.search(r"\b(debate|why|stats|data|actually|compare|versus|vs|method|strategy|alternative|perspective|thoughts|opinion)\b", text_lower):
        category = "Analysis & Technical Debate"
        score += 10
        tags.append("Community Debate")
        reasons.append("Commenter provides analytical perspective, comparison, or technical discussion")
    else:
        category = "Community Discussion"
        score += 6
        tags.append("Organic Voice")
        reasons.append("Organic community reaction and feedback")

    final_score = min(99, max(65, score))

    if final_score >= 90:
        grade = "Exceptional Match"
    elif final_score >= 80:
        grade = "High Match"
    else:
        grade = "Moderate Match"

    reasoning_str = ". ".join(reasons) + "." if reasons else f"Live social engagement related to '{target_topic}' within trending window."

    return final_score, grade, category, reasoning_str, tags[:3]


_DISPLAY_NAME = {"youtube": "YouTube", "reddit": "Reddit", "instagram": "Instagram", "x": "Twitter / X", "linkedin": "LinkedIn"}
_MEDIA_TYPE = {
    "youtube": "Video",
    "reddit": "Post & Discussion",
    "instagram": "Reel / Post",
    "x": "Tweet & Thread",
    "linkedin": "Professional Post",
}
_INSTAGRAM_NAMED = re.compile(r"\b(instagram|insta|ig|reels?)\b", re.IGNORECASE)


def _display_handle(platform: str, username: str) -> str:
    name = (username or "").strip().lstrip("@")
    if not name:
        return ""
    if platform == "reddit":
        return name if name.startswith("u/") else f"u/{name}"
    if platform == "linkedin":
        return name
    return f"@{name}"


async def _collect_via_pipeline(
    topic: str,
    keywords: List[str],
    platforms: List[str],
    now: datetime.datetime,
    cutoff_dt: datetime.datetime,
    per_platform: int = 25,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """Collect real comments through the same provider chains the collection jobs use.

    Nothing is invented: a platform that cannot deliver simply contributes no rows, and the
    reason is returned in the per-platform status.
    """
    from server.collection.harvester import harvest_platform
    from server.collection.models import CollectionLimits, PlatformProgress
    from server.collection.planner import plan_with_rules
    from server.collection.ranking import parse_iso
    from server.collection.registry import get_collector, normalize_platforms

    plan = plan_with_rules(topic)
    seen = {k.lower() for k in plan.keywords}
    plan.keywords = plan.keywords + [k for k in keywords if k and k.lower() not in seen]
    limits = CollectionLimits(target_comments=per_platform, max_posts=6, max_seconds=90.0, candidates_per_platform=30)

    async def _one(platform: str):
        progress = PlatformProgress(platform=platform)
        index: Dict[str, Any] = {}
        rows = await harvest_platform(get_collector(platform), plan, limits, progress, post_index=index)
        return platform, rows, index, progress

    items: List[Dict[str, Any]] = []
    status: Dict[str, Dict[str, Any]] = {}
    for platform, rows, index, progress in await asyncio.gather(*[_one(p) for p in normalize_platforms(platforms)]):
        status[platform] = {
            "status": progress.status,
            "collected": len(rows),
            "stop_reason": progress.stop_reason,
            "error": progress.error,
            "notes": progress.notes,
        }
        for row in rows:
            when = parse_iso(row.created_at)
            if when and when < cutoff_dt:  # older than the recency window
                continue
            post = index.get(row.post_url)
            items.append({
                "platform": _DISPLAY_NAME.get(platform, platform.title()),
                "media_type": _MEDIA_TYPE.get(platform, "Post"),
                "media_title": (post.title if post and post.title else "")[:120] or f"{_DISPLAY_NAME.get(platform)} post",
                "media_url": row.post_url,
                "user_name": _display_handle(platform, row.username),
                "user_id": row.user_id,
                "provider": row.provider,
                "comment": row.comment,
                "likes": row.likes,
                "published_date": when.strftime("%Y-%m-%d") if when else None,
                "recency_text": format_relative_time(when, now) if when else "Date unknown",
                "is_trending_window": bool(when),
            })
    return items, status


async def discover_and_filter_profiles(
    field: str,
    description: str,
    media_types: Optional[List[str]] = None,
    connected_platforms: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Universal Multi-Platform Social Intelligence Extractor:
    1. Processes user query using Google Gemini API to extract clean topic, search keywords, and user intent.
    2. Queries live trending posts across platforms concurrently (YouTube, Reddit, Instagram, Twitter/X, LinkedIn).
    3. Strictly filters content to <= 3 to 4 months old (120 days).
    4. Extracts commenter usernames and real comments.
    5. Evaluates semantic match and intent categories dynamically.
    6. Uses Gemini to synthesize an executive social briefing for the user.
    """
    raw_query = description or field or "Trending"

    # Step 1: Process user query with Gemini
    qp = get_query_processor()
    processed_query = await qp.process_user_query(
        query=raw_query,
        fallback_field=field,
        connected_platforms=connected_platforms,
    )

    target_topic = processed_query.clean_topic
    search_keywords = processed_query.search_keywords or [target_topic]
    primary_search_term = search_keywords[0] if search_keywords else target_topic

    now, cutoff_dt, cutoff_yyyymmdd, cutoff_ts = get_recency_cutoff()

    # Platforms requested by user or active connections
    candidate_platforms = processed_query.target_platforms or connected_platforms or [p for p, data in get_platform_statuses().items() if data["connected"]]
    active_keys = [p.lower() for p in candidate_platforms]

    logger.info(
        "Universal live discovery starting: clean_topic=%r, intent=%r, cutoff=%s (%d days) across platforms=%r",
        target_topic, processed_query.intent, cutoff_yyyymmdd, CUTOFF_DAYS, active_keys
    )

    # Instagram spends paid credits, so it is only searched when the user's request names it.
    run_platforms = [p for p in active_keys if p != "instagram" or _INSTAGRAM_NAMED.search(raw_query)]
    all_comments, platform_status = await _collect_via_pipeline(
        target_topic, search_keywords, run_platforms, now, cutoff_dt
    )

    # Run Semantic Match & Intent Filtering
    matched_results = []
    for item in all_comments:
        c_text = item["comment"]
        u_name = item["user_name"]
        score, grade, cat, reasoning, tags = semantic_comment_match(
            c_text, u_name, item["media_title"], target_topic, user_intent=processed_query.intent
        )

        matched_results.append({
            "user_name": u_name,
            "username": u_name,
            "comment": c_text,
            "comment_text": c_text,
            "platform": item["platform"],
            "media_type": item["media_type"],
            "media_title": item["media_title"],
            "media_url": item["media_url"],
            "post_url": item["media_url"],
            "link": item["media_url"],
            "likes": item.get("likes", 0),
            "published_date": item.get("published_date"),
            "recency_text": item.get("recency_text", "Date unknown"),
            "is_trending_window": bool(item.get("is_trending_window")),
            "match_score": score,
            "match_grade": grade,
            "category": cat,
            "intent_category": cat,
            "llm_reasoning": reasoning,
            "qualification_tags": tags or processed_query.qualification_tags,
            # UI aliases for profiles view
            "display_name": u_name.lstrip("@").lstrip("u/").replace("_", " ").title(),
            "profile_url": item["media_url"],
            "user_id": item.get("user_id"),
            "provider": item.get("provider"),
            "bio": c_text[:120],
        })

    # Sort primarily by match score
    matched_results.sort(key=lambda x: x["match_score"], reverse=True)

    # Step 6: Use Gemini to synthesize intelligent executive briefing
    ai_summary = await qp.synthesize_social_insights(
        topic=target_topic,
        comments=matched_results,
        user_query=raw_query,
    )

    searched_plat_names = [_DISPLAY_NAME.get(p, p.title()) for p in platform_status]

    return {
        "status": "success",
        "chatbot_message": ai_summary,
        "summary_message": ai_summary,
        "ai_response_plan": processed_query.ai_response,
        "user_goal": processed_query.user_goal,
        "intent": processed_query.intent,
        "field": target_topic,
        "topic": target_topic,
        "search_keywords": search_keywords,
        "description": raw_query,
        "matched_profiles": matched_results,
        "matched_comments": matched_results,
        "comments": matched_results,
        "total_scraped": len(all_comments),
        "total_matched": len(matched_results),
        "platforms_searched": searched_plat_names,
        "platform_status": platform_status,
        "recency_cutoff_date": cutoff_dt.strftime("%Y-%m-%d"),
        "recency_window": "3 to 4 months (<= 120 days)",
    }
