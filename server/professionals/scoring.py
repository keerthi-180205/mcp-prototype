"""Transparent 0-100 ranking for the review queue. It orders the work; it never decides anything."""

import math

from server.professionals.models import ENTITY_ORG, ProfessionalRecord

STRONG_CREDENTIALS = {"RCI", "M.Phil", "MD Psychiatry", "DPM", "Licensed"}


def fit_score(rec: ProfessionalRecord) -> float:
    score = rec.confidence * 50                                   # how sure we are they are a clinician
    if rec.entity_type == ENTITY_ORG:
        score -= 15                                               # individuals first; clinics are a second route
    if rec.city_match:
        score += 15
    if STRONG_CREDENTIALS & set(rec.credentials):
        score += 10
    if rec.licence.numbers:
        score += 5
    elif rec.licence.claim:
        score += 3

    emails = [c for c in rec.channels if c.kind == "email"]
    direct = [c for c in rec.channels if c.kind in ("email", "phone", "whatsapp", "contact_form")]
    if any(not c.is_generic for c in emails):
        score += 12                                               # a personal address they published
    elif direct:
        score += 8                                                # a clinic inbox, phone or contact form
    elif any(c.kind in ("instagram", "linkedin") for c in rec.channels):
        score += 3                                                # reachable only through their profile
    if rec.followers:
        score += min(5.0, math.log10(max(rec.followers, 1)))
    return round(max(0.0, min(100.0, score)), 1)
