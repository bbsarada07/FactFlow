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

**Next action:** commit and push Step 2; then Step 5 (check the quota). Step 3 is on hold (Step 0d gate).
