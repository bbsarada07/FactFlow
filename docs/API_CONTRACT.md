# FactFlow Shield API contract

For the frontend. Covers every route added for email and message checks and the mail agent, and
the JSON they return. Real output from the pipeline is in `backend/data/sample_verdicts/`; use it
instead of hand-written mocks:

| File | What it is |
|---|---|
| `safe.json`, `suspicious.json`, `dangerous.json` | Verdicts (rules-only mode, so `reader_notes` is null and there are no claims) |
| `task_done.json` | A mail-agent task on a DANGEROUS email: protective steps ran, the attempted forward was blocked |
| `task_awaiting_approval.json` | A task on a SUSPICIOUS email waiting for an approval (strict mode) |

The claim (Truth) routes and the other public routes are listed at the end, in "Claim pipeline and public
routes". Every route the backend serves (`GET /openapi.json`) is documented in this file.
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
| `DELETE /api/mail/outbox`, `POST /api/mail/outbox/clear` | **operator** | Empty the simulated outbox |
| `GET /api/approvals` | **operator** | Approval requests (pending ones include their token) |
| `POST /api/approvals/{id}/decision` | **operator** | Approve once, or deny; resumes the task |
| `GET /api/audit` | **operator** | Audit log, paginated, optionally for one email |
| `GET /api/audit/verify` | **operator** | Recompute the hash chain |
| `GET /api/policy` | public | Current policy mode and trusted domains |
| `PUT /api/policy/mode` | **operator** | Switch strict / balanced |
| `PUT /api/policy/allowed-domains` | **operator** | Replace the trusted recipient domains |
| `POST /api/sandbox/run`, `GET`/`DELETE /api/sandbox/outbox`, `POST /api/sandbox/outbox/clear` | **operator** | Sandbox assistant (section below) |
| `POST /api/benchmark/run`, `GET /api/benchmark/runs`, `/latest`, `/runs/{run_id}` | **operator** | Red-team benchmark (section below) |
| `POST /api/whatsapp/webhook` | provider signature | WhatsApp checks (section below) |
| claim routes, `/api/registry`, `/api/v/{slug}`, `/api/config`, `/health` ... | public | See "Claim pipeline and public routes" |

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
(`paste | upload | demo | gmail | whatsapp | sandbox | benchmark`). For `whatsapp` rows the stored verdict has the
message text and every excerpt of it removed, and `subject` / `from_addr` are empty.

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

### DELETE /api/mail/outbox (or POST /api/mail/outbox/clear)

**Operator.** Empties the simulated outbox (the same table the sandbox uses) and writes an `outbox_cleared` audit
entry. Answers `{"simulated": true, "cleared": <rows removed>}`. Not rate-limited (the sandbox route of the same
name is).

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
  proposed_actions: { action: Action; target: string | null; origin: "user" | "untrusted_content"; policy: PolicyDecision | null }[];
  explanation: { en: string /* English rules summary, always set */; user_language: string /* language of `text` */;
                 text: string; whatsapp_warning: string /* empty unless the AI explainer ran */ };
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
- **Explanation language:** `explanation.user_language` names the language `explanation.text` is really in. In
  rules-only mode, when the quota is used up, or when the explainer fails, `text` is the English rules summary and
  `user_language` is `"en"`, even if another language was requested. Offer a language label or selector only for
  `user_language`; do not assume the requested language was delivered.


## Sandbox Email Assistant (operator)

### POST /api/sandbox/run

Run simulated email assistant on an email with `shield=on` (protected by quarantine, policy and approvals) or `shield=off` (intentionally vulnerable baseline).

- **Headers:** `X-Operator-Token`
- **Request Body:**
  ```json
  {
    "raw": "optional raw RFC 822 or pasted text",
    "eml_base64": "optional base64-encoded .eml",
    "email_id": "optional id of an analysed email to link the run to (only together with raw or eml_base64)",
    "shield": "on" | "off" | true | false,
    "mode": "full" | "rules"
  }
  ```
- **Constraints & Behavior:**
  - Send `raw` or `eml_base64`. Raw messages are not stored, so `email_id` alone is refused with 422; an unknown
    `email_id` gives 404. Rate limit: 30 runs per minute per client (429 with `Retry-After`).
  - `shield=off` requires server env `ALLOW_VULNERABLE_DEMO=true`. Returns 403 Forbidden if disabled.
  - In `shield=off`, feeds raw email directly to the LLM with tool access to `simulated_outbox`. If LLM is unavailable, returns `"status": "unavailable", "detail": "unavailable, nothing executed"` and never a fake attack success.
  - In `shield=on`, runs through the real quarantine, policy and approval pipeline.
  - Every response is labelled `"simulated": true`.
