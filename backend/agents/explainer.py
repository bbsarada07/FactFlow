"""Agent 4 — Explainer (Nano): plain-language verdict, translation, myth vs fact, WhatsApp reply."""
from agents.context import AgentOutput, PipelineContext
from models.groq_client import call_nano
from services.text_utils import truncate

SYSTEM = """You are the Explainer agent of NemesisAI. You turn forensic verdicts into short, kind, plain-language
messages that ordinary people — including elderly relatives in family WhatsApp groups — will read and trust.
Never shame the sender. Respond with a single JSON object and nothing else."""

PROMPT = """CLAIM: {claim}
VERDICT: {verdict} ({confidence:.0%} confidence)
FINDINGS: {summary}
WHAT IS TRUE: {fact}
KEY SOURCE: {key_source}
TARGET LANGUAGE: {language} (code: {code})

Return JSON:
{{"simple_summary": "2-3 sentences in plain English (max 60 words) explaining what we found",
 "local_summary": "the same explanation written natively in {language}; if {language} is English repeat simple_summary",
 "myth": "the claim as people are sharing it, max 20 words, in English",
 "fact": "what is actually true, max 35 words, in English",
 "fact_source": "short source attribution, e.g. 'WHO' or 'Alt News fact-check'",
 "whatsapp_reply": "a ready-to-send reply to the forward, written in {language}, max 70 words, warm and respectful, stating the verdict and the true facts, asking people not to forward it further, ending with the line: — Checked with NemesisAI"}}

If the verdict is TRUE, "myth" should restate the claim and "fact" should confirm it with context.
If the verdict is UNVERIFIED, say clearly that no reliable confirmation exists yet and advise waiting for official sources."""


async def run(ctx: PipelineContext) -> AgentOutput:
    res = await call_nano(
        SYSTEM,
        PROMPT.format(
            claim=ctx.claim,
            verdict=ctx.verdict,
            confidence=ctx.confidence,
            summary=ctx.summary or "(none)",
            fact=ctx.fact or "(not established)",
            key_source=ctx.key_source or "(none)",
            language=ctx.output_language_name,
            code=ctx.output_language,
        ),
        max_tokens=1200,
    )
    d = res.data

    simple = str(d.get("simple_summary") or "").strip()
    if simple:
        ctx.summary = simple
    ctx.summary_local = str(d.get("local_summary") or ctx.summary).strip()
    ctx.myth = truncate(str(d.get("myth") or ctx.claim), 220)
    ctx.fact = truncate(str(d.get("fact") or ctx.fact), 320)
    ctx.fact_source = str(d.get("fact_source") or ctx.key_source or "NemesisAI analysis").strip()
    ctx.whatsapp_reply = str(d.get("whatsapp_reply") or "").strip()

    return AgentOutput(
        preview=f"Verdict explained in {ctx.output_language_name} · WhatsApp reply + myth/fact card ready",
        model=res.model,
        ms=res.ms,
    )


def fallback(ctx: PipelineContext) -> None:
    """Deterministic output used if the Explainer call fails."""
    ctx.summary_local = ctx.summary
    ctx.myth = truncate(ctx.claim, 220)
    ctx.fact = ctx.fact or ctx.summary
    ctx.fact_source = ctx.key_source or "NemesisAI analysis"
    ctx.whatsapp_reply = (
        f"This message has been checked and appears to be {ctx.verdict}. {ctx.fact} "
        "Please don't forward it further.\n— Checked with NemesisAI"
    )
