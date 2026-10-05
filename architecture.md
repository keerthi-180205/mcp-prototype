# Architecture Documentation

## Phase 1 Architecture (Foundation)

In Phase 1, the objective was exclusively to establish the core Model Context Protocol (MCP) server foundation and health check mechanism.

```text
                    PHASE 1

              +---------------+
              |   MCP Client  |
              +-------+-------+
                      |
                      | MCP (stdio)
                      |
              +-------v-------+
              |   MMTF MCP    |
              |    Server     |
              +-------+-------+
                      |
                      v
               health_check()
```

---

## Phase 2 Architecture (GitHub Provider & Data Model)

In Phase 2, a dedicated **GitHubProvider** was introduced behind the abstract `RepositoryProvider` interface to discover mental-health repository candidates via the official GitHub REST API without scraping.

```text
                         PHASE 2

                    +-------------+
                    | MCP Server  |
                    +------+------+
                           |
                           | (Internal Provider API)
                           |
                    +------v------+
                    |   GitHub    |
                    |   Provider  |
                    +------+------+
                           |
                           | Official REST API (httpx)
                           |
                    +------v------+
                    |   GitHub    |
                    |     API     |
                    +------+------+
                           |
                           v
                  Repository Metadata
               (RepositoryCandidate)
```

---

## Phase 3 Architecture (MCP GitHub Repository Discovery)

Phase 3 connected the decoupled `GitHubProvider` directly into the MCP tool surface, exposing `search_mental_health_repositories` over the standard MCP protocol.

---

## Phase 4 Architecture (Dataset & Resource Discovery)

Phase 4 moved beyond repository metadata to discover and classify **dataset and resource candidates** referenced in repository documentation (README) using the official GitHub REST API.

---

## Phase 5 Architecture (External Dataset Connectors)

Phase 5 introduces a unified **connector architecture** that resolves external dataset references (from Hugging Face, Kaggle, and Zenodo) and queries their official platform REST APIs to retrieve normalized dataset metadata and provenance information without scraping HTML or downloading dataset contents.

```text
                               MCP CLIENT
                                   │
                                   │ JSON-RPC (stdio)
                                   ▼
             +---------------------------------------------+
             |               MMTF MCP Server               |
             |                                             |
             | health_check()                              |
             | search_mental_health_repositories()         |
             | inspect_repository_resources()              |
             | resolve_dataset_metadata()                  |
             +----------------------+----------------------+
                                    │
                                    │ URL Resolution
                                    ▼
                      resolve_dataset_provider(url)
                                    │
            +-----------------------+-----------------------+
            │                       │                       │
     "huggingface"              "kaggle"                "zenodo"
            │                       │                       │
            ▼                       ▼                       ▼
   HuggingFaceProvider        KaggleProvider          ZenodoProvider
            │                       │                       │
            │ Official REST API     │ Official REST API     │ Official REST API
            ▼                       ▼                       ▼
    Hugging Face API            Kaggle API             Zenodo API
    (/api/datasets/...)    (/api/v1/datasets/...)   (/api/records/...)
            │                       │                       │
            +-----------------------+-----------------------+
                                    │
                                    ▼
                             DatasetMetadata
```

### Component Responsibilities

1. **MCP Server (`server/server.py`)**:
   * Protocol interface dispatching requests to tools: `health_check`, `search_mental_health_repositories`, `inspect_repository_resources`, and `resolve_dataset_metadata`.
   * Maps platform-specific connector exceptions to structured error responses without leaking credentials.

2. **URL Resolver (`server/providers/resolver.py`)**:
   * Deterministically parses URLs to map them to the corresponding platform provider (`huggingface`, `kaggle`, `zenodo`, or `unknown`) and extracts platform-specific dataset identifiers.

3. **External Dataset Connectors**:
   * **`HuggingFaceProvider` (`server/providers/huggingface.py`)**: Interacts with `https://huggingface.co/api/datasets/{identifier}` to retrieve dataset cards, tags, licenses, languages, and file sizes.
   * **`KaggleProvider` (`server/providers/kaggle.py`)**: Interacts with `https://www.kaggle.com/api/v1/datasets/view/{owner}/{name}` using HTTP Basic Auth via `KAGGLE_USERNAME` and `KAGGLE_KEY`. Refuses unauthenticated scraping.
   * **`ZenodoProvider` (`server/providers/zenodo.py`)**: Interacts with `https://zenodo.org/api/records/{record_id}` to retrieve public research metadata, DOIs, licenses, and creators.

