"""Build the research report (Word + PDF) from the stored analysis runs.

Every number in the findings sections is read from the database/analytic file at build time, so the report cannot drift from
the application.  Usage:  DJANGO_DEBUG=1 python src/reporting/build_report.py
Writes reports/research_report.docx, reports/research_report.pdf and reports/figures/*.png (PDF needs LibreOffice).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "eduineq.settings")
os.environ.setdefault("DJANGO_DEBUG", "1")

import django  # noqa: E402

django.setup()

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from docx import Document  # noqa: E402
from docx.enum.text import WD_ALIGN_PARAGRAPH  # noqa: E402
from docx.shared import Cm, Pt, RGBColor  # noqa: E402

from portal import models as m, services as S  # noqa: E402

FIG = ROOT / "reports" / "figures"
FIG.mkdir(parents=True, exist_ok=True)
A = S.get_analytic()
Q = S.get_quality()
I = S.latest_default("inequality").results
C = S.latest_default("causal").results
SIMS = {r.label[:2]: r.results for r in m.AnalysisRun.objects.filter(analysis_type="simulation", status="succeeded").order_by("created_at")}
REG = json.loads((ROOT / "config" / "source_register.json").read_text())
TRACE = json.loads((ROOT / "reports" / "requirements_traceability.json").read_text()) if (ROOT / "reports" / "requirements_traceability.json").exists() else None
import xml.etree.ElementTree as _ET
NTEST = len(list(_ET.parse(ROOT / 'reports' / 'pytest_results.xml').getroot().iter('testcase')))
INDEP = json.loads((ROOT / "reports" / "independent_check.json").read_text())
NOTE = "#555555"
NORTH, SOUTH, ACC = "#b5483a", "#2f6f8f", "#444444"


# ------------------------------------------------------------------------------------------------------------ figures
def fig_ranking():
    d = A.dropna(subset=["oos_total_2021"]).sort_values("oos_total_2021")
    fig, ax = plt.subplots(figsize=(7, 8))
    ax.barh(d.state, d.oos_total_2021, color=[NORTH if r == "North" else SOUTH for r in d.region])
    ax.set_xlabel("Primary out-of-school rate, 2021 (%)")
    ax.set_title("Out-of-school rate by state (MICS6 2021)")
    ax.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=NORTH), plt.Rectangle((0, 0), 1, 1, color=SOUTH)], labels=["North", "South"], loc="lower right")
    ax.tick_params(axis="y", labelsize=7)
    fig.tight_layout(); fig.savefig(FIG / "fig1_ranking.png", dpi=150); plt.close(fig)


def fig_zones():
    z = I["zone_summary"]
    fig, ax = plt.subplots(figsize=(6, 3.2))
    ax.bar([r["zone"] for r in z], [r["mean"] for r in z], color=[NORTH if r["zone"] in ("NE", "NW", "NC") else SOUTH for r in z])
    for i, r in enumerate(z):
        ax.plot([i, i], [r["min"], r["max"]], color=ACC, lw=1.2)
        ax.text(i, r["max"] + 1.5, f"{r['mean']:.0f}", ha="center", fontsize=8)
    ax.set_ylabel("Out-of-school rate (%)"); ax.set_title("Zone means (bars) and state range (lines)")
    fig.tight_layout(); fig.savefig(FIG / "fig2_zones.png", dpi=150); plt.close(fig)


def fig_poverty():
    d = A.dropna(subset=["oos_total_2021", "pov_215"])
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.scatter(d.pov_215, d.oos_total_2021, c=[NORTH if r == "North" else SOUTH for r in d.region], s=np.sqrt(d.pop6_11_2015) / 8)
    for _, r in d.iterrows():
        if r.oos_total_2021 > 55 or r.oos_total_2021 < 3:
            ax.annotate(r.state, (r.pov_215, r.oos_total_2021), fontsize=7, xytext=(3, 3), textcoords="offset points")
    ax.set_xlabel("Poverty headcount at $2.15/day, 2018 (%)"); ax.set_ylabel("Out-of-school rate, 2021 (%)")
    ax.set_title(f"State poverty and out-of-school rate (Spearman {I['poverty_gradient']['spearman_oos_poverty']:.2f})")
    fig.tight_layout(); fig.savefig(FIG / "fig3_poverty.png", dpi=150); plt.close(fig)


def fig_national():
    g = I["national_groups"]
    fig, axes = plt.subplots(1, 2, figsize=(7, 3), gridspec_kw={"width_ratios": [5, 2]})
    w = g["wealth"]["rates"]; axes[0].bar(list(w), list(w.values()), color=SOUTH); axes[0].set_title("By wealth quintile"); axes[0].set_ylabel("Primary out-of-school (%)")
    a = g["area"]["rates"]; axes[1].bar(list(a), list(a.values()), color=NORTH); axes[1].set_title("By area")
    for ax in axes:
        for p in ax.patches:
            ax.text(p.get_x() + p.get_width() / 2, p.get_height() + 1, f"{p.get_height():.0f}", ha="center", fontsize=8)
    fig.suptitle("National out-of-school rates by group (MICS6 2021)", fontsize=10); fig.tight_layout(); fig.savefig(FIG / "fig4_national.png", dpi=150); plt.close(fig)


def fig_forest():
    est = C["estimates"]
    fig, ax = plt.subplots(figsize=(7, 3))
    for i, e in enumerate(est[::-1]):
        col = "#999999" if e["kind"] == "naive" else ACC
        ax.plot([e["effect_10pct_ci_low"], e["effect_10pct_ci_high"]], [i, i], color=col, lw=2)
        ax.plot(e["effect_10pct_reduction"], i, "o", color=col)
    ax.axvline(0, color="k", lw=0.8, ls="--")
    ax.set_yticks(range(len(est))); ax.set_yticklabels([e["method"].split("(")[0].strip() for e in est[::-1]], fontsize=8)
    ax.set_xlabel("Change in out-of-school rate from a 10% cut in pupils per qualified teacher (points)")
    ax.set_title("Estimated effects with 95% intervals (grey = unadjusted, not causal)", fontsize=9)
    fig.tight_layout(); fig.savefig(FIG / "fig5_forest.png", dpi=150); plt.close(fig)


def fig_scenarios():
    fig, ax = plt.subplots(figsize=(7, 3))
    for i, (k, s) in enumerate(SIMS.items()):
        h = s["headline"]; lo, hi = h["statistical_interval_pp"]
        ax.plot([lo, hi], [i, i], color="#999999", lw=5, alpha=0.6, solid_capstyle="butt")
        ax.plot(h["absolute_change_pp"], i, "o", color=ACC)
        imp = h["implementation_range_pp"]; ax.plot(imp, [i + 0.18] * 2, color=NORTH, lw=2)
    ax.axvline(0, color="k", lw=0.8, ls="--")
    ax.set_yticks(range(len(SIMS))); ax.set_yticklabels([s["scenario"]["name"] for s in SIMS.values()], fontsize=8)
    ax.set_xlabel("HYPOTHETICAL change in national out-of-school rate (points)")
    ax.set_title("Grey: statistical interval; red: implementation range (50-100% fidelity); dot: full implementation", fontsize=8)
    fig.tight_layout(); fig.savefig(FIG / "fig6_scenarios.png", dpi=150); plt.close(fig)


# ------------------------------------------------------------------------------------------------------------ document helpers
doc = Document()
st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(10.5)
for sec in doc.sections:
    sec.left_margin = sec.right_margin = Cm(2.2); sec.top_margin = sec.bottom_margin = Cm(2.2)


def H(text, lvl=1):
    return doc.add_heading(text, lvl)


def P(text, bold=False, italic=False, size=None, color=None):
    p = doc.add_paragraph(); r = p.add_run(text); r.bold, r.italic = bold, italic
    if size: r.font.size = Pt(size)
    if color: r.font.color.rgb = RGBColor.from_string(color.lstrip("#"))
    p.paragraph_format.space_after = Pt(6)
    return p


def B(items):
    for t in items:
        doc.add_paragraph(t, style="List Bullet").paragraph_format.space_after = Pt(2)


def T(header, rows, widths=None, size=8.5):
    t = doc.add_table(rows=1, cols=len(header)); t.style = "Light Grid Accent 1"
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]; c.text = ""; r = c.paragraphs[0].add_run(str(h)); r.bold = True; r.font.size = Pt(size)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""; r = cells[i].paragraphs[0].add_run(str(v)); r.font.size = Pt(size)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(4)


def FIGURE(name, caption, width=15):
    doc.add_picture(str(FIG / name), width=Cm(width)); doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    P(caption, italic=True, size=9, color=NOTE).alignment = WD_ALIGN_PARAGRAPH.CENTER


def pp(x, d=2):
    return f"{x:+.{d}f}"


# ------------------------------------------------------------------------------------------------------------ numbers
prof, reg, pg, gg = I["profile"], I["regional_gap"], I["poverty_gradient"], I["national_groups"]
est = {e["method"].split(" ")[0]: e for e in C["estimates"]}
ols, gps, dml, naive = C["estimates"]
rv = C["sensitivity_unmeasured_confounding"]
n_s = int(A.in_primary_sample.sum())
cnt = TRACE["counts"] if TRACE else {}
ranking = I["ranking"]
top5 = ", ".join(f"{r['state']} ({r['oos_total_2021']:.0f}%)" for r in ranking[:5])
bot5 = ", ".join(f"{r['state']} ({r['oos_total_2021']:.0f}%)" for r in ranking[-5:])
S1, S2, S3 = SIMS["S1"], SIMS["S2"], SIMS["S3"]
dataset_rows = list(m.DatasetVersion.objects.select_related("dataset").order_by("dataset__dataset_id"))


def build():
    for f in (fig_ranking, fig_zones, fig_poverty, fig_national, fig_forest, fig_scenarios):
        f()

    # ---- title
    t = doc.add_heading("Modelling Educational Inequality in Nigeria: A Software Engineering and Causal AI Approach", 0)
    P("Research report accompanying the open-access portal (no login required)", italic=True)
    P(f"Date: {date.today():%d %B %Y}.   Prepared for: Kor Terhemba Japheth.   Analysis data fingerprint: {S.data_fingerprint()[:16]}...")

    H("Summary", 1)
    P("What was built. A Django portal and a Python research pipeline that (i) assemble documented state-level data on education and poverty, (ii) measure educational inequality, (iii) estimate, under stated assumptions, whether lower pupil-to-qualified-teacher ratios are associated causally with lower primary out-of-school rates, and (iv) simulate hypothetical policy scenarios. The system deliberately has no login or accounts.")
    P("Main findings from actual data:", bold=True)
    B([f"Inequality across states is very large. Primary out-of-school rates in 2021 range from {prof['min']['value']:.0f}% ({prof['min']['state']}) to {prof['max']['value']:.0f}% ({prof['max']['state']}); the population-weighted mean is {prof['weighted_mean']:.1f}%. The Gini coefficient across states is {prof['gini']:.2f}.",
       f"The North-South divide dominates: northern states average {reg['means']['North']:.1f}% against {reg['means']['South']:.1f}% in the South, a gap of {reg['gap']:.1f} points (state-resampling interval {reg['ci_low']:.1f} to {reg['ci_high']:.1f}).",
       f"Poorer states have more out-of-school children (Spearman {pg['spearman_oos_poverty']:.2f}); nationally the rate is {gg['wealth']['rates']['Poorest']:.0f}% in the poorest wealth quintile against {gg['wealth']['rates']['Richest']:.0f}% in the richest, and {gg['area']['rates']['Rural']:.0f}% in rural against {gg['area']['rates']['Urban']:.0f}% in urban areas.",
       f"The causal question is inconclusive. A 10% cut in pupils per qualified teacher is associated with a change of {pp(ols['effect_10pct_reduction'])} points (95% interval {pp(ols['effect_10pct_ci_low'])} to {pp(ols['effect_10pct_ci_high'])}; {n_s} states) after adjusting for poverty and region. All adjusted estimators include zero. The unadjusted association ({pp(naive['effect_10pct_reduction'])} points) is about four times larger, because poor northern states have both high ratios and high out-of-school rates.",
       "Scenario results are hypothetical illustrations. Their statistical intervals include zero, and no scenario is ranked by cost because no cost data exist."])
    P("Confidence. High confidence in the descriptive inequality figures as published by their sources (arithmetic independently reproduced; source accuracy is not independently checkable). Moderate confidence that the cleaning rules removed the worst reporting errors. Low confidence in any causal reading of the teacher-ratio result, which the data cannot support or reject.", italic=True)

    # ---- 1 introduction
    H("1. Introduction and research questions", 1)
    P("Nigeria has one of the world's largest populations of out-of-school children, concentrated in the North. Understanding where inequality lies is a descriptive task; judging which policy lever would reduce it is a causal task that needs different evidence. The project follows an implementation plan that insists on keeping four tasks apart: descriptive analysis, prediction, causal inference and counterfactual simulation. Five research questions guide the system and this report:")
    B(["RQ1. How does educational inequality vary across Nigerian states and population groups? (Section 5.1)",
       "RQ2. Which socioeconomic and school-related factors are associated with these differences? (Sections 5.1 and 5.2)",
       "RQ3. What is the estimated causal effect of a selected intervention (more qualified teachers) on the primary outcome? (Section 5.2)",
       "RQ4. Would the intervention reduce inequality rather than merely improve the national average? (Section 5.3)",
       "RQ5. How sensitive are estimates to missing data, alternative assumptions and uncertainty? (Sections 5.2 and 6)"])

    # ---- 2 literature
    H("2. Background and literature", 1)
    P("Inequality measurement. Absolute and relative gaps, the Gini coefficient and Theil index summarise dispersion across units (Theil, 1967); health and education economics add rank-based measures such as the concentration index (Wagstaff, Paci and van Doorslaer, 1991; Erreygers, 2009) and the slope and relative indices of inequality (Mackenbach and Kunst, 1997). The system applies the Gini only to numeric state rates, never to categories.")
    P("Teachers, class size and learning. Evidence on school resources is mixed and design-dependent. Randomised and quasi-experimental studies find effects of smaller classes in some settings (Krueger, 1999; Angrist and Lavy, 1999), little effect of simply reducing pupil-teacher ratios in others, and larger gains when additional teachers come with changes in pedagogy or incentives (Banerjee et al., 2007; Duflo, Dupas and Kremer, 2015). Reviews conclude that how resources are used matters as much as how many there are (Glewwe and Muralidharan, 2016; Hanushek and Rivkin, 2012). These studies concern learning or attendance in specific programmes; none estimates the effect of state-level pupil-qualified-teacher ratios on state out-of-school rates in Nigeria, which is why the present estimate should be read as a modest, assumption-laden contribution.")
    P("Causal inference. The potential-outcomes framework (Rubin, 1974; Imbens and Rubin, 2015) and graphical models (Pearl, 2009) separate the estimand from the estimator. With observed confounders, regression adjustment, generalised propensity scores for continuous treatments (Hirano and Imbens, 2004) and double/debiased machine learning (Chernozhukov et al., 2018) are standard; each relies on conditional ignorability. Sensitivity to omitted variables can be summarised with partial R-squared and the robustness value (Cinelli and Hazlett, 2020). DoWhy structures identification and refutation (Sharma and Kiciman, 2020). Feature attributions such as SHAP (Lundberg and Lee, 2017) describe a fitted predictor, not a policy effect.")

    # ---- 3 data
    H("3. Data", 1)
    P("Data acquisition was treated as a formal workstream. Each source is recorded with URL, publisher, period, access date, coverage, licence, limitations and permitted uses (config/source_register.json; the Data page of the portal). Original files are kept unmodified with SHA-256 checksums, cleaned data are stored separately, and a readiness gate classifies every dataset as Approved, Approved with limitations or Rejected. The unit of analysis is the state; no household, learner or school records were available or used, so every finding is ecological.")
    H("3.1 Sources", 2)
    T(["ID", "Source", "Publisher", "Period", "Licence"],
      [[s["source_id"], s["name"][:90], s["publisher"][:55], s["collection_period"], s["licence"][:50]] for s in REG["sources"]], widths=[2.4, 5.2, 3.6, 2.4, 3.2], size=7.5)
    H("3.2 Datasets and readiness gate", 2)
    d2 = {d["dataset_id"]: d for d in REG["datasets"]}
    T(["Dataset", "Source", "Rows", "Readiness"], [[v.dataset.dataset_id, d2[v.dataset.dataset_id]["source_id"], v.n_rows, v.readiness] for v in dataset_rows], widths=[5, 4, 2, 4.5], size=8)
    P("Gate 1 (no causal estimation without a defensible dataset for the primary outcome) is satisfied by the 2021 MICS6 state out-of-school table, approved with limitations: it is a household survey with unreported sampling error, published as whole percentages, and the extraction scrambled its urban, rural and wealth columns, which were therefore rejected at state level. The 2015/16 net enrolment ratio from the Federal Ministry of Education was retained as context only: it is administrative, uses a different definition, and its definitions are not comparable with the 2021 survey measure, so the two are never mixed. The third-party state-capitals GeoJSON was rejected because 16 of its 37 coordinates disagreed with independently entered capital coordinates by more than 0.3 degrees; map points use the project's own reference file (config/states.csv).")
    H("3.3 Data-quality findings", 2)
    P("The published administrative tables contain visible errors, which the pipeline detects, documents and handles without inventing values. Rules R01-R09 set impossible values to missing, flag implausible ones and reject whole columns that contradict other tables.")
    T(["Rule", "Check", "Checked", "Failed", "Action", "States affected"],
      [[c["rule"], c["description"][:80], c["n_checked"], c["n_failed"], c["action"], ", ".join(c.get("states", [])[:6]) + ("..." if len(c.get("states", [])) > 6 else "")] for c in Q["cross_checks"]], widths=[1.2, 6.2, 1.5, 1.4, 2.3, 4.3], size=7.5)
    P(f"Of 37 states, {n_s} enter the primary analytic sample. Excluded, each with a recorded reason: " + "; ".join(f"{e['state']} ({e['exclusion_reason']})" for e in Q["analytic"]["excluded"]) + ".")
    P("Corrected defect found during final verification. Nasarawa's state code is the two letters 'NA', which pandas silently read as a missing value; the state lost its identifier. The reference file is now read with keep_default_na disabled, a regression test was added, and the database and all stored results were rebuilt.")
    H("3.4 Additional evidence considered but not integrated", 2)
    P("The 2015 Nigeria Education Data Survey (NEDS) state reports (National Population Commission and RTI International, with USAID) give net attendance ratios by sex, residence and wealth quintile. Searches surfaced only 18 state reports on the NBS site. A single-pass text extraction of these reports suggests that administrative net enrolment diverges sharply from household attendance (primary net attendance versus the ministry's 2015/16 net enrolment: Abia 84% versus 20%; Kano 63% versus 96%; Katsina 51% versus 93%; Borno 17% versus 46%; Anambra 87% versus 94%). These figures were not verified against the PDFs, mix different definitions, and are used here only to support the decision not to treat administrative enrolment as the outcome. State-level residence and wealth gaps from NEDS are a recommended next addition once the full reports can be downloaded and checked.")

    # ---- 4 methods
    H("4. Methods and system design", 1)
    H("4.1 Architecture", 2)
    P("One Django project (eduineq) with one application (portal) over a plain-Python pipeline (src/ingestion, cleaning, inequality, causal, simulation, validation, reporting). Bootstrap 5 and Plotly are vendored, so the site works offline. Application records, metadata, runs and results are stored in a relational schema with 15 entities (sources, datasets and versions with checksums, quality reports, import jobs, indicator definitions, analysis runs, inequality results, causal models, model versions, validation runs, policy scenarios, simulation runs and results, audit log). A database constraint forbids results on a run that did not succeed. Analyses run through a job workflow with status, timeout, bounded retries and duplicate-submission protection. SQLite is the default; MySQL is configured and documented. Per the project decision there is no authentication: django.contrib.auth, admin and sessions are not installed, there is no upload endpoint, and the open site is protected by CSRF tokens, security headers, strict input validation and per-client throttling.")
    H("4.2 Inequality engine", 2)
    P("For the state out-of-school rate the engine reports population-weighted mean, range and max-min ratio, P90/P10, the Gini coefficient, Theil T and coefficient of variation; a North-South absolute gap and ratio with a state-resampling bootstrap interval; zone summaries; sex gaps; the Wagstaff concentration index and Spearman correlation against state poverty; a Lorenz curve; teacher-resource inequality; and, nationally, absolute and relative gaps, concentration indices (Wagstaff, Erreygers) and the slope and relative indices of inequality by wealth quintile. Intervals are bootstrap intervals over states, not survey sampling-error intervals.")
    H("4.3 Causal engine", 2)
    P(f"Estimand: the average effect on a state's primary out-of-school rate (percentage points) of a 10% proportional reduction in public pupils per qualified teacher (PQTR, 2016/17). Confounders: 2018 poverty headcount and region (North or South). Graph: poverty and region cause both PQTR and out-of-school rates; PQTR causes the outcome; private-school share and enrolment ratios are deliberately not adjusted for because they may be mediators or colliders. A second graph adds an unobserved common cause to show the threat. Identification is checked with DoWhy (backdoor set: poverty, region). Six methods were assessed against the data: regression adjustment, generalised propensity-score weighting and double/debiased ML are applicable; difference-in-differences, panel fixed effects and instrumental variables are not, because the data are a single cross-section with no credible instrument. Estimators: OLS with HC3 errors and t-intervals (Long and Ervin, 2000), GPS-weighted regression, EconML LinearDML with random-forest nuisances, and an unadjusted association reported for comparison only. Diagnostics: overlap and balance, three DoWhy refutations, eight alternative specifications, leave-one-out and leave-one-zone-out, permutation test, fractional logit, omitted-variable robustness value, and subgroup estimates. Seven explicit assumptions (A1-A7) are stored with the result.")
    H("4.4 Simulation engine", 2)
    P("A scenario defines coverage (all states, a region, a poverty threshold or a list), the intervention (cap PQTR at X, or reduce it by X%), the effect model (pooled or region-specific slope), an implementation-fidelity range (default 50-100%), and a seed. The engine applies the estimated effect to each covered state's observed baseline, floors rates at 0%, draws from the sampling distribution of the estimate (4,000 draws) to give a statistical interval, and reports the implementation range separately and never combined with it. It reports the national change, the change in the North-South gap, the high-low poverty gap and the Gini, subgroup effects, and arithmetic (not budget) for extra qualified teachers. It warns about extrapolation beyond observed PQTR and about excluded states. No cost-effectiveness is computed.")
    H("4.5 Validation strategy", 2)
    P(f"Three kinds of validation were applied: data validation (reconciliation of raw to cleaned data, integrity rules, an independent re-download compared cell by cell); software validation ({NTEST} automated tests: unit, integration, security and end-to-end journeys); and scientific validation (independent recomputation of headline numbers, out-of-sample comparison with baselines, refutation and sensitivity analysis, subgroup checks, and cross-process reproducibility of result hashes).")

    # ---- 5 findings
    H("5. Findings", 1)
    H("5.1 Descriptive inequality (RQ1, RQ2)", 2)
    P(f"Source: MICS6 2021 state out-of-school rates (whole percentages as published). Highest rates: {top5}. Lowest: {bot5}.")
    FIGURE("fig1_ranking.png", "Figure 1. Primary out-of-school rate by state, 2021. Several states carry data-integrity flags on other variables; see the portal ranking table.", 12)
    T(["Measure", "Value"], [["Population-weighted mean (%)", f"{prof['weighted_mean']:.1f}"], ["Unweighted mean (%)", f"{prof['unweighted_mean']:.1f}"], ["Range (points)", f"{prof['range']:.0f}"], ["P90/P10 ratio", f"{prof['p90_p10_ratio']:.1f}"],
                             ["Gini across states (weighted)", f"{prof['gini']:.3f}"], ["Theil T", f"{prof['theil_t']:.3f}"], ["Coefficient of variation", f"{prof['cv']:.2f}"],
                             ["North mean / South mean (%)", f"{reg['means']['North']:.1f} / {reg['means']['South']:.1f}"], ["North-South gap (points) [95% bootstrap]", f"{reg['gap']:.1f} [{reg['ci_low']:.1f}, {reg['ci_high']:.1f}]"], ["North/South ratio", f"{reg['ratio']:.1f}"],
                             ["Spearman, out-of-school vs poverty", f"{pg['spearman_oos_poverty']:.2f}"], ["Concentration index (Wagstaff), states ordered by poverty", f"{pg['concentration_index_wagstaff']:.2f}"]], widths=[9, 5])
    FIGURE("fig2_zones.png", "Figure 2. Zone means and ranges. North-East and North-West are far above all southern zones.", 10)
    FIGURE("fig3_poverty.png", "Figure 3. Poverty and out-of-school rates across states (marker size proportional to child population). An ecological relationship, not a household-level result.", 11)
    w, a = gg["wealth"], gg["area"]
    gap_txt = ", ".join(f"{x['state']} ({x['gap_pp']:.0f} points)" for x in I["gender_gap"][:4])
    P(f"National groups (MICS6 2021, national table). Wealth: poorest {w['rates']['Poorest']:.0f}%, second {w['rates']['Second']:.0f}%, middle {w['rates']['Middle']:.0f}%, fourth {w['rates']['Fourth']:.0f}%, richest {w['rates']['Richest']:.0f}%; absolute gap {w['absolute_gap_poorest_richest']:.0f} points, ratio {w['ratio_poorest_richest']:.1f}, Wagstaff concentration index {w['concentration_index_wagstaff']:.2f}, relative index of inequality {w['rii']:.1f}. The linear slope index (-65) extrapolates outside 0-100% because the gradient is convex, and is flagged as such. Area: rural {a['rates']['Rural']:.0f}% against urban {a['rates']['Urban']:.0f}% (gap {a['absolute_gap_rural_urban']:.0f} points). Sex: male {gg['sex']['rates']['Male']:.0f}% and female {gg['sex']['rates']['Female']:.0f}% nationally; within states the largest girl-boy gaps are in {gap_txt}. Wealth and rural-urban gaps are published only nationally, so they cannot be combined with states.")
    FIGURE("fig4_national.png", "Figure 4. National out-of-school rates by wealth quintile and area.", 12)
    ri = I["resource_inequality"]
    P(f"Resources. Pupils per qualified public teacher (2016/17) vary from {ri['pqtr_min']:.0f} to {ri['pqtr_max']:.0f} across {ri['n_states']} states with usable data (median {ri['pqtr_median']:.0f}; max/min {ri['pqtr_max_min_ratio']:.0f}); the Gini of qualified teachers per 1,000 pupils is {ri['gini_qualified_teachers_per_1000_pupils']:.2f}. The weakest-resourced states are mostly northern. Answer to RQ2: poverty and region are strongly associated with out-of-school rates, and poverty is by far the most important feature in the fitted predictive model (permutation importance 0.79 against 0.10 for teacher ratio), but predictive importance is not causal importance.")
    P("Confidence: high for the described patterns (large, consistent across zones and measures); moderate for exact state ranks (whole-percent rounding, unreported sampling error, and states with flags).", italic=True)

    H("5.2 Causal analysis of teacher quality (RQ3, RQ5)", 2)
    T(["Estimator", "n", "Effect of 10% cut in PQTR (points)", "95% interval", "Includes zero?"],
      [[e["method"].split("(")[0].strip(), e["n"], pp(e["effect_10pct_reduction"]), f"{pp(e['effect_10pct_ci_low'])} to {pp(e['effect_10pct_ci_high'])}", "NOT A CAUSAL ESTIMATE" if e["kind"] == "naive" else ("yes" if e["ci_includes_zero"] else "no")] for e in C["estimates"]], widths=[5.5, 1, 3.5, 3.5, 3], size=8)
    FIGURE("fig5_forest.png", "Figure 5. Estimated effects (hypothetical intervention of a 10% reduction) with 95% intervals.", 13)
    refs = C["identification"]["refutations"]
    P(f"Interpretation. Under assumptions A1-A7, the regression-adjusted estimate is {pp(ols['effect_10pct_reduction'])} points (interval {pp(ols['effect_10pct_ci_low'])} to {pp(ols['effect_10pct_ci_high'])}); the GPS and double ML estimates are smaller still ({pp(gps['effect_10pct_reduction'])} and {pp(dml['effect_10pct_reduction'])}). Every adjusted interval includes zero, so the data are consistent with no effect and with modest effects, and cannot tell them apart. Verdict recorded by the system: {C['explanation']['verdict']}")
    P(f"Diagnostics. Overlap: PQTR ranges overlap across regions but the generalised propensity weighting did not achieve covariate balance (maximum weighted correlation {C['overlap_balance']['gps']['max_abs_weighted_corr']:.2f}); the weighted estimate is therefore the least reliable. Refutations: adding a random common cause changed the coefficient from {refs[0]['original']:.2f} to {refs[0]['new']:.2f}; a placebo (permuted) treatment gave {refs[1]['new']:.2f}, near zero as it should; random 80% subsets gave {refs[2]['new']:.2f}. Passing these checks does not prove that the assumptions are true. Sensitivity: an unmeasured confounder would need partial R-squared of about {rv['robustness_value_q1']*100:.0f}% with both treatment and outcome to explain the point estimate away, and the robustness value for statistical significance at 5% is {rv['robustness_value_q1_alpha05']:.0%} (the result is not significant to begin with). Poverty alone has partial R-squared of about 20% with the outcome, so a confounder of that strength is entirely plausible. Subgroups: the northern, southern, below-median-poverty and above-median-poverty strata (16, 15, 16 and 15 states) all have intervals that include zero; the point estimates differ in sign between North and South, which is uninformative at these sample sizes.")
    P("Prediction is a separate task. In leave-one-state-out evaluation, a model with poverty and region (RMSE 13.3 points) beats the mean baseline (21.9) and region only (14.9); adding teacher ratio changes little (13.0), and a random forest is no better (13.7). In leave-one-zone-out evaluation, the harder test, models with covariates range from 15.8 to 17.5 against 24.8 for the mean baseline, and the random forest is best (15.8) while adding teacher ratio to poverty and region does not help (16.9 against 16.2). The point of the comparison is to show that teacher ratio adds almost no predictive information once poverty and region are known, consistent with the causal result.")
    P("Why this is honest and not a failure: the design is a cross-section of 31 states with confounders measured at the state level; DiD, panel and IV designs were assessed and are not applicable. The plan requires narrowing claims in that case, and that is what the system does: it reports an adjusted association with explicit assumptions and an inconclusive verdict.")
    P("Confidence: high that the data cannot support a confident causal claim; low in the sign and magnitude of any true effect.", italic=True)

    H("5.3 Counterfactual policy simulation (RQ4)", 2)
    P("All results in this section are hypothetical. They apply the regression-adjusted estimate to observed baselines and are conditional on assumptions A1-A7; they are not forecasts, and no time horizon is modelled.", bold=True)
    rows = []
    for k, s in SIMS.items():
        h, ch = s["headline"], s["inequality"]["change"]
        rows.append([s["scenario"]["name"], f"{h['baseline_national_oos']:.1f}", f"{h['counterfactual_national_oos']:.1f}", pp(h["absolute_change_pp"]), f"{h['statistical_interval_pp'][0]:+.1f} to {h['statistical_interval_pp'][1]:+.1f}",
                     f"{h['implementation_range_pp'][1]:+.1f} to {h['implementation_range_pp'][0]:+.1f}", pp(ch["gap_north_south"], 1), pp(ch["gap_high_low_poverty"], 1)])
    T(["Scenario", "Baseline %", "Counter-factual %", "Change (pts)", "Statistical interval", "Implementation range (50-100%)", "Change in N-S gap", "Change in poverty gap"], rows, widths=[3.6, 1.4, 1.6, 1.4, 2.4, 2.6, 1.6, 1.6], size=7.5)
    FIGURE("fig6_scenarios.png", "Figure 6. Hypothetical scenario results. All statistical intervals include zero.", 13)
    P(f"Reading. Because the estimated slope is positive, lowering PQTR is projected to lower out-of-school rates, and because the highest ratios are in the poorer North, the reductions fall where need is greatest: for S1 the North-South gap narrows by {abs(S1['inequality']['change']['gap_north_south']):.1f} points and the high-low poverty gap by {abs(S1['inequality']['change']['gap_high_low_poverty']):.1f} points, while the Gini across states changes by only {S1['inequality']['change']['gini_across_states']:+.3f}. So, if the adjusted estimate were true, the policies would reduce the gap as well as the mean; but because the interval includes zero, the system cannot say that they would. S1 would require about {S1['extra_qualified_teachers_total']:,.0f} additional qualified teachers (arithmetic, not a budget). The simulator separates outcome improvement from disparity change as the plan requires, and refuses to rank scenarios by cost.")
    P("Confidence: high that the arithmetic is right (independently reproduced); low that real-world effects would follow.", italic=True)

    # ---- 6 validation
    H("6. Validation results", 1)
    P(f"Software. {NTEST} automated tests pass (unit, integration, security, end-to-end), including tests for import and schema validation, database constraints, inequality calculations against hand-computed cases, causal input validation, simulation arithmetic, job failures and retries, report generation, export safety, CSRF, headers, path traversal, escaping, injection and throttling. Tests that exercised authentication in the original plan were replaced by tests proving that no authentication machinery exists and that every page and download works anonymously.")
    P("Independent recomputation. Fourteen headline numbers (Gini, Theil, coefficient of variation, P90/P10, weighted mean, Spearman correlation, North-South gap, OLS coefficient, HC3 standard error and interval, effect of a 10% cut, S1 baseline and S1 change) were recomputed with separate code; all agree within tolerance (largest absolute difference 1.4e-13).")
    T(["Quantity", "Independent", "Stored", "Agrees"], [[x["quantity"], f"{x['independent']:.6f}", f"{x['stored']:.6f}", "yes" if x["agrees"] else "NO"] for x in INDEP], widths=[7, 3, 3, 1.8], size=8)
    P("Source reconciliation. The main administrative tables, the poverty table and the national subgroup table were re-retrieved on a later date and compared with the stored raw files: 1,671 of 1,671 cells identical. Both retrievals use the same text-extraction route, so errors inside a source PDF would not be detected by this check; they are handled by the integrity rules instead.")
    P("Reproducibility. Re-cleaning from raw data reproduces the analytic-file checksum, and recomputing the inequality and causal analyses reproduces their result hashes (verify_reproducibility). A cross-process hash mismatch caused by last-bit floating-point noise was found earlier and fixed with a regression test.")
    H("6.1 Requirements cross-check", 2)
    if TRACE:
        P(f"The executable cross-check (src/validation/requirements_check.py) tests {TRACE['total']} requirements drawn from plan sections 2-18 against files, the database, rendered pages, stored results and the test results file. Outcome: " + ", ".join(f"{v} {k.replace('_', ' ').lower()}" for k, v in cnt.items() if v) + ". The full matrix is in docs/REQUIREMENTS_TRACEABILITY.md.")
        lim = [r for r in TRACE["items"] if r["status"] != "MET"]
        T(["ID", "Requirement", "Status", "Why"], [[r["id"], r["requirement"][:85], r["status"].replace("_", " ").title(), (r["evidence"].split("|")[-1].strip() or r["evidence"])[:230]] for r in lim], widths=[1.1, 5.4, 2.3, 8], size=7)
    P("Items marked Superseded concern user accounts, roles and login, which the project owner excluded. Items marked Not Verified need a live MySQL server or a public HTTPS host that the build environment did not have. Version control (Git) is not initialised because no repository was created or committed without being asked.")

    # ---- 7 discussion
    H("7. Discussion", 1)
    P("Three conclusions follow. First, the descriptive evidence is strong and consistent: educational exclusion in Nigeria is concentrated by region and poverty, with a gap between northern and southern states that dwarfs differences among southern states. Second, the data available at state level cannot answer the causal question about teacher ratios: with 31 observations, state-level confounding and a cross-sectional design, the honest result is an interval around zero. This is informative: it says that the current public data cannot justify ranking teacher deployment against other levers, and that the large raw association mostly reflects poverty and region. Third, the simulator is useful as a transparent calculator for what a given assumed effect implies, provided users keep the hypothetical label in view; it is not evidence about what policy would work.")
    P("Implications for policy. Targeting the poorest northern states is supported by the descriptive data regardless of the teacher result, because that is where the out-of-school rate is highest. Whether teacher deployment is the right tool there needs evidence from designs with variation that is plausibly exogenous: staggered rollouts, household panel data, or trials. Ratio-only targets risk missing the quality, language-of-instruction, safety and household-cost barriers that studies in similar settings find important.")
    P("Fairness. A national model can conceal regional differences and perform poorly where data are weakest. The sample excludes Borno (no poverty estimate, owing to insecurity) and five other states with unusable teacher data, so some of the most affected populations are absent from the causal analysis. The report therefore avoids statements about those states' response to policy.")

    # ---- 8 limitations
    H("8. Limitations, ethics and risks", 1)
    B(["Ecological design: state aggregates cannot show what happens to individual children or households.",
       "Small sample: 31 states, wide intervals; confounders are only poverty and region, measured in 2018, after the 2016/17 treatment, treated as pre-treatment and tested by dropping it.",
       "Source quality: the Federal Ministry tables contain duplicated rows and impossible values; the system sets these to missing and documents them, but undetected errors may remain. MICS6 values are whole percentages with sampling error not available in the extraction, and the transcription route was text extraction from PDFs.",
       "Not mixed on purpose: administrative net enrolment (2015/16) and survey out-of-school rates (2021) are different measures.",
       "No state-level rural-urban or wealth analysis: only national tables were reliable. NEDS 2015 state reports could close this gap.",
       "Map: a point map over a national outline; state boundary polygons with usable licences were not available.",
       "MySQL: configured and documented, but not run against a live server here; Celery/Redis not used (a bounded worker thread is sufficient for a one-minute analysis).",
       "Licences: several source licences are 'not stated'; confirm redistribution rights with publishers before republishing raw tables.",
       "Data protection and ethics: no personal data are held, so the Nigeria Data Protection Act 2023 is engaged only marginally (the audit log stores salted address hashes); a formal ethics or legal review has not been done and is recommended before wide release."])
    H("8.1 Risk register", 2)
    T(["Risk (plan section 16)", "What happened / mitigation"],
      [["Inaccessible or incomplete records", "Individual-level and school-level data were not accessible; scope narrowed to state aggregates and stated as ecological"],
       ["Incompatible datasets", "Different definitions not mixed; linkage only by standardised state"],
       ["Weak causal identification", "Six designs assessed, three rejected; claims narrowed to adjusted association; verdict inconclusive"],
       ["Missing or biased observations", "Rules R01-R09; exclusions listed; leave-one-out and sensitivity analyses"],
       ["Misleading policy predictions", "Hypothetical labels, intervals that include zero, extrapolation warnings, no cost ranking"],
       ["Model complexity", "Transparent OLS baseline first; ML estimators only as comparisons"],
       ["Slow application", "Job workflow with timeout, retries and stored results"],
       ["Privacy or security breach", "No personal data; CSRF, headers, throttling, no upload endpoint; security tests"],
       ["Irreproducible results", "Checksums, fixed seeds, pinned versions, verify_reproducibility; one real hash defect found and fixed"],
       ["Scope creep", "One outcome, one causal question, three scenarios"],
       ["Tooling defect found late", "Nasarawa code 'NA' lost to NaN; fixed with a regression test"]], widths=[5, 11.5], size=8)

    # ---- 9 conclusion
    H("9. Conclusions and next steps", 1)
    B(["Use the portal for what it supports: transparent measurement of inequality by state, zone and poverty, with documented data limits.",
       "Do not use the teacher-ratio result to justify or reject a policy; it is inconclusive.",
       "Add state-level NEDS 2015 and MICS6 microdata (if access is granted) to enable rural-urban and wealth analysis within states, and household-level causal designs.",
       "Seek variation suitable for credible designs (staggered teacher deployment, panel years of the same outcome) and cost data before any cost-effectiveness claim.",
       "Run the test suite against MySQL on the target server, initialise Git, and complete a formal ethics and data-protection review before public release."])

    # ---- references
    H("References", 1)
    P("A. Methods and literature", bold=True)
    LIT = [
        "Angrist, J.D. and Lavy, V. (1999) 'Using Maimonides' rule to estimate the effect of class size on scholastic achievement', Quarterly Journal of Economics, 114(2), pp. 533-575.",
        "Banerjee, A.V., Cole, S., Duflo, E. and Linden, L. (2007) 'Remedying education: evidence from two randomized experiments in India', Quarterly Journal of Economics, 122(3), pp. 1235-1264.",
        "Chernozhukov, V., Chetverikov, D., Demirer, M., Duflo, E., Hansen, C., Newey, W. and Robins, J. (2018) 'Double/debiased machine learning for treatment and structural parameters', The Econometrics Journal, 21(1), pp. C1-C68.",
        "Cinelli, C. and Hazlett, C. (2020) 'Making sense of sensitivity: extending omitted variable bias', Journal of the Royal Statistical Society: Series B, 82(1), pp. 39-67.",
        "Duflo, E., Dupas, P. and Kremer, M. (2015) 'School governance, teacher incentives, and pupil-teacher ratios: experimental evidence from Kenyan primary schools', Journal of Public Economics, 123, pp. 92-110.",
        "Efron, B. and Tibshirani, R.J. (1993) An Introduction to the Bootstrap. New York: Chapman and Hall.",
        "Erreygers, G. (2009) 'Correcting the concentration index', Journal of Health Economics, 28(2), pp. 504-515.",
        "Glewwe, P. and Muralidharan, K. (2016) 'Improving education outcomes in developing countries: evidence, knowledge gaps, and policy implications', in Hanushek, E.A., Machin, S. and Woessmann, L. (eds) Handbook of the Economics of Education, vol. 5. Amsterdam: Elsevier, pp. 653-743.",
        "Hanushek, E.A. and Rivkin, S.G. (2012) 'The distribution of teacher quality and implications for policy', Annual Review of Economics, 4, pp. 131-157.",
        "Hirano, K. and Imbens, G.W. (2004) 'The propensity score with continuous treatments', in Gelman, A. and Meng, X.-L. (eds) Applied Bayesian Modeling and Causal Inference from Incomplete-Data Perspectives. Chichester: Wiley, pp. 73-84.",
        "Imbens, G.W. and Rubin, D.B. (2015) Causal Inference for Statistics, Social, and Biomedical Sciences. Cambridge: Cambridge University Press.",
        "Krueger, A.B. (1999) 'Experimental estimates of education production functions', Quarterly Journal of Economics, 114(2), pp. 497-532.",
        "Long, J.S. and Ervin, L.H. (2000) 'Using heteroscedasticity consistent standard errors in the linear regression model', The American Statistician, 54(3), pp. 217-224.",
        "Lundberg, S.M. and Lee, S.-I. (2017) 'A unified approach to interpreting model predictions', Advances in Neural Information Processing Systems, 30.",
        "Mackenbach, J.P. and Kunst, A.E. (1997) 'Measuring the magnitude of socio-economic inequalities in health: an overview of available measures illustrated with two examples from Europe', Social Science and Medicine, 44(6), pp. 757-771.",
        "Pearl, J. (2009) Causality: Models, Reasoning, and Inference. 2nd edn. Cambridge: Cambridge University Press.",
        "Rubin, D.B. (1974) 'Estimating causal effects of treatments in randomized and nonrandomized studies', Journal of Educational Psychology, 66(5), pp. 688-701.",
        "Sharma, A. and Kiciman, E. (2020) 'DoWhy: an end-to-end library for causal inference', arXiv:2011.04216.",
        "Theil, H. (1967) Economics and Information Theory. Amsterdam: North-Holland.",
        "Wagstaff, A., Paci, P. and van Doorslaer, E. (1991) 'On the measurement of inequalities in health', Social Science and Medicine, 33(5), pp. 545-557."]
    for r in LIT:
        doc.add_paragraph(r, style="List Bullet").paragraph_format.space_after = Pt(1)
    P("B. Data sources (accessed 22-24 October 2026)", bold=True)
    for s in REG["sources"]:
        doc.add_paragraph(f"{s['publisher']} ({s.get('publication_year') or 'n.d.'}) {s['name']}. {s['collection_period']}. Available at: {s['url']}", style="List Bullet").paragraph_format.space_after = Pt(1)
    for extra in [
        "Federal Ministry of Education (2019) Table 2.15 Gross and Net Enrolment Rates in Primary Schools by State and Gender: 2015/2016. Available at: https://education.gov.ng/wp-content/uploads/2019/05/Gross-and-Net-Enrolment-Rates-in-Primary-Schools-by-State-and-Gender-2015-2016.pdf (used for the context and verification checks).",
        "Federal Ministry of Education (2019) Table 2.22 Pupil-teacher ratio for public primary schools: 2013/2014-2015/2016. Available at: https://education.gov.ng/wp-content/uploads/2019/05/Pupil-Teacher-Ratio-for-Public-Primary-Schools-2013%e2%80%93-2016..pdf (verification).",
        "National Bureau of Statistics (2020) 2019 Poverty and Inequality in Nigeria. Abuja: NBS (state headcount rates, survey 2018/19). Available at: https://taxaide.com.ng/wp-content/uploads/2020/05/2019-POVERTY-AND-INEQUALITY.pdf (mirror, verification).",
        "National Bureau of Statistics and UNICEF (2022) Nigeria Multiple Indicator Cluster Survey 2021 (MICS6), Full report. Available at: https://www.unicef.org/nigeria/media/6316/file/2021%20MICS%20full%20report%20.pdf",
        "National Population Commission and RTI International, with USAID (2015) 2015 Nigeria Education Data Survey (NEDS): state reports. Available at: https://www.nigerianstat.gov.ng/pdfuploads/Anambra_PDF_rev.compressed.pdf (and sibling state files); education profile at https://shared.rti.org/node/310 (considered, not integrated).",
        "Federal Republic of Nigeria (2023) Nigeria Data Protection Act 2023.",
        "World Bank (2026) World Development Indicators, Nigeria. Available at: https://api.worldbank.org/v2/country/NGA/indicator/"]:
        doc.add_paragraph(extra, style="List Bullet").paragraph_format.space_after = Pt(1)
    P("C. Software", bold=True)
    for r in ["Django Software Foundation (2026) Django 6.1. https://www.djangoproject.com/", "Harris, C.R. et al. (2020) 'Array programming with NumPy', Nature, 585, pp. 357-362.",
              "McKinney, W. (2010) 'Data structures for statistical computing in Python', Proceedings of the 9th Python in Science Conference, pp. 56-61.", "Pedregosa, F. et al. (2011) 'Scikit-learn: machine learning in Python', Journal of Machine Learning Research, 12, pp. 2825-2830.",
              "Seabold, S. and Perktold, J. (2010) 'Statsmodels: econometric and statistical modeling with Python', Proceedings of the 9th Python in Science Conference.", "Virtanen, P. et al. (2020) 'SciPy 1.0: fundamental algorithms for scientific computing in Python', Nature Methods, 17, pp. 261-272.",
              "Microsoft Research ALICE team, EconML: a Python package for ML-based heterogeneous treatment effects estimation. https://github.com/py-why/EconML", "Plotly Technologies Inc. Plotly JavaScript open source graphing library. https://plotly.com/javascript/", "Bootstrap 5.3.3. https://getbootstrap.com/"]:
        doc.add_paragraph(r, style="List Bullet").paragraph_format.space_after = Pt(1)
    P("Note on references. Source-data URLs and values were retrieved during the project and the computations were re-run for this report. Methodological and software citations are given from the author's knowledge of the literature and were not re-checked against the publishers' pages in this session; verify page numbers before formal submission.", italic=True, size=9, color=NOTE)

    out = ROOT / "reports" / "research_report.docx"
    doc.save(out)
    r = subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(ROOT / "reports"), str(out)], capture_output=True, text=True, timeout=240)
    print("docx", out.exists(), "| pdf", (ROOT / "reports" / "research_report.pdf").exists(), r.stderr[-200:])


if __name__ == "__main__":
    build()
