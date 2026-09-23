# CLAUDE.md — ORYC Aeolian Flotilla site

## Current state

**Deployed and live at https://sicily-flotilla.com/** - the
pipeline fetches five models, derives passage and berth guidance, the Action
commits `data/weather.json`, and Pages serves it. Setup is finished: the repo
is public, Pages is enabled and built from `main` / root, and
`ANTHROPIC_API_KEY` is set as a repo secret (added 2026-09-20 02:07Z). Every
`github-actions[bot]` weather commit carries a briefing. The custom domain was
added 2026-09-20: DNS is at Hover (four `@` A records to GitHub's Pages IPs,
`www` CNAME to `gormleylab.github.io`), the `CNAME` file in the repo root is
what tells Pages about it, and HTTPS is enforced. The old
`gormleylab.github.io/ORYC-Sicily/` URL 301s to the new one, so links already
sent to the fleet keep working. Do not delete `CNAME` - that drops the domain.

Don't guess at any of that - `gh` is installed and authenticated, so ask:

```bash
gh repo view GormleyLab/ORYC-Sicily --json visibility
gh api repos/GormleyLab/ORYC-Sicily/pages --jq '{status,cname,https_enforced,branch:.source.branch}'
gh secret list --repo GormleyLab/ORYC-Sicily
gh workflow run update-weather.yml        # regenerate on demand
```

**A local `update_weather.py` run has no API key** unless you put one in the
environment, so it writes `briefing: null` and says "briefing skipped" - that
is the additive path working, not a missing secret. Do not commit such a run
over a good one: it blanks the Skipper's briefing on the live site until the
next cron. Prefer `gh workflow run update-weather.yml`, which uses the secret
and lands a complete run.

**All twelve moorings in `data/waypoints.json` are `"verified": true`** - ten
from the Imray pilot chapter, and Drautto and Portorosa from the fleet owner,
who sails them. Baia Milazzese was deleted as a duplicate of Cala Zimmari.
Two authorities may close an exposure sector and nothing else; `MOORINGS.md`
has the rule and two tests enforce it.

Verified is not the same as right. **One caveat is on the record and open:** at
Drautto, 200 m further offshore the arc widens from 97-227 to 76-243, so a boat
on an outer buoy may be less sheltered than the stored figure. See
"Safety-critical data" below.

## Project summary

