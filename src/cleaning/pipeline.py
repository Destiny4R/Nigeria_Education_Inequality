"""Reproducible cleaning pipeline with documented rules, quality reports and the data-readiness gate.

Principles (plan section 5):
* raw data are never edited; every transformation is logged;
* a value is only set to missing when a documented rule shows it is invalid or cannot be trusted;
  when two rows are exact duplicates of each other we cannot tell which is correct, so BOTH are
  set to missing (never "repaired" by guessing);
* printed percentages/ratios are recomputed from counts rather than trusted;
* each dataset is assigned a readiness status: Approved / Approved with limitations / Rejected.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

from src.common import INTERIM, PROCESSED, canonical_state, parse_number, states_reference, stable_json, sha256_text
from src.ingestion.loader import load_raw, RawDataset

# ----------------------------------------------------------------------------------------
# Documented cleaning rules (the identifiers appear in every quality report)
# ----------------------------------------------------------------------------------------
RULES = {
    "R01": "Standardise state labels to the canonical list of 36 states + FCT; drop the 'National' row (kept only for reconciliation).",
    "R02": "Parse numbers as printed (strip thousands separators, % signs, footnote asterisks); values marked '?' by the extraction are treated as unreliable and set to missing.",
    "R03": "Arithmetic identity checks (male+female=total, public+private=total, qualified<=all teachers, pop-enrolment=out-of-school); mismatches beyond rounding are flagged and the affected component set to missing.",
    "R04": "Exact duplicate rows across different states (or public==private within a state) cannot be trusted: BOTH copies are set to missing.",
    "R05": "Printed percentages/ratios are recomputed from counts; printed values are used only for reconciliation.",
    "R06": "Plausibility bounds: enrolment ratio labelled 'net' cannot exceed 100%; average pupils per school must lie in [20, 3000]; enrolment/child-population above 150% is implausible.",
    "R07": "Cross-table and cross-year reconciliation (Table 2.8 vs 2.10/2.11 vs 2015/16): inconsistencies are flagged (non-critical) unless a hard rule above applies.",
    "R08": "Column-level acceptance: a column whose values fail a necessary consistency test for more than 20% of rows, or carries uncertainty markers, is rejected entirely.",
    "R09": "Robust outlier screening (median/MAD, |z|>3.5 on the log scale for ratios) - flagged, never silently removed.",
}

CRITICAL = "critical"
WARNING = "warning"
INFO = "info"


@dataclass
class DatasetReport:
    dataset_id: str
    sha256: str
    rows_in: int = 0
    rows_national_removed: int = 0
    rows_state: int = 0
    n_states: int = 0
    checks: list = field(default_factory=list)
    transformations: list = field(default_factory=list)
    missingness: dict = field(default_factory=dict)
    usable_columns: list = field(default_factory=list)
    rejected_columns: dict = field(default_factory=dict)
    flags: dict = field(default_factory=dict)  # state -> list[{code, severity, detail}]
    readiness: dict = field(default_factory=dict)

    # helpers ---------------------------------------------------------------------------
    def check(self, rule_id, description, n_checked, failed, severity=WARNING, action="flag", detail=""):
        failed = sorted(set(failed))
        self.checks.append(dict(rule=rule_id, description=description, n_checked=int(n_checked), n_failed=len(failed),
                                states=failed, severity=severity, action=action, detail=detail))

    def transform(self, step, description, n_rows):
        self.transformations.append(dict(step=step, description=description, rows_affected=int(n_rows)))

    def flag(self, state, code, severity, detail=""):
        self.flags.setdefault(state, []).append(dict(code=code, severity=severity, detail=detail))

    def to_dict(self):
        return asdict(self)


# ----------------------------------------------------------------------------------------
def _num_frame(df: pd.DataFrame, cols, rep: DatasetReport):
    """Rule R02. Returns numeric frame; '?'-marked cells become NaN."""
    out = df.copy()
    n_uncertain = 0
    n_unparse = 0
    for c in cols:
        vals, marks = zip(*[parse_number(v) for v in df[c]])
        out[c] = vals
        n_uncertain += sum(m == "uncertain" for m in marks)
        n_unparse += sum(m == "unparseable" for m in marks)
        if any(m == "uncertain" for m in marks):
            out[c] = [np.nan if m == "uncertain" else v for v, m in zip(vals, marks)]
    rep.transform("R02", f"Parsed numeric columns {list(cols)}", len(df))
    if n_uncertain:
        rep.transform("R02", f"{n_uncertain} cells with '?' uncertainty markers set to missing", n_uncertain)
    if n_unparse:
        rep.transform("R02", f"{n_unparse} unparseable cells set to missing", n_unparse)
    return out


def _standardise_states(raw: RawDataset, rep: DatasetReport):
    """Rule R01."""
    df = raw.frame.copy()
    rep.rows_in = len(df)
    df["_canon"] = df["state"].map(canonical_state)
    nat = df["_canon"].isna()
    unknown = [s for s in df.loc[nat, "state"] if str(s).strip().lower() not in ("national", "nigeria", "total")]
    rep.rows_national_removed = int(nat.sum() - len(unknown))
    annotated = [s for s in df["state"] if str(s).startswith("*")]
    df = df[~nat].copy()
    df["state"] = df["_canon"]
    df = df.drop(columns="_canon").reset_index(drop=True)
    rep.rows_state = len(df)
    rep.n_states = df["state"].nunique()
    dups = df["state"][df["state"].duplicated()].tolist()
    rep.check("R01", "State labels map to the canonical list; no duplicate states", len(raw.frame), dups + unknown, CRITICAL, "flag",
              detail=f"unknown labels: {unknown}; duplicates: {dups}")
    rep.transform("R01", f"Standardised state names; removed {rep.rows_national_removed} National row(s)", rep.rows_in)
    for a in annotated:
        s = canonical_state(a)
        rep.flag(s, "SOURCE_ANNOTATION", WARNING, f"Source marks the row with an asterisk ('{a}'); meaning not documented")
    return df, [canonical_state(a) for a in annotated]


def _duplicate_vectors(df, cols, min_nonzero=2):
    """States whose numeric vector over cols is identical to another state's (R04)."""
    sub = df[["state"] + list(cols)].dropna()
    sub = sub[(sub[list(cols)] != 0).sum(axis=1) >= min_nonzero]
    key = sub[list(cols)].round(6).astype(str).agg("|".join, axis=1)
    dup = sub.loc[key.duplicated(keep=False), "state"].tolist()
    return dup


