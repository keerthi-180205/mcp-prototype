"""Collect the comments on MMTF's own posts and triage them.

Guards, in order: the account must be listed in MMTF_OWN_ACCOUNTS; every post must be proven to belong to it;
the credit cap is checked between posts; the account's own replies are not treated as audience.
"""

from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

from server.audience.accounts import SUPPORTED, AccountsError, normalise_platform, require_account
from server.audience.models import CARE_LABELS, AudienceComment
from server.audience.sources import SourceError, get_source
from server.audience.triage import triage
from server.collection.collectors.base import CollectorFatalError
from server.collection.models import CommentRow, PostCandidate
from server.storage import audience as store


class AudienceError(Exception):
    """The request cannot be carried out (and nothing was collected)."""


def _credits(source: Any, collector: Any) -> float:
    total = float(getattr(source, "credits_used", 0.0) or 0.0)
    try:
        for value in (collector.usage() or {}).values():
            if isinstance(value, dict):
                total += float(value.get("credits_used", 0) or 0)
    except Exception:
        pass
    return total


MAX_COMMENT_CHARS = 5000    # platforms allow 2,200 (Instagram) to 10,000 (Reddit / YouTube); more is never a real comment


def to_audience(row: CommentRow, account: str) -> Optional[AudienceComment]:
    text = (row.comment or "").strip()[:MAX_COMMENT_CHARS]
    if not text or (row.username or "").lstrip("@").lower() == account:      # our own replies are not audience
        return None
    return AudienceComment(
        platform=row.platform, account=account, post_url=row.post_url, username=row.username or "", user_id=row.user_id,
        comment=text, likes=row.likes or 0, created_at=row.created_at, provider=row.provider, comment_id=row.comment_id,
        parent_id=row.parent_id, triage=triage(text),
    )


async def collect_own_comments(
    platform: str,
    account: Optional[str] = None,
    post_urls: Optional[Sequence[str]] = None,
    max_posts: int = 10,
    max_comments_per_post: int = 500,
    max_credits: float = 80.0,
    source: Any = None,
    collector: Any = None,
    db_path: Optional[str] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    platform = normalise_platform(platform)
    if platform not in SUPPORTED:
        raise AudienceError(f"own-post collection supports {', '.join(SUPPORTED)} for now; {platform} posts cannot be ownership-checked yet")
    try:
        account = require_account(platform, account)
    except AccountsError as exc:
        raise AudienceError(str(exc)) from exc
    say = on_progress or (lambda _msg: None)
    max_posts = max(1, min(int(max_posts), 50))
    max_comments_per_post = max(1, min(int(max_comments_per_post), 1000))

    try:
        source = source or get_source(platform)
        source.check_ready()
        posts, notes = await (source.check_posts(post_urls, account) if post_urls else source.list_posts(account, max_posts))
    except SourceError as exc:
        raise AudienceError(str(exc)) from exc
    notes = list(notes)

    summary: Dict[str, Any] = {
        "platform": platform, "account": account, "posts_found": len(posts), "posts_with_comments": 0, "comments": 0,
        "new": 0, "updated": 0, "new_care_items": 0, "by_label": {}, "served_by": {}, "credits_used": 0.0,
        "stopped": None, "notes": notes,
    }
    if not posts:
        summary["stopped"] = "no posts of this account could be confirmed"
        summary["credits_used"] = round(float(getattr(source, "credits_used", 0.0) or 0.0), 2)
        return summary

    if collector is None:
        from server.collection.registry import get_collector
        collector = get_collector(platform)

    for index, post in enumerate(posts, 1):
        spent = _credits(source, collector)
        if spent >= max_credits:
            summary["stopped"] = f"credit cap reached ({spent:.0f} of {max_credits:.0f}); {len(posts) - index + 1} post(s) not collected"
            break
        say(f"post {index}/{len(posts)}: reading comments")
        candidate = PostCandidate(platform=platform, post_id=post.post_id, url=post.url, title=post.caption[:100], text=post.caption,
                                  author_username=account, comment_count=post.comment_count, published_at=post.published_at)
        try:
            got = await collector.fetch_comments([candidate], {post.url: max_comments_per_post})
        except CollectorFatalError as exc:
            notes.append(f"stopped: {str(exc)[:160]}")
            summary["stopped"] = "provider unavailable"
            break
        except Exception as exc:
            notes.append(f"post {index}: {str(exc)[:120]}")
            continue
        rows = [c for c in (to_audience(r, account) for r in got.get(post.url, [])) if c]
        store.upsert_post({"url": post.url, "platform": platform, "account": account, "post_id": post.post_id, "caption": post.caption,
                           "comment_count": post.comment_count, "published_at": post.published_at}, db_path)
        result = store.upsert_comments(rows, db_path)
        summary["new"] += result["new"]
        summary["updated"] += result["updated"]
        summary["new_care_items"] += result["new_care"]
        summary["comments"] += len(rows)
        summary["posts_with_comments"] += bool(rows)
        for c in rows:
            summary["by_label"][c.triage.label] = summary["by_label"].get(c.triage.label, 0) + 1
            summary["served_by"][c.provider or "?"] = summary["served_by"].get(c.provider or "?", 0) + 1

    summary["credits_used"] = round(_credits(source, collector), 2)
    summary["care_labels"] = list(CARE_LABELS)
    return summary
