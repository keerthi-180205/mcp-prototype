"""Find a clinician's own website from their name, then read its contact page.

LinkedIn profiles carry no contact details, so for the individuals the finder lists the only channel is the
profile itself. One Google search per person (name + role + city) usually finds a practice page; the site is then
read with the same polite fetcher as everywhere else (robots.txt, two pages, public addresses only).

Precision beats recall here: a wrong person's phone number is worse than none. A result is accepted only if every
part of the name AND a psychology / psychiatry term appear in it, the site is not a directory or social network,
and the match is flagged for a human to confirm. Sites shared by many doctors (hospitals) give shared lines, marked
as such.
"""

import asyncio
import logging
import re
import urllib.parse
from typing import Any, Callable, Dict, List, Optional, Tuple

from server.collection.collectors.base import CollectorFatalError
from server.collection.collectors.serp import SerpSearch
from server.professionals.classify import MH_STRONG
from server.professionals.models import ENTITY_PERSON, Channel, Licence, ProfessionalRecord
from server.professionals.licence import extract_licence
from server.professionals.queries import city_matches, is_directory, is_non_practice
from server.professionals.scoring import fit_score
from server.professionals.web import SiteFetcher, probe_site
from server.providers.brightdata.serp import BrightDataSerpError, SerpResult
from server.storage import professionals as store

logger = logging.getLogger("mcp_server.professionals.enrich")

NOTE = "website found by name search - confirm it is this person"
_TITLES = re.compile(r"\b(dr|mr|ms|mrs|prof|ph\.?d|m\.?d|mbbs|m\.?sc|m\.?phil|rci)\b\.?", re.IGNORECASE)
ROLE_WORDS = {
    "clinical_psychologist": "clinical psychologist", "counselling_psychologist": "counselling psychologist",
    "psychologist": "psychologist", "psychiatrist": "psychiatrist", "psychotherapist": "psychotherapist",
    "counsellor": "counsellor",
}


def name_tokens(name: str) -> List[str]:
    """Letters-only parts of a person's name, without titles, credentials or initials: "Dr. Asha Rao, MBBS" -> [asha, rao]."""
    s = re.sub(r"[\(\[].*?[\)\]]", " ", name or "")
    s = _TITLES.sub(" ", s.split(",")[0].split("|")[0].split(" - ")[0])
    return [t.lower() for t in re.findall(r"[^\W\d_]{2,}", s, flags=re.UNICODE)]


def build_query(tokens: List[str], role: str, city: str) -> str:
    return f'"{" ".join(tokens)}" {ROLE_WORDS.get(role, "psychologist")} {city} -site:linkedin.com -site:instagram.com'


# A site counts as "theirs" only if the domain carries their name, or the host is itself a hospital / clinic / practice.
# Anything else that matches by name (health apps, aggregators, journals) is some third party's page: its email and
# phone belong to that third party, not to the clinician.
ORG_HOST_HINT = re.compile(r"hospital|clinic|medical|institute|psych|mind|counsel|therap|neuro|brain|wellness|nimhans", re.IGNORECASE)


def acceptable_host(host: str, tokens: List[str]) -> Optional[str]:
    """"personal" / "organisation" if the host may be this person's site, else None."""
    if is_directory(host) or is_non_practice(host):
        return None
    if any(len(t) >= 4 and t in host for t in tokens):
        return "personal"
    if ORG_HOST_HINT.search(host):
        return "organisation"
    return None


def pick_site(results: List[SerpResult], tokens: List[str], city: str) -> Optional[Tuple[SerpResult, str]]:
    """The one result that is plausibly this person's own page, with the reason it was chosen; None if unsure."""
    best: Optional[Tuple[int, SerpResult, str]] = None
    for r in results:
        host = urllib.parse.urlparse(r.url).netloc.lower().split(":")[0]
        if not host or not acceptable_host(host, tokens):
            continue
        text = f"{r.title} {r.snippet}".lower()
        if not all(re.search(rf"\b{re.escape(t)}\b", text) for t in tokens):
            continue
        if not MH_STRONG.search(text):
            continue
        in_domain = any(len(t) >= 4 and t in host for t in tokens)
        score = 2 + (2 if in_domain else 0) + (1 if city_matches(text, city) else 0)
        why = "name and role in the result" + (", name in the domain" if in_domain else "") + (", city matches" if city_matches(text, city) else "")
        if best is None or score > best[0]:
            best = (score, r, why)
    return (best[1], best[2]) if best else None


def _record(d: Dict[str, Any]) -> ProfessionalRecord:
    return ProfessionalRecord(
        pro_id=d["pro_id"], kind=d["kind"], entity_type=d["entity_type"], name=d["name"], role=d["role"], confidence=d["confidence"],
        classified_by=d["classified_by"], credentials=d["credentials"], evidence=d["evidence"], red_flags=d["red_flags"],
        needs_review_reason=d["needs_review_reason"], city=d["city"], city_match=d["city_match"], headline=d["headline"],
        snippet=d["snippet"], profile_url=d["profile_url"], handle=d["handle"], website_url=d["website_url"], followers=d["followers"],
        licence=Licence(claim=d["licence"]["claim"], numbers=d["licence"]["numbers"]), fit_score=d["fit_score"],
        channels=[Channel(kind=c["kind"], value=c["value"], is_generic=c["is_generic"], found_via=c["found_via"], source_url=c["source_url"])
                  for c in d["channels"]],
    )


CONCURRENCY = 3


