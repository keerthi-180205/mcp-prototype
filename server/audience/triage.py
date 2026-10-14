"""Rule-based triage of comments on MMTF's own posts.

The aim is narrow: make sure a person sees every comment that may come from someone who is struggling, and
that nothing here decides anything *about* the commenter. So:

  * rules only - no third-party LLM ever sees a comment;
  * recall over precision for the urgent labels (a false alarm costs a reviewer seconds, a miss costs more);
  * every flag keeps the phrase that caused it, so the reviewer can overrule it at a glance;
  * labels describe the comment, never the person ("seeking_help" is a comment that asks for help).

Order of precedence: crisis > seeking_help > distress > question > spam > positive > other.
"""

import re
import unicodedata
from typing import List, Optional, Tuple

from server.audience.models import PRIORITY, Triage

FIRST_PERSON = re.compile(r"\b(?:i|i'?m|im|i'?ve|ive|i'?d|i'?ll|my|me|mine|myself)\b", re.IGNORECASE)

_SELF = r"my\s*self"


def _compile(rules: List[Tuple[str, str]]) -> List[Tuple["re.Pattern[str]", str]]:
    return [(re.compile(pattern, re.IGNORECASE), reason) for pattern, reason in rules]


# ---- crisis: intent, plan or a statement of wanting to die (English, Hinglish, Hindi) -------------------------
CRISIS_RULES = _compile([
    (rf"\bkill(?:ing)?\s+{_SELF}\b", "kill myself"),
    (r"\b(?:end|ending|take|taking)\s+(?:my|his|her|their)\s+(?:own\s+)?(?:life|lives)\b", "end my life"),
    (r"\bend(?:ing)?\s+(?:it\s+all|everything)\b", "end it all"),
    (r"\b(?:want|wanna|going|gonna|thinking(?:\s+(?:of|about))?|ready|time)\s+(?:to\s+)?end(?:ing)?\s+it\b", "end it"),
    (r"\b(?:want(?:s|ed|ing)?|wanna|wish(?:es|ed)?|plan(?:s|ned|ning)?|ready|thinking\s+(?:of|about)|feel(?:ing)?\s+like)"
     r"\s+(?:to\s+|i\s+(?:was|were|could|would)\s+)?(?:just\s+)?(?:die+|dead|dying|disappear(?:ing)?|(?:not\s+)?wake\s+up|be\s+dead)\b", "wants to die"),
    (r"\b(?:don'?t|do\s+not|dont|no\s+longer|never)\s+want\s+to\s+(?:live|be\s+alive|be\s+here|exist|wake\s+up)\b", "does not want to live"),
    (r"\b(?:no|not\s+any|zero)\s+(?:reason|point)\s+(?:to|in)\s+(?:live|living|go(?:ing)?\s+on|being\s+alive|exist(?:ing)?)\b", "no reason to live"),
    (r"\b(?:can'?t|cannot|cant)\s+(?:go|carry)\s+on\b", "cannot go on"),
    (r"\b(?:better|best)\s+off\s+(?:dead|without\s+me)\b|\bwish\s+i\s+(?:was|were)\s+(?:never\s+born|dead)\b", "better off dead"),
    (rf"\bself[\s-]*harm(?:ing)?\b|\b(?:cut|cutting|hurt|hurting|harm|harming)\s+{_SELF}\b", "self-harm"),
    (r"\boverdos(?:e|ed|ing)\b", "overdose"),
    (rf"\bjump(?:ing)?\s+(?:off|from)\s+(?:a\s+|the\s+|my\s+)?(?:roof|building|bridge|terrace|balcony)\b|\bhang(?:ing)?\s+{_SELF}\b", "method"),
    # Hinglish (Roman script)
    (r"\bmar(?:na|ne|jana|jaana|jaun|jau)\s*(?:chah(?:ta|ti|te)|hai|hu|hoon|h)\b|\bmar\s+jaana\s+chah", "wants to die (Hinglish)"),
    (r"\bjee?ne\s+ka\s+(?:mann?|mood|koi\s+matlab)\s+nahi\b|\bjee?na\s+nahi\s+chah", "does not want to live (Hinglish)"),
    (r"\b(?:khud\s*kushi|aatm\s*hatya|atmahatya|suicide\s+karna|suicide\s+kar\s+(?:lu|lunga|lungi|loonga|loongi))\b", "suicide (Hinglish)"),
    (r"\bkhud\s+ko\s+(?:khatam|maar)\b|\bzindagi\s+(?:khatam|se\s+thak)", "end my life (Hinglish)"),
    # Hindi (Devanagari)
    (r"आत्महत्या|खुदकुशी|मरना\s+चाह|जीना\s+नहीं|जीने\s+का\s+मन\s+नहीं|जान\s+दे", "suicide (Hindi)"),
])
SUICIDE_WORD = re.compile(r"\bsuicid(?:e|al)\b", re.IGNORECASE)

