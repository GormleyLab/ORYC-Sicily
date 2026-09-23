# ORYC Aeolian Flotilla — itinerary & weather

A single-page site for the Ocean Reef Yacht Club flotilla in the Aeolian Islands,
**3–10 October 2026**. It carries the eight-day itinerary and, more importantly,
a marine weather briefing that rebuilds itself on a schedule.

**Live site:** https://sicily-flotilla.com/ (the old
https://gormleylab.github.io/ORYC-Sicily/ link redirects there)

---

## What it does

Wind in knots, sea and swell in **feet**, directions in degrees true and
meteorological (the direction the wind comes *from*). The models publish metres
and `data/weather.json` stores metres — feet are produced at the point of
display, so the archived JSON stays directly comparable with the source data.

A **ft / m switch** sits in the masthead beside the theme buttons and is
remembered per device. It moves the figures only: the skipper's briefing, the
passage reasons and the pilot-book notes are prose written when the run was
built and stay in feet, so the status strip carries a caveat while metres are
showing.

| | |
|---|---|
| **Passage planner** | For each of the seven legs: rhumb-line bearing, distance, and wind / gust / wave sampled at departure, midpoint and arrival for every departure hour from 06:00 to 14:00 — with true wind angle, point of sail, Beaufort force, reefing guidance and a go / caution / no-go call. Tells you the best window and when it deteriorates. |
| **Lee-side berth picker** | Every mooring option from the itinerary carries an *exposure sector* — the arc of compass bearings it is open to. Given the forecast wind and swell for that night, the options are scored and ranked, so you can see that (say) an ENE blow makes Rinella a much better bet than Santa Marina. |
| **Route map** | Leaflet map of the legs and moorings, markers coloured by shelter verdict, with wind arrows you can scrub through the next five days. |
| **Wind & sea charts** | Every model drawn as its own line rather than averaged, because where the models diverge is what you actually need to know. |
| **Skipper's briefing** | Claude writes the prose briefing from the numbers above — synopsis, overnight conditions, next-morning outlook — in the style of the captain's original Gemini prompt. |
| **Stromboli panel** | Links to the Smithsonian GVP and INGV bulletins for the Monday-night option and the Sciara del Fuoco night sail. |

It is **mobile-first** — the phone layout is the default and desktop is layered
on top, because this gets read one-handed in a cockpit. The hour-by-hour figures
stack into rows on a phone and become a table only on wider screens, so the
primary content never scrolls sideways.

There are **three themes**: day, dark, and a red-on-black **night-vision** mode
that protects dark adaptation — useful on the Sciara del Fuoco night sail, where
a white screen costs you an hour of night vision. The choice is remembered per
device.

Everything is designed to print: `@media print` renders the briefing, passage
table and berth recommendations cleanly, for a paper copy before you leave wifi.

---

## Where the weather comes from

