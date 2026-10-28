# Administrator guide

The system has no user accounts, so "administration" means operating the server. Everything below is done from the command line on the host.

## Routine tasks
| Task | Command |
|---|---|
| Refresh data after changing raw files or the register | `python manage.py import_datasets` |
| Recompute the standard analyses | `python manage.py run_standard_analyses` (idempotent: identical configuration and data reuse the stored run) |
| Prove results still reproduce from raw data | `python manage.py verify_reproducibility` |
| Back up | `python scripts/backup.py --dest /var/backups/eduineq` |
| Restore | `python scripts/restore.py /var/backups/eduineq/eduineq-backup-<stamp> --target /srv/eduineq` |
| Requirements cross-check | `python src/validation/requirements_check.py` |

## Settings (environment variables)
`DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DJANGO_BEHIND_HTTPS`, `DB_*`, `ANALYSIS_EXECUTION` (`sync` or `thread`), `ANALYSIS_TIMEOUT_SECONDS`, `ANALYSIS_MAX_RETRIES`, `THROTTLE_RUNS_PER_HOUR`, `MAX_SAVED_SCENARIOS`, `LOG_LEVEL`. The current non-secret configuration is visible on `/status/`.

## Monitoring and audit
* `/healthz` returns 200 when the application and database respond; point the uptime monitor at it.
* `/activity/` lists audited actions (analysis submitted, data downloaded, scenario saved). Client addresses are stored only as a salted 16-character hash; no personal data are kept.
* A run that fails is recorded with its error and is never marked successful; open it from `/reports/` and use Retry.

## Because there is no login
Anyone who can reach the site can run analyses and save scenarios. Protection is: CSRF tokens, per-client throttling (default 30 runs per hour), a cap on saved scenarios, strict input validation, no upload endpoint, no write access to the evidence base from the web. If a deployment needs to restrict access, do it at Nginx (IP allow-list or HTTP basic auth) rather than inside the application.
