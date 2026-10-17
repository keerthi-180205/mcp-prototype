"""Hermetic test environment.

The app loads `.env` on import, so without this the suite would use real API keys: it would
make live Gemini calls (and hang for minutes), could spend provider credits, would read the
developer's real Reddit login and would write test rows into the real database and export folder.

The blanking below runs at import time, before any test module imports `server.*`.
Tests that need a credential set it explicitly with `monkeypatch.setenv`.
"""

import os
import tempfile

import pytest

_SECRET_VARS = (
    "GEMINI_API_KEY",
    "GITHUB_TOKEN",
    "HF_TOKEN",
    "KAGGLE_USERNAME",
    "KAGGLE_KEY",
    "ZENODO_TOKEN",
    "TRUESCRAPE_API_KEY",
    "SOCIALCRAWL_API_KEY",
    "BRIGHTDATA_API_KEY",
    "APIFY_API_TOKEN",
    "REDDIT_SESSION",
    "TWITTER_AUTH_TOKEN",
    "TWITTER_CT0",
    "YOUTUBE_COOKIES_FILE",
    "LINKEDIN_ACCESS_TOKEN",
    "FACEBOOK_ACCESS_TOKEN",
    "PROFESSIONALS_API_TOKEN",
    "AUDIENCE_API_TOKEN",
    "MMTF_OWN_ACCOUNTS",        # which accounts count as ours: tests set it explicitly
    "CARE_HELPLINE_TEXT",
    "CARE_SUPPORT_LINK",
    "BRIGHTDATA_SERP_ZONE",     # set in the real .env once a SERP zone exists
    "BRIGHTDATA_SERP_COUNTRY",
)

# dotenv never overrides a variable that already exists, so "" keeps the real .env value out.
for _name in _SECRET_VARS:
    os.environ[_name] = ""

# Path.home() decides where rdt-cli keeps its login: point it away from the real one.
_FAKE_HOME = tempfile.mkdtemp(prefix="mmtf-test-home-")
os.environ["HOME"] = _FAKE_HOME


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    """Send the default SQLite database and export folder to a per-test temp dir."""
    import server.collection.export as export
    import server.storage.sqlite as sqlite_store

    monkeypatch.setattr(sqlite_store, "DEFAULT_DB_PATH", str(tmp_path / "default.db"))
    monkeypatch.setattr(export, "DEFAULT_EXPORT_DIR", str(tmp_path / "exports"))

    from server.config import get_settings
    from server.providers.brightdata.serp import reset_zone_cache

    reset_zone_cache()
    get_settings(reload=True)
    yield
    get_settings(reload=True)
