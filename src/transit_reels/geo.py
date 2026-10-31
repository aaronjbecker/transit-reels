"""The frame's projection: Web Mercator, fitted to a portrait (or any) frame."""

from __future__ import annotations

import math

import numpy as np

R = 6_378_137.0


def mercator(lon, lat):
    lon, lat = np.asarray(lon, float), np.clip(np.asarray(lat, float), -85, 85)
    return R * np.radians(lon), R * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


class Frame:
    """Maps lon/lat to pixels for a static camera centered on `center`, `width_km` across."""

    def __init__(self, center: tuple[float, float], width_km: float, width: int, height: int):
        self.center, self.width_km, self.width, self.height = center, width_km, width, height
        self.cx, self.cy = mercator(*center)
        # Mercator stretches distance by 1/cos(lat); scale so width_km is true ground distance.
        self.m_per_px = width_km * 1000 / width / math.cos(math.radians(center[1]))

    def px(self, lon, lat):
        x, y = mercator(lon, lat)
        return (self.width / 2 + (x - self.cx) / self.m_per_px,
                self.height / 2 - (y - self.cy) / self.m_per_px)

    def bbox(self, pad: float = 0.05) -> tuple[float, float, float, float]:
        """(west, south, east, north) of the frame, padded by a fraction."""
        hw, hh = self.width / 2 * (1 + pad) * self.m_per_px, self.height / 2 * (1 + pad) * self.m_per_px
        lon = lambda x: math.degrees(x / R)
        lat = lambda y: math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2)
        return lon(self.cx - hw), lat(self.cy - hh), lon(self.cx + hw), lat(self.cy + hh)


def auto_frame(lonlat: np.ndarray, width: int, height: int, fill: float = 1.0,
               focus_y: float = 0.57) -> tuple[tuple[float, float], float]:
    """Center and width_km that fit where the vehicles are (5th-95th percentile of their
    positions), so one long outlying commuter line does not shrink the city. The busy part sits
    a little below the middle (focus_y), under the title block."""
    x, y = mercator(lonlat[:, 0], lonlat[:, 1])
    x0, x1 = np.percentile(x, [5, 95])
    y0, y1 = np.percentile(y, [5, 95])
    span_x = max(x1 - x0, (y1 - y0) * width / height / 0.7) / fill
    m_per_px = span_x / width
    cx = (x0 + x1) / 2
    cy = (y0 + y1) / 2 + (focus_y - 0.5) * height * m_per_px
    lat_c = math.degrees(2 * math.atan(math.exp(cy / R)) - math.pi / 2)
    center = (math.degrees(cx / R), lat_c)
    return center, span_x * math.cos(math.radians(lat_c)) / 1000
