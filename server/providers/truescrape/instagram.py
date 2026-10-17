"""TrueScrape Instagram provider for high-speed Instagram search, post details, and comments.

Provides direct REST-based access to TrueScrape's Instagram endpoints:
- /v1/instagram/popular-search
- /v1/instagram/post
- /v1/instagram/post-comments
- /v1/instagram/profile
"""

import logging
from typing import Any, Dict, List, Optional

from server.config import Settings, get_settings
from server.providers.truescrape.client import TrueScrapeClient, TrueScrapeError

logger = logging.getLogger("mcp_server.providers.truescrape.instagram")


class TrueScrapeInstagramProvider:
    """Instagram provider communicating with TrueScrape REST API."""

    def __init__(
        self,
        client: Optional[TrueScrapeClient] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        cfg = settings or get_settings()
        self.client = client or TrueScrapeClient(settings=cfg)
        self.settings = cfg

    def is_available(self) -> bool:
        """Check if TrueScrape client has a configured API key."""
        return self.client.is_configured

    async def search_posts_or_reels(
        self,
        query: str,
        max_results: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search public Instagram posts or reels for a query or hashtag.

        Uses TrueScrape's /v1/instagram/popular-search endpoint.
        """
        clean_query = query.strip()
        safe_limit = max(1, min(max_results, 50))

        logger.info(
            "[TRUESCRAPE_INSTAGRAM] Searching posts/reels for query=%r (limit=%d)",
            clean_query,
            safe_limit,
        )

        try:
            res = await self.client.get(
                "/v1/instagram/popular-search",
                params={"query": clean_query},
            )
        except TrueScrapeError as e:
            logger.warning("[TRUESCRAPE_INSTAGRAM] Popular search error for query=%r: %s", clean_query, e)
            return []

        raw_items = []
        if isinstance(res, dict):
            data = res.get("data")
            if isinstance(data, dict):
                raw_items = data.get("items") or []
            elif isinstance(data, list):
                raw_items = data

        formatted_items: List[Dict[str, Any]] = []
        for item in raw_items[:safe_limit]:
            if not isinstance(item, dict):
                continue
            # Format to unified fields expected by normalize_post_data
            url = item.get("url") or f"https://www.instagram.com/reel/{item.get('id', '')}/"
            formatted = {
                "id": item.get("id"),
                "shortCode": item.get("id"),
                "url": url,
                "postUrl": url,
                "type": item.get("type") or "reel",
                "caption": item.get("text") or item.get("title") or "",
                "text": item.get("text") or item.get("title") or "",
                "likesCount": item.get("likeCount", 0),
                "commentsCount": item.get("commentCount", 0),
                "videoViews": item.get("viewCount", 0),
                "timestamp": item.get("publishedAt"),
                "ownerId": item.get("authorId"),
                "ownerUsername": item.get("authorHandle"),
                "ownerFullName": item.get("authorName"),
                "author": {
                    "id": item.get("authorId"),
                    "username": item.get("authorHandle"),
                    "name": item.get("authorName"),
                },
                "thumbnailUrl": item.get("thumbnailUrl"),
                "raw": item,
            }
            formatted_items.append(formatted)

        logger.info(
            "[TRUESCRAPE_INSTAGRAM] Retrieved %d post(s) for query=%r",
            len(formatted_items),
            clean_query,
        )
        return formatted_items

    async def get_post_details(
        self,
        post_url: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch details of a single post or reel via /v1/instagram/post."""
        logger.info("[TRUESCRAPE_INSTAGRAM] Fetching post details for url=%s", post_url)
        try:
            res = await self.client.get(
                "/v1/instagram/post",
                params={"url": post_url},
            )
        except TrueScrapeError as e:
            logger.warning("[TRUESCRAPE_INSTAGRAM] Error fetching post details: %s", e)
            return None

        if isinstance(res, dict) and isinstance(res.get("data"), dict):
            item = res["data"]
            url = item.get("url") or post_url
            return {
                "id": item.get("id"),
                "shortCode": item.get("id"),
                "url": url,
                "postUrl": url,
                "type": item.get("type") or "reel",
                "caption": item.get("text") or item.get("title") or "",
                "text": item.get("text") or item.get("title") or "",
                "likesCount": item.get("likeCount", 0),
                "commentsCount": item.get("commentCount", 0),
                "videoViews": item.get("viewCount", 0),
                "timestamp": item.get("publishedAt"),
                "ownerId": item.get("authorId"),
                "ownerUsername": item.get("authorHandle"),
                "ownerFullName": item.get("authorName"),
                "author": {
                    "id": item.get("authorId"),
                    "username": item.get("authorHandle"),
                    "name": item.get("authorName"),
                },
                "thumbnailUrl": item.get("thumbnailUrl"),
                "raw": item,
            }
        return None

    async def get_post_comments(
        self,
        post_url: str,
        max_comments: int = 10,
    ) -> List[Dict[str, Any]]:
        """Fetch public comments for a post or reel via /v1/instagram/post-comments."""
        safe_limit = max(1, min(max_comments, 100))
        logger.info(
            "[TRUESCRAPE_INSTAGRAM] Fetching comments for url=%s (limit=%d)",
            post_url,
            safe_limit,
        )

        try:
            res = await self.client.get(
                "/v1/instagram/post-comments",
                params={
                    "url": post_url,
                    "count": safe_limit,
                },
            )
        except TrueScrapeError as e:
            logger.warning("[TRUESCRAPE_INSTAGRAM] Error fetching comments: %s", e)
            return []

        if isinstance(res, dict) and res.get("success") is False:
            err = res.get("error") or {}
            logger.warning("[TRUESCRAPE_INSTAGRAM] API error for %s: %s", post_url, err.get("message"))
            return []

        raw_items = []
        if isinstance(res, dict):
            data = res.get("data")
            if isinstance(data, dict):
                raw_items = data.get("items") or []
            elif isinstance(data, list):
                raw_items = data

        formatted_comments: List[Dict[str, Any]] = []
        for item in raw_items[:safe_limit]:
            if not isinstance(item, dict):
                continue
            author_id = item.get("authorId") or item.get("userId") or item.get("id")
            handle = (
                item.get("authorHandle")
                or item.get("username")
                or item.get("ownerUsername")
                or item.get("authorName")
                or (f"user_{author_id}" if author_id else None)
            )
            formatted = {
                "id": item.get("id") or item.get("comment_id"),
                "comment_id": item.get("id") or item.get("comment_id"),
                "text": item.get("text") or item.get("comment") or "",
                "likesCount": item.get("likeCount", 0),
                "replyCount": item.get("replyCount", 0),
                "timestamp": item.get("createdAt") or item.get("publishedAt"),
                "user": {
                    "id": author_id,
                    "username": handle,
                    "name": item.get("authorName") or item.get("name") or handle,
                    "profile_pic_url": item.get("authorAvatarUrl") or item.get("profilePicUrl") or item.get("avatarUrl"),
                },
                "raw": item,
            }
            formatted_comments.append(formatted)

        logger.info(
            "[TRUESCRAPE_INSTAGRAM] Retrieved %d comments for url=%s",
            len(formatted_comments),
            post_url,
        )
        return formatted_comments

    async def get_profile(
        self,
        handle: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch public profile metadata via /v1/instagram/profile."""
        clean_handle = handle.lstrip("@").strip()
        logger.info("[TRUESCRAPE_INSTAGRAM] Fetching profile for handle=%s", clean_handle)

        try:
            res = await self.client.get(
                "/v1/instagram/profile",
                params={"handle": clean_handle},
            )
        except TrueScrapeError as e:
            logger.warning("[TRUESCRAPE_INSTAGRAM] Error fetching profile: %s", e)
            return None

        if isinstance(res, dict) and isinstance(res.get("data"), dict):
            data = res["data"]
            return {
                "id": data.get("id"),
                "username": data.get("handle") or clean_handle,
                "display_name": data.get("displayName"),
                "bio": data.get("bio"),
                "profile_picture_url": data.get("avatarUrl"),
                "followers_count": data.get("followerCount"),
                "following_count": data.get("followingCount"),
                "posts_count": data.get("postCount"),
                "is_verified": data.get("isVerified", False),
            }
        return None
