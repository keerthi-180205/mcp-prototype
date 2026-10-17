"""Reply DRAFTS for the care queue. A person reads, edits and posts them as a public reply under the post.

Nothing here is ever sent automatically, and no draft asks the commenter to move to a private chat or sells
anything. Helplines (India) checked 2026-10-14 against the official Tele-MANAS portal and CHILDLINE pages:
  Tele-MANAS 14416 / 1800-891-4416 (free, 24x7, Ministry of Health), 112 (single emergency number),
  CHILDLINE 1098 (free, 24x7, for children). Numbers change: override the text with CARE_HELPLINE_TEXT and
  re-check it every quarter. Commenters outside India need their own country's line.
"""

import os
from typing import Dict

DEFAULT_HELPLINE = (
    "If you're in India, Tele-MANAS is free and open 24x7: call 14416 or 1800-891-4416. "
    "If you are in immediate danger, call 112. Elsewhere, please contact your local emergency number or crisis line."
)
MINOR_LINE = "CHILDLINE (1098) is also free and open 24x7 for children and teens, and talking to an adult you trust can help."

HANDLING = {
    "crisis": (
        "Urgent. A trained person replies publicly as soon as possible with the resources above. Do not ask for details in "
        "the thread, do not diagnose or promise outcomes, and do not message the person privately first. If the comment "
        "suggests immediate danger, also use the platform's self-harm report option. Mark it replied when done."
    ),
    "seeking_help": "Reply in the thread and let the person choose to contact us; do not message them privately first. No marketing.",
    "distress": "Optional kind reply. No marketing. Dismiss it if it is only a general remark, not a personal one.",
}
MINOR_HANDLING = " Possible minor: keep the reply public and short, point to a trusted adult and CHILDLINE, never move to a private channel."


def helpline_text() -> str:
    return (os.getenv("CARE_HELPLINE_TEXT") or DEFAULT_HELPLINE).strip()


def reply_draft(label: str, username: str = "", possible_minor: bool = False) -> Dict[str, str]:
    """{draft, handling} for a care label; empty strings for every other label."""
    if label not in HANDLING:
        return {"draft": "", "handling": ""}
    who = f"@{username.lstrip('@')}" if username else "there"
    helpline = helpline_text()
    minor = f" {MINOR_LINE}" if possible_minor else ""
    link = (os.getenv("CARE_SUPPORT_LINK") or "").strip()
    if label == "crisis":
        draft = (f"Hi {who}, thank you for writing this - it takes courage, and we're glad you did. You matter, and you deserve "
                 f"support right now. {helpline}{minor} You're not alone. \U0001F499")
    elif label == "seeking_help":
        find = f"You can find a counsellor or therapist through {link}. " if link else ""
        draft = (f"Hi {who}, thank you for reaching out - asking for help is a brave first step, and you don't have to work this "
                 f"out alone. {find}If things feel heavy right now: {helpline}{minor} \U0001F499")
    else:
        draft = (f"Hi {who}, thank you for sharing how you feel - many people feel this way, and you're not alone. Talking to "
                 f"someone you trust, or a counsellor, can really help. {helpline}{minor} \U0001F499")
    return {"draft": draft, "handling": HANDLING[label] + (MINOR_HANDLING if possible_minor else "")}
