"""Narrate through the Anthropic API (pay per use). `base_url` lets you point at a relay."""
from __future__ import annotations

import base64
import mimetypes

from . import NarratorError


class AnthropicNarrator:
    name = "anthropic-api"
    can_see_images = True

    def __init__(self, *, api_key: str, model: str = "claude-sonnet-5-5",
                 base_url: str | None = None, max_tokens: int = 2048, web_search: bool = True):
        try:
            import anthropic
        except ImportError:
            raise NarratorError("要用 API 模式请先 pip install anthropic") from None
        kw = {"api_key": api_key}
        if base_url:
            kw["base_url"] = base_url
        self._client = anthropic.Anthropic(**kw)
        self.model = model
        self.max_tokens = max_tokens
        self.allow_web_search = web_search

    def _call(self, system: str, messages: list[dict], tools: list | None = None) -> str:
        kw = dict(model=self.model, max_tokens=self.max_tokens, messages=messages)
        if system:
            kw["system"] = system
        if tools:
            kw["tools"] = tools
        try:
            msg = self._client.messages.create(**kw)
        except Exception as e:  # SDK raises many shapes; the traveler only needs the gist
            raise NarratorError(f"场景引擎出错（API）：{type(e).__name__}: {str(e)[:200]}") from None
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        if not text:
            raise NarratorError("场景引擎没有返回文字（API）")
        return text

    def complete(self, system: str, prompt: str, *, web_search: bool = False) -> str:
        tools = ([{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
                 if web_search and self.allow_web_search else None)
        return self._call(system, [{"role": "user", "content": prompt}], tools)

    def world(self, system: str, history: list[dict], new_input: str, state: dict) -> tuple[str, dict]:
        # first user turn = the arrival brief kept in state; then world/traveler alternate
        messages: list[dict] = []
        opening = state.get("opening")
        if opening is None:
            state = {**state, "opening": new_input}
            messages.append({"role": "user", "content": new_input})
        else:
            messages.append({"role": "user", "content": opening})
            for e in history:
                messages.append({"role": "assistant" if e["role"] == "world" else "user",
                                 "content": e["content"]})
            messages.append({"role": "user", "content": new_input})
        return self._call(system, messages), state

    def look(self, prompt: str, image_paths: list[str]) -> str:
        content: list[dict] = []
        for i, p in enumerate(image_paths):
            mt = mimetypes.guess_type(p)[0] or "image/jpeg"
            with open(p, "rb") as fh:
                data = base64.b64encode(fh.read()).decode()
            content.append({"type": "text", "text": f"{i}:"})
            content.append({"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}})
        content.append({"type": "text", "text": prompt})
        return self._call("", [{"role": "user", "content": content}])
