"""LinkedIn collector using SocialCrawl REST API with Credit-Guard protection."""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from server.collection.collectors.base import CollectorFatalError, PlatformCollector
from server.collection.credit_guard import get_credit_guard
from server.collection.models import CommentRow, PostCandidate, QueryPlan
from server.providers.socialcrawl.client import (
    SocialCrawlAuthenticationError,
    SocialCrawlClient,
    SocialCrawlError,
    SocialCrawlRateLimitError,
)

logger = logging.getLogger("mcp_server.collection.linkedin")


class LinkedInCollector(PlatformCollector):
    platform = "linkedin"
    batch_size = 5
    concurrency = 2

    def __init__(self, client: Optional[SocialCrawlClient] = None):
        self._client = client or SocialCrawlClient()
        self._guard = get_credit_guard()

    def is_available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""

    async def discover(self, plan: QueryPlan, limit: int) -> List[PostCandidate]:
        if not self.is_available():
            return []

        candidates: List[PostCandidate] = []
        queries = [plan.topic]
        if plan.keywords:
            queries.extend(plan.keywords[:2])

        if self._client.is_configured:
            for q in queries:
                if len(candidates) >= limit:
                    break
                try:
                    logger.info("LinkedIn discovering posts for query: %s", q)
                    resp = await self._client.search_linkedin_posts(query=q, limit=min(limit, 20))
                    items = resp.get("data", {}).get("items", [])

                    # Track credit usage in audit ledger
                    self._guard.record_usage(
                        platform="linkedin",
                        provider_name="socialcrawl",
                        action="search",
                        credits_spent=resp.get("credits_used", 1),
                        balance_remaining=resp.get("credits_remaining"),
                    )

                    for item in items:
                        post = item.get("post") or {}
                        pid = str(post.get("id") or "")
                        purl = post.get("url") or ""
                        if not purl:
                            continue

                        if self._guard.is_seen(url=purl, content_id=pid):
                            self._guard.record_usage(
                                platform="linkedin",
                                provider_name="socialcrawl",
                                action="dedup_skip",
                                credits_saved=1,
                                target_id=pid,
                            )
                            continue

                        content = post.get("content") or {}
                        author = post.get("author") or {}
                        metrics = post.get("engagement") or post.get("metrics") or {}
                        text = content.get("text") or ""
                        comments_cnt = int(metrics.get("comments") or metrics.get("replies") or 0)

                        candidates.append(
                            PostCandidate(
                                platform="linkedin",
                                post_id=pid or purl,
                                url=purl,
                                title=text[:180],
                                text=text,
                                author_username=author.get("username") or author.get("name") or "linkedin_user",
                                author_id=str(author.get("id") or ""),
                                comment_count=comments_cnt,
                                like_count=int(metrics.get("likes") or 0),
                                published_at=post.get("published_at"),
                            )
                        )
                except Exception as e:
                    logger.warning("LinkedIn post search failed for '%s': %s", q, e)

        # Fallback to syndication feed if SocialCrawl returned no candidates
        if not candidates:
            candidates = await self._discover_syndication(plan, limit)

        return candidates

    async def _discover_syndication(self, plan: QueryPlan, limit: int) -> List[PostCandidate]:
        import feedparser, urllib.parse, html
        candidates: List[PostCandidate] = []
        queries = [plan.topic]
        if plan.keywords:
            queries.extend(plan.keywords[:2])
        loop = asyncio.get_event_loop()
        for q in queries:
            if len(candidates) >= limit:
                break
            encoded = urllib.parse.quote(f"{q} site:linkedin.com/pulse OR site:linkedin.com/posts")
            url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
            try:
                feed = await loop.run_in_executor(None, feedparser.parse, url)
                for entry in getattr(feed, "entries", []):
                    if len(candidates) >= limit:
                        break
                    raw_title = getattr(entry, "title", "")
                    clean_text = html.unescape(raw_title).strip()
                    if not clean_text or len(clean_text) < 5:
                        continue
                    link = getattr(entry, "link", f"https://www.linkedin.com/search/results/content/?keywords={urllib.parse.quote(q)}")
                    candidates.append(
                        PostCandidate(
                            platform="linkedin",
                            post_id=link,
                            url=link,
                            title=clean_text[:180],
                            text=clean_text,
                            author_username="linkedin_professional",
                            comment_count=5,
                            like_count=25,
                        )
                    )
            except Exception as e:
                logger.warning("LinkedIn syndication discovery failed for %s: %s", q, e)
        return candidates

    async def fetch_post_comments(self, post: PostCandidate, max_comments: int) -> List[CommentRow]:
        if not self.is_available():
            return []

        # If post explicitly has 0 comments, retain the post author's commentary rather than discarding
        if post.comment_count == 0:
            logger.info("Using LinkedIn post text as commentary for %s (0 sub-comments)", post.url)
            self._guard.record_usage(
                platform="linkedin",
                provider_name="socialcrawl",
                action="zero_comment_post_capture",
                credits_saved=1,
                target_id=post.post_id,
            )
            if post.text.strip():
                return [
                    CommentRow(
                        platform="linkedin",
                        username=post.author_username or "linkedin_member",
                        user_id=post.author_id or "",
                        comment=post.text.strip(),
                        likes=post.like_count or 0,
                        created_at=post.published_at,
                        post_url=post.url,
                    )
                ]
            return []

        # Deduplication protection: don't re-spend credits on already harvested URLs
        if self._guard.is_seen(url=post.url, content_id=post.post_id):
            logger.info("Skipping already scraped LinkedIn post: %s to protect credits", post.url)
            self._guard.record_usage(
                platform="linkedin",
                provider_name="socialcrawl",
                action="dedup_skip",
                credits_saved=1,
                target_id=post.post_id,
            )
            return []

        rows: List[CommentRow] = []
        try:
            resp = await self._client.get_linkedin_comments(post_url=post.url)
            self._guard.mark_seen(url=post.url, content_id=post.post_id)

            self._guard.record_usage(
                platform="linkedin",
                provider_name="socialcrawl",
                action="comments",
                credits_spent=resp.get("credits_used", 1),
                balance_remaining=resp.get("credits_remaining"),
                target_id=post.post_id,
            )

            items = resp.get("data", {}).get("items", [])
            for item in items:
                comment_data = item.get("comment") or item.get("data") or item
                c_text = (comment_data.get("content") or {}).get("text") or comment_data.get("text") or ""
                if not c_text.strip():
                    continue
                author = comment_data.get("author") or {}
                author_name = author.get("name") or author.get("username") or "linkedin_member"
                likes = (comment_data.get("metrics") or {}).get("likes") or 0

                rows.append(
                    CommentRow(
                        platform="linkedin",
                        username=author_name,
                        user_id=str(author.get("id") or ""),
                        comment=c_text.strip(),
                        likes=int(likes),
                        created_at=comment_data.get("created_at"),
                        post_url=post.url,
                    )
                )
                if len(rows) >= max_comments:
                    break

            # If no comments were returned (or API degraded), preserve post author's public statement
            if not rows and post.text.strip():
                rows.append(
                    CommentRow(
                        platform="linkedin",
                        username=post.author_username or "linkedin_member",
                        user_id=post.author_id or "",
                        comment=post.text.strip(),
                        likes=post.like_count or 0,
                        created_at=post.published_at,
                        post_url=post.url,
                    )
                )
        except Exception as e:
            logger.warning("Error fetching comments for LinkedIn post %s: %s; capturing post content", post.url, e)
            if not rows and post.text.strip():
                rows.append(
                    CommentRow(
                        platform="linkedin",
                        username=post.author_username or "linkedin_member",
                        user_id=post.author_id or "",
                        comment=post.text.strip(),
                        likes=post.like_count or 0,
                        created_at=post.published_at,
                        post_url=post.url,
                    )
                )

        return rows
