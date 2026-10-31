"""The interactive version: every vehicle on the map, which you can play, scrub, zoom, filter by
mode, search, and tap for its line, destination and scheduled stops (or tap a stop for its next
departures). The viewer is player.js, plain JavaScript; the base map is OpenFreeMap's tiles
drawn by MapLibre GL, loaded from a CDN when the page opens.

Two ways out:
- one self-contained HTML file (player, data and still map inlined; the tiled base map needs
  a connection, and without one the page falls back to the still map);
- `--embed DIR`: player.js, <slug>.json and <slug>-plate.jpg as separate files plus a demo
  index.html, for a site to serve and mount (see the README, "Put it on a website")."""

from __future__ import annotations

import base64
import io
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

from .geo import Frame
from .render import Vehicles, draw_rank, rgb, route_color

PLAYER = Path(__file__).with_name("player.js")
hexc = lambda c: "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in np.clip(c, 0, 1))


def simplify(x: np.ndarray, y: np.ndarray, t: np.ndarray | None = None, tol: float = 0.4,
             tol_t: float = 1.5) -> np.ndarray:
    """Indices of the points to keep (Douglas-Peucker): a point goes only if the path moves
    less than `tol` px without it and, with times, the vehicle less than `tol_t` seconds off
    its schedule. Cuts the page size several-fold with no visible change."""
    n = len(x)
    if n <= 2:
        return np.arange(n)
    keep = np.zeros(n, bool)
    keep[[0, n - 1]] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        i = np.arange(a + 1, b)
        dx, dy = x[b] - x[a], y[b] - y[a]
        L2 = dx * dx + dy * dy
        f = np.clip(((x[i] - x[a]) * dx + (y[i] - y[a]) * dy) / L2, 0, 1) if L2 > 0 else np.zeros(len(i))
        err = np.hypot(x[i] - (x[a] + f * dx), y[i] - (y[a] + f * dy)) / tol
        if t is not None:
            # Time along the chord, by distance travelled: the player interpolates the same way.
            d = np.concatenate([[0], np.cumsum(np.hypot(np.diff(x[a:b + 1]), np.diff(y[a:b + 1])))])
            share = d[1:-1] / d[-1] if d[-1] > 0 else (i - a) / (b - a)
            err = np.maximum(err, np.abs(t[i] - (t[a] + share * (t[b] - t[a]))) / tol_t)
        k = int(np.argmax(err))
        if err[k] > 1:
            keep[a + 1 + k] = True
            stack += [(a, a + 1 + k), (a + 1 + k, b)]
    return np.flatnonzero(keep)


