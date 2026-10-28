# Educational Inequality in Nigeria: a software engineering and causal AI approach

An open-access Django research portal that (1) gathers and documents education and poverty data for Nigeria's 36 states and the FCT, (2) measures educational inequality, (3) estimates, under explicit assumptions, the effect of one school-resource factor (pupils per qualified teacher) on primary out-of-school rates, and (4) simulates hypothetical policy scenarios against a baseline.

**There is no login, no user account and no role of any kind.** This is a project decision: `django.contrib.auth`, `admin` and `sessions` are not installed. The public site is read-only apart from running analyses and saving scenarios, which are CSRF-protected and throttled. There is no upload endpoint; data are imported by the operator on the server.

## What is in the box

| Path | Content |
|---|---|
| `eduineq/` | Django project (settings, URLs, WSGI) |
| `portal/` | The web application: models, views, templates, exports, plotting, services |
| `src/ingestion, cleaning, inequality, causal, simulation, validation` | The research pipeline, usable without Django |
| `data/raw/` | Original files as retrieved, plus `verification/` (independent re-downloads) |
| `data/interim/`, `data/processed/` | Cleaned datasets, the analytic file, quality report |
| `config/` | `source_register.json` (provenance of every source), `states.csv` |
| `tests/` | Unit, integration, security and analytical validation tests |
| `docs/` | Installation, administration, data import, user manual, deployment, reproducibility, data dictionary, requirements traceability |
| `reports/` | Research report (Word and PDF), requirements traceability JSON, test results |
| `deploy/`, `scripts/` | Nginx, Gunicorn, systemd, backup and restore |

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
export DJANGO_DEBUG=1
python manage.py migrate
python manage.py import_datasets          # validate, clean, document, register datasets
python manage.py run_standard_analyses    # inequality + causal + 3 scenarios (about 1 minute)
python manage.py runserver
```

Open http://127.0.0.1:8000/. Run the tests with `python -m pytest`, and the requirements cross-check with `python src/validation/requirements_check.py --junit reports/pytest_results.xml`.

## Headline findings (details in `reports/research_report.pdf`)

* Primary out-of-school rates (MICS6, 2021) range from 1% (Imo) to 65% (Kebbi); the North averages about 36% against about 6% in the South (gap 29.6 points, bootstrap interval 21.6 to 37.8).
* The adjusted causal estimate for a 10% cut in pupils per qualified teacher is -0.43 points (95% interval -1.36 to +0.51, n = 31 states): **inconclusive**. The unadjusted association is four times larger, mostly because of poverty and region.
* Scenario results are hypothetical illustrations that inherit that uncertainty; their intervals include zero.

## Known limitations

State-level data are published aggregates, not household or school records, so the study is ecological. Rural-urban and wealth gaps exist only at national level. MySQL is configured and documented but was not run against a live server in the build environment. See the report, section 8.
