"""Conversation layer assistant for comment-collection chat interface.

Provides:
1. Session management with TTL and rate limiting.
2. Rule-based intent & slot parser with Gemini LLM fallback.
3. Server-side confirmation gatekeeper for collection jobs.
4. Explanations for stop reasons and platform availability.
5. Untrusted comment safety (never passed as LLM instructions).
"""

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from server.collection.cli import find_binary
from server.collection.collectors.reddit import credential_path
from server.collection.jobs import CollectionJobManager, JobError
from server.collection.models import (
    CollectionLimits,
    SUPPORTED_PLATFORMS,
    STOP_BUDGET,
    STOP_ERROR,
    STOP_MAX_POSTS,
    STOP_MAX_TIME,
    STOP_NO_MORE,
    STOP_TARGET,
    STOP_UNAVAILABLE,
)
from server.collection.export import export_job
from server.config import get_settings

logger = logging.getLogger("mcp_server.chat.assistant")

SESSION_TTL_SECONDS = 3600.0  # 1 hour
MAX_REQUESTS_PER_MINUTE = 30


# ---------------------------------------------------------------------------
# Platform Availability Helper
# ---------------------------------------------------------------------------

def get_platforms_availability() -> Dict[str, Dict[str, Any]]:
    """Query available platforms and reason. Returns booleans and reasons only, NEVER secrets.
    Availability:
      youtube = yt-dlp installed
      reddit = REDDIT_SESSION set or rdt-cli credential file present
      x = TWITTER_AUTH_TOKEN and TWITTER_CT0 set
      instagram = APIFY_API_TOKEN set
    """
    out: Dict[str, Dict[str, Any]] = {}

    # YouTube: yt-dlp installed
    yt_installed = bool(find_binary("yt-dlp"))
    out["youtube"] = {
        "available": yt_installed,
        "reason": "yt-dlp is installed and ready" if yt_installed else "yt-dlp is not installed (pip install yt-dlp)",
    }

    # Reddit: REDDIT_SESSION set or rdt-cli credential file present
    has_reddit_cred = bool(os.getenv("REDDIT_SESSION")) or credential_path().exists()
    out["reddit"] = {
        "available": has_reddit_cred,
        "reason": "Reddit session credentials found" if has_reddit_cred else "REDDIT_SESSION is not set or rdt credential file missing",
    }

    # X: TWITTER_AUTH_TOKEN and TWITTER_CT0 set
    has_tw = bool(os.getenv("TWITTER_AUTH_TOKEN")) and bool(os.getenv("TWITTER_CT0"))
    out["x"] = {
        "available": has_tw,
        "reason": "Twitter/X session tokens configured" if has_tw else "TWITTER_AUTH_TOKEN and TWITTER_CT0 must both be set",
    }

    # Instagram: APIFY_API_TOKEN set
    has_apify = bool(os.getenv("APIFY_API_TOKEN"))
    out["instagram"] = {
        "available": has_apify,
        "reason": "Apify token configured (billed per run)" if has_apify else "APIFY_API_TOKEN is not set",
    }

    return out


# ---------------------------------------------------------------------------
# Stop reason explanations
# ---------------------------------------------------------------------------

STOP_REASON_EXPLANATIONS = {
    STOP_TARGET: "Reached the target number of comments.",
    STOP_NO_MORE: "Ran out of matching posts before reaching the target.",
    STOP_BUDGET: "Reached the Apify safety cap (item or cost limit) configured to protect your account credits.",
    STOP_MAX_POSTS: "Processed the maximum allowed posts for this platform.",
    STOP_MAX_TIME: "Reached the maximum time limit for collection.",
    STOP_UNAVAILABLE: "Platform is unavailable or credentials are missing.",
    STOP_ERROR: "An error occurred during collection.",
}


# ---------------------------------------------------------------------------
# Parser Data Models
# ---------------------------------------------------------------------------

class ParsedIntent(BaseModel):
    intent: str  # start_collection | confirm | cancel_plan | status | show_results | export | explain | platforms | help | unknown
    topic: Optional[str] = None
    platforms: Optional[List[str]] = None
    target: Optional[int] = None
    max_minutes: Optional[float] = None
    max_posts: Optional[int] = None
    page: Optional[int] = None
    platform_filter: Optional[str] = None
    format: Optional[str] = None  # csv | json
    explanation_target: Optional[str] = None


# ---------------------------------------------------------------------------
# Rule-based Parser (Always active as fallback)
# ---------------------------------------------------------------------------

