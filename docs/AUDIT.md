# Phase 0 audit: FactFlow x Sentinel

> **This is the Phase 0 snapshot from 2026-10-22, kept as a record. It is not the current status.** Several risks
> listed here have since been fixed. For example, the SSRF-guarded fetcher (risk 5) and operator authentication
> (risk 6) were added in Phases 2-3. Some planned work was cut, for example Phase 6, the extension's Gmail banner
> (decision D54). For the current status see [DECISIONS.md](DECISIONS.md), [REVIEW_PHASE4_5.md](REVIEW_PHASE4_5.md)
> and [WORKLOG_FINAL.md](WORKLOG_FINAL.md).

Read-only audit for the master build prompt and Addendum v2. Date: 2026-10-22. Branch `shield-integration` at
`fa9406a`. Sentinel audited from `_reference/CVR` at `2a885c1` (same commit as `../CVR`).

Nothing in either repo was changed except this file. Evidence for each finding is the file and line named, or a
command run during the audit (listed in section 9).

---

## 1. Section 2 claims: confirmed or corrected

### 1.1 FactFlow (formerly NemesisAI)

| Claim in the prompt | Finding | Evidence |
|---|---|---|
| Python 3.11+ FastAPI backend, venv | **Confirmed.** FastAPI 0.148.0, venv on Python 3.11. The machine's default `python` is 3.14; the venv must be created with `py -3.11`. | `backend/requirements.txt`, `py -0` |
| PostgreSQL + pgvector (Docker) | **Corrected.** PostgreSQL 16 runs natively (not Docker), and a SQLite fallback is used automatically when Postgres is unreachable. **pgvector is not used**: repeat detection is rapidfuzz `token_set_ratio`. The Docker daemon is not running. | `database/connection.py:36-50`, `services/registry.py:1-5`, `docker ps` |
| Redis (Docker) | **Corrected.** Memurai 4.1.2 (native, Redis-compatible). Redis is optional: it is only needed when `USE_CELERY=true`. By default the pipeline runs in-process with an in-memory event bus. | `services/event_bus.py`, `main.py:56-69` |
| Tesseract OCR | **Partly confirmed.** Tesseract 5.4 is installed, but only `eng` and `osd` language data are present. Hindi and Telugu screenshots will not OCR correctly. | `tesseract --list-langs` |
| ffmpeg | **Installed but unused.** No code references ffmpeg; there is no audio path. | `git grep ffmpeg` |
| 6 agents (Orchestrator, Intake & Triage, Source Tracer, Deep Reasoning, Multilingual Explainer, Harm Assessor) | **Confirmed**, with the explainer named "Explainer" in code. | `agents/orchestrator.py:28-35` |
| Light = `openai/gpt-oss-20b`, heavy = `openai/gpt-oss-120b`, both via Groq | **Confirmed** as defaults. Also: screenshots can be read by Gemma 4 through the Gemini API (`VISION_PROVIDER=gemini`); with no `GEMINI_API_KEY` set (current `.env`), Tesseract is used. | `config.py:17-30`, `/health` |
| Next.js frontend, dark aesthetic, SSE live tracker | **Confirmed.** Next.js 14.2.35 Pages Router, Tailwind, Framer Motion. SSE via `EventSource` with a polling fallback. | `frontend/package.json`, `pages/index.js:209-240` |
| Chrome MV3 extension, tested in Edge | **MV3 confirmed.** Edge testing cannot be confirmed from the repo. Two defects found (section 2.6). | `extension/manifest.json` |
| Android overlay is a mockup only | **Confirmed.** Verdicts in it are pre-filled. | `android/README.md:47` |
| Palghar claim returned FALSE ~98% in ~10 s | **Not reproduced.** One live run today of bench case F01 (the child-kidnapper forward) returned **FALSE, confidence 0.94, in 28 s**, escalated to the Ultra model, with 5 tier-2 refuting sources. One run is not a benchmark. No bench results file is committed (`tests/bench/results/latest.json` is absent). | Live run, section 9 |
| Hindi in, Marathi out; URL; image; cache | **Not re-run.** The code paths exist: `language` request field, URL fetch, image read. "Cache" is the **public verdict registry** (repeat detection over stored verdicts, 7-day window), not Redis. | `api/verify.py:108-199`, `services/registry.py` |
| Existing backend tests pass | **Confirmed.** 146 test cases (111 test functions) pass. `npm test` (3) and `npm run build` pass. | Run during the rename |

