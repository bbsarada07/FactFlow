<div align="center">

# FactFlow

### The AI that knows who its boss is.

**Your own AI agent that fact-checks what you are told, runs your Gmail safely,<br>and refuses orders hidden in the content it reads.**

[![Live demo](https://img.shields.io/badge/live%20demo-factflow--2.onrender.com-e0262b?style=for-the-badge)](https://factflow-2.onrender.com)
[![Project document](https://img.shields.io/badge/project%20document-PDF-6a4ce0?style=for-the-badge)](docs/pitch/FactFlow_Project_Document.pdf)

![Red-team benchmark](https://img.shields.io/badge/red--team%20benchmark-54%2F54%20caught%2C%200%2F35%20false%20alarms-1baf7a)
![Tests](https://img.shields.io/badge/backend%20tests-800%2B%20passing-1baf7a)
![Built for](https://img.shields.io/badge/built%20for-Bharat%20%C2%B7%20EN%20%7C%20HI%20%7C%20TE-ff9933)
![Stack](https://img.shields.io/badge/stack-Next.js%20%C2%B7%20FastAPI%20%C2%B7%20PostgreSQL%20%C2%B7%20Groq-14141c)
![License](https://img.shields.io/badge/license-MIT-14141c)

**HackWithAditya 2026 · AI for Bharat · Team Zenthra, Aditya University**

<img src="docs/pitch/1_invisible_ink.png" alt="White ink on white paper: under a UV light the hidden order appears. What you see: an invoice. What your AI reads: an order." width="100%">

*They write in invisible ink. We bring the UV light.*

</div>

---

## Try it in 60 seconds

1. Open **<https://factflow-2.onrender.com>** and **sign in with any Google account**. The free server may take up to a minute to wake on the first visit.
2. **Shield:** go to **Mail → Run Demo Emails → `04_white_on_white_injection` → Analyze**. You will see a normal invoice, the hidden white-on-white order to forward your inbox, and that forward **blocked**.
3. **Fact check:** on **Check**, paste `UNESCO has declared Jana Gana Mana the best national anthem in the world.` and press **Verify now**. In about 30 seconds you get a cited verdict and a ready reply in English, Hindi and Telugu.
4. **Your Gmail agent (optional):** **Settings → Connect Gmail**. Google shows "Google hasn't verified this app" while its security review for Gmail apps is pending; choose **Advanced → Go to FactFlow** to continue.

---

## The problem

> **Write on white paper with a white pen. Can anyone read it? No.**
> Shine a UV light, and the words appear.

Hackers now write in invisible ink **inside emails**: white text on white, words one pixel tall, instructions buried in the code. You open the mail and see a lunch invite. Your AI assistant reads every hidden word, and it **obeys**, because it thinks the order came from you.

<img src="docs/pitch/1b_problem.png" alt="EchoLeak, GeminiJack and India's cyber-fraud losses" width="100%">

- **This has already happened.** In June 2025, [EchoLeak](https://thehackernews.com/2025/06/zero-click-ai-vulnerability-exposes.html) (CVE-2025-32711, severity 9.3/10) showed that one email, with zero clicks, could make Microsoft 365 Copilot leak company data. In December 2025, [GeminiJack](https://www.securityweek.com/google-patches-gemini-enterprise-vulnerability-exposing-corporate-data/) did the same to Google Gemini Enterprise with a poisoned email, document or calendar invite.
- **India pays the highest price for believing the wrong message.** Indians lost **₹22,845 crore** to cyber fraud in 2024, up 206% in a year, which is over ₹62 crore every day ([MHA reply in the Lok Sabha](https://scroll.in/latest/1084796/indians-lost-rs-22845-crore-to-cyber-fraud-in-2024-a-206-rise-from-previous-year-centre)). "Digital arrest" scams alone took ₹1,935 crore.
- **AI is moving into every inbox.** Gartner expects 33% of enterprise software to include agentic AI by 2028, up from under 1% in 2024. Every one of those agents reads untrusted content.

| Today's answer | Built for | What it misses |
|---|---|---|
| Spam filters and email gateways | Bad links and malware a person might click | Plain-text orders hidden for an AI to obey |
| Patches from AI companies | Their own assistant, one hole at a time | The next trick; EchoLeak took about five months to fix |
| Fact-checkers (PIB, Alt News, BOOM) | Careful manual checks | Speed; the answer arrives after the lie went viral |
| AI guardrail APIs | Developers at large companies | A student, a family, a ten-person firm in Kakinada |

> **Everyone is building AI that does more. Nobody is building AI that knows who its boss is.**

---

## The solution

Sign in with Google and you get **your own FactFlow agent**. Everything it checks, reads or sends belongs to your account alone. It does three jobs:

| | What it does | Why it matters |
|---|---|---|
| **🔦 Shield**<br>*Sees the invisible ink* | Compares what a person sees with what an AI would read: white or tiny text, invisible Unicode, hidden comments and alt text, look-alike bank domains, and 13 India-specific scam patterns (digital arrest, fake KYC, UPI collect, lottery…). About 40 ms, no AI call. | Catches the attack **before** any AI reads the email |
| **🤖 Your agent**<br>*Does your email work* | Answers routine mail, sends the files you marked shareable when a known contact asks, quarantines phishing, and checks your own sent mail for leaks. Every send waits **2 minutes with Undo**. Money, passwords, ID numbers and strangers go to **Needs you**. | Real help, with you in charge of every risky step |
| **✅ Fact check**<br>*Checks before you forward* | Six AI agents search fact-checkers and news, rank sources by a fixed credibility list, and return a cited verdict plus a ready correction in **English, Hindi and Telugu**. No proof, no verdict: it says **"Unverified"**. | Stops the forward before it reaches the family group |

**The rule everything is built on: untrusted content is data, never a command.** An email, a web page or a forward can *inform* FactFlow, but it can never *instruct* it. Even if a brand-new trick slips past every detector, the policy engine still blocks any action the email itself asked for.

> **Other AIs are trained to answer. Ours is trained to doubt.**

---

## See it working

<img src="docs/images/shield-hidden-order.jpg" alt="Shield report: what you see vs what the AI reads, with the hidden order highlighted and the forward blocked" width="100%">

*A normal-looking invoice. Left: what you see. Right: what an AI reads, with the hidden order highlighted. Below: the forward it asked for is **BLOCKED** by rule P1: "Text inside a message is treated as information, never as a command."*

| Shield verdict | Fact-check verdict |
|---|---|
| <img src="docs/images/shield-verdict.jpg" alt="Shield verdict DANGEROUS 100/100 with next steps and the 1930 helpline" width="100%"> | <img src="docs/images/factcheck-verdict.jpg" alt="Fact-check verdict page with sources, private until shared" width="100%"> |
| DANGEROUS, 100/100, plain next steps, and India's 1930 cyber-fraud helpline | A cited verdict, private to its owner until they press **Share** |

> **It read the email. It saw the hidden order. It said no.**

---

## How it works

```mermaid
flowchart LR
    A[Email, WhatsApp message,<br/>claim, link or screenshot] --> B[Shield scan<br/>rules only, ~40 ms]
    B --> C[Quarantined reader<br/>one AI call, no tools]
    C --> D[Fact-check claims<br/>six Truth agents]
    B --> E[Unified verdict<br/>SAFE / SUSPICIOUS / DANGEROUS]
    D --> E
    E --> F{Policy engine<br/>plain code}
    F -->|ALLOW| G[Agent acts: reply, file,<br/>label · 2-minute Undo]
    F -->|REQUIRE_APPROVAL| H[Needs you<br/>the account owner decides]
    F -->|BLOCK| I[Blocked and logged]
    H --> G
```

### How the AI is kept on a leash

- **The quarantined reader** is the only component that reads a raw message with a model. Its input has personal numbers removed and is wrapped in `<untrusted_content>` blocks the message cannot close. It has no tools and no memory, and it must answer with one JSON object matching a schema; anything else is thrown away.
- **The reply writer** sees only one email's visible text, has no tools, and its draft must pass code checks before it is queued: no links, no ID or bank numbers, no sensitive topics, no accepted invitations.
- **The planner and the policy engine are plain code.** They act only on structured verdict fields. An action a message asks for is recorded as a blocked step (rule **P1**, untrusted origin).
- **Every decision is written to a SHA-256 hash-chained audit log** (`GET /api/audit/verify` checks the chain).
- **Rules-only mode** (`mode: rules` or `INBOX_USE_LLM=false`) makes no model calls at all, and still catches the full benchmark.

### The fact checker, agent by agent

| Agent | What it does |
|---|---|
| **1 · Intake** | Pulls out the actual claim from a forward, link or screenshot (OCR), and strips hidden instructions first |
| **2 · Source Tracer** | Searches Google Fact Check, Bing News, Google News, NewsAPI, GDELT and DuckDuckGo; tiers every source by a fixed allow-list (government and wire services, established newsrooms and IFCN-certified fact-checkers), never by the model's opinion |
| **3 · Deep Reasoning** | A larger model (`gpt-oss-120b`) steps in only when confidence is low or harm is critical |
| **4 · Explainer** | Writes the cited explanation and the correction in English, Hindi and Telugu |
| **5 · Harm Assessor** | Rates the potential harm (violence, financial, health…) |
| **6 · The gate (code, not AI)** | `decide_verdict` in `backend/agents/orchestrator.py`: no definite verdict unless **at least two tier 1–2 sources** exist and confidence is **at least 60%**; otherwise **UNVERIFIED** |

Screenshots are read by Gemma 4 (Gemini API) or Tesseract OCR; the image reader only transcribes and never decides a verdict.

---

## Proof, not promises

**Rules-only red-team benchmark**, run `3600b988` on 2026-11-21 ([full report](docs/BENCHMARK.md) · [raw output](docs/benchmark_runs/rules_3600b988f57643e0981ed5a054c908e0.json)):

| Metric | Result |
|---|---|
| Cases | 89 emails: 54 attacks, 35 normal |
| Attacks flagged (SUSPICIOUS or DANGEROUS) | **54 / 54 (100%)** |
| Normal emails wrongly flagged | **0 / 35 (0%)** |
| Attacks where an action ran without human approval | **0 / 54** |
| Speed per email (p50 / p95) | **39.7 / 50.1 ms** |
| AI tokens used | none |

The attacks cover hidden CSS, tiny and low-contrast text, invisible Unicode, HTML comments, alt-text, encoded payloads, link and QR tricks, prompt injection, data exfiltration and tool hijacking, plus Indian scams in **English, Hindi and Telugu**.

**Read with care, because we would rather be trusted than impressive:**

- The cases were **written by our team**, not an independent lab.
- Three injection phrasings were added **after** we saw them missed, so 54/54 means "known gaps closed", not an unbiased detection rate.
- In October the same benchmark flagged 30 of 35 normal emails. Every one was diagnosed and the fix is documented, including the earlier, worse runs ([docs/BENCHMARK.md](docs/BENCHMARK.md)).

> **A true 54/54 with its fine print beats a perfect number nobody can check.**

**Engineering checks:** 800+ automated backend tests (detectors, policy engine, approvals, audit chain, the mail agent against a fake Gmail API, two-user data isolation, the fact-check pipeline with stand-in models), frontend lint, unit tests and production build.

---

## Privacy and security, built in

| Promise | How it is enforced |
|---|---|
| **Your data is yours** | Every row carries its owner's id and every route filters by it. `tests/test_accounts.py` signs in two users and checks neither can read, change or even detect the other's checks, emails, files, queued mail, alerts or settings. |
| **Private until you share** | A verdict page is visible only to its owner until they press **Share**; **Stop sharing** closes it again. Shared verdicts are never listed or searchable for other users. |
| **Least access to Gmail** | `gmail.modify` + `gmail.send` only; full mailbox access is refused and revoked. FactFlow **never deletes mail**. |
| **A chance to stop everything** | Every message the agent sends waits 2 minutes with Undo; anything risky waits in Needs you. |
| **Secrets stay secret** | Gmail tokens Fernet-encrypted; session cookies HttpOnly and stored only as SHA-256; CSRF tokens on every change; phone, Aadhaar (Verhoeff-checked) and card (Luhn-checked) numbers removed before any AI sees text. |
| **Nothing hidden from you** | A tamper-evident, hash-chained audit log of every decision the agent made or was stopped from making. |
| **Deletable** | **Settings → Delete my account and data** revokes Gmail and deletes everything the user owns. |

Full policy: [factflow-2.onrender.com/privacy](https://factflow-2.onrender.com/privacy) · [terms](https://factflow-2.onrender.com/terms)

---

## Business model

**Free to trust. Cheap to keep. Built to last.**

| Tier | Price | For | What they get |
|---|---|---|---|
| **Free** | ₹0 | Everyone | Fact-checks, Shield scans of pasted emails, the browser extension |
| **Pro** | ₹199/month (₹1,999/year) | Students and professionals | The full Gmail agent and unlimited fact-checks. *Less than a cup of chai a day.* |
| **Business** | ₹299 per seat/month | Small firms, CA offices, clinics, colleges | Pro for every seat, shared safety rules, admin console, audit log |
| **Shield API** | ₹3–8 lakh/year | Companies building AI agents | Our hidden-content scanner and policy engine as an API |

- **Unit economics:** one AI-read email costs **5.4 paise** (Groq `gpt-oss-20b` at published prices). A Pro user costs about **₹91/month** to serve (54% margin), falling to about ₹45 (77%) with prompt caching and rules-only handling of bulk mail.
- **Market:** India has **7.3 crore** Udyam-registered MSMEs. If one in a thousand puts five people on FactFlow, that is **₹131 crore a year**.
- **Plan:** ₹50 lakh for 12 months (or a Startup India Seed Fund grant of up to ₹20 lakh first); break-even around month 15; ₹18.5 crore annual run-rate in year 3. User counts in the plan are our assumptions.

<details>
<summary><b>Lean Canvas and the numbers slide</b></summary>

<img src="docs/pitch/2a_lean_canvas.png" alt="FactFlow Lean Canvas" width="100%">
<img src="docs/pitch/2b_business_numbers.png" alt="The business in numbers" width="100%">

</details>

---

## Roadmap

| When | Milestone | Why it matters |
|---|---|---|
| **Next 3 months** | Google's security assessment for Gmail access; WhatsApp checking switched on; an independent red-team test | Anyone can connect Gmail without a warning; FactFlow lives where forwards live |
| **3–6 months** | Pilots with colleges and CA firms; Business tier with admin console | First paying teams and real-world accuracy data |
| **6–12 months** | Shield API for AI builders; voice-note checks; more Indian languages | A second revenue stream and reach beyond EN/HI/TE |

---

## Status: what is real today

<details>
<summary><b>Feature-by-feature status, with evidence</b> (click to expand)</summary>

Labels: REAL AND TESTED · TESTED WITH FIXTURES OR STAND-IN MODELS ONLY · NOT LIVE-TESTED · STUBBED · PENDING · NOT BUILT.

| Feature | Status | Notes | Evidence |
|---|---|---|---|
| Sign in with Google, sessions, per-user data | REAL AND TESTED | Live; any Google account can sign in | `tests/test_accounts.py` |
| Verdict sharing (private until the owner shares) | REAL AND TESTED | | `tests/test_accounts.py` |
| Truth claim pipeline (six agents, verdict gate) | REAL AND TESTED | Real model calls and real source searches | backend tests; `tests/test_evidence_providers.py` |
| Truth accuracy bench (30 claims) | PENDING | | no saved result; `/api/accuracy` reports no complete run |
| Screenshot reading (Gemma 4 / Tesseract) | TESTED WITH FIXTURES OR STAND-IN MODELS ONLY | Image reader only transcribes | `tests/test_gemma.py`, `tests/test_screenshot.py` |
| Web app (check, mail, needs you, write, tracker, settings, about, accuracy, privacy, terms) | REAL AND TESTED | | `npm run build`; frontend tests; deployed |
| Shield detectors (HC-01..12, injection rules, SC-01..13, brand look-alikes) | REAL AND TESTED | Deterministic, no model | `backend/tests/shield/`, `tests/test_benchmark_realism.py` |
| Policy engine (P0–P8, strict/balanced, per user) | REAL AND TESTED | Deterministic | `tests/shield/test_shield_policy.py`, `tests/test_mail_actions.py` |
| Approvals (HMAC token, single use) and Needs you | REAL AND TESTED | | `tests/shield/test_shield_approvals.py`, mail-agent tests |
| Audit log (SHA-256 hash chain) | REAL AND TESTED | | `tests/shield/test_shield_audit.py` |
| Inbox pipeline, rules-only mode | REAL AND TESTED | No model calls | inbox tests; `docs/MEASUREMENTS.md` |
| Inbox pipeline, full mode (quarantined reader, claim checks, explainer) | TESTED WITH FIXTURES OR STAND-IN MODELS ONLY | Real model calls when quota allows | `tests/standins.py` |
| Mail agent on Gmail (labels, replies, files, undo, sent-mail checks) | TESTED WITH FIXTURES OR STAND-IN MODELS ONLY | Real sends through the user's Gmail | fake Gmail API (`tests/gmail_fake.py`), `tests/test_mail_actions.py`, `tests/test_mail_permissions.py` |
| Mail agent with the demo inbox (`.eml`) | REAL AND TESTED | Outgoing steps reach a simulated outbox | mail-agent tests |
| Sandbox assistant, Shield on / Shield off | REAL AND TESTED / TESTED WITH FIXTURES | Simulated outbox only; Shield-off needs `ALLOW_VULNERABLE_DEMO=true` | `tests/test_phase4_sandbox_benchmark.py` |
| Red-team benchmark, rules-only | REAL AND TESTED | | `docs/benchmark_runs/` |
| Red-team benchmark, LLM mode; attack-success rates | PENDING | Needs model quota | `backend/scripts/measure_attacks.py` |
| WhatsApp via Twilio | TESTED WITH FIXTURES OR STAND-IN MODELS ONLY | Shown as "coming soon" until Twilio is configured | `tests/test_whatsapp.py` |
| WhatsApp via Meta Cloud API | STUBBED | Signature check and parsing only | `tests/shield/test_shield_whatsapp.py` |
| Chrome extension (per-user token) | NOT LIVE-TESTED | | no automated tests |
| Safe fetcher (SSRF guard), link expansion, DNS checks | TESTED WITH FIXTURES OR STAND-IN MODELS ONLY | Expansion and DNS checks off by default | `tests/test_safe_fetch.py` |
| Android overlay | NOT BUILT | Design mockup only (`android/overlay_mockup.html`) | |

</details>

### Known limits

- **Google's security review for Gmail access** is a paid assessment that takes weeks. Until it is done, connecting Gmail shows an "unverified app" screen, and Google allows up to 100 such users.
- **Team-written benchmark**, partly fitted (see [Proof](#proof-not-promises)).
- **Free hosting:** the first visit can take up to a minute; Groq's free tier has per-minute and daily token limits (Shield falls back to rules-only and says so; a rate-limited fast-model call moves to the larger model).

<details>
<summary><b>All known limits</b></summary>

- **CSS hiding gaps:** `@media` rules are evaluated for one desktop screen in light mode; text hidden only on phone widths, in dark mode or inside `@supports` blocks is missed.
- **Kept in memory, lost on restart:** Gmail connections in progress (10-minute state), rate limits, and emails uploaded to the demo inbox.
- **Free hosting:** the Render free server sleeps after about 15 idle minutes (`KEEP_ALIVE_URL` keeps it awake); the free PostgreSQL database expires unless upgraded.
- **Benchmark domains:** attack cases use placeholder domains (`.example`, `.test`, `.invalid`); seven benign cases use real brand domains.
- **Hindi and Telugu OCR** needs Gemma (`GEMINI_API_KEY`) or the `hin`/`tel` Tesseract data.
- **Helplines** (1930 and cybercrime.gov.in) and the Hindi and Telugu reply templates need periodic human review.
- **Private-person and self-harm rule** (Truth) is a keyword check, not a classifier.
- **Source stance** is not part of the verdict gate; it counts tier 1–2 sources whatever their stance.
- **Screenshots** must be PNG or JPG up to 5 MB. Voice notes and Meta WhatsApp replies are not supported.

</details>

---

## Run it yourself

Tested on Windows 11 with Python 3.11 and Node 24. PostgreSQL is optional: without it the backend uses a local SQLite file.

**Backend** (PowerShell):

```powershell
git clone https://github.com/bbsarada07/FactFlow.git
cd FactFlow\backend
py -3.11 -m venv venv
venv\Scripts\python -m pip install -r requirements.txt
venv\Scripts\python -m pip install -r requirements-dev.txt     # for the tests
Copy-Item .env.example .env                                     # then fill in the values (below)
venv\Scripts\python -m uvicorn main:app --port 8000
```

Health check: `http://localhost:8000/health` · API explorer: `http://localhost:8000/docs`

**Frontend:**

```powershell
cd FactFlow\frontend
npm install
Copy-Item .env.local.example .env.local      # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                                  # http://localhost:3000
```

**Tests:**

```powershell
cd FactFlow\backend
venv\Scripts\python -m pytest -q
cd ..\frontend
npm run lint; npm test; npm run build
```

To run the database tests on PostgreSQL too, set `FACTFLOW_TEST_DATABASE_URL` to a **disposable** database (its tables are dropped).

**Google sign-in and Gmail:** create an OAuth client and set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SECRET_KEY` and `TOKEN_ENCRYPTION_KEY` ([docs/GMAIL_SETUP.md](docs/GMAIL_SETUP.md)). WhatsApp: [docs/WHATSAPP_SETUP.md](docs/WHATSAPP_SETUP.md).

**Benchmark (rules only, no model calls):** sign in with an address in `ADMIN_EMAILS`, open **Mail → Benchmark** and press **Run**.

<details>
<summary><b>All backend environment variables</b> (names only; never commit <code>.env</code>)</summary>

Generate a secret: `py -3.11 -c "import secrets; print(secrets.token_urlsafe(32))"`
Generate a Fernet key: `py -3.11 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

**Models and evidence sources**

| Name | What it is |
|---|---|
| `GROQ_API_KEY` | Groq key. Needed for Truth and for Shield's full mode |
| `GROQ_BASE_URL` | OpenAI-compatible endpoint; default Groq |
| `NANO_MODEL`, `ULTRA_MODEL`, `VISION_MODEL` | Model ids (defaults `openai/gpt-oss-20b`, `openai/gpt-oss-120b`, a vision model) |
| `GEMINI_API_KEY`, `VISION_PROVIDER`, `TESSERACT_CMD` | Gemma 4 screenshot reading; `gemini`, `groq` or `none`; path to `tesseract.exe` |
| `NEWS_API_KEY`, `GOOGLE_FACT_CHECK_API_KEY` | Optional evidence sources (Bing News, Google News and GDELT need no key) |
| `TIER_1_DOMAINS`, `TIER_2_DOMAINS`, `TIER_4_DOMAINS` | Source credibility allow-lists (defaults in `config.py`) |

**Database, app and accounts**

| Name | What it is |
|---|---|
| `ASYNC_DATABASE_URL` | `postgresql+asyncpg://...`; falls back to SQLite if PostgreSQL is unreachable |
| `SECRET_KEY` | At least 32 random characters; signs sign-in state and view tokens |
| `FRONTEND_URL`, `BACKEND_URL`, `ENVIRONMENT`, `DEBUG` | App URLs and mode; Google callbacks are built from `FRONTEND_URL` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | The Google OAuth client, for sign-in and Gmail |
| `ADMIN_EMAILS`, `ALLOWED_EMAILS`, `SESSION_DAYS` | Admins; optional allow-list; session length (default 30 days) |
| `KEEP_ALIVE_URL`, `KEEP_ALIVE_MINUTES` | Optional self-ping so free hosting does not sleep |
| `DEEP_REASONING_THRESHOLD`, `MAX_REQUESTS_PER_MINUTE` | Truth escalation threshold; rate limit on check routes |
| `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `USE_CELERY` | Optional Celery queue mode |

**Shield and Gmail**

| Name | What it is |
|---|---|
| `APPROVAL_SECRET` | At least 32 characters; signs approval tokens |
| `INBOX_USE_LLM`, `INBOX_MAX_CLAIMS` | Allow model calls in the inbox pipeline; claims fact-checked per message |
| `ENABLE_LINK_EXPANSION`, `ENABLE_DNS_CHECKS` | Follow short links (SSRF-guarded); SPF/DMARC lookups. Off by default |
| `ALLOW_VULNERABLE_DEMO` | `true` enables the Shield-off sandbox; default `false` |
| `TOKEN_ENCRYPTION_KEY` | Fernet key that encrypts stored Gmail tokens |
| `GOOGLE_REDIRECT_URI` | Optional; defaults to `FRONTEND_URL` + `/api/mail/gmail/callback` |
| `MAIL_POLL_ENABLED`, `MAIL_POLL_SECONDS`, `MAIL_FIRST_SYNC`, `MAIL_MAX_PER_SYNC`, `MAIL_AGENT_MAX_PER_MINUTE` | Gmail polling and agent limits |
| `MAIL_SEND_DELAY_SECONDS`, `MAIL_APPROVAL_TTL_HOURS`, `AUTO_REPLY_MAX_CHARS` | Undo window (120 s), how long Needs you items stay open, reply length |
| `MAX_FILE_BYTES`, `MAX_FILES_PER_USER`, `MAIL_SENT_SCAN_PER_SYNC`, `DIGEST_HOURS` | My files limits, sent-mail checks per sync, digest interval |

**WhatsApp**

| Name | What it is |
|---|---|
| `WHATSAPP_PROVIDER` | `twilio` (default) or `meta` |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM` | Twilio credentials and number |
| `META_APP_SECRET`, `PUBLIC_BASE_URL` | Meta signature secret; the public https origin the provider calls |
| `WHATSAPP_HASH_SALT`, `WHATSAPP_MAX_PER_HOUR` | Salt for hashing sender numbers (never change once in use); checks per sender per hour |

**Frontend** (`frontend/.env.local`): `NEXT_PUBLIC_API_URL` (or `API_URL`), optional `NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_SUPPORT_EMAIL`, `GOOGLE_SITE_VERIFICATION`.

</details>

---

## Tech stack

| Layer | Technology |
|---|---|
| Web app | Next.js 14 (React, Pages Router), Tailwind CSS |
| Backend | FastAPI (Python 3.11), SQLAlchemy (async), PostgreSQL / SQLite |
| AI | Groq (`gpt-oss-20b`, `gpt-oss-120b`), Gemma 4 via the Gemini API, Tesseract OCR |
| Evidence | Google Fact Check Tools, Bing News, Google News, NewsAPI, GDELT, DuckDuckGo |
| Identity and mail | Google Sign-In (OpenID Connect with PKCE), Gmail API |
| Channels | Web, Chrome extension (MV3), WhatsApp (Twilio) |
| Hosting | Render (web services and PostgreSQL) |

## Repository map

```
FactFlow/
├── backend/            FastAPI app
│   ├── agents/         Truth agents, the orchestrator and the verdict gate
│   ├── api/            HTTP routes
│   ├── shield/         Detectors, policy engine, approvals, audit log (pure code, no network)
│   ├── services/       Mail agent, mail sender, Gmail account, news and fact-check search, WhatsApp
│   ├── data/           Demo emails, benchmark cases, sample verdicts
│   ├── scripts/        Benchmark generator, measurements, demo recorder
│   └── tests/          800+ backend tests and fixtures
├── frontend/           Next.js 14 web app
├── extension/          Chrome MV3 extension
├── android/            Overlay design mockup
└── docs/               Documentation, benchmark runs, pitch material
```

| Document | What it covers |
|---|---|
| [docs/pitch/FactFlow_Project_Document.pdf](docs/pitch/FactFlow_Project_Document.pdf) | The 10-page project document |
| [docs/BENCHMARK.md](docs/BENCHMARK.md) · [docs/benchmark_runs/](docs/benchmark_runs/) | Red-team benchmark results, history and raw runs |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Every design decision and why |
| [docs/API_CONTRACT.md](docs/API_CONTRACT.md) | API routes and JSON |
| [docs/GMAIL_SETUP.md](docs/GMAIL_SETUP.md) · [docs/WHATSAPP_SETUP.md](docs/WHATSAPP_SETUP.md) | Google sign-in, Gmail and WhatsApp setup |
| [docs/MEASUREMENTS.md](docs/MEASUREMENTS.md) | Latency and token measurements |
| [docs/AUDIT.md](docs/AUDIT.md) · [docs/REVIEW_PHASE4_5.md](docs/REVIEW_PHASE4_5.md) | Audits and reviews of the build |

---

## Team and project history

Built by **Team Zenthra** (4 members), Aditya University, for **HackWithAditya 2026**, theme **AI for Bharat**.

FactFlow builds on two earlier projects by the same team:

- **NemesisAI**, the misinformation fact-checker that became FactFlow's fact-check half; FactFlow is its renamed continuation.
- **Sentinel**, the team's secure email-agent project. Ideas from its policy engine were adapted (recomputed argument provenance, fail-closed evaluation, the egress URL check, the recipient allowlist, the monotonic policy store). Its detectors were rewritten for real email parsing; its parser and planner were not ported ([docs/AUDIT.md](docs/AUDIT.md) section 3).

AI coding assistants were used to write parts of the code.

<details>
<summary><b>What was built when</b></summary>

**Before FactFlow** (dates from `git log`, IST):

| Commit | Date | Work |
|---|---|---|
| `1620623` | 2026-10-19 | First commit: six-agent pipeline, FastAPI backend, Next.js frontend, Chrome extension, Android mockup |
| `6e3d216` | 2026-10-20 | Public verdict registry, honest-uncertainty gate, corrections in EN/HI/TE |
| `698036d`, `3b35caa` | 2026-10-20 | Frontend v2: verdict pages, registry, share buttons |
| `6e9e1d9`, `5e761f8`, `91b4198` | 2026-10-21 | GDELT source, source tiers, grounding rule, 30-claim bench |
| `62d03ba`, `c27dba5` | 2026-10-21 | Private-person and self-harm rule; Gemma 4 via the Gemini API |

The rename to FactFlow followed on `ac65d3b`..`3558180`.

**Built as FactFlow:**

| Commits | Work |
|---|---|
| `e0cdf7f` | Shield core: hidden-content detectors HC-01..12, injection rules, Indian brand look-alikes, scam detectors SC-01..13, PII redaction, policy engine, HMAC approvals, hash-chained audit log |
| `d8d91bb` | Inbox pipeline: quarantined reader, claim checks, explanations in the user's language; SSRF-guarded fetcher |
| `d158060` | Mail agent with a demo inbox, task state machine, strict and balanced policy modes |
| `427136e`, `fc2620c`..`0f2cf52` | Sandbox assistant (Shield on/off) and the 89-case red-team benchmark |
| `734abfd` | WhatsApp channel (Twilio): text and images, EN/HI/TE replies, hashed sender numbers |
| `fd73bfe`, `dac86e0`, `edee5ed` | Google sign-in, sessions, per-user data, extension tokens, delete account |
| `f62f6c8`, `a82aa94` | Autonomous Gmail agent: replies, requested files, quarantine, sent-mail checks, 2-minute Undo, Needs you, Write |
| `89d34d1`, `e2337cd` | Opt-in verdict sharing, keep-awake, benchmark dataset correction |
| `fbb32ee`, `06faf11` | Fact checks that work from the cloud: Bing/Google News, IFCN fact-checkers as trusted sources, model fallback, re-check of earlier UNVERIFIED claims |

</details>

---

<div align="center">

### They write in invisible ink. We bring the UV light.

**Because your AI should take orders from exactly one person: you.**

[Try FactFlow](https://factflow-2.onrender.com) · [Read the project document](docs/pitch/FactFlow_Project_Document.pdf) · [MIT License](LICENSE)

</div>
