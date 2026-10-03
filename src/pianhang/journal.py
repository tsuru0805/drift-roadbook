"""A temperature source that reads plain-text notes from a folder.

Point `PIANHANG_JOURNAL_DIR` at wherever your companion (or you) keep diary-ish text files —
`.md` / `.txt` changed in the last few days are read, newest first. Without it, the only
temperature material is the `mood` line passed to `start_drift`.
"""
from __future__ import annotations

import time
from pathlib import Path


class JournalTemperature:
    def __init__(self, folder: str | Path | None, *, days: float = 3, max_chars: int = 4000,
                 per_traveler: bool = True):
        self.folder = Path(folder) if folder else None
        self.days = days
        self.max_chars = max_chars
        self.per_traveler = per_traveler

    def collect(self, traveler: str, mood: str) -> str | None:
        parts: list[str] = []
        if self.folder and self.folder.is_dir():
            # <folder>/<traveler>/ if it exists, so travelers don't read each other's notes
            root = self.folder / traveler if self.per_traveler and (self.folder / traveler).is_dir() else self.folder
            cutoff = time.time() - self.days * 86400
            files = sorted((p for p in root.iterdir()
                            if p.is_file() and p.suffix in (".md", ".txt") and p.stat().st_mtime >= cutoff),
                           key=lambda p: p.stat().st_mtime, reverse=True)
            used = 0
            for p in files:
                text = p.read_text(encoding="utf-8", errors="replace").strip()
                if not text:
                    continue
                chunk = text[: max(0, self.max_chars - used)]
                parts.append(f"[{p.stem}]\n{chunk}")
                used += len(chunk)
                if used >= self.max_chars:
                    break
        if mood:
            parts.append(f"[出发时说] {mood}")
        return "\n\n".join(parts) or None
