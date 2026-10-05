"""Instagram service layer for business logic, validation, and data normalization.

Decouples MCP tools from specific provider/scraping implementations.
Strictly adheres to public-data acquisition and privacy principles:
- Treats returned profile fields as public interaction metadata only.
- Does not attempt identity enrichment, de-anonymization, or sensitive-person classification.
- Handles missing or null fields gracefully without crashing.
"""

import re
from typing import Any, Dict, List, Optional

from server.logging_config import get_logger
from server.models import (
    InstagramAuthor,
    InstagramComment,
    InstagramCommentsResult,
    InstagramCommentUser,
    InstagramPost,
    InstagramTopicPostContent,
    InstagramTopicPostResult,
    InstagramTopicResearchResult,
)
from server.providers.apify.instagram import ApifyInstagramProvider

logger = get_logger(__name__)

# Regular expression pattern to validate public Instagram post or reel URLs
INSTAGRAM_URL_PATTERN = re.compile(
    r"^https?://(www\.)?instagram\.com/(p|reel|reels)/([A-Za-z0-9_-]+)/?.*$",
    re.IGNORECASE,
)


class InstagramServiceError(Exception):
    """Base exception for Instagram service errors."""
    pass


class InstagramValidationError(InstagramServiceError):
    """Raised when request parameters or Instagram URLs fail validation."""
    pass


def validate_instagram_url(url: str) -> str:
    """Validate that the given string is a public Instagram post or reel URL.

    Args:
        url: The candidate URL.

    Returns:
        The stripped, canonical URL.

    Raises:
        InstagramValidationError: If the URL is empty or does not match Instagram format.
    """
    if not url or not url.strip():
        raise InstagramValidationError("Instagram URL cannot be empty.")

    clean_url = url.strip()
    match = INSTAGRAM_URL_PATTERN.match(clean_url)
    if not match:
        raise InstagramValidationError(
            f"Invalid Instagram post or reel URL: '{clean_url}'. "
            "Supported formats: https://www.instagram.com/reel/<shortcode>/ or https://www.instagram.com/p/<shortcode>/"
        )
    return clean_url


