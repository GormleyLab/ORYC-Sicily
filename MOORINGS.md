# Adding, editing and removing moorings

`data/waypoints.json` is the safety-critical file in this project. A mooring
entry decides where the forecast is sampled, which berth the page recommends
for a given night, and what the map draws. A wrong exposure sector produces a
confidently wrong shelter recommendation, which is the worst failure this site
can have — so every change here ends with the same three commands, and most
changes should end with `verified: false`.

Read `CLAUDE.md` § *Safety-critical data* first if you have not already.

## The shape of an entry

```json
"panarea_drautto": {
  "name": "Drautto buoy field",
  "island": "Panarea",
  "lat": 38.6288,
  "lon": 15.07,
  "type": "buoy",
  "exposed_sector": [97, 227],
  "shelter_note": "Nautilus buoy field in Baia di Drautto…",
  "verified": false,
  "group": "Panarea",
  "position_source": "Campo Boe Nautilus… 38°37.73'N 015°04.20'E",
  "sector_source": "derived from OSM coastline, rays to 5 nm",
  "verification_note": "Not described separately in the Isole Eolie chapter…",
  "hazard_note": "An old groyne runs about 100 m SE from the ferry mole…",
  "no_anchoring": true
}
```

| Field | Required | What it does |
|---|---|---|
| `name` | yes | Shown on the page, the map popup and in the briefing |
| `island` | yes | Grouping fallback when `group` is absent |
| `lat`, `lon` | yes | **Where the forecast is sampled.** Must be in water — see below |
| `type` | yes | `marina`, `harbour`, `dock`, `anchorage` or `buoy`. Carried into `weather.json`; nothing renders it yet, but the run raises `KeyError` without it |
| `exposed_sector` | yes | The arc(s) the berth is open to. `null` means enclosed |
| `shelter_note` | yes | One or two sentences the berth card prints verbatim |
| `verified` | yes | `true` only after a chart or pilot-book check by a human |
| `group` | no | Which "right now" card this berth belongs to; falls back to `island` |
| `position_source` | no | Where the coordinate came from |
| `sector_source` | **if `verified`** | What verified the sector. A test enforces this |
| `verification_note` | no | Why it is not verified, or what a check would still resolve |
| `hazard_note` | no | Printed as a warning on the berth card |
| `no_anchoring` | no | `true` where anchoring is prohibited and you must take a buoy |

### `exposed_sector` in detail

Degrees **true**, **meteorological** (the direction weather comes *from*),
`[from, to]` clockwise. `[97, 227]` means the berth is open from ESE round to
SW. Arcs may wrap through north: `[345, 99]` is valid.

A berth open in two directions takes a **list of arcs**:

```json
"exposed_sector": [[83, 232], [10, 35]]
```

`sailing.sector_proximity` takes the max across arcs. This matters — San Pietro
faces east *and* has a gap to the north, and scoring only the widest arc
reported a northerly there as sheltered. Both forms have tests.

Two special values:

* `null` — a fully enclosed basin. `shelter_score` returns 1.0 unconditionally.
  Only correct for an artificial marina, and it bypasses all scoring, so do not
  reach for it to mean "quite well sheltered".
* `[0, 359]` — open all round, as at Stromboli, where the pilot says swell
  rolls in from almost any direction. A berth with no sheltered arc is capped
  at "workable" however calm the hour is.

## Adding a mooring

1. **Pick a key.** Lowercase `island_place`, matching the existing ones:
   `lipari_pignataro`, `panarea_zimmari`. The key is referenced from the
   itinerary and the legs, so choose it once and leave it alone.

2. **Get a position that is in water.** A coordinate on land makes the forecast
   and the shelter score meaningless — four of the original thirteen were on dry
   land. Check before you commit:

   ```bash
   python scripts/fix_positions.py     # reports; --write to snap into water
   ```

   Prefer a real source — a pilot-book waypoint, a buoy-field operator's
   published GPS, an OSM harbour feature — over a coordinate read off a map by
   eye. Record it in `position_source`.

