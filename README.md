# MMTF MCP Client Discovery Server

## Project Purpose

This project is an MCP-based technical bridge intended to eventually help **MyMindTherapyFriend (MMTF)** discover potential organizations and research datasets through legitimate structured data sources.

---

## Phase Summary

* **Phase 1 — MCP Server Foundation**: FastMCP server with `health_check()` and stdio transport.
* **Phase 2 — GitHub Repository Discovery Provider**: Modular `GitHubProvider` interfacing with official GitHub REST API (`/search/repositories`).
* **Phase 3 — MCP GitHub Discovery Tools**: Exposes `search_mental_health_repositories` via MCP.
* **Phase 4 — Mental-Health Dataset and Resource Discovery**: Extracts `DatasetCandidate` objects from repository documentation (`/readme`).
* **Phase 5 — External Dataset Connectors**: Added official API connectors for **Hugging Face**, **Kaggle**, and **Zenodo**, with deterministic URL resolution via `resolve_dataset_metadata`.
* **Phase 6 — Dataset Validation, Privacy & Provenance**: Deterministic, evidence-based validation engine analyzing documented licensing, privacy/de-identification statements, sensitive-data warnings, and origin provenance.
* **Phase 7 — Gemini Integration**: Intelligent interpretation layer providing grounded summarization, categorization, relevance analysis, and comprehensive reports over structured metadata and validation findings.

---

## Phase 7 — Gemini Integration

Phase 7 introduces Google Gemini as an interpretation and synthesis layer operating over verified, deterministic dataset metadata and validation findings.

> **Critical Rule**:
> Gemini is an interpretation layer and does not replace deterministic metadata retrieval or validation.
> Gemini must never be used to infer facts that are not present in the source metadata, nor make legal or ethical approval decisions.

### Core Capabilities:
* **Objective Summaries (`summarize_dataset`)**: Synthesizes dataset purpose, data type, documented license, documented privacy statements, and known limitations.
* **Mental-Health Relevance & Categorization (`analyze_dataset_relevance`)**: Assesses topical relevance (`high`, `medium`, `low`, `unknown`) to mental-health/therapy NLP and suggests taxonomy categories while preserving the original deterministic `data_type`.
* **Human-Readable Reports (`generate_dataset_report`)**: Produces structured plain-text reports for researchers and compliance review.
* **Strict Grounding & Schema Validation**: Guardrails enforce that missing data is explicitly stated as unknown, and all responses are validated against Pydantic schemas.

---

## Available MCP Tools

1. `health_check()`:
   * Verifies that the MCP server is running properly.
2. `search_mental_health_repositories(query, limit=20, updated_after=None, language=None)`:
   * Discovers publicly accessible GitHub repositories related to mental health topics or datasets.
3. `inspect_repository_resources(owner, repository)`:
   * Inspects repository README documentation to discover and classify referenced dataset candidates.
4. `resolve_dataset_metadata(dataset_url)`:
   * Resolves an external dataset URL (Hugging Face, Kaggle, Zenodo) and retrieves normalized metadata from its official API.
5. `validate_dataset(dataset_url)`:
   * Deterministically validates an external dataset's license, privacy/anonymization claims, sensitive data warnings, and provenance with evidence records.
6. `summarize_dataset(dataset_url)`:
   * Uses Gemini to generate an objective, structured summary of a dataset based strictly on documented metadata.
7. `analyze_dataset_relevance(dataset_url)`:
   * Uses Gemini to evaluate mental-health NLP relevance and suggested taxonomy categorization.
8. `generate_dataset_report(dataset_url)`:
   * Uses Gemini to generate a complete, formatted human-readable report synthesizing documented facts, validation findings, and interpretation.
9. `search_instagram_reels(query, max_results=5)`:
   * Discovers public Instagram posts or reels for a topic or hashtag using Apify and extracts normalized metrics and author details.
10. `get_instagram_comments(post_url, max_comments=10)`:
    * Extracts public comments and commenter profile metadata for a specific public post or reel URL via Apify.
11. `research_instagram_topic(query, max_posts=5, max_comments_per_post=10)`:
    * End-to-end topic research workflow finding posts and retrieving public comments in a single structured response.

---

## Tool Invocation Examples