### 1.2 Sentinel (`bbsarada07/CVR`)

| Claim in the prompt | Finding | Evidence |
|---|---|---|
| Secure email-action agent against indirect prompt injection | **Confirmed.** | `README.md`, `orchestrator.py:1-10` |
| 6 isolated agent roles | **Confirmed as Python classes**: parser, investigator, injection analyst, risk assessor, action planner, executor, plus a deliberately vulnerable naive agent. A code-level capability map restricts which tools each may call. | `agents.py:59-107` |
| Dual-LLM isolation ("the heart of Sentinel") | **Corrected. The protected pipeline makes no LLM calls at all.** The only LLM call in the codebase is in the vulnerable `NaiveAgent` (`agents.py:572`). There is no quarantined LLM to port; `quarantine.py` must be built new in FactFlow. | `grep -n "llm\." agents.py orchestrator.py tools.py evidence.py` |
| Deterministic Python policy engine | **Confirmed**, and it is the strongest part of Sentinel (section 3). | `policy.py` |
| Python 3.11, FastAPI, Pydantic v2, vanilla JS | **Confirmed.** FastAPI 0.143.0, Pydantic 2.14.1, `static/index.html`. | `requirements.txt` |
| 0 of 10 test attacks reached a consequential action | **True at ledger level, with caveats** from Sentinel's own `METRICS.md`: only **5 of 10** attacks got a BLOCK verdict. A3, A5, A6 and A7 were ALLOWed because the planner proposed a read-only action (`summarize`/`label`), and A10 got CONFIRM. Verdicts matched expectations for 17 of 24 emails, and one legitimate email (N9) was blocked. Safety came from action tiering, not detection. | `METRICS.md` |
| Tests | **182 tests pass** (run in a throwaway venv on Python 3.11). | Section 9 |

Two Sentinel results depend on seed-specific code (section 3.3):

- **Seed-shaped parser and planner.** `ParserAgent` and `ActionPlannerAgent` decide intent with keyword branches written for the seed corpus. Their verdicts would not carry over to real email.
- **Canned protection-OFF fallback.** When the LLM call fails, `NaiveAgent` produces a hardcoded "attack succeeded" result. In `METRICS.md`, A1's protection-OFF result used this path (`engine: offline`).

---

## 2. How FactFlow works today

### 2.1 Layout

The backend is **flat**, not `backend/app/...` as the prompt assumes:

```
backend/
  main.py  config.py
  agents/     orchestrator, intake_agent, source_tracer, deep_reasoning, explainer, harm_assessor,
              context (PipelineContext), grounding, uncertainty, query_variants
  api/        verify, stream, result, history, incidents, stats, registry, public_config, accuracy
  database/   connection (engine, create_all, add-missing-columns), models, seed_data
  models/     groq_client, gemini_client, vision_output   <- LLM clients, not Pydantic schemas
  services/   input_service, news_service, factcheck_service, registry, event_bus, safety,
              text_utils, tiers, cache_service
  tasks/      pipeline_task (Celery or in-process dispatch)
  scripts/    run_bench.py
  tests/      146 cases, bench/claims.json
frontend/     pages/, components/, lib/, styles/
extension/    MV3: background.js, content.js, popup, options
android/      overlay_mockup.html (mockup only)
```

### 2.2 Pipeline

`POST /api/verify` (`api/verify.py`) does the following before any agent runs:

