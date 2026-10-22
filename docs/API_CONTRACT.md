# FactFlow Shield API contract

For the frontend. Covers every route added for email and message checks and the mail agent, and
the JSON they return. Real output from the pipeline is in `backend/data/sample_verdicts/`; use it
instead of hand-written mocks:

| File | What it is |
|---|---|
| `safe.json`, `suspicious.json`, `dangerous.json` | Verdicts (rules-only mode, so `reader_notes` is null and there are no claims) |
| `task_done.json` | A mail-agent task on a DANGEROUS email: protective steps ran, the attempted forward was blocked |
| `task_awaiting_approval.json` | A task on a SUSPICIOUS email waiting for an approval (strict mode) |

The existing claim routes (`/api/verify`, `/api/stream/{id}`, `/api/result/{id}` ...) are unchanged.
Base URL in development: `http://localhost:8000`. All bodies are JSON (UTF-8).

> **Render everything as text.** Subjects, senders, `visible_text`, `raw_text`, `diff`, hidden
> text, summaries, action items, claims and targets come from the message, which may be an attack.
> Never put them into the DOM as HTML (no `dangerouslySetInnerHTML`). Show them escaped, as React
> does by default.

## What changed in Phase 3

1. **`GET /api/inbox/{id}` and `/stream` are no longer public.** They need either the operator
   token or the `view_token` that `POST /api/inbox/analyze` returns to whoever submitted the
   message. Use the `stream_url` and `result_url` from the analyze response; they already carry
   the view token.
2. **New `/api/mail/*` routes:** Gmail connect, callback and disconnect; mail status; sync; agent
   tasks and steps; the simulated outbox.
3. **Approvals now come only from mail-agent steps.** Analysing a message no longer creates any.
   Deciding an approval resumes the task (`executed`, `step` and `task_state` in the reply).
4. **Strict mode runs `summarize`, `report_phishing` and `quarantine_email` automatically**, with
   a `notice` on the policy decision explaining why, instead of asking for approval.
5. **New verdict fields:** `llm_status` (is the AI part working?), `reader_notes` (summary, action
   items, meeting). Policy decisions gain `notice`. The action list gains `extract_action_items`.
6. **`GET /api/inbox` rows** gain `provider`, `quarantined`, `reported_phishing` and `llm_state`.

## Authentication

Routes marked **operator** need:

```
X-Operator-Token: <OPERATOR_TOKEN from backend/.env>
```

- Ask the operator to type it once, keep it in `sessionStorage`, and send it on every operator
  route. Never put it in the code, in `NEXT_PUBLIC_*` variables, or in `localStorage`.
- `401`: missing or wrong token. `429`: too many wrong tokens from this address (5 a minute by
  default); it is refused even with the right token until the minute passes.
- `503`: the server has no `OPERATOR_TOKEN`, so these routes are closed.
- **Streaming:** the browser's `EventSource` cannot send headers. For operator streams, use
  `fetch()` with a `ReadableStream` reader; for the submitter's own analysis, use the `stream_url`
  with its `view_token`.

The analyse routes are public and rate-limited per address (`MAX_INBOX_PER_MINUTE`, default 10).
Over the limit they answer `429` with a `Retry-After` header.

## Routes

