"""Find one photo that matches where the traveler actually went — or none at all.

Candidates come from Wikimedia Commons (free, no key): a keyword search per photo query
(the most specific first), plus photos geotagged near the spot when we have its coordinates.
A narrator that can see images then picks the one closest to what the travelogue describes and
rejects the kinds of pictures that would be wrong (ordinary apartment blocks, map/street-view
captures, aerial skylines, promo shots). Two tiers: the exact spot, then its street/district.
Nothing acceptable → no photo. A wrong photo is worse than an empty frame.
"""
from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx

from .place import UA, valid_coords

_API = "https://commons.wikimedia.org/w/api.php"
_TIMEOUT = 8.0
_PER_QUERY = 8
_MAX_CANDIDATES = 12
_THUMB_W = 512
_SHOW_W = 1280
_MIMES = {"image/jpeg", "image/png", "image/webp"}
# filenames that are almost never a traveler's view of a place
_REJECT_TITLE = re.compile(
    r"(aerial|skyline|panorama|satellite|street ?view|map\b|plan\b|logo|flag|coat of arms|emblem|"
    r"diagram|seal\b|sign\b|ticket|poster|plaza block|apartment|residential|housing estate|"
    r"tower block|\.svg|\.gif|\.tif)", re.I)

DEFAULT_RULES = """挑选规则：
- 只选和游记里写到的场景最贴的那一张（地点、氛围、旅行者的视角）。
- 一律拒绝：普通居民楼/住宅小区、地图或街景截图、城市航拍与天际线、商业大楼与商场、宣传照/海报、
  人物特写、文字或标志为主的图、明显与游记无关的地方。
- 都不合格就不选——宁可没有照片，也不要错的照片。"""


@dataclass
class Photo:
    image: str
    page: str
    credit: str
    lat: float | None = None
    lon: float | None = None
    tier: str = "spot"            # "spot" | "street"


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


def _candidates(client: httpx.Client, *, query: str | None = None,
                near: tuple[float, float] | None = None) -> list[dict]:
    params = {"action": "query", "format": "json", "prop": "imageinfo",
              "iiprop": "url|mime|size|extmetadata", "iiurlwidth": _SHOW_W,
              "iiextmetadatafilter": "Artist|LicenseShortName|GPSLatitude|GPSLongitude"}
    if query:
        params.update(generator="search", gsrsearch=query, gsrnamespace=6, gsrlimit=_PER_QUERY)
    else:
        params.update(generator="geosearch", ggscoord=f"{near[0]}|{near[1]}", ggsradius=600,
                      ggsnamespace=6, ggslimit=_PER_QUERY)
    r = client.get(_API, params=params, headers=UA)
    if r.status_code != 200:
        return []
    pages = ((r.json() or {}).get("query") or {}).get("pages") or {}
    out = []
    for p in sorted(pages.values(), key=lambda p: p.get("index", 0)):
        info = (p.get("imageinfo") or [{}])[0]
        title = str(p.get("title") or "")
        if info.get("mime") not in _MIMES or _REJECT_TITLE.search(title):
            continue
        if (info.get("width") or 0) < 640:
            continue
        meta = info.get("extmetadata") or {}
        artist = _strip_html((meta.get("Artist") or {}).get("value", ""))[:80]
        lic = _strip_html((meta.get("LicenseShortName") or {}).get("value", ""))[:40]
        co = valid_coords(_f((meta.get("GPSLatitude") or {}).get("value")),
                          _f((meta.get("GPSLongitude") or {}).get("value")))
        out.append({"title": title, "image": info.get("thumburl") or info.get("url"),
                    "page": info.get("descriptionurl"), "credit": " · ".join(x for x in (artist, lic) if x),
                    "coords": co})
    return out


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _thumb_url(url: str, width: int) -> str:
    return re.sub(r"/\d+px-", f"/{width}px-", url, count=1)


class PhotoFinder:
    def __init__(self, narrator=None, *, rules: str = DEFAULT_RULES, client: httpx.Client | None = None):
        self.narrator = narrator
        self.rules = rules
        self._client = client

    def find(self, photo_queries: list[str], spot: tuple[float, float] | None,
             travelogue: str) -> Photo | None:
        own = self._client is None
        client = self._client or httpx.Client(timeout=_TIMEOUT, follow_redirects=True)
        try:
            queries = [q for q in (photo_queries or []) if isinstance(q, str) and q.strip()]
            spot_tier = queries[:1]
            street_tier = queries[1:]
            seen: set[str] = set()

            def gather(qs: list[str], use_near: bool) -> list[dict]:
                got: list[dict] = []
                for q in qs:
                    got += _candidates(client, query=q)
                if use_near and spot:
                    got += _candidates(client, near=spot)
                fresh = []
                for c in got:
                    if c["image"] and c["title"] not in seen:
                        seen.add(c["title"])
                        fresh.append(c)
                return fresh[:_MAX_CANDIDATES]

            for tier, qs, use_near in (("spot", spot_tier, True), ("street", street_tier, False)):
                cands = gather(qs, use_near)
                if not cands:
                    continue
                pick = self._pick(client, cands, travelogue)
                if pick is not None:
                    c = cands[pick]
                    co = c["coords"]
                    return Photo(image=c["image"], page=c["page"] or "", credit=c["credit"],
                                 lat=co[0] if co else None, lon=co[1] if co else None, tier=tier)
            return None
        finally:
            if own:
                client.close()

    def _pick(self, client: httpx.Client, cands: list[dict], travelogue: str) -> int | None:
        if self.narrator is None or not getattr(self.narrator, "can_see_images", False):
            # nobody can look at it, so nobody can vouch for it: a wrong photo is worse than none
            return None
        with tempfile.TemporaryDirectory(prefix="pianhang-photo-") as d:
            paths, index = [], []
            for i, c in enumerate(cands):
                n = len(paths)   # files are named by their position in the list the model sees
                try:
                    r = client.get(_thumb_url(c["image"], _THUMB_W), headers=UA)
                except httpx.HTTPError:
                    continue
                if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
                    continue
                p = Path(d) / f"{n}.jpg"
                p.write_bytes(r.content)
                paths.append(str(p))
                index.append(i)
            if not paths:
                return None
            prompt = (f"游记：\n{travelogue[:1500]}\n\n{self.rules}\n\n"
                      '只输出 JSON：{"pick": 编号或 null, "why": "一句话"}')
            answer = self.narrator.look(prompt, paths)
        m = re.search(r"\{.*\}", answer, re.S)
        try:
            pick = json.loads(m.group(0)).get("pick") if m else None
        except json.JSONDecodeError:
            return None
        if isinstance(pick, int) and not isinstance(pick, bool) and 0 <= pick < len(index):
            return index[pick]
        return None
