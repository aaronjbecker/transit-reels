"""Render a few frames of the made-up feed to an MP4, end to end (no network: water off)."""

import datetime as dt
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

from transit_reels import bake as bake_mod
from transit_reels import render
from transit_reels.geo import Frame
from transit_reels.gtfs import Feed
from transit_reels.recipe import DEFAULTS

from test_bake import TABLES


class RenderTest(unittest.TestCase):
    def test_frames_to_mp4(self):
        with tempfile.TemporaryDirectory() as tmp:
            feed = Path(tmp) / "feed.zip"
            with zipfile.ZipFile(feed, "w") as z:
                for name, text in TABLES.items():
                    z.writestr(name, text)
            baked = bake_mod.bake(Feed(feed), dt.date(2026, 11, 4), 8 * 3600, 8 * 3600 + 600, log=lambda *_: None)
            npz = Path(tmp) / "bake.npz"
            bake_mod.save(baked, npz)
            baked = bake_mod.load(npz)
            frame = Frame((0.01, 0.0), 3.0, 216, 384)
            style = DEFAULTS["style"]
            base = render.plate(baked, frame, style, None, log=lambda *_: None)
            words = {"title": "Test", "subtitle": "one line", "note": "note", "credit": "credit"}
            times = 8 * 3600 + np.arange(5) * 60.0
            out = Path(tmp) / "t.mp4"
            render.encode(render.frames(baked, frame, style, words, base, times), out, 216, 384, 5,
                          out.with_suffix(".png"), log=lambda *_: None)
            self.assertGreater(out.stat().st_size, 1000)
            self.assertTrue(out.with_suffix(".png").exists())


if __name__ == "__main__":
    unittest.main()


class CreditTest(unittest.TestCase):
    def test_long_credit_wraps_instead_of_shrinking_away(self):
        credit = ("Route and arrival data used in this product or service is provided by permission of "
                  "TransLink. TransLink assumes no responsibility for the accuracy or currency of the Data "
                  "used in this product or service · Map © OpenStreetMap contributors · mapped.earth/transit-reels")
        lines, f = render.credit_lines(credit, 22, 1000)
        self.assertGreater(len(lines), 1)
        self.assertGreaterEqual(f.size, 17)
        self.assertTrue(all(f.getlength(ln) <= 1000 for ln in lines))
        self.assertEqual(" ".join(lines).replace(" · ", " ").split(), credit.replace(" · ", " ").split())


class WaterNullPointsTest(unittest.TestCase):
    def test_mask_skips_null_points(self):
        from transit_reels.water import mask
        square = [{"lon": 2, "lat": 2}, None, {"lon": 8, "lat": 2}, {"lon": 8, "lat": 8}, {"lon": 2, "lat": 8}, {"lon": 2, "lat": 2}]
        m = mask({"elements": [{"type": "way", "tags": {"natural": "water"}, "geometry": square}]},
                 lambda x, y: (x, y), 10, 10)
        self.assertTrue(m[5, 5])


ALL_TYPES = list(range(13))  # so the made-up feed's every route counts as a colored line


class GlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        feed = Path(self.tmp.name) / "feed.zip"
        with zipfile.ZipFile(feed, "w") as z:
            for name, text in TABLES.items():
                z.writestr(name, text)
        baked = bake_mod.bake(Feed(feed), dt.date(2026, 11, 4), 8 * 3600, 8 * 3600 + 600, log=lambda *_: None)
        npz = Path(self.tmp.name) / "bake.npz"
        bake_mod.save(baked, npz)
        self.baked = bake_mod.load(npz)
        self.frame = Frame((0.01, 42.0), 3.0, 216, 384)

    def tearDown(self):
        self.tmp.cleanup()

    def test_colored_vehicle_is_its_line_color_not_white(self):
        style = {**DEFAULTS["style"], "line_types": ALL_TYPES}
        veh = render.Vehicles(self.baked, self.frame, style)
        routes = self.baked["routes"]
        for j, i in enumerate(self.baked["trip_route"].tolist()):
            line = render.route_color(routes[i], style)
            if routes[i]["type"] in style["line_types"]:
                self.assertTrue(veh.colored[j])
                self.assertLess(np.abs(veh.col[j] - line).max(), 0.21)

    def test_line_glow_lightens_beside_the_line(self):
        style = {**DEFAULTS["style"], "line_types": ALL_TYPES}
        lit = render.plate(self.baked, self.frame, style, None, log=lambda *_: None)
        style["line_glow_gain"] = 0
        flat = render.plate(self.baked, self.frame, style, None, log=lambda *_: None)
        self.assertGreater(lit.sum(), flat.sum())
        self.assertLessEqual(lit.max(), 1.0)