_PLATFORM_ALIASES = {
    "youtube": "youtube",
    "yt": "youtube",
    "reddit": "reddit",
    "subreddit": "reddit",
    "subreddits": "reddit",
    "x": "x",
    "twitter": "x",
    "tweet": "x",
    "tweets": "x",
    "instagram": "instagram",
    "insta": "instagram",
    "ig": "instagram",
}

_WORD_NUMBERS = {
    "a hundred": 100,
    "one hundred": 100,
    "two hundred": 200,
    "three hundred": 300,
    "four hundred": 400,
    "five hundred": 500,
    "six hundred": 600,
    "seven hundred": 700,
    "eight hundred": 800,
    "nine hundred": 900,
    "a thousand": 1000,
    "one thousand": 1000,
    "two thousand": 2000,
    "three thousand": 3000,
    "four thousand": 4000,
    "five thousand": 5000,
}


def _extract_number(text: str) -> Optional[int]:
    """Extract comment target numbers like '500', '1k', '2.5k', 'a thousand'."""
    lower = text.lower()
    for phrase, val in _WORD_NUMBERS.items():
        if re.search(r"\b" + re.escape(phrase) + r"\b", lower):
            return val

    # Match '1.5k' or '2k'
    k_match = re.search(r"\b(\d+(?:\.\d+)?)\s*[kK]\b", text)
    if k_match:
        try:
            return int(float(k_match.group(1)) * 1000)
        except ValueError:
            pass

    # Match plain digits: 500 comments, 250, etc.
    digit_match = re.search(r"\b(\d{1,5})\b", text)
    if digit_match:
        try:
            val = int(digit_match.group(1))
            # Don't mistake a year (e.g. 2026) for comment count if preceded by 'year' or part of topic
            if val in (2024, 2025, 2026, 2027, 2028, 2030):
                # Check if it has 'comments' or 'rows' immediately after
                post_text = text[digit_match.end():digit_match.end() + 15].lower()
                if not re.search(r"^\s*(comments?|rows?|items?)", post_text):
                    # Check next match
                    sub = text[digit_match.end():]
                    next_m = re.search(r"\b(\d{1,5})\b", sub)
                    if next_m:
                        return int(next_m.group(1))
                    return None
            return val
        except ValueError:
            pass
    return None


def _extract_platforms(text: str) -> Optional[List[str]]:
    """Extract mentioned platforms from text using aliases."""
    found: List[str] = []
    # Tokenize words
    words = re.findall(r"[a-zA-Z0-9]+", text.lower())
    for w in words:
        if w in _PLATFORM_ALIASES:
            canon = _PLATFORM_ALIASES[w]
            if canon not in found:
                found.append(canon)
    return found if found else None


_PLATFORM_TERMS_RE = r"(?:youtube|yt|reddit|subreddit|subreddits|x|twitter|tweet|tweets|instagram|insta|ig)"


def _extract_topic(text: str) -> Optional[str]:
    """Extract the search topic from phrases like 'about Asian Games 2026', 'on AI agents'."""
    # Pattern 1: about/on/regarding/for/discussing <topic>
    pat1 = re.search(
        r"\b(?:about|on|regarding|discussing|topic|for)\s+([\"']?[a-zA-Z0-9\s\-_.:&]{2,60}[\"']?)",
        text,
        re.IGNORECASE,
    )
    if pat1:
        candidate = pat1.group(1).strip(" \"'")
        # Strip trailing platform clauses: "from youtube", "on reddit", "from yt and subreddit", "from tweets"
        plat_clause = r"\s+(?:from|across|in|on)\s+" + _PLATFORM_TERMS_RE + r"(?:\s+(?:and|&|,)\s+" + _PLATFORM_TERMS_RE + r")*\s*$"
        candidate = re.sub(plat_clause, "", candidate, flags=re.IGNORECASE).strip()
        # Strip trailing words like 'comments', 'posts'
        candidate = re.sub(r"\s+(?:comments?|posts?|videos?|threads?)\s*$", "", candidate, flags=re.IGNORECASE).strip()
        candidate = re.sub(plat_clause, "", candidate, flags=re.IGNORECASE).strip()
        if candidate and candidate.lower() not in _PLATFORM_ALIASES:
            return candidate

    # Pattern 2: "get me 500 <topic> comments from youtube"
    pat2 = re.search(
        r"(?:get|collect|find|scrape|fetch)\s+(?:me\s+)?(?:\d+(?:\.\d+)?[kK]?\s+)?([a-zA-Z0-9\s\-_.:&]{2,50})\s+(?:comments?|commenters?)\s+(?:from|on)",
        text,
        re.IGNORECASE,
    )
    if pat2:
        candidate = pat2.group(1).strip(" \"'")
        if candidate:
            return candidate

    return None