A static GitHub Pages site for a yacht-club flotilla in the Aeolian Islands,
3–10 October 2026. Shows the itinerary and a multi-model marine weather
briefing that rebuilds three times a day, at 05:40, 12:40 and 16:40 UTC — one
slot per model cycle (00Z, the 06Z IFS/AIFS, ICON-2i's 12Z). No build step: a
GitHub Action runs Python, commits `data/weather.json`, and Pages serves it.
The browser makes no API calls.

The Action is fired by **three cron-job.org jobs** that POST to its `dispatches`
endpoint, not by its own `schedule:` crons — GitHub ran those four to five
hours late on three consecutive days, which would put the morning briefing
after the fleet had sailed. The GitHub crons stay as a fallback, but they only
cover 05:40 and 16:40; there is no 12:40 cron in the workflow, so the midday
slot depends on the external trigger alone. A dispatch is always treated as
manual by the workflow's gate, so it never hits the pre-trip evening skip.
See *How it updates* in `README.md`; the PAT expires 2026-10-23.

A run costs about **$0.10**, all of it the Claude briefing (~12.5k in, ~1.6k
out on Opus 5); Open-Meteo, Actions minutes and cron-job.org are free. Every
run records its own `usage` in `data/weather.json` — read that rather than
re-deriving the figure.

See `README.md` for the full architecture and setup checklist, and
`MOORINGS.md` for how to add, edit, remove or verify a mooring.

## Locked-in decisions (do not relitigate without the owner)

* **No build step, no framework.** Plain HTML/CSS/JS plus two pinned CDN
  libraries (Leaflet, Chart.js). Deploy is `git push`. Chosen for reliability
  three weeks before departure over matching the Astro convention used in
  `GormleyLab-website`.
* **GitHub Pages, not Render.** GH Actions gives free cron; Render's free tier
  sleeps and its cron jobs are paid. Committing the JSON also gives a free
  forecast archive in git history. "Reliable" turned out to be wrong about the
  cron — hence the external trigger above — but everything else holds.
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
consequential bug this project can have. Every entry carries `"verified"`, and
the page badges unverified ones in two places: an `unverified` chip on the berth
cards and a "Not yet chart-verified" line in the map popup. Do not remove those
badges to tidy the UI.

There used to be a page-level notice counting the unverified moorings as well.
The owner had it dropped before the 2026 trip — there was no time to chart-check
the last three and the banner alarmed the fleet without telling them anything
actionable at the moment of choosing a berth. The badges carry the caveat
instead, at the point of use. Do not reinstate the banner without asking.

The same applies to the go/caution/no-go thresholds in `sailing.py` — they are
conservative defaults for 45ft cats, meant to be tuned by the fleet captain, and
the page says so.

## The pilot book is the authority

`Pilot-book.pdf` is a 13-page scan (Imray *Italian Waters Pilot*, Heikell,
Isole Eolie pp.371-383) with no text layer - extract the page images with
pypdf and read those. `scripts/apply_pilot.py` encodes its shelter statements
and sets `verified: true` for the ten moorings it covers. Drautto and
Portorosa are not described there and were closed by the owner instead.
Baia Milazzese was deleted: it was 40 m from Cala Zimmari and the pilot
treats the two as one anchorage, so the planner was scoring the same water
twice under two names. Cala Zimmari carries both names now.

**The pilot overturned two derived sectors and one of my own worked
examples.** Porto Pignataro is open SW, not east - the harbour mouth faces
into the roadstead - so both the hand guess (60-120) and the ray-cast (95-161)
were wrong. Santa Marina's S basin has good all-round shelter with southerlies
the concern, not the east-facing exposure that was derived. That reversed the
Salina worked example: **Rinella is the one open E-S, and Santa Marina is the
refuge in an easterly** - the opposite of what the tests originally asserted.

Stromboli is the case geometry could never get: the pilot says swell rolls in
from almost any direction, so its sector is the full circle and it is capped
at "workable" however calm it is. A berth with no sheltered arc is never
"sheltered" - that word would describe the place, not the hour.

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
wind. `verified` stays false until one of the two authorities confirms it: the
Imray pilot book, or the fleet owner, who sails these anchorages. See
`MOORINGS.md` - the rule is enforced by two tests.

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
  FROM). Speeds in knots. Heights are **stored in metres and shown in feet** -
  the fleet is American. `data/weather.json`, the model fields and every
  threshold in `sailing.py` stay metric; conversion happens only at the point
  of display, by `ORYC.height` in the browser and `sailing.feet` for the prose
  Python writes into `reasons` and `reason`. `briefing.py` converts into the
  payload instead, naming every converted key `*_ft`, because ground rule 1
  forbids Claude from stating a number the payload does not contain. Tests in
  both suites assert the rendered figure is the converted one - a regression
  here prints a sea a third of its real height with "ft" still on it.
* **Depths and distances in crew-facing prose are feet, with the source's
  metric figure in brackets** - `16-33 ft (5-10 m)`. The Imray pilot is metric
  and `apply_pilot.py` transcribes it, so the bracket is what lets the next
  reader check a note against page 377; a charter boat in Italy also has its
  depth sounder in metres. Feet always come first and a test enforces it. The
  provenance fields - `position_source`, `sector_source`, `verification_note` -
  stay metric: they compare coordinates against OSM and chart data and nobody
  in the fleet reads them. Passage distances stay nautical miles.
* **The ft/m switch in the masthead moves the numbers only.** It is a header
  toggle beside the theme buttons, persisted in `localStorage` under
  `oryc-units`, defaulting to feet. Because every figure is converted at render
  time from metric storage, switching is just `renderAll()` plus
  `ORYCCharts.refresh()` - there is no second copy of the data to keep in step.
  What it cannot move is prose written at build time: the Claude briefing, the
  `reasons`/`reason` strings from `sailing.py`, and the pilot-book notes all
  stay in feet. That is deliberate, not an oversight - you cannot safely
  regex-rewrite a model-written sentence about wave height - and `ORYC.unitNote`
  puts a caveat in the status strip whenever metres are showing so a skipper
  meets it before the mismatch. `test_render.js` drives the real button and
  checks ft → m → ft is byte-identical.
* Status is never conveyed by colour alone — every chip carries a glyph and a
  word, so it survives colour blindness and greyscale printing.
* Everything reaching `innerHTML` goes through `ORYC.esc`.
* Palette is sampled from `ORYC_flag.png`, which is exactly three colours:
  `#D2232A` red, `#23408F` navy, white. Do not invent brand colours.
* `picture-of-logo.jpg` (1.7 MB) is gitignored — the site uses the 10 KB PNG.