# ---- asking for help ---------------------------------------------------------------------------------------
HELP_RULES = _compile([
    (r"\bhel+p+\s*(?:me|us)\b|\b(?:pl[sz]|plea?se*)\s+hel+p+\b|\bi\s+(?:really\s+)?need\s+(?:some\s+|your\s+|a\s+bit\s+of\s+)?(?:hel+p+|support|advice|guidance|someone|a\s+(?:therapist|counsel+or|doctor|friend))", "asks for help"),
    (r"\b(?:how|where)\s+(?:do|can|to|should)\s+(?:i|we)\s+(?:find|get|reach|contact|talk\s+to|speak\s+to|consult|see|meet|book)\b.{0,40}\b(?:therapist|counsel+or|counsel+ing|psychologist|psychiatrist|doctor|professional|help|support)\b", "asks how to reach a professional"),
    (r"\b(?:can|could|will)\s+(?:you|someone|anyone|anybody)\s+(?:please\s+)?(?:hel+p+|suggest|recommend|guide|talk|listen)\b", "asks someone to help"),
    (r"\b(?:suggest|recommend|know)\s+(?:me\s+)?(?:a\s+|any\s+)?(?:good\s+)?(?:therapist|counsel+or|psychologist|psychiatrist)\b|\b(?:looking|searching)\s+for\s+(?:a\s+|some\s+)?(?:good\s+)?(?:therapist|counsel+or|psychologist|psychiatrist|help|support)\b", "looking for a professional"),
    (r"\b(?:who|whom)\s+(?:can|should|do)\s+i\s+(?:talk|speak|reach|contact|go|turn)\b|\bneed\s+to\s+(?:talk|speak|vent)\b|\b(?:nobody|no\s+one)\s+to\s+talk\b", "needs someone to talk to"),
    (r"\b(?:madad|help|sahayata|support)\s+(?:chahiye|chahie|karo|kijiye|kariye)\b|\bkis(?:s?e|ko)\s+baat\s+kar(?:u|oon|un)\b|\b(?:therapist|counsel+or)\s+(?:chahiye|ka\s+number|batao|bataiye)\b", "asks for help (Hinglish)"),
])

# ---- distress: a first-person statement of suffering --------------------------------------------------------
STRONG_DISTRESS = re.compile(
    r"\b(?:depress(?:ed|ion)|anxi(?:ous|ety)|panic(?:king|\s+attacks?)?|hopeless|worthless|helpless|lonel(?:y|iness)|overwhelm(?:ed|ing)|"
    r"burn(?:ed|t)?[\s-]*out|breaking\s+down|breakdown|numb|empty\s+inside|hate\s+my\s*self|"
    r"(?:no\s+one|nobody)\s+(?:understands|cares|listens)|tired\s+of\s+(?:everything|life|it\s+all|living)|"
    r"can'?t\s+(?:sleep|focus|concentrate|eat|breathe|stop\s+(?:crying|thinking|overthinking))|cry(?:ing)?\s+(?:every|all|myself)|"
    r"give\s+up|giving\s+up|insomnia|overthink(?:ing)?|self[\s-]*esteem|can'?t\s+(?:take|do)\s+(?:it|this)\s+any\s*more)\b",
    re.IGNORECASE,
)
WEAK_DISTRESS = re.compile(r"\b(?:stress(?:ed|ful)?|sad|scared|afraid|worried|nervous|exhausted|drained|tired|pressure|failed|failing|alone)\b", re.IGNORECASE)

# ---- everything else ------------------------------------------------------------------------------------------
QUESTION_TERMS = re.compile(
    r"\b(?:how\s+much|price|fees?|cost|charges?|book(?:ing)?|appointments?|sessions?|schedule|consultation|link|website|app|download|"
    r"contact|number|whatsapp|email|address|timings?|available|register|sign\s*up|enrol+)\b",
    re.IGNORECASE,
)
INTERROGATIVE = re.compile(r"\?|^\s*(?:how|where|when|what|which|do|does|can|is|are)\b", re.IGNORECASE)
SPAM = re.compile(
    r"https?://|www\.|\bdm\s+(?:me|for)\b|\bfollow\s+(?:me|back|for)\b|\bcheck\s+(?:out\s+)?my\b|\bpromo(?:tion)?\b|\bearn\s+\$?\d|"
    r"\bcrypto\b|\bforex\b|\bwhatsapp\s+me\b|\bf4f\b|\bs4s\b|\bgiveaway\b|\bloan\b|\bcasino\b|\bbetting\b",
    re.IGNORECASE,
)
POSITIVE = re.compile(
    r"\b(?:thank(?:s|\s+you)|thx|grateful|helpful|helped|great|amazing|beautiful|love(?:d)?|well\s+said|so\s+true|needed\s+this|inspiring|"
    r"powerful|important|good\s+work|nice|awesome|true|agree|exactly|relatable|wonderful|brilliant)\b",
    re.IGNORECASE,
)
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿❤️‍]")
POSITIVE_EMOJI = re.compile("[❤💙💜💛💚🧡🤍🖤🙏👏🔥💯😍🥰👍✨🌟💪]")

