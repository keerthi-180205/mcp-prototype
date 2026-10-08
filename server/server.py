import shutil
from typing import Any, Dict, List, Optional

from server.config import get_settings
from server.logging_config import async_timed_operation, configure_logging, get_logger, timed_operation

configure_logging()
logger = get_logger("server")
settings = get_settings()


try:
    from mcp.server.fastmcp import FastMCP
except (ImportError, ModuleNotFoundError):
    from mcp.server.mcpserver import MCPServer as FastMCP

from server.providers.github import (
    GitHubProvider,
    GitHubAuthenticationError,
    GitHubRateLimitError,
    GitHubTimeoutError,
    GitHubConnectionError,
    GitHubAPIError,
)
from server.providers.huggingface import (
    HuggingFaceProvider,
    HuggingFaceNotFoundError,
    HuggingFaceAuthenticationError,
    HuggingFaceRateLimitError,
    HuggingFaceTimeoutError,
    HuggingFaceConnectionError,
    HuggingFaceError,
)
from server.providers.kaggle import (
    KaggleProvider,
    KaggleNotFoundError,
    KaggleAuthenticationError,
    KaggleRateLimitError,
    KaggleTimeoutError,
    KaggleConnectionError,
    KaggleError,
)
from server.providers.resolver import resolve_dataset_provider
from server.providers.zenodo import (
    ZenodoProvider,
    ZenodoNotFoundError,
    ZenodoAuthenticationError,
    ZenodoRateLimitError,
    ZenodoTimeoutError,
    ZenodoConnectionError,
    ZenodoError,
)
from server.validation.validator import DatasetValidator
from server.llm import (
    GeminiClient,
    GeminiError,
    GeminiConfigurationError,
    GeminiAuthenticationError,
    GeminiRateLimitError,
    GeminiTimeoutError,
    GeminiConnectionError,
    GeminiInvalidResponseError,
)
from server.providers.apify import (
    ApifyClient,
    ApifyInstagramProvider,
    ApifyError,
    ApifyAuthenticationError,
    ApifyActorError,
    ApifyRateLimitError,
    ApifyTimeoutError,
    ApifyConnectionError,
    ApifyEmptyDatasetError,
)
from server.services.instagram import (
    InstagramService,
    InstagramServiceError,
    InstagramValidationError,
)
from server.models import NormalizedSocialRecord
from server.services.filtering import (
    filter_by_relevance,
    generate_social_report as create_social_report,
    normalize_raw_social_data,
)
from server.services.social_intelligence import get_social_intelligence_service

# Initialize the MCP server with the service name
mcp = FastMCP("mmtf-client-discovery")

# Reusable platform provider instances
github_provider = GitHubProvider(settings=settings)
huggingface_provider = HuggingFaceProvider(settings=settings)
kaggle_provider = KaggleProvider(settings=settings)
zenodo_provider = ZenodoProvider(settings=settings)
dataset_validator = DatasetValidator()
gemini_client = GeminiClient(settings=settings)
apify_client = ApifyClient(settings=settings)
apify_instagram_provider = ApifyInstagramProvider(client=apify_client, settings=settings)
instagram_service = InstagramService(provider=apify_instagram_provider)
social_service = get_social_intelligence_service()



@mcp.tool()
def health_check() -> Dict[str, str]:
    """Check whether the MMTF MCP server is running."""
    return {
        "status": "ok",
        "service": "mmtf-client-discovery",
        "message": "MCP server is running successfully",
    }


