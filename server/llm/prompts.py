"""Prompts and guardrail templates for Gemini dataset interpretation."""

import json
from typing import Any, Dict, Optional

SYSTEM_GUARDRAILS = """You are an objective, evidence-based research dataset assistant for MyMindTherapyFriend (MMTF).
Your role is to interpret, synthesize, and categorize documented dataset metadata and validation findings.

CRITICAL OPERATIONAL RULES:
1. Grounding: Rely strictly and exclusively on the supplied JSON metadata and validation findings.
2. No Hallucination: Do not invent or assume details, authors, attributes, or properties not explicitly provided.
3. No Speculative Privacy Inferences: Never infer privacy or anonymization from public availability or open-source licenses. If no privacy statement was documented, explicitly state: "No explicit dataset-level de-identification or anonymization statement was found in documented metadata."
4. No Legal or Ethical Approval Decisions: Do NOT output legal conclusions, approval decisions, or safety scores (such as 'safe_to_use', 'approved', 'legally_compliant'). You are providing factual evidence and interpretation for human and legal review.
5. Missing Data: If information is missing or not documented, explicitly declare it as "unknown" or "not documented".
6. Fact vs. Interpretation: Keep documented facts distinct from analytical interpretations.
7. Output Format: Output ONLY raw, valid JSON conforming to the requested schema. Do not enclose in markdown code fences unless specifically requested.
"""


def build_summary_prompt(structured_input: Dict[str, Any]) -> str:
    """Build prompt for generating a structured dataset summary."""
    input_str = json.dumps(structured_input, indent=2)
    return f"""{SYSTEM_GUARDRAILS}

TASK: Generate a concise, objective summary of the following dataset based strictly on its documented metadata.

INPUT DATA:
{input_str}

REQUIRED JSON SCHEMA:
{{
  "summary": "A concise, factual 2-3 sentence overview synthesizing the dataset's purpose and contents",
  "data_type": "Primary structure/format of data (e.g. conversation, text, survey)",
  "purpose": "Documented purpose or research goal",
  "likely_category": "Research or usage category",
  "language": "Documented language(s) or 'unknown'",
  "source": "Platform source name and hosting provider",
  "documented_privacy": "Factual statement regarding documented privacy/anonymization (or state that none was documented)",
  "documented_license": "Documented license and any non-commercial or usage scope notes",
  "limitations": [
    "List of documented limitations, missing metadata, or license cautions"
  ]
}}

Respond ONLY with valid JSON.
"""


def build_classification_prompt(structured_input: Dict[str, Any]) -> str:
    """Build prompt for suggesting a dataset category while preserving deterministic type."""
    input_str = json.dumps(structured_input, indent=2)
    return f"""{SYSTEM_GUARDRAILS}

TASK: Suggest a dataset category from the allowed taxonomy based on the documented description, tags, and structure.
The deterministic data_type from the input must be preserved.

ALLOWED CATEGORIES:
- conversation
- text
- survey
- emotion
- sentiment
- mental_health_assessment
- research_data
- multimodal
- other
- unknown

INPUT DATA:
{input_str}

REQUIRED JSON SCHEMA:
{{
  "deterministic_type": "{structured_input.get('dataset', {}).get('data_type', 'unknown')}",
  "gemini_category": "One of the allowed categories listed above",
  "confidence": 0.85,
  "reason": "Clear explanation referencing specific phrases or tags from the documented metadata"
}}

Respond ONLY with valid JSON.
"""


def build_relevance_prompt(structured_input: Dict[str, Any]) -> str:
    """Build prompt for assessing mental-health and therapy research relevance."""
    input_str = json.dumps(structured_input, indent=2)
    return f"""{SYSTEM_GUARDRAILS}

TASK: Assess the relevance of this dataset to mental-health research, psychological counseling, and emotional wellbeing NLP for MyMindTherapyFriend.
IMPORTANT: This is a topical relevance evaluation, NOT a safety, ethical, or legal score.

ALLOWED RELEVANCE LEVELS:
- high: Directly focuses on mental health, therapy transcripts, clinical psychology, distress, or psychological assessments.
- medium: Pertains to general emotion, sentiment, human dialogue, empathy, or social wellbeing.
- low: Peripheral or general domain dataset with minimal mental-health context.
- unknown: Metadata insufficient to determine topical relevance.

INPUT DATA:
{input_str}

REQUIRED JSON SCHEMA:
{{
  "relevance": "high | medium | low | unknown",
  "confidence": 0.85,
  "reason": "Concise factual justification based strictly on the provided metadata topics, title, and description"
}}

Respond ONLY with valid JSON.
"""


def build_report_prompt(
    structured_input: Dict[str, Any],
    relevance_override: Optional[Dict[str, Any]] = None,
) -> str:
    """Build prompt for generating a comprehensive human-readable dataset report."""
    input_str = json.dumps(structured_input, indent=2)
    rel_context = f"\nRELEVANCE CONTEXT: {json.dumps(relevance_override)}" if relevance_override else ""

    return f"""{SYSTEM_GUARDRAILS}

TASK: Generate a comprehensive, professional dataset report combining documented facts and interpretative synthesis.
Ensure missing fields are explicitly identified as unknown or not documented.
Never claim a dataset is anonymized or safe if no explicit statement exists.

INPUT DATA:
{input_str}
{rel_context}

REQUIRED JSON SCHEMA:
{{
  "dataset_name": "Dataset name",
  "source_platform": "Platform source",
  "purpose": "Documented purpose",
  "data_type": "Data type",
  "language": "Documented language or 'unknown'",
  "license": "Documented license name or 'unspecified'",
  "privacy_documentation": "Documented privacy statements or 'No explicit dataset-level de-identification statement was found.'",
  "access_method": "Access method (e.g. public_metadata, authenticated, restricted)",
  "provenance": "Provenance chain and discovery origin",
  "warnings": [
    "Documented warnings, license cautions, or missing information notes"
  ],
  "missing_information": [
    "Key attributes not documented"
  ],
  "relevance": "Summary of topical relevance to mental-health NLP",
  "notes": "Additional notes or 'None'",
  "formatted_report": "A complete, structured plain-text report suitable for researchers and legal review"
}}

Respond ONLY with valid JSON.
"""