def _close(a, b, tol_abs=1.0, tol_rel=0.002):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    return np.abs(a - b) <= np.maximum(tol_abs, tol_rel * np.maximum(np.abs(a), np.abs(b)))


def _missingness(df, cols):
    return {c: round(float(df[c].isna().mean() * 100), 1) for c in cols}


# ----------------------------------------------------------------------------------------
# Dataset-specific cleaners
# ----------------------------------------------------------------------------------------
def clean_fme_2015_16(raw: RawDataset):
    rep = DatasetReport(raw.dataset_id, raw.sha256)
    df, annotated = _standardise_states(raw, rep)
    cols = [c for c in df.columns if c != "state"]
    df = _num_frame(df, cols, rep)
    n = len(df)
    # R03 identities
    bad = df.loc[~_close(df.enrol_m + df.enrol_f, df.enrol_mf), "state"].tolist()
    rep.check("R03", "enrol_m + enrol_f = enrol_mf", n, bad)
    bad = df.loc[~_close(df.pop_m + df.pop_f, df.pop_mf), "state"].tolist()
    rep.check("R03", "pop_m + pop_f = pop_mf", n, bad)
    bad = df.loc[~_close(df.pop_mf - df.enrol_mf, df.out_of_school_mf), "state"].tolist()
    rep.check("R03", "population - enrolment = out_of_school_mf", n, bad)
    # R04 duplicates
    dup = _duplicate_vectors(df, ["enrol_m", "enrol_f", "enrol_mf"])
    rep.check("R04", "No two states share identical enrolment vectors", n, dup, CRITICAL, "set_missing",
              detail="Identical enrolment (m, f, total) in two states; cannot tell which is correct")
    for s in dup:
        rep.flag(s, "DUPLICATE_ROW", CRITICAL, "Enrolment identical to another state's row")
        df.loc[df.state == s, ["enrol_m", "enrol_f", "enrol_mf"]] = np.nan
    if dup:
        rep.transform("R04", f"Enrolment set to missing for duplicated rows: {sorted(dup)}", len(dup))
    # annotated rows
    for s in annotated:
        df.loc[df.state == s, ["enrol_m", "enrol_f", "enrol_mf"]] = np.nan
        rep.flag(s, "ANNOTATED_ROW_EXCLUDED", CRITICAL, "Asterisked in source; enrolment excluded pending clarification")
    if annotated:
        rep.check("R06", "Rows annotated by the source (asterisk) are excluded", n, annotated, CRITICAL, "set_missing")
    # R05 recompute ratios from counts
    for sx, e, p in (("m", "enrol_m", "pop_m"), ("f", "enrol_f", "pop_f"), ("mf", "enrol_mf", "pop_mf")):
        printed = df[f"ner_{sx}"]
        calc = df[e] / df[p] * 100
        bad = df.loc[(printed - calc).abs() > 0.5, "state"].tolist()
        rep.check("R05", f"printed ner_{sx} equals enrolment/population (tol 0.5pp)", int(calc.notna().sum()), bad)
        df[f"etpr_{sx}"] = calc
        # R06: a net ratio above 100% is logically impossible
        inval = df.loc[calc > 100, "state"].tolist()
        rep.check("R06", f"etpr_{sx} <= 100 (a 'net' ratio cannot exceed 100%)", int(calc.notna().sum()), inval, CRITICAL, "set_missing")
        for s in inval:
            rep.flag(s, f"ETPR_{sx.upper()}_ABOVE_100", CRITICAL, "Ratio above 100% is invalid for a net ratio (source uses enrolment of all ages)")
        df.loc[calc > 100, f"etpr_{sx}"] = np.nan
    df["oos_children_2015"] = df["pop_mf"] - df["enrol_mf"]
    df = df.rename(columns={"pop_mf": "pop6_11_2015", "pop_m": "pop6_11_m_2015", "pop_f": "pop6_11_f_2015", "enrol_mf": "enrol_2015", "enrol_m": "enrol_m_2015", "enrol_f": "enrol_f_2015", "etpr_mf": "etpr_2015", "etpr_m": "etpr_m_2015", "etpr_f": "etpr_f_2015"})
    keep = ["state", "pop6_11_2015", "pop6_11_m_2015", "pop6_11_f_2015", "enrol_2015", "enrol_m_2015", "enrol_f_2015", "etpr_2015", "etpr_m_2015", "etpr_f_2015", "oos_children_2015"]
    clean = df[keep]
    rep.usable_columns = keep[1:]
    rep.rejected_columns = {"ner_m/ner_f/ner_mf": "Printed ratios not used (R05): recomputed from counts. Label 'NER' is a misnomer (all-age enrolment / age 6-11 population)."}
    rep.missingness = _missingness(clean, keep[1:])
    return clean, rep


