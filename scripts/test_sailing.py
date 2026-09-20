"""Unit tests for the derived sailing maths.

Run: python -m pytest scripts/ -q
"""

import json
import math
import pathlib

import pytest

import sailing as s

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
WAYPOINTS = json.loads((DATA / "waypoints.json").read_text(encoding="utf-8"))
MOORINGS = WAYPOINTS["moorings"]


# --- Geometry ---------------------------------------------------------------

def test_bearing_cardinal_directions():
    assert s.initial_bearing(0, 0, 1, 0) == pytest.approx(0, abs=0.1)     # north
    assert s.initial_bearing(0, 0, 0, 1) == pytest.approx(90, abs=0.1)    # east
    assert s.initial_bearing(0, 0, -1, 0) == pytest.approx(180, abs=0.1)  # south
    assert s.initial_bearing(0, 0, 0, -1) == pytest.approx(270, abs=0.1)  # west


def test_bearing_is_always_in_range():
    for lat in (-60, 0, 38.5, 70):
        for lon in (-170, 0, 15, 179):
            b = s.initial_bearing(38.5, 15.0, lat, lon)
            assert 0 <= b < 360


def test_distance_one_degree_of_latitude_is_sixty_nm():
    assert s.distance_nm(38.0, 15.0, 39.0, 15.0) == pytest.approx(60, abs=0.2)


@pytest.mark.parametrize("leg", WAYPOINTS["legs"], ids=lambda l: l["id"])
def test_leg_distance_matches_the_itinerary(leg):
    """Computed rhumb distance should be close to the itinerary's own figure.

    The itinerary's numbers are sailed distances including any dogleg around
    headlands, so the straight-line figure runs a little short. A 30% band
    catches a transposed coordinate without flagging honest routing slack.
    """
    a, b = MOORINGS[leg["from"]], MOORINGS[leg["to"]]
    computed = s.distance_nm(a["lat"], a["lon"], b["lat"], b["lon"])
    stated = leg["stated_nm"]
    assert computed == pytest.approx(stated, rel=0.30), (
        f"{leg['id']}: computed {computed:.1f} nm vs itinerary {stated} nm"
    )


def test_portorosa_to_lipari_heads_roughly_north():
    a, b = MOORINGS["portorosa"], MOORINGS["lipari_pignataro"]
    bearing = s.initial_bearing(a["lat"], a["lon"], b["lat"], b["lon"])
    assert 340 <= bearing or bearing <= 25, f"expected a northerly course, got {bearing:.0f}"


def test_every_mooring_sits_in_the_aeolian_box():
    """Guards against a lat/lon swap or a stray digit."""
    for key, m in MOORINGS.items():
        assert 38.0 <= m["lat"] <= 39.0, f"{key} latitude {m['lat']} out of range"
        assert 14.4 <= m["lon"] <= 15.4, f"{key} longitude {m['lon']} out of range"


# --- Sectors ----------------------------------------------------------------

def test_in_sector_simple_and_wrapping():
    assert s.in_sector(90, [60, 120])
    assert not s.in_sector(200, [60, 120])
    assert s.in_sector(10, [340, 20])     # wraps through north
    assert s.in_sector(350, [340, 20])
    assert not s.in_sector(180, [340, 20])


def test_sector_proximity_tapers_outside_the_arc():
    assert s.sector_proximity(90, [60, 120]) == 1.0
    assert s.sector_proximity(135, [60, 120]) == pytest.approx(0.5, abs=0.01)
    assert s.sector_proximity(180, [60, 120]) == 0.0
    assert s.sector_proximity(90, None) == 0.0


def test_angular_difference_handles_wraparound():
    assert s.angular_difference(350, 10) == pytest.approx(20)
    assert s.angular_difference(10, 350) == pytest.approx(20)
    assert s.angular_difference(0, 180) == pytest.approx(180)


def test_compass_point():
    assert s.compass_point(0) == "N"
    assert s.compass_point(90) == "E"
    assert s.compass_point(293) == "WNW"
    assert s.compass_point(359) == "N"
    assert s.compass_point(None) == "-"


# --- Wind relative to the boat ---------------------------------------------

def test_true_wind_angle_and_point_of_sail():
    assert s.true_wind_angle(0, 0) == 0            # dead on the nose
    assert s.true_wind_angle(0, 180) == 180        # dead astern
    assert s.true_wind_angle(90, 180) == 90        # beam on
    assert s.point_of_sail(0) == "head to wind - motor"
    # The point-of-sail label must never reuse the safety verdict's vocabulary.
    assert "no-go" not in s.point_of_sail(0)
    assert s.point_of_sail(40) == "close hauled"
    assert s.point_of_sail(90) == "beam reach"
    assert s.point_of_sail(170) == "run"


