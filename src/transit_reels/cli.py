"""transit-reels: an animated map of every scheduled vehicle in a city, from its GTFS timetable.

  transit-reels find "boston"            search the Mobility Database catalog for feeds
  transit-reels inspect <url or zip>     what is in a feed, and trips per day for 3 weeks
  transit-reels still recipe.toml        one frame as PNG, to check the framing fast
  transit-reels render recipe.toml       the video (MP4) and its first frame (PNG)
  transit-reels render recipe.toml --format horizontal    the same, 16:9 for X / LinkedIn
  (a recipe with [grid] puts up to nine cities in one reel: still, render and stats take it too)
  transit-reels stats recipe.toml        runs, paths and vehicles moving: numbers for a caption
  transit-reels key set <name>           store an API key privately, for feeds that need one
  transit-reels web recipe.toml          a single self-contained interactive HTML page
"""

from __future__ import annotations

import argparse
import csv
import re
import datetime as dt
import hashlib
import io
import json
import sys
import time
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np

from . import bake as bake_mod
from . import grid as grid_mod
from . import keys as keys_mod
from . import recipe as recipe_mod
from . import render as render_mod
from .geo import Frame, auto_frame
from .gtfs import ROUTE_TYPE_NAMES, Calendar, Feed, base_route_type, pick_weekday, trips_per_day

CATALOG = "https://files.mobilitydatabase.org/feeds_v2.csv"
UA = {"User-Agent": "Mozilla/5.0 (transit-reels; +https://github.com/)"}


def log(msg: str) -> None:
    print(msg, flush=True)


