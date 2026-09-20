"""Open-Meteo client for the ORYC Aeolian flotilla.

Everything here is keyless and free for non-commercial use. Three endpoints:

  * /v1/forecast            atmosphere, multi-model, multi-coordinate
  * marine-api /v1/marine   waves, swell, period, SST
  * /data/<model>/static/meta.json   model run initialisation times

The captain's briefing prompt asks explicitly for model initialisation times,
so those are fetched and surfaced rather than left implicit.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import requests

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
META_URL = "{host}/data/{model}/static/meta.json"
FORECAST_HOST = "https://api.open-meteo.com"
MARINE_HOST = "https://marine-api.open-meteo.com"

TIMEZONE = "Europe/Rome"
TIMEOUT = 45

# Atmospheric models, in the order we prefer to trust them.
ATMO_MODELS = [
    {
        "id": "ecmwf_ifs025",
        "label": "ECMWF IFS 0.25°",
        "short": "IFS",
        "resolution": "~25 km",
        "provides_gusts": True,
        "note": "ECMWF's operational physics model, open-data release. Its gust "
                "field is a maximum over the output interval, not an instantaneous "
                "value, so gust factors look large in light air.",
    },
    {
        "id": "ecmwf_aifs025_single",
        "label": "ECMWF AIFS",
        "short": "AIFS",
        "resolution": "~28 km",
        "provides_gusts": False,
        "note": "ECMWF's machine-learning model - a genuinely independent opinion. "
                "Publishes no gust field, so gusts come from IFS and ICON-2i only.",
    },
    {
        "id": "italia_meteo_arpae_icon_2i",
        "label": "ItaliaMeteo ICON-2i",
        "short": "ICON-2i",
        "resolution": "2 km",
        "provides_gusts": True,
        "note": "ItaliaMeteo / ARPAE high-resolution model for Italy - the finest "
                "grid available here. Runs only ~60-72 h ahead and updates every "
                "12 h, so it drops out of the longer-range view.",
    },
]

# MFWAM is the primary wave model: it is the only one on Open-Meteo that
# decomposes the sea into wind wave and swell, which the captain's briefing
# prompt asks for by name. ECMWF WAM returns total wave height only and is
# carried as a second opinion on that one figure.
WAVE_MODELS = [
    {
        "id": "meteofrance_wave",
        "label": "Météo-France MFWAM",
        "short": "MFWAM",
        "resolution": "~8 km",
        "host": MARINE_HOST,
        "primary": True,
        "note": "Full sea-state decomposition - total wave, wind wave and swell "
                "with heights, directions and periods.",
    },
    {
        "id": "ecmwf_wam025",
        "label": "ECMWF WAM 0.25°",
        "short": "WAM",
        "resolution": "~25 km",
        "host": MARINE_HOST,
        "primary": False,
        "note": "Total significant wave height only - used to cross-check MFWAM.",
    },
]

HOURLY_ATMO = [
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "temperature_2m", "apparent_temperature",
    "precipitation", "precipitation_probability", "weather_code",
    "cloud_cover", "pressure_msl", "visibility",
]

# Sea surface temperature is not served for the Tyrrhenian by either wave
# model, so it is not requested - asking for it only yields a null column.
HOURLY_MARINE = [
    "wave_height", "wave_direction", "wave_period",
    "wind_wave_height", "wind_wave_direction", "wind_wave_period",
    "swell_wave_height", "swell_wave_direction", "swell_wave_period",
]


class OpenMeteoError(RuntimeError):
    pass


def _get(url: str, params: dict[str, Any] | None = None) -> Any:
    try:
        r = requests.get(url, params=params, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise OpenMeteoError(f"request to {url} failed: {e}") from e
    if r.status_code != 200:
        raise OpenMeteoError(f"{url} returned HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


# --- Model metadata ---------------------------------------------------------

def fetch_model_runs(models: list[dict]) -> list[dict]:
    """Initialisation time and data age for each model.

    A model whose meta.json is unreachable is still reported, flagged, rather
    than dropped - a missing init time is information the skipper wants.
    """
    now = dt.datetime.now(dt.timezone.utc)
    out = []
    for m in models:
        entry = dict(m)
        try:
            host = m.get("host", FORECAST_HOST)
            meta = _get(META_URL.format(host=host, model=m["id"]))
            init = meta.get("last_run_initialisation_time")
            avail = meta.get("last_run_availability_time")
            if init:
                init_dt = dt.datetime.fromtimestamp(init, dt.timezone.utc)
                entry["init"] = init_dt.isoformat()
                entry["init_label"] = init_dt.strftime("%d %b %HZ")
                entry["age_hours"] = round((now - init_dt).total_seconds() / 3600.0, 1)
            if avail:
                entry["available"] = dt.datetime.fromtimestamp(
                    avail, dt.timezone.utc).isoformat()
            interval = meta.get("update_interval_seconds")
            if interval:
                entry["update_interval_hours"] = round(interval / 3600.0, 1)
            entry["ok"] = bool(init)
        except OpenMeteoError as e:
            entry["ok"] = False
            entry["error"] = str(e)
        out.append(entry)
    return out


# --- Forecasts --------------------------------------------------------------

def _normalise(payload: Any) -> list[dict]:
    """Open-Meteo returns a bare object for one coordinate, a list for many."""
    return payload if isinstance(payload, list) else [payload]


def fetch_atmosphere(points: list[dict], forecast_days: int = 7) -> dict[str, dict]:
    """Multi-model wind/weather for every point, in one request per model.

    Keyed by point id. Each point holds `{model_id: {time: [...], var: [...]}}`.
    Models are requested separately rather than with a combined `models=` list
    so that one model being out of domain (ICON-2i is Italy-only) or briefly
    unavailable cannot take the whole fetch down with it.
    """
    if not points:
        return {}
    lats = ",".join(f"{p['lat']:.4f}" for p in points)
    lons = ",".join(f"{p['lon']:.4f}" for p in points)

    result: dict[str, dict] = {
        p["id"]: {"id": p["id"], "name": p.get("name", p["id"]),
                  "lat": p["lat"], "lon": p["lon"], "models": {}}
        for p in points
    }

    for model in ATMO_MODELS:
        params = {
            "latitude": lats, "longitude": lons,
            "hourly": ",".join(HOURLY_ATMO),
            "models": model["id"],
            "wind_speed_unit": "kn",
            "timezone": TIMEZONE,
            "forecast_days": forecast_days,
        }
        try:
            blocks = _normalise(_get(FORECAST_URL, params))
        except OpenMeteoError as e:
            for pid in result:
                result[pid]["models"][model["id"]] = {"error": str(e)}
            continue

        for point, block in zip(points, blocks):
            hourly = block.get("hourly") or {}
            if not hourly.get("time"):
                result[point["id"]]["models"][model["id"]] = {
                    "error": "no hourly data returned (likely outside model domain)"}
                continue
            result[point["id"]]["models"][model["id"]] = hourly

    return result


def fetch_marine(points: list[dict], forecast_days: int = 7) -> dict[str, dict]:
    """Wave, swell and period for every offshore sample point."""
    if not points:
        return {}
    lats = ",".join(f"{p['lat']:.4f}" for p in points)
    lons = ",".join(f"{p['lon']:.4f}" for p in points)

    result: dict[str, dict] = {
        p["id"]: {"id": p["id"], "name": p.get("name", p["id"]),
                  "lat": p["lat"], "lon": p["lon"], "models": {}}
        for p in points
    }

    for model in WAVE_MODELS:
        params = {
            "latitude": lats, "longitude": lons,
            "hourly": ",".join(HOURLY_MARINE),
            "models": model["id"],
            "length_unit": "metric",
            "timezone": TIMEZONE,
            "forecast_days": forecast_days,
        }
        try:
            blocks = _normalise(_get(MARINE_URL, params))
        except OpenMeteoError as e:
            for pid in result:
                result[pid]["models"][model["id"]] = {"error": str(e)}
            continue

        for point, block in zip(points, blocks):
            hourly = block.get("hourly") or {}
            if not hourly.get("time"):
                result[point["id"]]["models"][model["id"]] = {
                    "error": "no hourly wave data at this point"}
                continue
            result[point["id"]]["models"][model["id"]] = hourly

    return result


# --- Lookup helpers ---------------------------------------------------------

def series_at(hourly: dict | None, variable: str, iso_hour: str) -> float | None:
    """Value of `variable` at `iso_hour`, matched on timestamp, never on index.

    ICON-2i's arrays are far shorter than ECMWF's, so positional lookups across
    models would silently read the wrong hour.
    """
    if not hourly or "error" in hourly:
        return None
    times = hourly.get("time") or []
    values = hourly.get(variable) or []
    try:
        i = times.index(iso_hour)
    except ValueError:
        return None
    if i >= len(values):
        return None
    return values[i]


def available_hours(hourly: dict | None) -> list[str]:
    if not hourly or "error" in hourly:
        return []
    return list(hourly.get("time") or [])