| Method and path | Auth | What it does |
|---|---|---|
| `POST /api/inbox/analyze` | public, rate-limited | Analyse an email or pasted message |
| `GET /api/inbox/demo` | public | List the 14 seeded demo emails |
| `POST /api/inbox/demo/{name}` | public, rate-limited | Analyse one demo email |
| `GET /api/inbox/{email_id}` | view token or **operator** | One analysis and its verdict |
| `GET /api/inbox/{email_id}/stream` | view token or **operator** | Live progress (Server-Sent Events) |
| `GET /api/inbox` | **operator** | List analysed messages |
| `GET /api/mail/status` | **operator** | Active inbox, Gmail connection, AI availability |
| `PUT /api/mail/provider` | **operator** | Choose `auto`, `gmail` (live) or `eml` (demo inbox) |
| `POST /api/mail/gmail/connect` | **operator** | Start Google consent (read-only) |
| `GET /api/mail/gmail/callback` | public (single-use state) | Google redirects here; redirects to the frontend |
| `POST /api/mail/gmail/disconnect` | **operator** | Revoke at Google and delete the token |
| `POST /api/mail/sync` | **operator** | Fetch and process new mail now |
| `POST /api/mail/upload` | **operator** | Hand an .eml or pasted message to the agent |
| `GET /api/mail/tasks` | **operator** | Agent tasks, newest first |
| `GET /api/mail/tasks/{task_id}` | **operator** | One task with all steps and transitions |
| `POST /api/mail/tasks/{task_id}/steps` | **operator** | Ask the agent to do something with a message |
| `GET /api/mail/outbox` | **operator** | The simulated outbox |
| `GET /api/approvals` | **operator** | Approval requests (pending ones include their token) |
| `POST /api/approvals/{id}/decision` | **operator** | Approve once, or deny; resumes the task |
| `GET /api/audit` | **operator** | Audit log, paginated, optionally for one email |
| `GET /api/audit/verify` | **operator** | Recompute the hash chain |
| `GET /api/policy` | public | Current policy mode and trusted domains |
| `PUT /api/policy/mode` | **operator** | Switch strict / balanced |
| `PUT /api/policy/allowed-domains` | **operator** | Replace the trusted recipient domains |

### POST /api/inbox/analyze

Request:

```json
{
  "raw": "string: raw email source (headers + body) or plain pasted text",
  "eml_base64": "string: an .eml file, base64 (use instead of raw for uploads)",
  "source": "paste | upload",
  "language": "auto | en | hi | te | ta | mr | ...",
  "mode": "full | rules",
  "wait": false,
  "force": false
}
```

- Send `raw` or `eml_base64`. A message without headers is treated as a pasted message.
- `language`: language of the explanation and WhatsApp warning. `auto` uses the message's language.
- `mode`: `rules` makes no model calls (about 35-50 ms). `full` also runs the quarantined reader,
  fact-checks claims and writes the explanation. If the server has `INBOX_USE_LLM=false`, `full`
  is downgraded to `rules`; then `verdict.llm_status.state` is `disabled`.
- `wait`: `false` answers at once with `202` and you follow the stream; `true` waits and answers
  `200` with the verdict.
- `force`: the same bytes in the same mode and language are normally answered from the cache
  (`cached: true`, the earlier `email_id`); `true` analyses again.

This route only analyses. It does not start the mail agent, so it never creates approvals. Use
`POST /api/mail/upload` for that.

Response (`202`, or `200` when `wait` is true or the answer is cached):

```json
{
  "email_id": "7d19ea74a2cf4cd6b7895cff35a229cd",
  "status": "processing | complete | failed",
  "mode": "full | rules",
  "cached": false,
  "view_token": "40 hex characters; lets the submitter read this analysis; keep it private",
  "stream_url": "/api/inbox/7d19.../stream?view_token=...",
  "result_url": "/api/inbox/7d19...?view_token=...",
  "verdict": null,
  "error": null
}
```

Errors:

| Status | When |
|---|---|
| `413` | More than 5 MB |
| `422` | No `raw`/`eml_base64`, invalid base64, more than 20 attachments, or (with `wait`) the analysis failed |
| `429` | Rate limit |

### GET /api/inbox/demo, POST /api/inbox/demo/{name}

`GET` answers `{"items": [{"name": "04_white_on_white_injection", "subject": "...", "from_addr": "..."}]}`.
`POST` takes `language`, `mode`, `wait` and `force` (the body may be empty) and answers like analyze,
with `source` set to `demo`. `404` for an unknown name.

| name | rules-only label |
|---|---|
| `01_benign_newsletter`, `02_benign_meeting_invite`, `03_benign_bank_alert` | SAFE |
| `13_quishing_qr` | SUSPICIOUS |
| `04`-`12`, `14` | DANGEROUS |