def clean_fme_2016_17_enrolment(raw: RawDataset):
    rep = DatasetReport(raw.dataset_id, raw.sha256)
    df, _ = _standardise_states(raw, rep)
    cols = [c for c in df.columns if c != "state"]
    df = _num_frame(df, cols, rep)
    n = len(df)
    bad = df.loc[~_close(df.pub_pupils + df.priv_pupils, df.total_pupils), "state"].tolist()
    rep.check("R03", "public + private pupils = total pupils", n, bad)
    bad = df.loc[~_close(df.pub_female + df.priv_female, df.total_female), "state"].tolist()
    rep.check("R03", "public + private female = total female", n, bad)
    # printed % female (R05)
    pf = df.pub_female / df.pub_pupils * 100
    bad = df.loc[(pf - df.pub_pct_female).abs() > 1.5, "state"].tolist()
    rep.check("R05", "printed public % female equals computed (tol 1.5pp)", n, bad, WARNING, "recompute",
              detail="Printed values of 0% are impossible for these counts; percentages recomputed from counts")
    rep.transform("R05", "Percent-female columns recomputed from counts", n)
    # R04 duplicates
    dup_priv = _duplicate_vectors(df, ["priv_pupils", "priv_female"])
    rep.check("R04", "No two states share identical private-enrolment vectors", n, dup_priv, CRITICAL, "set_missing")
    for s in dup_priv:
        rep.flag(s, "DUPLICATE_ROW", CRITICAL, "Private enrolment identical to another state's row")
        df.loc[df.state == s, ["priv_pupils", "priv_female", "total_pupils", "total_female"]] = np.nan
    within = df.loc[(df.pub_pupils == df.priv_pupils) & (df.pub_female == df.priv_female) & df.pub_pupils.notna(), "state"].tolist()
    rep.check("R04", "Public enrolment differs from private enrolment within a state", n, within, CRITICAL, "set_missing")
    for s in within:
        rep.flag(s, "DUPLICATE_ROW", CRITICAL, "Public enrolment identical to private enrolment in the same row")
        df.loc[df.state == s, ["pub_pupils", "pub_female", "priv_pupils", "priv_female", "total_pupils", "total_female"]] = np.nan
    if dup_priv or within:
        rep.transform("R04", f"Enrolment set to missing for duplicated rows: {sorted(set(dup_priv) | set(within))}", len(set(dup_priv) | set(within)))
    # R06 plausibility: pupils per school
    pps = df.pub_pupils / df.pub_schools
    imp = df.loc[(pps < 20) | (pps > 3000), "state"].tolist()
    rep.check("R06", "average pupils per public school in [20, 3000]", int(pps.notna().sum()), imp, CRITICAL, "set_missing",
              detail="e.g. 77,869 public schools in Imo for 906,401 pupils")
    for s in imp:
        rep.flag(s, "IMPLAUSIBLE_SCHOOL_COUNT", CRITICAL, "Pupils per school outside [20, 3000]")
        df.loc[df.state == s, "pub_schools"] = np.nan
    pps_priv = df.priv_pupils / df.priv_schools
    imp2 = df.loc[(pps_priv < 20) | (pps_priv > 3000), "state"].tolist()
    rep.check("R06", "average pupils per private school in [20, 3000]", int(pps_priv.notna().sum()), imp2, WARNING, "flag")
    # recompute percentages
    df["female_share_total"] = df.total_female / df.total_pupils * 100
    df["private_share_enrol"] = df.priv_pupils / df.total_pupils * 100
    df["gpi_counts"] = df.total_female / (df.total_pupils - df.total_female)
    keep = ["state", "pub_schools", "pub_pupils", "pub_female", "priv_schools", "priv_pupils", "priv_female", "total_pupils", "total_female", "female_share_total", "private_share_enrol", "gpi_counts"]
    clean = df[keep]
    rep.usable_columns = keep[1:]
    rep.rejected_columns = {"pub_pct_female/priv_pct_female/total_pct_female": "Printed percentages contain impossible zeros and a National value of 1612%; recomputed (R05)."}
    rep.missingness = _missingness(clean, keep[1:])
    return clean, rep


def clean_fme_2016_17_teachers(raw: RawDataset):
    rep = DatasetReport(raw.dataset_id, raw.sha256)
    df, _ = _standardise_states(raw, rep)
    cols = [c for c in df.columns if c != "state"]
    df = _num_frame(df, cols, rep)
    n = len(df)
    bad_all = df.loc[~_close(df.t_m + df.t_f, df.t_mf), "state"].tolist()
    rep.check("R03", "male + female teachers = all teachers", n, bad_all, WARNING, "set_missing",
              detail="Gender components set to missing; totals retained when consistent with Table 2.11")
    bad_q = df.loc[~_close(df.q_m + df.q_f, df.q_mf), "state"].tolist()
    rep.check("R03", "male + female qualified = qualified total", n, bad_q)
    bad_le = df.loc[df.q_mf > df.t_mf, "state"].tolist()
    rep.check("R03", "qualified teachers <= all teachers", n, bad_le, CRITICAL)
    for s in bad_all:
        rep.flag(s, "IDENTITY_MISMATCH_TEACHER_GENDER", WARNING, "male+female teachers != total")
        df.loc[df.state == s, ["t_m", "t_f"]] = np.nan
    calc = df.q_mf / df.t_mf * 100
    bad = df.loc[(calc - df.pct_qualified).abs() > 2.0, "state"].tolist()
    rep.check("R05", "printed % qualified equals computed (tol 2pp)", n, bad, WARNING, "recompute",
              detail="e.g. Jigawa printed 0% for 6,642/12,408 qualified; recomputed from counts")
    rep.transform("R05", "% qualified recomputed from counts", n)
    dup = _duplicate_vectors(df, ["t_m", "t_f", "t_mf", "q_m", "q_f", "q_mf"])
    rep.check("R04", "No two states share identical teacher vectors", n, dup, CRITICAL, "set_missing",
              detail="Kogi's teacher row is identical to Imo's")
    for s in dup:
        rep.flag(s, "DUPLICATE_ROW", CRITICAL, "Teacher row identical to another state's row")
        df.loc[df.state == s, ["t_m", "t_f", "t_mf", "q_m", "q_f", "q_mf"]] = np.nan
    if dup:
        rep.transform("R04", f"Teacher counts set to missing for duplicated rows: {sorted(dup)}", len(dup))
    df["pct_qualified_calc"] = df.q_mf / df.t_mf * 100
    df["female_teacher_share"] = df.t_f / df.t_mf * 100
    keep = ["state", "t_m", "t_f", "t_mf", "q_m", "q_f", "q_mf", "pct_qualified_calc", "female_teacher_share"]
    clean = df[keep]
    rep.usable_columns = keep[1:]
    rep.rejected_columns = {"t_pct_f/pct_qualified/q_pct_f": "Printed percentages inconsistent with counts; recomputed (R05)."}
    rep.missingness = _missingness(clean, keep[1:])
    return clean, rep


