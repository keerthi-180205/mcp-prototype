"""GitHub data provider implementing repository discovery and resource inspection via the official REST API."""

import base64
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
import httpx

from server.config import Settings, get_settings
from server.logging_config import async_timed_operation, get_logger
from server.models import DatasetCandidate, RepositoryCandidate
from server.providers.base import RepositoryProvider
from server.resilience import retry_async_http

logger = get_logger(__name__)



class GitHubError(Exception):
    """Base exception for all GitHub provider errors."""
    pass


class GitHubAuthenticationError(GitHubError):
    """Raised when authentication fails (HTTP 401) or permissions are lacking."""
    pass


class GitHubRateLimitError(GitHubError):
    """Raised when GitHub API rate limit is exceeded (HTTP 403/429)."""
    pass


class GitHubTimeoutError(GitHubError):
    """Raised when a request to GitHub API times out."""
    pass


class GitHubConnectionError(GitHubError):
    """Raised when a network connection to GitHub API fails."""
    pass


class GitHubAPIError(GitHubError):
    """Raised when GitHub returns a generic API or validation error."""
    pass


class GitHubProvider(RepositoryProvider):
    """Provider for searching and retrieving repository metadata and documentation from the official GitHub REST API."""

    DEFAULT_BASE_URL = "https://api.github.com"
    DEFAULT_TIMEOUT = 20.0
    USER_AGENT = "MMTF-MCP-Client-Discovery/0.1"
    MAX_LIMIT = 100
    DEFAULT_LIMIT = 20

    # Recognized external dataset platforms
    PLATFORM_DOMAINS = {
        "huggingface.co": "Hugging Face",
        "hf.co": "Hugging Face",
        "kaggle.com": "Kaggle",
        "zenodo.org": "Zenodo",
        "figshare.com": "Figshare",
        "osf.io": "OSF",
        "drive.google.com": "Google Drive",
        "github.com": "GitHub",
    }

    # Keyword rules for data type classification
    DATA_TYPE_RULES = [
        (
            re.compile(r"\b(therapy|counseling|counselling|conversation|conversations|dialogue|dialogues|chat|chats|session|transcript|transcripts)\b", re.I),
            "conversation",
        ),
        (
            re.compile(r"\b(phq|gad|survey|surveys|questionnaire|questionnaires|assessment|assessments|depression scale|bdi|ces-d)\b", re.I),
            "mental_health_assessment",
        ),
        (
            re.compile(r"\b(emotion|emotions|sentiment|sentiments|affect|affective|mood|feeling|feelings)\b", re.I),
            "emotion",
        ),
        (
            re.compile(r"\b(tweet|tweets|twitter|reddit|weibo|post|posts|social media|forum|corpus|text|texts)\b", re.I),
            "text",
        ),
        (
            re.compile(r"\b(audio|speech|video|multimodal|facial|eeg|physiological|sensor)\b", re.I),
            "multimodal",
        ),
    ]

    # Keyword rules for privacy status detection
    PRIVACY_RULES = [
        (
            re.compile(r"\b(anonymi[zs]ed|anonymi[zs]ation|anonymi[zs]e)\b", re.I),
            "explicitly_anonymized",
        ),
        (
            re.compile(r"\b(de-identified|deidentified|de-identification|deidentification)\b", re.I),
            "explicitly_deidentified",
        ),
        (
            re.compile(r"\b(sensitive personal|distress warning|trigger warning|suicid|confidential|crisis content)\b", re.I),
            "contains_sensitive_data_warning",
        ),
    ]

    def __init__(
        self,
        token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
        settings: Optional[Settings] = None,
    ) -> None:
        """Initialize the GitHub provider."""
        cfg = settings or get_settings()
        self._token = token or cfg.github_token
        self.base_url = (base_url or cfg.github_api_base_url).rstrip("/")
        self.timeout = timeout if timeout is not None else cfg.github_timeout
        self._client = client

    @property
    def headers(self) -> Dict[str, str]:
        """Generate request headers with User-Agent and optional authentication."""
        hdrs = {
            "Accept": "application/vnd.github+json",
            "User-Agent": self.USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            hdrs["Authorization"] = f"Bearer {self._token}"
        return hdrs

    async def _send_request(self, url: str, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        """Execute an asynchronous HTTP request with retry logic on transient errors."""
        async def _make_call() -> httpx.Response:
            if self._client:
                return await self._client.get(url, params=params, headers=self.headers)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    return await client.get(url, params=params, headers=self.headers)

        try:
            return await retry_async_http(
                _make_call,
                operation_name="github_request",
            )
        except httpx.TimeoutException as exc:
            raise GitHubTimeoutError(f"Request to GitHub API timed out after {self.timeout}s") from exc
        except httpx.RequestError as exc:
            raise GitHubConnectionError(f"Failed to connect to GitHub API: {exc}") from exc


    def _check_response_status(self, response: httpx.Response) -> None:
        """Check for HTTP error statuses and raise appropriate typed exceptions."""
        status_code = response.status_code
        if status_code in (200, 404):
            return

        try:
            error_data = response.json()
            message = error_data.get("message", response.text)
        except Exception:
            message = response.text or f"HTTP {status_code}"

        if status_code == 401:
            raise GitHubAuthenticationError(f"GitHub authentication failed: {message}")

        if status_code in (403, 429):
            rate_remaining = response.headers.get("x-ratelimit-remaining")
            if rate_remaining == "0" or "rate limit" in message.lower():
                raise GitHubRateLimitError(f"GitHub API rate limit reached: {message}")
            raise GitHubAPIError(f"GitHub API access forbidden: {message}")

        if status_code == 422:
            raise GitHubAPIError(f"GitHub API validation failed: {message}")

        if status_code >= 500:
            raise GitHubAPIError(f"GitHub server-side error (HTTP {status_code}): {message}")

        raise GitHubAPIError(f"GitHub API returned unexpected status (HTTP {status_code}): {message}")

    def _build_search_query(
        self,
        query: str,
        updated_after: Optional[str] = None,
        language: Optional[str] = None,
    ) -> str:
        """Construct a validated GitHub search query string with qualifiers."""
        query_parts = [query.strip()]

        if updated_after:
            cleaned_date = updated_after.strip()
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", cleaned_date):
                raise ValueError(f"Invalid updated_after date format: '{updated_after}'. Expected YYYY-MM-DD.")
            query_parts.append(f"updated:>={cleaned_date}")

        if language:
            cleaned_lang = language.strip()
            if cleaned_lang:
                query_parts.append(f"language:{cleaned_lang}")

        return " ".join(query_parts)

    def _normalize_repository(self, item: Dict[str, Any]) -> RepositoryCandidate:
        """Normalize raw GitHub API repository JSON into a RepositoryCandidate model."""
        owner_data = item.get("owner") or {}
        license_data = item.get("license") or {}

        license_val = license_data.get("spdx_id")
        if not license_val or license_val == "NOASSERTION":
            license_val = license_data.get("name")

        return RepositoryCandidate(
            id=item["id"],
            name=item.get("name", ""),
            full_name=item.get("full_name", ""),
            owner=owner_data.get("login", ""),
            owner_type=owner_data.get("type", "User"),
            description=item.get("description"),
            html_url=item.get("html_url", ""),
            api_url=item.get("url", ""),
            language=item.get("language"),
            topics=item.get("topics") or [],
            stars=item.get("stargazers_count", 0),
            forks=item.get("forks_count", 0),
            open_issues=item.get("open_issues_count", 0),
            created_at=item.get("created_at", ""),
            updated_at=item.get("updated_at", ""),
            pushed_at=item.get("pushed_at"),
            license=license_val,
            default_branch=item.get("default_branch", "main"),
            archived=item.get("archived", False),
            fork=item.get("fork", False),
            source="github",
        )

    async def search_repositories(
        self,
        query: str,
        limit: int = 20,
        updated_after: Optional[str] = None,
        language: Optional[str] = None,
    ) -> List[RepositoryCandidate]:
        """Search for repositories matching the query and filtering criteria using the official GitHub REST API."""
        if not query or not query.strip():
            raise ValueError("Search query cannot be empty.")

        async with async_timed_operation(logger, component="github", operation="search", query=query.strip()) as op:
            effective_limit = max(1, min(limit, self.MAX_LIMIT))
            search_query = self._build_search_query(query, updated_after, language)

            url = f"{self.base_url}/search/repositories"
            params = {"q": search_query, "per_page": effective_limit}

            response = await self._send_request(url, params=params)
            self._check_response_status(response)

            try:
                data = response.json()
            except Exception as exc:
                raise GitHubAPIError("Invalid JSON response received from GitHub API") from exc

            items = data.get("items", [])
            results = [self._normalize_repository(item) for item in items[:effective_limit]]
            op.set_detail("count", len(results))
            return results


    async def get_repository_details(self, owner: str, repository: str) -> Optional[Dict[str, Any]]:
        """Fetch general repository metadata from GET /repos/{owner}/{repo}."""
        if not owner or not repository:
            raise ValueError("Owner and repository must be specified.")

        url = f"{self.base_url}/repos/{owner.strip()}/{repository.strip()}"
        response = await self._send_request(url)
        if response.status_code == 404:
            return None
        self._check_response_status(response)
        try:
            return response.json()
        except Exception as exc:
            raise GitHubAPIError("Invalid JSON response from repository details endpoint") from exc

    async def get_repository_readme(
        self,
        owner: str,
        repository: str,
    ) -> Optional[Dict[str, Any]]:
        """Fetch repository README metadata and decoded text content using GET /repos/{owner}/{repo}/readme."""
        if not owner or not repository:
            raise ValueError("Owner and repository must be specified.")

        async with async_timed_operation(logger, component="github", operation="readme", repo=f"{owner}/{repository}"):
            url = f"{self.base_url}/repos/{owner.strip()}/{repository.strip()}/readme"
            response = await self._send_request(url)
            if response.status_code == 404:
                return None

            self._check_response_status(response)


        try:
            data = response.json()
        except Exception as exc:
            raise GitHubAPIError("Invalid JSON response from README endpoint") from exc

        raw_content = data.get("content", "")
        encoding = data.get("encoding", "")

        decoded_text = ""
        if encoding == "base64" and raw_content:
            try:
                decoded_bytes = base64.b64decode(raw_content)
                decoded_text = decoded_bytes.decode("utf-8", errors="replace")
            except Exception:
                decoded_text = raw_content
        elif isinstance(raw_content, str):
            decoded_text = raw_content

        return {
            "name": data.get("name", "README.md"),
            "path": data.get("path", "README.md"),
            "size": data.get("size", len(decoded_text)),
            "html_url": data.get("html_url", ""),
            "download_url": data.get("download_url"),
            "content": decoded_text,
        }

    def _detect_platform(self, url: str) -> str:
        """Identify hosting platform from dataset URL domain."""
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            # Strip subdomains for matching where appropriate
            for plat_domain, plat_name in self.PLATFORM_DOMAINS.items():
                if domain == plat_domain or domain.endswith("." + plat_domain):
                    return plat_name
            return domain or "unknown"
        except Exception:
            return "unknown"

    def _classify_data_type(self, text_context: str) -> str:
        """Classify dataset data type deterministically based on keyword matching."""
        for pattern, dtype in self.DATA_TYPE_RULES:
            if pattern.search(text_context):
                return dtype
        return "research_data"

    def _detect_privacy_status(self, text_context: str) -> str:
        """Detect explicit privacy / anonymization status from text context."""
        for pattern, status in self.PRIVACY_RULES:
            if pattern.search(text_context):
                return status
        return "unknown"

    def _detect_license(
        self,
        text_context: str,
        repo_license: Optional[str],
        readme_text: str = "",
    ) -> Optional[str]:
        """Detect explicit license declarations in text or fall back to repository license."""
        lic_patterns = [
            (
                re.compile(
                    r"\b(CC[\s\-_]BY(?:[\s\-_](?:NC|SA|ND))*(?:[\s\-_]+[0-9]+(?:\.[0-9]+)?)?)\b",
                    re.I,
                ),
                r"\1",
            ),
            (re.compile(r"\b(Creative[\s]+Commons(?:\s+[A-Za-z0-9\-.]+)?)\b", re.I), r"\1"),
            (re.compile(r"\b(MIT(?:\s+License)?)\b", re.I), "MIT"),
            (re.compile(r"\b(Apache[\s\-]+2\.?0?)\b", re.I), "Apache-2.0"),
            (re.compile(r"\b(GPL[\s\-]?v?[23]\.?0?)\b", re.I), "GPL"),
            (re.compile(r"\b(ODC[\s\-_]By)\b", re.I), "ODC-By"),
        ]
        # 1. Check link text context
        for pattern, label in lic_patterns:
            match = pattern.search(text_context)
            if match:
                return match.group(1).strip()

        # 2. Check if README explicitly mentions dataset license
        if readme_text:
            dataset_lic_match = re.search(
                r"(?:dataset|data)\s+(?:is\s+)?licensed\s+under\s+([^\n\r]+)", readme_text, re.I
            )
            if dataset_lic_match:
                candidate_str = dataset_lic_match.group(1).strip().rstrip(".")
                for pattern, _ in lic_patterns:
                    m = pattern.search(candidate_str)
                    if m:
                        return m.group(1).strip()
                return candidate_str

        # 3. Fall back to repository license
        return repo_license

    def _detect_access_method(self, url: str, text_context: str) -> str:
        """Determine access method from URL and context."""
        if re.search(r"\b(form|request|application|agreement|permission|apply)\b", text_context, re.I):
            return "request_form"
        if "github.com" in url and any(sub in url for sub in ("/blob/", "/tree/", "/raw/", "/releases/")):
            return "repository_files"
        if url:
            return "external_link"
        return "unknown"

    async def inspect_repository_resources(
        self,
        owner: str,
        repository: str,
    ) -> List[DatasetCandidate]:
        """Inspect repository documentation/README and discover mental-health dataset candidates."""
        if not owner or not repository:
            raise ValueError("Owner and repository must be specified.")

        owner_clean = owner.strip()
        repo_clean = repository.strip()
        repo_full_name = f"{owner_clean}/{repo_clean}"
        repo_url = f"https://github.com/{repo_full_name}"

        async with async_timed_operation(logger, component="github", operation="inspect_resources", repo=repo_full_name) as op:
            results = await self._inspect_resources_internal(owner_clean, repo_clean, repo_full_name, repo_url)
            op.set_detail("count", len(results))
            return results

    async def _inspect_resources_internal(
        self,
        owner_clean: str,
        repo_clean: str,
        repo_full_name: str,
        repo_url: str,
    ) -> List[DatasetCandidate]:
        """Internal resource inspection logic."""
        # 1. Fetch repo details for context (license, default description)
        repo_details = await self.get_repository_details(owner_clean, repo_clean)
        repo_license = None
        repo_desc = ""
        if repo_details:
            lic_data = repo_details.get("license") or {}
            repo_license = lic_data.get("spdx_id")
            if not repo_license or repo_license == "NOASSERTION":
                repo_license = lic_data.get("name")
            repo_desc = repo_details.get("description") or ""

        # 2. Fetch README content
        readme_data = await self.get_repository_readme(owner_clean, repo_clean)
        if not readme_data or not readme_data.get("content"):
            return []


        readme_text = readme_data["content"]
        candidates: List[DatasetCandidate] = []
        seen_urls = set()

        # Overall repository privacy and license detection
        overall_privacy = self._detect_privacy_status(readme_text)

        # 3. Extract Markdown links: [Link Text](URL)
        md_links = re.findall(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)", readme_text)
        dataset_keywords = re.compile(
            r"\b(dataset|datasets|data|corpus|dialogue|dialogues|conversation|conversations|benchmark|download|zenodo|huggingface|kaggle|figshare|osf|survey|records|drive\.google)\b",
            re.I,
        )

        for link_text, link_url in md_links:
            clean_url = link_url.strip().rstrip(".,;)")
            if clean_url in seen_urls:
                continue

            platform = self._detect_platform(clean_url)
            is_dataset_domain = platform in ("Hugging Face", "Kaggle", "Zenodo", "Figshare", "OSF", "Google Drive")
            has_dataset_keyword = bool(dataset_keywords.search(link_text) or dataset_keywords.search(clean_url))

            if is_dataset_domain or has_dataset_keyword:
                seen_urls.add(clean_url)

                # Contextual evaluation around the link text
                text_context = f"{link_text} {clean_url}"
                data_type = self._classify_data_type(text_context)
                privacy_status = self._detect_privacy_status(text_context)
                if privacy_status == "unknown":
                    privacy_status = overall_privacy

                license_val = self._detect_license(text_context, repo_license, readme_text=readme_text)
                access_method = self._detect_access_method(clean_url, text_context)
                confidence = "high" if (is_dataset_domain or "dataset" in link_text.lower()) else "medium"

                candidate = DatasetCandidate(
                    name=link_text.strip(),
                    description=f"Referenced dataset link: '{link_text}' on {platform}",
                    data_type=data_type,
                    source_repository=repo_full_name,
                    source_repository_url=repo_url,
                    dataset_url=clean_url,
                    source_platform=platform,
                    license=license_val,
                    access_method=access_method,
                    discovered_from="README",
                    privacy_status=privacy_status,
                    confidence=confidence,
                    notes=f"Extracted from README link [{link_text}]({clean_url})",
                )
                candidates.append(candidate)

        # 4. If repository itself is a dedicated dataset/corpus repository, add it as a candidate if not already added
        is_repo_dataset = bool(
            dataset_keywords.search(repo_clean)
            or dataset_keywords.search(repo_desc)
            or re.search(r"#+\s*.*(dataset|corpus|data)", readme_text, re.I)
        )
        if is_repo_dataset and repo_url not in seen_urls:
            data_type = self._classify_data_type(f"{repo_clean} {repo_desc}")
            candidate = DatasetCandidate(
                name=repo_clean,
                description=repo_desc or f"Dataset repository {repo_full_name}",
                data_type=data_type,
                source_repository=repo_full_name,
                source_repository_url=repo_url,
                dataset_url=repo_url,
                source_platform="GitHub",
                license=repo_license,
                access_method="repository_files",
                discovered_from="README",
                privacy_status=overall_privacy,
                confidence="high",
                notes="Repository itself directly hosts or indexes mental-health dataset resources.",
            )
            candidates.append(candidate)

        return candidates
