"""PDF / Excel exports (plan section 10.3).

Every export carries the analysis-run identifier, configuration hash, data checksum, results checksum and
software versions, so each exported figure can be traced to its run and to the exact dataset version.
"""
from __future__ import annotations

import io
import json
import logging
from datetime import date

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import models as m, plotting as P, services as S

TITLES = {"inequality": "Educational inequality analysis", "causal": "Causal analysis (PQTR and primary out-of-school rate)",
          "simulation": "Counterfactual policy simulation (hypothetical what-if)"}
HYPOTHETICAL = ("Simulation results are hypothetical what-if calculations conditional on an estimated effect; they are not forecasts "
                "and not empirical findings. No cost data were used, so no scenario is ranked by cost-effectiveness.")


# ------------------------------------------------------------------------------------------------ helpers
def _meta(run) -> list[tuple[str, str]]:
    return [("Run identifier", str(run.public_id)), ("Analysis type", run.analysis_type), ("Label", run.label or "-"),
            ("Created (UTC)", run.created_at.strftime("%Y-%m-%d %H:%M:%S")), ("Status", run.status),
            ("Configuration hash", run.config_hash), ("Data fingerprint (SHA-256)", run.data_sha256), ("Results hash (SHA-256)", run.results_sha256 or "-"),
            ("Configuration", json.dumps(run.config, sort_keys=True))]


def _flat(v):
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, default=str, ensure_ascii=False)
    return v


def _narrative(run) -> list[tuple[str, list[str]]]:
    r = run.results or {}
    out = []
    if run.analysis_type == "causal":
        ex = r.get("explanation", {})
        out.append(("Verdict", [ex.get("verdict", "")]))
        out.append(("Summary", ex.get("summary", [])))
        out.append(("Warnings", r.get("warnings", [])))
        out.append(("Assumptions", [_flat(a) if not isinstance(a, str) else a for a in r.get("specification", {}).get("assumptions", [])]))
    elif run.analysis_type == "simulation":
        out.append(("Interpretation", [r.get("interpretation", "")]))
        out.append(("Assumptions", r.get("assumptions", [])))
        out.append(("Warnings", r.get("warnings", [])))
        out.append(("Status of these results", [HYPOTHETICAL]))
    else:
        out.append(("Warnings", r.get("warnings", [])))
        out.append(("Notes", [r.get("resource_inequality_note", ""), r.get("national_groups", {}).get("note", "")]))
    return [(h, [x for x in xs if x]) for h, xs in out if any(xs)]


def _tables(run) -> dict[str, list[dict]]:
    r = run.results or {}
    t: dict[str, list[dict]] = {}
    if run.analysis_type == "causal":
        t["Estimates"] = r["estimates"]
        t["Specification curve"] = r["robustness"]["specification_table"]
        t["Leave one out"] = [{"measure": k, "value": _flat(v)} for k, v in (r["robustness"].get("leave_one_out") or {}).items()]
        t["Subgroups"] = [{"stratum": k, **v} for k, v in (r["subgroups"].get("strata") or {}).items() if isinstance(v, dict)]
        t["Feature importance"] = r["explainability"].get("importance", [])
        t["Predictive performance"] = r["explainability"].get("predictive_performance", [])
    elif run.analysis_type == "simulation":
        h = r["headline"]
        t["Headline"] = [{"measure": k, "value": _flat(v)} for k, v in h.items()]
        t["Inequality"] = [{"measure": k, "baseline": r["inequality"]["baseline"].get(k), "counterfactual": r["inequality"]["counterfactual"].get(k),
                            "change": r["inequality"]["change"].get(k), "statistical_interval_95": _flat(r["inequality"]["statistical_interval_95"].get(k))}
                           for k in r["inequality"]["baseline"]]
        t["Subgroup effects"] = r["subgroups"]
        t["States"] = r["states"]
    else:
        t["Ranking"] = r["ranking"]
        t["Zones"] = r.get("zone_summary") or []
        t["Gender gap"] = r.get("gender_gap") or []
        t["Profile"] = [{"measure": k, "value": _flat(v)} for k, v in r["profile"].items()]
        t["Resource inequality"] = [{"measure": k, "value": _flat(v)} for k, v in (r.get("resource_inequality") or {}).items()]
        ng = r["national_groups"]
        t["National groups"] = [{"dimension": d, "group": g, "rate_pct": v} for d in ("wealth", "area", "sex") for g, v in (ng.get(d, {}).get("rates") or {}).items()]
        t["National gaps"] = [{"dimension": d, "measure": k, "value": _flat(v)} for d in ("wealth", "area", "sex") for k, v in ng.get(d, {}).items() if k != "rates" and not isinstance(v, str)]
    return {k: v for k, v in t.items() if v}