3. **Derive the sector rather than guessing it.**

   ```bash
   python scripts/derive_sectors.py    # reports; --write to apply
   ```

   This ray-casts every degree out to 5 nm against coastline, breakwaters and
   piers. It is a far better first pass than a guess, but it is **not** a chart
   check: it cannot see swell refraction, depth, holding ground, or a low spit
   that stops swell but not wind. Leave `verified: false`.

   ⚠ `derive_sectors.py --write` rewrites **every** mooring's sector, including
   pilot-verified ones. If you only want the new entry, run it without
   `--write` and copy the arc by hand.

4. **Offer it as a berth.** A mooring is only scored on nights where the
   itinerary lists it. In `data/itinerary.json`, add the key to that day's
   `mooring_options`:

   ```json
   { "date": "2026-10-05", "mooring_options": ["panarea_sanpietro", "panarea_drautto"] }
   ```

   Without this the entry still appears on the map and in `series`, but never
   as a berth recommendation.

5. **Set `group`** if the berth shares a "right now" card with others on the
   same island. One card is rendered per distinct group.

6. **Run the checks** (below).

## Editing a mooring

Change the fields in place. Two rules:

* **If you move `lat`/`lon`, re-derive the sector.** The arc is a property of
  the position, and an arc cast from the wrong water is worse than no arc —
  that was the Drautto bug. Run `derive_sectors.py` afterwards and confirm it
  reports `agrees`.
* **If you change `exposed_sector`, say where it came from** in
  `sector_source`, and reconsider `verified`. A better estimate is still an
  estimate.

`data/weather.json` embeds each mooring's coordinates, so after any position
change the committed forecast is stale until the next run. Regenerate with:

```bash
gh workflow run update-weather.yml
```

Do **not** just run `scripts/update_weather.py` locally for this — without
`ANTHROPIC_API_KEY` in your environment it writes `briefing: null`, and
committing that blanks the Skipper's briefing on the live site until the next
cron.

## Removing a mooring

Delete the entry, then remove every reference to its key, or the run will fail
with a `KeyError`:

* `data/itinerary.json` — any day's `mooring_options`
* `data/waypoints.json` — any leg's `from` or `to`

A leg whose endpoint you deleted has to be deleted or repointed; there is no
fallback. Check for stragglers:

```bash
grep -rn "the_key_you_removed" data/ scripts/ assets/
```

## Marking one verified

`verified: true` means a human checked the exposure sector against a chart or a
pilot book. OpenStreetMap geometry, a marina listing and a web search are
**not** that standard — they are good enough to fix a position, not to close a
sector.

The idiomatic path is `scripts/apply_pilot.py`, which holds the Imray statements
in a `PILOT` dict and sets the flag:

```bash
python scripts/apply_pilot.py            # report: derived vs. pilot, side by side
python scripts/apply_pilot.py --write    # apply, set verified: true
```

Note the constraint in `test_sailing.py:252`: anything `verified` must carry a
`sector_source` containing the word `Pilot`. If you verify from a chart or from
a harbourmaster rather than from the book, that test fails **by design** — it
is enforcing the current evidence standard. Widening it is a deliberate
decision about what counts as verification, not a test to paper over.

Three moorings are currently unverified: **Portorosa**, **Drautto** and **Baia
Milazzese**. Their positions have been cross-checked, their sectors have not.

## After any change

```bash
python -m pytest scripts/ -q     # sector forms, bearings, verdicts
node scripts/test_render.js      # renders the page against real data
python scripts/derive_sectors.py # does geometry still agree with what is stored?
```

`test_render.js` is the one that catches the likeliest bug in a two-language
project: a field Python renamed that JavaScript still reads — silent in a
browser, invisible to a linter.

## Things that will bite you

* **Every mooring costs two Open-Meteo points**, one atmospheric and one
  marine, fetched for every model. Adding berths is not free.
* **Wave-model cells inside harbours are land** and return null.
  `update_weather.nearest_marine` falls back to the closest point with real
  data rather than reporting a flat calm that does not exist.
* **Never match series on index** — ICON-2i runs ~63 h then returns nulls, and
  Open-Meteo pads rather than substituting. Use `openmeteo.series_at`.
* **The page badges unverified moorings** in two places: an `unverified` chip on
  the berth cards and a "Not yet chart-verified" line in the map popup. Do not
  remove those to tidy the UI.
* **Status is never colour alone.** Anything you add to a berth card needs a
  glyph and a word as well, so it survives colour blindness and a greyscale
  print.
