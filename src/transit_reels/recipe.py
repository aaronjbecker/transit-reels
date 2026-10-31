"""A recipe is one TOML file per reel: the feed, the day and hours, the frame and the words.
Everything not given falls back to DEFAULTS; see recipes/example.toml for every key."""

from __future__ import annotations

import copy
import datetime as dt
import os
import tomllib
from pathlib import Path

FORMATS = {"vertical": (1080, 1920), "horizontal": (1920, 1080), "square": (1080, 1080)}

# The window: the morning peak, 20 minutes of timetable in 10 s (two minutes a second, slow
# enough to follow a train). A recipe can move it with [time] start / minutes, [video] seconds.
WINDOW = {"start": "08:00", "minutes": 20, "seconds": 10}
FAST_MINUTES_PER_SECOND = 4  # faster than this, the dots blur: allowed, with a warning
WARNINGS: list[str] = []  # repeated at the end of a command, with render's

DEFAULTS = {
    "title": "",
    "subtitle": "",
    # {date} {weekday} {minutes} are filled in at render time. Drawn as a small upper-case label.
    "note": "every scheduled vehicle · {weekday}, {date}",
    # key names a stored API key (never the key itself); key_param / key_header say how the
    # agency wants it sent; signup is where to get one.
    "feed": {"url": "", "mirror": "", "path": "", "attribution": "", "license": "", "route_types": None,
             "retype": {},  # fix mislabelled modes, e.g. {"T2" = 0}: route T2 is a tram
             # Trips without a route shape are left out (a straight line between stops is a
             # wrong path), and a feed with no shapes at all is refused; true draws them straight.
             "straight": False,
             "key": "", "key_param": "", "key_header": "", "signup": ""},
    "time": {"date": "next-weekday", "start": None, "minutes": None},
    # format: vertical (Reels, TikTok, Shorts), horizontal (X, LinkedIn, YouTube) or square.
    # width/height override the format's size.
    "video": {"format": "vertical", "width": None, "height": None, "fps": 30, "seconds": None},
    # center + width_km frame the vertical reel. Other formats keep the center and the same
    # ground area unless [map.horizontal] / [map.square] give their own center/width_km.
    "map": {"center": None, "width_km": None, "water": True},
    "style": {
        "land": "#25272c",
        "water": "#0c0d10",
        "text": "#ffffff",
        "muted": "#b4b8c0",
        # Route types drawn as thick colored lines that their vehicles ride inside (metro,
        # rail, ferry, cable cars ...). thin_types (trams) get a thin line in their own color
        # and tinted dots. Everything else (buses) is a white dot on a thin slate network.
        "line_types": [1, 2, 4, 5, 6, 7, 12],
        "thin_types": [0],
        "thin_width": 1.5,
        "thin_alpha": 0.45,
        "thin_whiten": 0.8,
        # "route": each line in its own route_color. "mode": one color per mode (whole
        # countries), from mode_colors keyed by route type, e.g. {"2" = "#ff8a4c"}.
        "color_by": "route",
        "mode_colors": {},
        "line_width": 5.5,
        "line_alpha": 0.85,
        "network": "#5b7396",
        "network_width": 1.0,
        "network_alpha": 0.45,
        "dot_color": "#ffffff",
        # A faint rim around every dot (px at 1080); "" for none.
        "glow_max": 0.12,  # the most the halos can cover where many overlap (0-1)
        "outline": "#9a9fa8",
        "outline_width": 1.2,
        "outline_alpha": 0.85,
        # A crisp disc per vehicle (radius in px at 1080; gain is how opaque) with a faint soft
        # halo (glow_gain; 0 for none).
        "dot": {"radius": 1.5, "gain": 4.0, "glow_sigma": 2.5, "glow_gain": 0.12},
        "line_dot": {"radius": 2.8, "gain": 5.0, "glow_sigma": 3.5, "glow_gain": 0.25, "whiten": 0.88},
        "text_shadow": 0.8,  # a soft shadow under the letters, for legibility over the map
        "title_top": None,   # px from the top at 1080; default 250 vertical, 72 otherwise
        "credit_y": None,    # fraction of the height; default 0.80 vertical, the foot otherwise
        "counter": "{n:,} vehicles",
        # The line naming the tool under every reel. It stays on unless a recipe sets this to
        # false; please keep it, it is how people find the recipe.
        "tool_credit": True,
    },
}

TOOL_CREDIT = "mapped.earth/transit-reels"


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(path: str | Path) -> dict:
    path = Path(path)
    with open(path, "rb") as f:
        r = _merge(DEFAULTS, tomllib.load(f))
    # One feed under [feed], or several as [[feeds]] (cities whose agencies publish separately).
    r["feeds"] = [_merge(DEFAULTS["feed"], f) for f in r["feeds"]] if r.get("feeds") else [r["feed"]]
    if r["time"].pop("window", "peak") != "peak":
        raise SystemExit("[time] window: only the peak is offered now (a whole day in a reel is too fast "
                         "to read). Remove the line, or set start and minutes for another stretch.")
    for table, key in (("time", "start"), ("time", "minutes"), ("video", "seconds")):
        if r[table][key] is None:
            r[table][key] = WINDOW[key]
    rate = r["time"]["minutes"] / r["video"]["seconds"]
    if rate > FAST_MINUTES_PER_SECOND:
        WARNINGS.append(f"{r['time']['minutes']} minutes of timetable in {r['video']['seconds']} s is "
                        f"{rate:.0f} minutes a second, faster than {FAST_MINUTES_PER_SECOND}: the dots will blur and "
                        "no single vehicle can be followed. Fine if that is the look you want; otherwise show "
                        "less time ([time] minutes) or make the video longer ([video] seconds).")
    r["slug"] = r.get("slug") or path.stem
    r["_dir"] = path.parent
    return r


def work_dir(recipe: dict) -> Path:
    """Generated files go to ./work/<slug>/ unless TRANSIT_REELS_WORK says otherwise."""
    root = Path(os.environ.get("TRANSIT_REELS_WORK", "work")).expanduser()
    d = root / recipe["slug"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def clock(s: str) -> int:
    h, m = s.split(":")[:2]
    return int(h) * 3600 + int(m) * 60


def fill_words(recipe: dict, day: dt.date, width_km: float = 0) -> dict:
    fields = {"date": f"{day:%b} {day.day}, {day.year}", "weekday": f"{day:%A}", "minutes": recipe["time"]["minutes"]}
    words = {k: recipe[k].format(**fields) for k in ("title", "subtitle", "note")}
    parts = [f["attribution"].format(**fields) for f in recipe["feeds"] if f["attribution"]]
    if recipe["map"]["water"]:
        from .water import COUNTRY_KM
        parts.append("Map: Natural Earth" if width_km > COUNTRY_KM else "Map © OpenStreetMap contributors")
    if recipe["style"]["tool_credit"] is not False:
        parts.append(TOOL_CREDIT)
    words["credit"] = "  ·  ".join(parts)
    return words


def frame_spec(recipe: dict, fmt: str | None = None) -> tuple[str, int, int]:
    """(format, width, height) for the recipe, or for another format asked on the command line."""
    v = recipe["video"]
    fmt = fmt or v["format"]
    if fmt not in FORMATS:
        raise SystemExit(f"format must be one of {', '.join(FORMATS)}")
    w, h = FORMATS[fmt]
    if fmt == v["format"]:
        w, h = v["width"] or w, v["height"] or h
    return fmt, w, h
