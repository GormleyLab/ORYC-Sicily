"""Apply Imray *Italian Waters Pilot* (Heikell) shelter data to the waypoints.

The geometric derivation in derive_sectors.py is a good first pass but cannot
see swell refraction, ground swell, katabatic gusts off high ground, or ferry
wash. This applies what the pilot book states directly, which is the check the
`verified` flag was always waiting for.

Source: Imray, *Italian Waters Pilot*, Isole Eolie chapter, pp. 371-383.
Only the factual shelter directions, waypoints and hazards are recorded here.

Where the pilot gives an explicit shelter sector the entry is marked verified.
Where it does not - Drautto and Baia Milazzese are not described separately,
and Portorosa is on the north Sicily coast, outside this chapter - the derived
sector stands and `verified` stays false.

    python scripts/apply_pilot.py            # report
    python scripts/apply_pilot.py --write    # apply
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
WAYPOINTS = ROOT / "data" / "waypoints.json"
SOURCE = "Imray Italian Waters Pilot (Heikell), Isole Eolie pp.371-383"


def dm(deg: int, minutes: float) -> float:
    return deg + minutes / 60.0


# mooring -> pilot waypoint (lat, lon) or None, exposure sector(s), the pilot's
# shelter statement in brief, and any hazard it flags.
PILOT = {
    "lipari_pignataro": {
        "pos": (dm(38, 28.69), dm(14, 57.88)),
        "sector": [200, 250],
        "shelter": "Good shelter in summer. Open SW for a short distance; strong "
                   "southerlies make it untenable. The pilot calls it the safest "
                   "place on Lipari.",
        "hazard": "Gusts out of the bay from W-NW. Entrance between moored boats "
                  "and the breakwater is tight when a tripper boat is moving.",
    },
    "lipari_marina_lunga": {
        "pos": None,
        "sector": [45, 135],
        "shelter": "Open NE-SE. With gales from anywhere many berths may become "
                   "untenable, particularly with southerlies.",
        "hazard": "Ground swell often creeps round beyond the harbour, and there "
                  "is constant ferry wash. Keep pulled well off the pontoon.",
    },
    "lipari_valle_muria": {
        "pos": None,
        "sector": [180, 280],
        "shelter": "Open W and south. Anchor towards the N end in 5-10 m.",
        "hazard": "Reef at the S end of the bay.",
    },
    "panarea_sanpietro": {
        "pos": (dm(38, 38.37), dm(15, 4.81)),
        "sector": [30, 180],
        "shelter": "Adequate in settled weather, but with any fresh wind or "
                   "moderate sea from anywhere in the E this is not the place to be.",
        "hazard": "Cannot anchor within 200 m of the pier; keep clear of the laid "
                  "moorings. Yachts generally not permitted on the pier.",
    },
    "panarea_zimmari": {
        "pos": (dm(38, 37.6), dm(15, 4.0)),
        "sector": [80, 190],
        "shelter": "Open E and south. Anchor in 5-10 m on sand, good holding.",
        "hazard": "The Punta Milazzese area is technically off limits - navigating "
                  "and anchoring in the vicinity is prohibited, and you may be told "
                  "to move on.",
    },
    "stromboli_gabbiano": {
        "pos": (dm(38, 47.91), dm(15, 14.55)),
        # The pilot is explicit that swell rolls in from almost any direction, so
        # there is no sheltered arc to encode. Full exposure is the honest value.
        "sector": [0, 359],
        "shelter": "An open roadstead. With winds from almost any direction an "
                   "uncomfortable swell rolls around here. Suitable in calm weather "
                   "only - leave at the slightest sign of bad weather.",
        "hazard": "Holding uncertain in places; underwater cables off the village. "
                  "Mooring buoys N of the mole Apr-Oct; pick-up lines can be fouled.",
    },
    "filicudi_porto": {
        "pos": (dm(38, 33.7), dm(14, 35.0)),
        "sector": [345, 99],
        "shelter": "A short mole on the E side of the island; yachts anchor off in "
                   "settled weather. About 20 visitors' moorings laid in the bay.",
        "hazard": "An old groyne runs about 100 m SE from the ferry mole, just under "
                  "the surface and hard to see. Bottom stoney with weed; holding not "
                  "good everywhere.",
    },
    "filicudi_pecorini": {
        "pos": (dm(38, 33.5), dm(14, 34.0)),
        "sector": [109, 269],
        "shelter": "Anchor off rather than use the mole - there is really no room "
                   "for yachts. Twelve yellow mooring buoys laid in summer.",
        "hazard": "There is nearly always some ground swell here, and it is deep "
                  "everywhere. Not the calm alternative it looks on a chart.",
    },
    "salina_santamarina": {
        "pos": (dm(38, 33.22), dm(14, 52.42)),
        "sector": [150, 210],
        "shelter": "Good shelter in settled conditions in both harbours; the S basin "
                   "affords the better all-round shelter. Strong southerlies would "
                   "probably affect the S basin.",
        "hazard": None,
    },
    "salina_rinella": {
        "pos": (dm(38, 32.7), dm(14, 49.6)),
        "sector": [90, 190],
        "shelter": "A short mole off a hamlet on the S coast. Open E-S.",
        "hazard": "Limited anchoring room inside the laid local moorings; space "
                  "outside them in 15 m+.",
    },
}

NOT_IN_PILOT = {
    "panarea_drautto": "Not described separately in the Isole Eolie chapter.",
    "portorosa": "On the north Sicily coast, outside the Isole Eolie chapter.",
}


def nm(a, b, c, d) -> float:
    R = 3440.065
    p1, p2 = math.radians(a), math.radians(c)
    dphi, dlam = p2 - p1, math.radians(d - b)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def fmt(sec) -> str:
    if sec is None:
        return "enclosed"
    if isinstance(sec[0], (list, tuple)):
        return ", ".join(f"{a[0]}-{a[1]}" for a in sec)
    return f"{sec[0]}-{sec[1]}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    wp = json.loads(WAYPOINTS.read_text(encoding="utf-8"))
    M = wp["moorings"]

    print(f"{'mooring':22} {'derived':>22} -> {'pilot':>12}  {'pos delta':>9}")
    print("-" * 78)
    for key, p in PILOT.items():
        m = M[key]
        delta = ""
        if p["pos"]:
            delta = f"{nm(m['lat'], m['lon'], *p['pos']):.2f} nm"
        print(f"{key:22} {fmt(m.get('exposed_sector')):>22} -> {fmt(p['sector']):>12}  {delta:>9}")

    print()
    for key, why in NOT_IN_PILOT.items():
        print(f"  {key:22} left derived - {why}")

    if args.write:
        for key, p in PILOT.items():
            m = M[key]
            if p["pos"]:
                m["lat"], m["lon"] = round(p["pos"][0], 4), round(p["pos"][1], 4)
                m["position_source"] = SOURCE
            m["exposed_sector"] = p["sector"]
            m["sector_source"] = SOURCE
            m["shelter_note"] = p["shelter"]
            if p["hazard"]:
                m["hazard_note"] = p["hazard"]
            m["verified"] = True
        for key, why in NOT_IN_PILOT.items():
            M[key]["verification_note"] = why
        WAYPOINTS.write_text(json.dumps(wp, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        verified = sum(1 for m in M.values() if m.get("verified"))
        print(f"\nwrote pilot data. verified: {verified}/{len(M)}")
    else:
        print("\nReport only. Re-run with --write to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
