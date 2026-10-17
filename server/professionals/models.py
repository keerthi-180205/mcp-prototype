"""Models and constants for the professional finder."""

import re
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

# ---- roles ------------------------------------------------------------------------------------
ROLE_PSYCHIATRIST = "psychiatrist"
ROLE_CLINICAL = "clinical_psychologist"
ROLE_COUNSELLING = "counselling_psychologist"
ROLE_PSYCHOLOGIST = "psychologist"          # "psychologist" without clinical / counselling
ROLE_PSYCHOTHERAPIST = "psychotherapist"
ROLE_COUNSELLOR = "counsellor"
ROLE_ORG = "organisation"
ROLE_OTHER = "other"

PERSON_ROLES = (ROLE_PSYCHIATRIST, ROLE_CLINICAL, ROLE_COUNSELLING, ROLE_PSYCHOLOGIST, ROLE_PSYCHOTHERAPIST, ROLE_COUNSELLOR)
ALL_ROLES = PERSON_ROLES + (ROLE_ORG, ROLE_OTHER)

ENTITY_PERSON = "person"
ENTITY_ORG = "organisation"

KIND_LINKEDIN = "linkedin"
KIND_INSTAGRAM = "instagram"
KIND_WEBSITE = "website"

REVIEW_STATUSES = ("new", "approved", "rejected", "do_not_contact")
CHANNEL_KINDS = ("email", "phone", "whatsapp", "contact_form", "website", "linkedin", "instagram")
PLATFORMS = ("linkedin", "instagram", "web")

DEFAULT_SPECIALTIES = ["clinical psychologist", "counselling psychologist", "psychiatrist"]

_UNSAFE = re.compile(r'["():<>\\|]|\bsite\s*:|\binurl\s*:|(?<!\w)-(?=\w)')


def clean_term(value: str, max_len: int = 40) -> str:
    """Make free text safe to place inside a Google query (no operators, quotes or brackets)."""
    value = _UNSAFE.sub(" ", value or "")
    return " ".join(value.split())[:max_len].strip()


class FinderParams(BaseModel):
    city: str
    specialties: List[str] = Field(default_factory=lambda: list(DEFAULT_SPECIALTIES))
    focus: Optional[str] = None            # e.g. "anxiety": narrows Instagram / web queries
    platforms: List[str] = Field(default_factory=lambda: list(PLATFORMS))
    pages: int = 1                         # Google result pages per query (10 results, 1 credit each)
    country: Optional[str] = "in"
    max_serp_credits: int = 30             # hard stop for Bright Data credits in one run
    max_profile_lookups: int = 15          # Instagram bios to read (1 TrueScrape credit each)
    max_sites: int = 25                    # websites to open (free)

    @field_validator("city")
    @classmethod
    def _city(cls, v: str) -> str:
        v = clean_term(v, 60)
        if not v:
            raise ValueError("city must not be empty")
        return v

    @field_validator("specialties")
    @classmethod
    def _specialties(cls, v: List[str]) -> List[str]:
        out = list(dict.fromkeys(t for t in (clean_term(s) for s in v) if t))[:6]
        if not out:
            raise ValueError("give at least one specialty")
        return out

    @field_validator("focus")
    @classmethod
    def _focus(cls, v: Optional[str]) -> Optional[str]:
        return clean_term(v) or None if v else None

    @field_validator("platforms")
    @classmethod
    def _platforms(cls, v: List[str]) -> List[str]:
        aliases = {"web": "web", "website": "web", "google": "web", "ig": "instagram", "li": "linkedin"}
        out = list(dict.fromkeys(aliases.get(p.lower().strip(), p.lower().strip()) for p in v))
        out = [p for p in out if p in PLATFORMS]
        if not out:
            raise ValueError(f"platforms must be a subset of {list(PLATFORMS)}")
        return out

    @field_validator("pages")
    @classmethod
    def _pages(cls, v: int) -> int:
        return max(1, min(3, int(v)))

    @field_validator("max_serp_credits")
    @classmethod
    def _credits(cls, v: int) -> int:
        return max(1, min(100, int(v)))

    @field_validator("max_profile_lookups", "max_sites")
    @classmethod
    def _caps(cls, v: int) -> int:
        return max(0, min(60, int(v)))


class Candidate(BaseModel):
    """A profile or website found by a search, before it is classified."""

    key: str                      # canonical identity, e.g. "linkedin:asha-rao-12ab"
    kind: str                     # linkedin | instagram | website
    name: str = ""
    profile_url: str
    handle: Optional[str] = None
    headline: str = ""
    snippet: str = ""
    followers: Optional[int] = None
    query: str = ""
    rank: int = 0
    website_url: Optional[str] = None
    bio: str = ""


class Classification(BaseModel):
    keep: bool
    entity_type: str = ENTITY_PERSON
    role: str = ROLE_OTHER
    confidence: float = 0.0
    credentials: List[str] = Field(default_factory=list)
    evidence: str = ""
    red_flags: List[str] = Field(default_factory=list)
    method: str = "rules"         # rules | gemini
    needs_review: bool = False
    reason: str = ""
    org_hint: bool = False        # speaks like an organisation but also like a person: let Gemini decide


class Channel(BaseModel):
    kind: str
    value: str
    is_generic: bool = False
    found_via: str = ""           # mailto | tel | jsonld | text | bio | link | form | serp
    source_url: str = ""


class Licence(BaseModel):
    claim: str = ""                                   # e.g. "Clinical Psychologist (RCI Licensed)"
    numbers: List[Dict[str, str]] = Field(default_factory=list)   # [{"body": "RCI", "number": "A12345", "context": "..."}]


class ProfessionalRecord(BaseModel):
    pro_id: str
    kind: str
    entity_type: str
    name: str = ""
    role: str = ROLE_OTHER
    confidence: float = 0.0
    classified_by: str = "rules"
    credentials: List[str] = Field(default_factory=list)
    evidence: str = ""
    red_flags: List[str] = Field(default_factory=list)
    needs_review_reason: str = ""
    city: str = ""
    city_match: bool = False
    headline: str = ""
    snippet: str = ""
    profile_url: str
    handle: Optional[str] = None
    website_url: Optional[str] = None
    followers: Optional[int] = None
    licence: Licence = Field(default_factory=Licence)
    fit_score: float = 0.0
    channels: List[Channel] = Field(default_factory=list)
