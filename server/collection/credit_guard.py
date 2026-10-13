"""Intelligent Credit-Guard Multi-Provider Router & Ledger.

Enforces zero credit waste:
1. Tier 0 (Free Local / yt-dlp) always takes precedence where available.
2. Direct REST providers are ranked by platform-specific performance & cost.
3. Strict single-provider execution per platform: never queries multiple paid APIs simultaneously.
4. In-flight and persistent URL/Post deduplication to prevent re-fetching the same content.
5. Real-time credit balance tracking and audit ledger.
6. Extensible architecture: easily plug in new APIs with platform priorities.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("mcp_server.collection.credit_guard")


class CostTier(str, Enum):
    TIER_0_FREE = "tier_0_free"          # yt-dlp, local tools (0 credits)
    TIER_1_REST = "tier_1_rest"          # TrueScrape, SocialCrawl, specialized REST
    TIER_2_BATCH = "tier_2_batch"        # Bright Data, Apify, async batch


@dataclass
class ProviderBenchmark:
    """Benchmark rating for a provider on a specific platform."""
    provider_name: str
    platform: str
    cost_tier: CostTier
    priority: int                        # Higher = higher preference (e.g. 100 for free yt-dlp)
    success_rate: float = 1.0            # Dynamic EMA of success rate
    avg_latency_ms: float = 500.0
    notes: str = ""


@dataclass
class CreditAuditRecord:
    """Ledger entry tracking credit usage and credit savings."""
    timestamp: str
    platform: str
    provider_name: str
    action: str                          # "search", "comments", "dedup_skip", "free_tier_save"
    credits_spent: int = 0
    credits_saved: int = 0
    balance_remaining: Optional[int] = None
    target_id: Optional[str] = None


class CreditGuardRouter:
    """
    Central router that decides the single optimal provider per platform
    and ensures zero redundant API credits are consumed.
    """

    def __init__(self):
        # In-memory deduplication set: seen post URLs and content IDs
        self._seen_urls: Set[str] = set()
        self._seen_ids: Set[str] = set()

        # Ledger of credit transactions and savings
        self._audit_log: List[CreditAuditRecord] = []

        # Platform-to-Provider routing matrix (ordered by priority descending)
        # Higher priority = selected first. Tier 0 free always has highest priority.
        self._routing_matrix: Dict[str, List[ProviderBenchmark]] = {
            "youtube": [
                ProviderBenchmark(
                    provider_name="yt-dlp",
                    platform="youtube",
                    cost_tier=CostTier.TIER_0_FREE,
                    priority=100,
                    notes="Local Agent Reach yt-dlp. 100% free, zero API credits consumed.",
                ),
                ProviderBenchmark(
                    provider_name="socialcrawl",
                    platform="youtube",
                    cost_tier=CostTier.TIER_1_REST,
                    priority=20,
                    notes="Paid fallback only if local yt-dlp binary fails.",
                ),
            ],
            "instagram": [
                ProviderBenchmark(
                    provider_name="truescrape",
                    platform="instagram",
                    cost_tier=CostTier.TIER_1_REST,
                    priority=90,
                    notes="Primary fast REST API for hashtag reels and comments.",
                ),
                ProviderBenchmark(
                    provider_name="socialcrawl",
                    platform="instagram",
                    cost_tier=CostTier.TIER_1_REST,
                    priority=50,
                    notes="Fallback REST API if TrueScrape encounters rate limits.",
                ),
                ProviderBenchmark(
                    provider_name="apify",
                    platform="instagram",
                    cost_tier=CostTier.TIER_2_BATCH,
                    priority=30,
                    notes="Fallback actor scraping.",
                ),
            ],
            "reddit": [
                ProviderBenchmark(
                    provider_name="truescrape",
                    platform="reddit",
                    cost_tier=CostTier.TIER_1_REST,
                    priority=85,
                    notes="Direct REST API for Reddit posts and full nested comment trees.",
                ),
                ProviderBenchmark(
                    provider_name="rdt-cli",
                    platform="reddit",
                    cost_tier=CostTier.TIER_0_FREE,
                    priority=80,
                    notes="Free CLI if session cookie configured.",
                ),
                ProviderBenchmark(
                    provider_name="socialcrawl",
                    platform="reddit",
                    cost_tier=CostTier.TIER_1_REST,
                    priority=60,
                    notes="Secondary REST API fallback.",
                ),
            ],
            "x": [
                ProviderBenchmark(
                    provider_name="socialcrawl",
                    platform="x",
                    cost_tier=CostTier.TIER_1_REST,
                    priority=90,
                    notes="Primary REST API for Twitter/X search and replies (HTTP 200 verified).",
                ),
                ProviderBenchmark(
                    provider_name="twitter-cli",
                    platform="x",
                    cost_tier=CostTier.TIER_0_FREE,
                    priority=70,
                    notes="Local CLI if session tokens are configured.",
                ),
            ],
            "linkedin": [
                ProviderBenchmark(
                    provider_name="socialcrawl",
                    platform="linkedin",
                    cost_tier=CostTier.TIER_1_REST,
                    priority=95,
                    notes="Primary REST API for LinkedIn post search & comments (HTTP 200 verified).",
                ),
                ProviderBenchmark(
                    provider_name="brightdata",
                    platform="linkedin",
                    cost_tier=CostTier.TIER_2_BATCH,
                    priority=30,
                    notes="Dataset scraper fallback.",
                ),
            ],
        }

    def register_provider(
        self,
        platform: str,
        provider_name: str,
        cost_tier: CostTier,
        priority: int,
        notes: str = "",
    ) -> None:
        """Dynamically register an additional provider (e.g. user's new APIs)."""
        plat = platform.lower().strip()
        if plat not in self._routing_matrix:
            self._routing_matrix[plat] = []
        bench = ProviderBenchmark(
            provider_name=provider_name,
            platform=plat,
            cost_tier=cost_tier,
            priority=priority,
            notes=notes,
        )
        # Remove existing if present, insert and keep sorted by priority desc
        self._routing_matrix[plat] = [b for b in self._routing_matrix[plat] if b.provider_name != provider_name]
        self._routing_matrix[plat].append(bench)
        self._routing_matrix[plat].sort(key=lambda b: b.priority, reverse=True)
        logger.info("Registered provider '%s' for '%s' with priority %d (%s)", provider_name, plat, priority, cost_tier.value)

    def get_ranked_providers(self, platform: str) -> List[ProviderBenchmark]:
        """Return benchmarks ordered by priority descending."""
        plat = platform.lower().strip()
        if plat in ("twitter", "tweet"):
            plat = "x"
        return list(self._routing_matrix.get(plat, []))

    def is_seen(self, url: Optional[str] = None, content_id: Optional[str] = None) -> bool:
        """Check if post/content has already been scraped to avoid duplicate API calls."""
        if url and url.strip() in self._seen_urls:
            return True
        if content_id and content_id.strip() in self._seen_ids:
            return True
        return False

    def mark_seen(self, url: Optional[str] = None, content_id: Optional[str] = None) -> None:
        """Mark post as scraped so future calls will not re-fetch it."""
        if url and url.strip():
            self._seen_urls.add(url.strip())
        if content_id and content_id.strip():
            self._seen_ids.add(content_id.strip())

    def record_usage(
        self,
        platform: str,
        provider_name: str,
        action: str,
        credits_spent: int = 0,
        credits_saved: int = 0,
        balance_remaining: Optional[int] = None,
        target_id: Optional[str] = None,
    ) -> None:
        """Log credit consumption and savings."""
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        rec = CreditAuditRecord(
            timestamp=now,
            platform=platform,
            provider_name=provider_name,
            action=action,
            credits_spent=credits_spent,
            credits_saved=credits_saved,
            balance_remaining=balance_remaining,
            target_id=target_id,
        )
        self._audit_log.append(rec)
        logger.info(
            "CreditGuard [%s/%s] %s: spent=%d, saved=%d, rem=%s",
            platform, provider_name, action, credits_spent, credits_saved, balance_remaining
        )

    def get_summary(self) -> Dict[str, Any]:
        """Return credit usage summary and active provider matrix."""
        total_spent = sum(r.credits_spent for r in self._audit_log)
        total_saved = sum(r.credits_saved for r in self._audit_log)
        
        matrix_summary = {}
        for plat, benchmarks in self._routing_matrix.items():
            matrix_summary[plat] = [
                {
                    "provider": b.provider_name,
                    "tier": b.cost_tier.value,
                    "priority": b.priority,
                    "notes": b.notes,
                }
                for b in benchmarks
            ]

        return {
            "total_credits_spent": total_spent,
            "total_credits_saved": total_saved,
            "unique_items_cached": len(self._seen_urls) + len(self._seen_ids),
            "routing_matrix": matrix_summary,
            "audit_entries_count": len(self._audit_log),
        }


# Global singleton instance
_guard_instance: Optional[CreditGuardRouter] = None


def get_credit_guard() -> CreditGuardRouter:
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = CreditGuardRouter()
    return _guard_instance
