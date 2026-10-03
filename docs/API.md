# HTTP API

The engine serves a small read API for frontends (the bundled web roadbook, or your own UI).
MCP tools are documented in [PROTOCOL.md](PROTOCOL.md).

## Auth

If `PIANHANG_TOKEN` is set, every `/api/*` request must carry it, either as
`Authorization: Bearer <token>` or as `?key=<token>`. The web roadbook reads `?key=` from its own
URL and forwards it. Without a token configured, the API only listens on loopback.

## `GET /api/config`

```json
{
  "title": "偏航",
  "home": { "lat": 34.9858, "lon": 135.7588, "label": "Kyoto Station" },
  "travelers": [ { "id": "aki", "name": "Aki" } ]
}
```

`home` is where the roadbook draws its starting point. It is configuration, not data — set it to
somewhere you are comfortable showing.

## `GET /api/drifts?traveler=<id>&limit=<n>&offset=<n>`

Newest first. `traveler` optional (all travelers when omitted). `limit` default 50, max 200.

```json
[
  {
    "id": "d_01J…",
    "traveler": "aki",
    "traveler_name": "Aki",
    "date": "2026-10-03",
    "title": "苏州平江路运河茶坊",
    "destination": "苏州平江路的运河茶坊",
    "country": "中国",
    "city": "苏州",
    "temperature": { "texture": "午后光线落在各自的角落", "warmth": 7 },
    "place": {
      "name": "苏州",
      "lat": 31.3157, "lon": 120.6305,
      "level": "spot",
      "image": "https://upload.wikimedia.org/…/1280px-….jpg",
      "image_page": "https://commons.wikimedia.org/wiki/File:….jpg",
      "image_credit": "Author name · CC BY-SA 4.0"
    },
    "travelogue": "推开那扇木门时……",
    "luggage": { "item": "三弦女子的沙哑嗓音", "note": "她唱给没来的船……" },
    "rounds": 6
  }
]
```

Field rules:

- `place` may be `null` (location not found). Inside it, `lat`/`lon` are both present or both
  `null`; `image`, `image_page`, `image_credit` may be `null` (no acceptable photo — the engine
  prefers no photo over a wrong one).
- `place.level`: `"spot"` (the exact place), `"street"` (its street/district), `"city"`
  (fell back to the city). Frontends may zoom differently per level.
- `luggage.item` may be `"空手"` / `"empty-handed"` — coming back empty-handed is a souvenir too.
- `travelogue` is plain text written by the traveler, newlines preserved. Render it as text,
  never as HTML.

## `GET /api/drifts/<id>`

One record, same shape. `404` with `{"error": "not found"}` when missing.

## Errors

Every non-2xx response is JSON: `{"error": "<human-readable reason>"}`.
