"""Who narrates the world.

- `ClaudeCLINarrator`  — your Claude subscription through the `claude` CLI (Claude Code).
- `AnthropicNarrator`  — an API key (and optionally a relay `base_url`).
- no narrator at all   — pass `narrator=None` to the engine: your own companion narrates the
  world itself, and the engine only gathers material (see engine docs, "host mode").
"""
from __future__ import annotations

from typing import Protocol


class NarratorError(RuntimeError):
    """The narrator could not answer. The message is safe to show to the traveler."""


class Narrator(Protocol):
    name: str
    can_see_images: bool

    def complete(self, system: str, prompt: str, *, web_search: bool = False) -> str:
        """One question, one answer."""

    def world(self, system: str, history: list[dict], new_input: str, state: dict) -> tuple[str, dict]:
        """Continue the world conversation. `history` is every earlier entry
        (`{"role": "world"|"traveler", "content": str}`); `state` is whatever this narrator
        stored last time (opaque, JSON-safe). Returns the new scene and the new state."""

    def look(self, prompt: str, image_paths: list[str]) -> str:
        """Look at local image files and answer. Only called when `can_see_images`."""


from .claude_cli import ClaudeCLINarrator  # noqa: E402
from .anthropic_api import AnthropicNarrator  # noqa: E402

__all__ = ["Narrator", "NarratorError", "ClaudeCLINarrator", "AnthropicNarrator"]