def download(url: str, dest: Path, headers: dict | None = None, shown: str | None = None) -> Path:
    """Fetch url into dest. `shown` is what the log prints (the url without any key in it)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    log(f"  downloading {shown or url}")
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    return dest


def cached_feed(url: str) -> Path:
    """Where a feed url is kept once downloaded: work/feeds/<hash of the url>.zip."""
    return recipe_mod.work_dir({"slug": "feeds"}) / (hashlib.sha1(url.encode()).hexdigest()[:12] + ".zip")


def feed_path(recipe: dict, feed: dict) -> Path:
    """The feed, or with `member` the feed zipped inside the download, unpacked beside it once."""
    outer = download_feed(recipe, feed)
    if not feed.get("member"):
        return outer
    inner = outer.with_name(f"{outer.stem}-{re.sub(r'[^A-Za-z0-9]+', '-', feed['member'])}.zip")
    if not inner.exists():
        with zipfile.ZipFile(outer) as z:
            try:
                data = z.read(feed["member"])
            except KeyError:
                raise SystemExit(f"{outer.name} has no {feed['member']}. Inside it: " + ", ".join(z.namelist()[:20]))
        inner.with_suffix(".part").write_bytes(data)
        inner.with_suffix(".part").rename(inner)
    return inner


def download_feed(recipe: dict, feed: dict) -> Path:
    """A local feed if the recipe names one, else the URL downloaded once into work/feeds/
    (falling back to the Mobility Database mirror when the agency's server refuses, or when the
    agency wants a key you have not set yet)."""
    if feed["path"]:
        p = Path(feed["path"]).expanduser()
        return p if p.is_absolute() else recipe["_dir"] / p
    if not (feed["url"] or feed["mirror"]):
        raise SystemExit("Each feed needs a url or a path")
    dest = cached_feed(feed["url"] or feed["mirror"])  # named by the url, never by a key
    if dest.exists():
        return dest
    tries = []  # (url to fetch, headers, url to show)
    if feed["url"]:
        if feed.get("key"):
            value = keys_mod.get(feed["key"])
            if value:
                url, headers = keys_mod.apply(feed["url"], feed, value)
                tries.append((url, headers, feed["url"]))
            elif feed["mirror"]:
                log(f"  ! no '{feed['key']}' key set, so using the Mobility Database mirror (it can lag the\n"
                    f"    agency by a few days). For the agency's own copy: sign up at "
                    f"{feed.get('signup') or 'its developer portal'},\n    then run: uv run transit-reels key set {feed['key']}")
            else:
                raise SystemExit(keys_mod.missing_message(feed))
        else:
            tries.append((feed["url"], {}, feed["url"]))
    if feed["mirror"]:
        tries.append((feed["mirror"], {}, feed["mirror"]))
    for i, (url, headers, shown) in enumerate(tries):
        try:
            return download(url, dest.with_suffix(".part"), headers, shown).rename(dest)
        except Exception as err:
            if i == len(tries) - 1:
                hint = ("\n" + keys_mod.missing_message(feed)) if feed.get("key") and "40" in str(err) else ""
                raise SystemExit(f"Could not download the feed: {err}{hint}")
            log(f"  ! {err}; trying the mirror")


# ------------------------------------------------------------------ commands

def cmd_find(args) -> None:
    cache = Path(recipe_mod.work_dir({"slug": "_catalog"})) / "feeds_v2.csv"
    if not cache.exists() or time.time() - cache.stat().st_mtime > 7 * 86400:
        download(CATALOG, cache)
    words = [w.lower() for w in args.query]
    hits = 0
    for r in csv.DictReader(open(cache, encoding="utf-8")):
        if r["data_type"] != "gtfs" or r.get("status") not in ("active", ""):
            continue
        hay = " ".join(r[k] for k in ("provider", "name", "location.municipality",
                                      "location.subdivision_name", "location.country_code")).lower()
        if all(w in hay for w in words):
            hits += 1
            log(f"{r['id']:>10}  {r['location.country_code']} {r['location.municipality'] or r['location.subdivision_name']}"
                f"  —  {r['provider']}{' / ' + r['name'] if r['name'] else ''}")
            log(f"{'':>12}url:    {r['urls.direct_download']}")
            if r["urls.latest"]:
                log(f"{'':>12}mirror: {r['urls.latest']}")
            if r["urls.authentication_type"] not in ("", "0"):
                name = re.sub(r"[^a-z0-9]", "", r["provider"].lower().split()[0]) or r["id"]
                how = (f'key_header = "{r["urls.api_key_parameter_name"]}"' if r["urls.authentication_type"] == "2"
                       else f'key_param = "{r["urls.api_key_parameter_name"] or "key"}"')
                log(f"{'':>12}NEEDS A KEY (usually free): sign up at {r['urls.authentication_info'] or 'the provider'}")
                log(f"{'':>12}  then run `uv run transit-reels key set {name}` and add to [feed]:")
                for line in (f'key = "{name}"', how, f'signup = "{r["urls.authentication_info"]}"'):
                    log(f"{'':>14}{line}")
                log(f"{'':>12}  Without a key the mirror above works as-is.")
            if r["urls.license"]:
                log(f"{'':>12}license: {r['urls.license']}")
    if not hits:
        log("No active GTFS feeds match. Try fewer words, the agency's name, or the country code.")


def cmd_inspect(args) -> None:
    src = args.feed
    if src.endswith(".toml"):  # a recipe: inspect its (first) feed, downloading it with its key
        recipe = recipe_mod.load(src)
        no_grid(recipe, "inspect")
        src = str(feed_path(recipe, recipe["feeds"][0]))
    if src.startswith(("http://", "https://")):
        dest = cached_feed(src)  # a recipe with the same url reuses it
        if not dest.exists():
            download(src, dest.with_suffix(".part")).rename(dest)
        log(f"feed:       {dest}")
        src = dest
    feed = Feed(src)
    types = Counter()
    for r in feed.rows("routes.txt"):
        types[base_route_type(int(r.get("route_type") or 3))] += 1
    agencies = [a.get("agency_name", "") for a in feed.rows("agency.txt")]
    cal = Calendar(feed)
    log(f"agencies:   {len(set(agencies))}: {', '.join(sorted(set(agencies)))}")
    log("routes:     " + ", ".join(f"{n} {ROUTE_TYPE_NAMES.get(t, t)} ({t})" for t, n in types.most_common()))
    cov = cal.coverage()
    log(f"calendar:   {cov[0]} to {cov[1]} at most (the trips per day below are the real check)" if cov
        else "calendar:   none found")
    log(f"shapes:     {'yes' if feed.has('shapes.txt') else 'NO: rendering will stop; vehicles could only move in straight lines between stops (`straight = true` accepts that)'}")
    if feed.has("frequencies.txt"):
        log("frequencies.txt: yes — some trips are headway templates, not individual runs")
    start = dt.date.fromisoformat(args.start) if args.start else dt.date.today()
    log("trips per day (a short bar on a weekday is a holiday or a disrupted timetable):")
    counts = trips_per_day(feed, cal, start, 21)
    top = max(1, max(n for _, n in counts))
    for day, n in counts:
        log(f"  {day:%a %Y-%m-%d}  {n:>7,}  {'#' * round(40 * n / top)}")


def no_grid(recipe: dict, command: str) -> None:
    if "grid" in recipe:
        raise SystemExit(f"`{command}` works on one city: run it on a city's own recipe, not on a [grid].")


def bake_cached(recipe: dict) -> tuple[dict, dt.date]:
    """The baked window, re-baked only when the feeds, the day or the window change."""
    feeds = [Feed(feed_path(recipe, f)) for f in recipe["feeds"]]
    t = recipe["time"]
    day = pick_weekday(feeds) if t["date"] == "next-weekday" else dt.date.fromisoformat(str(t["date"]))
    start = recipe_mod.clock(t["start"])
    end = start + int(t["minutes"] * 60)
    work = recipe_mod.work_dir(recipe)
    tag = recipe.get("_bake_tag", "")
    out = work / f"bake{tag}.npz"
    key = json.dumps([[str(f.path), f.path.stat().st_mtime, spec["route_types"], spec["retype"], spec["straight"], 5]
                      for f, spec in zip(feeds, recipe["feeds"])]
                     + [day.isoformat(), start, end])
    stamp = work / f"bake{tag}.key"
    if not out.exists() or not stamp.exists() or stamp.read_text() != key:
        log(f"baking {recipe['slug']}: {day:%a %b} {day.day}, {day.year}, {t['start']} for {t['minutes']} min")
        parts = []
        for f, spec in zip(feeds, recipe["feeds"]):
            log(f"  feed {f.path.name}")
            part = bake_mod.bake(f, day, start, end, spec["route_types"], log=log, straight=spec["straight"])
            # Correct a feed's mislabelled modes: {"T2" = 0} by route short name or id, "*" for all.
            for rid, r in part["routes"].items():
                fix = spec["retype"].get(r.get("short", ""), spec["retype"].get(rid, spec["retype"].get("*")))
                if fix is not None:
                    r["type"] = int(fix)
            parts.append(part)
        bake_mod.save(bake_mod.merge(parts), out)
        stamp.write_text(key)
    return bake_mod.load(out), day


def prepare(recipe: dict, fmt: str | None = None) -> tuple[dict, Frame, dict, dt.date, str]:
    """Bake (cached) and fit the frame for the recipe's format, or another one."""
    baked, day = bake_cached(recipe)
    frame = fit_frame(recipe, baked, fmt)
    fmt = recipe_mod.frame_spec(recipe, fmt)[0]
    return baked, frame, recipe_mod.fill_words(recipe, day, frame.width_km), day, fmt


