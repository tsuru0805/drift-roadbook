// Roadbook: a map stage + timeline + stop list + detail view for drifts served by the engine's HTTP API.
// Plain browser script (no modules, no build) so the page also works when opened from file://.
// Needs land.js (window.PIANHANG_LAND). Data: /api/config + /api/drifts (docs/API.md), or demo/ with ?demo=1 / file://.
(() => {
"use strict";

// ═══ utils ═══════════════════════════════════════════════════════════════
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const pad2 = (n) => String(n).padStart(2, "0");
const ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const clip = (s, n) => { const a = Array.from(s); return a.length <= n ? s : a.slice(0, n).join("") + "…"; };
const str = (v) => (typeof v === "string" ? v.trim() : "");
const nowS = () => performance.now() / 1000;
const lsGet = (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable: render anyway */ } };
const safeUrl = (u) => { try { const x = new URL(u); return x.protocol === "https:" || x.protocol === "http:" ? x.href : null; } catch (e) { return null; } };
const rootStyle = getComputedStyle(document.documentElement);
const SANS = rootStyle.getPropertyValue("--sans").trim() || "sans-serif";

// ═══ theme: the one place colours are defined (CSS variables + the canvas read this same object) ═══
const THEME_KEY = "pianhang.roadbook.theme";
const hex2rgb = (h) => { h = h.replace("#", ""); if (h.length === 3) h = h.split("").map((c) => c + c).join(""); const n = parseInt(h, 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
const rgb2hex = (c) => "#" + c.map((v) => Math.round(clamp(v, 0, 255)).toString(16).padStart(2, "0")).join("");
const mix = (a, b, t) => { const x = hex2rgb(a), y = hex2rgb(b); return rgb2hex(x.map((v, i) => v + (y[i] - v) * t)); };
const lum = (h) => { const [r, g, b] = hex2rgb(h); return (0.299 * r + 0.587 * g + 0.114 * b) / 255; };
const A = (hex, a) => { const [r, g, b] = hex2rgb(hex); return `rgba(${r},${g},${b},${a})`; };

function derive(t) {
  const dark = lum(t.bg) < 0.5;
  const ink = t.ink || (dark ? "#ecebe6" : "#1c1b18");
  return {
    id: t.id, name: t.name, bg: t.bg, sig: t.sig, ink,
    dim: t.dim || mix(t.bg, ink, 0.5),
    faint: t.faint || mix(t.bg, ink, 0.25),
    pink2: t.pink2 || (dark ? mix(t.sig, "#ffffff", 0.78) : mix(t.sig, t.bg, 0.5)),
  };
}
const PRESETS = [
  derive({ id: "pinkblack", name: "粉黑", bg: "#0e0f0e", ink: "#ecebe6", dim: "#86857f", faint: "#4a4b45", sig: "#ff2f8e", pink2: "#ffd3e6" }),
  derive({ id: "mist", name: "雾蓝", bg: "#0b1118", sig: "#5cb4ff" }),
  derive({ id: "moss", name: "苔绿", bg: "#0c120e", sig: "#7ce0a3" }),
  derive({ id: "amber", name: "琥珀", bg: "#14100b", sig: "#ffb347" }),
  derive({ id: "paper", name: "纸白", bg: "#f2efe7", sig: "#d9246f" }),
];
let theme = PRESETS[0];
let themeVer = 0;

function applyTheme(t, persist) {
  theme = t; themeVer += 1;
  const s = document.documentElement.style;
  s.setProperty("--bg", t.bg); s.setProperty("--ink", t.ink); s.setProperty("--dim", t.dim);
  s.setProperty("--faint", t.faint); s.setProperty("--sig", t.sig); s.setProperty("--pink2", t.pink2);
  s.setProperty("--bg-rgb", hex2rgb(t.bg).join(", ")); s.setProperty("--ink-rgb", hex2rgb(t.ink).join(", ")); s.setProperty("--sig-rgb", hex2rgb(t.sig).join(", "));
  const m = document.querySelector('meta[name="theme-color"]'); if (m) m.setAttribute("content", t.bg);
  if (persist) lsSet(THEME_KEY, JSON.stringify(t.id === "custom" ? { id: "custom", sig: t.sig, bg: t.bg } : { id: t.id }));
  syncPicker();
}
function loadTheme() {
  try {
    const o = JSON.parse(lsGet(THEME_KEY) || "null");
    if (o && o.id === "custom" && /^#[0-9a-f]{6}$/i.test(o.sig) && /^#[0-9a-f]{6}$/i.test(o.bg)) return derive({ id: "custom", name: "自定义", sig: o.sig, bg: o.bg });
    if (o) { const p = PRESETS.find((x) => x.id === o.id); if (p) return p; }
  } catch (e) { /* ignore */ }
  return PRESETS[0];
}

// ═══ geo ════════════════════════════════════════════════════════════════
const PROJ_K = Math.cos((38 * Math.PI) / 180);   // keep equal to the constant used to pre-project land.js
const proj = (p) => ({ x: (p.lon + 180) * PROJ_K, y: 90 - p.lat });
const rad = (x) => (x * Math.PI) / 180;
function haversine(a, b) {
  const dl = rad(b.lat - a.lat), dn = rad(b.lon - a.lon);
  const h = Math.sin(dl / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dn / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(h)));
}
const validLatLon = (lat, lon) => typeof lat === "number" && typeof lon === "number" && Number.isFinite(lat) && Number.isFinite(lon)
  && lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180;

// ═══ stops: API drift → stop, assembled into one road ═══════════════════════
function toParas(text) {
  return str(text) ? text.split(/\n+/).map((s) => s.trim()).filter(Boolean) : [];
}

function draftFromDrift(f) {
  if (!f || typeof f !== "object") throw new Error("not an object");
  const id = str(f.id); if (!id) throw new Error("no id");
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(str(f.date)); if (!m) throw new Error("bad date");
  const ts = Date.UTC(+m[1], +m[2] - 1, +m[3], 12);
  const place = f.place && typeof f.place === "object" ? f.place : null;
  const coords = !!place && validLatLon(place.lat, place.lon);
  const dest = str(f.destination);
  const body = toParas(f.travelogue);
  const tex = f.temperature && typeof f.temperature === "object" ? str(f.temperature.texture) : "";
  const warm = f.temperature && typeof f.temperature.warmth === "number" ? f.temperature.warmth : null;
  const lug = f.luggage && typeof f.luggage === "object" && str(f.luggage.item) ? { item: str(f.luggage.item), note: str(f.luggage.note) } : null;
  const imgSrc = place ? safeUrl(place.image) : null;
  return {
    id: "d:" + id, ts, date: m[0],
    title: str(f.title) || clip(dest, 16) || "未命名偏航",
    excerpt: tex || clip(body[0] || dest, 60),
    body, dest, city: str(place && place.name) || str(f.city) || null,
    level: place && ["spot", "street", "city"].includes(place.level) ? place.level : "spot",
    image: imgSrc ? { src: imgSrc, page: safeUrl(place.image_page), credit: str(place.image_credit) } : null,
    onMap: coords, at: coords ? { lat: place.lat, lon: place.lon } : null,
    texture: tex, warmth: warm, luggage: lug,
  };
}

/** Oldest-first accumulation of distance; returns newest-first stops. `origin` = where the road starts. */
function assemble(drafts, origin) {
  const asc = drafts.slice().sort((a, b) => a.ts - b.ts || a.id.localeCompare(b.id));
  let prev = origin, cum = 0;
  const out = asc.map((d, i) => {
    const to = d.onMap && d.at ? d.at : prev;
    const part = d.onMap && d.at ? haversine(prev, to) : 0;
    cum += part;
    const s = Object.assign({}, d, { seq: i + 1, from: prev, to, part, cum });
    prev = to;
    return s;
  });
  return out.reverse();
}

const matches = (s, city, q) => {
  if (city && s.city !== city) return false;
  const k = q.trim().toLowerCase();
  if (!k) return true;
  const hay = [s.title, s.excerpt, s.dest, s.city || "", s.texture, s.luggage ? s.luggage.item + "\n" + s.luggage.note : "", ...s.body].join("\n").toLowerCase();
  return hay.includes(k);
};
function cityStamps(stops) {
  const m = new Map();
  for (const s of stops) {
    if (!s.city) continue;
    const e = m.get(s.city) || { n: 0, last: 0 };
    e.n += 1; e.last = Math.max(e.last, s.ts); m.set(s.city, e);
  }
  return [...m.entries()].map(([city, e]) => ({ city, n: e.n, last: e.last })).sort((a, b) => b.n - a.n || b.last - a.last);
}
const monthOf = (s) => s.date.slice(0, 7);
function timelinePos(stops) {
  if (!stops.length) return () => 0;
  const t0 = Math.min(...stops.map((s) => s.ts)), t1 = Math.max(...stops.map((s) => s.ts)), span = Math.max(1, t1 - t0);
  return (s) => (s.ts - t0) / span;
}
function nearestOnTimeline(stops, x, pos) {
  let best = null, bd = Infinity;
  for (const s of stops) { const d = Math.abs(pos(s) - x); if (d < bd) { bd = d; best = s; } }
  return best;
}
function nextAtPlace(stops, city, currentId) {
  const group = stops.filter((s) => s.onMap && s.city === city);
  if (!group.length) return null;
  const i = group.findIndex((s) => s.id === currentId);
  return i < 0 ? group[0] : group[(i + 1) % group.length];
}

// ═══ stage maths (camera / photo placement / hit test) ═══════════════════════
const ANCHOR_Y = 0.56, Z_MIN = 1.2, TOP_SAFE = 34, BOTTOM_SAFE = 58;
const Z_BY_LEVEL = { spot: 26, street: 14, city: 8 };   // closer zoom for exact places, wider for city-level fallbacks

function clampCam(c, H) {
  const top = (H * ANCHOR_Y - TOP_SAFE) / c.z, bottom = (H * (1 - ANCHOR_Y) - BOTTOM_SAFE * 0.3) / c.z;
  const yMin = 6 + top, yMax = 148 - bottom;
  const y = yMin <= yMax ? Math.min(yMax, Math.max(yMin, c.y)) : (yMin + yMax) / 2;
  return { x: c.x, y, z: c.z };
}
/** One trip: frame from → to. Off-map / zero-length: pull back and frame everything walked so far. */
function cameraFor(s, ascUpTo, W, H, home) {
  const usableH = H - TOP_SAFE - BOTTOM_SAFE;
  if (!s.onMap || s.part < 1) {
    const pts = (home ? [home] : []).concat(ascUpTo.filter((x) => x.onMap && x.at).map((x) => x.at)).map(proj);
    if (!pts.length) return { x: 142, y: 60, z: Math.max(Z_MIN, W / 284) };
    const x0 = Math.min(...pts.map((p) => p.x)), x1 = Math.max(...pts.map((p) => p.x));
    const y0 = Math.min(...pts.map((p) => p.y)), y1 = Math.max(...pts.map((p) => p.y));
    const z = Math.min(8, (W * 0.8) / Math.max(x1 - x0, 1), (usableH * 0.7) / Math.max(y1 - y0, 1));
    return clampCam({ x: (x0 + x1) / 2, y: (y0 + y1) / 2 + (y1 - y0) * 0.06, z: Math.max(Z_MIN, z) }, H);
  }
  const a = proj(s.from), b = proj(s.to);
  const span = Math.max(Math.abs(a.x - b.x), Math.abs(a.y - b.y) * (W / usableH), 6);
  const zMax = Z_BY_LEVEL[s.level] || 26;
  return clampCam({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: Math.min(zMax, Math.max(Z_MIN, (W * 0.46) / span)) }, H);
}
function toScreen(p, cam, W, H) {
  const q = proj(p);
  return { x: W * 0.5 + (q.x - cam.x) * cam.z, y: H * ANCHOR_Y + (q.y - cam.y) * cam.z };
}
const SHAPES = [[0.42, 1.25], [0.5, 0.78], [0.38, 1], [0.44, 1.33], [0.52, 0.7]];
/** Photo sits on the far side of the point; computed from the camera TARGET (the camera may still be flying). */
function placePhoto(s, cam, W, H) {
  const p = toScreen(s.to, cam, W, H);
  const [wr, ar] = SHAPES[s.seq % SHAPES.length];
  let w = W * wr;
  const h = Math.min((H - TOP_SAFE - BOTTOM_SAFE) * 0.78, w * ar);
  w = h / ar;
  const left = p.x > W / 2;
  const x = left ? 16 + ((s.seq * 13) % 20) : W - 16 - w - ((s.seq * 17) % 20);
  const top = p.y > (TOP_SAFE + H - BOTTOM_SAFE) / 2;
  const y = top ? TOP_SAFE + 8 + ((s.seq * 7) % 14) : H - BOTTOM_SAFE - h - 8 - ((s.seq * 11) % 12);
  return { x, y, w, h, ax: left ? 1 : 0, ay: top ? 1 : 0, tilt: (((s.seq * 7) % 9) - 4) * 0.6 };
}
function hitCity(stops, cam, W, H, tx, ty) {
  let best = null, bd = 22;
  for (const s of stops) {
    if (!s.onMap || !s.at || !s.city) continue;
    const p = toScreen(s.at, cam, W, H), d = Math.hypot(p.x - tx, p.y - ty);
    if (d < bd) { bd = d; best = s.city; }
  }
  return best;
}

// ═══ data loading (config + drifts; each route reports its own failure) ═══════
const params = new URLSearchParams(location.search);
const KEY = params.get("key");
const DEMO = params.get("demo") === "1" || location.protocol === "file:";
const PAGE = 200, MAX_PAGES = 10;

function withKey(path) {
  if (KEY == null) return path;
  return path + (path.includes("?") ? "&" : "?") + "key=" + encodeURIComponent(KEY);
}
async function getJSON(path, forwardKey = true) {
  let r;
  try { r = await fetch(forwardKey ? withKey(path) : path, { headers: { Accept: "application/json" } }); }
  catch (e) { throw new Error("连不上"); }
  let body = null;
  try { body = await r.json(); } catch (e) { /* not json */ }
  if (!r.ok) throw new Error(`HTTP ${r.status}${body && typeof body.error === "string" ? " · " + body.error : ""}`);
  if (body == null) throw new Error("回包不是 JSON");
  return body;
}
function loadScript(src) {
  return new Promise((res, rej) => { const s = document.createElement("script"); s.src = src; s.onload = res; s.onerror = () => rej(new Error("demo/demo.js 没载入")); document.head.appendChild(s); });
}
/** demo/config.json or demo/drifts.json. file:// pages cannot fetch() local files, so there the generated mirror demo/demo.js is used. */
async function demoJSON(name) {
  if (location.protocol === "file:") {
    if (!window.PIANHANG_DEMO) await loadScript("demo/demo.js");
    const v = window.PIANHANG_DEMO && window.PIANHANG_DEMO[name];
    if (v == null) throw new Error(`demo/${name} 缺失`);
    return v;
  }
  return getJSON(`demo/${name}.json`, false);
}

async function fetchConfig() {
  return DEMO ? demoJSON("config") : getJSON("/api/config");
}
async function fetchDrifts(traveler) {
  if (DEMO) {
    const all = await demoJSON("drifts");
    if (!Array.isArray(all)) throw new Error("回包不是列表");
    return traveler ? all.filter((x) => x && x.traveler === traveler) : all;
  }
  const out = [];
  for (let pg = 0; pg < MAX_PAGES; pg++) {
    const q = `/api/drifts?${traveler ? "traveler=" + encodeURIComponent(traveler) + "&" : ""}limit=${PAGE}&offset=${pg * PAGE}`;
    const page = await getJSON(q);
    if (!Array.isArray(page)) throw new Error("回包不是列表");
    out.push(...page);
    if (page.length < PAGE) break;
  }
  return out;
}

// ═══ state ══════════════════════════════════════════════════════════════
const errs = new Map();                       // route label → message (shown verbatim on the page)
const state = {
  config: null, home: null, travelers: [], traveler: null,
  all: [], asc: [], ascIndex: new Map(), visible: [], visibleSet: new Set(),
  city: null, q: "", activeId: null, loaded: false, origin: null,
};
let loadGen = 0, goGen = 0;

function renderErrors() {
  const box = $("errs"); box.textContent = "";
  for (const m of errs.values()) box.appendChild(el("div", null, m));
}

async function load() {
  const mine = ++loadGen;
  resetStage();
  state.loaded = false; state.all = []; state.activeId = null; state.city = null;
  recompute(); renderAll();
  errs.delete("偏航"); errs.delete("偏航格式");
  let drifts = [];
  try { drifts = await fetchDrifts(state.traveler); }
  catch (e) { errs.set("偏航", `偏航没取到(${e instanceof Error ? e.message : "未知错误"})`); }
  if (mine !== loadGen) return;
  const drafts = []; let bad = 0; const seen = new Set();
  for (const f of drifts) {
    try { const d = draftFromDrift(f); if (!seen.has(d.id)) { seen.add(d.id); drafts.push(d); } } catch (e) { bad += 1; }
  }
  if (bad) errs.set("偏航格式", `偏航有 ${bad} 条格式不对,没显示`);
  const firstAt = drafts.filter((d) => d.onMap).sort((a, b) => a.ts - b.ts)[0];
  state.origin = state.home || (firstAt ? firstAt.at : { lat: 20, lon: 0 });   // road start: config home, else the first stop
  state.all = assemble(drafts, state.origin);
  state.loaded = true;
  recompute(); renderAll();
}

function recompute() {
  const s = state;
  s.asc = s.all.slice().reverse();
  s.ascIndex = new Map(s.asc.map((x, i) => [x.id, i]));
  s.visible = s.all.filter((x) => matches(x, s.city, s.q));
  s.visibleSet = new Set(s.visible.map((x) => x.id));
  s.pos = timelinePos(s.all);
}

// ═══ stage (Canvas 2D) ══════════════════════════════════════════════════
const cv = $("cv"), ctx = cv.getContext("2d");
const LAND = new Path2D(window.PIANHANG_LAND || "");
const CAN_FILTER = ctx && "filter" in ctx;
const S = {
  W: 0, H: 0, dpr: 1,
  cam: { x: 142, y: 60, z: 1.4 }, camT: { x: 142, y: 60, z: 1.4 },
  seg: 1, a: -1,
  photo: { img: null, rect: null, t0: 0 }, ghost: { img: null, rect: null, t0: 0 },
  points: [], labels: [], homeP: null, homeLabel: "",
  running: false, last: 0, landCv: null, landKey: "",
  cumStart: [], parts: [], scratch: document.createElement("canvas"),
};

function resetStage() {
  goGen += 1; S.a = -1; S.seg = 1;
  S.photo = { img: null, rect: null, t0: 0 }; S.ghost = { img: null, rect: null, t0: 0 };
  hideCard();
}
function sizeStage() {
  const st = $("stage"), W = st.clientWidth, H = st.clientHeight;
  if (!W || !H) return false;
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  if (W === S.W && H === S.H && dpr === S.dpr) return false;
  S.W = W; S.H = H; S.dpr = dpr;
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  S.landKey = "";
  return true;
}

function updateStageData() {
  const { asc, visibleSet, home } = state;
  S.points = asc.map((x) => { const p = proj(x.to); return { x: p.x, y: p.y, on: x.onMap, dim: !visibleSet.has(x.id) }; });
  S.labels = asc.map((x, i) => (x.onMap && x.city ? { ...proj(x.to), text: x.city, dim: !visibleSet.has(x.id), asc: i } : null)).filter(Boolean);
  S.homeP = home ? proj(home) : null;
  S.homeLabel = home && home.label ? home.label : "";
  S.cumStart = asc.map((x) => x.cum - x.part);
  S.parts = asc.map((x) => x.part);
}

// photo loading: try CORS-clean first (needed for the mosaic/tone effect), else plain (drawn without the effect)
const imgCache = new Map();
function loadImage(src) {
  if (imgCache.has(src)) return imgCache.get(src);
  const attempt = (cors) => new Promise((res) => {
    const im = new Image();
    if (cors) im.crossOrigin = "anonymous";
    im.referrerPolicy = "no-referrer";
    im.onload = () => res({ img: im, cors });
    im.onerror = () => res(null);
    im.src = src;
  });
  const p = attempt(true).then((r) => r || attempt(false));
  imgCache.set(src, p);
  if (imgCache.size > 24) imgCache.delete(imgCache.keys().next().value);
  p.then((v) => { if (!v) imgCache.delete(src); });
  return p;
}

function drawLandLayer(c, W, H, dpr) {
  const k = `${c.x.toFixed(3)}|${c.y.toFixed(3)}|${c.z.toFixed(3)}|${W}|${H}|${dpr}|${themeVer}`;
  if (k === S.landKey && S.landCv) return S.landCv;
  if (!S.landCv) S.landCv = document.createElement("canvas");
  const lc = S.landCv; lc.width = Math.round(W * dpr); lc.height = Math.round(H * dpr);
  const g = lc.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const sx = (x) => W * 0.5 + (x - c.x) * c.z, sy = (y) => H * ANCHOR_Y + (y - c.y) * c.z;
  // graticule: 10 deg (plus 5 deg when zoomed in)
  const lonAt = (px) => ((px - W * 0.5) / c.z + c.x) / PROJ_K - 180, latAt = (py) => 90 - ((py - H * ANCHOR_Y) / c.z + c.y);
  const L0 = lonAt(0), L1 = lonAt(W), T0 = latAt(0), T1 = latAt(H);   // grid keeps going past the poles so a tall stage never shows a bare band
  g.lineWidth = 1;
  const steps = c.z > 9 ? [10, 5] : [10];
  steps.forEach((st, si) => {
    g.strokeStyle = A(theme.ink, si === 0 ? 0.06 : 0.03);
    g.beginPath();
    for (let lon = Math.floor(L0 / st) * st; lon <= L1; lon += st) { const x = Math.round(sx((lon + 180) * PROJ_K)) + 0.5; g.moveTo(x, sy(90 - T0)); g.lineTo(x, sy(90 - T1)); }
    for (let lat = Math.ceil(T1 / st) * st; lat <= T0; lat += st) { const y = Math.round(sy(90 - lat)) + 0.5; g.moveTo(0, y); g.lineTo(W, y); }
    g.stroke();
  });
  // land: filled + hairline edge
  g.save();
  g.translate(W * 0.5 - c.x * c.z, H * ANCHOR_Y - c.y * c.z);
  g.scale(c.z, c.z);
  g.fillStyle = A(theme.ink, 0.06); g.fill(LAND);
  g.strokeStyle = A(theme.ink, 0.22); g.lineWidth = 1 / (c.z * dpr); g.lineJoin = "round";
  g.stroke(LAND);
  g.restore();
  S.landKey = k;
  return lc;
}

function drawPhoto(g, ps, alpha, isGhost, now) {
  const r = ps.rect;
  if (!r || !ps.img) return;
  const age = now - ps.t0;
  const rv = ease(isGhost ? 1 : clamp((age - 0.35) / 1.0, 0, 1));
  if (rv <= 0 || alpha <= 0) return;
  const cw = r.w * rv, ch = r.h * rv;
  const cx0 = r.ax ? r.x + r.w - cw : r.x, cy0 = r.ay ? r.y + r.h - ch : r.y;
  const B = 5;
  g.save();
  g.translate(r.x + r.w / 2, r.y + r.h / 2);
  g.rotate((((r.tilt || 0) * Math.PI) / 180));
  g.translate(-(r.x + r.w / 2), -(r.y + r.h / 2));
  // white sticker border with a drop shadow that appears with the unfolding
  g.save();
  g.globalAlpha = alpha;
  g.shadowColor = `rgba(0,0,0,${(0.55 * alpha * rv).toFixed(3)})`;
  g.shadowBlur = 16 * S.dpr; g.shadowOffsetX = 2 * S.dpr; g.shadowOffsetY = 6 * S.dpr;
  g.fillStyle = "#ffffff";
  g.fillRect(cx0 - B, cy0 - B, cw + 2 * B, ch + 2 * B);
  g.restore();
  g.beginPath(); g.rect(cx0 - B, cy0 - B, cw + 2 * B, ch + 2 * B); g.clip();
  g.globalAlpha = alpha;
  g.fillStyle = "#ffffff"; g.fillRect(cx0 - B, cy0 - B, cw + 2 * B, ch + 2 * B);
  // "developing" photo: coarse pixels → sharp, grey + over-exposed → colour
  const im = ps.img, iw = im.naturalWidth, ih = im.naturalHeight;
  const s = Math.max(r.w / iw, r.h / ih), sw = r.w / s, sh = r.h / s, sx0 = (iw - sw) / 2, sy0 = (ih - sh) / 2;
  const dv = isGhost ? 1 : clamp((age - 0.35) / 1.6, 0, 1);
  const de = 1 - Math.pow(1 - dv, 3);
  const fx = ps.cors !== false;                                   // effect needs a clean (CORS) image on most browsers
  const cell = fx ? Math.max(1, Math.round(42 * Math.pow(1 - de, 2.2))) : 1;
  const mono = isGhost ? 1 : 1 - de, expo = isGhost ? 0 : 1.4 * (1 - de);
  if (CAN_FILTER && fx && (mono > 0.01 || expo > 0.01)) g.filter = `grayscale(${mono.toFixed(3)}) brightness(${(1 + expo).toFixed(3)})`;
  if (cell > 1) {
    const tw = Math.max(1, Math.ceil(r.w / cell)), th = Math.max(1, Math.ceil(r.h / cell));
    const sc = S.scratch; sc.width = tw; sc.height = th;
    const sg = sc.getContext("2d"); sg.imageSmoothingEnabled = true;
    sg.drawImage(im, sx0, sy0, sw, sh, 0, 0, tw, th);
    g.imageSmoothingEnabled = false;
    g.drawImage(sc, 0, 0, tw, th, r.x, r.y, tw * cell, th * cell);
    g.imageSmoothingEnabled = true;
  } else {
    g.drawImage(im, sx0, sy0, sw, sh, r.x, r.y, r.w, r.h);
  }
  g.filter = "none";
  if (!isGhost && de > 0 && de < 1) {                              // scan line
    const ly = r.y + r.h * de;
    g.globalAlpha = 0.85 * alpha; g.fillStyle = theme.sig; g.fillRect(r.x, ly, r.w, 1.5);
    g.globalAlpha = 0.6 * alpha; g.fillStyle = theme.bg; g.fillRect(r.x, ly + 1.5, r.w, r.y + r.h - ly - 1.5);
  }
  g.restore();
}

function drawStage(now, dt) {
  const { W, H, dpr } = S;
  // camera / segment progress
  const c0 = S.cam, t = S.camT, k = 1 - Math.exp(-dt * 3.2);
  S.cam = { x: c0.x + (t.x - c0.x) * k, y: c0.y + (t.y - c0.y) * k, z: c0.z + (t.z - c0.z) * k };
  if (S.seg < 1) S.seg = Math.min(1, S.seg + dt / 1.3);
  const c = S.cam;
  const sx = (x) => W * 0.5 + (x - c.x) * c.z, sy = (y) => H * ANCHOR_Y + (y - c.y) * c.z;

  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.drawImage(drawLandLayer(c, W, H, dpr), 0, 0);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const a = S.a, pts = S.points, n = pts.length;
  const hx = S.homeP ? sx(S.homeP.x) : n ? sx(pts[0].x) : 0, hy = S.homeP ? sy(S.homeP.y) : n ? sy(pts[0].y) : 0;
  if (n) {
    // whole planned route (dashed), walked path, current segment
    ctx.lineWidth = 1; ctx.strokeStyle = A(theme.ink, 0.18); ctx.setLineDash([2, 4]);
    ctx.beginPath(); ctx.moveTo(hx, hy); for (let i = 0; i < n; i++) ctx.lineTo(sx(pts[i].x), sy(pts[i].y)); ctx.stroke();
    ctx.setLineDash([]);
  }
  let headX = hx, headY = hy;
  for (let i = 0; i <= a && i < n; i++) {
    const fx = i === 0 ? hx : sx(pts[i - 1].x), fy = i === 0 ? hy : sy(pts[i - 1].y);
    const tx = sx(pts[i].x), ty = sy(pts[i].y), cur = i === a;
    const e = cur ? ease(S.seg) : 1;
    const qx = fx + (tx - fx) * e, qy = fy + (ty - fy) * e;
    ctx.strokeStyle = cur ? theme.sig : A(theme.pink2, 0.3);
    ctx.lineWidth = cur ? 1.6 : 1;
    ctx.beginPath(); ctx.moveTo(fx, fy); ctx.lineTo(qx, qy); ctx.stroke();
    if (cur) { headX = qx; headY = qy; }
  }
  // stops
  for (let i = 0; i < n; i++) {
    const pt = pts[i];
    if (!pt.on || i === a) continue;
    ctx.fillStyle = pt.dim ? A(theme.ink, 0.1) : i <= a ? A(theme.ink, 0.8) : A(theme.ink, 0.35);
    ctx.beginPath(); ctx.arc(sx(pt.x), sy(pt.y), 2, 0, Math.PI * 2); ctx.fill();
  }
  // city names (collision-checked; the current one is placed first and brightest)
  const boxes = [];
  const place = (txt, x, y, hi, dim) => {
    ctx.font = hi ? `500 11.5px ${SANS}` : `10px ${SANS}`;
    const w = ctx.measureText(txt).width;
    const bx = x + 7, by = y - 8, bw = w + 4, bh = 13;
    if (bx > W || bx + bw < 0 || by < 30 || by > H - 50) return;
    if (!hi) for (let j = 0; j < boxes.length; j += 4) {
      if (bx < boxes[j] + boxes[j + 2] && bx + bw > boxes[j] && by < boxes[j + 1] + boxes[j + 3] && by + bh > boxes[j + 1]) return;
    }
    boxes.push(bx, by, bw, bh);
    ctx.fillStyle = hi ? theme.ink : dim ? A(theme.ink, 0.15) : A(theme.ink, 0.5);
    ctx.fillText(txt, x + 8, y + 3.5);
  };
  ctx.textBaseline = "alphabetic";
  for (const l of S.labels) if (l.asc === a) place(l.text, sx(l.x), sy(l.y), true, false);
  for (let i = S.labels.length - 1; i >= 0; i--) { const l = S.labels[i]; if (l.asc !== a) place(l.text, sx(l.x), sy(l.y), false, l.dim); }
  // home
  if (S.homeP) {
    ctx.strokeStyle = A(theme.ink, 0.7); ctx.lineWidth = 1;
    ctx.strokeRect(hx - 3.5, hy - 3.5, 7, 7);
    if (S.homeLabel) { ctx.font = `10px ${SANS}`; ctx.fillStyle = A(theme.ink, 0.6); ctx.fillText(S.homeLabel, hx + 8, hy + 3.5); }
  }
  // photo (previous one fades out; current one unfolds + develops), leader line, signal dot
  const gh = S.ghost;
  if (gh.rect) { const ga = 1 - Math.min(1, (now - gh.t0) / 0.9); if (ga > 0) drawPhoto(ctx, gh, ga, true, now); }
  const ph = S.photo;
  drawPhoto(ctx, ph, 1, false, now);
  if (a >= 0 && ph.rect) {
    const r = ph.rect, cx = r.x + (r.ax ? r.w : 0), cy = r.y + (r.ay ? r.h : 0);
    const le = 1 - Math.pow(1 - clamp((now - ph.t0) / 0.7, 0, 1), 3);
    ctx.strokeStyle = A(theme.ink, 0.55); ctx.lineWidth = 1; ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(headX, headY); ctx.lineTo(headX + (cx - headX) * le, headY + (cy - headY) * le); ctx.stroke();
    ctx.setLineDash([]);
    if (le > 0.98) { ctx.fillStyle = theme.sig; ctx.beginPath(); ctx.arc(cx, cy, 2.4, 0, Math.PI * 2); ctx.fill(); }
  }
  if (a >= 0) {
    const kk = (now / 1.6) % 1;
    ctx.strokeStyle = A(theme.sig, 0.45 * (1 - kk)); ctx.lineWidth = 1;
    ctx.beginPath(); ctx.arc(headX, headY, 4 + kk * 16, 0, Math.PI * 2); ctx.stroke();
    ctx.fillStyle = theme.sig; ctx.beginPath(); ctx.arc(headX, headY, 3.2, 0, Math.PI * 2); ctx.fill();
  }
  updateOdo();
}

function frame(ts) {
  if (!S.running) return;
  const dt = Math.min(0.25, S.last ? (ts - S.last) / 1000 : 0.0167);   // generous clamp: animations stay on wall-clock time even at low fps
  S.last = ts;
  if (S.W) drawStage(nowS(), dt);
  requestAnimationFrame(frame);
}
function startLoop() { if (S.running) return; S.running = true; S.last = 0; requestAnimationFrame(frame); }
function stopLoop() { S.running = false; }

// ── odometer (mechanical: units roll continuously, a higher digit only moves once the lower ones reach 9)
const DIGITS = 6;
const digitPos = (v, i) => {
  const p = Math.pow(10, i);
  if (i === 0) return v % 10;
  const lower = v % p, digit = Math.floor(v / p) % 10;
  return digit + (lower > p - 1 ? lower - (p - 1) : 0);
};
const strips = [];
(function buildOdo() {
  const box = $("odo");
  for (let i = DIGITS - 1; i >= 0; i--) {
    const cell = el("div", "cell"), strip = el("div", "strip");
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 0].forEach((n) => strip.appendChild(el("div", "d", String(n))));
    cell.appendChild(strip); box.appendChild(cell); strips[i] = strip;
    if (i === 3) box.appendChild(el("div", "sep", ","));
  }
})();
let odoLast = -1;
function updateOdo() {
  const a = S.a;
  const v = a < 0 || !S.parts.length ? 0 : Math.round(S.cumStart[a] + S.parts[a] * ease(S.seg));
  if (v === odoLast) return;
  odoLast = v;
  const val = Math.max(0, v);
  for (let i = 0; i < DIGITS; i++) strips[i].style.transform = `translateY(${-digitPos(val, i) * 12}px)`;
}

// ═══ UI: header, controls, list, timeline, card ═════════════════════════════
const list = $("list"), listPad = $("listPad");
const rowEls = new Map();
let rowY = new Map(), lockUntil = 0;
const pickOffset = () => list.clientHeight * 0.28;

function renderWho() {
  const box = $("who"); box.textContent = "";
  for (const t of state.travelers) {
    const b = el("button", "who" + (state.traveler === t.id ? " on" : ""), t.name);
    b.type = "button"; b.setAttribute("aria-pressed", String(state.traveler === t.id));
    b.addEventListener("click", () => { if (state.traveler !== t.id) { state.traveler = t.id; renderWho(); load(); } });
    box.appendChild(b);
  }
}

function renderControls() {
  const chip = $("chip"); chip.textContent = "偏航 ";
  chip.appendChild(el("span", "n", String(state.all.length)));
  const stamps = cityStamps(state.all), box = $("stamps");
  box.textContent = "";
  box.hidden = !stamps.length;
  for (const c of stamps) {
    const b = el("button", "stamp" + (state.city === c.city ? " on" : ""));
    b.type = "button"; b.appendChild(el("span", null, c.city)); b.appendChild(el("span", "n", "×" + c.n));
    b.addEventListener("click", () => { state.city = state.city === c.city ? null : c.city; afterFilter(); });
    box.appendChild(b);
  }
}

function renderList() {
  listPad.textContent = ""; rowEls.clear();
  if (!state.loaded) { listPad.appendChild(el("div", "empty", "在翻路书…")); return; }
  if (!state.visible.length) { listPad.appendChild(el("div", "empty", state.all.length ? "没有找到。换个词试试。" : "还没有走过的路。")); return; }
  let lastM = "";
  for (const x of state.visible) {
    const m = monthOf(x);
    if (m !== lastM) {
      lastM = m;
      const h = el("div", "month"); h.appendChild(el("span", null, m.replace("-", " · "))); h.appendChild(el("i"));
      listPad.appendChild(h);
    }
    const row = el("button", "row" + (x.id === state.activeId ? " on" : "")); row.type = "button";
    row.appendChild(el("span", "rn", pad2(x.seq)));
    row.appendChild(el("span", "rt"));
    row.appendChild(el("span", "rm", `${x.date.slice(5)} · 偏航${x.city ? " · " + x.city : ""}${x.part > 1 ? " · " + Math.round(x.part).toLocaleString("en") + " KM" : ""}`));
    row.appendChild(el("span", "rh", x.title));
    if (x.excerpt) row.appendChild(el("span", "rp", x.excerpt));
    row.addEventListener("click", () => openDetail(x));
    rowEls.set(x.id, row); listPad.appendChild(row);
  }
  listPad.style.paddingBottom = Math.round(list.clientHeight * 0.8) + "px";
  measureRows();
}
function measureRows() { rowY = new Map(); for (const [id, r] of rowEls) rowY.set(id, r.offsetTop); }

function renderTimeline() {
  const tl = $("tl"); tl.textContent = "";
  tl.appendChild(el("div", "base"));
  const seen = new Set();
  for (const x of state.asc) {
    const m = monthOf(x);
    if (!seen.has(m)) { seen.add(m); const e = el("div", "mo", Number(m.slice(5)) + "月"); e.style.left = clamp(state.pos(x) * 100, 0, 94) + "%"; tl.appendChild(e); }
  }
  for (const x of state.asc) {
    const t = el("div", "tick" + (state.visibleSet.has(x.id) ? "" : " off")); t.style.left = state.pos(x) * 100 + "%"; tl.appendChild(t);
  }
  const knob = el("div", "knob"); knob.id = "knob"; tl.appendChild(knob);
  moveKnob();
}
function moveKnob() {
  const k = $("knob"), a = activeStop();
  if (k && a) k.style.left = state.pos(a) * 100 + "%";
}
const activeStop = () => (state.activeId ? state.all.find((x) => x.id === state.activeId) || null : null);

function renderHud() {
  const a = activeStop();
  const t = $("hudL"); t.textContent = "";
  if (!a) { t.textContent = "— / —"; return; }
  t.appendChild(el("b", null, `${pad2(a.seq)} / ${pad2(state.all.length)} · ${a.date}`));
  if (a.city) t.appendChild(document.createTextNode("  " + a.city));
}

function renderAll() {
  renderWho(); renderControls(); renderList(); renderTimeline(); renderHud(); renderErrors();
  updateStageData();
  ensureActive();
}

function afterFilter() {
  recompute(); renderControls(); renderList(); renderTimeline(); updateStageData(); ensureActive();
}

// current stop must be a visible one; otherwise snap to the first visible
function ensureActive() {
  if (!state.visible.length) {
    S.a = -1; state.activeId = null; hideCard(); S.photo = { img: null, rect: null, t0: 0 }; renderHud();
    return;
  }
  if (!state.activeId || !state.visibleSet.has(state.activeId)) {
    const v = state.visible[0];
    const i = state.ascIndex.get(v.id) || 0;
    S.cam = cameraFor(v, state.asc.slice(0, i + 1), S.W || 360, S.H || 320, state.home);
    go(v);
    list.scrollTop = 0;
  } else { for (const [id, r] of rowEls) r.classList.toggle("on", id === state.activeId); }
}

// ── card (stops without a photo)
function hideCard() { const c = $("card"); c.hidden = true; c.classList.remove("in"); }
function showCard(st, rect, failed) {
  const c = $("card");
  c.style.left = rect.x + "px"; c.style.top = rect.y + "px"; c.style.width = rect.w + "px"; c.style.height = rect.h + "px";
  const lines = Math.max(3, Math.floor((rect.h - 40) / 22));
  const tx = $("cardTxt"); tx.textContent = st.body[0] || st.excerpt; tx.style.webkitLineClamp = String(lines);
  $("cardLab").textContent = failed ? "图没取到 · 纯文字" : "NO IMAGE · 纯文字";
  c.hidden = false; c.classList.remove("in");
  void c.offsetWidth; c.classList.add("in");
}

// ── go to a stop
function go(st) {
  const i = state.ascIndex.get(st.id);
  if (i == null) return;
  const prev = S.a, my = ++goGen;
  state.activeId = st.id;
  S.a = i;
  S.seg = i > prev ? 0 : 1;                       // moving forward draws the segment; going back snaps
  const target = cameraFor(st, state.asc.slice(0, i + 1), S.W, S.H, state.home);
  S.camT = target;
  const rect = placePhoto(st, target, S.W, S.H);
  const t = nowS();
  S.ghost = { img: S.photo.img, cors: S.photo.cors, rect: S.photo.rect, t0: t };
  S.photo = { img: null, rect, t0: t };
  hideCard();
  if (st.image) {
    loadImage(st.image.src).then((res) => {
      if (goGen !== my) return;
      if (!res) { showCard(st, rect, true); return; }
      S.photo = { img: res.img, cors: res.cors, rect, t0: nowS() };
    });
  } else showCard(st, rect, false);
  for (const [id, r] of rowEls) r.classList.toggle("on", id === st.id);
  renderHud(); moveKnob();
}

function jump(st, animated) {
  lockUntil = performance.now() + (animated ? 900 : 150);
  go(st);
  const y = rowY.get(st.id);
  if (y != null) list.scrollTo({ top: Math.max(0, y - pickOffset() + 6), behavior: animated ? "smooth" : "auto" });
}

list.addEventListener("scroll", () => {
  if (performance.now() < lockUntil || !state.visible.length) return;
  const line = list.scrollTop + pickOffset();
  let hit = state.visible[0];
  for (const v of state.visible) { const ry = rowY.get(v.id); if (ry != null && ry <= line) hit = v; }
  if (hit.id !== state.activeId) go(hit);
}, { passive: true });

// ── map tap (photo → detail, city dot → jump through the visits there)
cv.addEventListener("click", (ev) => {
  const b = cv.getBoundingClientRect(), x = ev.clientX - b.left, y = ev.clientY - b.top;
  const r = S.photo.rect, a = activeStop();
  if (r && a && S.photo.img && x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h) { openDetail(a); return; }
  const city = hitCity(state.visible, S.cam, S.W, S.H, x, y);
  if (!city) return;
  const nx = nextAtPlace(state.visible, city, state.activeId);
  if (nx) jump(nx, true);
});

// ── timeline scrub
(function () {
  const tl = $("tl");
  const scrub = (ev) => {
    const b = tl.getBoundingClientRect();
    const nx = nearestOnTimeline(state.visible, clamp((ev.clientX - b.left) / b.width, 0, 1), state.pos);
    if (nx && nx.id !== state.activeId) jump(nx, false);
  };
  let down = false;
  tl.addEventListener("pointerdown", (ev) => { down = true; try { tl.setPointerCapture(ev.pointerId); } catch (e) { /* ignore */ } scrub(ev); });
  tl.addEventListener("pointermove", (ev) => { if (down) scrub(ev); });
  const up = () => { down = false; };
  tl.addEventListener("pointerup", up); tl.addEventListener("pointercancel", up);
})();

// ── search
(function () {
  const wrap = $("search"), input = $("q"), btn = $("searchBtn"), ctrl = $("ctrl");
  const setOpen = (open) => {
    wrap.classList.toggle("open", open); ctrl.classList.toggle("searching", open);
    input.hidden = !open; btn.textContent = open ? "✕" : "⌕";
    if (open) input.focus();
    else if (state.q) { state.q = ""; input.value = ""; afterFilter(); }
  };
  btn.addEventListener("click", () => setOpen(!wrap.classList.contains("open")));
  input.addEventListener("input", () => { state.q = input.value; afterFilter(); });
  $("chip").addEventListener("click", () => { if (state.city) { state.city = null; afterFilter(); } });
})();

// ═══ detail ═════════════════════════════════════════════════════════════
const detailEl = $("detail");
let detailOpen = false, closeTimer = null;

function line(node, i) {
  const w = el("div", "line"), inner = el("div", "in");
  inner.style.setProperty("--i", String(Math.min(i, 8)));
  inner.appendChild(node); w.appendChild(inner); return w;
}
function box(k, v, note) {
  const b = el("div", "dBox"); b.appendChild(el("div", "dBoxK", k)); b.appendChild(el("div", "dBoxV", v));
  if (note) b.appendChild(el("div", "dBoxN", note));
  return b;
}
function quote(st) { return el("div", "quote", st.body[0] || st.excerpt); }

function openDetail(st) {
  if (detailOpen) return;
  if (st.id !== state.activeId) go(st);
  const stage = $("stage").getBoundingClientRect();
  const r = S.photo.rect || placePhoto(st, S.camT, S.W, S.H);
  const origin = { x: stage.left + r.x, y: stage.top + r.y, w: r.w, h: r.h };
  detailOpen = true; stopLoop();
  if (closeTimer) { clearTimeout(closeTimer); closeTimer = null; }

  const col = $("dCol"); col.textContent = "";
  const HH = Math.round(window.innerHeight * 0.44);
  const spacer = el("div"); spacer.style.height = HH + 8 + "px"; col.appendChild(spacer);
  let k = 0;
  col.appendChild(line(el("div", "dMeta", [pad2(st.seq), "偏航", st.date, st.city || "", st.part > 1 ? "+" + Math.round(st.part).toLocaleString("en") + " KM" : ""].filter(Boolean).join(" · ")), k++));
  col.appendChild(line(el("h2", "dH2", st.title), k++));
  if (st.dest) col.appendChild(line(el("p", "dDest", st.dest), k++));
  st.body.forEach((para) => col.appendChild(line(el("p", "dPara", para), k++)));       // textContent only: user text is never parsed as HTML
  if (!st.body.length) col.appendChild(line(el("p", "dDest faint", "这次没有留下游记正文。"), k++));
  if (st.texture) col.appendChild(line(box("出发温度", st.texture, st.warmth != null ? "WARMTH " + st.warmth : ""), k++));
  if (st.luggage) col.appendChild(line(box("带回的行李", st.luggage.item, st.luggage.note), k++));
  if (st.image && st.image.credit) {
    const c = el("div", "dCredit"); c.appendChild(document.createTextNode("图:"));
    if (st.image.page) { const a = el("a", null, st.image.credit); a.href = st.image.page; a.target = "_blank"; a.rel = "noopener noreferrer"; c.appendChild(a); }
    else c.appendChild(document.createTextNode(st.image.credit));
    col.appendChild(line(c, k++));
  }

  detailEl.hidden = false; detailEl.classList.remove("open", "closing");
  const sc = $("dScroll"); sc.scrollTop = 0;
  const colB = col.getBoundingClientRect(), colW = colB.width, colL = colB.left;
  const hero = $("dHero"); hero.textContent = "";
  hero.classList.remove("fly"); hero.style.left = colL + "px"; hero.style.width = colW + "px"; hero.style.height = HH + "px"; hero.style.opacity = "1";
  if (st.image) {
    const im = new Image(); im.alt = ""; im.referrerPolicy = "no-referrer"; im.decoding = "async";
    im.onerror = () => { hero.textContent = ""; hero.appendChild(quote(st)); };
    im.src = st.image.src; hero.appendChild(im);
  } else hero.appendChild(quote(st));
  const fromT = `translate(${origin.x - colL}px, ${origin.y}px) scale(${origin.w / colW}, ${origin.h / HH})`;
  hero.style.transform = fromT;
  void hero.offsetWidth;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    hero.classList.add("fly"); detailEl.classList.add("open"); hero.style.transform = "translate(0px, 0px) scale(1, 1)";
  }));
  detail.settle = setTimeout(() => { hero.classList.remove("fly"); detail.settled = true; parallax(); }, 800);
  detail.settled = false; detail.fromT = fromT; detail.HH = HH;
  $("dClose").focus({ preventScroll: true });
}
const detail = { settled: false, settle: null, fromT: "", HH: 0 };
function parallax() {
  if (!detail.settled) return;
  const y = $("dScroll").scrollTop, hero = $("dHero");
  hero.style.transform = `translate(0px, ${-y * 0.45}px) scale(1, 1)`;
  hero.style.opacity = String(Math.max(0.1, 1 - y / (detail.HH * 1.1)));
}
$("dScroll").addEventListener("scroll", parallax, { passive: true });

