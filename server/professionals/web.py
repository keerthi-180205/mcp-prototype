"""Read a clinician's own website politely and extract the contact channels they publish.

Rules this module keeps
* robots.txt is honoured (a site whose robots.txt cannot be read is skipped, not assumed open);
* at most two pages per site (the page we were given + its contact page), one request per host per second;
* plain HTTP only: no JavaScript rendering, no CAPTCHA solving, no proxies, no TLS downgrade. A site that
  blocks us is recorded as blocked and left alone;
* every channel keeps the URL of the page it was found on.
"""

import asyncio
import ipaddress
import json
import logging
import re
import socket
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

from server.professionals.models import Channel

logger = logging.getLogger("mcp_server.professionals.web")

UA = "Mozilla/5.0 (compatible; MMTFResearchBot/0.1)"
MAX_BYTES = 1_500_000
PER_HOST_DELAY = 1.0
MAX_TEXT = 6000
MAX_EMAILS = 5
MAX_PHONES = 5

GENERIC_LOCALS = {
    "info", "contact", "contactus", "hello", "hi", "support", "admin", "care", "appointment", "appointments",
    "enquiry", "enquiries", "inquiry", "inquiries", "help", "office", "reception", "mail", "team", "booking",
    "bookings", "connect", "reach", "sales", "services", "wellness", "counselling", "counseling", "therapy",
    "clinic", "desk", "front", "frontdesk", "feedback",
}
IGNORED_LOCALS = {
    "noreply", "no-reply", "donotreply", "do-not-reply", "webmaster", "privacy", "abuse", "postmaster", "hr",
    "careers", "career", "jobs", "press", "media", "legal", "unsubscribe", "accounts", "billing", "dpo",
}
_JUNK_TLD = {"png", "jpg", "jpeg", "gif", "svg", "webp", "css", "js", "woff", "woff2", "ico", "mp4", "pdf"}
_JUNK_DOMAIN = ("example.com", "sentry", "wixpress", "domain.com", "email.com", "yourdomain", "mysite", "godaddy", "test.com")

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
_PHONE_TEXT = re.compile(
    r"(?<![\d.])(?:\+?91[\s\-.]?|0)?[6-9]\d{4}[\s\-.]?\d{5}(?!\d)"                      # mobile
    r"|(?<![\d.])0\d{2,4}[\s\-]\d{3,4}[\s\-]?\d{3,4}(?!\d)"                              # landline: 080 2345 6789
    r"|(?<![\d.])\+91[\s\-.]?\(?0?\d{2,4}\)?[\s\-.]\d{3,4}[\s\-]?\d{3,4}(?!\d)"        # +91 80 2345 6789
)
_CONTACT_WORDS = re.compile(r"contact|reach\s+us|get\s+in\s+touch|enquir|inquir", re.IGNORECASE)
_BOOK_WORDS = re.compile(r"book|appointment|consult", re.IGNORECASE)
_IG_LINK = re.compile(r"instagram\.com/([A-Za-z0-9_.]{2,30})/?(?:[?#].*)?$", re.IGNORECASE)
_IG_RESERVED = {"p", "reel", "reels", "tv", "explore", "stories", "accounts", "direct", "about", "share"}
_LI_LINK = re.compile(r"linkedin\.com/in/([^/?#\s]+)", re.IGNORECASE)
_WA_LINK = re.compile(r"(?:wa\.me/|api\.whatsapp\.com/send\?[^\"' ]*phone=|whatsapp\.com/send\?[^\"' ]*phone=)\+?(\d{8,15})", re.IGNORECASE)


# ---- small pure helpers ---------------------------------------------------------------------
def clean_email(raw: str) -> Optional[str]:
    e = raw.strip().strip(".,;:()<>[]'\"").lower()
    if not _EMAIL.fullmatch(e):
        return None
    local, _, domain = e.partition("@")
    if domain.rsplit(".", 1)[-1] in _JUNK_TLD or any(j in domain for j in _JUNK_DOMAIN) or "@2x" in e:
        return None
    if local in IGNORED_LOCALS:
        return None
    return e


def email_is_generic(email: str) -> bool:
    return email.split("@", 1)[0] in GENERIC_LOCALS


