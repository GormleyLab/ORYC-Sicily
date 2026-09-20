# ORYC Aeolian Flotilla — itinerary & weather

A single-page site for the Ocean Reef Yacht Club flotilla in the Aeolian Islands,
**3–10 October 2026**. It carries the eight-day itinerary and, more importantly,
a marine weather briefing that rebuilds itself on a schedule.

**Live site:** https://gormleylab.github.io/ORYC-Sicily/

---

## What it does

| | |
|---|---|
| **Passage planner** | For each of the seven legs: rhumb-line bearing, distance, and wind / gust / wave sampled at departure, midpoint and arrival for every departure hour from 06:00 to 14:00 — with true wind angle, point of sail, Beaufort force, reefing guidance and a go / caution / no-go call. Tells you the best window and when it deteriorates. |
| **Lee-side berth picker** | Every mooring option from the itinerary carries an *exposure sector* — the arc of compass bearings it is open to. Given the forecast wind and swell for that night, the options are scored and ranked, so you can see that (say) an ENE blow makes Rinella a much better bet than Santa Marina. |
| **Route map** | Leaflet map of the legs and moorings, markers coloured by shelter verdict, with wind arrows you can scrub through the next five days. |
| **Wind & sea charts** | Every model drawn as its own line rather than averaged, because where the models diverge is what you actually need to know. |
| **Skipper's briefing** | Claude writes the prose briefing from the numbers above — synopsis, overnight conditions, next-morning outlook — in the style of the captain's original Gemini prompt. |
| **Stromboli panel** | Links to the Smithsonian GVP and INGV bulletins for the Monday-night option and the Sciara del Fuoco night sail. |

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

`.github/workflows/update-weather.yml` runs the pipeline and commits the result:

* **once a day** (05:40 UTC / 07:40 CEST) until 3 October
* **twice a day** (adding 16:40 UTC / 18:40 CEST) once underway
* manually any time via *Actions → Update weather → Run workflow*

Times sit just after the relevant model runs land. The browser makes no API
calls — it renders a single pre-computed `data/weather.json`, so every update is
also archived in the git history.

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

- [ ] Make the repository **public** (free Actions minutes and Pages)
- [ ] **Settings → Pages → Deploy from branch → `main` / root**
- [ ] **Settings → Secrets → Actions →** add `ANTHROPIC_API_KEY`
- [ ] Run *Actions → Update weather → Run workflow* once to seed the data
- [ ] **Verify the waypoints** — see below

## ⚠ Before the fleet relies on this

Every mooring in `data/waypoints.json` currently carries `"verified": false`.
The coordinates and exposure sectors were derived from the itinerary text and
general knowledge of the islands, not from a chart. **The shelter rankings are
only as good as those sectors** — a wrong sector produces a confidently wrong
recommendation, which is the worst failure this site could have.

Work through them on the map against satellite imagery and a pilot book,
confirm each sits in the right bay with the right exposure, and flip
`verified` to `true`. The page badges every unverified mooring and shows a
standing warning until they are all done.

The site is a planning aid, not a navigation tool. Always verify against the
Guardia Costiera and Meteomar bulletins before departure.
