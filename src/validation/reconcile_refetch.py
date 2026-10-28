"""Independent re-extraction check (plan 11.1 "source-to-cleaned-data reconciliation").

Compares the raw files held in data/raw/ cell by cell against a second, independently performed extraction of the same
published tables stored in data/raw/verification/refetch_<date>/.  Numbers are parsed (thousands separators removed) and compared
numerically; text is compared after trimming.

Limitation (recorded in the report): both extractions pass through the same web-text-extraction service, so this detects
transcription error, not errors present in the source PDF itself.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
RAW = ROOT / "data" / "raw"

# (existing raw file, refetched file, key column in each, [(existing col, refetch col), ...] or None = all numeric by position)
PAIRS = [
    ("nemis_2015_16_gross_net_enrolment.csv", "fme_table_2_15_gross_net_enrolment_primary_2015_16.csv", "Table 2.15 gross/net enrolment 2015/16"),
    ("fme_2015_16_table2_23_oos_by_state.csv", "fme_table_2_23_out_of_school_children_6_11_2015_16.csv", "Table 2.23 out-of-school children 2015/16"),
    ("nemis_2013_16_public_primary_teachers.csv", "fme_table_2_22_pupil_teacher_ratio_public_primary_2013_16.csv", "Table 2.22 pupil-teacher ratio 2013/14-2015/16"),
    ("nbs_poverty_2018_19.csv", "nbs_nlss_2018_19_poverty_headcount_by_state.csv", "NBS NLSS 2018/19 poverty headcount"),
]


def _num(x):
    if x is None:
        return None
    s = str(x).strip().replace(",", "").replace("%", "").lstrip("*")
    if s in ("", "NA", "nan", "?"):
        return None
    try:
        return float(s)
    except ValueError:
        return s


def _load(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df.iloc[:, 0] = df.iloc[:, 0].str.strip().str.lstrip("*")
    return df.set_index(df.columns[0])


def compare(existing: Path, refetch: Path) -> dict:
    a, b = _load(existing), _load(refetch)
    common_rows = [r for r in a.index if r in b.index]
    only_a = [r for r in a.index if r not in b.index]
    only_b = [r for r in b.index if r not in a.index]
    ncol = min(a.shape[1], b.shape[1])
    n_cells, diffs = 0, []
    for r in common_rows:
        for j in range(ncol):
            va, vb = _num(a.loc[r].iloc[j]), _num(b.loc[r].iloc[j])
            n_cells += 1
            same = (va == vb) or (isinstance(va, float) and isinstance(vb, float) and abs(va - vb) < 1e-9)
            if not same and isinstance(va, str) and isinstance(vb, str):        # an annotated missing marker, e.g. "Unavailable" vs "Unavailable, as ..."
                same = vb.startswith(va) or va.startswith(vb)
            if not same:
                diffs.append({"row": r, "column": a.columns[j], "existing": a.loc[r].iloc[j], "refetch": b.loc[r].iloc[j]})
    return {"rows_compared": len(common_rows), "cells_compared": n_cells, "n_differences": len(diffs), "differences": diffs[:20],
            "rows_only_in_existing": only_a, "rows_only_in_refetch": only_b}


def run(refetch_dir: Path | None = None) -> dict:
    refetch_dir = refetch_dir or max((RAW / "verification").glob("refetch_*"))
    out = {"refetch_dir": str(refetch_dir.relative_to(ROOT)), "tables": {}}
    for ex, rf, label in PAIRS:
        res = compare(RAW / ex, refetch_dir / rf)
        res["existing_file"], res["refetch_file"] = ex, rf
        out["tables"][label] = res
    out["total_cells"] = sum(t["cells_compared"] for t in out["tables"].values())
    out["total_differences"] = sum(t["n_differences"] for t in out["tables"].values())
    return out


if __name__ == "__main__":
    res = run()
    (RAW / "verification" / "reconcile_refetch_result.json").write_text(json.dumps(res, indent=1))
    for k, v in res["tables"].items():
        print(f"{k}: {v['cells_compared']} cells, {v['n_differences']} differences; only-existing={v['rows_only_in_existing']} only-refetch={v['rows_only_in_refetch']}")
        for d in v["differences"][:8]:
            print("   ", d)
    print("TOTAL", res["total_cells"], "cells,", res["total_differences"], "differences")
    sys.exit(1 if res["total_differences"] else 0)
