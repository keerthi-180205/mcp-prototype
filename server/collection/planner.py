"""Query planner: topic -> keywords, hashtags and subreddits (rule-based, optional Gemini)."""

import asyncio
import json
import logging
import re
from typing import List, Optional

from server.collection.models import QueryPlan

logger = logging.getLogger("mcp_server.collection.planner")

_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "for", "and", "to", "at", "is", "are", "with", "about",
}

_SUBREDDIT_RULES = [
    ({"games", "game", "olympic", "olympics", "cup", "league", "championship", "tournament",
      "fifa", "nba", "nfl", "cricket", "ipl", "football", "soccer", "tennis", "athletics",
      "medal", "asian", "sports", "match"},
     ["olympics", "sports", "worldnews", "news"]),
    ({"ai", "gpt", "llm", "software", "app", "iphone", "android", "tech", "startup", "chip",
      "gadget", "linux", "python", "openai"},
     ["technology", "artificial", "gadgets"]),
    ({"election", "president", "minister", "government", "senate", "policy", "war", "protest",
      "parliament", "vote"},
     ["politics", "worldnews", "news"]),
    ({"movie", "film", "series", "season", "trailer", "album", "song", "netflix", "actor",
      "bollywood", "anime", "concert"},
     ["movies", "television", "music", "entertainment"]),
    ({"stock", "stocks", "crypto", "bitcoin", "market", "economy", "inflation", "bank", "ipo"},
     ["wallstreetbets", "investing", "economics", "cryptocurrency"]),
    ({"health", "mental", "therapy", "anxiety", "depression", "wellness", "fitness"},
     ["mentalhealth", "health", "fitness"]),
]
_DEFAULT_SUBREDDITS = ["news", "worldnews", "AskReddit"]
_KEYWORD_SUFFIXES = ["highlights", "reaction", "news"]


def tokenize(text: str) -> List[str]:
    """Lowercase alphanumeric tokens without stopwords (unicode letters allowed)."""
    return [t for t in re.findall(r"[^\W_]+", text.lower()) if t not in _STOPWORDS]


def _dedupe(items: List[str], limit: int) -> List[str]:
    seen, out = set(), []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
        if len(out) >= limit:
            break
    return out


def plan_with_rules(topic: str) -> QueryPlan:
    topic = " ".join(topic.split())
    toks = tokenize(topic)

    keywords = [topic]
    no_year = [t for t in toks if not re.fullmatch(r"(19|20)\d{2}", t)]
    if no_year and len(no_year) != len(toks):
        keywords.append(" ".join(no_year))
    keywords += [f"{topic} {s}" for s in _KEYWORD_SUFFIXES]

    hashtags: List[str] = []
    if toks:
        hashtags.append("".join(toks))
    if no_year and len(no_year) != len(toks):
        hashtags.append("".join(no_year))
    if len(toks) > 2:
        hashtags.append("".join(toks[:2]))

    tokset = set(toks)
    subs: List[str] = []
    for words, subreddits in _SUBREDDIT_RULES:
        if tokset & words:
            subs += subreddits
    subs = subs or _DEFAULT_SUBREDDITS

    return QueryPlan(
        topic=topic,
        keywords=_dedupe(keywords, 5),
        hashtags=_dedupe(hashtags, 4),
        subreddits=_dedupe(subs, 5),
        planner="rules",
    )


async def _gemini_suggestions(topic: str, api_key: str, model: str, timeout: float) -> Optional[dict]:
    try:
        from google import genai  # type: ignore
    except Exception:
        return None

    prompt = (
        "You help find social media posts about a topic. For the topic below return ONLY JSON "
        '{"keywords":[up to 4 short search phrases],"hashtags":[up to 4 hashtags without #],'
        '"subreddits":[up to 4 relevant subreddit names without r/]}.\nTopic: ' + topic
    )

    def _call() -> str:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(model=model, contents=prompt)
        return resp.text or ""

    try:
        raw = await asyncio.wait_for(asyncio.to_thread(_call), timeout=timeout)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        return json.loads(match.group(0)) if match else None
    except Exception as exc:  # optional enhancement: never fail the job because of it
        logger.info("Gemini query planning skipped: %s", type(exc).__name__)
        return None


async def plan_query(topic: str, use_llm: bool = True, settings=None) -> QueryPlan:
    """Build the search plan. Rules always run; Gemini only augments when GEMINI_API_KEY is set."""
    plan = plan_with_rules(topic)
    if not use_llm:
        return plan
    if settings is None:
        from server.config import get_settings

        settings = get_settings()
    if not settings.gemini_api_key:
        return plan

    data = await _gemini_suggestions(topic, settings.gemini_api_key, settings.gemini_model, 20.0)
    if not isinstance(data, dict):
        return plan

    def _clean(vals, prefix_strip: str = "") -> List[str]:
        return [str(v).strip().lstrip(prefix_strip) for v in (vals or []) if str(v).strip()]

    plan.keywords = _dedupe(plan.keywords + _clean(data.get("keywords")), 7)
    plan.hashtags = _dedupe(plan.hashtags + [h.replace(" ", "") for h in _clean(data.get("hashtags"), "#")], 6)
    plan.subreddits = _dedupe(plan.subreddits + [s.replace("r/", "") for s in _clean(data.get("subreddits"))], 7)
    plan.planner = "rules+gemini"
    return plan