4. **Data Models (`server/models.py`)**:
   * `RepositoryCandidate`: Normalized repository representation (Phase 2).
   * `DatasetCandidate`: Discovered dataset reference from READMEs (Phase 4).
   * `DatasetMetadata`: Normalized external dataset metadata model from official platform APIs (Phase 5).

---

## Phase 6 Architecture (Dataset Validation, Privacy & Provenance)

Phase 6 implements a deterministic, evidence-based validation layer that collects and exposes documented facts regarding dataset licensing, privacy/de-identification claims, sensitive-data warnings, and origin provenance without downloading raw dataset files or invoking LLMs.

> **Important Principle**:
> The validation layer reports documented metadata and evidence.
> It does not make legal or ethical approval decisions.

```text
                     ┌──────────────────────┐
                     │ GitHub Discovery     │
                     └──────────┬───────────┘
                                ↓
                     ┌──────────────────────┐
                     │ Dataset Candidate    │
                     └──────────┬───────────┘
                                ↓
                     ┌──────────────────────┐
                     │ External Provider    │
                     └──────────┬───────────┘
                                ↓
                     ┌──────────────────────┐
                     │ Dataset Metadata     │
                     └──────────┬───────────┘
                                ↓
                     ┌──────────────────────┐
                     │ Validation Engine    │
                     └──────────┬───────────┘
                                ↓
             ┌──────────────────┼──────────────────┐
             ↓                  ↓                  ↓
          License            Privacy          Provenance
             │                  │                  │
             └──────────────────┼──────────────────┘
                                ↓
                     DatasetValidationResult
```

### Component Responsibilities (Phase 6)

1. **`DatasetValidator` (`server/validation/validator.py`)**:
   * Master orchestrator combining license, privacy, and provenance evaluations into `DatasetValidationResult`.
   * Evaluates access permissions (`public_metadata`, `authenticated`, `restricted`, `unknown`) and documentation completeness.

2. **`LicenseValidation` (`server/validation/licensing.py`)**:
   * Evaluates explicit platform license fields deterministically.
   * Reports factual status (`documented` vs `missing`), captures evidence records, and flags non-commercial restrictions without approving or rejecting.

3. **`PrivacyValidation` (`server/validation/privacy.py`)**:
   * Detects explicit dataset-level de-identification (`explicitly_deidentified`) and anonymization (`explicitly_anonymized`) statements.
   * Strictly distinguishes documented dataset statements (e.g., "all records were de-identified", "PII was removed") from general discussions of privacy or security.
   * Detects explicit warnings regarding sensitive mental health, suicidality, or crisis content (`contains_sensitive_data_warning`), while ignoring unrelated uses (e.g. "sensitive hyperparameters").

4. **`ProvenanceValidation` (`server/validation/provenance.py`)**:
   * Tracks and preserves the complete origin chain in a structured `ProvenanceRecord`: discovery source, source GitHub repository, hosting provider, source URL, access method, and retrieval timestamp.

5. **Models (`server/models.py`)**:
   * `EvidenceRecord`: Structured audit trail capturing `field`, `value`, `source`, and `evidence_type`.
   * `ProvenanceRecord`: Immutable audit trail of how and where metadata was collected.
   * `DatasetValidationResult`: Complete factual validation summary avoiding legal decision fields.

---

## Phase 7 Architecture (Gemini LLM Interpretation Layer)

Phase 7 introduces Google Gemini as an intelligent, evidence-grounded interpretation layer operating over structured metadata and deterministic validation results.

> **Core Principle**:
> Gemini is an interpretation layer and does not replace deterministic metadata retrieval or validation.
> Gemini must never be used to infer facts that are not present in the source metadata, nor make legal or ethical approval decisions.

```text
                       GitHub
                          ↓
                  Dataset Discovery
                          ↓
                 Dataset Candidate
                          ↓
                 External Providers
                          ↓
                  Dataset Metadata
                          ↓
                   Validation
                          ↓
              ┌───────────┴───────────┐
              ↓                       ↓
       Deterministic Data       Gemini Analysis
          / Evidence               / Summary
              ↓                       ↓
              └───────────┬───────────┘
                          ↓
                   MCP Response
```

