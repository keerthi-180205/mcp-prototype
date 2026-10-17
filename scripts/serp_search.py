"""Run a Google search through Bright Data's SERP API (1 credit per result page) and save the results.

Uses the same cache, daily budget and usage ledger as the collectors, so repeating a query is free and
you cannot overspend the free tier by accident.

Examples
  python scripts/serp_search.py 'site:linkedin.com/in clinical psychologist Bangalore' --pages 3 --csv
  python scripts/serp_search.py 'site:instagram.com psychologist "book a session"' --csv out.csv
  python scripts/serp_search.py 'site:x.com inurl:status "anxiety therapy"' --recent month
  python scripts/serp_search.py --zones          # list the zones on your Bright Data account
"""

import argparse
import asyncio
import csv
import datetime
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

import httpx  # noqa: E402

from server.collection.collectors.base import CollectorFatalError  # noqa: E402
from server.collection.collectors.serp import SerpSearch  # noqa: E402
from server.collection.ledger import get_budget, get_ledger  # noqa: E402
from server.csv_safe import safe_row  # noqa: E402
from server.providers.brightdata.serp import BrightDataSerpError, matches_site  # noqa: E402

RECENT = {"day": "qdr:d", "week": "qdr:w", "month": "qdr:m", "year": "qdr:y"}
FIELDS = ["query", "page", "rank", "title", "url", "snippet", "source", "display", "off_target"]


def list_zones() -> int:
    key = os.getenv("BRIGHTDATA_API_KEY")
    if not key:
        print("BRIGHTDATA_API_KEY is not set in .env")
        return 1
    base = os.getenv("BRIGHTDATA_BASE_URL", "https://api.brightdata.com").rstrip("/")
    resp = httpx.get(f"{base}/zone/get_active_zones", headers={"Authorization": f"Bearer {key}"}, timeout=30)
    if resp.status_code != 200:
        print(f"Bright Data answered HTTP {resp.status_code}")
        return 1
    zones = resp.json()
    if not zones:
        print("No zones yet: create a 'SERP API' zone in the Bright Data control panel.")
        return 1
    for z in zones:
        print(f"  {z.get('name'):24} type={z.get('type')}")
    serp = [z["name"] for z in zones if z.get("type") == "serp"]
    if len(serp) == 1:
        print(f"\nOnly one SERP zone ({serp[0]}): it is used automatically. Set BRIGHTDATA_SERP_ZONE={serp[0]} in .env only to pin it.")
    elif len(serp) > 1:
        print(f"\nSeveral SERP zones: add the one to use to .env, e.g.\n  BRIGHTDATA_SERP_ZONE={serp[0]}")
    return 0


async def run(args: argparse.Namespace) -> int:
    search = SerpSearch("web")
    if not search.is_available():
        print(f"Not ready: {search.unavailable_reason()}\n")
        list_zones()
        return 1

    tbs = RECENT[args.recent] if args.recent else None
    rows, start = [], 0
    for page_no in range(1, args.pages + 1):
        try:
            page = await search.search(args.query, start=start, tbs=tbs, country=args.country)
        except CollectorFatalError as exc:
            print(f"Stopped: {exc}")
            break
        except BrightDataSerpError as exc:
            print(f"Search failed (no credit charged): {exc}")
            break
        if page.degraded:
            print(f"! page {page_no}: Google ignored the site: filter for most results (not cached; "
                  f"run it again to retry). Off-target rows are marked with '?'.\n")
        for r in page.results:
            rows.append({"query": args.query, "page": page_no, "rank": r.rank, "title": r.title, "url": r.url,
                         "snippet": r.snippet, "source": r.source, "display": r.display,
                         "off_target": not matches_site(args.query, r.url)})
        if not page.next_start or not page.results:
            break
        start = page.next_start

    for r in rows:
        flag = "?" if r["off_target"] else " "
        print(f"{flag}{r['page']}.{r['rank']:<3} {r['title'][:70]}\n      {r['url']}\n      {r['source']} | {r['display']} | {r['snippet'][:110]}\n")
    ledger = get_ledger()
    budget = get_budget("brightdata")
    print(f"{len(rows)} results | credits spent by this run: {search.credits_used:g} "
          f"(repeat searches are cached and free) | spent in the last 24h: {ledger.spent_today('brightdata'):g}"
          f" of the {budget['per_day']} daily cap")

    if args.csv is not None and rows:
        path = args.csv or os.path.join(
            ROOT, "data", "exports",
            f"serp_{re.sub(r'[^a-z0-9]+', '_', args.query.lower())[:40].strip('_')}_{datetime.datetime.now():%Y%m%d_%H%M%S}.csv",
        )
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(safe_row(r) for r in rows)
        print(f"saved {path}")
    return 0 if rows else 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="?", help="Google query; operators like site: and inurl: work")
    ap.add_argument("--pages", type=int, default=1, help="result pages to fetch, 10 results and 1 credit each (max 5)")
    ap.add_argument("--recent", choices=sorted(RECENT), help="only results from the last day/week/month/year")
    ap.add_argument("--country", help="two-letter country for the search, e.g. in or us")
    ap.add_argument("--csv", nargs="?", const="", metavar="PATH", help="save results as CSV (default: data/exports/)")
    ap.add_argument("--zones", action="store_true", help="list the zones on your Bright Data account and exit")
    args = ap.parse_args()
    args.pages = max(1, min(5, args.pages))
    if args.zones:
        return list_zones()
    if not args.query:
        ap.error("give a query, or use --zones")
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
