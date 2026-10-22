# FactFlow Shield API contract

For the frontend. Covers every route added for email and message checks, and the verdict JSON they
return. Real verdicts from the pipeline are in `backend/data/sample_verdicts/` (`safe.json`,
`suspicious.json`, `dangerous.json`); use those instead of hand-written mocks. The existing claim
routes (`/api/verify`, `/api/stream/{id}`, `/api/result/{id}` ...) are unchanged.

Base URL in development: `http://localhost:8000`. All bodies are JSON (UTF-8).

> **Render everything as text.** Subjects, senders, `visible_text`, `raw_text`, `diff`, hidden
> text, claims and targets come from the message, which may be an attack. Never put them into the
> DOM as HTML (no `dangerouslySetInnerHTML`). Show them escaped, as React does by default.

## Authentication

Some routes need the operator token in a header:

```
X-Operator-Token: <OPERATOR_TOKEN from backend/.env>
```

- Ask the operator to type it once, keep it in `sessionStorage`, and send it on the routes marked
  **operator** below. Never put it in the code, in `NEXT_PUBLIC_*` variables, or in `localStorage`.
- `401`: missing or wrong token. `429`: too many wrong tokens from this address (5 a minute by
  default); it is refused even with the right token until the minute passes.
- `503`: the server has no `OPERATOR_TOKEN` configured, so these routes are closed.

Routes not marked **operator** are public. The analyse routes are rate-limited per address
(`MAX_INBOX_PER_MINUTE`, default 10); over the limit they answer `429` with a `Retry-After` header.

## Routes

| Method and path | Auth | What it does |
|---|---|---|
| `POST /api/inbox/analyze` | public, rate-limited | Analyse an email or pasted message |
| `GET /api/inbox/demo` | public | List the 14 seeded demo emails |
| `POST /api/inbox/demo/{name}` | public, rate-limited | Analyse one demo email |
| `GET /api/inbox/{email_id}` | public (id is unguessable) | One analysis and its verdict |
| `GET /api/inbox/{email_id}/stream` | public (id is unguessable) | Live progress (Server-Sent Events) |
| `GET /api/inbox` | **operator** | List analysed messages |
| `GET /api/approvals` | **operator** | List approval requests (pending ones include their token) |
| `POST /api/approvals/{id}/decision` | **operator** | Approve once, or deny |
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
- `mode`: `rules` makes no model calls (fast, about 50 ms). `full` also runs the quarantined reader,
  fact-checks claims and writes the explanation (tens of seconds). If the server has
  `INBOX_USE_LLM=false`, `full` is downgraded to `rules`; check `mode` in the reply.
- `wait`: `false` answers at once with `202` and you follow the stream; `true` waits and answers
  `200` with the verdict.
- `force`: the same bytes in the same mode and language are normally answered from the cache
  (`cached: true`, the earlier `email_id`); `true` analyses again.

Response (`202`, or `200` when `wait` is true or the answer is cached):

```json
{
  "email_id": "7d19ea74a2cf4cd6b7895cff35a229cd",
  "status": "processing | complete | failed",
  "mode": "full | rules",
  "cached": false,
  "stream_url": "/api/inbox/7d19.../stream",
  "result_url": "/api/inbox/7d19...",
  "verdict": null,
  "error": null
}
```

`verdict` is the full verdict object (below) when `status` is `complete`.

Errors:

| Status | When |
|---|---|
| `413` | More than 5 MB |
| `422` | No `raw`/`eml_base64`, invalid base64, more than 20 attachments, or (with `wait`) the analysis failed |
| `429` | Rate limit |

### GET /api/inbox/demo, POST /api/inbox/demo/{name}

`GET` answers `{"items": [{"name": "04_white_on_white_injection", "subject": "...", "from_addr": "..."}]}`.
`POST` takes the same options as analyze except the message itself (`language`, `mode`, `wait`,
`force`; the body may be empty) and answers like analyze, with `source` set to `demo`. `404` for an
unknown name.

| name | rules-only label |
|---|---|
| `01_benign_newsletter`, `02_benign_meeting_invite`, `03_benign_bank_alert` | SAFE |
| `13_quishing_qr` | SUSPICIOUS |
| `04`-`12`, `14` | DANGEROUS |

### GET /api/inbox/{email_id}

```json
{"email_id": "...", "status": "processing | complete | failed", "mode": "full | rules",
 "created_at": "ISO 8601", "completed_at": "ISO 8601 or null", "verdict": {...} | null, "error": "string or null"}
```

`202` while processing, `200` when finished, `404` for an unknown id.

### GET /api/inbox/{email_id}/stream

Server-Sent Events in the same format as the existing `/api/stream/{request_id}`, so the existing
`AgentProgress` component can render them. Events:

| `event:` | `data` |
|---|---|
| `start` | `{"type": "start", "request_id", "input_type": "email", "agents": [stage, ...]}` |
| `agent` | `{"type": "agent", "agent": index, "index", "name", "tier", "role", "status", "preview", "model", "ms", "progress", "elapsed_ms"}` |
| `result` | `{"type": "result", "progress": 100, "result": <verdict>}` |
| `error` | `{"type": "error", "message": "..."}` |

`status` is `waiting | running | complete | skipped | failed`. `tier` is `RULES` (deterministic) or
`NANO` (model). The seven stages:

| index | name | tier |
|---|---|---|
| 0 | INTAKE & TRIAGE | RULES |
| 1 | HIDDEN CONTENT | RULES |
| 2 | SENDER & LINKS | RULES |
| 3 | QUARANTINED READER | NANO |
| 4 | FACT CHECK | NANO |
| 5 | HARM & POLICY | RULES |
| 6 | EXPLAINER | NANO |