# ------------------------------------------------------------------------------------------------ Excel
def run_to_xlsx(run) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Run"
    ws.append([TITLES.get(run.analysis_type, run.analysis_type)])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    for k, v in _meta(run):
        ws.append([k, v])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
    ws.append([])
    ws.append(["Software versions", json.dumps(run.software_versions, sort_keys=True)])
    ws.append(["Provenance", "Source register: config/source_register.json; data checksums are listed on the Data page of the portal."])
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 110
    for row in ws.iter_rows():
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    nar = wb.create_sheet("Narrative")
    for h, xs in _narrative(run):
        nar.append([h])
        nar.cell(nar.max_row, 1).font = Font(bold=True)
        for x in xs:
            nar.append([x])
            nar.cell(nar.max_row, 1).alignment = Alignment(wrap_text=True, vertical="top")
        nar.append([])
    nar.column_dimensions["A"].width = 140
    head_fill = PatternFill("solid", fgColor="DDE6F0")
    for name, rows in _tables(run).items():
        sh = wb.create_sheet(name[:31])
        cols = list(dict.fromkeys(k for row in rows for k in row))
        sh.append(cols)
        for c in sh[1]:
            c.font = Font(bold=True)
            c.fill = head_fill
        for row in rows:
            sh.append([_flat(row.get(k)) for k in cols])
        for i, col in enumerate(cols, 1):
            width = max(len(str(col)), *(len(str(_flat(r.get(col)) or "")) for r in rows[:50])) if rows else len(str(col))
            sh.column_dimensions[get_column_letter(i)].width = min(60, width + 2)
        sh.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------ PDF
def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("Small", parent=ss["BodyText"], fontSize=7.5, leading=9.5))
    ss.add(ParagraphStyle("Cell", parent=ss["BodyText"], fontSize=7.5, leading=9))
    ss.add(ParagraphStyle("Caveat", parent=ss["BodyText"], fontSize=9, leading=12, backColor=colors.HexColor("#FFF4D6"), borderPadding=5, spaceBefore=4, spaceAfter=6))
    return ss


def _esc(x) -> str:
    return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.3f}" if abs(v) < 1000 else f"{v:,.0f}"
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str)[:80]
    return "" if v is None else str(v)


