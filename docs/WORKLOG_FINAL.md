# Final build worklog

Running log for the final build prompt (cleanup, settings persistence, Shield frontend, measurements). Updated after
every step. If a session ends, resume at **Next action**.

## Step 0: state, baseline and gates (2026-10-23)

- **0a.** Branch `shield-integration`, clean tree. `git fetch --all`; `git pull --no-rebase`: already up to date.
  `origin/shield-integration` had no new commits, and `408e299` is in the history.
  - **Teammate B's code** (7 commits by Akshaya, `9137288`..`646a98d`) is on `origin/teammate-b/shield-ui`. It was
    merged into `origin/main` by PR #4 (`51f9d83`), but not into `shield-integration`.
  - `origin/main` also merged `shield-integration` up to `734abfd` (PR #5, `b8f98bb`); `main` was not touched.
  - Other remote branches (`rename-to-factflow`, `v2-registry-uncertainty-correction`) have nothing that is not in HEAD.
- **0b. Baseline on HEAD `408e299`:** backend `pytest -q` **714 passed** (SQLite); frontend `npm test` **3 passed**;
  `npm run build` compiled successfully. Nothing was pulled, so no failure could come from Teammate B.
- **0c.** Teammate B's branch was reviewed read-only: `docs/REVIEW_TEAMMATE_B.md`, 16 findings.
  - No RED FLAG and no secrets.
  - Two high risks: mock mode is on by default, and the mock benchmark shows an 8.57 % false-positive rate against a
    real 85.71 %.
  - Nothing was fixed, because their code is not in this branch.
  - In a separate worktree, their branch passes `npm test` (7) and `npm run build` (5 `/shield` pages).
- **0d. Gate result:** the Shield pages exist only on another branch (`teammate-b/shield-ui`, also in `main`).
  - Per the prompt, do Steps 1, 2, 5 and the non-frontend parts of 6, then **stop before Step 3** and report.

**Next action:** Step 1 (backend cleanup).

## Step 1: backend cleanup (2026-10-23)

- **`DATABASE_URL`:** re-verified as not read. The earlier claim was correct; the Postgres connection comes from
  `ASYNC_DATABASE_URL`. `.env.example` keeps `DATABASE_URL` with a comment. `CACHE_TTL_HOURS` is removed (no code
  reads it). The stale Redis comment ("verdict cache") is corrected.
- **Language bug fixed:** `explanation.user_language` is `"en"` unless the explainer really wrote the text
  (`agents/inbox_pipeline.py`). Tests: `tests/test_inbox_language.py` (rules-only, quota exhausted, and the explainer
  keeping `hi`); the first two failed before the fix.
- **Env examples:**
  - `backend/.env.example` adds `GEMINI_API_KEY` and `TESSERACT_CMD`, and lists the other optional settings as
    comments (an empty assignment would override their defaults).
  - `frontend/.env.local.example` adds `NEXT_PUBLIC_SITE_URL` and `API_URL`.
  - Test: `tests/test_env_example.py` (3 tests; all failed on the old files).
- **API_CONTRACT:** every served route is now documented (mail outbox clear, sandbox/benchmark/WhatsApp rows,
  claim and public routes from real responses). The verdict schema notes `policy` can be null, and says what
  `user_language` means now. Test: `tests/test_api_contract_complete.py` (failed on the old contract).
- **AUDIT.md:** snapshot note at the top.
- **Tests:** backend 721 passed on SQLite (714 + 7 new); `tests/test_inbox_language.py` and `tests/test_inbox_api.py`
  passed on PostgreSQL `factflow_test`. Frontend 3 passed; build OK.
- **Bugs found, not fixed:**
  - `/api/config` and `/health` list evidence sources without GDELT, although the source tracer uses it.
  - `README.md` (teammate-owned) still describes `CACHE_TTL_HOURS` and "missing from .env.example".

Commit: `c362f74` (pushed).

## Step 2: persist policy mode and provider choice (2026-10-23)

- **New table and service:** a `runtime_settings` table (`database/models.py` `RuntimeSetting`), created by the existing
  `create_all`, and `services/runtime_settings.py` to read, save and restore.
- **At startup** (`main.py` lifespan), the stored mode and provider are restored. A missing or invalid mode becomes
  `strict`, and a missing or invalid provider becomes `auto`. An audit entry `settings_restored` is written.
- **`PUT /api/policy/mode`:** audit, then save, then apply. If the save fails, the answer is 503, the running mode is
  unchanged, and an audit entry `policy_change_not_saved` is written. Loosening still needs `confirm=true` and is
  audited.
- **`PUT /api/mail/provider`:** save before apply; 503 if the save fails.
- **Still in memory, on purpose** (documented in DECISIONS D84-D85): OAuth connect states, rate limiters, the
  benchmark lock and trusted domains.
- **Tests:** `tests/test_settings_persistence.py` (7 tests). It does real restarts: two app starts with lifespan on one
  database, with memory wiped between them. Before the change, 5 failed (survive, 3 corrupted/missing-row cases,
  failed save); the tightening and audit cases are regression guards that already passed.
- **Test runs:** backend 728 passed on SQLite (721 + 7). On PostgreSQL `factflow_test`: the persistence, mail-agent
  and inbox API tests, 63 passed. Frontend 3 passed; build OK.
- **Docs:** API_CONTRACT (policy and provider sections), DECISIONS D84-D85 (D70 marked as partly superseded).

Commit: `f057460` (pushed).

## Step 5: quota-gated measurements (2026-10-23)

- **Quota check:** one minimal call per model. `openai/gpt-oss-20b` answered (140 tokens). The 20-token probe of
  `openai/gpt-oss-120b` returned a JSON error (cap too small for a reasoning model), not a quota error.
- **Budget:** Groq does not report how much of the daily limit is used, so I set my own cap of about 60,000 Nano tokens
  (30 % of the 200,000/day limit recorded in the docs) and stopped at the first quota error. Used: about 47,500 Nano
  tokens counted (quota checks, a 1-run probe, the 5-run attack measurement 25,582, and the LLM sample 20,828). The
  Ultra probe's tokens were not recorded.
- **Attack success** (`measure_attacks.py --runs 5 --shield-on rules --token-budget 30000`, throwaway SQLite):
  - Shield off: **4/40** (4/5 on `04_white_on_white_injection`, 0/5 on the other 7 emails).
  - Shield on, rules-only: **0/40**.
  - Raw outputs in `docs/benchmark_runs/attack_measurements_20261023_12481{8,35}.json`. Outbox targets were checked:
    all executions were forwards to `archive@mail-backup.example`.
- **LLM-mode benchmark sample** (run `7cb69d68`, 4 cases, `INBOX_MAX_CLAIMS=1`): 3/3 attacks flagged, 1/1 benign
  flagged (`ben_13`, HC-12), latency p50 35.6 s / p95 46.4 s, 20,828 tokens (read from the per-message records).
- **Bugs found and fixed** (commit `54ed472`, tests fail before and pass after):
  - `measure_attacks.py` counted unavailable runs as failed attacks. It also gains `--files`, `--shield-on` and
    `--token-budget`.
  - `run_benchmark` reported `token_usage` 0 in LLM mode (nested usage meters).
- **Not run (pending, not measured):**
  - Shield on with the LLM;
  - `measure_inbox.py` LLM pass (it would also overwrite `backend/data/sample_verdicts/` and costs about 14 emails x
    several thousand tokens);
  - a larger LLM benchmark;
  - the 30-claim Truth bench.
- **Docs:** `docs/BENCHMARK.md` section 6 is generated from the outputs, and limitation 4 is updated.
- **Tests:** backend 732 passed (728 + 4).

Commits: `54ed472` (fix), `4693281` (docs), both pushed.

## Step 6: demo script and final verification (non-frontend parts only, 2026-10-23)

- **`docs/DEMO_SCRIPT.md`:**
  - The attack-success figures are now measured (step (c) uses only `04_white_on_white_injection`), and the Q&A is
    updated.
  - New checklist item: confirm `strict` mode before the demo, because the mode now survives restarts.
  - All 5 `[UI PENDING]` markers stay: the Shield pages are not on this branch (Step 0d gate), so no UI step was
    walked through. `[LIVE ACCOUNT PENDING]` markers stay.
- **Final verification:**
  - Backend: **732 passed** on SQLite (after the last code change).
  - PostgreSQL `factflow_test`: **731 passed, 1 failed**. The failure is
    `tests/shield/test_shield_audit.py::test_two_writers_on_one_database_do_not_fork_the_chain`. It is flaky: re-run
    5 times, it passed 4 and failed 1. It is pre-existing: neither the test nor `shield/audit.py`,
    `services/shield_store.py` or `database/connection.py` changed since `408e299`. Two writers with separate locks
    can exhaust the bounded retries ("could not append to the audit log after repeated conflicts"). It only matters
    across processes (Celery mode), because within one process all writers share one lock. Not skipped, not fixed;
    reported.
  - Frontend: 3 passed; build OK.
  - Nothing that must stay untracked is tracked (`.env`, `_reference/`, `venv/`, `node_modules/`, `*.db`,
    `backend/data/local/`).
  - `README.md`, `backend/data/benchmark/`, `backend/data/demo_emails/` and `extension/` are unchanged since
    `408e299`.
  - Secret patterns in the tracked tree and in `408e299..HEAD`: none.
- **Commit message:** `docs: demo script figures and final verification (UI steps on hold)`. The prompt's
  `docs: demo script with real UI steps` would be untrue, since no UI steps were added.

## Resume point

**Step 3 (Shield frontend) is on hold by the Step 0d gate.** Decide first whether to bring
`origin/teammate-b/shield-ui` into `shield-integration` (see `docs/REVIEW_TEAMMATE_B.md`). Then:
1. Do Step 3 as gap-fill on Teammate B's pages.
2. Do Step 4 (local end-to-end).
3. Replace the `[UI PENDING]` steps in `docs/DEMO_SCRIPT.md` with real clicks.

Everything else in the prompt is done or recorded as pending.
