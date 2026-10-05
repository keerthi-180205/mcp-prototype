"""Feasibility experiment script to discover and inspect GitHub repositories and datasets

Investigates social-media mental-health datasets across 12 target queries,
extracting documented schemas, timestamps, identifiers, and collection periods.
"""

import asyncio
import json
import os
import re
from typing import Any, Dict, List, Set

from dotenv import load_dotenv

load_dotenv()

from server.providers.github import GitHubProvider
from server.providers.resolver import resolve_dataset_provider
from server.validation.validator import DatasetValidator

QUERIES = [
    "mental health social media dataset",
    "mental health Twitter dataset",
    "mental health Reddit dataset",
    "mental health Instagram dataset",
    "mental health LinkedIn dataset",
    "mental health YouTube comments dataset",
    "mental health comments dataset",
    "mental health social media posts",
    "depression Twitter dataset",
    "anxiety Twitter dataset",
    "stress social media dataset",
    "emotional support social media dataset",
]


async def run_study():
    github = GitHubProvider()
    validator = DatasetValidator()

    print("=====================================================================")
    print("STARTING SOCIAL MEDIA MENTAL-HEALTH DATASET FEASIBILITY INVESTIGATION")
    print("=====================================================================\n")

    repo_map: Dict[str, Dict[str, Any]] = {}
    query_hits: Dict[str, List[str]] = {}

    for q in QUERIES:
        print(f"[*] Searching query: '{q}'...")
        try:
            candidates = await github.search_repositories(query=q, limit=5)
            query_hits[q] = [c.full_name for c in candidates]
            for c in candidates:
                if c.full_name not in repo_map:
                    repo_map[c.full_name] = {
                        "candidate": c,
                        "queries": [q],
                    }
                else:
                    repo_map[c.full_name]["queries"].append(q)
            print(f"    -> Found {len(candidates)} candidates.")
        except Exception as exc:
            print(f"    -> Error searching query '{q}': {exc}")
        await asyncio.sleep(0.5)

    print(f"\n[+] Total unique repository candidates discovered: {len(repo_map)}")

    results = []

    for full_name, repo_info in repo_map.items():
        c = repo_info["candidate"]
        print(f"\n--- Inspecting: {full_name} (Stars: {c.stars}, Lang: {c.language}, Pushed: {c.pushed_at}) ---")
        owner, repo_name = full_name.split("/", 1)

        readme_data = await github.get_repository_readme(owner, repo_name)
        readme_text = readme_data.get("content", "") if readme_data else ""

        # Inspect resources
        resources = await github.inspect_repository_resources(owner, repo_name)
        print(f"    Referenced dataset resources found: {len(resources)}")

        # Analyze README for documented schema, fields, and timelines
        has_post_text = bool(re.search(r"\b(tweet|text|post|content|comment|body|message|utterance|title)\b", readme_text, re.I))
        has_username = bool(re.search(r"\b(username|user_name|screen_name|author|handle|user_id|author_id|author_name)\b", readme_text, re.I))
        has_profile_url = bool(re.search(r"\b(profile_url|profile_link|user_url|author_url)\b", readme_text, re.I))
        has_email = bool(re.search(r"\b(email|e-mail)\b", readme_text, re.I))
        has_phone = bool(re.search(r"\b(phone|telephone|mobile)\b", readme_text, re.I))
        has_timestamp = bool(re.search(r"\b(timestamp|created_at|date|posted_at|post_date|time)\b", readme_text, re.I))

        # Check for actual data files in repo or external datasets
        actual_records_in_repo = bool(re.search(r"\.(csv|json|jsonl|parquet|tsv|tsv\.gz|csv\.gz|zip|tar\.gz)\b", readme_text, re.I))
        
        # Extract date ranges or collection period mentions
        dates_found = re.findall(r"\b(201\d|202[0-6])(?:[-/](?:0?[1-9]|1[0-2])(?:[-/](?:0?[1-9]|[12]\d|3[01]))?)?\b", readme_text)
        collection_period = re.findall(r"\b(?:between|from|collected from|collected between|period of|during)\s+([A-Za-z0-9\s,\-–—to]+(?:201\d|202[0-6]))", readme_text, re.I)

        # Inspect external dataset links if any
        resolved_datasets = []
        for res in resources:
            if res.dataset_url and res.source_platform in ("Hugging Face", "Kaggle", "Zenodo"):
                print(f"    -> Resolving external dataset: {res.dataset_url} ({res.source_platform})")
                try:
                    provider = resolve_dataset_provider(res.dataset_url)
                    meta = await provider.get_dataset_metadata(provider.extract_identifier(res.dataset_url))
                    resolved_datasets.append(meta)
                except Exception as exc:
                    print(f"       Could not resolve {res.dataset_url}: {exc}")

        results.append({
            "repository": full_name,
            "url": c.html_url,
            "description": c.description,
            "stars": c.stars,
            "pushed_at": c.pushed_at,
            "updated_at": c.updated_at,
            "queries": repo_info["queries"],
            "readme_len": len(readme_text),
            "actual_records_hint": actual_records_in_repo,
            "has_post_text": has_post_text,
            "has_username": has_username,
            "has_profile_url": has_profile_url,
            "has_email": has_email,
            "has_phone": has_phone,
            "has_timestamp": has_timestamp,
            "license": c.license,
            "privacy_statuses": [r.privacy_status for r in resources if r.privacy_status],
            "collection_period_snippets": collection_period[:3],
            "years_mentioned": sorted(list(set(dates_found))),
            "resources_count": len(resources),
            "resources": [r.model_dump() for r in resources],
            "resolved_datasets": [d.model_dump() for d in resolved_datasets],
        })
        await asyncio.sleep(0.3)


    out_file = "scripts/feasibility_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\n[+] Feasibility analysis saved to {out_file}")


if __name__ == "__main__":
    asyncio.run(run_study())