def fit_frame(recipe: dict, baked: dict, fmt: str | None = None, size: tuple[int, int] | None = None) -> Frame:
    """The camera for a format: the recipe's own framing, or the one it implies for another shape
    (`size`: any other shape, keeping the center and the ground area)."""
    fmt, W, H = recipe_mod.frame_spec(recipe, fmt)
    W, H = size or (W, H)
    m = recipe["map"]
    own = m.get(fmt) if isinstance(m.get(fmt), dict) else {}
    center, width_km = own.get("center") or m["center"], own.get("width_km")
    if width_km is None and m["width_km"]:
        # The recipe frames its own format; another format keeps the center and the ground area.
        _, W0, H0 = recipe_mod.frame_spec(recipe)
        width_km = float(m["width_km"]) * ((W / H) / (W0 / H0)) ** 0.5
    if not (center and width_km):
        pts = baked["trip_pts"]
        inside = pts[(pts[:, 2] >= baked["start"]) & (pts[:, 2] <= baked["end"]), :2]
        auto_c, auto_w = auto_frame(inside, W, H)
        center, width_km = center or auto_c, width_km or auto_w
        log(f"  auto framing ({fmt}): center = [{center[0]:.4f}, {center[1]:.4f}], width_km = {width_km:.1f}")
    return Frame(tuple(center), float(width_km), W, H)


def out_name(recipe: dict, fmt: str, ext: str) -> Path:
    """work/<slug>/<slug>.mp4 for the recipe's own format, <slug>-horizontal.mp4 etc. otherwise."""
    tail = "" if fmt == recipe["video"]["format"] else f"-{fmt}"
    return recipe_mod.work_dir(recipe) / f"{recipe['slug']}{tail}{ext}"