def parse_with_rules(text: str, action: Optional[str] = None, session: Optional[Any] = None) -> ParsedIntent:
    """Deterministic rules parser. Always runs when LLM is unavailable or fails."""
    t_clean = (text or "").strip()
    lower = t_clean.lower()
    action_clean = (action or "").strip().lower()

    # 1. Direct Actions or Confirmation
    if action_clean == "confirm" or re.fullmatch(r"(yes|confirm|start|proceed|go ahead|yep|sure|ok|okay|do it|please start|start collection)", lower):
        return ParsedIntent(intent="confirm")

    if action_clean == "cancel" or re.fullmatch(r"(cancel|no|stop|abort|nevermind|cancel plan|don't start|no thanks)", lower):
        return ParsedIntent(intent="cancel_plan")

    # 2. Export
    if action_clean.startswith("export") or re.search(r"\b(export|download)\b", lower):
        fmt = "json" if "json" in lower else "csv"
        return ParsedIntent(intent="export", format=fmt)

    # 3. Status queries
    if re.search(r"\b(what'?s the status|status|how is it going|is it done|check status|what is the progress|job status|progress)\b", lower):
        return ParsedIntent(intent="status")

    # 4. Explanations (e.g. "why is instagram so low?", "why below target?")
    if re.search(r"\b(why\s+(?:is\s+)?(?:instagram|ig|insta|reddit|youtube|x|twitter)?\s*(?:so\s+)?(?:low|few|below)|why\s+did\s+it\s+stop|what\s+does\s+(?:no_more_candidates|budget_cap_reached|stop_reason)\s+mean|explain\s+(?:stop\s+reason|why|results))\b", lower):
        target_plat = None
        for p in ("instagram", "reddit", "youtube", "x", "twitter"):
            if p in lower:
                target_plat = "x" if p == "twitter" else ("instagram" if p in ("insta", "ig") else p)
                break
        return ParsedIntent(intent="explain", explanation_target=target_plat)

    # 5. Platforms availability
    if re.search(r"\b(what\s+platforms|which\s+platforms|available\s+platforms|supported\s+platforms|platform\s+status|platforms)\b", lower):
        return ParsedIntent(intent="platforms")

    # 6. Help
    if re.fullmatch(r"(help|commands|how does this work|what can you do|\?)", lower):
        return ParsedIntent(intent="help")

    # 7. Show results / filters / pagination
    page_match = re.search(r"\bpage\s+(\d+)\b", lower)
    if page_match:
        return ParsedIntent(intent="show_results", page=int(page_match.group(1)))
    if re.search(r"\bnext\s+page\b", lower):
        curr_page = getattr(session, "last_results_view", {}).get("page", 1) if session else 1
        return ParsedIntent(intent="show_results", page=curr_page + 1)
    if re.search(r"\b(?:previous|prev)\s+page\b", lower):
        curr_page = getattr(session, "last_results_view", {}).get("page", 1) if session else 1
        return ParsedIntent(intent="show_results", page=max(1, curr_page - 1))

    # Single-platform filter queries: "only reddit", "show only youtube", "filter by x"
    filter_match = re.search(r"\b(?:only|just|filter\s+by|show\s+only)\s+(youtube|yt|reddit|x|twitter|instagram|insta|ig)\b", lower)
    if filter_match:
        plat_key = _PLATFORM_ALIASES.get(filter_match.group(1), filter_match.group(1))
        return ParsedIntent(intent="show_results", platform_filter=plat_key)

    if re.fullmatch(r"(show results|view results|results|show comments|see comments)", lower):
        return ParsedIntent(intent="show_results")

    # 8. Start Collection Request
    # Detect collection intention: verbs or mentions of comments/topics
    has_collect_verbs = bool(re.search(r"\b(get|collect|find|scrape|fetch|gather|search|harvest|extract|pull|retrieve|need|want)\b", lower))
    has_comment_term = bool(re.search(r"\b(comments?|commenters?)\b", lower))
    has_topic_marker = bool(re.search(r"\b(about|regarding|discussing)\b", lower))

    if has_collect_verbs or has_comment_term or has_topic_marker:
        topic = _extract_topic(t_clean)
        target = _extract_number(t_clean) or 500
        platforms = _extract_platforms(t_clean)
        return ParsedIntent(
            intent="start_collection",
            topic=topic,
            platforms=platforms,
            target=target,
            max_minutes=10.0,
            max_posts=30,
        )

    # 9. Fallback: unknown / nonsense input
    return ParsedIntent(intent="unknown")


