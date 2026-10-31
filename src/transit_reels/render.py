"""Draw the reel: a static map plate, a dot per vehicle on top, and the title, clock and
credit. A plain numpy frame loop piped to ffmpeg; the camera never moves.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import water as water_mod
from .geo import Frame

FONT = Path(__file__).parent / "fonts" / "SpaceGrotesk.ttf"

# Used when a feed leaves route_color blank (or sets it to near-black / near-white), and for
# every route when style.color_by = "mode" (whole countries, where route colors are noise).
FALLBACK = {0: "#7bd389", 1: "#4fc3f7", 2: "#ff8a4c", 4: "#8ec9ff", 5: "#f48fb1",
            6: "#f48fb1", 7: "#f48fb1", 11: "#e0e0e0", 12: "#4dd0e1"}


def rgb(hexstr: str) -> np.ndarray:
    h = hexstr.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], float) / 255


# Where lines share a corridor, which is drawn on top. Bottom to top: the bus network, ferries,
# cable cars and funiculars, regional rail, trams, monorail, and metro always last, on top.
DRAW_RANK = {4: 1, 5: 2, 6: 2, 7: 2, 2: 3, 0: 4, 12: 5, 1: 6}


def draw_rank(route_type: int, style: dict) -> int:
    drawn = route_type in style["line_types"] or route_type in style["thin_types"]
    return DRAW_RANK.get(route_type, 3) if drawn else 0


def route_color(route: dict, style: dict) -> np.ndarray:
    if route["type"] not in style["line_types"] and route["type"] not in style["thin_types"]:
        return rgb(style["dot_color"])
    mode = style.get("mode_colors", {}).get(str(route["type"]))
    if style.get("color_by") == "mode" or mode:  # by mode, or just this mode recolored
        return rgb(mode or FALLBACK.get(route["type"], "#ffffff"))
    c = route.get("color")
    if c and len(c) == 7:
        v = rgb(c)
        if 0.12 < v.max() and v.min() < 0.92:  # not black, not white: usable on a dark map
            # Lift dark brand colors so they read on a near-black plate.
            return v + (1 - v) * max(0.0, 0.35 - v.max())
    return rgb(FALLBACK.get(route["type"], "#ffffff"))


def font(size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT), size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


# ---------------------------------------------------------------- the plate

WARNINGS: list[str] = []  # problems worth repeating at the end of a command


def plate(baked: dict, frame: Frame, style: dict, water_cache: Path | None, log=print) -> np.ndarray:
    """The still map under the vehicles: land, water and the network's lines. float32 HxWx3."""
    W, H, ss = frame.width, frame.height, 2
    u = min(W, H) / 1080
    img = Image.new("RGB", (W * ss, H * ss), style["land"])
    if water_cache is not None:
        try:
            to_px = lambda lon, lat: tuple(v * ss for v in frame.px(lon, lat))
            if frame.width_km > water_mod.COUNTRY_KM:
                m = water_mod.natural_earth_mask(frame.bbox(0.1), water_cache.parent / "naturalearth", to_px,
                                                 W * ss, H * ss, log)
            else:
                osm = water_mod.fetch(frame.bbox(0.1), water_cache, log)
                m = water_mod.mask(osm, to_px, W * ss, H * ss)
            img.paste(style["water"], mask=Image.fromarray(m.astype(np.uint8) * 255))
        except Exception as err:
            log(f"  ! no water layer ({err}); drawing land only")
            WARNINGS.append(f"no water drawn ({err}). OpenStreetMap's free Overpass service may be busy: "
                            "run again later, or set `water = false` under [map] if land only is intended.")

    draw = ImageDraw.Draw(img, "RGBA")
    routes = baked["routes"]
    pts, off, rix = baked["net_pts"], baked["net_off"], baked["net_route"]
    x, y = frame.px(pts[:, 0], pts[:, 1])
    tier = lambda t: 2 if t in style["line_types"] else 1 if t in style["thin_types"] else 0
    order = sorted(range(len(rix)), key=lambda i: draw_rank(routes[rix[i]]["type"], style))
    for i in order:
        r = routes[rix[i]]
        seg = list(zip(x[off[i]:off[i + 1]] * ss, y[off[i]:off[i + 1]] * ss))
        if tier(r["type"]):
            c = (route_color(r, style) * 255).astype(int)
            w, a = ((style["line_width"], style["line_alpha"]) if tier(r["type"]) == 2
                    else (style["thin_width"], style["thin_alpha"]))
            draw.line(seg, fill=(*c, int(255 * a)), width=max(1, round(w * u * ss)), joint="curve")
        else:
            c = rgb(style["network"]) * 255
            draw.line(seg, fill=(*c.astype(int), int(255 * style["network_alpha"])), width=max(1, round(style["network_width"] * u * ss)))
    img = img.resize((W, H), Image.LANCZOS)
    return np.asarray(img, np.float32) / 255


