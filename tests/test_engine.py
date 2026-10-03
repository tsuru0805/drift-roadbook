import json

import pytest

from pianhang.engine import DriftEngine
from pianhang.models import Place
from pianhang.narrators import NarratorError
from pianhang.narrators.claude_cli import ClaudeCLINarrator
from pianhang.photo import Photo
from pianhang.session_store import SessionStore
from pianhang.storage_sqlite import SQLiteStorage

DEST = {"destination": "苏州平江路的运河茶坊", "short_name": "平江路茶坊", "country": "中国", "city": "苏州",
        "place_en": "Pingjiang Road", "lat": 31.318, "lon": 120.632, "kind": "运河边茶馆",
        "time_of_day": "下午", "reason": "想听水声", "search_queries": ["平江路 游记"],
        "photo_queries": ["Pingjiang Road Suzhou", "Suzhou canal street"]}


class FakeNarrator:
    name = "fake"
    can_see_images = True

    def __init__(self):
        self.prompts = []
        self.fail_world = False

    def complete(self, system, prompt, *, web_search=False):
        self.prompts.append(prompt)
        if "情绪质地" in system:
            return '{"texture": "雨天关着窗的安静", "warmth": 4, "movement": "缓慢", "season_feel": "秋天的窗边"}'
        if web_search:
            return "青石板湿亮\n评弹声从茶馆里传出来"
        return json.dumps(DEST, ensure_ascii=False)

    def world(self, system, history, new_input, state):
        if self.fail_world:
            raise NarratorError("模拟断线")
        n = state.get("n", 0) + 1
        return f"场景{n}：{new_input[:10]}", {**state, "n": n}

    def look(self, prompt, paths):
        return '{"pick": 0}'


class FakePhotos:
    def __init__(self, photo=None):
        self.photo = photo
        self.calls = []

    def find(self, queries, spot, travelogue):
        self.calls.append((queries, spot))
        return self.photo


def fake_resolve(place_en, city):
    return Place(name=city, lat=31.30, lon=120.62, level="city", wiki="Suzhou")


@pytest.fixture
def make(tmp_path):
    def _make(narrator="fake", photos=None, storage=None, **kw):
        n = FakeNarrator() if narrator == "fake" else narrator
        return DriftEngine(storage=storage or SQLiteStorage(tmp_path / "d.db"),
                           store=SessionStore(tmp_path / "state"), narrator=n,
                           travelers={"aki": "Aki", "ren": "Ren"}, photo_finder=photos or FakePhotos(),
                           photo_async=False, resolve_place=fake_resolve, **kw), n
    return _make


TRAVELOGUE = "推开木门，茶已经凉了。三弦的声音从隔壁传来，我在桥上停了很久。"


def walk(engine, who, n):
    for i in range(n):
        assert engine.act(who, f"第{i + 1}步，我往前走").ok


def test_full_drift_is_written_by_the_traveler(make):
    e, n = make(photos=FakePhotos(Photo(image="https://upload.wikimedia.org/x.jpg",
                                        page="https://commons.wikimedia.org/wiki/File:x.jpg",
                                        credit="A · CC BY-SA 4.0", lat=31.318, lon=120.632)))
    r = e.start("aki", mood="下雨了")
    assert r.ok and "平江路茶坊" in r.text
    walk(e, "aki", 4)
    r = e.finish("aki", TRAVELOGUE, "三弦的声音", "她唱给没来的船")
    assert r.ok, r.text
    rec = e.storage.list("aki")[0]
    assert rec.travelogue.startswith(TRAVELOGUE)            # the traveler's words, untouched
    assert "「带走了：三弦的声音」" in rec.travelogue
    assert rec.luggage_item == "三弦的声音" and rec.rounds == 4
    assert rec.place.image.endswith("x.jpg") and rec.place.level == "spot"
    assert e.store.get("aki") is None
    assert "照片找到了" in e.status("aki").text


def test_two_travelers_drift_at_once_and_survive_restart(make, tmp_path):
    e, _ = make()
    assert e.start("aki").ok and e.start("ren").ok
    e2, _ = make()                                           # a fresh process, same state dir
    assert e2.act("aki", "我走到桥上").ok
    assert e2.act("ren", "我蹲下来看石板").ok
    assert e2.store.get("aki")["round"] == 1


def test_missing_travelogue_keeps_the_drift(make):
    e, _ = make()
    e.start("aki")
    walk(e, "aki", 4)
    r = e.finish("aki", "", "石子")
    assert not r.ok and "travelogue" in r.text
    assert e.store.get("aki") is not None
    assert e.finish("aki", TRAVELOGUE, "石子").ok


def test_unfinished_drift_blocks_next_start_with_a_summary(make):
    e, _ = make()
    e.start("aki")
    walk(e, "aki", 2)
    r = e.start("aki")
    assert not r.ok and r.data["unfinished"] and "平江路茶坊" in r.text and "finish_drift" in r.text


def test_round_gates(make):
    e, _ = make(max_rounds=5)
    e.start("aki")
    walk(e, "aki", 2)
    assert "至少走" in e.finish("aki", TRAVELOGUE, "石子").text
    walk(e, "aki", 3)
    r = e.act("aki", "再走一步")
    assert not r.ok and "该回去了" in r.text


def test_self_chosen_destination_uses_the_wish(make):
    e, n = make()
    e.start("aki", destination="我想去苏州的平江路")
    assert any("我想去苏州的平江路" in p for p in n.prompts)
    assert e.store.get("aki")["destination"]["chosen_by"] == "self"