- **Response** (shape only; the values are placeholders, not measurements):
  ```json
  {
    "simulated": true,
    "shield": "off" | "on",
    "status": "complete" | "unavailable" | "failed",
    "executed": false,
    "summary": "...",
    "draft_reply": "...",
    "tool_calls": [],
    "outbox_entries": [],
    "verdict": { ... },
    "steps": [ ... ],
    "latency_ms": 120
  }
  ```

### GET /api/sandbox/outbox

- **Headers:** `X-Operator-Token`
- **Query:** `limit=50`, `offset=0`
- Rate limit, shared with the clear route: 60 requests per minute per client (429 with `Retry-After`).
- **Response** (shape only; the values are placeholders):
  ```json
  {
    "simulated": true,
    "count": 2,
    "items": [
      {
        "id": 1,
        "task_id": "sandbox-...",
        "step_id": "step-...",
        "kind": "forward",
        "target": "archive@...",
        "subject": "...",
        "body_preview": "...",
        "approved_by": "policy:allowed",
        "simulated": true
      }
    ]
  }
  ```

### DELETE /api/sandbox/outbox (or POST /api/sandbox/outbox/clear)

- **Headers:** `X-Operator-Token`
- Clears all entries from `simulated_outbox` and appends an audit event. Same rate limit as the list route.
- **Response:** `{"simulated": true, "cleared": 2}`


## Red-Team Benchmark (operator)

### POST /api/benchmark/run

Run the real red-team benchmark over `backend/data/benchmark/` cases. Only one run can execute at a time (409 otherwise).

- `mode` defaults to `rules` (no model calls). `llm` runs a 10-case sample spread over the manifest unless
  `sample_size` is given; an explicit `sample_size` is also spread over the manifest (attacks and benign cases).
- `mode` in the response is the mode that **really ran**: a request for `llm` while the server has
  `INBOX_USE_LLM=false` comes back as `"mode": "rules"` with `"requested_mode": "llm"`.
- A case for which the pipeline produced no verdict is listed in `failed_cases` (with `actual_label: null`), counted in
  `summary.errors`, and excluded from the rates.

- **Headers:** `X-Operator-Token`
- **Request Body:**
  ```json
  {
    "mode": "rules" | "llm",
    "sample_size": 20
  }
  ```
- **Response.** The values below are from the rules-only run `31376138137544938f198afc1c9aaaed`, saved in
  `docs/benchmark_runs/` (see docs/BENCHMARK.md). Latency is machine-dependent.
  ```json
  {
    "id": "31376138137544938f198afc1c9aaaed",
    "mode": "rules",
    "requested_mode": "rules",
    "status": "complete",
    "dataset_size": 89,
    "attack_count": 54,
    "benign_count": 35,
    "detection_rate": 94.44,
    "false_positive_rate": 85.71,
    "policy_block_rate": 100.0,
    "per_category": { ... },
    "confusion_matrix": { "TP": 51, "FP": 30, "TN": 5, "FN": 3 },
    "latency_p50_ms": 34.3,
    "latency_p95_ms": 43.5,
    "token_usage": {},
    "failed_cases": [ ... ],
    "summary": {
      "errors": 0,
      "requested_mode": "rules",
      "llm_states": { "not_used": 89 },
      "attack_flagged_by_label": { "SUSPICIOUS": 2, "DANGEROUS": 49 },
      "benign_flagged_by_label": { "SUSPICIOUS": 23, "DANGEROUS": 7 },
      "...": "..."
    }
  }
  ```

### GET /api/benchmark/runs

List historical benchmark runs.

- **Headers:** `X-Operator-Token`
- **Query:** `limit=20`, `offset=0`
- **Response:** `{"count": 1, "runs": [ ... ]}`

### GET /api/benchmark/latest

Fetch the most recent completed benchmark run.

- **Headers:** `X-Operator-Token`
- **Response:** Full benchmark run object.

### GET /api/benchmark/runs/{run_id}

Fetch a specific benchmark run by ID.

- **Headers:** `X-Operator-Token`
- **Response:** Full benchmark run object.


## WhatsApp (Phase 5)

Setup: docs/WHATSAPP_SETUP.md. There are no operator routes; checks appear in `GET /api/inbox?source=whatsapp`.

### POST /api/whatsapp/webhook (called by Twilio or Meta, not by the UI)

- **Twilio** (default): `application/x-www-form-urlencoded` webhook fields, header `X-Twilio-Signature`. The signature
  is checked over `PUBLIC_BASE_URL` + `/api/whatsapp/webhook` (+ query) and all form fields.
- **Meta** (`WHATSAPP_PROVIDER=meta`): JSON body, header `X-Hub-Signature-256` (`sha256=` + HMAC-SHA256 of the raw
  body with `META_APP_SECRET`).
