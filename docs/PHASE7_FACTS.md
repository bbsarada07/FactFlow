# Phase 7 facts (working file for the team)

The facts the README and DEMO_SCRIPT rely on, each with its source. Gathered on 2026-10-23 at commit `734abfd`
(branch `shield-integration`). Check this list; anything wrong here is wrong in the README too.

## Facts and sources

| Fact | Source |
|---|---|
| Commits since the rename: Phase 1 `e0cdf7f`, Phase 2 `d8d91bb`, Phase 3 `d158060`, Phase 4 `427136e` (built by another AI agent, reviewed and fixed in `fc2620c`..`0f2cf52`), Phase 5 `734abfd` | `git log` |
| 45 API routes, including `/health` | `main.app.openapi()` (listed in the review session) |
| Backend tests: 714 passed (SQLite, PostgreSQL `factflow_test`, and a clean Python 3.11 venv) | `pytest -q` run on 2026-10-23 at `734abfd` (re-checked before this commit, see bottom) |
| Frontend: 3 tests (`frontend/tests/stance.test.mjs`); `npm run build` passes; pages: `/`, `/about`, `/accuracy`, `/incidents`, `/registry`, `/tracker`, `/v/[slug]` | `frontend/pages/`, `npm test`, `npm run build`, `next dev` probe (all 200) |
| No inbox, approvals, sandbox, benchmark or WhatsApp pages in the frontend on this branch; a teammate's UI is on `origin/teammate-b/shield-ui` (not merged) | `frontend/pages/`, `git branch -r` |
| The frontend contains no operator token and no `NEXT_PUBLIC_*` secret (only `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SITE_URL`) | `grep` over `frontend/pages`, `components`, `lib` |
| Shield detectors: HC-01..HC-12 hidden content, SC-01..SC-13 scam patterns, injection rules in `patterns.yml`, brand lookalikes in `brands.yml` | `backend/shield/` |
| Policy rules: P0-P8, E-EGRESS, E-FINANCIAL, S1; default mode `strict`; approval TTL 600 s | `backend/shield/policy.py`, `shield/config/policy.yml`, `GET /api/policy` |
| Model isolation as built: one quarantined reader call (no tools, PII-redacted input inside `<untrusted_content>` blocks, schema-checked JSON output); the explainer gets FactFlow's findings plus short quotes; planner and policy are deterministic code. The reader and the explainer use the **same** model (`NANO_MODEL`, default `openai/gpt-oss-20b`). | `backend/shield/quarantine.py`, `backend/agents/inbox_pipeline.py`, `backend/config.py` |
| Rules-only benchmark, latest run `31376138137544938f198afc1c9aaaed` (2026-10-23 10:36 UTC): 89 cases (54 attack / 35 benign), detection 94.44 % (51/54), false positives 85.71 % (30/35), policy level 100.0 % (54/54), no model tokens | `docs/benchmark_runs/rules_31376138137544938f198afc1c9aaaed.json` |
| Same counts on a repeat run `363bd3cc...`; before the review fixes `577704ad...` = `5bf450da...` (FP 82.86 %) | `docs/benchmark_runs/` (all four saved) |
| False-positive causes (26 HC-12 plain/HTML mismatches in the test data, 4 brand names on placeholder domains) | `docs/benchmark_runs/benign_case_diagnosis_2026-10-23.txt`, `docs/BENCHMARK.md` section 5 |
| Attack-success rates (shield on/off, 20 runs): not measured | `docs/BENCHMARK.md` section 6; no `backend/data/local/attack_measurements_*.json` |
| One recorded real shield=off run, 2026-10-22 17:45:42 UTC, `openai/gpt-oss-20b` | `backend/data/demo_recordings/demo_run_20261022_174542.json`; matching audit seq 1432 exists only in the local dev database (not in the repo) |
| Rules-only latency of the inbox pipeline, p50 35 ms / p95 41 ms, 14 demo emails, 2026-10-22 | `docs/MEASUREMENTS.md`, raw data `backend/data/measurements/inbox_2026-10-22.json` |
| Full (LLM) mode token use: not measured | `docs/MEASUREMENTS.md` |
| Truth pipeline 30-claim bench: no saved result (`backend/tests/bench/results/latest.json` does not exist), so `/api/accuracy` reports no complete run | file check |
| One live claim run during the Phase 0 audit: FALSE, 0.94, 28,049 ms, Ultra used | `docs/AUDIT.md` section 9 |
| Gmail: `gmail.readonly` only; tested with fixtures built from documented formats, never against a live account | `docs/DECISIONS.md` D57-D58, `backend/tests/fixtures/gmail/` |
| WhatsApp: tested with recorded-format fixtures and a fake Twilio API; never against a live Twilio account. A local rehearsal on 2026-10-23 (Hindi text, dry run) returned a 456-character Hindi reply, recorded as `delivery: dry_run` | `backend/tests/test_whatsapp.py`, rehearsal in this session |
| Tesseract on the dev machine has only `eng` and `osd` (no `hin`, `tel`) | `pytesseract.get_languages` on 2026-10-23 |
| In-memory state lost on restart: policy mode and allowed domains, active mail provider, OAuth states, rate limiters, the benchmark run lock | `docs/DECISIONS.md` D70, `backend/api/*.py` |
| Sentinel: ideas from its policy engine (provenance recomputation, fail-closed evaluation, egress URL check, recipient allowlist, monotonic policy store) and its executor/ledger pattern were adapted; its detectors were rewritten; its seed-specific parser and planner were dropped | `docs/AUDIT.md` section 3 |