function closeDetail() {
  if (!detailOpen) return;
  detailOpen = false; clearTimeout(detail.settle);
  const hero = $("dHero");
  detail.settled = false;
  hero.style.opacity = "1";
  hero.classList.add("fly");
  void hero.offsetWidth;
  detailEl.classList.remove("open"); detailEl.classList.add("closing");
  hero.style.transform = detail.fromT;
  closeTimer = setTimeout(() => { detailEl.hidden = true; detailEl.classList.remove("closing"); closeTimer = null; startLoop(); }, 650);
}
$("dClose").addEventListener("click", closeDetail);
document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Escape") return;
  if (detailOpen) closeDetail(); else if (!$("pick").hidden) setPickerOpen(false);
});

// ═══ colour picker ══════════════════════════════════════════════════════
function setPickerOpen(open) { $("pick").hidden = !open; $("pickBtn").setAttribute("aria-expanded", String(open)); }
function syncPicker() {
  for (const b of $("swatches").children) b.classList.toggle("on", b.dataset.id === theme.id);
  $("cSig").value = theme.sig; $("cBg").value = theme.bg;
}
(function buildPicker() {
  const box = $("swatches");
  for (const p of PRESETS) {
    const b = el("button", "sw"); b.type = "button"; b.dataset.id = p.id; b.title = p.name; b.setAttribute("aria-label", p.name);
    b.style.background = `linear-gradient(135deg, ${p.sig} 0 50%, ${p.bg} 50% 100%)`;
    b.addEventListener("click", () => applyTheme(p, true));
    box.appendChild(b);
  }
  const custom = () => applyTheme(derive({ id: "custom", name: "自定义", sig: $("cSig").value, bg: $("cBg").value }), true);
  $("cSig").addEventListener("input", custom); $("cBg").addEventListener("input", custom);
  $("pickBtn").addEventListener("click", () => setPickerOpen($("pick").hidden));
  document.addEventListener("pointerdown", (ev) => { if (!$("pick").hidden && !$("pick").contains(ev.target) && ev.target !== $("pickBtn")) setPickerOpen(false); });
})();