1. Redacts phone numbers, e-mails and @handles.
2. Validates screenshots by magic bytes.
3. Rate-limits to 10 requests per minute per IP (in-memory).
4. Runs the private-person and self-harm rule.
5. Answers repeat claims from the registry.

Otherwise it stores a `claims` row and dispatches `run_pipeline` in-process (or through Celery).

`agents/orchestrator.py` runs the six agents:

| Step | Agent | Model | Notes |
|---|---|---|---|
| 0 | Orchestrator | none | Routes text, URL or image. URLs are fetched with `httpx` and parsed with BeautifulSoup; images are read by Gemma 4 or Tesseract. Matches known patterns. |
| 1 | Intake & Triage | Nano | Claim, language, type, urgency, search queries |
| 2 | Source Tracer | Nano | GDELT, NewsAPI, Google Fact Check and DuckDuckGo in parallel. Tiers come from config allow-lists; the model judges relevance and stance. |
| 3 | Deep Reasoning | Ultra | Only if confidence is below 0.85 or urgency is CRITICAL |
| gate | `decide_verdict` | none | Honest-uncertainty gate: at least 2 tier 1-2 sources and confidence of at least 0.6, otherwise UNVERIFIED |
| 4 and 5 | Explainer and Harm Assessor | Nano | Run in parallel |
| final | grounding | none | Drops sentences that contradict the verdict or cite no source |

The result is persisted and published to the registry (`/v/{slug}`) unless the request was private. The pipeline
timeout is 170 s. Each agent gets one orchestrator retry, and `groq_client` adds tenacity retries that honour
`retry-after`.

### 2.3 SSE events (reuse this format)

`GET /api/stream/{request_id}` (`api/stream.py`, sse-starlette, 15 s keep-alive). The SSE `event:` name equals the
`type` field, and `data` is the JSON object:

| type | fields |
|---|---|
| `start` | `request_id`, `input_type`, `agents` (full list) |
| `agent` | `agent` (index), `index`, `name`, `tier`, `role`, `status` (`waiting`, `running`, `complete`, `skipped` or `failed`), `preview`, `model`, `ms`, `progress` (0-100), `elapsed_ms` |
| `result` | `progress`, `result` (`Claim.to_result()`) |
| `error` / `withheld` | `message` |

Events live in a per-request log (`MemoryBus`, or `RedisBus` under the `factflow:events:` keys) with a one-hour
retention. A finished request is replayed from the database if the process restarted.

`components/AgentProgress.js` renders **any** `agents[]` list in this shape. An inbox pipeline can reuse it by
emitting its own stage list in `start` and `agent` events. The heading "ANALYZING CLAIM" is hardcoded and needs an
optional prop.

### 2.4 "Cache" and database

- **No verdict cache in Redis.** Reuse comes from the registry: exact hash on normalised text, then a fuzzy match
  over the 500 newest public claims, within a 7-day window (`services/registry.py`).
- **Tables:** `claims`, `sources`, `known_patterns`, `incidents` (seed: 6 incidents, 10 patterns).
- **Schema management:** `Base.metadata.create_all`, then `_add_missing_columns` adds new model columns in place.
  This works on both Postgres and SQLite. There is no Alembic and there are no SQL migration files
  (`database/connection.py:53-95`).

### 2.5 Frontend navigation

The navbar (`components/Navbar.js`) links Verify `/`, Tracker `/tracker`, Incidents `/incidents` and About `/about`.
`/registry`, `/accuracy` and `/v/[slug]` exist but are not in the navbar. On the right sit a "BEST APPS TRACK" badge,
a leftover from the earlier hackathon, and "GROQ × GPT-OSS". No page uses `dangerouslySetInnerHTML`. The
Myth-vs-Fact card is exported with html2canvas.

### 2.6 Extension and the WhatsApp Web hover

- **Content script** on `<all_urls>`. Site adapters for WhatsApp Web, X and Instagram find a message container and
  its text.
- **WhatsApp adapter:** container `el.closest("[data-id]")`; text from `span.selectable-text` and
  `div.copyable-text span[dir]`. These are WhatsApp class names and can change without notice.
