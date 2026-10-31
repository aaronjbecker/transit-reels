// transit-reels interactive player: every scheduled vehicle on a map you can explore.
// Plain JavaScript, no build step. Standalone pages inline this file; a site can import it:
//
//   import { mount } from "./player.js";
//   const player = await mount(element, "paris.json");   // or the data object itself
//   player.destroy();                                     // when the element goes away
//
// The element should have a size (the player fills it). Colors and the typeface follow CSS
// variables on the element or any parent: --tr-font, --tr-bg, --tr-panel, --tr-text,
// --tr-muted, --tr-line, --tr-accent.
//
// The base map is OpenFreeMap (free, no key, OpenStreetMap data), drawn by MapLibre GL, which
// is loaded from unpkg on first use. Offline, or with {basemap: "plate"}, the player falls back
// to the still map baked into the data (the reel's framing only).

const MAPLIBRE = "https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl";
const BASEMAP = "https://tiles.openfreemap.org/styles/dark";
const BASEMAP_CREDIT = "Map: OpenFreeMap © OpenMapTiles, data © OpenStreetMap contributors";

const CSS = `
.tr{position:relative;overflow:hidden;container-type:inline-size;background:var(--tr-bg,#0c0d10);color:var(--tr-text,#f2f3f5);
  font:14px/1.4 var(--tr-font,system-ui,-apple-system,"Segoe UI",sans-serif);user-select:none;-webkit-user-select:none;touch-action:none}
.tr:focus{outline:none}.tr:focus-visible{outline:2px solid var(--tr-accent,#7bd3ff);outline-offset:-2px}
.tr canvas,.tr-map{position:absolute;inset:0;width:100%;height:100%;display:block;cursor:grab}
.tr-map{pointer-events:none}.tr.coop canvas{touch-action:pan-y}
.tr-hint{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:#0008;font-size:15px;
  opacity:0;transition:opacity .25s;pointer-events:none}.tr-hint.on{opacity:1}
.tr canvas.drag{cursor:grabbing}.tr canvas.over{cursor:pointer}
.tr button,.tr input,.tr select{font:inherit;color:inherit}
.tr-head{position:absolute;left:14px;top:12px;width:min(300px,calc(100% - 28px));pointer-events:none}
.tr-title{text-shadow:0 1px 3px #000,0 0 14px #000e}
.tr-head{z-index:1}.tr-tip,.tr-panel,.tr-hint{z-index:2}
.tr.tiles .tr-head::before{content:"";position:absolute;inset:-40px -80px -30px -40px;z-index:-1;pointer-events:none;
  background:radial-gradient(closest-side,color-mix(in srgb,var(--tr-bg,#0c0d10) 70%,transparent),transparent)}
.tr-title b{display:block;font-size:22px;line-height:1.1;font-weight:700}
.tr-title span{color:var(--tr-muted,#a9adb6);font-size:13px}
.tr-clock{font-size:30px;font-weight:600;font-variant-numeric:tabular-nums;line-height:1}
.tr-count{color:var(--tr-muted,#a9adb6);font-size:13px;margin-top:2px}
.tr-search{pointer-events:auto;position:relative;margin-top:10px;width:min(260px,100%)}
.tr-search input{width:100%;box-sizing:border-box;background:var(--tr-panel,#17191fe6);border:1px solid var(--tr-line,#ffffff26);
  border-radius:8px;padding:7px 10px;outline:none}
.tr-search input:focus{border-color:var(--tr-accent,#7bd3ff)}
.tr-results{position:absolute;top:100%;left:0;right:0;margin-top:4px;background:var(--tr-panel,#17191ff2);border:1px solid var(--tr-line,#ffffff26);
  border-radius:8px;overflow:hidden;display:none;max-height:50vh;overflow-y:auto}
.tr-results button{display:flex;gap:8px;align-items:center;width:100%;text-align:left;background:none;border:0;padding:7px 10px;cursor:pointer}
.tr-results button:hover,.tr-results button.on{background:#ffffff14}
.tr-results small{color:var(--tr-muted,#a9adb6)}
.tr-legend{position:absolute;right:12px;top:12px;background:var(--tr-panel,#17191fd9);border:1px solid var(--tr-line,#ffffff1f);
  border-radius:10px;padding:8px 6px 6px}
.tr-legend h4{margin:0 8px 4px;font-size:10.5px;letter-spacing:.09em;color:var(--tr-muted,#a9adb6);font-weight:500}
.tr-mode{display:flex;gap:8px;align-items:center;padding:3px 8px;border-radius:6px;cursor:pointer;font-size:13px}
.tr-mode:hover{background:#ffffff10}
.tr-mode i{width:9px;height:9px;border-radius:50%;display:block;flex:none}.tr-mode s{display:flex;gap:2px;text-decoration:none}
.tr-mode span{flex:1}
.tr-mode em{font-style:normal;color:var(--tr-muted,#a9adb6);font-variant-numeric:tabular-nums;min-width:30px;text-align:right}
.tr-mode.off{opacity:.4}.tr-mode.off i{background:transparent!important;box-shadow:inset 0 0 0 1px #fff8}
.tr-foot{display:contents}.tr-panel.on ~ .tr-foot .tr-legend{display:none}
.tr-bar{position:absolute;left:0;right:0;bottom:0;padding:8px 12px 10px;display:flex;gap:10px;align-items:center;
  background:linear-gradient(transparent,#000a 40%)}
.tr-bar button,.tr-bar select{background:var(--tr-panel,#17191fe6);border:1px solid var(--tr-line,#ffffff26);border-radius:7px;padding:5px 9px;cursor:pointer}
.tr-play{min-width:34px}
.tr-spark{flex:1;height:34px;position:relative;cursor:pointer}
.tr-spark canvas{position:absolute;inset:0;width:100%;height:100%;cursor:pointer}
.tr-credit{position:absolute;left:12px;right:12px;bottom:52px;font-size:10.5px;color:var(--tr-muted,#a9adb6);text-align:center;
  text-shadow:0 1px 4px #000;pointer-events:none}
.tr-tip{position:absolute;pointer-events:none;background:var(--tr-panel,#17191ff2);border:1px solid var(--tr-line,#ffffff26);border-radius:7px;
  padding:5px 8px;font-size:12.5px;white-space:nowrap;display:none;transform:translate(12px,-50%)}
.tr-panel{position:absolute;right:12px;top:12px;bottom:58px;width:min(330px,calc(100% - 24px));background:var(--tr-panel,#17191ff2);
  border:1px solid var(--tr-line,#ffffff26);border-radius:12px;display:none;flex-direction:column;overflow:hidden;
  box-shadow:0 10px 30px #0008;user-select:text;-webkit-user-select:text}
.tr-panel.on{display:flex}
.tr-ph{padding:12px 14px 10px;border-bottom:1px solid var(--tr-line,#ffffff1a);position:relative}
.tr-ph h3{margin:0;font-size:17px;line-height:1.25;padding-right:26px}
.tr-ph p{margin:3px 0 0;color:var(--tr-muted,#a9adb6);font-size:13px}
.tr-x{position:absolute;right:8px;top:8px;background:none;border:0;font-size:20px;line-height:1;cursor:pointer;color:var(--tr-muted,#a9adb6);padding:4px 6px}
.tr-acts{display:flex;gap:6px;margin-top:9px;flex-wrap:wrap}
.tr-acts button{background:#ffffff10;border:1px solid var(--tr-line,#ffffff26);border-radius:7px;padding:4px 9px;cursor:pointer;font-size:12.5px}
.tr-acts button.on{border-color:var(--tr-accent,#7bd3ff);color:var(--tr-accent,#7bd3ff)}
.tr-pb{overflow-y:auto;padding:6px 0 10px;flex:1}
.tr-row{display:flex;gap:9px;align-items:center;padding:5px 14px;font-size:13px;cursor:default}
.tr-row.click{cursor:pointer}.tr-row.click:hover{background:#ffffff0d}
.tr-row .t{font-variant-numeric:tabular-nums;color:var(--tr-muted,#a9adb6);min-width:44px}
.tr-row.past{opacity:.45}.tr-row.next{font-weight:600}.tr-row.next .t{color:var(--tr-text,#fff)}
.tr-row .n{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tr-chip{display:inline-flex;align-items:center;justify-content:center;min-width:14px;height:20px;padding:0 6px;border-radius:5px;
  font-size:12px;font-weight:700;box-sizing:border-box;flex:none}
.tr-sec{padding:10px 14px 3px;font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--tr-muted,#a9adb6)}
.tr-note{padding:4px 14px;color:var(--tr-muted,#a9adb6);font-size:12.5px}
.tr-zoom{position:absolute;right:12px;bottom:58px;display:flex;flex-direction:column;gap:4px}
.tr-zoom button{width:32px;height:32px;background:var(--tr-panel,#17191fe6);border:1px solid var(--tr-line,#ffffff26);border-radius:7px;cursor:pointer;font-size:16px}
.tr-panel.on ~ .tr-zoom{display:none}
@container (max-width:640px){
  .tr-panel{top:auto;bottom:52px;right:8px;left:8px;width:auto;height:46%}
  .tr-title b{font-size:18px}.tr-clock{font-size:24px}
  .tr-foot{display:flex;flex-direction:column;gap:6px;position:absolute;left:8px;right:8px;bottom:50px;pointer-events:none}
  .tr-panel.on ~ .tr-foot{display:none}
  .tr-legend,.tr-credit{position:static}.tr-legend{background:none;border:0;padding:0;pointer-events:auto}.tr-legend h4{display:none}
  .tr-modes{display:flex;flex-wrap:wrap;gap:4px;justify-content:center}
  .tr-mode{font-size:12px;padding:2px 8px 2px 6px;gap:5px;background:var(--tr-panel,#17191fd9);border:1px solid var(--tr-line,#ffffff1f);border-radius:999px}
  .tr-mode em{min-width:0}.tr-credit{font-size:9.5px}.tr-zoom{display:none}
}`;