### Component Responsibilities (Phase 7)

1. **`GeminiClient` (`server/llm/gemini.py`)**:
   * Encapsulates communication with Google GenAI SDK (`google.genai`).
   * Builds sanitized payloads containing exclusively metadata and validation findings (never API tokens, passwords, raw datasets, or user transcripts).
   * Robust error mapping translating SDK/network failures into structured exceptions (`GeminiAuthenticationError`, `GeminiRateLimitError`, `GeminiTimeoutError`, `GeminiInvalidResponseError`).
   * Validates all LLM responses against strict Pydantic schemas.

2. **Prompts & Guardrails (`server/llm/prompts.py`)**:
   * Strict system guardrails enforcing:
     * Grounding exclusively on provided metadata.
     * Declaring missing attributes explicitly as `"unknown"` or `"not documented"`.
     * Never assuming public availability implies anonymization or privacy safety.
     * Enforcing valid JSON output without conversational filler.

3. **Domain Models (`server/models.py`)**:
   * `DatasetSummary`: Objective 2-3 sentence synthesis, purpose, documented license, documented privacy, and limitations.
   * `DatasetCategoryClassification`: Suggested taxonomic category while strictly preserving deterministic `data_type`.
   * `DatasetRelevance`: Topical relevance rating (`high`, `medium`, `low`, `unknown`) and justification for mental-health NLP (NOT a safety or legal score).
   * `DatasetReport`: Full human-readable report synthesizing facts, provenance, warnings, and relevance.

---

## Architectural Principles

### 1. Strict No-Scraping Policy
* All data is retrieved exclusively through official platform REST APIs (GitHub, Hugging Face, Kaggle, Zenodo).
* No HTML scraping, BeautifulSoup, Selenium, or headless browser automation.

### 2. Metadata Retrieval Only (No Ingestion)
* Connector tools retrieve metadata, licenses, file sizes, and descriptions only.
* No dataset files, zip archives, or private communications are downloaded.

### 3. Explicit Privacy Safeguards & No Legal Decisions
* Privacy statuses (`explicitly_anonymized`, `explicitly_deidentified`, `contains_sensitive_data_warning`) are strictly populated when documented explicitly by the source platform or dataset card, never assumed.
* No legal approval decisions (`safe_to_use`, `approved`, `legally_safe`) are generated; outputs provide factual evidence for human review.

### 4. Deterministic Reproducibility
* Discovery, API access, provenance, and validation are 100% deterministic and reproducible.
* LLMs are restricted to interpretation, explanation, and summarization; they cannot overwrite deterministic facts.

### 5. Sanitized LLM Payloads
* Gemini receives only structured, sanitized metadata payloads.
* API keys, tokens, credentials, private user messages, and raw dataset contents are never transmitted.

---

## Phase 8 Architecture (Productionization & Resilience)

Phase 8 hardens the discovery engine for production readiness, fault tolerance, and credential safety across all layers:

```text
                               MCP CLIENT
                                   |
                                   | JSON-RPC (stdio)
                                   v
             +---------------------------------------------+
             |         MMTF MCP Discovery Server           |
             |                                             |
             |  +---------------------------------------+  |
             |  |        Settings (server/config.py)     |  |
             |  +---------------------------------------+  |
             |  |    Structured Logging & Secret Filter |  |
             |  |       (server/logging_config.py)      |  |
             |  +---------------------------------------+  |
             |  |      Resilience & Backoff Engine      |  |
             |  |        (server/resilience.py)         |  |
             |  +---------------------------------------+  |
             +---------------------+-----------------------+
                                   |
           +-----------------------+-----------------------+
           |                       |                       |
           v                       v                       v
    +--------------+       +---------------+       +---------------+
    | GitHub       |       | Connectors    |       | Gemini Client |
    | Provider     |       | (HF, Kaggle,  |       | (Structured   |
    |              |       |  Zenodo)      |       |  Layer)       |
    +-------+------+       +-------+-------+       +-------+-------+
            |                      |                       |
            | Controlled Retries   | Controlled Retries    | Controlled
            | (429, 5xx, Network)  | (429, 5xx, Network)   | Retries
            v                      v                       v
    GitHub REST API        Official REST APIs      Google Gemini API
```