- **Hover button:** a red "V" in an open shadow root (`<factflow-hover>`). Clicking it sends `FACTFLOW_VERIFY_TEXT`
  to the service worker. The worker calls `POST /api/verify`, polls `/api/result`, and the content script shows an
  inline chip (`<factflow-inline>`).
- **Other entry points:** context menus on any selection or image, a "Verify this message" menu on the social
  sites, and the Ctrl+Shift+V shortcut.
- **Storage:** `chrome.storage.local.history` holds the last 5 results.
- **Defect 1, settings ignored:** the options page saves `apiBase`, but `background.js:3` and `popup.js:1`
  hardcode `http://localhost:8000` and never read it.
- **Defect 2, localhost only:** `host_permissions` cover only `localhost:8000` and `127.0.0.1:8000`, so a deployed
  backend URL would not work even if the setting were read.

### 2.7 Security posture of the current code (relevant to Section 13)

| Item | State |
|---|---|
| Authentication | **None** on any route. `SECRET_KEY` is defined in config but unused. |
| CORS | `FRONTEND_URL`, `localhost:3000` and **any** `chrome-extension://` origin |
| Rate limiting | In-memory sliding window, `/api/verify` only, keyed by client IP |
| Outbound fetch | `fetch_url_text` and `download_image` follow redirects to any host. **No SSRF guard**: private, loopback and metadata IPs are reachable. |
| Untrusted text to LLMs | Forwards, fetched pages, OCR text and **search-result titles and snippets** are pasted into prompts inside `"""` quotes, with no delimiting tag and no detector. A `"""` inside a forward closes the quote. |
| Hidden content in fetched pages | `fetch_url_text` removes `script`, `style` and `noscript`, but keeps `<p>` text inside `display:none` or white-on-white elements, which then reaches the LLMs. |
| Output channels for injected text | `whatsapp_reply`, the corrections (EN/HI/TE) and the **public registry page `/v/{slug}`**. An injection that steers the Explainer could get attacker text published on a public page. |
| PII | `redact_pii` covers phone, e-mail, @handle and runs of 10 or more digits. No Aadhaar, PAN, UPI or card checksums. Registry fuzzy matching depends on its lowercase placeholders (`registry.py:21`), so it must not be changed in place. |
| Secrets in git | No `.env` was ever committed to either repo. Key-shaped strings in FactFlow history are test placeholders (one `gsk_` string of 33 characters with placeholder markers; the `AIza…` strings are visibly fake). Sentinel history has none. **No rotation needed.** |

---

## 3. Sentinel: port, rewrite, drop

Sentinel's unit of work is a seed object with pre-filled `spf`, `dkim`, `dmarc` and `reply_to` attributes, not a
parsed RFC 822 message. Most of its detection reads from `seed_data.py` (21 contacts, 8 threads, 30 domain-intel
entries with fixed domain ages). Its scenario is a Western business (Northwind Traders, IBAN payment fraud), not
Indian consumer scams.

### 3.1 Port (adapt the idea and code into `backend/shield/`)

