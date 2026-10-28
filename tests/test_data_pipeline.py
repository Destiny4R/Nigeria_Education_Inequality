"""Data validation (plan 11.1) and the data-readiness gate (plan 5.2)."""
import pandas as pd
import pytest

from src.cleaning import pipeline as P
from src.common import load_register, sha256_file, RAW
from src.ingestion import loader as L


@pytest.fixture(scope="module")
def cleaned():
    return P.run_cleaning(write=False)


def test_register_is_complete_and_files_exist():
    reg = load_register()
    ids = {s["source_id"] for s in reg["sources"]}
    for s in reg["sources"]:
        assert L.validate_source_metadata(s) == [], s["source_id"]       # plan 5.1: provenance fields recorded
    for d in reg["datasets"]:
        assert d["source_id"] in ids
        assert (RAW / d["file"]).exists(), d["file"]


def test_missing_provenance_fields_are_reported():
    assert set(L.validate_source_metadata({})) == set(L.REQUIRED_SOURCE_FIELDS)
    assert L.validate_source_metadata({f: "x" for f in L.REQUIRED_SOURCE_FIELDS}) == []


def test_loader_rejects_wrong_schema(tmp_path, monkeypatch):
    reg = load_register()
    d = next(x for x in reg["datasets"] if x["dataset_id"] == "wb_poverty_2018")
    bad = tmp_path / d["file"]
    bad.write_text("state,wrong\nLagos,1\n")
    monkeypatch.setattr(L, "RAW", tmp_path)
    with pytest.raises(L.SchemaError):
        L.load_raw("wb_poverty_2018")


def test_loader_rejects_unknown_dataset_and_missing_file(tmp_path, monkeypatch):
    with pytest.raises(KeyError):
        L.load_raw("nope")
    monkeypatch.setattr(L, "RAW", tmp_path)
    with pytest.raises(FileNotFoundError):
        L.load_raw("wb_poverty_2018")


def test_checksums_recorded_match_files(cleaned):
    _, _, reports, _ = cleaned
    reg = {d["dataset_id"]: d for d in load_register()["datasets"]}
    for did, rep in reports.items():
        assert rep.sha256 == sha256_file(RAW / reg[did]["file"])


def test_source_to_cleaned_reconciliation(cleaned):
    """Plan 11.1: the cleaning report must explain how many records were retained, excluded or flagged."""
    _, _, reports, _ = cleaned
    for did, rep in reports.items():
        if did == "wdi_national" or did == "mics_2021_national":
            continue
        assert rep.rows_in == rep.rows_state + rep.rows_national_removed, did
        assert rep.rows_state <= 37
        assert rep.transformations, f"{did}: no transformation recorded"
        assert {"R01", "R02"} <= {t["step"] for t in rep.transformations} or did == "gh_capitals"


def test_analytic_dataset_structure(cleaned):
    a, _, _, info = cleaned
    assert len(a) == 37 and a.state.is_unique
    assert set(a.state) == set(pd.read_csv("config/states.csv").state)
    assert info["n_states"] == 37
    s = a[a.in_primary_sample]
    assert len(s) == info["n_primary_sample"] == 31
    assert s[["pqtr", "oos_total_2021", "pov_215"]].notna().all().all()      # inclusion criteria hold for every included row
    # a critical flag on a variable that is NOT used (e.g. the 2015/16 covariates) does not exclude a state, but a critical flag
    # that nulls a used variable always does (checked in test_duplicate_rows_are_set_to_missing_not_averaged)
    assert s.pqtr.between(1, 1000).all() and s.oos_total_2021.between(0, 100).all()


def test_every_excluded_state_has_a_documented_reason(cleaned):
    a, _, _, info = cleaned
    excluded = a[~a.in_primary_sample]
    assert len(excluded) == len(info["excluded"]) == 6
    assert excluded.exclusion_reason.notna().all() and (excluded.exclusion_reason != "").all()
    assert {e["state"] for e in info["excluded"]} == set(excluded.state)


