"""Derived sailing intelligence for the ORYC Aeolian flotilla.

Pure functions only - no I/O, no network. Everything here is unit-tested in
test_sailing.py because a wrong bearing or a wrong shelter verdict is the most
consequential kind of bug in this project.

Conventions used throughout:
  * Directions are degrees TRUE, 0-360, and meteorological: a "wind direction"
    is the direction the wind blows FROM.
  * Wind speeds are knots. Wave heights are metres.
  * A "sector" is [from, to] clockwise in degrees true, and may wrap past 360.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

EARTH_RADIUS_NM = 3440.065

# Planning speed used by the itinerary for every leg.
PLANNING_SPEED_KT = 6.0

# --- Thresholds -------------------------------------------------------------
# Tuned for 45ft cruising catamarans. These are deliberately conservative
# defaults for a mixed-experience flotilla; the fleet captain should adjust
# them rather than treat them as authoritative.
WIND_GO_KT, WIND_CAUTION_KT = 18.0, 25.0
GUST_GO_KT, GUST_CAUTION_KT = 24.0, 32.0
WAVE_GO_M, WAVE_CAUTION_M = 1.25, 2.0

# ECMWF IFS open data is 3-hourly at range and its gust field is a maximum over
# the interval, not an instantaneous value. Against a light mean wind that
# produces gust factors of 5x or more, which are a model artefact rather than a
# squall. Treating those as a real caution trains skippers to ignore the amber
# chip, so they are reported as a footnote instead.
GUST_SPIKE_RATIO = 2.5
GUST_SPIKE_MAX_MEAN_KT = 10.0


def is_gust_spike(wind_kt, gust_kt) -> bool:
    """True when a high gust is an artefact of a light, unstable mean wind."""
    if wind_kt is None or gust_kt is None or wind_kt <= 0:
        return False
    return wind_kt < GUST_SPIKE_MAX_MEAN_KT and (gust_kt / wind_kt) > GUST_SPIKE_RATIO

# WMO weather codes for thunderstorms - any of these in a passage window is an
# automatic no-go regardless of how benign the wind looks.
THUNDERSTORM_CODES = {95, 96, 99}

COMPASS_16 = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


# --- Geometry ---------------------------------------------------------------

def initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle initial bearing from point 1 to point 2, degrees true."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_NM * math.asin(math.sqrt(a))


def angular_difference(a: float, b: float) -> float:
    """Smallest absolute angle between two bearings, 0-180."""
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def compass_point(deg: float | None) -> str:
    """16-point compass abbreviation, e.g. 293 -> 'WNW'."""
    if deg is None:
        return "-"
    return COMPASS_16[int((deg % 360.0) / 22.5 + 0.5) % 16]


def in_sector(bearing: float, sector: Sequence[float] | None) -> bool:
    """True if `bearing` falls inside the clockwise arc `sector` = [from, to]."""
    if not sector:
        return False
    start, end = sector[0] % 360.0, sector[1] % 360.0
    b = bearing % 360.0
    if start <= end:
        return start <= b <= end
    return b >= start or b <= end  # sector wraps through north


def _one_sector_proximity(bearing: float, sector: Sequence[float],
                          margin: float) -> float:
    if in_sector(bearing, sector):
        return 1.0
    gap = min(angular_difference(bearing, sector[0]),
              angular_difference(bearing, sector[1]))
    return max(0.0, 1.0 - gap / margin)


def sector_proximity(bearing: float, sector: Sequence | None,
                     margin: float = 30.0) -> float:
    """How exposed `bearing` is to `sector`, 1.0 inside, tapering to 0.0.

    A berth does not become safe the instant the wind clears the headland, so
    directions just outside the sector still carry partial exposure, fading
    linearly over `margin` degrees.

    `sector` may be a single [from, to] arc or a list of them. Several berths
    here are open to more than one arc - San Pietro on Panarea faces east AND
    has a gap to the north - and scoring only the widest arc would report the
    others as sheltered.
    """
    if not sector:
        return 0.0
    arcs = sector if isinstance(sector[0], (list, tuple)) else [sector]
    return max(_one_sector_proximity(bearing, a, margin) for a in arcs)


# --- Wind relative to the boat ---------------------------------------------

def true_wind_angle(course: float, wind_from: float) -> float:
    """Angle between the course sailed and the wind's origin, 0-180.

    0 means the wind is dead on the nose; 180 means dead astern.
    """
    return angular_difference(course, wind_from)


def point_of_sail(twa: float) -> str:
    if twa < 30:
        # Deliberately not called "no-go": that phrase is reserved for the
        # go/caution/no-go safety verdict, and showing both on one row read as
        # a contradiction.
        return "head to wind - motor"
    if twa < 50:
        return "close hauled"
    if twa < 80:
        return "close reach"
    if twa < 100:
        return "beam reach"
    if twa < 150:
        return "broad reach"
    return "run"


def is_upwind(twa: float) -> bool:
    return twa < 50


def beaufort(kt: float | None) -> dict:
    """Beaufort force and its sea description."""
    if kt is None:
        return {"force": None, "label": "-", "sea": "-"}
    table = [
        (0, 0, "Calm", "Sea like a mirror"),
        (1, 1, "Light air", "Ripples"),
        (2, 4, "Light breeze", "Small wavelets"),
        (3, 7, "Gentle breeze", "Large wavelets, scattered whitecaps"),
        (4, 11, "Moderate breeze", "Small waves, frequent whitecaps"),
        (5, 17, "Fresh breeze", "Moderate waves, many whitecaps"),
        (6, 22, "Strong breeze", "Large waves, some spray"),
        (7, 28, "Near gale", "Sea heaps up, foam streaks"),
        (8, 34, "Gale", "Moderately high waves, spindrift"),
        (9, 41, "Strong gale", "High waves, dense foam"),
        (10, 48, "Storm", "Very high waves, sea white"),
    ]
    force, label, sea = 0, "Calm", "Sea like a mirror"
    for f, floor, lab, s in table:
        if kt >= floor:
            force, label, sea = f, lab, s
    return {"force": force, "label": label, "sea": sea}


def reef_guidance(kt: float | None) -> str:
    """Sail plan suggestion for a 45ft cruising catamaran."""
    if kt is None:
        return "-"
    if kt < 10:
        return "Full main and genoa; consider the code zero"
    if kt < 18:
        return "Full main and genoa"
    if kt < 23:
        return "First reef"
    if kt < 28:
        return "Second reef, furl some genoa"
    if kt < 34:
        return "Third reef and staysail-sized headsail"
    return "Too much for a comfortable passage - stay in port"


# --- Verdicts ---------------------------------------------------------------

def _worst(*verdicts: str) -> str:
    order = {"go": 0, "caution": 1, "no-go": 2, "unknown": -1}
    known = [v for v in verdicts if v in order and v != "unknown"]
    if not known:
        return "unknown"
    return max(known, key=lambda v: order[v])


def leg_verdict(wind_kt: float | None, gust_kt: float | None,
                wave_m: float | None, twa: float | None = None,
                swell_dir: float | None = None, wind_dir: float | None = None,
                weather_codes: Iterable[int] = ()) -> dict:
    """Green / amber / red call for a passage, with the reasons that drove it."""
    reasons: list[str] = []
    verdict = "go"

    if wind_kt is None and gust_kt is None and wave_m is None:
        return {"verdict": "unknown", "reasons": ["No forecast data for this window"]}

    if wind_kt is not None:
        if wind_kt > WIND_CAUTION_KT:
            verdict = _worst(verdict, "no-go")
            reasons.append(f"Sustained wind {wind_kt:.0f} kt exceeds {WIND_CAUTION_KT:.0f} kt")
        elif wind_kt > WIND_GO_KT:
            verdict = _worst(verdict, "caution")
            reasons.append(f"Sustained wind {wind_kt:.0f} kt")

    spike = is_gust_spike(wind_kt, gust_kt)
    if gust_kt is not None and spike:
        reasons.append(
            f"Gusts to {gust_kt:.0f} kt against a {wind_kt:.0f} kt mean - this is an "
            "interval-maximum gust from a single model in a light wind, so it is "
            "reported but not treated as a caution")
    elif gust_kt is not None:
        if gust_kt > GUST_CAUTION_KT:
            verdict = _worst(verdict, "no-go")
            reasons.append(f"Gusts {gust_kt:.0f} kt exceed {GUST_CAUTION_KT:.0f} kt")
        elif gust_kt > GUST_GO_KT:
            verdict = _worst(verdict, "caution")
            reasons.append(f"Gusts {gust_kt:.0f} kt")

    if wave_m is not None:
        if wave_m > WAVE_CAUTION_M:
            verdict = _worst(verdict, "no-go")
            reasons.append(f"Significant wave {wave_m:.1f} m exceeds {WAVE_CAUTION_M:.1f} m")
        elif wave_m > WAVE_GO_M:
            verdict = _worst(verdict, "caution")
            reasons.append(f"Significant wave {wave_m:.1f} m")

    # Wind against swell stands the sea up short and steep - worth a flag even
    # when neither figure alone is alarming.
    if (swell_dir is not None and wind_dir is not None
            and angular_difference(swell_dir, wind_dir) > 90
            and (wind_kt or 0) > 12 and (wave_m or 0) > 0.75):
        verdict = _worst(verdict, "caution")
        reasons.append("Wind opposing swell - short, steep sea")

    codes = set(weather_codes)
    if codes & THUNDERSTORM_CODES:
        verdict = _worst(verdict, "no-go")
        reasons.append("Thunderstorms forecast in the passage window")

    if twa is not None and is_upwind(twa) and (wind_kt or 0) > WIND_GO_KT:
        reasons.append(f"Upwind leg (TWA {twa:.0f}°) - expect a slow, wet beat")

    if not reasons:
        reasons.append("Within comfortable limits for a 45ft cat")
    return {"verdict": verdict, "reasons": reasons}


def shelter_score(exposed_sector: Sequence[float] | None,
                  wind_dir: float | None, wind_kt: float | None,
                  swell_dir: float | None = None,
                  swell_m: float | None = None) -> dict:
    """Rank how sheltered a mooring will be overnight, 0.0 (untenable) to 1.0.

    An enclosed marina (`exposed_sector is None`) always scores 1.0. Otherwise
    wind and swell arriving from inside the exposure sector each subtract from
    the score in proportion to their strength.
    """
    if exposed_sector is None:
        return {
            "score": 1.0, "verdict": "sheltered",
            "reason": "Enclosed marina - all-round shelter",
            "wind_exposed": False, "swell_exposed": False,
        }

    wind_exposure = sector_proximity(wind_dir, exposed_sector) if wind_dir is not None else 0.0
    swell_exposure = sector_proximity(swell_dir, exposed_sector) if swell_dir is not None else 0.0

    wind_penalty = wind_exposure * min((wind_kt or 0.0) / 30.0, 1.0) * 0.55
    swell_penalty = swell_exposure * min((swell_m or 0.0) / 2.5, 1.0) * 0.45
    score = max(0.0, min(1.0, 1.0 - wind_penalty - swell_penalty))

    if score >= 0.80:
        verdict = "sheltered"
    elif score >= 0.55:
        verdict = "workable"
    elif score >= 0.30:
        verdict = "exposed"
    else:
        verdict = "untenable"

    arcs = (exposed_sector if isinstance(exposed_sector[0], (list, tuple))
            else [exposed_sector])
    bits = []
    if wind_exposure > 0.5 and (wind_kt or 0) >= 8:
        bits.append(f"{compass_point(wind_dir)} wind {wind_kt:.0f} kt blows straight in")
    if swell_exposure > 0.5 and (swell_m or 0) >= 0.5:
        bits.append(f"{swell_m:.1f} m swell from {compass_point(swell_dir)} wraps in")
    if not bits:
        sec = ", ".join(f"{a[0]:.0f}-{a[1]:.0f}°" for a in arcs)
        bits.append(f"Wind and swell stay clear of the exposed arc{'s' if len(arcs) > 1 else ''} ({sec})")

    return {
        "score": round(score, 3), "verdict": verdict, "reason": "; ".join(bits),
        "wind_exposed": wind_exposure > 0.5, "swell_exposed": swell_exposure > 0.5,
    }


# --- Model agreement --------------------------------------------------------

def model_agreement(values: Sequence[float | None]) -> dict:
    """Spread across models for one variable at one time.

    Reported as a confidence band rather than a single number, because "the
    models disagree" is itself the most useful thing a skipper can be told.
    """
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return {"n": len(vals), "mean": vals[0] if vals else None,
                "spread": None, "confidence": "single-model" if vals else "none"}
    mean = sum(vals) / len(vals)
    spread = max(vals) - min(vals)
    if spread <= 4:
        confidence = "high"
    elif spread <= 9:
        confidence = "moderate"
    else:
        confidence = "low"
    return {"n": len(vals), "mean": round(mean, 1), "min": round(min(vals), 1),
            "max": round(max(vals), 1), "spread": round(spread, 1),
            "confidence": confidence}


def circular_mean(directions: Sequence[float | None]) -> float | None:
    """Vector mean of compass directions - a plain average is wrong near 360."""
    dirs = [d for d in directions if d is not None]
    if not dirs:
        return None
    x = sum(math.cos(math.radians(d)) for d in dirs)
    y = sum(math.sin(math.radians(d)) for d in dirs)
    if abs(x) < 1e-9 and abs(y) < 1e-9:
        return None
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def hours_for_distance(nm: float, speed_kt: float = PLANNING_SPEED_KT) -> float:
    return nm / speed_kt
