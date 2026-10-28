"""Independent recalculation of headline results (plan 11.4: "results match independently calculated test cases").

This module deliberately does NOT import src.inequality / src.causal / src.simulation.  It recomputes the headline numbers from the
cleaned analytic file with different formulas (pairwise-difference Gini, explicit sandwich estimator, scipy rank correlation) and
compares them with the numbers stored by the standard analysis runs.  Agreement shows the engines implement the stated definitions;
it does not validate the data themselves (see reconcile_refetch.py for that).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def wgini_pairwise(x, w):
    x, w = np.asarray(x, float), np.asarray(w, float)
    w = w / w.sum()
    mu = (w * x).sum()
    return float((w[:, None] * w[None, :] * np.abs(x[:, None] - x[None, :])).sum() / (2 * mu))


def ols_hc3(y, X):
    X = np.column_stack([np.ones(len(y)), X])
    XtXi = np.linalg.inv(X.T @ X)
    b = XtXi @ X.T @ y
    e = y - X @ b
    h = np.einsum("ij,jk,ik->i", X, XtXi, X)
    meat = (X * (e / (1 - h))[:, None]).T @ (X * (e / (1 - h))[:, None])
    V = XtXi @ meat @ XtXi
    return b, np.sqrt(np.diag(V)), len(y) - X.shape[1]


def recompute(analytic: pd.DataFrame) -> dict:
    out = {}
    y = analytic["oos_total_2021"].astype(float).to_numpy()
    w = analytic["pop6_11_2015"].astype(float).to_numpy()
    mu = np.average(y, weights=w)
    wn = w / w.sum()
    out["gini"] = wgini_pairwise(y, w)
    out["theil_t"] = float((wn * (y / mu) * np.log(np.where(y > 0, y, np.nan) / mu)).sum()) if (y > 0).all() else float(np.nansum(wn * (y / mu) * np.log(np.where(y > 0, y, np.nan) / mu)))
    out["cv"] = float(np.sqrt(np.average((y - mu) ** 2, weights=w)) / mu)
    out["p90_p10"] = float(np.percentile(y, 90) / np.percentile(y, 10))
    out["weighted_mean"] = float(mu)
    m = analytic["pov_215"].notna().to_numpy()
    out["spearman_oos_poverty"] = float(stats.spearmanr(y[m], analytic.loc[m, "pov_215"]).statistic)
    north = analytic["region"].eq("North").to_numpy()
    out["north_mean"], out["south_mean"] = float(np.average(y[north], weights=w[north])), float(np.average(y[~north], weights=w[~north]))
    out["north_south_gap"] = out["north_mean"] - out["south_mean"]

    s = analytic[analytic["in_primary_sample"].astype(bool)]
    ys = s["oos_total_2021"].astype(float).to_numpy()
    X = np.column_stack([s["log_pqtr"].astype(float), s["pov_215"].astype(float), s["region"].eq("North").astype(float)])
    b, se, dof = ols_hc3(ys, X)
    out["ols_n"], out["ols_coef_log_pqtr"], out["ols_se_hc3"] = int(len(ys)), float(b[1]), float(se[1])
    tq = stats.t.ppf(0.975, dof)
    out["ols_ci_low"], out["ols_ci_high"] = float(b[1] - tq * se[1]), float(b[1] + tq * se[1])
    out["ols_effect_10pct_reduction_pp"] = float(b[1] * np.log(0.9))

    # Scenario S1 (cap at 35 pupils per qualified teacher), full implementation, point estimate
    pq, wn_s = s["pqtr"].astype(float).to_numpy(), s["pop6_11_2015"].astype(float).to_numpy()
    new = np.minimum(pq, 35.0)
    delta = np.maximum(0.0, ys + b[1] * (np.log(new) - np.log(pq))) - ys          # documented rule: a rate cannot fall below 0%
    out["s1_baseline_national_oos"] = float(np.average(ys, weights=wn_s))
    out["s1_change_pp"] = float(np.average(delta, weights=wn_s))
    return out


def compare(stored_ineq: dict, stored_causal: dict, stored_sim_s1: dict | None, analytic: pd.DataFrame) -> list[dict]:
    r = recompute(analytic)
    prim = next(e for e in stored_causal["estimates"] if e["kind"] == "primary")
    rows = [
        ("Gini across states (pop-weighted)", r["gini"], stored_ineq["profile"]["gini"], 5e-4),
        ("Theil T", r["theil_t"], stored_ineq["profile"]["theil_t"], 5e-4),
        ("Coefficient of variation (weighted)", r["cv"], stored_ineq["profile"]["cv"], 5e-4),
        ("P90/P10 ratio", r["p90_p10"], stored_ineq["profile"]["p90_p10_ratio"], 5e-3),
        ("Weighted national mean OOS", r["weighted_mean"], stored_ineq["profile"]["weighted_mean"], 5e-4),
        ("Spearman (OOS, poverty)", r["spearman_oos_poverty"], stored_ineq["poverty_gradient"]["spearman_oos_poverty"], 5e-4),
        ("North-South gap (pp)", r["north_south_gap"], stored_ineq["regional_gap"]["gap"], 5e-4),
        ("OLS coefficient, log PQTR", r["ols_coef_log_pqtr"], prim["coef_per_log_unit"], 1e-6),
        ("OLS HC3 standard error", r["ols_se_hc3"], prim["se"], 1e-6),
        ("OLS 95% CI low", r["ols_ci_low"], prim["ci_low"], 1e-6),
        ("OLS 95% CI high", r["ols_ci_high"], prim["ci_high"], 1e-6),
        ("Effect of 10% PQTR reduction (pp)", r["ols_effect_10pct_reduction_pp"], prim["effect_10pct_reduction"], 1e-6),
    ]
    if stored_sim_s1:
        h = stored_sim_s1["headline"]
        rows += [("S1 baseline national OOS (pp)", r["s1_baseline_national_oos"], h["baseline_national_oos"], 5e-4),
                 ("S1 point change at full implementation (pp)", r["s1_change_pp"], h["absolute_change_pp"], 5e-4)]
    return [{"quantity": q, "independent": a, "stored": b, "abs_diff": abs(a - b), "tolerance": t, "agrees": abs(a - b) <= t} for q, a, b, t in rows]


if __name__ == "__main__":
    import os
    os.environ.setdefault("DJANGO_DEBUG", "1")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "eduineq.settings")
    import django
    django.setup()
    from portal import services as S
    ineq, causal = S.latest_default("inequality").results, S.latest_default("causal").results
    s1 = next((r.results for r in S.m.AnalysisRun.objects.filter(analysis_type="simulation", status="succeeded", label__startswith="S1").order_by("-created_at")[:1]), None)
    res = compare(ineq, causal, s1, S.get_analytic())
    for x in res:
        print(f"{'OK ' if x['agrees'] else 'BAD'} {x['quantity']:48s} independent={x['independent']:.6f} stored={x['stored']:.6f} diff={x['abs_diff']:.2e}")
    (ROOT / "reports" / "independent_check.json").write_text(json.dumps(res, indent=1))
    sys.exit(0 if all(x["agrees"] for x in res) else 1)
