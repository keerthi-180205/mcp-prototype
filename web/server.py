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

import asyncio
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
from server.collection.jobs import CollectionJobManager, JobError
from server.collection.export import export_job
from server.chat.assistant import handle_assistant_message, get_platforms_availability

load_dotenv()
logger = logging.getLogger("mcp_server.web")
logging.basicConfig(level=logging.INFO)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def extract_topic_from_prompt(user_query: str) -> Tuple[str, str, str]:
    """
    Extract the clean target subject/topic, hashtag search key, and target platform from a natural language prompt.
    Completely dynamic without any hardcoded topic assumptions.
    Returns: (display_topic, search_tag, platform)
    """
    q = (user_query or "").strip()
    if not q:
        return "Trending", "trending", "all"

    q_lower = q.lower()
    platform = "all"
    if "youtube" in q_lower:
        platform = "youtube"
    elif "instagram" in q_lower:
        platform = "instagram"
    elif "reddit" in q_lower:
        platform = "reddit"
    elif "linkedin" in q_lower:
        platform = "linkedin"
    elif "twitter" in q_lower or " x " in q_lower:
        platform = "twitter"

    # Generic extraction: remove conversational stopwords
    stop_words = {
        "i", "want", "data", "from", "on", "about", "instagram", "reels", "reel",
        "posts", "post", "comments", "comment", "find", "search", "the", "a", "an",
        "who", "commented", "what", "they", "said", "and", "for", "get", "collect",
        "show", "me", "look", "fetch", "extract", "public", "user", "users", "ids",
        "handles", "recent", "youtube", "yt", "video", "videos", "tell", "give", "please",
        "info", "information", "trending", "most", "like", "in", "any", "social", "media"
    }
    tokens = [w for w in re.findall(r"[A-Za-z0-9]+", q_lower) if w not in stop_words]

    if not tokens:
        tokens = [w for w in re.findall(r"[A-Za-z0-9]+", q_lower)]

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
    dist_file = os.path.join(WORKSPACE_ROOT, "web_ui", "dist", "index.html")
    if os.path.exists(dist_file):
        return FileResponse(dist_file)
    index_file = os.path.join(STATIC_DIR, "index.html")
    return FileResponse(index_file)


async def fetch_platform_comments(provider, p_name: str, query: str, top_content: int, top_comments: int):
    """Fetch top trending posts/videos and their public comments for a specific provider."""
    try:
        display_name = {
            "youtube": "YouTube",
            "reddit": "Reddit",
            "x": "Twitter / X",
            "twitter": "Twitter / X",
            "instagram": "Instagram",
        }.get(p_name.lower(), p_name.capitalize())

        records = await asyncio.wait_for(provider.search_content(query, limit=top_content), timeout=25.0)
        if not records:
            return []

        collected = []
        for rec in records[:top_content]:
            post_url = rec.source_url or (f"https://www.youtube.com/watch?v={rec.content_id}" if p_name == "youtube" else "")
            try:
                comments = await asyncio.wait_for(
                    provider.get_comments(rec.source_url or rec.content_id, limit=min(50, top_comments)),
                    timeout=15.0
                )
                for c in comments:
                    c_text = (c.text or "").strip()
                    if not c_text:
                        continue
                    author_name = (c.author.username or c.author.display_name or "anonymous").strip()
                    if p_name == "youtube":
                        clean_u = author_name.lstrip("@")
                        formatted_user = f"@{clean_u}"
                    elif p_name == "reddit":
                        clean_u = author_name.replace("u/", "")
                        formatted_user = f"u/{clean_u}"
                    elif p_name in ["x", "twitter", "instagram"]:
                        clean_u = author_name.lstrip("@")
                        formatted_user = f"@{clean_u}"
                    else:
                        formatted_user = author_name

                    category = dynamic_comment_intent(c_text, query)

                    collected.append({
                        "user_id": formatted_user,
                        "username": formatted_user,
                        "comment": c_text,
                        "comment_text": c_text,
                        "platform": display_name,
                        "link": post_url,
                        "post_url": post_url,
                        "likes": c.likes or 0,
                        "category": category,
                        "created_at": c.created_at or "Recent",
                    })
            except Exception as c_err:
                logger.warning("Error fetching comments for %s on %s: %s", rec.content_id, p_name, c_err)
        return collected
    except Exception as e:
        logger.warning("Failed fetching from platform %s: %s", p_name, e)
        return []


async def platforms_status_endpoint(request: Request):
    """Retrieve platform connection status (Instagram, LinkedIn, YouTube, etc.)."""
    from server.services.profile_discovery import get_platform_statuses
    return JSONResponse({"status": "success", "platforms": get_platform_statuses()})


