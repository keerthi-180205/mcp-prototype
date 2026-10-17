"""Which accounts are MMTF's own. Collection is refused for every other account.

MMTF_OWN_ACCOUNTS="instagram:handle1,handle2; youtube:@channel"   (profile URLs are accepted too)
A malformed value raises instead of being ignored: a typo must not silently weaken the guard.
"""

import os
import re
from typing import Dict, List, Optional, Set

ENV = "MMTF_OWN_ACCOUNTS"
SUPPORTED = ("instagram", "youtube")   # platforms whose own posts can be listed and ownership-checked
_ALIASES = {"ig": "instagram", "insta": "instagram", "yt": "youtube", "twitter": "x", "li": "linkedin"}
_KNOWN = ("instagram", "youtube", "x", "reddit", "linkedin")
_URL_HANDLE = re.compile(
    r"(?:instagram\.com|youtube\.com|x\.com|twitter\.com|reddit\.com/(?:user|u)|linkedin\.com/(?:company|in))/@?([A-Za-z0-9._\-]+)",
    re.IGNORECASE,
)


class AccountsError(ValueError):
    """The configured accounts do not allow what was asked."""


def normalise_handle(handle: str) -> str:
    h = (handle or "").strip()
    m = _URL_HANDLE.search(h)
    if m:
        h = m.group(1)
    h = re.sub(r"^(?:u|user)/", "", h.strip().lstrip("@"), flags=re.IGNORECASE)
    return h.strip("/ ").lower()


def normalise_platform(platform: str) -> str:
    key = (platform or "").strip().lower()
    return _ALIASES.get(key, key)


def parse_accounts(raw: Optional[str]) -> Dict[str, Set[str]]:
    out: Dict[str, Set[str]] = {}
    for entry in re.split(r"[;\n]+", raw or ""):
        entry = entry.strip()
        if not entry:
            continue
        platform, sep, handles = entry.partition(":")
        platform = normalise_platform(platform)
        if not sep or platform not in _KNOWN:
            raise AccountsError(f"{ENV}: cannot read {entry!r}; use platform:handle[,handle] with platform one of {', '.join(_KNOWN)}")
        names = {normalise_handle(h) for h in handles.split(",") if normalise_handle(h)}
        if not names:
            raise AccountsError(f"{ENV}: {platform} has no handle")
        out.setdefault(platform, set()).update(names)
    return out


def own_accounts() -> Dict[str, Set[str]]:
    return parse_accounts(os.getenv(ENV, ""))


def accounts_for(platform: str) -> List[str]:
    return sorted(own_accounts().get(normalise_platform(platform), set()))


def is_own(platform: str, handle: str) -> bool:
    return normalise_handle(handle) in own_accounts().get(normalise_platform(platform), set())


def require_account(platform: str, account: Optional[str] = None) -> str:
    """The account to collect for: the one asked for if it is MMTF's, else the only configured one."""
    platform = normalise_platform(platform)
    configured = accounts_for(platform)
    if not configured:
        raise AccountsError(
            f"no {platform} account is configured as MMTF's own. Set {ENV}, e.g. {ENV}=\"{platform}:<our_handle>\". "
            "Only accounts listed there can be collected."
        )
    if account:
        handle = normalise_handle(account)
        if handle not in configured:
            raise AccountsError(f"@{handle} is not one of MMTF's configured {platform} accounts, so its comments are not collected")
        return handle
    if len(configured) > 1:
        raise AccountsError(f"several {platform} accounts are configured ({', '.join(configured)}); say which one")
    return configured[0]