const MODES = {0: "Tram", 1: "Subway", 2: "Rail", 3: "Bus", 4: "Ferry", 5: "Cable tram", 6: "Aerial lift",
  7: "Funicular", 11: "Trolleybus", 12: "Monorail"};
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const hhmm = s => { s = Math.floor(s) % 86400; if (s < 0) s += 86400;
  return String(Math.floor(s / 3600)).padStart(2, "0") + ":" + String(Math.floor(s % 3600 / 60)).padStart(2, "0"); };
const undelta = (a, k = 1) => { const o = new Float64Array(a.length); let s = 0; for (let i = 0; i < a.length; i++) { s += a[i]; o[i] = s / k; } return o; };
const mix = (a, b, f) => "#" + [0, 2, 4].map(i => Math.round(parseInt(a.substr(1 + i, 2), 16) * (1 - f) + parseInt(b.substr(1 + i, 2), 16) * f).toString(16).padStart(2, "0")).join("");
const lum = hex => { const n = parseInt(hex.slice(1), 16); return (0.299 * (n >> 16) + 0.587 * (n >> 8 & 255) + 0.114 * (n & 255)) / 255; };

export async function mount(el, data, opts = {}) {
  if (typeof data === "string") data = await (await fetch(data)).json();
  const D = data;
  if (!document.getElementById("tr-css")) {
    const st = document.createElement("style"); st.id = "tr-css"; st.textContent = CSS; document.head.appendChild(st);
  }
  // ---------------------------------------------------------------- data
  const span = D.end - D.start;
  const routes = D.routes.map(([short, long, type, line, dot, agency, tier, rank = tier]) => ({short, long, type, line, dot, tier, rank, drawn: tier > 0, agency: D.agencies[agency] || ""}));
  const stops = D.stops.map(([name, x, y]) => ({name, x: x / 10, y: y / 10}));
  const trips = D.trips.map(([r, isLine, dx, dy, dt, head, ds, da, dw]) => {
    const ts = undelta(dt);
    return {r, isLine: !!isLine, xs: undelta(dx, 10), ys: undelta(dy, 10), ts, t0: ts[0], t1: ts[ts.length - 1], k: 0,
      head: D.headsigns[head] || "", stops: undelta(ds), arr: undelta(da), dwell: dw, mode: routes[r].type};
  });
  const dayText = new Date(D.day + "T12:00:00").toLocaleDateString("en-US", {weekday: "long", month: "short", day: "numeric", year: "numeric"});
  const label = r => r.short || r.long || MODES[r.type] || "";
  // A line's badge: its short name, or with none (MBTA's "Red Line") the long name, shortened.
  const chip = r => { const c = r.line || "#3a3f49";
    const t = r.short || (r.long || "").replace(/\s+(Line|Linie|Ligne|Línea|Linha)$/i, "").split(/\s+/).slice(0, 2).join(" ");
    return `<span class="tr-chip" style="background:${c};color:${lum(c) > 0.6 ? "#111" : "#fff"}">${esc(t)}</span>`; };
  // In a heading the name follows, so a line with no short name gets a plain color bar.
  const hchip = r => r.short ? chip(r) : `<span class="tr-chip" style="background:${r.line || "#3a3f49"};min-width:6px;padding:0 3px"></span>`;
  const where = r => [r.short && r.long ? r.long : "", MODES[r.type], r.agency].filter(Boolean).join(" · ");

  // ---------------------------------------------------------------- dom
  el.classList.add("tr"); el.tabIndex = 0;
  const w = D.words;
  el.innerHTML = `<div class="tr-map"></div><canvas></canvas>
    <div class="tr-head"><div class="tr-title"><b>${esc(w.title)}</b><span>${esc(w.subtitle)}</span>
      <div class="tr-clock" style="margin-top:8px"></div><div class="tr-count"></div></div>
      <div class="tr-search"><input placeholder="Find a line or stop" aria-label="Find a line or stop"><div class="tr-results"></div></div></div>
    <div class="tr-tip"></div><div class="tr-hint"></div>
    <div class="tr-panel"></div>
    <div class="tr-foot"><div class="tr-legend"><h4>MODE</h4><div class="tr-modes"></div></div><div class="tr-credit"></div></div>
    <div class="tr-zoom"><button data-z="1.6" aria-label="Zoom in">+</button><button data-z="0.625" aria-label="Zoom out">−</button><button data-z="0" aria-label="Fit">⤢</button></div>
    <div class="tr-bar"><button class="tr-play" aria-label="Play or pause">❚❚</button>
      <div class="tr-spark" title="Vehicles on the road over the window; tap to jump"><canvas></canvas></div>
      <select aria-label="Speed"><option value="0.25">¼×</option><option value="0.5">½×</option><option value="1" selected>1×</option><option value="2">2×</option><option value="4">4×</option></select></div>`;
  const $ = s => el.querySelector(s);
  const cv = $("canvas"), cx = cv.getContext("2d");
  const spark = $(".tr-spark canvas"), sx = spark.getContext("2d");
  const panel = $(".tr-panel"), tip = $(".tr-tip"), input = $(".tr-search input"), results = $(".tr-results");
  const plate = new Image(); plate.src = opts.plate || D.plate;
  const mapDiv = $(".tr-map");
  let map = null;  // the MapLibre map, when the tiled base map is on

  // ---------------------------------------------------------------- state
  let t = opts.t ?? 0, playing = opts.autoplay ?? true, speed = 1, last = performance.now(), raf = 0, alive = true;
  let view = {s: 1, x: 0, y: 0}, fitted = false;
  let sel = null;          // {kind: "trip"|"route"|"stop", i}
  let hover = -1, follow = false, panelAt = 0;
  const off = new Set();   // hidden modes
  const present = [...new Set(trips.map(tr => tr.mode))].sort((a, b) => a - b);
  let pos = [];            // [tripIndex, x, y] of vehicles on the road now

  // The reel's framing to open on: vertical on a tall screen, horizontal on a wide one.
  const F = D.frame, R0 = 6378137;
  const lonlat = (px, py) => { const mx = F.cx + (px - D.w / 2) * F.m, my = F.cy - (py - D.h / 2) * F.m;
    return [mx / R0 * 180 / Math.PI, (2 * Math.atan(Math.exp(my / R0)) - Math.PI / 2) * 180 / Math.PI]; };
  const opening = () => { const b = el.getBoundingClientRect(); return D.views[b.width < b.height ? "vertical" : "horizontal"] || D.views.vertical; };
  function fit() {
    if (map) { const [w0, s0, e0, n0] = opening(); map.fitBounds([[w0, s0], [e0, n0]], {padding: 0, animate: false}); return; }
    const W = cv.width, H = cv.height, s = Math.min(W / D.w, H / D.h);
    view = {s, x: (W - D.w * s) / 2, y: (H - D.h * s) / 2};
  }
  function syncView() {  // frame pixels -> canvas pixels, from the map's camera
    const r = devicePixelRatio || 1, c = map.getCenter(), k = 512 * 2 ** map.getZoom() / (2 * Math.PI * R0);
    const cmx = R0 * c.lng * Math.PI / 180, cmy = R0 * Math.log(Math.tan(Math.PI / 4 + c.lat * Math.PI / 360));
    view = {s: F.m * k * r, x: ((F.cx - D.w / 2 * F.m) - cmx) * k * r + cv.width / 2, y: (cmy - F.cy - D.h / 2 * F.m) * k * r + cv.height / 2};
  }
  async function loadMap() {
    if (!window.maplibregl) {
      const css = document.createElement("link"); css.rel = "stylesheet"; css.href = MAPLIBRE + ".css"; document.head.appendChild(css);
      await new Promise((ok, no) => { const sc = document.createElement("script"); sc.src = MAPLIBRE + ".js"; sc.onload = ok; sc.onerror = no; document.head.appendChild(sc); });
    }
    const [w0, s0, e0, n0] = opening();
    // The canvas on top takes every gesture and moves this camera (pan, zoomAt).
    const m = new maplibregl.Map({container: mapDiv, style: BASEMAP, bounds: [[w0, s0], [e0, n0]], interactive: false,
      attributionControl: false, renderWorldCopies: false, maxZoom: 17, fadeDuration: 0});
    await new Promise((ok, no) => { m.once("load", ok); m.once("error", e => no(e.error)); setTimeout(() => no(new Error("timeout")), 15000); });
    // The base map in the reel's palette: its land and water, roads a shade off the land, place
    // names faint. Buildings, parks, airports, road names and the map's own railways go (the
    // network is ours, and the chrome sits over the map).
    const road = mix(S.land, "#ffffff", 0.06), label = mix(S.land, "#ffffff", 0.3);
    for (const l of m.getStyle().layers) {
      const id = l.id, set = (k, v) => m.setPaintProperty(id, k, v);
      if (l.type === "background") set("background-color", S.land);
      else if (id === "water" || id === "waterway") set(l.type + "-color", S.water);
      else if (l.type === "fill" || /^(aeroway|railway|road_|highway_name)|casing|dashline/.test(id)) m.setLayoutProperty(id, "visibility", "none");
      else if (l.type === "line" && id.startsWith("highway")) set("line-color", road);
      else if (l.type === "symbol") { set("text-color", label); set("text-halo-color", S.land); if (id.startsWith("water")) set("text-color", mix(S.water, "#ffffff", 0.3)); }
    }
    m.setMinZoom(Math.max(0, m.getZoom() - 3));
    return m;
  }
  function resize() {
    const r = devicePixelRatio || 1, b = el.getBoundingClientRect();
    const W = Math.max(1, Math.round(b.width * r)), H = Math.max(1, Math.round(b.height * r));
    if (cv.width !== W || cv.height !== H) {
      const k = cv.width ? W / cv.width : 1;
      cv.width = W; cv.height = H;
      if (map) map.resize();
      else if (!fitted) { fit(); fitted = true; } else { view.x *= k; view.y *= k; view.s *= k; }
      spark.width = Math.round(spark.clientWidth * r); spark.height = Math.round(spark.clientHeight * r); drawSpark();
    }
  }
  const ro = new ResizeObserver(resize); ro.observe(el);

  function at(tr, tt) {  // position along the trip at time tt (seconds into the window)
    const ts = tr.ts; let k = tr.k;
    while (k < ts.length - 2 && ts[k + 1] <= tt) k++;
    while (k > 0 && ts[k] > tt) k--;
    tr.k = k;
    const f = ts[k + 1] > ts[k] ? Math.min(1, Math.max(0, (tt - ts[k]) / (ts[k + 1] - ts[k]))) : 0;
    return [tr.xs[k] + (tr.xs[k + 1] - tr.xs[k]) * f, tr.ys[k] + (tr.ys[k + 1] - tr.ys[k]) * f];
  }
  const visible = tr => !off.has(tr.mode);

  // ---------------------------------------------------------------- timeline
  const N = 240, counts = new Float32Array(N);
  function tally() {
    counts.fill(0);
    for (const tr of trips) if (visible(tr)) {
      const a = Math.max(0, Math.ceil(tr.t0 / span * (N - 1))), b = Math.min(N - 1, Math.floor(tr.t1 / span * (N - 1)));
      for (let i = a; i <= b; i++) counts[i]++;
    }
    drawSpark();
  }
  function drawSpark() {
    const W = spark.width, H = spark.height; if (!W) return;
    sx.clearRect(0, 0, W, H);
    let max = 1; for (const c of counts) max = Math.max(max, c);
    sx.beginPath(); sx.moveTo(0, H);
    for (let i = 0; i < N; i++) sx.lineTo(i / (N - 1) * W, H - 2 - counts[i] / max * (H - 6));
    sx.lineTo(W, H); sx.closePath(); sx.fillStyle = "#ffffff26"; sx.fill();
    sx.beginPath(); for (let i = 0; i < N; i++) sx.lineTo(i / (N - 1) * W, H - 2 - counts[i] / max * (H - 6));
    sx.strokeStyle = "#ffffff8c"; sx.lineWidth = 1.5 * (devicePixelRatio || 1); sx.stroke();
    const x = t / span * W; sx.fillStyle = getComputedStyle(el).getPropertyValue("--tr-accent").trim() || "#7bd3ff";
    sx.fillRect(x - 1, 0, 2 * (devicePixelRatio || 1), H);
  }

  // ---------------------------------------------------------------- drawing
  const S = D.style, u = Math.min(D.w, D.h) / 1080;
  // The network, for the tiled base map (the still map has it baked in): one path per look,
  // drawn in the reel's order (rank: metro on top where lines share a corridor).
  let netPaths = null, tripOrder = null;
  function buildNet() {
    const groups = new Map();
    for (const [r, dx, dy] of D.net) {
      const rt = routes[r], key = rt.tier ? rt.rank + rt.line : "0";
      if (!groups.has(key)) groups.set(key, {tier: rt.tier, rank: rt.rank, color: rt.tier ? rt.line : S.network, path: new Path2D()});
      const xs = undelta(dx, 10), ys = undelta(dy, 10), p = groups.get(key).path;
      p.moveTo(xs[0], ys[0]); for (let i = 1; i < xs.length; i++) p.lineTo(xs[i], ys[i]);
    }
    netPaths = [...groups.values()].sort((a, b) => a.rank - b.rank);
  }
  function drawNet(z) {
    if (!netPaths) buildNet();
    cx.lineJoin = cx.lineCap = "round";
    for (const g of netPaths) {
      const [wd, a] = g.tier === 2 ? [S.line_width, S.line_alpha] : g.tier === 1 ? [S.thin_width, S.thin_alpha] : [S.network_width, S.network_alpha];
      cx.strokeStyle = g.color; cx.globalAlpha = a; cx.lineWidth = Math.max(wd * u / z, 0.6 / view.s); cx.stroke(g.path);
    }
    cx.globalAlpha = 1;
  }
  const routeNet = new Map();  // route -> paths, built on first selection
  function netOf(r) {
    if (!routeNet.has(r)) routeNet.set(r, D.net.filter(n => n[0] === r).map(n => [undelta(n[1], 10), undelta(n[2], 10)]));
    return routeNet.get(r);
  }
  function focusRoute() { return !sel ? -1 : sel.kind === "route" ? sel.i : sel.kind === "trip" ? trips[sel.i].r : -1; }
  // Feeds list each platform as its own stop: a selected stop means every stop of that name
  // close by (both directions, every line at the station).
  function stopGroup(si) {
    const st = stops[si], lim = Math.max(D.w, D.h) * 0.012, g = new Set();
    stops.forEach((s, i) => { if (s.name === st.name && Math.hypot(s.x - st.x, s.y - st.y) < lim) g.add(i); });
    return g;
  }
  function stopRoutes(g) {
    const set = new Set(); for (const tr of trips) for (let k = 0; k < tr.stops.length; k++) if (g.has(tr.stops[k])) { set.add(tr.r); break; }
    return set;
  }
  let stopRouteSet = null, group = null;

  function draw(now) {
    if (!alive) return;
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    if (playing) { t += dt * speed * span / D.seconds; if (t > span) t = 0; }
    const W = cv.width, H = cv.height, r = devicePixelRatio || 1;
    if (follow && sel?.kind === "trip") {
      const tr = trips[sel.i];
      if (t >= tr.t0 && t <= tr.t1) {
        const [x, y] = at(tr, t);
        if (map) { const c = map.getCenter(), [lo, la] = lonlat(x, y); map.jumpTo({center: [c.lng + (lo - c.lng) * 0.12, c.lat + (la - c.lat) * 0.12]}); }
        else { view.x += (W / 2 - (x * view.s + view.x)) * 0.12; view.y += (H / 2 - (y * view.s + view.y)) * 0.12; }
      }
    }
    if (map) syncView();
    const fr = focusRoute(), z = Math.max(1, Math.sqrt(view.s / r)), dim = sel != null;
    cx.setTransform(1, 0, 0, 1, 0, 0);
    if (map) cx.clearRect(0, 0, W, H);
    else { cx.fillStyle = "#0c0d10"; cx.fillRect(0, 0, W, H); }
    cx.setTransform(view.s, 0, 0, view.s, view.x, view.y);
    cx.save();
    if (map) {
      drawNet(z);
      if (dim) { cx.save(); cx.setTransform(1, 0, 0, 1, 0, 0); cx.fillStyle = "#0c0d10b3"; cx.fillRect(0, 0, W, H); cx.restore(); }
    } else {
      cx.beginPath(); cx.rect(0, 0, D.w, D.h); cx.clip();  // nothing drawn off the still map
      if (plate.complete) cx.drawImage(plate, 0, 0, D.w, D.h);
      if (dim) { cx.fillStyle = "#0c0d10b3"; cx.fillRect(0, 0, D.w, D.h); }
    }
    if (fr >= 0) {  // the selected line, drawn bright over the dimmed map
      cx.strokeStyle = routes[fr].line || "#e8e9ec"; cx.lineWidth = Math.max(2.5, S.line_width || 4) * u / z * 1.2;
      cx.lineJoin = cx.lineCap = "round"; cx.globalAlpha = 0.95;
      for (const [xs, ys] of netOf(fr)) { cx.beginPath(); for (let i = 0; i < xs.length; i++) cx.lineTo(xs[i], ys[i]); cx.stroke(); }
      cx.globalAlpha = 1;
    }
    // Stops, once zoomed in far enough to tell them apart (or the selected stop at any zoom).
    if (view.s / r > 2.5 || sel?.kind === "stop") {
      const x0 = -view.x / view.s, y0 = -view.y / view.s, x1 = x0 + W / view.s, y1 = y0 + H / view.s, sr = 2.2 * u / z;
      cx.strokeStyle = "#ffffff73"; cx.lineWidth = 1 / view.s * r; cx.beginPath();
      if (view.s / r > 2.5) for (const st of stops) if (st.x > x0 && st.x < x1 && st.y > y0 && st.y < y1) { cx.moveTo(st.x + sr, st.y); cx.arc(st.x, st.y, sr, 0, 7); }
      cx.stroke();
      if (sel?.kind === "stop") { const st = stops[sel.i]; cx.strokeStyle = "#fff"; cx.lineWidth = 2.5 / view.s * r; cx.beginPath(); cx.arc(st.x, st.y, 9 * r / view.s, 0, 7); cx.stroke(); }
    }
    // Vehicles: halo, then a faint gray rim, then the dot, as the video draws them.
    pos = [];
    tripOrder ||= [...trips.keys()].sort((a, b) => routes[trips[a].r].rank - routes[trips[b].r].rank);
    for (const i of tripOrder) {  // in rank order, so a metro train sits over a commuter train
      const tr = trips[i];
      if (t < tr.t0 || t > tr.t1 || !visible(tr)) continue;
      const [x, y] = at(tr, t); pos.push([i, x, y]);
    }
    const lit = i => !dim || (fr >= 0 ? trips[i].r === fr : stopRouteSet?.has(trips[i].r));
    for (const pass of [0, 1]) {  // dimmed vehicles first, the selection's on top
      const list = pos.filter(p => lit(p[0]) === !!pass);
      if (!list.length) continue;
      cx.globalAlpha = pass ? 1 : (dim ? 0.28 : 1);
      if (!dim || pass) {
        cx.globalCompositeOperation = "lighten";
        for (const [i, x, y] of list) { const tr = trips[i], sp = tr.isLine ? S.line_dot : S.dot; if (!(sp.glow_gain > 0)) continue;
          cx.globalAlpha = Math.min(S.glow_max, sp.glow_gain * 0.5); cx.fillStyle = routes[tr.r].dot;
          cx.beginPath(); cx.arc(x, y, sp.glow_sigma * u / z * 1.5, 0, 7); cx.fill(); }
        cx.globalCompositeOperation = "source-over"; cx.globalAlpha = pass ? 1 : (dim ? 0.28 : 1);
      }
      if (S.outline) {
        cx.fillStyle = S.outline; const a = cx.globalAlpha; cx.globalAlpha = a * S.outline_alpha; cx.beginPath();
        for (const [i, x, y] of list) { const sp = trips[i].isLine ? S.line_dot : S.dot, rr = (sp.radius + S.outline_width) * u / z; cx.moveTo(x + rr, y); cx.arc(x, y, rr, 0, 7); }
        cx.fill(); cx.globalAlpha = a;
      }
      const byColor = new Map();
      for (const p of list) { const c = routes[trips[p[0]].r].dot; if (!byColor.has(c)) byColor.set(c, []); byColor.get(c).push(p); }
      for (const [c, ps] of byColor) {
        cx.fillStyle = c; cx.beginPath();
        for (const [i, x, y] of ps) { const sp = trips[i].isLine ? S.line_dot : S.dot, rr = sp.radius * u / z; cx.moveTo(x + rr, y); cx.arc(x, y, rr, 0, 7); }
        cx.fill();
      }
    }
    cx.globalAlpha = 1;
    // Rings on the hovered and the selected vehicle.
    const ring = (i, c, wdt) => { const tr = trips[i]; if (t < tr.t0 || t > tr.t1) return; const [x, y] = at(tr, t);
      cx.strokeStyle = c; cx.lineWidth = wdt / view.s * r; cx.beginPath(); cx.arc(x, y, 8 * r / view.s, 0, 7); cx.stroke(); };
    if (hover >= 0) ring(hover, "#ffffffb3", 1.5);
    if (sel?.kind === "trip") ring(sel.i, getComputedStyle(el).getPropertyValue("--tr-accent").trim() || "#7bd3ff", 2.5);

    cx.restore();
    $(".tr-clock").textContent = hhmm(D.start + t);
    if (now - panelAt > 250) { panelAt = now; status(); if (sel) renderPanel(false); drawSpark(); }
    raf = requestAnimationFrame(draw);
  }

  // ---------------------------------------------------------------- chrome
  const modeBox = $(".tr-modes");
  function status() {
    const by = {}; for (const [i] of pos) by[trips[i].mode] = (by[trips[i].mode] || 0) + 1;
    $(".tr-count").textContent = pos.length.toLocaleString() + " vehicles on the road · " + dayText;
    if (!modeBox.children.length) {  // the legend: each mode in the colors it is drawn in; tap to hide it
      modeBox.innerHTML = present.map(m => `<div class="tr-mode" data-m="${m}" role="button" aria-pressed="true" title="Show or hide">
        <s>${modeColors(m).map(c => `<i style="background:${c}"></i>`).join("")}</s><span>${esc(MODES[m] || "Other")}</span><em></em></div>`).join("");
      modeBox.querySelectorAll(".tr-mode").forEach(b => b.onclick = () => {
        const m = +b.dataset.m; off.has(m) ? off.delete(m) : off.add(m);
        b.classList.toggle("off", off.has(m)); b.setAttribute("aria-pressed", !off.has(m)); tally();
      });
    }
    modeBox.querySelectorAll(".tr-mode").forEach(b => { b.querySelector("em").textContent = off.has(+b.dataset.m) ? "" : (by[b.dataset.m] || 0).toLocaleString(); });
  }
  function modeColors(m) {  // as the mode is drawn: its lines' colors (up to four), or the dot color for buses
    const used = new Set(trips.filter(tr => tr.mode === m).map(tr => tr.r)), n = new Map();
    for (const r of used) { const rt = routes[r], c = rt.tier && rt.line ? rt.line : rt.dot; n.set(c, (n.get(c) || 0) + 1); }
    return [...n].sort((a, b) => b[1] - a[1]).slice(0, 4).map(a => a[0]); }

  // ---------------------------------------------------------------- the panel
  function nextIndex(tr) { let k = 0; while (k < tr.stops.length && tr.arr[k] < t) k++; return k; }
  const timeOf = (tr, k) => (tr.dwell[k] < 0 ? "~" : "") + hhmm(D.start + tr.arr[k]);
  function renderPanel(full = true) {
    if (!sel) { panel.classList.remove("on"); return; }
    const body = panel.querySelector(".tr-pb");
    const keep = body ? body.scrollTop : 0;
    let head = "", rows = "";
    if (sel.kind === "trip") {
      const tr = trips[sel.i], r = routes[tr.r], k = nextIndex(tr), live = t >= tr.t0 && t <= tr.t1;
      head = `<h3>${hchip(r)} ${esc(label(r))}${tr.head ? " to " + esc(tr.head) : ""}</h3><p>${esc(where(r))}</p>
        <p>${!live ? (t < tr.t0 ? "Not yet on the road" : "Finished its run") : k < tr.stops.length ? `Next: <b>${esc(stops[tr.stops[k]].name)}</b> at ${timeOf(tr, k)}` : "Arriving"}</p>
        <div class="tr-acts"><button data-a="follow" class="${follow ? "on" : ""}">Follow</button><button data-a="route">The whole line</button></div>`;
      rows = `<div class="tr-sec">Scheduled stops</div>` + Array.from(tr.stops, (s, j) =>
        `<div class="tr-row click ${j < k ? "past" : j === k ? "next" : ""}" data-s="${s}"><span class="t">${timeOf(tr, j)}</span><span class="n">${esc(stops[s].name)}</span></div>`).join("")
        + `<div class="tr-note">Times from the published timetable${tr.dwell.some(d => d < 0) ? "; ~ marks a time estimated between timed stops" : ""}. Not live positions.</div>`;
    } else if (sel.kind === "route") {
      const r = routes[sel.i], mine = trips.map((tr, i) => [tr, i]).filter(([tr]) => tr.r === sel.i);
      const inWin = mine.filter(([tr]) => tr.t1 >= 0 && tr.t0 <= span), now = pos.filter(p => trips[p[0]].r === sel.i);
      const heads = {}; for (const [tr] of inWin) heads[tr.head] = (heads[tr.head] || 0) + 1;
      const mins = Math.round(span / 60);
      head = `<h3>${hchip(r)} ${esc(r.long && r.short ? r.long : label(r))}</h3><p>${esc([MODES[r.type], r.agency].filter(Boolean).join(" · "))}</p>
        <p><b>${now.length}</b> on the road now · <b>${inWin.length}</b> runs in these ${mins} minutes</p>`;
      rows = `<div class="tr-sec">Runs by destination</div>` + Object.entries(heads).sort((a, b) => b[1] - a[1]).map(([h, n]) =>
          `<div class="tr-row"><span class="n">${esc(h || "(no destination given)")}</span><span class="t" style="text-align:right">${n}</span></div>`).join("")
        + `<div class="tr-sec">On the road now</div>` + (now.map(([i]) => { const tr = trips[i], k = nextIndex(tr);
          return `<div class="tr-row click" data-t="${i}"><span class="n">${tr.head ? "to " + esc(tr.head) : esc(label(r))}</span><span class="t" style="text-align:right">${k < tr.stops.length ? esc(stops[tr.stops[k]].name) : ""}</span></div>`; }).join("")
          || `<div class="tr-note">None at this moment.</div>`);
    } else {
      const st = stops[sel.i], deps = [];
      for (let i = 0; i < trips.length; i++) { const tr = trips[i]; if (!visible(tr)) continue;
        for (let k = 0; k < tr.stops.length; k++) if (group.has(tr.stops[k]) && tr.arr[k] >= t - 30 && k < tr.stops.length - 1) deps.push([tr.arr[k], i, k]); }
      deps.sort((a, b) => a[0] - b[0]);
      const served = [...(stopRouteSet || [])].map(r => routes[r]);
      head = `<h3>${esc(st.name)}</h3><p>${served.slice(0, 14).map(chip).join(" ")}</p>`;
      rows = `<div class="tr-sec">Next departures</div>` + (deps.slice(0, 40).map(([a, i, k]) => { const tr = trips[i], r = routes[tr.r];
          return `<div class="tr-row click" data-t="${i}"><span class="t">${timeOf(tr, k)}</span>${chip(r)}<span class="n">${esc(tr.head || label(r))}</span></div>`; }).join("")
        || `<div class="tr-note">No more departures in this window.</div>`);
    }
    if (full || !body) {
      panel.innerHTML = `<div class="tr-ph"><button class="tr-x" aria-label="Close">×</button>${head}</div><div class="tr-pb">${rows}</div>`;
      panel.classList.add("on");
    } else {
      panel.querySelector(".tr-ph").innerHTML = `<button class="tr-x" aria-label="Close">×</button>${head}`;
      body.innerHTML = rows; body.scrollTop = keep;
    }
    if (full && sel.kind === "trip") {  // bring the next stop into view
      const nx = panel.querySelector(".tr-row.next"); if (nx) nx.scrollIntoView({block: "center"});
    }
  }
  panel.addEventListener("click", e => {
    const b = e.target.closest("button,[data-s],[data-t]"); if (!b) return;
    if (b.classList.contains("tr-x")) return select(null);
    if (b.dataset.a === "follow") { follow = !follow; renderPanel(false); return; }
    if (b.dataset.a === "route") return select({kind: "route", i: trips[sel.i].r});
    if (b.dataset.s != null) return select({kind: "stop", i: +b.dataset.s}, true);
    if (b.dataset.t != null) return select({kind: "trip", i: +b.dataset.t}, true);
  });
  function select(s, center = false) {
    sel = s; follow = false;
    group = s?.kind === "stop" ? stopGroup(s.i) : null;
    stopRouteSet = group ? stopRoutes(group) : null;
    renderPanel(true);
    if (center && s) {
      let x, y;
      if (s.kind === "stop") ({x, y} = stops[s.i]);
      else if (s.kind === "trip") { const tr = trips[s.i]; [x, y] = at(tr, Math.min(Math.max(t, tr.t0), tr.t1)); }
      if (x != null) {  // zoom to at least 3x the fitted view, centered, clear of a side panel
        const r = devicePixelRatio || 1, k = Math.max(view.s, 3 * Math.min(cv.width / D.w, cv.height / D.h));
        const wide = cv.width > 640 * r, side = wide ? 170 * r : 0, up = wide ? 0 : cv.height * 0.22;  // clear of the panel
        if (map) map.easeTo({center: lonlat(x, y), zoom: map.getZoom() + Math.log2(k / view.s), offset: [-side / r, -up / r], duration: 450});
        else view = {s: k, x: cv.width / 2 - side - x * k, y: cv.height / 2 - up - y * k};
      }
    }
  }

  // ---------------------------------------------------------------- search
  const index = [...routes.map((r, i) => ({kind: "route", i, text: (r.short + " " + r.long).toLowerCase(), r})),
    ...(() => { const seen = new Map(); stops.forEach((s, i) => { const k = s.name.toLowerCase(); if (s.name && !seen.has(k)) seen.set(k, i); });
      return [...seen].map(([text, i]) => ({kind: "stop", i, text})); })()];
  let hits = [], hi = 0;
  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    if (!q) { results.style.display = "none"; return; }
    const score = x => x.text === q ? 0 : x.text.startsWith(q) || (x.r && x.r.short.toLowerCase() === q) ? 1 : x.text.includes(" " + q) ? 2 : x.text.includes(q) ? 3 : 9;
    hits = index.map(x => [score(x), x]).filter(a => a[0] < 9).sort((a, b) => a[0] - b[0] || a[1].text.length - b[1].text.length).slice(0, 8).map(a => a[1]);
    hi = 0; paintHits();
  });
  function paintHits() {
    results.innerHTML = hits.map((x, j) => x.kind === "route"
      ? `<button class="${j === hi ? "on" : ""}" data-j="${j}">${chip(x.r)}<span>${esc(x.r.long || label(x.r))}</span></button>`
      : `<button class="${j === hi ? "on" : ""}" data-j="${j}"><span>${esc(stops[x.i].name)}</span><small>stop</small></button>`).join("")
      || `<div class="tr-note" style="padding:8px 10px">Nothing by that name</div>`;
    results.style.display = "block";
  }
  input.addEventListener("keydown", e => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { hi = (hi + (e.key === "ArrowDown" ? 1 : hits.length - 1)) % Math.max(1, hits.length); paintHits(); e.preventDefault(); }
    if (e.key === "Enter" && hits[hi]) pick(hits[hi]);
    if (e.key === "Escape") { input.value = ""; results.style.display = "none"; el.focus({preventScroll: true}); }
    e.stopPropagation();
  });
  results.addEventListener("click", e => { const b = e.target.closest("button"); if (b) pick(hits[+b.dataset.j]); });
  function pick(x) { results.style.display = "none"; input.value = ""; el.focus({preventScroll: true}); select({kind: x.kind, i: x.i}, x.kind === "stop"); }

  // ---------------------------------------------------------------- pointer
  const ptrs = new Map(); let moved = 0, pinch = 0;
  const toWorld = (px, py) => [(px - view.x) / view.s, (py - view.y) / view.s];
  function hitAt(cxp, cyp) {  // the vehicle (or, zoomed in, the stop) under a canvas point
    const [wx, wy] = toWorld(cxp, cyp), r = devicePixelRatio || 1, lim = 12 * r / view.s;
    let best = -1, bd = lim * lim;
    for (const [i, x, y] of pos) { const d = (x - wx) ** 2 + (y - wy) ** 2; if (d < bd) { bd = d; best = i; } }
    if (best >= 0) return {kind: "trip", i: best};
    if (view.s / r > 2.5) { let bs = -1; bd = lim * lim;
      stops.forEach((s, i) => { const d = (s.x - wx) ** 2 + (s.y - wy) ** 2; if (d < bd) { bd = d; bs = i; } });
      if (bs >= 0) return {kind: "stop", i: bs}; }
    return null;
  }
  const local = e => { const b = cv.getBoundingClientRect(), r = devicePixelRatio || 1; return [(e.clientX - b.left) * r, (e.clientY - b.top) * r]; };
  cv.addEventListener("pointerdown", e => { cv.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, local(e)); moved = 0; pinch = 0; el.focus({preventScroll: true}); });
  cv.addEventListener("pointermove", e => {
    const p = local(e);
    if (!ptrs.has(e.pointerId)) {  // hover with a mouse
      if (e.pointerType !== "mouse") return;
      const h = hitAt(...p); hover = h?.kind === "trip" ? h.i : -1;
      cv.classList.toggle("over", !!h);
      if (h) { const b = cv.getBoundingClientRect();
        tip.innerHTML = h.kind === "trip" ? `${chip(routes[trips[h.i].r])} ${esc(trips[h.i].head ? "to " + trips[h.i].head : label(routes[trips[h.i].r]))}` : esc(stops[h.i].name);
        tip.style.left = (e.clientX - b.left) + "px"; tip.style.top = (e.clientY - b.top) + "px"; tip.style.display = "block"; }
      else tip.style.display = "none";
      return;
    }
    const q = ptrs.get(e.pointerId); ptrs.set(e.pointerId, p);
    if (ptrs.size === 1) { pan(p[0] - q[0], p[1] - q[1]); moved += Math.abs(p[0] - q[0]) + Math.abs(p[1] - q[1]); if (moved > 6) { cv.classList.add("drag"); follow = false; } }
    else if (ptrs.size === 2) {
      const [a, b] = [...ptrs.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (pinch) zoomAt((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, d / pinch);
      pinch = d; moved = 99;
    }
  });
  const up = e => {
    if (!ptrs.has(e.pointerId)) return;
    ptrs.delete(e.pointerId); cv.classList.remove("drag");
    if (moved < 6 && !ptrs.size) { const h = hitAt(...local(e)); select(h); }
    if (ptrs.size < 2) pinch = 0;
  };
  cv.addEventListener("pointerup", up);
  cv.addEventListener("pointercancel", e => { ptrs.delete(e.pointerId); cv.classList.remove("drag"); pinch = 0; });  // the page took the swipe
  cv.addEventListener("pointerleave", () => { hover = -1; tip.style.display = "none"; });
  function pan(dx, dy) {
    const r = devicePixelRatio || 1;
    if (map) { map.panBy([-dx / r, -dy / r], {animate: false}); syncView(); } else { view.x += dx; view.y += dy; }
  }
  function zoomAt(px, py, k) {
    const r = devicePixelRatio || 1, base = Math.min(cv.width / D.w, cv.height / D.h);
    if (map) { map.jumpTo({zoom: map.getZoom() + Math.log2(k), around: map.unproject([px / r, py / r])}); syncView(); return; }
    const s = Math.min(base * 60, Math.max(base * 0.8, view.s * k)); k = s / view.s;
    view.x = px - (px - view.x) * k; view.y = py - (py - view.y) * k; view.s = s;
  }
  // Embedded in a page (not filling the window), plain scrolling and one-finger vertical swipes
  // scroll the page; zoom with Ctrl/⌘ + scroll (trackpad pinch sends that too) or two fingers.
  const coop = opts.cooperative ?? (el.getBoundingClientRect().height < innerHeight * 0.95);
  el.classList.toggle("coop", coop);
  const hint = $(".tr-hint"); let hintT = 0;
  hint.textContent = (/Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl") + " + scroll to zoom";
  cv.addEventListener("wheel", e => {
    if (coop && !e.ctrlKey && !e.metaKey) { hint.classList.add("on"); clearTimeout(hintT); hintT = setTimeout(() => hint.classList.remove("on"), 900); return; }
    e.preventDefault(); const [px, py] = local(e); zoomAt(px, py, Math.exp(-e.deltaY / (e.ctrlKey ? 100 : 400)));
  }, {passive: false});
  cv.addEventListener("dblclick", e => { const [px, py] = local(e); zoomAt(px, py, 2); });
  $(".tr-zoom").addEventListener("click", e => { const b = e.target.closest("button"); if (!b) return;
    const z = +b.dataset.z; if (!z) fit(); else zoomAt(cv.width / 2, cv.height / 2, z); });

  // ---------------------------------------------------------------- controls
  const playBtn = $(".tr-play");
  const setPlay = p => { playing = p; playBtn.textContent = p ? "❚❚" : "▶"; };
  setPlay(playing);
  playBtn.onclick = () => setPlay(!playing);
  $(".tr-bar select").onchange = e => speed = +e.target.value;
  let scrub = false;
  const seek = e => { const b = spark.getBoundingClientRect(); t = Math.min(1, Math.max(0, (e.clientX - b.left) / b.width)) * span; trips.forEach(tr => tr.k = 0); };
  spark.addEventListener("pointerdown", e => { scrub = true; spark.setPointerCapture(e.pointerId); seek(e); });
  spark.addEventListener("pointermove", e => scrub && seek(e));
  spark.addEventListener("pointerup", () => scrub = false);
  el.addEventListener("keydown", e => {
    if (e.target === input) return;
    if (e.key === " ") { setPlay(!playing); e.preventDefault(); }
    else if (e.key === "ArrowRight" || e.key === "ArrowLeft") { t = Math.min(span, Math.max(0, t + (e.key === "ArrowRight" ? 30 : -30))); e.preventDefault(); }
    else if (e.key === "Escape") select(null);
    else if (e.key === "/") { input.focus(); e.preventDefault(); }
  });

  resize(); tally();
  const credit = $(".tr-credit"); credit.textContent = w.credit;
  raf = requestAnimationFrame(draw);
  if (opts.basemap !== "plate" && D.frame) loadMap().then(m => {
    if (!alive) return m.remove();
    map = m; el.classList.add("tiles");
    const own = /Map(: Natural Earth| © OpenStreetMap contributors)/;  // the still map's credit, now the tiles'
    credit.textContent = own.test(w.credit) ? w.credit.replace(own, BASEMAP_CREDIT) : w.credit + "  ·  " + BASEMAP_CREDIT;
  }).catch(e => console.warn("transit-reels: no tiled base map, using the still map", e));
  return {
    play: () => setPlay(true), pause: () => setPlay(false),
    seek: clock => { t = Math.min(span, Math.max(0, clock - D.start)); trips.forEach(tr => tr.k = 0); },
    destroy: () => { alive = false; cancelAnimationFrame(raf); ro.disconnect(); map?.remove(); el.innerHTML = ""; el.classList.remove("tr", "tiles"); },
  };
}
