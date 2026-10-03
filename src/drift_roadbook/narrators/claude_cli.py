"""Narrate through the `claude` CLI, billed to your Claude subscription.

Every call runs `claude -p` in a scrubbed environment: any `*API_KEY*` / `ANTHROPIC*`
variable is removed first, so a call can never fall through to pay-per-use billing.
Headless `claude -p` authenticates with a long-lived token from `claude setup-token`,
passed in as `oauth_token`.

One drift = one CLI conversation (`--session-id`, then `--resume`), so the world remembers
what already happened without the whole history being resent every round.
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

from . import NarratorError


class ClaudeCLINarrator:
    name = "claude-cli"
    can_see_images = True

    def __init__(self, *, workdir: str | os.PathLike, model: str = "claude-sonnet-5-5",
                 effort: str = "low", binary: str = "claude", oauth_token: str | None = None,
                 timeout: float = 240):
        self.workdir = Path(workdir)
        self.model = model
        self.effort = effort
        self.binary = binary
        self.oauth_token = oauth_token
        self.timeout = timeout

    def _env(self) -> dict[str, str]:
        # strip every route to pay-per-use: API keys, and the switches that send Claude Code to a
        # cloud provider's billing (Bedrock / Vertex / Foundry)
        env = {k: v for k, v in os.environ.items() if not self._risky_env_key(k)}
        env.setdefault("HOME", os.path.expanduser("~"))
        if self.oauth_token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = self.oauth_token
        return env

    MANAGED_SETTINGS = ("/Library/Application Support/ClaudeCode/managed-settings.json",
                        "/etc/claude-code/managed-settings.json")

    @staticmethod
    def _risky_env_key(k: str) -> bool:
        return "API_KEY" in k or "ANTHROPIC" in k or k.startswith("CLAUDE_CODE_USE_")

    @classmethod
    def check_settings(cls, home: str | None = None) -> None:
        """Refuse to run if Claude Code settings could route calls to pay-per-use (`apiKeyHelper`, or an
        API key / Anthropic endpoint / cloud-provider switch in the settings' `env`) — settings would
        bypass the environment scrubbing."""
        paths = [Path(home or os.path.expanduser("~")) / ".claude" / "settings.json",
                 *(Path(p) for p in cls.MANAGED_SETTINGS)]
        for path in paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            env = data.get("env") if isinstance(data.get("env"), dict) else {}
            if data.get("apiKeyHelper") or any(cls._risky_env_key(k) for k in env):
                raise NarratorError(f"{path} 里配了 apiKeyHelper / API key / Anthropic 端点，"
                                    "claude -p 可能走按量计费——不运行。")

    def _run(self, prompt: str, args: list[str]) -> str:
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.check_settings(self._env().get("HOME"))
        # the prompt goes in on stdin: text starting with "-" must never be read as an option
        cmd = [self.binary, "-p", *args,
               "--permission-mode", "dontAsk", "--model", self.model,
               "--effort", self.effort, "--output-format", "json", "--disable-slash-commands"]
        try:
            r = subprocess.run(cmd, input=prompt.encode("utf-8"), capture_output=True, env=self._env(),
                               timeout=self.timeout, cwd=self.workdir)
        except FileNotFoundError:
            raise NarratorError(f"找不到 claude 命令（{self.binary}）——这台机器没装 Claude Code？") from None
        except subprocess.TimeoutExpired:
            raise NarratorError(f"场景引擎超时（{int(self.timeout)} 秒没有回应）") from None
        try:
            out = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
        except json.JSONDecodeError:
            out = {}
        if r.returncode != 0 or out.get("is_error") or not out.get("result"):
            detail = (out.get("result") or r.stderr.decode("utf-8", "replace")).strip()[-300:]
            raise NarratorError(f"场景引擎出错（claude rc={r.returncode}）：{detail or '没有输出'}")
        return str(out["result"]).strip()

    def complete(self, system: str, prompt: str, *, web_search: bool = False) -> str:
        # an empty --system-prompt would fall back to Claude Code's own coding prompt
        system = system or "照用户的要求回答，只输出被要求的内容。"
        tools = ["--tools", "WebSearch", "--allowedTools", "WebSearch"] if web_search else ["--tools", ""]
        return self._run(prompt, ["--system-prompt", system, *tools, "--no-session-persistence"])

    def world(self, system: str, history: list[dict], new_input: str, state: dict) -> tuple[str, dict]:
        sid = state.get("cli_session")
        base = ["--system-prompt", system, "--tools", ""]
        if sid:
            try:
                return self._run(new_input, [*base, "--resume", sid]), state
            except NarratorError:
                # the CLI transcript is gone (cleaned up, other machine…) — replay below
                pass
        sid = str(uuid.uuid4())
        prompt = new_input
        if history:
            replay = "\n\n".join(
                f"{'【场景】' if e['role'] == 'world' else '【旅行者】'}\n{e['content']}" for e in history)
            prompt = f"（之前已经发生的）\n{replay}\n\n（现在）\n{new_input}"
        text = self._run(prompt, [*base, "--session-id", sid])
        return text, {**state, "cli_session": sid}

    def look(self, prompt: str, image_paths: list[str]) -> str:
        dirs = sorted({str(Path(p).parent) for p in image_paths})
        listing = "\n".join(f"{i}: {p}" for i, p in enumerate(image_paths))
        args = ["--system-prompt", "你在帮旅行系统挑照片。只按要求读图、只输出被要求的 JSON。",
                "--tools", "Read", "--allowedTools", "Read", "--no-session-persistence"]
        for d in dirs:
            args += ["--add-dir", d]
        return self._run(f"逐张读取这些图片（用 Read 工具）：\n{listing}\n\n{prompt}", args)