async def enrich_professionals(
    serp: Any = None,
    fetcher: Optional[SiteFetcher] = None,
    db_path: Optional[str] = None,
    limit: int = 10,
    max_credits: int = 15,
    statuses: Tuple[str, ...] = ("new", "approved"),
    force: bool = False,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Look up websites for individuals who have none. Costs at most `max_credits` search credits, three people at a time."""
    serp = serp or SerpSearch("enrich")
    owns_fetcher = fetcher is None
    fetcher = fetcher or SiteFetcher()
    stats: Dict[str, int] = {}
    notes: List[str] = []
    bump = lambda k, n=1: stats.__setitem__(k, stats.get(k, 0) + n)
    say = on_progress or (lambda _msg: None)
    spent0 = getattr(serp, "credits_used", 0)
    halt = {"stop": False}

    async def work(p: Dict[str, Any], tokens: List[str]) -> None:
        bump("searched")
        try:
            page = await serp.search(build_query(tokens, p["role"], p["city"]), country="in")
        except CollectorFatalError as exc:
            halt["stop"] = True
            notes.append(f"stopped: {str(exc)[:140]}")
            return
        except BrightDataSerpError as exc:
            bump("search_failed")
            notes.append(f"search failed for one person: {str(exc)[:100]}")
            return
        hit = pick_site(page.results, tokens, p["city"])
        if not hit:
            store.log_enrich_attempt(p["pro_id"], "no_match", "", db_path)
            bump("no_match")
            say("no confident match")
            return
        result, why = hit
        probe = await probe_site(fetcher, result.url)
        host = urllib.parse.urlparse(result.url).netloc.lower().removeprefix("www.")
        personal_site = any(len(t) >= 4 and t in host for t in tokens)
        channels = [Channel(kind="website", value=result.url, found_via="name_search", source_url=result.url)]
        for ch in probe.channels:
            # a page shared by many doctors (hospital, group practice) gives shared lines, not this person's
            channels.append(ch.model_copy(update={"is_generic": True}) if (not personal_site and ch.kind in ("email", "phone", "whatsapp", "contact_form")) else ch)
        for kind, url in probe.social.items():
            channels.append(Channel(kind=kind, value=url, found_via="link", source_url=probe.pages[0] if probe.pages else result.url))
        rec = _record(store.get_professional(p["pro_id"], db_path))
        have = {(c.kind, c.value) for c in rec.channels}
        rec.channels += [c for c in channels if (c.kind, c.value) not in have]
        rec.website_url = result.url
        parts = [rec.needs_review_reason] if rec.needs_review_reason else []
        if NOTE not in rec.needs_review_reason:
            parts.append(NOTE)
        rec.needs_review_reason = "; ".join(parts)
        if probe.text:
            rec.city_match = rec.city_match or city_matches(probe.text, rec.city)
            found = extract_licence(probe.text)
            rec.licence = Licence(claim=rec.licence.claim or found.claim, numbers=rec.licence.numbers or found.numbers)
        rec.fit_score = fit_score(rec)
        store.upsert_professional(rec, None, db_path)
        direct = any(c.kind in ("email", "phone", "whatsapp", "contact_form") for c in probe.channels)
        store.log_enrich_attempt(p["pro_id"], "found" if probe.status == "ok" else f"found_site_{probe.status}", why, db_path)
        bump("found")
        bump("found_direct_channel" if direct else "found_no_channel")
        bump(f"site_{probe.status}")
        say(f"website found, site {probe.status}" + (", with a contact channel" if direct else ""))

    try:
        _, people = store.list_professionals(statuses=list(statuses), entity_type=ENTITY_PERSON, sort="fit_score", limit=500, db_path=db_path)
        todo: List[Tuple[Dict[str, Any], List[str]]] = []
        for p in people:
            if p["website_url"] or p["suppressed"] or len(todo) >= limit:
                continue
            tokens = name_tokens(p["name"])
            if len(tokens) < 2:
                bump("skipped_name_too_short")
            elif not force and store.last_enrich_attempt(p["pro_id"], db_path):
                bump("skipped_already_tried")
            else:
                todo.append((p, tokens))
        i = 0
        while i < len(todo) and not halt["stop"]:
            room = max_credits - (getattr(serp, "credits_used", 0) - spent0)
            if room <= 0:
                notes.append(f"stopped: reached max_credits={max_credits}")
                break
            chunk = todo[i:i + min(CONCURRENCY, int(room))]
            i += len(chunk)
            say(f"looking up {i - len(chunk) + 1}-{i} of {len(todo)}")
            await asyncio.gather(*[work(p, t) for p, t in chunk])
    finally:
        if owns_fetcher:
            await fetcher.aclose()
    stats["search_credits"] = int(getattr(serp, "credits_used", 0) - spent0)
    return {"stats": stats, "notes": notes}


def audit_enrichments(db_path: Optional[str] = None) -> Dict[str, int]:
    """Re-check every stored name-search website against the current rules; undo the ones that would no longer be accepted.

    The undone person is searched again by the next `enrich` run (cached results make that free for a few hours).
    """
    _, people = store.list_professionals(entity_type=ENTITY_PERSON, limit=500, db_path=db_path)
    checked = reset = 0
    for p in people:
        if not any(c["found_via"] == "name_search" for c in p["channels"]):
            continue
        checked += 1
        host = urllib.parse.urlparse(p["website_url"] or "").netloc.lower().removeprefix("www.")
        if not acceptable_host(host, name_tokens(p["name"])):
            store.reset_enrichment(p["pro_id"], NOTE, db_path)
            reset += 1
    return {"checked": checked, "reset": reset}
