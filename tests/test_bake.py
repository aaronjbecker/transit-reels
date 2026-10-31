"""The timetable maths on a tiny made-up feed. Run: uv run python -m unittest"""

import datetime as dt
import tempfile
import unittest
import zipfile
from pathlib import Path

import numpy as np

from transit_reels.bake import bake
from transit_reels.gtfs import Calendar, Feed, pick_weekday

# One straight east-west line at 42 N (0,0 is treated as a missing coordinate), three stops 0.01 degrees apart, a shape with a vertex between
# every pair of stops. Stop B has no times (not a timepoint).
TABLES = {
    "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\nA,Test,http://x,UTC\n",
    "routes.txt": "route_id,agency_id,route_short_name,route_type,route_color\nR,A,1,3,\nT,A,T,1,FF0000\n",
    "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                    "WK,1,1,1,1,1,0,0,20260101,20261231\n",
    "calendar_dates.txt": "service_id,date,exception_type\nWK,20261103,2\n",
    "trips.txt": "route_id,service_id,trip_id,shape_id\nR,WK,day,S\nR,WK,late,S\nT,WK,freq,S\n",
    "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\nA,A,42,0\nB,B,42,0.01\nC,C,42,0.02\n",
    "shapes.txt": "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
                  "S,42,0,1\nS,42,0.005,2\nS,42,0.01,3\nS,42,0.015,4\nS,42,0.02,5\n",
    "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                      "day,08:00:00,08:00:00,A,1\nday,,,B,2\nday,08:10:00,08:10:00,C,3\n"
                      "late,24:00:00,24:00:00,A,1\nlate,,,B,2\nlate,24:20:00,24:20:00,C,3\n"
                      "freq,00:00:00,00:00:00,A,1\nfreq,00:02:00,00:03:00,B,2\nfreq,00:05:00,00:05:00,C,3\n",
    "frequencies.txt": "trip_id,start_time,end_time,headway_secs\nfreq,08:00:00,09:00:00,600\n",
}


class BakeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = Path(cls.tmp.name) / "feed.zip"
        with zipfile.ZipFile(cls.path, "w") as z:
            for name, text in TABLES.items():
                z.writestr(name, text)
        cls.feed = Feed(cls.path)

    def position(self, baked, route, t):
        out = []
        for tr in baked["trips"]:
            if tr["route"] == route and tr["t"][0] <= t <= tr["t"][-1]:
                out.append(np.interp(t, tr["t"], tr["lonlat"][:, 0]))
        return sorted(out)

    def test_schedule_kept_for_the_interactive_page(self):
        from transit_reels import bake as bake_mod
        b = bake(self.feed, dt.date(2026, 11, 4), 8 * 3600, 8 * 3600 + 600, log=lambda *_: None)
        with tempfile.TemporaryDirectory() as d:
            bake_mod.save(b, Path(d) / "bake.npz")
            got = bake_mod.load(Path(d) / "bake.npz")
        j = next(i for i, r in enumerate(got["trip_route"]) if got["routes"][r]["id"] == "R")
        o = got["sched_off"]
        names = [got["stops"][s][1] for s in got["sched_stop"][o[j]:o[j + 1]]]
        self.assertEqual(names, ["A", "B", "C"])
        # B has no time in the feed: it is filled in, and flagged as estimated.
        self.assertEqual(got["sched_timed"][o[j]:o[j + 1]].tolist(), [True, False, True])
        self.assertEqual(got["sched_time"][o[j], 0], 8 * 3600)
        self.assertEqual(got["agencies"], {"A": "Test"})

    def test_calendar_exception_removes_a_day(self):
        cal = Calendar(self.feed)
        self.assertEqual(cal.services_on(dt.date(2026, 11, 4)), {"WK"})
        self.assertEqual(cal.services_on(dt.date(2026, 11, 3)), set())  # removed by calendar_dates

    def test_untimed_stop_is_interpolated_by_distance(self):
        b = bake(self.feed, dt.date(2026, 11, 4), 8 * 3600, 8 * 3600 + 600, log=lambda *_: None)
        # Halfway in time = halfway along the line, at stop B.
        self.assertAlmostEqual(self.position(b, "R", 8 * 3600 + 300)[0], 0.01, places=6)
        self.assertAlmostEqual(self.position(b, "R", 8 * 3600 + 150)[0], 0.005, places=6)

    def test_trip_past_midnight_runs_the_next_morning(self):
        # 'late' is scheduled 24:00-24:20 on Wednesday, so it is on the road 00:00-00:20 Thursday.
        b = bake(self.feed, dt.date(2026, 11, 5), 0, 1200, log=lambda *_: None)
        self.assertAlmostEqual(self.position(b, "R", 600)[0], 0.01, places=6)

    def test_frequencies_expand_with_dwell(self):
        b = bake(self.feed, dt.date(2026, 11, 4), 8 * 3600, 9 * 3600, log=lambda *_: None)
        starts = sorted(tr["t"][0] for tr in b["trips"] if tr["route"] == "T")
        self.assertEqual(len(starts), 6)  # 08:00, 08:10 ... 08:50
        # The train waits at B from +2:00 to +3:00.
        (x,) = self.position(b, "T", 8 * 3600 + 150)
        self.assertAlmostEqual(x, 0.01, places=6)

    def test_pick_weekday_skips_the_removed_day(self):
        self.assertEqual(pick_weekday(self.feed, dt.date(2026, 11, 2)), dt.date(2026, 11, 4))


