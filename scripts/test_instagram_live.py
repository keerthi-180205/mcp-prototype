#!/usr/bin/env python3
"""Manual verification script for testing live Apify Instagram data acquisition.

Supports:
1. Topic Search & Research:
   python scripts/test_instagram_live.py "sports"
   python scripts/test_instagram_live.py "football"

2. Direct Post/Reel Comments Extraction:
   python scripts/test_instagram_live.py "https://www.instagram.com/reel/C_example123/"
   python scripts/test_instagram_live.py "https://www.instagram.com/p/DeCOZfzDMqR/" 10

Requires APIFY_API_TOKEN in .env or environment.
"""

import asyncio
import json
import os
from pathlib import Path
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.config import get_settings
from server.services.instagram import InstagramService, validate_instagram_url


async def run_live_demo() -> None:
    settings = get_settings()

    print("=======================================================")
    print("Apify + Instagram Live Acquisition Verification")
    print("=======================================================")

    if not settings.apify_api_token:
        print("\n[NOTE] APIFY_API_TOKEN is not set in environment or .env.")
        print("Set APIFY_API_TOKEN=<your_token> to execute live Apify queries.")
        print("Skipping live network calls.\n")
        return

    masked_token = f"{settings.apify_api_token[:3]}...{settings.apify_api_token[-3:]}"
    print(f"Loaded Apify Token: {masked_token}")
    print(f"Base URL:           {settings.apify_api_base_url}")
    print(f"Search Actor:       {settings.apify_instagram_search_actor}")
    print(f"Comments Actor:     {settings.apify_instagram_comments_actor}")
    print("=======================================================\n")

    service = InstagramService()
    input_arg = sys.argv[1] if len(sys.argv) > 1 else "sports"
    limit_arg = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 5

    # Check if the input argument is a direct Instagram post/reel URL
    is_url = ("instagram.com" in input_arg) or input_arg.startswith("http://") or input_arg.startswith("https://")

    if is_url:
        print(f"Targeting Specific Instagram Post/Reel URL: {input_arg}")
        print(f"Fetching up to {limit_arg} comment(s)...")
        try:
            target_url = validate_instagram_url(input_arg)
            comments_res = await service.get_post_comments(post_url=target_url, max_comments=limit_arg)
            print(f"\nSuccessfully retrieved {len(comments_res.comments)} comment(s) for {target_url}:")
            for c_idx, comm in enumerate(comments_res.comments, start=1):
                commenter = comm.user.username if comm.user and comm.user.username else "Anonymous"
                verified = " [Verified]" if comm.user and comm.user.is_verified else ""
                private = " [Private]" if comm.user and comm.user.is_private else ""
                print(f"  [{c_idx}] @{commenter}{verified}{private}: {comm.text or '(empty)'} (Likes: {comm.like_count})")

            print("\nFull Normalized JSON Output:")
            print(json.dumps(comments_res.model_dump(), indent=2))
        except Exception as exc:
            print(f"[ERROR] Comment extraction failed: {exc}", file=sys.stderr)
        return

    # Otherwise, execute Topic Search and End-to-End Research
    query = input_arg
    print(f"Step 1: Searching Instagram Reels for '{query}' (limit=2)...")
    try:
        posts = await service.search_posts_or_reels(query=query, max_results=2)
        print(f"Discovered {len(posts)} post(s):")
        for idx, post in enumerate(posts, start=1):
            print(f"  [{idx}] URL: {post.url}")
            print(f"      Caption: {post.caption[:60] if post.caption else 'None'}...")
            print(f"      Author:  {post.author.username if post.author else 'None'}")
            print(f"      Likes:   {post.like_count}, Comments: {post.comment_count}")

        if posts and posts[0].url:
            target_url = posts[0].url
            # 2. Get Comments (low limit: 3)
            print(f"\nStep 2: Fetching comments for {target_url} (limit=3)...")
            comments_res = await service.get_post_comments(post_url=target_url, max_comments=3)
            print(f"Retrieved {len(comments_res.comments)} comment(s):")
            for c_idx, comm in enumerate(comments_res.comments, start=1):
                commenter = comm.user.username if comm.user and comm.user.username else "Anonymous"
                print(f"  [{c_idx}] @{commenter}: {comm.text[:60] if comm.text else ''} (Likes: {comm.like_count})")

        # 3. End-to-end Topic Research (low limit: max_posts=1, max_comments_per_post=2)
        print(f"\nStep 3: End-to-end Topic Research for '{query}' (max_posts=1, max_comments_per_post=2)...")
        research = await service.research_topic(
            query=query,
            max_posts=1,
            max_comments_per_post=2,
        )
        print(f"Completed topic research for '{research.query}'. Results JSON:")
        print(json.dumps(research.model_dump(), indent=2))

    except Exception as exc:
        print(f"[ERROR] Live call failed: {exc}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(run_live_demo())