All forecasts come from [Open-Meteo](https://open-meteo.com), which is keyless
and free for non-commercial use.

| Model | Grid | Used for | Notes |
|---|---|---|---|
| ECMWF IFS 0.25° | ~25 km | wind, gust, pressure, weather | Gust field is an **interval maximum**, not instantaneous — gust factors look large in light air. |
| ECMWF AIFS | ~28 km | wind, pressure | ECMWF's ML model, a genuinely independent opinion. **Publishes no gust field.** |
| ItaliaMeteo ARPAE ICON-2i | 2 km | wind, gust | Finest grid available here. Runs only ~60–72 h and updates every 12 h, so it drops out of the longer-range view. |
| Météo-France MFWAM | ~8 km | wave, wind wave, **swell** | The only model on Open-Meteo that decomposes the sea into wind wave and swell. |
| ECMWF WAM 0.25° | ~25 km | total wave height | Cross-check on MFWAM. |

Model **initialisation times** are fetched from each model's `meta.json` and
shown on the page, so the data's age is never a guess.

### Why not Windy?

The fleet uses Windy daily, so it is worth being explicit: Windy is a *viewer*,
not a model. Its layers are ECMWF IFS, GFS, ICON-EU, AROME and the ECMWF/GFS
wave models — the same forecasts Open-Meteo serves, and Open-Meteo additionally
carries ICON-2i at 2 km where Windy's best regional layer over Italy is ICON-EU
at 7 km. Windy is also unusable as a data source here: its free Point Forecast
tier returns *"randomly shuffled and slightly modified data — development
purpose only"*, and the €990/year Professional tier excludes ECMWF under
licensing. So Windy appears as **deep links** next to every leg and mooring —
one click into the app you already trust, no key and no embed.

Google **WeatherNext 3** was evaluated and deferred: it needs a billed GCP
project, which is the one thing in this stack that could fail on a billing
issue mid-trip.

---

## How it updates

`.github/workflows/update-weather.yml` runs the pipeline and commits the result
**three times a day**. Each slot sits just after a model cycle lands, so every
run carries genuinely new data rather than re-fetching the last one:

| UTC | CEST | Picks up |
|---|---|---|
| 05:40 | 07:40 | the 00Z runs — the morning briefing, before anyone sails |
| 12:40 | 14:40 | the 06Z IFS / AIFS cycle — an afternoon refresh |
| 16:40 | 18:40 | ICON-2i's 12Z — overnight and next-morning outlook |

You can also run it any time from *Actions → Update weather → Run workflow*.

### What actually triggers it

The workflow carries its own `schedule:` crons, but **GitHub does not run them on
time**. Scheduled triggers are best-effort and queue behind platform load: over
20–22 September the 05:40 UTC slot started at 10:03, 10:16 and 11:02 UTC — four
to five hours late. During the trip that would land the morning briefing after
the fleet had already sailed.

So the real trigger is **external**: three jobs on [cron-job.org](https://cron-job.org)
POST to the workflow's `dispatches` endpoint at 05:40, 12:40 and 16:40 UTC. A
dispatch starts within seconds — measured end to end, trigger to committed
`data/weather.json`, in 52 s.

```
POST https://api.github.com/repos/GormleyLab/ORYC-Sicily/actions/workflows/update-weather.yml/dispatches
Accept: application/vnd.github+json
Authorization: Bearer <fine-grained PAT>
X-GitHub-Api-Version: 2022-11-28
{"ref":"main"}
```

The PAT is scoped to this repository with **Actions: read and write** and nothing
else, so the worst a compromise could do is trigger a weather update. It
**expires 2026-10-23**, two weeks after disembarkation — after that the jobs fail
and cron-job.org emails on the first failure.

**GitHub's own crons stay in place as a fallback.** They cost nothing and are the
only thing that still fires if the external trigger lapses; hours-late data beats
none, the same trade the `stale` banner makes. The cost is a duplicate run on
days GitHub is slow, which just commits a fresher forecast. Two asymmetries to
know about: the workflow carries no 12:40 cron of its own, so **the midday slot
has no fallback**; and its gate skips the *scheduled* evening run before
3 October, so until then the fallback is morning-only. A dispatch is always
treated as manual and proceeds, so none of this affects the external jobs.

**What a run costs.** The Open-Meteo fetches, the Actions minutes (free on a
public repo) and cron-job.org are all free; the only metered cost is the Claude
briefing, at roughly 12.5k input and 1.6k output tokens — about **$0.10 a run**
on Claude Opus 5, so ~$0.30 a day. Each run records its own `usage` in
`data/weather.json`, so the figure can be re-checked rather than trusted.

The browser makes no API calls — it renders a single pre-computed
`data/weather.json`, so every update is also archived in the git history.

If a fetch fails, the previous file is kept and flagged `stale`, and the page
shows a warning banner — publishing labelled stale data beats publishing
nothing. If the Claude call fails, the numbers publish anyway with no briefing.

---

## Layout

```
index.html                  the whole page
assets/
  style.css                 ORYC palette + print stylesheet
  sailing.js                display helpers, Windy deep links
  app.js                    renders briefing, passages, berths, itinerary
  map.js                    Leaflet route + wind arrows
  charts.js                 Chart.js wind and sea timeseries
data/
  itinerary.json            hand-authored from Itinerary.txt     (static)
  waypoints.json            coordinates + exposure sectors       (static)
  weather.json              rebuilt by the cron                  (generated)
scripts/
  update_weather.py         orchestrator and entry point
  openmeteo.py              API client, model metadata
  sailing.py                bearings, TWA, Beaufort, verdicts, shelter scoring
  briefing.py               Claude API call
  test_sailing.py           unit tests for the maths
  test_render.js            renders the page against real data
```

---

## Running it locally

```bash
pip install -r scripts/requirements.txt

python -m pytest scripts/ -q                              # the sailing maths
python scripts/update_weather.py --dry-run --no-briefing  # fetch, write to temp
python scripts/update_weather.py                          # write data/weather.json
node scripts/test_render.js                               # render against real data

python -m http.server 8000 && open http://localhost:8000
```

Useful flags:

* `--dry-run` — write to a temp file, leave `data/` alone
* `--no-briefing` — skip the Claude call (no API key needed)
* `--simulate` — **preview mode.** Shifts the itinerary dates into the live
  forecast window so the passage planner and berth picker can be exercised
  before the real dates come into range. The page shows a loud red banner while
  this data is in place. Never used by the scheduled job.

Until roughly 28 September the real trip dates sit beyond every model's
horizon, so a normal run legitimately reports `legs with forecast: 0/7`. Use
`--simulate` to see the planner working.

---

## Setup checklist

- [x] Make the repository **public** (free Actions minutes and Pages)
- [x] **Settings → Pages → Deploy from branch → `main` / root**
- [x] **Settings → Secrets → Actions →** add `ANTHROPIC_API_KEY`
- [x] Run *Actions → Update weather → Run workflow* once to seed the data
- [x] **Custom domain** — `sicily-flotilla.com` at Hover: four `@` A records to
      GitHub's Pages IPs (185.199.108-111.153), `www` CNAME to
      `gormleylab.github.io`; `CNAME` file in the repo root; HTTPS enforced
- [x] **External trigger** — three cron-job.org jobs dispatching the workflow at
      05:40, 12:40 and 16:40 UTC, because GitHub's own crons run hours late; see
      *How it updates*. PAT expires 2026-10-23.
- [ ] **Verify the waypoints** — see below, and `MOORINGS.md`

Setup is done; the site is live at <https://sicily-flotilla.com/>.
Verified with `gh`, not assumed — visibility PUBLIC, Pages `built` from `main` /
root with `cname` set and `https_enforced` true, the secret present since
2026-09-20 02:07Z, and bot weather commits carrying a briefing. Re-check with `gh repo view`, `gh api .../pages` and
`gh secret list` rather than trusting this list.

## Deriving the waypoints

```bash
python scripts/fix_positions.py     # anchor to OSM harbours, snap into water
python scripts/derive_sectors.py    # ray-cast the exposure sectors
```

Both report by default; `--write` applies. `fix_positions.py` anchors each
mooring to its OpenStreetMap harbour, marina or anchorage feature and walks the
point seaward until it is genuinely on water. `derive_sectors.py` casts a ray
every degree out to 5 nm against coastline, breakwaters and piers, and keeps
every arc that reaches open sea.

Running these found that **four of the original thirteen coordinates sat on dry
land**, which made their forecasts and shelter scores meaningless.

## Pilot book verification

Ten of the twelve moorings are checked against Imray's *Italian Waters
Pilot* (Heikell), Isole Eolie chapter, via `scripts/apply_pilot.py`. Where the
pilot states a shelter direction it wins over the geometry, and the entry
carries its prose, any hazard it flags, and `verified: true`.

It overturned two sectors outright. **Porto Pignataro is open SW**, not east —
the harbour mouth faces into the Lipari roadstead — and **Santa Marina's south
basin gives good all-round shelter**, with strong southerlies the concern. That
reverses the Salina example: Rinella is the berth open E–S, and Santa Marina is
the refuge in an easterly.

Drautto and Portorosa are not described in that chapter; both were closed by
the fleet owner instead, who is the second of the two authorities allowed to
settle a sector. Baia Milazzese was deleted as a duplicate of Cala Zimmari —
40 m apart, one anchorage in the pilot, two entries here.

## Before the fleet relies on this

**All twelve moorings now carry `"verified": true`** — ten from the Imray pilot
chapter, and Drautto and Portorosa from the fleet owner, who sails them. Two
authorities may close an exposure sector and nothing else; see `MOORINGS.md`,
where two tests enforce it.

That is not the same as saying every number is right. **The shelter rankings
are only as good as those sectors** — a wrong sector produces a confidently
wrong recommendation, which is the worst failure this site could have. One
caveat is on the record and unresolved: at Drautto, 200 m further offshore the
arc widens from 97–227 to 76–243, so a boat on an outer buoy may be less
sheltered than the stored figure says.

The go / caution / no-go thresholds in `sailing.py` are still conservative
defaults for 45 ft cats, meant to be tuned by the fleet captain, and the page
says so.

The site is a planning aid, not a navigation tool. Always verify against the
Guardia Costiera and Meteomar bulletins before departure.