def find_emails(text: str) -> List[str]:
    text = re.sub(r"\s*[\[\(]\s*at\s*[\]\)]\s*", "@", text or "", flags=re.IGNORECASE)
    text = re.sub(r"\s*[\[\(]\s*dot\s*[\]\)]\s*", ".", text, flags=re.IGNORECASE)
    out: List[str] = []
    for raw in _EMAIL.findall(text):
        e = clean_email(raw)
        if e and e not in out:
            out.append(e)
    return out


def normalize_phone(raw: str) -> Optional[str]:
    digits = re.sub(r"\D", "", raw or "")
    plus = (raw or "").strip().startswith("+")
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    if len(digits) == 11 and digits[0] == "0" and digits[1] != "0":
        return "+91" + digits[1:]  # trunk 0 + 10-digit number (mobile or STD landline): same E.164 form
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return "+" + digits
    if plus and 8 <= len(digits) <= 15:
        return "+" + digits
    if digits.startswith("0") and 9 <= len(digits) <= 12:
        return digits  # landline written with its STD code
    return None


def find_phones(text: str) -> List[str]:
    out: List[str] = []
    for m in _PHONE_TEXT.finditer(text or ""):
        p = normalize_phone(m.group(0))
        if p and p not in out:
            out.append(p)
    return out


def looks_blocked(text: str) -> bool:
    """A bot-check page is small and says so; a normal page that merely has a reCAPTCHA form is large."""
    low = text[:6000].lower()
    signs = ("just a moment", "cf-browser-verification", "enable javascript and cookies to continue",
             "attention required! | cloudflare", "checking your browser before accessing")
    return len(text) < 20000 and any(s in low for s in signs)


# ---- page extraction --------------------------------------------------------------------------
@dataclass
class PageContacts:
    emails: List[Tuple[str, str]] = field(default_factory=list)     # (email, via)
    phones: List[Tuple[str, str]] = field(default_factory=list)     # (normalised, via)
    whatsapp: List[str] = field(default_factory=list)
    has_form: bool = False
    social: Dict[str, str] = field(default_factory=dict)            # instagram / linkedin -> URL
    contact_link: Optional[str] = None
    title: str = ""
    description: str = ""
    text: str = ""


def _jsonld_values(soup: BeautifulSoup, keys: Tuple[str, ...]) -> List[Tuple[str, str]]:
    found: List[Tuple[str, str]] = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in keys and isinstance(v, str):
                    found.append((k, v))
                else:
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            walk(json.loads(tag.string or tag.get_text() or "null"))
        except (ValueError, TypeError):
            continue
    return found


def extract_page(html: str, base_url: str) -> PageContacts:
    soup = BeautifulSoup(html or "", "html.parser")
    out = PageContacts()
    out.title = " ".join((soup.title.get_text() if soup.title else "").split())[:200]
    meta = soup.find("meta", attrs={"name": re.compile("^description$", re.I)}) or soup.find("meta", attrs={"property": "og:description"})
    out.description = " ".join((meta.get("content") or "").split())[:300] if meta else ""

    def add_email(raw: str, via: str):
        e = clean_email(urllib.parse.unquote(raw))
        if e and e not in [x for x, _ in out.emails]:
            out.emails.append((e, via))

    def add_phone(raw: str, via: str):
        p = normalize_phone(raw)
        if p and p not in [x for x, _ in out.phones]:
            out.phones.append((p, via))

    for key, value in _jsonld_values(soup, ("email", "telephone")):
        (add_email if key == "email" else add_phone)(value.replace("mailto:", ""), "jsonld")

    base_host = urllib.parse.urlparse(base_url).netloc.lower()
    best_contact: Tuple[int, Optional[str]] = (99, None)
    for a in soup.find_all("a", href=True):
        href, label = a["href"].strip(), a.get_text(" ", strip=True)
        low = href.lower()
        if low.startswith("mailto:"):
            add_email(href[7:].split("?")[0], "mailto")
            continue
        if low.startswith("tel:"):
            add_phone(href[4:], "tel")
            continue
        wa = _WA_LINK.search(href)
        if wa:
            num = normalize_phone("+" + wa.group(1)) or wa.group(1)
            if num not in out.whatsapp:
                out.whatsapp.append(num)
            continue
        absolute = urllib.parse.urljoin(base_url, href)
        ig = _IG_LINK.search(absolute)
        if ig and ig.group(1).lower() not in _IG_RESERVED:
            out.social.setdefault("instagram", f"https://www.instagram.com/{ig.group(1)}/")
        li = _LI_LINK.search(absolute)
        if li:
            out.social.setdefault("linkedin", f"https://www.linkedin.com/in/{li.group(1).lower()}")
        if urllib.parse.urlparse(absolute).netloc.lower() == base_host and not low.startswith(("#", "javascript:")):
            haystack = f"{href} {label}"
            rank = 0 if _CONTACT_WORDS.search(haystack) else 1 if _BOOK_WORDS.search(haystack) else 99
            if rank < best_contact[0]:
                best_contact = (rank, absolute.split("#")[0])
    out.contact_link = best_contact[1]

    for form in soup.find_all("form"):
        if form.get("role") == "search" or form.find("input", attrs={"type": "search"}):
            continue
        if form.find("textarea") or (
            form.find("input", attrs={"type": "email"}) and form.find("input", attrs={"name": re.compile("name|message|phone", re.I)})
        ):
            out.has_form = True
            break

    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ", strip=True).split())
    out.text = text[:MAX_TEXT]
    for e in find_emails(text):
        add_email(e, "text")
    for p in find_phones(text):
        add_phone(p, "text")
    return out


