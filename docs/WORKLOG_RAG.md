# Worklog: Scoped Local No-Quota Semantic Retrieval Layer (RAG v1)

## Overview & Constraints
- **Branch**: `shield-integration`
- **Time Box Budget**: 4 working sessions max
- **Core Requirements**:
  - No network calls for embeddings, no LLM calls anywhere in retrieval path. Local CPU embeddings (`sentence-transformers` with `all-MiniLM-L6-v2`).
  - No new infrastructure (no pgvector, no Docker, no external vector services). Vectors stored as JSON arrays in existing SQLite/PostgreSQL database; similarity via NumPy cosine similarity. p95 < 200 ms.
  - Never fabricate citations: below threshold returns empty list ("no matching verified record").
  - RapidFuzz repeat-claim registry remains intact; RAG is a second, distinctly labelled signal.
  - Zero modifications to frontend pages, README.md, deployment files, or test/benchmark datasets.

---

## Baseline State (Step 0)
- **Branch**: `shield-integration` (up to date with `origin/shield-integration`)
- **Git Status**: Clean before feature work
- **Baseline Test Count**:
  - Backend pytest: **732 passed**, 0 failed, 2 warnings
  - Frontend test: **7 passed**, 0 failed
  - Total: **739 tests passed**
- **Architecture Review**:
  - `agents/source_tracer.py`: Collects evidence across GDELT, Fact Check, NewsAPI, DDG; assigns credibility tiers; LLM assesses stance/relevance.
  - `agents/explainer.py`: Grounds summaries and facts to evidence references [S#]; drops uncited sentences.
  - `services/registry.py`: Fast exact hash + RapidFuzz `token_set_ratio` (min length ratio 0.6, threshold 85).
  - `shield/scam_patterns.py`: Scans text against regex pattern detectors loaded from `patterns.yml`.
  - `shield/phishing.py`: Header authentication, sender lookalike/homoglyph checks, URL flag heuristics.

---

## Implementation Plan

### Step 1: Knowledge Base and Ingestion
- SQLAlchemy model `KBDocument` in `backend/database/models.py` (`kb_documents` table: id, source_type, title, body_text, source_url, verified, verified_by, verified_on, embedding, created_at).
- Embeddings module `backend/shield/kb/embeddings.py`:
  - Singleton model loader for `all-MiniLM-L6-v2` (`local_files_only=True`).
  - Robust batch encoding handling empty or whitespace-only inputs without crashing.
- Seed data in `backend/data/kb_seed/`:
  - At least 10 real Indian government schemes with live-verified URLs (verified via live fetch or verified=False).
  - At least 10 scam templates derived from `scam_patterns.py` categories.
  - Helpline entry linked to `backend/shield/config/helplines.yml`.
- Ingestion script `backend/shield/kb/ingest.py`:
  - Imports `incidents` and `known_patterns` from database into `kb_documents` (idempotent, deduplicated by slug/title).
  - Ingests seed files from `backend/data/kb_seed/`.
- Retrieval module `backend/shield/kb/retrieve.py`:
  - Query embedding + in-memory cosine similarity over `kb_documents`.
  - Configurable threshold (default 0.70). Returns empty list if top score < threshold.
  - Returns `list[KBResult]` with score, id, title, source_url, excerpt.
- Unit and latency tests in `backend/tests/shield/test_kb_rag.py`.

### Step 2: Integration into Source Tracer
- In `agents/source_tracer.py`, invoke internal KB retrieval alongside external search.
- Mark internal hits distinctly with `origin: "internal"` and proper tiering.
- Pass internal hits through standard relevance/stance assessment.
- Explainer updates: ensure plain-language attribution for internal records ("according to verified government scheme records [S#]") while preserving strict sentence grounding.
- Regression tests in `tests/test_rag_source_tracer.py`.

### Step 3: Integration into Shield Scam Detection
- In `shield/scam_patterns.py` (or helper `shield/scam_retrieval.py`), query `scam_template` KB documents after regex rules run.
- Add hit above threshold as additive evidence in verdict (`scam_template_hit` / extra evidence) without changing rule-based severity or breaking existing expectations.
- Tests in `tests/shield/test_shield_scam_rag.py`.

### Step 4: Honest Evaluation
- Evaluation script `backend/scripts/eval_retrieval.py` with 20+ query/document pairs (schemes, scams, and 5+ adversarial distractors).
- Report precision, recall, and misses in `docs/RAG_EVAL.md`.
- Add section to `docs/BENCHMARK.md` describing internal retrieval scope and real numbers.

### Step 5: API Exposure (if time allows)
- Update schemas and document in `docs/API_CONTRACT.md`.

---

## Session Tracking & Resume Points
- **Session 1**:
  - Completed Step 0 (state check, baseline tests: 732 backend + 7 frontend, code reviews, decisions D86-D89 documented).
  - Completed Step 1:
    - Added `KBDocument` SQLAlchemy model to `backend/database/models.py`.
    - Added `backend/shield/kb/embeddings.py` using local `all-MiniLM-L6-v2` with zero network calls and robust empty/whitespace handling.
    - Created seed data in `backend/data/kb_seed/`:
      - `schemes.yml`: 12 real Indian government schemes (11 verified live via real HTTP 200 checks, 1 unverified due to timeout).
      - `scam_templates.yml`: 11 scam templates matching the 13 scam pattern categories.
      - `helpline.yml`: single source of truth pointing to `backend/shield/config/helplines.yml`.
    - Added `backend/shield/kb/ingest.py`: idempotent ingestion from database (`incidents`, `known_patterns`) and seed files.
    - Added `backend/shield/kb/retrieve.py`: in-memory cosine similarity via NumPy with strict threshold enforcement and one-line excerpt generation.
    - Added `backend/tests/shield/test_kb_rag.py`: 6 tests passing (embeddings edge cases, idempotent ingestion, scheme retrieval, unrelated rejection, adversarial near-miss rejection, measured p95 latency = 15.65 ms).
    - Updated `backend/config.py` and `backend/.env.example` with `KB_SIMILARITY_THRESHOLD` and `KB_TOP_K`.
    - Updated `backend/requirements.txt` with `sentence-transformers==6.2.0`.
    - Test count: **738 backend passed + 7 frontend passed = 745 total**.
    - Committed as `feat: kb ingestion and retrieval` (`e3df6c3`) and pushed to `shield-integration`.

- **Session 2**:
  - Completed Step 2:
    - In `backend/agents/grounding.py`: expanded `source_aliases()` to recognise plain-language citations to internal records (`officialscheme`, `officialschemepage`, `schemepage`, `verifiedrecord`, `verifiedrecords`, `internalrecord`, `officialportal`, `verifiedknowledgebase`, `knowledgebase`) so `require_named_sources()` accepts phrases like "according to the official scheme page [S#]" while continuing to drop uncited or unsupported sentences.
    - In `backend/agents/source_tracer.py`:
      - Added `search_internal_kb()` to query semantic retrieval over `kb_documents`.
      - Wired `search_internal_kb` into parallel `_gather()` tasks under provider label `"Internal KB"`.
      - Clearly labelled output preview with `({internal_count} internal, {external_count} web)` when internal evidence is present.
      - Ranked `"internal": 0` in `origin_rank` for tie-breaking within same tier.
      - Ensured candidates pass through the exact same LLM relevance and stance assessment with zero automatic credibility boost.
    - In `backend/agents/explainer.py`:
      - Updated `PROMPT` rules for clear plain-language internal attribution ("according to the official scheme page [S#]" or "according to verified records [S#]") without blending uncited text.
      - Handled internal records in `_source_line()` fallback and formatted `SOURCES` list with `internal verified record`.
    - Added `backend/tests/test_rag_source_tracer.py`:
      - `test_source_tracer_retrieves_internal_kb_scheme`: verifies scheme query retrieves internal doc, labels preview, and Explainer produces grounded citations.
      - `test_source_tracer_regression_no_kb_match`: verifies non-matching claims fall back cleanly to `UNVERIFIED` and "No sources found yet".
      - `test_internal_hit_not_automatically_trusted`: verifies that internal hits with low relevance are dropped rather than trusted automatically.
    - Full test suite passed: **741 backend passed + 7 frontend passed = 748 total passed**, zero regressions.
  - **Exact Resume Point**: Proceed to Step 3 (Integrate scam template semantic retrieval into `backend/shield/scam_patterns.py` or new `backend/shield/scam_retrieval.py` as additive evidence).
