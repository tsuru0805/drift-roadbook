"""Run the drift engine as an MCP server (stdio or HTTP) plus a small read API and the web roadbook.

    pianhang stdio            # for a local Claude Code / Claude Desktop
    pianhang serve            # HTTP: /mcp (MCP), /api/* (read API), / (web roadbook)

Configuration is environment variables — see README for the full list.
"""
from __future__ import annotations

import argparse
import asyncio
import hmac
import os
import shutil
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .engine import DriftEngine
from .journal import JournalTemperature
from .narrators import AnthropicNarrator, ClaudeCLINarrator
from .session_store import SessionStore
from .storage_sqlite import SQLiteStorage

WEB_DIR = Path(__file__).parent / "web"


# ── configuration ──────────────────────────────────────────────────────────

def _travelers() -> dict[str, str]:
    raw = os.getenv("PIANHANG_TRAVELERS", "").strip()
    out: dict[str, str] = {}
    for item in raw.split(","):
        if not item.strip():
            continue
        tid, _, name = item.partition(":")
        out[tid.strip()] = (name or tid).strip()
    return out


def _home() -> dict:
    raw = os.getenv("PIANHANG_HOME", "").strip()
    if not raw:
        return {"lat": 0.0, "lon": 0.0, "label": "home"}
    lat, lon, *label = [x.strip() for x in raw.split(",")]
    return {"lat": float(lat), "lon": float(lon), "label": label[0] if label else "home"}


def _narrator(data_dir: Path):
    kind = os.getenv("PIANHANG_NARRATOR", "").strip().lower()
    model = os.getenv("PIANHANG_MODEL", "claude-sonnet-5-5")
    claude_bin = os.getenv("PIANHANG_CLAUDE_BIN") or shutil.which("claude")
    if not kind:
        kind = "claude-cli" if claude_bin else ("anthropic" if os.getenv("ANTHROPIC_API_KEY") else "none")
    if kind == "claude-cli":
        if not claude_bin:
            sys.exit("PIANHANG_NARRATOR=claude-cli but no `claude` command found (install Claude Code).")
        return ClaudeCLINarrator(workdir=data_dir / "cli", model=model, binary=claude_bin,
                                 oauth_token=os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or None)
    if kind == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY")
        if not key:
            sys.exit("PIANHANG_NARRATOR=anthropic needs ANTHROPIC_API_KEY.")
        return AnthropicNarrator(api_key=key, model=model, base_url=os.getenv("ANTHROPIC_BASE_URL") or None)
    if kind == "none":
        return None
    sys.exit(f"PIANHANG_NARRATOR must be claude-cli / anthropic / none, got {kind!r}")


def build_engine() -> DriftEngine:
    data_dir = Path(os.getenv("PIANHANG_DATA_DIR", "./pianhang-data")).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)
    return DriftEngine(
        storage=SQLiteStorage(data_dir / "drifts.db"), store=SessionStore(data_dir / "state"),
        narrator=_narrator(data_dir), travelers=_travelers(),
        temperature=JournalTemperature(os.getenv("PIANHANG_JOURNAL_DIR") or None,
                                       per_traveler=os.getenv("PIANHANG_JOURNAL_SHARED", "") != "1"),
        min_rounds=int(os.getenv("PIANHANG_MIN_ROUNDS", "4")),
        max_rounds=int(os.getenv("PIANHANG_MAX_ROUNDS", "10")),
        tz=os.getenv("PIANHANG_TZ", "Asia/Shanghai"))


# ── MCP tools ──────────────────────────────────────────────────────────────