# ---- possible minors: a prompt to reply more carefully, never a conclusion -------------------------------------
MINOR_RULES = _compile([
    (r"\bi\s*(?:'?m|am)\s+(?:only\s+|just\s+)?(?:1[0-7]|[89])\b(?!\s*(?:min|hour|hr|day|week|month|%|k\b|km\b|kg\b|lakh|rs\b|rupees))", "says they are under 18"),
    (r"\b(?:1[0-7]|[89])\s*(?:yo|y/o|yrs?\s*old|years?\s*old)\b", "says they are under 18"),
    (r"\b(?:class|grade|std|standard)\s*(?:[6-9]|1[0-2])(?:th)?\b|\b(?:[6-9]|1[0-2])(?:th|st|nd|rd)\s*(?:class|grade|std|standard)\b|\b(?:9th|10th|11th|12th)\b", "school class mentioned"),
    (r"\bboard\s+exams?\b|\bhigh\s+school\b|\bschool\s+(?:student|kid|life|teacher|bullying)|\bmy\s+(?:school|teacher|classmates?)\b|\bteen(?:ager|age)?s?\b|\bunder\s*18\b", "school-age cue"),
])


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").replace("’", "'").replace("‘", "'")
    t = re.sub(r"(.)\1{3,}", r"\1\1", t)           # "pleeeeease" -> "pleease"
    return re.sub(r"\s+", " ", t).strip()


def _first_hit(rules: List[Tuple["re.Pattern[str]", str]], text: str) -> Optional[Tuple[str, str]]:
    for pattern, reason in rules:
        m = pattern.search(text)
        if m:
            return reason, m.group(0)[:60]
    return None


def _near_first_person(text: str, start: int, end: int, before: int = 60, after: int = 25) -> bool:
    return bool(FIRST_PERSON.search(text[max(0, start - before):start])) or bool(FIRST_PERSON.search(text[end:end + after]))


def _is_generic(text: str) -> bool:
    letters = re.sub(r"[^\w]|\d|_", "", EMOJI.sub("", text), flags=re.UNICODE)
    return len(letters) < 3 or (len(text.split()) <= 2 and bool(POSITIVE.search(text)))


def triage(text: str) -> Triage:
    t = normalise(text)
    out = Triage(generic=_is_generic(t))
    minor = _first_hit(MINOR_RULES, t)
    out.possible_minor = minor is not None

    def done(label: str, reasons: List[str]) -> Triage:
        out.label = label
        out.priority = PRIORITY.get(label, 0)
        out.reasons = reasons[:3]
        return out

    hits = [f"{reason}: \"{phrase}\"" for reason, phrase in filter(None, (_one(pattern, reason, t) for pattern, reason in CRISIS_RULES))]
    suicide = SUICIDE_WORD.search(t)
    if suicide and FIRST_PERSON.search(t):
        hits.append(f"mentions suicide with a personal statement: \"{suicide.group(0)}\"")
    if hits:
        return done("crisis", hits)

    helps = [f"{reason}: \"{phrase}\"" for reason, phrase in filter(None, (_one(pattern, reason, t) for pattern, reason in HELP_RULES))]
    if helps:
        return done("seeking_help", helps)

    reasons: List[str] = []
    if suicide:                       # general talk about suicide, no personal statement: a person should still look
        reasons.append(f"mentions suicide, no personal statement: \"{suicide.group(0)}\"")
    for m in STRONG_DISTRESS.finditer(t):
        if _near_first_person(t, m.start(), m.end()):
            reasons.append(f"first-person distress: \"{m.group(0)[:40]}\"")
            break
    else:
        for m in WEAK_DISTRESS.finditer(t):
            if _near_first_person(t, m.start(), m.end(), before=30, after=10):
                reasons.append(f"first-person distress: \"{m.group(0)[:40]}\"")
                break
    if reasons:
        return done("distress", reasons)

    if QUESTION_TERMS.search(t) and INTERROGATIVE.search(t):
        return done("question", ["asks about our service"])
    if SPAM.search(t):
        return done("spam", ["link / promotion"])
    if POSITIVE.search(t) or POSITIVE_EMOJI.search(t):
        return done("positive", [])
    return done("other", [])


def _one(pattern: "re.Pattern[str]", reason: str, text: str) -> Optional[Tuple[str, str]]:
    m = pattern.search(text)
    return (reason, m.group(0)[:60]) if m else None
