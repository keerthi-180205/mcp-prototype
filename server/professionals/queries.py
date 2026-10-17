"""Query planning for the professional finder: city x specialty x platform -> Google queries."""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from server.professionals.models import FinderParams

# Places that are known under several names; matching any of them counts as "in that city".
CITY_ALIASES: Dict[str, Tuple[str, ...]] = {
    "bangalore": ("bangalore", "bengaluru"),
    "bengaluru": ("bangalore", "bengaluru"),
    "mumbai": ("mumbai", "bombay", "navi mumbai", "thane"),
    "delhi": ("delhi", "new delhi", "ncr", "gurgaon", "gurugram", "noida", "faridabad", "ghaziabad"),
    "new delhi": ("delhi", "new delhi", "ncr"),
    "gurgaon": ("gurgaon", "gurugram"),
    "gurugram": ("gurgaon", "gurugram"),
    "chennai": ("chennai", "madras"),
    "kolkata": ("kolkata", "calcutta"),
    "hyderabad": ("hyderabad", "secunderabad"),
    "pune": ("pune", "poona"),
}

# Marketplaces and directories: their contact details belong to the platform, not to a clinician,
# and scraping a competitor's roster is not what this tool is for.
# Contact-data brokers sell scraped emails and phone numbers of people who never gave them out: never a source.
BROKER_HOSTS = (
    "rocketreach.", "zoominfo.", "aeroleads.", "lusha.", "apollo.io", "signalhire.", "contactout.", "hunter.io", "snov.io",
    "theorg.", "crunchbase.", "leadiq.", "clearbit.", "uplead.", "seamless.ai", "adapt.io", "datanyze.", "kaspr.", "salesql.",
    "peoplelooker.", "spokeo.", "whitepages.", "radaris.", "mylife.", "ai-ark.", "wiza.co", "getprospect.", "skrapp.",
)
DIRECTORY_HOSTS = (
    "practo.", "justdial.", "lybrate.", "sulekha.", "credihealth.", "apollo247.", "1mg.", "docprime.",
    "psychologytoday.", "betterhelp.", "talkspace.", "mindtalk.", "therapyroute.", "yourdost.", "innerhour.",
    "zocdoc.", "wellnessforum", "medipract.", "healthgrades.", "doximity.", "drlogy.", "docindia.", "medindia.", "mfine.", "curofy.",
    "medibuddy.", "tatahealth.", "kivihealth.", "amahahealth.", "manastha.", "wysa.", "healthtap.", "catexhealth.", "nectarplus.",
    "rockethealth.", "unifers.", "bajajfinservhealth.", "eka.care", "ijneronline.",
)
# Social networks, reference sites and media: never a practice website.
NON_PRACTICE_HOSTS = (
    "linkedin.", "instagram.", "facebook.", "youtube.", "x.com", "twitter.", "reddit.", "quora.", "medium.",
    "pinterest.", "wikipedia.", "wikihow.", "healthline.", "webmd.", "clevelandclinic.", "nih.gov", "apa.org",
    "cambridge.", "thehindu.", "timesofindia.", "indiatimes.", "hindustantimes.", "ndtv.", "indianexpress.",
    "sagepub.", "springer.", "sciencedirect.", "researchgate.", "scribd.", "slideshare.",
)

# Only the two networks that have their own dedicated queries. A longer list of -site: operators made Google
# reject the query or return nothing (measured live, Oct 2026); directories and portals are filtered afterwards.
_EXCLUDE_FOR_WEB = "-site:linkedin.com -site:instagram.com"


@dataclass(frozen=True)
class Query:
    platform: str     # linkedin | instagram | web
    q: str


def is_directory(host: str) -> bool:
    host = host.lower()
    return any(h in host for h in DIRECTORY_HOSTS) or any(h in host for h in BROKER_HOSTS)


def is_non_practice(host: str) -> bool:
    host = host.lower()
    return any(h in host for h in NON_PRACTICE_HOSTS)


def city_terms(city: str) -> Tuple[str, ...]:
    key = " ".join((city or "").lower().split())
    return CITY_ALIASES.get(key, (key,)) if key else ()


def city_matches(text: str, city: str) -> bool:
    low = (text or "").lower()
    return any(re.search(rf"\b{re.escape(t)}\b", low) for t in city_terms(city))


def build_queries(p: FinderParams) -> List[Query]:
    """One query per specialty and platform. LinkedIn finds people, Instagram finds practising
    clinicians who invite bookings, the open web finds practice websites."""
    focus = f" {p.focus}" if p.focus else ""
    out: List[Query] = []
    for spec in p.specialties:
        if "linkedin" in p.platforms:
            out.append(Query("linkedin", f"site:linkedin.com/in {spec} {p.city}{focus}"))
        if "instagram" in p.platforms:
            out.append(Query("instagram", f'site:instagram.com {spec} {p.city} "book a session"{focus}'))
        if "web" in p.platforms:
            out.append(Query("web", f"{spec} {p.city} book appointment{focus} {_EXCLUDE_FOR_WEB}"))
    return out


def estimate(p: FinderParams) -> Dict[str, int]:
    """What a run can cost, before it starts."""
    queries = len(build_queries(p))
    serp = min(queries * p.pages, p.max_serp_credits)
    return {
        "queries": queries,
        "serp_credits_max": serp,                  # Bright Data (free tier: 5,000 / month)
        "instagram_profile_credits_max": p.max_profile_lookups if "instagram" in p.platforms else 0,  # TrueScrape
        "websites_to_open_max": p.max_sites,       # free
    }