def _table(rows: list[dict], ss, max_rows=40, cols=None):
    cols = cols or list(dict.fromkeys(k for row in rows for k in row))[:8]
    data = [[Paragraph(f"<b>{_esc(c)}</b>", ss["Cell"]) for c in cols]]
    for row in rows[:max_rows]:
        data.append([Paragraph(_esc(_fmt(row.get(c))), ss["Cell"]) for c in cols])
    t = Table(data, repeatRows=1, hAlign="LEFT")
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDE6F0")), ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3)]))
    return t


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.drawString(15 * mm, 9 * mm, getattr(doc, "footer_text", "Educational inequality in Nigeria"))
    canvas.drawRightString(195 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _build(story, footer: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=16 * mm, title="Educational inequality in Nigeria")
    doc.footer_text = footer
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buf.getvalue()


def run_to_pdf(run) -> bytes:
    ss = _styles()
    s = [Paragraph(_esc(TITLES.get(run.analysis_type, run.analysis_type)), ss["Title"]), Paragraph(f"Generated {date.today():%d %B %Y} from analysis run {run.public_id}", ss["Small"]), Spacer(1, 4)]
    mt = Table([[Paragraph(f"<b>{_esc(k)}</b>", ss["Cell"]), Paragraph(_esc(v), ss["Cell"])] for k, v in _meta(run)], colWidths=[45 * mm, 135 * mm])
    mt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    s += [mt, Spacer(1, 6)]
    for h, xs in _narrative(run):
        s.append(Paragraph(_esc(h), ss["Heading3"]))
        for x in xs:
            s.append(Paragraph(_esc(x), ss["Caveat"] if h in ("Verdict", "Status of these results", "Warnings") else ss["BodyText"]))
    for name, rows in _tables(run).items():
        s += [Paragraph(_esc(name), ss["Heading3"]), _table(rows, ss), Spacer(1, 4)]
        if len(rows) > 40:
            s.append(Paragraph(f"Showing 40 of {len(rows)} rows; the Excel export contains all rows.", ss["Small"]))
    s += [Paragraph("Data provenance and limitations", ss["Heading3"]),
          Paragraph("All inputs are published aggregate statistics registered in the source register with URL, access date, licence and limitations. "
                    "Datasets passed a data-readiness gate; rows failing integrity rules were excluded rather than repaired. State-level analyses use 31 or fewer observations, "
                    "so intervals are wide. Software versions: " + _esc(json.dumps(run.software_versions, sort_keys=True)), ss["Small"])]
    return _build(s, f"Run {run.public_id} | config {run.config_hash[:12]} | data {run.data_sha256[:12]}")


def summary_pdf() -> bytes:
    """One-page-style evidence summary built from the standard analyses and dataset readiness table."""
    ss = _styles()
    s = [Paragraph("Educational inequality in Nigeria: evidence summary", ss["Title"]), Paragraph(f"Generated {date.today():%d %B %Y}. Data fingerprint {S.data_fingerprint()[:16]}", ss["Small"]), Spacer(1, 6)]
    ineq, causal = S.latest_default("inequality"), S.latest_default("causal")
    if ineq:
        p = ineq.results["profile"]
        s += [Paragraph("Inequality (primary out-of-school rate, MICS6 2021)", ss["Heading3"]),
              Paragraph(f"Across {p['n_states']} states the population-weighted mean is {p['weighted_mean']:.1f}%, ranging from {p['min']['value']:.0f}% ({_esc(p['min']['state'])}) to "
                        f"{p['max']['value']:.0f}% ({_esc(p['max']['state'])}). Gini across states {p['gini']:.2f}; P90/P10 ratio {p['p90_p10_ratio']:.1f}.", ss["BodyText"])]
        rg = ineq.results.get("regional_gap")
        if rg:
            s.append(Paragraph("North-South gap: " + _esc(json.dumps(rg, default=str))[:300], ss["Small"]))
    if causal:
        ex = causal.results["explanation"]
        s += [Paragraph("Causal analysis", ss["Heading3"]), Paragraph(_esc(ex["verdict"]), ss["Caveat"])] + [Paragraph(_esc(x), ss["BodyText"]) for x in ex["summary"]]
    rows = [{"dataset": v.dataset.dataset_id, "version": v.version, "rows": v.n_rows, "readiness": v.readiness, "sha256": v.sha256[:16]}
            for v in m.DatasetVersion.objects.select_related("dataset").order_by("dataset__dataset_id", "-version")]
    if rows:
        s += [Paragraph("Dataset readiness", ss["Heading3"]), _table(rows, ss)]
    s.append(Paragraph(HYPOTHETICAL, ss["Small"]))
    return _build(s, "Educational inequality in Nigeria - evidence summary")


# ------------------------------------------------------------------------------------------------ DOCX: causal matrix report (9 combinations)
OUTCOME_GROUP = {"oos_total_2021": "all children", "oos_male_2021": "boys", "oos_female_2021": "girls"}
QUICK_CAUSAL = {"n_boot": 300, "n_refute": 30, "dml_repeats": 3}
CAUSAL_REPORT_COMBINATIONS = [
    ("oos_total_2021", ("pov_215", "north"), "All Children vs. Poverty + Region"),
    ("oos_total_2021", ("north",), "All Children vs. Region Only"),
    ("oos_total_2021", ("pov_215",), "All Children vs. Poverty Only"),
    ("oos_male_2021", ("pov_215", "north"), "Boys vs. Poverty + Region"),
    ("oos_male_2021", ("north",), "Boys vs. Region Only"),
    ("oos_male_2021", ("pov_215",), "Boys vs. Poverty Only"),
    ("oos_female_2021", ("pov_215", "north"), "Girls vs. Poverty + Region"),
    ("oos_female_2021", ("north",), "Girls vs. Region Only"),
    ("oos_female_2021", ("pov_215",), "Girls vs. Poverty Only"),
]


def _run_one(outcome: str, confounders: tuple) -> dict:
    from src.causal.engine import CausalConfig, run_causal_analysis
    cfg = CausalConfig(outcome=outcome, confounders=tuple(confounders), **QUICK_CAUSAL)
    return run_causal_analysis(S.get_analytic(), cfg)


def _n2(v) -> str:
    return "" if v is None else f"{v:+.2f}"


def _p_str(p) -> str:
    if p is None:
        return "not reported (bootstrap interval only)"
    s = f"p = {p:.3f}"
    return s + (" ; a value below 0.05 suggests the result is unlikely to be due to chance alone" if p < 0.05 else "")


def _ci_pair(lo, hi) -> str:
    return f"{lo:+.2f} to {hi:+.2f}"


def _docx_table(doc, headers: list[str], rows: list[list[str]], font_size=9):
    from docx.shared import Pt
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    for h, cell in zip(headers, t.rows[0].cells):
        cell.text = ""
        r = cell.paragraphs[0].add_run(h)
        r.bold = True
        r.font.size = Pt(font_size)
    for row in rows:
        cells = t.add_row().cells
        for v, cell in zip(row, cells):
            cell.text = str(v)
            for p in cell.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(font_size)
    doc.add_paragraph()


def _docx_bullets(doc, items: list[str], style="List Bullet"):
    for x in items:
        if x:
            doc.add_paragraph(x, style=style)


def _png_from_fig(fig_dict: dict, width: int = 900) -> bytes:
    import plotly.io as _pio
    for name in ("choreographer", "kaleido", "plotly"):
        logging.getLogger(name).setLevel(logging.WARNING)
    fig = _pio.from_json(json.dumps(fig_dict))
    fig.update_layout(width=width)
    return fig.to_image(format="png", scale=2)


def _docx_fig(doc, fig_dict: dict, caption: str, width: int = 900):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt
    doc.add_picture(io.BytesIO(_png_from_fig(fig_dict, width)), width=Cm(15.9))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    cap = doc.add_paragraph(caption)
    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for r_ in cap.runs:
        r_.font.size = Pt(9)
        r_.italic = True


def _shade(cell, hex_fill: str):
    from docx.oxml.ns import qn
    from docx.oxml.shared import OxmlElement
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_fill)
    cell._tc.get_or_add_tcPr().append(shd)


