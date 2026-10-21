# NemesisAI

> In April 2020, two sadhus and their driver were lynched by a mob in Palghar, Maharashtra, after child-kidnapping
> rumours spread in the area ([source](https://en.wikipedia.org/wiki/2020_Palghar_mob_lynching)).
> **NemesisAI checks a forward like that one against published sources, live, and says plainly when it cannot tell.**

NemesisAI is a multi-agent misinformation forensics system for India. Paste a WhatsApp forward, tweet, headline, link
or screenshot, and six AI agents trace the evidence, reason over it, and return a verdict you can understand, share and
forward back into the chat. Each step streams live while it runs.

![Stack](https://img.shields.io/badge/backend-FastAPI-009688) ![Stack](https://img.shields.io/badge/frontend-Next.js%2014-black) ![Stack](https://img.shields.io/badge/inference-Groq-f55036) ![License](https://img.shields.io/badge/license-MIT-green)

---

## 1. What NemesisAI does

- **Verifies any input:** pasted text, a URL (the article is fetched and read), or an image (Tesseract OCR, with a
  vision-model fallback).
- **Streams the investigation live:** each agent's progress arrives over Server-Sent Events, so users watch the evidence
  being gathered instead of staring at a spinner.
- **Produces a Truth Autopsy Report:** verdict (FALSE / TRUE / MISLEADING / UNVERIFIED / SATIRE), calibrated
  confidence, reasoning chain, contradictions, tiered and credibility-scored sources, harm assessment, a downloadable
  Myth-vs-Fact card, and a ready-to-send WhatsApp correction in the user's language (12 Indian languages).
- **Tracks the landscape:** a live tracker with verdict and harm breakdowns, and an incident library of documented
  real-world harm (Palghar, Muzaffarnagar, Dhule, Manipur and more) that can be re-run with one click.
- **Meets people where rumours spread:** a Chrome extension (right-click, keyboard shortcut and inline buttons on
  WhatsApp Web, X and Instagram) and an Android overlay prototype.

## 2. Inference: two tiers on Groq

All model calls go through the `openai` Python client pointed at Groq's OpenAI-compatible endpoint
(`https://api.groq.com/openai/v1/`). Keys are loaded from `backend/.env` with `python-dotenv` / `pydantic-settings`.

| Tier | Model (default) | Used by | Why |
|---|---|---|---|
| **Nano** (fast) | `openai/gpt-oss-20b` | Intake, Source Tracer, Explainer, Harm Assessor | ~0.5–1.5 s structured-JSON calls keep the pipeline fast |
| **Ultra** (deep) | `openai/gpt-oss-120b` | Deep Reasoning | Multi-hop reasoning, only when it can change the outcome |
| Vision | `qwen/qwen3.8-27b` | Screenshot text extraction | Fallback when Tesseract finds no text |

The Ultra tier is **escalated only when needed**: when the Source Tracer's confidence is below 85%
(`DEEP_REASONING_THRESHOLD`) or Intake marks the claim **CRITICAL** (imminent risk of violence or physical harm).

**Provider-agnostic by design.** Models and base URL are plain environment variables. Any OpenAI-compatible
endpoint, such as NVIDIA Nemotron models on Nebius, can be swapped in by editing `GROQ_BASE_URL`, `GROQ_API_KEY`,
`NANO_MODEL` and `ULTRA_MODEL` with no code changes. (The Llama 3.1 8B / 3.3 70B models were retired from Groq, which is
why the defaults are the gpt-oss pair.)

## 3. Six-agent pipeline

```
           ┌────────────────────────────────────────────────────────────────────┐
 text ─┐   │ 0 ORCHESTRATOR  route input · fetch URL / OCR image · verdict cache │
 url  ─┼──▶│                 known-pattern match · retries · SSE events          │
 image─┘   └──────────────┬─────────────────────────────────────────────────────┘
                          ▼
              1 INTAKE & TRIAGE (Nano)       core claim · language · type · urgency · search queries
                          ▼
              2 SOURCE TRACER (Nano)         Google Fact Check + NewsAPI + DuckDuckGo
                          │                  tier + credibility scoring · stance · preliminary verdict
          conf < 85% or CRITICAL?
                 yes ▼            no ─────────────┐
              3 DEEP REASONING (Ultra)            │  sub-claims · contradictions · manipulation markers
                          ▼                       ▼
              4 EXPLAINER (Nano)   ║   5 HARM ASSESSOR (Nano)      ← run in parallel
              plain language,      ║   harm type · level · severity 0–10
              translation, myth/   ║
              fact, WhatsApp reply ║
                          ▼
                   Truth Autopsy Report  →  PostgreSQL · Redis cache · SSE "result"
```

| # | Agent | File | Output |
|---|---|---|---|
| 0 | Orchestrator | `backend/agents/orchestrator.py` | Input routing, cache, pattern match, SSE events, fallbacks, persistence |
| 1 | Intake & Triage | `backend/agents/intake_agent.py` | Claim, language, claim type, urgency, search queries |
| 2 | Source Tracer | `backend/agents/source_tracer.py` | Evidence with tier 1–4, credibility, stance; preliminary verdict |
| 3 | Deep Reasoning | `backend/agents/deep_reasoning.py` | Reasoning chain, contradictions, final verdict |
| 4 | Explainer | `backend/agents/explainer.py` | Simple + localised summary, myth/fact, WhatsApp reply |
| 5 | Harm Assessor | `backend/agents/harm_assessor.py` | Harm type, level, severity, rationale |

**Resilience:** every model call retries with backoff and honours Groq's `retry-after` hints. JSON responses that are
truncated are retried with a larger budget. If an agent still fails, the orchestrator degrades gracefully: Intake falls
back to the raw text, the Explainer and Harm Assessor fall back to deterministic output, and Deep Reasoning failure keeps
the tracer's verdict. A request only fails if no verdict can be reached at all.

**Source tiers:** Tier 1 covers IFCN-style fact-checkers, wire services, WHO and `.gov.in`. Tier 2 covers established
national and international newsrooms. Tier 3 is everything else. Tier 4 covers social platforms, blogs and user-generated
content.

**Known patterns:** ten recurring Indian misinformation archetypes (child-lifter rumours, miracle cures, recycled
footage, fake schemes, currency hoaxes and others) are matched by character-trigram similarity plus keywords. This
works across scripts and needs no embedding model or pgvector.

## 4. Run locally

Tested on Windows 11 with Python 3.11, Node 24, PostgreSQL 16 and Memurai (Redis-compatible).

**Prerequisites:** Python 3.11+, Node 18+, Tesseract OCR (optional), and optionally PostgreSQL 15+ and Redis.
Without PostgreSQL the backend automatically falls back to a local SQLite file. Without Redis it uses an in-memory
cache.

### Backend

```bash
cd backend
python -m venv venv                  # use Python 3.11 or 3.12
venv\Scripts\activate                # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # then add GROQ_API_KEY (+ NEWS_API_KEY, GOOGLE_FACT_CHECK_API_KEY)
uvicorn main:app --reload --port 8000
```

Tables are created and seed data (6 incidents, 10 known patterns) is loaded automatically on first start.
Check the server with `curl http://localhost:8000/health`.

**Optional Celery worker** (set `USE_CELERY=true`; requires Redis):

```bash
celery -A tasks.pipeline_task worker --loglevel=info --pool=solo   # --pool=solo is required on Windows
```

### Frontend

```bash
cd frontend
npm install
cp .env.local.example .env.local      # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                           # http://localhost:3000
```

### API keys

| Key | Where | Needed for |
|---|---|---|
| `GROQ_API_KEY` | https://console.groq.com/keys | All agents (required) |
| `NEWS_API_KEY` | https://newsapi.org/register | News evidence (free: 100 req/day) |
| `GOOGLE_FACT_CHECK_API_KEY` | Google Cloud Console → enable *Fact Check Tools API* | Fact-check evidence |

DuckDuckGo search needs no key.

> **Free-tier note:** Groq's free tier allows 8,000 tokens/minute on `gpt-oss-20b`. A verification uses about 4–5k,
> so back-to-back runs may wait a few seconds for the rate limit. The pipeline retries automatically rather than
> failing.

## 5. API reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/verify` | Queue a verification → `202 {request_id, stream_url, result_url}` |
| `GET` | `/api/stream/{request_id}` | SSE stream: `start`, `agent`, `result`, `error` events |
| `GET` | `/api/result/{request_id}` | Full report (`200`), or `202 {status}` while running |
| `GET` | `/api/status/{request_id}` | Status, progress %, per-agent log |
| `GET` | `/api/history?limit=20` | Recent completed verifications |
| `GET` | `/api/incidents` | Incident library with each incident's latest live run |
| `GET` | `/api/stats` | Totals, verdict breakdown, harm categories, average time |
| `GET` | `/health` | DB / cache / model / evidence-source status |

```bash
# Verify text (language: auto | en | hi | mr | bn | ta | te | gu | kn | ml | pa | ur)
curl -X POST http://localhost:8000/api/verify \
  -H "Content-Type: application/json" \
  -d '{"text": "ALERT!! Gangs of child kidnappers are moving in villages at night dressed as sadhus. They remove kidneys. Forward to all groups!", "language": "hi", "platform": "whatsapp"}'

# Verify a URL or an image
curl -X POST http://localhost:8000/api/verify -H "Content-Type: application/json" -d '{"url": "https://example.com/article"}'
curl -X POST http://localhost:8000/api/verify -H "Content-Type: application/json" -d '{"image_url": "https://example.com/forward.png"}'
#   or {"image_base64": "data:image/png;base64,..."}

# Watch the agents live
curl -N http://localhost:8000/api/stream/<request_id>

# Fetch the report
curl http://localhost:8000/api/result/<request_id>
```

Example `agent` event:

```json
{"type": "agent", "agent": 2, "name": "SOURCE TRACER", "tier": "NANO", "status": "complete",
 "preview": "26 sources scanned · 8 relevant · 8 refute · 0 support → FALSE (95%)",
 "model": "openai/gpt-oss-20b", "ms": 990, "progress": 50, "elapsed_ms": 7364}
```

`POST /api/verify` is rate-limited per client IP (`MAX_REQUESTS_PER_MINUTE`, default 10). Identical inputs are served
from the verdict cache for `CACHE_TTL_HOURS` (default 24).

## 6. Chrome extension

1. Start the backend on `http://localhost:8000`.
2. Open `chrome://extensions` and enable **Developer mode**.
3. Click **Load unpacked** and select the `extension/` folder.

Ways to verify:

- **Right-click** selected text or an image, then choose **🔍 Verify with NemesisAI**. A glass verdict badge slides in at
  the top-right and auto-dismisses after 8 seconds.
- **Ctrl+Shift+V** (⌘⇧V on Mac) verifies the current selection. Chrome may keep its own "paste as plain text" binding;
  if so, assign the shortcut at `chrome://extensions/shortcuts`.
- **WhatsApp Web, X and Instagram:** hover a message or post and click the red **V** button, or right-click it and choose
  **Verify this message**. The verdict appears *inline on that message bubble*.
- **Popup:** the last 5 verifications, backend status, **Verify Selected Text** and **Open Dashboard →**.

The inline handlers are DOM-based content-script adapters (`extension/content.js`). They depend on each site's current
markup and may need selector updates when those sites change.

## 7. Business model

| Stream | Who pays | Offer |
|---|---|---|
| Citizens | Free (₹99/yr Family Shield) | Verification, extension and WhatsApp replies free; family plan adds priority checks and alerts |
| Newsrooms & fact-checkers | Usage-based API | Harm-ranked triage queue with evidence pre-gathered |
| Platforms & telcos | Annual trust & safety licence | Rumour alerts by region, language and harm type |
| Government & NGOs | Programme contracts | Election-integrity and public-health early warning |

Market size (TAM: Indian WhatsApp users × ₹99/yr; SAM: those who regularly forward news; SOM: the share reachable
within three years): estimate, source to be added. No figure is given until it has a cited source.

## 8. Future scope

- WhatsApp Business bot: forward a message to a number, get the verdict back in the chat.
- Native Android overlay (see `android/README.md`): on-device OCR, Accessibility-based region capture.
- Audio and video: Whisper transcription of voice notes and reels; deepfake and recycled-footage detection via
  reverse image/video search.
- Semantic claim clustering (embeddings + pgvector) to detect waves of the same rumour across languages.
- Regional early-warning dashboard for police and district administrations when CRITICAL claims spike.
- Human-in-the-loop review queue for partner fact-checkers, with their verdicts fed back as Tier-1 evidence.

## Best Use of Gemma 4

NemesisAI calls **Gemma 4** through the **Gemini API**, using the `google-genai` Python SDK
(`backend/models/gemini_client.py`).

| Setting | Value |
|---|---|
| Model identifier | `gemma-4-26b-a4b-it` (`GEMMA_MODEL`). Confirmed on 2026-10-21 from the Gemini API models list, which showed `gemma-4-26b-a4b-it` and `gemma-4-31b-it`. `gemma-4-31b-it` returned 503/500 errors in testing that day, so the 26B model is the default. |
| Provider switch | `MODEL_PROVIDER=gemini` or `groq`. If unset, Gemma is used only when `GEMINI_API_KEY` is set. |
| Key handling | `GEMINI_API_KEY` is read from the environment / `backend/.env`. Provider errors are re-raised with the key masked, and the key is never logged. |

**Steps that use Gemma 4** (when the provider is `gemini`):

1. **Screenshot claim extraction.** A PNG or JPG up to 5 MB is sent to Gemma 4 with the same
   extraction instruction used elsewhere: transcribe all text, then describe the image in one line.
   If Gemma fails, Tesseract OCR is the fallback.
2. **Deep Reasoning (agent 3).** Multi-hop reasoning over the retrieved evidence. It runs only when
   the Source Tracer's confidence is below 0.85 or the claim is CRITICAL, so a clear-cut claim may
   finish without calling Gemma. The output is the same JSON shape the Groq path produces, so the
   verdict gate treats both identically.

Intake, Source Tracer, Explainer and Harm Assessor stay on Groq (`NANO_MODEL`). `/health` and
`/api/config` (shown in the site footer) report which reasoning model is in use.

## Limitations

- **Private-person and self-harm rule is a keyword check, not a classifier.**
  - It withholds suicide, self-harm and sexual-violence claims, and harm or death stories that name
    a person or give an age, unless a public role (minister, MLA, actor…) is mentioned.
  - It can miss unfamiliar phrasings, names written in lowercase, and names in non-Latin scripts.
  - It withholds some claims it didn't need to, such as a public figure's suicide.
  - For screenshots it runs after text extraction, so the extraction model sees the image.
  - The browser extension doesn't yet show the withheld message.
- **Throttling.** GDELT allows one request per 5 seconds per IP and often refuses requests.
  DuckDuckGo can time out from cloud hosts. A failed provider is recorded as an evidence gap in the
  record, but fewer sources can mean UNVERIFIED instead of a definite verdict.
- **Groq's free tier** has a daily token limit (200,000 tokens/day for `openai/gpt-oss-20b` at the
  time of testing). A full 30-claim bench run needs more than that.
- **The verdict gate is code, not model output.** `decide_verdict` in `agents/orchestrator.py`
  returns UNVERIFIED with fewer than 2 tier 1–2 sources, confidence below 0.6, or missing context
  with no contradiction, whatever the model says.
  - The gate counts tier 1–2 sources regardless of their stance, so a TRUE verdict can rest on
    strong sources labelled REFUTES (seen on the Palghar event claim).
  - Source tiers come from fixed domain lists, so some official sites (e.g. `rbi.org.in`) are tier 3.

## Pre-existing work

Every commit below predates the Hacktoberfest Hack Day (25 October 2026). Dates are taken from
`git log` (IST).

| Commit | Date | Work |
|---|---|---|
| `1620623` | 2026-10-19 | First commit: six-agent pipeline, FastAPI backend, Next.js frontend, Chrome extension, Android mockup |
| `6e3d216` | 2026-10-20 | Public verdict registry, honest-uncertainty gate, corrections in EN/HI/TE |
| `698036d`, `3b35caa` | 2026-10-20 | Frontend v2: public verdict pages, registry, share buttons |
| `5a1908d`, `3f0f721`, `f371e5b` | 2026-10-20 | Public record fields, repeat-detection fix, extension options page |
| `6e9e1d9`, `5e761f8`, `91b4198` | 2026-10-21 | GDELT source, source tiers, grounding rule, 30-claim bench |
| `869f341`–`b3af000` | 2026-10-21 | Spelling variants, named-source summaries, sourced homepage line, `/health` build commit |
| `62d03ba` | 2026-10-21 | Private-person and self-harm rule |
| `c27dba5` | 2026-10-21 | Gemma 4 via the Gemini API |

**Added during the Hack Day:** nothing yet. Any commits dated 25 October 2026 belong here.

## Project structure

```
nemesisai/
├── backend/        FastAPI app, agents/, api/, database/, services/, tasks/
├── frontend/       Next.js 14 (Pages Router) + Tailwind + Framer Motion + Recharts
├── extension/      Chrome MV3 extension
├── android/        Overlay design + interactive mockup
├── LICENSE         MIT
└── README.md
```

## License

[MIT](LICENSE)
