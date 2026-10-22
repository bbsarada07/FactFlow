# Decisions

Choices made where the build prompt was ambiguous, conflicted with the repo, or needed a judgement
call. Newest phase last. "Approved" means the team agreed to it explicitly.

## Phase 0 (approved 2026-10-22)

| # | Decision | Why |
|---|---|---|
| D1 | The prompt's `backend/app/` is `backend/`. Shield lives in `backend/shield/`, routers in `backend/api/`. | The existing backend is flat; one import style. |
| D2 | Verdict schemas live in `shield/schemas.py`, not `models/verdict.py`. | `backend/models/` holds the LLM clients; keeping schemas inside `shield/` keeps the package self-contained for the edge device. |
| D3 | New tables are SQLAlchemy models created by the existing `create_all` and add-missing-columns step, not SQL migration files. | The repo has no Alembic, and hand-written SQL would need one version per dialect and would bypass the SQLite fallback. |
| D4 | Rate limiting reuses the existing `RateLimiter` (`api/verify.py`) instead of adding slowapi. | Fewer dependencies; same behaviour. |
| D5 | Scoring is its own module (`shield/scoring.py`). | Policy and scoring tested separately. |
| D6 | `OPERATOR_TOKEN` protects approval decisions, policy-mode changes, Gmail connect and disconnect, and audit verify. The user enters it at runtime; the frontend keeps it in `sessionStorage` only (never in the bundle or in a `NEXT_PUBLIC_*` variable). The backend compares it in constant time and rate-limits failed attempts. Claim-check routes stay public but rate-limited. | The backend has no authentication; an HMAC-bound approval token stops tampering but not an outsider approving. Wired in when the routes are built (Phases 2-3). |
| D7 | Policy rules keep the prompt's names `P1`-`P8`. Checks ported from Sentinel are named by function: `E-EGRESS` (outgoing URLs), `E-FINANCIAL` (bank/card/identity numbers in outgoing text), `P0` (fail closed). Sentinel's recipient check is folded into `P4`. Strict-mode escalation is `S1`. | Sentinel's own `P-01`..`P-08` mean different things. |
| D8 | Extension: content scripts only on `mail.google.com`, `web.whatsapp.com`, `x.com`, `twitter.com`, `instagram.com`; other pages get the script injected on demand (`activeTab` + `chrome.scripting`), so right-click verify keeps working without `<all_urls>`. | Applies in the extension phase; right-click verify is re-tested then. |
| D9 | The "BEST APPS TRACK" navbar badge, a leftover from the earlier hackathon, is removed. Nothing else in the existing UI changes. | Team decision. |

## Plan additions (approved 2026-10-22)

