"""Candidate relevance + ranking: comment count x relevance x recency."""

import datetime
import math
import re
from typing import Iterable, List, Optional

from server.collection.models import PostCandidate
from server.collection.planner import tokenize


def relevance_score(topic: str, *texts: Optional[str]) -> float:
    """Fraction of the topic's tokens present in the candidate text (1.0 if the phrase appears)."""
    haystack = " ".join(t for t in texts if t).lower()
    if not haystack:
        return 0.0
    topic_l = " ".join(topic.lower().split())
    if topic_l and topic_l in " ".join(haystack.split()):
        return 1.0
    toks = tokenize(topic)
    if not toks:
        return 0.0
    hay_tokens = set(tokenize(haystack))
    score = sum(1 for t in toks if t in hay_tokens) / len(toks)

    # Hashtags squash words together ("#asiangames2026"): compare the squashed forms too.
    squashed = re.sub(r"[\W_]+", "", haystack)
    if "".join(toks) in squashed:
        return 1.0
    core = "".join(t for t in toks if not re.fullmatch(r"(19|20)\d{2}", t))
    if core and core in squashed:
        score = max(score, 0.8)
    return score


def parse_iso(value: Optional[str]) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def recency_factor(published_at: Optional[str], now: Optional[datetime.datetime] = None) -> float:
    """Half-life of 90 days, floor 0.1; unknown date gets a neutral 0.5."""
    dt = parse_iso(published_at)
    if dt is None:
        return 0.5
    now = now or datetime.datetime.now(datetime.timezone.utc)
    age_days = max(0.0, (now - dt).total_seconds() / 86400.0)
    return max(0.1, 0.5 ** (age_days / 90.0))


def comment_weight(candidate: PostCandidate) -> float:
    """log-scaled comment volume; unknown counts fall back to a small view/like based estimate."""
    count = candidate.comment_count
    if count is None:
        if candidate.view_count:
            count = int(candidate.view_count * 0.002)
        elif candidate.like_count:
            count = int(candidate.like_count * 0.05)
        else:
            count = 1
    return math.log1p(max(count, 0))


def rank_candidates(
    topic: str,
    candidates: Iterable[PostCandidate],
    min_relevance: float = 0.5,
    now: Optional[datetime.datetime] = None,
) -> List[PostCandidate]:
    """Score, filter off-topic candidates, de-duplicate by URL, sort best first."""
    seen = set()
    ranked: List[PostCandidate] = []
    for c in candidates:
        if c.url in seen:
            continue
        seen.add(c.url)
        c.relevance = relevance_score(topic, c.title, c.text)
        if c.relevance < min_relevance:
            continue
        c.score = comment_weight(c) * c.relevance * recency_factor(c.published_at, now)
        ranked.append(c)
    ranked.sort(key=lambda c: c.score, reverse=True)
    return ranked