def clean_fme_2016_17_ptr(raw: RawDataset):
    rep = DatasetReport(raw.dataset_id, raw.sha256)
    df, _ = _standardise_states(raw, rep)
    cols = [c for c in df.columns if c != "state"]
    df = _num_frame(df, cols, rep)
    n = len(df)
    bad = df.loc[(df.enrolment_mf / df.teachers_mf - df.ptr).abs() > 1.0, "state"].tolist()
    rep.check("R05", "printed PTR equals enrolment / teachers (tol 1)", n, bad)
    bad = df.loc[(df.enrolment_mf / df.qualified_teachers - df.pqtr).abs() > 1.0, "state"].tolist()
    rep.check("R05", "printed PQTR equals enrolment / qualified teachers (tol 1)", n, bad)
    df["ptr_calc"] = df.enrolment_mf / df.teachers_mf
    df["pqtr_calc"] = df.enrolment_mf / df.qualified_teachers
    keep = ["state", "enrolment_mf", "teachers_mf", "qualified_teachers", "ptr_calc", "pqtr_calc"]
    clean = df[keep].rename(columns={"enrolment_mf": "t211_enrolment", "teachers_mf": "t211_teachers", "qualified_teachers": "t211_qualified"})
    rep.usable_columns = list(clean.columns[1:])
    rep.rejected_columns = {"ptr/pqtr (printed)": "Used for reconciliation only; ratios recomputed."}
    rep.missingness = _missingness(clean, list(clean.columns[1:]))
    return clean, rep


def clean_fme_2016_17_key_indicators(raw: RawDataset):
    rep = DatasetReport(raw.dataset_id, raw.sha256)
    df, _ = _standardise_states(raw, rep)
    cols = [c for c in df.columns if c != "state"]
    df = _num_frame(df, cols, rep)
    n = len(df)
    for c in ("completion_m", "completion_f", "ger_m", "ger_f"):
        big = df.loc[df[c] > 150, "state"].tolist()
        rep.check("R06", f"{c} <= 150% (implausible above)", n, big, CRITICAL, "set_missing")
        for s in big:
            rep.flag(s, f"{c.upper()}_IMPLAUSIBLE", WARNING, f"{c}={float(df.loc[df.state == s, c].iloc[0]):.1f}")
        over100 = df.loc[(df[c] > 100) & (df[c] <= 150), "state"].tolist()
        rep.check("R06", f"{c} in (100,150] (possible only via over-age/repeat enrolment)", n, over100, INFO)
        df.loc[df[c] > 150, c] = np.nan
    calc = df.ger_f / df.ger_m
    bad = df.loc[(calc - df.gpi).abs() > 0.02, "state"].tolist()
    rep.check("R05", "printed GPI equals GER_f / GER_m (tol 0.02)", int(calc.notna().sum()), bad)
    # R08: PTR/PCR printed here vs Table 2.11 is checked in the cross-table stage; mark as rejected
    rep.rejected_columns = {
        "completion_m/completion_f": "Column pairing inferred from layout (source labels not extractable) and many values >100; descriptive use only with warning.",
        "ptr": "Rejected (R08): disagrees with Table 2.11 PTR for most states (e.g. Abia 7 vs 14).",
        "pcr": "Not used: no classroom data to validate.",
    }
    df["gpi_printed_check"] = calc
    keep = ["state", "ger_m", "ger_f", "gpi", "completion_m", "completion_f", "ptr"]
    clean = df[keep].rename(columns={"gpi": "gpi_printed", "ptr": "ptr_t212"})
    rep.usable_columns = ["ger_m", "ger_f", "gpi_printed"]
    rep.missingness = _missingness(clean, list(clean.columns[1:]))
    return clean, rep


def clean_mics_2021(raw: RawDataset):
    rep = DatasetReport(raw.dataset_id, raw.sha256)
    df, _ = _standardise_states(raw, rep)
    cols = ["oos_total", "oos_male", "oos_female", "oos_urban", "oos_rural", "fig38_map_label"]
    # the consistency test below must see the values as printed, so parse them ignoring '?' first
    u_all = df["oos_urban"].map(lambda v: parse_number(str(v).replace("?", ""))[0])
    r_all = df["oos_rural"].map(lambda v: parse_number(str(v).replace("?", ""))[0])
    df_raw_marked = df["oos_urban"].astype(str).str.contains(r"\?") | df["oos_rural"].astype(str).str.contains(r"\?")
    n_marked = int(df["oos_urban"].astype(str).str.contains(r"\?").sum() + df["oos_rural"].astype(str).str.contains(r"\?").sum())
    df = _num_frame(df, cols, rep)
    n = len(df)
    rng = df[["oos_male", "oos_female"]].agg(["min", "max"], axis=1)
    outside = df.loc[(df.oos_total < rng["min"] - 1) | (df.oos_total > rng["max"] + 1), "state"].tolist()
    rep.check("R03", "total out-of-school rate lies between male and female rates (+/-1pp rounding)", n, outside, WARNING)
    for s in outside:
        rep.flag(s, "TOTAL_OUTSIDE_SEX_RANGE", WARNING, "Total not between male and female values")
    diff = df.loc[(df.oos_total - df.fig38_map_label).abs() > 1, "state"].tolist()
    rep.check("R07", "table total equals Figure 38 map label (+/-1pp)", int(df.fig38_map_label.notna().sum()), diff, WARNING,
              detail="Sokoto: 53 (table) vs 51 (map)")
    for s in diff:
        rep.flag(s, "TABLE_VS_MAP_DISAGREE", WARNING, "Table value differs from Figure 38 label")
    # R08 urban/rural: uncertain markers + necessary condition test
    both = pd.concat([u_all, r_all], axis=1)
    lo = both.min(axis=1)
    hi = both.max(axis=1)
    ok = both.notna().all(axis=1)
    viol = df.loc[ok & ((df.oos_total < lo - 1) | (df.oos_total > hi + 1)), "state"].tolist()
    testable = int(ok.sum())
    share = len(viol) / testable if testable else 1
    rep.check("R08", "total lies between urban and rural rates (necessary condition)", testable, viol, WARNING, "flag",
              detail=f"{testable - len(viol)}/{testable} testable rows pass; passing is necessary but not sufficient for correct alignment")
    marked = df.loc[df_raw_marked, "state"].tolist()
    rep.check("R08", "urban/rural cells free of extraction uncertainty markers ('?')", len(df), marked, CRITICAL, "reject_column",
              detail=f"{n_marked} cells carry '?'; the extraction assigned urban values positionally to the first 35 states (Ekiti and Imo missing) and flagged Anambra as internally inconsistent")
    rep.rejected_columns = {
        "oos_urban/oos_rural": "Rejected for inference (R08): alignment of the urban/rural columns to states cannot be verified (extraction uncertainty markers, positional assignment, 2 states missing). State-level rural-urban inequality is therefore NOT supported; national rural-urban rates come from the separate dataset mics_2021_national.",
        "poorest/richest quintile": "Not retrievable (text extraction could not separate the columns). State-level wealth-quintile inequality is NOT supported; national wealth-quintile rates come from mics_2021_national.",
    }
    rep.usable_columns = ["oos_total", "oos_male", "oos_female"]
    df["oos_gender_gap"] = df.oos_female - df.oos_male
    clean = df[["state", "oos_total", "oos_male", "oos_female", "oos_gender_gap"]].rename(columns={"oos_total": "oos_total_2021", "oos_male": "oos_male_2021", "oos_female": "oos_female_2021", "oos_gender_gap": "oos_gender_gap_2021"})
    rep.missingness = _missingness(clean, list(clean.columns[1:]))
    return clean, rep


