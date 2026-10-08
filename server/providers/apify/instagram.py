"""Apify Instagram provider for executing Instagram search and comments Actors.

Provides provider-level encapsulation of Actor invocation and payload structuring.
"""

from typing import Any, Dict, List, Optional

from server.config import Settings, get_settings
from server.logging_config import get_logger
from server.providers.apify.client import ApifyClient

logger = get_logger(__name__)


class ApifyInstagramProvider:
    """Instagram provider communicating with Apify Actors for search and comments."""

    def __init__(
        self,
        client: Optional[ApifyClient] = None,
        settings: Optional[Settings] = None,
        search_actor: Optional[str] = None,
        comments_actor: Optional[str] = None,
    ) -> None:
        cfg = settings or get_settings()
        self.client = client or ApifyClient(settings=cfg)
        self.search_actor = search_actor or cfg.apify_instagram_search_actor
        self.comments_actor = comments_actor or cfg.apify_instagram_comments_actor

    async def search_posts_or_reels(
        self,
        query: str,
        max_results: int = 20,
    ) -> List[Dict[str, Any]]:
        """Execute the Instagram post/reel search Actor via Apify API.

        Builds Actor-compatible search parameters and retrieves raw dataset items.
        """
        clean_tag = query.lstrip("#").replace(" ", "").lower()
        tag_url = f"https://www.instagram.com/explore/tags/{clean_tag}/"

        safe_limit = max(1, min(max_results, 50))
        run_input: Dict[str, Any] = {
            "directUrls": [tag_url],
            "resultsType": "posts",
            "resultsLimit": safe_limit,
        }

        logger.info(
            "[APIFY_INSTAGRAM] Searching Instagram posts/reels for query=%r with actor=%s, limit=%d",
            query,
            self.search_actor,
            max_results,
        )

        items = await self.client.run_actor_sync_get_dataset(
            actor_id=self.search_actor,
            run_input=run_input,
        )
        return items

    async def get_post_comments(
        self,
        post_url: str,
        max_comments: int = 10,
    ) -> List[Dict[str, Any]]:
        """Execute the Instagram comments scraper Actor via Apify API.

        Builds Actor-compatible comment parameters and retrieves raw dataset items.
        """
        run_input: Dict[str, Any] = {
            "directUrls": [post_url],
            "resultsType": "comments",
            "resultsLimit": max_comments,
        }

        logger.info(
            "[APIFY_INSTAGRAM] Fetching Instagram comments for url=%s with actor=%s, limit=%d",
            post_url,
            self.comments_actor,
            max_comments,
        )

        items = await self.client.run_actor_sync_get_dataset(
            actor_id=self.comments_actor,
            run_input=run_input,
        )
        return items

    async def search_hashtags(
        self,
        hashtags: List[str],
        results_per_tag: int,
        max_items: Optional[int] = None,
        max_total_charge_usd: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Discover recent posts for several hashtags in ONE Actor run (cheaper than one run per tag)."""
        urls = []
        for tag in hashtags:
            clean = tag.lstrip("#").replace(" ", "").lower()
            if clean:
                urls.append(f"https://www.instagram.com/explore/tags/{clean}/")
        if not urls:
            return []
        run_input: Dict[str, Any] = {
            "directUrls": urls,
            "resultsType": "posts",
            "resultsLimit": max(1, int(results_per_tag)),
        }
        logger.info("[APIFY_INSTAGRAM] Hashtag discovery tags=%d limit/tag=%d", len(urls), results_per_tag)
        return await self.client.run_actor_sync_get_dataset(
            actor_id=self.search_actor,
            run_input=run_input,
            max_items=max_items,
            max_total_charge_usd=max_total_charge_usd,
        )

    async def get_comments_batch(
        self,
        post_urls: List[str],
        comments_per_post: int,
        max_items: Optional[int] = None,
        max_total_charge_usd: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch comments for MANY posts in ONE Actor run (each run has a fixed cost)."""
        if not post_urls:
            return []
        run_input: Dict[str, Any] = {
            "directUrls": list(post_urls),
            "resultsLimit": max(1, int(comments_per_post)),
        }
        logger.info(
            "[APIFY_INSTAGRAM] Comment batch posts=%d limit/post=%d max_items=%s",
            len(post_urls), comments_per_post, max_items,
        )
        return await self.client.run_actor_sync_get_dataset(
            actor_id=self.comments_actor,
            run_input=run_input,
            max_items=max_items,
            max_total_charge_usd=max_total_charge_usd,
        )
