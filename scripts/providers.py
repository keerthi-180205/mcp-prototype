"""See which data providers are usable right now, what they cost today, and forget a remembered block.

  python scripts/providers.py status            # per-platform chains, blocked providers (and why), credits vs daily caps
  python scripts/providers.py unblock socialcrawl   # after topping up credits, so the platform tries it again at once

A provider that reports "no credits" or a rejected key is remembered for 6 hours (or until its key changes in .env).
"""

import argparse
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from server.chat.assistant import get_platforms_availability  # noqa: E402
from server.collection.health import refresh_provider_state  # noqa: E402
from server.collection.ledger import get_budget, get_ledger  # noqa: E402

PROVIDERS = ("truescrape", "socialcrawl", "apify", "brightdata")


def status() -> int:
    ledger = get_ledger()
    balance = asyncio.run(refresh_provider_state(ledger)).get("socialcrawl", {})   # free balance check
    if balance.get("balance") is not None:
        print(f"SocialCrawl credits left: {balance['balance']}\n")
    print("Platforms (find posts -> read comments):")
    for name, v in get_platforms_availability().items():
        mark = "ok " if v["available"] else "NOT"
        print(f"  [{mark}] {name:10} discover={v['providers']['discover']} comments={v['providers']['comments']}")
        for prov, why in v["unavailable_providers"].items():
            print(f"        - {prov}: {why}")
    print("\nCredits in the last 24h vs the daily cap:")
    for p in PROVIDERS:
        b = get_budget(p)
        blocked = ledger.blocked_reason(p)
        print(f"  {p:12} {ledger.spent_today(p):6g} / {b['per_day'] or 'unlimited'}" + (f"   BLOCKED: {blocked}" if blocked else ""))
    return 0


def unblock(name: str) -> int:
    was = get_ledger().clear_blocked(name)
    print(f"{name}: " + ("block cleared; the next job will try it again" if was else "was not blocked"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    u = sub.add_parser("unblock")
    u.add_argument("provider", choices=PROVIDERS)
    args = ap.parse_args()
    return status() if args.cmd == "status" else unblock(args.provider)


if __name__ == "__main__":
    sys.exit(main())
