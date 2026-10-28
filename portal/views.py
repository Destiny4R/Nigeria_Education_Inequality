"""Views.  Every page is public (no authentication by design)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.db import connection
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from src.common import INTERIM, PROCESSED, load_register, sha256_file
from src.inequality import metrics as M
from src.causal.engine import software_versions
from src.simulation.engine import DEFAULT_SCENARIOS, compare_scenarios

from . import exports, models as m, plotting as P, services as S
from .forms import CausalRunForm, InequalityFilterForm, ScenarioForm


def _states():
    return sorted(S.get_analytic().state.tolist())


def _charts(**kw):
    return kw


# ---------------------------------------------------------------------------------------------------- public pages
def home(request):
    a = S.get_analytic()
    q = S.get_quality()
    causal_run = S.latest_default("causal")
    ineq = S.latest_default("inequality")
    ctx = {"n_states": len(a), "n_sample": int(a.in_primary_sample.sum()), "causal_run": causal_run, "ineq_run": ineq,
           "n_sources": m.DataSource.objects.count(), "n_datasets": m.Dataset.objects.count(), "fingerprint": S.data_fingerprint()[:12]}
    if causal_run:
        ctx["causal_expl"] = causal_run.results["explanation"]
        ctx["primary"] = next(e for e in causal_run.results["estimates"] if e["kind"] == "primary")
    if ineq:
        ctx["profile"] = ineq.results["profile"]
        ctx["regional"] = ineq.results.get("regional_gap")
        ctx["wealth"] = ineq.results["national_groups"]["wealth"]
        ctx["area"] = ineq.results["national_groups"]["area"]
    return render(request, "portal/home.html", ctx)


def methodology(request):
    return render(request, "portal/methodology.html", {"indicators": m.IndicatorDefinition.objects.all(), "scenarios": DEFAULT_SCENARIOS})


def dashboard(request):
    ineq = S.latest_default("inequality")
    a = S.get_analytic()
    if not ineq:
        return render(request, "portal/empty.html", {"what": "standard inequality analysis"})
    r = ineq.results
    ind = r["indicator"]
    charts = {
        "map": P.point_map(a.to_dict("records"), "oos_total_2021", "Primary OOS rate 2021 (%)"),
        "bars": P.state_bars(r["ranking"], ind["label"], ind["unit"], ind["code"]),
        "national": P.national_groups(r["national_groups"]),
        "lorenz": P.lorenz(r["lorenz"], r["profile"]["gini"]),
        "trend_oos": P.trend_chart(r["trends"]["SE.PRM.UNER"]["series"], "Children out of school, primary (number, WDI)"),
        "trend_gpi": P.trend_chart(r["trends"]["SE.ENR.PRIM.FM.ZS"]["series"], "Gender parity index, primary gross enrolment (WDI)"),
        "trend_exp": P.trend_chart(r["trends"]["SE.XPD.TOTL.GD.ZS"]["series"], "Government education expenditure (% of GDP, WDI)"),
    }
    recent = m.AnalysisRun.objects.order_by("-created_at")[:6]
    changes = {k: v["change"] for k, v in r["trends"].items()}
    return render(request, "portal/dashboard.html", {"run": ineq, "r": r, "charts": charts, "recent": recent, "changes": changes})


def inequality(request):
    a = S.get_analytic()
    states = _states()
    form = InequalityFilterForm(request.GET or None, state_choices=states)
    run, r, error = None, None, None
    if request.GET and form.is_valid():
        if S.throttled(request, "inequality"):
            return render(request, "portal/throttled.html", status=429)
        try:
            run, _ = S.submit_run("inequality", form.config(), request=request, wait=True)
            if run.status == "succeeded":
                r = run.results
                S.audit(request, "inequality_viewed", run, config=run.config)
            else:
                error = run.error
        except ValueError as e:
            error = str(e)
    elif not request.GET:
        run = S.latest_default("inequality")
        r = run.results if run else None
    charts = {}
    if r:
        ind = r["indicator"]
        charts["bars"] = P.state_bars(r["ranking"], ind["label"], ind["unit"], ind["code"])
        if r.get("zone_summary"):
            charts["zones"] = P.zone_bars(r["zone_summary"], ind["label"], ind["unit"])
        if r.get("lorenz"):
            charts["lorenz"] = P.lorenz(r["lorenz"], r["profile"]["gini"])
        charts["scatter"] = P.poverty_scatter(r["scatter"], ind["code"], ind["label"])
        charts["national"] = P.national_groups(r["national_groups"])
        if r["gender_gap"]:
            charts["gender"] = P.gender_bars(r["gender_gap"])
    return render(request, "portal/inequality.html", {"form": form, "run": run, "r": r, "charts": charts, "error": error, "querystring": request.GET.urlencode()})


@require_GET
def inequality_export(request):
    form = InequalityFilterForm(request.GET, state_choices=_states())
    if not form.is_valid():
        return HttpResponse("Invalid filters", status=400)
    run, _ = S.submit_run("inequality", form.config(), request=request, wait=True)
    if run.status != "succeeded":
        return HttpResponse("Analysis failed", status=500)
    df = pd.DataFrame(run.results["ranking"])
    meta = (f"# Educational inequality in Nigeria - ranking export\n# indicator: {run.results['indicator']['label']}\n# run: {run.public_id}\n"
            f"# config_hash: {run.config_hash}\n# data_sha256: {run.data_sha256}\n# note: states with missing values are not ranked (see run page)\n")
    resp = HttpResponse(meta + df.to_csv(index=False), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="inequality_ranking_{str(run.public_id)[:8]}.csv"'
    S.audit(request, "inequality_exported", run)
    return resp


# ---------------------------------------------------------------------------------------------------- data management
def data_home(request):
    datasets = m.Dataset.objects.select_related("source").prefetch_related("versions").all()
    q = S.get_quality()
    rows = []
    for d in datasets:
        v = d.versions.first()
        rows.append({"d": d, "v": v})
    return render(request, "portal/data_home.html", {"sources": m.DataSource.objects.all(), "rows": rows, "jobs": m.ImportJob.objects.all()[:5], "fingerprint": S.data_fingerprint(),
                                                     "rules": q["rules"], "analytic": q["analytic"]})


def dataset_detail(request, dataset_id):
    d = get_object_or_404(m.Dataset.objects.select_related("source"), dataset_id=dataset_id)
    versions = d.versions.select_related("quality_report").all()
    return render(request, "portal/dataset_detail.html", {"d": d, "versions": versions, "v": versions.first(), "rules": S.get_quality()["rules"]})


DICTIONARY = [
    ("state", "Standardised state name (36 states + FCT)", "Grouping / adjustment", "config/states.csv; all sources"),
    ("state_code", "Two-letter state code (assigned by this project)", "Identifier", "config/states.csv"),
    ("zone", "Geopolitical zone: NC, NE, NW, SE, SS, SW", "Grouping", "config/states.csv"),
    ("region", "North (NC, NE, NW) or South (SE, SS, SW)", "Confounder / subgroup", "derived"),
    ("oos_total_2021, oos_male_2021, oos_female_2021", "Primary out-of-school rate, % of primary-age children (MICS6 2021)", "PRIMARY OUTCOME and sex components", "UNICEF-MICS6-2021"),
    ("pqtr", "Public pupils / qualified public teachers, 2016/17 (computed from counts)", "TREATMENT (log used in models)", "FME-DIGEST-2017"),
    ("ptr", "Public pupils / all public teachers, 2016/17", "Alternative treatment", "FME-DIGEST-2017"),
    ("pct_qualified_calc", "Qualified teachers as % of all public teachers", "Descriptive / predictive feature", "FME-DIGEST-2017"),
    ("pov_215", "Poverty headcount at $2.15/day, 2018, %", "CONFOUNDER / subgroup variable", "WB-GPP-2018"),
    ("pop6_11_2015", "Projected population aged 6-11 (2015/16)", "Weight", "FME-OOS-2015"),
    ("etpr_2015", "Enrolment-to-population ratio, age 6-11, 2015/16 (%)", "Baseline access (lagged covariate)", "FME-OOS-2015"),
    ("private_share_enrol", "Private schools' share of primary enrolment, %", "Descriptive (not adjusted for: possible mediator)", "FME-DIGEST-2017"),
    ("female_share_total", "Girls' share of primary enrolment, %", "Gender inequality (counts)", "FME-DIGEST-2017"),
    ("completion_m / completion_f, ger_m / ger_f", "Primary completion and gross enrolment ratios by sex (as printed; several implausible >100%)", "Descriptive only; flagged", "FME-DIGEST-2017"),
    ("in_primary_sample", "True when treatment, outcome and confounder are all valid", "Inclusion criterion", "derived"),
    ("flags / n_critical_flags", "Integrity flags raised by the cleaning rules", "Quality", "derived"),
    ("oos_primary / oos_lower_secondary / oos_upper_secondary", "National out-of-school rates by sex, area and wealth quintile (MICS6 2021, Table 3)", "National inequality by wealth / rural-urban / sex", "UNICEF-MICS6-2021"),
    ("rural_urban (state level)", "NOT available at state level: the extraction could not be verified (see data quality report)", "Rejected", "UNICEF-MICS6-2021"),
    ("household_wealth (household level)", "NOT available: no household microdata were accessible; wealth quintile rates exist only at national level", "Not available", "-"),
]


def dictionary(request):
    a = S.get_analytic()
    cols = [{"name": c, "dtype": str(a[c].dtype), "n_valid": int(a[c].notna().sum())} for c in a.columns]
    return render(request, "portal/dictionary.html", {"dictionary": DICTIONARY, "columns": cols, "indicators": m.IndicatorDefinition.objects.all()})


@require_GET
def data_download(request, name):
    """Download a cleaned dataset (CSV).  Only whitelisted names are served (no path traversal)."""
    if name == "state_analytic":
        df = S.get_analytic()
    elif name == "national_groups":
        df = S.get_groups()
    elif name == "national_series":
        df = S.get_series()
    elif m.Dataset.objects.filter(dataset_id=name).exists() and (INTERIM / f"{name}_clean.parquet").exists():
        df = pd.read_parquet(INTERIM / f"{name}_clean.parquet")
    else:
        raise Http404
    resp = HttpResponse(df.to_csv(index=False), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{name}.csv"'
    S.audit(request, "data_downloaded", None, name=name)
    return resp


# ---------------------------------------------------------------------------------------------------- causal analysis
def causal(request):
    form = CausalRunForm(request.POST or None)
    if request.method == "POST":
        if S.throttled(request, "causal"):
            return render(request, "portal/throttled.html", status=429)
        if form.is_valid():
            try:
                run, created = S.submit_run("causal", form.config(), label="Custom causal analysis", request=request)
            except ValueError as e:
                form.add_error(None, str(e))
            else:
                return redirect("run_detail", public_id=run.public_id)
    run = S.latest_default("causal")
    return render(request, "portal/causal.html", {"form": form, "run": run, "r": run.results if run else None, "charts": _causal_charts(run.results) if run else {},
                                                  "other_runs": m.AnalysisRun.objects.filter(analysis_type="causal").order_by("-created_at")[:8]})


def _causal_charts(r):
    return {"forest": P.forest(r["estimates"], "Estimated effect of a 10% reduction in pupils per qualified teacher"),
            "spec": P.spec_curve(r["robustness"]["specification_table"]), "dag": P.dag(r["specification"]["graph_identifying"]),
            "dag_threat": P.dag(r["specification"]["graph_threat"], True), "shap": P.importance_bars(r["explainability"]["importance"]),
            "pred": P.prediction_bars(r["explainability"]["predictive_performance"])}


# ---------------------------------------------------------------------------------------------------- simulation
def simulate(request):
    states = sorted(S.get_analytic().loc[S.get_analytic().in_primary_sample, "state"])
    form = ScenarioForm(request.POST or None, state_choices=states)
    if request.method == "POST":
        if S.throttled(request, "simulate"):
            return render(request, "portal/throttled.html", status=429)
        if m.PolicyScenario.objects.count() >= settings.MAX_SAVED_SCENARIOS:
            form.add_error(None, "The saved-scenario limit has been reached; please contact the site operator.")
        elif form.is_valid():
            try:
                run, _ = S.submit_run("simulation", form.config(), label=form.cleaned_data["name"], request=request, wait=True)
            except ValueError as e:
                form.add_error(None, str(e))
            else:
                if run.status == "succeeded":
                    return redirect("run_detail", public_id=run.public_id)
                form.add_error(None, "The simulation failed: " + (run.error.splitlines()[0] if run.error else "unknown error"))
    presets = m.PolicyScenario.objects.filter(is_preset=True)
    saved = m.SimulationRun.objects.select_related("scenario", "run").filter(run__status="succeeded").order_by("-created_at")[:25]
    return render(request, "portal/simulate.html", {"form": form, "presets": presets, "saved": saved})


def simulate_compare(request):
    ids = request.GET.getlist("id")[:4]
    runs = []
    for i in ids:
        try:
            r = m.AnalysisRun.objects.get(public_id=i, analysis_type="simulation", status="succeeded")
            runs.append(r)
        except (m.AnalysisRun.DoesNotExist, ValueError, Exception):
            continue
    if len(runs) < 2:
        presets = m.AnalysisRun.objects.filter(analysis_type="simulation", status="succeeded", simulation__scenario__is_preset=True).order_by("created_at")
        runs = list(presets)
    table = compare_scenarios([r.results for r in runs]) if runs else pd.DataFrame()
    return render(request, "portal/sim_compare.html", {"runs": runs, "table": table.to_dict("records"), "chart": P.sim_compare(table.to_dict("records")) if len(table) else None,
                                                       "candidates": m.AnalysisRun.objects.filter(analysis_type="simulation", status="succeeded").order_by("-created_at")[:30]})


# ---------------------------------------------------------------------------------------------------- run pages
def _run_or_404(public_id):
    S.reap_stale_runs()
    return get_object_or_404(m.AnalysisRun, public_id=public_id)


def run_detail(request, public_id):
    run = _run_or_404(public_id)
    ctx = {"run": run, "r": run.results, "charts": {}, "can_retry": run.status == "failed" and run.retries < settings.ANALYSIS_MAX_RETRIES}
    if run.status == "succeeded":
        r = run.results
        if run.analysis_type == "causal":
            ctx["charts"] = _causal_charts(r)
        elif run.analysis_type == "simulation":
            ctx["charts"] = {"headline": P.sim_headline(r), "states": P.sim_states(r)}
        elif run.analysis_type == "inequality":
            ind = r["indicator"]
            ctx["charts"] = {"bars": P.state_bars(r["ranking"], ind["label"], ind["unit"], ind["code"]), "national": P.national_groups(r["national_groups"])}
    S.audit(request, "run_viewed", run)
    return render(request, "portal/run_detail.html", ctx)


@require_GET
def run_status(request, public_id):
    run = _run_or_404(public_id)
    return JsonResponse({"status": run.status, "progress": run.progress, "error": run.error[:300], "retries": run.retries})


@require_POST
def run_retry(request, public_id):
    run = _run_or_404(public_id)
    S.retry_run(run, request)
    return redirect("run_detail", public_id=run.public_id)


@require_GET
def run_export(request, public_id, fmt):
    run = _run_or_404(public_id)
    if run.status != "succeeded":
        raise Http404("Only successful runs can be exported")
    if fmt == "xlsx":
        data, ctype = exports.run_to_xlsx(run), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif fmt == "pdf":
        data, ctype = exports.run_to_pdf(run), "application/pdf"
    elif fmt == "json":
        data, ctype = json.dumps({"run": str(run.public_id), "type": run.analysis_type, "config": run.config, "config_hash": run.config_hash, "data_sha256": run.data_sha256,
                                  "results_sha256": run.results_sha256, "software_versions": run.software_versions, "results": run.results}, indent=1).encode(), "application/json"
    else:
        raise Http404
    S.audit(request, "run_exported", run, format=fmt)
    resp = HttpResponse(data, content_type=ctype)
    resp["Content-Disposition"] = f'attachment; filename="{run.analysis_type}_{str(run.public_id)[:8]}.{fmt}"'
    return resp


# ---------------------------------------------------------------------------------------------------- reports, audit, status
def reports(request):
    S.reap_stale_runs()
    runs = m.AnalysisRun.objects.all()[:60]
    docs = []
    for name, label in [("research_report.pdf", "Research report (PDF)"), ("research_report.docx", "Research report (Word)"), ("requirements_traceability.pdf", "Requirements cross-check (PDF)")]:
        if (settings.REPORT_DIR / name).exists():
            docs.append({"name": name, "label": label, "size_kb": (settings.REPORT_DIR / name).stat().st_size // 1024})
    return render(request, "portal/reports.html", {"runs": runs, "docs": docs})


@require_GET
def summary_pdf(request):
    data = exports.summary_pdf()
    S.audit(request, "summary_exported", None)
    resp = HttpResponse(data, content_type="application/pdf")
    resp["Content-Disposition"] = 'attachment; filename="evidence_summary.pdf"'
    return resp


@require_GET
def report_document(request, name):
    if not re.fullmatch(r"[A-Za-z0-9_\-]+\.(pdf|docx)", name):
        raise Http404
    p = settings.REPORT_DIR / name
    if not p.exists():
        raise Http404
    return FileResponse(open(p, "rb"), as_attachment=True, filename=name)


def activity(request):
    return render(request, "portal/activity.html", {"logs": m.AuditLog.objects.all()[:200], "n": m.AuditLog.objects.count()})


def status_page(request):
    S.reap_stale_runs()
    q = S.get_quality()
    counts = {t: m.AnalysisRun.objects.filter(status=t).count() for t in ("queued", "running", "succeeded", "failed")}
    return render(request, "portal/status.html", {"versions": software_versions(), "db_vendor": connection.vendor, "db_engine": settings.DATABASES["default"]["ENGINE"], "execution": settings.ANALYSIS_EXECUTION,
                                                  "timeout": settings.ANALYSIS_TIMEOUT_SECONDS, "fingerprint": S.data_fingerprint(), "counts": counts, "analytic_sha": q["analytic_sha256"],
                                                  "debug": settings.DEBUG, "https": settings.BEHIND_HTTPS, "jobs": m.ImportJob.objects.all()[:5]})


def healthz(request):
    try:
        m.DataSource.objects.exists()
        ok = True
    except Exception:
        ok = False
    return JsonResponse({"status": "ok" if ok else "database_unavailable"}, status=200 if ok else 503)


def not_found(request, exception=None):
    return render(request, "portal/404.html", status=404)


def server_error(request):
    return render(request, "portal/500.html", status=500)
