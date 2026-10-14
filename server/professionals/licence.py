"""Licence *claims* found in a profile or website. Nothing here is verification: a person checks the
number in the official register (RCI for psychologists, the medical council for psychiatrists)."""

import re
from typing import Dict, List

from server.professionals.models import Licence

_CLAIM = re.compile(
    r"(?:rci\s*(?:licen[sc]ed|registered|reg\b\.?)|registered\s+with\s+(?:the\s+)?rci|"
    r"licen[sc]ed\s+(?:clinical|counsell?ing|rehabilitation)\s+psycholog\w+|"
    r"registered\s+(?:clinical|counsell?ing)\s+psycholog\w+|rehabilitation\s+council\s+of\s+india)",
    re.IGNORECASE,
)
# RCI Central Rehabilitation Register numbers look like "A12345"; a bare 4-digit number is usually a year.
_RCI_NUMBER = re.compile(
    r"\b(?:rci|crr)\b[^\n]{0,30}?(?:reg(?:istration)?\.?\s*)?(?:no\.?|number|#)\s*[:.\-]?\s*([A-Z]\s?\d{4,7}|\d{5,7})\b",
    re.IGNORECASE,
)
_MEDICAL_NUMBER = re.compile(
    r"\b(?:nmc|mci|kmc|medical\s+council|reg(?:istration)?\.?\s*(?:no\.?|number))\b[^\n]{0,20}?[:.\-#]?\s*"
    r"((?:[A-Z]{1,4}[\s\-/]?)?\d{4,8})\b",
    re.IGNORECASE,
)
_MEDICAL_CONTEXT = re.compile(r"\b(mbbs|m\.?d\.?|psychiatr\w+|dpm|dnb|doctor|dr\.)", re.IGNORECASE)


def _context(text: str, start: int, end: int, pad: int = 45) -> str:
    return " ".join(text[max(0, start - pad): end + pad].split())


def extract_licence(text: str) -> Licence:
    text = text or ""
    claim = ""
    m = _CLAIM.search(text)
    if m:
        claim = _context(text, m.start(), m.end())
    numbers: List[Dict[str, str]] = []
    seen = set()
    for m in _RCI_NUMBER.finditer(text):
        num = re.sub(r"\s+", "", m.group(1)).upper()
        if re.fullmatch(r"(19|20)\d\d", num) or num in seen:
            continue
        seen.add(num)
        numbers.append({"body": "RCI", "number": num, "context": _context(text, m.start(), m.end())})
    if _MEDICAL_CONTEXT.search(text):
        for m in _MEDICAL_NUMBER.finditer(text):
            num = re.sub(r"[\s]+", "", m.group(1)).upper()
            if re.fullmatch(r"(19|20)\d\d", num) or num in seen:
                continue
            seen.add(num)
            numbers.append({"body": "medical_council", "number": num, "context": _context(text, m.start(), m.end())})
    return Licence(claim=claim, numbers=numbers[:3])
