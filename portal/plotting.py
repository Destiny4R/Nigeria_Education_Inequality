"""Plotly figure builders.  Each returns a plain dict (Plotly JSON) that is embedded with ``json_script`` and rendered by static/portal/js/charts.js."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from django.conf import settings

REGION_COL = {"North": "#D55E00", "South": "#0072B2"}
BLUE, ORANGE, GREEN, GREY, PINK, SKY = "#0072B2", "#D55E00", "#009E73", "#6b7280", "#CC79A7", "#56B4E9"
FONT = dict(family="system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif", size=13, color="#1f2937")


def _layout(fig: go.Figure, title: str = "", height: int = 420, **kw) -> dict:
    margin = kw.pop("margin", dict(l=60, r=20, t=50 if title else 20, b=60))
    legend = kw.pop("legend", dict(orientation="h", y=-0.2))
    fig.update_layout(template="simple_white", font=FONT, title=dict(text=title, x=0, font=dict(size=15)), height=height,
                      margin=margin, legend=legend, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", **kw)
    return json.loads(fig.to_json())


def state_bars(ranking: list[dict], label: str, unit: str, ind: str) -> dict:
    d = pd.DataFrame(ranking)
    if d.empty:
        return _layout(go.Figure(), label)
    d = d.sort_values(ind)
    d["region"] = np.where(d.zone.isin(["NC", "NE", "NW"]), "North", "South")
    fig = go.Figure()
    for reg in ("North", "South"):
        s = d[d.region == reg]
        fig.add_bar(x=s[ind], y=s["state"], orientation="h", name=reg, marker_color=REGION_COL[reg], customdata=s["zone"], hovertemplate="%{y} (%{customdata}): %{x:.1f}<extra></extra>")
    fig.update_xaxes(title=unit)
    return _layout(fig, label, height=max(420, 17 * len(d) + 120), yaxis=dict(automargin=True, dtick=1, tickfont=dict(size=11)))


def zone_bars(zs: list[dict], label: str, unit: str) -> dict:
    d = pd.DataFrame(zs).sort_values("mean")
    fig = go.Figure(go.Bar(x=d["mean"], y=d["zone"], orientation="h", marker_color=BLUE, error_x=dict(type="data", symmetric=False, array=(d["max"] - d["mean"]).tolist(), arrayminus=(d["mean"] - d["min"]).tolist(), color="#9ca3af"),
                           hovertemplate="Zone %{y}: weighted mean %{x:.1f}<extra></extra>"))
    fig.update_xaxes(title=unit + " (bar = population-weighted mean; whiskers = min-max state)")
    return _layout(fig, "By geopolitical zone", height=320)


def lorenz(lz: list[dict], gini: float) -> dict:
    d = pd.DataFrame(lz)
    fig = go.Figure()
    fig.add_scatter(x=[0, 1], y=[0, 1], mode="lines", line=dict(color="#9ca3af", dash="dash"), name="Perfect equality")
    fig.add_scatter(x=d.pop_share, y=d.value_share, mode="lines+markers", line=dict(color=ORANGE), name=f"Lorenz curve (Gini {gini:.2f})", marker=dict(size=4))
    fig.update_xaxes(title="Cumulative share of children (states ordered low to high)", range=[0, 1])
    fig.update_yaxes(title="Cumulative share of the indicator total", range=[0, 1], scaleanchor="x")
    return _layout(fig, "Lorenz curve across states", height=380)


def poverty_scatter(rows: list[dict], ind: str, label: str) -> dict:
    d = pd.DataFrame(rows).dropna(subset=["pov_215", ind])
    fig = go.Figure()
    for reg in ("North", "South"):
        s = d[d.region == reg]
        fig.add_scatter(x=s.pov_215, y=s[ind], mode="markers", name=reg, marker=dict(color=REGION_COL[reg], size=np.clip(s.pop6_11_2015 / 60000, 7, 30), opacity=.8, line=dict(width=1, color="white")),
                        text=s.state, hovertemplate="%{text}<br>Poverty %{x:.1f}%<br>" + label + " %{y:.1f}<extra></extra>")
    fig.update_xaxes(title="Poverty headcount at $2.15/day, 2018 (%)")
    fig.update_yaxes(title=label)
    return _layout(fig, "Indicator vs state poverty (bubble size = child population)", height=400)


def gender_bars(rows: list[dict]) -> dict:
    d = pd.DataFrame(rows)
    if d.empty:
        return _layout(go.Figure(), "Girls minus boys")
    d = d.sort_values("gap_pp")
    fig = go.Figure(go.Bar(x=d.gap_pp, y=d.state, orientation="h", marker_color=[ORANGE if v > 0 else BLUE for v in d.gap_pp],
                           hovertemplate="%{y}: girls minus boys %{x:+.0f} pp<extra></extra>"))
    fig.update_xaxes(title="Girls' minus boys' out-of-school rate (pp); positive = girls worse off")
    return _layout(fig, "Gender gap in out-of-school rates by state (MICS 2021, whole-% rounded)", height=max(420, 16 * len(d) + 120), yaxis=dict(automargin=True, dtick=1, tickfont=dict(size=11)))


def national_groups(ng: dict) -> dict:
    fig = go.Figure()
    items = [("Wealth quintile", list(ng["wealth"]["rates"].items()), BLUE), ("Area", list(ng["area"]["rates"].items()), GREEN), ("Sex", list(ng["sex"]["rates"].items()), PINK)]
    for name, kv, col in items:
        fig.add_bar(x=[k for k, _ in kv], y=[v for _, v in kv], name=name, marker_color=col, text=[f"{v:.0f}%" for _, v in kv], textposition="outside", hovertemplate="%{x}: %{y:.0f}%<extra></extra>")
    fig.add_hline(y=ng["total"], line_dash="dash", line_color="#6b7280", annotation_text=f"National {ng['total']:.0f}%", annotation_position="top right")
    fig.update_yaxes(title="Out-of-school rate (%)", range=[0, max(70, ng["wealth"]["rates"]["Poorest"] * 1.2)])
    return _layout(fig, "National out-of-school rate by group (MICS6 2021)", height=380)


def trend_chart(series: list[dict], label: str) -> dict:
    d = pd.DataFrame(series)
    fig = go.Figure()
    fig.add_scatter(x=d.year, y=d.value_clean, mode="lines+markers", line=dict(color=BLUE), name=label, connectgaps=False, hovertemplate="%{x}: %{y:,.2f}<extra></extra>")
    bad = d[d.flag.fillna("") != ""]
    if len(bad):
        fig.add_scatter(x=bad.year, y=bad.value, mode="markers", marker=dict(symbol="x", color=ORANGE, size=10), name="Excluded outlier", hovertemplate="%{x}: %{y:,.2f} (excluded)<extra></extra>")
    return _layout(fig, label, height=300)


def point_map(rows: list[dict], ind: str, label: str) -> dict:
    p = Path(settings.BASE_DIR) / "portal" / "static" / "portal" / "data" / "nigeria_outline.geojson"
    gj = json.loads(p.read_text())
    fig = go.Figure()
    geom = gj["features"][0]["geometry"]
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    xs, ys = [], []
    for poly in polys:
        for ring in poly:
            xs += [c[0] for c in ring] + [None]
            ys += [c[1] for c in ring] + [None]
    fig.add_scatter(x=xs, y=ys, mode="lines", line=dict(color="#6b7280", width=1), fill="toself", fillcolor="rgba(229,231,235,0.55)", hoverinfo="skip", showlegend=False)
    d = pd.DataFrame(rows)
    have = d.dropna(subset=[ind])
    miss = d[d[ind].isna()]
    fig.add_scatter(x=have.lon, y=have.lat, mode="markers", name=label, text=have.state, customdata=have.zone,
                    marker=dict(size=np.clip(have.pop6_11_2015.fillna(5e5) / 55000, 9, 34), color=have[ind], colorscale="YlOrRd", showscale=True, colorbar=dict(title=label, thickness=12, len=.7), line=dict(width=1, color="#374151"), opacity=.9),
                    hovertemplate="%{text} (%{customdata}): %{marker.color:.1f}<extra></extra>")
    if len(miss):
        fig.add_scatter(x=miss.lon, y=miss.lat, mode="markers", name="No valid value", text=miss.state, marker=dict(symbol="x", size=9, color="#6b7280"), hovertemplate="%{text}: no valid value<extra></extra>")
    fig.update_xaxes(visible=False, range=[2.5, 15])
    fig.update_yaxes(visible=False, range=[3.9, 14.0], scaleanchor="x", scaleratio=1.0)
    return _layout(fig, "Approximate state-capital locations (point map; boundaries not available)", height=520)


def forest(estimates: list[dict], title: str, key: str = "effect_10pct") -> dict:
    d = estimates
    labels = [e["method"][:70] for e in d][::-1]
    fig = go.Figure()
    for i, e in enumerate(d[::-1]):
        naive = e.get("kind") == "naive"
        col = GREY if naive else (ORANGE if e.get("kind") == "primary" else BLUE)
        fig.add_scatter(x=[e["effect_10pct_ci_low"], e["effect_10pct_ci_high"]], y=[labels[i]] * 2, mode="lines", line=dict(color=col, width=3), showlegend=False, hoverinfo="skip")
        fig.add_scatter(x=[e["effect_10pct_reduction"]], y=[labels[i]], mode="markers", marker=dict(color=col, size=10, symbol="diamond" if naive else "circle"), showlegend=False,
                        hovertemplate=f"{e['method']}<br>n={e['n']}<br>%{{x:+.2f}} pp [{e['effect_10pct_ci_low']:+.2f}, {e['effect_10pct_ci_high']:+.2f}]<extra></extra>")
    fig.add_vline(x=0, line_dash="dash", line_color="#6b7280")
    fig.update_xaxes(title="Change in primary out-of-school rate (pp) for a 10% reduction in pupils per qualified teacher (95% interval)")
    return _layout(fig, title, height=max(320, 46 * len(d) + 120), yaxis=dict(automargin=True), margin=dict(l=330, r=20, t=50, b=70))


def dag(graph: dict, threat: bool = False) -> dict:
    CANON = {"north": (0.0, 0.5), "pov_215": (0.5, 1.0), "log_pqtr": (0.5, 0.0), "oos_total_2021": (1.0, 0.5), "U": (0.5, 0.5)}
    NAMES = {"north": "Region<br>(North)", "pov_215": "Poverty<br>2018", "log_pqtr": "Pupils per qualified<br>teacher (treatment)",
             "oos_total_2021": "Out-of-school<br>rate 2021 (outcome)", "oos_male_2021": "Boys' OOS<br>rate 2021 (outcome)",
             "oos_female_2021": "Girls' OOS<br>rate 2021 (outcome)", "U": "Unmeasured<br>(U)"}
    node_ids = list(graph["nodes"]) + (["U"] if threat else [])
    outgoing = {a for a, _ in graph["edges"]}
    outcome = next(n for n in node_ids if n not in outgoing and n != "U")
    if set(node_ids) <= set(CANON):
        pos = {n: CANON[n] for n in node_ids}
        names = {n: NAMES[n] for n in node_ids}
    else:
        pos = {"log_pqtr": CANON["log_pqtr"], outcome: CANON["oos_total_2021"], "U": CANON["U"]}
        names = {"log_pqtr": NAMES["log_pqtr"], outcome: NAMES.get(outcome, f"{outcome}<br>(outcome)"), "U": NAMES["U"]}
        confounders = [n for n in node_ids if n not in pos]
        if len(confounders) == 1:
            pos[confounders[0]] = (0.0, 0.5)
        else:
            for i, n in enumerate(sorted(confounders)):
                pos[n] = (0.0, 0.85 - 0.7 * i / (len(confounders) - 1))
        names.update({n: NAMES.get(n, str(graph["nodes"].get(n, n)).replace(" ", "<br>")) for n in confounders})
    fig = go.Figure()
    edges = [(a, b, False) for a, b in graph["edges"]]
    if threat:
        edges += [(a, b, True) for a, b in graph.get("edges_unobserved", [])]
    for a, b, dashed in edges:
        (x0, y0), (x1, y1) = pos[a], pos[b]
        fig.add_annotation(x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y", showarrow=True, arrowhead=3, arrowsize=1.2, arrowwidth=1.6,
                           arrowcolor="#9ca3af" if dashed else "#374151", standoff=34, startstandoff=34)
    fig.add_scatter(x=[pos[n][0] for n in node_ids], y=[pos[n][1] for n in node_ids], mode="markers+text", text=[names[n] for n in node_ids], textposition="middle center",
                    marker=dict(size=92, color=["#fde68a" if n == "log_pqtr" else "#bfdbfe" if n == outcome else "#fecaca" if n == "U" else "#e5e7eb" for n in node_ids], line=dict(width=1, color="#374151")),
                    textfont=dict(size=11, color="#0f172a"), hoverinfo="skip", showlegend=False)
    fig.update_xaxes(visible=False, range=[-0.25, 1.25])
    fig.update_yaxes(visible=False, range=[-0.3, 1.3])
    return _layout(fig, "Assumed causal graph" + (" with an unmeasured common cause" if threat else ""), height=360)


FEATURE_LABELS = {
    "log_pqtr": "Pupils per qualified<br>teacher (log)",
    "pov_215": "Poverty headcount<br>($2.15/day)",
    "north": "North region",
    "pct_qualified_calc": "Qualified teachers<br>(% of public)",
    "private_share_enrol": "Private enrolment<br>share (%)",
}

MODEL_TICKS = {
    "Baseline: mean of training states": "Baseline",
    "OLS: region only": "OLS: region",
    "OLS: poverty + region": "OLS: poverty+region",
    "OLS: poverty + PQTR": "OLS: poverty+PQTR",
    "OLS: poverty + region + log PQTR": "OLS: poverty+region+PQTR",
    "Random forest (5 features)": "Random forest",
}


def importance_bars(imp: list[dict]) -> dict:
    d = pd.DataFrame(imp).sort_values("mean_abs_shap")
    labels = d.feature.map(FEATURE_LABELS).fillna(d.feature)
    fig = go.Figure(go.Bar(x=d.mean_abs_shap, y=labels, orientation="h", marker_color=SKY, customdata=d.feature,
                           hovertemplate="%{customdata}: mean |SHAP| %{x:.2f} pp<extra></extra>"))
    fig.update_xaxes(title="Mean |SHAP| (percentage points of predicted OOS) - predictive, NOT causal")
    return _layout(fig, "Feature importance in the predictive model", height=320, yaxis=dict(automargin=True))


def prediction_bars(perf: list[dict]) -> dict:
    d = pd.DataFrame(perf)
    vals = d.model.tolist()
    ticks = [MODEL_TICKS.get(m, m) for m in vals]
    fig = go.Figure()
    fig.add_bar(x=vals, y=d.loo_rmse, name="Leave-one-state-out RMSE", marker_color=BLUE, customdata=vals,
                hovertemplate="%{customdata}<br>state-out RMSE %{y:.1f} pp<extra></extra>")
    fig.add_bar(x=vals, y=d.leave_zone_out_rmse, name="Leave-one-zone-out RMSE", marker_color=ORANGE, customdata=vals,
                hovertemplate="%{customdata}<br>zone-out RMSE %{y:.1f} pp<extra></extra>")
    fig.update_yaxes(title="RMSE (pp)")
    fig.update_xaxes(tickmode="array", tickvals=vals, ticktext=ticks, tickangle=-30)
    return _layout(fig, "Out-of-sample prediction error (lower is better)", height=420,
                   margin=dict(l=60, r=20, t=50, b=170), legend=dict(orientation="h", y=-0.62))


def sim_headline(result: dict) -> dict:
    h = result["headline"]
    fig = go.Figure()
    fig.add_bar(x=["Baseline (2021)", "Counterfactual"], y=[h["baseline_national_oos"], h["counterfactual_national_oos"]], marker_color=[GREY, GREEN], text=[f"{h['baseline_national_oos']:.1f}%", f"{h['counterfactual_national_oos']:.1f}%"], textposition="outside")
    fig.update_yaxes(title="Population-weighted OOS rate (%)", range=[0, h["baseline_national_oos"] * 1.35])
    return _layout(fig, "National out-of-school rate: baseline vs counterfactual", height=320)


def sim_states(result: dict) -> dict:
    d = pd.DataFrame(result["states"])
    d = d[d.covered & (d.change_pp != 0)].sort_values("change_pp")
    if d.empty:
        return _layout(go.Figure(), "No state changes")
    fig = go.Figure()
    for _, r in d.iterrows():
        fig.add_scatter(x=[r.oos_base, r.oos_cf], y=[r.state] * 2, mode="lines", line=dict(color="#9ca3af"), showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=d.oos_base, y=d.state, mode="markers", name="Baseline", marker=dict(color=GREY, size=9))
    fig.add_scatter(x=d.oos_cf, y=d.state, mode="markers", name="Counterfactual", marker=dict(color=GREEN, size=9))
    fig.update_xaxes(title="Out-of-school rate (%)")
    return _layout(fig, "State-level change (point estimates, full implementation)", height=max(340, 20 * len(d) + 120), yaxis=dict(automargin=True, dtick=1))


def sim_compare(rows: list[dict]) -> dict:
    d = pd.DataFrame(rows)
    fig = go.Figure()
    fig.add_bar(x=d.scenario, y=d.change_pp, name="National change", marker_color=GREEN, error_y=dict(type="data", symmetric=False, array=(d.stat_ci_high - d.change_pp).tolist(), arrayminus=(d.change_pp - d.stat_ci_low).tolist()))
    fig.add_bar(x=d.scenario, y=d.north_south_gap_change_pp, name="North-South gap change", marker_color=ORANGE, error_y=dict(type="data", symmetric=False, array=(d.ns_gap_ci_high - d.north_south_gap_change_pp).tolist(), arrayminus=(d.north_south_gap_change_pp - d.ns_gap_ci_low).tolist()))
    fig.add_hline(y=0, line_color="#6b7280", line_dash="dash")
    fig.update_yaxes(title="Change (percentage points); bars = 95% statistical interval")
    return _layout(fig, "Scenario comparison", height=420, barmode="group")


def spec_curve(table: list[dict]) -> dict:
    return forest(table, "Robustness: alternative specifications")
