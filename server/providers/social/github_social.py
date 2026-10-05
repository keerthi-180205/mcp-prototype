"""GitHub social & open source intelligence provider."""

import datetime
import logging
from typing import Any, Dict, List, Optional

from server.config import get_settings
from server.models import (
    NormalizedSocialRecord,
    ProvenanceMetadata,
    SocialAuthor,
    SocialContent,
    SocialEngagement,
    SocialInteraction,
)
from server.providers.github import GitHubProvider
from server.providers.social.base import SocialDataProvider

logger = logging.getLogger("mcp_server.providers.social.github")


class GitHubSocialProvider(SocialDataProvider):
    """
    Acquires public repositories, discussions, and open-source project discussions
    leveraging the existing official GitHub API provider.
    """

    platform_name = "github"
    provider_name = "github_api"

    def __init__(self, github_provider: Optional[GitHubProvider] = None):
        settings = get_settings()
        self.provider = github_provider or GitHubProvider(settings=settings)

    def is_available(self) -> bool:
        """GitHub is always available (rate-limited without token, higher limit with token)."""
        return True

    async def search_content(
        self, query: str, limit: int = 10, **kwargs: Any
    ) -> List[NormalizedSocialRecord]:
        """Search public GitHub repositories for a topic or keyword."""
        try:
            repos = await self.provider.search_repositories(query=query, per_page=limit)
        except Exception as e:
            logger.error("GitHub search failed: %s", e)
            return []

        records: List[NormalizedSocialRecord] = []
        now_iso = datetime.datetime.utcnow().isoformat() + "Z"

        for repo in repos:
            record_id = f"github:{repo.id}"
            author_url = f"https://github.com/{repo.owner}"
            record = NormalizedSocialRecord(
                record_id=record_id,
                platform="github",
                content_type="repository",
                source_url=repo.html_url,
                content_id=str(repo.id),
                published_at=repo.created_at,
                author=SocialAuthor(
                    username=repo.owner,
                    display_name=repo.owner,
                    profile_url=author_url,
                ),
                content=SocialContent(
                    title=repo.full_name,
                    text=repo.description or repo.name,
                    caption=repo.description,
                    tags=repo.topics,
                ),
                engagement=SocialEngagement(
                    likes=repo.stars,
                    shares=repo.forks,
                    comments=repo.open_issues,
                ),
                interactions=[],
                metadata=ProvenanceMetadata(
                    source_platform="github",
                    source_provider="github_api",
                    backend_tool="rest_v3",
                    fetched_at=now_iso,
                    source_url=repo.html_url,
                ),
            )
            records.append(record)

        return records

    async def get_content(
        self, content_url_or_id: str
    ) -> Optional[NormalizedSocialRecord]:
        """Retrieve repository details by owner/repo string or full URL."""
        slug = content_url_or_id.replace("https://github.com/", "").strip("/")
        parts = slug.split("/")
        if len(parts) < 2:
            return None
        owner, repo_name = parts[0], parts[1]

        try:
            repo = await self.provider.get_repository(owner, repo_name)
        except Exception as e:
            logger.error("Failed to get GitHub repo %s/%s: %s", owner, repo_name, e)
            return None

        now_iso = datetime.datetime.utcnow().isoformat() + "Z"
        return NormalizedSocialRecord(
            record_id=f"github:{repo.id}",
            platform="github",
            content_type="repository",
            source_url=repo.html_url,
            content_id=str(repo.id),
            published_at=repo.created_at,
            author=SocialAuthor(
                username=repo.owner,
                display_name=repo.owner,
                profile_url=f"https://github.com/{repo.owner}",
            ),
            content=SocialContent(
                title=repo.full_name,
                text=repo.description or repo.name,
                caption=repo.description,
                tags=repo.topics,
            ),
            engagement=SocialEngagement(
                likes=repo.stars,
                shares=repo.forks,
                comments=repo.open_issues,
            ),
            interactions=[],
            metadata=ProvenanceMetadata(
                source_platform="github",
                source_provider="github_api",
                backend_tool="rest_v3",
                fetched_at=now_iso,
                source_url=repo.html_url,
            ),
        )

    async def get_comments(
        self, content_url_or_id: str, limit: int = 20
    ) -> List[SocialInteraction]:
        """Issues act as interactions on repositories."""
        return []

    async def get_profile(
        self, identifier: str
    ) -> Optional[SocialAuthor]:
        """Get public user profile."""
        username = identifier.replace("https://github.com/", "").strip("@").strip("/")
        return SocialAuthor(
            username=username,
            profile_url=f"https://github.com/{username}",
        )
