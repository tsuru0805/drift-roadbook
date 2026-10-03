import json
import subprocess

import pytest

from pianhang.narrators import NarratorError
from pianhang.narrators.claude_cli import ClaudeCLINarrator


def test_prompt_goes_in_on_stdin_never_as_an_argument(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["input"], seen["env"] = cmd, kw.get("input"), kw["env"]
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"result": "ok"}).encode(), stderr=b"")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    n = ClaudeCLINarrator(workdir=tmp_path / "w", binary="claude")
    assert n.complete("sys", "- 走进巷子") == "ok"
    assert "- 走进巷子" not in seen["cmd"] and seen["input"] == "- 走进巷子".encode()
    assert "CLAUDE_CODE_USE_BEDROCK" not in seen["env"]


@pytest.mark.parametrize("settings", [{"apiKeyHelper": "echo k"}, {"env": {"ANTHROPIC_API_KEY": "x"}},
                                      {"env": {"CLAUDE_CODE_USE_VERTEX": "1"}}])
def test_refuses_when_settings_route_to_paid_api(monkeypatch, tmp_path, settings):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps(settings))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("must not run"))
    with pytest.raises(NarratorError):
        ClaudeCLINarrator(workdir=tmp_path / "w").complete("s", "p")