class GridTest(unittest.TestCase):
    def test_every_count_fits_in_regular_cells(self):
        from transit_reels.grid import GridLayout
        words = {"title": "T", "subtitle": "s", "note": "n", "credit": "a credit"}
        for size in ((1080, 1920), (1920, 1080), (1080, 1080)):
            page = Frame((0.0, 0.0), 1.0, *size)
            for n in range(2, 10):
                L = GridLayout(page, DEFAULTS["style"], words, n)
                self.assertEqual(len(L.rects), n)
                cw, ch = L.cell_size
                self.assertEqual((cw % 2, ch % 2), (0, 0))
                self.assertGreater(min(cw, ch), 150, (size, n))
                for i, (x, y) in enumerate(L.rects):
                    self.assertTrue(0 <= x and x + cw <= size[0] and 0 <= y and y + ch <= size[1], (size, n, x, y))
                    for u, v in L.rects[i + 1:]:
                        self.assertTrue(u >= x + cw or x >= u + cw or v >= y + ch or y >= v + ch, (size, n))

    def test_nine_is_three_by_three(self):
        from transit_reels.grid import shape
        self.assertEqual(shape(9, 1056, 1040, 6), (3, 3))
        self.assertEqual(shape(4, 1056, 1040, 6), (2, 2))
        self.assertEqual(shape(6, 1056, 1056, 6, columns=2), (2, 3))

    def test_ten_cities_are_refused(self):
        from transit_reels import recipe
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "g.toml"
            f.write_text('title = "x"\n[grid]\ncities = [' + ",".join(f'"c{i}"' for i in range(10)) + "]\n")
            with self.assertRaises(SystemExit):
                recipe.cities(recipe.load(f))

    def test_grid_end_to_end(self):
        from transit_reels import cli
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            feed = tmp / "feed.zip"
            with zipfile.ZipFile(feed, "w") as z:
                for name, text in TABLES.items():
                    z.writestr(name, text)
            for c in ("a", "b", "c"):
                (tmp / f"{c}.toml").write_text(
                    f'title = "{c.upper()}"\n[feed]\npath = "feed.zip"\nattribution = "Timetable: test"\n'
                    '[map]\nwater = false\ncenter = [0.01, 0.0]\nwidth_km = 3\n')
            (tmp / "g.toml").write_text('title = "Three"\n[grid]\ncities = ["a", "b", "c"]\nwidth_km = 3\n'
                                        '[time]\ndate = "2026-11-04"\nstart = "08:00"\nminutes = 10\n'
                                        '[video]\nwidth = 216\nheight = 384\nfps = 5\nseconds = 1\n')
            import os
            old = os.environ.get("TRANSIT_REELS_WORK")
            os.environ["TRANSIT_REELS_WORK"] = str(tmp / "work")
            try:
                cli.main(["render", str(tmp / "g.toml"), "--out", str(tmp / "g.mp4")])
                cli.main(["stats", str(tmp / "g.toml")])
            finally:
                os.environ.pop("TRANSIT_REELS_WORK") if old is None else os.environ.update(TRANSIT_REELS_WORK=old)
            self.assertGreater((tmp / "g.mp4").stat().st_size, 1000)
            self.assertTrue((tmp / "work" / "a" / "bake-grid-0800-10.npz").exists())
            self.assertFalse((tmp / "work" / "a" / "bake.npz").exists())  # the city's own is left alone
