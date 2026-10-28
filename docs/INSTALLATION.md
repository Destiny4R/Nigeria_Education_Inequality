# Installation guide

## Requirements
* Linux, macOS or Windows with Python 3.12 or newer (developed on 3.13).
* About 2 GB of free memory for the causal analysis (DoWhy, EconML, SHAP) and about 1 GB of disk.
* No internet is needed at run time: Bootstrap and Plotly are vendored in `portal/static/portal/vendor/`.

## Steps
1. Create an environment and install the pinned packages:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt            # runtime
   pip install -r requirements-dev.txt        # tests and Word report builder (optional)
   ```
2. Configure (development): `export DJANGO_DEBUG=1`. A development secret key is then supplied automatically. For anything else copy `.env.example` to `.env`, set `DJANGO_SECRET_KEY`, and load it into the environment. The server refuses to start in production mode without a secret key.
3. Database: SQLite is the default (`db.sqlite3`). For MySQL set `DB_ENGINE=mysql`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`; install `mysqlclient` (`pip install -r requirements-production.txt`; needs the MySQL client headers) or rely on the PyMySQL fallback.
4. Create the schema and load the evidence base:
   ```bash
   python manage.py migrate
   python manage.py import_datasets
   python manage.py run_standard_analyses
   ```
5. Start: `python manage.py runserver` (development) or Gunicorn behind Nginx (see `DEPLOYMENT.md`).
6. Verify: `python -m pytest` (164 tests, about 3 minutes) and `python manage.py verify_reproducibility`.

## Troubleshooting
* *Pages say "no analysis available yet"*: step 4 has not been run on this database.
* *`DJANGO_SECRET_KEY must be set`*: production mode needs a key; use `DJANGO_DEBUG=1` for development.
* *Causal run times out*: raise `ANALYSIS_TIMEOUT_SECONDS`; it normally takes about one minute.
