"""Look up provider state that can be read for free, so availability does not wait for a failing job."""

import hashlib
import logging
from typing import Any, Dict, Optional

from server.collection.ledger import NO_CREDIT_BLOCK_TTL, ProviderLedger, get_ledger
from server.providers.socialcrawl.client import SocialCrawlAuthenticationError, SocialCrawlClient, SocialCrawlError

logger = logging.getLogger("mcp_server.collection.health")


async def refresh_provider_state(ledger: Optional[ProviderLedger] = None, socialcrawl: Optional[SocialCrawlClient] = None) -> Dict[str, Any]:
    """Refresh what we know about providers whose balance is free to read (currently SocialCrawl).

    Zero credits -> remembered as blocked (until the key changes or credits appear); credits present -> any
    old block is cleared, so a top-up is noticed without anyone running a job.
    """
    ledger = ledger or get_ledger()
    client = socialcrawl or SocialCrawlClient()
    state: Dict[str, Any] = {}
    if not client.is_configured:
        return {"socialcrawl": {"configured": False}}
    fp = hashlib.sha1(client._api_key.encode()).hexdigest()[:10]
    try:
        balance = await client.credit_balance()
    except SocialCrawlAuthenticationError as exc:
        ledger.set_blocked("socialcrawl", f"SocialCrawl rejected the API key: {str(exc)[:100]}", NO_CREDIT_BLOCK_TTL, fp)
        return {"socialcrawl": {"configured": True, "balance": None, "blocked": True}}
    except SocialCrawlError as exc:   # unreachable / unexpected: leave what we knew
        logger.info("SocialCrawl balance check failed: %s", str(exc)[:100])
        return {"socialcrawl": {"configured": True, "balance": None, "error": str(exc)[:100]}}
    if balance is not None and balance <= 0:
        ledger.set_blocked("socialcrawl", "SocialCrawl has no credits left (balance 0)", NO_CREDIT_BLOCK_TTL, fp)
    elif balance is not None:
        ledger.clear_blocked("socialcrawl")
    state["socialcrawl"] = {"configured": True, "balance": balance, "blocked": bool(balance is not None and balance <= 0)}
    return state
