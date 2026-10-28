"""Causal analysis engine (plan section 8).

Causal question (documented, fixed for the minimum viable system)
-----------------------------------------------------------------
Treatment : log of public pupils per *qualified* teacher, 2016/17 (``log_pqtr``; lower = more qualified
            teachers per pupil).  A 10% reduction in PQTR has the effect  beta * ln(0.9).
Outcome   : primary out-of-school rate, MICS6 2021 (``oos_total_2021``), % of primary-age children.
Confounders (adjustment set under the assumed graph): poverty headcount 2018 and a North/South indicator.
Estimand  : average treatment effect (ATE) of a marginal proportional change in PQTR on the state
            OOS rate, in percentage points, over the states in the analytical sample.

Design limitation (stated, not hidden)
--------------------------------------
The data are ONE cross-section of at most 37 states, with a single outcome wave.  No credible
instrument, no pre/post comparison and no repeated outcome measurement are available, so
difference-in-differences, fixed effects and IV are *not applicable* (see ``method_applicability``).  The
estimates are therefore *adjusted associations that are interpreted causally only under the stated
conditional-ignorability assumption*; the sensitivity analysis quantifies how strong an omitted
confounder would have to be to change the conclusion.
"""
from __future__ import annotations

import logging
import platform
import warnings
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from src.common import round_floats, sha256_text, stable_json

SEED = 20260101
TREATMENT = "log_pqtr"
OUTCOME = "oos_total_2021"
CONFOUNDERS = ["pov_215", "north"]
LN090 = float(np.log(0.9))

OUTCOME_LABELS = {
    "oos_total_2021": "Primary OOS rate 2021 [outcome]",
    "oos_male_2021": "Boys' primary OOS rate 2021 [outcome]",
    "oos_female_2021": "Girls' primary OOS rate 2021 [outcome]",
}
CONFOUNDER_LABELS = {
    "pov_215": "Poverty headcount 2018 ($2.15/day)",
    "north": "North/South region (1 = North)",
}


def build_graphs(outcome: str = OUTCOME, confounders: tuple | None = None, treatment: str = TREATMENT) -> tuple[dict, dict]:
    """Identifying + threat DAG for the given outcome and adjustment set: every allowed confounder is a
    common cause of the treatment and the outcome, so backdoor adjustment on it identifies the effect."""
    outcome = outcome or OUTCOME
    if confounders is None:
        confounders = tuple(CONFOUNDERS)
    confounders = tuple(c for c in confounders if c != outcome and c != treatment)
    nodes = {"log_pqtr": "log(pupils per qualified teacher), 2016/17 [treatment]",
             outcome: OUTCOME_LABELS.get(outcome, f"{outcome} [outcome]")}
    for c in confounders:
        nodes[c] = CONFOUNDER_LABELS.get(c, c)
    edges = [("north", "pov_215")] if {"north", "pov_215"} <= set(confounders) else []
    edges += [(c, treatment) for c in confounders] + [(c, outcome) for c in confounders] + [(treatment, outcome)]
    identifying = {"nodes": nodes, "edges": edges}
    threat = {**identifying, "unobserved": {"U": "Unmeasured state capacity, insecurity/conflict, cultural attitudes to schooling, school funding"},
              "edges_unobserved": [("U", treatment), ("U", outcome)]}
    return identifying, threat


GRAPH_IDENTIFYING, GRAPH_THREAT = build_graphs()

ASSUMPTIONS = [
    "A1 Conditional ignorability: given poverty (2018) and region, states' PQTR is as good as randomly assigned with respect to potential OOS outcomes (no unmeasured common causes).",
    "A2 Positivity/overlap: states with similar poverty and region show a range of PQTR values (checked with overlap diagnostics).",
    "A3 Consistency / SUTVA: no spillovers of teachers or pupils between states; 'a 10% lower PQTR' is a well-defined intervention.",
    "A4 Temporal order: PQTR (2016/17) precedes the outcome (2021); poverty (2018) is treated as pre-treatment although it could be partly shaped by earlier schooling (tested by dropping it).",
    "A5 Functional form: the effect is linear in log(PQTR) and additive in the confounders (tested with alternative forms and DML).",
    "A6 Measurement: PQTR from the Digest and OOS from MICS are measured without systematic error related to the other variable (administrative reporting errors are documented and the worst rows excluded).",
    "A7 Excluded variables: private-school share and enrolment rates are possible mediators/colliders and are deliberately NOT adjusted for.",
]


# ----------------------------------------------------------------------------------------
@dataclass
class CausalConfig:
    treatment: str = TREATMENT
    outcome: str = OUTCOME
    confounders: tuple = tuple(CONFOUNDERS)
    n_boot: int = 1000
    n_refute: int = 100
    dml_repeats: int = 10
    seed: int = SEED
    run_dowhy: bool = True
    run_dml: bool = True

    def to_dict(self):
        d = asdict(self)
        d["confounders"] = list(self.confounders)
        return d


