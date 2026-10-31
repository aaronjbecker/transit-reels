---
name: transit-reel
description: Make an animated map of every scheduled vehicle in a city (bus, metro, tram, rail, ferry) from its public GTFS timetable, as a vertical video and an interactive web page. Use when asked for a transit map animation, a "every bus in <city>" reel, a GTFS visualization, or to add a city recipe to this repo.
---

# Make a transit reel

The output is a static map of a city with a dot for every vehicle the timetable puts on the
road, moving for a short window (by default 20 minutes of the morning rush squeezed into
10 seconds), with a title, a clock and a credit line. Everything runs from one recipe file.

Work in this order. Each step names what to look at before going on.

## 1. Find the feed

```bash
uv run transit-reels find <city or agency words>
```

This searches the Mobility Database catalog (about 4,500 open GTFS feeds) by agency name and
place. For each hit it prints the agency's download URL, a mirror kept by the Mobility
Database, and the catalog's license link. Search the local-language name too ("lisboa", not
only "lisbon"; "wien", "münchen"), and the regional authority's name: the consolidated feed
is often listed under it.

- **Prefer one consolidated regional feed** (Seattle's "Puget Sound Consolidated", the Paris
  region's IDFM) over the agencies' separate feeds. Where the agencies only publish
  separately, take the ones that make the picture (the metro, the main bus operator, the
  suburban rail, the ferries) and list each as a `[[feeds]]` entry (step 3).
- **Read the license before rendering; it is a gate, not a note.** Open the license page with
  your web tool and read it. Most allow reuse with attribution; some (TransLink, for example)
  require an exact credit sentence. Put the required words in `attribution` and a one-line
  summary with the URL in `license`. The catalog's license link is sometimes missing, or
  points at the agency's software license rather than the data's: then search for the
  agency's developer or open-data terms (for example "TriMet developer terms of use") and
  read those. If nothing states the terms, tell the person and suggest a nearby city or
  another feed whose terms are clear: there are thousands of open feeds, so an unclear one is
  rarely worth publishing. If you cannot open web pages, say so plainly in your report and
  name the page the person should read before posting.
- A hit marked `NEEDS A KEY` wants an API key from the provider; see "Feeds that need a key"
  below. Its mirror works without one.

## 2. Inspect it

```bash
uv run transit-reels inspect <the feed's url>      # or a local .zip or unzipped folder
```

`inspect` downloads the url into `work/feeds/` (a recipe with the same url reuses that copy).
Check:

| Line | What it tells you |
|---|---|
| `routes:` | which modes exist (bus 3, subway 1, rail 2, tram 0, ferry 4 ...). Name them in the subtitle. |
| `calendar:` | the widest date range the calendar mentions. Feeds often declare years ahead; the trips-per-day table is the real check. A feed whose service has lapsed cannot show "today"; pick a date it covers and say that date on screen. |
| `shapes: NO` | the render stops: vehicles could only move in straight lines between stops, which cuts across blocks, hills and water. Look for another feed of the network with shapes (the agency's own often has them). Only if there is none, and the user agrees, add `straight = true` to that feed. |
| `left out N runs ... no route shape` | those trips have no shape in an otherwise shaped feed, so they are not drawn: a missing vehicle is better than a wrong path. Mention it if N is a large share; `straight = true` draws them anyway. |
| `frequencies.txt` | some service is published as "every N minutes", not as individual runs; the dots are then the vehicles needed to run that headway. |
| trips per day | a weekday with a short bar is a holiday or a disrupted timetable. `next-weekday` skips those automatically. |

## 3. Write the recipe

Copy `recipes/example.toml` (every key is explained there) to `recipes/<city>.toml`. The
minimum is a title, a feed URL and an attribution:

```toml
title = "Seattle"
subtitle = "Link, ferries, Sounder, streetcar and bus"

[feed]
url = "https://gtfs.sound.obaweb.org/prod/gtfs_puget_sound_consolidated.zip"
mirror = "https://files.mobilitydatabase.org/mdb-1080/latest.zip"
attribution = "Timetable: Puget Sound consolidated GTFS (OneBusAway)"
```

Several agencies: replace `[feed]` with one `[[feeds]]` table per feed. Each takes the same
keys as `[feed]` (`url`, `mirror`, `path`, `attribution`, `license`, `route_types`); their
attributions are joined into one credit line. The day is chosen from the first feed, so put
the biggest operator first, and run `inspect` on each to make sure all cover that day.

`license` is a note for you and anyone reading the recipe; it is not drawn. `attribution` is.

The window is 08:00-08:20, shown in 10 seconds, on the next ordinary Tuesday to Thursday
the feed covers (see "Choosing the window").
Times are the agency's local time, as in the timetable itself. "Next ordinary" means: of the
Tuesdays to Thursdays in the three weeks from tomorrow, the earliest whose trip count is
within 3% of the busiest, so a holiday or strike timetable is skipped.

## 4. Render a still and look at it

```bash
uv run transit-reels still recipes/<city>.toml      # work/<slug>/<slug>-still.png
```

Open the PNG and look at it (an agent that can read images must actually read it).
`--at HH:MM` renders another moment of the window (saved as `<slug>-still-HHMM.png`, so it does not replace the first). A line starting `WARNING:` at the end of any command (no water drawn, say) means the picture is not what the recipe asked for: read it before going on. Check:

- **Framing.** The first run prints `auto framing: center = [...], width_km = ...`. Auto
  framing fits where the vehicles are, which in a region with a far-flung commuter network
  is too wide. Set `[map] center = [lon, lat]` and `width_km` (true ground distance across
  the frame at its center) to frame the city, re-run the still. 15-45 km suits most cities
  in a 9:16 frame: about 17 for Boston, 26 for Paris, 42 for the Seattle region.
- **Water.** Sea, lakes and rivers come from OpenStreetMap. Each region between coastlines is
  voted sea or land, so a wrong fill (open sea drawn gray, or a peninsula drawn black) means
  a coastline that leaves the frame only as a tiny sliver. Move the center by about 5% of
  `width_km` so the coastline crosses the frame edge cleanly, or widen the frame, and render
  the still again. If Overpass is down the map is drawn without water and the log says so;
  re-run later or set `water = false`.
  Frames wider than 150 km (regions, whole countries) take land and lakes from Natural
  Earth instead (public domain, fetched once), since Overpass cannot answer at that size;
  the credit line then says "Map: Natural Earth".
- **Text.** Title, subtitle and note shrink to fit; keep the subtitle short anyway.
- **Colors.** Rail, tram and ferry use the feed's `route_color`. A feed with no colors gets
  a fallback per mode. Override in `[style]` only if a line is unreadable. For a whole
  country, set `color_by = "mode"`: one color per mode reads better than hundreds of
  operators' brand colors.

## 5. Render the video

```bash
uv run transit-reels render recipes/<city>.toml     # work/<slug>/<slug>.mp4 + .png
```

A 10-second 1080x1920 reel takes well under a minute on a laptop once the feed is baked.

Then the 16:9 version (X, LinkedIn, YouTube) and the interactive page (step 6). Make all
three unless the person asked for only one: they are what the README and the site promise.

```bash
uv run transit-reels render recipes/<city>.toml --format horizontal   # <slug>-horizontal.mp4
```

It keeps the center and the ground area of the vertical frame. If the city needs a different
crop sideways, give `[map.horizontal] center` and `width_km`, and check it with
`still --format horizontal`.
Look at the first frame (the PNG), and at the middle and the end with
`still --at HH:MM`. The on-screen count is the vehicles inside the frame at that moment; it
should be plausible for what is shown (central Boston at 8 am: about 600).

## 6. The interactive page

```bash
uv run transit-reels web recipes/<city>.toml        # work/<slug>/<slug>.html
```

One file: open it in any browser. It opens on the reel's framing (vertical on a phone,
horizontal on a desktop) over a full-screen OpenFreeMap base map, and falls back to the
reel's still map offline. Viewers scrub the time, zoom, read the legend and switch modes,
and tap a vehicle (line, destination, its scheduled stops), a line (runs by destination,
where each vehicle is) or a stop (next departures). It can be hosted as-is (GitHub Pages, any
static host). For a website, `--embed <folder>` writes the player, data and map as separate
files; the README's "Put it on a website" shows plain HTML and SvelteKit.

Before handing it over, open it and tap a vehicle and a stop: check the panel names a real
line, destination and stop, and that the times are in the window.

## 7. Hand it over

The person may never have used a terminal. Say in plain words where the files are (the
video, the horizontal video, the cover image, the interactive page) with their full paths,
offer to open the folder (`open work/<slug>` on a Mac, `explorer work\<slug>` on Windows,
`xdg-open` on Linux), give the caption numbers from `stats`, and repeat the credit line they
must keep when posting.

## Choosing the window

The default, 08:00-08:20 in 10 s, is the network at its busiest, at two minutes of timetable
a second: slow enough to follow one train. Another stretch: set `start` and `minutes` under
`[time]` (and `seconds` under `[video]`), e.g. the evening peak, `start = "17:15"`; last
trains, `start = "00:30"` (trips past 24:00 carry over). Keep it near two minutes a second:
past four the tool warns, because the dots blur and no vehicle can be followed. The person
decides; recommend against a whole day in one reel, but make it if they ask.

## Numbers for the caption

```bash
uv run transit-reels stats recipes/<city>.toml              # every 5 min
```

Vehicle runs in the window, distinct paths, runs by mode, and how many vehicles are moving
at each step across the whole feed, with the peak. These are the numbers a caption can
quote ("7,760 at 07:40"). The on-screen counter differs: it counts only what is in frame.

## Feeds that need a key

Some agencies (Trafiklab in Sweden, WMATA, TMB in Barcelona, 511 in the Bay Area) hand out
their timetable only with a free API key. `find` prints, for such a feed, the sign-up page and
the exact lines for the recipe:

```toml
[feed]
url = "https://opendata.samtrafiken.se/gtfs-sweden/sweden.zip"
mirror = "https://files.mobilitydatabase.org/mdb-2939/latest.zip"
key = "trafiklab"            # the NAME of a stored key, never the key itself
key_param = "key"            # or key_header = "..." if the agency wants a header
signup = "https://developer.trafiklab.se/register"
```

With no key stored, the tool uses the mirror and says where to get a key; with no mirror, it
stops and prints the sign-up steps. To store a key the person runs, in their own terminal:

```bash
uv run transit-reels key set trafiklab
```

It asks for the key without showing it and keeps it in `~/.config/transit-reels/keys.toml`,
readable only by them (or `TRANSIT_REELS_KEY_TRAFIKLAB` in the environment).

**If you are an agent:** never ask for a key in the chat, never accept one pasted there, and
never write one into a recipe, a file in the repo, a command line or a log. Tell the person
which page to sign up on and to run `key set` themselves in a terminal, then carry on with
the mirror meanwhile. `transit-reels key list` shows which keys are set, never their values.

## Whole countries

A national feed works the same way: `color_by = "mode"`, and a frame wide
enough for the country (`width_km` of several hundred). Expect a few minutes and a few GB
of memory for the bake of a feed with 100,000+ runs a day; it is cached afterwards. Use
`line_width = 2.2` or so at this scale. Prefer the agency's own feed over the Mobility
Database mirror here: Sweden's mirror copy lacked most regional rail and its long-distance
shapes, while Trafiklab's own feed (free key) has the full network.

## Pitfalls

- **It is the timetable, not live positions.** Say "scheduled" in the note or caption. The
  default note does ("every scheduled vehicle · <date>").
- **The date on screen must be a date the calendar covers.** `next-weekday` guarantees it.
- **Huge feeds**: a whole country (Sweden: 800 MB zipped) takes about two minutes and ~6 GB
  of memory to bake; a big city (all of New York's nine MTA feeds), well under a minute. The
  bake is cached in `work/<city>/bake.npz` and reused while the recipe's feed, date
  and window are unchanged.
- **A download refused by the agency's server** (some block scripts): the recipe's `mirror`
  is tried next.
- **Routes in the wrong mode** (a feed calling its metro a "rail" line): restrict or recolour
  with `route_types` in `[feed]` and `line_types` in `[style]`.
- **A feed that labels a mode wrongly** (Barcelona's TRAM Baix calls its T2 tram "rail", so
  it draws as a thick line): fix it in that `[[feeds]]` entry with `retype = {"T2" = 0}`
  (by route short name or route id; `"*"` for the whole feed). Compare the still with the
  agency's own network map: thick lines should be metro, rail and ferry only.