### GET /api/inbox/{email_id} (view token or operator)

Query `view_token=...`, or the `X-Operator-Token` header.

```json
{"email_id": "...", "status": "processing | complete | failed", "mode": "full | rules",
 "created_at": "ISO 8601", "completed_at": "ISO 8601 or null", "verdict": {...} | null, "error": "string or null"}
```

Answers `202` while processing, `200` when finished, `401` without a valid view token or operator
token, and `404` for an unknown id. Messages fetched by the mail agent (Gmail, demo inbox) have no
view token: only the operator can read them.

### GET /api/inbox/{email_id}/stream (view token or operator)

Server-Sent Events in the same format as the existing `/api/stream/{request_id}`, so the existing
`AgentProgress` component can render them:

| `event:` | `data` |
|---|---|
| `start` | `{"type": "start", "request_id", "input_type": "email", "agents": [stage, ...]}` |
| `agent` | `{"type": "agent", "agent": index, "index", "name", "tier", "role", "status", "preview", "model", "ms", "progress", "elapsed_ms"}` |
| `result` | `{"type": "result", "progress": 100, "result": <verdict>}` |
| `error` | `{"type": "error", "message": "..."}` |

`status` is `waiting | running | complete | skipped | failed`. `tier` is `RULES` (deterministic) or
`NANO` (model). The stages:

| index | name | tier |
|---|---|---|
| 0 | INTAKE & TRIAGE | RULES |
| 1 | HIDDEN CONTENT | RULES |
| 2 | SENDER & LINKS | RULES |
| 3 | QUARANTINED READER | NANO |
| 4 | FACT CHECK | NANO |
| 5 | HARM & POLICY | RULES |
| 6 | EXPLAINER | NANO |

In rules mode stages 3, 4 and 6 are `skipped`. When the AI part is unavailable they show `skipped`
or `failed` with the reason in `preview`. A finished analysis is replayed when you connect late.

### GET /api/inbox (operator)

Query: `limit` (1-100, default 30), `offset`, `label` (`SAFE | SUSPICIOUS | DANGEROUS`), `source`
(`paste | upload | demo | gmail`).

```json
{"total": 42, "items": [{"email_id": "...", "created_at": "...", "source": "gmail", "status": "complete", "mode": "full",
  "subject": "...", "from_addr": "...", "label": "DANGEROUS", "score": 95, "top_reason": "hidden content scored 85",
  "provider": "gmail", "quarantined": true, "reported_phishing": true, "llm_state": "ok"}]}
```

`quarantined` and `reported_phishing` are FactFlow-only flags; the real mailbox is never changed.

## Mail provider and agent (operator)

### GET /api/mail/status

```json
{"active_provider": "gmail | eml", "provider_setting": "auto | gmail | eml",
 "gmail": {"provider": "gmail", "configured": true, "status": "connected | reconnect_required | disconnected",
           "email_address": "test-inbox@gmail.com", "connected_at": "...", "last_sync_at": "...",
           "last_error": null, "reconnect_required": false,
           "scope": "https://www.googleapis.com/auth/gmail.readonly"},
 "demo_inbox": {"messages": 14}, "poll_seconds": 45, "poll_enabled": true,
 "llm": {"state": "ok | quota_exhausted | disabled", "retry_after_seconds": null}}
```

- `configured: false`: the server lacks Google settings or `TOKEN_ENCRYPTION_KEY`, so hide the
  Connect button or explain why.
- `reconnect_required: true`: show a **Reconnect Gmail** button. Testing-mode refresh tokens
  expire after about a week.
- No token ever appears in any response.

### PUT /api/mail/provider

`{"provider": "auto" | "gmail" | "eml"}`. With `auto`, the agent reads Gmail when it is connected
and the demo inbox otherwise. If Gmail needs reconnecting, `auto` does **not** fall back
silently: sync answers `409`. Use this for the "Live Gmail / Demo inbox" switch. Answers like
`GET /api/mail/status`.

