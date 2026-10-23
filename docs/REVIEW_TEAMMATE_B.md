# Review of Teammate B's Shield frontend (branch `teammate-b/shield-ui`)

Reviewed on 2026-10-23 from the actual diffs, read-only.

**Where the code is.** Teammate B's work is 7 commits by Akshaya, 2026-10-23, `9137288`..`646a98d`. It is on
`origin/teammate-b/shield-ui` and was merged into `origin/main` by PR #4 (`51f9d83`). It is **not** in
`shield-integration`, so the agreed `git pull` brought nothing. Following the Step 0d gate, nothing was changed in
this code; the findings are listed for the team.

**Size.** 27 files, +3,864/-7:
- 5 pages under `/shield`: `index`, `report/[id]`, `approvals`, `advanced/benchmark`, `advanced/audit`;
- 5 components in `components/shield/`;
- `lib/shieldApi.js` and `lib/shieldSecurity.mjs`;
- 3 mock verdicts;
- 1 test file;
- 10 PNGs;
- a Navbar change.

**Builds and tests.** In a separate worktree (same `package.json`, no new dependencies), `npm test` gave 7 passed
(3 existing + 4 new) and `npm run build` succeeded with the 5 `/shield` pages.

Overall, this is a solid start that already follows the important safety rules: text is escaped, the operator token
lives in `sessionStorage` only, and nothing uses `dangerouslySetInnerHTML`. The main issues are mock mode being on by
default, a mock benchmark that does not match the real one, and the missing mail-agent, sandbox and policy-mode
parts.

| # | File | Finding | Severity |
|---|---|---|---|
| 1 | `frontend/lib/shieldApi.js:11` | `USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS !== "false"`: **mock mode is on by default**. A build or deployment without `NEXT_PUBLIC_USE_MOCKS=false` shows mock data on every Shield page. The only label is a small "MOCK DATA" pill in `ShieldNav`. | risk (high) |
| 2 | `frontend/lib/shieldApi.js:224-249` | The mock benchmark run shows `false_positive_rate: 8.57` and confusion matrix FP 3 / TN 32, with an invented per-category table and latency 19.9/25.0 ms. The real measured rate is **85.71 % (30/35)** (`docs/benchmark_runs/rules_31376138...json`). The data is marked MOCK in code and nav, so it is not a RED FLAG, but a plausible-looking wrong number on the benchmark page is risky in a demo. Suggest default-off mocks, or mock numbers that are obviously fake, plus an in-page MOCK banner. | risk (high) |
| 3 | `frontend/pages/shield/advanced/benchmark.js` | No disclaimer that the cases are team-authored and not an independent evaluation (required by the spec). No FAILED-cases list. | rule violation |
| 4 | `frontend/pages/shield/advanced/benchmark.js:98-105` | The chart reads `val.rate`, but the real `per_category` has `attack_detection_rate_pct` / `benign_false_positive_rate_pct`, so every rate shows 0 with real data. `missed = total - detected` is wrong for benign categories, where `detected` means flagged. | bug |
| 5 | `frontend/components/shield/EmailSandboxedIframe.js:13, 16-38` | The HTML preview defaults to "rendered" (spec: off by default). The `srcDoc` has no CSP meta tag, so remote images and tracking pixels in an email would load in the viewer's browser. It is currently **imported but not rendered** (`VisibleVsAiReads.js:4`), so there is no live impact yet. | rule violation (latent) |
| 6 | `frontend/lib/shieldSecurity.mjs` | `escapeSuspiciousCharacters` turns every ZWJ/ZWNJ (U+200D/U+200C) into `[U+200D]`/`[U+200C]`. These are normal in Hindi and Telugu text (the backend's HC-06 has an Indic exception), so Indic emails will display broken. | bug |
| 7 | `frontend/components/Navbar.js` | Adds the "Shield" item (fine), but also changes spacing, logo size, text size, background opacity and makes the nav scroll horizontally. The spec allowed adding nav items only. | rule violation (minor) |
| 8 | `frontend/public/screenshots/*.png` (10 files) | All five "1280px" files are byte-identical, and so are all five "390px" files; they are blank white images. They show nothing, so they claim nothing, but their names suggest real page screenshots. Remove them or replace them with real captures. | risk |
| 9 | `frontend/lib/shieldApi.js` | No calls to `/api/mail/*` (provider status, Gmail connect/disconnect, upload, tasks, steps, outbox), `/api/sandbox/*` (Shield ON/OFF panel) or `PUT /api/policy/mode`. The spec's provider switch, mail-agent task view with inline approve/deny, Shield ON/OFF panel and policy toggle are missing. | gap |
| 10 | `frontend/pages/shield/report/[id].js` | No "Download report image" (html2canvas pattern) and no language selector. The `AgentProgress` reuse exists. | gap |
| 11 | `frontend/lib/shieldApi.js:149, 171, 181-218, 329, 364`; `frontend/mocks/*.json` | The secret scanner flags hex strings. All were judged placeholders or hashes: sequential fake approval tokens (`a1b2c3...`), made-up mock audit hashes, `mock-view-token...` strings, and `audit_head_hash`/`sha256` copied from the real sample verdicts. **No secrets.** | note |
| 12 | `frontend/mocks/verdict.*.json` | Derived from the real `backend/data/sample_verdicts/` files (same email ids, rules-only, `llm_status.state: not_used`) and marked `"_mock": true`. Good. | note |
| 13 | `frontend/lib/shieldApi.js:62-119` | Operator token: `sessionStorage` only, sent as `X-Operator-Token`, never from `NEXT_PUBLIC_*`, never logged. 401/403/409/410/429/503 have messages. The spec wants 503 to say "operator token is not configured on the server". The current text is generic but includes the server's detail. | note |
| 14 | `frontend/components/shield/VisibleVsAiReads.js` | The hero view renders `visible_vs_raw` as escaped text, with hidden `diff` segments highlighted, an HC-ID chip and a tooltip from `explanation_en`. No `dangerouslySetInnerHTML` anywhere. Matches the contract. | note (good) |
| 15 | scope | No changes to `README.md`, datasets, deployment files, the extension or `package.json` (no new dependencies). | note (good) |
| 16 | routes | Pages live under `/shield/...`, not `/inbox` and `/approvals` as in the build prompt. If the team keeps Teammate B's structure, the demo script should use `/shield/...`. | note |

## What to decide

1. Whether to bring Teammate B's branch into `shield-integration`, for example by merging `origin/teammate-b/shield-ui`
   (no conflicts are expected: it only adds files under `frontend/` plus a Navbar change). Until then, Step 3 of the
   final build prompt is on hold, so that their work is not duplicated.
2. Whether to fix #1-#6 on their branch (by Teammate B) or after the merge (as small `fix:` commits).
