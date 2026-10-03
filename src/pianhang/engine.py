"""The drift engine: set off → a few rounds in the world → come home with a travelogue and one thing.

The core never changes: one traveler goes alone, walks a while, and comes back with something.
The traveler writes their own travelogue and picks what they bring back — the engine never
writes for them, never gives up on their behalf, and never loses a drift that wasn't finished.

Every call returns a `Receipt`. When something can't be done, the receipt says what and why,
and nothing is half-written.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from . import place as place_mod
from . import sources
from .models import Destination, DriftRecord, Place, Receipt, Temperature
from .narrators import NarratorError
from .photo import DEFAULT_RULES, PhotoFinder
from .ports import NullReminder, Reminder, Storage, TemperatureSource
from .prompts import PromptSet
from .session_store import SessionStore

EMPTY_HANDED = {"空手", "empty-handed", "empty handed", "nothing"}
MAX_LUGGAGE_CHARS = 30
MIN_TRAVELOGUE_CHARS = 20


def _json_from(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S) or re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in reply")
    return json.loads(m.group(1) if m.lastindex else m.group(0))


def _as_list(v) -> list:
    return v if isinstance(v, list) else []


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    from math import asin, cos, radians, sin, sqrt
    la1, lo1, la2, lo2 = map(radians, (*a, *b))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return 6371 * 2 * asin(sqrt(h))


class DriftEngine:
    def __init__(self, *, storage: Storage, store: SessionStore, narrator=None,
                 prompts: PromptSet | None = None, temperature: TemperatureSource | None = None,
                 reminder: Reminder | None = None, travelers: dict[str, str] | None = None,
                 photo_finder: PhotoFinder | None = None, min_rounds: int = 4, max_rounds: int = 10,
                 tz: str = "Asia/Tokyo", photo_async: bool = True,
                 on_photo: Callable[[str, str, Place | None], None] | None = None,
                 resolve_place: Callable[[str | None, str | None], Place] = place_mod.resolve):
        self.storage = storage
        self.store = store
        self.narrator = narrator              # None = host mode: the companion narrates the world
        self.prompts = prompts or PromptSet()
        self.temperature = temperature
        self.reminder = reminder or NullReminder()
        self.travelers = travelers or {}
        self.photos = photo_finder or PhotoFinder(narrator, rules=self.prompts.photo_rules or DEFAULT_RULES)
        self.min_rounds = min_rounds
        self.max_rounds = max_rounds
        self.tz = ZoneInfo(tz)
        self.photo_async = photo_async
        self.on_photo = on_photo
        self.resolve_place = resolve_place

    # ── helpers ─────────────────────────────────────────────────────────────

    def name(self, traveler: str) -> str:
        return self.travelers.get(traveler, traveler)

    def _check_traveler(self, traveler: str) -> Receipt | None:
        if not traveler or (self.travelers and traveler not in self.travelers):
            known = "、".join(self.travelers) or "任意非空 id"
            return Receipt(False, f"traveler 参数不对：{traveler!r}。可用：{known}。你是谁就传谁。")
        return None

    def _today(self) -> str:
        return datetime.now(self.tz).strftime("%Y-%m-%d")

    @staticmethod
    def _summary(session: dict) -> str:
        d = session["destination"]
        steps = [e for e in session["history"]]
        tail = "\n".join(f"{'【场景】' if e['role'] == 'world' else '【你】'}{e['content'][:120]}"
                         for e in steps[-4:])
        return (f"{session['date']} 出发去「{d['short_name']}」，走了 {session['round']} 轮，还没写游记。\n"
                f"最后几段：\n{tail}")

    def _last_line(self, traveler: str) -> str:
        last = self.store.get_last(traveler) or {}
        photo = last.get("photo")
        if not last or photo in (None, "searching") or last.get("photo_reported"):
            return ""
        last["photo_reported"] = True
        self.store.put_last(traveler, last)
        if photo == "found":
            return f"（上次「{last.get('short_name', '')}」的偏航：照片找到了，已放进路书。）\n"
        return f"（上次「{last.get('short_name', '')}」的偏航：没有找到合适的照片，路书上那一站不放图。）\n"

    # ── set off ─────────────────────────────────────────────────────────────

    def start(self, traveler: str, destination: str = "", mood: str = "") -> Receipt:
        if (bad := self._check_traveler(traveler)):
            return bad
        with self.store.locked(traveler):
            open_session = self.store.get(traveler)
            if open_session:
                return Receipt(False, (
                    "你上一次的偏航还没收尾，先把它写完再出发：\n\n" + self._summary(open_session) +
                    "\n\n写完就调用 finish_drift(travelogue=你的游记, luggage=带走的一样东西)。"
                    "不想要了，可以调用 abandon_drift(confirm=True) 放弃它——只有你自己能放弃。"),
                    {"unfinished": True})
            if self.narrator is None:
                return self._start_host(traveler, destination.strip(), mood)
            try:
                return self._start_narrated(traveler, destination.strip(), mood)
            except NarratorError as e:
                return Receipt(False, f"没能出发：{e}\n什么都没有记下，可以稍后再试一次。")

    def _read_temperature(self, traveler: str, mood: str) -> Temperature:
        raw = self.temperature.collect(traveler, mood) if self.temperature else (mood or None)
        if not raw:
            return Temperature()
        try:
            t = _json_from(self.narrator.complete(self.prompts.temperature, raw))
            w = t.get("warmth")
            return Temperature(texture=str(t.get("texture") or ""),
                               warmth=int(w) if isinstance(w, (int, float)) else None,
                               movement=str(t.get("movement") or ""),
                               season_feel=str(t.get("season_feel") or ""))
        except (ValueError, json.JSONDecodeError):
            return Temperature()

    def _avoid_text(self) -> str:
        kinds = self.store.recent_kinds()[-10:]
        names = []
        for r in self.storage.recent(None, 50):
            if r.title and r.title not in names:
                names.append(r.title)
        lines = []
        if kinds:
            lines.append("最近去过的地方类型和时段（这次别再是同一种地方、同一个时段）：")
            lines += [f"- {k.get('kind', '')} · {k.get('time_of_day', '')}" for k in kinds]
        if names:
            lines.append("这些地方已经去过，不要再选：" + "、".join(names))
        return "\n".join(lines)

    def _destination(self, wish: str, temp: Temperature) -> Destination:
        if wish:
            prompt = self.prompts.resolve_destination.format(wish=wish)
        else:
            prompt = self.prompts.pick_destination.format(
                texture=temp.texture or "（今天读不出来）", warmth=temp.warmth or "?",
                movement=temp.movement or "?", season_feel=temp.season_feel or "?",
                avoid=self._avoid_text())
        last_err = None
        for _ in range(2):
            try:
                d = _json_from(self.narrator.complete("", prompt))
                dest = Destination.from_dict({**d, "chosen_by": "self" if wish else "temperature"})
                if not dest.destination or not dest.short_name:
                    raise ValueError("missing destination/short_name")
                dest.search_queries = [q for q in _as_list(dest.search_queries) if isinstance(q, str)][:3]
                dest.photo_queries = [q for q in _as_list(dest.photo_queries) if isinstance(q, str)][:3]
                valid = place_mod.valid_coords(d.get("lat"), d.get("lon"))
                dest.approx = list(valid) if valid else None
                return dest
            except (ValueError, json.JSONDecodeError, TypeError) as e:
                last_err = e
        raise NarratorError(f"选址的回答看不懂（{last_err}）")

    def _luggage_text(self, traveler: str) -> str:
        items = [f"{r.luggage_item}（来自{r.title}，{r.date}）" for r in self.storage.recent(traveler, 5)
                 if r.luggage_item]
        return "；".join(items) or "空的"

    def _start_narrated(self, traveler: str, wish: str, mood: str) -> Receipt:
        temp = self._read_temperature(traveler, mood)
        dest = self._destination(wish, temp)
        try:
            fragments = self.narrator.complete("", self.prompts.sensory.format(
                destination=dest.destination,
                queries="\n".join(f"- {q}" for q in dest.search_queries) or f"- {dest.destination}"),
                web_search=True)
        except NarratorError:
            fragments = sources.material(dest.destination)[0] or f"（没搜到资料，请按你对{dest.destination}的了解来写）"
        luggage = self._luggage_text(traveler)
        arrival = self.prompts.arrival.format(
            destination=dest.destination, time_of_day=dest.time_of_day or "", reason=dest.reason,
            texture=temp.texture or "（没读出来）", fragments=fragments, luggage=luggage)
        scene, nstate = self.narrator.world(self.prompts.world, [], arrival, {})
        session = {
            "id": str(uuid.uuid4()), "traveler": traveler, "date": self._today(),
            "started_at": datetime.now(self.tz).isoformat(timespec="seconds"),
            "host_mode": False, "destination": dest.to_dict(),
            "temperature": temp.to_dict(), "history": [{"role": "world", "content": scene}],
            "round": 0, "narrator_state": nstate,
        }
        self.store.put(traveler, session)
        self.store.push_kind({"kind": dest.kind, "time_of_day": dest.time_of_day,
                              "short_name": dest.short_name, "date": session["date"]})
        self.reminder.opened(traveler, session["id"], f"偏航「{session['destination']['short_name']}」还没写游记")
        chosen = "你选的地方" if wish else "今天的温度选的地方"
        return Receipt(True, (
            self._last_line(traveler) +
            f"🧭 偏航开始 — {session['date']}\n旅行者：{self.name(traveler)}\n"
            + (f"温度：「{temp.texture}」warmth={temp.warmth}\n" if temp.texture else "")
            + f"目的地（{chosen}）：{dest.short_name}（{dest.country}）\n"
            + (f"理由：{dest.reason}\n" if dest.reason else "")
            + f"行李：{luggage}\n\n--- 场景 ---\n{scene}\n\n"
            f"你现在在这里。用第一人称决定接下来做什么，调用 drift_act(action=…)。"
            f"至少走 {self.min_rounds} 轮，最多 {self.max_rounds} 轮；"
            f"结束时调用 finish_drift，写下你自己的游记和带走的一样东西。"),
            {"destination": dest.to_dict(), "temperature": temp.to_dict()})

    def _start_host(self, traveler: str, wish: str, mood: str) -> Receipt:
        if not wish:
            return Receipt(False, (
                "这台偏航引擎没有接场景模型，由你自己来讲述旅途。"
                "先想好今天要去哪里——可以照着今天的心情选——再调用 start_drift(destination=…)。"))
        text, title = sources.material(wish)
        dest = Destination(destination=wish, short_name=wish[:12], place_en=title or "",
                           photo_queries=[title] if title else [], chosen_by="self")
        session = {
            "id": str(uuid.uuid4()), "traveler": traveler, "date": self._today(),
            "started_at": datetime.now(self.tz).isoformat(timespec="seconds"),
            "host_mode": True, "destination": dest.to_dict(),
            "temperature": Temperature(texture=mood[:20]).to_dict() if mood else Temperature().to_dict(),
            "history": [], "round": 0, "narrator_state": {},
        }
        self.store.put(traveler, session)
        self.reminder.opened(traveler, session["id"], f"偏航「{session['destination']['short_name']}」还没写游记")
        return Receipt(True, (
            self._last_line(traveler) +
            f"🧭 偏航开始 — {session['date']}\n旅行者：{self.name(traveler)}\n目的地：{wish}\n\n"
            f"--- 关于这里的资料 ---\n{text or '（没找到资料，按你知道的来）'}\n\n"
            f"这次由你自己来讲：每一步把你看到的和你做的一起写进 drift_act(action=…)。"
            f"至少 {self.min_rounds} 步，最多 {self.max_rounds} 步；"
            f"结束时调用 finish_drift，写下你的游记和带走的一样东西。"))

    # ── one step ────────────────────────────────────────────────────────────

    def act(self, traveler: str, action: str) -> Receipt:
        if (bad := self._check_traveler(traveler)):
            return bad
        if not (action or "").strip():
            return Receipt(False, "action 是空的：写下你接下来要做什么。")
        with self.store.locked(traveler):
            s = self.store.get(traveler)
            if not s:
                return Receipt(False, "现在没有进行中的偏航。要出发请调用 start_drift。")
            if s["round"] >= self.max_rounds:
                return Receipt(False, self.prompts.last_round.format(round=s["round"]) +
                               "\n调用 finish_drift(travelogue=…, luggage=…)。", {"round": s["round"]})
            rnd = s["round"] + 1
            if s.get("host_mode"):
                s["history"].append({"role": "traveler", "content": action})
                scene = ""
            else:
                try:
                    scene, s["narrator_state"] = self.narrator.world(
                        self.prompts.world, s["history"], action, s.get("narrator_state") or {})
                except NarratorError as e:
                    return Receipt(False, f"这一步没送到场景引擎：{e}\n偏航还在，原样再发一次这一步就行。")
                s["history"] += [{"role": "traveler", "content": action}, {"role": "world", "content": scene}]
            s["round"] = rnd
            self.store.put(traveler, s)
        hint = ""
        if rnd >= self.max_rounds:
            hint = self.prompts.last_round.format(round=rnd)
        elif rnd >= self.min_rounds:
            hint = self.prompts.round_hint.format(round=rnd)
        body = f"--- 第 {rnd} 轮 ---\n{scene}\n\n" if scene else f"（第 {rnd} 步记下了）\n\n"
        return Receipt(True, body + hint, {"round": rnd})

    # ── come home ───────────────────────────────────────────────────────────

    def finish(self, traveler: str, travelogue: str = "", luggage: str = "", note: str = "") -> Receipt:
        if (bad := self._check_traveler(traveler)):
            return bad
        travelogue = (travelogue or "").strip()
        luggage = (luggage or "").strip()
        with self.store.locked(traveler):
            s = self.store.get(traveler)
            if not s:
                return Receipt(False, "现在没有进行中的偏航，没有可以收尾的。")
            missing = []
            if len(travelogue) < MIN_TRAVELOGUE_CHARS:
                missing.append("travelogue（你自己写的游记）")
            if not luggage:
                missing.append("luggage（带走的一样东西，可以写「空手」）")
            if missing:
                return Receipt(False, "还不能收尾，缺：" + "、".join(missing) +
                               "。偏航先替你留着，写好再调用 finish_drift。", {"round": s["round"]})
            if len(luggage) > MAX_LUGGAGE_CHARS:
                return Receipt(False, f"带走的东西写短一点（{MAX_LUGGAGE_CHARS} 字以内），备注可以放进 note。偏航还留着。")
            if s["round"] < self.min_rounds:
                return Receipt(False, f"才走了 {s['round']} 轮，至少走 {self.min_rounds} 轮再收尾。偏航还留着。",
                               {"round": s["round"]})
            dest = s["destination"]
            temp = Temperature(**{k: s["temperature"].get(k) for k in Temperature.__dataclass_fields__})
            where = self._locate(dest)
            footer = self.prompts.footer.format(
                date=s["date"], short_name=dest["short_name"], name=self.name(traveler),
                texture=temp.texture or "—", luggage=luggage)
            record = DriftRecord(
                traveler=traveler, date=s["date"], title=dest["short_name"],
                destination=dest["destination"], travelogue=f"{travelogue}\n\n{footer}",
                luggage_item=luggage, luggage_note=(note or "").strip(), country=dest.get("country", ""),
                city=dest.get("city", ""), temperature=temp, place=where, rounds=s["round"])
            try:
                drift_id = self.storage.save(record)
            except Exception as e:
                return Receipt(False, f"游记没存进去：{type(e).__name__}: {str(e)[:200]}\n"
                                      "偏航还留着，你写的游记没丢——稍后再调用一次 finish_drift。")
            self.store.clear(traveler)
            self.store.put_last(traveler, {"drift_id": drift_id, "short_name": dest["short_name"],
                                           "photo": "searching"})
        self.reminder.closed(traveler, s["id"], True)
        record.id = drift_id
        self._photo(traveler, record, dest)
        level = {"spot": "具体地点", "street": "街道", "city": "城市"}.get(where.level or "", "")
        where_line = (f"定位：{where.name or dest['short_name']}（{level}）" if where.lat is not None
                      else "定位：没找到坐标，路书上这一站只显示文字")
        return Receipt(True, (
            f"🧭 偏航收好了 — {s['date']} · {dest['short_name']}\n"
            f"走了 {s['round']} 轮，带回来：{luggage}\n{where_line}\n"
            "照片在找，找到合适的会放进路书；没有合适的就不放。"),
            {"drift_id": drift_id, "short_name": dest["short_name"]})

    def _locate(self, dest: dict) -> Place:
        where = self.resolve_place(dest.get("place_en"), dest.get("city"))
        approx = dest.get("approx")
        # the narrator's own estimate refines a city-level fallback, if it lands near that city
        if approx and where.lat is not None and where.level == "city":
            if _distance_km((where.lat, where.lon), tuple(approx)) <= 30:
                where.lat, where.lon, where.level = approx[0], approx[1], "street"
        return where

    def _photo(self, traveler: str, record: DriftRecord, dest: dict) -> None:
        def work():
            place = record.place or Place(name=dest.get("city"))
            outcome = "none"
            try:
                spot = (place.lat, place.lon) if place.lat is not None and place.level in ("spot", "street") else None
                photo = self.photos.find(dest.get("photo_queries") or [], spot, record.travelogue)
                if photo:
                    place.image, place.image_page, place.image_credit = photo.image, photo.page, photo.credit
                    if photo.lat is not None and place.level != "spot":
                        place.lat, place.lon, place.level = photo.lat, photo.lon, photo.tier
                    self.storage.update_place(record.id, place)
                    outcome = "found"
            except Exception:
                outcome = "error"
            with self.store.locked(traveler):
                last = self.store.get_last(traveler) or {}
                if last.get("drift_id") == record.id:
                    last["photo"] = outcome
                    self.store.put_last(traveler, last)
            if self.on_photo:
                self.on_photo(traveler, outcome, place)

        if self.photo_async:
            threading.Thread(target=work, name="pianhang-photo", daemon=True).start()
        else:
            work()

    # ── give up / look ──────────────────────────────────────────────────────

    def abandon(self, traveler: str, confirm: bool = False) -> Receipt:
        if (bad := self._check_traveler(traveler)):
            return bad
        if not confirm:
            return Receipt(False, "放弃需要你明确确认：abandon_drift(confirm=True)。放弃后这次偏航不会留下记录。")
        with self.store.locked(traveler):
            s = self.store.get(traveler)
            if not s:
                return Receipt(False, "现在没有进行中的偏航。")
            self.store.clear(traveler)
        self.reminder.closed(traveler, s["id"], False)
        return Receipt(True, f"放弃了「{s['destination']['short_name']}」那次偏航，没有留下记录。")

    def status(self, traveler: str) -> Receipt:
        if (bad := self._check_traveler(traveler)):
            return bad
        s = self.store.get(traveler)
        if s:
            return Receipt(True, "进行中：\n" + self._summary(s), {"in_progress": True, "round": s["round"]})
        line = self._last_line(traveler)
        return Receipt(True, (line or "") + "现在没有进行中的偏航。", {"in_progress": False})

    def refind_photo(self, drift_id: str, photo_queries: list[str]) -> Receipt:
        """Search a photo again for an already stored drift (e.g. after improving the rules)."""
        rec = self.storage.get(drift_id)
        if not rec:
            return Receipt(False, f"找不到这次偏航：{drift_id}")
        place = rec.place or Place(name=rec.city)
        spot = (place.lat, place.lon) if place.lat is not None and place.level in ("spot", "street") else None
        photo = self.photos.find(photo_queries, spot, rec.travelogue)
        if not photo:
            place.image = place.image_page = place.image_credit = None
            self.storage.update_place(drift_id, place)
            return Receipt(True, "没有合适的照片，已清空这一站的图。", {"photo": None})
        place.image, place.image_page, place.image_credit = photo.image, photo.page, photo.credit
        if photo.lat is not None and place.level != "spot":
            place.lat, place.lon, place.level = photo.lat, photo.lon, photo.tier
        self.storage.update_place(drift_id, place)
        return Receipt(True, f"换上了：{photo.page}", {"photo": photo.image})