def _safe_int(val: Any, default: int = 0) -> int:
    """Safely convert a value to integer."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def normalize_post_data(raw_item: Dict[str, Any]) -> InstagramPost:
    """Normalize a raw post or reel item returned by the provider into an InstagramPost model.

    Safely handles missing, renamed, or null fields.
    """
    if not isinstance(raw_item, dict):
        raw_item = {}

    # Extract content identifier (shortcode or id)
    content_id = (
        raw_item.get("id")
        or raw_item.get("shortCode")
        or raw_item.get("code")
        or raw_item.get("pk")
    )
    short_code = (
        raw_item.get("shortCode")
        or raw_item.get("code")
    )
    if short_code:
        short_code = str(short_code)

    # Extract canonical public URL
    raw_url = (
        raw_item.get("url")
        or raw_item.get("postUrl")
        or raw_item.get("webUrl")
        or raw_item.get("inputUrl")
    )

    if raw_url and ("/p/" in raw_url or "/reel/" in raw_url or "/reels/" in raw_url):
        url = raw_url
    elif short_code:
        url = f"https://www.instagram.com/reel/{short_code}/"
    elif content_id and not str(content_id).startswith("http") and not str(content_id).isalpha() and len(str(content_id)) > 5:
        url = f"https://www.instagram.com/reel/{content_id}/"
    elif raw_url:
        url = raw_url
    elif content_id:
        url = f"https://www.instagram.com/reel/{content_id}/"
    else:
        url = "https://www.instagram.com"

    # Detect content type
    raw_type = str(raw_item.get("type") or raw_item.get("contentType") or "").lower()
    if "reel" in raw_type or "/reel/" in url:
        content_type = "reel"
    elif raw_type in ("video", "clip"):
        content_type = "reel"
    elif raw_type in ("image", "sidecar", "post"):
        content_type = "post"
    else:
        content_type = "reel"

    # Extract caption
    caption = raw_item.get("caption") or raw_item.get("text") or None
    if isinstance(caption, dict):
        caption = caption.get("text")
    if caption:
        caption = str(caption)

    # Extract author details
    owner_data = raw_item.get("owner") or raw_item.get("author") or {}
    if not isinstance(owner_data, dict):
        owner_data = {}

    author_id = (
        raw_item.get("ownerId")
        or owner_data.get("id")
        or raw_item.get("userId")
    )
    author_username = (
        raw_item.get("ownerUsername")
        or owner_data.get("username")
        or raw_item.get("username")
    )
    author_name = (
        raw_item.get("ownerFullName")
        or owner_data.get("full_name")
        or owner_data.get("name")
    )

    author = None
    if author_id or author_username or author_name:
        author = InstagramAuthor(
            id=str(author_id) if author_id is not None else None,
            username=str(author_username) if author_username is not None else None,
            display_name=str(author_name) if author_name is not None else None,
        )

    # Extract creation timestamp
    created_at = (
        raw_item.get("timestamp")
        or raw_item.get("created_at")
        or raw_item.get("publishedAt")
        or raw_item.get("date")
    )
    if created_at is not None:
        created_at = str(created_at)

    # Extract metric counters
    like_count = _safe_int(
        raw_item.get("likesCount")
        or raw_item.get("likes")
        or raw_item.get("like_count")
    )
    comment_count = _safe_int(
        raw_item.get("commentsCount")
        or raw_item.get("comments")
        or raw_item.get("comment_count")
    )
    view_count = _safe_int(
        raw_item.get("videoViews")
        or raw_item.get("videoPlayCount")
        or raw_item.get("viewsCount")
        or raw_item.get("view_count")
        or raw_item.get("plays")
    )

    return InstagramPost(
        platform="instagram",
        content_type=content_type,
        content_id=content_id,
        url=str(url),
        caption=caption,
        author=author,
        created_at=created_at,
        like_count=like_count,
        comment_count=comment_count,
        view_count=view_count,
    )


def normalize_comment_data(raw_item: Dict[str, Any]) -> InstagramComment:
    """Normalize a raw comment item into an InstagramComment model.

    Only retains public fields legitimately provided by the provider.
    Never invents or enriches profile data.
    """
    if not isinstance(raw_item, dict):
        raw_item = {}

    comment_id = (
        raw_item.get("id")
        or raw_item.get("comment_id")
        or raw_item.get("pk")
    )
    if comment_id:
        comment_id = str(comment_id)

    # User / Commenter metadata
    user_dict = raw_item.get("user") or raw_item.get("owner") or {}
    if not isinstance(user_dict, dict):
        user_dict = {}

    u_id = (
        user_dict.get("id")
        or raw_item.get("ownerId")
        or raw_item.get("userId")
    )
    u_username = (
        user_dict.get("username")
        or raw_item.get("ownerUsername")
        or raw_item.get("username")
    )
    u_name = (
        user_dict.get("full_name")
        or user_dict.get("name")
        or raw_item.get("ownerFullName")
    )
    is_verified = bool(
        user_dict.get("is_verified")
        or user_dict.get("isVerified")
        or raw_item.get("isVerified")
        or False
    )
    is_private = bool(
        user_dict.get("is_private")
        or user_dict.get("isPrivate")
        or raw_item.get("isPrivate")
        or False
    )
    pic_url = (
        user_dict.get("profile_pic_url")
        or raw_item.get("ownerProfilePicUrl")
        or raw_item.get("profilePicUrl")
    )

    user = None
    if u_id or u_username or u_name or pic_url or is_verified or is_private:
        user = InstagramCommentUser(
            id=str(u_id) if u_id is not None else None,
            username=str(u_username) if u_username is not None else None,
            display_name=str(u_name) if u_name is not None else None,
            is_verified=is_verified,
            is_private=is_private,
            profile_picture_url=str(pic_url) if pic_url else None,
        )

    # Text content
    text = (
        raw_item.get("text")
        or raw_item.get("caption")
        or raw_item.get("comment")
    )
    if text is not None:
        text = str(text)

    # Timestamp
    created_at = (
        raw_item.get("timestamp")
        or raw_item.get("created_at")
        or raw_item.get("createdAt")
    )
    if created_at is not None:
        created_at = str(created_at)

    # Engagement counters
    like_count = _safe_int(
        raw_item.get("likesCount")
        or raw_item.get("likes")
        or raw_item.get("likeCount")
    )
    reply_count = _safe_int(
        raw_item.get("replyCount")
        or raw_item.get("repliesCount")
        or raw_item.get("childCommentsCount")
    )

    return InstagramComment(
        comment_id=comment_id,
        user=user,
        text=text,
        created_at=created_at,
        like_count=like_count,
        reply_count=reply_count,
    )


class InstagramService:
    """Service layer coordinating Instagram data acquisition and normalization."""

    def __init__(
        self,
        provider: Optional[ApifyInstagramProvider] = None,
    ) -> None:
        self.provider = provider or ApifyInstagramProvider()

    async def search_posts_or_reels(
        self,
        query: str,
        max_results: int = 5,
    ) -> List[InstagramPost]:
        """Search public Instagram posts/reels for a given topic query.

        Args:
            query: Topic or search keyword (e.g. 'mental health').
            max_results: Maximum number of results to retrieve.

        Returns:
            List of normalized InstagramPost objects.

        Raises:
            InstagramValidationError: If query is empty or limit is non-positive.
            ApifyError: If provider API or Actor execution fails.
        """
        if not query or not query.strip():
            raise InstagramValidationError("Search query cannot be empty.")
        if max_results <= 0:
            raise InstagramValidationError("max_results must be a positive integer.")

        clean_query = query.strip()
        raw_items = await self.provider.search_posts_or_reels(
            query=clean_query,
            max_results=max_results,
        )

        results: List[InstagramPost] = []
        for raw in raw_items:
            post = normalize_post_data(raw)
            if "/p/" in post.url or "/reel/" in post.url or "/reels/" in post.url:
                results.append(post)
            if len(results) >= max_results:
                break

        # Fallback if no specific post/reel URL pattern was matched
        if not results and raw_items:
            for raw in raw_items[:max_results]:
                results.append(normalize_post_data(raw))

        logger.info(
            "[INSTAGRAM_SERVICE] Retrieved and normalized %d post(s) for query=%r",
            len(results),
            clean_query,
        )
        return results

    async def get_post_comments(
        self,
        post_url: str,
        max_comments: int = 10,
    ) -> InstagramCommentsResult:
        """Retrieve public comments for a specific Instagram post or reel URL.

        Args:
            post_url: Canonical Instagram URL.
            max_comments: Maximum number of comments to retrieve.

        Returns:
            InstagramCommentsResult with normalized comments.

        Raises:
            InstagramValidationError: If URL is invalid or limit is non-positive.
            ApifyError: If provider API or Actor execution fails.
        """
        clean_url = validate_instagram_url(post_url)
        if max_comments <= 0:
            raise InstagramValidationError("max_comments must be a positive integer.")

        raw_items = await self.provider.get_post_comments(
            post_url=clean_url,
            max_comments=max_comments,
        )

        comments: List[InstagramComment] = []
        for raw in raw_items[:max_comments]:
            comment = normalize_comment_data(raw)
            comments.append(comment)

        logger.info(
            "[INSTAGRAM_SERVICE] Retrieved and normalized %d comment(s) for url=%s",
            len(comments),
            clean_url,
        )
        return InstagramCommentsResult(
            platform="instagram",
            content_url=clean_url,
            comments=comments,
        )

    async def research_topic(
        self,
        query: str,
        max_posts: int = 5,
        max_comments_per_post: int = 10,
    ) -> InstagramTopicResearchResult:
        """Execute the end-to-end flow: search posts for a topic and fetch comments for each post.

        Workflow:
        1. Search Instagram posts/reels using query (up to max_posts).
        2. Extract public URLs.
        3. For each URL, retrieve comments (up to max_comments_per_post).
        4. Normalize and structure into a single response.

        Args:
            query: Topic or search keyword (e.g. 'mental health').
            max_posts: Maximum number of posts/reels to retrieve.
            max_comments_per_post: Maximum comments to retrieve per post.

        Returns:
            InstagramTopicResearchResult.
        """
        if not query or not query.strip():
            raise InstagramValidationError("Search query cannot be empty.")
        if max_posts <= 0:
            raise InstagramValidationError("max_posts must be a positive integer.")
        if max_comments_per_post <= 0:
            raise InstagramValidationError("max_comments_per_post must be a positive integer.")

        posts = await self.search_posts_or_reels(
            query=query,
            max_results=max_posts,
        )

        topic_results: List[InstagramTopicPostResult] = []

        for post in posts:
            post_comments: List[InstagramComment] = []
            try:
                comments_res = await self.get_post_comments(
                    post_url=post.url,
                    max_comments=max_comments_per_post,
                )
                post_comments = comments_res.comments
            except Exception as exc:
                logger.warning(
                    "[INSTAGRAM_SERVICE] Could not retrieve comments for %s: %s",
                    post.url,
                    exc,
                )
                post_comments = []

            content_summary = InstagramTopicPostContent(
                url=post.url,
                type=post.content_type,
                caption=post.caption,
                author=post.author,
                created_at=post.created_at,
            )

            topic_results.append(
                InstagramTopicPostResult(
                    content=content_summary,
                    comments=post_comments,
                )
            )

        logger.info(
            "[INSTAGRAM_SERVICE] Completed topic research for query=%r: %d posts processed",
            query,
            len(topic_results),
        )

        return InstagramTopicResearchResult(
            query=query.strip(),
            platform="instagram",
            results=topic_results,
        )
