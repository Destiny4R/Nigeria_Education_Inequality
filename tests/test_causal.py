"""Causal engine: input validation, estimator accuracy on data with a KNOWN effect (analytical validation), sensitivity algebra,
and the structural guarantees of the full pipeline (plan 8, 11.3).  The simulated data below exist only inside the tests."""
import networkx as nx
import numpy as np
import pandas as pd
import pytest
from scipy import stats

from src.causal import engine as C


def make_world(n=60, beta=4.0, seed=0):
    """y = 10 + beta*logT + 0.3*poverty + 5*north + noise ; logT depends on poverty and region (confounded)."""
    rng = np.random.default_rng(seed)
    north = rng.integers(0, 2, n)
    pov = rng.normal(40 + 20 * north, 12, n).clip(2, 95)
    logt = 3.0 + 0.02 * pov + 0.6 * north + rng.normal(0, 0.5, n)
    y = 10 + beta * logt + 0.3 * pov + 5 * north + rng.normal(0, 4, n)
    female = np.clip(y + rng.normal(1.0, 2.0, n), 0, 100)
    return pd.DataFrame({"log_pqtr": logt, "pqtr": np.exp(logt), "oos_total_2021": y, "oos_female_2021": female, "pov_215": pov, "north": north, "state": [f"S{i}" for i in range(n)]})


CFG = C.CausalConfig()


def test_adjusted_ols_recovers_known_effect_and_naive_is_biased():
    est = [C.estimate_ols(make_world(400, seed=s), CFG, list(CFG.confounders), "adj")[0]["coef_per_log_unit"] for s in range(10)]
    naive = [C.estimate_ols(make_world(400, seed=s), CFG, [], "naive", kind="naive")[0]["coef_per_log_unit"] for s in range(10)]
    assert abs(np.mean(est) - 4.0) < 0.35
    assert np.mean(naive) > 5.0                       # omitted-confounder bias is real and visible in this world


def test_confidence_interval_coverage():
    """Frequentist check: a nominal 95 % HC3 interval should cover the truth most of the time (n = 60)."""
    hits = 0
    reps = 300
    for s in range(reps):
        row, _ = C.estimate_ols(make_world(60, seed=1000 + s), CFG, list(CFG.confounders), "adj")
        hits += row["ci_low"] <= 4.0 <= row["ci_high"]
    assert hits / reps > 0.90


def test_policy_effect_scaling_is_per_ten_percent_reduction():
    row, _ = C.estimate_ols(make_world(200, seed=3), CFG, list(CFG.confounders), "adj")
    assert row["effect_10pct_reduction"] == pytest.approx(row["coef_per_log_unit"] * np.log(0.9))
    assert row["effect_10pct_ci_low"] <= row["effect_10pct_reduction"] <= row["effect_10pct_ci_high"]
    assert row["ci_includes_zero"] == (row["ci_low"] <= 0 <= row["ci_high"])


def test_estimator_with_no_effect_includes_zero_most_of_the_time():
    inc = np.mean([C.estimate_ols(make_world(60, beta=0.0, seed=50 + s), CFG, list(CFG.confounders), "adj")[0]["ci_includes_zero"] for s in range(100)])
    assert inc > 0.88


# ------------------------------------------------------------------------------------------ input validation (plan 8.3 step 2)
def test_validate_inputs_accepts_valid_specification():
    assert C.validate_inputs(make_world(), CFG) == []


def test_validate_inputs_rejects_bad_specifications():
    df = make_world()
    assert any("not found" in p for p in C.validate_inputs(df.drop(columns="pov_215"), CFG))
    assert any("differ" in p for p in C.validate_inputs(df, C.CausalConfig(outcome="log_pqtr")))
    assert any("cannot be used as a confounder" in p for p in C.validate_inputs(df, C.CausalConfig(confounders=("log_pqtr", "north"))))
    assert any("teacher-supply" in p for p in C.validate_inputs(df, C.CausalConfig(outcome="pqtr")))
    assert any("too few" in p for p in C.validate_inputs(df.head(10), CFG))
    d2 = df.copy()
    d2.loc[0, "pov_215"] = np.nan
    assert any("missing" in p for p in C.validate_inputs(d2, CFG))
    d3 = df.copy()
    d3["private_share_enrol"] = 5.0
    assert any("post-treatment" in p for p in C.validate_inputs(d3, C.CausalConfig(confounders=("pov_215", "private_share_enrol"))))
    d4 = df.copy()
    d4["north"] = d4["north"].astype(str)
    assert any("not numeric" in p for p in C.validate_inputs(d4, CFG))