def prepare_data(analytic: pd.DataFrame, cfg: CausalConfig | None = None) -> pd.DataFrame:
    """Rows of the primary sample with the analysis variables (sorted by state for determinism)."""
    s = analytic[analytic["in_primary_sample"]].copy()
    s["north"] = (s["region"] == "North").astype(int)
    s = s.sort_values("state").reset_index(drop=True)
    return s


def validate_inputs(df: pd.DataFrame, cfg: CausalConfig) -> list[str]:
    """Plan 8.3 step 2 - validate treatment/outcome/confounder definitions.  Returns a list of problems."""
    problems = []
    for c in [cfg.treatment, cfg.outcome, *cfg.confounders]:
        if c not in df.columns:
            problems.append(f"Variable '{c}' not found in the analytical dataset")
    if problems:
        return problems
    if cfg.treatment == cfg.outcome:
        problems.append("Treatment and outcome must differ")
    if cfg.treatment in cfg.confounders or cfg.outcome in cfg.confounders:
        problems.append("Treatment/outcome cannot be used as a confounder")
    if cfg.outcome in ("pqtr", "log_pqtr", "ptr", "pct_qualified_calc"):
        problems.append("Outcome must be an educational outcome, not a teacher-supply variable")
    for c in [cfg.treatment, cfg.outcome, *cfg.confounders]:
        if not pd.api.types.is_numeric_dtype(df[c]):
            problems.append(f"Variable '{c}' is not numeric")
        elif df[c].isna().any():
            problems.append(f"Variable '{c}' has {int(df[c].isna().sum())} missing values in the sample")
    if len(df) < 15:
        problems.append(f"Only {len(df)} observations: too few for causal estimation")
    post = {"private_share_enrol", "etpr_2015", "completion_m", "completion_f", "ger_m", "ger_f", "oos_male_2021", "oos_female_2021"}
    bad = [c for c in cfg.confounders if c in post]
    if bad:
        problems.append(f"Confounder(s) {bad} are possible post-treatment variables (mediators/colliders); adjusting for them can introduce bias")
    return problems


# ----------------------------------------------------------------------------------------
def _ols(df, y, xcols, weights=None, cov="HC3"):
    X = sm.add_constant(df[xcols], has_constant="add")
    if weights is None:
        m = sm.OLS(df[y], X).fit(cov_type=cov, use_t=True)
    else:
        m = sm.WLS(df[y], X, weights=weights).fit(cov_type=cov, use_t=True)
    return m


def _row(method, df_n, coef, se, ci, p, notes="", kind="adjusted", extra=None):
    """One estimate row.  ``coef`` is per unit of ln(PQTR); the policy effect is per 10% reduction."""
    r = {"method": method, "kind": kind, "n": int(df_n), "coef_per_log_unit": float(coef), "se": float(se) if se is not None else None,
         "ci_low": float(ci[0]), "ci_high": float(ci[1]), "p_value": None if p is None else float(p),
         "effect_10pct_reduction": float(coef * LN090), "effect_10pct_ci_low": float(min(ci[0] * LN090, ci[1] * LN090)),
         "effect_10pct_ci_high": float(max(ci[0] * LN090, ci[1] * LN090)), "notes": notes}
    r["ci_includes_zero"] = bool(ci[0] <= 0 <= ci[1])
    if extra:
        r.update(extra)
    return r


def estimate_ols(df, cfg, xcols, label, notes="", kind="adjusted", weights=None, cov="HC3"):
    m = _ols(df, cfg.outcome, [cfg.treatment, *xcols], weights, cov)
    ci = m.conf_int().loc[cfg.treatment].to_numpy()
    return _row(label, len(df), m.params[cfg.treatment], m.bse[cfg.treatment], ci, m.pvalues[cfg.treatment], notes, kind), m


def _boot_ci(fn, df, n_boot, seed, alpha=0.05):
    rng = np.random.default_rng(seed)
    vals = []
    n = len(df)
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        try:
            v = fn(df.iloc[idx].reset_index(drop=True))
        except Exception:
            continue
        if np.isfinite(v):
            vals.append(v)
    vals = np.asarray(vals)
    return np.quantile(vals, [alpha / 2, 1 - alpha / 2]), len(vals)


# --- generalised propensity score (continuous treatment) -------------------------------
def gps_weights(df, cfg, trim=(0.05, 0.95)):
    """Stabilised inverse-probability weights for a continuous treatment: w = f(T) / f(T | Z), both normal.
    Weights are truncated at the given percentiles (n is small, so extreme weights are dangerous)."""
    T = df[cfg.treatment].to_numpy()
    Z = sm.add_constant(df[list(cfg.confounders)])
    m = sm.OLS(T, Z).fit()
    sd_c = np.sqrt(m.scale)
    num = stats.norm.pdf(T, T.mean(), T.std(ddof=1))
    den = stats.norm.pdf(T, m.fittedvalues, sd_c)
    w = num / den
    lo, hi = np.quantile(w, trim)
    return np.clip(w, lo, hi), m


