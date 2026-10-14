"""The audience of MMTF's OWN accounts: collect who comments on our posts and make sure the people who need a reply get one.

  accounts   which accounts are configured as ours (MMTF_OWN_ACCOUNTS) - nothing else can be collected
  collect    read the comments on our recent posts (or specific posts of ours), triage them, store them
  queue      the care queue: comments that look like a call for help or distress, most urgent first, with a reply draft
  handle     record what a person did: replied | dismissed | new
  export     CSV of everything collected (usernames + comments: personal data)
  stats      counts, and how long the oldest unanswered care item has waited
  purge      delete handled care items and ordinary comments older than N days (+ expired provider cache)
  forget     erase everything held about one commenter ("please delete my comments")

How this is meant to be used: the reply is a PUBLIC comment under the post, written by a person. No cold DMs, no
marketing to people who only commented. Crisis comments get the helpline text and a trained person's attention first.

Examples
  python scripts/audience.py accounts
  python scripts/audience.py collect --platform instagram --posts 10 --comments 500 --max-credits 60
  python scripts/audience.py queue --label crisis seeking_help
  python scripts/audience.py handle 3fa9c1 replied --by Asha --note "replied publicly with Tele-MANAS"
  python scripts/audience.py purge --days 90
"""

import argparse
import asyncio
import os
import sys
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))

from server.audience import accounts  # noqa: E402
from server.audience.collect import AudienceError, collect_own_comments  # noqa: E402
from server.audience.export import export_audience  # noqa: E402
from server.audience.models import CARE_LABELS, STATUSES  # noqa: E402
from server.audience.queue import handle_item, queue_items  # noqa: E402
from server.collection.ledger import get_ledger  # noqa: E402
from server.storage import audience as store  # noqa: E402


def cmd_accounts(args: argparse.Namespace) -> int:
    configured = accounts.own_accounts()
    if not configured:
        print(f"No accounts configured. Add them to .env, e.g.\n  {accounts.ENV}=\"instagram:<our_handle>; youtube:@<our_channel>\"")
        print("Only accounts listed there can be collected.")
        return 1
    for platform, handles in sorted(configured.items()):
        note = "" if platform in accounts.SUPPORTED else "   (not supported yet: its posts cannot be ownership-checked)"
        print(f"{platform:<10} {', '.join('@' + h for h in sorted(handles))}{note}")
    return 0


async def cmd_collect(args: argparse.Namespace) -> int:
    summary = await collect_own_comments(
        args.platform, account=args.account, post_urls=args.post_url or None, max_posts=args.posts,
        max_comments_per_post=args.comments, max_credits=args.max_credits, allow_fallback=args.allow_fallback,
        on_progress=lambda m: print(f"  ... {m}"),
    )
    print(f"@{summary['account']} on {summary['platform']}: {summary['posts_found']} post(s) confirmed as ours, "
          f"{summary['posts_with_comments']} with comments")
    print(f"comments read: {summary['comments']} ({summary['new']} new, {summary['updated']} already stored)   credits used: {summary['credits_used']}")
    if summary["by_label"]:
        print("what they are: " + ", ".join(f"{n} {label}" for label, n in sorted(summary["by_label"].items(), key=lambda kv: -kv[1])))
    print(f"care queue: {summary['new_care_items']} new item(s) need a person   ->   python scripts/audience.py queue")
    for note in summary["notes"]:
        print(f"  note: {note}")
    if summary["stopped"]:
        print(f"  stopped: {summary['stopped']}")
    if args.export:
        out = export_audience(platform=summary["platform"], account=summary["account"])
        print(f"saved {out['path']}  ({out['rows']} rows; contains usernames and comments - personal data, keep it private)")
    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    items = queue_items(tuple(args.status), args.label or None, args.limit, args.platform, args.account, with_text=not args.no_text)
    if not items:
        print("The care queue is empty.")
        return 0
    for it in items:
        minor = "  (possible minor)" if it["possible_minor"] else ""
        wait = f"{it['waiting_hours']}h" if it["waiting_hours"] is not None else "?"
        who = f"@{it['username']}" if "username" in it else ""
        print(f"[{it['label'].upper():<12}] {it['key'][:10]}  {it['platform']} {who}  waiting {wait}  {it['status']}{minor}")
        if "comment" in it:
            print(f"    \"{it['comment'][:400]}\"")
            if it["reasons"]:
                print(f"    why flagged: {'; '.join(it['reasons'])}")
            print(f"    post: {it['post_url']}")
            print(f"    draft reply (edit, then post publicly): {it['draft']}")
            print(f"    how: {it['handling']}")
            if it["handler_note"]:
                print(f"    note: {it['handler_note']}")
    print(f"\n{len(items)} item(s). Mark each when done:  python scripts/audience.py handle <key> replied|dismissed --by <name>")
    return 0