### 1. Search Repositories
```python
result = await session.call_tool(
    "search_mental_health_repositories",
    {
        "query": "mental health dataset",
        "limit": 5,
        "updated_after": "2026-01-01"
    }
)
```

### 2. Inspect Repository Documentation for Datasets
```python
result = await session.call_tool(
    "inspect_repository_resources",
    {
        "owner": "kharrigian",
        "repository": "mental-health-datasets"
    }
)
```

### 3. Resolve External Dataset Metadata
```python
result = await session.call_tool(
    "resolve_dataset_metadata",
    {
        "dataset_url": "https://huggingface.co/datasets/dair-ai/emotion"
    }
)
```

### 4. Validate Dataset Licensing, Privacy & Provenance
```python
result = await session.call_tool(
    "validate_dataset",
    {
        "dataset_url": "https://huggingface.co/datasets/dair-ai/emotion"
    }
)
```

### 5. Generate Gemini Dataset Summary
```python
result = await session.call_tool(
    "summarize_dataset",
    {
        "dataset_url": "https://huggingface.co/datasets/dair-ai/emotion"
    }
)
```

### 6. Analyze Mental-Health Relevance & Category
```python
result = await session.call_tool(
    "analyze_dataset_relevance",
    {
        "dataset_url": "https://huggingface.co/datasets/dair-ai/emotion"
    }
)
```

### 7. Generate Comprehensive Human-Readable Report
```python
result = await session.call_tool(
    "generate_dataset_report",
    {
        "dataset_url": "https://huggingface.co/datasets/dair-ai/emotion"
    }
)
```

---

## Data Flow (Phases 1 — 7)

```text
MCP Client
    │
    ├─► [1] search_mental_health_repositories()
    │         └── GitHub REST API (/search/repositories) ──► RepositoryCandidate[]
    │
    ├─► [2] inspect_repository_resources(owner, repo)
    │         └── GitHub REST API (/repos/{owner}/{repo}/readme) ──► DatasetCandidate[]
    │
    ├─► [3] resolve_dataset_metadata(dataset_url)
    │         ├── URL Resolver (huggingface, kaggle, zenodo)
    │         └── Official Platform REST APIs ──► DatasetMetadata
    │
    ├─► [4] validate_dataset(dataset_url)
    │         ├── resolve_dataset_metadata() ──► DatasetMetadata
    │         └── DatasetValidator ──► DatasetValidationResult
    │
    └─► [5] summarize_dataset() / analyze_dataset_relevance() / generate_dataset_report()
              ├── resolve_dataset_metadata() ──► DatasetMetadata
              ├── DatasetValidator ──► DatasetValidationResult
              └── GeminiClient (google.genai)
                    ├── Pydantic-validated JSON Schema
                    └── Guardrails (No hallucination, no legal decisions)
```

---

## Installation & Configuration

Clone the repository and prepare the virtual environment:

```bash
git clone <repository-url>
cd mmtf-mcp-client-discovery

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
```

### Environment Configuration

Copy `.env.example` to `.env` to configure optional and platform credentials:

```bash
cp .env.example .env
```

Available environment variables:
* `GITHUB_TOKEN`: Optional GitHub personal access token (increases rate limit to 5,000 req/hr).
* `HF_TOKEN`: Optional Hugging Face token for gated/private dataset access.
* `KAGGLE_USERNAME` & `KAGGLE_KEY`: Required for official Kaggle API access.
* `ZENODO_TOKEN`: Optional token for Zenodo API access.
* `GEMINI_API_KEY`: Required for Gemini interpretation tools (`summarize_dataset`, `analyze_dataset_relevance`, `generate_dataset_report`).
* `GEMINI_MODEL`: Gemini model identifier (default: `gemini-flash-lite-latest`).
* `GEMINI_TIMEOUT`: Request timeout in seconds (default: `90`).
* `ENVIRONMENT`: Environment identifier (`development` or `production`, default: `development`).
* `LOG_LEVEL`: Logging verbosity level (default: `INFO`).
* `MAX_RETRIES`: Maximum retry attempts on transient network or HTTP 429/5xx failures (default: `3`).
* `RETRY_INITIAL_DELAY`: Initial delay before exponential backoff retry in seconds (default: `0.5`).

---

## Phase 8 — Productionization & Hardening

Phase 8 elevates the system to production-grade resilience, safety, and reliability without altering core interfaces:

1. **Centralized Configuration Hardening (`server/config.py`)**:
   * Encapsulates all environment settings with sensible defaults.
   * Performs lazy on-demand credential validation when a specific provider is used.
   * Masks all sensitive tokens in string and object representations (`repr(settings)`).

2. **Secret Safety & Log Scrubbing (`server/logging_config.py`)**:
   * Automatic `SecretScrubbingFilter` intercepts and redacts `Bearer`, `Basic`, API keys, and passwords from logs.
   * Zero secrets, auth headers, or private user data are ever emitted.

3. **Structured Operational Logging**:
   * Contextual operations log `component`, `operation`, `status`, `duration`, and key-value metrics.
   * Example: `INFO github.search status=success duration=0.75s query=mental health dataset count=2`

4. **Explicit Request Timeouts**:
   * Every external network call (GitHub, Hugging Face, Kaggle, Zenodo, Gemini) enforces explicit timeouts.

5. **Controlled Retry & Exponential Backoff (`server/resilience.py`)**:
   * Automatically retries transient HTTP status codes (`429`, `500`, `502`, `503`, `504`) and network connectivity errors.
   * Fails fast on deterministic client errors (`400`, `401`, `403`, `404`, `422`) with zero unnecessary retries.

---

## Running

Run the MCP server directly using Python's module syntax:

```bash
python -m server.server
```

The server listens on standard input/output (`stdio`) for Model Context Protocol (MCP) JSON-RPC messages.

---

## Testing

Run the full automated test suite (110 offline tests covering all tools, connectors, validation, prompts, Gemini client, configuration, logging, and resilience):

```bash
pytest
```

Run manual live verification scripts (optional, performs real API calls):

* Test GitHub Provider search directly:
  ```bash
  python3 scripts/test_github_live.py
  ```
* Test Gemini integration directly:
  ```bash
  python3 scripts/test_gemini_live.py
  ```
* Test end-to-end MCP Client over stdio (all 8 tools across discovery, metadata, validation, and Gemini interpretation):
  ```bash
  python3 scripts/test_mcp_live.py
  ```

---

## Roadmap

* **Phase 1** → MCP server foundation *(Complete)*
* **Phase 2** → GitHub mental-health repository discovery provider *(Complete)*
* **Phase 3** → MCP GitHub repository discovery tools *(Complete)*
* **Phase 4** → Mental-health dataset and resource discovery *(Complete)*
* **Phase 5** → External dataset connectors (Hugging Face, Kaggle, Zenodo) *(Complete)*
* **Phase 6** → Dataset validation, privacy & provenance *(Complete)*
* **Phase 7** → Gemini interpretation layer *(Complete)*
* **Phase 8** → Productionization, configuration hardening, structured logging, resilience & secret safety *(Complete)*

---

## Instagram + Apify Demo

> **Notice**: This is an initial **proof-of-concept** for public-data acquisition. It strictly queries public posts/reels and public comments returned by Apify Actors without bypassing access controls, accessing private accounts or DMs, or using browser session tokens. Commenter data is treated purely as public interaction metadata; no identity enrichment or sensitive classification is performed.

### 1. Required Environment Variable

Configure your Apify API token in `.env`:

```env
APIFY_API_TOKEN=your_apify_api_token_here
```

Optional tuning parameters (with sensible defaults):

```env
APIFY_API_BASE_URL=https://api.apify.com/v2
APIFY_INSTAGRAM_SEARCH_ACTOR=apify/instagram-scraper
APIFY_INSTAGRAM_COMMENTS_ACTOR=apify/instagram-comment-scraper
APIFY_TIMEOUT=120
```

### 2. How to Run the MCP Server

Run the MCP server over standard I/O:

```bash
python -m server.server
```

Or run the manual live verification script (uses conservative limits):

```bash
python scripts/test_instagram_live.py
```

### 3. Available MCP Tools

* **`search_instagram_reels(query: str, max_results: int = 5)`**:
  Searches public Instagram reels and posts matching a topic query or hashtag.
* **`get_instagram_comments(post_url: str, max_comments: int = 10)`**:
  Fetches public comments and publicly returned commenter profile metadata for a given post/reel URL.
