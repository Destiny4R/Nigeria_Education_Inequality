"""Counterfactual policy-simulation engine (plan section 9).

A scenario changes the public pupils-per-qualified-teacher ratio (PQTR) in a set of states.  The
counterfactual OOS rate of state i is

    OOS_cf_i = max(0, OOS_base_i + fidelity * beta_g(i) * [ln(PQTR_new_i) - ln(PQTR_base_i)])

where beta is the percentage-point change in the OOS rate per unit change in ln(PQTR) estimated by the
causal engine (regression adjustment by default).  The baseline is the observed 2021 OOS rate.

What this is - and is not
-------------------------
* It is a *what-if calculation conditional on the estimated effect*, not a forecast.  The estimate comes
  from a cross-section, rests on the identification assumptions listed in the causal module and, in the
  current data, is statistically indistinguishable from zero.  The simulator therefore reports intervals
  that include zero and says so.
* Statistical uncertainty (sampling variability of beta) is propagated by drawing beta from a t
  distribution centred on the estimate; it is reported SEPARATELY from implementation uncertainty
  (the share of the estimated effect actually realised - ``fidelity``), which the user supplies as a range.
* The model has no time dimension: the result is the estimated *long-run difference between otherwise
  similar states* with different PQTR, so ``horizon`` is reported as "not modelled".
* No cost data are available: resource requirements are expressed as additional qualified teachers
  (arithmetic) and the simulator never ranks scenarios by cost-effectiveness.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd
import statsmodels.api as sm

from src.common import sha256_text, stable_json
from src.inequality import metrics as M
from src.causal.engine import CausalConfig, prepare_data, validate_inputs, SEED

EFFECT_MODELS = {
    "pooled_adjusted": "Pooled regression adjustment (poverty + region); one slope for every state",
    "region_specific": "Region-specific slopes (North / South interaction); exploratory, wider intervals",
}
INTERVENTIONS = {
    "pct_reduction": "Proportional reduction of PQTR by X% in covered states",
    "cap": "Bring PQTR down to a maximum of X pupils per qualified teacher in covered states that exceed it",
}
COVERAGE_KINDS = {"all": "All states in the analytical sample", "region": "States in one region (North or South)",
                  "poverty_min": "States with 2018 poverty headcount at or above X%", "states": "An explicit list of states"}

DEFAULT_SCENARIOS = [
    dict(name="S1 Universal cap at 35:1", description="Every state above 35 pupils per qualified teacher is brought down to 35:1 (35:1 is the commonly cited national policy benchmark for primary schools - an assumption to confirm).",
         intervention="cap", value=35.0, coverage="all", coverage_value=None, effect_model="pooled_adjusted", fidelity_low=0.5, fidelity_high=1.0),
    dict(name="S2 20% reduction in the North", description="PQTR falls by 20% in all northern states.",
         intervention="pct_reduction", value=20.0, coverage="region", coverage_value="North", effect_model="pooled_adjusted", fidelity_low=0.5, fidelity_high=1.0),
    dict(name="S3 Targeted cap in high-poverty states", description="States with poverty headcount of at least 40% are brought down to a maximum of 35:1; others unchanged.",
         intervention="cap", value=35.0, coverage="poverty_min", coverage_value=40.0, effect_model="pooled_adjusted", fidelity_low=0.5, fidelity_high=1.0),
]


@dataclass
class Scenario:
    name: str
    intervention: str = "pct_reduction"
    value: float = 10.0
    coverage: str = "all"
    coverage_value: object = None
    effect_model: str = "pooled_adjusted"
    fidelity_low: float = 0.5
    fidelity_high: float = 1.0
    description: str = ""
    n_draws: int = 4000
    seed: int = SEED

    def to_dict(self):
        return asdict(self)


def validate_scenario(sc: Scenario, sample: pd.DataFrame) -> list[str]:
    """Plan 9.4: reject unsupported inputs before any calculation."""
    p = []
    if not str(sc.name).strip():
        p.append("Scenario needs a name")
    if sc.intervention not in INTERVENTIONS:
        p.append(f"Unknown intervention '{sc.intervention}'")
    if sc.effect_model not in EFFECT_MODELS:
        p.append(f"Unknown effect model '{sc.effect_model}'")
    if sc.coverage not in COVERAGE_KINDS:
        p.append(f"Unknown coverage '{sc.coverage}'")
    if sc.intervention == "pct_reduction" and not (0 < sc.value < 100):
        p.append("Percentage reduction must be between 0 and 100 (exclusive)")
    if sc.intervention == "cap" and not (sc.value > 0):
        p.append("PQTR cap must be positive")
    if not (0 <= sc.fidelity_low <= sc.fidelity_high <= 1):
        p.append("Implementation fidelity must satisfy 0 <= low <= high <= 1")
    if sc.coverage == "region" and sc.coverage_value not in ("North", "South"):
        p.append("Region must be 'North' or 'South'")
    if sc.coverage == "poverty_min":
        try:
            float(sc.coverage_value)
        except (TypeError, ValueError):
            p.append("Poverty threshold must be a number")
    if sc.coverage == "states":
        if not sc.coverage_value:
            p.append("Provide at least one state")
        else:
            bad = [s for s in sc.coverage_value if s not in set(sample.state)]
            if bad:
                p.append("States not in the analytical sample (missing treatment/outcome/confounder after quality rules): " + ", ".join(bad))
    if not (100 <= sc.n_draws <= 20000):
        p.append("Number of draws must be between 100 and 20,000")
    return p


def _fit_effect_model(sample: pd.DataFrame, effect_model: str):
    """Return (beta vector aligned to states, covariance information, dof) for the chosen effect model."""
    cfg = CausalConfig()
    d = sample.copy()
    if effect_model == "pooled_adjusted":
        X = sm.add_constant(d[[cfg.treatment, *cfg.confounders]])
        m = sm.OLS(d[cfg.outcome], X).fit(cov_type="HC3", use_t=True)
        i = list(X.columns).index(cfg.treatment)
        mean = np.full(len(d), float(m.params[cfg.treatment]))
        # draws: single coefficient
        return {"kind": "pooled", "mean": float(m.params[cfg.treatment]), "se": float(m.bse[cfg.treatment]), "dof": int(m.df_resid)}
    d["T_x_north"] = d[cfg.treatment] * d["north"]
    X = sm.add_constant(d[[cfg.treatment, "T_x_north", *cfg.confounders]])
    m = sm.OLS(d[cfg.outcome], X).fit(cov_type="HC3", use_t=True)
    cols = list(X.columns)
    cov = m.cov_params().loc[[cfg.treatment, "T_x_north"], [cfg.treatment, "T_x_north"]].to_numpy()
    return {"kind": "region", "mean": np.array([m.params[cfg.treatment], m.params["T_x_north"]], float), "cov": cov, "dof": int(m.df_resid)}


def _covered(sc: Scenario, d: pd.DataFrame) -> pd.Series:
    if sc.coverage == "all":
        return pd.Series(True, index=d.index)
    if sc.coverage == "region":
        return d.region == sc.coverage_value
    if sc.coverage == "poverty_min":
        return d.pov_215 >= float(sc.coverage_value)
    return d.state.isin(list(sc.coverage_value))


def _new_pqtr(sc: Scenario, d: pd.DataFrame, covered: pd.Series) -> pd.Series:
    if sc.intervention == "pct_reduction":
        new = d.pqtr * (1 - sc.value / 100.0)
    else:
        new = np.minimum(d.pqtr, sc.value)
    return pd.Series(np.where(covered, new, d.pqtr), index=d.index)


def _inequality_block(oos: np.ndarray, d: pd.DataFrame) -> dict:
    w = d.pop6_11_2015.to_numpy(float)
    north = (d.region == "North").to_numpy()
    tert = M.poverty_terciles(d)
    hi = (tert == "High poverty").to_numpy()
    lo = (tert == "Low poverty").to_numpy()
    return {"national_weighted_mean": float(np.average(oos, weights=w)),
            "gap_north_south": float(np.average(oos[north], weights=w[north]) - np.average(oos[~north], weights=w[~north])),
            "gap_high_low_poverty": float(np.average(oos[hi], weights=w[hi]) - np.average(oos[lo], weights=w[lo])),
            "gini_across_states": M.gini(oos, w)}


def run_simulation(analytic: pd.DataFrame, sc: Scenario) -> dict:
    """Run one scenario.  Deterministic for a given dataset, scenario and seed."""
    cfg = CausalConfig()
    sample = prepare_data(analytic, cfg)
    problems = validate_inputs(sample, cfg) + validate_scenario(sc, sample)
    if problems:
        raise ValueError("Invalid scenario: " + "; ".join(problems))
    d = sample.copy()
    covered = _covered(sc, d)
    if not covered.any():
        raise ValueError("Invalid scenario: no states in the analytical sample are covered by this scenario")
    new = _new_pqtr(sc, d, covered)
    dlog = np.log(new.to_numpy(float)) - np.log(d.pqtr.to_numpy(float))
    changed = (np.abs(dlog) > 1e-12)
    eff = _fit_effect_model(d, sc.effect_model)
    rng = np.random.default_rng(sc.seed)
    base = d[cfg.outcome].to_numpy(float)
    w = d.pop6_11_2015.to_numpy(float)
    north = (d.region == "North").to_numpy().astype(float)
    # beta draws  (n_draws x n_states) --------------------------------------------------------
    if eff["kind"] == "pooled":
        b = eff["mean"] + eff["se"] * rng.standard_t(eff["dof"], size=sc.n_draws)
        beta_draws = np.repeat(b[:, None], len(d), axis=1)
        beta_point = np.full(len(d), eff["mean"])
    else:
        L = np.linalg.cholesky(eff["cov"])
        z = rng.standard_normal((sc.n_draws, 2)) / np.sqrt(rng.chisquare(eff["dof"], size=(sc.n_draws, 1)) / eff["dof"])
        coef = eff["mean"] + z @ L.T
        beta_draws = coef[:, [0]] + coef[:, [1]] * north[None, :]
        beta_point = eff["mean"][0] + eff["mean"][1] * north
    fid_mid = (sc.fidelity_low + sc.fidelity_high) / 2

    def cf(beta, fid):
        return np.maximum(0.0, base + fid * beta * dlog)

    cf_point = cf(beta_point, 1.0)  # full-fidelity point estimate
    cf_mid = cf(beta_point, fid_mid)
    # statistical-uncertainty interval at full fidelity, national weighted mean
    draws_nat = np.array([np.average(cf(beta_draws[k], 1.0), weights=w) for k in range(sc.n_draws)])
    base_nat = float(np.average(base, weights=w))
    nat_change_draws = draws_nat - base_nat
    stat_ci = np.quantile(nat_change_draws, [0.025, 0.975])
    # separate implementation uncertainty: scale the point estimate by the fidelity range (no statistical noise)
    impl = [float(np.average(cf(beta_point, f), weights=w) - base_nat) for f in (sc.fidelity_low, sc.fidelity_high)]
    # ---- inequality changes (point estimate, full fidelity) + statistical interval ----------------------------------
    ineq_base = _inequality_block(base, d)
    ineq_cf = _inequality_block(cf_point, d)
    ineq_change = {k: ineq_cf[k] - ineq_base[k] for k in ineq_base}
    keys = ["gap_north_south", "gap_high_low_poverty", "gini_across_states"]
    draws_ineq = {k: [] for k in keys}
    for k_ in range(min(sc.n_draws, 2000)):
        blk = _inequality_block(cf(beta_draws[k_], 1.0), d)
        for k in keys:
            draws_ineq[k].append(blk[k] - ineq_base[k])
    ineq_ci = {k: [float(np.quantile(v, 0.025)), float(np.quantile(v, 0.975))] for k, v in draws_ineq.items()}
    # ---- subgroup effects ---------------------------------------------------------------------------------------
    def sub(mask_name, mask):
        if not mask.any():
            return None
        return {"group": mask_name, "n_states": int(mask.sum()), "baseline": float(np.average(base[mask], weights=w[mask])),
                "counterfactual": float(np.average(cf_point[mask], weights=w[mask])),
                "change_pp": float(np.average(cf_point[mask], weights=w[mask]) - np.average(base[mask], weights=w[mask]))}
    tert = M.poverty_terciles(d).to_numpy()
    subgroups = [s for s in [sub("North", north == 1), sub("South", north == 0), sub("Low poverty", tert == "Low poverty"),
                             sub("Middle poverty", tert == "Middle poverty"), sub("High poverty", tert == "High poverty")] + [sub(f"Zone {z}", (d.zone == z).to_numpy()) for z in sorted(d.zone.unique())] if s]
    # ---- per-state table ------------------------------------------------------------------------------------------
    state_tab = pd.DataFrame({"state": d.state, "zone": d.zone, "region": d.region, "covered": covered.to_numpy(), "pqtr_base": d.pqtr.round(2), "pqtr_new": new.round(2),
                              "oos_base": base, "oos_cf": cf_point.round(3), "change_pp": (cf_point - base).round(3),
                              "extra_qualified_teachers": np.where(changed, np.ceil(d.pub_pupils / new - d.pub_pupils / d.pqtr), 0.0)})
    # ---- support / extrapolation warnings --------------------------------------------------------------------------
    warnings = []
    obs_min, obs_max = float(d.pqtr.min()), float(d.pqtr.max())
    for _, r in state_tab[state_tab.covered & (state_tab.pqtr_new != state_tab.pqtr_base)].iterrows():
        reg_min = float(d[d.region == r.region].pqtr.min())
        if r.pqtr_new < obs_min:
            warnings.append(f"{r.state}: target PQTR {r.pqtr_new:.1f} is below the lowest value observed in any sampled state ({obs_min:.1f}) - EXTRAPOLATION beyond the data.")
        elif r.pqtr_new < reg_min:
            warnings.append(f"{r.state}: target PQTR {r.pqtr_new:.1f} is below the lowest value observed among {r.region}ern states ({reg_min:.1f}) - extrapolation beyond regional support.")
    excluded = analytic.loc[~analytic.in_primary_sample, "state"].tolist()
    if excluded:
        warnings.append("States not simulated (missing treatment/outcome/confounder after data-quality rules): " + ", ".join(excluded))
    cap_note = "" if not np.any(cf_point == 0) else " Some counterfactual rates were floored at 0%."
    if stat_ci[0] <= 0 <= stat_ci[1]:
        warnings.append("The statistical interval for the national change INCLUDES ZERO: the data do not rule out no effect.")
    warnings.append("Cross-sectional estimate: the result is a conditional what-if under the causal module's assumptions A1-A7, not a forecast; no time horizon is modelled." + cap_note)
    warnings.append("No cost data: cost-effectiveness is not computed and scenarios must not be ranked by cost. 'Extra qualified teachers' is arithmetic (public pupils / target PQTR minus current qualified teachers), not a budget.")
    n_covered = int((covered & changed).sum())
    nat_cf = float(np.average(cf_point, weights=w))
    result = {
        "scenario": sc.to_dict(),
        "model": {"effect_model": sc.effect_model, "description": EFFECT_MODELS[sc.effect_model],
                  "beta_per_log_unit": (float(eff["mean"]) if eff["kind"] == "pooled" else [float(x) for x in eff["mean"]]),
                  "beta_se": (float(eff["se"]) if eff["kind"] == "pooled" else None), "dof": eff["dof"], "horizon": "not modelled (cross-sectional)"},
        "n_states_simulated": int(len(d)), "n_states_changed": n_covered, "population_weight": "children aged 6-11 (2015/16 projection)",
        "headline": {"baseline_national_oos": base_nat, "counterfactual_national_oos": nat_cf, "absolute_change_pp": nat_cf - base_nat,
                     "relative_change_pct": (nat_cf / base_nat - 1) * 100 if base_nat else None,
                     "statistical_interval_pp": [float(stat_ci[0]), float(stat_ci[1])],
                     "implementation_range_pp": sorted(impl), "midpoint_fidelity_change_pp": float(np.average(cf_mid, weights=w) - base_nat),
                     "interval_note": "Statistical interval (95%) reflects sampling uncertainty of the estimated effect at full implementation; the implementation range scales the point estimate by the fidelity range. They are separate sources of uncertainty and are not combined."},
        "inequality": {"baseline": ineq_base, "counterfactual": ineq_cf, "change": ineq_change, "statistical_interval_95": ineq_ci},
        "subgroups": subgroups,
        "states": state_tab.to_dict("records"),
        "extra_qualified_teachers_total": float(state_tab.extra_qualified_teachers.sum()),
        "warnings": warnings,
        "assumptions": ["Effect estimated from the causal module (cross-sectional adjusted association; assumptions A1-A7).", "Linear in log(PQTR); effects outside the observed PQTR range are extrapolations.",
                        "No spillovers between states; no change in other inputs (poverty, funding, security).", "Baseline = observed 2021 MICS rates.", f"Implementation fidelity range {sc.fidelity_low:.2f}-{sc.fidelity_high:.2f} is a user assumption, not an estimate."],
        "interpretation": interpret(nat_cf - base_nat, stat_ci, ineq_change, ineq_ci),
    }
    result["results_sha256"] = sha256_text(stable_json(result))
    return result


def interpret(change, ci, ineq_change, ineq_ci) -> str:
    s = f"Estimated national change {change:+.2f} pp (95% statistical interval {ci[0]:+.2f} to {ci[1]:+.2f}). "
    if ci[0] <= 0 <= ci[1]:
        s += "The interval includes zero, so the data are consistent with no change. "
    g = ineq_change["gap_north_south"]
    gi = ineq_ci["gap_north_south"]
    s += f"The North-South gap changes by {g:+.2f} pp (95% interval {gi[0]:+.2f} to {gi[1]:+.2f}); "
    if gi[0] <= 0 <= gi[1]:
        s += "because the interval includes zero, a narrowing of the gap cannot be distinguished from no change."
    elif gi[1] < 0:
        s += "the whole interval lies below zero, i.e. the gap narrows under the model's assumptions."
    else:
        s += "the whole interval lies above zero, i.e. the gap widens under the model's assumptions."
    return s


def compare_scenarios(results: list[dict]) -> pd.DataFrame:
    """Side-by-side table; all scenarios share the same outcome definition, baseline and population weights."""
    rows = []
    for r in results:
        h = r["headline"]
        i = r["inequality"]
        rows.append({"scenario": r["scenario"]["name"], "states_changed": r["n_states_changed"], "baseline_oos": h["baseline_national_oos"],
                     "counterfactual_oos": h["counterfactual_national_oos"], "change_pp": h["absolute_change_pp"], "stat_ci_low": h["statistical_interval_pp"][0],
                     "stat_ci_high": h["statistical_interval_pp"][1], "north_south_gap_change_pp": i["change"]["gap_north_south"],
                     "ns_gap_ci_low": i["statistical_interval_95"]["gap_north_south"][0], "ns_gap_ci_high": i["statistical_interval_95"]["gap_north_south"][1],
                     "extra_qualified_teachers": r["extra_qualified_teachers_total"]})
    return pd.DataFrame(rows)