def cmd_handle(args: argparse.Namespace) -> int:
    key = store.resolve_key(args.key)
    done = handle_item(key, args.status, args.by or "", args.note or "")
    print(f"{key[:10]} is now {done['status']}" if done else "not found")
    return 0 if done else 1


def cmd_export(args: argparse.Namespace) -> int:
    out = export_audience(platform=args.platform, account=args.account, labels=args.label or None)
    print(f"saved {out['path']}  ({out['rows']} rows)\nIt contains usernames and what people said: personal data. Keep it private, delete it when done.")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    s = store.stats()
    print(f"{s['comments']} comments on {s['posts']} post(s)")
    for label, n in sorted(s["by_label"].items(), key=lambda kv: -kv[1]):
        print(f"  {label:<13} {n}")
    waiting = s["waiting_for_a_reply"]
    print("waiting for a person: " + (", ".join(f"{n} {label}" for label, n in waiting.items()) if waiting else "nothing") +
          (f"   (oldest since {s['oldest_waiting']})" if s["oldest_waiting"] else ""))
    return 0


def cmd_purge(args: argparse.Namespace) -> int:
    out = store.purge(args.days)
    cache = get_ledger().purge_expired()
    print(f"deleted {out['handled_care_items']} handled care item(s) and {out['other_comments']} other comment(s) older than {args.days} days; "
          f"{cache} expired provider-cache row(s). Care items nobody has handled yet are kept.")
    return 0


def cmd_forget(args: argparse.Namespace) -> int:
    n = store.forget_user(args.platform, args.username)
    print(f"erased {n} comment(s) by @{args.username.lstrip('@')} on {args.platform}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("accounts", help="show the accounts configured as MMTF's own")

    c = sub.add_parser("collect", help="read and triage the comments on our own posts")
    c.add_argument("--platform", required=True, choices=list(accounts.SUPPORTED))
    c.add_argument("--account", help="which of our accounts (needed only if several are configured)")
    c.add_argument("--post-url", action="append", help="a specific post of ours (repeatable); its owner is checked")
    c.add_argument("--posts", type=int, default=10, help="how many recent posts (default 10)")
    c.add_argument("--comments", type=int, default=500, help="comments per post (default 500)")
    c.add_argument("--max-credits", type=float, default=80.0, help="stop before the next post once this many credits are spent")
    c.add_argument("--allow-fallback", action="store_true", help="if TrueScrape is unavailable or over budget, also use SocialCrawl / Apify (pay per result)")
    c.add_argument("--export", action="store_true", help="also write a CSV of this account's collected comments")

    q = sub.add_parser("queue", help="comments that need a person (most urgent first)")
    q.add_argument("--label", nargs="+", choices=list(CARE_LABELS))
    q.add_argument("--status", nargs="+", default=["new"], choices=list(STATUSES))
    q.add_argument("--platform")
    q.add_argument("--account")
    q.add_argument("--limit", type=int, default=20)
    q.add_argument("--no-text", action="store_true", help="hide usernames, comments and drafts (for sharing a screen)")

    h = sub.add_parser("handle", help="record what was done with a queue item")
    h.add_argument("key", help="the key (or its first 6+ characters) shown in the queue")
    h.add_argument("status", choices=list(STATUSES))
    h.add_argument("--by", help="who handled it")
    h.add_argument("--note")

    e = sub.add_parser("export", help="CSV of collected comments (personal data)")
    e.add_argument("--platform")
    e.add_argument("--account")
    e.add_argument("--label", nargs="+")

    sub.add_parser("stats", help="counts and waiting time")
    pg = sub.add_parser("purge", help="delete old handled items")
    pg.add_argument("--days", type=int, default=store.DEFAULT_RETENTION_DAYS)
    f = sub.add_parser("forget", help="erase one commenter's rows")
    f.add_argument("--platform", required=True)
    f.add_argument("--username", required=True)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    handlers: Dict[str, Any] = {"accounts": cmd_accounts, "collect": cmd_collect, "queue": cmd_queue, "handle": cmd_handle,
                                "export": cmd_export, "stats": cmd_stats, "purge": cmd_purge, "forget": cmd_forget}
    fn = handlers[args.cmd]
    try:
        return asyncio.run(fn(args)) if asyncio.iscoroutinefunction(fn) else fn(args)
    except (AudienceError, accounts.AccountsError, ValueError) as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
