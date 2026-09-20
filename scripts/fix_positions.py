"""Correct mooring coordinates against OSM harbour features, and snap to water.

Two independent checks found that four of the thirteen hand-written mooring
coordinates sit on dry land: Porto Pignataro, San Pietro, Marina del Gabbiano
and Filicudi Porto. A forecast sampled over land is meaningless, and so is any
shelter score derived from it.

This anchors each mooring to the OSM harbour / marina / anchorage feature that
actually represents it, then walks the point seaward until it is genuinely on
water with a little clearance, so both the weather sampling and the ray-cast
that derives the exposure sector have something real to work with.

The mooring -> OSM feature mapping below is stated explicitly rather than fuzzy
matched: there are only thirteen, and a wrong automatic match would be worse
than no match at all.

    python scripts/fix_positions.py            # report, changes nothing
    python scripts/fix_positions.py --write    # apply to waypoints.json
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
COAST = ROOT / "scripts" / "_coastline.json"
HARBOURS = ROOT / "scripts" / "_harbours.json"
WAYPOINTS = ROOT / "data" / "waypoints.json"

# Minimum clearance from the shoreline for a sample point, in metres. Far
# enough that a forecast grid cell is over water, close enough to still
# represent the berth.
CLEARANCE_M = 120.0

# mooring id -> (OSM feature name or None, fallback lat, lon, note)
# Names are matched against the OSM extract; where the archipelago has no
# mapped feature for a berth, an explicit fallback coordinate is used and
# flagged for a human to confirm.
ANCHORS = {
    "portorosa":           ("Marina di Portorosa", None, None),
    "lipari_pignataro":    ("Porto Pignataro", None, None),
    "lipari_marina_lunga": ("Lipari Marina Lunga", None, None),
    "lipari_valle_muria":  (None, 38.4565, 14.9295),   # no OSM feature; bay mouth
    "panarea_sanpietro":   (None, 38.6390, 15.0790),   # no OSM feature; off the village
    "panarea_drautto":     (None, 38.6315, 15.0775),   # no OSM feature; off the beach
    "panarea_zimmari":     (None, 38.6288, 15.0790),   # no OSM feature
    "panarea_milazzese":   (None, 38.6264, 15.0664),   # OSM anchorage node
    "stromboli_gabbiano":  (None, 38.8007, 15.2441),   # OSM anchorage, 600 m N of Scari
    "filicudi_porto":      (None, 38.5606, 14.5858),   # OSM anchorage off the port
    "filicudi_pecorini":   (None, 38.5579, 14.5677),   # OSM anchorage
    "salina_santamarina":  ("Santa Marina Salina", None, None),
    "salina_rinella":      (None, 38.5465, 14.8303),   # OSM anchorage
}

M_PER_NM = 1852.0


def coastline_segments() -> np.ndarray:
    d = json.loads(COAST.read_text(encoding="utf-8"))
    out = []
    for el in d["elements"]:
        if (el.get("tags") or {}).get("natural") != "coastline":
            continue
        g = el.get("geometry") or []
        for a, b in zip(g, g[1:]):
            out.append((a["lon"], a["lat"], b["lon"], b["lat"]))
    return np.asarray(out, dtype=float)


def harbour_features() -> dict[str, tuple[float, float]]:
    d = json.loads(HARBOURS.read_text(encoding="utf-8"))
    feats = {}
    for el in d["elements"]:
        t = el.get("tags", {})
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        name = t.get("name") or t.get("seamark:name")
        if lat is not None and name:
            feats.setdefault(name, (float(lat), float(lon)))
    return feats


def on_land(seg: np.ndarray, lat: float, lon: float) -> bool:
    """Crossing parity of a ray due north. Island coastlines are closed rings,
    so an odd number of crossings means the point is inside land."""
    sel = seg[(np.minimum(seg[:, 0], seg[:, 2]) <= lon)
              & (np.maximum(seg[:, 0], seg[:, 2]) >= lon)]
    if not len(sel):
        return False
    x1, y1, x2, y2 = sel[:, 0], sel[:, 1], sel[:, 2], sel[:, 3]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (lon - x1) / (x2 - x1)
    ok = np.isfinite(t) & (t >= 0) & (t < 1)
    ylat = y1 + t * (y2 - y1)
    return bool(np.sum(ok & (ylat > lat)) % 2)


def dist_to_coast_m(seg: np.ndarray, lat: float, lon: float) -> float:
    kx = math.cos(math.radians(lat)) * 111_320.0
    ky = 110_540.0
    win = 4000.0
    sel = seg[(np.minimum(seg[:, 0], seg[:, 2]) <= lon + win / kx)
              & (np.maximum(seg[:, 0], seg[:, 2]) >= lon - win / kx)
              & (np.minimum(seg[:, 1], seg[:, 3]) <= lat + win / ky)
              & (np.maximum(seg[:, 1], seg[:, 3]) >= lat - win / ky)]
    if not len(sel):
        return float("inf")
    ax = (sel[:, 0] - lon) * kx; ay = (sel[:, 1] - lat) * ky
    bx = (sel[:, 2] - lon) * kx; by = (sel[:, 3] - lat) * ky
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.clip(-(ax * dx + ay * dy) / np.where(L2 == 0, 1, L2), 0, 1)
    px, py = ax + t * dx, ay + t * dy
    return float(np.min(np.hypot(px, py)))


def step(lat: float, lon: float, bearing_deg: float, metres: float) -> tuple[float, float]:
    kx = math.cos(math.radians(lat)) * 111_320.0
    th = math.radians(bearing_deg)
    return lat + (metres * math.cos(th)) / 110_540.0, lon + (metres * math.sin(th)) / kx


def snap_to_water(seg: np.ndarray, lat: float, lon: float) -> tuple[float, float, str]:
    """Move the point seaward until it is on water with CLEARANCE_M to spare.

    Tries every bearing and takes the shortest move that works, so the point
    ends up just off the nearest piece of open water rather than arbitrarily
    far out.
    """
    if not on_land(seg, lat, lon) and dist_to_coast_m(seg, lat, lon) >= CLEARANCE_M:
        return lat, lon, "already clear"

    best = None
    for dist in range(50, 3001, 25):
        for brg in range(0, 360, 5):
            la, lo = step(lat, lon, brg, dist)
            if on_land(seg, la, lo):
                continue
            if dist_to_coast_m(seg, la, lo) < CLEARANCE_M:
                continue
            best = (la, lo, f"moved {dist} m on {brg:03d}°")
            break
        if best:
            break
    return best or (lat, lon, "COULD NOT FIND WATER")


def nm_between(a, b, c, d) -> float:
    R = 3440.065
    p1, p2 = math.radians(a), math.radians(c)
    dphi, dlam = p2 - p1, math.radians(d - b)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    seg = coastline_segments()
    feats = harbour_features()
    wp = json.loads(WAYPOINTS.read_text(encoding="utf-8"))
    moorings = wp["moorings"]

    print(f"{len(seg):,} coastline segments, {len(feats)} named harbour features\n")
    print(f"{'mooring':22} {'old':>17} {'new':>17} {'moved':>7}  source / action")
    print("-" * 104)

    updates = {}
    for key, m in moorings.items():
        name, flat, flon = ANCHORS[key]
        if name and name in feats:
            tlat, tlon = feats[name]
            src = f"OSM '{name}'"
        elif flat is not None:
            tlat, tlon = flat, flon
            src = "explicit fallback"
        else:
            print(f"{key:22} no anchor available")
            continue

        nlat, nlon, action = snap_to_water(seg, tlat, tlon)
        moved = nm_between(m["lat"], m["lon"], nlat, nlon)
        was_land = on_land(seg, m["lat"], m["lon"])
        flag = "  <-- was ON LAND" if was_land else ""
        print(f"{key:22} {m['lat']:8.4f},{m['lon']:7.4f} {nlat:8.4f},{nlon:7.4f} "
              f"{moved:6.2f}nm  {src}; {action}{flag}")
        updates[key] = (round(nlat, 4), round(nlon, 4), src, action)

    print()
    bad = [k for k in moorings if on_land(seg, *(updates[k][:2] if k in updates
                                                 else (moorings[k]["lat"], moorings[k]["lon"])))]
    print("on land after correction:", bad or "none")

    if args.write:
        for key, (la, lo, src, action) in updates.items():
            moorings[key]["lat"] = la
            moorings[key]["lon"] = lo
            moorings[key]["position_source"] = f"{src}; {action}"
        WAYPOINTS.write_text(json.dumps(wp, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        print(f"\nwrote {len(updates)} corrected positions to {WAYPOINTS.name}")
        print("'verified' left false - these are better positions, not a chart check.")
    else:
        print("\nReport only. Re-run with --write to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