@mcp.tool()
def readiness_check() -> Dict[str, Any]:
    """Check whether the MMTF MCP server and providers are configured and ready to accept requests.

    Inspects local configuration state without executing costly or blocking network requests.
    Exposes credential statuses without revealing secret values.
    """
    with timed_operation(logger, component="server", operation="readiness_check"):
        cfg = get_settings()

        github_auth = "configured" if cfg.github_token else "optional_unconfigured"
        hf_auth = "configured" if cfg.hf_token else "optional_unconfigured"
        kaggle_auth = "configured" if (cfg.kaggle_username and cfg.kaggle_key) else "missing"
        zenodo_auth = "configured" if cfg.zenodo_token else "optional_unconfigured"
        gemini_auth = "configured" if cfg.gemini_api_key else "missing"
        apify_auth = "configured" if cfg.apify_api_token else "optional_unconfigured"

        providers = {
            "github": {
                "status": "ready",
                "authentication": github_auth,
            },
            "huggingface": {
                "status": "ready",
                "authentication": hf_auth,
            },
            "kaggle": {
                "status": "ready" if kaggle_auth == "configured" else "not_ready",
                "authentication": kaggle_auth,
            },
            "zenodo": {
                "status": "ready",
                "authentication": zenodo_auth,
            },
            "gemini": {
                "status": "ready" if gemini_auth == "configured" else "not_ready",
                "authentication": gemini_auth,
            },
            "apify": {
                "status": "ready" if apify_auth == "configured" else "optional_unconfigured",
                "authentication": apify_auth,
            },
            "youtube": {
                "status": "ready" if shutil.which("yt-dlp") else "optional_unconfigured",
                "backend": "yt-dlp",
            },
        }

        # Overall readiness: ready if core providers can serve requests; not_ready if required configuration is missing
        is_ready = gemini_auth == "configured"
        overall_status = "ready" if is_ready else "not_ready"

        return {
            "status": overall_status,
            "environment": cfg.environment,
            "providers": providers,
        }



