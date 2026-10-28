"""Descriptive educational-inequality engine (plan section 7).

Every function documents its denominator / weighting / missing-data rule, because the plan requires
each indicator to define them.  All functions are pure (no I/O), deterministic, and are covered by
tests that compare them with independently computed values.

Conventions
-----------
* Rates are percentages (0-100) unless stated otherwise.
* Rows with a missing value (or missing weight) are dropped listwise *for that indicator only*; the
  number used is always returned so the caller can display it.
* "Disadvantage" direction: for out-of-school (OOS) rates a *higher* value is worse.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------------------------
# Basic gaps and ratios
# ----------------------------------------------------------------------------------------
def absolute_gap(a: float, b: float) -> float:
    """G = A - B (percentage points for rates), e.g. Rural - Urban OOS rate."""
    return float(a) - float(b)


def relative_gap(a: float, b: float) -> float:
    """Ratio A / B.  Undefined (NaN) when B == 0."""
    return float(a) / float(b) if float(b) != 0 else float("nan")


def _clean(x, w=None):
    x = np.asarray(x, dtype=float)
    w = np.ones_like(x) if w is None else np.asarray(w, dtype=float)
    m = np.isfinite(x) & np.isfinite(w) & (w > 0)
    return x[m], w[m]


def weighted_mean(x, w=None) -> float:
    x, w = _clean(x, w)
    return float(np.sum(x * w) / np.sum(w)) if len(x) else float("nan")


# ----------------------------------------------------------------------------------------
# Summary inequality measures for a distribution of non-negative values across units
# ----------------------------------------------------------------------------------------
def lorenz_points(x, w=None) -> pd.DataFrame:
    """Lorenz curve (population share vs share of the total of x), units sorted ascending by x."""
    x, w = _clean(x, w)
    if len(x) == 0 or np.any(x < 0):
        raise ValueError("Lorenz curve needs non-negative values")
    o = np.argsort(x, kind="mergesort")
    x, w = x[o], w[o]
    F = np.concatenate([[0.0], np.cumsum(w) / w.sum()])
    tot = np.sum(x * w)
    L = np.concatenate([[0.0], np.cumsum(x * w) / tot]) if tot > 0 else np.linspace(0, 1, len(x) + 1)
    return pd.DataFrame({"pop_share": F, "value_share": L})


def gini(x, w=None) -> float:
    """Weighted Gini coefficient, G = 1 - sum (F_i - F_{i-1})(L_i + L_{i-1}).

    Suitable for non-negative *numerical* distributions across units (e.g. the OOS rate or the
    number of qualified teachers per pupil across states, weighted by child population).  It is not
    meaningful for categorical variables and is not applied to group labels.
    """
    lz = lorenz_points(x, w)
    F, L = lz.pop_share.to_numpy(), lz.value_share.to_numpy()
    return float(1.0 - np.sum((F[1:] - F[:-1]) * (L[1:] + L[:-1])))


def theil_t(x, w=None) -> float:
    """Weighted Theil T index; 0 = perfect equality.  Zero values contribute 0 (limit x ln x -> 0)."""
    x, w = _clean(x, w)
    if len(x) == 0 or np.any(x < 0):
        raise ValueError("Theil needs non-negative values")
    mu = np.sum(x * w) / np.sum(w)
    if mu == 0:
        return 0.0
    r = x / mu
    with np.errstate(divide="ignore", invalid="ignore"):
        term = np.where(r > 0, r * np.log(r), 0.0)
    return float(np.sum(w * term) / np.sum(w))


def coefficient_of_variation(x, w=None) -> float:
    x, w = _clean(x, w)
    mu = np.sum(x * w) / np.sum(w)
    var = np.sum(w * (x - mu) ** 2) / np.sum(w)
    return float(np.sqrt(var) / mu) if mu else float("nan")


# ----------------------------------------------------------------------------------------
# Socio-economic gradient measures (grouped data)
# ----------------------------------------------------------------------------------------
def ridit_midpoints(weights) -> np.ndarray:
    """Fractional rank (mid-point of each group's cumulative population share); groups ordered from
    most disadvantaged (rank near 0) to most advantaged (rank near 1)."""
    w = np.asarray(weights, dtype=float)
    p = w / w.sum()
    return np.cumsum(p) - p / 2


def concentration_index(rates, weights, kind: str = "wagstaff") -> float:
    """Concentration index of a *rate* (0-100) over socio-economic groups ordered from the most
    disadvantaged to the most advantaged.

    C = (2 / mu) * sum_i p_i * mu_i * R_i - 1, with R_i the ridit mid-point.  Negative values mean the
    outcome is concentrated among the disadvantaged (for OOS: pro-poor concentration of a bad).
    kind = 'standard' -> C ;  'wagstaff' -> C / (1 - mu)  (bounded rates) ;
           'erreygers' -> 4 * mu * C  (bounded in [0, 1] proportions; Erreygers 2009).
    Rates are converted to proportions internally.
    """
    r = np.asarray(rates, dtype=float) / 100.0
    w = np.asarray(weights, dtype=float)
    p = w / w.sum()
    mu = float(np.sum(p * r))
    R = ridit_midpoints(w)
    C = 2.0 / mu * float(np.sum(p * r * R)) - 1.0
    if kind == "standard":
        return C
    if kind == "wagstaff":
        return C / (1.0 - mu)
    if kind == "erreygers":
        return 4.0 * mu * C
    raise ValueError(kind)


def slope_index_of_inequality(rates, weights) -> dict:
    """SII and RII (WHO/Mackenbach-Kunst).  Regress the group rate on the ridit mid-point (weighted
    by group size).  SII = predicted(rank 1) - predicted(rank 0) in percentage points (negative for a
    bad outcome concentrated among the disadvantaged, whose rank is low).  RII = ratio of fitted rates at
    rank 0 vs rank 1 from a log-linear fit."""
    r = np.asarray(rates, dtype=float)
    w = np.asarray(weights, dtype=float)
    R = ridit_midpoints(w)
    W = w / w.sum()
    xm = np.sum(W * R)
    ym = np.sum(W * r)
    slope = np.sum(W * (R - xm) * (r - ym)) / np.sum(W * (R - xm) ** 2)
    icpt = ym - slope * xm
    p0, p1 = icpt, icpt + slope
    out_of_range = bool(p0 < 0 or p1 < 0 or p0 > 100 or p1 > 100)
    # log-linear RII: ratio of the fitted rate at rank 0 to rank 1 (valid when all rates > 0)
    rii = float("nan")
    if np.all(r > 0):
        lr = np.log(r)
        lm = np.sum(W * lr)
        b = np.sum(W * (R - xm) * (lr - lm)) / np.sum(W * (R - xm) ** 2)
        rii = float(np.exp(-b))
    return {"sii": float(slope), "pred_most_disadvantaged": float(p0), "pred_most_advantaged": float(p1),
            "sii_out_of_range": out_of_range, "rii": rii,
            "note": "Linear SII extrapolates outside 0-100% when the gradient is convex; interpret it together with the log-linear RII."}


# ----------------------------------------------------------------------------------------
# State-level helpers
# ----------------------------------------------------------------------------------------
def group_summary(df: pd.DataFrame, value: str, by: str, weight: str | None = None) -> pd.DataFrame:
    """Weighted mean, min, max and n of ``value`` by ``by`` (listwise deletion for value/weight)."""
    cols = [value, by] + ([weight] if weight else [])
    d = df[cols].dropna()
    rows = []
    for g, s in d.groupby(by, sort=False):
        w = s[weight] if weight else None
        rows.append({by: g, "n_states": len(s), "mean": weighted_mean(s[value], w), "min": s[value].min(), "max": s[value].max()})
    return pd.DataFrame(rows)


def bootstrap_group_gap(df: pd.DataFrame, value: str, group: str, high: str, low: str, weight: str | None = None,
                        n_boot: int = 2000, seed: int = 20260101, alpha: float = 0.05) -> dict:
    """Percentile-bootstrap interval for the weighted-mean gap (high - low) between two groups of states.

    The units resampled are *states* within each group.  The interval therefore describes how much the
    gap depends on which states fall in each group; it is NOT a survey sampling-error interval, and is
    reported only where both groups contain at least 5 states.
    """
    d = df[[value, group] + ([weight] if weight else [])].dropna()
    a = d[d[group] == high]
    b = d[d[group] == low]
    if len(a) < 5 or len(b) < 5:
        return {"gap": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"), "n_high": len(a), "n_low": len(b), "note": "too few states for an interval"}
    rng = np.random.default_rng(seed)

    def wm(s):
        return weighted_mean(s[value], s[weight] if weight else None)

    gap = wm(a) - wm(b)
    boots = []
    for _ in range(n_boot):
        ia = rng.integers(0, len(a), len(a))
        ib = rng.integers(0, len(b), len(b))
        boots.append(wm(a.iloc[ia]) - wm(b.iloc[ib]))
    lo, hi = np.quantile(boots, [alpha / 2, 1 - alpha / 2])
    return {"gap": float(gap), "ci_low": float(lo), "ci_high": float(hi), "n_high": len(a), "n_low": len(b),
            "note": "State-resampling bootstrap; not a survey sampling-error interval."}


def poverty_terciles(df: pd.DataFrame, col: str = "pov_215") -> pd.Series:
    """Label states Low / Middle / High poverty by tercile (ties broken by rank order)."""
    r = df[col].rank(method="first")
    n = r.notna().sum()
    out = pd.Series(index=df.index, dtype=object)
    out[r <= n / 3] = "Low poverty"
    out[(r > n / 3) & (r <= 2 * n / 3)] = "Middle poverty"
    out[r > 2 * n / 3] = "High poverty"
    return out


# ----------------------------------------------------------------------------------------
# Indicator catalogue (plan 6.2 IndicatorDefinition)
# ----------------------------------------------------------------------------------------
INDICATORS: dict[str, dict] = {
    "oos_total_2021": dict(label="Primary out-of-school rate, 2021 (MICS6)", unit="% of primary-age children", direction="higher_worse",
                           denominator="Children of primary-school age (household survey sample)", weighting="Survey-weighted by UNICEF/NBS; state rates used as published (rounded to whole %)",
                           missing_rule="No imputation; none missing", source="UNICEF-MICS6-2021", comparable=True,
                           interpretation="Share of primary-age children not attending school; the primary outcome of the project."),
    "oos_male_2021": dict(label="Primary OOS rate, boys, 2021", unit="%", direction="higher_worse", denominator="Boys of primary-school age", weighting="As above", missing_rule="No imputation", source="UNICEF-MICS6-2021", comparable=True, interpretation="Sex-specific component of the primary outcome."),
    "oos_female_2021": dict(label="Primary OOS rate, girls, 2021", unit="%", direction="higher_worse", denominator="Girls of primary-school age", weighting="As above", missing_rule="No imputation", source="UNICEF-MICS6-2021", comparable=True, interpretation="Sex-specific component of the primary outcome."),
    "pov_215": dict(label="Poverty headcount at $2.15/day, 2018", unit="% of population", direction="higher_worse", denominator="Population", weighting="As published", missing_rule="Borno missing; no imputation", source="WB-GPP-2018", comparable=True, interpretation="Socio-economic confounder / grouping variable (secondary compilation)."),
    "pqtr": dict(label="Public pupils per qualified teacher, 2016/17", unit="pupils per teacher", direction="higher_worse", denominator="Qualified public primary teachers (NCE and above as defined in the Digest)", weighting="Unweighted ratio of state totals", missing_rule="Set to missing where integrity rules R04/R06 fail", source="FME-DIGEST-2017", comparable=True, interpretation="Treatment / resource indicator. Computed from counts, not from the printed ratio column."),
    "ptr": dict(label="Public pupils per teacher (all), 2016/17", unit="pupils per teacher", direction="higher_worse", denominator="All public primary teachers", weighting="Unweighted ratio of state totals", missing_rule="As PQTR", source="FME-DIGEST-2017", comparable=True, interpretation="Alternative resource indicator."),
    "pct_qualified_calc": dict(label="Qualified share of public primary teachers, 2016/17", unit="%", direction="higher_better", denominator="All public primary teachers", weighting="Ratio of state totals", missing_rule="As PQTR", source="FME-DIGEST-2017", comparable=True, interpretation="Teacher quality indicator recomputed from counts."),
    "private_share_enrol": dict(label="Private share of primary enrolment, 2016/17", unit="%", direction="neutral", denominator="Total primary pupils", weighting="Ratio of state totals", missing_rule="Missing where totals fail integrity checks", source="FME-DIGEST-2017", comparable=True, interpretation="School-sector composition."),
    "female_share_total": dict(label="Girls' share of primary enrolment, 2016/17", unit="%", direction="neutral", denominator="Total primary pupils", weighting="Ratio of state totals", missing_rule="Missing where totals fail integrity checks", source="FME-DIGEST-2017", comparable=True, interpretation="Gender parity indicator (50% = parity of enrolment counts, not of rates)."),
    "etpr_2015": dict(label="Enrolment-to-population ratio, age 6-11, 2015/16", unit="%", direction="higher_better", denominator="Projected population age 6-11", weighting="Ratio of state totals", missing_rule="Rows failing duplicate/identity checks set missing", source="FME-OOS-2015", comparable=False, interpretation="Administrative baseline access measure; denominators are projections so it is NOT comparable with the 2021 survey rate."),
}


def state_ranking(df: pd.DataFrame, value: str, ascending: bool = False) -> tuple[pd.DataFrame, list[str]]:
    """Rank states on a comparable indicator.  Returns (table, warnings).  States whose value is missing
    or flagged by a critical rule are listed in the warnings instead of being ranked silently."""
    meta = INDICATORS.get(value, {})
    warnings = []
    if meta and not meta.get("comparable", True):
        warnings.append(f"{meta['label']} is not comparable across states/years; ranking shown for orientation only.")
    d = df[["state", "zone", value, "flags"]].copy()
    miss = d[d[value].isna()].state.tolist()
    if miss:
        warnings.append("Not ranked (value missing after quality rules): " + ", ".join(miss))
    d = d.dropna(subset=[value]).sort_values(value, ascending=ascending).reset_index(drop=True)
    d.insert(0, "rank", np.arange(1, len(d) + 1))
    return d, warnings


def state_inequality_profile(df: pd.DataFrame, value: str = "oos_total_2021", weight: str = "pop6_11_2015") -> dict:
    """Population-weighted summary of dispersion across states for one indicator."""
    d = df[["state", "zone", "region", value, weight]].dropna(subset=[value, weight])
    x, w = d[value].to_numpy(), d[weight].to_numpy()
    hi = d.loc[d[value].idxmax()]
    lo = d.loc[d[value].idxmin()]
    return {
        "n_states": int(len(d)),
        "weighted_mean": weighted_mean(x, w),
        "unweighted_mean": float(np.mean(x)),
        "min": {"state": lo["state"], "value": float(lo[value])},
        "max": {"state": hi["state"], "value": float(hi[value])},
        "range": float(x.max() - x.min()),
        "max_min_ratio": relative_gap(x.max(), x.min()),
        "p90_p10_ratio": relative_gap(np.quantile(x, .9), np.quantile(x, .1)),
        "gini": gini(x, w),
        "theil_t": theil_t(x, w),
        "cv": coefficient_of_variation(x, w),
        "weight": weight,
    }


def regional_gap(df: pd.DataFrame, value: str = "oos_total_2021", weight: str = "pop6_11_2015") -> dict:
    out = bootstrap_group_gap(df, value, "region", "North", "South", weight)
    g = group_summary(df, value, "region", weight)
    out["means"] = {r.region: float(r["mean"]) for _, r in g.iterrows()}
    out["ratio"] = relative_gap(out["means"].get("North", np.nan), out["means"].get("South", np.nan))
    return out


def zone_summary(df: pd.DataFrame, value: str = "oos_total_2021", weight: str = "pop6_11_2015") -> pd.DataFrame:
    return group_summary(df, value, "zone", weight).sort_values("mean", ascending=False).reset_index(drop=True)


def gender_gap_table(df: pd.DataFrame) -> pd.DataFrame:
    """Girls minus boys OOS (pp) and the girls/boys ratio, per state (MICS 2021)."""
    d = df[["state", "zone", "oos_male_2021", "oos_female_2021"]].dropna().copy()
    d["gap_pp"] = d.oos_female_2021 - d.oos_male_2021
    d["ratio_f_m"] = np.where(d.oos_male_2021 > 0, d.oos_female_2021 / d.oos_male_2021, np.nan)
    return d.sort_values("gap_pp", ascending=False).reset_index(drop=True)


def national_group_analysis(groups: pd.DataFrame, level: str = "oos_primary") -> dict:
    """Wealth / area / sex gaps from the national MICS table (no weights available: quintiles are
    treated as equal-sized, which is how MICS defines wealth quintiles of the *household population*;
    child-population shares can differ slightly)."""
    g = groups.set_index(["group_type", "group"])[level]
    wealth = g["wealth"].loc[["Poorest", "Second", "Middle", "Fourth", "Richest"]]
    area = g["area"]
    sex = g["sex"]
    w = np.ones(5)
    out = {
        "level": level,
        "total": float(g[("total", "Total")]),
        "wealth": {"rates": wealth.to_dict(),
                   "absolute_gap_poorest_richest": absolute_gap(wealth["Poorest"], wealth["Richest"]),
                   "ratio_poorest_richest": relative_gap(wealth["Poorest"], wealth["Richest"]),
                   "concentration_index_wagstaff": concentration_index(wealth.to_numpy(), w, "wagstaff"),
                   "concentration_index_erreygers": concentration_index(wealth.to_numpy(), w, "erreygers"),
                   **slope_index_of_inequality(wealth.to_numpy(), w)},
        "area": {"rates": area.to_dict(), "absolute_gap_rural_urban": absolute_gap(area["Rural"], area["Urban"]), "ratio_rural_urban": relative_gap(area["Rural"], area["Urban"])},
        "sex": {"rates": sex.to_dict(), "absolute_gap_female_male": absolute_gap(sex["Female"], sex["Male"]), "ratio_female_male": relative_gap(sex["Female"], sex["Male"])},
        "note": "Rates are rounded to whole percentages as printed; no confidence intervals are available, so small gaps (e.g. by sex) may not be statistically distinguishable.",
    }
    return out


def resource_inequality(df: pd.DataFrame) -> dict:
    """Distribution of qualified-teacher provision.  The Gini is computed on qualified teachers PER
    1,000 PUPILS (1000 / PQTR), weighted by public pupils, across states with a valid PQTR."""
    d = df[["state", "pqtr", "pub_pupils"]].dropna()
    d = d[d.pqtr > 0]
    x = 1000.0 / d.pqtr.to_numpy()
    w = d.pub_pupils.to_numpy()
    return {"n_states": int(len(d)), "gini_qualified_teachers_per_1000_pupils": gini(x, w),
            "pqtr_min": float(d.pqtr.min()), "pqtr_median": float(d.pqtr.median()), "pqtr_max": float(d.pqtr.max()),
            "pqtr_max_min_ratio": relative_gap(d.pqtr.max(), d.pqtr.min())}


def poverty_gradient(df: pd.DataFrame, value: str = "oos_total_2021", weight: str = "pop6_11_2015") -> dict:
    """Concentration index of OOS across states ordered by poverty (poorest state = lowest rank)."""
    d = df[[value, "pov_215", weight]].dropna().sort_values("pov_215", ascending=False)
    ci = concentration_index(d[value].to_numpy(), d[weight].to_numpy(), "wagstaff")
    return {"n_states": int(len(d)), "concentration_index_wagstaff": ci,
            "spearman_oos_poverty": float(d[value].rank().corr(d["pov_215"].rank())),
            "note": "States ordered by 2018 poverty headcount (poorest first). Negative values: OOS concentrated in poorer states. Ecological (state-level) gradient only - not a household-level result."}


def national_trends(series: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Per-indicator national time series from WDI using the cleaned (outlier-removed) values."""
    out = {}
    for code, g in series.groupby("indicator_code"):
        out[code] = g.sort_values("year")[["year", "value", "value_clean", "flag"]].reset_index(drop=True)
    return out


def trend_change(g: pd.DataFrame) -> dict:
    """First/last available cleaned observation and the change between them."""
    v = g.dropna(subset=["value_clean"])
    if len(v) < 2:
        return {}
    a, b = v.iloc[0], v.iloc[-1]
    return {"from_year": int(a.year), "to_year": int(b.year), "from": float(a.value_clean), "to": float(b.value_clean), "change": float(b.value_clean - a.value_clean)}


def filter_states(df: pd.DataFrame, states: Iterable[str] | None = None, region: str | None = None, zone: str | None = None,
                  poverty_group: str | None = None) -> pd.DataFrame:
    d = df.copy()
    d["poverty_group"] = poverty_terciles(d)
    if states:
        d = d[d.state.isin(list(states))]
    if region and region != "All":
        d = d[d.region == region]
    if zone and zone != "All":
        d = d[d.zone == zone]
    if poverty_group and poverty_group != "All":
        d = d[d.poverty_group == poverty_group]
    return d
