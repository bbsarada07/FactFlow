"""Run the labelled bench through the full pipeline and score it.

Usage (from backend/):
    python scripts/run_bench.py                 # all claims
    python scripts/run_bench.py --ids T01 F02   # a subset
    python scripts/run_bench.py --keep          # keep the (private) bench records afterwards

Each claim is stored as a PRIVATE claim (never in the public registry), run through the same
orchestrator the API uses (repeat detection is bypassed so every claim is analysed fresh),
then scored. Uses the database and API keys from backend/.env.
"""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete  # noqa: E402

from agents.grounding import ABSENCE_PATTERN, split_sentences, uncited_sentences, valid_refs  # noqa: E402
from agents.orchestrator import run_pipeline  # noqa: E402
from database import connection  # noqa: E402
from database.models import Claim, Source, new_slug  # noqa: E402
from services.text_utils import input_hash, normalize, redact_pii  # noqa: E402

BENCH = Path(__file__).resolve().parents[1] / "tests" / "bench" / "claims.json"


def grounding_problems(c: Claim, n: int) -> list[str]:
    """Every grounding-rule violation in a stored record (current code's rule):
      * a sentence in summary / fact / reasons / contradictions without a valid [S#] (when n > 0);
      * a 'sentence' that is only citations (its text was lost);
      * an absence claim ("no official / announcement / evidence") without a valid citation,
        anywhere, including the corrections and WhatsApp reply.
    """
    issues: list[str] = []
    fields = {"summary": c.summary or "", "fact": c.fact or ""}
    for i, r in enumerate(c.reasoning_chain or []):
        fields[f"reason{i + 1}"] = r
    for i, r in enumerate(x for x in (c.contradictions or []) if not x.startswith("Manipulation marker:")):
        fields[f"contradiction{i + 1}"] = r
    for name, text in fields.items():
        for sent in split_sentences(text):
            if not re.sub(r"\[S\d+\]|[\s.!?]", "", sent):
                issues.append(f"{name}: citation-only sentence {sent!r}")
        if n:
            issues += [f"{name}: uncited {s!r}" for s in uncited_sentences(text, n)]
    extra = [c.whatsapp_reply or ""] + [v for k, v in (c.correction or {}).items() if k.startswith("text_") and v]
    for text in list(fields.values()) + extra:
        for sent in split_sentences(text):
            if ABSENCE_PATTERN.search(sent) and not valid_refs(sent, n):
                issues.append(f"absence claim without citation {sent!r}")
    return issues


async def run_one(item: dict) -> dict:
    """Run one bench claim through the pipeline and return the scored row."""
    text = redact_pii(item["claim"])
    factory = connection.session_factory()
    async with factory() as s:
        claim = Claim(
            input_type="text", raw_input=text, input_hash=input_hash(text), normalized_text=normalize(text),
            requested_language="en", platform="web", status="queued", slug=new_slug(), is_public=False,
        )
        s.add(claim)
        await s.commit()
        claim_id = claim.id

    t0 = time.perf_counter()
    await run_pipeline(claim_id)
    secs = time.perf_counter() - t0

    async with factory() as s:
        c = await s.get(Claim, claim_id)
        n = len(c.sources)
        problems = grounding_problems(c, n)
        return {
            "id": item["id"],
            "claim": item["claim"],
            "expected": item["expected"],
            "got": c.verdict if c.status == "complete" else f"ERROR: {c.error}",
            "sources": n,
            "strong": sum(1 for x in c.sources if x.tier in (1, 2)),
            "gaps": c.evidence_gaps or [],
            "ungrounded": len(problems),
            "grounding_problems": problems,
            "seconds": round(secs, 1),
            "claim_id": claim_id,
        }


def score(rows: list[dict]) -> dict:
    """Counts as defined in the bench spec."""
    labelled = [r for r in rows if r["expected"] in ("TRUE", "FALSE")]
    return {
        "total": len(rows),
        "matches": sum(r["got"] == r["expected"] for r in rows),
        "false_negatives": sum(r["expected"] == "TRUE" and r["got"] in ("UNVERIFIED", "FALSE") for r in rows),
        "false_positives": sum(r["expected"] == "FALSE" and r["got"] == "TRUE" for r in rows),
        "wrong_but_honest": sum(r["got"] == "UNVERIFIED" for r in labelled),
        "errors": sum(r["got"].startswith("ERROR") for r in rows),
        "ungrounded_sentences": sum(r["ungrounded"] for r in rows),
    }


def print_table(rows: list[dict]) -> None:
    """Plain-text table: claim, expected, got, match."""
    print(f"{'ID':<4} {'CLAIM':<62} {'EXPECTED':<11} {'GOT':<11} {'MATCH':<5} {'SRC':>3} {'T1-2':>4} {'SEC':>5}")
    print("-" * 112)
    for r in rows:
        claim = r["claim"] if len(r["claim"]) <= 62 else r["claim"][:61] + "…"
        match = "yes" if r["got"] == r["expected"] else "no"
        print(f"{r['id']:<4} {claim:<62} {r['expected']:<11} {r['got'][:11]:<11} {match:<5} {r['sources']:>3} {r['strong']:>4} {r['seconds']:>5}")


async def main() -> None:
    """Run the bench and print the table and counts."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", nargs="*", help="only run these claim ids")
    parser.add_argument("--keep", action="store_true", help="keep the private bench records")
    parser.add_argument("--json", type=Path, help="also write rows + counts to this file")
    parser.add_argument("--pause", type=float, default=20, help="seconds between claims (free-tier LLM rate limits)")
    args = parser.parse_args()

    items = json.loads(BENCH.read_text(encoding="utf-8"))["claims"]
    if args.ids:
        items = [i for i in items if i["id"] in set(args.ids)]

    await connection.init_db()
    rows = []
    try:
        for n, item in enumerate(items, 1):
            row = await run_one(item)
            rows.append(row)
            print(f"[{n}/{len(items)}] {row['id']} expected={row['expected']} got={row['got']} ({row['seconds']}s)", flush=True)
            if n < len(items):
                await asyncio.sleep(args.pause)
    finally:
        if not args.keep and rows:
            async with connection.session_factory()() as s:
                ids = [r["claim_id"] for r in rows]
                await s.execute(delete(Source).where(Source.claim_id.in_(ids)))
                await s.execute(delete(Claim).where(Claim.id.in_(ids)))
                await s.commit()
        await connection.close_db()

    print()
    print_table(rows)
    counts = score(rows)
    print()
    for k, v in counts.items():
        print(f"{k:<22} {v}")
    if args.json:
        args.json.write_text(json.dumps({"rows": rows, "counts": counts}, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
