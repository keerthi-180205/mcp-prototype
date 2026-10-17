"""The finder: search -> classify -> read bios and websites -> re-classify -> store for human review.

    Google (SERP)  ->  candidates (LinkedIn profile / Instagram handle / website)
                   ->  rules drop non-clinicians
                   ->  Instagram bio (TrueScrape, 1 credit) -> the clinician's own website
                   ->  website + contact page (free, robots.txt respected)
                   ->  re-classify with the richer text (Gemini only for the ambiguous)
                   ->  licence claims, city check, score, store as review_status="new"

Nothing here contacts anyone and nothing is "verified": a person approves each record before export.
"""

import asyncio
import logging
import urllib.parse
from collections import Counter
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from server.collection.collectors.base import CollectorFatalError
from server.collection.collectors.serp import SerpSearch
from server.collection.collectors.truescrape import TrueScrapeBackend
from server.professionals.candidates import extract_candidates, merge_candidates
from server.professionals.classify import LlmCall, classify_candidates, gemini_labels
from server.professionals.licence import extract_licence
from server.professionals.models import (
    ENTITY_ORG,
    KIND_INSTAGRAM,
    KIND_LINKEDIN,
    KIND_WEBSITE,
    Candidate,
    Channel,
    Classification,
    FinderParams,
    ProfessionalRecord,
)
from server.professionals.queries import build_queries, city_matches, is_directory, is_non_practice
from server.professionals.scoring import fit_score
from server.professionals.web import SiteFetcher, email_is_generic, find_emails, find_phones, probe_site
from server.providers.brightdata.serp import BrightDataSerpError
from server.storage import professionals as store

logger = logging.getLogger("mcp_server.professionals.finder")

ProgressFn = Callable[[Dict[str, Any]], None]
PROFILE_CONCURRENCY = 3
SITE_CONCURRENCY = 3
BIO_CHARS = 500


