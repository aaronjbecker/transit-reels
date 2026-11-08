"""Up to nine cities in one reel, in a regular grid: the same local hours of each, on one clock,
by default at one ground scale. Each map is an ordinary plate and vehicles from render.py."""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

import numpy as np

from . import recipe as recipe_mod
from . import render
from .geo import Frame
from .water import COUNTRY_KM


def shape(n: int, w: float, h: float, gap: float, columns: int | None = None) -> tuple[int, int]:
    """(columns, rows) for n maps in a w x h area: whatever makes the maps largest, as square as
    can be when two shapes tie."""
    def cell(c):
        r = math.ceil(n / c)
        return (w - gap * (c - 1)) / c, (h - gap * (r - 1)) / r
    best = columns or max(range(1, n + 1), key=lambda c: (round(min(cell(c))), -abs(cell(c)[0] - cell(c)[1])))
    if not 1 <= best <= n:
        raise SystemExit(f"[grid] columns: must be between 1 and {n}")
    return best, math.ceil(n / best)


class GridLayout(render.Layout):
    """The title column and the maps. Vertical and square frames stack the words above the grid,
    the credit below it; a horizontal frame keeps the words in a column left of the grid.
    `rects` is each map's top-left corner, row by row, a short last row centered."""

    def __init__(self, page: Frame, style: dict, words: dict, n: int, columns: int | None = None, gap: float = 6):
        super().__init__(page, style, words)
        W, H, u = self.W, self.H, self.u
        gap, edge = gap * u, 12 * u
        beside = W > H
        credit = words.get("credit", "")
        if beside:
            x0, x1, y0, y1 = W - H + edge, W - edge, edge, H - edge
            self.right = x0 - 40 * u
            self.credit_x, self.credit_w = (self.left + self.right) / 2, self.right - self.left
        else:
            # The maps line up with the words' 64 px column: a phone taller than 9:16 crops the
            # sides of a full-screen reel, which cut off city names set 24 px from the edge.
            x0, x1, y0 = self.left, self.right, self.bottom
            step_lines, f = render.credit_lines(credit, int(22 * u), self.credit_w) if credit else ([], None)
            if H > W:
                y1 = self.credit_y - 14 * u  # the credit grows down from here
            else:
                y1 = self.credit_y - (len(step_lines) - 1) * (f.size * 1.35 if f else 0) - 14 * u
        # Columns and rows as for the full width, so the margin shrinks the maps but never
        # reshapes the grid (a narrower area tips six maps from 3x2 to 2x3).
        cols, rows = shape(n, x1 - x0 if beside else W - 2 * edge, y1 - y0, gap, columns)
        # Even sizes: each map is pasted whole and the frame stays even for the encoder.
        cw = int((x1 - x0 - gap * (cols - 1)) / cols) // 2 * 2
        ch = int((y1 - y0 - gap * (rows - 1)) / rows) // 2 * 2
        self.cell_size = (cw, ch)
        self.cols, self.rows = cols, rows
        self.rects = []
        top = y0 + (y1 - y0 - (ch * rows + gap * (rows - 1))) / 2
        for r in range(rows):
            m = min(cols, n - r * cols)
            left = x0 + (x1 - x0 - (cw * m + gap * (m - 1))) / 2
            self.rects += [(round(left + c * (cw + gap)), round(top + r * (ch + gap))) for c in range(m)]
        self.name_font = render.font(int(30 * u), "Bold")
        self.count_font = render.font(int(20 * u), "Regular")


@dataclass
class Cell:
    label: str
    baked: dict
    frame: Frame
    style: dict
    base: np.ndarray
    x: int
    y: int
    u: float
    veh: render.Vehicles = field(init=False)

    def __post_init__(self):
        self.veh = render.Vehicles(self.baked, self.frame, self.style)


