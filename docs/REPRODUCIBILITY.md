# Reproducibility procedure

Goal: the same raw files and configuration yield the same results, byte for byte after rounding to 10 significant figures.

1. `pip install -r requirements.txt` (versions are pinned to those used for the published results).
2. `python manage.py import_datasets` re-validates every raw file against its recorded SHA-256, re-runs cleaning and records the analytic-file checksum.
3. `python manage.py run_standard_analyses` computes the standard inequality, causal and scenario runs. Each run stores the configuration hash, data fingerprint, software versions, seed and results hash.
4. `python manage.py verify_reproducibility` re-cleans from raw data, recomputes the inequality and causal results in a fresh computation and compares SHA-256 hashes; it fails loudly on any mismatch.
5. `python src/validation/independent_check.py` recomputes 14 headline numbers with separate code (pairwise Gini, an explicit HC3 sandwich estimator, SciPy Spearman, scenario arithmetic); all agree within tolerance (`reports/independent_check.json`).
6. `data/raw/verification/` holds independent re-downloads of the main tables; `src/validation/reconcile_refetch.py` compares them cell by cell (1,671 of 1,671 cells identical). Both retrievals use the same text-extraction route, so an error inside a source PDF would not be detected this way.
7. `notebooks/01_reproduce_key_results.ipynb` reproduces the key tables from the processed files.

Seeds are fixed (`20260101` for simulations); the causal pipeline rounds floating-point output so that last-bit noise does not alter hashes across processes (regression-tested).

The data dictionary (`docs/DATA_DICTIONARY.md`) is generated from `portal.views.DICTIONARY`, `config/source_register.json`, the analytic file and the database tables; regenerate it after any data change.
