# CLAUDE.md — ORYC Aeolian Flotilla site

## Current state

Complete and working end to end. The pipeline fetches five models, derives
passage and berth guidance, and the page renders it. Not yet deployed: Pages
needs enabling and `ANTHROPIC_API_KEY` needs adding as a repo secret.

**The one open task that matters:** every mooring in `data/waypoints.json` is
`"verified": false`. See "Safety-critical data" below.

## Project summary

A static GitHub Pages site for a yacht-club flotilla in the Aeolian Islands,
3–10 October 2026. Shows the itinerary and a multi-model marine weather
briefing that rebuilds on a cron — daily before the trip, twice daily during
it. No build step: a GitHub Action runs Python, commits `data/weather.json`,
and Pages serves it. The browser makes no API calls.

See `README.md` for the full architecture and setup checklist.

## Locked-in decisions (do not relitigate without the owner)

* **No build step, no framework.** Plain HTML/CSS/JS plus two pinned CDN
  libraries (Leaflet, Chart.js). Deploy is `git push`. Chosen for reliability
  three weeks before departure over matching the Astro convention used in
  `GormleyLab-website`.
* **GitHub Pages, not Render.** GH Actions gives free reliable cron; Render's
  free tier sleeps and its cron jobs are paid. Committing the JSON also gives a
  free forecast archive in git history.
* **Open-Meteo is the only data source.** Windy appears as deep links only —
  its free API tier returns deliberately shuffled data and its paid tier
  excludes ECMWF. Google WeatherNext 3 deferred: needs a billed GCP project.
* **MFWAM is the primary wave model**, not ECMWF WAM. It is the only one on
  Open-Meteo that decomposes wind wave from swell, which the captain's briefing
  prompt asks for by name. ECMWF WAM gives total wave height only and is kept
  as a cross-check.
* **The AI briefing is strictly additive.** If the Claude call fails or the key
  is missing, the run still succeeds and publishes every number. Nothing
  deterministic may ever depend on it.
* **Mobile-first CSS.** Everything outside a media query is the phone layout;
  `min-width` queries add desktop on top. The fleet reads this in a cockpit.
  The hour-by-hour data is stacked rows on a phone and a table only from 720px
  up - the primary content must never scroll sideways on a handheld.
* **Three themes, including night vision.** Day, dark, and a red-on-black
  "night" mode that preserves dark adaptation, because the fleet sails to the
  Sciara del Fuoco after dark and a white phone screen costs you an hour of
  night vision. Night mode is deliberately monochrome; charts separate their
  lines by dash pattern rather than hue there.
* **Type is Fraunces + IBM Plex Sans/Mono**, not the generic serif-on-cream
  look. All figures are tabular mono. Palette is cool and blue-biased, not
  warm cream.
* **Structured output, not markdown**, from the Claude call — the page renders
  real elements from validated JSON, so no markdown parser ships to the browser.

## Safety-critical data

`data/waypoints.json` encodes an **exposure sector** per mooring: the arc of
compass bearings that berth is open to. `scripts/sailing.py:shelter_score`
turns those into the "tonight's berth" recommendation.

These sectors were inferred from the itinerary text, **not from charts**. A
wrong sector produces a confidently wrong shelter recommendation — the most
consequential bug this project can have. Every entry carries `"verified"`, the
page badges unverified ones, and a standing warning shows until they are all
checked. Do not remove that warning to tidy the UI.

The same applies to the go/caution/no-go thresholds in `sailing.py` — they are
conservative defaults for 45ft cats, meant to be tuned by the fleet captain, and
the page says so.

## Waypoint tools

Two scripts derive the safety-critical waypoint data from OpenStreetMap
instead of guessing it. Both report by default and only change anything with
`--write`. They cache the OSM extract in `scripts/_*.json` (gitignored).

```bash
python scripts/fix_positions.py     # anchor to OSM harbours, snap into water
python scripts/derive_sectors.py    # ray-cast the exposure sectors
```

`fix_positions.py` found that four of the original thirteen coordinates were
**on dry land** - Porto Pignataro, San Pietro, Marina del Gabbiano and Filicudi
Porto - which made their forecasts and shelter scores meaningless. Two
independent tests agreed: ray-casting reported "0 degrees open" (the signature
of being inside a coastline ring) and a crossing-parity test said inside.