async def platforms_connect_endpoint(request: Request):
    """Connect or disconnect a platform."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    platform = body.get("platform", "")
    connected = bool(body.get("connected", True))
    account = body.get("account")
    from server.services.profile_discovery import update_platform_connection
    try:
        updated = update_platform_connection(platform, connected, account)
        return JSONResponse({"status": "success", "platform": updated})
    except Exception as e:
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)


async def chat_endpoint(request: Request):
    """
    Universal Chatbot & Multi-Platform endpoint.
    1. Reads user field & description.
    2. Explores connected platforms (Instagram, LinkedIn, YouTube, Reddit).
    3. Finds media (reels, posts, videos) and scrapes creator profiles.
    4. Filters and ranks profiles using Agent Reach semantic matching (WITHOUT Gemini API).
    """
    try:
        body = await request.json()
    except Exception:
        body = {}

    user_query = body.get("query", "").strip()
    field = body.get("field", "").strip()
    description = body.get("description", "").strip() or user_query
    platform = body.get("platform", "").strip().lower()
    media_types = body.get("media_types", ["reels", "posts", "videos"])
    connected_platforms = body.get("connected_platforms", [])

    if not description and not user_query and not field:
        return JSONResponse({"status": "error", "message": "Please provide a description or topic field."}, status_code=400)

    top_content = int(body.get("max_reels") or body.get("top_content") or 4)
    top_comments = int(body.get("max_comments_per_reel") or body.get("top_comments") or 100)

    logger.info("Chat discovery request: field=%r, desc=%r, connected=%r", field, description, connected_platforms)

    # 1. Run Agent Reach Profile Discovery & Semantic Matching
    from server.services.profile_discovery import discover_and_filter_profiles
    profile_results = await discover_and_filter_profiles(
        field=field,
        description=description,
        media_types=media_types,
        connected_platforms=connected_platforms,
    )

    # 2. Extract clean search keyword for social comments crawler (optional or fast)
    clean_display, clean_keyword, _ = extract_topic_from_prompt(description or user_query)

    from server.providers.social.registry import get_social_registry
    registry = get_social_registry()

    # Fast YouTube comments via Agent Reach (runs in <2s)
    final_comments = []
    try:
        from server.providers.social.youtube import YouTubeSocialProvider
        yt = YouTubeSocialProvider()
        yt_records = await asyncio.wait_for(yt.search_content(clean_keyword or clean_display, limit=2), timeout=4.0)
        for rec in yt_records:
            try:
                c_list = await asyncio.wait_for(yt.get_comments(rec.content_id, limit=10), timeout=3.0)
                for c in c_list:
                    if c.text:
                        final_comments.append({
                            "user_id": f"@{c.author.username.lstrip('@')}" if c.author.username else "anonymous",
                            "username": c.author.username,
                            "comment": c.text,
                            "platform": "YouTube",
                            "link": rec.source_url or f"https://www.youtube.com/watch?v={rec.content_id}",
                            "likes": c.likes or 0,
                            "category": "Community Feedback",
                        })
            except Exception:
                pass
    except Exception as yt_err:
        logger.debug("Fast comment gathering skipped: %s", yt_err)

    reached_platforms = set(profile_results.get("platforms_searched", []))
    reached_names = list(reached_platforms) or ["Instagram", "LinkedIn", "YouTube"]
    reached_str = ", ".join(reached_names)
    total_valid = len(final_comments)

    msg = f"Reached {reached_str}. Extracted {total_valid} top trending comments for '{user_query}'."

    return JSONResponse({
        "status": "success",
        "query": user_query or description,
        "topic": profile_results.get("field", user_query.title() if user_query else "Social Intelligence"),
        "field": profile_results.get("field"),
        "description": profile_results.get("description"),
        "platform": reached_str,
        "platforms_reached": reached_names,
        "chatbot_message": profile_results.get("chatbot_message", msg),
        "summary_message": profile_results.get("chatbot_message", msg),
        "matched_profiles": profile_results.get("matched_profiles", []),
        "matched_comments": profile_results.get("matched_comments", profile_results.get("matched_profiles", [])),
        "total_scraped": profile_results.get("total_scraped", 0),
        "total_matched": profile_results.get("total_matched", 0),
        "personas": profile_results.get("personas", []),
        "criteria": profile_results.get("criteria", []),
        "comments": profile_results.get("matched_comments") or final_comments,
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


async def search_topic_endpoint(request: Request):
    """Direct API endpoint for search_social_topic tool."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    query = body.get("query", "").strip()
    platform = body.get("platform", "instagram")
    top_n = int(body.get("top_n", 20))
    comments_per_content = int(body.get("comments_per_content", 20))
    date_from = body.get("date_from")
    date_to = body.get("date_to")
    days_back = int(body["days_back"]) if "days_back" in body and body["days_back"] is not None else None

    from server.services.social_intelligence import get_social_intelligence_service
    srv = get_social_intelligence_service()
    res = await srv.search_social_topic(
        query=query,
        platform=platform,
        top_n=top_n,
        comments_per_content=comments_per_content,
        date_from=date_from,
        date_to=date_to,
        days_back=days_back,
    )
    return JSONResponse(res)


# ---------------------------------------------------------------------------
# Comment Collection REST API & Assistant Chat Endpoint
# ---------------------------------------------------------------------------

collection_manager = CollectionJobManager()


def _get_manager(request: Request) -> CollectionJobManager:
    return getattr(request.app.state, "collection_manager", collection_manager)