- Responses:
  - `200` Twilio: empty TwiML `<Response></Response>` (the reply is sent separately through the REST API).
    Meta: `{"received": <number of messages>}`.
  - `403` missing or invalid signature (nothing is processed).
  - `413` body over 64 KB.
  - `503` WhatsApp is not configured (missing `TWILIO_AUTH_TOKEN` / `PUBLIC_BASE_URL` / `META_APP_SECRET`, or
    `WHATSAPP_HASH_SALT` shorter than 16 characters). The log names the missing settings.
- After a `200`, the message is checked in the background and one reply goes to the sender (at most 900
  characters). Without `TWILIO_ACCOUNT_SID` / `TWILIO_WHATSAPP_FROM` (and always for Meta), the reply is recorded in
  the audit log as `whatsapp_reply` with `delivery: "dry_run"` and is not sent.

### Audit events (actor `whatsapp:<first 12 hex of the salted number hash>`)

| event_type | payload |
|---|---|
| `whatsapp_received` | `message_id`, `chars`, `media` (content type or null) |
| `whatsapp_reply` | `delivery` (`sent` / `dry_run` / `failed`), `chars`, `language`; `reply` and `note` for a dry run; `provider_message_id` when sent |
| `whatsapp_opt_out` / `whatsapp_opt_in` | (empty) |
| `whatsapp_ignored` | `reason` (opted out) |
| `whatsapp_rate_limited` | `limit_per_hour` |

The analysis itself uses the normal inbox audit events (`email_received`, `scan_summary`, `policy_decision`,
`verdict`) with `source: "whatsapp"`.

### Stored row: `whatsapp_checks`

`id`, `created_at`, `sender` (`whatsapp:<hash prefix>`), `input_type` (`text | image | voice | unsupported |
too_large | command`), `language` (`en | hi | te`), `label`, `score`, `llm_state`, `email_id` (the `emails` row with
`source=whatsapp`), `reply_chars`, `delivery`. No phone number and no message text.


## Claim pipeline and public routes

These are the Truth (claim-checking) routes and other public routes. All are public; `POST /api/verify` is
rate-limited per client (`MAX_REQUESTS_PER_MINUTE`).

| Method and path | What it does |
|---|---|
| `POST /api/verify` | Queue a claim check. Body: one of `text` (up to `MAX_CLAIM_CHARS`), `url`, `image_base64` (PNG/JPG data URL) or `image_url`; plus `language` (default `auto`), `platform`, `visibility` (`public` / `private`). Answers `202` with `{request_id, slug, status, mode, cached, matched_slug, matched_at, match_score, registry_url, stream_url, result_url, message}`. `message` is set when a claim is withheld under the private-person / self-harm rule. A claim seen within `REPEAT_WINDOW_DAYS` is answered from the registry (`cached: true`). |
| `GET /api/stream/{request_id}` | Server-Sent Events: `start`, `agent`, `result`, `error` |
| `GET /api/result/{request_id}` | The full Truth Autopsy Report (`200`), or `202 {status}` while it runs; `404` for an unknown id |
| `GET /api/status/{request_id}` | `{request_id, status, progress (0-100), verdict, error, agents}`; `404` for an unknown id |
| `GET /api/history?limit=20&offset=0` | `{total, items}`: recent completed checks (claim summaries) |
| `GET /api/registry?q=&limit=20` | Public verdicts. Empty `q` lists the latest; otherwise a fuzzy search, and each item has `match_score`. Answers `{query, items}` |
| `GET /api/v/{slug}?track=true` | One public verdict record for its share page, with `urgency`, `processing_ms`, `processing_time_seconds` and `versions` (other checks of the same claim). It counts a view unless `track=false`. `404` if the slug is not public |
| `GET /api/incidents` | `{items}`: the documented incidents, each with `latest_run` |
| `GET /api/stats` | `{total_claims, live_claims, claims_today, false_or_misleading_pct, critical_threats, avg_seconds, ultra_rate_pct, verdict_breakdown, harm_categories}` |
| `GET /api/accuracy` | The last complete 30-claim bench run: `{complete: true, run_at, models, counts, rows, known_failures}`, or `{complete: false, message}` when there is none (the case today) |
| `GET /api/config` | `{provider, models: {nano, ultra}, vision, evidence_sources, frontend_url, max_claim_chars, repeat_window_days}`. `vision` is null without a Gemini key. Known gap: `evidence_sources` does not list GDELT even when it is used |
| `GET /health` | `{status, build_commit, database, database_ok, redis, llm_configured, keys_configured, reasoning_provider, vision_provider, models, queue, evidence_sources}`. `keys_configured` holds true/false flags only, never key values |