def test_temperature_pick_avoids_recent_kinds(make):
    e, n = make()
    e.start("aki")
    walk(e, "aki", 4)
    e.finish("aki", TRAVELOGUE, "石子")
    e.start("ren")
    pick = [p for p in n.prompts if "选址引擎" in p][-1]
    assert "运河边茶馆" in pick and "平江路茶坊" in pick


def test_abandon_needs_explicit_confirm(make):
    e, _ = make()
    e.start("aki")
    assert not e.abandon("aki").ok and e.store.get("aki")
    assert e.abandon("aki", confirm=True).ok and e.store.get("aki") is None


def test_storage_failure_keeps_the_drift(make, tmp_path):
    class Broken(SQLiteStorage):
        def save(self, record):
            raise OSError("disk full")
    e, _ = make(storage=Broken(tmp_path / "b.db"))
    e.start("aki")
    walk(e, "aki", 4)
    r = e.finish("aki", TRAVELOGUE, "石子")
    assert not r.ok and "不用重写" in r.text and e.store.get("aki")


def test_narrator_failure_in_act_changes_nothing(make):
    e, n = make()
    e.start("aki")
    n.fail_world = True
    r = e.act("aki", "我走")
    assert not r.ok and "再发一次" in r.text
    assert e.store.get("aki")["round"] == 0


def test_city_fallback_refined_by_nearby_estimate_and_no_photo_reported(make):
    e, _ = make(photos=FakePhotos(None))
    e.start("aki")
    walk(e, "aki", 4)
    e.finish("aki", TRAVELOGUE, "空手")
    rec = e.storage.list("aki")[0]
    assert rec.place.level == "street" and rec.place.lat == 31.318 and rec.place.image is None
    assert "没有找到合适的照片" in e.start("aki").text


def test_host_mode_without_narrator(make, monkeypatch):
    monkeypatch.setattr("pianhang.sources.material", lambda place, **k: ("资料", "Pingjiang Road"))
    e, _ = make(narrator=None)
    assert not e.start("aki").ok                             # must name a destination itself
    assert e.start("aki", destination="平江路").ok
    walk(e, "aki", 4)
    assert e.finish("aki", TRAVELOGUE, "石子").ok


def test_unknown_traveler_rejected(make):
    e, _ = make()
    assert not e.start("someone").ok


def test_cli_env_never_carries_api_keys(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://proxy")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-y")
    env = ClaudeCLINarrator(workdir=tmp_path, oauth_token="tok")._env()
    assert not any("API_KEY" in k or "ANTHROPIC" in k for k in env)
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok"


def test_reminder_opens_and_closes_with_the_same_key(make):
    class Rec:
        def __init__(self):
            self.log = []

        def opened(self, traveler, key, summary):
            self.log.append(("open", traveler, key, summary))

        def closed(self, traveler, key, finished):
            self.log.append(("close", traveler, key, finished))
    rec = Rec()
    e, _ = make(reminder=rec)
    e.start("aki")
    walk(e, "aki", 4)
    e.finish("aki", TRAVELOGUE, "石子")
    e.start("ren")
    e.abandon("ren", confirm=True)
    (o1, t1, k1, s1), (c1, _, k1b, f1), (o2, _, k2, _), (c2, _, k2b, f2) = rec.log
    assert (o1, c1, o2, c2) == ("open", "close", "open", "close")
    assert k1 == k1b and k2 == k2b and k1 != k2 and f1 is True and f2 is False
    assert "平江路茶坊" in s1


def test_storage_failure_keeps_what_was_written(make, tmp_path):
    class Flaky(SQLiteStorage):
        fail = True

        def save(self, record):
            if Flaky.fail:
                raise OSError("disk full")
            return super().save(record)
    e, _ = make(storage=Flaky(tmp_path / "f.db"))
    e.start("aki")
    walk(e, "aki", 4)
    r = e.finish("aki", TRAVELOGUE, "石子", "捡的")
    assert not r.ok and "不用重写" in r.text
    assert e.store.get("aki")["draft"]["travelogue"] == TRAVELOGUE
    Flaky.fail = False
    assert e.finish("aki").ok                                  # no need to write it again
    rec = e.storage.list("aki")[0]
    assert rec.travelogue.startswith(TRAVELOGUE) and rec.luggage_item == "石子" and rec.luggage_note == "捡的"


def test_foreign_session_is_left_alone(make):
    e, _ = make()
    e.store.put("aki", {"mode": "fantasy", "universe": "u/x", "history": [], "round": 2})
    assert not e.start("aki").ok
    for r in (e.act("aki", "走"), e.finish("aki", TRAVELOGUE, "石子"), e.abandon("aki", confirm=True)):
        assert not r.ok and "不是这台引擎开的" in r.text
    assert e.store.get("aki")["mode"] == "fantasy"


def test_photo_error_and_interrupted_search_are_reported_as_such(make):
    class Boom:
        def find(self, *a, **k):
            raise RuntimeError("commons down")
    e, _ = make(photos=Boom())
    e.start("aki")
    walk(e, "aki", 4)
    e.finish("aki", TRAVELOGUE, "石子")
    assert "出错了" in e.status("aki").text and "commons down" in e.store.get_last("aki")["photo_error"]
    e.store.put_last("ren", {"drift_id": "x", "short_name": "某地", "photo": "searching", "photo_started": 0})
    assert "中断" in e.status("ren").text
