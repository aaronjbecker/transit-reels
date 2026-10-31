"""Read a GTFS feed (a .zip or an unzipped folder) with nothing but the csv module.

Only the tables a reel needs are read, and stop_times.txt is streamed so a big feed never
has to fit in memory as a table.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# GTFS route_type codes, including the common "extended" ranges (100s rail, 700s bus, ...).
ROUTE_TYPE_NAMES = {
    0: "tram", 1: "subway", 2: "rail", 3: "bus", 4: "ferry", 5: "cable tram",
    6: "aerial lift", 7: "funicular", 11: "trolleybus", 12: "monorail",
}


def base_route_type(code: int) -> int:
    """Fold an extended route_type (e.g. 109 suburban rail, 700 bus) onto the basic codes."""
    if code < 100:
        return code
    if 100 <= code < 200:
        return 2
    if 400 <= code < 500:
        return 1
    if 200 <= code < 300 or 700 <= code < 800:
        return 3
    if code == 800:
        return 11
    if 900 <= code < 1000:
        return 0
    if code == 1000 or code == 1200:
        return 4
    if code == 1300:
        return 6
    if code == 1400:
        return 7
    return 3


def seconds(hms: str) -> int | None:
    """'25:10:00' -> 90600. GTFS times run past 24:00 for trips that cross midnight."""
    hms = hms.strip()
    if not hms:
        return None
    h, m, s = hms.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


class Feed:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._zip = None
        if self.path.is_dir():
            self._members = {p.name: p for p in self.path.iterdir() if p.suffix == ".txt"}
        else:
            self._zip = zipfile.ZipFile(self.path)
            # Some feeds nest their files in a folder inside the zip.
            self._members = {Path(n).name: n for n in self._zip.namelist() if n.endswith(".txt")}

    def has(self, name: str) -> bool:
        return name in self._members

    def _open(self, name: str):
        member = self._members[name]
        raw = member.open("rb") if isinstance(member, Path) else self._zip.open(member)
        return io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")

    def rows(self, name: str):
        """Yield each row of a table as a dict. A missing table yields nothing."""
        if not self.has(name):
            return
        with self._open(name) as f:
            reader = csv.reader(f)
            header = [h.strip() for h in next(reader, [])]
            for row in reader:
                if row:
                    yield dict(zip(header, (v.strip() for v in row)))

    def columns(self, name: str, wanted: list[str]):
        """Yield tuples of just the wanted columns ('' where a column is absent). Fast path for
        stop_times.txt, which can run to tens of millions of rows."""
        if not self.has(name):
            return
        with self._open(name) as f:
            reader = csv.reader(f)
            header = [h.strip() for h in next(reader, [])]
            idx = [header.index(w) if w in header else None for w in wanted]
            n = len(header)
            for row in reader:
                if len(row) < n:
                    if not row:
                        continue
                    row = row + [""] * (n - len(row))
                yield tuple(row[i].strip() if i is not None else "" for i in idx)


def ymd(day: dt.date) -> str:
    return day.strftime("%Y%m%d")


class Calendar:
    """Which service_ids run on which date (calendar.txt plus calendar_dates.txt exceptions)."""

    def __init__(self, feed: Feed):
        self.weekly = [r for r in feed.rows("calendar.txt")]
        self.added: dict[str, set[str]] = defaultdict(set)
        self.removed: dict[str, set[str]] = defaultdict(set)
        for r in feed.rows("calendar_dates.txt"):
            (self.added if r.get("exception_type") == "1" else self.removed)[r["date"]].add(r["service_id"])

    def services_on(self, day: dt.date) -> set[str]:
        d, col = ymd(day), WEEKDAYS[day.weekday()]
        ids = {r["service_id"] for r in self.weekly
               if r.get(col) == "1" and r["start_date"] <= d <= r["end_date"]}
        return (ids | self.added.get(d, set())) - self.removed.get(d, set())

    def coverage(self) -> tuple[dt.date, dt.date] | None:
        dates = [r["start_date"] for r in self.weekly] + [r["end_date"] for r in self.weekly]
        dates += list(self.added)
        if not dates:
            return None
        parse = lambda s: dt.datetime.strptime(s, "%Y%m%d").date()
        return parse(min(dates)), parse(max(dates))


def trips_per_day(feed: Feed, cal: Calendar, start: dt.date, days: int) -> list[tuple[dt.date, int]]:
    per_service = Counter(r["service_id"] for r in feed.rows("trips.txt"))
    out = []
    for i in range(days):
        day = start + dt.timedelta(days=i)
        out.append((day, sum(per_service[s] for s in cal.services_on(day))))
    return out


def pick_weekday(feeds: Feed | list[Feed], today: dt.date | None = None) -> dt.date:
    """The next ordinary Tuesday to Thursday every feed covers, from tomorrow: of the Tue-Thu in
    the next three weeks, the earliest on which each feed runs within 3% of its busiest, so a
    holiday, election-day or strike timetable in any one feed is skipped."""
    feeds = feeds if isinstance(feeds, list) else [feeds]
    tomorrow = (today or dt.date.today()) + dt.timedelta(days=1)
    per_feed = []
    for feed in feeds:
        cal = Calendar(feed)
        counts = {d: n for d, n in trips_per_day(feed, cal, tomorrow, 21) if d.weekday() in (1, 2, 3) and n}
        if not counts:
            raise SystemExit(f"{feed.path.name} has no Tue-Thu service in the next three weeks (calendar covers "
                             f"{cal.coverage()}). Pass an explicit date the calendar covers.")
        per_feed.append(counts)
    days = sorted(set.intersection(*(set(c) for c in per_feed)))
    if not days:
        raise SystemExit("The feeds share no Tue-Thu in the next three weeks. Pass an explicit date.")
    # First day on which every feed is within 3% of its own busiest: ordinary service everywhere.
    ok = [d for d in days if all(c[d] >= 0.97 * max(c[x] for x in days) for c in per_feed)]
    return ok[0] if ok else max(days, key=lambda d: sum(c[d] / max(c.values()) for c in per_feed))
