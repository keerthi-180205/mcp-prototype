"""Live verification script for Gemini integration (Phase 7).

Only executes live Gemini API calls if GEMINI_API_KEY is configured in the environment.
Retrieves metadata for a known public dataset, validates it, and generates structured interpretations via Gemini.
"""

import asyncio
import os
from pathlib import Path
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv()

from server.llm import GeminiClient
from server.providers.huggingface import HuggingFaceProvider
from server.validation import DatasetValidator


async def main() -> None:
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not api_key.strip():
        print("=======================================================")
        print("Live Gemini Verification: SKIPPED")
        print("GEMINI_API_KEY environment variable is not configured.")
        print("To run live Gemini tests, set GEMINI_API_KEY in your environment or .env file.")
        print("=======================================================")
        sys.exit(0)

    print("=======================================================")
    print("Executing Live Gemini Integration Verification...")
    print("=======================================================\n")

    hf_provider = HuggingFaceProvider()
    validator = DatasetValidator()
    client = GeminiClient(api_key=api_key)

    # 1. Retrieve metadata
    dataset_identifier = "dair-ai/emotion"
    print(f"[1/4] Retrieving official metadata for '{dataset_identifier}' from Hugging Face...")
    metadata = await hf_provider.get_dataset_metadata(dataset_identifier)
    print(f"      Platform: {metadata.source_platform} | License: {metadata.license}")

    # 2. Validate metadata
    print(f"\n[2/4] Validating metadata deterministically...")
    validation = validator.validate(metadata)
    print(f"      Validation Status: {validation.validation_status}")
    print(f"      Privacy Status:    {validation.privacy_status}")
    print(f"      License Status:    {validation.license_status}")

    # 3. Gemini Summary
    print(f"\n[3/4] Requesting structured summary from Gemini ({client.model})...")
    summary = await client.summarize_dataset(metadata, validation)
    print(f"      Summary:     {summary.summary}")
    print(f"      Data Type:   {summary.data_type}")
    print(f"      Purpose:     {summary.purpose}")
    print(f"      Privacy:     {summary.documented_privacy}")
    print(f"      License:     {summary.documented_license}")
    print(f"      Limitations: {summary.limitations}")

    # 4. Gemini Relevance & Categorization
    print(f"\n[4/4] Requesting relevance and categorization from Gemini...")
    relevance = await client.assess_relevance(metadata, validation)
    classification = await client.classify_dataset(metadata, validation)
    print(f"      Relevance:      {relevance.relevance} (Confidence: {relevance.confidence})")
    print(f"      Reason:         {relevance.reason}")
    print(f"      Category:       {classification.gemini_category} (Original: {classification.deterministic_type})")

    # 5. Full Report
    print(f"\n[5/5] Generating full human-readable report...")
    report = await client.generate_dataset_report(metadata, validation)
    print("-------------------------------------------------------")
    print(report.formatted_report)
    print("-------------------------------------------------------")

    print("\n=======================================================")
    print("Live Gemini Verification: SUCCESSFUL!")
    print("=======================================================")


if __name__ == "__main__":
    asyncio.run(main())
