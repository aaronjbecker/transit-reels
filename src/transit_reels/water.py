"""Sea, lakes and rivers for the map, from OpenStreetMap through the public Overpass API (no key).

Coastlines in OSM are lines with the land on their left, not polygons. Instead of assembling
polygons, the coastline is drawn as a barrier on a raster, the regions between barriers are
flood-filled, and each region is voted sea or land by test points just right (sea side) or
left (land side) of the coastline. Lakes and riverbanks are ordinary polygons drawn on top.
"""

from __future__ import annotations

import gzip
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

# Tried in turn: the main server goes down for hours at a time.
OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.openstreetmap.fr/api/interpreter")
TILES = "https://tiles.openfreemap.org/planet"
# Frames wider than this draw water from Natural Earth (public domain, 1:10m) instead: at
# country scale Overpass runs out of memory, and 1:10m detail is plenty for the picture.
COUNTRY_KM = 150
NATURAL_EARTH = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/"


def fetch(bbox: tuple[float, float, float, float], cache: Path, log=print) -> dict:
    """Coastline and water bodies in (west, south, east, north), cached as JSON. An earlier fetch
    that already covers this box is reused: extra water outside the frame does no harm."""
    if cache.exists():
        return json.loads(cache.read_text())
    w, s, e, n = bbox
    for f in cache.parent.glob("*.json") if cache.parent.exists() else ():
        try:
            w0, s0, e0, n0 = (float(v) for v in f.stem.split("_"))
        except ValueError:
            continue
        if w0 <= w and s0 <= s and e0 >= e and n0 >= n and (e0 - w0) < 4 * (e - w):
            return json.loads(f.read_text())
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
    for attempt in range(4):
        server = OVERPASS[attempt % len(OVERPASS)]
        try:
            req = urllib.request.Request(server, data=data, headers={"User-Agent": "transit-reels"})
            with urllib.request.urlopen(req, timeout=240) as r:
                out = json.loads(r.read())
            # Overpass reports a failed query (out of memory, timeout) as a 200 with a remark
            # and no elements: an empty map that must not be cached as if it were real.
            if "error" in out.get("remark", "").lower():
                raise RuntimeError(f"Overpass: {out['remark'].strip()[:160]}")
            break
        except Exception as err:  # Overpass is a shared free service: back off and retry
            if attempt == 3:
                raise
            log(f"  Overpass failed ({err}); trying again in 20 s")
            time.sleep(20)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(out))
    return out


def _varint(b: bytes, i: int) -> tuple[int, int]:
    v, shift = 0, 0
    while True:
        c = b[i]
        i += 1
        v |= (c & 0x7f) << shift
        if not c & 0x80:
            return v, i
        shift += 7


def _fields(b: bytes):
    """(field number, value) of a protobuf message: an int, or bytes for a length-delimited field."""
    i = 0
    while i < len(b):
        key, i = _varint(b, i)
        kind = key & 7
        if kind == 0:
            v, i = _varint(b, i)
        elif kind == 2:
            n, i = _varint(b, i)
            v, i = b[i:i + n], i + n
        elif kind == 1:
            v, i = b[i:i + 8], i + 8
        elif kind == 5:
            v, i = b[i:i + 4], i + 4
        else:
            raise ValueError(f"protobuf wire type {kind}")
        yield key >> 3, v


def _rings_of(geometry: bytes) -> list[list[tuple[int, int]]]:
    """A vector-tile polygon's rings, in tile units."""
    rings, ring, x, y, i = [], [], 0, 0, 0
    while i < len(geometry):
        cmd, i = _varint(geometry, i)
        op, count = cmd & 7, cmd >> 3
        if op == 7:
            rings.append(ring)
            ring = []
            continue
        for _ in range(count):
            dx, i = _varint(geometry, i)
            dy, i = _varint(geometry, i)
            x += (dx >> 1) ^ -(dx & 1)
            y += (dy >> 1) ^ -(dy & 1)
            if op == 1:
                ring = []
            ring.append((x, y))
    return rings


