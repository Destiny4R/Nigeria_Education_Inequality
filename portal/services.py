"""Application services: data registry sync, analysis-run lifecycle, auditing and throttling."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import traceback
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from src.common import PROCESSED, ROOT, load_register, sha256_file, sha256_text, stable_json, to_jsonable
from src.inequality import metrics as M
from src.inequality.analysis import run_inequality_analysis, default_config as ineq_default
from src.causal.engine import CausalConfig, run_causal_analysis, software_versions
from src.simulation.engine import Scenario, run_simulation, DEFAULT_SCENARIOS

from . import models as m

log = logging.getLogger(__name__)

ANALYTIC = PROCESSED / "state_analytic.parquet"
GROUPS = PROCESSED / "national_groups.parquet"
SERIES = PROCESSED / "national_series.parquet"
QUALITY = PROCESSED / "quality_report.json"

CAUSAL_ALLOWED = {
    "outcome": {"oos_total_2021", "oos_male_2021", "oos_female_2021"},
    "confounders": {("pov_215", "north"), ("north",), ("pov_215",)},
}


# ----------------------------------------------------------------------------------------------------
# Data access
# ----------------------------------------------------------------------------------------------------
def _mtime(p: Path) -> float:
    return p.stat().st_mtime


@lru_cache(maxsize=8)
def _read(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(path)


def get_analytic() -> pd.DataFrame:
    return _read(str(ANALYTIC), _mtime(ANALYTIC)).copy()


def get_groups() -> pd.DataFrame:
    return _read(str(GROUPS), _mtime(GROUPS)).copy()


def get_series() -> pd.DataFrame:
    return _read(str(SERIES), _mtime(SERIES)).copy()


def get_quality() -> dict:
    return json.loads(QUALITY.read_text())


def data_fingerprint() -> str:
    """One checksum for everything the analyses read: any change in the processed data changes it."""
    h = hashlib.sha256()
    for p in (ANALYTIC, GROUPS, SERIES):
        h.update(sha256_file(p).encode())
    return h.hexdigest()


def config_hash(analysis_type: str, config: dict) -> str:
    return sha256_text(stable_json({"type": analysis_type, "config": config}))


# ----------------------------------------------------------------------------------------------------
# Audit and throttling
# ----------------------------------------------------------------------------------------------------
def client_hash(request) -> str:
    addr = request.META.get("REMOTE_ADDR", "")
    if getattr(settings, "TRUST_PROXY_HEADERS", False):
        addr = request.META.get("HTTP_X_REAL_IP", addr)
    return hashlib.sha256((settings.IP_HASH_SALT + addr).encode()).hexdigest()[:16]


def audit(request, action: str, obj=None, **details):
    try:
        m.AuditLog.objects.create(action=action, object_type=obj.__class__.__name__ if obj is not None else "",
                                  object_id=str(getattr(obj, "public_id", getattr(obj, "pk", ""))) if obj is not None else "",
                                  details=to_jsonable(details), client_hash=client_hash(request) if request is not None else "system")
    except Exception:  # auditing must never break a request
        log.exception("audit logging failed")


def throttled(request, key: str = "runs") -> bool:
    """True when this client exceeded the hourly allowance for expensive operations."""
    k = f"throttle:{key}:{client_hash(request)}:{timezone.now():%Y%m%d%H}"
    n = cache.get(k, 0) + 1
    cache.set(k, n, 3700)
    return n > settings.THROTTLE_RUNS_PER_HOUR


# ----------------------------------------------------------------------------------------------------
# Registry synchronisation (ImportJob)
# ----------------------------------------------------------------------------------------------------
def import_all_datasets() -> m.ImportJob:
    """Run the cleaning pipeline and record sources, datasets, versions, quality reports and indicator definitions."""
    from src.cleaning.pipeline import run_cleaning
    job = m.ImportJob.objects.create()
    try:
        analytic, national, reports, info = run_cleaning(write=True)
        reg = load_register()
        created_versions = 0
        with transaction.atomic():
            for s in reg["sources"]:
                m.DataSource.objects.update_or_create(source_id=s["source_id"], defaults=dict(
                    name=s["name"], publisher=s.get("publisher", ""), url=s["url"], publication_year=s.get("publication_year"),
                    collection_period=s.get("collection_period", ""), access_date=s["access_date"], geographic_coverage=s.get("geographic_coverage", ""),
                    licence=s["licence"], documentation=s.get("documentation", ""), limitations=s["limitations"], permitted_uses=s["permitted_uses"],
                    retrieval_method=s.get("retrieval_method", "")))
            for d in reg["datasets"]:
                src = m.DataSource.objects.get(source_id=d["source_id"])
                rep = reports.get(d["dataset_id"])
                role = rep.readiness.get("role", "") if rep else ""
                ds, _ = m.Dataset.objects.update_or_create(dataset_id=d["dataset_id"], defaults=dict(
                    name=d["name"], source=src, unit_of_analysis=d.get("unit_of_analysis", ""), role=role, raw_file=d["file"]))
                if rep is None:
                    continue
                if not m.DatasetVersion.objects.filter(dataset=ds, sha256=rep.sha256).exists():
                    nxt = (ds.versions.order_by("-version").values_list("version", flat=True).first() or 0) + 1
                    ver = m.DatasetVersion.objects.create(dataset=ds, version=nxt, sha256=rep.sha256, n_rows=rep.rows_in,
                                                          size_bytes=Path(ROOT / "data" / "raw" / d["file"]).stat().st_size, readiness=rep.readiness["status"])
                    m.DataQualityReport.objects.create(version=ver, readiness_reasons=to_jsonable(rep.readiness.get("reasons", [])),
                                                       readiness_detail=to_jsonable(rep.readiness), checks=to_jsonable(rep.checks),
                                                       transformations=to_jsonable(rep.transformations), missingness=to_jsonable(rep.missingness),
                                                       rejected_columns=to_jsonable(rep.rejected_columns), flags=to_jsonable(rep.flags))
                    created_versions += 1
            for code, meta in M.INDICATORS.items():
                m.IndicatorDefinition.objects.update_or_create(code=code, defaults=dict(
                    label=meta["label"], unit=meta["unit"], direction=meta["direction"], denominator=meta["denominator"], weighting=meta["weighting"],
                    missing_rule=meta["missing_rule"], source_id=meta["source"], comparable=meta["comparable"], interpretation=meta["interpretation"]))
        job.status = "succeeded"
        job.summary = {"datasets": len(reg["datasets"]), "new_versions": created_versions, "analytic_rows": int(len(analytic)),
                       "primary_sample": int(info["n_primary_sample"]), "data_fingerprint": data_fingerprint()}
    except Exception as e:
        job.status = "failed"
        job.error = f"{type(e).__name__}: {e}"
        log.exception("import failed")
    job.finished_at = timezone.now()
    job.save()
    return job


# ----------------------------------------------------------------------------------------------------
# Analysis runs
# ----------------------------------------------------------------------------------------------------
def normalise_config(analysis_type: str, config: dict) -> dict:
    """Whitelist and canonicalise user input so that identical requests produce identical hashes."""
    if analysis_type == "inequality":
        c = {**ineq_default(), **{k: v for k, v in config.items() if k in ineq_default()}}
        c["states"] = sorted(c.get("states") or [])
        return c
    if analysis_type == "causal":
        base = CausalConfig().to_dict()
        c = {k: config[k] for k in ("outcome", "confounders", "n_boot", "n_refute", "dml_repeats") if k in config}
        out = {**base, **c}
        out["confounders"] = list(out["confounders"])
        out["treatment"] = "log_pqtr"
        out["seed"] = base["seed"]
        out["run_dowhy"] = True
        out["run_dml"] = True
        return out
    if analysis_type == "simulation":
        allowed = Scenario.__dataclass_fields__.keys()
        c = {k: v for k, v in config.items() if k in allowed}
        sc = Scenario(**c)
        d = sc.to_dict()
        if d["coverage"] == "states" and d["coverage_value"]:
            d["coverage_value"] = sorted(d["coverage_value"])
        return d
    raise ValueError("Unknown analysis type")


def validate_causal_config(c: dict) -> list[str]:
    p = []
    if c["outcome"] not in CAUSAL_ALLOWED["outcome"]:
        p.append("Outcome not allowed")
    if tuple(c["confounders"]) not in CAUSAL_ALLOWED["confounders"]:
        p.append("Confounder set not allowed (choose a documented adjustment set)")
    if not (100 <= int(c["n_boot"]) <= 2000) or not (10 <= int(c["n_refute"]) <= 200) or not (1 <= int(c["dml_repeats"]) <= 20):
        p.append("Bootstrap/refutation/DML repetition counts out of range")
    return p


def submit_run(analysis_type: str, config: dict, *, label: str = "", force: bool = False, is_default: bool = False, request=None, wait: bool = False) -> tuple[m.AnalysisRun, bool]:
    """Create (or reuse) an analysis run.  Duplicate-submission protection: an identical configuration on identical data that is
    queued, running or already succeeded is returned instead of re-computed (unless ``force``)."""
    cfg = normalise_config(analysis_type, config)
    if analysis_type == "causal":
        problems = validate_causal_config(cfg)
        if problems:
            raise ValueError("; ".join(problems))
    h = config_hash(analysis_type, cfg)
    fp = data_fingerprint()
    with transaction.atomic():
        if not force:
            existing = (m.AnalysisRun.objects.select_for_update().filter(analysis_type=analysis_type, config_hash=h, data_sha256=fp,
                                                                         status__in=["queued", "running", "succeeded"]).order_by("-created_at").first())
            if existing:
                if is_default and not existing.is_default and existing.status == "succeeded":
                    m.AnalysisRun.objects.filter(analysis_type=analysis_type, is_default=True).update(is_default=False)
                    existing.is_default = True
                    existing.save(update_fields=["is_default"])
                return existing, False
        run = m.AnalysisRun.objects.create(analysis_type=analysis_type, config=cfg, config_hash=h, data_sha256=fp, label=label, is_default=False,
                                           software_versions=software_versions())
    audit(request, f"{analysis_type}_submitted", run, label=label)
    _dispatch(run.pk, is_default, wait)
    run.refresh_from_db()
    return run, True


def _dispatch(run_id: int, is_default: bool = False, wait: bool = False):
    if settings.ANALYSIS_EXECUTION == "thread" and not wait:
        threading.Thread(target=execute_run, args=(run_id, is_default), daemon=True, name=f"run-{run_id}").start()
    else:
        execute_run(run_id, is_default)


def _compute(analysis_type: str, config: dict) -> dict:
    analytic = get_analytic()
    if analysis_type == "inequality":
        return run_inequality_analysis(analytic, get_groups(), get_series(), config)
    if analysis_type == "causal":
        return to_jsonable(run_causal_analysis(analytic, CausalConfig(**{**config, "confounders": tuple(config["confounders"])})))
    if analysis_type == "simulation":
        return to_jsonable(run_simulation(analytic, Scenario(**config)))
    raise ValueError(analysis_type)


def execute_run(run_id: int, is_default: bool = False):
    """Worker entry point.  Results are written in ONE transaction together with ``status='succeeded'``; any failure leaves the run
    ``failed`` with no results (enforced by a database check constraint)."""
    with transaction.atomic():
        run = m.AnalysisRun.objects.select_for_update().get(pk=run_id)
        if run.status != "queued":
            return
        run.status, run.started_at, run.progress = "running", timezone.now(), "computing"
        run.save(update_fields=["status", "started_at", "progress"])
    try:
        result = _compute(run.analysis_type, run.config)
        art_dir = Path(settings.ARTEFACT_DIR)
        art_dir.mkdir(parents=True, exist_ok=True)
        art = art_dir / f"{run.analysis_type}_{run.public_id}.json"
        payload = json.dumps(result, sort_keys=True, separators=(",", ":"))
        art.write_text(payload)
        with transaction.atomic():
            run = m.AnalysisRun.objects.select_for_update().get(pk=run_id)
            if run.status != "running":      # reaped (timed out) while computing: do not resurrect it
                log.warning("run %s no longer running; discarding result", run.public_id)
                art.unlink(missing_ok=True)
                return
            if is_default:
                m.AnalysisRun.objects.filter(analysis_type=run.analysis_type, is_default=True).update(is_default=False)
            run.results = result
            run.results_sha256 = result.get("results_sha256", sha256_text(payload))
            run.artefact_path = str(art.relative_to(settings.BASE_DIR)) if str(art).startswith(str(settings.BASE_DIR)) else str(art)
            run.status, run.finished_at, run.progress, run.error, run.is_default = "succeeded", timezone.now(), "done", "", is_default or run.is_default
            run.save()
            _persist_derived(run, result, art, payload)
    except Exception as e:
        log.exception("run %s failed", run_id)
        with transaction.atomic():
            run = m.AnalysisRun.objects.select_for_update().get(pk=run_id)
            if run.status in ("running", "queued"):
                run.status, run.results, run.results_sha256, run.finished_at = "failed", None, "", timezone.now()
                run.error = f"{type(e).__name__}: {e}"[:2000] + "\n" + "".join(traceback.format_exc().splitlines(True)[-3:])[:1500]
                run.progress = "failed"
                run.save()


def _persist_derived(run: m.AnalysisRun, result: dict, art: Path, payload: str):
    if run.analysis_type == "inequality":
        rows = []
        prof = result.get("profile") or {}
        ind = result["indicator"]["code"]
        for k in ("gini", "theil_t", "cv", "range", "max_min_ratio", "p90_p10_ratio", "weighted_mean"):
            if prof.get(k) is not None:
                rows.append(m.InequalityResult(run=run, indicator=ind, group_type="states", group="selected", metric=k, value=prof[k], n=prof.get("n_states")))
        rg = result.get("regional_gap")
        if rg:
            rows.append(m.InequalityResult(run=run, indicator=ind, group_type="region", group="North-South", metric="absolute_gap", value=rg["gap"], ci_low=rg["ci_low"], ci_high=rg["ci_high"], n=rg["n_high"] + rg["n_low"]))
        ng = result["national_groups"]
        for gt in ("wealth", "area", "sex"):
            for gname, val in ng[gt]["rates"].items():
                rows.append(m.InequalityResult(run=run, indicator="national_" + result["config"]["level"], group_type=gt, group=gname, metric="rate", value=val))
        m.InequalityResult.objects.bulk_create(rows)
    elif run.analysis_type == "causal":
        spec = result["specification"]
        cm = m.CausalModel.objects.create(run=run, name=f"PQTR -> {spec['outcome']}", treatment=spec["treatment"], outcome=spec["outcome"], confounders=spec["confounders"],
                                          estimand=spec["estimand"], graph=spec["graph_identifying"], assumptions=spec["assumptions"], identification=result.get("identification", {}))
        mv = m.ModelVersion.objects.create(causal_model=cm, version=result["results_sha256"][:12], software_versions=result["software_versions"],
                                           artefact_path=str(art), artefact_sha256=hashlib.sha256(payload.encode()).hexdigest())
        refs = result.get("identification", {}).get("refutations", [])
        m.ValidationRun.objects.create(model_version=mv, kind="refutation", summary={"tests": refs}, passed=all((r.get("p_value") or 0) > 0.05 for r in refs) if refs else None)
        m.ValidationRun.objects.create(model_version=mv, kind="sensitivity", summary=result["sensitivity_unmeasured_confounding"], passed=None)
        m.ValidationRun.objects.create(model_version=mv, kind="robustness", summary={k: result["robustness"][k] for k in ("leave_one_out", "pairs_bootstrap_baseline", "permutation_p_value")}, passed=None)
        m.ValidationRun.objects.create(model_version=mv, kind="predictive", summary={"performance": result["explainability"]["predictive_performance"]}, passed=None)
        m.ValidationRun.objects.create(model_version=mv, kind="overlap", summary=result["overlap_balance"], passed=bool(result["overlap_balance"]["gps"]["balance_achieved"]))
    elif run.analysis_type == "simulation":
        cfgh = run.config_hash
        sc = result["scenario"]
        scenario, _ = m.PolicyScenario.objects.get_or_create(config_hash=sha256_text(stable_json(sc)), defaults=dict(
            name=sc["name"][:120], description=sc.get("description", "")[:500], config=sc, is_preset=sc["name"] in {x["name"] for x in DEFAULT_SCENARIOS}))
        sim = m.SimulationRun.objects.create(scenario=scenario, run=run)
        h = result["headline"]
        rows = [m.SimulationResult(simulation=sim, group_type="national", group="Nigeria (sampled states)", baseline=h["baseline_national_oos"],
                                   counterfactual=h["counterfactual_national_oos"], change_pp=h["absolute_change_pp"], ci_low=h["statistical_interval_pp"][0], ci_high=h["statistical_interval_pp"][1])]
        for s in result["subgroups"]:
            rows.append(m.SimulationResult(simulation=sim, group_type="subgroup", group=s["group"], baseline=s["baseline"], counterfactual=s["counterfactual"], change_pp=s["change_pp"]))
        for s in result["states"]:
            rows.append(m.SimulationResult(simulation=sim, group_type="state", group=s["state"], baseline=s["oos_base"], counterfactual=s["oos_cf"], change_pp=s["change_pp"]))
        m.SimulationResult.objects.bulk_create(rows)


def reap_stale_runs() -> int:
    """Mark runs that have been 'running' longer than the timeout as failed (a crashed or hung worker)."""
    cutoff = timezone.now() - timedelta(seconds=settings.ANALYSIS_TIMEOUT_SECONDS)
    qs = m.AnalysisRun.objects.filter(status__in=["running", "queued"], created_at__lt=cutoff)
    n = 0
    for run in qs:
        with transaction.atomic():
            r = m.AnalysisRun.objects.select_for_update().get(pk=run.pk)
            if r.status in ("running", "queued"):
                r.status, r.results, r.results_sha256, r.finished_at, r.progress = "failed", None, "", timezone.now(), "timed out"
                r.error = f"Timed out after {settings.ANALYSIS_TIMEOUT_SECONDS} s"
                r.save()
                n += 1
    return n


def retry_run(run: m.AnalysisRun, request=None) -> bool:
    """Retry a failed run (bounded by ANALYSIS_MAX_RETRIES)."""
    with transaction.atomic():
        r = m.AnalysisRun.objects.select_for_update().get(pk=run.pk)
        if r.status != "failed" or r.retries >= settings.ANALYSIS_MAX_RETRIES:
            return False
        r.status, r.retries, r.error, r.finished_at, r.started_at, r.progress = "queued", r.retries + 1, "", None, None, ""
        r.save()
    audit(request, "run_retried", r, retries=r.retries)
    _dispatch(r.pk, r.is_default, wait=False)
    return True


def latest_default(analysis_type: str) -> m.AnalysisRun | None:
    return m.AnalysisRun.objects.filter(analysis_type=analysis_type, status="succeeded", is_default=True).order_by("-created_at").first() or \
        m.AnalysisRun.objects.filter(analysis_type=analysis_type, status="succeeded").order_by("-created_at").first()


def run_standard_analyses(request=None) -> dict:
    """The analyses shown on the public pages (idempotent)."""
    out = {}
    out["inequality"], _ = submit_run("inequality", ineq_default(), label="Standard inequality analysis", is_default=True, request=request)
    out["causal"], _ = submit_run("causal", {}, label="Standard causal analysis (PQTR -> primary OOS)", is_default=True, request=request)
    sims = []
    for s in DEFAULT_SCENARIOS:
        r, _ = submit_run("simulation", s, label=s["name"], is_default=False, request=request)
        sims.append(r)
    out["simulations"] = sims
    return out
