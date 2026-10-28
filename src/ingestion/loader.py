"""Ingestion: load unmodified raw files, validate schema and source metadata, record checksums.

The raw files are never modified. Every load returns the data exactly as stored (all values as
strings) together with provenance metadata (checksum, size, row count, source register entry).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd

from src.common import RAW, load_register, sha256_file


class SchemaError(ValueError):
    """Raised when a raw file does not match the expected schema."""


EXPECTED_COLUMNS: dict[str, list[str]] = {
    "fme_2015_16_oos": ["state", "enrol_m", "enrol_f", "enrol_mf", "pop_m", "pop_f", "pop_mf", "ner_m", "ner_f", "ner_mf", "out_of_school_mf"],
    "fme_2016_17_enrolment": ["state", "pub_schools", "pub_pupils", "pub_female", "pub_pct_female", "priv_schools", "priv_pupils", "priv_female", "priv_pct_female", "total_pupils", "total_female", "total_pct_female"],
    "fme_2016_17_teachers": ["state", "t_m", "t_f", "t_mf", "t_pct_f", "q_m", "q_f", "q_mf", "pct_qualified", "q_pct_f"],
    "fme_2016_17_ptr": ["state", "enrolment_mf", "teachers_mf", "ptr", "qualified_teachers", "pqtr"],
    "fme_2016_17_key_indicators": ["state", "completion_m", "completion_f", "ger_m", "ger_f", "gpi", "ptr", "pcr"],
    "mics_2021_oos": ["state", "oos_total", "oos_male", "oos_female", "oos_urban", "oos_rural", "fig38_map_label"],
    "mics_2021_national": ["group_type", "group", "oos_primary", "oos_lower_secondary", "oos_upper_secondary"],
    "wb_poverty_2018": ["state", "pov_215", "pov_365", "pov_685", "year", "source"],
    "wdi_national": ["indicator_code", "indicator_name", "year", "value"],
}
REQUIRED_SOURCE_FIELDS = ["url", "name", "access_date", "geographic_coverage", "licence", "limitations", "permitted_uses"]


@dataclass
class RawDataset:
    dataset_id: str
    frame: pd.DataFrame
    sha256: str
    size_bytes: int
    n_rows: int
    path: str
    meta: dict = field(default_factory=dict)


def dataset_entry(dataset_id: str) -> tuple[dict, dict]:
    reg = load_register()
    ds = next((d for d in reg["datasets"] if d["dataset_id"] == dataset_id), None)
    if ds is None:
        raise KeyError(f"Unknown dataset {dataset_id!r}")
    src = next(s for s in reg["sources"] if s["source_id"] == ds["source_id"])
    return ds, src


def validate_source_metadata(src: dict) -> list[str]:
    """Return a list of missing provenance fields (empty list = complete)."""
    return [f for f in REQUIRED_SOURCE_FIELDS if not src.get(f)]


def load_raw(dataset_id: str) -> RawDataset:
    ds, src = dataset_entry(dataset_id)
    path = RAW / ds["file"]
    if not path.exists():
        raise FileNotFoundError(path)
    missing_meta = validate_source_metadata(src)
    if missing_meta:
        raise SchemaError(f"Source {src['source_id']} lacks provenance fields: {missing_meta}")
    if path.suffix == ".geojson":
        with open(path) as fh:
            gj = json.load(fh)
        rows = []
        for f in gj["features"]:
            lon, lat = f["geometry"]["coordinates"]
            rows.append({"state": f["properties"]["state"], "capital": f["properties"]["capital"], "lon": str(lon), "lat": str(lat)})
        frame = pd.DataFrame(rows)
    else:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        expected = EXPECTED_COLUMNS[dataset_id]
        if list(frame.columns) != expected:
            raise SchemaError(f"{path.name}: columns {list(frame.columns)} != expected {expected}")
        if frame.empty:
            raise SchemaError(f"{path.name}: no rows")
    return RawDataset(
        dataset_id=dataset_id, frame=frame, sha256=sha256_file(path), size_bytes=path.stat().st_size,
        n_rows=len(frame), path=str(path.relative_to(path.parents[2])), meta={"dataset": ds, "source": src},
    )
