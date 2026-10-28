# Data import guide

Data enter the system **only** through the server-side pipeline; there is no browser upload because an open site with no login must not let visitors change the evidence base.

## Procedure
1. **Obtain the original file** from the publisher. Never edit it. If a table can only be read from a web page or PDF, transcribe it exactly as printed (keep printed errors; the cleaning rules handle them) and say so in `retrieval_method`.
2. **Save it unmodified** in `data/raw/`. Anything identifiable or restricted goes in `data/external_restricted/`, which Git ignores and which is never web-served.
3. **Register the source** in `config/source_register.json` under `sources`. Required fields: `source_id`, `name`, `publisher`, `url`, `publication_year`, `collection_period`, `access_date`, `geographic_coverage`, `licence`, `documentation`, `limitations`, `permitted_uses`. A missing field makes import fail with a provenance error.
4. **Register the dataset** under `datasets`: `dataset_id`, `file`, `source_id`, `unit_of_analysis`, `name`. Do not mix units: a state-level figure is never treated as a household measurement.
5. **Declare the schema** in `src/ingestion/loader.py::EXPECTED_COLUMNS` and write a cleaning function in `src/cleaning/pipeline.py` that standardises state names (`src.common.canonical_state`), converts numbers, applies rules and records every check in the dataset report.
6. **Run** `python manage.py import_datasets`. For each dataset it records a version with a SHA-256, a data-quality report (rows kept, set to missing, flagged, and why) and a readiness status.
7. **Read the readiness status.** `Approved`, `Approved with limitations` or `Rejected`. A rejected dataset is kept for the record but its columns never reach the analytic file. Gate 1: the causal engine refuses to run unless the primary-outcome dataset is approved.
8. **Re-run** `python manage.py run_standard_analyses` and `python manage.py verify_reproducibility`, then `python -m pytest`.

## Rules to keep
Harmonise indicators only when definitions are genuinely comparable (the 2015/16 net enrolment ratio and the 2021 out-of-school rate are not, and are not mixed). Never fill missing values with invented data; set invalid values to missing and document why. Record checksums; the test suite re-hashes every raw file.
