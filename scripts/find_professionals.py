"""Find, review and export therapists / psychologists / psychiatrists who publish how to reach them.

  plan     show the Google queries and the maximum credits a run could use (spends nothing)
  run      search, classify, read bios and websites, save everything as "new" for review
  list     the review queue (best first)           show     one person with every channel and its source
  review   approve | reject | dnc (do not contact) | new       licence   record your register check
  enrich   find each individual's own website from their name and read its contact page (1 search credit each)
  suppress add an email / phone / domain / profile URL to the do-not-contact list
  export   CSV / JSON of APPROVED people only (do-not-contact and suppressed people are never exported)

Examples
  python scripts/find_professionals.py plan --city Bangalore
  python scripts/find_professionals.py run --city Bangalore --specialties "clinical psychologist" psychiatrist
  python scripts/find_professionals.py list --has-channel any --limit 20
  python scripts/find_professionals.py review 3fa9c1 approve --note "RCI register checked"
  python scripts/find_professionals.py export
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

from pydantic import ValidationError  # noqa: E402

from server.professionals.enrich import audit_enrichments, enrich_professionals  # noqa: E402
from server.professionals.export import export_professionals  # noqa: E402
from server.professionals.finder import ProfessionalFinder  # noqa: E402
from server.professionals.models import DEFAULT_SPECIALTIES, REVIEW_STATUSES, FinderParams  # noqa: E402
from server.professionals.queries import build_queries, estimate  # noqa: E402
from server.storage import professionals as store  # noqa: E402

REVIEW_ALIASES = {"approve": "approved", "approved": "approved", "reject": "rejected", "rejected": "rejected",
                  "dnc": "do_not_contact", "do_not_contact": "do_not_contact", "new": "new", "reset": "new"}


def _params(args: argparse.Namespace) -> FinderParams:
    try:
        return FinderParams(
            city=args.city, specialties=args.specialties or list(DEFAULT_SPECIALTIES), focus=args.focus,
            platforms=args.platforms, pages=args.pages, country=args.country, max_serp_credits=args.max_credits,
            max_profile_lookups=args.max_profiles, max_sites=args.max_sites,
        )
    except ValidationError as exc:
        raise SystemExit("invalid options: " + "; ".join(f"{e['loc'][0]}: {e['msg']}" for e in exc.errors()))


def _line(p: Dict[str, Any]) -> str:
    best = store.best_channel(p["channels"])
    flag = " !" if p["needs_review_reason"] else "  "
    sup = " [SUPPRESSED]" if p.get("suppressed") else ""
    return (f"{p['pro_id'][:8]} {p['fit_score']:5.1f}{flag} {p['review_status']:<14} {p['role']:<24} "
            f"{(p['name'] or '?')[:28]:<28} {(best['kind'] + ': ' + best['value'])[:48] if best else '(no channel)'}{sup}")


def cmd_plan(args: argparse.Namespace) -> int:
    p = _params(args)
    print(f"City: {p.city} | specialties: {', '.join(p.specialties)} | platforms: {', '.join(p.platforms)} | pages per query: {p.pages}\n")
    for q in build_queries(p):
        print(f"  [{q.platform:9}] {q.q}")
    e = estimate(p)
    print(f"\nA run can use at most: {e['serp_credits_max']} Bright Data search credits, "
          f"{e['instagram_profile_credits_max']} TrueScrape credits (Instagram bios), and open up to {e['websites_to_open_max']} websites (free).")
    return 0


async def cmd_run(args: argparse.Namespace) -> int:
    p = _params(args)
    e = estimate(p)
    print(f"Run for {p.city}: up to {e['serp_credits_max']} search credits + {e['instagram_profile_credits_max']} Instagram-bio credits.")
    run_id = f"pro_cli_{os.urandom(4).hex()}"
    store.create_run(run_id, p.model_dump(), args.db)
    last = {"phase": ""}

    def progress(info: Dict[str, Any]) -> None:
        if info.get("phase") != last["phase"]:
            last["phase"] = info.get("phase", "")
            print(f"  ... {last['phase']}")

    try:
        result = await ProfessionalFinder(db_path=args.db, use_llm=not args.no_gemini).run(p, run_id=run_id, on_progress=progress)
    except Exception as exc:
        store.update_run(run_id, status="failed", error=str(exc)[:240], db_path=args.db)
        print(f"Run failed: {type(exc).__name__}: {exc}")
        return 1
    stats, notes = result["stats"], result["notes"]
    store.update_run(run_id, status="completed", stats={**stats, "notes": notes}, db_path=args.db)

    print(f"\nFound {stats.get('candidates', 0)} candidates -> kept {stats.get('kept', 0)} "
          f"({stats.get('new_records', 0)} new, {stats.get('already_known', 0)} already known)")
    dropped = {k[9:]: v for k, v in stats.items() if k.startswith("dropped:")}
    if dropped:
        print("Dropped: " + "; ".join(f"{v} x {k}" for k, v in sorted(dropped.items(), key=lambda kv: -kv[1])))
    print(f"Credits: {stats.get('serp_credits', 0)} search, {stats.get('instagram_profile_credits', 0)} Instagram bios. "
          f"Websites: " + (", ".join(f"{k[5:]}={v}" for k, v in sorted(stats.items()) if k.startswith("site_")) or "none opened"))
    print(f"With a direct channel (email / phone / form / WhatsApp): {stats.get('with_direct_channel', 0)} of {stats.get('kept', 0)}; "
          f"flagged for a closer look: {stats.get('needs_review', 0)}")
    for n in notes:
        print(f"  note: {n}")
    print("\nTop of the review queue:")
    for item in store.list_professionals(statuses=["new"], limit=args.show, db_path=args.db)[1]:
        print("  " + _line(item))
    print("\nNext: review each one (python scripts/find_professionals.py show <id> / review <id> approve), then export.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    statuses = None if args.status == "all" else [args.status]
    total, items = store.list_professionals(
        statuses=statuses, role=args.role, entity_type=args.entity, city=args.city, min_confidence=args.min_confidence,
        has_channel=args.has_channel, needs_review=True if args.flagged else None, q=args.q, sort=args.sort,
        limit=args.limit, offset=args.offset, db_path=args.db)
    print(f"{total} match(es){' (showing ' + str(len(items)) + ')' if total > len(items) else ''}   [! = needs a closer look]")
    for item in items:
        print(_line(item))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    p = store.get_professional(store.resolve_pro_id(args.id, args.db), args.db)
    print(f"{p['name']}  ({p['entity_type']}, {p['role']}, confidence {p['confidence']}, classified by {p['classified_by']})")
    print(f"  id {p['pro_id']} | status {p['review_status']}" + (f" - {p['review_note']}" if p["review_note"] else "") + (f" | SUPPRESSED ({p['suppressed']})" if p["suppressed"] else ""))
    print(f"  headline: {p['headline']}\n  evidence: {p['evidence']}\n  credentials: {', '.join(p['credentials']) or '-'} | city match: {p['city_match']} | followers: {p['followers']}")
    lic = p["licence"]
    print(f"  licence claim: {lic['claim'] or '-'} | numbers: {', '.join(n['body'] + ' ' + n['number'] for n in lic['numbers']) or '-'} | verified by a person: {lic['verified']}")
    if p["needs_review_reason"]:
        print(f"  ! look closer: {p['needs_review_reason']}")
    print(f"  profile: {p['profile_url']}" + (f"\n  website: {p['website_url']}" if p["website_url"] else ""))
    print("  channels (value <- where it was found):")
    for c in p["channels"] or []:
        print(f"    {c['kind']:<13} {c['value']}{'  (generic inbox)' if c['is_generic'] else ''}   <- {c['found_via']} @ {c['source_url']}")
    if not p["channels"]:
        print("    none")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    pid = store.resolve_pro_id(args.id, args.db)
    status = REVIEW_ALIASES.get(args.decision.lower())
    if status is None:
        raise SystemExit(f"decision must be one of {sorted(set(REVIEW_ALIASES))}")
    p = store.set_review(pid, status, args.note or "", args.db)
    print(f"{p['name']}: {p['review_status']}" + ("  (their profile, emails and phones are now on the do-not-contact list)" if status == "do_not_contact" else ""))
    return 0


def cmd_licence(args: argparse.Namespace) -> int:
    pid = store.resolve_pro_id(args.id, args.db)
    value = {"verified": True, "not-found": False, "clear": None}[args.result]
    store.set_licence_verified(pid, value, args.db)
    print(f"licence check recorded: {args.result}")
    return 0


async def cmd_enrich(args: argparse.Namespace) -> int:
    if args.audit:
        res = audit_enrichments(args.db)
        print(f"checked {res['checked']} name-search websites against the current rules; undid {res['reset']} (they will be searched again by the next `enrich` run)")
        return 0
    res = await enrich_professionals(db_path=args.db, limit=args.limit, max_credits=args.max_credits, force=args.force,
                                     on_progress=lambda m: print(f"  ... {m}", flush=True))
    st = res["stats"]
    print(f"searched {st.get('searched', 0)} people ({st.get('search_credits', 0)} search credits): website found for {st.get('found', 0)} "
          f"({st.get('found_direct_channel', 0)} with an email / phone / form, {st.get('found_no_channel', 0)} without), no confident match for {st.get('no_match', 0)}")
    skipped = {k[8:]: v for k, v in st.items() if k.startswith("skipped_")}
    if skipped:
        print("skipped: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in skipped.items()))
    print("sites: " + (", ".join(f"{k[5:]}={v}" for k, v in sorted(st.items()) if k.startswith("site_")) or "none opened"))
    for n in res["notes"]:
        print(f"  note: {n}")
    print("Each website is a best guess from the name: open it and confirm it is the same person before approving.")
    return 0


def cmd_suppress(args: argparse.Namespace) -> int:
    try:
        norm = store.add_suppression(args.kind, args.value, args.reason or "", args.db)
    except ValueError as exc:
        raise SystemExit(str(exc))
    print(f"suppressed {args.kind}: {norm}")
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    statuses: List[str] = [args.status]
    result = export_professionals(statuses, args.format, db_path=args.db)
    print(f"{result['rows']} row(s) -> {result['path']}")
    if args.status != "approved":
        print("note: exporting people who have not been approved is for internal review only, not for outreach.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=None, help="SQLite file (default: data/social_intelligence.db)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def search_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("--city", required=True)
        p.add_argument("--specialties", nargs="+", help=f"default: {', '.join(DEFAULT_SPECIALTIES)}")
        p.add_argument("--focus", help="topic they post about, e.g. anxiety (narrows Instagram / web queries)")
        p.add_argument("--platforms", nargs="+", default=["linkedin", "instagram", "web"])
        p.add_argument("--pages", type=int, default=1, help="Google result pages per query (1 credit each)")
        p.add_argument("--country", default="in")
        p.add_argument("--max-credits", type=int, default=30, help="hard cap on search credits for this run")
        p.add_argument("--max-profiles", type=int, default=15, help="Instagram bios to read (1 credit each)")
        p.add_argument("--max-sites", type=int, default=25, help="websites to open (free)")

    search_opts(sub.add_parser("plan", help="show queries and maximum cost; spends nothing"))
    r = sub.add_parser("run", help="search and save candidates for review")
    search_opts(r)
    r.add_argument("--no-gemini", action="store_true", help="rules only; never call Gemini")
    r.add_argument("--show", type=int, default=15, help="how many of the best results to print")
    ls = sub.add_parser("list", help="the review queue")
    ls.add_argument("--status", default="new", choices=["all", *REVIEW_STATUSES])
    ls.add_argument("--role")
    ls.add_argument("--entity", choices=["person", "organisation"])
    ls.add_argument("--city")
    ls.add_argument("--min-confidence", type=float, default=0.0)
    ls.add_argument("--has-channel", choices=["any", "email", "personal_email", "phone", "contact_form"])
    ls.add_argument("--flagged", action="store_true", help="only the ones marked ! (need a closer look)")
    ls.add_argument("--q", help="name / headline contains")
    ls.add_argument("--sort", default="fit_score", choices=["fit_score", "confidence", "recent", "name"])
    ls.add_argument("--limit", type=int, default=25)
    ls.add_argument("--offset", type=int, default=0)
    sh = sub.add_parser("show", help="one person with every channel and where it was found")
    sh.add_argument("id")
    rv = sub.add_parser("review", help="record a decision")
    rv.add_argument("id")
    rv.add_argument("decision", help="approve | reject | dnc | new")
    rv.add_argument("--note")
    lc = sub.add_parser("licence", help="record the result of YOUR check in the official register")
    lc.add_argument("id")
    lc.add_argument("result", choices=["verified", "not-found", "clear"])
    sp = sub.add_parser("suppress", help="never contact this email / phone / domain / profile again")
    sp.add_argument("kind", choices=list(store.SUPPRESSION_KINDS))
    sp.add_argument("value")
    sp.add_argument("--reason")
    en = sub.add_parser("enrich", help="find individuals' own websites from their names")
    en.add_argument("--limit", type=int, default=10, help="people to look up (best-ranked first)")
    en.add_argument("--max-credits", type=int, default=15, help="hard cap on search credits")
    en.add_argument("--force", action="store_true", help="search again for people already tried")
    en.add_argument("--audit", action="store_true", help="spend nothing: undo stored websites the current rules would not accept")
    ex = sub.add_parser("export", help="CSV / JSON of approved people")
    ex.add_argument("--status", default="approved", choices=list(REVIEW_STATUSES))
    ex.add_argument("--format", default="csv", choices=["csv", "json"])
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {"plan": cmd_plan, "run": cmd_run, "list": cmd_list, "show": cmd_show, "review": cmd_review,
                "licence": cmd_licence, "suppress": cmd_suppress, "export": cmd_export, "enrich": cmd_enrich}
    fn = handlers[args.cmd]
    try:
        return asyncio.run(fn(args)) if asyncio.iscoroutinefunction(fn) else fn(args)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
