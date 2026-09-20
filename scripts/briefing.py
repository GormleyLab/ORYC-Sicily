"""Claude-written skipper's briefing for the ORYC Aeolian flotilla.

This mirrors the evening briefing a captain produced by hand with Gemini
(see weather-prompt.txt), with one important difference: Claude is handed the
actual multi-model numbers this pipeline already fetched rather than being
asked to go and find them. It writes prose about data it can see, so there is
nothing for it to invent.

The call is structured-output, so the result is validated JSON the page renders
as real HTML elements - no markdown parser shipped to the browser and no
injection surface.

Requires ANTHROPIC_API_KEY. If the key is missing or the call fails, the caller
publishes the numbers with briefing=None; the deterministic content must never
depend on this step.
"""

from __future__ import annotations

import datetime as dt
import json
import os

import sailing as s

MODEL = "claude-opus-5"

BRIEFING_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "string",
            "description": "One sentence, under 110 characters, that a skipper "
                           "could read aloud at a dock briefing.",
        },
        "synopsis": {
            "type": "string",
            "description": "2-4 sentences on the synoptic picture: the pressure "
                           "pattern, where the wind is coming from and how it is "
                           "expected to evolve over the next 24-48 hours.",
        },
        "overnight_anchorage": {
            "type": "string",
            "description": "2-4 sentences on conditions at tonight's berth, naming "
                           "the recommended mooring and why, and what would make "
                           "the fleet want to move.",
        },
        "tomorrow_morning": {
            "type": "string",
            "description": "2-4 sentences on the next morning's outlook and the "
                           "departure window for the next leg.",
        },
        "passage_notes": {
            "type": "array",
            "description": "One short note per upcoming leg that has a forecast.",
            "items": {
                "type": "object",
                "properties": {
                    "leg": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["leg", "note"],
                "additionalProperties": False,
            },
        },
        "cautions": {
            "type": "array",
            "description": "Specific things to watch. Empty if there is genuinely "
                           "nothing of concern - do not invent a caution.",
            "items": {"type": "string"},
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "moderate", "low"],
            "description": "Forecast confidence, driven by how well the models "
                           "agree and how far out the period is.",
        },
        "confidence_note": {
            "type": "string",
            "description": "One sentence explaining the confidence call, citing "
                           "model agreement or disagreement.",
        },
    },
    "required": ["headline", "synopsis", "overnight_anchorage", "tomorrow_morning",
                 "passage_notes", "cautions", "confidence", "confidence_note"],
    "additionalProperties": False,
}

SYSTEM = """You are writing the evening marine weather briefing for a flotilla of \
45ft cruising catamarans in the Aeolian Islands, north of Sicily (around 38.6 N, \
15 E), for Ocean Reef Yacht Club.

Ground rules, in order of importance:

1. The JSON payload in the user message is your ONLY source of weather \
information. Never state a number that is not in it. If something is not in the \
payload, say you do not have it rather than estimating.
2. Name the model and its initialisation time when you cite a figure, the way a \
professional briefing does - for example "ECMWF IFS, 12Z run".
3. Where the models disagree, say so plainly and give the range. Disagreement is \
information the skippers need, not something to smooth over.
4. Wind speeds in knots, wave and swell heights in metres, directions as compass \
points. Times are local (CEST).
5. Be concrete and brief. These are experienced sailors reading on a phone in a \
cockpit. No filler, no weather-presenter enthusiasm, no restating the question.
6. This is a planning aid, not an official forecast. Never tell the fleet a \
passage is definitively safe. The computed go/caution/no-go verdicts in the \
payload are conservative thresholds, not decisions - the skipper decides.
7. If the payload shows conditions are simply benign, say so in one line. Do not \
manufacture drama or a caution to seem useful."""


def _trim_leg(leg: dict) -> dict:
    """Just enough of a leg for the briefing - not the whole window table."""
    out = {
        "leg": leg["label"],
        "date": leg["date"],
        "distance_nm": leg["stated_nm"],
        "bearing": f"{leg['bearing']}°T ({leg['bearing_label']})",
        "status": leg["status"],
    }
    if leg["status"] != "forecast":
        out["note"] = leg.get("message", "Beyond the forecast horizon")
        return out
    out["verdict"] = leg.get("verdict")
    out["recommended_departure"] = leg.get("recommended_window")
    out["deteriorates_after"] = leg.get("deteriorates_after")
    out["windows"] = [
        {
            "depart": w["depart"], "arrive": w["arrive"],
            "wind_kt": w["max_wind_kt"], "gust_kt": w["max_gust_kt"],
            "wind_dir": w["wind_dir_label"], "wave_m": w["max_wave_m"],
            "twa": w["twa"], "point_of_sail": w["point_of_sail"],
            "beaufort": w["beaufort"]["force"], "verdict": w["verdict"],
            "reasons": w["reasons"],
        }
        for w in leg["windows"][::2]  # every other hour keeps the payload lean
    ]
    return out


def _trim_berth(b: dict) -> dict:
    out = {"date": b["date"], "port": b["port"], "status": b["status"],
           "recommended": b.get("recommended_name"),
           "choice_matters": b.get("choice_matters")}
    if b["status"] != "forecast":
        return out
    out["options"] = [
        {"name": o["name"], "verdict": o["verdict"], "score": o["score"],
         "wind_kt": o.get("wind_kt"), "gust_kt": o.get("gust_kt"),
         "wind_dir": o.get("wind_dir_label"),
         "swell_m": o.get("swell_m"), "swell_dir": o.get("swell_dir_label"),
         "reason": o["reason"], "exposed_sector": o["exposed_sector"],
         "no_anchoring": o.get("no_anchoring", False)}
        for o in b["options"]
    ]
    return out