if __name__ == "__main__":
    unittest.main()


class BadCoordinatesTest(unittest.TestCase):
    def test_impossible_and_far_stops_are_dropped(self):
        from transit_reels.bake import _drop_bad_stops
        stops = {f"s{i}": (18.0 + i * 0.01, 59.3 + i * 0.01) for i in range(50)}
        stops.update(nullisland=(0.0, 0.0), typo=(13.1, 5.957), huge=(18.0, 56030846.0))
        kept, near = _drop_bad_stops(stops, log=lambda *_: None)
        self.assertEqual(set(kept), {f"s{i}" for i in range(50)})
        self.assertTrue(near(18.2, 59.5))
        self.assertFalse(near(13.1, 5.957))


class PickDayAcrossFeedsTest(unittest.TestCase):
    def test_a_short_day_in_any_feed_is_skipped(self):
        from unittest import mock
        from transit_reels import gtfs
        a, b = mock.Mock(), mock.Mock()
        tue, wed = dt.date(2026, 11, 3), dt.date(2026, 11, 4)
        counts = {id(a): [(tue, 1000), (wed, 1000)], id(b): [(tue, 950), (wed, 1000)]}  # b: election day
        with mock.patch.object(gtfs, "Calendar"), \
             mock.patch.object(gtfs, "trips_per_day", side_effect=lambda f, cal, d, n: counts[id(f)]):
            self.assertEqual(gtfs.pick_weekday([a, b], dt.date(2026, 11, 2)), wed)
            self.assertEqual(gtfs.pick_weekday([a], dt.date(2026, 11, 2)), tue)


class MissingShapesTest(unittest.TestCase):
    """A trip with no route shape would be drawn on a straight line that is not its path."""

    def feed(self, tables):
        d = tempfile.mkdtemp()
        path = Path(d) / "feed.zip"
        with zipfile.ZipFile(path, "w") as z:
            for name, text in tables.items():
                z.writestr(name, text)
        return Feed(path)

    def tables(self):
        t = dict(TABLES)
        t["routes.txt"] += "B2,A,99,3,\nF,A,F1,4,\n"
        t["trips.txt"] += "B2,WK,noshape,\nF,WK,ferry,\n"
        t["stop_times.txt"] += ("noshape,08:00:00,08:00:00,A,1\nnoshape,08:10:00,08:10:00,C,2\n"
                                "ferry,08:00:00,08:00:00,A,1\nferry,08:10:00,08:10:00,C,2\n")
        return t

    def routes_baked(self, feed, **kw):
        b = bake(feed, dt.date(2026, 11, 4), 8 * 3600, 8 * 3600 + 600, log=lambda *_: None, **kw)
        return {tr["route"] for tr in b["trips"]}

    def test_shapeless_bus_left_out_ferry_kept(self):
        got = self.routes_baked(self.feed(self.tables()))
        self.assertNotIn("B2", got)
        self.assertIn("F", got)
        self.assertIn("R", got)

    def test_straight_true_keeps_it(self):
        self.assertIn("B2", self.routes_baked(self.feed(self.tables()), straight=True))

    def test_feed_without_any_shapes_is_refused_unless_straight(self):
        t = self.tables()
        del t["shapes.txt"]
        t["trips.txt"] = t["trips.txt"].replace(",S\n", ",\n")
        with self.assertRaises(SystemExit) as err:
            self.routes_baked(self.feed(t))
        self.assertIn("straight = true", str(err.exception))
        self.assertIn("B2", self.routes_baked(self.feed(t), straight=True))


class SimplifyTest(unittest.TestCase):
    def test_keeps_corners_and_schedule_drops_straight_points(self):
        from transit_reels.web import simplify
        x = np.array([0, 1, 2, 3, 3, 3], float)
        y = np.array([0, 0, 0, 0, 1, 2], float)
        self.assertEqual(simplify(x, y).tolist(), [0, 3, 5])
        # Same straight line, but the vehicle waits at x=1 (a stop): that point stays.
        t = np.array([0, 10, 40, 50, 60, 70], float)
        self.assertIn(1, simplify(x, y, t).tolist())
