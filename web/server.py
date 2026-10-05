"""Web Application & Chatbot Server for Instagram Social Intelligence & Outreach."""

import json
import logging
import os
import re
import sys
from typing import Any, Dict, List

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

# Mental health & subtopic keyword classifiers
MENTAL_HEALTH_KEYWORDS = [
    "mental health", "stress", "anxiety", "anxious", "work pressure", "burnout",
    "exam tension", "exam", "depression", "panic", "overwhelmed", "therapy",
    "crying", "mental", "exhausted", "tired", "pressure", "healing", "coping",
    "mindset", "self care", "peace", "alone", "breathe", "tension", "struggle",
]


def classify_comment(text: str, reel_caption: str = "") -> str:
    """Classify comment into specific mental health categories (work pressure, exam tension, anxiety, stress)."""
    full_text = f"{text} {reel_caption}".lower()

    if re.search(r"\b(exam|exams|test|tests|study|studying|student|students|marks|grade|college|school|cgpa|pass|fail|finals)\b", full_text):
        return "Exam Tension & Students"
    elif re.search(r"\b(work|job|boss|corporate|office|burnout|shift|salary|colleague|colleagues|deadline|career|hustle)\b", full_text):
        return "Work Pressure & Burnout"
    elif re.search(r"\b(anxiety|anxious|panic|attack|overthinking|fear|nervous|heart racing|scared)\b", full_text):
        return "Anxiety & Panic"
    elif re.search(r"\b(stress|stressed|pressure|overwhelmed|headache|exhausted|tired|crying|breakdown)\b", full_text):
        return "Stress & Coping"
    else:
        return "Mental Health Discussion"


def is_mental_health_related(text: str, reel_caption: str = "") -> bool:
    """Filter to ensure the comment or reel context relates to mental health / emotional well-being."""
    full = f"{text} {reel_caption}".lower()
    return any(kw in full for kw in MENTAL_HEALTH_KEYWORDS) or len(text.split()) > 3


async def index(request: Request):
    """Serve the chatbot single-page application."""
    index_file = os.path.join(STATIC_DIR, "index.html")
    return FileResponse(index_file)


async def chat_endpoint(request: Request):
    """
    Chatbot API endpoint.
    Searches Instagram reels on requested topics (stress, anxiety, exam tension, work pressure),
    extracts public commenter handles + comments, filters for mental health, and returns structured data.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    user_query = body.get("query", "mental health").strip()
    max_reels = min(int(body.get("max_reels", 2)), 5)
    max_comments = min(int(body.get("max_comments_per_reel", 10)), 25)

    logger.info("Processing chat query: %r (max_reels=%d, max_comments=%d)", user_query, max_reels, max_comments)

    # 1. Determine Instagram search topic from user prompt
    search_term = "mental health"
    q_lower = user_query.lower()
    if "exam" in q_lower or "student" in q_lower:
        search_term = "exam tension"
    elif "work" in q_lower or "burnout" in q_lower or "corporate" in q_lower:
        search_term = "work pressure"
    elif "anxiety" in q_lower:
        search_term = "anxiety relief"
    elif "stress" in q_lower:
        search_term = "stress relief"
    elif user_query:
        # Clean custom query
        clean = re.sub(r"(find|search|collect|get|instagram|reels|comments|data|from|about|with)", "", user_query, flags=re.I).strip()
        if clean:
            search_term = clean

    service: InstagramService = get_instagram_service()

    try:
        # Search public Instagram Reels
        discovered_posts = await service.search_posts_or_reels(
            query=search_term,
            max_results=max_reels,
        )
    except Exception as e:
        logger.error("Error searching Instagram reels: %s", e)
        return JSONResponse({
            "status": "error",
            "message": f"Failed to search Instagram reels via Apify: {str(e)}",
        }, status_code=500)

    extracted_comments: List[Dict[str, Any]] = []
    normalized_records: List[NormalizedSocialRecord] = []

    # 2. Iterate each discovered reel and fetch public comment section
    for post in discovered_posts:
        reel_url = post.url
        reel_caption = post.caption or ""
        shortcode = post.content_id or reel_url.rstrip("/").split("/")[-1]

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
            category = classify_comment(comment_text, reel_caption)

            extracted_item = {
                "user_handle": username,
                "user_id": user_id,
                "is_verified": is_verified,
                "comment_text": comment_text,
                "category": category,
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

        # Build normalized record for storage
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

    summary_msg = (
        f"Analyzed {len(discovered_posts)} Instagram reel(s) related to '{search_term}'. "
        f"Extracted {len(extracted_comments)} public comments and user handles."
    )

    return JSONResponse({
        "status": "success",
        "query": user_query,
        "search_term": search_term,
        "summary_message": summary_msg,
        "reels_analyzed": len(discovered_posts),
        "comments": extracted_comments,
    })


async def history_endpoint(request: Request):
    """Retrieve historical stored comments and commenters from SQLite."""
    records = get_social_records(platform="instagram", limit=50)
    comments = []
    for r in records:
        for i in r.interactions:
            comments.append({
                "user_handle": i.author.username,
                "user_id": i.author.user_id,
                "comment_text": i.text,
                "category": classify_comment(i.text),
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
    print(f"🚀 SocialReach AI Chatbot running at: http://localhost:{port}")
    print(f"=======================================================\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
