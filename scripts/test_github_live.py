"""Manual verification script for testing live GitHub REST API repository discovery.

This script is strictly for manual/optional verification and is NOT run as part of the automated pytest suite.
"""

import asyncio
import json
from pathlib import Path
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from server.providers.github import GitHubProvider


async def run_live_search(query: str, limit: int = 5, updated_after: str | None = None) -> None:
    print(f"\n=======================================================")
    print(f"Executing Live GitHub API Query: '{query}' (limit={limit})")
    print(f"=======================================================")

    provider = GitHubProvider()

    try:
        results = await provider.search_repositories(
            query=query,
            limit=limit,
            updated_after=updated_after,
        )

        print(f"Discovered {len(results)} repository candidate(s):\n")
        for idx, repo in enumerate(results, start=1):
            print(f"[{idx}] {repo.full_name} (Stars: {repo.stars}, Forks: {repo.forks})")
            print(f"    URL:         {repo.html_url}")
            print(f"    Description: {repo.description or 'No description provided'}")
            print(f"    Language:    {repo.language or 'None'}")
            print(f"    Topics:      {repo.topics}")
            print(f"    License:     {repo.license or 'None'}")
            print(f"    Updated At:  {repo.updated_at}")
            print(f"    Source:      {repo.source}")
            print()

        if results:
            print("First Candidate Raw Model Dump (JSON):")
            print(json.dumps(results[0].model_dump(), indent=2))

    except Exception as exc:
        print(f"Error during live search: {exc}", file=sys.stderr)


async def main() -> None:
    queries = [
        "mental health dataset",
        "mental health",
        "depression dataset",
    ]

    for q in queries:
        await run_live_search(q, limit=3)


if __name__ == "__main__":
    asyncio.run(main())
