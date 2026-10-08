"""Data models for the comment-collection pipeline."""

import os
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

SUPPORTED_PLATFORMS = ["instagram", "youtube", "reddit", "x"]

# Stop reasons recorded per platform
STOP_TARGET = "target_reached"
STOP_MAX_POSTS = "max_posts_reached"
STOP_MAX_TIME = "max_time_reached"
STOP_NO_MORE = "no_more_candidates"
STOP_BUDGET = "budget_cap_reached"
STOP_UNAVAILABLE = "platform_unavailable"
STOP_ERROR = "error"


class CommentRow(BaseModel):
    """One commenter + comment. This is the exported / stored row format."""

    platform: str
    username: str = ""
    user_id: Optional[str] = None
    comment: str
    likes: int = 0
    created_at: Optional[str] = None
    post_url: str


class PostCandidate(BaseModel):
    """A discovered post/video/thread whose comments may be harvested."""

    platform: str
    post_id: str
    url: str
    title: str = ""
    text: str = ""
    author_username: Optional[str] = None
    author_id: Optional[str] = None
    comment_count: Optional[int] = None
    like_count: Optional[int] = None
    view_count: Optional[int] = None
    published_at: Optional[str] = None
    relevance: float = 0.0
    score: float = 0.0
    extra: Dict[str, Any] = Field(default_factory=dict)


class QueryPlan(BaseModel):
    """Rule-based (optionally LLM-assisted) search plan for one topic."""

    topic: str
    keywords: List[str] = Field(default_factory=list)
    hashtags: List[str] = Field(default_factory=list)
    subreddits: List[str] = Field(default_factory=list)
    planner: str = "rules"

    def keywords_for(self, platform: str) -> List[str]:
        return list(self.keywords)


class CollectionLimits(BaseModel):
    """Per-platform harvesting limits."""

    target_comments: int = 500
    max_posts: int = 30
    max_seconds: float = 600.0
    candidates_per_platform: int = 40
    min_relevance: float = 0.5
    # Instagram / Apify hard caps per query (protect credits). Env-driven on purpose: the chatbot
    # cannot raise them through a tool argument.
    apify_max_comments_per_query: int = Field(
        default_factory=lambda: int(os.getenv("APIFY_MAX_COMMENTS_PER_QUERY", "1500"))
    )
    apify_max_cost_usd: float = Field(
        default_factory=lambda: float(os.getenv("APIFY_MAX_COST_PER_QUERY_USD", "0.5"))
    )
    instagram_discovery_posts: int = Field(
        default_factory=lambda: int(os.getenv("INSTAGRAM_DISCOVERY_POSTS", "120"))
    )


class PlatformProgress(BaseModel):
    platform: str
    status: str = "pending"  # pending|discovering|harvesting|done|failed|skipped
    target: int = 0
    candidates_found: int = 0
    posts_processed: int = 0
    comments_raw: int = 0
    comments_collected: int = 0
    stop_reason: Optional[str] = None
    error: Optional[str] = None
    elapsed_seconds: float = 0.0
    notes: List[str] = Field(default_factory=list)
