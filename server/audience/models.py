"""Shapes shared by the audience modules."""

import hashlib
from typing import List, Optional

from pydantic import BaseModel, Field

# Comments that may come from someone who is struggling: these (and only these) enter the care queue.
CARE_LABELS = ("crisis", "seeking_help", "distress")
LABELS = CARE_LABELS + ("question", "positive", "spam", "other")
PRIORITY = {"crisis": 3, "seeking_help": 2, "distress": 1}
STATUSES = ("new", "replied", "dismissed")


class Triage(BaseModel):
    label: str = "other"
    priority: int = 0
    reasons: List[str] = Field(default_factory=list)   # the phrases that triggered the label (for the reviewer)
    possible_minor: bool = False                       # a cue, never a conclusion: reply more carefully
    generic: bool = False                              # emoji-only / one-word reaction


class AudienceComment(BaseModel):
    platform: str
    account: str                      # the MMTF account whose post this is
    post_url: str
    username: str = ""
    user_id: Optional[str] = None
    comment: str
    likes: int = 0
    created_at: Optional[str] = None
    provider: Optional[str] = None
    comment_id: Optional[str] = None
    parent_id: Optional[str] = None
    triage: Triage = Field(default_factory=Triage)

    @property
    def key(self) -> str:
        return comment_key(self.platform, self.post_url, self.comment_id, self.username, self.comment)


def comment_key(platform: str, post_url: str, comment_id: Optional[str], username: str, text: str) -> str:
    """Stable id, so collecting the same post twice updates rows instead of duplicating them."""
    basis = f"{platform}|{post_url}|{comment_id}" if comment_id else f"{platform}|{post_url}|{username.lower()}|{text.strip()}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:20]
