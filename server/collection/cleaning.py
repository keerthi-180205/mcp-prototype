"""Comment cleaning: drop empty, drop the post creator's own comments, dedupe."""

import re
from typing import Iterable, List, Optional, Set, Tuple

from server.collection.models import CommentRow, PostCandidate


def norm_username(name: Optional[str]) -> str:
    return (name or "").strip().lstrip("@").lower()


def norm_text(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def dedupe_key(row: CommentRow) -> Tuple[str, str, str]:
    return (row.platform, norm_username(row.username), norm_text(row.comment).lower())


def is_creator_comment(row: CommentRow, post: Optional[PostCandidate]) -> bool:
    if post is None:
        return False
    # Never drop the post's own commentary/statement itself
    if norm_text(row.comment) == norm_text(post.text):
        return False
    # If the platform is microblogging (X/Twitter or LinkedIn) where the post itself is a public commentary, retain it
    if row.platform in ("x", "linkedin") and norm_text(row.comment) in norm_text(post.text):
        return False
    author = norm_username(post.author_username)
    if author and norm_username(row.username) == author:
        return True
    if post.author_id and row.user_id and str(row.user_id) == str(post.author_id):
        return True
    return False


def clean_comments(
    rows: Iterable[CommentRow],
    post: Optional[PostCandidate] = None,
    seen: Optional[Set[Tuple[str, str, str]]] = None,
) -> List[CommentRow]:
    """Return cleaned rows. Pass a shared `seen` set to dedupe across posts/batches."""
    seen = seen if seen is not None else set()
    out: List[CommentRow] = []
    for row in rows:
        text = norm_text(row.comment)
        if not text:
            continue
        if is_creator_comment(row, post):
            continue
        uname = (row.username or "").strip().lstrip("@")
        if not uname and row.user_id:
            uname = f"user_{row.user_id}"
        elif not uname:
            uname = "anonymous"
        row = row.model_copy(update={"comment": text, "username": uname})
        key = dedupe_key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out