def _docx_box(doc, text: list[str], fill: str, bold_first=False):
    t = doc.add_table(rows=1, cols=1)
    t.style = "Table Grid"
    cell = t.rows[0].cells[0]
    _shade(cell, fill)
    cell.text = ""
    for i, line in enumerate(text):
        p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
        r = p.add_run(line)
        r.bold = bold_first and i == 0
    doc.add_paragraph()


def _docx_cover(doc):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor
    for _ in range(5):
        doc.add_paragraph()
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Educational Inequality in Nigeria")
    r.font.size = Pt(30)
    r.bold = True
    r.font.color.rgb = RGBColor(0x1F, 0x29, 0x37)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("Causal Analysis Report: Teacher Supply and Out-of-School Rates")
    r.font.size = Pt(16)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(date.today().strftime("%d %B %Y"))
    r.font.size = Pt(12)
    r.italic = True
    for _ in range(2):
        doc.add_paragraph()
    _docx_box(doc, [
        "What this document is, and what it is not",
        "This report re-runs the portal's causal analysis for every outcome and confounder combination offered on the "
        "'Run a custom analysis' form, and explains each in plain English. Treatment is the number of public pupils per "
        "qualified teacher (PQTR, 2016/17); outcomes are the primary out-of-school (OOS) rates from the 2021 UNICEF/MICS "
        "survey. The design is one cross-section of at most 37 states. Results are adjusted associations depending on "
        "stated assumptions - they are not proof of causation. Every section embeds the portal's six charts (both causal "
        "graphs, the forest plot, the specification curve and the two predictive-model charts) as numbered screenshots. "
        "See Section 2 (Reader's guide) before interpreting any number.",
    ], "FFF4D6", bold_first=True)
    doc.add_paragraph()
    _docx_box(doc, ["Contents"] + ["1. Reader's guide (methods, definitions, assumptions)"] + [
        f"{2 + i}. {_title}" for i, (_o, _c, _title) in enumerate(CAUSAL_REPORT_COMBINATIONS)
    ] + [f"{2 + len(CAUSAL_REPORT_COMBINATIONS)}. Glossary of technical terms",
         "Note: this outline is a fixed list (not a Word auto-TOC). Section numbering matches the headings in the body."],
          "E5E7EB")
    doc.add_page_break()


