"""Live end-to-end run through the MCP tool functions: start -> poll status -> results -> export.

Usage: python scripts/collect_job_live.py --topic "Asian Games 2026" --platforms youtube reddit x instagram --target 500
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server.server as srv  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", default="Asian Games 2026")
    ap.add_argument("--platforms", nargs="*", default=None)
    ap.add_argument("--target", type=int, default=500)
    ap.add_argument("--max-minutes", type=int, default=10)
    args = ap.parse_args()

    started = await srv.start_comment_collection(args.topic, args.platforms, args.target, max_minutes=args.max_minutes)
    print("START:", json.dumps(started, ensure_ascii=False))
    job_id = started["job_id"]
    while True:
        st = srv.get_collection_status(job_id)
        print("STATUS:", st["status"], "|", st["summary"])
        if st["finished"]:
            break
        await asyncio.sleep(10)

    res = srv.get_collection_results(job_id, page=1, page_size=3)
    print("COUNTS:", json.dumps(res["counts_per_platform"]), "total", res["total_comments"])
    print("BELOW_TARGET:", json.dumps(res["below_target"], ensure_ascii=False))
    print("USAGE:", json.dumps(st.get("usage")))
    for plat, rows in res["top_comments"].items():
        for r in rows[:2]:
            print(f"  TOP[{plat}] @{r['username']} ({r['likes']} likes): {r['comment'][:90]!r}")
    for fmt in ("csv", "json"):
        print("EXPORT:", json.dumps(srv.export_collection_results(job_id, fmt)))


if __name__ == "__main__":
    asyncio.run(main())