// ═══ boot ═══════════════════════════════════════════════════════════════
function onResize() {
  if (!sizeStage()) return;
  const a = activeStop();
  if (a && S.a >= 0) {
    const i = S.a;
    S.camT = cameraFor(a, state.asc.slice(0, i + 1), S.W, S.H, state.home);
    S.cam = Object.assign({}, S.camT);
    const rect = placePhoto(a, S.camT, S.W, S.H);
    S.photo.rect = rect;
    if (!$("card").hidden) showCard(a, rect, $("cardLab").textContent.startsWith("图没"));
  }
  listPad.style.paddingBottom = Math.round(list.clientHeight * 0.8) + "px";
  measureRows();
}
new ResizeObserver(onResize).observe($("stage"));
window.addEventListener("resize", onResize);
document.addEventListener("visibilitychange", () => { if (document.hidden) stopLoop(); else if (!detailOpen) startLoop(); });

async function boot() {
  applyTheme(loadTheme(), false);
  sizeStage();
  S.cam = { x: 142, y: 60, z: Math.max(Z_MIN, (S.W || 360) / 290) }; S.camT = Object.assign({}, S.cam);
  if (!window.PIANHANG_LAND) errs.set("底图", "底图没载入(land.js)");
  startLoop();
  recompute(); renderAll();
  try {
    state.config = await fetchConfig();
    const c = state.config;
    if (c && c.home && validLatLon(c.home.lat, c.home.lon)) state.home = { lat: c.home.lat, lon: c.home.lon, label: str(c.home.label) };
    else errs.set("起点", "配置里没有起点(home)");
    state.travelers = Array.isArray(c && c.travelers) ? c.travelers.filter((t) => t && str(t.id)).map((t) => ({ id: str(t.id), name: str(t.name) || str(t.id) })) : [];
  } catch (e) {
    errs.set("配置", `配置没取到(${e instanceof Error ? e.message : "未知错误"})`);
  }
  const want = params.get("traveler");
  state.traveler = state.travelers.some((t) => t.id === want) ? want : state.travelers[0] ? state.travelers[0].id : null;
  await load();
}
boot();
})();