def estimate_gps(df, cfg):
    def one(d):
        w, _ = gps_weights(d, cfg)
        mm = sm.WLS(d[cfg.outcome], sm.add_constant(d[[cfg.treatment, *cfg.confounders]]), weights=w).fit()
        return mm.params[cfg.treatment]

    w, m = gps_weights(df, cfg)
    # weighted outcome regression that also includes the confounders ("doubly robust" style): consistent if either the
    # outcome model or the treatment (GPS) model is correct
    mm = sm.WLS(df[cfg.outcome], sm.add_constant(df[[cfg.treatment, *cfg.confounders]]), weights=w).fit(cov_type="HC3", use_t=True)
    ci_b, nb = _boot_ci(one, df, cfg.n_boot, cfg.seed + 1)
    ess = float(w.sum() ** 2 / np.sum(w ** 2))
    # weighted balance: correlation of T with each confounder before / after weighting
    def wcorr(a, b, ww):
        am = np.average(a, weights=ww)
        bm = np.average(b, weights=ww)
        cov = np.average((a - am) * (b - bm), weights=ww)
        return float(cov / np.sqrt(np.average((a - am) ** 2, weights=ww) * np.average((b - bm) ** 2, weights=ww)))

    T = df[cfg.treatment].to_numpy()
    bal = {c: {"corr_unweighted": wcorr(T, df[c].to_numpy(float), np.ones(len(df))), "corr_weighted": wcorr(T, df[c].to_numpy(float), w)} for c in cfg.confounders}
    row = _row("GPS-weighted regression (stabilised weights truncated 5/95, outcome model adjusted)", len(df), mm.params[cfg.treatment], mm.bse[cfg.treatment], ci_b,
               None, notes=f"Percentile bootstrap CI ({nb} resamples, GPS re-estimated). ESS={ess:.1f} of {len(df)}.", extra={"ess": ess})
    max_after = max(abs(v["corr_weighted"]) for v in bal.values())
    diag = {"balance_achieved": bool(max_after < 0.1), "max_abs_weighted_corr": float(max_after),
            "balance_note": ("Weighting did not reduce the treatment-confounder correlation below 0.1 (n is small and weights are truncated); the estimate relies mainly on the outcome-model adjustment." if max_after >= 0.1 else "Weighted correlations below 0.1."),
            "weights": {"min": float(w.min()), "max": float(w.max()), "ess": ess}, "balance": bal,
            "treatment_model_r2": float(m.rsquared), "treatment_model_resid_sd": float(np.sqrt(m.scale))}
    return row, diag


# --- double / debiased machine learning --------------------------------------------------
def estimate_dml(df, cfg):
    """Partially-linear DML (EconML LinearDML), random-forest nuisance models, 5-fold cross-fitting repeated
    ``dml_repeats`` times; point estimate = median over repeats; variance = median of (se^2 + (theta_s - median)^2)
    (Chernozhukov et al. 2018, Def. 3.3)."""
    from econml.dml import LinearDML
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import KFold

    Y = df[cfg.outcome].to_numpy(float)
    T = df[cfg.treatment].to_numpy(float)
    W = df[list(cfg.confounders)].to_numpy(float)
    ests, ses = [], []
    for r in range(cfg.dml_repeats):
        est = LinearDML(model_y=RandomForestRegressor(n_estimators=150, min_samples_leaf=3, random_state=cfg.seed + r, n_jobs=1),
                        model_t=RandomForestRegressor(n_estimators=150, min_samples_leaf=3, random_state=cfg.seed + 100 + r, n_jobs=1),
                        cv=KFold(5, shuffle=True, random_state=cfg.seed + 200 + r), random_state=cfg.seed + r, discrete_treatment=False)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            est.fit(Y, T, X=None, W=W)
            inf = est.effect_inference()
        ests.append(float(np.ravel(inf.point_estimate)[0]))
        ses.append(float(np.ravel(inf.stderr)[0]))
    ests, ses = np.array(ests), np.array(ses)
    med = float(np.median(ests))
    se = float(np.sqrt(np.median(ses ** 2 + (ests - med) ** 2)))
    tcrit = stats.t.ppf(0.975, len(df) - len(cfg.confounders) - 2)
    ci = (med - tcrit * se, med + tcrit * se)
    p = 2 * (1 - stats.t.cdf(abs(med / se), len(df) - len(cfg.confounders) - 2)) if se > 0 else None
    return _row("Double/debiased ML (EconML LinearDML, RF nuisance, 5-fold x%d)" % cfg.dml_repeats, len(df), med, se, ci, p,
                notes="Median over repeated cross-fits; t-quantile interval (n is small, so the interval is approximate and probably too narrow).",
                extra={"repeat_estimates": [round(float(x), 4) for x in ests]})


# --- DoWhy identification and refutation -----------------------------------------------
def _gml(graph, extra_unobserved=False):
    nodes = list(graph["nodes"]) + (list(graph.get("unobserved", {})) if extra_unobserved else [])
    edges = list(graph["edges"]) + (list(graph.get("edges_unobserved", [])) if extra_unobserved else [])
    s = "graph [directed 1\n" + "\n".join(f'node [id "{n}" label "{n}"]' for n in nodes) + "\n"
    s += "\n".join(f'edge [source "{a}" target "{b}"]' for a, b in edges) + "\n]"
    return s


