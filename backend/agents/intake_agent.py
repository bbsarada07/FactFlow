"""Agent 1 — Intake & Triage (Nano): extract the core claim, detect language, classify urgency."""
from agents.context import (
    CLAIM_TYPES,
    LANGUAGE_NAMES,
    UNTRUSTED_NOTICE,
    URGENCY,
    AgentOutput,
    PipelineContext,
    pick,
    str_list,
    untrusted,
)
from models.groq_client import call_nano
from services.text_utils import truncate

SYSTEM = """You are the Intake & Triage agent of FactFlow, a misinformation forensics system focused on India.
You receive raw content (a WhatsApp forward, tweet, headline, OCR text or article) and prepare it for fact-checking.
Respond with a single JSON object and nothing else.
""" + UNTRUSTED_NOTICE

PROMPT = """Today's date: {today}
Known misinformation patterns that resemble this content: {patterns}

RAW CONTENT:
{text}

Return JSON with exactly these keys:
- "claim": the single core factual assertion that can be checked, rewritten in clear English, max 30 words. Keep names, places, numbers and dates. If several claims exist, choose the most consequential one.
- "language": ISO 639-1 code of the RAW CONTENT's main language (e.g. "en", "hi", "mr", "ta"). Romanised Hindi (Hinglish) counts as "hi".
- "language_name": English name of that language.
- "claim_type": one of {claim_types}.
- "urgency": one of LOW, MEDIUM, HIGH, CRITICAL.
    CRITICAL = could plausibly trigger imminent violence or mob action against identifiable people or groups, or immediate physical harm (dangerous medical advice).
    HIGH = health, communal, or election content likely to spread fast and mislead many people.
    MEDIUM = misleading but low immediate risk. LOW = trivia, satire, or low-stakes content.
- "entities": list of up to 6 key people, places, organisations or products.
- "search_queries": list of 3 short English web-search queries (3-8 words each) that would surface news coverage or debunks of this claim. Write them the way a journalist would search, not by copying the forward's wording: name the rumour or event neutrally (e.g. "child kidnapping rumour WhatsApp India", "cow urine COVID cure claim"). Query 1 must end with "fact check". Query 2 is a plain news-style query. Query 3 names the relevant authority (e.g. "WHO", "ICMR", "police advisory", "Election Commission"). Never include meta words like "news coverage" or "official statement".
- "fact_check_query": one 2-5 word generic name for the rumour as fact-checkers would title it (e.g. "child kidnapping rumour", "garlic cures coronavirus").
- "satire_signals": true if the content looks like satire, parody or a joke.
- "platform": one of whatsapp, twitter, instagram, facebook, youtube, news, unknown — your best guess from the style."""


async def run(ctx: PipelineContext) -> AgentOutput:
    patterns = ", ".join(p["name"] for p in ctx.pattern_matches) or "none"
    res = await call_nano(
        SYSTEM,
        PROMPT.format(today=ctx.today, patterns=patterns, text=untrusted(ctx.raw_text[:4000], "content"), claim_types=", ".join(CLAIM_TYPES)),
        max_tokens=700,
    )
    d = res.data

    ctx.claim = truncate(str(d.get("claim") or ctx.raw_text), 300)
    lang = str(d.get("language") or "en").lower()[:8]
    ctx.language = lang
    ctx.language_name = str(d.get("language_name") or LANGUAGE_NAMES.get(lang, lang))
    ctx.claim_type = pick(d.get("claim_type"), CLAIM_TYPES, "OTHER")
    ctx.urgency = pick(d.get("urgency"), URGENCY, "MEDIUM")
    ctx.entities = str_list(d.get("entities"), 6)
    ctx.search_queries = str_list(d.get("search_queries"), 3) or [truncate(ctx.claim, 80)]
    ctx.fact_check_query = str(d.get("fact_check_query") or ctx.search_queries[0])[:120]
    ctx.satire_signals = bool(d.get("satire_signals"))
    if ctx.platform in ("web", "unknown", ""):
        guess = str(d.get("platform") or "").lower()
        if guess in ("whatsapp", "twitter", "instagram", "facebook", "youtube", "news"):
            ctx.platform = guess

    preview = f"Claim extracted: '{truncate(ctx.claim, 90)}' · {ctx.language_name} · {ctx.urgency}"
    return AgentOutput(preview=preview, model=res.model, ms=res.ms)