| Sentinel piece | Why it is worth keeping | Becomes |
|---|---|---|
| `policy._Provenance`: argument provenance **recomputed** by matching values against the email text and user/system registries, then lowered to whatever the planner claimed | This is how "origin = untrusted_content" can be decided in code rather than trusted from an LLM | `shield/policy.py`, which computes `origin` before rules P1-P8 |
| `policy.evaluate` fail-closed wrapper (any exception becomes BLOCK) and unknown tool becomes BLOCK | Matches "fail closed" | `shield/policy.py` |
| `find_disallowed_urls` with `_url_host` (IDNA, `javascript:`/`data:`, `\` in netloc) | Egress check for drafts: blocks image or link exfiltration (EchoLeak-style) | `shield/policy.py` egress check on `draft_reply`, `send_reply` and `forward_email` |
| `_bad_recipients` (recipient domain allowlist) | Equivalent of prompt rule P4 | `shield/policy.py` |
| `PolicyStore` monotonic config (tiers can only tighten; adding domains needs `confirm=True`; every change audited) | The `strict`/`balanced` toggle loosens policy, so switching to `balanced` should need confirmation and an audit entry | `shield/policy.py` config store |
| `executor.py` and `ledger.py` pattern: the side effect is recorded **inside** the tool body, so a ledger entry exists only if the tool really ran | The simulated outbox becomes proof of what executed | `shield/sandbox_agent.py` with a DB-backed `simulated_outbox` |
| Frozen provenance-carrying `Field` and `least_trusted` | Useful for planner arguments | `shield/schemas.py` |
| Test ideas from `tests/test_policy.py` | Fail-closed, tier monotonicity, egress | `tests/shield/test_policy.py` |

### 3.2 Rewrite (keep the goal, replace the code)

| Sentinel piece | Problem | Replacement |
|---|---|---|
| `InjectionAnalystAgent.scan` and `tools.detect_hidden_content` | Regex over `style="..."` strings. "color:white" is flagged regardless of background, there is no inheritance, no `<style>` blocks, no Unicode Tags block, and comments are flagged on 6 keywords. | HC-01 to HC-12 with BeautifulSoup and lxml, computed styles, contrast ratio; `shield/hidden_content.py`, `shield/injection.py` |
| `tools.check_auth` | Reads seed attributes | Parse `Authentication-Results`, `Received-SPF` and `DKIM-Signature` from real headers; `shield/phishing.py` |
| `tools.analyze_links`, domain lookalike (`difflib` ratio 0.8 against 2 Western domains) | Wrong brand set; no punycode/homoglyph or subdomain tricks against Indian brands | `shield/phishing.py` with `config/brands.yml` |
| `NaiveAgent` | The offline fallback fabricates attack success from seed strings | Shield-OFF assistant that only uses a real LLM. If the LLM is unavailable it reports "unavailable, nothing executed", never a canned success. Gated by `ALLOW_VULNERABLE_DEMO`. |
| `PolicyStore` audit (in-memory list) and `ledger` (in-memory) | Lost on restart, not tamper-evident | `shield/audit.py`: SHA-256 hash chain in the `audit_log` table |

### 3.3 Drop

| Sentinel piece | Reason |
|---|---|
| `ParserAgent` and `ActionPlannerAgent` intent logic | Keyword branches written for the seed corpus (`agents.py:205-244`; the attacker address is hardcoded at lines 214 and 515). Porting them would produce canned results, which Rule 5 forbids. Replaced by the stdlib email parser plus a structured planner over validated fields. |
| `evidence.py` log-odds fusion and `RiskAssessorAgent` | The prompt defines a different, deterministic scoring rule (section 4.6). Two scoring systems would conflict. The "open questions" idea can be reused in explanations. |
| `tools.lookup_contact`, `thread_history`, `domain_intel` | Read fixed seed tables (fabricated domain ages). No real data source in scope. |
| `seed_data.py`, `seed_emails.md` | Western business scenario. Replaced by 14 India-specific demo emails (section 9.3). |
| `static/index.html` | Vanilla-JS UI. FactFlow's Next.js UI is the only UI. |
| `llm.py` | FactFlow's `models/groq_client.py` already has retries, JSON mode and `retry-after` handling. |
| Untracked `sentinel/` folder in CVR | Older copy with its own `.venv`, git-ignored |

### 3.4 Rule ID collision

Sentinel uses `P-00` to `P-08`. The prompt's P1-P8 table assigns different meanings to the same numbers. **Proposal:**
keep the prompt's `P1`-`P8` as the decision rules, and name the ported Sentinel checks by function:

- `E-EGRESS`: outbound URL check
- `E-RECIPIENT`: recipient allowlist check
- `E-FINANCIAL`: payment details taken from email content
- `P0`: fail-closed exception handler

This goes into `docs/DECISIONS.md` in Phase 1.

---

## 4. Addendum v2 Phase 0 items

| Item | Finding |
|---|---|
| Existing extension and WhatsApp Web hover | Documented in section 2.6 |
| Live Gmail DOM | **Not inspectable from this environment** (no browser session). Candidate message-id sources to verify against live Gmail in Phase 6, **all unverified**: the `data-legacy-message-id` attribute (hex; commonly reported to equal the Gmail API message id), the `data-message-id` attribute (`#msg-f:<decimal>` format), and the thread id in the URL hash. All selectors will live in `extension/gmail_selectors.js` with documented fallbacks. If none is stable, the banner falls back to the opt-in "Scan what I'm reading" path. |
| Can the stack accept webhooks? | FastAPI can, but the backend is localhost-only and **no tunnel tool is installed** (`ngrok` and `cloudflared` are not on PATH). Twilio signature validation is computed over the exact public URL, so the tunnel URL must be configured precisely. Options: Cloudflare quick tunnel (no account needed) or ngrok in dev; Render (Sentinel already deploys there) or Railway for deployment. FactFlow has no deploy config yet. |
| `<all_urls>` removal (A5.5) vs "never break existing features" (Rule 4) | **Conflict.** Today's right-click "Verify with FactFlow" works on any page because the content script runs on `<all_urls>`. Proposal: content scripts only on `mail.google.com`, `web.whatsapp.com`, `x.com`, `twitter.com` and `instagram.com`; on other pages inject on demand with `activeTab` plus `chrome.scripting.executeScript` (adds the `scripting` permission). This keeps the feature without `<all_urls>`. Needs your approval. |
| Gmail OAuth realities | `gmail.readonly` is a restricted scope; an app in "Testing" mode with listed test users works without Google verification. Refresh tokens in Testing mode expire after about 7 days, so design for reconnect (as A2 already says). |
| WhatsApp | Twilio sandbox users must first send the "join" code. Replies to a user's message fall inside WhatsApp's customer-service window. The helpline and portal (1930, cybercrime.gov.in) will be checked against official sources in Phase 5 before hardcoding, as A4.4 requires. |

---

## 5. Proposed file plan (adapted to the real layout)

The prompt's `backend/app/` becomes `backend/`. `shield/` stays importable on its own: **no imports of FastAPI,
database or `config.py` inside `shield/`**, so the edge device can reuse it later. Persistence and HTTP live outside
it.

```
backend/
  shield/                       NEW package, pure Python
    __init__.py
    schemas.py                  Pydantic v2: HiddenFinding, RuleHit, components, UnifiedVerdict,
                                ProposedAction, PolicyDecision, Approval  (prompt's models/verdict.py; see note)
    email_parser.py             stdlib email, policy.default; limits 5 MB / 20 attachments / 200k chars
    hidden_content.py           HC-01..HC-12
    css.py                      inline style + <style> block resolution, colour parsing, WCAG contrast
    views.py                    visible_view, raw_view, diff tagged with HC-IDs
    injection.py                rule layer (Phase 1); LLM layer added in Phase 2
    phishing.py                 auth headers, sender checks, lookalikes, links (no fetching by default)
    scam_patterns.py            India-specific detectors
    redact.py                   typed placeholders, Verhoeff/Luhn; separate from services/text_utils.redact_pii
    scoring.py                  deterministic overall score and label (section 4.6); weights from policy.yml
    policy.py                   P0, P1-P8, strict/balanced, provenance (ported), egress/recipient checks
    approvals.py                HMAC token bind/verify, expiry, single use (pure; storage injected)
    audit.py                    canonical JSON, hash chain, verify (pure; storage injected)
    quarantine.py               Phase 2: Q-LLM wrapper, <untrusted_content> blocks, schema validation
    qr.py                       Phase 2 (SHOULD)
    mail_agent.py               Phase 3 state machine
    providers/                  Phase 3: base.py (MailProvider), eml.py, gmail.py; Phase 5: whatsapp.py
    sandbox_agent.py            Phase 4
    config/patterns.yml  brands.yml ("HUMAN MUST VERIFY")  policy.yml
  database/models.py            ADD tables: emails, approvals, audit_log, simulated_outbox, benchmark_runs
                                (Phase 3: mail_accounts, mail_tasks; Phase 5: whatsapp_checks)
  services/shield_store.py      DB-backed storage for approvals, audit and outbox (keeps shield/ pure)
  api/inbox.py approvals.py audit.py         Phase 2-3
  api/benchmark.py                           Phase 4
  api/mail.py                                Phase 3 (Gmail connect/callback/disconnect)
  api/whatsapp.py                            Phase 5
  data/demo_emails/*.eml  data/benchmark/
  scripts/generate_demo_emails.py           (backend/scripts already exists)
  tests/shield/test_*.py
frontend/
  pages/inbox/index.js  pages/inbox/[id].js  pages/approvals.js
  pages/advanced/benchmark.js  pages/advanced/audit.js
  components/ApprovalPanel.js (global)  components/WhatYouSee.js  (+ optional heading prop on AgentProgress)
docs/
  AUDIT.md (this file)  DECISIONS.md (Phase 1)  ... rest in Phase 7
```

Notes on deviations (recorded in `docs/DECISIONS.md` in Phase 1 if you approve):

1. **`backend/app/` becomes `backend/`.** Keeps imports consistent with the existing code.
2. **Schemas go in `shield/schemas.py`, not `models/verdict.py`.** `backend/models/` already holds LLM clients, and
   keeping schemas inside `shield/` keeps the package self-contained for the edge.
3. **Migrations.** The repo has no Alembic. It uses SQLAlchemy `create_all` plus an add-missing-columns step that
   works on both Postgres and SQLite. Hand-written SQL files would have to be maintained per dialect and would
   bypass the SQLite fallback. Proposal: define the new tables as SQLAlchemy models (same mechanism), not SQL files.
4. **Rate limiting.** Reuse the existing `RateLimiter` (`api/verify.py`) for `/api/inbox/*` and `/api/whatsapp/*`
   instead of adding slowapi.
5. **Scoring.** The deterministic score is a separate `scoring.py` so policy and scoring can be tested
   independently.
6. **Approvals need an identity.** The backend has no auth. An HMAC-bound token stops tampering with the
   (email, action, target) triple, but anyone who can reach the API could approve. Proposal: an `OPERATOR_TOKEN`
   header required on approval decisions and policy-mode changes, entered once in the UI. This is enough for a
   single-user prototype.

### Phase 1 dependencies to add (pinned when added)

`pyyaml` (config), `pypdf` (HC-09), `cryptography` (Fernet, Phase 3). `dnspython` is optional, for
`ENABLE_DNS_CHECKS`, which defaults to off. A QR decoder is needed in Phase 2: `opencv-python-headless` is
cross-platform with no system library, while `pyzbar` needs the zbar DLL or `libzbar0`. The choice will be recorded
in DECISIONS. BeautifulSoup and lxml are already present.

---

## 6. Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| 1 | **Groq free-tier daily token limit** (README: about 200k tokens/day for `gpt-oss-20b`). Each email can trigger a Q-LLM classification, claim extraction and up to 3 full fact-checks. | Benchmark (80+ cases) and demo rehearsals can exhaust the quota | Benchmark has a rules-only mode plus an LLM mode, and reports which runs used the LLM; reuse registry answers for repeated claims; consider a paid tier or second key for demo day |
| 2 | **Latency.** One fact-check measured 28 s (with Ultra). The prompt's target is an email pipeline p50 under 12 s. | Target not met if claims block the verdict | Return the Shield verdict first; stream claim fact-checks into the "Claims" component as they finish; report real numbers |
| 3 | **Detector false positives.** Marketing email routinely uses `display:none` preheaders, 1 px tracking images and tiny fonts; Indic text uses ZWJ/ZWNJ. | Strict mode would pause most legitimate mail | Benign benchmark cases for each; HC-06 Indic-context rule; severity tuning; strict mode is honest about this in the UI |
| 4 | **Untrusted text into the existing pipeline**, including search snippets, with the public registry page as an output channel | Attacker text published on a public page | Phase 2 hardening: wrap all untrusted inputs, run detectors, and add a regression test on registry output |
| 5 | **No SSRF guard** in the existing URL and image fetch | Server-side requests to internal addresses | Shared guarded fetcher (resolve, then check the IP, re-validate each redirect, size caps) in Phase 2 |
| 6 | **No authentication** | Anyone with network access can approve actions or change the policy mode | `OPERATOR_TOKEN` (section 5, note 6); keep the backend on localhost or behind the tunnel only during the demo |
| 7 | **Audit chain concurrency.** The pipeline runs as concurrent asyncio tasks, or in Celery workers. | Two writers can fork the chain | Single writer: an asyncio lock in-process plus a Postgres row lock on the chain head; Celery mode writes through the same lock |
| 8 | **Policy rule-ID collision** with Sentinel | Confusing docs and tests | Section 3.4 naming |
| 9 | **`<all_urls>` conflict** in the extension | Breaking right-click verify on arbitrary pages | Section 4 proposal |
| 10 | **Tesseract has no `hin`/`tel` data**, and Gemma vision has no key in the current `.env` | Hindi/Telugu screenshot and QR-image checks degrade | Install the `hin` and `tel` traineddata, or set `GEMINI_API_KEY`; QR decoding does not depend on OCR |
| 11 | **Gmail DOM and Twilio specifics unverified** from here | Extension banner selectors or webhook signatures fail on the day | Verify in Phases 5-6 against live services; the `.eml` demo inbox stays the fallback |
| 12 | **Schedule.** 29 days to feature freeze (20 Nov) for Phases 1-6. | Scope overrun | Follow the addendum's cut order; Phase 1 is deterministic only, so it can be tested without quota |
| 13 | **Old-hackathon UI text.** The navbar "BEST APPS TRACK" badge, and the README "Gemma 4" section framed for the earlier event. | A judge sees another event's branding | Your call. A1.2 says to keep the existing UI unchanged, so I have not touched it. |
| 14 | **Docker not running** | A `run_all.ps1` that assumes Docker would fail | Script native Postgres and Memurai, which are both installed |

---

## 7. Decisions needed from you before Phase 1

1. Approve the layout deviations in section 5 (notes 1-5).
2. `OPERATOR_TOKEN` for approvals and policy-mode changes (section 5, note 6).
3. The rule-ID naming in section 3.4.
4. The extension `<all_urls>` resolution in section 4. This applies in Phase 6, but affects nothing before.
5. Whether to remove the "BEST APPS TRACK" navbar badge (risk 13).

## 8. Not covered by this audit

- Hardware and edge (postponed by the addendum).
- Live Gmail DOM inspection, Twilio sandbox behaviour and Google OAuth console steps (need live accounts).
- Re-running the Hindi-to-Marathi, URL and image checks from Section 2 (code paths read; not executed).
- Performance beyond the single live run above.

## 9. Commands run during the audit

| Purpose | Command (summary) | Result |
|---|---|---|
| Toolchain | `tesseract --version`, `--list-langs`, `ffmpeg`, `psql`, `docker`, `memurai`, `ngrok`, `cloudflared` | Section 1.1 and section 4 |
| Secrets scan | `git log --all -p` searched for key-shaped strings; values never printed | Section 2.7 |
| Sentinel tests | Fresh Python 3.11 venv in a scratch folder, `pip install -r requirements.txt`, `pytest -q -p no:cacheprovider` | 182 passed |
| Live claim | Backend on port 8012, `POST /api/verify` with bench case F01 (`visibility: private`), result read from the SSE stream | FALSE, 0.94, 28,049 ms, Ultra used |