# ---- only public internet addresses --------------------------------------------------------------------------
Resolver = Callable[[str], Awaitable[List[str]]]
_INTERNAL_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet")


async def default_resolver(host: str) -> List[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def is_public_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip.split("%")[0]).is_global
    except ValueError:
        return False


# ---- polite fetching ---------------------------------------------------------------------------
@dataclass
class Fetch:
    status: str            # ok | robots | robots_unavailable | blocked | http_error | error
    url: str
    final_url: str = ""
    code: int = 0
    text: str = ""
    reason: str = ""


class SiteFetcher:
    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        delay: float = PER_HOST_DELAY,
        timeout: float = 12.0,
        resolver: Optional[Resolver] = None,
    ):
        self._client = client
        self._owns_client = client is None
        self._resolver = resolver or default_resolver
        self._host_ok: Dict[str, bool] = {}
        if client is not None:
            client.event_hooks.setdefault("request", []).append(self._guard_request)
        self.delay = delay
        self.timeout = timeout
        self._robots: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}
        self._robots_lock = asyncio.Lock()
        self._turns: Dict[str, asyncio.Lock] = {}
        self._last: Dict[str, float] = {}

    async def __aenter__(self) -> "SiteFetcher":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml", "Accept-Language": "en"},
                follow_redirects=True,
                event_hooks={"request": [self._guard_request]},
            )
        return self._client

    async def _public_host(self, host: Optional[str]) -> bool:
        """URLs come from strangers (Instagram bios, search results), so never fetch anything that is not on the
        public internet: loopback, private ranges, link-local / cloud-metadata addresses, internal names.
        (A DNS answer can still change between this check and the connection; this stops the practical cases.)"""
        host = (host or "").lower().strip("[]").rstrip(".")
        if not host:
            return False
        if host not in self._host_ok:
            try:
                ipaddress.ip_address(host)
                ips = [host]
            except ValueError:
                if "." not in host or host.endswith(_INTERNAL_SUFFIXES):
                    ips = []
                else:
                    try:
                        ips = await self._resolver(host)
                    except Exception:
                        ips = []
            self._host_ok[host] = bool(ips) and all(is_public_ip(ip) for ip in ips)
        return self._host_ok[host]

    async def _guard_request(self, request: httpx.Request) -> None:   # runs for every request, redirects included
        if not await self._public_host(request.url.host):
            raise httpx.RequestError("refusing a non-public address", request=request)

    async def _wait_turn(self, host: str) -> None:
        lock = self._turns.setdefault(host, asyncio.Lock())
        async with lock:
            gap = self.delay - (time.monotonic() - self._last.get(host, 0.0))
            if gap > 0:
                await asyncio.sleep(gap)
            self._last[host] = time.monotonic()

    async def _allowed(self, url: str) -> Tuple[bool, str]:
        parts = urllib.parse.urlparse(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        async with self._robots_lock:
            if origin not in self._robots:
                rp: Optional[urllib.robotparser.RobotFileParser] = urllib.robotparser.RobotFileParser()
                try:
                    await self._wait_turn(parts.netloc)
                    resp = await self.client.get(f"{origin}/robots.txt", timeout=8)
                    if resp.status_code == 200:
                        rp.parse(resp.text.splitlines())
                    elif resp.status_code in (401, 403):
                        rp.disallow_all = True
                    elif resp.status_code < 500:
                        rp.allow_all = True
                    else:
                        rp = None  # server error: cannot tell, so do not crawl
                except Exception:
                    rp = None
                self._robots[origin] = rp
            rp = self._robots[origin]
        if rp is None:
            return False, "robots.txt could not be read"
        if not rp.can_fetch(UA, url):
            return False, "disallowed by robots.txt"
        return True, ""

    async def fetch(self, url: str) -> Fetch:
        parts = urllib.parse.urlparse(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return Fetch("error", url, reason="not an http(s) URL")
        if not await self._public_host(parts.hostname):
            return Fetch("error", url, reason="not a public internet address")
        ok, why = await self._allowed(url)
        if not ok:
            return Fetch("robots" if "disallowed" in why else "robots_unavailable", url, reason=why)
        await self._wait_turn(parts.netloc)
        try:
            async with self.client.stream("GET", url, timeout=self.timeout) as resp:
                code, ctype = resp.status_code, resp.headers.get("content-type", "")
                if code in (401, 403, 429, 503):
                    return Fetch("blocked", url, str(resp.url), code, reason=f"HTTP {code}")
                if code >= 400:
                    return Fetch("http_error", url, str(resp.url), code, reason=f"HTTP {code}")
                if ctype and "html" not in ctype.lower() and "xml" not in ctype.lower():
                    return Fetch("http_error", url, str(resp.url), code, reason=f"not a web page ({ctype.split(';')[0]})")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) >= MAX_BYTES:
                        break
                del body[MAX_BYTES:]  # a single large chunk must not get past the cap either
                text = bytes(body).decode(resp.encoding or "utf-8", errors="replace")
        except httpx.HTTPError as exc:
            return Fetch("error", url, reason=type(exc).__name__)
        if looks_blocked(text):
            return Fetch("blocked", url, str(resp.url), code, reason="bot check page")
        return Fetch("ok", url, str(resp.url), code, text)


# ---- one site -------------------------------------------------------------------------------------
@dataclass
class SiteProbe:
    url: str
    status: str = "error"
    reason: str = ""
    pages: List[str] = field(default_factory=list)
    channels: List[Channel] = field(default_factory=list)
    title: str = ""
    description: str = ""
    text: str = ""
    social: Dict[str, str] = field(default_factory=dict)


def _channels_from(page: PageContacts, source_url: str, include_form_url: Optional[str] = None) -> List[Channel]:
    chans: List[Channel] = []
    for email, via in page.emails[:MAX_EMAILS]:
        chans.append(Channel(kind="email", value=email, is_generic=email_is_generic(email), found_via=via, source_url=source_url))
    for phone, via in page.phones[:MAX_PHONES]:
        chans.append(Channel(kind="phone", value=phone, found_via=via, source_url=source_url))
    for num in page.whatsapp[:2]:
        chans.append(Channel(kind="whatsapp", value=num, found_via="link", source_url=source_url))
    if page.has_form and include_form_url:
        chans.append(Channel(kind="contact_form", value=include_form_url, found_via="form", source_url=source_url))
    return chans


async def probe_site(fetcher: SiteFetcher, url: str) -> SiteProbe:
    """Read `url` and, if it links to one, the contact page. Never more than two requests."""
    probe = SiteProbe(url=url)
    first = await fetcher.fetch(url)
    probe.status, probe.reason = first.status, first.reason
    if first.status != "ok":
        return probe
    base = first.final_url or url
    page = extract_page(first.text, base)
    probe.pages.append(base)
    probe.title, probe.description, probe.social = page.title, page.description, dict(page.social)
    texts = [page.text]
    channels = _channels_from(page, base, include_form_url=base)

    link = page.contact_link
    if link and link.rstrip("/") != base.rstrip("/"):
        second = await fetcher.fetch(link)
        if second.status == "ok":
            sbase = second.final_url or link
            spage = extract_page(second.text, sbase)
            probe.pages.append(sbase)
            texts.append(spage.text)
            for k, v in spage.social.items():
                probe.social.setdefault(k, v)
            channels += _channels_from(spage, sbase, include_form_url=sbase)

    seen = set()
    for ch in channels:
        if (ch.kind, ch.value) not in seen:
            seen.add((ch.kind, ch.value))
            probe.channels.append(ch)
    probe.text = " ".join(t for t in texts if t)[:MAX_TEXT]
    return probe