def _docx_intro(doc):
    from src.causal.engine import CONFOUNDERS, OUTCOME, TREATMENT, software_versions
    doc.add_heading("1. Reader's guide", level=1)

    doc.add_heading("1.1 The causal question", level=2)
    doc.add_paragraph(
        "Treatment (T): log of the pupil-per-qualified-teacher ratio (PQTR) in public primary schools, 2016/17. "
        "Log scale means effects are reported per proportional change (a 10% reduction in PQTR), not per pupil.")
    doc.add_paragraph("Outcome (Y): the out-of-school (OOS) rate in 2021 from the UNICEF MICS6 survey - the share of "
                      "primary-school-age children not attending school, as a percentage. Separate sections run this in turn "
                      "for all children, for boys, and for girls.")
    doc.add_paragraph("Estimand: the average effect on the OOS rate (in percentage points, pp) of a 10% proportional "
                      "reduction in PQTR, across the states in the analysis sample. A negative number means states with "
                      "fewer pupils per qualified teacher tend to have lower OOS rates (and vice versa).")
    conf_names = {"pov_215": "the state poverty headcount rate at $2.15/day (World Bank, 2018)", "north": "a binary indicator for the state being in the North (NC/NE/NW zones)"}
    doc.add_paragraph("Confounders (Z): adjustment sets of " + " or ".join(conf_names[c] for c in CONFOUNDERS) +
                      ". The best-justified set is poverty 2018 + region; the single-confounder sets are shown for "
                      "transparency about what each adjustment does, and are weaker (regions differ in much else besides poverty).")

    doc.add_heading("1.2 How to read the numbers", level=2)
    _docx_bullets(doc, [
        "Effect sizes are always percentage-point changes in the state OOS rate per 10% reduction in PQTR. Log-unit coefficients never appear in the prose.",
        "Every effect carries a 95% confidence interval: we are 95% confident the true effect lies between the two endpoints (approximate; see assumptions).",
        "p-values come with the reminder: a value below 0.05 suggests the result is unlikely to be due to chance alone.",
        "The 'Unadjusted' row is the raw association with no statistical control at all; it is shown only to expose confounding and is NOT a causal estimate.",
        "Each section embeds six screenshots of the portal's own charts, numbered Figure N.1 to N.6 for section N: both causal graphs (N.1, N.2), the forest plot (N.3), the specification curve (N.4) and the two predictive-model charts (N.5, N.6). Figures 5 and 6 are explicitly labelled as NOT causal evidence.",
        "Only the data itself decides the outcome; where every adjusted interval includes zero the honest reading is 'Inconclusive' - the data are consistent with effects of modest size and with no effect.",
    ])

    doc.add_heading("1.3 The three estimators", level=2)
    _docx_bullets(doc, [
        "Regression adjustment (OLS): ordinary regression of the OOS rate on log PQTR and the confounders, with HC3 robust standard errors. This is the primary estimate.",
        "GPS-weighted regression: weighting states by a generalised propensity score so confounders are balanced; a robustness check for the same effect.",
        "Double/debiased machine learning (DML): random-forest cross-fitting estimate; noisy with ~31 states, reported as a cross-check only.",
    ])

    doc.add_heading("1.4 How to read the causal graphs (DAGs)", level=2)
    doc.add_paragraph("A directed acyclic graph (DAG) is a diagram of assumed cause-and-effect directions: an arrow A -> B "
                      "means 'we assume A influences B'. Circles are variables; a dashed red arrow is a path through a "
                      "variable nobody measured (labelled U). In the portal's charts the treatment circle is amber, the "
                      "outcome circle is blue, measured confounder circles are grey, and the unmeasured 'U' circle is red.")
    doc.add_paragraph("Section 3 explains every element of both graphs for each combination - each section embeds "
                      "screenshots of them (Figure 3.1 and Figure 3.2 there): the identifying DAG used for "
                      "estimation, and the threat DAG that adds one unmeasured common cause U of treatment and outcome. "
                      "Under the threat DAG, adjusting for the observed confounders can no longer fully separate the effect "
                      "from confounding - the sensitivity (Cinelli-Hazlett) analysis quantifies how strong U would need to "
                      "be to overturn the conclusion, measured in partial R-squared terms.")

    doc.add_heading("1.5 Data provenance and honesty limits", level=2)
    _docx_bullets(doc, [
        "Inputs are published aggregate statistics (UNICEF/NBS Digest and MICS6, World Bank WDI) registered with URLs, licences and limitations; rows failing integrity checks were excluded rather than repaired.",
        "The analysis sample holds about 31 states; with n < 40, intervals are wide and estimates can change markedly when a single state is dropped (leave-one-out shown in every section).",
        "Software and data checksums: extracted from the engine at generation time; a full audit trail exists on the portal's run pages for the standard (full-fidelity) analyses.",
        f"Generated with: {', '.join(f'{k} {v}' for k, v in software_versions().items() if k in ('python', 'numpy', 'pandas', 'statsmodels', 'dowhy', 'econml')).replace('python python', 'Python')}.",
    ])
    doc.add_page_break()


def _docx_config_summary(doc, r: dict, outcome_label: str, conf_label: str):
    spec = r["specification"]
    _docx_table(doc, ["Item", "Value"], [
        ["Section", f"{outcome_label} - adjusted for {conf_label}"],
        ["Outcome variable (state-level, 2021)", spec["outcome"]],
        ["Treatment variable", spec["treatment"]],
        ["Confounders in the adjustment set", ", ".join(spec["confounders"])],
        ["States in the sample (n)", str(spec["n"])],
        ["Diagnostic detail / settings", f"Generalised results use {QUICK_CAUSAL['n_boot']} bootstrap resamples, {QUICK_CAUSAL['n_refute']} refutation simulations, {QUICK_CAUSAL['dml_repeats']} DML cross-fit repeats"],
    ])


def _outcome_plain(outcome: str) -> str:
    g = OUTCOME_GROUP[outcome]
    if g == "all children":
        return "the share of primary-school-age children (girls and boys) who are not in school"
    return f"the share of primary-school-age {g} who are not in school"