def dowhy_analysis(df, cfg):
    from dowhy import CausalModel
    logging.getLogger("dowhy").setLevel(logging.ERROR)
    out = {"identifying_graph": {}, "threat_graph": {}, "estimate": None, "refutations": []}
    data = df[[cfg.treatment, cfg.outcome, *cfg.confounders]].reset_index(drop=True)
    graph_id, graph_threat = build_graphs(cfg.outcome, cfg.confounders, cfg.treatment)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # (a) the identifying graph (assumption A1)
        m = CausalModel(data=data, treatment=cfg.treatment, outcome=cfg.outcome, graph=_gml(graph_id))
        ie = m.identify_effect(proceed_when_unidentifiable=False)
        out["identifying_graph"] = {"backdoor_adjustment_set": sorted(ie.get_backdoor_variables()), "identified": True, "estimand_type": str(ie.estimand_type)}
        est = m.estimate_effect(ie, method_name="backdoor.linear_regression", test_significance=True, confidence_intervals=True)
        ci = np.asarray(est.get_confidence_intervals()).ravel()
        out["estimate"] = {"method": "backdoor.linear_regression (DoWhy, non-robust SEs)", "coef_per_log_unit": float(est.value),
                           "ci_low": float(ci[0]), "ci_high": float(ci[1])}
        # (b) the threat graph with an unobserved common cause U -> the effect is NOT identifiable by backdoor adjustment
        try:
            m2 = CausalModel(data=data, treatment=cfg.treatment, outcome=cfg.outcome, graph=_gml(graph_threat, True))
            ie2 = m2.identify_effect(proceed_when_unidentifiable=True)
            out["threat_graph"] = {"backdoor_adjustment_set": sorted(ie2.get_backdoor_variables()) if ie2.estimands.get("backdoor") else [],
                                   "identified_by_backdoor": bool(ie2.estimands.get("backdoor")),
                                   "interpretation": "With an unobserved common cause U of treatment and outcome, backdoor adjustment on the observed variables alone does not identify the effect; the conclusion rests on assumption A1 and on the sensitivity analysis."}
        except Exception as e:  # pragma: no cover
            out["threat_graph"] = {"error": str(e)}
        # (c) refutation tests
        for name, kw, label, expect in [
            ("random_common_cause", {}, "Add a random common cause", "estimate should not change"),
            ("placebo_treatment_refuter", {"placebo_type": "permute"}, "Placebo treatment (permuted)", "effect should go to ~0"),
            ("data_subset_refuter", {"subset_fraction": 0.8}, "Random 80% subsets", "estimate should be stable"),
        ]:
            try:
                r = m.refute_estimate(ie, est, method_name=name, num_simulations=cfg.n_refute, random_seed=cfg.seed, show_progress_bar=False, **kw)
                pv = r.refutation_result.get("p_value") if isinstance(r.refutation_result, dict) else None
                out["refutations"].append({"test": label, "expectation": expect, "original": float(r.estimated_effect), "new": float(r.new_effect),
                                           "p_value": None if pv is None else float(pv)})
            except Exception as e:  # pragma: no cover
                out["refutations"].append({"test": label, "expectation": expect, "error": str(e)})
    return out


# --- sensitivity to unmeasured confounding (Cinelli & Hazlett 2020) ----------------------
def robustness_value(t_stat: float, dof: int, q: float = 1.0, alpha: float | None = None) -> float:
    """Robustness value RV_{q,alpha}: the minimum strength (partial R^2 with BOTH treatment and outcome) of an
    omitted confounder able to reduce the estimate by 100q% (alpha=None) or to make it statistically
    insignificant at level alpha."""
    f = q * abs(t_stat) / np.sqrt(dof)
    if alpha is not None:
        f = f - stats.t.ppf(1 - alpha / 2, dof - 1) / np.sqrt(dof - 1)
        if f <= 0:
            return 0.0
    return float(0.5 * (np.sqrt(f ** 4 + 4 * f ** 2) - f ** 2))


def sensitivity(df, cfg):
    m = sm.OLS(df[cfg.outcome], sm.add_constant(df[[cfg.treatment, *cfg.confounders]])).fit()  # classical SE for the t/dof algebra
    t = float(m.tvalues[cfg.treatment])
    dof = int(m.df_resid)
    r2yd = t ** 2 / (t ** 2 + dof)
    # benchmark: partial R2 of each observed confounder with the outcome (given the others and T)
    bench = {}
    for c in cfg.confounders:
        others = [x for x in cfg.confounders if x != c]
        mr = sm.OLS(df[cfg.outcome], sm.add_constant(df[[cfg.treatment, *others]])).fit()
        mf = sm.OLS(df[cfg.outcome], sm.add_constant(df[[cfg.treatment, *cfg.confounders]])).fit()
        r2_y = float((mr.ssr - mf.ssr) / mr.ssr)
        tr = sm.OLS(df[cfg.treatment], sm.add_constant(df[others])).fit()
        tf = sm.OLS(df[cfg.treatment], sm.add_constant(df[list(cfg.confounders)])).fit()
        r2_t = float((tr.ssr - tf.ssr) / tr.ssr)
        bench[c] = {"partial_r2_with_outcome": r2_y, "partial_r2_with_treatment": r2_t}
    rv0 = robustness_value(t, dof, 1.0)
    rv05 = robustness_value(t, dof, 1.0, 0.05)
    sig_note = (f"{rv05:.1%} would make it statistically insignificant at 5%." if rv05 > 0 else "The adjusted estimate is already statistically insignificant at 5%, so no additional confounding is needed for that.")
    return {"t_statistic": t, "dof": dof, "partial_r2_treatment_outcome": float(r2yd),
            "robustness_value_q1": rv0, "robustness_value_q1_alpha05": rv05,
            "benchmarks": bench,
            "interpretation": (f"An omitted confounder explaining {rv0:.1%} of the residual variance of BOTH PQTR and the OOS rate (partial R^2) would be enough to reduce the point estimate to zero. "
                               f"{sig_note} The observed confounders have partial R^2 with the outcome of "
                               + ", ".join(f"{k}: {v['partial_r2_with_outcome']:.1%}" for k, v in bench.items()) + " (benchmarks).")}


