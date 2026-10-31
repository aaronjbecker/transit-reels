"""Draw order and the reel's speed limit."""
import tempfile
import unittest
from pathlib import Path

from transit_reels import recipe
from transit_reels.render import draw_rank

STYLE = recipe.DEFAULTS["style"]


class DrawOrderTest(unittest.TestCase):
    def test_metro_is_on_top(self):
        # subway over tram, monorail, rail, cable car, ferry; buses (the network) at the bottom
        ranks = [draw_rank(t, STYLE) for t in (3, 4, 6, 2, 0, 12, 1)]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(len(set(ranks)), len(ranks))


class SpeedLimitTest(unittest.TestCase):
    def load(self, time: str) -> dict:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.toml"
            p.write_text(f'[feed]\nurl = "x"\n[time]\n{time}\n')
            return recipe.load(p)

    def test_peak_by_default(self):
        r = self.load("")
        self.assertEqual((r["time"]["start"], r["time"]["minutes"], r["video"]["seconds"]), ("08:00", 20, 10))

    def test_too_fast_warns(self):
        recipe.WARNINGS.clear()
        r = self.load('start = "05:00"\nminutes = 900')
        self.assertEqual(r["time"]["minutes"], 900)
        self.assertEqual(len(recipe.WARNINGS), 1)
        recipe.WARNINGS.clear()
        self.load("")
        self.assertEqual(recipe.WARNINGS, [])


if __name__ == "__main__":
    unittest.main()
