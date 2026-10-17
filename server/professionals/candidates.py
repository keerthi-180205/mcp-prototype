"""Turn Google (SERP) results into typed candidates: LinkedIn profiles, Instagram handles, websites."""

import re
import urllib.parse
from typing import Dict, Iterable, List, Optional

from server.professionals.models import KIND_INSTAGRAM, KIND_LINKEDIN, KIND_WEBSITE, Candidate
from server.professionals.queries import is_directory, is_non_practice
from server.providers.brightdata.serp import SerpResult, parse_followers

_LI_PROFILE = re.compile(r"https?://(?:[a-z]{2,3}\.|www\.)?linkedin\.com/in/([^/?#\s]+)", re.IGNORECASE)
_IG_URL = re.compile(r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9_.]+)/?(?:[?#].*)?$")
_IG_RESERVED = {"p", "reel", "reels", "tv", "explore", "stories", "accounts", "direct", "about", "web", "developer"}
_HANDLE = re.compile(r"^[A-Za-z0-9_.]{1,30}$")


def _after_dot(source: str) -> str:
    """"Instagram · dr.jud" -> "dr.jud";  "LinkedIn · Asha Rao" -> "Asha Rao"."""
    return source.split("·", 1)[1].strip() if "·" in (source or "") else ""


def _clean_title(title: str) -> str:
    title = re.sub(r"\s*[|\-–]\s*LinkedIn\s*$", "", title or "", flags=re.IGNORECASE)
    return title.replace("...", "").replace("…", "").strip(" -–|")


def _linkedin(r: SerpResult, query: str) -> Optional[Candidate]:
    m = _LI_PROFILE.match(r.url)
    if not m:
        return None
    slug = urllib.parse.unquote(m.group(1)).lower().rstrip("/")
    title = _clean_title(r.title)
    name_part, _, headline = title.partition(" - ")
    return Candidate(
        key=f"linkedin:{slug}", kind=KIND_LINKEDIN,
        name=_after_dot(r.source) or name_part.strip(),
        profile_url=f"https://www.linkedin.com/in/{slug}",
        headline=headline.strip(), snippet=r.snippet, followers=parse_followers(r.display),
        query=query, rank=r.rank,
    )


def _instagram(r: SerpResult, query: str) -> Optional[Candidate]:
    handle = _after_dot(r.source)
    if not _HANDLE.match(handle or ""):
        m = _IG_URL.match(r.url)
        handle = m.group(1) if m and m.group(1).lower() not in _IG_RESERVED else ""
    if not handle:
        return None
    handle = handle.lstrip("@")
    return Candidate(
        key=f"instagram:{handle.lower()}", kind=KIND_INSTAGRAM, name=handle, handle=handle,
        profile_url=f"https://www.instagram.com/{handle}/",
        headline=r.title, snippet=r.snippet, query=query, rank=r.rank,
    )


def _website(r: SerpResult, query: str) -> Optional[Candidate]:
    parts = urllib.parse.urlparse(r.url)
    host = parts.netloc.lower().split(":")[0]
    if not host or parts.scheme not in ("http", "https") or is_directory(host) or is_non_practice(host):
        return None
    domain = host[4:] if host.startswith("www.") else host
    page = f"{parts.scheme}://{parts.netloc}{parts.path}".rstrip("/") or f"{parts.scheme}://{parts.netloc}"
    return Candidate(
        key=f"website:{domain}", kind=KIND_WEBSITE, name=r.source or r.title,
        profile_url=f"{parts.scheme}://{parts.netloc}/", website_url=page,
        headline=r.title, snippet=r.snippet, query=query, rank=r.rank,
    )


_BUILDERS = {"linkedin": _linkedin, "instagram": _instagram, "web": _website}


def extract_candidates(platform: str, results: Iterable[SerpResult], query: str = "") -> List[Candidate]:
    """Candidates found in one result page, de-duplicated by identity (several Instagram posts by
    the same handle become one candidate whose snippet holds the posts' text)."""
    build = _BUILDERS[platform]
    found: Dict[str, Candidate] = {}
    for r in results:
        cand = build(r, query)
        if cand is None:
            continue
        have = found.get(cand.key)
        if have is None:
            found[cand.key] = cand
        elif cand.kind == KIND_INSTAGRAM and cand.snippet and cand.snippet not in have.snippet:
            have.snippet = f"{have.snippet} {cand.snippet}".strip()[:900]
    return list(found.values())


def merge_candidates(into: Dict[str, Candidate], new: Iterable[Candidate]) -> int:
    """Add `new` to `into` by key (keeping the better-ranked copy). Returns how many were new."""
    added = 0
    for cand in new:
        have = into.get(cand.key)
        if have is None:
            into[cand.key] = cand
            added += 1
        elif cand.kind == KIND_INSTAGRAM and cand.snippet and cand.snippet not in have.snippet:
            have.snippet = f"{have.snippet} {cand.snippet}".strip()[:900]
    return added
