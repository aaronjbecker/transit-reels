# Put the interactive map on a website

```bash
uv run transit-reels web recipes/lyon.toml --embed site/static/transit/lyon
```

writes `player.js` (plain JavaScript, no build step; it loads MapLibre GL from unpkg for the
base map), `lyon.json` and
`lyon-plate.jpg`, plus an `index.html` that shows how to mount it. Serve the folder (the
JSON compresses well, so let the server gzip it) and mount the player in any element that
has a size:

```html
<div id="map" style="height: 80vh"></div>
<script type="module">
  import { mount } from "/transit/lyon/player.js";
  mount(document.getElementById("map"), "/transit/lyon/lyon.json",
        { plate: "/transit/lyon/lyon-plate.jpg" });
</script>
```

In SvelteKit, put the folder under `static/` and mount it from a component, so it only runs
in the browser:

```svelte
<script>
  import { onMount } from "svelte";
  export let src = "/transit/lyon";   // the --embed folder, as served
  export let name = "lyon";
  let el;
  onMount(() => {
    let player;
    import(/* @vite-ignore */ `${src}/player.js`)
      .then(({ mount }) => mount(el, `${src}/${name}.json`, { plate: `${src}/${name}-plate.jpg` }))
      .then(p => (player = p));
    return () => player?.destroy();
  });
</script>

<div bind:this={el} style="height: 80vh; border-radius: 12px"></div>
```

`mount` returns `{ play, pause, seek, destroy }`; options are `plate`, `autoplay`, `t`
(seconds into the window), `basemap: "plate"` (the reel's still map only, no tiles) and
`cooperative`. When the player is shorter than the window it shares gestures with the page:
plain scrolling and vertical swipes scroll the page, and zooming takes Ctrl/⌘ + scroll or a
pinch. `cooperative: false` or `true` overrides that. The player takes its colors and typeface from CSS variables on
the element or a parent (`--tr-font`, `--tr-bg`, `--tr-panel`, `--tr-text`, `--tr-muted`,
`--tr-line`, `--tr-accent`), and lays itself out for its own width, so it works in a narrow
column as well as full screen.
