"""EmlProvider: the demo inbox. Reads .eml files from a folder (data/demo_emails) and messages
added at runtime (uploads and pasted source). It is the fallback when Wi-Fi or OAuth fails."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from shield.providers.base import RawMessageRef


class EmlProvider:
    name = "eml"

    def __init__(self, folder: Path | None = None) -> None:
        self.folder = folder
        self._added: dict[str, tuple[bytes, datetime]] = {}

    def add(self, data: bytes, name: str | None = None) -> str:
        """Register an uploaded or pasted message; returns its message id (content hash if unnamed)."""
        message_id = name or "upload-" + hashlib.sha256(data).hexdigest()[:16]
        self._added.setdefault(message_id, (data, datetime.now(timezone.utc)))
        return message_id

    def _files(self) -> list[Path]:
        return sorted(self.folder.glob("*.eml")) if self.folder and self.folder.exists() else []

    async def list_new(self, since: datetime | None) -> list[RawMessageRef]:
        refs = []
        for path in self._files():
            received = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            refs.append(RawMessageRef(self.name, path.stem, received))
        refs += [RawMessageRef(self.name, mid, at) for mid, (_data, at) in self._added.items()]
        if since is not None:
            refs = [r for r in refs if r.received_at is None or r.received_at > since]
        return sorted(refs, key=lambda r: (r.received_at or datetime.min.replace(tzinfo=timezone.utc), r.message_id))

    async def fetch_raw(self, message_id: str) -> bytes:
        if message_id in self._added:
            return self._added[message_id][0]
        for path in self._files():
            if path.stem == message_id:
                return path.read_bytes()
        raise KeyError(message_id)
