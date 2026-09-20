"""Build data/weather.json for the ORYC Aeolian flotilla site.

Fetches multi-model forecasts from Open-Meteo, derives passage and berth
guidance with sailing.py, optionally asks Claude for a prose briefing, and
writes the result atomically so a failed run can never publish a half-file.

    python scripts/update_weather.py                 # full run, writes data/
    python scripts/update_weather.py --dry-run       # write to a temp file
    python scripts/update_weather.py --no-briefing   # skip the Claude call
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import tempfile
import traceback

import openmeteo as om
import sailing as s

# GitHub Actions runners and Windows consoles disagree about the default
# encoding; force UTF-8 so log lines with arrows or degree signs never crash
# a run that otherwise succeeded.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "weather.json"

TZ = dt.timezone(dt.timedelta(hours=2))  # CEST - Italy is UTC+2 for the whole trip
TRIP_START = dt.date(2026, 10, 3)
TRIP_END = dt.date(2026, 10, 10)

# Hours of chart data to publish. Five days keeps the payload small enough to
# load over a marina wifi or a phone tether while still covering the fleet's
# whole planning horizon once underway.
CHART_HOURS = 120

DEPARTURE_HOURS = list(range(6, 15))  # 06:00 to 14:00 local
OVERNIGHT_HOURS = [21, 0, 3]          # evening, midnight, early morning

# Set by --simulate: shifts every itinerary date into the live forecast window
# so the passage planner and berth picker can be exercised and previewed before
# the real dates come into range. Never used by the scheduled job.
DATE_SHIFT = dt.timedelta(0)

CHART_VARS = ["wind_speed_10m", "wind_gusts_10m", "wind_direction_10m"]
CONDITION_VARS = ["temperature_2m", "precipitation", "weather_code", "cloud_cover",
                  "pressure_msl"]
MARINE_VARS = ["wave_height", "wave_direction", "wave_period",
               "swell_wave_height", "swell_wave_direction", "swell_wave_period"]


# --- helpers ----------------------------------------------------------------

def load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def hour_key(date: dt.date, hour: int) -> str:
    """Open-Meteo returns local ISO timestamps without an offset."""
    return f"{date.isoformat()}T{hour:02d}:00"


def shift(date: dt.date, hour: int, hours: float) -> tuple[dt.date, int]:
    base = dt.datetime.combine(date, dt.time(hour)) + dt.timedelta(hours=hours)
    return base.date(), base.hour


def effective(date_str: str) -> dt.date:
    """The date to look weather up for - shifted only in --simulate mode."""
    return dt.date.fromisoformat(date_str) + DATE_SHIFT


def fmt_date(d: dt.date) -> str:
    """'Sun 4 Oct' - built by hand because %-d is not portable to Windows."""
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


def rnd(v, n=1):
    return None if v is None else round(v, n)


def consensus(models: dict, variable: str, key: str, how: str = "mean"):
    """Combine a variable across atmospheric models at one hour.

    `mean` for wind speed, `max` for gusts (the conservative choice - a gust
    one model sees and another misses is still a gust the fleet may meet),
    `circular` for directions.
    """
    vals = [om.series_at(models.get(m["id"]), variable, key) for m in om.ATMO_MODELS]
    present = [v for v in vals if v is not None]
    if not present:
        return None, {"confidence": "none", "n": 0}
    if how == "circular":
        return s.circular_mean(present), s.model_agreement([])
    agree = s.model_agreement(vals)
    value = max(present) if how == "max" else sum(present) / len(present)
    return value, agree


def nearest_marine(marine: dict, lat: float, lon: float, key: str) -> dict:
    """Sea state at `key`, from the closest sample point that actually has data.

    Wave-model grid cells inside a harbour are often land, so a mooring's own
    coordinates can come back null. Falling back to the nearest point with real
    numbers is better than reporting a flat calm that does not exist.
    """
    best = None
    for point in sorted(
        marine.values(),
        key=lambda p: s.distance_nm(lat, lon, p["lat"], p["lon"]),
    ):
        primary = point["models"].get("meteofrance_wave")
        wave = om.series_at(primary, "wave_height", key)
        if wave is None:
            continue
        dist = s.distance_nm(lat, lon, point["lat"], point["lon"])
        best = {
            "wave_height": rnd(wave, 2),
            "wave_direction": om.series_at(primary, "wave_direction", key),
            "wave_period": rnd(om.series_at(primary, "wave_period", key), 1),
            "swell_height": rnd(om.series_at(primary, "swell_wave_height", key), 2),
            "swell_direction": om.series_at(primary, "swell_wave_direction", key),
            "swell_period": rnd(om.series_at(primary, "swell_wave_period", key), 1),
            "source": point["id"],
            "source_distance_nm": round(dist, 1),
        }
        # Cross-check total wave height against ECMWF WAM where available.
        wam = om.series_at(point["models"].get("ecmwf_wam025"), "wave_height", key)
        if wam is not None:
            best["wave_height_wam"] = rnd(wam, 2)
            best["wave_agreement"] = s.model_agreement([wave, wam])
        break
    return best or {}


# --- passage planning -------------------------------------------------------

def sample_conditions(atmo: dict, marine: dict, point_id: str,
                      date: dt.date, hour: int) -> dict:
    """Everything we know about one place at one hour."""
    point = atmo.get(point_id)
    if not point:
        return {}
    key = hour_key(date, hour)
    models = point["models"]

    wind, wind_agree = consensus(models, "wind_speed_10m", key, "mean")
    gust, _ = consensus(models, "wind_gusts_10m", key, "max")
    direction, _ = consensus(models, "wind_direction_10m", key, "circular")
    codes = [om.series_at(models.get(m["id"]), "weather_code", key)
             for m in om.ATMO_MODELS]

    sea = nearest_marine(marine, point["lat"], point["lon"], key)
    return {
        "time": key,
        "hour": hour,
        "wind_kt": rnd(wind),
        "gust_kt": rnd(gust),
        "wind_dir": None if direction is None else round(direction),
        "wind_dir_label": s.compass_point(direction),
        "agreement": wind_agree,
        "weather_codes": [c for c in codes if c is not None],
        "sea": sea,
    }


def plan_leg(leg: dict, moorings: dict, atmo: dict, marine: dict,
             horizon: set[str]) -> dict:
    a, b = moorings[leg["from"]], moorings[leg["to"]]
    bearing = s.initial_bearing(a["lat"], a["lon"], b["lat"], b["lon"])
    computed_nm = s.distance_nm(a["lat"], a["lon"], b["lat"], b["lon"])
    stated_nm = leg["stated_nm"]
    duration = s.hours_for_distance(stated_nm)
    date = effective(leg["date"])

    out = {
        "id": leg["id"],
        "label": leg["label"],
        "date": leg["date"],
        "from": leg["from"], "to": leg["to"],
        "from_name": a["name"], "to_name": b["name"],
        "from_lat": a["lat"], "from_lon": a["lon"],
        "to_lat": b["lat"], "to_lon": b["lon"],
        "midpoint": leg["midpoint"],
        "optional": leg.get("optional", False),
        "bearing": round(bearing),
        "bearing_label": s.compass_point(bearing),
        "stated_nm": stated_nm,
        "computed_nm": round(computed_nm, 1),
        "duration_hours": round(duration, 2),
        "duration_label": leg["stated_time"],
        "note": leg.get("note", ""),
        "arrive_by": leg.get("arrive_by"),
        "windows": [],
    }

    # Is this leg's date inside the published forecast at all?
    if not any(k.startswith(date.isoformat()) for k in horizon):
        days_out = (date - dt.datetime.now(TZ).date()).days
        out["status"] = "beyond_horizon"
        out["available_in_days"] = max(0, days_out - 5)
        out["message"] = (
            f"{fmt_date(date)} is still beyond the forecast horizon. "
            f"Wind and sea for this passage appear about "
            f"{max(0, days_out - 5)} day(s) from now."
        ) if days_out > 5 else "Forecast for this passage is arriving now."
        return out

    out["status"] = "forecast"
    mid_id = f"{leg['id']}__mid"

    for depart in DEPARTURE_HOURS:
        arr_date, arr_hour = shift(date, depart, duration)
        mid_date, mid_hour = shift(date, depart, duration / 2)

        start = sample_conditions(atmo, marine, leg["from"], date, depart)
        middle = sample_conditions(atmo, marine, mid_id, mid_date, mid_hour)
        end = sample_conditions(atmo, marine, leg["to"], arr_date, arr_hour)
        legs_samples = [x for x in (start, middle, end) if x]
        if not legs_samples:
            continue

        winds = [x["wind_kt"] for x in legs_samples if x.get("wind_kt") is not None]
        gusts = [x["gust_kt"] for x in legs_samples if x.get("gust_kt") is not None]
        waves = [x["sea"].get("wave_height") for x in legs_samples
                 if x.get("sea", {}).get("wave_height") is not None]
        dirs = [x["wind_dir"] for x in legs_samples if x.get("wind_dir") is not None]
        swell_dirs = [x["sea"].get("swell_direction") for x in legs_samples
                      if x.get("sea", {}).get("swell_direction") is not None]
        codes = [c for x in legs_samples for c in x.get("weather_codes", [])]

        mean_dir = s.circular_mean(dirs)
        twa = s.true_wind_angle(bearing, mean_dir) if mean_dir is not None else None

        verdict = s.leg_verdict(
            wind_kt=max(winds) if winds else None,
            gust_kt=max(gusts) if gusts else None,
            wave_m=max(waves) if waves else None,
            twa=twa,
            wind_dir=mean_dir,
            swell_dir=s.circular_mean(swell_dirs),
            weather_codes=codes,
        )

        out["windows"].append({
            "depart": f"{depart:02d}:00",
            "depart_hour": depart,
            "arrive": f"{arr_hour:02d}:00",
            "arrive_next_day": arr_date != date,
            "start": start, "middle": middle, "end": end,
            "max_wind_kt": rnd(max(winds)) if winds else None,
            "max_gust_kt": rnd(max(gusts)) if gusts else None,
            "max_wave_m": rnd(max(waves), 2) if waves else None,
            "wind_dir": None if mean_dir is None else round(mean_dir),
            "wind_dir_label": s.compass_point(mean_dir),
            "twa": None if twa is None else round(twa),
            "point_of_sail": s.point_of_sail(twa) if twa is not None else "-",
            "beaufort": s.beaufort(max(winds) if winds else None),
            "reefing": s.reef_guidance(max(winds) if winds else None),
            "verdict": verdict["verdict"],
            "reasons": verdict["reasons"],
        })

    # The recommended window is the earliest one with the best verdict - an
    # early start leaves daylight in hand if anything goes wrong.
    rank = {"go": 0, "caution": 1, "no-go": 2, "unknown": 3}
    usable = [w for w in out["windows"] if w["verdict"] != "unknown"]
    if usable:
        best = min(usable, key=lambda w: (rank[w["verdict"]], w["depart_hour"]))
        out["recommended_window"] = best["depart"]
        out["verdict"] = best["verdict"]
        deteriorates = [w for w in usable
                        if w["depart_hour"] > best["depart_hour"]
                        and rank[w["verdict"]] > rank[best["verdict"]]]
        if deteriorates:
            out["deteriorates_after"] = deteriorates[0]["depart"]
    else:
        out["verdict"] = "unknown"

    # Honest check on our own inputs: if the computed rhumb distance is wildly
    # off the itinerary's figure, the coordinates are probably wrong.
    if abs(computed_nm - stated_nm) / stated_nm > 0.35:
        out["distance_warning"] = (
            f"Computed {computed_nm:.1f} nm vs itinerary {stated_nm} nm - "
            "check the waypoint coordinates.")
    return out


# --- berths -----------------------------------------------------------------

def plan_berths(day: dict, moorings: dict, atmo: dict, marine: dict,
                horizon: set[str]) -> dict | None:
    options = day.get("mooring_options") or []
    if not options:
        return None
    date = effective(day["date"])
    out = {"date": day["date"], "forecast_date": date.isoformat(), "port": day["port"], "day": day["day"],
           "optional": day.get("optional", False), "options": []}

    if not any(k.startswith(date.isoformat()) for k in horizon):
        out["status"] = "beyond_horizon"
        out["options"] = [{"id": o, "name": moorings[o]["name"],
                           "island": moorings[o]["island"],
                           "exposed_sector": moorings[o]["exposed_sector"],
                           "shelter_note": moorings[o]["shelter_note"],
                           "no_anchoring": moorings[o].get("no_anchoring", False),
                           "verified": moorings[o].get("verified", False),
                           "lat": moorings[o]["lat"], "lon": moorings[o]["lon"]}
                          for o in options]
        return out

    out["status"] = "forecast"
    for oid in options:
        m = moorings[oid]
        # Score the whole night and keep the worst hour - a berth that is fine
        # at nine and untenable at three in the morning is not a good berth.
        worst = None
        for hour in OVERNIGHT_HOURS:
            d = date if hour >= 12 else date + dt.timedelta(days=1)
            sample = sample_conditions(atmo, marine, oid, d, hour)
            if not sample:
                continue
            sea = sample.get("sea", {})
            score = s.shelter_score(
                m["exposed_sector"],
                wind_dir=sample.get("wind_dir"), wind_kt=sample.get("wind_kt"),
                swell_dir=sea.get("swell_direction"), swell_m=sea.get("swell_height"),
            )
            entry = {**score, "at": sample["time"], "wind_kt": sample.get("wind_kt"),
                     "gust_kt": sample.get("gust_kt"),
                     "wind_dir": sample.get("wind_dir"),
                     "wind_dir_label": sample.get("wind_dir_label"),
                     "swell_m": sea.get("swell_height"),
                     "swell_dir": sea.get("swell_direction"),
                     "swell_dir_label": s.compass_point(sea.get("swell_direction"))}
            if worst is None or entry["score"] < worst["score"]:
                worst = entry

        out["options"].append({
            "id": oid, "name": m["name"], "island": m["island"],
            "type": m["type"], "lat": m["lat"], "lon": m["lon"],
            "exposed_sector": m["exposed_sector"],
            "shelter_note": m["shelter_note"],
            "no_anchoring": m.get("no_anchoring", False),
            "verified": m.get("verified", False),
            **(worst or {"score": None, "verdict": "unknown",
                         "reason": "No forecast data for this night"}),
        })

    scored = [o for o in out["options"] if o.get("score") is not None]
    if scored:
        best = max(scored, key=lambda o: o["score"])
        out["recommended"] = best["id"]
        out["recommended_name"] = best["name"]
        spread = best["score"] - min(o["score"] for o in scored)
        out["choice_matters"] = spread >= 0.15
    return out


# --- chart payload ----------------------------------------------------------

def chart_series(atmo: dict, marine: dict) -> dict:
    """Trimmed hourly arrays for the charts.

    Rounded and capped at CHART_HOURS so the published JSON stays small enough
    to load on a phone in a marina.
    """
    out = {}
    for pid, point in atmo.items():
        if "__mid" in pid:
            continue
        ref = None
        for m in om.ATMO_MODELS:
            h = point["models"].get(m["id"])
            if h and "error" not in h and h.get("time"):
                ref = h
                break
        if not ref:
            continue
        times = ref["time"][:CHART_HOURS]
        entry = {"name": point["name"], "lat": point["lat"], "lon": point["lon"],
                 "time": times, "models": {}}
        for m in om.ATMO_MODELS:
            h = point["models"].get(m["id"])
            if not h or "error" in h:
                continue
            series = {}
            for var in CHART_VARS:
                vals = h.get(var) or []
                lookup = dict(zip(h["time"], vals))
                digits = 0 if var == "wind_direction_10m" else 1
                series[var] = [rnd(lookup.get(t), digits) for t in times]
            entry["models"][m["id"]] = series

        primary = None
        for m in om.ATMO_MODELS:
            h = point["models"].get(m["id"])
            if h and "error" not in h:
                primary = h
                break
        if primary:
            entry["conditions"] = {}
            for var in CONDITION_VARS:
                vals = primary.get(var) or []
                lookup = dict(zip(primary["time"], vals))
                entry["conditions"][var] = [rnd(lookup.get(t), 1) for t in times]

        sea = nearest_marine(marine, point["lat"], point["lon"], times[0])
        if sea.get("source"):
            src = marine[sea["source"]]["models"].get("meteofrance_wave") or {}
            lookup_t = src.get("time") or []
            entry["sea"] = {"source": sea["source"], "series": {}}
            for var in MARINE_VARS:
                vals = src.get(var) or []
                lookup = dict(zip(lookup_t, vals))
                digits = 0 if "direction" in var else 2
                entry["sea"]["series"][var] = [rnd(lookup.get(t), digits) for t in times]
        out[pid] = entry
    return out


# --- main -------------------------------------------------------------------

def build_rehearsal(legs, itinerary, moorings, atmo, marine, horizon) -> dict:
    """Run the real legs and berths against live weather, dated to now.

    Until the trip dates come inside the forecast horizon the passage planner
    has nothing to show, so there is no way to tell whether the analysis is
    working. This re-dates each leg into the current window and runs exactly
    the same code, which means every pre-trip day exercises the machinery the
    fleet will depend on, against real numbers.

    It is a dry run of the analysis, not a forecast for the trip, and the page
    says so.
    """
    today = dt.datetime.now(TZ).date()
    horizon_days = sorted({h[:10] for h in horizon})
    if not horizon_days:
        return {"available": False}

    out_legs, out_berths = [], []
    # Leg 1 tomorrow, leg 2 the day after, and so on, as far as the models reach.
    for offset, leg in enumerate(legs, start=1):
        target = today + dt.timedelta(days=offset)
        if target.isoformat() not in horizon_days:
            break
        shifted = dict(leg, date=target.isoformat())
        planned = plan_leg(shifted, moorings, atmo, marine, horizon)
        if planned.get("status") != "forecast":
            continue
        planned["real_date"] = leg["date"]
        out_legs.append(planned)

    for offset, day in enumerate(itinerary["days"], start=0):
        target = today + dt.timedelta(days=offset)
        if target.isoformat() not in horizon_days:
            break
        shifted = dict(day, date=target.isoformat())
        berth = plan_berths(shifted, moorings, atmo, marine, horizon)
        if berth and berth.get("status") == "forecast":
            berth["real_date"] = day["date"]
            out_berths.append(berth)

    return {
        "available": bool(out_legs or out_berths),
        "note": "A dry run: the real legs and berths scored against the next few "
                "days' live weather, so the analysis can be checked before the "
                "trip dates come into range. These are NOT forecasts for the trip.",
        "legs": out_legs,
        "berths": out_berths[:8],
    }


def build(no_briefing: bool = False) -> dict:
    global DATE_SHIFT
    itinerary = load("itinerary.json")
    waypoints = load("waypoints.json")
    moorings = waypoints["moorings"]
    legs = waypoints["legs"]

    atmo_points = [{"id": k, "name": v["name"], "lat": v["lat"], "lon": v["lon"]}
                   for k, v in moorings.items()]
    atmo_points += [{"id": f"{l['id']}__mid", "name": f"{l['label']} (midpoint)",
                     **l["midpoint"]} for l in legs]
    marine_points = [{"id": l["id"], "name": l["label"], **l["wave_point"]}
                     for l in legs]
    marine_points += [{"id": f"{k}__sea", "name": v["name"],
                       "lat": v["lat"], "lon": v["lon"]}
                      for k, v in moorings.items()]

    runs = om.fetch_model_runs(om.ATMO_MODELS + om.WAVE_MODELS)
    atmo = om.fetch_atmosphere(atmo_points, forecast_days=7)
    marine = om.fetch_marine(marine_points, forecast_days=7)

    if not any(
        h.get("time") for p in atmo.values() for h in p["models"].values()
        if isinstance(h, dict) and "error" not in h
    ):
        raise om.OpenMeteoError("no atmospheric data returned for any point")

    horizon: set[str] = set()
    for point in atmo.values():
        for h in point["models"].values():
            if isinstance(h, dict) and "error" not in h:
                horizon.update(h.get("time") or [])

    now = dt.datetime.now(TZ)
    today = now.date()
    if today < TRIP_START:
        phase, day_index = "pre-trip", None
    elif today > TRIP_END:
        phase, day_index = "post-trip", None
    else:
        phase, day_index = "underway", (today - TRIP_START).days + 1

    planned = [plan_leg(l, moorings, atmo, marine, horizon) for l in legs]
    berths = [b for b in (plan_berths(d, moorings, atmo, marine, horizon)
                          for d in itinerary["days"]) if b]

    doc = {
        "generated_at": now.isoformat(),
        "generated_at_utc": now.astimezone(dt.timezone.utc).isoformat(),
        "timezone": "Europe/Rome",
        "phase": phase,
        "trip_day": day_index,
        "days_to_departure": (TRIP_START - today).days,
        "stale": False,
        "simulated": bool(DATE_SHIFT),
        "simulated_shift_days": DATE_SHIFT.days,
        "models": runs,
        "legs": planned,
        "berths": berths,
        "series": chart_series(atmo, marine),
        "rehearsal": build_rehearsal(legs, itinerary, moorings, atmo, marine, horizon),
        "horizon_end": max(horizon) if horizon else None,
        "briefing": None,
    }

    try:
        import verification
        doc["verification"] = verification.build(doc, moorings)
    except Exception as e:                     # never block the numbers
        doc["verification"] = {"available": False, "reason": f"{type(e).__name__}: {e}"}

    if not no_briefing:
        try:
            import briefing
            doc["briefing"] = briefing.generate(doc, itinerary, waypoints)
        except Exception as e:  # never let the AI step break the numbers
            doc["briefing"] = None
            doc["briefing_error"] = f"{type(e).__name__}: {e}"
            print(f"  briefing skipped: {type(e).__name__}: {e}", file=sys.stderr)

    return doc


def write_atomic(doc: dict, path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def mark_previous_stale(reason: str) -> bool:
    """Flag the existing file rather than publishing nothing."""
    if not OUT.exists():
        return False
    try:
        doc = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return False
    doc["stale"] = True
    doc["stale_reason"] = reason
    doc["stale_checked_at"] = dt.datetime.now(TZ).isoformat()
    write_atomic(doc, OUT)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="write to a temp file instead of data/weather.json")
    ap.add_argument("--no-briefing", action="store_true",
                    help="skip the Claude API call")
    ap.add_argument("--simulate", action="store_true",
                    help="shift trip dates into the live forecast window so the "
                         "passage planner can be previewed before Oct 3")
    args = ap.parse_args()

    global DATE_SHIFT
    if args.simulate:
        DATE_SHIFT = (dt.datetime.now(TZ).date() + dt.timedelta(days=1)) - TRIP_START
        print(f"SIMULATE: shifting itinerary dates by {DATE_SHIFT.days} days")

    try:
        doc = build(no_briefing=args.no_briefing)
    except Exception as e:
        traceback.print_exc()
        reason = f"{type(e).__name__}: {e}"
        if mark_previous_stale(reason):
            print(f"\nFetch failed. Previous weather.json kept and flagged stale.",
                  file=sys.stderr)
            return 0  # publishing stale-but-labelled data beats publishing nothing
        print(f"\nFetch failed and there is no previous file to fall back on.",
              file=sys.stderr)
        return 1

    target = (pathlib.Path(tempfile.gettempdir()) / "weather-dryrun.json"
              if args.dry_run else OUT)
    write_atomic(doc, target)

    size_kb = target.stat().st_size / 1024
    print(f"wrote {target}  ({size_kb:.0f} KB)")
    if doc.get("simulated"):
        print("  *** SIMULATED DATES - preview only, not real trip weather ***")
    print(f"  phase: {doc['phase']}   forecast reaches: {doc['horizon_end']}")
    for m in doc["models"]:
        status = m.get("init_label", "UNAVAILABLE")
        print(f"  {m['short']:8} {status:14} age {m.get('age_hours', '-')}h")
    ready = [l for l in doc["legs"] if l["status"] == "forecast"]
    print(f"  legs with forecast: {len(ready)}/{len(doc['legs'])}")
    reh = doc.get("rehearsal") or {}
    if reh.get("available"):
        print(f"  rehearsal: {len(reh['legs'])} legs, {len(reh['berths'])} berths "
              f"scored against live weather")
    ver = doc.get("verification") or {}
    if ver.get("available"):
        print(f"  stability: {ver['points_compared']:,} points across "
              f"{ver['snapshots_compared']} earlier runs")
    else:
        print(f"  stability: {ver.get('reason','n/a')[:60]}")
    for l in ready:
        print(f"    {l['label'][:34]:34} {l.get('verdict','-'):8} "
              f"depart {l.get('recommended_window','-')}")
    if doc.get("briefing"):
        print(f"  briefing: {doc['briefing'].get('headline', '')[:70]}")
    elif doc.get("briefing_error"):
        print(f"  briefing: none ({doc['briefing_error'][:60]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
