"""SocialCrawl API client for cross-platform social intelligence.

Isolates HTTP communication with the SocialCrawl REST API (https://www.socialcrawl.dev/v1).
Authenticates via the 'x-api-key' header.
Tracks credit consumption in real-time to avoid wasting user credits.
"""

import logging
import re
from typing import Any, Dict, List, Optional
import httpx

from server.config import Settings, get_settings

logger = logging.getLogger("mcp_server.providers.socialcrawl.client")


class SocialCrawlError(Exception):
    """Base exception for SocialCrawl client and API errors."""
    pass


class SocialCrawlAuthenticationError(SocialCrawlError):
    """Raised when SocialCrawl authentication fails (HTTP 401/403)."""
    pass


class SocialCrawlRateLimitError(SocialCrawlError):
    """Raised when SocialCrawl quota/rate limit is exceeded (HTTP 429)."""
    pass


class SocialCrawlClient:
    """Async client for interacting with the SocialCrawl REST API."""

    DEFAULT_BASE_URL = "https://www.socialcrawl.dev/v1"
    DEFAULT_TIMEOUT = 30.0
    USER_AGENT = "SocialRadar-SocialCrawl-Client/1.0"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        cfg = settings or get_settings()
        self._api_key = api_key or getattr(cfg, "socialcrawl_api_key", None)
        raw_base = (base_url or getattr(cfg, "socialcrawl_base_url", None) or self.DEFAULT_BASE_URL).rstrip("/")
        if not raw_base.endswith("/v1"):
            raw_base = f"{raw_base}/v1"
        self.base_url = raw_base
        self.timeout = timeout if timeout is not None else self.DEFAULT_TIMEOUT
        self._client = client
        self.last_credits_remaining: Optional[int] = None
        self.total_credits_used: int = 0

    @property
    def is_configured(self) -> bool:
        """Return True if an API key is available."""
        return bool(self._api_key and self._api_key.strip())

    @property
    def headers(self) -> Dict[str, str]:
        """HTTP headers including x-api-key authentication."""
        hdrs: Dict[str, str] = {
            "Accept": "application/json",
            "User-Agent": self.USER_AGENT,
        }
        if self._api_key:
            hdrs["x-api-key"] = self._api_key.strip()
        return hdrs

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._client and not self._client.is_closed:
            return self._client
        return httpx.AsyncClient(timeout=self.timeout)

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute HTTP request with authentication and credit tracking."""
        if not self.is_configured:
            raise SocialCrawlAuthenticationError("SocialCrawl API key is not configured. Set SOCIALCRAWL_API_KEY.")

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}

        client = self._get_http_client()
        should_close = client != self._client

        try:
            response = await client.request(
                method=method.upper(),
                url=url,
                headers=self.headers,
                params=clean_params or None,
                json=json_data,
                timeout=self.timeout,
            )

            # Track credits from response headers or body
            rem_hdr = response.headers.get("x-credits-remaining")
            if rem_hdr and rem_hdr.isdigit():
                self.last_credits_remaining = int(rem_hdr)

            if response.status_code in (401, 403):
                raise SocialCrawlAuthenticationError(f"SocialCrawl authentication failed ({response.status_code}): {response.text}")
            elif response.status_code == 429:
                raise SocialCrawlRateLimitError(f"SocialCrawl quota/rate limit exceeded: {response.text}")
            elif response.status_code >= 400:
                raise SocialCrawlError(f"SocialCrawl API error ({response.status_code}): {response.text}")

            payload = response.json()
            if isinstance(payload, dict):
                credits_used = payload.get("credits_used")
                if isinstance(credits_used, int):
                    self.total_credits_used += credits_used
                credits_rem = payload.get("credits_remaining")
                if isinstance(credits_rem, int):
                    self.last_credits_remaining = credits_rem
            return payload

        except httpx.TimeoutException as exc:
            raise SocialCrawlError(f"SocialCrawl request timed out: {exc}") from exc
        except httpx.RequestError as exc:
            raise SocialCrawlError(f"SocialCrawl request error: {exc}") from exc
        finally:
            if should_close and not client.is_closed:
                await client.aclose()

    async def credit_balance(self) -> Optional[int]:
        """Credits left on the account, at no cost.

        SocialCrawl validates a request before billing it and reports `credits_remaining` in the error body,
        so a deliberately invalid request is a free balance check. Returns None if the balance cannot be read.
        """
        try:
            await self._request("GET", "/linkedin/post/comments", params={"url": "balance-check"})
        except SocialCrawlAuthenticationError:
            raise
        except SocialCrawlError as exc:
            m = re.search(r'"credits_remaining"\s*:\s*(\d+)', str(exc))
            return int(m.group(1)) if m else (0 if "INSUFFICIENT_CREDITS" in str(exc) else None)
        return self.last_credits_remaining

    # ---- Twitter / X Endpoints ----
    async def search_tweets(self, query: str, limit: int = 20, cursor: Optional[str] = None) -> Dict[str, Any]:
        """Search Twitter/X posts matching query."""
        params = {"query": query, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/twitter/search/tweets", params=params)

    async def get_tweet_replies(self, tweet_url: str, cursor: Optional[str] = None) -> Dict[str, Any]:
        """Fetch replies/comments for a specific tweet URL."""
        params = {"url": tweet_url}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/twitter/tweet/replies", params=params)

    # ---- LinkedIn Endpoints ----
    async def search_linkedin_posts(self, query: str, limit: int = 20, cursor: Optional[str] = None) -> Dict[str, Any]:
        """Search public LinkedIn posts matching query."""
        params = {"query": query, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/linkedin/search/posts", params=params)

    async def get_linkedin_comments(self, post_url: str, cursor: Optional[str] = None) -> Dict[str, Any]:
        """Fetch comments for a public LinkedIn post URL."""
        params = {"url": post_url}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/linkedin/post/comments", params=params)

    # ---- Reddit Endpoints ----
    async def search_reddit(self, query: str, limit: int = 20, cursor: Optional[str] = None) -> Dict[str, Any]:
        """Search Reddit posts matching query."""
        params = {"query": query, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/reddit/search", params=params)

    async def get_reddit_comments(self, post_url: str, cursor: Optional[str] = None) -> Dict[str, Any]:
        """Fetch comments for a Reddit post URL."""
        params = {"url": post_url}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/reddit/post/comments", params=params)

    # ---- Instagram Endpoints ----
    async def search_instagram_hashtag(self, hashtag: str, limit: int = 20) -> Dict[str, Any]:
        """Search Instagram posts by hashtag."""
        tag = hashtag.lstrip("#")
        return await self._request("GET", "/instagram/search/hashtag", params={"hashtag": tag, "limit": limit})

    async def get_instagram_comments(self, post_url: str, cursor: Optional[str] = None) -> Dict[str, Any]:
        """Fetch comments for an Instagram post URL."""
        params = {"url": post_url}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/instagram/post/comments", params=params)