def test_beaufort_boundaries():
    assert s.beaufort(0)["force"] == 0
    assert s.beaufort(12)["force"] == 4
    assert s.beaufort(22)["force"] == 6
    assert s.beaufort(35)["force"] == 8


def test_reef_guidance_escalates_with_wind():
    assert "Full main" in s.reef_guidance(12)
    assert "First reef" in s.reef_guidance(20)
    assert "Second reef" in s.reef_guidance(25)
    assert "stay in port" in s.reef_guidance(40)


# --- Verdicts ---------------------------------------------------------------

def test_leg_verdict_green_amber_red():
    assert s.leg_verdict(12, 18, 0.8)["verdict"] == "go"
    assert s.leg_verdict(20, 26, 1.4)["verdict"] == "caution"
    assert s.leg_verdict(28, 35, 2.4)["verdict"] == "no-go"


def test_leg_verdict_gust_alone_can_force_no_go():
    """Benign sustained wind must not mask a dangerous gust spread."""
    out = s.leg_verdict(14, 34, 0.9)
    assert out["verdict"] == "no-go"
    assert any("Gusts" in r for r in out["reasons"])


def test_thunderstorms_override_calm_wind():
    out = s.leg_verdict(8, 12, 0.4, weather_codes=[3, 95])
    assert out["verdict"] == "no-go"
    assert any("Thunderstorm" in r for r in out["reasons"])


def test_wind_against_swell_raises_caution():
    out = s.leg_verdict(16, 21, 1.0, wind_dir=0, swell_dir=180)
    assert out["verdict"] == "caution"
    assert any("opposing swell" in r for r in out["reasons"])


def test_gust_spike_in_light_wind_is_a_note_not_a_caution():
    """IFS reports an interval-maximum gust; against a 4 kt mean that is an
    artefact, and flagging it amber would train skippers to ignore amber."""
    out = s.leg_verdict(4, 26, 0.2)
    assert out["verdict"] == "go"
    assert any("interval-maximum" in r for r in out["reasons"])


def test_real_gust_in_a_real_breeze_still_triggers():
    """The spike rule must not swallow a genuine gust in a working breeze."""
    out = s.leg_verdict(20, 34, 1.0)
    assert out["verdict"] == "no-go"
    assert any("Gusts" in r and "interval-maximum" not in r for r in out["reasons"])


def test_gust_spike_detection_boundaries():
    assert s.is_gust_spike(4, 26)          # 6.5x on a light mean
    assert not s.is_gust_spike(20, 34)     # 1.7x in a real breeze
    assert not s.is_gust_spike(12, 34)     # mean too strong to be an artefact
    assert not s.is_gust_spike(None, 30)
    assert not s.is_gust_spike(0, 30)


def test_verdict_unknown_when_no_data():
    assert s.leg_verdict(None, None, None)["verdict"] == "unknown"


# --- Shelter ----------------------------------------------------------------

def test_enclosed_marina_always_sheltered():
    out = s.shelter_score(None, wind_dir=90, wind_kt=30, swell_dir=90, swell_m=3.0)
    assert out["score"] == 1.0
    assert out["verdict"] == "sheltered"


def test_salina_easterly_favours_santa_marina_over_rinella():
    """Pilot: Rinella is "Open E-S"; Santa Marina's S basin "affords the better
    all-round shelter". So in an easterly the fleet wants Santa Marina.

    This assertion is the reverse of what this test originally claimed. The
    first version encoded a guessed sector that had Santa Marina open to the
    east; the pilot book says otherwise, and the pilot wins.
    """
    sm = s.shelter_score(MOORINGS["salina_santamarina"]["exposed_sector"],
                         wind_dir=90, wind_kt=20, swell_dir=90, swell_m=1.5)
    rin = s.shelter_score(MOORINGS["salina_rinella"]["exposed_sector"],
                          wind_dir=90, wind_kt=20, swell_dir=90, swell_m=1.5)
    assert sm["score"] > rin["score"]
    assert rin["wind_exposed"] and not sm["wind_exposed"]


def test_salina_strong_southerly_reaches_santa_marina():
    """Pilot: "Strong southerlies would probably affect the S basin." A
    southerly is the one direction that gets into Santa Marina."""
    sm = s.shelter_score(MOORINGS["salina_santamarina"]["exposed_sector"],
                         wind_dir=180, wind_kt=25, swell_dir=180, swell_m=2.0)
    assert sm["wind_exposed"]
    assert sm["verdict"] in ("exposed", "untenable", "workable")