### Gmail connect, callback, disconnect

- `POST /api/mail/gmail/connect` answers
  `{"auth_url": "https://accounts.google.com/...", "scope": "...gmail.readonly", "expires_in": 600, "warning": "Connect only a throwaway test Gmail account..."}`.
  Show the warning, then send the browser to `auth_url`. Answers `503` with the missing settings
  when Gmail is not set up.
- `GET /api/mail/gmail/callback` is where Google sends the browser back. It redirects to
  `{FRONTEND_URL}/inbox?gmail=connected`, or `?gmail=error&reason=denied | scope_not_allowed | auth_failed | not_configured | google_unreachable | missing_code`.
  The inbox page should read these query parameters and show a message.
- `POST /api/mail/gmail/disconnect` answers `{"revoked": true, ...status fields}`. `revoked: false`
  means Google could not be reached, but the token was still deleted here.

### POST /api/mail/sync

Body (optional) `{"mode": "full" | "rules"}`. Processes new mail from the active inbox now.

```json
{"provider": "gmail", "listed": 20, "new_tasks": ["task id", "..."], "duplicates": 0, "deferred": 0,
 "failed": 0, "errors": [], "reconnect_required": false}
```

On the first Gmail connect at most the 20 most recent messages are taken, then at most 50 per sync.
`deferred` messages hit the per-minute cap and are picked up next time. The answer is `409` when
Gmail is the active provider but is not connected or needs reconnecting. The server also polls
Gmail every `poll_seconds`.

### POST /api/mail/upload

Same body as analyze (`raw` or `eml_base64`, `mode`). Hands the message to the agent (demo inbox
provider) and answers with the task (below). `409` if this exact message was already handed over.

### Tasks

`GET /api/mail/tasks?limit=30&offset=0&state=AWAITING_APPROVAL` answers
`{"total": 20, "items": [task summary]}`; there, `steps` is shortened to
`{task, status, decision}`.

`GET /api/mail/tasks/{task_id}` answers the full task:

```json
{"task_id": "…", "provider": "gmail | eml", "message_id": "…", "email_id": "…",
 "state": "FETCHED | PARSED | SCANNED | PLANNED | POLICY_CHECKED | EXECUTED | AWAITING_APPROVAL | BLOCKED | DONE | FAILED",
 "policy_mode": "strict | balanced", "error": null, "created_at": "…", "updated_at": "…",
 "subject": "…", "from_addr": "…", "label": "DANGEROUS", "score": 95, "quarantined": true, "reported_phishing": true,
 "steps": [Step, ...], "transitions": [{"state": "FETCHED", "at": "ISO 8601"}, ...]}
```

```ts
interface Step {
  id: string;
  task: "summarize" | "extract_action_items" | "draft_reply" | "propose_calendar_event" | "propose_forward"
      | "propose_share_data" | "propose_open_link" | "report_phishing" | "quarantine_email" | "follow_message_instructions";
  action: Action;              // the policy action it maps to
  target: string | null;       // recipient or URL
  origin: "user" | "untrusted_content";
  requested_by: "agent" | "user" | "message";   // "message" = the email itself tried to make an AI do this
  status: "planned" | "executed" | "awaiting_approval" | "denied" | "expired" | "blocked" | "failed";
  policy: PolicyDecision | null;
  approval_id: string | null;  // set while it waits for a person
  notice: string | null;       // e.g. strict mode ran this automatically
  result: object;              // see below
  created_at: string;
}
```

`result` by task:

| task | result |
|---|---|
| `summarize` | `{summary, verdict, score, why}` |
| `extract_action_items` | `{items: [{task, due, amount}], meeting: {title, when, where} or null, note}` |
| `draft_reply` | `{draft, stored_in}`: the draft stays inside FactFlow |
| `report_phishing`, `quarantine_email` | `{flag, where}` |
| `propose_*` (after approval) | `{outbox_id, simulated: true, note}` |

What the agent plans by itself (from structured verdict fields only):

