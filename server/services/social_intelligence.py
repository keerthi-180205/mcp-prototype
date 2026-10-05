"""Orchestrator service for Universal Social Intelligence and Outreach Data Platform."""

import logging
from typing import Any, Dict, List, Optional

from server.models import (
    NormalizedSocialRecord,
    SocialAuthor,
    SocialIntelligenceReport,
    SocialInteraction,
)
from server.providers.apify import (
    ApifyActorError,
    ApifyAuthenticationError,
    ApifyConnectionError,
    ApifyError,
    ApifyRateLimitError,
    ApifyTimeoutError,
)
from server.providers.social.registry import SocialProviderRegistry, get_social_registry
from server.services.filtering import (
    filter_by_recency,
    filter_by_relevance,
    generate_social_report,
    rank_social_candidates,
)
from server.storage.sqlite import get_social_records, save_social_records

logger = logging.getLogger("mcp_server.services.social_intelligence")


class SocialIntelligenceService:
    """
    Coordinates multi-platform discovery, provider routing,
    normalization, recency & relevance filtering, deduplication, and persistence.
    """

    def __init__(self, registry: Optional[SocialProviderRegistry] = None):
        self.registry = registry or get_social_registry()

    async def search_content(
        self,
        platform: str,
        topic: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        months_back: Optional[int] = 3,
        max_results: int = 10,
    ) -> List[NormalizedSocialRecord]:
        """Search and normalize content for a specific platform with recency filtering."""
        provider = self.registry.get_provider(platform)
        if not provider:
            logger.error("No provider registered for platform: %s", platform)
            return []

        records = await provider.search_content(query=topic, limit=max_results)

        # Apply recency filter
        if date_from or date_to or months_back:
            records = filter_by_recency(
                records, months_back=months_back, date_from=date_from, date_to=date_to
            )

        # Score relevance
        records = await filter_by_relevance(records, topic=topic, min_score=0.1)

        return records[:max_results]

    async def get_content(
        self, platform: str, content_url_or_id: str
    ) -> Optional[NormalizedSocialRecord]:
        """Fetch a specific post, video, or discussion."""
        provider = self.registry.get_provider(platform)
        if not provider:
            return None
        return await provider.get_content(content_url_or_id)

    async def get_comments(
        self, platform: str, content_url_or_id: str, max_comments: int = 20
    ) -> List[SocialInteraction]:
        """Fetch comments for a given piece of content."""
        provider = self.registry.get_provider(platform)
        if not provider:
            return []
        return await provider.get_comments(content_url_or_id, limit=max_comments)

    async def get_profile(
        self, platform: str, identifier: str
    ) -> Optional[SocialAuthor]:
        """Fetch public profile metadata."""
        provider = self.registry.get_provider(platform)
        if not provider:
            return None
        return await provider.get_profile(identifier)

    async def search_multi_platform(
        self,
        topic: str,
        platforms: Optional[List[str]] = None,
        months_back: int = 3,
        max_results_per_platform: int = 10,
        min_relevance: float = 0.2,
        auto_store: bool = True,
    ) -> List[NormalizedSocialRecord]:
        """
        Execute concurrent multi-platform discovery, normalize records,
        apply recency and relevance filters, deduplicate, and store results.
        """
        raw_records = await self.registry.search_multi_platform(
            topic=topic,
            platforms=platforms,
            max_per_platform=max_results_per_platform,
        )

        # Recency filtering
        recent_records = filter_by_recency(raw_records, months_back=months_back)

        # Relevance filtering
        relevant_records = await filter_by_relevance(
            recent_records, topic=topic, min_score=min_relevance
        )

        # Auto persistence and deduplication
        if auto_store and relevant_records:
            save_social_records(relevant_records)

        return relevant_records

    async def search_social_topic(
        self,
        query: str,
        platform: str = "instagram",
        top_n: int = 20,
        comments_per_content: int = 20,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        days_back: Optional[int] = None,
        min_relevance: float = 0.0,
        auto_store: bool = True,
    ) -> Dict[str, Any]:
        """
        High-level universal social search tool.
        Accepts a natural language query with NO content URL required.
        Discovers, ranks, selects top N, fetches public comments/commenters,
        deduplicates, filters, attaches provenance, and returns normalized schema.
        """
        # STEP 1: Validate input
        if not query or not query.strip():
            return {
                "status": "error",
                "error_type": "invalid_query",
                "message": "Search query cannot be empty",
                "query": query or "",
                "platform": platform or "instagram",
                "results": [],
            }

        clean_query = query.strip()
        platform_norm = (platform or "instagram").strip().lower()
        safe_top_n = max(1, min(top_n, 50))
        safe_comments = max(1, min(comments_per_content, 50))

        # STEP 2: Provider lookup
        provider = self.registry.get_provider(platform_norm)
        if not provider:
            return {
                "status": "error",
                "error_type": "provider_unavailable",
                "message": f"No provider registered for platform: {platform_norm}",
                "query": clean_query,
                "platform": platform_norm,
                "results": [],
            }

        if not provider.is_available():
            return {
                "status": "error",
                "error_type": "provider_unavailable",
                "message": f"Provider for '{platform_norm}' is not configured or credentials missing",
                "query": clean_query,
                "platform": platform_norm,
                "results": [],
            }

        # STEP 3, 4, 5: Discover candidate posts/reels
        fetch_limit = min(50, max(safe_top_n * 2, 20))
        try:
            candidates = await provider.search_content(query=clean_query, limit=fetch_limit)
        except ApifyAuthenticationError as exc:
            logger.error("Authentication failed during discovery for %r: %s", clean_query, exc)
            return {
                "status": "error",
                "error_type": "authentication_required",
                "message": f"Authentication failed for {platform_norm} provider: {exc}",
                "query": clean_query,
                "platform": platform_norm,
                "results": [],
            }
        except ApifyRateLimitError as exc:
            logger.warning("Rate limit hit during discovery for %r: %s", clean_query, exc)
            return {
                "status": "error",
                "error_type": "rate_limited",
                "message": f"Rate limit reached on {platform_norm} provider: {exc}",
                "query": clean_query,
                "platform": platform_norm,
                "results": [],
            }
        except ApifyTimeoutError as exc:
            logger.warning("Timeout during discovery for %r: %s", clean_query, exc)
            return {
                "status": "error",
                "error_type": "timeout",
                "message": f"Request timed out while querying {platform_norm}: {exc}",
                "query": clean_query,
                "platform": platform_norm,
                "results": [],
            }
        except (ApifyConnectionError, ApifyActorError, ApifyError) as exc:
            logger.error("Provider error during discovery for %r: %s", clean_query, exc)
            return {
                "status": "error",
                "error_type": "provider_error",
                "message": f"Provider failure for {platform_norm}: {exc}",
                "query": clean_query,
                "platform": platform_norm,
                "results": [],
            }
        except Exception as exc:
            logger.error("Unexpected discovery error for %r: %s", clean_query, exc, exc_info=True)
            return {
                "status": "error",
                "error_type": "internal_error",
                "message": f"Discovery failed unexpectedly: {exc}",
                "query": clean_query,
                "platform": platform_norm,
                "results": [],
            }

        if not candidates:
            return {
                "status": "success",
                "query": clean_query,
                "platform": platform_norm,
                "total_found": 0,
                "results": [],
                "message": f"No content found for query '{clean_query}'",
            }

        # Deduplicate candidate posts on (platform, content_id)
        seen_candidate_ids = set()
        deduped_candidates: List[NormalizedSocialRecord] = []
        for c in candidates:
            cid = (c.platform, c.content_id)
            if cid not in seen_candidate_ids:
                seen_candidate_ids.add(cid)
                deduped_candidates.append(c)

        # STEP 11/12: Recency filtering
        if date_from or date_to or days_back is not None:
            deduped_candidates = filter_by_recency(
                deduped_candidates,
                days_back=days_back,
                date_from=date_from,
                date_to=date_to,
                months_back=None,
            )

        # STEP 6: Rank candidates
        ranked_candidates = rank_social_candidates(deduped_candidates, query=clean_query)

        if min_relevance > 0.0:
            ranked_candidates = [
                r for r in ranked_candidates if (r.relevance_score or 0.0) >= min_relevance
            ]

        # STEP 7: Select top N
        selected_records = ranked_candidates[:safe_top_n]

        # STEP 8, 9, 10: Retrieve public comments & commenter information
        for record in selected_records:
            if safe_comments > 0:
                try:
                    comments = await provider.get_comments(
                        record.source_url or record.content_id, limit=safe_comments
                    )
                    # Deduplicate comments on interaction_id / text
                    seen_comment_keys = set()
                    deduped_comments = []
                    for c in comments:
                        c_key = c.interaction_id or c.text.strip().lower()[:50]
                        if c_key not in seen_comment_keys:
                            seen_comment_keys.add(c_key)
                            deduped_comments.append(c)
                    record.interactions = deduped_comments
                except Exception as c_exc:
                    logger.warning(
                        "Partial comment retrieval failed for content %s: %s",
                        record.source_url,
                        c_exc,
                    )
                    record.interactions = []

        # STEP 13 & Auto persistence
        if auto_store and selected_records:
            try:
                save_social_records(selected_records)
            except Exception as store_exc:
                logger.warning("Failed to store social records: %s", store_exc)

        # STEP 14: Structured response matching Section 14 normalized schema
        results: List[Dict[str, Any]] = []
        for idx, r in enumerate(selected_records):
            comments_list: List[Dict[str, Any]] = []
            for c in r.interactions:
                comments_list.append({
                    "comment_id": c.interaction_id,
                    "text": c.text,
                    "created_at": c.created_at,
                    "author": {
                        "username": c.author.username if c.author else None,
                        "user_id": c.author.user_id if c.author else None,
                        "full_name": c.author.display_name if c.author else None,
                        "profile_url": c.author.profile_url if c.author else None,
                    },
                    "likes": c.likes,
                    "reply_count": None,
                })

            results.append({
                "rank": idx + 1,
                "content_type": r.content_type,
                "content_id": r.content_id,
                "content_url": r.source_url,
                "author": {
                    "username": r.author.username if r.author else None,
                    "user_id": r.author.user_id if r.author else None,
                    "full_name": r.author.display_name if r.author else None,
                    "profile_url": r.author.profile_url if r.author else None,
                },
                "caption": r.content.caption or r.content.text,
                "published_at": r.published_at,
                "engagement": {
                    "likes": r.engagement.likes,
                    "comments": r.engagement.comments,
                    "views": r.engagement.views,
                    "shares": r.engagement.shares,
                },
                "comments": comments_list,
                "source": {
                    "provider": r.metadata.source_provider,
                    "backend": r.metadata.backend_tool or "apify/instagram-scraper",
                    "source_url": r.metadata.source_url or r.source_url,
                    "fetched_at": r.metadata.fetched_at,
                    "query": clean_query,
                },
            })

        return {
            "status": "success",
            "query": clean_query,
            "platform": platform_norm,
            "total_found": len(results),
            "results": results,
        }

    def store_records(self, records: List[NormalizedSocialRecord]) -> Dict[str, int]:
        """Persist records to SQLite with deduplication."""
        return save_social_records(records)

    def query_stored(
        self, platform: Optional[str] = None, topic: Optional[str] = None, limit: int = 50
    ) -> List[NormalizedSocialRecord]:
        """Query previously stored records."""
        return get_social_records(platform=platform, topic=topic, limit=limit)

    def generate_report(
        self, records: List[NormalizedSocialRecord], topic: str
    ) -> SocialIntelligenceReport:
        """Synthesize records into a structured executive report."""
        return generate_social_report(records, topic=topic)


_service_instance: Optional[SocialIntelligenceService] = None


def get_social_intelligence_service() -> SocialIntelligenceService:
    """Singleton accessor for SocialIntelligenceService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = SocialIntelligenceService()
    return _service_instance
