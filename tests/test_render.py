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
