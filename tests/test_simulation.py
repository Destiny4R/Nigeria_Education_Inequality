"""Counterfactual policy simulator (plan 9)."""
import copy

import numpy as np
import pytest

from src.simulation import engine as S


@pytest.fixture(scope="module")
def analytic():
    from src.cleaning.pipeline import run_cleaning
    return run_cleaning(write=False)[0]


def sim(analytic, **kw):
    base = dict(name="t", intervention="pct_reduction", value=10.0, coverage="all", coverage_value=None, fidelity_low=0.5, fidelity_high=1.0, n_draws=300)
    base.update(kw)
    return S.run_simulation(analytic, S.Scenario(**base))


def test_scenario_validation_messages(analytic):
    sample = analytic[analytic.in_primary_sample]
    v = lambda **kw: S.validate_scenario(S.Scenario(**{"name": "x", **kw}), sample)
    assert v() == []
    assert any("between 0 and 100" in p for p in v(value=100.0))
    assert any("between 0 and 100" in p for p in v(value=0.0))
    assert any("cap must be positive" in p for p in v(intervention="cap", value=-3.0))
    assert any("fidelity" in p.lower() for p in v(fidelity_low=0.9, fidelity_high=0.2))
    assert any("Region" in p for p in v(coverage="region", coverage_value="East"))
    assert any("Provide at least one state" in p for p in v(coverage="states", coverage_value=[]))
    assert any("Adamawa" in p for p in v(coverage="states", coverage_value=["Adamawa"]))        # excluded by the data-quality rules
    assert any("Unknown intervention" in p for p in v(intervention="magic"))
    assert any("draws" in p for p in v(n_draws=5))
    assert any("name" in p for p in v(name="  "))


def test_invalid_scenario_raises_before_any_calculation(analytic):
    with pytest.raises(ValueError, match="Invalid scenario"):
        sim(analytic, value=250.0)


def test_noop_scenario_changes_nothing(analytic):
    r = sim(analytic, intervention="cap", value=100000.0)
    assert r["n_states_changed"] == 0
    assert r["headline"]["absolute_change_pp"] == pytest.approx(0.0, abs=1e-12)
    assert all(abs(s["change_pp"]) < 1e-12 for s in r["states"])
    assert r["extra_qualified_teachers_total"] == 0


def test_baseline_equals_observed_data(analytic):
    r = sim(analytic)
    s = analytic[analytic.in_primary_sample]
    obs = np.average(s.oos_total_2021, weights=s.pop6_11_2015)
    assert r["headline"]["baseline_national_oos"] == pytest.approx(obs)


def test_direction_and_dose_response(analytic):
    a, b = sim(analytic, value=10.0), sim(analytic, value=30.0)
    assert a["headline"]["absolute_change_pp"] < 0                       # fewer pupils per teacher -> fewer out-of-school (estimated beta > 0)
    assert b["headline"]["absolute_change_pp"] < a["headline"]["absolute_change_pp"]


def test_coverage_limits_effects_to_covered_states(analytic):
    r = sim(analytic, coverage="region", coverage_value="North")
    for s in r["states"]:
        if s["region"] == "South":
            assert s["covered"] is False and s["change_pp"] == 0 and s["pqtr_new"] == s["pqtr_base"]
        else:
            assert s["covered"] is True and s["pqtr_new"] < s["pqtr_base"]
    with pytest.raises(ValueError, match="no states"):
        sim(analytic, coverage="poverty_min", coverage_value=99.9)


def test_cap_only_touches_states_above_cap(analytic):
    r = sim(analytic, intervention="cap", value=35.0)
    for s in r["states"]:
        assert s["pqtr_new"] == pytest.approx(min(s["pqtr_base"], 35.0), abs=0.01)
        if s["pqtr_base"] <= 35.0:
            assert s["change_pp"] == 0


def test_counterfactual_rates_never_negative(analytic):
    r = sim(analytic, value=95.0)
    assert min(s["oos_cf"] for s in r["states"]) >= 0


