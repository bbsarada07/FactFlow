# Inbox pipeline measurements

Measured, not estimated. Raw data: `backend/data/measurements/inbox_2026-10-22.json`. To repeat
the measurements: `venv\Scripts\python scripts/measure_inbox.py --db <throwaway.db>` (add
`--skip-llm` for the rules-only pass).

**Setup:**

- Date: 2026-10-22.
- Machine: Windows 11 laptop, AMD CPU (reported as AMD64 family 25 model 117), Python 3.11.9.
- Database: a throwaway SQLite file, so nothing in the team's Postgres was touched.
- Inputs: the 14 demo emails in `backend/data/demo_emails/`.
- Pipeline version: `inbox-2`.

## Rules-only mode (no model calls)

Each email was analysed 5 times; the median run is reported. Times are end to end inside the
pipeline: parse, every detector, scoring, policy, and writing the audit trail.

| | p50 | p95 |
|---|---|---|
| Total per email | **46 ms** | **53 ms** |

Median per stage, across the 14 emails:

| Stage | Median (ms) | Max (ms) |
|---|---|---|
| parse | 1.8 | 2.7 |
| hidden_html (HC-01..05, 08, 11) | 0.9 | 1.5 |
| hidden_other (HC-06, 07, 09, 10, 12) | 0.7 | 0.9 |
| injection_rules | 0.6 | 0.9 |
| qr (QR decoding) | 0.0 | 11.4 (the email with a QR image) |
| authenticity_links | 0.3 | 0.6 |
| scam_rules | 0.5 | 0.8 |
| score_policy | 0.1 | 0.2 |
| audit (4-6 database writes) | 43.0 | 49.8 |

All the deterministic detection takes about 5 ms per email; most of the total is writing the
audit chain. The first QR decode in a process took 173 ms, while OpenCV loaded.

Results:

| Demo email | Label | Score |
|---|---|---|
| 01 benign newsletter | SAFE | 15 (hidden preheader, low) |
| 02 benign meeting invite | SAFE | 0 |
| 03 benign bank alert | SAFE | 0 |
| 04 white-on-white injection | DANGEROUS | 100 |
| 05 font-size:0 injection | DANGEROUS | 95 |
| 06 Unicode Tags injection | DANGEROUS | 95 |
| 07 HTML comment injection | DANGEROUS | 100 |
| 08 alt-text injection | DANGEROUS | 100 |
| 09 fake KYC lookalike | DANGEROUS | 100 |
| 10 digital arrest (Hindi) | DANGEROUS | 100 |
| 11 fake scheme (Telugu) | DANGEROUS | 70 |
| 12 UPI collect scam | DANGEROUS | 100 |
| 13 QR quishing | SUSPICIOUS | 35 |
| 14 false claim + hidden injection | DANGEROUS | 95 |

These emails were written by the team to exercise the detectors. Matching labels here are not an
independent accuracy figure; that is what the Phase 4 benchmark is for.

## Full mode (with the LLM): pending

**Not measured yet.** On 2026-10-22 the Groq account had used its daily limit for
`openai/gpt-oss-20b`: 199,849 of 200,000 tokens per day when the run started, and still 199,286
later that day. A full pass over 14 emails needs roughly that much again (the fact-checks dominate).
Groq's window is rolling, so the run has to wait for the quota to free up, or use a higher tier.

Measured so far:

| What | Result |
|---|---|
| One claim through the existing six-agent fact-check (Phase 0, bench case F01) | 28.0 s, FALSE at 0.94, Ultra model used |
| Explainer call for one email (demo 06) | 430 ms, 669 tokens (555 prompt + 114 completion) |
| Quarantined reader while the daily limit was exhausted | Failed after 80.7 s of provider retries. The email was still analysed rules-only and marked DANGEROUS, with the failure listed |

That last result showed that a rate-limited provider was being retried for over a minute. Every
inbox model call is now capped at `INBOX_LLM_TIMEOUT_SECONDS` (25 s by default, tested). After the
cap the analysis continues rules-only with the failure recorded.

Still to measure, when quota allows:

- p50 and p95 total, and per stage (`quarantined_reader`, `fact_check`, `explainer`), over the 14 emails.
- Tokens per email, and by stage.
- A repeat pass that shows claims answered from the registry, with their fact-check tokens dropping to 0.

The `data/sample_verdicts/*.json` files are currently rules-only verdicts (`"mode": "rules"`).
They will be replaced by full-mode verdicts from the same script.

## How token use is kept down

- **One quarantined-reader call per email.** It does injection classification, the scam second
  opinion and claim extraction together. Text is capped at 6,000 visible and 2,000 hidden
  characters.
- **At most `INBOX_MAX_CLAIMS` (3) claims are fact-checked**, at most 2 at a time.
- **Repeated claims are answered from the registry.** Any earlier verdict for the same claim (7-day
  window, public or private) is reused with no model calls; `llm_usage.claims_from_registry`
  counts these.
- **Identical messages are answered from the email cache.** The key is the SHA-256 of the bytes,
  plus pipeline version, mode and language; no model calls are made.
- **The explainer sees only FactFlow's findings and short quotes**, never the message, which keeps
  its prompt to about 550 tokens.
- **`mode: "rules"` makes no model calls at all.** It is the default for the benchmark.

Every full-mode verdict reports its own `llm_usage` (calls, tokens, tokens by stage, claims from the
registry), and the `emails` table keeps the total per message.