| # | Addition |
|---|---|
| A1 | The Shield-OFF demo assistant uses a real LLM only. If the LLM is unavailable it says so and nothing is executed; there is no canned "attack succeeded" fallback (Sentinel's `NaiveAgent` had one; it is not ported). |
| A2 | Phase 4 measures how often each attack actually succeeds against the Shield-OFF assistant over about 20 runs per attack, and reports the rates as measured, including attacks that rarely or never succeed. |
| A3 | The benchmark's default mode is rules-only (`shield/scan.py`, no LLM, no quota use). The LLM mode is opt-in and its results are labelled as such. |

## Phase 1: Shield core

### Intake and limits

| # | Decision | Why |
|---|---|---|
| D10 | Inputs over 5 MB or with more than 20 attachments are rejected (`EmailInputError`, mapped to HTTP 4xx later). A body over 200,000 characters is **truncated, not rejected**, and the truncation is recorded in `analysis_failures` (+15 to the score). | "Max 200k chars of body processed" reads as a processing cap; rejecting long newsletters would be worse for users. **Phase 2: also floors the label at SUSPICIOUS (D37).** |
| D11 | Raw source vs plain paste is decided by looking for a header block (at least two header lines, one of them a common header). | A pasted forward that starts with "Note: ..." must not be parsed as headers. |

### Hidden-content detection

| # | Decision | Why |
|---|---|---|
| D12 | CSS is resolved without a browser: presentational attributes, then `<style>` rules in document order (no specificity), then inline styles. `@media` and other @-rules are skipped. Background defaults to white; dark mode is not modelled. | Good enough for the hiding techniques seen in practice; a full CSS engine is out of scope. Listed as a known limit. **Phase 2: specificity and @media added (D38).** |
| D13 | HC-02 boxes: `height`, `max-height`, `width`, `max-width` or `line-height` of 1px or less count only together with `overflow:hidden`/`clip`. Font size 2px or less always counts. | `max-height:0` without overflow hiding still shows the text. |
| D14 | HC-04: `left`/`top`/`right`/`text-indent`/`margin-*` of -999px or less; `position:absolute|fixed` with `left`/`top` of 5000px or more; zero `clip` rects; `clip-path: inset(50%|100%)`, `circle(0)`; `transform: scale(0)`. | Covers the standard screen-reader and spam hiding tricks. |
| D15 | Severity of hidden text depends on what it says: critical if it matches an injection rule, medium if it is prose (40+ characters and 6+ words), low otherwise. | A hidden marketing preheader is common and harmless; hidden instructions are not. |
| D16 | HC-06 does not flag ZWJ/ZWNJ between Indic or Arabic-script letters, ZWJ inside emoji sequences, tag characters inside emoji subdivision flags (e.g. the England flag), or a byte-order mark at the very start. | These are legitimate uses (prompt section 10). |
| D17 | HC-08 carriers (alt, title, aria-label, data-*, meta, hidden inputs, noscript, template, title, style/script text) become findings only when instruction-like or prose. Their text always appears in the "what the AI reads" view and its diff. | The diff should show everything an AI would read that a person does not; findings should not fire on "Company logo". |
| D18 | HC-11: a mismatch that goes through a known email click-tracking domain (`brands.yml: link_trackers`) is medium instead of high. | Newsletters routinely do this. |
| D19 | HC-12 runs only when the message has a `multipart/alternative` part with at least 5 words in each version. | Very short parts give meaningless Jaccard scores. |

### Rules and domains

| # | Decision | Why |
|---|---|---|
| D20 | Rules are matched on normalised text (Unicode Tags decoded, NFKC, invisible characters removed, Cyrillic/Greek lookalikes mapped to Latin, casefolded). Injection rules are tried with line breaks kept and with them flattened; scam rules use the flattened text. In a pattern, `[^.\n]` ("same sentence") also lets through a dot that is not followed by whitespace. | Without this, a line break or the dot in `x.com` stopped a rule from matching. |
| D21 | Registrable domains use the short multi-part suffix list in `brands.yml`, not the full Public Suffix List. | No extra dependency; covers Indian and common suffixes. Rare suffixes are a known limit. |
| D22 | `brands.yml` legitimate domains come from general knowledge and are marked **HUMAN MUST VERIFY**. Domains under `.bank.in` are treated as regulated (only banks can register there). | A wrong allowlist entry is a security bug, so it must be checked by a person before the demo. |
| D23 | No link is fetched and no DNS lookup is made in Phase 1. `ENABLE_LINK_EXPANSION` and `ENABLE_DNS_CHECKS` (both default off) arrive in Phase 2 with the SSRF-guarded fetcher. | Outbound requests need the SSRF guard first (AUDIT risk 5). |
| D24 | Plain `http://` links are not flagged. | Not in the spec, and strict mode escalates on any flagged link: it would pause most newsletters. **Reversed in Phase 2 (D39).** |

### Scoring and policy

| # | Decision | Why |
|---|---|---|
| D25 | Each entry in `analysis_failures` adds 15 (so two failures add 30). | "Any entry adds 15" read per entry; failures can only raise the score. |
| D26 | Confidence is a documented formula (`policy.yml: scoring.confidence`): 0.6 base, +0.1 per corroborating component, 0.9 when the hidden-injection override applies, -0.15 per analysis failure, clamped to 0.2-0.95. | The schema needs a number; this one is explainable. |
| D27 | Strict mode is applied as an upgrade on top of balanced: a balanced ALLOW becomes REQUIRE_APPROVAL (`S1`) when any signal is present. Without explicit signals, any label other than SAFE counts. | Guarantees strict is never looser than balanced (tested). |
| D28 | `E-EGRESS` blocks in both modes, like Sentinel's P-04. | Links and images in outgoing text can leak data. |
| D29 | An unknown action is BLOCK (`P0`), not REQUIRE_APPROVAL (`P8`). | Nothing not explicitly modelled should reach a human as if it were legitimate. |
| D30 | Origin is recomputed: an action's target counts as the user's only if the user typed it (`UserContext.user_values`); anything else, including a target a model invented, is untrusted. | Ported from Sentinel; stops a planner from laundering an injected address. |
| D31 | Loosening the policy (strict to balanced, or adding a trusted domain) needs `confirm=True`; tightening does not. A change takes effect only after the audit callback succeeds. | Ported from Sentinel's monotonic policy store. |

### Approvals, audit, redaction

| # | Decision | Why |
|---|---|---|
| D32 | The audit hash covers `actor` and `event_type` as well as the payload: `SHA-256(prev_hash \| canonical_json({actor, event_type, payload}) \| ts \| seq)`. `ts` is stored as the exact string hashed; `seq` is the primary key. | Stricter than the spec (changing who did something is detected); the primary key stops two writers forking the chain. |
| D33 | The approval token is HMAC-SHA256 over the approval id, `email_id`, `action`, `target` and expiry. The secret must be at least 32 bytes or nothing is created. Decisions use a conditional update so a token works once even under concurrent requests. Refused decisions are audited. | Section 7. |
| D34 | Redaction placeholders are `[KIND]`. When a request needs to restore values, `Redactor(numbered=True)` gives `[KIND_n]` and keeps the map in that object only (never stored). `services/text_utils.redact_pii` is unchanged. | The registry's repeat matching depends on the old placeholders. |
| D35 | `shield/` imports nothing from FastAPI, SQLAlchemy, `config.py` or `database/` (tested). Storage is in `services/shield_store.py`. | Edge reuse later. |
| D36 | Before the LLM layer exists, "what the hidden text tried to do" (`attempted_actions`) is read deterministically from injection rule hits and the addresses/URLs in the text. Phase 2 merges the LLM's reading. | Lets the policy engine and the UI show blocked attempts from Phase 1. |

### Dependencies

`pyyaml==6.0.3` (configuration), `pypdf==6.21.2` (PDF attachment text and metadata, HC-09).

### Deferred from Phase 1

`APPROVAL_SECRET` and `OPERATOR_TOKEN` settings are added with the routes that use them (Phases 2-3).
The `emails`, `simulated_outbox` and `benchmark_runs` tables arrive with the features that write to them.

## Phase 2: LLM layer and inbox pipeline

### Team additions (2026-10-22)

| # | Decision |
|---|---|
| D37 | A truncated body, or an attachment that could not be fully read (PDF over 20 pages, unreadable PDF, text over 50,000 bytes), adds an `analysis_failures` entry (+15) and floors the label at SUSPICIOUS. Unscanned content is never treated as clean. A failed *model* call on a fully scanned message adds +15 but does not floor the label, since the rules saw everything; strict mode still pauses every step on it (rule S1). |
| D38 | `css.py` now applies `<style>` rules by specificity then source order, with `!important` and inline styles in the browser's order, and evaluates `@media` for an 800px desktop screen in light mode. Known misses, pinned by tests: content hidden only on phones (`max-width` queries), only in dark mode, or inside `@supports`. |
| D39 | Plain `http://` links are flagged `no_https` (low). With strict mode this pauses messages that use plain-http links. |
| D40 | Every outbound fetch of a URL FactFlow did not choose goes through `services/safe_fetch.py`: http/https only; every resolved address must be public; the connection goes to the checked address (TLS still verifies the host name via SNI); every redirect is re-checked; no proxies, no cookies, time and size caps. Used by the existing URL and image inputs and by link expansion. |
| D41 | `OPERATOR_TOKEN` and `APPROVAL_SECRET` are wired in (see D6 and `docs/API_CONTRACT.md`). Besides the routes listed in D6, the operator token also protects the inbox list and the audit list, because both expose other people's messages. Single analyses stay readable by their unguessable id, like `/api/result/{id}`. |

### Design choices

| # | Decision | Why |
|---|---|---|
| D42 | The quarantined reader makes one model call per message that does injection classification, a scam second opinion and claim extraction. Its JSON is validated by Pydantic; anything else is discarded and becomes an analysis failure. Unknown action names map to `execute_instruction_from_content`, so they are always blocked. | Keeps token use low (one call instead of three) without weakening the schema check. |
| D43 | Before the reader call, PII is redacted with numbered placeholders. Afterwards, addresses in quotes and attempted actions are restored for display; claims stay redacted, because they go on to more model calls. | Section 4.7: no PII to external models. |
| D44 | The agent extensions in section 5 for Intake (input type), Source Tracer (sender and link reputation) and Harm Assessor (fraud harm) are deterministic code, not extra model calls. Deep Reasoning is used only through the existing claim pipeline. | Token budget (MEASUREMENTS.md); these checks need no model. |
| D45 | The explainer sees FactFlow's findings plus short quoted strings (claims, addresses the message named) in an untrusted block, never the message itself. Links and addresses are removed from its output by code. | A steered model cannot plant a link in the WhatsApp warning. |
| D46 | Claims extracted from messages are fact-checked as **private** claims (never in the public registry). A repeated claim reuses any earlier verdict from the last 7 days, public or private, inside the inbox pipeline only. `autopsy_id` is the claim's request id (`/api/result/{id}`). A SATIRE verdict is reported as UNVERIFIED, because the brief's claim verdicts have no SATIRE. | Email content can be personal; reuse saves the most tokens. |
| D47 | Every inbox model call is capped at `INBOX_LLM_TIMEOUT_SECONDS` (25 s); after that the analysis continues rules-only with the failure recorded. | Measured: a rate-limited provider was retried for 80 s (MEASUREMENTS.md). |
| D48 | For DANGEROUS messages the pipeline proposes `report_phishing` and `quarantine_email` (origin `user`). In strict mode these too go to approval (S1), as the addendum asks ("every step"). Approved actions are not executed yet; the simulated outbox comes in Phase 4. | Brief, Addendum A1.4. |
| D49 | The verdict gains optional fields: `mode`, `pipeline_version`, `input_type`, `message`, `harm`, `llm_usage`, and `links.items[].expanded_to`. `latency_ms.per_stage` is in milliseconds with one decimal. | The UI needs them; sub-millisecond stages showed as 0. |
| D50 | Policy settings changed at runtime are kept in memory and in the audit log; a restart returns to `policy.yml`. A change is written to the audit log before it is applied, under a lock. | Simple; no extra table yet. |
| D51 | The email cache key is SHA-256 of the raw bytes + pipeline version + mode + explanation language. `force=true` bypasses it. | Section 13; the language changes the explanation. |
| D52 | The existing fact-check pipeline is hardened: every agent prompt marks forwards, pages, OCR text, search titles and snippets as `<untrusted_content>`; fetched pages are reduced to the text a reader sees; invisible characters are removed before any agent. Detected hidden text and AI-directed instructions become manipulation markers in the report, without quoting them. | Section 5. The regression tests use a deliberately gullible fake model. |
| D53 | QR codes are decoded with OpenCV 4.14 (`opencv-python-headless`), not the newer 5.0 major release. Image size is checked before decoding. A link found in a QR code is at least medium severity. | Boring, stable library (Rule 6); refuses decompression bombs; a link hidden in a picture is itself a signal. |

### Dependencies

`opencv-python-headless==4.14.0.94` (QR), `dnspython==2.9.0` (optional DNS checks),
`segno==1.6.6` (dev only: generates the QR image in the demo emails).

## Phase 3: mail provider, mail agent, policy modes

### Scope changes agreed by the team (2026-10-22)

| # | Decision |
|---|---|
| D54 | Phase 6 (Gmail banner in the extension) is cut; the extension is unchanged. Phase 7 is reduced to README, DEMO_SCRIPT and BENCHMARK. A teammate builds the frontend pages, so this phase delivers backend routes and `docs/API_CONTRACT.md` only. |
| D55 | In strict mode, `report_phishing` and `quarantine_email` (and the `summarize` warning summary) run automatically with an audit entry and a `notice` on the policy decision; they create no approval. Approvals remain for anything that sends data out or opens links, and, as Addendum A1.4 says, for the other agent steps when the message raised a signal. P1/P2 always apply. |

### Design choices

| # | Decision | Why |
|---|---|---|
| D56 | Gmail and Google OAuth are called with `httpx` directly instead of `google-api-python-client` and `google-auth-oauthlib` (Rule 11). | Async, like the rest of the pipeline; every request explicit (which makes the read-only guarantee testable); the recorded fixtures replay through one mock transport; two fewer heavy dependencies. |
| D57 | The test fixtures in `tests/fixtures/gmail/` are built from the documented Gmail API formats (`scripts/build_gmail_fixtures.py`). They are not captures from a live account; none existed yet. `docs/GMAIL_SETUP.md` lists what to verify against live Gmail. | Honest labelling of test data. |
| D58 | The only scope is `gmail.readonly`, without `include_granted_scopes`. A token granted with any extra scope is refused and revoked at once. A test scans all code for any other Google scope and for the full-access `https://mail.google.com/`. | Read-only by construction, not by convention. |
| D59 | The OAuth callback is public (Google's redirect cannot carry the operator header). It is protected by a single-use, 10-minute `state` created only by an operator-authenticated connect, by PKCE (S256), and by a rate limit. Pending states are kept in memory; a restart cancels unfinished connects. | Standard OAuth protection. |
| D60 | New mail is found with `messages.list` (`labelIds=INBOX`, `q=after:<epoch>`). The cursor is the last sync's start minus 2 minutes, and deduplication is by message id (a unique constraint), so the overlap is safe. The cursor does not move when messages were deferred (per-minute cap) or failed, so none are skipped. The first connect takes the 20 most recent messages; later syncs take at most 50. | Simpler and more robust than `historyId` for a prototype; behaviour is the same for the agent. |
| D61 | Tokens are Fernet-encrypted (`TOKEN_ENCRYPTION_KEY`). An expired or revoked refresh token sets the account to `reconnect_required` and wipes the stored tokens; the poller logs a warning and keeps running. Disconnect revokes at Google and deletes locally even if Google is unreachable. | A2.1. |
| D62 | The mail agent's rules (states, transitions, planner, effects) are pure code in `shield/mail_agent.py`; persistence and execution are in `services/mail_agent.py`. | Keeps `shield/` reusable and testable. |
| D63 | The planner uses only structured verdict fields: label, `reply_requested`, has-headers, attempted actions. On its own it plans only steps whose effect stays inside FactFlow: summary, action items, a stored draft, and the protective flags. Outgoing steps (forward, share, open link, calendar) are planned only when the user asks for them (`POST /api/mail/tasks/{id}/steps`), and they always meet the policy. Actions the message tried to trigger become blocked steps with `requested_by: "message"`. | Clean mail is "handled automatically" (A3.4) without the agent ever deciding on its own to send anything. |
| D64 | A forward to an allowlisted recipient still needs approval: P4 passes, then P8 applies (fail closed). | "Approvals remain for anything that sends data out." |
| D65 | Approvals are created only for agent steps. Analysing a message (`/api/inbox/analyze`) never creates approvals. Without `APPROVAL_SECRET`, steps that need approval are `blocked` with a notice (fail closed). | One source of approvals; no orphan approvals. |
| D66 | Execution commits the effect, the step's status and the task's steps together, then writes the audit entry. The outbox's unique `step_id` means a step reaches it at most once. The executor also refuses any step whose origin is the message, even if a policy bug allowed it. | Atomic and idempotent under retries. SQLite allows one writer at a time, which this order respects. |
| D67 | `GET /api/inbox/{id}` and its stream need the operator token or a view token. The view token is an HMAC of the email id under `SECRET_KEY`, never stored, and given only to whoever submitted the message. Messages from the mail agent have none. | "Protect everything that shows message content." |
| D68 | `llm_status` reports `ok`, `not_used`, `disabled`, `llm_unavailable` or `quota_exhausted`. A daily-quota 429 trips a breaker until the provider's retry time, so later messages go straight to rules-only without waiting. In strict mode the policy reason states why steps paused. A malformed reader answer counts as `llm_unavailable`. | Visible degradation, never silent. |
| D69 | The provider setting `auto` uses Gmail when connected and the demo inbox otherwise, but not when Gmail needs reconnecting: sync then answers 409 instead of quietly reading the demo inbox. | The user must see that Gmail needs attention. |
| D70 | The provider choice, the OAuth states and the policy settings are kept in memory; a restart resets them. | Prototype; audit entries keep the history. |
| D71 | Database tests run on SQLite by default and on PostgreSQL when `FACTFLOW_TEST_DATABASE_URL` points to a disposable database (tables are dropped before each test). A `factflow_test` database was created on the local PostgreSQL 16 for this. | Both supported back-ends tested. |

### Dependencies

`cryptography==50.0.2` (already installed through `google-auth`; now pinned directly) for Fernet.
No Google client libraries (D56).
