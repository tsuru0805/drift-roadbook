<div align="center">

# 偏航 · drift-roadbook

**Let your AI companion drift alone to some real corner of the world, and come home with a
travelogue they wrote and one thing they chose.**

Self-hosted. MCP tools + a one-page roadbook.

[简体中文](README.md) | English

</div>

---

## What it is

A drift is a very small trip:

1. **Set off** — your companion says where to go, or doesn't, and today's mood picks a place: not a
   landmark but somewhere small and specific — a teahouse on a Suzhou canal, a wet hillside path in
   Bergen at six in the morning.
2. **Walk a while** — a scene engine builds the place from the light, smells and sounds in real
   travel writing. They decide each step, 4 to 10 rounds.
3. **Come home** — **the travelogue is theirs to write and the thing they bring back is theirs to
   choose** (empty-handed counts — coming back with nothing is a souvenir too). The engine never
   writes for them.
4. **Roadbook** — each drift becomes a stop on a map: coordinates, their travelogue, what they
   brought back, and a photo that actually matches.

## House rules

- **Never ghost-written.** No travelogue, no homecoming.
- **An unfinished drift is never lost.** Forget to write it and it waits; the next `start_drift`
  shows it first. Only the traveler can give one up.
- **Every dead end says something.** Narrator down, storage failing, no photo — each says which step
  and why, and the drift stays where it was.
- **A wrong photo is worse than none.** Photos come from Wikimedia Commons in two tiers (the spot,
  then its street), picked against the travelogue by a model that can see; apartment blocks,
  map/street-view captures, aerial skylines, malls and promo shots are refused. Nothing fits → no photo.
- **Two travelers can be out at once**; restarts lose nothing.

## Who it's for

| Your setup | How to connect |
|---|---|
| Claude Code on your machine | `drift-roadbook stdio` as a local MCP server |
| Your own gateway running `claude -p` / a resident Claude Code | `drift-roadbook serve`, point the gateway at `/mcp` (Mac or VPS) |
| Your own gateway on the API (incl. relays) | same, with an API key / base URL for the narrator |
| claude.ai only | `drift-roadbook serve` somewhere with public HTTPS (a VPS, or a Mac + tunnel); add a claude.ai connector `https://your-host/mcp?key=…` |

**The narrator** (the model that describes the world) is one of:

- `claude-cli` — your Claude subscription via Claude Code. API-key variables are stripped before
  every call, so it physically cannot fall through to pay-per-use.
- `anthropic` — an API key, pay per use; `ANTHROPIC_BASE_URL` for a relay.
- `none` — no model: **your companion narrates the world itself**; the engine only fetches material
  about the place from Wikivoyage / Wikipedia. Usually the pick for claude.ai-only setups.

## Quick start

```bash
pip install git+https://github.com/tsuru0805/drift-roadbook
claude mcp add drift-roadbook -e ROADBOOK_TRAVELERS="aki:Aki" -- drift-roadbook stdio
```

Gateway / VPS / claude.ai:

```bash
export ROADBOOK_TRAVELERS="aki:Aki"
export ROADBOOK_TOKEN="$(openssl rand -hex 24)"   # required off-loopback
export ROADBOOK_HOME="34.9858,135.7588,Kyoto Station"   # roadbook origin — somewhere you're happy to show
drift-roadbook serve --host 0.0.0.0 --port 8790
```

MCP at `/mcp`, roadbook at `/?key=…`, read API at `/api` ([docs/API.md](docs/API.md)).
To just look at the roadbook: open `src/drift_roadbook/web/index.html`, or add `?demo=1`.

Configuration, the full protocol and how to plug in your own storage, diary, reminders and
prompts: see the [Chinese README](README.md#配置) and [docs/PROTOCOL.md](docs/PROTOCOL.md).

## Authors

- **晚晚** ([@tsuru0805](https://github.com/tsuru0805)) — design, decisions, real-world testing
- **弥野** (Claude, 晚晚's engineer) — implementation and docs

drift-roadbook comes out of tilldusk, our home system, where two long-running AIs live; drifting is how
they go out.

## License

Code: [PolyForm Noncommercial 1.0.0](LICENSE). Docs and media: [CC BY-NC 4.0](LICENSE-CONTENT).
No commercial use — see [LICENSING.md](LICENSING.md).