async def collect_platforms_endpoint(request: Request):
    """Retrieve platform availability booleans and reasons. Never returns secrets."""
    return JSONResponse(get_platforms_availability())


async def collect_start_endpoint(request: Request):
    """Start an async background comment collection job."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    topic = body.get("topic", "")
    platforms = body.get("platforms")
    target_comments = int(body.get("target_comments", body.get("target_comments_per_platform", 500)))
    max_posts = int(body.get("max_posts", body.get("max_posts_per_platform", 30)))
    max_minutes = float(body.get("max_minutes", 10.0))

    mgr = _get_manager(request)
    try:
        res = mgr.start(
            topic=topic,
            platforms=platforms,
            target_comments=target_comments,
            max_posts=max_posts,
            max_minutes=max_minutes,
        )
        return JSONResponse(res)
    except JobError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


async def collect_status_endpoint(request: Request):
    """Progress of a comment collection job: per-platform status, posts, comments."""
    job_id = request.path_params["job_id"]
    mgr = _get_manager(request)
    try:
        res = mgr.status(job_id)
        return JSONResponse(res)
    except JobError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


async def collect_results_endpoint(request: Request):
    """Summary plus paginated collected comment rows."""
    job_id = request.path_params["job_id"]
    try:
        page = int(request.query_params.get("page", 1))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = int(request.query_params.get("page_size", 25))
    except (ValueError, TypeError):
        page_size = 25
    platform = request.query_params.get("platform")

    mgr = _get_manager(request)
    try:
        res = mgr.results(job_id, page=page, page_size=page_size, platform=platform)
        return JSONResponse(res)
    except JobError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)


async def collect_export_endpoint(request: Request):
    """Export collected comments as a downloadable file attachment (CSV or JSON)."""
    job_id = request.path_params["job_id"]
    fmt = request.query_params.get("format", "csv").lower().strip()
    if fmt not in ("csv", "json"):
        return JSONResponse({"status": "error", "message": "format must be 'csv' or 'json'"}, status_code=400)

    mgr = _get_manager(request)
    try:
        mgr.status(job_id)  # Validate job exists
        res = export_job(job_id, fmt=fmt, db_path=mgr.db_path)
        file_path = str(res["path"])
        filename = f"{job_id}.{fmt}"
        media_type = "text/csv; charset=utf-8" if fmt == "csv" else "application/json"
        return FileResponse(
            path=file_path,
            media_type=media_type,
            filename=filename,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except JobError as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=404)
    except Exception as exc:
        return JSONResponse({"status": "error", "message": str(exc)}, status_code=400)


async def assistant_message_endpoint(request: Request):
    """Conversational comment collection assistant endpoint."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    session_id = body.get("session_id", "").strip()
    text = body.get("text", "")
    action = body.get("action")

    mgr = _get_manager(request)
    res = await handle_assistant_message(
        session_id=session_id,
        text=text,
        action=action,
        manager=mgr,
    )
    return JSONResponse(res)


# Starlette app configuration
routes = [
    Route("/", endpoint=index, methods=["GET"]),
    Route("/api/collect/platforms", endpoint=collect_platforms_endpoint, methods=["GET"]),
    Route("/api/collect/start", endpoint=collect_start_endpoint, methods=["POST"]),
    Route("/api/collect/{job_id}/status", endpoint=collect_status_endpoint, methods=["GET"]),
    Route("/api/collect/{job_id}/results", endpoint=collect_results_endpoint, methods=["GET"]),
    Route("/api/collect/{job_id}/export", endpoint=collect_export_endpoint, methods=["GET"]),
    Route("/api/assistant/message", endpoint=assistant_message_endpoint, methods=["POST"]),
    Route("/api/chat", endpoint=chat_endpoint, methods=["POST"]),
    Route("/api/platforms/status", endpoint=platforms_status_endpoint, methods=["GET"]),
    Route("/api/platforms/connect", endpoint=platforms_connect_endpoint, methods=["POST"]),
    Route("/api/history", endpoint=history_endpoint, methods=["GET"]),
    Route("/api/search_topic", endpoint=search_topic_endpoint, methods=["POST"]),
    Mount("/static", app=StaticFiles(directory=STATIC_DIR), name="static"),
]

dist_assets_dir = os.path.join(WORKSPACE_ROOT, "web_ui", "dist", "assets")
if os.path.isdir(dist_assets_dir):
    routes.append(Mount("/assets", app=StaticFiles(directory=dist_assets_dir), name="assets"))

# Explicit CORS origins
cors_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]
extra_cors = os.getenv("CORS_ORIGINS", "")
if extra_cors:
    for origin in extra_cors.split(","):
        cleaned = origin.strip()
        if cleaned and cleaned not in cors_origins:
            cors_origins.append(cleaned)

middleware = [
    Middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["*"], allow_headers=["*"]),
]

app = Starlette(routes=routes, middleware=middleware)

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", 8080))
    print(f"\n=======================================================")
    print(f"🚀 Universal Social Intelligence Chatbot running at: http://{host}:{port}")
    print(f"=======================================================\n")
    uvicorn.run(app, host=host, port=port)
