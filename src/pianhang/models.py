"""Plain data shapes shared by the engine, storages and frontends."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Place:
    name: str | None = None
    lat: float | None = None
    lon: float | None = None
    level: str | None = None          # "spot" | "street" | "city" | None
    wiki: str | None = None
    image: str | None = None
    image_page: str | None = None
    image_credit: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "Place | None":
        if not isinstance(d, dict):
            return None
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})


@dataclass
class Destination:
    destination: str
    short_name: str
    country: str = ""
    city: str = ""
    place_en: str = ""
    kind: str = ""                    # what sort of place: "canal-side teahouse", "night market"…
    time_of_day: str = ""
    reason: str = ""
    search_queries: list[str] = field(default_factory=list)
    photo_queries: list[str] = field(default_factory=list)
    chosen_by: str = "temperature"    # "self" | "temperature"
    approx: list[float] | None = None  # narrator's own [lat, lon] estimate, refines a city-level fix

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Destination":
        kw = {k: d.get(k) for k in cls.__dataclass_fields__ if d.get(k) is not None}
        return cls(**kw)


@dataclass
class Temperature:
    texture: str = ""
    warmth: int | None = None
    movement: str = ""
    season_feel: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DriftRecord:
    """A finished drift, as stored and as served to frontends."""
    traveler: str
    date: str
    title: str
    destination: str
    travelogue: str
    luggage_item: str
    luggage_note: str = ""
    country: str = ""
    city: str = ""
    temperature: Temperature | None = None
    place: Place | None = None
    rounds: int = 0
    id: str = ""

    def to_api(self, traveler_name: str = "") -> dict[str, Any]:
        return {
            "id": self.id,
            "traveler": self.traveler,
            "traveler_name": traveler_name or self.traveler,
            "date": self.date,
            "title": self.title,
            "destination": self.destination,
            "country": self.country,
            "city": self.city,
            "temperature": ({"texture": self.temperature.texture, "warmth": self.temperature.warmth}
                            if self.temperature else None),
            "place": self.place.to_dict() if self.place else None,
            "travelogue": self.travelogue,
            "luggage": {"item": self.luggage_item, "note": self.luggage_note},
            "rounds": self.rounds,
        }


@dataclass
class Receipt:
    """What a tool call returns. `text` is written for the traveler (the AI) to read;
    `ok=False` always says what failed and what to do next — never a silent dead end."""
    ok: bool
    text: str
    data: dict[str, Any] = field(default_factory=dict)