- **Always:** `summarize`.
- **DANGEROUS:** `report_phishing` and `quarantine_email`. These run automatically, with a notice
  in strict mode.
- **Otherwise:** `extract_action_items`, plus `draft_reply` if the message has headers and asks for
  a reply.
- **Every action the message itself tried to trigger** becomes a step with
  `requested_by: "message"`. It is always `blocked`. Show it as "this email tried to make an AI
  …".

A SAFE message with no signals is handled automatically (`DONE`). In strict mode any signal parks
the non-protective steps for approval (`AWAITING_APPROVAL`).

### POST /api/mail/tasks/{task_id}/steps

`{"task": "propose_forward" | "propose_share_data" | "propose_open_link" | "propose_calendar_event" | "draft_reply" | "extract_action_items" | "report_phishing" | "quarantine_email", "target": "friend@example.com"}`.
The user asks the agent to do something with a message, for example forward it.

- `target` is required for forward, share and open-link, and counts as typed by the user.
- The step is policy-checked: anything that sends data out or opens a link waits for approval (or
  is blocked, e.g. forwarding a DANGEROUS email is blocked by P3). Once approved, it is written to
  the simulated outbox only.
- Answers with the full task. `409` if the task is not `DONE` yet; `422` for a missing target.

### GET /api/mail/outbox

```json
{"simulated": true, "items": [{"id": 1, "created_at": "…", "task_id": "…", "step_id": "…", "email_id": "…",
  "kind": "forward | share_data | open_link | calendar_event", "target": "…", "subject": "…",
  "body_preview": "…", "approved_by": "operator", "simulated": true}]}
```

Nothing in FactFlow sends real mail, opens links or changes the mailbox. This table is the only
effect of an approved outgoing step.

## Approvals (operator)

`GET /api/approvals?status=pending&limit=100`:

```json
{"enabled": true, "items": [{
  "id": "…", "email_id": "…", "action": "forward_email", "target": "friend@example.com", "origin": "user",
  "rule_id": "P4", "reason": "The recipient (…) is not on your list of trusted addresses.",
  "evidence": {"task": "propose_forward", "label": "SAFE", "llm_state": "ok", "hidden_text": ["…"], "attempted_actions": [...]},
  "status": "pending", "created_at": "…", "expires_at": "…", "decided_by": null, "decided_at": null,
  "token": "64 hex characters (pending only)"}]}
```

`enabled: false` means the server has no `APPROVAL_SECRET`. Steps that would need approval are then
`blocked`, with a notice saying why.

`POST /api/approvals/{id}/decision` with `{"decision": "approve" | "deny", "token": "<token from the list>"}`:

```json
{"approval": {...same fields, status "approved" or "denied"...},
 "executed": true, "step": {Step}, "task_state": "DONE",
 "note": "Nothing leaves FactFlow: approved outgoing steps are written to the simulated outbox only."}
```

| Status | When |
|---|---|
| `403` | Wrong token, or the action or target is not the one approved |
| `404` | Unknown approval |
| `409` | Already decided (a token works once) |
| `410` | Expired (10 minutes); the step is then `expired` and the task moves on |
| `503` | No `APPROVAL_SECRET` |

UI rules from the brief: **Deny** is the default and visually primary button, **Approve once** is
secondary, and there is no "always allow". `evidence.task` says which agent step is waiting.

## Audit (operator)

`GET /api/audit?offset=0&limit=50&email_id=<optional>`:

```json
{"total": 120, "items": [{"seq": 1, "ts": "2026-10-22T13:57:01.123456Z", "actor": "agent:mail",
  "event_type": "task_state", "payload": {...redacted...}, "prev_hash": "64 hex", "hash": "64 hex"}]}
```

Event types: `email_received`, `scan_summary`, `policy_decision`, `verdict`, `task_state`
(every agent transition), `step_executed`, `step_denied`, `step_expired`, `approval_created`,
`approval_decided`, `approval_refused`, `policy_changed`, `mail_connected`, `mail_disconnected`,
`mail_provider_changed`.