def clean_wb_poverty(raw: RawDataset):
    rep = DatasetReport(raw.dataset_id, raw.sha256)
    df, _ = _standardise_states(raw, rep)
    cols = ["pov_215", "pov_365", "pov_685", "year"]
    df = _num_frame(df, cols, rep)
    n = len(df)
    bad = df.loc[~((df.pov_215 <= df.pov_365) & (df.pov_365 <= df.pov_685)), "state"].tolist()
    rep.check("R06", "poverty headcount monotone in the poverty line (2.15 <= 3.65 <= 6.85)", n, bad, CRITICAL)
    rng = df.loc[(df[["pov_215", "pov_365", "pov_685"]] < 0).any(axis=1) | (df[["pov_215", "pov_365", "pov_685"]] > 100).any(axis=1), "state"].tolist()
    rep.check("R06", "poverty rates within [0, 100]", n, rng, CRITICAL)
    ref = set(states_reference()["state"])
    missing = sorted(ref - set(df.state))
    rep.check("R01", "all 37 states present", 37, missing, WARNING, "flag", detail=f"missing: {missing}")
    for s in missing:
        rep.flag(s, "POVERTY_MISSING", WARNING, "No poverty estimate in source")
    clean = df[["state", "pov_215", "pov_365", "pov_685"]]
    full = pd.DataFrame({"state": sorted(ref)}).merge(clean, on="state", how="left")
    rep.usable_columns = ["pov_215", "pov_365", "pov_685"]
    rep.missingness = _missingness(full, rep.usable_columns)
    rep.n_states = int(full.pov_215.notna().sum())
    return full, rep


def clean_wdi(raw: RawDataset):
    rep = DatasetReport(raw.dataset_id, raw.sha256)
    df = raw.frame.copy()
    rep.rows_in = len(df)
    df["year"] = df["year"].astype(int)
    df["value"] = df["value"].astype(float)
    dups = df[df.duplicated(["indicator_code", "year"], keep=False)]
    rep.check("R01", "no duplicate (indicator, year)", len(df), dups.indicator_code.unique().tolist(), CRITICAL)
    df["value_clean"] = df["value"]
    df["flag"] = ""
    # R09 outliers relative to neighbours (rolling median of adjacent observations)
    out_states = []
    for code, g in df.groupby("indicator_code"):
        g = g.sort_values("year")
        v = g["value"].to_numpy()
        for i in range(len(v)):
            nb = np.concatenate([v[max(0, i - 2):i], v[i + 1:i + 3]])
            if len(nb) >= 3 and np.median(nb) > 0:
                ratio = v[i] / np.median(nb)
                if ratio < 0.5 or ratio > 2.0:
                    idx = g.index[i]
                    df.loc[idx, "flag"] = "EXTREME_OUTLIER"
                    df.loc[idx, "value_clean"] = np.nan
                    out_states.append(f"{code}:{int(g.iloc[i]['year'])}")
    rep.check("R09", "no value deviates >2x from the median of its neighbours", len(df), out_states, CRITICAL, "set_missing",
              detail="e.g. gross primary enrolment 2015 = 25.6% vs 84% (2014) and 79% (2016)")
    rep.transform("R09", f"{len(out_states)} extreme outlier(s) set to missing in value_clean", len(out_states))
    cov = df.groupby("indicator_code")["year"].agg(["min", "max", "count"]).reset_index()
    rep.usable_columns = sorted(df.indicator_code.unique())
    rep.missingness = {r.indicator_code: round(100 * (1 - r["count"] / (r["max"] - r["min"] + 1)), 1) for _, r in cov.iterrows()}
    rep.n_states = 0
    return df, rep


