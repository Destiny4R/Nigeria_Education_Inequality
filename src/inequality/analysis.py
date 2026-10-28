"""Run a complete, filterable inequality analysis and return a JSON-safe result bundle (plan 7.2)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.common import sha256_text, stable_json, to_jsonable
from src.inequality import metrics as M

LEVELS = {"oos_primary": "Primary", "oos_lower_secondary": "Lower secondary", "oos_upper_secondary": "Upper secondary"}
STATE_INDICATORS = [k for k in M.INDICATORS]


def default_config() -> dict:
    return {"indicator": "oos_total_2021", "region": "All", "zone": "All", "poverty_group": "All", "states": [], "level": "oos_primary"}


def validate_config(cfg: dict, analytic: pd.DataFrame) -> list[str]:
    p = []
    if cfg.get("indicator") not in M.INDICATORS:
        p.append("Unknown indicator")
    if cfg.get("region", "All") not in ("All", "North", "South"):
        p.append("Region must be All, North or South")
    if cfg.get("zone", "All") not in ["All"] + sorted(analytic.zone.unique().tolist()):
        p.append("Unknown zone")
    if cfg.get("poverty_group", "All") not in ("All", "Low poverty", "Middle poverty", "High poverty"):
        p.append("Unknown poverty group")
    if cfg.get("level", "oos_primary") not in LEVELS:
        p.append("Unknown education level")
    bad = [s for s in cfg.get("states", []) if s not in set(analytic.state)]
    if bad:
        p.append("Unknown state(s): " + ", ".join(bad))
    return p


def run_inequality_analysis(analytic: pd.DataFrame, groups: pd.DataFrame, series: pd.DataFrame, cfg: dict | None = None) -> dict:
    cfg = {**default_config(), **(cfg or {})}
    problems = validate_config(cfg, analytic)
    if problems:
        raise ValueError("Invalid inequality configuration: " + "; ".join(problems))
    ind = cfg["indicator"]
    meta = M.INDICATORS[ind]
    full = analytic.copy()
    d = M.filter_states(full, cfg.get("states") or None, cfg["region"], cfg["zone"], cfg["poverty_group"])
    warnings = []
    if not meta["comparable"]:
        warnings.append(meta["label"] + ": administrative projections - not comparable with survey indicators; use for orientation only.")
    n_val = int(d[ind].notna().sum())
    if n_val < 5:
        warnings.append(f"Only {n_val} state(s) with data after filtering; summary measures are suppressed.")
    out = {"config": cfg, "indicator": {"code": ind, **meta}, "n_states_selected": int(len(d)), "n_states_with_value": n_val, "warnings": warnings}
    ranking, rw = M.state_ranking(d, ind, ascending=(meta["direction"] == "higher_better"))
    out["ranking"] = ranking
    out["warnings"] += rw
    if n_val >= 5:
        out["profile"] = M.state_inequality_profile(d, ind) if ind != "pqtr" else M.state_inequality_profile(d, ind)
        out["zone_summary"] = M.zone_summary(d, ind)
        if d.region.nunique() == 2:
            out["regional_gap"] = M.regional_gap(d, ind)
        lz = M.lorenz_points(d.dropna(subset=[ind, "pop6_11_2015"])[ind], d.dropna(subset=[ind, "pop6_11_2015"])["pop6_11_2015"]) if (d[ind].dropna() >= 0).all() else None
        out["lorenz"] = lz
    else:
        out["profile"] = None
    tmp = d.copy()
    out["scatter"] = tmp[["state", "zone", "region", ind, "pov_215", "pop6_11_2015"]].dropna(subset=[ind])
    full_oos = full
    out["gender_gap"] = M.gender_gap_table(d) if ind.startswith("oos_") else M.gender_gap_table(d)
    out["poverty_gradient"] = M.poverty_gradient(d) if d[["oos_total_2021", "pov_215"]].dropna().shape[0] >= 5 else None
    out["resource_inequality"] = M.resource_inequality(full)  # always the full valid sample
    out["resource_inequality_note"] = "Computed on all states with a valid PQTR (independent of the filters above)."
    out["national_groups"] = M.national_group_analysis(groups, cfg["level"])
    out["national_groups_all_levels"] = {lv: M.national_group_analysis(groups, lv) for lv in LEVELS}
    trends = M.national_trends(series)
    out["trends"] = {code: {"series": g, "change": M.trend_change(g)} for code, g in trends.items()}
    out["state_data_issues"] = {r.state: r.flags for r in full.itertuples() if r.flags}
    out["results_sha256"] = sha256_text(stable_json(to_jsonable(out)))
    return to_jsonable(out)