## Mismatches found (listed, not fixed: docs-only task)

| # | Mismatch | Where |
|---|---|---|
| 1 | `GEMINI_API_KEY`, `VISION_PROVIDER`, `TESSERACT_CMD`, `GEMMA_MODEL` and other settings exist in `config.py` but are missing from `backend/.env.example` | `backend/.env.example` vs `backend/config.py` |
| 2 | `DATABASE_URL` and `CACHE_TTL_HOURS` are in `.env.example` but nothing in the backend reads them (only `ASYNC_DATABASE_URL` is used; verdict reuse goes through the registry with `REPEAT_WINDOW_DAYS`). The old README said identical inputs are cached for `CACHE_TTL_HOURS`; that claim was stale and is not in the new README. | `backend/.env.example`, `backend/services/cache_service.py` |
| 3 | `NEXT_PUBLIC_SITE_URL` is read by the frontend but missing from `frontend/.env.local.example` | `frontend/lib/config.js:12` |
| 4 | `DELETE /api/mail/outbox` and `POST /api/mail/outbox/clear` (added in `427136e`) are not in `docs/API_CONTRACT.md` | `backend/api/mail.py:185-191` |
| 5 | `/api/registry`, `/api/v/{slug}` and `/api/config` are documented in neither the README API table nor API_CONTRACT | `backend/api/` |
| 6 | Bug: in rules-only mode (and when the quota is used up), `explanation.user_language` is set to the requested language (for example `hi`) while `explanation.text` is the English rules summary | `backend/agents/inbox_pipeline.py:295-296` |
| 7 | The WhatsApp spec says "2-3 reasons"; the reply shows only the reasons that apply (up to 3), so a message with one finding gets one reason. Scam-pattern names stay in English inside Hindi/Telugu replies. | `backend/shield/whatsapp_reply.py` |
| 8 | `docs/AUDIT.md` is the Phase 0 snapshot: its risks 5 (no SSRF guard) and 6 (no authentication) were fixed in Phases 2-3, and it still mentions Phase 6 work that was cut (D54). It says "FactFlow (formerly NemesisAI)" (deliberate). | `docs/AUDIT.md` |
| 9 | The API explorer (`/docs`) has no **Authorize** button: `OPERATOR_TOKEN` goes into the `x-operator-token` field of each operator route (it is a header parameter, not an OpenAPI security scheme). The docs are written that way. | `backend/services/operator_auth.py` |
| 10 | The old README sections "Business model" (TAM/SAM/SOM line without a source) and "Future scope" were dropped from the new README; they are not in the agreed section list. "WhatsApp Business bot" in Future scope is now partly built. | old `README.md` |

## Checks before the commit

- Demo rehearsal: see the bottom of `docs/DEMO_SCRIPT.md`.
- Every link and repository path in README.md and DEMO_SCRIPT.md exists (checked by script).
- Every table line in docs/BENCHMARK.md matches the saved runs (88 of 88 lines, regenerated from the run files).
- Tests after writing these docs (2026-10-23): backend `pytest -q` 714 passed (unchanged); frontend `npm test` 3 passed;
  `npm run build` compiled successfully.