# ---------------------------------------------------------------- vehicles

def splat(buf: np.ndarray, H: int, W: int, x: np.ndarray, y: np.ndarray, col: np.ndarray,
          gain: float, radius: float = 0.0, sigma: float = 0.0) -> None:
    """Add a dot for every vehicle into buf (4 x H*W): color-weighted sums in rows 0-2, the
    weight in row 3. With `radius`, a crisp disc with a one-pixel anti-aliased edge (sharp, yet
    smooth at any sub-pixel position); with `sigma`, a soft Gaussian (used for the halo)."""
    if len(x) == 0:
        return
    r = int(np.ceil(radius + 1)) if radius else int(np.ceil(sigma * 3))
    k = np.arange(-r, r + 1)
    ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
    dx = k[None, :] - (x - ix)[:, None] + 0.5  # pixel centers relative to each vehicle
    dy = k[None, :] - (y - iy)[:, None] + 0.5
    if radius:
        d = np.sqrt(dy[:, :, None] ** 2 + dx[:, None, :] ** 2)
        w = np.clip(radius + 0.5 - d, 0, 1) * gain
    else:
        gx, gy = np.exp(-dx ** 2 / (2 * sigma ** 2)), np.exp(-dy ** 2 / (2 * sigma ** 2))
        w = (gy[:, :, None] * gx[:, None, :]) * gain
    rows = iy[:, None, None] + k[None, :, None]
    cols = ix[:, None, None] + k[None, None, :]
    rows, cols = np.broadcast_to(rows, w.shape), np.broadcast_to(cols, w.shape)
    ok = (rows >= 0) & (rows < H) & (cols >= 0) & (cols < W)
    flat = (rows * W + cols)[ok]
    w = w[ok]
    buf[3] += np.bincount(flat, w, minlength=H * W)
    for c in range(3):
        buf[c] += np.bincount(flat, w * np.broadcast_to(col[:, c, None, None], ok.shape)[ok], minlength=H * W)