def clean_mics_national(raw: RawDataset):
    """National out-of-school rates by sex / area / wealth quintile (MICS6 2021, Table 3)."""
    rep = DatasetReport(raw.dataset_id, raw.sha256)
    df = raw.frame.copy()
    rep.rows_in = len(df)
    rep.rows_state = 0
    cols = ["oos_primary", "oos_lower_secondary", "oos_upper_secondary"]
    for c in cols:
        df[c] = df[c].map(lambda v: parse_number(v)[0])
    dup = df[df.duplicated(["group_type", "group"], keep=False)]
    rep.check("R01", "no duplicate (group_type, group)", len(df), dup.group.tolist(), CRITICAL)
    bad = df.loc[~df[cols].apply(lambda s: s.between(0, 100)).all(axis=1), "group"].tolist()
    rep.check("R06", "rates within 0-100%", len(df), bad, CRITICAL, "set_missing")
    tot = df[df.group_type == "total"].iloc[0]
    for gt in ("sex", "area"):
        g = df[df.group_type == gt]
        fails = [c for c in cols if not (g[c].min() - 1 <= tot[c] <= g[c].max() + 1)]
        rep.check("R03", f"total lies between {gt} sub-group rates (+/-1pp rounding)", len(cols), fails, WARNING)
    w = df[df.group_type == "wealth"].set_index("group").loc[["Poorest", "Second", "Middle", "Fourth", "Richest"]]
    nonmono = [c for c in cols if (w[c].diff().dropna() > 0).any()]
    rep.check("R07", "out-of-school rate non-increasing with wealth quintile", len(cols), nonmono, WARNING,
              detail="Upper-secondary Richest (21) > Fourth (18) as printed; retained and flagged, not altered")
    qmean = w[cols].mean()
    far = [c for c in cols if abs(qmean[c] - tot[c]) > 3]
    rep.check("R07", "mean of equal-sized quintiles within 3pp of the total", len(cols), far, WARNING)
    rep.usable_columns = cols
    rep.rejected_columns = {}
    rep.missingness = {c: float(df[c].isna().mean() * 100) for c in cols}
    rep.n_states = 0
    return df, rep


def clean_capitals(raw: RawDataset):
    rep = DatasetReport(raw.dataset_id, raw.sha256)
    df, _ = _standardise_states(raw, rep)
    df = _num_frame(df, ["lat", "lon"], rep)
    ref = states_reference()[["state", "lat", "lon"]].rename(columns={"lat": "lat_ref", "lon": "lon_ref"})
    m = df.merge(ref, on="state", how="outer")
    m["d"] = np.maximum((m.lat - m.lat_ref).abs(), (m.lon - m.lon_ref).abs())
    bad = m.loc[m.d > 0.3, "state"].tolist()
    rep.check("R08", "coordinates agree with independently entered capital coordinates (<=0.3 deg)", int(m.d.notna().sum()), bad, CRITICAL, "reject_column")
    rep.rejected_columns = {"lat/lon": f"Rejected: {len(bad)} of {int(m.d.notna().sum())} coordinates differ by >0.3 degrees from the independent values."}
    rep.usable_columns = []
    return df, rep


CLEANERS = {
    "fme_2015_16_oos": clean_fme_2015_16,
    "fme_2016_17_enrolment": clean_fme_2016_17_enrolment,
    "fme_2016_17_teachers": clean_fme_2016_17_teachers,
    "fme_2016_17_ptr": clean_fme_2016_17_ptr,
    "fme_2016_17_key_indicators": clean_fme_2016_17_key_indicators,
    "mics_2021_oos": clean_mics_2021,
    "mics_2021_national": clean_mics_national,
    "wb_poverty_2018": clean_wb_poverty,
    "wdi_national": clean_wdi,
    "gh_capitals": clean_capitals,
}


# ----------------------------------------------------------------------------------------
# Readiness gate (plan section 5.2)
# ----------------------------------------------------------------------------------------
ROLE = {
    "fme_2015_16_oos": ("Outcome (access) - secondary; baseline", "state-year 2015/16"),
    "fme_2016_17_enrolment": ("Enrolment; private share; gender parity", "state-year 2016/17"),
    "fme_2016_17_teachers": ("Treatment components (qualified teachers)", "state-year 2016/17"),
    "fme_2016_17_ptr": ("Reconciliation of ratios", "state-year 2016/17"),
    "fme_2016_17_key_indicators": ("Descriptive: GER/GPI", "state-year 2016/17"),
    "mics_2021_oos": ("PRIMARY OUTCOME: primary out-of-school rate", "state-year 2020/21"),
    "mics_2021_national": ("Descriptive: national inequality by wealth, area, sex", "national subgroup 2020/21"),
    "wb_poverty_2018": ("Confounder / subgroup (poverty)", "state 2018"),
    "wdi_national": ("National trends (context)", "country-year"),
    "gh_capitals": ("Map coordinates (cross-check only)", "state"),
}