`GET /api/audit/verify` answers
`{"ok": true, "checked": 120, "first_broken_seq": null, "reason": "", "head_hash": "…"}`. When the
log was changed: `ok: false`, `first_broken_seq: N`. Show "Chain intact" or "TAMPERED at #N".

## Policy

`GET /api/policy` answers
`{"mode": "strict", "allowed_domains": [], "approval_ttl_seconds": 600, "approvals_enabled": true}`.

`PUT /api/policy/mode` takes `{"mode": "strict" | "balanced", "confirm": false}`.
`PUT /api/policy/allowed-domains` takes `{"domains": ["partner.example"], "confirm": false}`.

- Both are **operator** routes and answer like `GET /api/policy`.
- Loosening (switching to `balanced`, or adding a domain) needs `confirm: true`; without it the
  answer is `409` with the reason. Use that to show a confirmation dialog.
- An invalid domain answers `422`.
- Every change is in the audit log. Changes are kept in memory; a restart goes back to
  `shield/config/policy.yml`.

## The verdict object

TypeScript-style types. Fields marked *FactFlow* are additions to the brief's schema.

```ts
type Severity = "low" | "medium" | "high" | "critical";
type Action = "summarize" | "extract_action_items" | "draft_reply" | "send_reply" | "forward_email" | "share_data"
  | "open_link" | "download_attachment" | "add_calendar_event" | "delete_email" | "report_phishing" | "quarantine_email"
  | "execute_instruction_from_content";

interface PolicyDecision { decision: "ALLOW" | "REQUIRE_APPROVAL" | "BLOCK"; rule_id: string; reason: string;
                           notice: string | null /* FactFlow: e.g. "Strict mode: ... ran automatically" */ }

interface Verdict {
  email_id: string;
  overall: { label: "SAFE" | "SUSPICIOUS" | "DANGEROUS"; score: number /* 0-100 */; confidence: number /* 0-1 */;
             reasons: string[] /* why the score is what it is; show them */ };
  components: {
    hidden_content: { score: number; findings: HiddenFinding[] };
    injection: { score: number; rule_hits: RuleHit[]; llm: LlmInjection | null; attempted_actions: AttemptedAction[] };
    authenticity: { score: number; spf: Auth; dkim: Auth; dmarc: Auth; reply_to_mismatch: boolean;
                    return_path_mismatch: boolean; display_name_impersonation: string | null;
                    lookalikes: Lookalike[]; signals: string[] /* plain-language sender findings */ };
    links: { score: number; items: LinkItem[] };
    scam: { score: number; detectors: ScamHit[] };
    claims: { score: number; items: ClaimItem[] };   // empty in rules mode
  };
  visible_vs_raw: { visible_text: string; raw_text: string; diff: { text: string; hc_id: string }[] };
  proposed_actions: { action: Action; target: string | null; origin: "user" | "untrusted_content"; policy: PolicyDecision }[];
  explanation: { en: string; user_language: string; text: string /* in user_language */; whatsapp_warning: string };
  analysis_failures: string[];             // anything here raised the score; never hide it
  latency_ms: { total: number; per_stage: Record<string, number> /* ms, one decimal */ };
  audit_head_hash: string | null;
  mode: "rules" | "full";                  // FactFlow
  pipeline_version: string;                // FactFlow
  input_type: "claim" | "email" | "phishing_or_scam" | "injection_attempt" | "qr" | "voice_note"; // FactFlow
  message: { source: string; has_headers: boolean; subject: string; from_addr: string; from_display: string;
             reply_to: string; to: string[]; date: string;
             attachments: { filename: string; content_type: string; size: number; sha256: string; inline: boolean;
                            text_extracted: boolean; scan_note: string | null }[] } | null;   // FactFlow
  harm: { types: ("FINANCIAL_FRAUD" | "CREDENTIAL_THEFT" | "DATA_EXFILTRATION" | "MISINFORMATION" | "IMPERSONATION")[];
          level: "NONE" | "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"; reasons: string[] };       // FactFlow
  llm_usage: { llm_calls: number; prompt_tokens: number; completion_tokens: number; total_tokens: number;
               by_stage: Record<string, number>; claims_from_registry: number } | null;      // FactFlow; null in rules mode
  llm_status: { state: "ok" | "not_used" | "disabled" | "llm_unavailable" | "quota_exhausted";
                reason: string | null; retry_after_seconds: number | null };                 // FactFlow
  reader_notes: { summary: string; action_items: { task: string; due: string | null; amount: string | null }[];
                  reply_requested: boolean; meeting: { title: string; when: string; where: string | null } | null
                } | null;                                                                     // FactFlow; null in rules mode
}

type Auth = "pass" | "fail" | "softfail" | "none" | "unknown";   // unknown = no headers / not reported

interface HiddenFinding {
  id: "HC-01" | "HC-02" | "HC-03" | "HC-04" | "HC-05" | "HC-06" | "HC-07" | "HC-08" | "HC-09" | "HC-10" | "HC-11" | "HC-12";
  type: string; severity: Severity;
  location: string;          // CSS path, attribute or part, e.g. "body > div:nth-of-type(2)" or "img @alt"
  hidden_text: string;       // max 300 chars; control characters shown as \uXXXX
  explanation_en: string;    // one plain sentence, use it as the tooltip
  instruction_like: boolean; // the hidden text tries to instruct an AI
}
interface RuleHit { id: string; category: string; severity: Severity; evidence: string; location: string }
interface LlmInjection { is_injection: boolean; confidence: number; categories: string[]; quoted_evidence: string[];
                         attempted_actions: AttemptedAction[] }
interface AttemptedAction { action: Action; target: string | null }   // what the message tried to make an AI do; never executed
interface Lookalike { domain: string; brand: string; legit_domain: string | null; reason: string; severity: Severity }
interface LinkItem { url: string; host: string | null; flags: string[]; severity: Severity | null; expanded_to: string | null }
interface ScamHit { id: string /* SC-01..SC-13, SC-LLM */; name: string; matched_evidence: string[]; severity: Severity }
interface ClaimItem { claim: string; autopsy_id: string | null; verdict: "TRUE" | "FALSE" | "MISLEADING" | "UNVERIFIED";
                      credibility: number /* 0-100 */; hidden: boolean /* the claim was in hidden text */ }
```