# ---------------------------------------------------------------------------
# LLM Parser (Gemini augmentation with Pydantic validation)
# ---------------------------------------------------------------------------

async def parse_intent_with_llm(text: str, settings=None, client=None) -> Optional[ParsedIntent]:
    """Parse text using Gemini LLM if GEMINI_API_KEY is configured. Never crashes on error."""
    settings = settings or get_settings()
    api_key = getattr(settings, "gemini_api_key", None)
    if not api_key:
        return None

    model = getattr(settings, "gemini_model", "gemini-2.5-flash")

    prompt = (
        "You are an NLP intent and slot parser for a social media comment-collection assistant.\n"
        "Given the user message, output ONLY valid JSON matching this schema:\n"
        "{\n"
        '  "intent": "start_collection" | "confirm" | "cancel_plan" | "status" | "show_results" | "export" | "explain" | "platforms" | "help" | "unknown",\n'
        '  "topic": string or null (the subject to collect comments about),\n'
        '  "platforms": list of strings (subset of ["youtube", "reddit", "x", "instagram"]) or null,\n'
        '  "target": integer or null (requested comments per platform),\n'
        '  "page": integer or null,\n'
        '  "platform_filter": string or null,\n'
        '  "format": "csv" | "json" or null\n'
        "}\n\n"
        f"User message: {text}\n"
        "JSON output:"
    )

    def _call() -> str:
        nonlocal client
        if client is None:
            from google import genai
            client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(model=model, contents=prompt)
        return resp.text or ""

    try:
        raw = await asyncio.wait_for(asyncio.to_thread(_call), timeout=6.0)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return None
        data = json.loads(match.group(0))
        # Validate through pydantic
        return ParsedIntent(**data)
    except Exception as exc:
        logger.debug("Gemini intent parser fallback to rules: %s", type(exc).__name__)
        return None


async def parse_intent(
    text: str,
    action: Optional[str] = None,
    session: Optional[Any] = None,
    settings=None,
    client=None,
) -> ParsedIntent:
    """Unified parser: runs LLM if available, falls back reliably to deterministic rules."""
    # Explicit buttons or quick actions bypass the LLM for maximum responsiveness and determinism
    if action or not text:
        return parse_with_rules(text, action=action, session=session)

    # Try LLM
    llm_parsed = await parse_intent_with_llm(text, settings=settings, client=client)
    if llm_parsed and llm_parsed.intent != "unknown":
        return llm_parsed

    # Fallback to rules
    return parse_with_rules(text, action=action, session=session)


# ---------------------------------------------------------------------------
# In-Memory Session Management
# ---------------------------------------------------------------------------

class Session:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.pending_plan: Optional[Dict[str, Any]] = None
        self.active_job_id: Optional[str] = None
        self.last_results_view: Dict[str, Any] = {"page": 1, "platform_filter": None}
        self.last_activity: float = time.time()
        self.request_timestamps: List[float] = []

    def check_rate_limit(self) -> bool:
        """Sliding window rate limit. Returns True if allowed, False if exceeded."""
        now = time.time()
        # Drop timestamps older than 60 seconds
        self.request_timestamps = [ts for ts in self.request_timestamps if now - ts < 60.0]
        if len(self.request_timestamps) >= MAX_REQUESTS_PER_MINUTE:
            return False
        self.request_timestamps.append(now)
        self.last_activity = now
        return True


class SessionStore:
    def __init__(self):
        self._sessions: Dict[str, Session] = {}

    def get_or_create(self, session_id: str) -> Session:
        now = time.time()
        # Prune expired sessions
        expired = [sid for sid, s in self._sessions.items() if now - s.last_activity > SESSION_TTL_SECONDS]
        for sid in expired:
            del self._sessions[sid]

        if session_id not in self._sessions:
            self._sessions[session_id] = Session(session_id)
        return self._sessions[session_id]


_GLOBAL_SESSIONS = SessionStore()
session_store = _GLOBAL_SESSIONS


# ---------------------------------------------------------------------------
# Assistant Orchestrator
# ---------------------------------------------------------------------------