# --- robustness -------------------------------------------------------------------------
def robustness_checks(df, cfg, analytic_full):
    rows = []
    adj = list(cfg.confounders)
    base, mbase = estimate_ols(df, cfg, adj, "Baseline: OLS adjusted for poverty + region (HC3)")
    rows.append(base)
    # leave-one-out
    loo = []
    for i in range(len(df)):
        d = df.drop(index=i)
        m = _ols(d, cfg.outcome, [cfg.treatment, *adj])
        loo.append((df.loc[i, "state"], float(m.params[cfg.treatment])))
    vals = np.array([v for _, v in loo])
    lo_state, hi_state = loo[int(vals.argmin())][0], loo[int(vals.argmax())][0]
    loo_summary = {"min": float(vals.min()), "max": float(vals.max()), "state_at_min": lo_state, "state_at_max": hi_state,
                   "sign_changes": bool((vals < 0).any() and (vals > 0).any())}
    # leave-one-zone-out
    zones = {}
    for z in sorted(df.zone.unique()):
        d = df[df.zone != z]
        if len(d) > 10:
            zones[z] = float(_ols(d, cfg.outcome, [cfg.treatment, *adj]).params[cfg.treatment])
    # influence
    infl = _ols(df, cfg.outcome, [cfg.treatment, *adj], cov="nonrobust").get_influence()
    cooks = pd.Series(infl.cooks_distance[0], index=df.state).sort_values(ascending=False)
    # alternative specifications
    r, _ = estimate_ols(df, cfg, [], "Unadjusted (association only - NOT causal)", "Includes all confounding by poverty and region", kind="naive")
    rows.append(r)
    r, _ = estimate_ols(df, cfg, ["north"], "Adjusted for region only (drops poverty; A4 check)")
    rows.append(r)
    r, _ = estimate_ols(df, cfg, ["pov_215"], "Adjusted for poverty only")
    rows.append(r)
    d2 = df.dropna(subset=["etpr_2015"])
    if len(d2) > 15:
        r, _ = estimate_ols(d2, cfg, adj + ["etpr_2015"], "Adjusted + 2015/16 enrolment ratio (lagged access)", f"n={len(d2)} (rows with missing 2015/16 value dropped)")
        rows.append(r)
    d3 = df[df.pqtr <= 150]
    r, _ = estimate_ols(d3, cfg, adj, "Excluding extreme PQTR (> 150)", f"Drops {len(df) - len(d3)} state(s): " + ", ".join(sorted(df[df.pqtr > 150].state)))
    rows.append(r)
    r, _ = estimate_ols(df, cfg, adj, "WLS weighted by child population (6-11)", weights=df["pop6_11_2015"])
    rows.append(r)
    # alternative treatment definition: PTR (all teachers)
    d4 = df.dropna(subset=["ptr"]).copy()
    d4["log_ptr"] = np.log(d4["ptr"])
    m = _ols(d4, cfg.outcome, ["log_ptr", *adj])
    ci = m.conf_int().loc["log_ptr"].to_numpy()
    rows.append(_row("Alternative treatment: log PTR (all teachers)", len(d4), m.params["log_ptr"], m.bse["log_ptr"], ci, m.pvalues["log_ptr"]))
    # linear treatment (per +10 pupils) kept separate because units differ
    m = _ols(df, cfg.outcome, ["pqtr", *adj])
    lin = {"coef_per_10_pupils": float(m.params["pqtr"] * 10), "ci_low": float(m.conf_int().loc["pqtr"][0] * 10), "ci_high": float(m.conf_int().loc["pqtr"][1] * 10)}
    # fractional-logit form for the bounded outcome
    glm = sm.GLM((df[cfg.outcome] / 100.0), sm.add_constant(df[[cfg.treatment, *adj]]), family=sm.families.Binomial()).fit(cov_type="HC3")
    p = (df[cfg.outcome] / 100.0).mean()
    # average marginal effect of a 10% PQTR reduction on the OOS rate (pp), by finite difference
    X1 = sm.add_constant(df[[cfg.treatment, *adj]]).copy()
    X0 = X1.copy()
    X0[cfg.treatment] = X0[cfg.treatment] + LN090
    ame = float(100 * (glm.predict(X0) - glm.predict(X1)).mean())
    frac = {"coef_logit_per_log_unit": float(glm.params[cfg.treatment]), "p_value": float(glm.pvalues[cfg.treatment]),
            "ame_10pct_reduction_pp": ame, "note": "Fractional logit (binomial GLM, robust SE); coefficient on the logit scale; AME by finite difference"}
    # pairs bootstrap for the baseline
    def one(d):
        return _ols(d, cfg.outcome, [cfg.treatment, *adj]).params[cfg.treatment]
    ci_b, nb = _boot_ci(one, df, cfg.n_boot, cfg.seed + 2)
    boot = {"ci_low": float(ci_b[0]), "ci_high": float(ci_b[1]), "n_valid": nb}
    # permutation (Freedman-Lane) p-value
    rng = np.random.default_rng(cfg.seed + 3)
    Zc = sm.add_constant(df[adj])
    t_res = sm.OLS(df[cfg.treatment], Zc).fit().resid.to_numpy()
    y_res = sm.OLS(df[cfg.outcome], Zc).fit().resid.to_numpy()
    obs = float(np.dot(t_res, y_res) / np.dot(t_res, t_res))
    perm = np.array([np.dot(t_res, rng.permutation(y_res)) / np.dot(t_res, t_res) for _ in range(5000)])
    p_perm = float((np.sum(np.abs(perm) >= abs(obs)) + 1) / (len(perm) + 1))
    return {"specification_table": rows, "leave_one_out": loo_summary, "leave_one_zone_out": zones,
            "top_influence_cooks_d": {k: float(v) for k, v in cooks.head(5).items()}, "linear_treatment": lin,
            "fractional_logit": frac, "pairs_bootstrap_baseline": boot, "permutation_p_value": p_perm,
            "multicollinearity": _collinearity(df, cfg)}


