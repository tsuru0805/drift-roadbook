"""Drifts in progress, one JSON file per traveler.

Two travelers can drift at the same time; a restart keeps whatever was underway;
several server processes sharing one state directory see the same thing
(writes are atomic renames under a per-traveler lock).
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import uuid
from pathlib import Path
from typing import Any, Iterator


class SessionStore:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)

    # traveler ids may be emoji or any text — key files by hex so the filename is always safe
    def _key(self, traveler: str) -> str:
        return traveler.encode("utf-8").hex()

    def _path(self, traveler: str, kind: str) -> Path:
        return self.root / f"{self._key(traveler)}.{kind}.json"

    @contextlib.contextmanager
    def locked(self, traveler: str) -> Iterator[None]:
        """Hold the traveler's lock across a read-modify-write."""
        self.root.mkdir(parents=True, exist_ok=True)
        with open(self.root / f"{self._key(traveler)}.lock", "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _read(self, path: Path) -> dict[str, Any] | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        return data if isinstance(data, dict) else None

    def _write(self, path: Path, data: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    # ── the drift in progress ──
    def get(self, traveler: str) -> dict[str, Any] | None:
        return self._read(self._path(traveler, "session"))

    def put(self, traveler: str, session: dict[str, Any]) -> None:
        self._write(self._path(traveler, "session"), session)

    def clear(self, traveler: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path(traveler, "session").unlink()

    # ── what happened after the last drift was written (e.g. the photo search) ──
    def get_last(self, traveler: str) -> dict[str, Any] | None:
        return self._read(self._path(traveler, "last"))

    def put_last(self, traveler: str, data: dict[str, Any]) -> None:
        self._write(self._path(traveler, "last"), data)

    # ── what kinds of places / times were visited lately (all travelers), to keep picks varied ──
    def recent_kinds(self) -> list[dict[str, Any]]:
        data = self._read(self.root / "recent.json") or {}
        items = data.get("items")
        return items if isinstance(items, list) else []

    def push_kind(self, item: dict[str, Any], keep: int = 20) -> None:
        with self.locked("__recent__"):
            items = [*self.recent_kinds(), item][-keep:]
            self._write(self.root / "recent.json", {"items": items})