def _domain(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _usable_website(url: str) -> bool:
    """A link in an Instagram bio worth opening: a real http(s) site that is not a social network or directory."""
    parts = urllib.parse.urlparse(url)
    host = parts.netloc.lower()
    return parts.scheme in ("http", "https") and bool(host) and not is_non_practice(host) and not is_directory(host)


class ProfessionalFinder:
    def __init__(
        self,
        serp: Any = None,
        profiles: Any = None,
        fetcher: Optional[SiteFetcher] = None,
        llm: Optional[LlmCall] = None,
        use_llm: bool = True,
        db_path: Optional[str] = None,
    ):
        self._serp = serp
        self._profiles = profiles
        self._fetcher = fetcher
        self._llm = llm
        self._use_llm = use_llm
        self.db_path = db_path

    # ---- dependencies (created lazily so tests can inject fakes) ----------------------------------
    def _deps(self) -> Tuple[Any, Any, SiteFetcher, Optional[LlmCall]]:
        serp = self._serp or SerpSearch("professionals")
        profiles = self._profiles or TrueScrapeBackend("instagram")
        fetcher = self._fetcher or SiteFetcher()
        llm = self._llm if self._llm is not None else (gemini_labels if self._use_llm else None)
        return serp, profiles, fetcher, llm

    # ---- run -------------------------------------------------------------------------------------------
    async def run(self, params: FinderParams, run_id: Optional[str] = None, on_progress: Optional[ProgressFn] = None) -> Dict[str, Any]:
        serp, profiles, fetcher, llm = self._deps()
        owns_fetcher = self._fetcher is None
        notes: List[str] = []
        stats: Counter = Counter()

        def progress(phase: str, **info: Any) -> None:
            if on_progress:
                on_progress({"phase": phase, **info})

        try:
            # 1) search
            progress("searching")
            cands = await self._search(params, serp, stats, notes, progress)
            stats["candidates"] = len(cands)
            for kind in (KIND_LINKEDIN, KIND_INSTAGRAM, KIND_WEBSITE):
                stats[f"candidates_{kind}"] = sum(1 for c in cands.values() if c.kind == kind)

            # 2) first pass: drop what is clearly not a clinician (no Gemini yet, no bios yet)
            progress("classifying", candidates=len(cands))
            first, first_stats = await classify_candidates(list(cands.values()), llm=None)
            for k, v in first_stats.items():
                if k.startswith("dropped:"):
                    stats[k] += v
            survivors = [c for c, _ in first]

            # 3) enrich: Instagram bios, then websites
            progress("reading profiles and websites", candidates=len(survivors))
            channels: Dict[str, List[Channel]] = {c.key: [] for c in survivors}
            site_text: Dict[str, str] = {}
            await self._read_bios(survivors, params, profiles, channels, stats, notes)
            survivors = self._merge_shared_websites(survivors, channels)
            await self._read_websites(survivors, params, fetcher, channels, site_text, stats)

            # 4) final classification with the richer text; Gemini settles the ambiguous ones
            progress("final classification", candidates=len(survivors))
            final, final_stats = await classify_candidates(survivors, llm=llm)
            for k, v in final_stats.items():
                if k.startswith("dropped:") or k.startswith("llm_"):
                    stats[k] += v

            # 5) build and store records
            progress("saving", kept=len(final))
            new = 0
            for cand, verdict in final:
                rec = self._record(cand, verdict, params, channels[cand.key], site_text.get(cand.key, ""))
                if store.upsert_professional(rec, run_id, self.db_path):
                    new += 1
                stats["kept"] += 1
                stats[f"kept_role_{rec.role}"] += 1
                stats["needs_review"] += 1 if rec.needs_review_reason else 0
                for ch in rec.channels:
                    stats[f"channel_{ch.kind}" + ("_generic" if ch.kind == "email" and ch.is_generic else "")] += 1
                stats["with_direct_channel"] += 1 if any(c.kind in ("email", "phone", "whatsapp", "contact_form") for c in rec.channels) else 0
            stats["new_records"], stats["already_known"] = new, stats["kept"] - new
        finally:
            if owns_fetcher:
                await fetcher.aclose()

        stats["serp_credits"] = int(getattr(serp, "credits_used", 0))
        stats["instagram_profile_credits"] = int(getattr(profiles, "credits_used", 0))
        return {"stats": dict(stats), "notes": notes}

    # ---- 1) search --------------------------------------------------------------------------------------------
    async def _search(self, params: FinderParams, serp: Any, stats: Counter, notes: List[str], progress: ProgressFn) -> Dict[str, Candidate]:
        found: Dict[str, Candidate] = {}
        spent_before = getattr(serp, "credits_used", 0)
        stop = False
        for q in build_queries(params):
            if stop:
                break
            start = 0
            for _ in range(params.pages):
                if getattr(serp, "credits_used", 0) - spent_before >= params.max_serp_credits:
                    notes.append(f"search stopped: reached max_serp_credits={params.max_serp_credits}")
                    stop = True
                    break
                try:
                    page = await serp.search(q.q, start=start, country=params.country)
                except CollectorFatalError as exc:   # budget, bad key, no credits: every further query would fail the same way
                    notes.append(f"search stopped: {str(exc)[:160]}")
                    stats["search_fatal"] += 1
                    stop = True
                    break
                except BrightDataSerpError as exc:
                    notes.append(f"query failed ({q.platform}): {str(exc)[:120]}")
                    stats["queries_failed"] += 1
                    break
                stats["queries_run"] += 1
                stats["degraded_pages"] += 1 if getattr(page, "degraded", False) else 0
                merge_candidates(found, extract_candidates(q.platform, page.results, q.q))
                progress("searching", queries_run=stats["queries_run"], candidates=len(found))
                if not page.next_start or not page.results:
                    break
                start = page.next_start
        return found

    # ---- 3a) Instagram bios --------------------------------------------------------------------------------------
    async def _read_bios(self, cands: List[Candidate], params: FinderParams, profiles: Any,
                         channels: Dict[str, List[Channel]], stats: Counter, notes: List[str]) -> None:
        for c in cands:  # every candidate is reachable through the profile it was found on
            if c.kind == KIND_LINKEDIN:
                channels[c.key].append(Channel(kind="linkedin", value=c.profile_url, found_via="serp", source_url=c.profile_url))
            elif c.kind == KIND_INSTAGRAM:
                channels[c.key].append(Channel(kind="instagram", value=c.profile_url, found_via="serp", source_url=c.profile_url))

        targets = sorted((c for c in cands if c.kind == KIND_INSTAGRAM), key=lambda c: c.rank)[: params.max_profile_lookups]
        skipped = sum(1 for c in cands if c.kind == KIND_INSTAGRAM) - len(targets)
        if skipped > 0:
            stats["instagram_bios_not_read"] += skipped
            notes.append(f"{skipped} Instagram candidates were not read (max_profile_lookups={params.max_profile_lookups})")
        sem = asyncio.Semaphore(PROFILE_CONCURRENCY)
        blocked = {"fatal": False}

        async def one(c: Candidate) -> None:
            if blocked["fatal"]:
                return
            async with sem:
                try:
                    prof = await profiles.instagram_profile(c.handle or "")
                except CollectorFatalError as exc:
                    blocked["fatal"] = True
                    notes.append(f"Instagram bios stopped: {str(exc)[:140]}")
                    return
                except Exception as exc:
                    stats["profile_lookup_failed"] += 1
                    logger.info("profile lookup failed for %s: %s", c.handle, type(exc).__name__)
                    return
            if not prof or prof.get("is_private"):
                stats["profile_unavailable"] += 1
                return
            stats["instagram_bios_read"] += 1
            c.bio = (prof.get("bio") or "")[:BIO_CHARS]
            c.name = prof.get("display_name") or c.name
            c.followers = prof.get("followers") if prof.get("followers") is not None else c.followers
            for email in find_emails(c.bio):
                channels[c.key].append(Channel(kind="email", value=email, found_via="bio", source_url=c.profile_url,
                                               is_generic=email_is_generic(email)))
            for phone in find_phones(c.bio):
                channels[c.key].append(Channel(kind="phone", value=phone, found_via="bio", source_url=c.profile_url))
            site = next((u for u in prof.get("external_links", []) if _usable_website(u)), None)
            if site:
                c.website_url = site

        await asyncio.gather(*[one(c) for c in targets])

    @staticmethod
    def _merge_shared_websites(cands: List[Candidate], channels: Dict[str, List[Channel]]) -> List[Candidate]:
        """If an Instagram bio points at a site that also turned up as its own candidate, the person owns it:
        keep one record (the Instagram one, which carries the website) instead of two."""
        owned = {_domain(c.website_url) for c in cands if c.kind == KIND_INSTAGRAM and c.website_url}
        out = [c for c in cands if not (c.kind == KIND_WEBSITE and _domain(c.profile_url) in owned)]
        for c in cands:
            if c not in out:
                channels.pop(c.key, None)
        return out

    # ---- 3b) websites ------------------------------------------------------------------------------------------------
    async def _read_websites(self, cands: List[Candidate], params: FinderParams, fetcher: SiteFetcher,
                             channels: Dict[str, List[Channel]], site_text: Dict[str, str], stats: Counter) -> None:
        order = sorted((c for c in cands if c.website_url), key=lambda c: (c.kind == KIND_WEBSITE, c.rank))   # personal sites before clinics
        targets: List[Candidate] = []
        seen = set()
        for c in order:
            d = _domain(c.website_url or "")
            if d and d not in seen:
                seen.add(d)
                targets.append(c)
        targets = targets[: params.max_sites]
        stats["sites_skipped_cap"] += max(0, len(seen) - len(targets))
        sem = asyncio.Semaphore(SITE_CONCURRENCY)

        async def one(c: Candidate) -> None:
            async with sem:
                probe = await probe_site(fetcher, c.website_url or "")
            stats[f"site_{probe.status}"] += 1
            if probe.status != "ok":
                return
            seen_here = {(ch.kind, ch.value) for ch in channels[c.key]}
            for ch in probe.channels:
                if (ch.kind, ch.value) not in seen_here:
                    channels[c.key].append(ch)
            if c.kind != KIND_WEBSITE:
                channels[c.key].append(Channel(kind="website", value=c.website_url or "", found_via="bio", source_url=c.profile_url))
            for kind in ("instagram", "linkedin"):
                url = probe.social.get(kind)
                if url and not any(ch.kind == kind for ch in channels[c.key]):
                    channels[c.key].append(Channel(kind=kind, value=url, found_via="link", source_url=probe.pages[0] if probe.pages else ""))
            if c.kind == KIND_WEBSITE:   # the site's own words are the best evidence about who it is
                c.bio = f"{probe.title}. {probe.description}".strip(". ")[:BIO_CHARS]
            site_text[c.key] = probe.text

        await asyncio.gather(*[one(c) for c in targets])

    # ---- 5) record ---------------------------------------------------------------------------------------------------------
    @staticmethod
    def _record(c: Candidate, v: Classification, params: FinderParams, chans: List[Channel], extra_text: str) -> ProfessionalRecord:
        text = " ".join(x for x in (c.name, c.headline, c.snippet, c.bio, extra_text) if x)
        if c.kind == KIND_WEBSITE and not any(ch.kind == "website" for ch in chans):
            chans = chans + [Channel(kind="website", value=c.website_url or c.profile_url, found_via="serp", source_url=c.profile_url)]
        reason = v.reason if v.needs_review else ""
        if c.kind == KIND_INSTAGRAM and not c.bio and "bio not read" not in reason:
            reason = (reason + "; " if reason else "") + "Instagram bio not read"
        if not city_matches(text, params.city):
            reason = (reason + "; " if reason else "") + f"no sign they practise in {params.city}"
        rec = ProfessionalRecord(
            pro_id=store.pro_id_for(c.key), kind=c.kind, entity_type=v.entity_type, name=c.name or c.handle or "",
            role=v.role, confidence=v.confidence, classified_by=v.method, credentials=v.credentials, evidence=v.evidence,
            red_flags=v.red_flags, needs_review_reason=reason, city=params.city, city_match=city_matches(text, params.city),
            headline=c.headline[:300], snippet=(c.snippet or c.bio)[:500], profile_url=c.profile_url, handle=c.handle,
            website_url=c.website_url, followers=c.followers, licence=extract_licence(text), channels=chans,
        )
        rec.fit_score = fit_score(rec)
        return rec
