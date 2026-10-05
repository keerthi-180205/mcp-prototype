"""Centralized configuration management for MMTF MCP Server.

Provides a hardened, environment-driven configuration layer with sensible
defaults, lazy validation of provider credentials, and secret masking.
"""

import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

# Ensure .env is loaded when config is accessed
load_dotenv()


def _mask_secret(val: Optional[str]) -> str:
    """Mask a secret value for safe logging and representation."""
    if not val:
        return "<not_set>"
    if len(val) <= 6:
        return "***"
    return f"{val[:3]}...{val[-3:]}"


@dataclass
class Settings:
    """Application configuration loaded from environment variables with sensible defaults."""

    # Environment & Logging
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())

    # GitHub API Configuration
    github_api_base_url: str = field(
        default_factory=lambda: os.getenv("GITHUB_API_BASE_URL", "https://api.github.com").rstrip("/")
    )
    github_token: Optional[str] = field(default_factory=lambda: os.getenv("GITHUB_TOKEN") or None)
    github_timeout: float = field(
        default_factory=lambda: float(os.getenv("GITHUB_TIMEOUT", "20.0"))
    )

    # Hugging Face API Configuration
    hf_token: Optional[str] = field(default_factory=lambda: os.getenv("HF_TOKEN") or None)
    hf_api_base_url: str = field(
        default_factory=lambda: os.getenv("HF_API_BASE_URL", "https://huggingface.co/api/datasets").rstrip("/")
    )
    hf_timeout: float = field(
        default_factory=lambda: float(os.getenv("HF_TIMEOUT", "20.0"))
    )

    # Kaggle API Configuration
    kaggle_username: Optional[str] = field(default_factory=lambda: os.getenv("KAGGLE_USERNAME") or None)
    kaggle_key: Optional[str] = field(default_factory=lambda: os.getenv("KAGGLE_KEY") or None)
    kaggle_api_base_url: str = field(
        default_factory=lambda: os.getenv("KAGGLE_API_BASE_URL", "https://www.kaggle.com/api/v1/datasets/view").rstrip("/")
    )
    kaggle_timeout: float = field(
        default_factory=lambda: float(os.getenv("KAGGLE_TIMEOUT", "20.0"))
    )

    # Zenodo API Configuration
    zenodo_token: Optional[str] = field(default_factory=lambda: os.getenv("ZENODO_TOKEN") or None)
    zenodo_api_base_url: str = field(
        default_factory=lambda: os.getenv("ZENODO_API_BASE_URL", "https://zenodo.org/api/records").rstrip("/")
    )
    zenodo_timeout: float = field(
        default_factory=lambda: float(os.getenv("ZENODO_TIMEOUT", "20.0"))
    )

    # Gemini LLM Configuration
    gemini_api_key: Optional[str] = field(default_factory=lambda: os.getenv("GEMINI_API_KEY") or None)
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
    )
    gemini_timeout: float = field(
        default_factory=lambda: float(os.getenv("GEMINI_TIMEOUT", "90.0"))
    )

    # Apify API Configuration
    apify_api_token: Optional[str] = field(default_factory=lambda: os.getenv("APIFY_API_TOKEN") or None)
    apify_api_base_url: str = field(
        default_factory=lambda: os.getenv("APIFY_API_BASE_URL", "https://api.apify.com/v2").rstrip("/")
    )
    apify_instagram_search_actor: str = field(
        default_factory=lambda: os.getenv("APIFY_INSTAGRAM_SEARCH_ACTOR", "apify/instagram-scraper")
    )
    apify_instagram_comments_actor: str = field(
        default_factory=lambda: os.getenv("APIFY_INSTAGRAM_COMMENTS_ACTOR", "apify/instagram-comment-scraper")
    )
    apify_timeout: float = field(
        default_factory=lambda: float(os.getenv("APIFY_TIMEOUT", "120.0"))
    )

    # Retry and Resilience Configuration
    max_retries: int = field(
        default_factory=lambda: int(os.getenv("MAX_RETRIES", "3"))
    )
    retry_initial_delay: float = field(
        default_factory=lambda: float(os.getenv("RETRY_INITIAL_DELAY", "0.5"))
    )
    retry_backoff_factor: float = field(
        default_factory=lambda: float(os.getenv("RETRY_BACKOFF_FACTOR", "2.0"))
    )
    retry_max_delay: float = field(
        default_factory=lambda: float(os.getenv("RETRY_MAX_DELAY", "5.0"))
    )

    def validate_kaggle_credentials(self) -> None:
        """Validate Kaggle credentials when Kaggle operations are invoked."""
        if not self.kaggle_username or not self.kaggle_key:
            raise ValueError(
                "Kaggle API authentication unavailable. Please set KAGGLE_USERNAME and KAGGLE_KEY environment variables."
            )

    def validate_gemini_credentials(self) -> None:
        """Validate Gemini API key when Gemini operations are invoked."""
        if not self.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY environment variable is not configured. "
                "Provide an API key via environment variable or client parameter."
            )

    def validate_apify_credentials(self) -> None:
        """Validate Apify API token when Apify operations are invoked."""
        if not self.apify_api_token:
            raise ValueError(
                "APIFY_API_TOKEN environment variable is not configured. "
                "Provide an API token via environment variable to use Apify Instagram tools."
            )

    def __repr__(self) -> str:
        """Return a string representation with all sensitive credentials securely masked."""
        return (
            f"Settings("
            f"environment={self.environment!r}, "
            f"log_level={self.log_level!r}, "
            f"github_api_base_url={self.github_api_base_url!r}, "
            f"github_token={_mask_secret(self.github_token)!r}, "
            f"github_timeout={self.github_timeout}, "
            f"hf_token={_mask_secret(self.hf_token)!r}, "
            f"hf_api_base_url={self.hf_api_base_url!r}, "
            f"hf_timeout={self.hf_timeout}, "
            f"kaggle_username={self.kaggle_username!r}, "
            f"kaggle_key={_mask_secret(self.kaggle_key)!r}, "
            f"kaggle_api_base_url={self.kaggle_api_base_url!r}, "
            f"kaggle_timeout={self.kaggle_timeout}, "
            f"zenodo_token={_mask_secret(self.zenodo_token)!r}, "
            f"zenodo_api_base_url={self.zenodo_api_base_url!r}, "
            f"zenodo_timeout={self.zenodo_timeout}, "
            f"gemini_api_key={_mask_secret(self.gemini_api_key)!r}, "
            f"gemini_model={self.gemini_model!r}, "
            f"gemini_timeout={self.gemini_timeout}, "
            f"apify_api_token={_mask_secret(self.apify_api_token)!r}, "
            f"apify_api_base_url={self.apify_api_base_url!r}, "
            f"apify_instagram_search_actor={self.apify_instagram_search_actor!r}, "
            f"apify_instagram_comments_actor={self.apify_instagram_comments_actor!r}, "
            f"apify_timeout={self.apify_timeout}, "
            f"max_retries={self.max_retries}, "
            f"retry_initial_delay={self.retry_initial_delay}"
            f")"
        )


_cached_settings: Optional[Settings] = None


def get_settings(reload: bool = False) -> Settings:
    """Retrieve or initialize application settings singleton."""
    global _cached_settings
    if _cached_settings is None or reload:
        _cached_settings = Settings()
    return _cached_settings
