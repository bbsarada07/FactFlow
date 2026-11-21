"""My files: documents a user uploads so their agent can send them when a teammate asks.

A file is only ever sent automatically if the user marked it shareable, and only when exactly one file clearly
matches the request (match()). Files are stored in the database (Render's free plan has no persistent disk), up to
MAX_FILE_BYTES each and MAX_FILES_PER_USER per user. Every function takes the owner's user_id.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from rapidfuzz import fuzz
from sqlalchemy import delete, func, select

from config import settings
from database import connection
from database.models import UserFile

MATCH_MIN = 75  # token_set_ratio a file must reach to be considered
MATCH_GAP = 12  # the best file must beat the next one by this much to be picked on its own
_WORDS = re.compile(r"[A-Za-z0-9]+")
_STOP = {"the", "a", "an", "please", "send", "share", "me", "us", "file", "files", "doc", "document", "copy", "of",
         "for", "by", "tonight", "today", "tomorrow", "asap", "latest", "final", "attached", "attach", "your", "our"}


class FileError(Exception):
    pass


@dataclass
class Match:
    file: UserFile | None
    candidates: list[dict]
    reason: str


def _words(text: str) -> str:
    return " ".join(w for w in (m.lower() for m in _WORDS.findall(text or "")) if w not in _STOP)


async def add(user_id: str, filename: str, content_type: str, data: bytes, shareable: bool = False,
              description: str | None = None) -> UserFile:
    if not data:
        raise FileError("The file is empty.")
    if len(data) > settings.MAX_FILE_BYTES:
        raise FileError(f"Files can be at most {settings.MAX_FILE_BYTES // (1024 * 1024)} MB.")
    name = re.sub(r"[\\/\r\n\t\0]", "_", (filename or "file").strip())[:255] or "file"
    async with connection.session_factory()() as s:
        count = await s.scalar(select(func.count()).select_from(UserFile).where(UserFile.user_id == user_id))
        if (count or 0) >= settings.MAX_FILES_PER_USER:
            raise FileError(f"You can keep at most {settings.MAX_FILES_PER_USER} files. Delete one first.")
        row = UserFile(user_id=user_id, filename=name, content_type=(content_type or "application/octet-stream")[:100],
                       size=len(data), sha256=hashlib.sha256(data).hexdigest(), data=data, shareable=bool(shareable),
                       description=(description or "").strip()[:300] or None)
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row


async def list_files(user_id: str) -> list[dict]:
    async with connection.session_factory()() as s:
        rows = (await s.scalars(select(UserFile).where(UserFile.user_id == user_id)
                                .order_by(UserFile.created_at.desc()))).all()
        return [r.to_dict() for r in rows]


async def get(user_id: str, file_id: str) -> UserFile | None:
    async with connection.session_factory()() as s:
        row = await s.get(UserFile, file_id)
        return row if row is not None and row.user_id == user_id else None


async def update(user_id: str, file_id: str, shareable: bool | None = None, description: str | None = None) -> dict | None:
    async with connection.session_factory()() as s:
        row = await s.get(UserFile, file_id)
        if row is None or row.user_id != user_id:
            return None
        if shareable is not None:
            row.shareable = bool(shareable)
        if description is not None:
            row.description = description.strip()[:300] or None
        await s.commit()
        return row.to_dict()


async def remove(user_id: str, file_id: str) -> bool:
    async with connection.session_factory()() as s:
        res = await s.execute(delete(UserFile).where(UserFile.id == file_id, UserFile.user_id == user_id))
        await s.commit()
        return res.rowcount == 1


async def match(user_id: str, request: str) -> Match:
    """The one file that clearly answers `request` (what the email asked for), or None with the reason."""
    wanted = _words(request)
    if not wanted:
        return Match(None, [], "the request does not name a file")
    async with connection.session_factory()() as s:
        rows = (await s.scalars(select(UserFile).where(UserFile.user_id == user_id))).all()
    scored = []
    for row in rows:
        stem = row.filename.rsplit(".", 1)[0]
        text = _words(f"{stem} {row.description or ''}")
        score = max(fuzz.token_set_ratio(wanted, text), fuzz.partial_ratio(wanted, _words(stem)))
        if score >= MATCH_MIN:
            scored.append((score, row))
    scored.sort(key=lambda t: -t[0])
    candidates = [{"id": r.id, "filename": r.filename, "score": round(sc), "shareable": bool(r.shareable)}
                  for sc, r in scored[:5]]
    if not scored:
        return Match(None, candidates, "no file in My files matches the request")
    if len(scored) > 1 and scored[0][0] - scored[1][0] < MATCH_GAP:
        return Match(None, candidates, "more than one file could be the one asked for")
    return Match(scored[0][1], candidates, "one file clearly matches")