def base_plate(recipe, baked, frame, fmt) -> np.ndarray:
    work = recipe_mod.work_dir(recipe)
    wc = None
    if recipe["map"]["water"]:
        w, s, e, n = frame.bbox(0.1)
        wc = work.parent / "water" / f"{w:.3f}_{s:.3f}_{e:.3f}_{n:.3f}.json"
    base = render_mod.plate(baked, frame, recipe["style"], wc, log)
    from PIL import Image
    Image.fromarray((base * 255).astype(np.uint8)).save(out_name(recipe, fmt, "-plate.png"))
    return base


def frame_times(recipe: dict, baked: dict) -> np.ndarray:
    v = recipe["video"]
    n = int(v["seconds"] * v["fps"])
    return baked["start"] + (baked["end"] - baked["start"]) * np.arange(n) / n


def shared_day(cities: list[dict]) -> None:
    """Every city in a grid on one calendar day where the timetables allow it. Cities with a date
    of their own keep it."""
    open_date = [c for c in cities if c["time"]["date"] == "next-weekday"]
    if len(open_date) < 2:
        return
    try:
        day = pick_weekday([Feed(feed_path(c, f)) for c in open_date for f in c["feeds"]])
    except SystemExit as err:
        log(f"  no one day suits every city ({err}); each uses its own")
        return
    for c in open_date:
        c["time"]["date"] = day.isoformat()


def prepare_grid(recipe: dict, fmt: str | None = None) -> tuple[list[grid_mod.Cell], grid_mod.GridLayout, dict, str, Frame]:
    """Bake every city (cached), lay out the page, and frame and draw each city's map."""
    fmt, W, H = recipe_mod.frame_spec(recipe, fmt)
    cities = recipe_mod.cities(recipe)
    shared_day(cities)
    baked = []
    days = []
    for city in cities:
        b, day = bake_cached(city)
        baked.append(b)
        days.append(day)
        log(f"  {city['label']}: {day:%a %b} {day.day}, {day.year}")
    g = recipe["grid"]
    page = Frame((0.0, 0.0), 1.0, W, H)
    # The layout depends on the credit and the words, the words on the scale, the scale only on
    # the cells' shape: measure the shape with the longest words first.
    probe = grid_mod.words(recipe, cities, days, 0.0)
    cw, ch = grid_mod.GridLayout(page, recipe["style"], probe, len(cities), g["columns"], g["gap"]).cell_size
    frames_ = [fit_frame(c, b, size=(cw, ch)) for c, b in zip(cities, baked)]
    same = g["scale"] == "same"
    km = float(g["width_km"] or np.median([f.width_km for f in frames_])) if same else 0.0
    if km:
        km = float(f"{km:.2g}") if not g["width_km"] else km  # a round number, for the subtitle
    if g["order"] == "count":
        mid = recipe_mod.clock(recipe["time"]["start"]) + recipe["time"]["minutes"] * 30.0
        def shown(i):
            city, f = cities[i], frames_[i]
            view = Frame(tuple(city["cell"].get("center") or f.center), float(city["cell"].get("width_km") or km or f.width_km), cw, ch)
            X, Y = render_mod.Vehicles(baked[i], view, city["style"]).at(np.array([mid]))
            return int(((X[0] >= 0) & (X[0] < cw) & (Y[0] >= 0) & (Y[0] < ch)).sum())
        rank = sorted(range(len(cities)), key=shown, reverse=True)
        cities, baked, days, frames_ = ([v[i] for i in rank] for v in (cities, baked, days, frames_))
    words = grid_mod.words(recipe, cities, days, km)
    L = grid_mod.GridLayout(page, recipe["style"], words, len(cities), g["columns"], g["gap"])
    cw, ch = L.cell_size
    u = max(min(cw, ch) / 1080, g["dot_scale"])
    cells = []
    for city, b, f, (x, y) in zip(cities, baked, frames_, L.rects):
        center = city["cell"].get("center") or f.center
        width = city["cell"].get("width_km") or km or f.width_km
        frame = Frame(tuple(center), float(width), cw, ch)
        wc = None
        if city["map"]["water"]:
            wc = recipe_mod.work_dir(city).parent / "water" / "grid.json"  # marks the folder; grids read tiles
        log(f"  map of {city['label']}: {frame.width_km:g} km wide")
        base = render_mod.plate(b, frame, city["style"], wc, log, u=u, water_tiles=True)
        cells.append(grid_mod.Cell(city["label"], b, frame, city["style"], base, x, y, u))
    return cells, L, words, fmt, page