def data(baked: dict, frame: Frame, recipe: dict, words: dict, views: dict | None = None) -> dict:
    """Everything the player needs, compact: tenths of a pixel and whole seconds as integers,
    each array delta-encoded (the player decodes it on load)."""
    style = recipe["style"]
    veh = Vehicles(baked, frame, style)
    start = float(baked["start"])
    delta = lambda v: np.diff(np.round(v).astype(np.int64), prepend=0).tolist()
    routes = baked["routes"]
    agencies = sorted(set(baked["agencies"].values()))
    aix = {a: i for i, a in enumerate(agencies)}
    dot = {}
    for j, ri in enumerate(baked["trip_route"].tolist()):
        dot.setdefault(ri, hexc(veh.col[j]))
    out_routes = []
    for i, r in enumerate(routes):
        # How the line is drawn: 2 thick (metro, rail, ferry), 1 thin in its color (trams), 0 network.
        tier = 2 if r["type"] in style["line_types"] else 1 if r["type"] in style["thin_types"] else 0
        line = hexc(route_color(r, style)) if tier else (r.get("color") if r.get("color") and len(r["color"]) == 7 else "")
        out_routes.append([r.get("short", ""), r.get("long", ""), int(r["type"]), line, dot.get(i, "#ffffff"),
                           aix.get(baked["agencies"].get(r.get("agency", ""), ""), -1), tier,
                           draw_rank(r["type"], style)])
    sx, sy = frame.px(np.array([s[2] for s in baked["stops"]]), np.array([s[3] for s in baked["stops"]]))
    so, stp, stt, timed = baked["sched_off"], baked["sched_stop"], baked["sched_time"], baked["sched_timed"]
    trips = []
    for j in range(len(veh.t0)):
        a, b = veh.off[j], veh.off[j + 1]
        kx, ky, kt = veh.x[a:b], veh.y[a:b], veh.t[a:b]
        k = simplify(kx, ky, kt)
        kx, ky, kt = kx[k], ky[k], kt[k]
        c, d = so[j], so[j + 1]
        dwell = np.where(timed[c:d], np.round(stt[c:d, 1] - stt[c:d, 0]), -1).astype(int).tolist()
        trips.append([int(baked["trip_route"][j]), int(veh.is_line[j]),
                      delta(kx * 10), delta(ky * 10), delta(kt - start),
                      int(baked["trip_head"][j]), delta(stp[c:d]), delta(stt[c:d, 0] - start), dwell])
    nx, ny = frame.px(baked["net_pts"][:, 0], baked["net_pts"][:, 1])
    no = baked["net_off"]
    net = []
    for k in range(len(no) - 1):
        px, py = nx[no[k]:no[k + 1]], ny[no[k]:no[k + 1]]
        keep = simplify(px, py)
        net.append([int(baked["net_route"][k]), delta(px[keep] * 10), delta(py[keep] * 10)])
    return {
        "w": frame.width, "h": frame.height,
        # Web Mercator meters at the frame's center and per frame pixel: the player places the
        # frame on the tiled base map with these; views are the reel framings, (w, s, e, n).
        "frame": {"cx": float(frame.cx), "cy": float(frame.cy), "m": frame.m_per_px},
        "views": views or {"vertical": frame.bbox(0)},
        "start": start, "end": float(baked["end"]), "day": baked["day"],
        "seconds": recipe["video"]["seconds"], "words": words,
        "routes": out_routes, "agencies": agencies, "headsigns": baked["headsigns"],
        "stops": [[s[1], int(round(x * 10)), int(round(y * 10))] for s, x, y in zip(baked["stops"], sx, sy)],
        "trips": trips, "net": net,
        "style": {**{k: style[k] for k in ("outline", "outline_width", "outline_alpha", "glow_max", "line_width", "line_alpha",
                                          "thin_width", "thin_alpha", "network_width", "network_alpha")},
                  **{k: hexc(rgb(style[k])) for k in ("land", "water", "network")},
                  "dot": style["dot"], "line_dot": style["line_dot"]},
    }


def _jpeg(base: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray((base * 255).astype(np.uint8)).save(buf, "JPEG", quality=88)
    return buf.getvalue()


def write(out: Path, baked: dict, frame: Frame, recipe: dict, words: dict, base: np.ndarray,
          views: dict | None = None) -> None:
    """One self-contained HTML file (the base map's tiles load online; offline it shows the still map)."""
    d = data(baked, frame, recipe, words, views)
    d["plate"] = "data:image/jpeg;base64," + base64.b64encode(_jpeg(base)).decode()
    player = PLAYER.read_text().replace("export async function mount", "async function mount")
    html = (PAGE.replace("__TITLE__", _esc(words["title"] or "Transit"))
            .replace("__BOOT__", "mount(document.getElementById('player'), __DATA__);")
            .replace("__PLAYER__", player)
            .replace("__DATA__", json.dumps(d, separators=(",", ":")).replace("</", "<\\/")))
    out.write_text(html)


def write_embed(folder: Path, slug: str, baked: dict, frame: Frame, recipe: dict, words: dict,
                base: np.ndarray, views: dict | None = None) -> list[Path]:
    """player.js, <slug>.json, <slug>-plate.jpg and a demo index.html in `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    d = data(baked, frame, recipe, words, views)
    (folder / f"{slug}-plate.jpg").write_bytes(_jpeg(base))
    (folder / f"{slug}.json").write_text(json.dumps(d, separators=(",", ":")))
    shutil.copyfile(PLAYER, folder / "player.js")
    demo = (PAGE.replace("__TITLE__", _esc(words["title"] or "Transit"))
            .replace("<script>", '<script type="module">')
            .replace("__PLAYER__", 'import { mount } from "./player.js";')
            .replace("__BOOT__", f'mount(document.getElementById("player"), "{slug}.json", {{plate: "{slug}-plate.jpg"}});'))
    (folder / "index.html").write_text(demo)
    return [folder / n for n in ("player.js", f"{slug}.json", f"{slug}-plate.jpg", "index.html")]


_esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;")

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>html,body{margin:0;height:100%;background:#0c0d10}#player{position:fixed;inset:0}</style>
</head><body><div id="player"></div>
<script>
__PLAYER__
__BOOT__
</script></body></html>
"""