def _docx_dag_explanation(doc, graph_id: dict, graph_threat: dict, confounders: tuple, number: int):
    outcome = next(n for n in graph_id["nodes"] if n not in {a for a, _ in graph_id["edges"]})
    conf_names = {"pov_215": "Poverty", "north": "Region"}
    doc.add_heading("Assumed causal graph (identifying DAG) - elements", level=3)
    _docx_fig(doc, P.dag(graph_id),
              f"Figure {number}.1: Screenshot of the portal's identifying DAG for this combination. "
              f"Every circle and arrow is explained in the table beneath.", 760)
    node_rows = [
        ["log_pqtr (amber circle)", "Treatment", "Average number of pupils in a state's public primary schools per qualified teacher, 2016/17 (log scale). Higher = fewer qualified teachers relative to pupils."],
        [f"{outcome} (blue circle)", "Outcome", f"{_outcome_plain(outcome)[0].upper() + _outcome_plain(outcome)[1:]} (2021). This is what we want to change."],
    ]
    for c in ("pov_215", "north"):
        if c in confounders:
            node_rows.append([f"{c} (grey circle)", "Measured confounder", (
                "The share of the state population living on less than $2.15 per day (2018). Poorer states have more pupils per qualified teacher and higher OOS rates, so it must be held constant."
                if c == "pov_215" else
                "A flag for whether the state is in the North (1) or South (0). Northern states differ systematically in education infrastructure, poverty and OOS rates, so it must be held constant.")])
    _docx_table(doc, ["Element (in the chart)", "What it is", "Plain-English meaning"], node_rows)
    edge_rows = []
    for c in confounders:
        nm = conf_names[c]
        edge_rows.append([f"{c} -> log_pqtr", "Confounding path into treatment", f"{nm} pushes the pupil-per-teacher ratio (e.g. poorer or more northern states staff schools differently)."])
        edge_rows.append([f"{c} -> {outcome}", "Confounding path into outcome", f"{nm} also drives OOS rates directly (e.g. via household resources), independently of teacher supply."])
    if {"pov_215", "north"} <= set(confounders):
        edge_rows.append(["north -> pov_215", "Confounder-to-confounder path", "Northern states are on average poorer, so region partly causes poverty; poverty is therefore the deeper control variable."])
    edge_rows.append([f"log_pqtr -> {outcome}", "The arrow of interest", "After holding the confounders constant, this is the estimated effect of teacher supply on the OOS rate - the quantity the analysis estimates."])
    _docx_table(doc, ["Arrow", "What it represents", "Plain-English meaning"], edge_rows)

    doc.add_heading("Assumed causal graph with an unmeasured common cause (threat DAG) - extra elements", level=3)
    _docx_fig(doc, P.dag(graph_threat, True),
              f"Figure {number}.2: Screenshot of the portal's threat DAG. The red circle U is a stand-in for everything "
              f"unmeasured; its dashed red arrows are the paths the observed data cannot block.", 760)
    _docx_table(doc, ["Element (in the chart)", "What it is", "Plain-English meaning"], [
        ["U (red circle, dashed border)", "Unmeasured confounder", "A stand-in for everything unobserved that raises or lowers both teacher supply and OOS rates: state governance capacity, conflict and insecurity, cultural attitudes to schooling, school construction funding."],
        ["U --> log_pqtr (dashed red arrow)", "Unmeasured path into treatment", "Better-governed states also attract and retain more qualified teachers, they are not purely set by poverty and region."],
        [f"U --> {outcome} (dashed red arrow)", "Unmeasured path into outcome", "The same governance/attitude factors also move OOS rates on their own."],
        ["What changes vs. Graph 1", "Non-identifiability", "With U present, adjusting for the observed confounders is no longer sufficient to isolate the causal effect; the estimate can be biased up or down by an unknown amount. This is the honest limit of the study design."],
        ["What it means for the reader", "Interpret with care", "Graph 1 is the best-case assumption (conditional ignorability). The sensitivity analysis in this section quantifies in partial R-squared terms how strong U would have to be to overturn the conclusion."],
    ])


def _docx_estimates(doc, r: dict, number: int):
    doc.add_heading("Estimates of the effect", level=3)
    rows = []
    for e in r["estimates"]:
        p = "" if e["p_value"] is None else f"p = {e['p_value']:.3f}"
        tail = "no plausible-effect direction (interval includes zero)" if e["ci_includes_zero"] else ""
        rows.append([e["method"], f"{_n2(e['effect_10pct_reduction'])} pp", _ci_pair(e["effect_10pct_ci_low"], e["effect_10pct_ci_high"]), p, (e["notes"] or tail)[:140]])
    _docx_table(doc, ["Estimator", "Effect size (pp per 10% PQTR reduction)", "95% interval (pp)", "p-value", "Notes"], rows)
    doc.add_paragraph("Reminder: a p-value below 0.05 suggests the result is unlikely to be due to chance alone. All effect "
                      "sizes are percentage-point (pp) changes in the OOS rate per 10% reduction in PQTR.")
    _docx_fig(doc, P.forest(r["estimates"], "Estimated effect of a 10% reduction in pupils per qualified teacher"),
              f"Figure {number}.3: Screenshot of the portal's forest plot - rounded effect estimate and 95% interval for "
              f"each estimator in the table above, on a common percentage-point scale.", 900)


def _docx_sensitivity(doc, sens: dict):
    doc.add_heading("Sensitivity analysis (How wrong could this be?)", level=3)
    doc.add_paragraph(sens["interpretation"])
    rows = [[c, f"{v['partial_r2_with_outcome']:.1%}", f"{v['partial_r2_with_treatment']:.1%}"] for c, v in sens["benchmarks"].items()]
    _docx_table(doc, ["Benchmark confounder", "Partial R-squared with the outcome", "Partial R-squared with the treatment"], rows)
    doc.add_paragraph("How to read it: if an unmeasured factor were correlated with PQTR and the OOS rate at a partial "
                      "R-squared larger than the robustness value (RV) above, it could erase the point estimate. The observed "
                      "confounders themselves provide a scale on the benchmark table.")