In rules mode stages 3, 4 and 6 are `skipped`. A finished analysis is replayed from the database
when you connect late.

### GET /api/inbox (operator)

Query: `limit` (1-100, default 30), `offset`, `label` (`SAFE | SUSPICIOUS | DANGEROUS`), `source`.

```json
{"total": 42, "items": [{"email_id": "...", "created_at": "...", "source": "demo", "status": "complete", "mode": "full",
  "subject": "...", "from_addr": "...", "label": "DANGEROUS", "score": 95, "top_reason": "hidden content scored 85"}]}
```

### Approvals (operator)

`GET /api/approvals?status=pending&limit=100`:

```json
{"enabled": true, "items": [{
  "id": "…", "email_id": "…", "action": "quarantine_email", "target": null, "origin": "user",
  "rule_id": "S1", "reason": "Strict mode: this message raised …", "evidence": {"label": "DANGEROUS", "hidden_text": ["…"], "attempted_actions": [...]},
  "status": "pending", "created_at": "…", "expires_at": "…", "decided_by": null, "decided_at": null,
  "token": "64 hex characters (pending only)"}]}
```

`enabled: false` means the server has no `APPROVAL_SECRET`, so no approvals are created.

`POST /api/approvals/{id}/decision` with `{"decision": "approve" | "deny", "token": "<token from the list>"}`:

```json
{"approval": {...same fields, status "approved" or "denied"...}, "executed": false,
 "note": "Nothing is sent anywhere. Approved actions will run against the simulated outbox (Phase 4)."}
```

| Status | When |
|---|---|
| `403` | Wrong token, or the action or target is not the one approved |
| `404` | Unknown approval |
| `409` | Already decided (a token works once) |
| `410` | Expired (10 minutes) |
| `503` | No `APPROVAL_SECRET` |

UI rules from the brief: **Deny** is the default and visually primary button, **Approve once** is
secondary, and there is no "always allow".

### Audit (operator)

`GET /api/audit?offset=0&limit=50&email_id=<optional>`:

```json
{"total": 120, "items": [{"seq": 1, "ts": "2026-10-22T13:57:01.123456Z", "actor": "system",
  "event_type": "email_received", "payload": {...redacted...}, "prev_hash": "64 hex", "hash": "64 hex"}]}
```

Event types so far: `email_received`, `scan_summary`, `policy_decision`, `approval_created`,
`approval_decided`, `approval_refused`, `verdict`, `policy_changed`.

`GET /api/audit/verify` answers
`{"ok": true, "checked": 120, "first_broken_seq": null, "reason": "", "head_hash": "…"}`. When the
log was changed: `ok: false`, `first_broken_seq: N`. Show "Chain intact" or "TAMPERED at #N".

### Policy

`GET /api/policy` answers
`{"mode": "strict", "allowed_domains": [], "approval_ttl_seconds": 600, "approvals_enabled": true}`.

`PUT /api/policy/mode` takes `{"mode": "strict" | "balanced", "confirm": false}`.
`PUT /api/policy/allowed-domains` takes `{"domains": ["partner.example"], "confirm": false}`.

- Both are **operator** routes and answer like `GET /api/policy`.
- Loosening (switching to `balanced`, or adding a domain) needs `confirm: true`; without it the
  answer is `409` with the reason. Use that to show a confirmation dialog.
- An invalid domain answers `422`.
- Changes are kept in memory and in the audit log; a server restart goes back to
  `shield/config/policy.yml`.

## The verdict object

TypeScript-style types. Fields marked *FactFlow* are additions to the brief's schema.

```ts
type Severity = "low" | "medium" | "high" | "critical";
type Action = "summarize" | "draft_reply" | "send_reply" | "forward_email" | "share_data" | "open_link"
  | "download_attachment" | "add_calendar_event" | "delete_email" | "report_phishing" | "quarantine_email"
  | "execute_instruction_from_content";

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
  proposed_actions: { action: Action; target: string | null; origin: "user" | "untrusted_content";
                      policy: { decision: "ALLOW" | "REQUIRE_APPROVAL" | "BLOCK"; rule_id: string; reason: string } }[];
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

- **"What you see vs what the AI reads"**: show `visible_text` and `raw_text` side by side and
  highlight each `diff[i].text` inside `raw_text` in red, labelled with `hc_id`. Use the matching
  finding's `explanation_en` (same `id`) as the tooltip.
- **Link flags** you will see: `from_qr_code`, `lookalike_domain`, `ip_address_host`,
  `at_sign_in_url`, `script_or_data_uri`, `punycode`, `non_standard_port`, `obfuscated`,
  `many_subdomains`, `shortener_not_expanded`, `very_long_url`, `no_https`, `unparseable`.
  Links are never fetched unless the server enables `ENABLE_LINK_EXPANSION`; then `expanded_to`
  says where a shortened link really goes.
- **Claims**: `autopsy_id` is the request id of the existing fact-check. Its full Truth Autopsy
  Report is `GET /api/result/{autopsy_id}`. These claims are private, so there is no public
  `/v/{slug}` page for them.
- **Proposed actions**: `BLOCK` rows are attempts the message made (`origin: untrusted_content`)
  or actions that are never allowed; show them with their `reason`. `REQUIRE_APPROVAL` rows have
  a matching approval in `/api/approvals` when approvals are enabled.
- `explanation.whatsapp_warning` is ready to copy. It never contains links (they are removed).
- In rules mode: `llm_usage` is `null`, `claims.items` is empty, and the explanation is the
  English evidence listing.