def _collinearity(df, cfg):
    out = {}
    X = df[[cfg.treatment, *cfg.confounders]].to_numpy(float)
    for i, c in enumerate([cfg.treatment, *cfg.confounders]):
        others = np.delete(X, i, axis=1)
        r2 = sm.OLS(X[:, i], sm.add_constant(others)).fit().rsquared
        out[c] = {"vif": float(1 / (1 - r2)), "r2_on_others": float(r2)}
    return out


# --- heterogeneity (subgroup explanation) -------------------------------------------------
def subgroup_effects(df, cfg):
    out = {}
    # North vs South stratified slopes with the remaining confounder
    for g, name in [(1, "North"), (0, "South")]:
        d = df[df.north == g]
        rest = [c for c in cfg.confounders if c != "north"]
        r, m = estimate_ols(d, cfg, rest, f"{name} states only")
        out[name] = r
    # interaction test
    d = df.copy()
    d["T_x_north"] = d[cfg.treatment] * d["north"]
    m = _ols(d, cfg.outcome, [cfg.treatment, "T_x_north", *cfg.confounders])
    inter = {"coef": float(m.params["T_x_north"]), "se": float(m.bse["T_x_north"]), "p_value": float(m.pvalues["T_x_north"]),
             "slope_south": float(m.params[cfg.treatment]), "slope_north": float(m.params[cfg.treatment] + m.params["T_x_north"])}
    # poverty groups (above / below median)
    med = df.pov_215.median()
    for name, d in [("Below-median poverty", df[df.pov_215 <= med]), ("Above-median poverty", df[df.pov_215 > med])]:
        rest = list(cfg.confounders)
        r, _ = estimate_ols(d, cfg, rest, name + " states")
        out[name] = r
    # DML CATE by region would be unstable at n=31; interaction model is reported instead
    return {"strata": out, "interaction_test": inter,
            "note": "Subgroup estimates use 15-17 states each and are exploratory; none should be used to target policy without further data."}