def _docx_robustness(doc, r: dict, number: int):
    doc.add_heading("Robustness across specifications", level=3)
    _docx_fig(doc, P.spec_curve(r["robustness"]["specification_table"]),
              f"Figure {number}.4: Screenshot of the portal's specification curve - the effect of a 10% PQTR reduction for "
              f"every robustness row in the table beneath, sorted by estimate.", 900)
    rows = []
    for e in r["robustness"]["specification_table"]:
        p = "" if e["p_value"] is None else f"{e['p_value']:.3f}"
        rows.append([e["method"][:110], f"{_n2(e['effect_10pct_reduction'])} pp", _ci_pair(e["effect_10pct_ci_low"], e["effect_10pct_ci_high"]), p])
    _docx_table(doc, ["Specification", "Effect size (pp per 10% PQTR reduction)", "95% interval (pp)", "p-value"], rows)
    lt = r["robustness"]["linear_treatment"]
    fl = r["robustness"]["fractional_logit"]
    pb = r["robustness"]["pairs_bootstrap_baseline"]
    doc.add_paragraph(
        f"Alternative treatment scale: measured on the raw pupil count (not the log), each extra 10 pupils per qualified teacher is associated with "
        f"about {lt['coef_per_10_pupils']:+.2f} pp (95% interval from {lt['ci_low']:+.2f} to {lt['ci_high']:+.2f}), from the same specification family.")
    doc.add_paragraph(
        f"Bounded-outcome form: a fractional logit on the school-share scale gives an average effect of {fl['ame_10pct_reduction_pp']:+.2f} pp per 10% PQTR "
        f"reduction ({_p_str(fl['p_value'])}), reassuring that conclusions do not hinge on the linear-percentage-point model.")
    loo = r["robustness"]["leave_one_out"]
    doc.add_paragraph(
        f"Stability check: dropping each state once moves the estimated effect between {loo['min']:+.2f} pp (lowest when leaving {loo['state_at_min']} out) and "
        f"{loo['max']:+.2f} pp (highest when leaving {loo['state_at_max']} out). Sign changes across the leave-one-out estimates: "
        f"{'yes - the estimate can change sign depending on a single state' if loo['sign_changes'] else 'no'}.")
    doc.add_paragraph(
        f"Interval cross-checks: pairs bootstrap gives {_ci_pair(pb['ci_low'], pb['ci_high'])} pp ({pb['n_valid']} valid resamples); a (Freedman-Lane) permutation test "
        f"puts the chance-only p at {r['robustness']['permutation_p_value']:.3f}.")


def _docx_verdict(doc, r: dict):
    doc.add_heading("Verdict (in plain words)", level=3)
    verdict = r["explanation"]["verdict"]
    primary = next(e for e in r["estimates"] if e["kind"] == "primary")
    if primary["ci_includes_zero"]:
        fill, band = "FFF4D6", "AMBER (inconclusive): the data cannot separate 'no effect' from effects of modest size."
    else:
        direction = "more pupils per qualified teacher go together with higher OOS rates" if primary["effect_10pct_reduction"] < 0 else "a negative adjusted association appears against the expected direction"
        fill, band = "E2EFDA", f"GREEN CONDITIONAL: an adjusted association is present ({direction}), but its causal meaning depends entirely on assumption A1."
    doc.add_paragraph(f"Verdict band: {band}")
    _docx_box(doc, r["explanation"]["summary"], fill)
    if r["warnings"]:
        doc.add_paragraph("Caveats carried through from the engine:")
        _docx_bullets(doc, r["warnings"])
    return verdict


def _docx_section(doc, number: int, title: str, outcome_key: str, confounders: tuple, outcome_label: str, conf_label: str):
    doc.add_heading(f"{number}. {title}", level=1)
    r = _run_one(outcome_key, confounders)
    _docx_config_summary(doc, r, outcome_label, conf_label)

    doc.add_heading("Causal graphs", level=2)
    _docx_dag_explanation(doc, r["specification"]["graph_identifying"], r["specification"]["graph_threat"], tuple(confounders), number)

    doc.add_heading("Assumptions the conclusion depends on", level=2)
    _docx_bullets(doc, r["specification"]["assumptions"], style="List Bullet 2")

    doc.add_heading("Analysis results", level=2)
    _docx_estimates(doc, r, number)
    _docx_sensitivity(doc, r["sensitivity_unmeasured_confounding"])
    _docx_robustness(doc, r, number)
    doc.add_heading("Predictive-model charts (NOT causal evidence)", level=2)
    doc.add_paragraph(
        "These two charts appear on every portal run page and summarise the machine-learning predictive layer of the "
        "analysis, which is entirely separate from the causal estimate above. A feature that predicts the OOS rate well is "
        "not necessarily a cause of it: importance and prediction error describe association in the sample. They are included "
        "here for completeness, clearly labelled so they cannot be mistaken for causal results.")
    _docx_fig(doc, P.importance_bars(r["explainability"]["importance"]),
              f"Figure {number}.5: Screenshot of the portal's feature-importance chart - mean absolute SHAP value of each "
              f"feature in the predictive model. High importance is not a causal claim.", 780)
    _docx_fig(doc, P.prediction_bars(r["explainability"]["predictive_performance"]),
              f"Figure {number}.6: Screenshot of the portal's prediction-error chart - out-of-sample RMSE in pp per model. "
              f"Prediction accuracy says nothing about the causal direction of any relationship.", 900)
    _docx_verdict(doc, r)
    doc.add_page_break()


