#!/usr/bin/env python3
"""Interactive live verification script for Universal Social Intelligence & Outreach Data Platform.

Usage:
    python scripts/test_social_intelligence_live.py
    python scripts/test_social_intelligence_live.py --topic "AI tools" --platforms youtube github --months 6
    python scripts/test_social_intelligence_live.py --topic "fitness" --platforms instagram youtube --limit 3
    python scripts/test_social_intelligence_live.py --topic "ebook selling" --platforms github
"""

import argparse
import asyncio
import json
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Ensure workspace root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.providers.social.registry import get_social_registry
from server.services.filtering import (
    filter_by_recency,
    filter_by_relevance,
    generate_social_report,
)
from server.services.social_intelligence import get_social_intelligence_service
from server.storage.sqlite import get_social_records, get_social_stats, save_social_records



async def run_live_check(topic: str, platforms: list, months: int, limit: int):
    print("=" * 65)
    print("UNIVERSAL SOCIAL INTELLIGENCE & DATA PLATFORM - LIVE CHECK")
    print("=" * 65)
    print(f"Target Topic:       {topic!r}")
    print(f"Target Platforms:   {platforms}")
    print(f"Recency Window:     Last {months} months")
    print(f"Max Per Platform:   {limit}")
    print("=" * 65)

    registry = get_social_registry()
    social_service = get_social_intelligence_service()

    # 1. Health & Capability Check
    print("\n[Step 1] Checking Provider Capabilities & Agent Reach...")
    health = await registry.get_system_health()
    agent_reach = health.get("capability_layers", {}).get("agent_reach", {})
    channels = agent_reach.get("available_channels", [])
    print(f"  * Agent Reach Installed: {agent_reach.get('installed', False)}")
    print(f"  * Available Channels:     {channels or 'None / check agent-reach doctor'}")

    for p in platforms:
        prov = registry.get_provider(p)
        status = prov.is_available() if prov else False
        name = prov.provider_name if prov else "None"
        print(f"  * Platform '{p}': provider={name}, available={status}")

    # 2. Multi-Platform Search & Discovery
    print(f"\n[Step 2] Executing Multi-Platform Discovery for {topic!r}...")
    records = await social_service.search_multi_platform(
        topic=topic,
        platforms=platforms,
        months_back=months,
        max_results_per_platform=limit,
        min_relevance=0.1,
        auto_store=True,
    )
    print(f"  -> Discovered & Normalized {len(records)} relevant records.")

    for i, r in enumerate(records, 1):
        print(f"\n  [{i}] [{r.platform.upper()}] ({r.content_type})")
        print(f"      Title/Caption: {r.content.title or r.content.caption or r.content.text[:80]}")
        print(f"      Author:        {r.author.username or 'Unknown'}")
        print(f"      URL:           {r.source_url}")
        print(f"      Published At:  {r.published_at or 'Unknown'}")
        print(f"      Engagement:    Likes={r.engagement.likes or 0}, Comments={r.engagement.comments or 0}, Views={r.engagement.views or 0}")
        print(f"      Provenance:    {r.metadata.source_provider} ({r.metadata.backend_tool or 'native'})")

    # 3. Deduplication & Storage Verification
    print("\n[Step 3] Verifying SQLite Storage & Deduplication...")
    stats = get_social_stats()
    print(f"  * Total Stored Records in SQLite:      {stats.get('total_records')}")
    print(f"  * Total Stored Interactions (Comments): {stats.get('total_interactions')}")
    print(f"  * Stored Platforms Breakdown:           {stats.get('platforms')}")

    # 4. Generate Structured Report
    print(f"\n[Step 4] Generating Executive Analytical Report...")
    report = generate_social_report(records, topic=topic)
    print(f"  * Report Topic:            {report.topic}")
    print(f"  * Total Records Analyzed:  {report.total_records}")
    print(f"  * Total Interactions:      {report.total_interactions}")
    print(f"  * Platforms Covered:       {[p.platform for p in report.platforms_covered]}")
    if report.top_records:
        top = report.top_records[0]
        print(f"  * Top Ranked Content:      [{top.platform}] {top.content.title or top.content.caption[:60]} ({top.source_url})")

    print("\n" + "=" * 65)
    print("SUCCESS: Multi-platform intelligence flow completed successfully!")
    print("=" * 65)


def main():
    parser = argparse.ArgumentParser(description="Live test for Universal Social Intelligence MCP Platform")
    parser.add_argument("--topic", default="AI tools", help="Topic to search (e.g. 'fitness', 'AI tools', 'mental health')")
    parser.add_argument("--platforms", nargs="+", default=["youtube", "github"], help="Platforms to query (youtube, github, instagram, web, etc.)")
    parser.add_argument("--months", type=int, default=6, help="Recency cutoff in months (e.g. 3, 6, 12)")
    parser.add_argument("--limit", type=int, default=2, help="Max results per platform")

    args = parser.parse_args()
    asyncio.run(run_live_check(args.topic, args.platforms, args.months, args.limit))


if __name__ == "__main__":
    main()
