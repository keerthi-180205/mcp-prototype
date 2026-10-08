"""Live smoke test: run the full collection pipeline for ONE platform and print the counts.

Usage: python scripts/collect_live.py --platform youtube --topic "Asian Games 2026" --target 500
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.collection.harvester import harvest_platform  # noqa: E402
from server.collection.models import CollectionLimits, PlatformProgress  # noqa: E402
from server.collection.planner import plan_query  # noqa: E402
from server.collection.registry import get_collector  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform", required=True)
    ap.add_argument("--topic", default="Asian Games 2026")
    ap.add_argument("--target", type=int, default=500)
    ap.add_argument("--max-posts", type=int, default=30)
    ap.add_argument("--max-seconds", type=float, default=600)
    ap.add_argument("--sample", type=int, default=3)
    args = ap.parse_args()

    plan = await plan_query(args.topic)
    print("PLAN:", json.dumps(plan.model_dump(), ensure_ascii=False))
    limits = CollectionLimits(target_comments=args.target, max_posts=args.max_posts, max_seconds=args.max_seconds)
    progress = PlatformProgress(platform=args.platform)
    rows = await harvest_platform(get_collector(args.platform), plan, limits, progress)

    print("PROGRESS:", json.dumps(progress.model_dump(), ensure_ascii=False))
    print(f"RESULT: {args.platform} collected {len(rows)} cleaned comments from "
          f"{len({r.post_url for r in rows})} posts (target {args.target}), stop={progress.stop_reason}")
    for r in rows[: args.sample]:
        print("  SAMPLE:", json.dumps(r.model_dump(), ensure_ascii=False)[:300])


if __name__ == "__main__":
    asyncio.run(main())