def _conditions(doc: dict, waypoints: dict, hours: int = 72, step: int = 6) -> list:
    """Current and near-term conditions per island, from the hourly series.

    Without this the pre-trip payload carries nothing but model metadata, and
    the briefing correctly refuses to describe a synoptic picture it cannot
    see. The series data is live every day, long before any trip date comes
    inside the forecast horizon.
    """
    series = doc.get("series") or {}
    moorings = (waypoints or {}).get("moorings") or {}
    seen, out = set(), []

    for pid, point in series.items():
        m = moorings.get(pid)
        if not m:
            continue
        group = m.get("group") or m.get("island")
        if group in seen:
            continue
        seen.add(group)

        times = point.get("time") or []
        rows = []
        for i in range(0, min(hours, len(times)), step):
            speeds, dirs, gusts = [], [], []
            for mdl in (point.get("models") or {}).values():
                v = (mdl.get("wind_speed_10m") or [None] * len(times))[i]
                d = (mdl.get("wind_direction_10m") or [None] * len(times))[i]
                g = (mdl.get("wind_gusts_10m") or [None] * len(times))[i]
                if v is not None: speeds.append(v)
                if d is not None: dirs.append(d)
                if g is not None: gusts.append(g)
            if not speeds:
                continue
            row = {
                "time": times[i],
                "wind_kt": round(sum(speeds) / len(speeds), 1),
                "wind_dir": None if not dirs else round(s.circular_mean(dirs)),
            }
            if len(speeds) > 1:
                spread = round(max(speeds) - min(speeds), 1)
                if spread > 6:
                    row["models_range_kt"] = [round(min(speeds), 1), round(max(speeds), 1)]
            if gusts:
                row["gust_kt"] = round(max(gusts), 1)
            sea = point.get("sea") or {}
            ser = sea.get("series") or {}
            for key, label in (("wave_height", "wave_m"), ("swell_wave_height", "swell_m")):
                vals = ser.get(key) or []
                if i < len(vals) and vals[i] is not None:
                    row[label] = vals[i]
            rows.append(row)

        if rows:
            out.append({"island": group, "hourly": rows})
    return out


def build_payload(doc: dict, itinerary: dict, waypoints: dict | None = None) -> dict:
    """The facts Claude is allowed to write about."""
    today = dt.date.fromisoformat(doc["generated_at"][:10])

    # Only near-term legs and berths - the briefing is about tonight and
    # tomorrow, not the whole week.
    def near(date_str: str, days: int = 3) -> bool:
        d = dt.date.fromisoformat(date_str)
        return 0 <= (d - today).days <= days or doc.get("simulated")

    legs = [_trim_leg(l) for l in doc["legs"]
            if l["status"] == "forecast" or near(l["date"], 5)]
    berths = [_trim_berth(b) for b in doc["berths"]
              if b["status"] == "forecast" or near(b["date"], 5)]

    return {
        "issued": doc["generated_at"],
        "timezone": doc["timezone"],
        "phase": doc["phase"],
        "days_to_departure": doc["days_to_departure"],
        "trip_day": doc.get("trip_day"),
        "simulated_dates": doc.get("simulated", False),
        "forecast_reaches": doc.get("horizon_end"),
        "models": [
            {"model": m["label"], "id": m["id"], "resolution": m["resolution"],
             "initialised": m.get("init_label"), "age_hours": m.get("age_hours"),
             "publishes_gusts": m.get("provides_gusts", True),
             "available": m.get("ok", False), "note": m.get("note")}
            for m in doc["models"]
        ],
        "legs": legs[:8],
        "berths": berths[:8],
        "current_conditions": _conditions(doc, waypoints),
        "current_conditions_note":
            "Consensus across every model with data at that hour, sampled every "
            "6 h. 'models_range_kt' appears only where the models disagree by "
            "more than 6 kt, and means exactly that - say so rather than "
            "quoting the mean as if it were certain.",
    }


def generate(doc: dict, itinerary: dict, waypoints: dict | None = None) -> dict | None:
    """Ask Claude for the briefing. Returns None if no API key is configured."""
    if not (os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    import anthropic

    payload = build_payload(doc, itinerary, waypoints)

    if doc["phase"] == "pre-trip" and not doc.get("simulated"):
        framing = (
            f"The flotilla departs in {doc['days_to_departure']} days. Most legs "
            "are still beyond the forecast horizon. Write a short pre-trip "
            "outlook: what the current pattern over the Aeolians looks like, "
            "what it would mean if it held, and be explicit that it is far too "
            "early for the trip dates themselves. Keep passage_notes brief."
        )
    else:
        framing = (
            "Write tonight's evening briefing for the fleet: the synoptic "
            "picture, overnight conditions at the berth, and the outlook and "
            "departure window for tomorrow's leg."
        )

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": BRIEFING_SCHEMA},
        },
        messages=[{
            "role": "user",
            "content": (
                f"{framing}\n\nHere is the complete forecast payload:\n\n"
                f"```json\n{json.dumps(payload, ensure_ascii=False, indent=1)}\n```"
            ),
        }],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError(f"model declined: {response.stop_details}")

    text = next(b.text for b in response.content if b.type == "text")
    result = json.loads(text)
    result["model"] = MODEL
    result["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    result["usage"] = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    return result