def grid_times(recipe: dict) -> np.ndarray:
    v, t = recipe["video"], recipe["time"]
    start = recipe_mod.clock(t["start"])
    n = int(v["seconds"] * v["fps"])
    return start + t["minutes"] * 60 * np.arange(n) / n


def cmd_still(args) -> None:
    recipe = recipe_mod.load(args.recipe)
    if "grid" in recipe:
        cells, L, words, fmt, page = prepare_grid(recipe, args.format)
        t = recipe_mod.clock(args.at or recipe["time"]["start"])
        _, img = next(grid_mod.frames(cells, L, page, recipe, words, np.array([float(t)])))
        at = f"-{render_mod.hhmm(t).replace(':', '')}" if args.at else ""
        out = Path(args.out) if args.out else out_name(recipe, fmt, f"-still{at}.png")
        from PIL import Image
        Image.fromarray(img).save(out)
        log(f"wrote {out}")
        return
    baked, frame, words, _, fmt = prepare(recipe, args.format)
    base = base_plate(recipe, baked, frame, fmt)
    t = recipe_mod.clock(args.at) if args.at else baked["start"]
    _, img = next(render_mod.frames(baked, frame, recipe["style"], words, base, np.array([float(t)])))
    at = f"-{render_mod.hhmm(t).replace(':', '')}" if args.at else ""
    out = Path(args.out) if args.out else out_name(recipe, fmt, f"-still{at}.png")
    from PIL import Image
    Image.fromarray(img).save(out)
    log(f"wrote {out}")


def cmd_render(args) -> None:
    recipe = recipe_mod.load(args.recipe)
    if "grid" in recipe:
        cells, L, words, fmt, page = prepare_grid(recipe, args.format)
        out = Path(args.out) if args.out else out_name(recipe, fmt, ".mp4")
        times = grid_times(recipe)
        log(f"rendering {len(times)} frames at {page.width}x{page.height}, {len(cells)} cities")
        t0 = time.time()
        render_mod.encode(grid_mod.frames(cells, L, page, recipe, words, times), out, page.width, page.height,
                          recipe["video"]["fps"], out.with_suffix(".png"), log)
        log(f"wrote {out} and {out.with_suffix('.png')} in {time.time() - t0:.0f} s")
        return
    baked, frame, words, day, fmt = prepare(recipe, args.format)
    base = base_plate(recipe, baked, frame, fmt)
    out = Path(args.out) if args.out else out_name(recipe, fmt, ".mp4")
    times = frame_times(recipe, baked)
    log(f"rendering {len(times)} frames at {frame.width}x{frame.height}")
    t0 = time.time()
    render_mod.encode(render_mod.frames(baked, frame, recipe["style"], words, base, times),
                      out, frame.width, frame.height, recipe["video"]["fps"], out.with_suffix(".png"), log)
    log(f"wrote {out} and {out.with_suffix('.png')} in {time.time() - t0:.0f} s")


def cmd_web(args) -> None:
    from . import web
    recipe = recipe_mod.load(args.recipe)
    no_grid(recipe, "web")
    baked, frame, words, day, fmt = prepare(recipe, args.format)
    base = base_plate(recipe, baked, frame, fmt)
    # The interactive page opens on the reel's framing for the screen's shape: vertical on a
    # phone, horizontal on a desktop, over a base map that goes on past both.
    views = {f: fit_frame(recipe, baked, f).bbox(0) for f in ("vertical", "horizontal")}
    if args.embed:
        files = web.write_embed(Path(args.embed), Path(out_name(recipe, fmt, "")).name, baked, frame, recipe, words, base, views)
        log("wrote " + ", ".join(str(f) for f in files))
        log("  serve the folder and open index.html; on a site, see the README, \"Put it on a website\"")
        return
    out = Path(args.out) if args.out else out_name(recipe, fmt, ".html")
    web.write(out, baked, frame, recipe, words, base, views)
    log(f"wrote {out}")


def cmd_key(args) -> None:
    if args.action == "list":
        names = keys_mod.names()
        log("\n".join(names) if names else "No keys set.")
        log(f"(stored in {keys_mod.key_file()}, or TRANSIT_REELS_KEY_<NAME> in the environment)")
        return
    if not args.name:
        raise SystemExit(f"Usage: transit-reels key {args.action} <name>")
    (keys_mod.set_key if args.action == "set" else keys_mod.remove)(args.name)


