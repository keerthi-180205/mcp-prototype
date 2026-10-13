"""Adaptive harvesting: keep fetching comments from the next-best post until a limit is hit."""

import asyncio
import logging
import math
import time
from typing import Callable, List, Optional, Set, Tuple

from server.collection.cleaning import clean_comments
from server.collection.collectors.base import CollectorFatalError, PlatformCollector
from server.collection.models import (
    STOP_BUDGET,
    STOP_ERROR,
    STOP_MAX_POSTS,
    STOP_MAX_TIME,
    STOP_NO_MORE,
    STOP_TARGET,
    STOP_UNAVAILABLE,
    CollectionLimits,
    CommentRow,
    PlatformProgress,
    PostCandidate,
    QueryPlan,
)
from server.collection.ranking import rank_candidates

logger = logging.getLogger("mcp_server.collection.harvester")

DEFAULT_ESTIMATE = 50
MAX_CONSECUTIVE_FAILURES = 4

RowSink = Callable[[str, List[CommentRow]], None]


def _estimate(post: PostCandidate) -> int:
    return post.comment_count if post.comment_count else DEFAULT_ESTIMATE


def _select_batch(
    queue: List[PostCandidate], collector: PlatformCollector, remaining: int, posts_left: int
) -> List[PostCandidate]:
    """Take the next-best posts until their estimated comments cover what is still needed."""
    batch: List[PostCandidate] = []
    covered = 0
    for post in queue:
        if len(batch) >= min(collector.batch_size, posts_left):
            break
        batch.append(post)
        covered += _estimate(post)
        if covered >= remaining * 1.3:
            break
    return batch


def _allocations(batch: List[PostCandidate], remaining: int) -> dict:
    cap = math.ceil(remaining * 1.2) + 10
    return {p.url: min(math.ceil(_estimate(p) * 1.2) + 10, cap) for p in batch}


async def harvest_platform(
    collector: PlatformCollector,
    plan: QueryPlan,
    limits: CollectionLimits,
    progress: PlatformProgress,
    on_rows: Optional[RowSink] = None,
) -> List[CommentRow]:
    """Discover, rank and harvest one platform. Never raises: failures land in `progress`."""
    started = time.monotonic()
    deadline = started + limits.max_seconds
    collected: List[CommentRow] = []
    seen: Set[Tuple[str, str, str]] = set()
    progress.target = limits.target_comments

    def _tick() -> None:
        progress.elapsed_seconds = round(time.monotonic() - started, 1)

    if not collector.is_available():
        progress.status = "skipped"
        progress.stop_reason = STOP_UNAVAILABLE
        progress.error = collector.unavailable_reason()
        return collected

    collector.configure(limits)

    try:
        progress.status = "discovering"
        try:
            found = await asyncio.wait_for(
                collector.discover(plan, limits.candidates_per_platform),
                timeout=max(5.0, deadline - time.monotonic()),
            )
        except asyncio.TimeoutError:
            progress.stop_reason = STOP_MAX_TIME
            progress.status = "done"
            progress.notes.append("discovery timed out")
            return collected

        queue = rank_candidates(plan.topic, found, limits.min_relevance)
        progress.candidates_found = len(queue)
        _tick()
        if not queue:
            progress.stop_reason = STOP_NO_MORE
            progress.status = "done"
            return collected

        progress.status = "harvesting"
        failures = 0
        while queue and len(collected) < limits.target_comments:
            if time.monotonic() >= deadline:
                progress.stop_reason = STOP_MAX_TIME
                break
            if progress.posts_processed >= limits.max_posts:
                progress.stop_reason = STOP_MAX_POSTS
                break
            if collector.budget_exhausted():
                progress.stop_reason = STOP_BUDGET
                break

            remaining = limits.target_comments - len(collected)
            batch = _select_batch(queue, collector, remaining, limits.max_posts - progress.posts_processed)
            del queue[: len(batch)]
            try:
                fetched = await asyncio.wait_for(
                    collector.fetch_comments(batch, _allocations(batch, remaining)),
                    timeout=max(5.0, deadline - time.monotonic()),
                )
            except asyncio.TimeoutError:
                progress.stop_reason = STOP_MAX_TIME
                progress.notes.append("a fetch was cut off by the time limit")
                break
            except CollectorFatalError as exc:
                progress.stop_reason = STOP_ERROR
                progress.error = str(exc)[:300]
                break
            except Exception as exc:
                failures += 1
                progress.posts_processed += len(batch)
                progress.notes.append(f"fetch failed: {str(exc)[:160]}")
                if failures >= MAX_CONSECUTIVE_FAILURES:
                    progress.stop_reason = STOP_ERROR
                    progress.error = f"{failures} consecutive fetch failures; last: {str(exc)[:200]}"
                    break
                continue

            failures = 0
            progress.posts_processed += len(batch)
            for post in batch:
                raw = fetched.get(post.url, [])
                progress.comments_raw += len(raw)
                rows = clean_comments(raw, post, seen)
                if rows:
                    collected.extend(rows)
                    if on_rows:
                        on_rows(post.url, rows)
                progress.comments_collected = len(collected)
            _tick()

        if progress.stop_reason is None:
            if len(collected) >= limits.target_comments:
                progress.stop_reason = STOP_TARGET
            elif progress.posts_processed >= limits.max_posts:
                progress.stop_reason = STOP_MAX_POSTS
            elif collector.budget_exhausted():
                progress.stop_reason = STOP_BUDGET
            else:
                progress.stop_reason = STOP_NO_MORE
        progress.status = "failed" if progress.stop_reason == STOP_ERROR and not collected else "done"
    except CollectorFatalError as exc:
        progress.status = "failed"
        progress.stop_reason = STOP_ERROR
        progress.error = str(exc)[:300]
    except Exception as exc:  # defensive: one platform must never take the job down
        logger.exception("Harvest failed for %s", collector.platform)
        progress.status = "failed"
        progress.stop_reason = STOP_ERROR
        progress.error = f"{type(exc).__name__}: {str(exc)[:200]}"
    finally:
        progress.comments_collected = len(collected)
        _tick()
    return collected
