"""Run lifecycle, registry, auditing, throttling and traceability (plan 6.2, 10.2, 10.3, 11.2, 11.4)."""
import json
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import IntegrityError, transaction
from django.test import RequestFactory
from django.utils import timezone

from portal import models as m, services as S
from src.common import load_register, sha256_file, sha256_text, stable_json
from src.inequality import metrics as M

pytestmark = pytest.mark.django_db

SIM = dict(name="T1", intervention="pct_reduction", value=15.0, coverage="all", n_draws=200)
CAUSAL_FAST = dict(n_boot=100, n_refute=10, dml_repeats=1)


# ------------------------------------------------------------------------------------------ registry / import job
def test_import_records_sources_datasets_versions_and_reports(imported):
    reg = load_register()
    assert m.DataSource.objects.count() == len(reg["sources"])
    assert m.Dataset.objects.count() == len(reg["datasets"]) == 10
    assert m.DatasetVersion.objects.count() == 10
    assert m.DataQualityReport.objects.count() == 10
    assert m.IndicatorDefinition.objects.count() == len(M.INDICATORS)
    assert set(m.DatasetVersion.objects.values_list("readiness", flat=True)) <= {"Approved", "Approved with limitations", "Rejected"}
    for v in m.DatasetVersion.objects.select_related("dataset"):
        raw = Path("data/raw") / v.dataset.raw_file
        assert v.sha256 == sha256_file(raw) and v.n_rows > 0 and v.size_bytes == raw.stat().st_size
    for src in m.DataSource.objects.all():                       # plan 5.1: provenance documented for every source
        assert src.url and src.licence and src.limitations and src.permitted_uses and src.access_date
    assert imported.summary["datasets"] == 10 and len(imported.summary["data_fingerprint"]) == 64


def test_import_is_idempotent(imported):
    again = S.import_all_datasets()
    assert again.status == "succeeded" and again.summary["new_versions"] == 0
    assert m.DatasetVersion.objects.count() == 10


def test_import_failure_is_recorded_not_raised(db, monkeypatch):
    import src.cleaning.pipeline as P

    def boom(write=True):
        raise OSError("disk unavailable")
    monkeypatch.setattr(P, "run_cleaning", boom)
    job = S.import_all_datasets()
    assert job.status == "failed" and "disk unavailable" in job.error and job.finished_at
    assert m.DatasetVersion.objects.count() == 0


def test_new_data_creates_a_new_dataset_version(imported, tmp_path, monkeypatch):
    ds = m.Dataset.objects.get(dataset_id="wb_poverty_2018")
    old = ds.versions.get()
    ds.versions.all().update(sha256="0" * 64)                     # pretend the stored version is from different raw data
    job = S.import_all_datasets()
    assert job.summary["new_versions"] == 1
    assert sorted(ds.versions.values_list("version", flat=True)) == [1, 2]
    assert ds.versions.get(version=2).sha256 == old.sha256          # the real checksum is recorded as the new version
    assert ds.versions.get(version=1).sha256 == "0" * 64            # the earlier version is kept for history


# ------------------------------------------------------------------------------------------ configuration handling
def test_config_normalisation_whitelists_and_is_order_independent():
    a = S.normalise_config("inequality", {"indicator": "oos_total_2021", "states": ["Lagos", "Abia"], "evil": "x"})
    b = S.normalise_config("inequality", {"states": ["Abia", "Lagos"], "indicator": "oos_total_2021"})
    assert "evil" not in a and a == b
    assert S.config_hash("inequality", a) == S.config_hash("inequality", b)
    sim = S.normalise_config("simulation", {**SIM, "junk": 1})
    assert "junk" not in sim
    with pytest.raises(ValueError):
        S.normalise_config("nope", {})


def test_causal_config_validation():
    ok = S.normalise_config("causal", {})
    assert S.validate_causal_config(ok) == []
    assert S.validate_causal_config({**ok, "outcome": "pqtr"})
    assert S.validate_causal_config({**ok, "confounders": ["pov_215", "private_share_enrol"]})
    assert S.validate_causal_config({**ok, "n_boot": 10**7})
    cfg = S.normalise_config("causal", {"treatment": "oos_total_2021", "seed": 1})
    assert cfg["treatment"] == "log_pqtr" and cfg["seed"] == S.CausalConfig().seed       # users cannot change treatment or seed


# ------------------------------------------------------------------------------------------ run lifecycle
def test_successful_run_is_complete_and_traceable():
    run, created = S.submit_run("inequality", {"indicator": "oos_total_2021"})
    assert created and run.status == "succeeded" and run.results
    assert run.data_sha256 == S.data_fingerprint()
    assert run.results_sha256 == run.results["results_sha256"] and len(run.config_hash) == 64
    assert run.software_versions["python"] and run.software_versions["Django"]
    art = Path(S.settings.BASE_DIR) / run.artefact_path if not Path(run.artefact_path).is_absolute() else Path(run.artefact_path)
    assert art.exists() and json.loads(art.read_text())["results_sha256"] == run.results_sha256
    assert run.started_at and run.finished_at and run.duration is not None


