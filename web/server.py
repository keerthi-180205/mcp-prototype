"""Universal Web Application & Chatbot Server for Multi-Topic Social Intelligence & Outreach.

Supports ANY subject/topic:
- Mental health, stress, anxiety
- Ebook selling & digital products
- Video editing & creative services
- AI tools & software
- Fitness & bodybuilding
- Freelancing & marketing
- Any custom user-provided topic!
"""

import json
import logging
import os
import re
import sys
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv

# Ensure workspace root is in python path
WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_ROOT)

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from server.models import (
    NormalizedSocialRecord,
    ProvenanceMetadata,
    SocialAuthor,
    SocialContent,
    SocialEngagement,
    SocialInteraction,
)
from server.services.instagram import InstagramService, get_instagram_service
from server.storage.sqlite import get_social_records, get_social_stats, save_social_records

load_dotenv()
logger = logging.getLogger("mcp_server.web")
logging.basicConfig(level=logging.INFO)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def extract_topic_from_prompt(user_query: str) -> Tuple[str, str, str]:
    """
    Extract the clean target subject/topic, hashtag search key, and target platform from a natural language prompt.
    Returns: (display_topic, search_tag, platform)
    """
    q = user_query.strip().lower()
    platform = "instagram"
    if "youtube" in q:
        platform = "youtube"
    elif "github" in q:
        platform = "github"

    # Common topic mappings to optimal Instagram exploration tags
    if "mental health" in q:
        return "Mental Health", "mentalhealth", platform
    elif "stress" in q:
        return "Stress Relief", "stressrelief", platform
    elif "anxiety" in q:
        return "Anxiety Relief", "anxietyrelief", platform
    elif "exam" in q:
        return "Exam Tension", "examstress", platform
    elif "work pressure" in q or "burnout" in q:
        return "Work Pressure", "burnout", platform
    elif "ebook" in q:
        return "Ebook Selling", "ebookselling", platform
    elif "video edit" in q or "video editor" in q:
        return "Video Editing", "videoediting", platform
    elif "ai tool" in q or "ai tools" in q or "artificial intelligence" in q:
        return "AI Tools", "aitools", platform
    elif "fitness" in q or "workout" in q or "gym" in q:
        return "Fitness & Health", "fitness", platform
    elif "freelanc" in q:
        return "Freelancing", "freelancing", platform
    elif "marketing" in q:
        return "Marketing", "marketing", platform
    elif "real estate" in q:
        return "Real Estate", "realestate", platform

    # Generic extraction: remove conversational stopwords
    stop_words = {
        "i", "want", "data", "from", "on", "about", "instagram", "reels", "reel",
        "posts", "post", "comments", "comment", "find", "search", "the", "a", "an",
        "who", "commented", "what", "they", "said", "and", "for", "get", "collect",
        "show", "me", "look", "fetch", "extract", "public", "user", "users", "ids",
        "handles", "recent"
    }
    tokens = [w for w in re.findall(r"\w+", q) if w not in stop_words]

    if not tokens:
        return "Trending", "trending", platform

    display_topic = " ".join(tokens).title()
    search_tag = "".join(tokens).lower()
    return display_topic, search_tag, platform


def dynamic_comment_intent(comment_text: str, topic: str, caption: str = "") -> str:
    """
    Dynamically classify user comments across any topic into intent categories:
    - Inquiries / Purchase / Questions
    - Pain Points & Struggles
    - Feedback / Endorsements / Praise
    - Tips & Method Discussion
    """
    text_lower = comment_text.lower()

    if re.search(r"\b(how much|cost|price|where to buy|link|dm me|info|interested|guide|how can i|available|order|purchase|how to)\b", text_lower):
        return "Inquiry & Interest"
    elif re.search(r"\b(struggling|hard|difficult|fail|confused|problem|tired|issue|cannot|can't|hate|stuck|anxiety|stress|pressure|burnout)\b", text_lower):
        return "Pain Point & Struggle"
    elif re.search(r"\b(love|great|awesome|helpful|works|best|thank you|thanks|agreed|true|fact|fire|gem|100%|accurate)\b", text_lower):
        return "Praise & Feedback"
    elif re.search(r"\b(tutorial|tool|app|software|technique|method|strategy|workflow|tips|advice|secret)\b", text_lower):
        return "Tips & Method"
    else:
        short_topic = topic.split()[0].title() if topic else "Topic"
        return f"{short_topic} Discussion"


async def index(request: Request):
    """Serve the universal chatbot SPA."""
    index_file = os.path.join(STATIC_DIR, "index.html")
    return FileResponse(index_file)