def test_run_rejects_post_treatment_adjustment(analytic):
    with pytest.raises(ValueError, match="post-treatment"):
        C.run_causal_analysis(analytic, C.CausalConfig(confounders=("pov_215", "private_share_enrol"), n_boot=100, n_refute=10, dml_repeats=1))


# ------------------------------------------------------------------------------------------ sensitivity algebra
def test_robustness_value_matches_published_formula():
    t, dof = 3.2, 40
    f = abs(t) / np.sqrt(dof)
    expected = 0.5 * (np.sqrt(f ** 4 + 4 * f ** 2) - f ** 2)                   # Cinelli & Hazlett (2020), eq. for RV_{q=1}
    assert C.robustness_value(t, dof) == pytest.approx(expected)
    assert 0 < C.robustness_value(t, dof) < 1
    assert C.robustness_value(1.0, 40) < C.robustness_value(5.0, 40)           # stronger evidence -> more robust
    assert C.robustness_value(0.5, 40, alpha=0.05) == 0.0                      # already insignificant -> RV_alpha is 0
    assert C.robustness_value(0.0, 40) == 0.0


def test_sensitivity_block_is_consistent():
    df = make_world(80, seed=5)
    s = C.sensitivity(df, CFG)
    assert s["dof"] == len(df) - 4          # constant + treatment + 2 confounders
    assert s["partial_r2_treatment_outcome"] == pytest.approx(s["t_statistic"] ** 2 / (s["t_statistic"] ** 2 + s["dof"]))
    assert set(s["benchmarks"]) == set(CFG.confounders)
    assert all(0 <= v["partial_r2_with_outcome"] <= 1 for v in s["benchmarks"].values())


def test_graph_specifications_are_acyclic_and_treatment_precedes_outcome():
    for g in (C.GRAPH_IDENTIFYING, C.GRAPH_THREAT):
        dg = nx.DiGraph(g["edges"])
        assert nx.is_directed_acyclic_graph(dg)
        assert C.TREATMENT in dg and C.OUTCOME in dg
        assert nx.has_path(dg, C.TREATMENT, C.OUTCOME)
    # no adjustment variable is a descendant of the treatment (that would be post-treatment adjustment)
    dg = nx.DiGraph(C.GRAPH_IDENTIFYING["edges"])
    assert not (set(C.CONFOUNDERS) & nx.descendants(dg, C.TREATMENT))


def test_graphs_build_for_every_allowed_outcome_and_adjustment_set():
    for outcome in C.OUTCOME_LABELS:
        for conf in (("pov_215", "north"), ("pov_215",), ("north",)):
            gi, gt = C.build_graphs(outcome, conf)
            for g in (gi, gt):
                dg = nx.DiGraph(g["edges"])
                assert nx.is_directed_acyclic_graph(dg)
                assert nx.has_path(dg, C.TREATMENT, outcome)
                assert outcome in g["nodes"]                                     # the failure that broke custom runs
            assert gt["edges_unobserved"] == [("U", C.TREATMENT), ("U", outcome)]


def test_dowhy_identification_accepts_custom_outcome_and_adjustment_set():
    df = make_world(60, seed=7)
    cfg = C.CausalConfig(outcome="oos_female_2021", confounders=("north",), n_refute=10)
    out = C.dowhy_analysis(df, cfg)
    assert out["identifying_graph"]["identified"] is True
    assert set(out["identifying_graph"]["backdoor_adjustment_set"]) == {"north"}
    assert out["threat_graph"]["identified_by_backdoor"] is False


