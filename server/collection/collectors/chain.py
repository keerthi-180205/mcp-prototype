"""Provider fallback chain: free tools first, paid REST APIs next, expensive batch actors last.

A platform is served by an ordered list of backends. The chain works per *operation*, because
providers are not equally capable (TrueScrape reads Instagram comments but cannot discover
posts, for example):

* discover - the first backend that returns candidates wins; no two paid providers are queried
  for the same thing.
* comments - posts go to the first backend; only posts it could not answer (errors) move on to
  the next one. A post that was answered with zero comments is never re-bought.

A backend that fails fatally (bad key, out of credits, budget limit) is switched off for the rest
of the job and the reason is kept in `notes` so the UI can explain why a platform fell back.
"""

import logging
from typing import Any, Dict, List, Tuple

from server.collection.collectors.base import CollectorFatalError, PlatformCollector
from server.collection.models import CollectionLimits, CommentRow, PostCandidate, QueryPlan

logger = logging.getLogger("mcp_server.collection.chain")


class ChainedCollector(PlatformCollector):
    provider = "chain"

    def __init__(self, platform: str, backends: List[PlatformCollector]):
        self.platform = platform
        self.backends = backends
        self.notes: List[str] = []
        self.served: Dict[str, int] = {}
        self._disabled: Dict[str, Tuple[str, bool]] = {}  # provider -> (reason, was_budget)

    # ---- backend selection ---------------------------------------------------------
    def _live(self, op: str) -> List[PlatformCollector]:
        flag = "can_discover" if op == "discover" else "can_comments"
        return [
            b for b in self.backends
            if getattr(b, flag) and b.provider not in self._disabled and b.is_available()
        ]

    def _disable(self, backend: PlatformCollector, reason: str, budget: bool = False) -> None:
        self._disabled[backend.provider] = (reason, budget)
        self.notes.append(f"{backend.provider} switched off: {reason[:160]}")
        logger.warning("%s/%s switched off: %s", self.platform, backend.provider, reason[:160])

    @staticmethod
    def _is_budget(reason: str) -> bool:
        low = reason.lower()
        return "limit" in low or "credit" in low or "budget" in low

    # ---- PlatformCollector API -----------------------------------------------------
    @property
    def batch_size(self) -> int:  # type: ignore[override]
        live = self._live("comments")
        return live[0].batch_size if live else 1

    def is_available(self) -> bool:
        return bool(self._live("discover")) and bool(self._live("comments"))

    def unavailable_reason(self) -> str:
        reasons = [f"{b.provider}: {b.unavailable_reason()}" for b in self.backends if not b.is_available()]
        for provider, (reason, _) in self._disabled.items():
            reasons.append(f"{provider}: {reason}")
        missing = [op for op in ("discover", "comments") if not self._live(op)]
        head = f"no provider can {' or '.join(missing)} {self.platform}" if missing else "unavailable"
        return head + (" - " + "; ".join(reasons) if reasons else "")

    def configure(self, limits: CollectionLimits) -> None:
        for b in self.backends:
            b.configure(limits)

    def budget_exhausted(self) -> bool:
        live = [b for b in self.backends if b.can_comments and b.is_available()]
        if not live:
            return False
        out_of_budget = 0
        for b in live:
            if b.provider in self._disabled:
                if self._disabled[b.provider][1]:
                    out_of_budget += 1
                else:
                    return False  # switched off by an error, not by budget
            elif b.budget_exhausted():
                out_of_budget += 1
            else:
                return False
        return out_of_budget > 0

    def describe(self) -> Dict[str, Any]:
        """Which providers can currently find posts / read comments, and why the others cannot."""
        unavailable = {b.provider: b.unavailable_reason() for b in self.backends if not b.is_available()}
        unavailable.update({p: r for p, (r, _) in self._disabled.items()})
        return {
            "discover": [b.provider for b in self._live("discover")],
            "comments": [b.provider for b in self._live("comments")],
            "unavailable": unavailable,
        }

    def usage(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"rows_by_provider": dict(self.served), "switched_off": {k: v[0] for k, v in self._disabled.items()}}
        for b in self.backends:
            fn = getattr(b, "usage", None)
            if callable(fn):
                out[b.provider] = fn()
        return out

    # ---- discovery -----------------------------------------------------------------
    async def discover(self, plan: QueryPlan, limit: int) -> List[PostCandidate]:
        problems: List[str] = []
        for backend in self._live("discover"):
            try:
                found = await backend.discover(plan, limit)
            except CollectorFatalError as exc:
                self._disable(backend, str(exc), self._is_budget(str(exc)))
                problems.append(f"{backend.provider}: {str(exc)[:140]}")
                continue
            except Exception as exc:
                self.notes.append(f"{backend.provider} discovery failed: {str(exc)[:120]}")
                problems.append(f"{backend.provider}: {str(exc)[:140]}")
                logger.warning("%s/%s discovery failed: %s", self.platform, backend.provider, exc)
                continue
            if found:
                for cand in found:
                    cand.extra.setdefault("discovered_by", backend.provider)
                return found
            self.notes.append(f"{backend.provider} found no posts")
        if problems:
            # Errors are not "no results": say why no provider could deliver instead of
            # reporting an empty platform as if nothing matched.
            raise CollectorFatalError("no provider could find posts - " + "; ".join(problems))
        return []

    # ---- comments ------------------------------------------------------------------
    async def fetch_post_comments(self, post: PostCandidate, max_comments: int) -> List[CommentRow]:
        return (await self.fetch_comments([post], {post.url: max_comments})).get(post.url, [])

    async def fetch_comments(
        self, posts: List[PostCandidate], per_post_limit: Dict[str, int]
    ) -> Dict[str, List[CommentRow]]:
        results: Dict[str, List[CommentRow]] = {}
        remaining = list(posts)
        last_error = ""

        for backend in self._live("comments"):
            if not remaining:
                break
            try:
                got = await backend.fetch_comments(remaining, {p.url: per_post_limit.get(p.url, 100) for p in remaining})
            except CollectorFatalError as exc:
                last_error = str(exc)
                self._disable(backend, last_error, self._is_budget(last_error))
                continue
            except Exception as exc:
                last_error = str(exc)
                self.notes.append(f"{backend.provider} comments failed: {last_error[:120]}")
                logger.warning("%s/%s comments failed: %s", self.platform, backend.provider, exc)
                continue

            for url, rows in got.items():
                for row in rows:
                    if not row.provider:
                        row.provider = backend.provider
                self.served[backend.provider] = self.served.get(backend.provider, 0) + len(rows)
                results[url] = rows
            remaining = [p for p in remaining if p.url not in results]

        if remaining and not results:
            if not self._live("comments"):
                raise CollectorFatalError(last_error or self.unavailable_reason())
            if last_error:  # let the harvester count consecutive failures
                raise RuntimeError(last_error)
        return results