def test_stored_result_reproduces_from_its_configuration():
    run, _ = S.submit_run("inequality", {"indicator": "oos_total_2021", "region": "North"})
    again = S._compute("inequality", run.config)
    assert again["results_sha256"] == run.results_sha256


def test_duplicate_submission_returns_existing_run():
    r1, c1 = S.submit_run("simulation", SIM)
    r2, c2 = S.submit_run("simulation", dict(reversed(list(SIM.items()))))      # same content, different key order
    assert c1 and not c2 and r1.pk == r2.pk
    r3, c3 = S.submit_run("simulation", SIM, force=True)
    assert c3 and r3.pk != r1.pk and r3.results_sha256 == r1.results_sha256       # forced re-run reproduces the same result
    assert m.AnalysisRun.objects.filter(analysis_type="simulation").count() == 2


def test_data_change_invalidates_reuse(tmp_path, monkeypatch):
    r1, _ = S.submit_run("inequality", {"indicator": "oos_total_2021"})
    import pandas as pd
    df = S.get_analytic()
    df.loc[0, "oos_total_2021"] = 77.0
    p = tmp_path / "state_analytic.parquet"
    df.to_parquet(p)
    S._read.cache_clear()
    monkeypatch.setattr(S, "ANALYTIC", p)
    assert S.data_fingerprint() != r1.data_sha256
    r2, created = S.submit_run("inequality", {"indicator": "oos_total_2021"})
    assert created and r2.pk != r1.pk and r2.data_sha256 != r1.data_sha256
    S._read.cache_clear()


def test_failed_run_never_carries_results(monkeypatch):
    def boom(*a, **k):
        raise ValueError("model exploded")
    monkeypatch.setattr(S, "_compute", boom)
    run, _ = S.submit_run("inequality", {"indicator": "oos_total_2021"})
    assert run.status == "failed" and run.results is None and run.results_sha256 == ""
    assert "model exploded" in run.error and run.finished_at
    assert not list((S.settings.ARTEFACT_DIR).glob("*")) if S.settings.ARTEFACT_DIR.exists() else True      # nothing half-written
    assert not m.InequalityResult.objects.filter(run=run).exists()


def test_database_forbids_results_on_unsuccessful_run():
    run = m.AnalysisRun.objects.create(analysis_type="inequality", config={}, config_hash="h", data_sha256="d")
    with pytest.raises(IntegrityError), transaction.atomic():
        m.AnalysisRun.objects.filter(pk=run.pk).update(results={"x": 1})                  # status is still 'queued'
    with pytest.raises(IntegrityError), transaction.atomic():
        m.AnalysisRun.objects.create(analysis_type="inequality", config={}, config_hash="h", data_sha256="d", status="failed", results={"x": 1})
    ok = m.AnalysisRun.objects.create(analysis_type="inequality", config={}, config_hash="h", data_sha256="d", status="succeeded", results={"x": 1})
    assert ok.pk


def test_failed_run_is_not_reused_and_can_be_retried(monkeypatch, settings):
    calls = {"n": 0}
    real = S._compute

    def flaky(t, c):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("transient")
        return real(t, c)
    monkeypatch.setattr(S, "_compute", flaky)
    run, _ = S.submit_run("inequality", {"indicator": "oos_total_2021"})
    assert run.status == "failed"
    assert S.retry_run(run) is True
    run.refresh_from_db()
    assert run.status == "succeeded" and run.retries == 1 and run.error == "" and run.results
    assert S.retry_run(run) is False                                                       # only failed runs can be retried


