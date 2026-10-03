"""Where on the map a drift happened — Wikipedia coordinates, no API key.

`resolve(place_en, city)` walks from the specific to the general: the exact article, then the
article with its leftmost word dropped ("Kiremit Caddesi Balat" → "Balat"), each time also trying
Wikipedia's own search; finally the city on zh.wikipedia. The result says which `level` it found.
Never raises: no coordinates → a Place with only the city name.
"""
from __future__ import annotations

import math
import time
from urllib.parse import quote

import httpx

from .models import Place

UA = {"User-Agent": "pianhang/0.1 (https://github.com/tsuru0805)"}
_WIKI = "https://en.wikipedia.org"
_WIKI_ZH = "https://zh.wikipedia.org"
_TIMEOUT = 5.0
_BUDGET = 10          # wiki requests per resolve
_DEADLINE = 12.0      # seconds for the whole resolve; past it we stop asking and keep what we have
# an article whose description reads like a settlement = we fell back to the city/town level
_SETTLEMENT_WORDS = ("city", "town", "municipality", "prefecture", "capital", "village", "metropolis",
                     "county", "province", "district of", "borough")


def _num(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except (OverflowError, ValueError):
        return None
    return f if math.isfinite(f) else None


def valid_coords(lat, lon) -> tuple[float, float] | None:
    la, lo = _num(lat), _num(lon)
    if la is None or lo is None or not (-90 <= la <= 90 and -180 <= lo <= 180):
        return None
    return la, lo


def _summary(client: httpx.Client, title: str, base: str = _WIKI) -> dict | None:
    t = title.strip().replace(" ", "_")
    if not t:
        return None
    r = client.get(f"{base}/api/rest_v1/page/summary/{quote(t, safe='')}", headers=UA)
    if r.status_code != 200:
        return None
    j = r.json()
    return j if isinstance(j, dict) else None


def _search(client: httpx.Client, q: str) -> list[str]:
    r = client.get(f"{_WIKI}/w/rest.php/v1/search/page", params={"q": q, "limit": 5}, headers=UA)
    if r.status_code != 200:
        return []
    pages = (r.json() or {}).get("pages")
    if not isinstance(pages, list):
        return []
    return [p["key"] for p in pages if isinstance(p, dict) and isinstance(p.get("key"), str) and p["key"]]


def _coords(s: dict | None) -> tuple[float, float] | None:
    if not isinstance(s, dict):
        return None
    co = s.get("coordinates")
    return valid_coords(co.get("lat"), co.get("lon")) if isinstance(co, dict) else None


def resolve(place_en: str | None, city: str | None, *, client: httpx.Client | None = None,
            deadline: float | None = None) -> Place:
    city = city.strip() if isinstance(city, str) else ""
    city = city or None
    name = place_en.strip() if isinstance(place_en, str) else ""
    if not name and not city:
        return Place()
    stop_at = time.monotonic() + (_DEADLINE if deadline is None else deadline)
    own = client is None
    client = client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
    try:
        words = name.split()
        tries = [" ".join(words[i:]) for i in range(len(words))][:4] if name else []
        budget = _BUDGET
        for depth, q in enumerate(tries):
            if time.monotonic() > stop_at:
                break
            s = _summary(client, q)
            budget -= 1
            cands = [s]
            if not _coords(s):
                for key in _search(client, q)[:2]:
                    if time.monotonic() > stop_at:
                        break
                    budget -= 2
                    cands.append(_summary(client, key))
            for c in cands:
                co = _coords(c)
                if not co:
                    continue
                title = c.get("title") if isinstance(c.get("title"), str) else ""
                desc = str(c.get("description") or "").lower()
                settlement = any(w in desc for w in _SETTLEMENT_WORDS)
                level = "spot" if depth == 0 and not settlement else ("city" if settlement else "street")
                return Place(name=city or title, lat=co[0], lon=co[1], level=level, wiki=title or None)
            if budget <= 0:
                break
        if city and time.monotonic() <= stop_at:
            s = _summary(client, city, base=_WIKI_ZH)
            co = _coords(s)
            if co:
                t = s.get("title") if isinstance(s.get("title"), str) else city
                return Place(name=city, lat=co[0], lon=co[1], level="city", wiki=t)
        return Place(name=city)
    except Exception:          # any odd wiki shape: keep the drift, just without coordinates
        return Place(name=city)
    finally:
        if own:
            client.close()