# --- prediction / explainability ----------------------------------------------------------
def explainability(df, cfg):
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.model_selection import LeaveOneOut, LeaveOneGroupOut, cross_val_predict
    from sklearn.inspection import permutation_importance
    import shap

    feats = ["log_pqtr", "pov_215", "north", "pct_qualified_calc", "private_share_enrol"]
    d = df.dropna(subset=feats + [cfg.outcome]).reset_index(drop=True)
    X, y = d[feats].to_numpy(float), d[cfg.outcome].to_numpy(float)
    groups = d["zone"].to_numpy()

    def rmse(p):
        return float(np.sqrt(np.mean((y - p) ** 2)))

    def loo_ols(cols):
        idx = [feats.index(c) for c in cols]
        preds = np.empty(len(y))
        for i in range(len(y)):
            tr = np.arange(len(y)) != i
            m = sm.OLS(y[tr], sm.add_constant(X[tr][:, idx], has_constant="add")).fit()
            preds[i] = m.predict(np.r_[1.0, X[i, idx]].reshape(1, -1))[0]
        return preds

    def logo_ols(cols):
        idx = [feats.index(c) for c in cols]
        preds = np.empty(len(y))
        for z in np.unique(groups):
            te = groups == z
            m = sm.OLS(y[~te], sm.add_constant(X[~te][:, idx], has_constant="add")).fit()
            preds[te] = m.predict(sm.add_constant(X[te][:, idx], has_constant="add"))
        return preds

    rf = RandomForestRegressor(n_estimators=300, min_samples_leaf=2, random_state=cfg.seed, n_jobs=1)
    perf = []
    base_loo = np.array([np.delete(y, i).mean() for i in range(len(y))])
    base_zone = np.empty(len(y))
    for z in np.unique(groups):
        te = groups == z
        base_zone[te] = y[~te].mean()
    perf.append({"model": "Baseline: mean of training states", "loo_rmse": rmse(base_loo), "leave_zone_out_rmse": rmse(base_zone)})
    for label, cols in [("OLS: region only", ["north"]), ("OLS: poverty + region", ["pov_215", "north"]), ("OLS: poverty + region + log PQTR", ["pov_215", "north", "log_pqtr"])]:
        perf.append({"model": label, "loo_rmse": rmse(loo_ols(cols)), "leave_zone_out_rmse": rmse(logo_ols(cols))})
    p_loo = cross_val_predict(rf, X, y, cv=LeaveOneOut())
    p_zone = cross_val_predict(rf, X, y, cv=LeaveOneGroupOut(), groups=groups)
    perf.append({"model": "Random forest (5 features)", "loo_rmse": rmse(p_loo), "leave_zone_out_rmse": rmse(p_zone)})
    rf.fit(X, y)
    perm = permutation_importance(rf, X, y, n_repeats=30, random_state=cfg.seed)
    ex = shap.TreeExplainer(rf)
    sv = ex.shap_values(X)
    shap_mean = np.abs(sv).mean(axis=0)
    importance = [{"feature": f, "permutation_importance": float(perm.importances_mean[i]), "mean_abs_shap": float(shap_mean[i])} for i, f in enumerate(feats)]
    importance.sort(key=lambda r: -r["mean_abs_shap"])
    shap_rows = [{"state": d.state[i], **{f: float(sv[i, j]) for j, f in enumerate(feats)}} for i in range(len(d))]
    return {"n": int(len(d)), "features": feats, "predictive_performance": perf, "importance": importance, "shap_by_state": shap_rows,
            "caution": "Feature importance and SHAP values describe the fitted PREDICTIVE model. A strong predictor (e.g. poverty or region) is not necessarily a policy lever, and a weak predictor is not proof of no causal effect."}


# --- applicability of identification strategies (plan 8.2) --------------------------------
def method_applicability(analytic: pd.DataFrame) -> list[dict]:
    n_states = int(analytic["in_primary_sample"].sum())
    return [
        {"method": "Regression adjustment", "applicable": True, "reason": f"Observational cross-section with measured confounders (poverty, region); n={n_states}. Requires assumption A1."},
        {"method": "Propensity-score methods (generalised, continuous treatment)", "applicable": True, "reason": "Continuous treatment: generalised PS weighting used; overlap and balance diagnostics reported."},
        {"method": "Double/debiased machine learning", "applicable": True, "reason": f"Applicable in principle; with n={n_states} nuisance models are noisy, so DML is a cross-check and not the primary estimate."},
        {"method": "Difference-in-differences", "applicable": False, "reason": "No pre/post outcome observations for the same states and no defined intervention with a comparison group; MICS 2021 is a single outcome wave (the 2015/16 and 2021 outcome measures use different definitions and are not comparable)."},
        {"method": "Fixed-effects panel model", "applicable": False, "reason": "Only one observation per state for the outcome; no repeated measures to difference out state effects."},
        {"method": "Instrumental variables", "applicable": False, "reason": "No credible instrument (relevance and exclusion) is available in the retrieved data."},
    ]


# ----------------------------------------------------------------------------------------
def software_versions() -> dict:
    import importlib.metadata as md
    pk = ["numpy", "pandas", "scipy", "statsmodels", "scikit-learn", "dowhy", "econml", "shap", "Django", "plotly"]
    out = {"python": platform.python_version()}
    for p in pk:
        try:
            out[p] = md.version(p)
        except md.PackageNotFoundError:
            out[p] = "not installed"
    return out