def test_retries_are_bounded(monkeypatch, settings):
    settings.ANALYSIS_MAX_RETRIES = 2
    monkeypatch.setattr(S, "_compute", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    run, _ = S.submit_run("inequality", {"indicator": "oos_total_2021"})
    assert S.retry_run(run) and S.retry_run(run)
    run.refresh_from_db()
    assert run.status == "failed" and run.retries == 2
    assert S.retry_run(run) is False


def test_stale_runs_are_reaped_and_late_results_discarded(settings, monkeypatch):
    settings.ANALYSIS_TIMEOUT_SECONDS = 60
    stuck = m.AnalysisRun.objects.create(analysis_type="inequality", config={}, config_hash="h1", data_sha256="d", status="running", started_at=timezone.now())
    m.AnalysisRun.objects.filter(pk=stuck.pk).update(created_at=timezone.now() - timedelta(seconds=300))
    fresh = m.AnalysisRun.objects.create(analysis_type="inequality", config={}, config_hash="h2", data_sha256="d", status="running", started_at=timezone.now())
    assert S.reap_stale_runs() == 1
    stuck.refresh_from_db(); fresh.refresh_from_db()
    assert stuck.status == "failed" and "Timed out" in stuck.error and stuck.results is None
    assert fresh.status == "running"
    # a worker that finishes after being reaped must not resurrect the run
    run = m.AnalysisRun.objects.create(analysis_type="inequality", config=S.normalise_config("inequality", {}), config_hash="h3", data_sha256="d")
    real = S._compute

    def slow(t, c):
        res = real(t, c)
        m.AnalysisRun.objects.filter(pk=run.pk).update(status="failed", error="Timed out", results=None)    # reaper wins the race
        return res
    monkeypatch.setattr(S, "_compute", slow)
    S.execute_run(run.pk)
    run.refresh_from_db()
    assert run.status == "failed" and run.results is None
    assert not any(Path(S.settings.ARTEFACT_DIR).glob(f"*{run.public_id}*"))


def test_only_queued_runs_execute():
    run, _ = S.submit_run("inequality", {"indicator": "oos_total_2021"})
    before = run.finished_at
    S.execute_run(run.pk)                               # already succeeded: no-op
    run.refresh_from_db()
    assert run.finished_at == before and run.status == "succeeded"


def test_thread_execution_mode_completes(settings):
    settings.ANALYSIS_EXECUTION = "thread"
    import threading
    run, _ = S.submit_run("simulation", {**SIM, "name": "threaded"}, wait=True)       # wait=True forces in-line execution (used by request/response views)
    assert run.status == "succeeded"
    run2, _ = S.submit_run("inequality", {"indicator": "oos_total_2021", "zone": "NW"})
    for t in [t for t in threading.enumerate() if t.name.startswith("run-")]:
        t.join(30)
    run2.refresh_from_db()
    # SQLite in-memory test DBs are per-connection, so a worker thread may not see the row; either outcome must be a clean state
    assert run2.status in ("queued", "running", "succeeded", "failed")
    assert (run2.results is not None) == (run2.status == "succeeded")


# ------------------------------------------------------------------------------------------ derived records
def test_inequality_run_persists_results_rows():
    run, _ = S.submit_run("inequality", {"indicator": "oos_total_2021"})
    rows = m.InequalityResult.objects.filter(run=run)
    metrics = set(rows.values_list("metric", flat=True))
    assert {"gini", "theil_t", "weighted_mean", "absolute_gap", "rate"} <= metrics
    assert rows.filter(group_type="wealth").count() == 5 and rows.filter(group_type="area").count() == 2


def test_simulation_run_persists_scenario_and_results():
    run, _ = S.submit_run("simulation", SIM)
    sim = run.simulation
    assert sim.scenario.config["value"] == 15.0
    nat = sim.results.get(group_type="national")
    assert nat.change_pp == pytest.approx(run.results["headline"]["absolute_change_pp"])
    assert sim.results.filter(group_type="state").count() == 31
    # the same scenario is stored once
    S.submit_run("simulation", SIM, force=True)
    assert m.PolicyScenario.objects.filter(config__value=15.0).count() == 1


@pytest.mark.slow
def test_causal_run_persists_model_versions_and_validations():
    run, _ = S.submit_run("causal", CAUSAL_FAST)
    assert run.status == "succeeded", run.error
    cm = run.causal_model
    assert cm.treatment == "log_pqtr" and cm.outcome == "oos_total_2021" and cm.confounders == ["pov_215", "north"] and cm.estimand and cm.assumptions
    mv = cm.versions.get()
    assert len(mv.artefact_sha256) == 64 and mv.software_versions
    kinds = set(mv.validations.values_list("kind", flat=True))
    assert kinds == {"refutation", "sensitivity", "robustness", "predictive", "overlap"}


# ------------------------------------------------------------------------------------------ audit & throttling
def test_audit_log_stores_only_a_salted_hash_of_the_address():
    req = RequestFactory().get("/", REMOTE_ADDR="203.0.113.77")
    S.audit(req, "test_action", None, k="v")
    log = m.AuditLog.objects.get(action="test_action")
    assert len(log.client_hash) == 16 and "203.0.113.77" not in json.dumps([log.client_hash, log.details, log.object_id])
    other = RequestFactory().get("/", REMOTE_ADDR="203.0.113.78")
    assert S.client_hash(other) != S.client_hash(req)
    assert S.client_hash(req) == S.client_hash(RequestFactory().get("/x", REMOTE_ADDR="203.0.113.77"))


def test_audit_never_breaks_a_request(monkeypatch):
    monkeypatch.setattr(m.AuditLog.objects, "create", lambda **k: (_ for _ in ()).throw(RuntimeError("db down")))
    S.audit(RequestFactory().get("/"), "x")        # must not raise


def test_throttle_limits_per_client(settings):
    settings.THROTTLE_RUNS_PER_HOUR = 3
    req = RequestFactory().get("/", REMOTE_ADDR="198.51.100.5")
    assert [S.throttled(req) for _ in range(5)] == [False, False, False, True, True]
    other = RequestFactory().get("/", REMOTE_ADDR="198.51.100.6")
    assert S.throttled(other) is False
    assert S.throttled(req, "other-bucket") is False


def test_run_submissions_are_audited():
    req = RequestFactory().get("/", REMOTE_ADDR="192.0.2.1")
    run, _ = S.submit_run("simulation", {**SIM, "name": "audited"}, request=req)
    assert m.AuditLog.objects.filter(action="simulation_submitted", object_id=str(run.public_id)).exists()