Notes for the UI:

- **`llm_status`: show it whenever `state` is not `ok`.**
  - `quota_exhausted` and `llm_unavailable` mean the result is **rules-only**: say so, and show
    `reason`. When `retry_after_seconds` is set, the AI part comes back after about that long.
  - `not_used`: the user asked for rules-only.
  - `disabled`: the server runs rules-only.
  - In strict mode, these states also pause agent steps, and the step's `policy.reason` says why.
- **"What you see vs what the AI reads":** show `visible_text` and `raw_text` side by side and
  highlight each `diff[i].text` inside `raw_text` in red, labelled with `hc_id`. Use the matching
  finding's `explanation_en` (same `id`) as the tooltip.
- **Link flags** you will see: `from_qr_code`, `lookalike_domain`, `ip_address_host`,
  `at_sign_in_url`, `script_or_data_uri`, `punycode`, `non_standard_port`, `obfuscated`,
  `many_subdomains`, `shortener_not_expanded`, `very_long_url`, `no_https`, `unparseable`. Links
  are never fetched unless the server enables `ENABLE_LINK_EXPANSION`; then `expanded_to` says
  where a shortened link goes.
- **Claims:** `autopsy_id` is the request id of the existing fact-check. Its Truth Autopsy Report
  is `GET /api/result/{autopsy_id}`. These claims are private: there is no public `/v/{slug}`
  page.
- **`proposed_actions`** is the policy's view of the message. Rows with
  `origin: untrusted_content` are attempts the message made, and they are always `BLOCK`. Actual
  agent work is in the mail tasks.
- `explanation.whatsapp_warning` is ready to copy. It never contains links (they are removed).
