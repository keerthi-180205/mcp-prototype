"""Shared plumbing for paid REST backends: cache lookup, budget check, call, usage record."""

import hashlib
import re
from typing import Any, Awaitable, Callable, Optional, Sequence

from server.collection.collectors.base import CollectorFatalError
from server.collection.ledger import (
    DEFAULT_BLOCK_TTL,
    NO_CREDIT_BLOCK_TTL,
    BudgetExceeded,
    ProviderLedger,
    cache_key,
    get_ledger,
)


class MeteredMixin:
    provider: str
    platform: str
    _ledger: Optional[ProviderLedger] = None
    credits_used: float = 0.0

    @property
    def ledger(self) -> ProviderLedger:
        if self._ledger is None:
            self._ledger = get_ledger()
        return self._ledger

    def _fingerprint(self) -> Optional[str]:
        """Short hash of the API key in use, so a block is forgotten when the key is replaced."""
        key = getattr(getattr(self, "client", None), "_api_key", None)
        return hashlib.sha1(key.encode()).hexdigest()[:10] if key else None

    def blocked_reason(self) -> Optional[str]:
        return self.ledger.blocked_reason(self.provider, self._fingerprint())

    async def _metered(
        self,
        key_parts: Sequence[Any],
        call: Callable[[], Awaitable[Any]],
        action: str,
        ttl: float,
        charged_of: Callable[[Any], float],
        map_error: Callable[[Exception], Optional[Exception]],
        cache_if: Callable[[Any], bool] = lambda _payload: True,
    ) -> Any:
        """Return a cached payload for free, otherwise spend credits within the budget.

        `charged_of(payload)` reads the real credits charged from the response. `map_error`
        turns a provider error into CollectorFatalError (auth, no credits) or returns None to
        re-raise it unchanged. Budget problems are always fatal for this provider only: the
        chain then falls through to the next one. A payload for which `cache_if` is False is
        returned (and its credits recorded) but not cached, so a bad response cannot poison repeats.
        """
        key = cache_key(self.provider, *key_parts)
        cached = self.ledger.cache_get(key)
        if cached is not None:
            self.ledger.record_usage(self.provider, self.platform, action, cached=True)
            return cached

        try:
            self.ledger.check_budget(self.provider, 1, self.credits_used)
        except BudgetExceeded as exc:
            raise CollectorFatalError(str(exc)) from exc

        try:
            payload = await call()
        except Exception as exc:
            self.ledger.record_usage(self.provider, self.platform, action, ok=False, detail=str(exc))
            mapped = map_error(exc)
            if mapped is not None:
                # No credits / bad key: remember it so the next jobs do not retry (and the UI can say why).
                # Those do not fix themselves, so remember for hours; rate limits clear up quickly.
                long_lived = re.search(r"no credits|out of credits|rejected the api key|no serp api zone", str(mapped), re.IGNORECASE)
                self.ledger.set_blocked(self.provider, str(mapped), NO_CREDIT_BLOCK_TTL if long_lived else DEFAULT_BLOCK_TTL, self._fingerprint())
                raise mapped from exc
            raise

        charged = charged_of(payload)
        self.credits_used += charged
        self.ledger.record_usage(self.provider, self.platform, action, credits=charged, cached=charged == 0)
        if cache_if(payload):
            self.ledger.cache_put(key, self.provider, payload, ttl)
        return payload