async def handle_assistant_message(
    session_id: str,
    text: str,
    action: Optional[str] = None,
    collection_manager: Optional[CollectionJobManager] = None,
    manager: Optional[CollectionJobManager] = None,
    session_store: Optional[SessionStore] = None,
    settings=None,
    gemini_client=None,
) -> Dict[str, Any]:
    """
    Main handler for POST /api/assistant/message.
    Processes user input, enforces the confirmation gatekeeper, and returns messages, cards, and quick replies.
    """
    if collection_manager is None:
        collection_manager = manager
    if collection_manager is None:
        raise ValueError("collection_manager instance must be provided")

    store = session_store or _GLOBAL_SESSIONS
    session = store.get_or_create(session_id)

    # Rate limiting check
    if not session.check_rate_limit():
        return {
            "messages": [
                {
                    "role": "assistant",
                    "text": "Rate limit exceeded (max 30 requests/minute). Please wait a moment before sending another message.",
                }
            ],
            "cards": [],
            "quick_replies": ["Check status", "Help"],
        }

    parsed = await parse_intent(text, action=action, session=session, settings=settings, client=gemini_client)
    intent = parsed.intent
    logger.info("Session %s parsed intent: %s (slots: topic=%s, platforms=%s, target=%s)", session_id, intent, parsed.topic, parsed.platforms, parsed.target)

    # -----------------------------------------------------------------------
    # INTENT: Confirm Plan (Confirmation Gatekeeper)
    # -----------------------------------------------------------------------
    if intent == "confirm":
        if not session.pending_plan:
            return {
                "messages": [
                    {
                        "role": "assistant",
                        "text": "There is no pending collection plan to start. Tell me what topic you'd like to collect comments about!",
                    }
                ],
                "cards": [],
                "quick_replies": ["Get 500 comments about Asian Games 2026", "Available platforms", "Help"],
            }

        plan = session.pending_plan
        session.pending_plan = None  # Consume the plan

        try:
            job_info = collection_manager.start(
                topic=plan["topic"],
                platforms=plan["platforms"],
                target_comments=plan["target_comments"],
                max_posts=plan.get("max_posts", 30),
                max_minutes=plan.get("max_minutes", 10.0),
            )
            session.active_job_id = job_info["job_id"]
            init_status = collection_manager.status(job_info["job_id"])

            return {
                "messages": [
                    {
                        "role": "assistant",
                        "text": f"🚀 Collection started for '{plan['topic']}' across {', '.join(plan['platforms']).upper()}. Live progress is tracking below.",
                    }
                ],
                "cards": [
                    {
                        "type": "job",
                        "job_id": job_info["job_id"],
                        "topic": plan["topic"],
                        "status": init_status["status"],
                        "platforms": init_status["platforms"],
                        "total_comments": init_status["total_comments"],
                        "finished": init_status["finished"],
                        "summary": init_status["summary"],
                    }
                ],
                "quick_replies": ["Check status", "Export CSV", "New topic"],
            }
        except JobError as exc:
            return {
                "messages": [
                    {
                        "role": "assistant",
                        "text": f"Could not start collection: {exc}",
                    }
                ],
                "cards": [],
                "quick_replies": ["Try another topic", "Help"],
            }

    # -----------------------------------------------------------------------
    # INTENT: Cancel Plan
    # -----------------------------------------------------------------------
    if intent == "cancel_plan":
        if session.pending_plan:
            session.pending_plan = None
            return {
                "messages": [{"role": "assistant", "text": "Collection plan cancelled. What else would you like to explore?"}],
                "cards": [],
                "quick_replies": ["Available platforms", "New topic", "Help"],
            }
        return {
            "messages": [{"role": "assistant", "text": "No pending plan to cancel."}],
            "cards": [],
            "quick_replies": ["Get 500 comments about Asian Games 2026", "Help"],
        }

    # -----------------------------------------------------------------------
    # INTENT: Start Collection (Plan Preparation & Gatekeeper)
    # -----------------------------------------------------------------------
    if intent == "start_collection":
        # Required slot: Topic
        if not parsed.topic or not parsed.topic.strip():
            return {
                "messages": [
                    {
                        "role": "assistant",
                        "text": "What topic would you like to collect comments about? For example: 'Asian Games 2026', 'AI agents', or 'Cricket World Cup'.",
                    }
                ],
                "cards": [],
                "quick_replies": [
                    "Get 500 comments about Asian Games 2026",
                    "Collect comments on AI agents from YouTube and Reddit",
                    "Available platforms",
                ],
            }

        topic = parsed.topic.strip()
        avail = get_platforms_availability()

        # Target clamping
        raw_target = parsed.target or 500
        clamped_target = max(1, min(raw_target, 5000))
        target_note = None
        if raw_target > 5000:
            target_note = f"Note: Target clamped from {raw_target} down to maximum allowed 5,000 comments per platform."
        elif raw_target < 1:
            target_note = "Note: Target clamped to minimum of 1 comment."

        # Platform resolution
        warnings: List[str] = []
        if target_note:
            warnings.append(target_note)

        chosen_platforms: List[str] = []
        unavailable_requested: List[Dict[str, str]] = []

        if parsed.platforms:
            # User named specific platforms
            for p in parsed.platforms:
                p_norm = p.lower().strip()
                if p_norm in avail:
                    if avail[p_norm]["available"]:
                        chosen_platforms.append(p_norm)
                    else:
                        unavailable_requested.append({"platform": p_norm, "reason": avail[p_norm]["reason"]})
        else:
            # Default: every AVAILABLE platform EXCEPT instagram
            for p in ("youtube", "reddit", "x"):
                if avail.get(p, {}).get("available"):
                    chosen_platforms.append(p)

        # Handle unavailable platform requests
        if unavailable_requested:
            for item in unavailable_requested:
                warnings.append(f"⚠️ {item['platform'].upper()} is unavailable: {item['reason']}.")

        # Instagram safety & cost warning (only if user named it)
        instagram_warning = None
        if "instagram" in chosen_platforms:
            limits = CollectionLimits()
            instagram_warning = (
                f"⚠️ Instagram collection uses Apify Actor credits (budget cap: ${limits.apify_max_cost_usd:.2f} USD, "
                f"item cap: {limits.apify_max_comments_per_query} comments). Hashtag explore feeds primarily surface recent posts "
                "with few comments, so collection often finishes below target."
            )
            warnings.append(instagram_warning)

        if not chosen_platforms:
            avail_list = [p.upper() for p, v in avail.items() if v["available"]]
            avail_msg = f"Available platforms: {', '.join(avail_list)}" if avail_list else "No platforms currently have valid credentials."
            return {
                "messages": [
                    {
                        "role": "assistant",
                        "text": f"None of the requested platforms are available right now.\n"
                                f"{'; '.join(warnings)}\n{avail_msg}",
                    }
                ],
                "cards": [
                    {"type": "platforms", "platforms": avail}
                ],
                "quick_replies": ["Check available platforms", "Help"],
            }

        # Store pending plan in session awaiting user confirmation
        session.pending_plan = {
            "topic": topic,
            "platforms": chosen_platforms,
            "target_comments": clamped_target,
            "max_minutes": parsed.max_minutes or 10.0,
            "max_posts": parsed.max_posts or 30,
            "warnings": warnings,
            "instagram_warning": instagram_warning,
        }

        plat_str = ", ".join(p.upper() for p in chosen_platforms)
        msg_text = (
            f"I've prepared a collection plan for **'{topic}'**.\n\n"
            f"• **Target:** Up to {clamped_target} comments per platform\n"
            f"• **Platforms:** {plat_str}\n"
            f"• **Estimated time:** Takes a few minutes in the background.\n\n"
            "Would you like to start collection?"
        )

        return {
            "messages": [{"role": "assistant", "text": msg_text}],
            "cards": [
                {
                    "type": "plan",
                    "topic": topic,
                    "platforms": chosen_platforms,
                    "target_comments": clamped_target,
                    "target": clamped_target,
                    "max_minutes": parsed.max_minutes or 10.0,
                    "max_posts": parsed.max_posts or 30,
                    "warnings": warnings,
                    "unavailable_requested": unavailable_requested,
                    "instagram_warning": instagram_warning,
                }
            ],
            "quick_replies": ["Confirm", "Cancel", "Available platforms"],
        }

    # -----------------------------------------------------------------------
    # INTENT: Job Status
    # -----------------------------------------------------------------------
    if intent == "status":
        if not session.active_job_id:
            return {
                "messages": [
                    {
                        "role": "assistant",
                        "text": "No active collection job in this session yet. Ask me to collect comments to start one!",
                    }
                ],
                "cards": [],
                "quick_replies": ["Get 500 comments about Asian Games 2026", "Available platforms", "Help"],
            }

        try:
            stat = collection_manager.status(session.active_job_id)
            if stat["finished"]:
                res = collection_manager.results(session.active_job_id, page=1, page_size=25)
                session.last_results_view = {"page": 1, "platform_filter": None}
                return {
                    "messages": [
                        {
                            "role": "assistant",
                            "text": f"Job **{session.active_job_id}** for '{stat['topic']}' is **{stat['status']}**! "
                                    f"Collected {stat['total_comments']} total comments.",
                        }
                    ],
                    "cards": [
                        {
                            "type": "results",
                            "job_id": session.active_job_id,
                            "topic": res["topic"],
                            "status": res["status"],
                            "finished": res["finished"],
                            "summary": res["summary"],
                            "counts_per_platform": res["counts_per_platform"],
                            "total_comments": res["total_comments"],
                            "below_target": res["below_target"],
                            "top_comments": res["top_comments"],
                            "page": res["page"],
                            "page_size": res["page_size"],
                            "total_pages": res["total_pages"],
                            "rows": res["rows"],
                            "current_platform_filter": None,
                            "filter_platform": None,
                            "platform_filter": None,
                        }
                    ],
                    "quick_replies": ["Export CSV", "Export JSON", "Show results", "New topic"],
                }

            return {
                "messages": [
                    {
                        "role": "assistant",
                        "text": f"Job **{session.active_job_id}** is running: {stat['summary']}",
                    }
                ],
                "cards": [
                    {
                        "type": "job",
                        "job_id": session.active_job_id,
                        "topic": stat["topic"],
                        "status": stat["status"],
                        "platforms": stat["platforms"],
                        "total_comments": stat["total_comments"],
                        "finished": stat["finished"],
                        "summary": stat["summary"],
                    }
                ],
                "quick_replies": ["Check status", "Help"],
            }
        except JobError as exc:
            return {
                "messages": [{"role": "assistant", "text": f"Error checking status: {exc}"}],
                "cards": [],
                "quick_replies": ["New topic", "Help"],
            }

    # -----------------------------------------------------------------------
    # INTENT: Show Results (Pagination / Filter)
    # -----------------------------------------------------------------------
    if intent == "show_results":
        if not session.active_job_id:
            return {
                "messages": [
                    {
                        "role": "assistant",
                        "text": "No collection job found to display results for. Start a job first!",
                    }
                ],
                "cards": [],
                "quick_replies": ["Get 500 comments about Asian Games 2026", "Available platforms", "Help"],
            }

        page = parsed.page or session.last_results_view.get("page", 1)
        p_filter = parsed.platform_filter if parsed.platform_filter is not None else session.last_results_view.get("platform_filter")

        try:
            res = collection_manager.results(session.active_job_id, page=page, page_size=25, platform=p_filter)
            session.last_results_view = {"page": res["page"], "platform_filter": p_filter}

            filter_msg = f" (filtered to {p_filter.upper()})" if p_filter else ""
            msg = f"Displaying page {res['page']} of {res['total_pages']}{filter_msg} for job **{session.active_job_id}** ({res['total_comments']} total comments)."

            replies = ["Export CSV", "Export JSON"]
            if res["total_pages"] > res["page"]:
                replies.append("Next page")
            if p_filter:
                replies.append("All platforms")
            replies.append("New topic")

            return {
                "messages": [{"role": "assistant", "text": msg}],
                "cards": [
                    {
                        "type": "results",
                        "job_id": session.active_job_id,
                        "topic": res["topic"],
                        "status": res["status"],
                        "finished": res["finished"],
                        "summary": res["summary"],
                        "counts_per_platform": res["counts_per_platform"],
                        "total_comments": res["total_comments"],
                        "below_target": res["below_target"],
                        "top_comments": res["top_comments"],
                        "page": res["page"],
                        "page_size": res["page_size"],
                        "total_pages": res["total_pages"],
                        "rows": res["rows"],
                        "current_platform_filter": p_filter,
                        "filter_platform": p_filter,
                        "platform_filter": p_filter,
                    }
                ],
                "quick_replies": replies,
            }
        except JobError as exc:
            return {
                "messages": [{"role": "assistant", "text": f"Error loading results: {exc}"}],
                "cards": [],
                "quick_replies": ["Help"],
            }

    # -----------------------------------------------------------------------
    # INTENT: Export (CSV / JSON)
    # -----------------------------------------------------------------------
    if intent == "export":
        if not session.active_job_id:
            return {
                "messages": [{"role": "assistant", "text": "No collection job found to export."}],
                "cards": [],
                "quick_replies": ["Get 500 comments about Asian Games 2026", "Help"],
            }

        fmt = parsed.format or "csv"
        try:
            exp = export_job(session.active_job_id, fmt=fmt, db_path=collection_manager.db_path)
            download_url = f"/api/collect/{session.active_job_id}/export?format={fmt}"
            return {
                "messages": [
                    {
                        "role": "assistant",
                        "text": f"Export ready! Generated **{fmt.upper()}** with {exp['rows']} comments.",
                    }
                ],
                "cards": [
                    {
                        "type": "export",
                        "job_id": session.active_job_id,
                        "format": fmt,
                        "rows": exp["rows"],
                        "download_url": download_url,
                    }
                ],
                "quick_replies": [
                    f"Export {'JSON' if fmt == 'csv' else 'CSV'}",
                    "Show results",
                    "New topic",
                ],
            }
        except Exception as exc:
            return {
                "messages": [{"role": "assistant", "text": f"Export failed: {exc}"}],
                "cards": [],
                "quick_replies": ["Help"],
            }

    # -----------------------------------------------------------------------
    # INTENT: Explain (Stop reasons, below target, Instagram details)
    # -----------------------------------------------------------------------
    if intent == "explain":
        target_p = parsed.explanation_target
        if session.active_job_id:
            try:
                res = collection_manager.results(session.active_job_id)
                below = res.get("below_target", {})
                explanations = []

                for p, info in below.items():
                    if target_p and p != target_p:
                        continue
                    reason = info.get("reason")
                    exp_text = STOP_REASON_EXPLANATIONS.get(reason, f"Reason: {reason or 'unknown'}")
                    if p == "instagram":
                        exp_text += " (Instagram explore feeds primarily surface newest posts which often have few comments; Apify safety caps also prevent excessive spending)."
                    explanations.append(f"• **{p.upper()}**: {exp_text} (collected {info.get('collected')}/{info.get('target')})")

                if explanations:
                    reply_text = "Here is why collection finished below target:\n\n" + "\n".join(explanations)
                else:
                    reply_text = f"All platforms in job {session.active_job_id} reached their targets or completed as expected."
                return {
                    "messages": [{"role": "assistant", "text": reply_text}],
                    "cards": [],
                    "quick_replies": ["Show results", "Export CSV", "New topic"],
                }
            except Exception:
                pass

        # General explanation if no active job
        return {
            "messages": [
                {
                    "role": "assistant",
                    "text": "When a platform collects fewer comments than the target, it is typically because:\n"
                            "• **no_more_candidates**: The search exhausted matching posts/threads before reaching the target count.\n"
                            "• **budget_cap_reached**: Instagram reached the Apify dollar/item protection cap.\n"
                            "• **Instagram feeds**: Only newest posts are returned by hashtag search, which usually have few comments.\n"
                            "• **max_time_reached / max_posts_reached**: The collection hit safety limits.",
                }
            ],
            "cards": [],
            "quick_replies": ["Available platforms", "Start a collection", "Help"],
        }

    # -----------------------------------------------------------------------
    # INTENT: Platforms
    # -----------------------------------------------------------------------
    if intent == "platforms":
        avail = get_platforms_availability()
        lines = []
        for p, info in avail.items():
            status_icon = "✅ Available" if info["available"] else "❌ Unavailable"
            lines.append(f"• **{p.upper()}**: {status_icon} - {info['reason']}")

        return {
            "messages": [
                {
                    "role": "assistant",
                    "text": "Here is the current platform status:\n\n" + "\n".join(lines),
                }
            ],
            "cards": [
                {"type": "platforms", "platforms": avail}
            ],
            "quick_replies": ["Get 500 comments about Asian Games 2026", "Help"],
        }

    # -----------------------------------------------------------------------
    # INTENT: Help
    # -----------------------------------------------------------------------
    if intent == "help":
        return {
            "messages": [
                {
                    "role": "assistant",
                    "text": (
                        "I can collect public comments across YouTube, Reddit, X, and Instagram for any topic!\n\n"
                        "**Example prompts:**\n"
                        "• *'Get me 500 comments about Asian Games 2026 from YouTube and Reddit'*\n"
                        "• *'Collect 1k comments on AI agents from X and Reddit'*\n"
                        "• *'Find 200 comments about Cricket World Cup'*\n\n"
                        "**Follow-up commands:**\n"
                        "• *'Show only Reddit'* or *'Next page'*\n"
                        "• *'What is the status?'*\n"
                        "• *'Export as CSV'* or *'Export as JSON'*\n"
                        "• *'Why is Instagram so low?'*\n"
                        "• *'Available platforms'*"
                    ),
                }
            ],
            "cards": [],
            "quick_replies": [
                "Get 500 comments about Asian Games 2026",
                "Available platforms",
                "Check status",
            ],
        }

    # -----------------------------------------------------------------------
    # INTENT: Unknown
    # -----------------------------------------------------------------------
    return {
        "messages": [
            {
                "role": "assistant",
                "text": "I didn't quite understand that. You can ask me to collect comments on a topic (e.g. 'Get 500 comments about Asian Games 2026 from YouTube'), check job status, or ask for available platforms.",
            }
        ],
        "cards": [],
        "quick_replies": [
            "Get 500 comments about Asian Games 2026",
            "Available platforms",
            "Help",
        ],
    }