def test_dag_plot_builder_handles_every_outcome_and_threat_graph():
    from portal.plotting import dag
    for outcome in C.OUTCOME_LABELS:
        gi, gt = C.build_graphs(outcome)
        for g, threat in ((gi, False), (gt, True)):
            fig = dag(g, threat)
            assert len(fig["layout"]["annotations"]) == len(g["edges"]) + (2 if threat else 0)
            colours = fig["data"][0]["marker"]["color"]
            assert sum(c == "#bfdbfe" for c in colours) == 1           # exactly one outcome node, wherever the outcome is
            texts = fig["data"][0]["text"]
            assert any("(outcome)" in t for t in texts)


# ------------------------------------------------------------------------------------------ full pipeline
@pytest.fixture(scope="module")
def full_result():
    from src.cleaning.pipeline import run_cleaning
    a, *_ = run_cleaning(write=False)
    cfg = C.CausalConfig(n_boot=100, n_refute=10, dml_repeats=1)
    return a, cfg, C.run_causal_analysis(a, cfg)


@pytest.mark.slow
def test_pipeline_documents_every_required_element(full_result):
    _, _, r = full_result
    spec = r["specification"]
    assert spec["treatment"] and spec["outcome"] and spec["confounders"] and spec["estimand"]      # plan 8.1: four elements
    assert len(spec["assumptions"]) >= 6
    kinds = [e["kind"] for e in r["estimates"]]
    assert kinds.count("primary") == 1 and kinds.count("naive") == 1
    naive = next(e for e in r["estimates"] if e["kind"] == "naive")
    assert "NOT a causal estimate" in naive["method"]
    assert all(e["ci_low"] < e["ci_high"] for e in r["estimates"])                                 # uncertainty reported for every estimate
    assert len(r["estimates"]) >= 4                                                                 # several defensible methods compared
    assert r["identification"]["identifying_graph"]["identified"] is True
    assert set(r["identification"]["identifying_graph"]["backdoor_adjustment_set"]) == set(spec["confounders"])
    assert len(r["identification"]["refutations"]) == 3
    assert r["identification"]["threat_graph"]["identified_by_backdoor"] is False                 # honest: unobserved confounding breaks it
    assert any("Cross-sectional" in w for w in r["warnings"])
    for k in ("sensitivity_unmeasured_confounding", "robustness", "subgroups", "overlap_balance", "explainability", "explanation", "software_versions"):
        assert k in r


@pytest.mark.slow
def test_pipeline_refuses_unsupported_designs(full_result):
    _, _, r = full_result
    app = {a["method"]: a for a in r["applicability"]}
    for name in ("Difference-in-differences", "Fixed-effects panel model", "Instrumental variables"):
        assert app[name]["applicable"] is False and app[name]["reason"]     # not run, with the reason recorded (plan 8.2)


@pytest.mark.slow
def test_explanation_does_not_overclaim(full_result):
    _, _, r = full_result
    primary = next(e for e in r["estimates"] if e["kind"] == "primary")
    verdict = r["explanation"]["verdict"].lower()
    if primary["ci_includes_zero"]:
        assert "inconclusive" in verdict or "no reliable evidence" in verdict
    assert "proves" not in " ".join(r["explanation"]["summary"]).lower()


@pytest.mark.slow
def test_pipeline_is_deterministic(full_result):
    a, cfg, r1 = full_result
    r2 = C.run_causal_analysis(a, cfg)
    assert r1["results_sha256"] == r2["results_sha256"]                    # plan 11.3: same inputs + configuration => same results


@pytest.mark.slow
def test_results_change_when_data_change(full_result):
    a, cfg, r1 = full_result
    a2 = a.copy()
    idx = a2.index[a2.in_primary_sample][0]
    a2.loc[idx, "oos_total_2021"] += 7.0
    r2 = C.run_causal_analysis(a2, cfg)
    assert r1["results_sha256"] != r2["results_sha256"]


@pytest.mark.slow
def test_predictive_models_are_validated_out_of_sample(full_result):
    _, _, r = full_result
    perf = {p["model"]: p for p in r["explainability"]["predictive_performance"]}
    assert "Baseline: mean of training states" in perf                         # plan 11.3: compare with a simple baseline
    base = perf["Baseline: mean of training states"]["loo_rmse"]
    assert perf["OLS: poverty + region"]["loo_rmse"] < base                    # leave-one-out and leave-zone-out (group-aware) splits
    assert all("leave_zone_out_rmse" in p for p in perf.values())
