"""Knowledge Base Ingestion (RAG v1).

Idempotently imports:
1. Existing incidents from the `incidents` table.
2. Existing patterns from the `known_patterns` table.
3. Starter scheme documents from backend/data/kb_seed/schemes.yml.
4. Scam templates from backend/data/kb_seed/scam_templates.yml.
5. Helpline placeholder pointing to backend/shield/config/helplines.yml as single source of truth.

No duplicate rows created upon repeated runs.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from database.models import Incident, KBDocument, KnownPattern
from shield.kb.embeddings import embed_text

SEED_DIR = BASE_DIR / "data" / "kb_seed"


def _parse_dt(val: Any) -> datetime | None:
    if not val:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


async def ingest_incidents(session: AsyncSession) -> int:
    """Import existing rows from incidents table as kb_documents (deduplicated by id)."""
    rows = (await session.scalars(select(Incident))).all()
    count = 0
    for inc in rows:
        doc_id = f"incident_{inc.slug}"
        text_to_embed = f"{inc.name}. {inc.summary} {inc.what_was_true} {inc.forward_text}".strip()
        emb = embed_text(text_to_embed).tolist()

        body = (
            f"Incident: {inc.name} ({inc.occurred_on.isoformat() if inc.occurred_on else 'undated'}). "
            f"Summary: {inc.summary} "
            f"What was true: {inc.what_was_true} "
            f"Forwarded text: {inc.forward_text}"
        )

        existing = await session.get(KBDocument, doc_id)
        if existing:
            existing.title = inc.name
            existing.body_text = body
            existing.source_url = inc.source_url
            existing.verified = inc.source_confirmed
            existing.verified_by = inc.source_label if inc.source_confirmed else None
            existing.embedding = emb
        else:
            session.add(
                KBDocument(
                    id=doc_id,
                    source_type="incident",
                    title=inc.name,
                    body_text=body,
                    source_url=inc.source_url,
                    verified=inc.source_confirmed,
                    verified_by=inc.source_label if inc.source_confirmed else None,
                    embedding=emb,
                )
            )
        count += 1
    return count


async def ingest_patterns(session: AsyncSession) -> int:
    """Import existing rows from known_patterns table as kb_documents (deduplicated by id)."""
    rows = (await session.scalars(select(KnownPattern))).all()
    count = 0
    for pat in rows:
        doc_id = f"pattern_{pat.slug}"
        text_to_embed = f"{pat.name}. {pat.category}. {pat.description}. Example: {pat.example_text}".strip()
        emb = embed_text(text_to_embed).tolist()

        body = (
            f"Pattern archetype: {pat.name} (Category: {pat.category}, Typical Verdict: {pat.typical_verdict}). "
            f"Description: {pat.description} "
            f"Example forward text: {pat.example_text}"
        )

        existing = await session.get(KBDocument, doc_id)
        if existing:
            existing.title = pat.name
            existing.body_text = body
            existing.verified = True
            existing.verified_by = "factflow_internal_registry"
            existing.embedding = emb
        else:
            session.add(
                KBDocument(
                    id=doc_id,
                    source_type="known_pattern",
                    title=pat.name,
                    body_text=body,
                    source_url=None,
                    verified=True,
                    verified_by="factflow_internal_registry",
                    embedding=emb,
                )
            )
        count += 1
    return count


async def ingest_schemes(session: AsyncSession) -> int:
    """Load government schemes from backend/data/kb_seed/schemes.yml."""
    schemes_file = SEED_DIR / "schemes.yml"
    if not schemes_file.exists():
        return 0
    data = yaml.safe_load(schemes_file.read_text(encoding="utf-8")) or {}
    items = data.get("schemes") or []
    count = 0
    for s in items:
        doc_id = s.get("id") or f"scheme_{s['slug']}"
        title = s["title"]
        body_text = s["body_text"]
        text_to_embed = f"{title}: {body_text}".strip()
        emb = embed_text(text_to_embed).tolist()

        existing = await session.get(KBDocument, doc_id)
        verified = bool(s.get("verified", False))
        verified_by = s.get("verified_by") if verified else None
        verified_on = _parse_dt(s.get("verified_on")) if verified else None

        if existing:
            existing.source_type = "scheme"
            existing.title = title
            existing.body_text = body_text
            existing.source_url = s.get("source_url")
            existing.verified = verified
            existing.verified_by = verified_by
            existing.verified_on = verified_on
            existing.embedding = emb
        else:
            session.add(
                KBDocument(
                    id=doc_id,
                    source_type="scheme",
                    title=title,
                    body_text=body_text,
                    source_url=s.get("source_url"),
                    verified=verified,
                    verified_by=verified_by,
                    verified_on=verified_on,
                    embedding=emb,
                )
            )
        count += 1
    return count


async def ingest_scam_templates(session: AsyncSession) -> int:
    """Load scam templates from backend/data/kb_seed/scam_templates.yml."""
    scam_file = SEED_DIR / "scam_templates.yml"
    if not scam_file.exists():
        return 0
    data = yaml.safe_load(scam_file.read_text(encoding="utf-8")) or {}
    items = data.get("scam_templates") or []
    count = 0
    for t in items:
        doc_id = t.get("id") or f"scam_{t['slug']}"
        title = t["title"]
        body_text = t["body_text"]
        text_to_embed = f"{title}: {body_text}".strip()
        emb = embed_text(text_to_embed).tolist()

        existing = await session.get(KBDocument, doc_id)
        verified = bool(t.get("verified", False))
        verified_by = t.get("verified_by") if verified else None
        verified_on = _parse_dt(t.get("verified_on")) if verified else None

        if existing:
            existing.source_type = "scam_template"
            existing.title = title
            existing.body_text = body_text
            existing.source_url = t.get("source_url")
            existing.verified = verified
            existing.verified_by = verified_by
            existing.verified_on = verified_on
            existing.embedding = emb
        else:
            session.add(
                KBDocument(
                    id=doc_id,
                    source_type="scam_template",
                    title=title,
                    body_text=body_text,
                    source_url=t.get("source_url"),
                    verified=verified,
                    verified_by=verified_by,
                    verified_on=verified_on,
                    embedding=emb,
                )
            )
        count += 1
    return count


async def ingest_helpline(session: AsyncSession) -> int:
    """Load helpline entry pointing to backend/shield/config/helplines.yml as single source of truth."""
    helpline_seed = SEED_DIR / "helpline.yml"
    if not helpline_seed.exists():
        return 0
    seed_info = (yaml.safe_load(helpline_seed.read_text(encoding="utf-8")) or {}).get("helpline_pointer", {})
    rel_path = seed_info.get("config_relpath", "shield/config/helplines.yml")
    config_file = BASE_DIR / rel_path

    if not config_file.exists():
        return 0

    cfg = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    india_cfg = cfg.get("india") or {}
    helpline_num = india_cfg.get("cyber_fraud_helpline", "1930")
    portal = india_cfg.get("cyber_crime_portal", "cybercrime.gov.in")
    source_desc = india_cfg.get("source", "https://cybercrime.gov.in")

    must_verify = bool(cfg.get("human_must_verify", True))
    verified = not must_verify and bool(cfg.get("verified_by"))
    verified_by = cfg.get("verified_by") if verified else None
    verified_on = _parse_dt(cfg.get("verified_on")) if verified else None

    doc_id = seed_info.get("id", "helpline_national_cybercrime")
    title = seed_info.get("title", f"National Cyber Crime Reporting Portal & Helpline ({helpline_num})")
    body = (
        f"Official Indian Cyber Crime Helpline {helpline_num} and National Cyber Crime Reporting Portal ({portal}) "
        f"under the Ministry of Home Affairs (MHA). Source: {source_desc}. "
        f"Report financial cyber fraud immediately via {helpline_num}."
    )
    text_to_embed = f"{title}: {body}".strip()
    emb = embed_text(text_to_embed).tolist()

    existing = await session.get(KBDocument, doc_id)
    if existing:
        existing.source_type = "helpline"
        existing.title = title
        existing.body_text = body
        existing.source_url = "https://cybercrime.gov.in/"
        existing.verified = verified
        existing.verified_by = verified_by
        existing.verified_on = verified_on
        existing.embedding = emb
    else:
        session.add(
            KBDocument(
                id=doc_id,
                source_type="helpline",
                title=title,
                body_text=body,
                source_url="https://cybercrime.gov.in/",
                verified=verified,
                verified_by=verified_by,
                verified_on=verified_on,
                embedding=emb,
            )
        )
    return 1


async def ingest_all(session: AsyncSession) -> dict[str, int]:
    """Run full idempotent ingestion across all sources."""
    inc_count = await ingest_incidents(session)
    pat_count = await ingest_patterns(session)
    sch_count = await ingest_schemes(session)
    scm_count = await ingest_scam_templates(session)
    hlp_count = await ingest_helpline(session)
    await session.commit()

    total = inc_count + pat_count + sch_count + scm_count + hlp_count
    return {
        "incidents": inc_count,
        "known_patterns": pat_count,
        "schemes": sch_count,
        "scam_templates": scm_count,
        "helpline": hlp_count,
        "total": total,
    }


async def main():
    from database import connection

    await connection.init_db()
    async with connection.session_factory()() as session:
        stats = await ingest_all(session)
        print("Knowledge base ingestion complete:")
        for k, v in stats.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    asyncio.run(main())

