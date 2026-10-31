# transit-reels

Animated maps of every scheduled vehicle in a city, from its public GTFS timetable.
Python, three dependencies (numpy, Pillow, imageio-ffmpeg, which bundles ffmpeg), no GIS stack,
no API keys, no build step.

## If you were given only the GitHub link

The person may not know Git, Python or a terminal: do the setup yourself, without asking
them to.

1. Get the code into the current folder. With Git: `git clone https://github.com/aaronjbecker/transit-reels`.
   Without it (on a Mac, a missing `git` opens an installer dialog instead of running):
   `curl -L -o transit-reels.zip https://github.com/aaronjbecker/transit-reels/archive/refs/heads/main.zip && unzip -q transit-reels.zip && mv transit-reels-main transit-reels`.
2. Install [uv](https://docs.astral.sh/uv/) if `uv --version` fails. It fetches Python and the
   dependencies, with no admin rights: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   (macOS, Linux), or on Windows
   `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`.
   Then open a new shell, or use the full path it prints.
3. `cd transit-reels` and follow `skills/transit-reel/SKILL.md` from step 1. Run every command
   from inside `transit-reels/`.

Next time, opening the `transit-reels` folder itself loads the skill on its own (linked for
Claude Code in `.claude/skills` and for Codex in `.agents/skills`).

## Making a reel

Follow `skills/transit-reel/SKILL.md`. In short: `find` the feed, `inspect` it, write
`recipes/<city>.toml`, render a `still` and look at it, then `render` (and `web` for the
interactive page). Run everything with `uv run transit-reels ...`, or `pip install -e .` and
then `transit-reels ...`.

## Layout

| Path | What |
|---|---|
| `src/transit_reels/gtfs.py` | reading a feed with the csv module; calendars; choosing the day |
| `src/transit_reels/bake.py` | the timetable maths: which vehicles run, where each is at any second |
| `src/transit_reels/geo.py` | Web Mercator framing |
| `src/transit_reels/water.py` | sea, lakes and rivers from OpenStreetMap (Overpass) |
| `src/transit_reels/render.py` | the map plate, the dots, the words, the ffmpeg pipe |
| `src/transit_reels/web.py` | the interactive page's data, as one HTML file or (`--embed`) files for a site |
| `src/transit_reels/player.js` | the interactive player: plain JavaScript, no build step; MapLibre GL (from unpkg) draws the OpenFreeMap base map |
| `recipes/` | one TOML per city; `example.toml` documents every key |
| `tests/` | the timetable maths on a tiny made-up feed: `uv run python -m unittest discover -s tests` |

## Rules for changes

- Keep the dependency list as it is. Anything that needs a compiler, a GIS library, a
  browser or an account makes the tool harder to run for the people it is for.
- Generated files (feeds, bakes, videos) go in `work/` (or `$TRANSIT_REELS_WORK`) and are
  never committed.
- A change to the timetable maths comes with a test in `tests/test_bake.py`.