def build_mcp(engine: DriftEngine, **kw) -> FastMCP:
    mcp = FastMCP(name="pianhang", instructions=(
        "偏航：独自去世界上某个真实的角落走一走，回来时带一篇自己写的游记和一样东西。"
        "start_drift 出发 → drift_act 一步步走 → finish_drift 收尾。"), **kw)

    async def call(fn, *a):
        r = await asyncio.to_thread(fn, *a)
        return r.text if r.ok else f"Error: {r.text}"

    @mcp.tool()
    async def start_drift(traveler: str, destination: str = "", mood: str = "") -> str:
        """Set off on a drift to a real place. You walk it round by round with drift_act and end it
        with finish_drift, writing your own travelogue. An unfinished drift is never dropped:
        start_drift shows it instead of setting off.

        Args:
            traveler: your traveler id
            destination: where you want to go, in your own words; empty = chosen from today's mood/notes
            mood: optional, a line about how today feels
        """
        return await call(engine.start, traveler, destination, mood)

    @mcp.tool()
    async def drift_act(traveler: str, action: str) -> str:
        """Your next step, first person (50-100 chars). Returns what happens next."""
        return await call(engine.act, traveler, action)

    @mcp.tool()
    async def finish_drift(traveler: str, travelogue: str, luggage: str, note: str = "") -> str:
        """Come home. travelogue: your own travelogue, first person. luggage: the one thing you bring
        back (≤30 chars, may be "空手"). note: optional, one line on why. Missing either → refused, drift kept."""
        return await call(engine.finish, traveler, travelogue, luggage, note)

    @mcp.tool()
    async def abandon_drift(traveler: str, confirm: bool = False) -> str:
        """Give up your unfinished drift; nothing is recorded. Requires confirm=True."""
        return await call(engine.abandon, traveler, confirm)

    @mcp.tool()
    async def drift_status(traveler: str) -> str:
        """Is a drift in progress? Also reports whether the last drift's photo was found."""
        return await call(engine.status, traveler)

    @mcp.tool()
    async def read_drifts(traveler: str = "", limit: int = 5) -> str:
        """Recent finished drifts (title, date, what was brought back)."""
        rows = await asyncio.to_thread(engine.storage.list, traveler or None, max(1, min(limit, 20)))
        if not rows:
            return "还没有偏航记录。"
        return "\n".join(f"{r.date} · {r.title} · {engine.name(r.traveler)} · 带回：{r.luggage_item}  (id={r.id})"
                         for r in rows)

    return mcp


# ── HTTP: read API + web roadbook ──────────────────────────────────────────

def build_http_app(engine: DriftEngine, token: str | None):
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route
    from starlette.staticfiles import StaticFiles

    kw: dict = {"stateless_http": True}
    if token:
        # behind a tunnel / domain the Host header is yours, not localhost; the key is the guard
        from mcp.server.transport_security import TransportSecuritySettings
        kw["transport_security"] = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    mcp = build_mcp(engine, **kw)
    app = mcp.streamable_http_app()

    def err(status: int, msg: str):
        return JSONResponse({"error": msg}, status_code=status)

    async def config(request):
        return JSONResponse({"title": os.getenv("PIANHANG_TITLE", "偏航"), "home": _home(),
                             "travelers": [{"id": k, "name": v} for k, v in engine.travelers.items()]})

    async def drifts(request):
        q = request.query_params
        try:
            limit = max(1, min(int(q.get("limit", 50)), 200))
            offset = max(0, int(q.get("offset", 0)))
        except ValueError:
            return err(400, "limit / offset must be integers")
        rows = await asyncio.to_thread(engine.storage.list, q.get("traveler") or None, limit, offset)
        return JSONResponse([r.to_api(engine.name(r.traveler)) for r in rows])

    async def drift_one(request):
        r = await asyncio.to_thread(engine.storage.get, request.path_params["drift_id"])
        return JSONResponse(r.to_api(engine.name(r.traveler))) if r else err(404, "not found")

    loopback_hosts = {"127.0.0.1", "localhost", "::1", "[::1]"}

    class Auth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            path = request.url.path
            if not token and path.startswith("/api/"):
                # no key configured = this server is only for this machine; refuse anything that
                # arrives under another host name (a tunnel, a forwarded port, DNS rebinding)
                host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
                if host not in loopback_hosts:
                    return err(403, "no PIANHANG_TOKEN set: only reachable as localhost")
            if token and (path.startswith("/api/") or path.startswith("/mcp")):
                given = request.query_params.get("key") or ""
                h = request.headers.get("authorization", "")
                if h.lower().startswith("bearer "):
                    given = h[7:].strip()
                if not hmac.compare_digest(given.encode(), token.encode()):
                    return err(401, "missing or wrong key")
            return await call_next(request)

    app.router.routes.extend([
        Route("/api/config", config),
        Route("/api/drifts", drifts),
        Route("/api/drifts/{drift_id}", drift_one),
        Mount("/", StaticFiles(directory=WEB_DIR, html=True)),
    ])
    app.add_middleware(Auth)
    return app


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="pianhang")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stdio", help="MCP over stdio (local Claude Code / Desktop)")
    sp = sub.add_parser("serve", help="HTTP: MCP at /mcp, read API at /api, web roadbook at /")
    sp.add_argument("--host", default=os.getenv("PIANHANG_HOST", "127.0.0.1"))
    sp.add_argument("--port", type=int, default=int(os.getenv("PIANHANG_PORT", "8790")))
    args = ap.parse_args(argv)
    engine = build_engine()
    if args.cmd == "stdio":
        build_mcp(engine).run("stdio")
        return
    token = os.getenv("PIANHANG_TOKEN", "").strip() or None
    if not token and args.host not in ("127.0.0.1", "localhost", "::1"):
        sys.exit("Refusing to listen on a non-loopback address without PIANHANG_TOKEN.")
    import uvicorn
    # no access log: the key may ride in the query string (?key=) and must not land in log files
    uvicorn.run(build_http_app(engine, token), host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
