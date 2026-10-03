"""Default storage: one local SQLite file."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path

from .models import DriftRecord, Place, Temperature

_SCHEMA = """
CREATE TABLE IF NOT EXISTS drifts (
  id TEXT PRIMARY KEY,
  traveler TEXT NOT NULL,
  date TEXT NOT NULL,
  title TEXT NOT NULL,
  destination TEXT NOT NULL,
  country TEXT, city TEXT,
  temperature TEXT,
  place TEXT,
  travelogue TEXT NOT NULL,
  luggage_item TEXT NOT NULL,
  luggage_note TEXT,
  rounds INTEGER,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);
CREATE INDEX IF NOT EXISTS drifts_traveler_date ON drifts(traveler, date DESC);
"""


class SQLiteStorage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    @staticmethod
    def _row(r: sqlite3.Row) -> DriftRecord:
        t = json.loads(r["temperature"]) if r["temperature"] else None
        return DriftRecord(
            id=r["id"], traveler=r["traveler"], date=r["date"], title=r["title"],
            destination=r["destination"], country=r["country"] or "", city=r["city"] or "",
            temperature=Temperature(**t) if t else None,
            place=Place.from_dict(json.loads(r["place"])) if r["place"] else None,
            travelogue=r["travelogue"], luggage_item=r["luggage_item"],
            luggage_note=r["luggage_note"] or "", rounds=r["rounds"] or 0)

    def save(self, record: DriftRecord) -> str:
        rid = record.id or f"d_{uuid.uuid4().hex[:16]}"
        with self._lock, self._conn() as c:
            c.execute(
                "INSERT INTO drifts (id, traveler, date, title, destination, country, city, temperature,"
                " place, travelogue, luggage_item, luggage_note, rounds) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (rid, record.traveler, record.date, record.title, record.destination, record.country,
                 record.city, json.dumps(record.temperature.to_dict(), ensure_ascii=False) if record.temperature else None,
                 json.dumps(record.place.to_dict(), ensure_ascii=False) if record.place else None,
                 record.travelogue, record.luggage_item, record.luggage_note, record.rounds))
        return rid

    def update_place(self, drift_id: str, place: Place) -> None:
        with self._lock, self._conn() as c:
            c.execute("UPDATE drifts SET place=? WHERE id=?",
                      (json.dumps(place.to_dict(), ensure_ascii=False), drift_id))

    def list(self, traveler: str | None = None, limit: int = 50, offset: int = 0) -> list[DriftRecord]:
        q, args = "SELECT * FROM drifts", []
        if traveler:
            q += " WHERE traveler=?"
            args.append(traveler)
        q += " ORDER BY date DESC, created_at DESC LIMIT ? OFFSET ?"
        args += [max(1, min(limit, 200)), max(0, offset)]
        with self._conn() as c:
            return [self._row(r) for r in c.execute(q, args)]

    def get(self, drift_id: str) -> DriftRecord | None:
        with self._conn() as c:
            r = c.execute("SELECT * FROM drifts WHERE id=?", (drift_id,)).fetchone()
        return self._row(r) if r else None

    def recent(self, traveler: str | None, limit: int) -> list[DriftRecord]:
        return self.list(traveler, limit=limit)
