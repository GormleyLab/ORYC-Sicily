"""How much does the forecast move as the hour approaches?

Every scheduled run commits data/weather.json, so git history holds a record
of what each model predicted for a given hour at each lead time. Comparing
those against the newest run shows how far a forecast typically shifts as it
firms up - which is the honest way to answer "how much should I trust the
three-day call for our departure?"

IMPORTANT about what this measures. There is no observation here. The
reference is the most recent run's value for the same hour, which is the
closest thing available to truth but is still a model. So this is forecast
*stability*, not verified accuracy: it shows how much the guidance changed,
not how wrong it was. A forecast can be perfectly stable and consistently
wrong. It is still the most useful confidence signal obtainable without a
weather station on the island, and it is labelled as such everywhere it is
shown.
"""

from __future__ import annotations

import json
import subprocess
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent

MAX_SNAPSHOTS = 24          # roughly three weeks of daily runs
WIND_VAR = "wind_speed_10m"
DIR_VAR = "wind_direction_10m"


def _git(args: list[str]) -> str:
    """Always run against the repo root: the updater is invoked from scripts/,
    where a relative pathspec like data/weather.json matches nothing."""
    return subprocess.run(["git", "-C", str(ROOT)] + args, capture_output=True,
                          text=True, encoding="utf-8", errors="replace").stdout


def snapshots(path: str = "data/weather.json") -> list[tuple[str, str]]:
    """(sha, iso date) for each committed version, newest first."""
    out = _git(["log", "--format=%H|%aI", "--", path]).strip().splitlines()
    rows = []
    for line in out[:MAX_SNAPSHOTS]:
        if "|" in line:
            sha, date = line.split("|", 1)
            rows.append((sha.strip(), date.strip()))
    return rows


def load(sha: str, path: str = "data/weather.json") -> dict | None:
    blob = _git(["show", f"{sha}:{path}"])
    if not blob.strip():
        return None
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def _angular_diff(a: float, b: float) -> float:
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def _series_value(doc: dict, loc: str, var: str, when: str):
    point = (doc.get("series") or {}).get(loc)
    if not point:
        return None
    times = point.get("time") or []
    try:
        i = times.index(when)
    except ValueError:
        return None
    vals = []
    for model in (point.get("models") or {}).values():
        arr = model.get(var) or []
        if i < len(arr) and arr[i] is not None:
            vals.append(arr[i])
    if not vals:
        return None
    return sum(vals) / len(vals)


def _inits(doc: dict) -> tuple:
    """The model initialisation times a run was built from."""
    return tuple(sorted((m.get("id"), m.get("init")) for m in (doc.get("models") or [])))


def build(current: dict, moorings: dict | None = None) -> dict:
    """Compare older runs against the current one, bucketed by lead time.

    Only runs built from *different* model initialisations are compared. Two
    runs an hour apart usually share the same 00Z/12Z cycle, so comparing them
    yields a near-zero shift that looks like strong agreement and actually
    means the same forecast was read twice. Reporting that as confidence would
    be worse than reporting nothing.
    """
    snaps = snapshots()
    if len(snaps) < 2:
        return {"available": False,
                "reason": "Needs at least two committed forecast runs; the "
                          "archive builds up one per day."}

    latest_sha = snaps[0][0]
    ref = current

    # Hours the newest run covers - only compare where both runs have a value.
    series = ref.get("series") or {}
    locs = [k for k in series if not moorings or k in moorings]
    if not locs:
        return {"available": False, "reason": "No comparable locations."}
    ref_times = set(series[locs[0]].get("time") or [])

    by_lead = defaultdict(lambda: {"wind_err": [], "dir_err": [], "runs": set()})
    compared = 0

    ref_inits = _inits(ref)
    skipped_same_cycle = 0

    for sha, date in snaps[1:]:
        old = load(sha)
        if not old:
            continue
        old_gen = old.get("generated_at", "")[:16]
        if not old_gen:
            continue
        if _inits(old) == ref_inits:
            skipped_same_cycle += 1
            continue

        for loc in locs:
            old_point = (old.get("series") or {}).get(loc)
            if not old_point:
                continue
            for when in (old_point.get("time") or []):
                if when not in ref_times or when <= old_gen:
                    continue          # only forecasts, not hindcast padding
                lead_h = (_hours_between(old_gen, when))
                if lead_h is None or lead_h > 120:
                    continue
                bucket = _bucket(lead_h)

                o_w = _series_value(old, loc, WIND_VAR, when)
                n_w = _series_value(ref, loc, WIND_VAR, when)
                if o_w is not None and n_w is not None:
                    by_lead[bucket]["wind_err"].append(abs(o_w - n_w))
                    by_lead[bucket]["runs"].add(sha[:8])
                    compared += 1

                o_d = _series_value(old, loc, DIR_VAR, when)
                n_d = _series_value(ref, loc, DIR_VAR, when)
                if o_d is not None and n_d is not None:
                    by_lead[bucket]["dir_err"].append(_angular_diff(o_d, n_d))

    if not compared:
        why = ("Every archived run so far was built from the same model cycle, "
               "so there is nothing to compare yet. Meaningful numbers appear "
               "once runs from different 00Z/12Z cycles accumulate - about a "
               "day.") if skipped_same_cycle else (
               "No overlapping hours between runs yet.")
        return {"available": False, "reason": why,
                "runs_skipped_same_cycle": skipped_same_cycle}

    buckets = []
    for label in ("0-12 h", "12-24 h", "24-48 h", "48-72 h", "72-120 h"):
        b = by_lead.get(label)
        if not b or not b["wind_err"]:
            continue
        w = b["wind_err"]
        d = b["dir_err"]
        buckets.append({
            "lead": label,
            "samples": len(w),
            "runs": len(b["runs"]),
            "mean_wind_shift_kt": round(sum(w) / len(w), 1),
            "max_wind_shift_kt": round(max(w), 1),
            "mean_dir_shift_deg": round(sum(d) / len(d)) if d else None,
        })

    return {
        "available": True,
        "measures": "forecast stability, not verified accuracy - the reference "
                    "is the newest model run for the same hour, not an observation",
        "snapshots_compared": len(snaps) - 1,
        "oldest_run": snaps[-1][1][:16],
        "points_compared": compared,
        "runs_skipped_same_cycle": skipped_same_cycle,
        "by_lead_time": buckets,
    }


def _hours_between(gen_iso: str, when_iso: str) -> float | None:
    import datetime as dt
    try:
        a = dt.datetime.fromisoformat(gen_iso[:16])
        b = dt.datetime.fromisoformat(when_iso[:16])
    except ValueError:
        return None
    return (b - a).total_seconds() / 3600.0


def _bucket(h: float) -> str:
    if h <= 12:
        return "0-12 h"
    if h <= 24:
        return "12-24 h"
    if h <= 48:
        return "24-48 h"
    if h <= 72:
        return "48-72 h"
    return "72-120 h"