def _water_polygons(tile: bytes) -> tuple[int, list[list[list[tuple[int, int]]]]]:
    """(extent, each feature's rings) of the tile's water layer."""
    extent, out = 4096, []
    for f, layer in _fields(tile):
        if f != 3:
            continue
        parts = list(_fields(layer))
        if next((v for k, v in parts if k == 1), b"") != b"water":
            continue
        extent = next((v for k, v in parts if k == 5), 4096)
        for k, feature in parts:
            if k == 2:
                geom = next((v for j, v in _fields(feature) if j == 4), b"")
                out.append(_rings_of(geom))
    return extent, out


def _tile(url: str, z: int, x: int, y: int, cache_dir: Path) -> bytes:
    f = cache_dir / str(z) / str(x) / f"{y}.pbf"
    if f.exists():
        return f.read_bytes()
    req = urllib.request.Request(url.format(z=z, x=x, y=y), headers={"User-Agent": "transit-reels"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
    except urllib.error.HTTPError as err:
        if err.code != 404:  # no tile: nothing mapped there
            raise
        data = b""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.with_suffix(".part").write_bytes(data)
    f.with_suffix(".part").rename(f)
    return data


def tiles_mask(bbox, width_km: float, cache_dir: Path, to_px, width: int, height: int, log=print) -> np.ndarray:
    """Boolean water mask from OpenFreeMap's vector tiles (OpenStreetMap data, no key, no query
    server to wait on). Each water polygon comes whole in the tile, so there is no coastline to
    assemble. Used by grids, whose many small maps need no finer detail."""
    with urllib.request.urlopen(urllib.request.Request(TILES, headers={"User-Agent": "transit-reels"}), timeout=60) as r:
        url = json.loads(r.read())["tiles"][0]
    z = 12 if width_km <= 50 else 11 if width_km <= 100 else 10
    n = 2 ** z
    w, s, e, nn = bbox
    tx = lambda lon: int((lon + 180) / 360 * n)
    ty = lambda lat: int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    xy = [(x % n, y) for x in range(tx(w), tx(e) + 1) for y in range(ty(nn), ty(s) + 1)]
    with ThreadPoolExecutor(8) as pool:
        tiles = list(pool.map(lambda p: _tile(url, z, p[0], p[1], cache_dir), xy))
    img = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(img)

    def px(ring, x, y, extent):
        lon = (x + np.array([p[0] for p in ring]) / extent) / n * 360 - 180
        lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * (y + np.array([p[1] for p in ring]) / extent) / n))))
        a, b = to_px(lon, lat)
        return list(zip(a.tolist(), b.tolist()))

    for (x, y), tile in zip(xy, tiles):
        if not tile:
            continue
        extent, features = _water_polygons(tile)
        for rings in features:
            # In a vector tile, an exterior ring has positive area and a hole negative.
            for ring in rings:
                if len(ring) < 3:
                    continue
                a = sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(ring, ring[1:] + ring[:1]))
                draw.polygon(px(ring, x, y, extent), fill=255 if a > 0 else 0)
    return np.asarray(img) > 127


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


def _points(geometry: list) -> list[tuple[float, float]]:
    """(lon, lat) of an Overpass geometry; some servers send null for points outside the bbox."""
    return [(g["lon"], g["lat"]) for g in geometry if g]


def mask(osm: dict, to_px, width: int, height: int) -> np.ndarray:
    """Boolean water mask, height x width."""
    coast, polys = [], []  # polys: (outer rings, inner rings)
    for el in osm.get("elements", []):
        tags = el.get("tags", {})
        if el["type"] == "way" and "geometry" in el:
            line = _points(el["geometry"])
            if tags.get("natural") == "coastline":
                coast.append(line)
            else:
                polys.append(([line], []))
        elif el["type"] == "relation":
            outer = [_points(m["geometry"]) for m in el.get("members", [])
                     if m.get("role") == "outer" and "geometry" in m]
            inner = [_points(m["geometry"]) for m in el.get("members", [])
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