* **`research_instagram_topic(query: str, max_posts: int = 5, max_comments_per_post: int = 10)`**:
  Executes the end-to-end acquisition pipeline: searches for posts on a topic, extracts URLs, and retrieves comments for each post.

### 4. Example Inputs

#### Search Reels
```json
{
  "query": "mental health",
  "max_results": 5
}
```

#### Get Comments
```json
{
  "post_url": "https://www.instagram.com/reel/C_example123/",
  "max_comments": 10
}
```

#### End-to-End Topic Research
```json
{
  "query": "mental health",
  "max_posts": 3,
  "max_comments_per_post": 5
}
```

### 5. Example Output Structures

#### Search Results (`search_instagram_reels`):
```json
{
  "platform": "instagram",
  "query": "mental health",
  "count": 1,
  "results": [
    {
      "platform": "instagram",
      "content_type": "reel",
      "content_id": "C_example123",
      "url": "https://www.instagram.com/reel/C_example123/",
      "caption": "5 daily mindfulness exercises for mental wellness #mentalhealth",
      "author": {
        "id": "17841400000000",
        "username": "mindful_wellness",
        "display_name": "Mindful Wellness"
      },
      "created_at": "2026-03-01T12:00:00Z",
      "like_count": 1250,
      "comment_count": 34,
      "view_count": 15400
    }
  ]
}
```

#### Comments Results (`get_instagram_comments`):
```json
{
  "platform": "instagram",
  "content_url": "https://www.instagram.com/reel/C_example123/",
  "comments": [
    {
      "comment_id": "17900000000000",
      "user": {
        "id": "17841455555555",
        "username": "grateful_soul",
        "display_name": "Alex S.",
        "is_verified": false,
        "is_private": false,
        "profile_picture_url": "https://instagram.fsnc1-1.fna.fbcdn.net/..."
      },
      "text": "This grounding exercise helped me so much today!",
      "created_at": "2026-03-01T13:15:00Z",
      "like_count": 8,
      "reply_count": 1
    }
  ]
}
```

#### Topic Research Results (`research_instagram_topic`):
```json
{
  "query": "mental health",
  "platform": "instagram",
  "results": [
    {
      "content": {
        "url": "https://www.instagram.com/reel/C_example123/",
        "type": "reel",
        "caption": "5 daily mindfulness exercises...",
        "author": {
          "id": "17841400000000",
          "username": "mindful_wellness",
          "display_name": "Mindful Wellness"
        },
        "created_at": "2026-03-01T12:00:00Z"
      },
      "comments": [
        {
          "comment_id": "17900000000000",
          "user": {
            "id": "17841455555555",
            "username": "grateful_soul",
            "display_name": "Alex S.",
            "is_verified": false,
            "is_private": false,
            "profile_picture_url": "https://instagram.fsnc1-1.fna.fbcdn.net/..."
          },
          "text": "This grounding exercise helped me so much today!",
          "created_at": "2026-03-01T13:15:00Z",
          "like_count": 8,
          "reply_count": 1
        }
      ]
    }
  ]
}
```

### 6. How the Data Flow Works

```
USER / MCP CLIENT
        ↓
    MCP TOOLS (server/server.py)
        ↓
 INSTAGRAM SERVICE (server/services/instagram.py)
   [URL Validation, Data Normalization, Privacy Safeguards]
        ↓
   APIFY PROVIDER (server/providers/apify/instagram.py)
   [Actor Payload Construction & Selection]
        ↓
    APIFY CLIENT (server/providers/apify/client.py)
   [Resilient HTTP, Retries, Bearer Auth, Error Mapping]
        ↓
  APIFY REST API v2 (https://api.apify.com/v2)
   [apify/instagram-scraper & apify/instagram-comment-scraper]
```

### 7. Current Limitations

1. **Proof-of-Concept**: Designed for demonstration of public content discovery and comment acquisition; does not replace dedicated data pipelines.
2. **Platform Restrictions**: Instagram is currently the only supported social platform.
3. **Public Content Only**: Only publicly accessible reels, posts, and comments are discoverable. Content on private accounts, restricted locations, or behind login forms cannot be accessed.
4. **Apify Actor Execution Limits & Quotas**: Scraper execution relies on available Apify platform credits, Actor availability, and rate limits.
5. **No Long-Term Storage**: Results are returned in-memory through the MCP protocol; no database persistence or background indexing is implemented in this phase.