def _docx_glossary(doc):
    doc.add_heading("Glossary of technical terms", level=1)
    _docx_table(doc, ["Term", "Plain-English meaning"], [
        ["OOS / out-of-school rate", "Percentage of primary-school-age children not attending school (source: UNICEF MICS6 2021)."],
        ["PQTR", "Pupils per Qualified Teacher Ratio: average public primary pupils per teacher recognised as qualified (source: 2016/17 Digest)."],
        ["Treatment / T", "The variable whose effect we estimate: here log PQTR; moving it 10% down is the intervention being evaluated."],
        ["Outcome / Y", "The variable that responds to the treatment: the OOS rate, in percentage points."],
        ["Confounder", "A cause of both treatment and outcome; dropping it from the model leaves the effect estimate contaminated."],
        ["DAG (Directed Acyclic Graph)", "A diagram of assumed causal directions; arrows only point forward, so there is no feedback loop in the picture."],
        ["Backdoor path", "Any path from treatment to outcome that starts with an arrow into the treatment; confounder adjustment shuts it."],
        ["ATE / estimand", "Average Treatment Effect: the average change in the outcome per 10% PQTR reduction across states."],
        ["Conditional ignorability (A1)", "Assumes that once you compare states with the same poverty and region values, their teacher-supply differences are as good as random."],
        ["Positivity / overlap (A2)", "Every combination of confounder values shows a spread of PQTR values, so regression has something to compare."],
        ["Consistency / SUTVA (A3)", "People receive the treatment as defined and do not affect one another across state borders."],
        ["HC3 robust SE", "A robust sandwich standard error that tolerates heteroskedasticity; HC3 is the small-sample default variant."],
        ["GPS / generalised propensity score", "For a continuous treatment, the fitted T-given-confounders distribution used to reweight states."],
        ["Stabilised IP weights", "Multiplicative weights correcting confounding; truncated at the 5th/95th percentile to avoid extreme reweights."],
        ["ESS (Effective Sample Size)", "How many datapoints the weighted sample is effectively worth after reweighting."],
        ["DML (Double/debiased ML)", "Estimation that bypasses parametric assumptions by cross-fitting machine-learnt predictions of treatment and outcome."],
        ["Cross-fitting (5-fold)", "Splinter the sample into 5 folds and predict fold outcomes with models trained on the other folds."],
        ["Bootstrap percentile interval", "Recompute the estimate on 1000 resampled datasets; the interval is where the middle 95% land."],
        ["p-value", "How often a pure-random-data process would produce an estimate as extreme - below 0.05 flags a noteworthy result."],
        ["Partial R-squared", "Share of the residual variance variable X explains after other model components (used for the sensitivity analysis)."],
        ["Robustness value (RV)", "The minimum partial R-squared strength with BOTH treatment and outcome an unmeasured confounder needs to null the estimate."],
        ["Leave-one-out (LOO)", "Drop a state, re-estimate, repeat for every state - checks how fragile the estimate is to a single datapoint."],
        ["Fractional logit", "Binomial GLM for a bounded outcome like a percentage; expressed here through its average marginal effect."],
        ["Permutation test (Freedman-Lane)", "Shuffle the treatment residuals 5000 times to get a distribution of what randomness alone produces."],
        ["Sensitivity analysis (Cinelli & Hazlett)", "Benchmarks how strong an unmeasured confounder would need to be to overturn the finding."],
        ["Adjusted association", "The statistical relationship after controls; causal only when the identification assumptions (A1-A7) hold."],
    ])


def causal_matrix_report_docx(progress=None) -> bytes:
    """Run all 9 outcome x confounder combinations and return a single annotated DOCX (plan: analysis matrix report)."""
    from docx import Document

    def say(msg):
        if progress:
            progress(msg)

    import time
    doc = Document()
    _docx_cover(doc)
    _docx_intro(doc)
    for i, (out_key, conf_keys, title) in enumerate(CAUSAL_REPORT_COMBINATIONS):
        outcome_label = next(o for k, o in [("oos_total_2021", "Primary OOS rate, all children (primary outcome)"), ("oos_male_2021", "Primary OOS rate, boys"), ("oos_female_2021", "Primary OOS rate, girls")] if k == out_key)
        conf_label = "Poverty (2018) + region" if len(conf_keys) == 2 else ("Region only" if conf_keys[0] == "north" else "Poverty only")
        t0 = time.time()
        say(f"Running combination {i + 1}/9: {title} ...")
        _docx_section(doc, 2 + i, title, out_key, conf_keys, outcome_label, conf_label)
        say(f"  done in {time.time() - t0:.0f}s")
    _docx_glossary(doc)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
