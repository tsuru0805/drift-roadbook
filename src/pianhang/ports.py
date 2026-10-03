"""The seams between the engine and your house.

Everything the engine needs from the outside world goes through one of these.
Swap any of them to fit your own gateway: where drifts are stored, where "today's
temperature" comes from, how a forgotten travelogue gets remembered.
"""
from __future__ import annotations

from typing import Protocol

from .models import DriftRecord, Place


class Storage(Protocol):
    def save(self, record: DriftRecord) -> str:
        """Persist a finished drift, return its id. Raise on failure."""

    def update_place(self, drift_id: str, place: Place) -> None:
        """Replace the place (coordinates / photo) of a stored drift."""

    def list(self, traveler: str | None = None, limit: int = 50, offset: int = 0) -> list[DriftRecord]:
        """Newest first."""

    def get(self, drift_id: str) -> DriftRecord | None: ...

    def recent(self, traveler: str | None, limit: int) -> list[DriftRecord]:
        """Recent drifts used to keep destinations from repeating (all travelers when None)."""


class TemperatureSource(Protocol):
    def collect(self, traveler: str, mood: str) -> str | None:
        """Raw text the temperature is read from: diary entries, recent notes, or just `mood`
        (what the traveler said about today when setting off). None = nothing to read."""


class Reminder(Protocol):
    def opened(self, traveler: str, summary: str) -> None:
        """A drift is underway and has no travelogue yet."""

    def closed(self, traveler: str) -> None:
        """The drift was finished or abandoned."""


class NullReminder:
    def opened(self, traveler: str, summary: str) -> None:
        pass

    def closed(self, traveler: str) -> None:
        pass