### Key Production Protections

1. **Centralized Configuration (`server/config.py`)**:
   * Single source of truth loaded from environment variables.
   * Credential masking: `repr(settings)` conceals all API keys and tokens.
   * On-demand validation: Optional credentials are not checked until the respective platform provider is invoked.

2. **Defense-in-Depth Secret Scrubbing (`server/logging_config.py`)**:
   * Global `SecretScrubbingFilter` strips `Bearer` tokens, `Basic` auth, and API keys from all log messages.
   * Structured operational events track `component`, `operation`, `status`, `duration`, and count metrics.

3. **Deterministic Failure Policy**:
   * Transient network errors and HTTP `429`, `500`, `502`, `503`, `504` are retried with exponential backoff (`delay = initial * (backoff_factor ^ attempt)`).
   * Client errors (`400`, `401`, `403`, `404`, `422`) fail fast immediately without retries.

4. **Explicit Request Timeouts**:
   * Every network client utilizes explicit configurable timeouts (GitHub: 20s, HF: 20s, Kaggle: 20s, Zenodo: 20s, Gemini: 90s, Apify: 120s). Infinite timeouts are strictly forbidden.

---

## Phase 9 Architecture (Instagram & Apify Public Data Acquisition)

Phase 9 introduces an isolated, multi-tiered data acquisition flow for public Instagram reels, posts, and comments via Apify Actors without scraping behind login, bypassing auth, or using browser cookies.

```text
                             MCP CLIENT
                                 │
                                 │ JSON-RPC (stdio)
                                 ▼
           +---------------------------------------------+
           |               MMTF MCP Server               |
           |                                             |
           | search_instagram_reels()                    |
           | get_instagram_comments()                    |
           | research_instagram_topic()                  |
           +---------------------+-----------------------+
                                 │
                                 │ Domain Calls
                                 ▼
           +---------------------------------------------+
           |              InstagramService               |
           |         (server/services/instagram.py)      |
           |                                             |
           | * URL validation (INSTAGRAM_URL_PATTERN)    |
           | * Missing/null field resilient normalization|
           | * Topic search & comment orchestration      |
           | * Strict public-only data handling          |
           +---------------------+-----------------------+
                                 │
                                 │ Provider Delegation
                                 ▼
           +---------------------------------------------+
           |           ApifyInstagramProvider            |
           |     (server/providers/apify/instagram.py)   |
           |                                             |
           | * Actor payload construction                |
           | * Search & comments actor dispatch          |
           +---------------------+-----------------------+
                                 │
                                 │ Resilient HTTP (Bearer Auth)
                                 ▼
           +---------------------------------------------+
           |                 ApifyClient                 |
           |       (server/providers/apify/client.py)    |
           |                                             |
           | * Exponential backoff retries               |
           | * Token secrecy & error mapping             |
           +---------------------+-----------------------+
                                 │
                                 │ Apify REST API v2
                                 ▼
           +─────────────────────────────────────────────+
           |             Apify Platform Actors           |
           |                                             |
           | * apify/instagram-scraper (Posts/Reels)     |
           | * apify/instagram-comment-scraper (Comments)|
           +─────────────────────────────────────────────+
```

### Component Decoupling & Isolation
1. **MCP Tool Layer (`server/server.py`)**: Exposes protocol tools, extracts JSON-RPC arguments, and converts service exceptions into structured, secret-safe MCP error envelopes.
2. **Domain Service Layer (`server/services/instagram.py`)**: Manages business logic, URL validation, data normalization into Pydantic models (`InstagramPost`, `InstagramComment`), and flow orchestration. Completely decoupled from Apify-specific HTTP logic.
3. **Provider Layer (`server/providers/apify/instagram.py`)**: Translates high-level domain requests into Actor-specific payloads (`directUrls`, `hashtags`, `resultsType`).
4. **API Client Layer (`server/providers/apify/client.py`)**: Handles raw HTTP communication with Apify REST API v2, Bearer auth headers, actor ID sanitization (`owner/name` to `owner~name`), and status code translation (`401`, `402`, `404`, `408`, `429`).