def test_implementation_range_scales_point_estimate_separately(analytic):
    r = sim(analytic, value=10.0, fidelity_low=0.5, fidelity_high=1.0)
    full = r["headline"]["absolute_change_pp"]
    lo, hi = sorted(r["headline"]["implementation_range_pp"])
    assert sorted([0.5 * full, full]) == pytest.approx([lo, hi], abs=1e-6)
    assert "separate" in r["headline"]["interval_note"]                  # statistical vs implementation uncertainty are reported apart (plan 9.4)
    assert r["headline"]["statistical_interval_pp"][0] < full < r["headline"]["statistical_interval_pp"][1]


def test_uncertainty_interval_includes_zero_for_current_data(analytic):
    r = sim(analytic, value=20.0, n_draws=2000)
    lo, hi = r["headline"]["statistical_interval_pp"]
    assert lo <= 0 <= hi
    assert any("INCLUDES ZERO" in w for w in r["warnings"])
    assert "consistent with no change" in r["interpretation"]


def test_extrapolation_beyond_observed_support_is_flagged(analytic):
    count = lambda r: sum("below the lowest value observed" in w for w in r["warnings"])
    big, small = sim(analytic, value=90.0), sim(analytic, value=1.0)
    assert any("EXTRAPOLATION" in w for w in big["warnings"])
    assert count(big) >= 25                  # almost every state is pushed far outside the observed range
    assert count(small) <= 2                 # a 1 % cut only leaves the support for the state(s) already at the observed minimum
    assert count(small) < count(big)


def test_excluded_states_are_reported_not_silently_dropped(analytic):
    r = sim(analytic)
    w = " ".join(r["warnings"])
    for st in analytic.loc[~analytic.in_primary_sample, "state"]:
        assert st in w
    assert r["n_states_simulated"] == 31


def test_no_cost_effectiveness_claim_without_cost_data(analytic):
    r = sim(analytic)
    assert any("No cost data" in w for w in r["warnings"])
    blob = str(sorted(r.keys())).lower()
    assert "cost_effect" not in blob and "cheapest" not in str(r).lower()


def test_outcome_and_inequality_are_assessed_separately(analytic):
    r = sim(analytic, coverage="region", coverage_value="North", value=30.0)
    ch = r["inequality"]["change"]
    assert {"gap_north_south", "gap_high_low_poverty", "gini_across_states"} <= set(ch)
    assert ch["gap_north_south"] < 0                                     # all effect lands in the North, so the point estimate narrows the gap
    lo, hi = r["inequality"]["statistical_interval_95"]["gap_north_south"]
    assert lo <= ch["gap_north_south"] <= hi
    assert any(s["group"] == "North" for s in r["subgroups"]) and any(s["group"] == "High poverty" for s in r["subgroups"])


def test_deterministic_and_seed_sensitive(analytic):
    r1, r2 = sim(analytic), sim(analytic)
    assert r1["results_sha256"] == r2["results_sha256"]
    r3 = sim(analytic, seed=7)
    assert r3["headline"]["absolute_change_pp"] == pytest.approx(r1["headline"]["absolute_change_pp"])     # point estimate is seed-free
    assert r3["headline"]["statistical_interval_pp"] != r1["headline"]["statistical_interval_pp"]         # Monte-Carlo interval is not


def test_region_specific_effect_model(analytic):
    r = sim(analytic, effect_model="region_specific", value=20.0)
    assert len(r["model"]["beta_per_log_unit"]) == 2
    assert "exploratory" in r["model"]["description"]


def test_compare_scenarios_uses_common_baseline(analytic):
    rs = [S.run_simulation(analytic, S.Scenario(**{**d, "n_draws": 300})) for d in S.DEFAULT_SCENARIOS]
    tab = S.compare_scenarios(rs)
    assert len(tab) == 3
    assert tab.baseline_oos.nunique() == 1                               # plan 9.4: identical outcome definitions and baselines
    assert (tab.stat_ci_low <= tab.change_pp).all() and (tab.change_pp <= tab.stat_ci_high).all()