def test_lipari_northeasterly_favours_pignataro_over_marina_lunga():
    """Pilot: Marina Lunga is "Open NE-SE"; Pignataro is open SW only. In a
    fresh north-easterly Pignataro is the place to be - which is why the pilot
    calls it the safest spot on Lipari."""
    pig = s.shelter_score(MOORINGS["lipari_pignataro"]["exposed_sector"],
                          wind_dir=60, wind_kt=22, swell_dir=60, swell_m=1.5)
    ml = s.shelter_score(MOORINGS["lipari_marina_lunga"]["exposed_sector"],
                         wind_dir=60, wind_kt=22, swell_dir=60, swell_m=1.5)
    assert pig["score"] > ml["score"]
    assert ml["wind_exposed"] and not pig["wind_exposed"]


def test_lipari_southwesterly_reaches_both_pignataro_and_valle_muria():
    """Pilot: Valle Muria "Open W and south"; Pignataro "Open SW for a short
    distance, but strong southerlies make it untenable". A SW blow is the case
    where neither is comfortable.

    Note the model has no concept of fetch: Pignataro's SW exposure is only
    across the bay, so this over-states it. Erring toward exposed is the safe
    direction, but it is why the pilot's prose is kept alongside the sector.
    """
    for key in ("lipari_valle_muria", "lipari_pignataro"):
        out = s.shelter_score(MOORINGS[key]["exposed_sector"],
                              wind_dir=235, wind_kt=25, swell_dir=235, swell_m=2.0)
        assert out["wind_exposed"], key


def test_stromboli_is_exposed_from_every_direction():
    """Pilot: an open roadstead where "with winds from almost any direction an
    uncomfortable swell rolls around here", suitable in calm weather only.
    There is no sheltered arc to find, so no wind direction should read as
    sheltered once it is blowing."""
    for brg in range(0, 360, 30):
        out = s.shelter_score(MOORINGS["stromboli_gabbiano"]["exposed_sector"],
                              wind_dir=brg, wind_kt=20, swell_dir=brg, swell_m=1.5)
        assert out["verdict"] != "sheltered", f"bearing {brg} read as sheltered"


# Two authorities may close an exposure sector, and nothing else. The pilot
# book, because Heikell surveyed these anchorages; and the fleet owner, who
# sails them. Geometry, OpenStreetMap, marina listings and web searches fix
# POSITIONS - none of them can settle an arc, because the thing they all miss
# is swell bending round a headland, which is what a wrong arc gets wrong.
SECTOR_AUTHORITIES = ("Pilot", "owner")


def test_verified_moorings_carry_their_source():
    """Anything marked verified must say what verified it.

    A berth with a real exposure arc needs one of SECTOR_AUTHORITIES named in
    its source - a wrong arc is the worst bug this project can have. A berth
    with `exposed_sector: null` has no arc to get wrong: `shelter_score`
    returns 1.0 unconditionally, so what is being verified is only that the
    basin really is enclosed, and the source must say so.
    """
    for key, m in MOORINGS.items():
        if not m.get("verified"):
            continue
        assert m.get("sector_source"), f"{key} verified with no source"
        if m.get("exposed_sector") is None:
            assert "enclosed" in m["sector_source"], (
                f"{key} has no arc, so its source must say why that is safe")
        else:
            assert any(a in m["sector_source"] for a in SECTOR_AUTHORITIES), (
                f"{key} sector_source names no recognised authority "
                f"(one of {SECTOR_AUTHORITIES}): {m['sector_source']!r}")


def test_no_mooring_is_verified_by_geometry_alone():
    """The failure this guards against is a derived arc quietly being blessed.

    `derive_sectors.py` writes `sector_source` itself, so a careless --write
    followed by a flag flip would present ray-cast geometry as verified.
    """
    for key, m in MOORINGS.items():
        if not m.get("verified") or m.get("exposed_sector") is None:
            continue
        src = m["sector_source"]
        assert not src.startswith("derived from OSM"), (
            f"{key} is verified but its source is still the raw derivation")


def test_multiple_arcs_are_all_scored():
    """Several berths are open to more than one arc. Scoring only the widest
    reported a northerly at San Pietro as sheltered when it is not."""
    arcs = [[103, 186], [340, 41]]
    assert s.sector_proximity(140, arcs) == 1.0
    assert s.sector_proximity(10, arcs) == 1.0     # the arc that used to be missed
    assert s.sector_proximity(355, arcs) == 1.0
    assert s.sector_proximity(250, arcs) == 0.0