`derive_sectors.py` casts a ray every degree out to 5 nm against coastline,
breakwaters and piers, and keeps every open arc. It is a much better first
pass than a guess, but it is still **not** a chart check: it cannot see swell
refraction, depth, holding ground, or a low spit that stops swell but not
wind. `verified` stays false until a human confirms against a pilot book.

**`exposed_sector` may be a single `[from, to]` arc or a list of them.** Four
berths are open to more than one arc - San Pietro faces east *and* has a gap
to the north - and scoring only the widest reported a northerly there as
sheltered. `sector_proximity` takes the max across arcs; there are tests for
both forms.

## Gotchas discovered the hard way

* **ECMWF AIFS publishes no gust field.** "Max gust across models" was silently
  just IFS. Models carry `provides_gusts` and the page says so.
* **IFS gusts are interval maxima**, not instantaneous. Against a light mean
  wind this yields 5×+ gust factors that are model artefacts, not squalls.
  `sailing.is_gust_spike` reports these as a footnote rather than raising a
  false amber — false cautions train people to ignore real ones.
* **ICON-2i runs ~63 h then returns nulls** for the rest of the array.
  Open-Meteo pads rather than substituting another model. Always match series
  on timestamp (`openmeteo.series_at`), never on index.
* **Wave-model cells inside harbours are land** and return null.
  `update_weather.nearest_marine` falls back to the closest point with real
  data rather than reporting a flat calm that does not exist.
* **Marine model metadata lives on `marine-api.open-meteo.com`**, not the main
  host. The `host` key on each wave model handles this.
* **`%-d` in strftime is not portable to Windows.** Use `fmt_date`.
* **"Right now" cards show the multi-model mean, never one model.** At 2 km
  ICON-2i sometimes resolves a local acceleration the coarser models miss - it
  read 16.5 kt at Filicudi where IFS and AIFS both said ~6 kt. A bare headline
  number from one model is misleading, so the cards average every available
  model and print the range when the spread exceeds 8 kt.
* **`const Foo` at the top of a classic script is NOT `window.Foo`.** It is a
  global *lexical* binding. `if (window.ORYCMap)` was therefore always false
  and the map and charts never initialised at all. Guard with
  `typeof ORYCMap !== 'undefined'`. `test_render.js` now asserts both actually
  run - its earlier `sandbox.window.ORYCMap = ...` line was itself a no-op and
  hid the bug.
* **A Chart.js canvas built in a zero-width container stays zero-width
  forever** - no error, no console output, just a blank chart. Fonts still
  loading or a section not yet laid out is enough to trigger it. `charts.js`
  keeps a ResizeObserver and nudges `resize()` after layout and after
  `document.fonts.ready`. A node render test cannot catch this: there is no
  layout. It has to be checked in a browser.
* **Map tiles are the only thing needing the network at view time.** Leaflet
  fires `tileerror`; the page then swaps in a grid background and says the
  route and moorings are still accurate, rather than showing an empty box.
* **The map's dark filter must target `.leaflet-tile-pane`,** not
  `#map-canvas` - filtering the whole pane inverted the route lines, markers
  and wind arrows too.
* **Wind arrows are inline SVG, not rotated text glyphs.** A rotated "↑" sat
  off its baseline and read as a stray tick mark at small sizes.
* **Point of sail must not say "no-go"** — it collided with the safety verdict
  and read as a contradiction on the same row. It says "head to wind — motor".
  There is a test asserting this.

## Testing

```bash
python -m pytest scripts/ -q     # sailing maths: bearings, sectors, verdicts
node scripts/test_render.js      # renders the page against real data
```

`test_render.js` exists because the likeliest bug in a two-language project is
a field Python renamed that JavaScript still reads — silent in a browser,
invisible to a linter. It runs in CI after every fetch.

Use `python scripts/update_weather.py --simulate` to preview the passage
planner before the real dates enter the forecast horizon. It shifts itinerary
dates into the live window and the page shows a loud red banner. Never commit
simulated data.

## Conventions

* Directions are degrees TRUE and meteorological (the direction wind comes
  FROM). Speeds in knots, heights in metres.
* Status is never conveyed by colour alone — every chip carries a glyph and a
  word, so it survives colour blindness and greyscale printing.
* Everything reaching `innerHTML` goes through `ORYC.esc`.
* Palette is sampled from `ORYC_flag.png`, which is exactly three colours:
  `#D2232A` red, `#23408F` navy, white. Do not invent brand colours.
* `picture-of-logo.jpg` (1.7 MB) is gitignored — the site uses the 10 KB PNG.
