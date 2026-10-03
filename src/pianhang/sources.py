"""Free reading material about a place, for when no narrator is connected (host mode).

Wikivoyage and Wikipedia intros, plain text, no key. The companion reads these and
narrates the place itself.
"""
from __future__ import annotations

import httpx

from .place import UA

_SITES = ("https://zh.wikivoyage.org", "https://zh.wikipedia.org", "https://en.wikivoyage.org")


def _search_title(client: httpx.Client, base: str, q: str) -> str | None:
    r = client.get(f"{base}/w/api.php", headers=UA, params={
        "action": "query", "list": "search", "srsearch": q, "srlimit": 1, "format": "json"})
    if r.status_code != 200:
        return None
    hits = ((r.json() or {}).get("query") or {}).get("search") or []
    return hits[0]["title"] if hits and isinstance(hits[0].get("title"), str) else None


def _extract(client: httpx.Client, base: str, title: str, chars: int) -> str:
    r = client.get(f"{base}/w/api.php", headers=UA, params={
        "action": "query", "prop": "extracts", "explaintext": 1, "exchars": chars,
        "titles": title, "format": "json", "redirects": 1})
    if r.status_code != 200:
        return ""
    pages = ((r.json() or {}).get("query") or {}).get("pages") or {}
    return next((str(p.get("extract") or "") for p in pages.values()), "").strip()


def material(place: str, *, chars: int = 1500, timeout: float = 6.0) -> tuple[str, str | None]:
    """→ (reading material, best Wikipedia-ish title or None). Never raises."""
    parts: list[str] = []
    title_found: str | None = None
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            for base in _SITES:
                t = _search_title(client, base, place)
                if not t:
                    continue
                text = _extract(client, base, t, chars)
                if text:
                    parts.append(f"【{t} · {base.split('//')[1]}】\n{text}")
                    if "wikipedia" in base and title_found is None:
                        title_found = t
                if len(parts) >= 2:
                    break
    except Exception:
        pass
    return "\n\n".join(parts), title_found