def test_multi_arc_shelter_score_flags_the_secondary_arc():
    single = s.shelter_score([103, 186], wind_dir=10, wind_kt=22,
                             swell_dir=10, swell_m=1.5)
    multi = s.shelter_score([[103, 186], [340, 41]], wind_dir=10, wind_kt=22,
                            swell_dir=10, swell_m=1.5)
    assert single["verdict"] == "sheltered"      # the old, wrong answer
    assert multi["score"] < single["score"]
    assert multi["wind_exposed"] and multi["swell_exposed"]


def test_single_arc_still_behaves_as_before():
    """The list form must not change results for berths with one arc."""
    a = s.shelter_score([60, 120], wind_dir=90, wind_kt=20, swell_dir=90, swell_m=1.2)
    b = s.shelter_score([[60, 120]], wind_dir=90, wind_kt=20, swell_dir=90, swell_m=1.2)
    assert a["score"] == b["score"] and a["verdict"] == b["verdict"]


def test_all_round_exposure_never_claims_shelter():
    """A berth open from every direction has no sheltered arc, so the reason
    must not say wind and swell stay clear of it - even in light air."""
    out = s.shelter_score([0, 359], wind_dir=90, wind_kt=4, swell_dir=90, swell_m=0.2)
    assert "stay clear" not in out["reason"]
    assert "every direction" in out["reason"]


def test_light_wind_inside_the_arc_is_described_honestly():
    out = s.shelter_score([60, 120], wind_dir=90, wind_kt=5, swell_dir=200, swell_m=0.2)
    assert "stay clear" not in out["reason"]
    assert "Open to the" in out["reason"]


def test_all_round_exposure_is_never_labelled_sheltered():
    """Stromboli's roadstead has no sheltered arc. Even flat calm it should
    read as workable at best - "sheltered" would describe the place, not the
    hour, and the place is never sheltered."""
    out = s.shelter_score([0, 359], wind_dir=90, wind_kt=3, swell_dir=90, swell_m=0.1)
    assert out["score"] >= 0.8
    assert out["verdict"] == "workable"
    out2 = s.shelter_score(MOORINGS["stromboli_gabbiano"]["exposed_sector"],
                           wind_dir=90, wind_kt=3, swell_dir=90, swell_m=0.1)
    assert out2["verdict"] != "sheltered"


def test_shelter_score_is_bounded():
    for wd in range(0, 360, 15):
        out = s.shelter_score([60, 120], wind_dir=wd, wind_kt=60, swell_dir=wd, swell_m=6.0)
        assert 0.0 <= out["score"] <= 1.0


def test_calm_conditions_leave_every_berth_comfortable():
    """In near-calm nothing should read worse than workable. Berths with no
    sheltered arc at all - Stromboli's roadstead - top out at workable by
    design, so they are exempt from the stronger assertion."""
    for key, m in MOORINGS.items():
        sec = m["exposed_sector"]
        out = s.shelter_score(sec, wind_dir=90, wind_kt=3, swell_dir=90, swell_m=0.2)
        assert out["score"] >= 0.8, f"{key} scored low in near-calm"
        arcs = [] if not sec else (sec if isinstance(sec[0], (list, tuple)) else [sec])
        all_round = sum((a[1] - a[0]) % 360 + 1 for a in arcs) >= 359
        expected = "workable" if all_round else "sheltered"
        assert out["verdict"] == expected, f"{key}: {out['verdict']} != {expected}"


# --- Model agreement --------------------------------------------------------

def test_model_agreement_confidence_bands():
    assert s.model_agreement([12, 13, 14])["confidence"] == "high"
    assert s.model_agreement([10, 16, 18])["confidence"] == "moderate"
    assert s.model_agreement([8, 20, 25])["confidence"] == "low"
    assert s.model_agreement([12])["confidence"] == "single-model"
    assert s.model_agreement([None, None])["confidence"] == "none"


def test_model_agreement_ignores_missing_models():
    out = s.model_agreement([12, None, 14])
    assert out["n"] == 2 and out["mean"] == pytest.approx(13)


def test_circular_mean_near_north():
    """A plain average of 350 and 10 gives 180 - the exact wrong answer."""
    assert s.circular_mean([350, 10]) == pytest.approx(0, abs=0.5)
    assert s.circular_mean([80, 100]) == pytest.approx(90, abs=0.5)
    assert s.circular_mean([]) is None
