"""Regression test: results must be byte-identical across separate Python processes (different hash randomisation).

A previous version stored DoWhy's adjustment set in the order DoWhy returned it, which varies between processes, so a stored
result could not be reproduced by a fresh process even though every number was identical."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CODE = (
    "import os, django; os.environ['DJANGO_SETTINGS_MODULE']='eduineq.settings'; django.setup();"
    "from portal import services as S;"
    "r = S._compute('causal', S.normalise_config('causal', dict(n_boot=30, n_refute=4, dml_repeats=1)));"
    "print('SHA', r['results_sha256']); print('ADJ', ','.join(r['identification']['identifying_graph']['backdoor_adjustment_set']))"
)


def _run(hashseed: str) -> dict:
    env = {**os.environ, "PYTHONHASHSEED": hashseed, "DJANGO_DEBUG": "1"}
    out = subprocess.run([sys.executable, "-c", CODE], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert out.returncode == 0, out.stderr[-2000:]
    return dict(line.split(" ", 1) for line in out.stdout.splitlines() if line.startswith(("SHA ", "ADJ ")))


@pytest.mark.slow
def test_causal_result_hash_is_identical_across_processes():
    a, b, c = _run("1"), _run("2"), _run("12345")
    assert a["SHA"] == b["SHA"] == c["SHA"]
    assert a["ADJ"] == "north,pov_215"          # sorted, therefore stable