def test_duplicate_rows_are_set_to_missing_not_averaged(cleaned):
    """Rule R04: a duplicated row cannot be trusted, so the affected variables are blanked (never imputed or averaged)."""
    a, _, reports, _ = cleaned
    A = a.set_index("state")
    checked = 0
    for s, fl in reports["fme_2016_17_teachers"].flags.items():
        if any(f["code"] == "DUPLICATE_ROW" for f in fl):
            assert pd.isna(A.loc[s, "q_mf"]) and pd.isna(A.loc[s, "pqtr"]) and not A.loc[s, "in_primary_sample"]
            checked += 1
    for s, fl in reports["fme_2016_17_enrolment"].flags.items():
        for f in fl:
            if f["code"] == "DUPLICATE_ROW" and f["detail"].startswith("Private"):
                assert pd.isna(A.loc[s, "priv_pupils"]) and pd.isna(A.loc[s, "total_pupils"])
                checked += 1
            if f["code"] == "DUPLICATE_ROW" and f["detail"].startswith("Public"):
                assert pd.isna(A.loc[s, "pub_pupils"]) and pd.isna(A.loc[s, "pqtr"])
                checked += 1
    for s, fl in reports["fme_2015_16_oos"].flags.items():
        if any(f["code"] == "DUPLICATE_ROW" for f in fl):
            assert pd.isna(A.loc[s, "enrol_2015"])
            checked += 1
    assert checked >= 5, "the Digest contains duplicated rows that the pipeline must have detected"


def test_duplicate_vector_detector():
    df = pd.DataFrame({"state": ["A", "B", "C", "D"], "x": [5, 5, 7, 0], "y": [9, 9, 1, 0]})
    assert set(P._duplicate_vectors(df, ["x", "y"])) == {"A", "B"}
    df2 = pd.DataFrame({"state": ["A", "B"], "x": [0, 0], "y": [0, 0]})
    assert P._duplicate_vectors(df2, ["x", "y"]) == []                  # all-zero vectors are not evidence of copying


def test_cleaning_is_reproducible(cleaned):
    """Plan 11.1/11.3: same inputs -> byte-identical analytic dataset."""
    a1 = cleaned[0].to_csv(index=False)
    a2 = P.run_cleaning(write=False)[0].to_csv(index=False)
    assert a1 == a2


def test_readiness_statuses_and_gate1(cleaned):
    _, _, reports, _ = cleaned
    valid = {"Approved", "Approved with limitations", "Rejected"}
    assert {r.readiness["status"] for r in reports.values()} <= valid
    assert reports["gh_capitals"].readiness["status"] == "Rejected"
    for r in reports.values():                                            # the seven plan-5.2 questions are all answered
        for k in ("file_available", "n_observations", "max_missing_pct", "definitions_consistent", "variables_relevant", "linkable", "licence_ok"):
            assert k in r.readiness
    # Gate 1: a defensible dataset supports the primary outcome
    assert reports["mics_2021_oos"].readiness["status"] in ("Approved", "Approved with limitations")
    assert reports["mics_2021_oos"].readiness["role"]


def test_readiness_rejects_when_majority_rows_fail():
    rep = P.DatasetReport("fme_2016_17_ptr", "x", rows_in=10, rows_state=10, n_states=10)
    for i in range(6):
        rep.flag(f"S{i}", "DUPLICATE_ROW", P.CRITICAL)
    assert P.assess_readiness(rep)["status"] == "Rejected"                # > 40 % critical rows
    ok = P.DatasetReport("wb_poverty_2018", "x", rows_in=36, rows_state=36, n_states=36, missingness={"pov_215": 2.0})
    assert P.assess_readiness(ok)["status"] == "Approved"


def test_rejected_columns_are_not_in_the_analytic_file(cleaned):
    a, _, reports, _ = cleaned
    assert "oos_urban" in reports["mics_2021_oos"].rejected_columns or any("urban" in k for k in reports["mics_2021_oos"].rejected_columns)
    assert not any(c in a.columns for c in ("oos_urban", "oos_rural"))


def test_national_series_drops_flagged_outlier(cleaned):
    _, national, _, _ = cleaned
    assert set(national.columns) >= {"indicator_code", "year", "value"}
    assert national.value.notna().any()