def assess_readiness(rep: DatasetReport, n_expected_states=37):
    """Apply the seven readiness questions of plan 5.2 and assign a status."""
    crit_states = {s for s, fl in rep.flags.items() if any(f["severity"] == CRITICAL for f in fl)}
    crit_checks = [c for c in rep.checks if c["severity"] == CRITICAL and c["n_failed"] > 0]
    rejected_cols = rep.rejected_columns
    reasons = []
    miss = max(rep.missingness.values()) if rep.missingness else 0.0
    is_national = rep.dataset_id in ("wdi_national", "mics_2021_national")
    share_crit = len(crit_states) / max(rep.n_states, 1) if not is_national else 0
    status = "Approved"
    if rep.dataset_id == "gh_capitals":
        status = "Rejected"
        reasons.append("Coordinates fail the independent cross-check; not used.")
    else:
        if crit_states:
            status = "Approved with limitations"
            reasons.append(f"{len(crit_states)} state row(s) carry critical integrity flags ({share_crit:.0%}) and are set to missing: {sorted(crit_states)}")
        if any(c["action"] == "reject_column" for c in crit_checks):
            status = "Approved with limitations"
            reasons.append("Some columns rejected: " + "; ".join(rejected_cols.keys()))
        if rep.dataset_id == "wdi_national":
            status = "Approved with limitations"
            reasons.append("National only (no subnational detail); sparse years; three requested indicators could not be retrieved; 2015 gross enrolment extreme outlier set to missing.")
        if rep.dataset_id == "mics_2021_national":
            status = "Approved with limitations"
            reasons.append("National subgroup rates only (rounded to whole %, no confidence intervals, no survey microdata); cannot be linked to states. Supports descriptive inequality by wealth, area and sex only.")
        if rep.dataset_id == "mics_2021_oos":
            reasons.append("Retrieved via text extraction of a PDF with scrambled tables: only total/male/female columns are aligned; no confidence intervals.")
        if rep.dataset_id == "wb_poverty_2018":
            reasons.append("Secondary compilation; Borno missing.")
        if rep.dataset_id.startswith("fme_"):
            status = "Approved with limitations"
            reasons.append("Administrative census data with documented transcription/reporting errors; population denominators are projections.")
        if miss > 10 and status == "Approved":
            status = "Approved with limitations"
            reasons.append(f"Missingness up to {miss}%")
        if share_crit > 0.4:
            status = "Rejected"
            reasons.append("More than 40% of rows fail critical checks")
    role, unit = ROLE.get(rep.dataset_id, ("", ""))
    return dict(
        status=status, reasons=reasons, role=role, unit_of_analysis=unit,
        file_available=True, n_observations=rep.rows_state or rep.rows_in, n_states=rep.n_states,
        max_missing_pct=miss, critical_state_count=len(crit_states),
        definitions_consistent="Within a table yes; across Digest tables/years and between sources NO (see reconciliation checks)" if not is_national else "Yes (single table / WDI definitions); WDI series breaks possible",
        variables_relevant=role,
        linkable="Yes on canonical state name (state-level only; no unit-level linkage claimed)" if not is_national else "National context only; cannot be linked to states",
        licence_ok="Licence not stated - research use with attribution" if rep.dataset_id != "wdi_national" else "CC BY 4.0",
    )


# ----------------------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------------------
def robust_z(x: pd.Series, log=True) -> pd.Series:
    v = np.log(x) if log else x
    med = v.median()
    mad = (v - med).abs().median() * 1.4826
    return (v - med) / mad if mad else v * 0