def runs_in_frame(cell: Cell) -> int:
    """Vehicle runs that show in this map at some point in the window."""
    b, f = cell.baked, cell.frame
    pts, off = b["trip_pts"], b["trip_off"]
    x, y = f.px(pts[:, 0], pts[:, 1])
    seen = (x >= 0) & (x < f.width) & (y >= 0) & (y < f.height) & (pts[:, 2] >= b["start"]) & (pts[:, 2] <= b["end"])
    t0, t1 = pts[off[:-1], 2], pts[off[1:] - 1, 2]
    live = (t0 <= b["end"]) & (t1 >= b["start"])
    return int(sum(seen[a:z].any() for a, z, ok in zip(off[:-1], off[1:], live) if ok))


def words(recipe: dict, cities: list[dict], days: list[dt.date], km: float) -> dict:
    """The page's words. One day for all, or none named if the cities' days differ; every city's
    required credit, each once, then the map's and the tool's."""
    t = recipe["time"]
    same_day = len(set(days)) == 1
    day = days[0]
    fields = {"start": t["start"], "minutes": t["minutes"], "km": f"{km:g}",
              "date": f"{day:%b} {day.day}, {day.year}" if same_day else "",
              "weekday": f"{day:%A}" if same_day else "weekday"}
    out = {k: recipe[k].format(**fields) for k in ("title", "subtitle", "note")}
    parts: list[str] = []
    for city, d in zip(cities, days):
        filled = {"date": f"{d:%b} {d.day}, {d.year}", "weekday": f"{d:%A}", "minutes": t["minutes"]}
        parts += [f["attribution"].format(**filled) for f in city["feeds"] if f["attribution"]]
    water = [c for c in cities if c["map"]["water"]]
    if any((c["cell"].get("width_km") or km or 0) <= COUNTRY_KM for c in water):
        parts.append("Map © OpenMapTiles © OpenStreetMap contributors")
    if any((c["cell"].get("width_km") or km or 0) > COUNTRY_KM for c in water):
        parts.append("Map: Natural Earth")
    if recipe["style"]["tool_credit"] is not False:
        parts.append(recipe_mod.TOOL_CREDIT)
    out["credit"] = "  ·  ".join(dict.fromkeys(parts))
    return out


def frames(cells: list[Cell], L: GridLayout, page: Frame, recipe: dict, meta: dict, times: np.ndarray):
    """Yield (time, uint8 HxWx3) for each time, every map at the same moment."""
    style, g = recipe["style"], recipe["grid"]
    text_rgb, text_a = render.chrome(meta, page, style, L)
    canvas = np.empty((page.height, page.width, 3), np.float32)
    canvas[:] = render.rgb(g["background"])
    clock = render.Stamp(L.clock_font, style["text"], L.u, style["text_shadow"])
    names = render.Stamp(L.name_font, style["text"], L.u, style["text_shadow"])
    counts = render.Stamp(L.count_font, style["text"], L.u, style["text_shadow"])
    pad = 12 * L.u
    for c0 in range(0, len(times), 60):
        T = times[c0:c0 + 60]
        at = [c.veh.at(T) for c in cells]
        for f, t in enumerate(T):
            img = canvas.copy()
            shown = []
            for cell, (X, Y) in zip(cells, at):
                h, w = cell.base.shape[:2]
                on = ~np.isnan(X[f])
                img[cell.y:cell.y + h, cell.x:cell.x + w] = render.paint(cell.base, cell.veh, X[f], Y[f], on, cell.style, cell.u)
                shown.append(int((on & (X[f] >= 0) & (X[f] < w) & (Y[f] >= 0) & (Y[f] < h)).sum()))
            img = np.clip(img * (1 - text_a) + text_rgb * text_a, 0, 1)
            clock.draw(img, render.hhmm(t), L.left, L.clock_y)
            for cell, n in zip(cells, shown):
                names.draw(img, cell.label, cell.x + pad, cell.y + pad)
                if g["count"] and style.get("counter"):
                    text = style["counter"].format(n=n)
                    counts.draw(img, text.replace("vehicles", "vehicle") if n == 1 else text,
                                cell.x + pad, cell.y + pad + 38 * L.u)
            yield t, (img * 255 + 0.5).astype(np.uint8)