def run_causal_analysis(analytic: pd.DataFrame, cfg: CausalConfig | None = None) -> dict:
    """Full pipeline of plan 8.3.  Deterministic for a given dataset and configuration."""
    cfg = cfg or CausalConfig()
    df = prepare_data(analytic, cfg)
    problems = validate_inputs(df, cfg)
    if problems:
        raise ValueError("Invalid causal specification: " + "; ".join(problems))
    warn = []
    estimates = []
    est_adj, m_adj = estimate_ols(df, cfg, list(cfg.confounders), "Regression adjustment (OLS, HC3 robust SE, t-interval)", "Primary estimate", kind="primary")
    estimates.append(est_adj)
    est_adj["bootstrap_ci"] = None
    gps_row, gps_diag = estimate_gps(df, cfg)
    estimates.append(gps_row)
    if cfg.run_dml:
        try:
            estimates.append(estimate_dml(df, cfg))
        except Exception as e:  # pragma: no cover
            warn.append(f"DML failed: {e}")
    naive, _ = estimate_ols(df, cfg, [], "Unadjusted association (for comparison only - NOT a causal estimate)", kind="naive")
    estimates.append(naive)
    dw = dowhy_analysis(df, cfg) if cfg.run_dowhy else {}
    sens = sensitivity(df, cfg)
    rob = robustness_checks(df, cfg, analytic)
    sub = subgroup_effects(df, cfg)
    expl = explainability(df, cfg)
    # secondary outcomes (boys / girls) with the same adjustment
    sec = []
    for o, lab in [("oos_male_2021", "Boys' OOS rate"), ("oos_female_2021", "Girls' OOS rate")]:
        c2 = CausalConfig(outcome=o, confounders=cfg.confounders)
        d2 = df.dropna(subset=[o])
        r, _ = estimate_ols(d2, c2, list(c2.confounders), f"Secondary outcome: {lab}")
        sec.append(r)
    graph_id, graph_threat = build_graphs(cfg.outcome, cfg.confounders, cfg.treatment)
    # overlap diagnostics
    T = df[cfg.treatment]
    Z = sm.add_constant(df[list(cfg.confounders)])
    mt = sm.OLS(T, Z).fit()
    overlap = {"treatment_range_pqtr": [float(df.pqtr.min()), float(df.pqtr.max())], "treatment_given_confounders_r2": float(mt.rsquared),
               "residual_treatment_sd": float(np.sqrt(mt.scale)),
               "pqtr_range_by_region": {r: [float(g.pqtr.min()), float(g.pqtr.max())] for r, g in df.groupby("region")},
               "n_by_region": df.region.value_counts().to_dict(), "gps": gps_diag}
    primary = est_adj
    sig = not primary["ci_includes_zero"]
    all_cis_zero = all(e["ci_includes_zero"] for e in estimates if e["kind"] != "naive")
    explanation = build_explanation(primary, estimates, sens, rob, sig, all_cis_zero, len(df))
    if len(df) < 40:
        warn.append(f"Only {len(df)} states are available: intervals are wide and estimates unstable.")
    warn.append("Cross-sectional design: results are adjusted associations interpreted causally only under assumptions A1-A7.")
    result = {
        "specification": {"treatment": cfg.treatment, "outcome": cfg.outcome, "confounders": list(cfg.confounders),
                          "estimand": "ATE of a 10% proportional reduction in public pupils-per-qualified-teacher on the state primary out-of-school rate (percentage points)",
                          "unit_of_analysis": "state (cross-section; treatment 2016/17, outcome 2021)", "n": int(len(df)),
                          "states": df.state.tolist(), "graph_identifying": graph_id, "graph_threat": graph_threat, "assumptions": ASSUMPTIONS},
        "applicability": method_applicability(analytic),
        "identification": dw,
        "estimates": estimates,
        "secondary_outcomes": sec,
        "overlap_balance": overlap,
        "sensitivity_unmeasured_confounding": sens,
        "robustness": rob,
        "subgroups": sub,
        "explainability": expl,
        "explanation": explanation,
        "warnings": warn,
        "software_versions": software_versions(),
        "config": cfg.to_dict(),
    }
    result["results_sha256"] = sha256_text(stable_json(round_floats({k: v for k, v in result.items() if k != "software_versions"})))
    return result


def build_explanation(primary, estimates, sens, rob, sig, all_cis_zero, n) -> dict:
    b = primary["coef_per_log_unit"]
    e10 = primary["effect_10pct_reduction"]
    ci10 = (primary["effect_10pct_ci_low"], primary["effect_10pct_ci_high"])
    naive = next(e for e in estimates if e["kind"] == "naive")
    lines = [
        f"Under assumptions A1-A7, the regression-adjusted estimate is that a 10% reduction in pupils per qualified teacher changes a state's primary out-of-school rate by {e10:+.2f} percentage points (95% interval {ci10[0]:+.2f} to {ci10[1]:+.2f}), n = {n} states.",
        f"The unadjusted association is much larger ({naive['effect_10pct_reduction']:+.2f} pp per 10% reduction) because states with high PQTR are also poorer and mostly in the North; most of that raw association is explained by poverty and region.",
    ]
    if all_cis_zero:
        lines.append("Every adjusted estimator gives an interval that includes zero: the data are CONSISTENT WITH both no effect and effects of modest size, and cannot distinguish them.")
    elif sig:
        lines.append("The primary interval excludes zero, but other estimators/specifications should be consulted before drawing a conclusion.")
    lines.append(f"Sensitivity: an unmeasured confounder would need a partial R^2 of about {sens['robustness_value_q1']:.0%} with both PQTR and the outcome to explain the point estimate away (RV); this is a measure of fragility, not evidence of causation.")
    return {"summary": lines, "verdict": "Inconclusive: no reliable evidence of a causal effect of PQTR on OOS rates that is distinguishable from zero in these data." if all_cis_zero else "Adjusted association present; causal interpretation depends on A1."}
