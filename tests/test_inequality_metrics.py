"""Inequality indicators checked against independently computed values (plan 11.4: results match independently
calculated test cases).  Independent calculations use only numpy and different algebra from the module."""
import math

import numpy as np
import pandas as pd
import pytest

from src.inequality import metrics as M


def test_plan_example_absolute_gap():
    # Plan 7.1: urban 85 %, rural 65 % -> 20 percentage points (illustrative figures in the plan)
    assert M.absolute_gap(85, 65) == 20
    assert M.relative_gap(85, 65) == pytest.approx(85 / 65)


def test_relative_gap_zero_denominator_is_nan_not_inf():
    assert math.isnan(M.relative_gap(5, 0))


def test_gini_equality_and_extreme():
    assert M.gini([5, 5, 5, 5]) == pytest.approx(0.0, abs=1e-12)
    assert M.gini([0, 0, 0, 1]) == pytest.approx(0.75)           # (n-1)/n for one unit holding everything


def test_gini_matches_mean_absolute_difference_formula():
    x = np.array([1.0, 2.0, 4.0, 8.0, 20.0])
    mad = np.abs(x[:, None] - x[None, :]).mean()                 # G = sum|xi-xj| / (2 n^2 mu)
    assert M.gini(x) == pytest.approx(mad / (2 * x.mean()))


def test_weighted_gini_equals_gini_of_replicated_units():
    x = [2.0, 5.0, 11.0]
    w = [3, 1, 2]
    rep = np.repeat(x, w)
    assert M.gini(x, w) == pytest.approx(M.gini(rep))


def test_theil_t_independent():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    mu = x.mean()
    expected = np.mean((x / mu) * np.log(x / mu))
    assert M.theil_t(x) == pytest.approx(expected)
    assert M.theil_t([3, 3, 3]) == pytest.approx(0.0, abs=1e-12)


def test_theil_handles_zero_values():
    assert np.isfinite(M.theil_t([0.0, 1.0, 2.0]))


def test_negative_values_rejected():
    with pytest.raises(ValueError):
        M.gini([1, -1, 2])
    with pytest.raises(ValueError):
        M.theil_t([1, -1])


def test_cv_and_weighted_mean():
    x = np.array([10.0, 20.0, 30.0])
    assert M.coefficient_of_variation(x) == pytest.approx(x.std() / x.mean())
    assert M.weighted_mean([10, 20], [1, 3]) == pytest.approx(17.5)


def test_missing_values_dropped_listwise():
    assert M.weighted_mean([10, np.nan, 30], [1, 1, 1]) == pytest.approx(20.0)
    assert M.weighted_mean([10, 30, 50], [1, 1, np.nan]) == pytest.approx(20.0)
    assert math.isnan(M.weighted_mean([np.nan], None))


def test_lorenz_endpoints_monotone():
    lz = M.lorenz_points([1, 3, 6, 10], [1, 1, 2, 1])
    assert lz.pop_share.iloc[0] == 0 and lz.pop_share.iloc[-1] == pytest.approx(1)
    assert lz.value_share.iloc[-1] == pytest.approx(1)
    assert (np.diff(lz.value_share) >= 0).all()
    assert (lz.value_share <= lz.pop_share + 1e-12).all()        # below the line of equality


def test_ridit_midpoints_equal_groups():
    assert M.ridit_midpoints([1, 1, 1, 1, 1]) == pytest.approx([0.1, 0.3, 0.5, 0.7, 0.9])


def test_slope_index_exact_for_linear_gradient():
    # rates fall linearly with rank: 60 - 50 * rank -> SII = -50, predictions 60 and 10
    ranks = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
    rates = 60 - 50 * ranks
    out = M.slope_index_of_inequality(rates, [1] * 5)
    assert out["sii"] == pytest.approx(-50)
    assert out["pred_most_disadvantaged"] == pytest.approx(60)
    assert out["pred_most_advantaged"] == pytest.approx(10)
    assert out["rii"] == pytest.approx(60 / 10, rel=0.25)      # log-linear ratio is close, not identical, for linear data
    assert out["sii_out_of_range"] is False


def test_sii_flags_out_of_range_extrapolation():
    out = M.slope_index_of_inequality([58, 33, 15, 9, 5], [1] * 5)   # the real MICS6 wealth gradient is convex
    assert out["sii_out_of_range"] is True


def test_concentration_index_matches_covariance_form():
    rates = np.array([58.0, 33.0, 15.0, 9.0, 5.0])
    w = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
    p = w / w.sum()
    R = np.cumsum(p) - p / 2
    h = rates / 100
    mu = (p * h).sum()
    cov = (p * (h - mu) * (R - (p * R).sum())).sum()
    C = 2 * cov / mu
    assert M.concentration_index(rates, w, "standard") == pytest.approx(C)
    assert M.concentration_index(rates, w, "wagstaff") == pytest.approx(C / (1 - mu))
    assert M.concentration_index(rates, w, "erreygers") == pytest.approx(4 * mu * C)
    assert C < 0                                              # bad outcome concentrated among the poorest


def test_concentration_index_zero_when_equal():
    assert M.concentration_index([20, 20, 20, 20], [1, 2, 3, 4], "standard") == pytest.approx(0.0, abs=1e-12)
    with pytest.raises(ValueError):
        M.concentration_index([1, 2], [1, 1], "nonsense")


def test_state_inequality_profile_on_toy_data():
    df = pd.DataFrame({"state": list("ABCD"), "zone": "NW", "region": "North", "oos": [10.0, 20.0, 30.0, np.nan], "w": [1, 1, 2, 5]})
    prof = M.state_inequality_profile(df, "oos", "w")
    assert prof["n_states"] == 3                               # the NaN row is not used
    assert prof["weighted_mean"] == pytest.approx((10 + 20 + 60) / 4)
    assert prof["max"]["value"] == 30 and prof["min"]["value"] == 10


def test_state_ranking_excludes_missing_and_warns():
    df = pd.DataFrame({"state": ["A", "B", "C"], "zone": "NW", "flags": "", "v": [5.0, np.nan, 9.0]})
    ranking, warnings = M.state_ranking(df, "v")
    assert list(ranking.state) == ["C", "A"]
    assert warnings and "B" in " ".join(warnings)              # plan 7.2: no ranking of incomplete data without a warning


def test_bootstrap_gap_reproducible_and_brackets_point():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"v": np.r_[rng.normal(36, 8, 20), rng.normal(6, 3, 17)], "g": ["N"] * 20 + ["S"] * 17})
    a = M.bootstrap_group_gap(df, "v", "g", "N", "S")
    b = M.bootstrap_group_gap(df, "v", "g", "N", "S")
    assert a == b
    assert a["ci_low"] < a["gap"] < a["ci_high"]