def build_analytic(cleaned: dict[str, pd.DataFrame], reports: dict[str, DatasetReport]) -> tuple[pd.DataFrame, dict]:
    """Merge the cleaned datasets into the state-level analytical dataset and apply cross-dataset rules.

    Inclusion criteria for the primary causal sample (documented, plan 5.3 step 10):
      1. valid treatment PQTR = public pupils / qualified public teachers (both present, no critical flag);
      2. valid primary outcome (MICS 2021 total out-of-school rate);
      3. valid confounder (poverty 2018, $2.15/day);
      4. no critical integrity flag on any variable used.
    """
    ref = states_reference().rename(columns={"lat": "lat", "lon": "lon"})
    A = ref.copy()
    for k in ("fme_2015_16_oos", "fme_2016_17_enrolment", "fme_2016_17_teachers", "fme_2016_17_ptr", "fme_2016_17_key_indicators", "mics_2021_oos", "wb_poverty_2018"):
        A = A.merge(cleaned[k], on="state", how="left")
    A["region"] = A["zone"].map(lambda z: "North" if z in ("NC", "NE", "NW") else "South")
    A["pqtr"] = A["pub_pupils"] / A["q_mf"]
    A["ptr"] = A["pub_pupils"] / A["t_mf"]
    A["log_pqtr"] = np.log(A["pqtr"])
    A["enrol_ratio_2016"] = A["total_pupils"] / A["pop6_11_2015"] * 100
    cross = []
    # ---- cross-dataset rules --------------------------------------------------------------
    flags: dict[str, list] = {}

    def add(state, code, sev, detail=""):
        flags.setdefault(state, []).append(dict(code=code, severity=sev, detail=detail))

    # inherit per-dataset flags
    for rep in reports.values():
        for st, fl in rep.flags.items():
            for f in fl:
                add(st, f["code"], f["severity"], f"[{rep.dataset_id}] {f['detail']}")
    # R06 implausible enrolment ratio
    imp = A.loc[A.enrol_ratio_2016 > 150, "state"].tolist()
    cross.append(dict(rule="R06", description="2016/17 enrolment / age 6-11 population (2015/16 projection) <= 150%", n_checked=int(A.enrol_ratio_2016.notna().sum()), n_failed=len(imp), states=imp, severity=CRITICAL, action="set_missing"))
    for s in imp:
        add(s, "IMPLAUSIBLE_ENROLMENT_RATIO", CRITICAL, f"{float(A.loc[A.state == s, 'enrol_ratio_2016'].iloc[0]):.0f}% of the age 6-11 population")
        A.loc[A.state == s, ["pub_pupils", "pqtr", "ptr", "log_pqtr", "total_pupils", "enrol_ratio_2016"]] = np.nan
    # R07 reconciliation of Table 2.11 against 2.8 / 2.10
    t = cleaned["fme_2016_17_ptr"].set_index("state")
    mism_enrol = [s for s in A.state if s in t.index and pd.notna(t.loc[s, "t211_enrolment"]) and pd.notna(A.set_index("state").loc[s, "pub_pupils"]) and abs(t.loc[s, "t211_enrolment"] - A.set_index("state").loc[s, "pub_pupils"]) > 1]
    cross.append(dict(rule="R07", description="Table 2.11 enrolment equals Table 2.8 public pupils", n_checked=37, n_failed=len(mism_enrol), states=mism_enrol, severity=WARNING, action="flag"))
    mism_teach = [s for s in A.state if s in t.index and pd.notna(t.loc[s, "t211_teachers"]) and pd.notna(A.set_index("state").loc[s, "t_mf"]) and abs(t.loc[s, "t211_teachers"] - A.set_index("state").loc[s, "t_mf"]) > 1]
    cross.append(dict(rule="R07", description="Table 2.11 teachers equal Table 2.10 total teachers", n_checked=37, n_failed=len(mism_teach), states=mism_teach, severity=WARNING, action="flag"))
    # R07 cross-year reconciliation 2015/16 vs 2016/17 total enrolment
    ratio = A["total_pupils"] / A["enrol_2015"]
    cy = A.loc[(ratio < 0.67) | (ratio > 1.5), "state"].tolist()
    cross.append(dict(rule="R07", description="Total enrolment 2016/17 within [0.67, 1.5] x enrolment 2015/16", n_checked=int(ratio.notna().sum()), n_failed=len(cy), states=cy, severity=WARNING, action="flag",
                      detail="Large year-on-year swings point to reporting error in at least one year"))
    for s in cy:
        add(s, "CROSS_YEAR_ENROLMENT_INCONSISTENT", WARNING, f"2016/17 / 2015/16 = {float(ratio[A.state == s].iloc[0]):.2f}")
    # R08 Table 2.12 printed PTR vs Table 2.11 recomputed PTR
    mm = [r.state for r in A.itertuples() if pd.notna(r.ptr_t212) and pd.notna(r.ptr_calc) and abs(r.ptr_t212 - r.ptr_calc) > 2]
    n_t = int((A.ptr_t212.notna() & A.ptr_calc.notna()).sum())
    cross.append(dict(rule="R08", description="Table 2.12 printed PTR agrees with Table 2.11 PTR (tol 2)", n_checked=n_t, n_failed=len(mm), states=mm, severity=CRITICAL, action="reject_column",
                      detail=f"{len(mm)/max(n_t,1):.0%} disagree -> the Table 2.12 PTR column is rejected"))
    # R09 outliers in treatment
    z = robust_z(A["pqtr"])
    A["pqtr_robust_z"] = z
    out = A.loc[z.abs() > 3.5, "state"].tolist()
    cross.append(dict(rule="R09", description="PQTR robust |z| <= 3.5 (log scale)", n_checked=int(A.pqtr.notna().sum()), n_failed=len(out), states=out, severity=WARNING, action="flag"))
    for s in out:
        add(s, "OUTLIER_PQTR", WARNING, f"robust z={float(z[A.state == s].iloc[0]):.1f}")
    # Convergent validity (informational): MICS OOS vs enrolment ratio 2015/16
    # ---- inclusion criteria ------------------------------------------------------------------
    def crit(s):
        return any(f["severity"] == CRITICAL for f in flags.get(s, []))

    need = ["pqtr", "oos_total_2021", "pov_215"]
    A["has_complete_vars"] = A[need].notna().all(axis=1) & (A["pqtr"] > 0)
    A["critical_flag"] = A["state"].map(crit)
    A["in_primary_sample"] = A["has_complete_vars"]  # critical flags already set affected variables to missing
    A["exclusion_reason"] = ""
    for i, r in A.iterrows():
        if r["in_primary_sample"]:
            continue
        why = []
        if pd.isna(r["pqtr"]):
            why.append("treatment (PQTR) missing: " + ", ".join(sorted({f["code"] for f in flags.get(r["state"], []) if f["severity"] == CRITICAL})))
        if pd.isna(r["oos_total_2021"]):
            why.append("outcome missing")
        if pd.isna(r["pov_215"]):
            why.append("poverty missing")
        A.at[i, "exclusion_reason"] = "; ".join(why)
    A["flags"] = A["state"].map(lambda s: "; ".join(sorted({f["code"] for f in flags.get(s, [])})))
    A["n_critical_flags"] = A["state"].map(lambda s: len({f["code"] for f in flags.get(s, []) if f["severity"] == CRITICAL}))
    info = dict(
        cross_checks=cross,
        flags=flags,
        n_states=int(len(A)),
        n_primary_sample=int(A["in_primary_sample"].sum()),
        excluded=A.loc[~A.in_primary_sample, ["state", "exclusion_reason"]].to_dict("records"),
        inclusion_criteria=[
            "Treatment PQTR (public pupils / qualified public teachers, 2016/17) available and not flagged critical",
            "Primary outcome (MICS 2021 total primary out-of-school rate) available",
            "Confounder poverty headcount at $2.15/day (2018) available",
            "No critical integrity flag on a variable used (such values are set to missing by rules R04-R06)",
        ],
    )
    return A, info


def run_cleaning(write: bool = True):
    """Run the full pipeline. Returns (analytic_df, national_df, reports, info)."""
    cleaned, reports = {}, {}
    for did, fn in CLEANERS.items():
        raw = load_raw(did)
        df, rep = fn(raw)
        rep.readiness = assess_readiness(rep)
        cleaned[did], reports[did] = df, rep
    analytic, info = build_analytic(cleaned, reports)
    national = cleaned["wdi_national"]
    if write:
        INTERIM.mkdir(parents=True, exist_ok=True)
        PROCESSED.mkdir(parents=True, exist_ok=True)
        for did, df in cleaned.items():
            df.to_parquet(INTERIM / f"{did}_clean.parquet", index=False)
        analytic.to_parquet(PROCESSED / "state_analytic.parquet", index=False)
        national.to_parquet(PROCESSED / "national_series.parquet", index=False)
        cleaned["mics_2021_national"].to_parquet(PROCESSED / "national_groups.parquet", index=False)
        payload = dict(
            rules=RULES,
            datasets={k: v.to_dict() for k, v in reports.items()},
            cross_checks=info["cross_checks"],
            analytic=dict(n_states=info["n_states"], n_primary_sample=info["n_primary_sample"], excluded=info["excluded"], inclusion_criteria=info["inclusion_criteria"]),
            flags=info["flags"],
            analytic_sha256=sha256_text(analytic.to_csv(index=False)),
        )
        (PROCESSED / "quality_report.json").write_text(stable_json(payload))
    return analytic, national, reports, info


def load_analytic() -> pd.DataFrame:
    p = PROCESSED / "state_analytic.parquet"
    if not p.exists():
        run_cleaning(write=True)
    return pd.read_parquet(p)


if __name__ == "__main__":  # pragma: no cover
    a, n, reps, info = run_cleaning()
    print("primary sample:", info["n_primary_sample"], "of", info["n_states"])
    for e in info["excluded"]:
        print("  excluded:", e)