async def chat_endpoint(request: Request):
    """
    Universal Chatbot endpoint.
    Accepts ANY subject (Ebook selling, AI tools, Video editors, Fitness, Mental health, etc.).
    Extracts public reels, navigates to comment sections, collects commenter IDs & exact comments.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    user_query = body.get("query", "").strip()
    if not user_query:
        return JSONResponse({"status": "error", "message": "Query cannot be empty."}, status_code=400)

    max_reels = min(int(body.get("max_reels", 2)), 5)
    max_comments = min(int(body.get("max_comments_per_reel", 10)), 30)

    # 1. Dynamically extract subject and search tag
    display_topic, search_tag, platform = extract_topic_from_prompt(user_query)
    logger.info("Universal request: raw_query=%r -> display=%r, search_tag=%r, platform=%r", user_query, display_topic, search_tag, platform)

    service: InstagramService = get_instagram_service()

    try:
        # Search public Instagram Reels for this tag
        discovered_posts = await service.search_posts_or_reels(
            query=search_tag,
            max_results=max_reels,
        )
    except Exception as e:
        logger.error("Error searching Instagram reels for topic %r: %s", search_tag, e)
        return JSONResponse({
            "status": "error",
            "message": f"Failed to acquire Instagram data for '{display_topic}': {str(e)}",
        }, status_code=500)

    extracted_comments: List[Dict[str, Any]] = []
    normalized_records: List[NormalizedSocialRecord] = []

    # 2. Extract public comments and commenter profiles from each reel
    for post in discovered_posts:
        reel_url = post.url
        reel_caption = post.caption or ""
        shortcode = post.content_id or reel_url.rstrip("/").split("/")[-1]

        # Skip explore tag pages if any slipped through
        if "/explore/tags/" in reel_url:
            continue

        try:
            comments_res = await service.get_post_comments(
                post_url=reel_url,
                max_comments=max_comments,
            )
            raw_comments = comments_res.comments
        except Exception as e:
            logger.warning("Could not fetch comments for %s: %s", reel_url, e)
            raw_comments = []

        interactions_for_record: List[SocialInteraction] = []

        for c in raw_comments:
            comment_text = (c.text or "").strip()
            if not comment_text:
                continue

            username = c.user.username if c.user and c.user.username else "instagram_user"
            user_id = c.user.id if c.user and c.user.id else None
            is_verified = c.user.is_verified if c.user else False
            intent_label = dynamic_comment_intent(comment_text, topic=display_topic, caption=reel_caption)

            extracted_item = {
                "user_handle": username,
                "user_id": user_id,
                "is_verified": is_verified,
                "comment_text": comment_text,
                "category": intent_label,
                "likes": c.like_count,
                "created_at": c.created_at,
                "post_url": reel_url,
                "reel_caption": reel_caption[:120] if reel_caption else None,
            }
            extracted_comments.append(extracted_item)

            interactions_for_record.append(
                SocialInteraction(
                    interaction_id=c.comment_id,
                    type="comment",
                    text=comment_text,
                    author=SocialAuthor(
                        username=username,
                        user_id=user_id,
                        profile_url=f"https://www.instagram.com/{username}/" if username else None,
                        is_verified=is_verified,
                    ),
                    created_at=c.created_at,
                    likes=c.like_count,
                )
            )

        # Build normalized social record
        now_iso = os.popen("date -u +'%Y-%m-%dT%H:%M:%SZ'").read().strip()
        record = NormalizedSocialRecord(
            record_id=f"instagram:{shortcode}",
            platform="instagram",
            content_type=post.content_type or "reel",
            source_url=reel_url,
            content_id=shortcode,
            published_at=post.created_at or now_iso,
            author=SocialAuthor(
                username=post.author.username if post.author else None,
                profile_url=f"https://www.instagram.com/{post.author.username}/" if post.author and post.author.username else None,
            ),
            content=SocialContent(
                caption=reel_caption,
                text=reel_caption,
            ),
            engagement=SocialEngagement(
                likes=post.like_count,
                comments=len(raw_comments),
                views=post.view_count,
            ),
            interactions=interactions_for_record,
            metadata=ProvenanceMetadata(
                source_platform="instagram",
                source_provider="apify",
                backend_tool="instagram-comment-scraper",
                fetched_at=now_iso,
                source_url=reel_url,
            ),
        )
        normalized_records.append(record)

    # 3. Persist to SQLite with automatic deduplication
    if normalized_records:
        try:
            save_social_records(normalized_records)
        except Exception as e:
            logger.warning("Failed to persist to SQLite: %s", e)

    valid_reels_count = len([p for p in discovered_posts if "/explore/tags/" not in p.url])
    summary_msg = (
        f"Searched Instagram for '{display_topic}' (tag #{search_tag}). "
        f"Discovered {valid_reels_count} reel(s) and extracted {len(extracted_comments)} "
        f"public commenter user handle(s) and their exact comments."
    )

    return JSONResponse({
        "status": "success",
        "query": user_query,
        "topic": display_topic,
        "search_tag": search_tag,
        "summary_message": summary_msg,
        "reels_analyzed": valid_reels_count,
        "comments": extracted_comments,
    })


async def history_endpoint(request: Request):
    """Retrieve historical stored comments and commenters across all topics."""
    records = get_social_records(platform="instagram", limit=50)
    comments = []
    for r in records:
        for i in r.interactions:
            comments.append({
                "user_handle": i.author.username,
                "user_id": i.author.user_id,
                "comment_text": i.text,
                "category": dynamic_comment_intent(i.text, topic=r.platform),
                "likes": i.likes or 0,
                "created_at": i.created_at,
                "post_url": r.source_url,
            })
    return JSONResponse({
        "status": "success",
        "total": len(comments),
        "comments": comments,
        "stats": get_social_stats(),
    })


# Starlette app configuration
routes = [
    Route("/", endpoint=index, methods=["GET"]),
    Route("/api/chat", endpoint=chat_endpoint, methods=["POST"]),
    Route("/api/history", endpoint=history_endpoint, methods=["GET"]),
    Mount("/static", app=StaticFiles(directory=STATIC_DIR), name="static"),
]

middleware = [
    Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]),
]

app = Starlette(routes=routes, middleware=middleware)

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    print(f"\n=======================================================")
    print(f"🚀 Universal Social Intelligence Chatbot running at: http://localhost:{port}")
    print(f"=======================================================\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
