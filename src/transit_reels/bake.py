"""Turn one day of a GTFS timetable into timed paths: for every vehicle running in the window,
a polyline along its route shape with a scheduled time at every vertex.

How a vehicle's position is worked out (the whole recipe):
1. The trips that run on the day are those whose service_id runs on it (calendar.txt plus the
   calendar_dates.txt exceptions). Trips of the PREVIOUS day whose times run past 24:00 are
   still on the road after midnight, so they come in too, shifted back by 24 h.
2. frequencies.txt trips are templates: one copy per headway between start_time and end_time.
3. Each stop is placed on the route's shape at its distance along it (projected, never
   trusting shape_dist_traveled units). With no shape, straight lines between stops.
4. Stops without times (non-timepoints) get times interpolated by distance between timed stops.
5. Between two stops the vehicle moves at constant speed along the shape; at a stop it waits
   from arrival_time to departure_time.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np

from .gtfs import Calendar, Feed, base_route_type, seconds

ARR, DEP, MID = 0, 1, 2
DAY = 86400


def _local_xy(lon, lat, lat0):
    """Equirectangular meters: plenty for distances along a city route."""
    k = 111_320.0
    return np.column_stack([np.asarray(lon) * k * math.cos(math.radians(lat0)), np.asarray(lat) * k])


def _locate_stops(shape_xy: np.ndarray, cum: np.ndarray, stops_xy: np.ndarray) -> np.ndarray:
    """Distance along the shape of each stop, never going backwards. Where the shape passes a
    stop twice (loops), the earliest pass within 30 m of the best match wins."""
    a, b = shape_xy[:-1], shape_xy[1:]
    ab = b - a
    seg_len = np.hypot(ab[:, 0], ab[:, 1])
    l2 = np.maximum(seg_len ** 2, 1e-9)
    out, prev = [], 0.0
    for p in stops_xy:
        t = np.clip(((p - a) * ab).sum(1) / l2, 0, 1)
        q = a + t[:, None] * ab
        dist = np.hypot(*(p - q).T)
        along = cum[:-1] + t * seg_len
        dist = np.where(along >= prev - 1.0, dist, np.inf)
        if not np.isfinite(dist).any():
            out.append(cum[-1])
            continue
        ok = np.flatnonzero(dist <= dist.min() + 30.0)
        prev = float(along[ok[0]])
        out.append(prev)
    return np.array(out)


class Pattern:
    """One stop sequence on one shape: the points a vehicle passes and, for each point, which
    stop interval it sits in and how far through it, so any trip's vertex times come from its
    stop times in one vectorised step."""

    def __init__(self, lonlat: np.ndarray, cum: np.ndarray, stop_d: np.ndarray):
        pts, seg, frac, kind = [], [], [], []
        n = len(stop_d)
        for i in range(n):
            p = [np.interp(stop_d[i], cum, lonlat[:, 0]), np.interp(stop_d[i], cum, lonlat[:, 1])]
            pts += [p, p]; seg += [i, i]; frac += [0.0, 0.0]; kind += [ARR, DEP]
            if i < n - 1 and stop_d[i + 1] > stop_d[i]:
                inside = np.flatnonzero((cum > stop_d[i]) & (cum < stop_d[i + 1]))
                for v in inside:
                    pts.append(lonlat[v]); seg.append(i); kind.append(MID)
                    frac.append((cum[v] - stop_d[i]) / (stop_d[i + 1] - stop_d[i]))
        self.lonlat = np.array(pts, dtype=np.float64)
        self.seg = np.array(seg)
        self.frac = np.array(frac)
        self.kind = np.array(kind)
        self.stop_d = stop_d
        self.line = lonlat  # the full drawn geometry, for the map's network layer

    def times(self, arr: np.ndarray, dep: np.ndarray) -> np.ndarray:
        nxt = np.minimum(self.seg + 1, len(arr) - 1)
        mid = dep[self.seg] + self.frac * (arr[nxt] - dep[self.seg])
        return np.where(self.kind == ARR, arr[self.seg], np.where(self.kind == DEP, dep[self.seg], mid))


def _fill_times(d: np.ndarray, arr: list, dep: list) -> tuple[np.ndarray, np.ndarray]:
    """Complete arrival/departure times: one copies the other where only one is given, and
    untimed stops are interpolated by distance between the timed ones."""
    a = np.array([x if x is not None else (y if y is not None else np.nan) for x, y in zip(arr, dep)], float)
    b = np.array([y if y is not None else (x if x is not None else np.nan) for x, y in zip(arr, dep)], float)
    known = ~np.isnan(a)
    if known.sum() < 2:
        return a, b
    if not known.all():
        a[~known] = np.interp(d[~known], d[known], a[known])
        b[~known] = a[~known]
    return a, np.maximum(b, a)


def _drop_bad_stops(stops: dict, log=print):
    """Drops stops whose coordinates are impossible (out of range, at 0,0) or far outside the
    network (a typo like 5.957 for 59.57 would draw a line across the frame). Returns the kept
    stops and a test for shape points by the same rule."""
    if not stops:
        return stops, lambda lon, lat: True
    def valid(lon, lat):
        return -90 <= lat <= 90 and -180 <= lon <= 180 and not (abs(lat) < 1 and abs(lon) < 1)
    ok = {k: p for k, p in stops.items() if valid(*p)}
    if ok:
        ll = np.array(list(ok.values()))
        lon0, lat0 = np.median(ll, axis=0)
        d = np.hypot((ll[:, 0] - lon0) * np.cos(np.radians(lat0)), ll[:, 1] - lat0)
        # Degrees. The floor (~220 km) keeps long commuter and intercity lines; typos land
        # tens of degrees away.
        reach = max(5 * float(np.percentile(d, 95)), 2.0)
    def near(lon, lat):
        return valid(lon, lat) and np.hypot((lon - lon0) * np.cos(np.radians(lat0)), lat - lat0) <= reach
    kept = {k: p for k, p in ok.items() if near(*p)}
    bad = sorted(set(stops) - set(kept))
    if bad:
        shown = ", ".join(f"{k} ({stops[k][1]:g}, {stops[k][0]:g})" for k in bad[:5])
        log(f"  ! skipped {len(bad)} stop(s) with impossible coordinates: {shown}{' ...' if len(bad) > 5 else ''}")
    return kept, (near if ok else (lambda lon, lat: True))


STRAIGHT_TYPES = {4, 6}  # ferries and aerial lifts really do go (nearly) straight

# Fastest believable speed between two stops, km/h, by basic route type. A run that needs more
# has a stop placed on the wrong stretch of its shape, or broken times, and would streak across
# the map. Generous on purpose: the half minute of slack in _too_fast absorbs times rounded to
# the minute, so only real errors trip it.
MAX_KMH = {0: 100, 1: 130, 2: 250, 3: 120, 4: 80, 5: 50, 6: 50, 7: 50, 11: 120, 12: 120}
SLACK_S = 30


def _too_fast(stop_d: np.ndarray, arr: np.ndarray, dep: np.ndarray, route_type: int) -> bool:
    """True if any stop-to-stop hop is faster than the mode can go."""
    dist_km = np.diff(stop_d) / 1000
    hours = (np.maximum(arr[1:] - dep[:-1], 0) + SLACK_S) / 3600
    return bool((dist_km / hours > MAX_KMH.get(route_type, 250)).any())


def bake(feed: Feed, day: dt.date, start_s: int, end_s: int, route_types: list[int] | None = None,
         margin_s: int = 120, log=print, straight: bool = False) -> dict:
    """Every trip on the road between start_s and end_s (seconds after midnight of `day`).
    `straight` draws trips that have no route shape as straight stop-to-stop lines; by default
    they are left out when the feed has shapes for its other trips, since a wrong path is worse
    than a missing vehicle."""
    cal = Calendar(feed)
    today, yesterday = cal.services_on(day), cal.services_on(day - dt.timedelta(days=1))
    log(f"  services: {len(today)} running on {day}, {len(yesterday)} the day before")

    routes = {}
    for r in feed.rows("routes.txt"):
        raw = int(r.get("route_type") or 3)
        rtype = base_route_type(raw)
        # route_types may name basic codes (2: all rail) or a feed's extended ones (109: suburban
        # rail only), so a recipe can keep the S-Bahn and leave out regional trains.
        if route_types is not None and rtype not in route_types and raw not in route_types:
            continue
        routes[r["route_id"]] = {
            "type": rtype,
            "color": "#" + (r.get("route_color") or "").lstrip("#") if r.get("route_color") else None,
            "short": r.get("route_short_name", ""),
            "long": r.get("route_long_name", ""),
            "agency": r.get("agency_id", ""),
        }

    trips = {}
    for t in feed.rows("trips.txt"):
        if t["route_id"] not in routes:
            continue
        offsets = ([0] if t["service_id"] in today else []) + ([-DAY] if t["service_id"] in yesterday else [])
        if offsets:
            trips[t["trip_id"]] = (t["route_id"], t.get("shape_id", ""), offsets, t.get("trip_headsign", ""))

    freq = defaultdict(list)
    for f in feed.rows("frequencies.txt"):
        if f["trip_id"] in trips:
            freq[f["trip_id"]].append((seconds(f["start_time"]), seconds(f["end_time"]), int(f["headway_secs"])))
    log(f"  {len(trips):,} trips scheduled ({len(freq):,} headway templates); reading stop_times")

    stop_times = defaultdict(list)
    for tid, seq, a, d, sid in feed.columns(
            "stop_times.txt", ["trip_id", "stop_sequence", "arrival_time", "departure_time", "stop_id"]):
        if tid in trips:
            stop_times[tid].append((int(seq), seconds(a), seconds(d), sid))

    # Which instances overlap the window, before any geometry work.
    lo, hi = start_s - margin_s, end_s + margin_s
    instances = []  # (trip_id, shift_seconds)
    for tid, rows in stop_times.items():
        rows.sort()
        timed = [x for r in rows for x in (r[1], r[2]) if x is not None]
        if len(rows) < 2 or not timed:
            continue
        first, last = min(timed), max(timed)
        for off in trips[tid][2]:
            if tid in freq:
                for f0, f1, h in freq[tid]:
                    for s in range(f0, f1, h):
                        shift = off + s - first
                        if first + shift <= hi and last + shift >= lo:
                            instances.append((tid, shift))
            elif first + off <= hi and last + off >= lo:
                instances.append((tid, off))
    need_stops = {r[3] for tid, _ in instances for r in stop_times[tid]}
    stops, stop_names = {}, {}
    for s in feed.rows("stops.txt"):
        if s["stop_id"] in need_stops and s.get("stop_lat") and s.get("stop_lon"):
            stops[s["stop_id"]] = (float(s["stop_lon"]), float(s["stop_lat"]))
            stop_names[s["stop_id"]] = s.get("stop_name", "")
    stops, near = _drop_bad_stops(stops, log)
    if not stops:
        raise SystemExit("No vehicles in that window: check the date, the times and the route types.")
    lat0 = float(np.median([p[1] for p in stops.values()]))

    need_shapes = {trips[tid][1] for tid, _ in instances if trips[tid][1]}
    shape_rows = defaultdict(list)
    for sid, seq, lat, lon in feed.columns("shapes.txt", ["shape_id", "shape_pt_sequence", "shape_pt_lat", "shape_pt_lon"]):
        if sid in need_shapes and near(float(lon), float(lat)):
            shape_rows[sid].append((int(seq), float(lon), float(lat)))
    shapes = {}
    for sid, rows in shape_rows.items():
        rows.sort()
        ll = np.array([[r[1], r[2]] for r in rows])
        xy = _local_xy(ll[:, 0], ll[:, 1], lat0)
        step = np.hypot(*np.diff(xy, axis=0).T)
        keep = np.concatenate([[True], step > 0.5])  # drop repeated points
        ll, xy = ll[keep], xy[keep]
        shapes[sid] = (ll, xy, np.concatenate([[0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]))

    patterns: dict[tuple, Pattern | None] = {}
    out_trips = []
    # A feed with no shapes at all can only draw straight lines between stops: refuse it unless
    # the recipe accepts that (ferries and lifts excepted, they go nearly straight anyway).
    if not shapes and not straight and any(routes[trips[t][0]]["type"] not in STRAIGHT_TYPES for t, _ in instances):
        name = Path(str(getattr(feed, "path", feed))).name
        raise SystemExit(
            f"{name} has no route shapes (no shapes.txt), so every vehicle would move in a straight line "
            "between stops, cutting across blocks, hills and water.\n"
            "  Better: find another feed of the same network that has shapes (`transit-reels find <city>`; "
            "the agency's own feed often does when a national aggregate does not).\n"
            "  Or accept straight lines: add `straight = true` to this feed in the recipe.")
    dropped: dict[str, int] = defaultdict(int)
    too_fast: dict[str, int] = defaultdict(int)
    for tid, shift in instances:
        rows = [r for r in stop_times[tid] if r[3] in stops]
        if len(rows) < 2:
            continue
        route_id, shape_id, _, headsign = trips[tid]
        key = (shape_id if shape_id in shapes else "", tuple(r[3] for r in rows),
               routes[route_id]["type"] in STRAIGHT_TYPES)
        if key not in patterns:
            s_ll = np.array([stops[r[3]] for r in rows])
            s_xy = _local_xy(s_ll[:, 0], s_ll[:, 1], lat0)
            if key[0] and len(shapes[key[0]][0]) >= 2:
                ll, xy, cum = shapes[key[0]]
                patterns[key] = Pattern(ll, cum, _locate_stops(xy, cum, s_xy))
            elif straight or routes[route_id]["type"] in STRAIGHT_TYPES:
                cum = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(s_xy, axis=0).T))])
                patterns[key] = Pattern(s_ll, cum, cum)
            else:
                patterns[key] = None
        pat = patterns[key]
        if pat is None:
            dropped[route_id] += 1
            continue
        arr, dep = _fill_times(pat.stop_d, [r[1] for r in rows], [r[2] for r in rows])
        if np.isnan(arr).any():
            continue
        if _too_fast(pat.stop_d, arr, dep, routes[route_id]["type"]):
            too_fast[route_id] += 1
            continue
        t = pat.times(arr + shift, dep + shift)
        # Keep only the stretch inside the window (plus one vertex either side to interpolate).
        i0 = max(int(np.searchsorted(t, lo, "right")) - 1, 0)
        i1 = min(int(np.searchsorted(t, hi, "left")) + 1, len(t))
        if i1 - i0 < 2:
            continue
        # The trip's stops and scheduled times, for the interactive page (stops more than half
        # an hour outside the window are left off). timed is False where the feed gives no
        # time and it was interpolated.
        near_window = [(r[3], float(a + shift), float(d + shift), r[1] is not None or r[2] is not None)
                       for r, a, d in zip(rows, arr, dep) if lo - 1800 <= a + shift <= hi + 1800]
        out_trips.append({"route": route_id, "pattern": id(pat), "lonlat": pat.lonlat[i0:i1], "t": t[i0:i1],
                          "headsign": headsign, "stops": near_window})

    route_of = {}
    for tr in out_trips:
        route_of.setdefault(tr["pattern"], tr["route"])
    network = [{"route": route_of[id(p)], "lonlat": p.line} for p in patterns.values() if id(p) in route_of]
    if dropped:
        names = ", ".join(sorted({routes[r].get("short") or r for r in dropped})[:8])
        log(f"  ! left out {sum(dropped.values()):,} runs on {len(dropped)} route(s) with no route shape "
            f"({names}{' ...' if len(dropped) > 8 else ''}): a straight line between stops would be a wrong path. "
            "`straight = true` on the feed draws them anyway")
    if too_fast:
        names = ", ".join(sorted({routes[r].get("short") or r for r in too_fast})[:8])
        log(f"  ! left out {sum(too_fast.values()):,} runs on {len(too_fast)} route(s) that would move faster "
            f"than the mode can ({names}{' ...' if len(too_fast) > 8 else ''}): a stop placed on the wrong "
            "stretch of the shape, or broken times in the feed")
    used_routes = {tr["route"] for tr in out_trips}
    log(f"  baked {len(out_trips):,} vehicle runs on {len(used_routes)} routes, {len(network)} distinct paths "
        f"(window plus {margin_s // 60} min either side)")
    used_stops = {s[0] for tr in out_trips for s in tr["stops"]}
    agencies = {a.get("agency_id", ""): a.get("agency_name", "") for a in feed.rows("agency.txt")}
    if len(agencies) == 1:  # a lone agency may leave agency_id out, here and in routes.txt
        agencies[""] = next(iter(agencies.values()))
    return {"day": day.isoformat(), "start": start_s, "end": end_s,
            "routes": {k: v for k, v in routes.items() if k in used_routes},
            "trips": out_trips, "network": network,
            "stops": {k: (stop_names[k], *stops[k]) for k in used_stops},
            "agencies": {k: v for k, v in agencies.items() if any(r["agency"] == k for r in routes.values())}}


def merge(parts: list[dict]) -> dict:
    """Several feeds baked for the same window, as one (route ids prefixed per feed)."""
    if len(parts) == 1:
        return parts[0]
    out = {k: parts[0][k] for k in ("day", "start", "end")}
    out.update(routes={}, trips=[], network=[], stops={}, agencies={})
    for i, p in enumerate(parts):
        out["routes"].update({f"{i}:{k}": dict(v, agency=f"{i}:{v['agency']}") for k, v in p["routes"].items()})
        out["trips"] += [dict(t, route=f"{i}:{t['route']}", stops=[(f"{i}:{s[0]}", *s[1:]) for s in t["stops"]])
                         for t in p["trips"]]
        out["network"] += [dict(n, route=f"{i}:{n['route']}") for n in p["network"]]
        out["stops"].update({f"{i}:{k}": v for k, v in p["stops"].items()})
        out["agencies"].update({f"{i}:{k}": v for k, v in p["agencies"].items()})
    return out


def _hhmm(s: float) -> str:
    s = int(s) % DAY
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}"


def save(baked: dict, path: Path) -> None:
    """One .npz with every vertex, plus a small .json beside it with the route table."""
    trips, net = baked["trips"], baked["network"]
    route_ids = sorted(baked["routes"])
    rix = {r: i for i, r in enumerate(route_ids)}
    stop_ids = sorted(baked["stops"])
    six = {s: i for i, s in enumerate(stop_ids)}
    sched = [s for t in trips for s in t["stops"]]
    heads = sorted({t["headsign"] for t in trips})
    hix = {h: i for i, h in enumerate(heads)}
    np.savez_compressed(
        path,
        trip_head=np.array([hix[t["headsign"]] for t in trips]),
        sched_off=np.cumsum([0] + [len(t["stops"]) for t in trips]),
        sched_stop=np.array([six[s[0]] for s in sched], np.int64).reshape(-1),
        sched_time=np.array([s[1:3] for s in sched], np.float64).reshape(-1, 2),
        sched_timed=np.array([s[3] for s in sched], bool).reshape(-1),
        trip_pts=np.concatenate([np.column_stack([t["lonlat"], t["t"]]) for t in trips]).astype(np.float64),
        trip_off=np.cumsum([0] + [len(t["t"]) for t in trips]),
        trip_route=np.array([rix[t["route"]] for t in trips]),
        net_pts=np.concatenate([n["lonlat"] for n in net]),
        net_off=np.cumsum([0] + [len(n["lonlat"]) for n in net]),
        net_route=np.array([rix[n["route"]] for n in net]),
    )
    meta = {k: baked[k] for k in ("day", "start", "end")}
    meta["routes"] = [dict(id=r, **baked["routes"][r]) for r in route_ids]
    meta["stops"] = [[s, *baked["stops"][s]] for s in stop_ids]
    meta["agencies"] = baked["agencies"]
    meta["headsigns"] = heads
    path.with_suffix(".json").write_text(json.dumps(meta, indent=1))


def load(path: Path) -> dict:
    z = np.load(path)
    meta = json.loads(path.with_suffix(".json").read_text())
    meta.update({k: z[k] for k in z.files})
    return meta
