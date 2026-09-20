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
  "verified": true,
  "group": "Panarea",
  "position_source": "confirmed by the fleet owner…",
  "sector_source": "Ray-cast from OSM coastline to 5 nm, then confirmed by the owner…",
  "verification_note": "Verified by the fleet owner, not by the pilot book…",
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
| `verified` | yes | `true` only once the pilot book or the fleet owner has closed the sector |
| `group` | no | Which "right now" card this berth belongs to; falls back to `island` |
| `position_source` | no | Where the coordinate came from |
| `sector_source` | **if `verified`** | What verified the sector. A test enforces this |
| `verification_note` | no | Why it is not verified, or what a check would still resolve |
| `hazard_note` | no | Printed as a warning on the berth card |
| `no_anchoring` | no | `true` where anchoring is prohibited and you must take a buoy |

### Units in the notes

`shelter_note` and `hazard_note` are printed to the fleet verbatim, and the
fleet is American. **Depths and distances go in feet, with the source's metric
figure in brackets** — `16-33 ft (5-10 m)`, `650 ft (200 m)`. Feet first, every
time. Keep the bracket: the Imray pilot is metric, so it is what lets the next
reader check the note against the book, and a charter boat in Italy usually has
its depth sounder set in metres. `test_crew_facing_notes_lead_with_feet`
enforces the order. Bearings stay degrees true, passage distances stay nautical
miles, and the provenance fields (`position_source`, `sector_source`,
`verification_note`) stay metric — they are engineering notes comparing against
OSM and chart data, not something the fleet reads.

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

`verified: true` means the exposure sector was closed by someone who could
actually settle it. **Two authorities count, and nothing else:**

* **the Imray pilot book**, because Heikell surveyed these anchorages;
* **the fleet owner**, who sails them.

OpenStreetMap geometry, marina listings and web searches are **not** that
standard. They are good enough to fix a *position* — and they have fixed
several — but none of them can close an *arc*, because the thing they all miss
is swell bending round a headland, which is exactly what a wrong arc gets
wrong.

For the pilot book the idiomatic path is `scripts/apply_pilot.py`, which holds
the Imray statements in a `PILOT` dict and sets the flag:

```bash
python scripts/apply_pilot.py            # report: derived vs. pilot, side by side
python scripts/apply_pilot.py --write    # apply, set verified: true
```

For an owner confirmation, edit the entry by hand and say so in
`sector_source` — name what was confirmed, not just that it was. Drautto is the
worked example: the arc is ray-cast, but the one quarter geometry could not
settle (whether NE gets in past Punta Torrione) was put to the owner and
answered.

Two tests enforce this, in `scripts/test_sailing.py`:

* `test_verified_moorings_carry_their_source` — a verified berth with a real
  arc must name one of `SECTOR_AUTHORITIES` in `sector_source`; one with
  `exposed_sector: null` must instead say the basin is `enclosed`.
* `test_no_mooring_is_verified_by_geometry_alone` — a verified berth's source
  may not still be the raw `derived from OSM…` string that
  `derive_sectors.py` writes. That combination means a derived arc was blessed
  without anyone actually checking it.

Widening `SECTOR_AUTHORITIES` is a deliberate decision about what counts as
evidence. Make it on purpose; never delete an assertion to make a flag stick.

**All twelve moorings are currently verified** — ten by the pilot, Drautto and
Portorosa by the owner. Baia Milazzese used to be the thirteenth; it was
deleted as a duplicate of Cala Zimmari, 40 m away, which the pilot treats as
the same anchorage. Cala Zimmari carries both names so the itinerary's
"Baia Milazzese" still resolves to something on the map.

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
