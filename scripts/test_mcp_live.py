"""Manual live verification script connecting to the MCP Server over stdio.

Tests full end-to-end flow across Phases 1 - 7:
1. MCP Client -> MMTF MCP Server -> health_check()
2. MCP Client -> MMTF MCP Server -> search_mental_health_repositories()
3. MCP Client -> MMTF MCP Server -> inspect_repository_resources()
4. MCP Client -> MMTF MCP Server -> resolve_dataset_metadata()
5. MCP Client -> MMTF MCP Server -> validate_dataset()
6. MCP Client -> MMTF MCP Server -> summarize_dataset()
7. MCP Client -> MMTF MCP Server -> analyze_dataset_relevance()
8. MCP Client -> MMTF MCP Server -> generate_dataset_report()
"""

import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()


async def main() -> None:
    print("=======================================================")
    print("Launching MCP Server over stdio transport...")
    print("=======================================================")

    server_params = StdioServerParameters(
        command="python3",
        args=["-m", "server.server"],
        env=None,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. List tools
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"Registered MCP Tools ({len(tool_names)}): {tool_names}\n")
            expected_tools = [
                "health_check",
                "readiness_check",
                "search_mental_health_repositories",
                "inspect_repository_resources",
                "resolve_dataset_metadata",
                "validate_dataset",
                "summarize_dataset",
                "analyze_dataset_relevance",
                "generate_dataset_report",
                "search_instagram_reels",
                "get_instagram_comments",
                "research_instagram_topic",
            ]
            for t in expected_tools:
                assert t in tool_names, f"Tool '{t}' missing from server!"

            # 2. Invoke health_check
            print("--- [1] Calling 'health_check' MCP tool ---")
            hc_res = await session.call_tool("health_check", {})
            print(f"Result: {hc_res.content[0].text}\n")

            # 3. Invoke readiness_check
            print("--- [1b] Calling 'readiness_check' MCP tool ---")
            ready_res = await session.call_tool("readiness_check", {})
            print(f"Result: {ready_res.content[0].text}\n")


            # 3. Invoke search_mental_health_repositories
            print("--- [2] Calling 'search_mental_health_repositories' MCP tool ---")
            query = "mental health dataset"
            search_res = await session.call_tool(
                "search_mental_health_repositories",
                {"query": query, "limit": 2},
            )
            search_payload = json.loads(search_res.content[0].text)
            print(f"Found {search_payload.get('count')} repository candidates for '{query}':")
            for r in search_payload.get("repositories", []):
                print(f"  * {r['full_name']} (Stars: {r['stars']}, Language: {r['language']})")
            print()

            # 4. Invoke inspect_repository_resources
            target_owner = "kharrigian"
            target_repo = "mental-health-datasets"
            print(f"--- [3] Calling 'inspect_repository_resources' for {target_owner}/{target_repo} ---")
            inspect_res = await session.call_tool(
                "inspect_repository_resources",
                {"owner": target_owner, "repository": target_repo},
            )
            inspect_payload = json.loads(inspect_res.content[0].text)
            candidates = inspect_payload.get("dataset_candidates", [])
            print(f"Discovered {len(candidates)} dataset candidate(s) in {target_owner}/{target_repo}.")
            selected_url = "https://huggingface.co/datasets/dair-ai/emotion"
            print(f"Targeting external dataset for validation & Gemini: {selected_url}\n")

            # 5. Invoke resolve_dataset_metadata
            print(f"--- [4] Calling 'resolve_dataset_metadata' for {selected_url} ---")
            resolve_res = await session.call_tool(
                "resolve_dataset_metadata",
                {"dataset_url": selected_url},
            )
            resolve_payload = json.loads(resolve_res.content[0].text)
            print(f"Status:   {resolve_payload.get('status')}")
            print(f"Provider: {resolve_payload.get('provider')}")
            ds = resolve_payload.get("dataset", {})
            print(f"Dataset:  {ds.get('name')} | Platform: {ds.get('source_platform')} | License: {ds.get('license')}\n")

            # 6. Invoke validate_dataset
            print(f"--- [5] Calling 'validate_dataset' for {selected_url} ---")
            val_res = await session.call_tool(
                "validate_dataset",
                {"dataset_url": selected_url},
            )
            val_payload = json.loads(val_res.content[0].text)
            val = val_payload.get("validation", {})
            print(f"Validation Status: {val.get('validation_status')}")
            print(f"License Status:    {val.get('license_status')} ({val.get('license_name')})")
            print(f"Privacy Status:    {val.get('privacy_status')}")
            print(f"Provenance Status: {val.get('provenance_status')}\n")

            # 7. Invoke summarize_dataset (Phase 7)
            print(f"--- [6] Calling 'summarize_dataset' for {selected_url} ---")
            summary_res = await session.call_tool(
                "summarize_dataset",
                {"dataset_url": selected_url},
            )
            summary_payload = json.loads(summary_res.content[0].text)
            print(f"Status: {summary_payload.get('status')}")
            if summary_payload.get("status") == "success":
                s = summary_payload.get("summary", {})
                print(f"Summary:   {s.get('summary')}")
                print(f"Purpose:   {s.get('purpose')}")
                print(f"Privacy:   {s.get('documented_privacy')}")
            else:
                print(f"Error Type: {summary_payload.get('error_type')}: {summary_payload.get('message')}")
            print()

            # 8. Invoke analyze_dataset_relevance (Phase 7)
            print(f"--- [7] Calling 'analyze_dataset_relevance' for {selected_url} ---")
            rel_res = await session.call_tool(
                "analyze_dataset_relevance",
                {"dataset_url": selected_url},
            )
            rel_payload = json.loads(rel_res.content[0].text)
            print(f"Status: {rel_payload.get('status')}")
            if rel_payload.get("status") == "success":
                rel = rel_payload.get("relevance", {})
                cat = rel_payload.get("category_classification", {})
                print(f"Relevance: {rel.get('relevance')} (Confidence: {rel.get('confidence')})")
                print(f"Reason:    {rel.get('reason')}")
                print(f"Category:  {cat.get('gemini_category')} (Deterministic: {cat.get('deterministic_type')})")
            else:
                print(f"Error Type: {rel_payload.get('error_type')}: {rel_payload.get('message')}")
            print()

            # 9. Invoke generate_dataset_report (Phase 7)
            print(f"--- [8] Calling 'generate_dataset_report' for {selected_url} ---")
            rep_res = await session.call_tool(
                "generate_dataset_report",
                {"dataset_url": selected_url},
            )
            rep_payload = json.loads(rep_res.content[0].text)
            print(f"Status: {rep_payload.get('status')}")
            if rep_payload.get("status") == "success":
                rep = rep_payload.get("report", {})
                print(f"Dataset Name: {rep.get('dataset_name')}")
                print(f"Purpose:      {rep.get('purpose')}")
                print(f"License:      {rep.get('license')}")
            else:
                print(f"Error Type: {rep_payload.get('error_type')}: {rep_payload.get('message')}")
            print()

    print("=======================================================")
    print("MCP Live Verification (Phases 1 - 7) Completed Successfully!")
    print("=======================================================")


if __name__ == "__main__":
    asyncio.run(main())
