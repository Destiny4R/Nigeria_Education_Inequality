"""Shared fixtures.  The analyses read the real processed data in data/processed/ (committed with the project);
artefact files written by tests go to a temporary directory so the project's artefacts are never touched."""
import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def _isolate(settings, tmp_path):
    settings.ARTEFACT_DIR = tmp_path / "artefacts"
    settings.ANALYSIS_EXECUTION = "sync"
    settings.THROTTLE_RUNS_PER_HOUR = 1000
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def analytic():
    from portal import services as S
    return S.get_analytic()


@pytest.fixture
def imported(db):
    """Datasets, sources, versions, quality reports and indicator definitions recorded in the database."""
    from portal import services as S
    job = S.import_all_datasets()
    assert job.status == "succeeded", job.error
    return job


@pytest.fixture(scope="session")
def fast_causal_cfg():
    return dict(n_boot=100, n_refute=10, dml_repeats=1)
