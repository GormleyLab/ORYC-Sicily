"""Compute each mooring's exposure sector from OpenStreetMap coastline geometry.

An exposure sector is the arc of compass bearings a berth is open to. Those
values drive every shelter recommendation the site makes, and the ones written
by hand were inferred from the itinerary text rather than from any chart.

This derives them geometrically instead: from each mooring, cast a ray every
degree and record how far it travels before hitting land, a breakwater or a
pier. Bearings that reach open sea are exposed; bearings blocked by a headland
or a mole are sheltered.

What this DOES give you: an objective, repeatable first pass that is far better
than a guess, and that catches a sector pointing the wrong way entirely.

What it does NOT give you, and why a pilot book still wins:
  * swell refracts around headlands, so a bay can roll from a direction this
    marks as blocked;
  * it says nothing about depth, holding ground, or room to swing;
  * it cannot see a low spit that stops swell but not wind;
  * rays stop at RANGE_NM, so anything beyond that reads as open sea.

    python scripts/derive_sectors.py            # report, changes nothing
    python scripts/derive_sectors.py --write    # write into waypoints.json
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import time

import numpy as np
import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "scripts" / "_coastline.json"
WAYPOINTS = ROOT / "data" / "waypoints.json"

# How far a ray travels before we call the bearing "open sea". Five miles is
# enough to clear every neighbouring island in the archipelago without running
# off the edge of the downloaded extract.
RANGE_NM = 5.0
STEP_DEG = 1

# Arcs narrower than this are slivers between rocks, not real exposure.
MIN_ARC_DEG = 12

BBOX = (37.90, 14.20, 39.00, 15.70)  # S, W, N, E
OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]
HEADERS = {"User-Agent": "ORYC-Sicily-waypoint-check/1.0 "
                         "(flotilla planning; github.com/GormleyLab/ORYC-Sicily)"}

QUERY = f"""
[out:json][timeout:180];
(
  way["natural"="coastline"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["man_made"="breakwater"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
  way["man_made"="pier"]({BBOX[0]},{BBOX[1]},{BBOX[2]},{BBOX[3]});
);
out geom;
"""

M_PER_NM = 1852.0


def load_geometry() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    for host in OVERPASS:
        try:
            r = requests.post(host, data={"data": QUERY}, headers=HEADERS, timeout=240)
            if r.status_code == 200:
                CACHE.write_text(r.text, encoding="utf-8")
                return r.json()
        except requests.RequestException:
            continue
        time.sleep(2)
    sys.exit("could not fetch coastline geometry from Overpass")


def segments(data: dict) -> np.ndarray:
    """All blocking segments as (N, 4) of lon1, lat1, lon2, lat2."""
    out = []
    for el in data["elements"]:
        g = el.get("geometry") or []
        for a, b in zip(g, g[1:]):
            out.append((a["lon"], a["lat"], b["lon"], b["lat"]))
    return np.asarray(out, dtype=float)


def local_xy(seg: np.ndarray, lat0: float, lon0: float) -> tuple[np.ndarray, np.ndarray]:
    """Project to metres on a local tangent plane centred on the mooring."""
    kx = math.cos(math.radians(lat0)) * 111_320.0
    ky = 110_540.0
    p = np.column_stack(((seg[:, 0] - lon0) * kx, (seg[:, 1] - lat0) * ky))
    q = np.column_stack(((seg[:, 2] - lon0) * kx, (seg[:, 3] - lat0) * ky))
    return p, q


def distance_profile(seg: np.ndarray, lat: float, lon: float) -> np.ndarray:
    """Distance in metres to the first obstruction on each bearing, 0..359."""
    reach = RANGE_NM * M_PER_NM

    # Only segments that could possibly be within reach.
    kx = math.cos(math.radians(lat)) * 111_320.0
    dlon = reach / kx
    dlat = reach / 110_540.0
    near = seg[
        (np.minimum(seg[:, 0], seg[:, 2]) <= lon + dlon)
        & (np.maximum(seg[:, 0], seg[:, 2]) >= lon - dlon)
        & (np.minimum(seg[:, 1], seg[:, 3]) <= lat + dlat)
        & (np.maximum(seg[:, 1], seg[:, 3]) >= lat - dlat)
    ]
    if not len(near):
        return np.full(360 // STEP_DEG, np.inf)

    P, Q = local_xy(near, lat, lon)
    S = Q - P                                    # segment vectors

    bearings = np.arange(0, 360, STEP_DEG)
    th = np.radians(bearings)
    R = np.column_stack((np.sin(th), np.cos(th)))  # ray dirs, bearing 0 = north

    # Ray from origin: origin + t*R  meets  P + u*S
    rxs = R[:, 0:1] * S[None, :, 1] - R[:, 1:2] * S[None, :, 0]      # (B, N)
    pxs = P[None, :, 0] * S[None, :, 1] - P[None, :, 1] * S[None, :, 0]
    pxr = (P[None, :, 0] * R[:, 1:2]) - (P[None, :, 1] * R[:, 0:1])

    with np.errstate(divide="ignore", invalid="ignore"):
        t = pxs / rxs
        u = pxr / rxs

    hit = np.isfinite(t) & (rxs != 0) & (t >= 0) & (t <= reach) & (u >= 0) & (u <= 1)
    t = np.where(hit, t, np.inf)
    return t.min(axis=1)


def arcs_from_open(open_mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous runs of open bearings, merged across 0/360."""
    b = np.arange(0, 360, STEP_DEG)
    if open_mask.all():
        return [(0, 359)]
    if not open_mask.any():
        return []
    runs, start = [], None
    for i, o in enumerate(open_mask):
        if o and start is None:
            start = i
        elif not o and start is not None:
            runs.append((b[start], b[i - 1]))
            start = None
    if start is not None:
        runs.append((b[start], b[-1]))
    # merge a run ending at 359 with one starting at 0
    if len(runs) > 1 and runs[0][0] == 0 and runs[-1][1] == 359:
        runs[0] = (runs[-1][0], runs[0][1])
        runs.pop()
    return runs


def arc_width(a: tuple[int, int]) -> int:
    return (a[1] - a[0]) % 360 + 1


def overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Degrees of overlap between two clockwise arcs."""
    inside = lambda x, arc: ((x - arc[0]) % 360) <= ((arc[1] - arc[0]) % 360)
    return sum(1 for d in range(360) if inside(d, a) and inside(d, b))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="write derived sectors into data/waypoints.json")
    args = ap.parse_args()

    data = load_geometry()
    seg = segments(data)
    print(f"{len(seg):,} coastline / breakwater / pier segments, "
          f"rays to {RANGE_NM:.0f} nm\n")

    wp = json.loads(WAYPOINTS.read_text(encoding="utf-8"))
    moorings = wp["moorings"]
    changes = {}

    for key, m in moorings.items():
        prof = distance_profile(seg, m["lat"], m["lon"])
        nearest_m = float(np.min(prof))
        open_mask = ~np.isfinite(prof)
        found = [a for a in arcs_from_open(open_mask) if arc_width(a) >= MIN_ARC_DEG]
        found.sort(key=arc_width, reverse=True)

        stored = m.get("exposed_sector")
        openness = int(open_mask.sum()) * STEP_DEG

        print(f"{m['name']}  ({m['island']})")
        print(f"   nearest land/mole : {nearest_m:,.0f} m"
              f"{'   << ON or ADJACENT TO the shoreline' if nearest_m < 25 else ''}")
        print(f"   open water        : {openness}° of 360  "
              f"({'fully enclosed' if openness == 0 else 'open arcs: ' + ', '.join(f'{a[0]}-{a[1]}' for a in found)})")

        if stored is None:
            verdict = "stored: enclosed marina" + (
                "  << but geometry says open!" if openness > 60 else "  (consistent)")
            print(f"   {verdict}")
        elif not found:
            prim = stored[0] if isinstance(stored[0], (list, tuple)) else stored
            print(f"   stored: {prim[0]}-{prim[1]}°  << geometry says fully enclosed")
        else:
            main_arc = found[0]
            prim = stored[0] if isinstance(stored[0], (list, tuple)) else stored
            ov = overlap(tuple(prim), main_arc)
            frac = ov / arc_width(tuple(prim)) if arc_width(tuple(prim)) else 0
            tag = ("agrees" if frac > 0.6 else
                   "PARTIAL - review" if frac > 0.25 else "DISAGREES - review")
            print(f"   stored: {prim[0]}-{prim[1]}°   derived: "
                  f"{main_arc[0]}-{main_arc[1]}°   overlap {ov}° ({frac:.0%})  -> {tag}")
            changes[key] = [[int(a[0]), int(a[1])] for a in found]
            if len(found) > 1:
                print("   also open: " + ", ".join(f"{a[0]}-{a[1]}°" for a in found[1:])
                      + "   (all arcs are kept for scoring)")
        print()

    if args.write:
        for key, arcs in changes.items():
            # Primary arc stays a plain [from, to] for display; the full list
            # is what the shelter score actually uses.
            moorings[key]["exposed_sector"] = arcs[0] if len(arcs) == 1 else arcs
            moorings[key]["sector_source"] = (
                f"derived from OSM coastline, rays to {RANGE_NM:.0f} nm")
        WAYPOINTS.write_text(json.dumps(wp, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        print(f"wrote {len(changes)} derived sectors into {WAYPOINTS.name}")
        print("NOTE: 'verified' is deliberately left false - a derived sector is a "
              "better first pass, not a chart check.")
    else:
        print("Report only. Re-run with --write to apply the derived sectors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