class Vehicles:
    """Every trip's path in pixels, ready to be sampled at any time."""

    def __init__(self, baked: dict, frame: Frame, style: dict):
        pts, off = baked["trip_pts"], baked["trip_off"]
        self.x, self.y = frame.px(pts[:, 0], pts[:, 1])
        self.t, self.off = pts[:, 2], off
        routes = baked["routes"]
        rix = baked["trip_route"]
        self.is_line = np.array([routes[i]["type"] in style["line_types"] for i in rix], bool)
        col = np.array([route_color(routes[i], style) for i in rix]).reshape(-1, 3)
        # A train is its line's color lifted toward white, so it stands out on its own line.
        thin = np.array([routes[i]["type"] in style["thin_types"] for i in rix], bool)
        lift = np.where(self.is_line, style["line_dot"]["whiten"], np.where(thin, style["thin_whiten"], 0.0))[:, None]
        self.col = col + (1 - col) * lift
        self.t0 = self.t[off[:-1]]
        self.t1 = self.t[off[1:] - 1]

    def at(self, times: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Positions (F x N) at each time; NaN where a vehicle is not on the road."""
        F, N = len(times), len(self.t0)
        X = np.full((F, N), np.nan)
        Y = np.full((F, N), np.nan)
        live = np.flatnonzero((self.t0 <= times.max()) & (self.t1 >= times.min()))
        for j in live:
            a, b = self.off[j], self.off[j + 1]
            on = (times >= self.t0[j]) & (times <= self.t1[j])
            X[on, j] = np.interp(times[on], self.t[a:b], self.x[a:b])
            Y[on, j] = np.interp(times[on], self.t[a:b], self.y[a:b])
        return X, Y


# ---------------------------------------------------------------- chrome

def fitted(text: str, size: int, weight: str, max_w: float) -> ImageFont.FreeTypeFont:
    """The font at `size`, shrunk until the text fits in max_w pixels."""
    f = font(size, weight)
    while size > 10 and f.getlength(text) > max_w:
        size -= 1
        f = font(size, weight)
    return f


def credit_lines(text: str, size: int, max_w: float) -> tuple[list[str], ImageFont.FreeTypeFont]:
    """The credit on one line if it fits at a readable size, else wrapped onto as few lines as
    fit, breaking at its " · " separators first, then between words. Required attribution is
    never cut off."""
    f = fitted(text, size, "Regular", max_w)
    if f.size >= size * 0.8:
        return [text], f
    f = font(int(size * 0.9), "Regular")
    lines: list[str] = []
    for part in text.split(" · "):
        joined = f"{lines[-1]} · {part}" if lines else part
        if lines and f.getlength(joined) <= max_w:
            lines[-1] = joined
            continue
        line = ""
        for w in part.split(" "):
            if line and f.getlength(f"{line} {w}") > max_w:
                lines.append(line)
                line = w
            else:
                line = f"{line} {w}".strip()
        lines.append(line)
    return lines, fitted(max(lines, key=f.getlength), f.size, "Regular", max_w)


class Layout:
    """Where the words go. One left-aligned column: a small upper-case label, the title, the
    subtitle, then the clock with the vehicle count beside it; the credit line at the foot.
    Sizes are for a frame whose short side is 1080 px and scale with it."""

    def __init__(self, frame: Frame, style: dict, words: dict):
        u = min(frame.width, frame.height) / 1080
        self.W, self.H, self.u = frame.width, frame.height, u
        self.left, self.right = 64 * u, frame.width - 64 * u
        vertical = frame.height > frame.width
        # In a vertical reel the top ~13% sits under the platform's own buttons.
        y = (style["title_top"] if style["title_top"] is not None else (250 if vertical else 72)) * u
        self.label_font = font(int(24 * u), "Medium")
        self.label_y = y
        y += 46 * u if words.get("note") else 0
        self.title_y, self.title_size = y, int(96 * u)
        y += 112 * u
        self.sub_y = y
        y += 58 * u if words.get("subtitle") else 0
        self.clock_y = y + 10 * u
        self.clock_font = font(int(60 * u), "Medium")
        self.counter_font = font(int(30 * u), "Regular")
        self.bottom = y + 90 * u
        cy = style["credit_y"] if style["credit_y"] is not None else (0.80 if vertical else None)
        self.credit_y = cy * frame.height if cy is not None else frame.height - 54 * u


def spaced(d: ImageDraw.ImageDraw, xy, text: str, f, fill, tracking: float) -> None:
    """Text with extra letter spacing (for the small upper-case label)."""
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill)
        x += f.getlength(ch) + tracking


def shadowed(layer: Image.Image, u: float, strength: float) -> Image.Image:
    """The text layer over a soft dark shadow of its own letters, so words read over any map
    without darkening the frame around them."""
    if strength <= 0:
        return layer
    a = layer.getchannel("A").filter(ImageFilter.MaxFilter(3 if u < 1.5 else 5))
    a = a.filter(ImageFilter.GaussianBlur(7 * u)).point(lambda v: min(255, int(v * 2.2 * strength)))
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow.putalpha(a)
    return Image.alpha_composite(shadow, layer)


def chrome(words: dict, frame: Frame, style: dict) -> tuple[np.ndarray, np.ndarray]:
    """Title block and credit as color + alpha layers (HxWx3, HxWx1)."""
    L = Layout(frame, style, words)
    W, H, u = L.W, L.H, L.u
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    span = L.right - L.left
    if words.get("note"):
        label = words["note"].upper()
        f = fitted(label, L.label_font.size, "Medium", span - len(label) * 3 * u)
        spaced(d, (L.left, L.label_y), label, f, style["muted"], 3 * u)
    if words.get("title"):
        d.text((L.left - 4 * u, L.title_y), words["title"], font=fitted(words["title"], L.title_size, "Bold", span),
               fill=style["text"])
    if words.get("subtitle"):
        d.text((L.left, L.sub_y), words["subtitle"], font=fitted(words["subtitle"], int(38 * u), "Regular", span),
               fill=style["text"])
    credit = words.get("credit", "")
    if credit:
        lines, f = credit_lines(credit, int(22 * u), W - 80 * u)
        step = f.size * 1.35
        # Vertical reels grow the credit down from its line; at the foot of a frame it grows up.
        y = L.credit_y if H > W else L.credit_y - step * (len(lines) - 1)
        for i, line in enumerate(lines):
            d.text((W / 2, y + i * step), line, font=f, fill=style["muted"], anchor="ma")
    a = np.asarray(shadowed(layer, u, style["text_shadow"]), np.float32) / 255
    return a[..., :3], a[..., 3:]


class Stamp:
    """Text that changes during the reel (the clock, the vehicle count), each string rendered
    once and cached. Digits get a fixed advance so a ticking clock does not jitter."""

    def __init__(self, font: ImageFont.FreeTypeFont, color: str, u: float = 1.0, shadow: float = 0.0):
        self.font, self.color, self.cache = font, color, {}
        self.u, self.shadow, self.pad = u, shadow, int(24 * u)
        self.digit = max(font.getlength(c) for c in "0123456789")

    def width(self, text: str) -> float:
        return sum(self.digit if c.isdigit() else self.font.getlength(c) for c in text)

    def draw(self, img: np.ndarray, text: str, left: float, top: float) -> float:
        """Draws text with its left edge at `left`; returns the x where it ends."""
        if text not in self.cache:
            p = self.pad  # room for the shadow
            w, h = int(self.width(text)) + 4 + 2 * p, int(self.font.size * 1.3) + 2 * p
            layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            d, x = ImageDraw.Draw(layer), float(p)
            for c in text:
                adv = self.digit if c.isdigit() else self.font.getlength(c)
                d.text((x + adv / 2, p), c, font=self.font, fill=self.color, anchor="ma")
                x += adv
            self.cache[text] = np.asarray(shadowed(layer, self.u, self.shadow), np.float32) / 255
        c = self.cache[text]
        h, w = c.shape[:2]
        x0, y0 = int(left) - self.pad, int(top) - self.pad
        if x0 < 0 or y0 < 0:
            c, x0, y0 = c[max(0, -y0):, max(0, -x0):], max(0, x0), max(0, y0)
            h, w = c.shape[:2]
        h, w = min(h, img.shape[0] - y0), min(w, img.shape[1] - x0)
        region = img[y0:y0 + h, x0:x0 + w]
        a = c[:h, :w, 3:]
        region[:] = region * (1 - a) + c[:h, :w, :3] * a
        return left + self.width(text)


# ---------------------------------------------------------------- the loop

def hhmm(s: float) -> str:
    s = int(s) % 86400
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}"


def frames(baked: dict, frame: Frame, style: dict, meta: dict, base: np.ndarray, times: np.ndarray):
    """Yield (time, uint8 HxWx3) for each time."""
    veh = Vehicles(baked, frame, style)
    text_rgb, text_a = chrome(meta, frame, style)
    L = Layout(frame, style, meta)
    clock = Stamp(L.clock_font, style["text"], L.u, style["text_shadow"])
    counter = Stamp(L.counter_font, style["muted"], L.u, style["text_shadow"])
    dot, line = style["dot"], style["line_dot"]
    H, W = base.shape[:2]
    glow = lambda spec: spec.get("glow_gain", 0) > 0
    rim = rgb(style["outline"]) if style.get("outline") else None
    for c0 in range(0, len(times), 60):
        T = times[c0:c0 + 60]
        X, Y = veh.at(T)
        for f, t in enumerate(T):
            on = ~np.isnan(X[f])
            # Counted only where the viewer can see them.
            visible = on & (X[f] >= 0) & (X[f] < W) & (Y[f] >= 0) & (Y[f] < H)
            img = base
            if glow(dot) or glow(line):
                # A faint halo, its own layer under the rim and the dots. Overlapping halos
                # merge up to a ceiling (glow_max), so a dense center stays clear, not fogged.
                gbuf = np.zeros((4, H * W), np.float32)
                for sel, spec in ((on & ~veh.is_line, dot), (on & veh.is_line, line)):
                    if glow(spec):
                        splat(gbuf, H, W, X[f, sel], Y[f, sel], veh.col[sel], spec["glow_gain"],
                              sigma=spec["glow_sigma"] * L.u)
                cap = style["glow_max"]
                a = (cap * (1 - np.exp(-gbuf[3] / cap))).reshape(H, W, 1)
                gcol = (gbuf[:3] / np.maximum(gbuf[3], 1e-6)).reshape(3, H, W).transpose(1, 2, 0)
                img = img * (1 - a) + gcol * a
            if rim is not None:
                # A faint gray rim under every dot, so dots stand off their line and the map.
                obuf = np.zeros((4, H * W), np.float32)
                for sel, spec in ((on & ~veh.is_line, dot), (on & veh.is_line, line)):
                    n = int(sel.sum())
                    splat(obuf, H, W, X[f, sel], Y[f, sel], np.broadcast_to(rim, (n, 3)), spec["gain"],
                          radius=(spec["radius"] + style["outline_width"]) * L.u)
                a = ((1 - np.exp(-obuf[3])) * style["outline_alpha"]).reshape(H, W, 1)
                img = img * (1 - a) + rim * a
            buf = np.zeros((4, H * W), np.float32)
            for sel, spec in ((on & ~veh.is_line, dot), (on & veh.is_line, line)):
                splat(buf, H, W, X[f, sel], Y[f, sel], veh.col[sel], spec["gain"], radius=spec["radius"] * L.u)
            # Dots are painted over the map, not added as light: where thousands overlap, the
            # area takes their mean color instead of burning out to white.
            wsum = buf[3]
            cover = (1 - np.exp(-wsum)).reshape(H, W, 1)
            color = (buf[:3] / np.maximum(wsum, 1e-6)).reshape(3, H, W).transpose(1, 2, 0)
            img = img * (1 - cover) + color * cover
            img = img * (1 - text_a) + text_rgb * text_a
            img = np.clip(img, 0, 1)
            end = clock.draw(img, hhmm(t), L.left, L.clock_y)
            if style.get("counter"):
                n = int(visible.sum())
                text = style["counter"].format(n=n)
                counter.draw(img, text.replace("vehicles", "vehicle") if n == 1 else text,
                             end + 28 * L.u, L.clock_y + 26 * L.u)
            yield t, (img * 255 + 0.5).astype(np.uint8)


def ffmpeg_exe() -> str:
    import shutil
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg  # ships its own ffmpeg binary, so nothing needs installing
    return imageio_ffmpeg.get_ffmpeg_exe()


def encode(frame_iter, out: Path, width: int, height: int, fps: int, poster: Path, log=print) -> None:
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
           "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = 0
    for n, (_, img) in enumerate(frame_iter, 1):
        if n == 1:
            Image.fromarray(img).save(poster)
        proc.stdin.write(img.tobytes())
        if n % fps == 0:
            log(f"  {n} frames")
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit("ffmpeg failed")
