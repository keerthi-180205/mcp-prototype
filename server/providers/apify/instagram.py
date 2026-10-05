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
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """Execute the Instagram post/reel search Actor via Apify API.

        Builds Actor-compatible search parameters and retrieves raw dataset items.
        """
        clean_tag = query.lstrip("#").replace(" ", "").lower()
        tag_url = f"https://www.instagram.com/explore/tags/{clean_tag}/"
        run_input: Dict[str, Any] = {
            "directUrls": [tag_url],
            "hashtags": [clean_tag],
            "resultsType": "posts",
            "resultsLimit": max_results,
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