def cmd_stats(args) -> None:
    """The numbers for a caption: vehicle runs, distinct paths, vehicles moving over the window."""
    recipe = recipe_mod.load(args.recipe)
    if "grid" in recipe:
        cells, *_ = prepare_grid(recipe)
        log("vehicle runs in each map:")
        for c in cells:
            log(f"  {c.label:<24} {grid_mod.runs_in_frame(c):>7,}")
        return
    baked, day = bake_cached(recipe)
    pts, off = baked["trip_pts"], baked["trip_off"]
    t0, t1 = pts[off[:-1], 2], pts[off[1:] - 1, 2]
    log(f"{day:%A, %B} {day.day}, {day.year}, {render_mod.hhmm(baked['start'])} to {render_mod.hhmm(baked['end'])}")
    inside = (t0 <= baked["end"]) & (t1 >= baked["start"])  # the bake keeps a margin either side
    log(f"vehicle runs in the window: {int(inside.sum()):,}")
    # A regional or national feed runs far past the picture; this is the number a caption wants.
    frame = fit_frame(recipe, baked)
    x, y = frame.px(pts[:, 0], pts[:, 1])
    seen = (x >= 0) & (x < frame.width) & (y >= 0) & (y < frame.height) & (pts[:, 2] >= baked["start"]) & (pts[:, 2] <= baked["end"])
    in_frame = int(sum(seen[a:b].any() for a, b, ok in zip(off[:-1], off[1:], inside) if ok))
    log(f"  of those, in the frame:   {in_frame:,}")
    log(f"distinct paths drawn:       {len(baked['net_off']) - 1:,}")
    log(f"routes:                     {len(set(baked['trip_route'][inside].tolist())):,}")
    types = {}
    for i in baked["trip_route"][inside]:
        name = ROUTE_TYPE_NAMES.get(baked["routes"][i]["type"], "other")
        types[name] = types.get(name, 0) + 1
    log("runs by mode:               " + ", ".join(f"{n:,} {k}" for k, n in sorted(types.items(), key=lambda x: -x[1])))
    step = args.every * 60
    rows = [(t, int(((t0 <= t) & (t1 >= t)).sum())) for t in np.arange(baked["start"], baked["end"] + 1, step)]
    peak = max(rows, key=lambda r: r[1])
    log(f"vehicles moving (whole feed, not just the frame), every {args.every} min; peak {peak[1]:,} at {render_mod.hhmm(peak[0])}:")
    top = max(1, peak[1])
    for t, n in rows:
        log(f"  {render_mod.hhmm(t)}  {n:>7,}  {'#' * round(40 * n / top)}")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="transit-reels", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("find", help="search the Mobility Database catalog")
    s.add_argument("query", nargs="+")
    s.set_defaults(fn=cmd_find)
    s = sub.add_parser("inspect", help="summarize a GTFS feed (a url, a .zip, a folder, or a recipe)")
    s.add_argument("feed")
    s.add_argument("--start", help="first day of the trips-per-day table (default today)")
    s.set_defaults(fn=cmd_inspect)
    for name, fn, helptext in (("still", cmd_still, "one frame as PNG"),
                               ("render", cmd_render, "the MP4"),
                               ("web", cmd_web, "an interactive HTML page")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("recipe")
        s.add_argument("--out")
        s.add_argument("--format", choices=list(recipe_mod.FORMATS),
                       help="render this format instead of the recipe's (horizontal for X, LinkedIn)")
        if name == "still":
            s.add_argument("--at", help="HH:MM (default: the start of the window)")
        if name == "web":
            s.add_argument("--embed", metavar="DIR",
                           help="write player.js, the data and the map as separate files in DIR, for a website")
        s.set_defaults(fn=fn)
    s = sub.add_parser("key", help="API keys for feeds that need one: set, list, remove")
    s.add_argument("action", choices=["set", "list", "remove"])
    s.add_argument("name", nargs="?")
    s.set_defaults(fn=cmd_key)
    s = sub.add_parser("stats", help="counts for a caption: runs, paths, vehicles moving over time")
    s.add_argument("recipe")
    s.add_argument("--every", type=int, default=5, help="minutes between rows (default 5)")
    s.set_defaults(fn=cmd_stats)
    args = p.parse_args(argv)
    args.fn(args)
    for w in recipe_mod.WARNINGS + render_mod.WARNINGS:  # repeated last, where a quick look at the output will see it
        log(f"WARNING: {w}")


if __name__ == "__main__":
    main()