@mcp.tool()
async def search_mental_health_repositories(
    query: str,
    limit: int = 20,
    updated_after: Optional[str] = None,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """Search GitHub for publicly accessible repositories related to a specified mental-health topic or dataset query.

    Uses the official GitHub REST API to return normalized repository metadata (stars, forks, topics, license, etc.).
    Does not download repository files or datasets, and does not inspect README contents.
    """
    try:
        candidates = await github_provider.search_repositories(
            query=query,
            limit=limit,
            updated_after=updated_after,
            language=language,
        )
        return {
            "query": query,
            "count": len(candidates),
            "repositories": [candidate.model_dump() for candidate in candidates],
        }
    except GitHubRateLimitError:
        return {
            "error": "github_rate_limit",
            "message": "GitHub API rate limit reached",
        }
    except GitHubAuthenticationError:
        return {
            "error": "github_auth_error",
            "message": "GitHub API authentication failed",
        }
    except GitHubTimeoutError:
        return {
            "error": "github_timeout",
            "message": "GitHub API request timed out",
        }
    except GitHubConnectionError:
        return {
            "error": "github_connection_error",
            "message": "Failed to connect to GitHub API",
        }
    except GitHubAPIError as exc:
        return {
            "error": "github_api_error",
            "message": str(exc),
        }
    except ValueError as exc:
        return {
            "error": "invalid_parameter",
            "message": str(exc),
        }


@mcp.tool()
async def inspect_repository_resources(
    owner: str,
    repository: str,
) -> Dict[str, Any]:
    """Inspect a discovered GitHub repository's README documentation to identify referenced mental-health datasets.

    Extracts dataset candidates, platform sources (e.g. Hugging Face, Zenodo, Kaggle), data types, licenses,
    and explicit privacy/anonymization status from official repository documentation without downloading dataset contents.
    """
    try:
        candidates = await github_provider.inspect_repository_resources(
            owner=owner,
            repository=repository,
        )
        full_repo_name = f"{owner.strip()}/{repository.strip()}"
        logger.info(
            "[DISCOVERY] Found %d dataset reference(s) in repository %s",
            len(candidates),
            full_repo_name,
        )
        return {
            "repository": full_repo_name,
            "dataset_candidates_count": len(candidates),
            "dataset_candidates": [candidate.model_dump() for candidate in candidates],
        }
    except GitHubRateLimitError:
        return {
            "error": "github_rate_limit",
            "message": "GitHub API rate limit reached",
        }
    except GitHubAuthenticationError:
        return {
            "error": "github_auth_error",
            "message": "GitHub API authentication failed",
        }
    except GitHubTimeoutError:
        return {
            "error": "github_timeout",
            "message": "GitHub API request timed out",
        }
    except GitHubConnectionError:
        return {
            "error": "github_connection_error",
            "message": "Failed to connect to GitHub API",
        }
    except GitHubAPIError as exc:
        return {
            "error": "github_api_error",
            "message": str(exc),
        }
    except ValueError as exc:
        return {
            "error": "invalid_parameter",
            "message": str(exc),
        }


@mcp.tool()
async def resolve_dataset_metadata(
    dataset_url: str,
) -> Dict[str, Any]:
    """Retrieve normalized metadata for an external dataset resource using official platform APIs.

    Accepts a dataset URL (e.g. from Hugging Face, Kaggle, or Zenodo), deterministically resolves the provider,
    and retrieves structured metadata (license, tags, size, privacy indicators) without downloading dataset files.
    """
    if not dataset_url or not dataset_url.strip():
        return {
            "status": "error",
            "error": "invalid_parameter",
            "message": "Dataset URL cannot be empty.",
        }

    clean_url = dataset_url.strip()
    platform, identifier = resolve_dataset_provider(clean_url)

    if platform == "unknown" or not identifier:
        return {
            "status": "unsupported_provider",
            "error": "unsupported_platform",
            "message": f"URL '{clean_url}' does not correspond to a supported platform (Hugging Face, Kaggle, Zenodo).",
        }

    try:
        if platform == "huggingface":
            metadata = await huggingface_provider.get_dataset_metadata(identifier)
        elif platform == "kaggle":
            metadata = await kaggle_provider.get_dataset_metadata(identifier)
        elif platform == "zenodo":
            metadata = await zenodo_provider.get_dataset_metadata(identifier)
        else:
            return {
                "status": "unsupported_provider",
                "message": f"Platform '{platform}' is not supported.",
            }

        logger.info(
            "[METADATA] Retrieved metadata from %s API for dataset identifier '%s'",
            metadata.source_platform,
            metadata.identifier,
        )

        return {
            "status": "success",
            "provider": platform,
            "dataset": metadata.model_dump(),
        }

    except (HuggingFaceNotFoundError, KaggleNotFoundError, ZenodoNotFoundError) as exc:
        return {
            "status": "error",
            "provider": platform,
            "error": "not_found",
            "message": str(exc),
        }
    except (HuggingFaceAuthenticationError, KaggleAuthenticationError, ZenodoAuthenticationError) as exc:
        return {
            "status": "error",
            "provider": platform,
            "error": "auth_error",
            "message": str(exc),
        }
    except (HuggingFaceRateLimitError, KaggleRateLimitError, ZenodoRateLimitError) as exc:
        return {
            "status": "error",
            "provider": platform,
            "error": "rate_limit",
            "message": str(exc),
        }
    except (HuggingFaceTimeoutError, KaggleTimeoutError, ZenodoTimeoutError) as exc:
        return {
            "status": "error",
            "provider": platform,
            "error": "timeout",
            "message": str(exc),
        }
    except (HuggingFaceConnectionError, KaggleConnectionError, ZenodoConnectionError) as exc:
        return {
            "status": "error",
            "provider": platform,
            "error": "connection_error",
            "message": str(exc),
        }
    except (HuggingFaceError, KaggleError, ZenodoError) as exc:
        return {
            "status": "error",
            "provider": platform,
            "error": "api_error",
            "message": str(exc),
        }
    except ValueError as exc:
        return {
            "status": "error",
            "provider": platform,
            "error": "invalid_parameter",
            "message": str(exc),
        }


@mcp.tool()
async def validate_dataset(
    dataset_url: str,
) -> Dict[str, Any]:
    """Deterministically validate an external dataset's license, privacy/anonymization, sensitive warnings, and provenance.

    Resolves the platform, fetches official API metadata, and evaluates documented facts with evidence.
    Does NOT make legal/ethical conclusions, does NOT approve/reject datasets, and does NOT download dataset files.
    """
    if not dataset_url or not dataset_url.strip():
        return {
            "status": "error",
            "error": "invalid_parameter",
            "message": "Dataset URL cannot be empty.",
        }

    clean_url = dataset_url.strip()
    platform, identifier = resolve_dataset_provider(clean_url)

    if platform == "unknown" or not identifier:
        return {
            "status": "unsupported_provider",
            "error": "unsupported_platform",
            "message": f"URL '{clean_url}' does not correspond to a supported platform (Hugging Face, Kaggle, Zenodo).",
        }

    try:
        if platform == "huggingface":
            metadata = await huggingface_provider.get_dataset_metadata(identifier)
        elif platform == "kaggle":
            metadata = await kaggle_provider.get_dataset_metadata(identifier)
        elif platform == "zenodo":
            metadata = await zenodo_provider.get_dataset_metadata(identifier)
        else:
            return {
                "status": "unsupported_provider",
                "message": f"Platform '{platform}' is not supported.",
            }

        logger.info(
            "[METADATA] Retrieved metadata from %s API for validation",
            metadata.source_platform,
        )

        validation_result = dataset_validator.validate(metadata)

        return {
            "status": "success",
            "dataset": metadata.name,
            "provider": platform,
            "validation": validation_result.model_dump(),
        }

    except (HuggingFaceNotFoundError, KaggleNotFoundError, ZenodoNotFoundError) as exc:
        return {
            "status": "error",
            "provider": platform,
            "error": "not_found",
            "message": str(exc),
        }
    except (HuggingFaceAuthenticationError, KaggleAuthenticationError, ZenodoAuthenticationError) as exc:
        return {
            "status": "error",
            "provider": platform,
            "error": "auth_error",
            "message": str(exc),
        }
    except (HuggingFaceRateLimitError, KaggleRateLimitError, ZenodoRateLimitError) as exc:
        return {
            "status": "error",
            "provider": platform,
            "error": "rate_limit",
            "message": str(exc),
        }
    except (HuggingFaceTimeoutError, KaggleTimeoutError, ZenodoTimeoutError) as exc:
        return {
            "status": "error",
            "provider": platform,
            "error": "timeout",
            "message": str(exc),
        }
    except (HuggingFaceConnectionError, KaggleConnectionError, ZenodoConnectionError) as exc:
        return {
            "status": "error",
            "provider": platform,
            "error": "connection_error",
            "message": str(exc),
        }
    except (HuggingFaceError, KaggleError, ZenodoError) as exc:
        return {
            "status": "error",
            "provider": platform,
            "error": "api_error",
            "message": str(exc),
        }
    except ValueError as exc:
        return {
            "status": "error",
            "provider": platform,
            "error": "invalid_parameter",
            "message": str(exc),
        }


async def _fetch_metadata_and_validation(dataset_url: str):
    """Internal helper to resolve, fetch, and validate dataset metadata."""
    if not dataset_url or not dataset_url.strip():
        return None, None, None, {
            "status": "error",
            "error": "invalid_parameter",
            "message": "Dataset URL cannot be empty.",
        }

    clean_url = dataset_url.strip()
    platform, identifier = resolve_dataset_provider(clean_url)

    if platform == "unknown" or not identifier:
        return None, None, None, {
            "status": "unsupported_provider",
            "error": "unsupported_platform",
            "message": f"URL '{clean_url}' does not correspond to a supported platform (Hugging Face, Kaggle, Zenodo).",
        }

    try:
        if platform == "huggingface":
            metadata = await huggingface_provider.get_dataset_metadata(identifier)
        elif platform == "kaggle":
            metadata = await kaggle_provider.get_dataset_metadata(identifier)
        elif platform == "zenodo":
            metadata = await zenodo_provider.get_dataset_metadata(identifier)
        else:
            return None, None, None, {
                "status": "unsupported_provider",
                "message": f"Platform '{platform}' is not supported.",
            }

        validation = dataset_validator.validate(metadata)
        return platform, metadata, validation, None

    except (HuggingFaceNotFoundError, KaggleNotFoundError, ZenodoNotFoundError) as exc:
        return None, None, None, {
            "status": "error",
            "provider": platform,
            "error": "not_found",
            "message": str(exc),
        }
    except (HuggingFaceAuthenticationError, KaggleAuthenticationError, ZenodoAuthenticationError) as exc:
        return None, None, None, {
            "status": "error",
            "provider": platform,
            "error": "auth_error",
            "message": str(exc),
        }
    except (HuggingFaceRateLimitError, KaggleRateLimitError, ZenodoRateLimitError) as exc:
        return None, None, None, {
            "status": "error",
            "provider": platform,
            "error": "rate_limit",
            "message": str(exc),
        }
    except (HuggingFaceTimeoutError, KaggleTimeoutError, ZenodoTimeoutError) as exc:
        return None, None, None, {
            "status": "error",
            "provider": platform,
            "error": "timeout",
            "message": str(exc),
        }
    except (HuggingFaceConnectionError, KaggleConnectionError, ZenodoConnectionError) as exc:
        return None, None, None, {
            "status": "error",
            "provider": platform,
            "error": "connection_error",
            "message": str(exc),
        }
    except (HuggingFaceError, KaggleError, ZenodoError) as exc:
        return None, None, None, {
            "status": "error",
            "provider": platform,
            "error": "api_error",
            "message": str(exc),
        }
    except ValueError as exc:
        return None, None, None, {
            "status": "error",
            "provider": platform,
            "error": "invalid_parameter",
            "message": str(exc),
        }


def _handle_gemini_error(exc: Exception) -> Dict[str, Any]:
    """Map Gemini client exceptions to structured MCP error responses."""
    if isinstance(exc, GeminiConfigurationError):
        err_type = "configuration_error"
    elif isinstance(exc, GeminiAuthenticationError):
        err_type = "auth_error"
    elif isinstance(exc, GeminiRateLimitError):
        err_type = "rate_limit"
    elif isinstance(exc, GeminiTimeoutError):
        err_type = "timeout"
    elif isinstance(exc, GeminiConnectionError):
        err_type = "connection_error"
    elif isinstance(exc, GeminiInvalidResponseError):
        err_type = "invalid_response"
    else:
        err_type = "api_error"

    return {
        "status": "error",
        "provider": "gemini",
        "error_type": err_type,
        "message": str(exc),
    }


@mcp.tool()
async def summarize_dataset(
    dataset_url: str,
) -> Dict[str, Any]:
    """Generate a concise, objective summary of an external dataset using Gemini based strictly on documented metadata.

    Reuses metadata resolution and deterministic validation. Gemini does NOT invent facts or make legal conclusions.
    """
    platform, metadata, validation, err = await _fetch_metadata_and_validation(dataset_url)
    if err:
        return err

    try:
        summary = await gemini_client.summarize_dataset(metadata, validation)
        return {
            "status": "success",
            "dataset": metadata.name,
            "provider": platform,
            "summary": summary.model_dump(),
            "validation_status": validation.validation_status,
        }
    except Exception as exc:
        return _handle_gemini_error(exc)


@mcp.tool()
async def analyze_dataset_relevance(
    dataset_url: str,
) -> Dict[str, Any]:
    """Assess topical relevance of an external dataset for mental-health NLP research using Gemini.

    Evaluates relevance (high, medium, low, unknown) and categorizes dataset structure while preserving deterministic data_type.
    This is NOT a safety or legal score.
    """
    platform, metadata, validation, err = await _fetch_metadata_and_validation(dataset_url)
    if err:
        return err

    try:
        relevance = await gemini_client.assess_relevance(metadata, validation)
        classification = await gemini_client.classify_dataset(metadata, validation)
        return {
            "status": "success",
            "dataset": metadata.name,
            "provider": platform,
            "relevance": relevance.model_dump(),
            "category_classification": classification.model_dump(),
        }
    except Exception as exc:
        return _handle_gemini_error(exc)


@mcp.tool()
async def generate_dataset_report(
    dataset_url: str,
) -> Dict[str, Any]:
    """Generate a comprehensive human-readable dataset report synthesizing documented facts, validation findings, and Gemini interpretation."""
    platform, metadata, validation, err = await _fetch_metadata_and_validation(dataset_url)
    if err:
        return err

    try:
        report = await gemini_client.generate_dataset_report(metadata, validation)
        return {
            "status": "success",
            "dataset": metadata.name,
            "provider": platform,
            "report": report.model_dump(),
        }
    except Exception as exc:
        return _handle_gemini_error(exc)


# ==============================================================================
# Instagram & Apify MCP Tools
# ==============================================================================

def _handle_instagram_error(exc: Exception) -> Dict[str, Any]:
    """Map Instagram service and Apify provider exceptions to structured MCP error responses."""
    if isinstance(exc, InstagramValidationError):
        return {
            "error": "invalid_parameter",
            "message": str(exc),
        }
    elif isinstance(exc, ApifyAuthenticationError):
        return {
            "error": "apify_auth_error",
            "message": str(exc),
        }
    elif isinstance(exc, ApifyRateLimitError):
        return {
            "error": "apify_rate_limit",
            "message": "Apify API rate limit exceeded.",
        }
    elif isinstance(exc, ApifyTimeoutError):
        return {
            "error": "apify_timeout",
            "message": "Apify actor execution timed out.",
        }
    elif isinstance(exc, ApifyActorError):
        return {
            "error": "apify_actor_error",
            "message": str(exc),
        }
    elif isinstance(exc, ApifyConnectionError):
        return {
            "error": "apify_connection_error",
            "message": "Failed to connect to Apify API.",
        }
    elif isinstance(exc, (ApifyError, InstagramServiceError)):
        return {
            "error": "apify_error",
            "message": str(exc),
        }
    elif isinstance(exc, ValueError):
        return {
            "error": "invalid_parameter",
            "message": str(exc),
        }
    else:
        logger.error("[INSTAGRAM] Unexpected error: %s", exc, exc_info=True)
        return {
            "error": "internal_error",
            "message": "An unexpected error occurred during Instagram data processing.",
        }


@mcp.tool()
async def search_instagram_reels(
    query: str,
    max_results: int = 5,
) -> Dict[str, Any]:
    """Search public Instagram posts or reels for a topic or hashtag using Apify.

    Extracts public posts/reels and normalizes engagement counters, author details,
    and metadata without requiring login or session cookies.
    """
    try:
        posts = await instagram_service.search_posts_or_reels(
            query=query,
            max_results=max_results,
        )
        return {
            "platform": "instagram",
            "query": query,
            "count": len(posts),
            "results": [post.model_dump() for post in posts],
        }
    except Exception as exc:
        return _handle_instagram_error(exc)


@mcp.tool()
async def get_instagram_comments(
    post_url: str,
    max_comments: int = 10,
) -> Dict[str, Any]:
    """Retrieve public comments and publicly returned commenter profile fields for an Instagram post or reel URL.

    Accepts a public Instagram post or reel URL, executes the Apify comment scraper Actor,
    and normalizes the extracted comment thread. Does not access private accounts or DMs.
    """
    try:
        comments_result = await instagram_service.get_post_comments(
            post_url=post_url,
            max_comments=max_comments,
        )
        return comments_result.model_dump()
    except Exception as exc:
        return _handle_instagram_error(exc)


@mcp.tool()
async def research_instagram_topic(
    query: str,
    max_posts: int = 5,
    max_comments_per_post: int = 10,
) -> str:
    """End-to-end Instagram topic research demo.

    Searches public Instagram posts/reels for a topic query, extracts their public URLs,
    fetches comments for each discovered post, and returns a text summary sorted by top comment likes.
    """
    try:
        research_result = await instagram_service.research_topic(
            query=query,
            max_posts=max_posts,
            max_comments_per_post=max_comments_per_post,
        )
        
        scored_posts = []
        for result in research_result.results:
            max_likes = 0
            top_comment_text = "No comments found"
            if result.comments:
                # Find comment with most likes
                top_c = max(result.comments, key=lambda c: c.like_count or 0)
                max_likes = top_c.like_count or 0
                top_comment_text = top_c.text or ""
                
            scored_posts.append((max_likes, result.content, top_comment_text))
            
        # Sort descending by comment likes
        scored_posts.sort(key=lambda x: x[0], reverse=True)
        
        output = [f"Top trending Instagram posts for '{query}' based on comment likes:\n"]
        for idx, (likes, content, comment_text) in enumerate(scored_posts, 1):
            caption_short = (content.caption[:100] + "...") if content.caption else "No caption"
            output.append(f"{idx}. URL: {content.url}")
            output.append(f"   Caption: {caption_short}")
            output.append(f"   Top Comment Likes: {likes}")
            output.append(f"   Top Comment: {comment_text}")
            output.append("")
            
        return "\n".join(output)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Error in research_instagram_topic", exc_info=True)
        return f"Error during research: {str(exc)}"

@mcp.tool()
async def search_social_trending_comments(
    query: str,
    platform: str = "reddit",
    top_content: int = 20,
    top_comments: int = 1000,
) -> Dict[str, Any]:
    """Discover trending content on a social platform (e.g., youtube, reddit, instagram) for a query, 
    extract public comments across all posts, and return the top ranking comments based on likes.
    
    This tool dynamically searches for 'query', finds up to 'top_content' trending/relevant
    posts, retrieves public comments from all of them, deduplicates, sorts by comment likes,
    and returns up to 'top_comments' normalized comments.
    """
    try:
        # Step 1: Discover content and fetch comments automatically via orchestrator
        res = await social_service.search_social_topic(
            query=query,
            platform=platform,
            top_n=top_content,
            comments_per_content=min(200, max(50, top_comments // top_content + 10)),
            auto_store=False
        )
        
        if res.get("status") == "error":
            return res
            
        # Step 2: Collect, normalize, and deduplicate comments from all posts
        all_comments = []
        seen_comments = set()
        
        for post_res in res.get("results", []):
            post_url = post_res.get("content_url")
            for comment in post_res.get("comments", []):
                text = (comment.get("text") or "").strip()
                if not text:
                    continue
                author_info = comment.get("author", {})
                username = author_info.get("username") if author_info else "anonymous"
                likes = comment.get("likes") or 0
                
                # Deduplication by username + text
                dedup_key = f"{username}:{text}"
                if dedup_key not in seen_comments:
                    seen_comments.add(dedup_key)
                    all_comments.append({
                        "username": username,
                        "comment": text,
                        "likes": likes,
                        "post_url": post_url
                    })
                    
        # Step 3: Sort by likes DESC across ALL posts
        all_comments.sort(key=lambda x: x["likes"], reverse=True)
        
        # Step 4: Truncate to top_comments
        final_comments = all_comments[:top_comments]
        
        return {
            "status": "success",
            "query": query,
            "platform": platform,
            "trending_posts_analyzed": len(res.get("results", [])),
            "total_comments_extracted": len(all_comments),
            "returned_comments": len(final_comments),
            "comments": final_comments
        }
        
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Error in search_social_trending_comments", exc_info=True)
        return {
            "status": "error",
            "message": f"Social discovery failed: {str(exc)}"
        }


# ==============================================================================
# Universal Social Intelligence & Outreach MCP Tools
# ==============================================================================


@mcp.tool()
async def search_social_content(
    platform: str,
    topic: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    months_back: Optional[int] = 3,
    max_results: int = 10,
) -> Dict[str, Any]:
    """Search public content on any supported platform (instagram, youtube, github, web, rss, reddit, x)

    Normalizes output into a common schema, filters by recency and relevance,
    and returns verified public content without accessing private accounts.
    """
    try:
        records = await social_service.search_content(
            platform=platform,
            topic=topic,
            date_from=date_from,
            date_to=date_to,
            months_back=months_back,
            max_results=max_results,
        )
        return {
            "status": "success",
            "platform": platform,
            "topic": topic,
            "count": len(records),
            "results": [r.model_dump() for r in records],
        }
    except Exception as exc:
        logger.error("[SOCIAL] search_social_content error: %s", exc, exc_info=True)
        return {"status": "error", "message": str(exc), "platform": platform}


@mcp.tool()
async def get_social_content(
    platform: str,
    content_url: str,
) -> Dict[str, Any]:
    """Retrieve details, captions/transcripts, and metadata for a specific public post, reel, or video."""
    try:
        record = await social_service.get_content(platform=platform, content_url_or_id=content_url)
        if not record:
            return {
                "status": "not_found",
                "message": f"Content not found or platform '{platform}' provider unconfigured.",
            }
        return {"status": "success", "record": record.model_dump()}
    except Exception as exc:
        logger.error("[SOCIAL] get_social_content error: %s", exc, exc_info=True)
        return {"status": "error", "message": str(exc)}


@mcp.tool()
async def get_social_comments(
    platform: str,
    content_url: str,
    max_comments: int = 20,
) -> Dict[str, Any]:
    """Extract public comments and public commenter details from a post or reel without accessing private DMs."""
    try:
        comments = await social_service.get_comments(
            platform=platform, content_url_or_id=content_url, max_comments=max_comments
        )
        return {
            "status": "success",
            "platform": platform,
            "content_url": content_url,
            "count": len(comments),
            "comments": [c.model_dump() for c in comments],
        }
    except Exception as exc:
        logger.error("[SOCIAL] get_social_comments error: %s", exc, exc_info=True)
        return {"status": "error", "message": str(exc)}


@mcp.tool()
async def get_profile(
    platform: str,
    profile_identifier: str,
) -> Dict[str, Any]:
    """Retrieve public profile metadata for a username, handle, or URL across supported platforms."""
    try:
        profile = await social_service.get_profile(platform=platform, identifier=profile_identifier)
        if not profile:
            return {"status": "not_found", "message": f"Profile not found on platform '{platform}'."}
        return {"status": "success", "platform": platform, "profile": profile.model_dump()}
    except Exception as exc:
        logger.error("[SOCIAL] get_profile error: %s", exc, exc_info=True)
        return {"status": "error", "message": str(exc)}


@mcp.tool()
async def search_multi_platform(
    topic: str,
    platforms: Optional[List[str]] = None,
    months_back: int = 3,
    max_results_per_platform: int = 10,
    min_relevance: float = 0.2,
    auto_store: bool = True,
) -> Dict[str, Any]:
    """Execute simultaneous cross-platform discovery across Instagram, YouTube, GitHub, Web, etc.

    Normalizes all content to a single schema, applies timestamp recency filtering
    (e.g., last 3, 6, 12 months), scores relevance, and automatically deduplicates & stores in SQLite.
    """
    try:
        records = await social_service.search_multi_platform(
            topic=topic,
            platforms=platforms,
            months_back=months_back,
            max_results_per_platform=max_results_per_platform,
            min_relevance=min_relevance,
            auto_store=auto_store,
        )
        return {
            "status": "success",
            "topic": topic,
            "total_records": len(records),
            "records": [r.model_dump() for r in records],
        }
    except Exception as exc:
        logger.error("[SOCIAL] search_multi_platform error: %s", exc, exc_info=True)
        return {"status": "error", "message": str(exc)}


@mcp.tool()
def filter_relevant_content(
    records: List[Dict[str, Any]],
    topic: str,
    min_relevance: float = 0.2,
) -> Dict[str, Any]:
    """Filter raw or normalized social records using lexical and hashtag relevance scoring."""
    try:
        parsed_records = [NormalizedSocialRecord(**r) for r in records]
        # Synchronous lexical scoring
        scored = []
        for r in parsed_records:
            score = 1.0
            from server.services.filtering import calculate_lexical_relevance
            score = calculate_lexical_relevance(r, topic)
            r.relevance_score = score
            if score >= min_relevance:
                scored.append(r)
        scored.sort(key=lambda x: (x.relevance_score or 0.0), reverse=True)
        return {
            "status": "success",
            "topic": topic,
            "original_count": len(records),
            "filtered_count": len(scored),
            "records": [r.model_dump() for r in scored],
        }
    except Exception as exc:
        logger.error("[SOCIAL] filter_relevant_content error: %s", exc, exc_info=True)
        return {"status": "error", "message": str(exc)}


@mcp.tool()
def normalize_social_data(
    raw_data: Dict[str, Any],
    platform: str,
    provider: str,
    content_type: str = "post",
) -> Dict[str, Any]:
    """Convert arbitrary raw provider output into the unified NormalizedSocialRecord schema."""
    try:
        record = normalize_raw_social_data(
            raw_dict=raw_data,
            platform=platform,
            provider=provider,
            content_type=content_type,
        )
        return {"status": "success", "record": record.model_dump()}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


@mcp.tool()
def store_social_records(
    records: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Persist normalized social records to SQLite with automatic deduplication on (platform, content_id)."""
    try:
        parsed = [NormalizedSocialRecord(**r) for r in records]
        stats = social_service.store_records(parsed)
        return {"status": "success", "storage_stats": stats}
    except Exception as exc:
        logger.error("[SOCIAL] store_social_records error: %s", exc, exc_info=True)
        return {"status": "error", "message": str(exc)}


@mcp.tool()
def generate_social_report(
    records: List[Dict[str, Any]],
    topic: str,
) -> Dict[str, Any]:
    """Synthesize cross-platform social records into an executive analytical report."""
    try:
        parsed = [NormalizedSocialRecord(**r) for r in records]
        report = create_social_report(parsed, topic=topic)
        return {"status": "success", "report": report.model_dump()}
    except Exception as exc:
        logger.error("[SOCIAL] generate_social_report error: %s", exc, exc_info=True)
        return {"status": "error", "message": str(exc)}


@mcp.tool()
async def search_social_topic(
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
    """Universal social-search and interaction-discovery tool.

    Accepts an arbitrary natural language query (e.g. 'Virat', 'mental health',
    'ebook selling', 'fitness') without requiring any post/reel or profile URL.

    Discovers relevant content, ranks candidates deterministically, selects the top N,
    fetches public comments & commenter information, deduplicates results,
    attaches provenance metadata, and returns a fully normalized schema.
    """
    logger.info(
        "[SOCIAL] search_social_topic called: query=%r, platform=%r, top_n=%d, comments_per_content=%d",
        query,
        platform,
        top_n,
        comments_per_content,
    )
    return await social_service.search_social_topic(
        query=query,
        platform=platform,
        top_n=top_n,
        comments_per_content=comments_per_content,
        date_from=date_from,
        date_to=date_to,
        days_back=days_back,
        min_relevance=min_relevance,
        auto_store=auto_store,
    )


if __name__ == "__main__":
    mcp.run()



