import asyncio

import pytest
from starlette.testclient import TestClient

from drift_roadbook import server
from drift_roadbook.engine import DriftEngine
from drift_roadbook.models import DriftRecord, Place, Temperature
from drift_roadbook.session_store import SessionStore
from drift_roadbook.storage_sqlite import SQLiteStorage


@pytest.fixture
def eng(tmp_path):
    st = SQLiteStorage(tmp_path / "d.db")
    st.save(DriftRecord(traveler="aki", date="2026-10-03", title="平江路茶坊", destination="苏州平江路的运河茶坊",
                        country="中国", city="苏州", travelogue="<b>游记</b>", luggage_item="空手",
                        temperature=Temperature(texture="安静", warmth=4),
                        place=Place(name="苏州", lat=31.3, lon=120.6, level="street")))
    return DriftEngine(storage=st, store=SessionStore(tmp_path / "s"), narrator=None, travelers={"aki": "Aki"})


def test_read_api_and_web(eng, monkeypatch):
    monkeypatch.setenv("ROADBOOK_HOME", "34.9858,135.7588,京都站")
    c = TestClient(server.build_http_app(eng, None), base_url="http://localhost")
    cfg = c.get("/api/config").json()
    assert cfg["home"] == {"lat": 34.9858, "lon": 135.7588, "label": "京都站"} and cfg["travelers"] == [{"id": "aki", "name": "Aki"}]
    rows = c.get("/api/drifts?traveler=aki").json()
    assert rows[0]["title"] == "平江路茶坊" and rows[0]["traveler_name"] == "Aki"
    assert rows[0]["place"]["level"] == "street" and rows[0]["luggage"]["item"] == "空手"
    assert c.get(f"/api/drifts/{rows[0]['id']}").json()["id"] == rows[0]["id"]
    assert c.get("/api/drifts/nope").status_code == 404
    assert c.get("/api/drifts?limit=x").status_code == 400
    assert "<canvas" in c.get("/").text or "roadbook" in c.get("/").text


def test_key_guards_api_and_mcp_but_not_page(eng):
    c = TestClient(server.build_http_app(eng, "s3cret"), base_url="http://localhost")
    assert c.get("/api/config").status_code == 401
    assert c.get("/api/config?key=wrong").status_code == 401
    assert c.get("/api/config?key=s3cret").status_code == 200
    assert c.get("/api/config", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert c.post("/mcp", json={}).status_code == 401
    assert c.get("/").status_code == 200


def test_mcp_tools_listed(eng):
    names = {t.name for t in asyncio.run(server.build_mcp(eng).list_tools())}
    assert names == {"start_drift", "drift_act", "finish_drift", "abandon_drift", "drift_status", "read_drifts"}


def test_refuses_public_bind_without_key(monkeypatch, tmp_path):
    monkeypatch.setenv("ROADBOOK_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ROADBOOK_NARRATOR", "none")
    monkeypatch.delenv("ROADBOOK_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        server.main(["serve", "--host", "0.0.0.0"])


def test_without_key_api_only_answers_as_localhost(eng):
    c = TestClient(server.build_http_app(eng, None), base_url="http://localhost")
    assert c.get("/api/config", headers={"host": "localhost:8790"}).status_code == 200
    assert c.get("/api/config", headers={"host": "evil.example"}).status_code == 403


def test_journal_reads_only_the_travelers_own_folder(tmp_path):
    from drift_roadbook.journal import JournalTemperature
    (tmp_path / "aki").mkdir()
    (tmp_path / "aki" / "d.md").write_text("aki 的日记", encoding="utf-8")
    (tmp_path / "shared.md").write_text("公共笔记", encoding="utf-8")
    (tmp_path.parent / "outside.md").write_text("目录外", encoding="utf-8")
    j = JournalTemperature(tmp_path)
    assert "aki 的日记" in j.collect("aki", "") and "公共笔记" not in j.collect("aki", "")
    assert j.collect("ren", "") is None
    assert j.collect("..", "") is None and j.collect("../x", "下雨") == "[出发时说] 下雨"
