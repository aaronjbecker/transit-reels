"""Sea, lakes and rivers for the map, from OpenStreetMap through the public Overpass API (no key).

Coastlines in OSM are lines with the land on their left, not polygons. Instead of assembling
polygons, the coastline is drawn as a barrier on a raster, the regions between barriers are
flood-filled, and each region is voted sea or land by test points just right (sea side) or
left (land side) of the coastline. Lakes and riverbanks are ordinary polygons drawn on top.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

OVERPASS = "https://overpass-api.de/api/interpreter"
# Frames wider than this draw water from Natural Earth (public domain, 1:10m) instead: at
# country scale Overpass runs out of memory, and 1:10m detail is plenty for the picture.
COUNTRY_KM = 150
NATURAL_EARTH = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/"


def fetch(bbox: tuple[float, float, float, float], cache: Path, log=print) -> dict:
    """Coastline and water bodies in (west, south, east, north), cached as JSON."""
    if cache.exists():
        return json.loads(cache.read_text())
    w, s, e, n = bbox
    b = f"{s:.5f},{w:.5f},{n:.5f},{e:.5f}"
    query = f"""[out:json][timeout:180];
(
  way["natural"="coastline"]({b});
  way["natural"="water"]({b});
  relation["natural"="water"]({b});
  way["waterway"="riverbank"]({b});
  relation["waterway"="riverbank"]({b});
);
out geom;"""
    log("  fetching water from OpenStreetMap (Overpass)...")
    data = urllib.parse.urlencode({"data": query}).encode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(OVERPASS, data=data, headers={"User-Agent": "transit-reels"})
            with urllib.request.urlopen(req, timeout=240) as r:
                out = json.loads(r.read())
            # Overpass reports a failed query (out of memory, timeout) as a 200 with a remark
            # and no elements: an empty map that must not be cached as if it were real.
            if "error" in out.get("remark", "").lower():
                raise RuntimeError(f"Overpass: {out['remark'].strip()[:160]}")
            break
        except Exception as err:  # Overpass is a shared free service: back off and retry
            if attempt == 2:
                raise
            log(f"  Overpass failed ({err}); retrying in 20 s")
            time.sleep(20)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out))
    return out


def _natural_earth(name: str, cache_dir: Path, log=print) -> dict:
    f = cache_dir / f"{name}.geojson"
    if not f.exists():
        log(f"  fetching {name} from Natural Earth (once)...")
        cache_dir.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(NATURAL_EARTH + f"{name}.geojson", headers={"User-Agent": "transit-reels"})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
        json.loads(data)  # a broken download must not be cached
        f.with_suffix(".part").write_bytes(data)
        f.with_suffix(".part").rename(f)
    return json.loads(f.read_text())


def natural_earth_mask(bbox, cache_dir: Path, to_px, width: int, height: int, log=print) -> np.ndarray:
    """Boolean water mask for a wide frame: everything is sea, minus Natural Earth's land, plus
    its lakes."""
    w, s, e, n = bbox
    img = Image.new("L", (width, height), 1)
    draw = ImageDraw.Draw(img)

    def polygons(geo):
        for feat in geo["features"]:
            g = feat["geometry"]
            for poly in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]):
                ring = np.asarray(poly[0])
                if ring[:, 0].max() < w or ring[:, 0].min() > e or ring[:, 1].max() < s or ring[:, 1].min() > n:
                    continue
                yield poly

    def fill(rings, outer, holes):
        x, y = to_px(np.asarray(rings[0])[:, 0], np.asarray(rings[0])[:, 1])
        draw.polygon(list(zip(x, y)), fill=outer)
        for hole in rings[1:]:
            x, y = to_px(np.asarray(hole)[:, 0], np.asarray(hole)[:, 1])
            draw.polygon(list(zip(x, y)), fill=holes)

    for poly in polygons(_natural_earth("ne_10m_land", cache_dir, log)):
        fill(poly, 0, 1)
    for poly in polygons(_natural_earth("ne_10m_lakes", cache_dir, log)):
        fill(poly, 1, 0)
    return np.asarray(img, bool)


def _rings(ways: list[list[tuple[float, float]]]) -> list[list[tuple[float, float]]]:
    """Join way fragments end to end into closed rings (multipolygon members come in pieces)."""
    pieces = [list(w) for w in ways if len(w) >= 2]
    rings = []
    while pieces:
        ring = pieces.pop()
        changed = True
        while ring[0] != ring[-1] and changed:
            changed = False
            for i, p in enumerate(pieces):
                if p[0] == ring[-1]:
                    ring += p[1:]
                elif p[-1] == ring[-1]:
                    ring += p[::-1][1:]
                elif p[-1] == ring[0]:
                    ring = p[:-1] + ring
                elif p[0] == ring[0]:
                    ring = p[::-1][:-1] + ring
                else:
                    continue
                pieces.pop(i)
                changed = True
                break
        rings.append(ring)  # an unclosed ring at the edge of the query is drawn as-is
    return rings


def mask(osm: dict, to_px, width: int, height: int) -> np.ndarray:
    """Boolean water mask, height x width."""
    coast, polys = [], []  # polys: (outer rings, inner rings)
    for el in osm.get("elements", []):
        tags = el.get("tags", {})
        if el["type"] == "way" and "geometry" in el:
            line = [(g["lon"], g["lat"]) for g in el["geometry"]]
            if tags.get("natural") == "coastline":
                coast.append(line)
            else:
                polys.append(([line], []))
        elif el["type"] == "relation":
            outer = [[(g["lon"], g["lat"]) for g in m["geometry"]] for m in el.get("members", [])
                     if m.get("role") == "outer" and "geometry" in m]
            inner = [[(g["lon"], g["lat"]) for g in m["geometry"]] for m in el.get("members", [])
                     if m.get("role") == "inner" and "geometry" in m]
            polys.append((_rings(outer), _rings(inner)))

    def px(line):
        x, y = to_px(np.array([p[0] for p in line]), np.array([p[1] for p in line]))
        return np.column_stack([x, y])

    water = np.zeros((height, width), bool)
    if coast:
        barrier = Image.new("I", (width, height), 0)
        draw = ImageDraw.Draw(barrier)
        lines = [px(c) for c in coast]
        for xy in lines:
            draw.line([tuple(p) for p in xy], fill=1, width=2)
        # Label every region a test point lands in; vote sea (right of the line) or land (left).
        votes, label = Counter(), 2
        for xy in lines:
            d = np.diff(xy, axis=0)
            length = np.hypot(d[:, 0], d[:, 1])
            for i in np.flatnonzero(length > 1.0):
                mid = (xy[i] + xy[i + 1]) / 2
                # (-dy, dx) points to the RIGHT of travel in pixel space (y grows downward),
                # which is the sea side of an OSM coastline.
                normal = np.array([-d[i, 1], d[i, 0]]) / length[i]
                for side, sign in (("sea", 1), ("land", -1)):
                    x, y = (mid + sign * 4 * normal).round().astype(int)
                    if not (0 <= x < width and 0 <= y < height):
                        continue
                    v = barrier.getpixel((x, y))
                    if v == 0:
                        ImageDraw.floodfill(barrier, (x, y), label)
                        v, label = label, label + 1
                    if v >= 2:
                        votes[(v, side)] += 1
        labels = np.array(barrier)
        for v in range(2, label):
            if votes[(v, "sea")] > votes[(v, "land")]:
                water |= labels == v
    img = Image.fromarray(water.astype(np.uint8) * 255)
    draw = ImageDraw.Draw(img)
    for outer, inner in polys:
        for ring in outer:
            if len(ring) >= 3:
                draw.polygon([tuple(p) for p in px(ring)], fill=255)
        for ring in inner:
            if len(ring) >= 3:
                draw.polygon([tuple(p) for p in px(ring)], fill=0)
    return np.array(img) > 127
