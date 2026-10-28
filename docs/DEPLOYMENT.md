# Deployment guide and operational checklist

## 1. Architecture
```
Users and browser
       |
       v
Nginx + HTTPS (deploy/nginx.conf)
       |  unix socket
       v
Gunicorn + Django (deploy/gunicorn.conf.py, systemd unit deploy/eduineq.service)
       |
       +--------------------+
       v                    v
 MySQL (application   Analysis worker threads + storage
 records, metadata)   (artefacts/ JSON with SHA-256, data/ files)
```
**Sizing / memory.** A causal run needs roughly 1 to 2 GB of memory and about one minute of CPU; simulations take seconds. Provision at least 4 GB RAM and 2 vCPUs, and keep `ANALYSIS_EXECUTION=thread` with 2 to 4 Gunicorn workers. If many concurrent users are expected, replace the thread worker with a queue (Celery and Redis); the service layer is already separated for this.

## 2. Checklist
1. Separate development, test and production configuration through environment variables (`.env.example`); production is the default (`DJANGO_DEBUG` off).
2. Install pinned packages: `pip install -r requirements-production.txt`.
3. Set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `DB_*`; keep the file outside the repository, mode 600.
4. Create the MySQL database (`utf8mb4`) and user; `python manage.py migrate`; then `import_datasets` and `run_standard_analyses`.
5. `python manage.py collectstatic`; install the Nginx site with a real certificate (Let's Encrypt) and set `DJANGO_BEHIND_HTTPS=1`.
6. Debug mode stays off.
7. Run `python manage.py check --deploy`. Only `security.W021` (HSTS preload) may remain: it is an irreversible opt-in that the domain owner should choose deliberately.
8. Enable the systemd unit; logs go to journald (`LOG_LEVEL`).
9. Monitor `/healthz`; alert on non-200 and on disk space.
10. Schedule `python scripts/backup.py` nightly; copy backups off the host.
11. **Test restoration** before go-live and quarterly: `python scripts/restore.py <backup> --target <scratch>` verifies every SHA-256 and table row count.
12. Run `pytest` against MySQL on the target server once (`DB_ENGINE=mysql`). This was not possible in the build sandbox, so MySQL operation is configured but unverified.

## 3. Backup and restore
`scripts/backup.py` writes the database (SQLite online backup or `mysqldump --single-transaction`), a tarball of config, raw, interim, processed and artefact files, and `MANIFEST.json` with checksums. `data/external_restricted` is archived only with `--include-restricted`; store such a backup in an access-controlled place.

## 4. Upgrades and rollback
Upgrade: back up; read the changelog of each pinned package; update `requirements.txt` in a test environment; run `pytest` and `verify_reproducibility`; deploy; run `migrate`; re-run `run_standard_analyses`; check `/healthz`. **Rollback:** stop the service, restore the previous release directory and the pre-upgrade backup with `scripts/restore.py`, restart, and confirm `/healthz` and `/status/`. Migrations are never edited after release; a schema rollback is a restore.

## 5. Dependency updates and security testing
Review pinned dependencies monthly and on any security advisory (`pip list --outdated`, `pip-audit`). After updates, run the full test suite, which includes security tests (headers, CSRF, method restrictions, path traversal, escaping, injection, throttling) and `check --deploy`.

## 6. Data retention and deletion
The system holds no personal data: only published aggregates and a salted hash of client addresses in the audit log. Retention: audit entries are kept 12 months, then deleted (`AuditLog.objects.filter(created_at__lt=...).delete()` from a management shell); failed runs older than 90 days may be deleted; backups are kept 90 days. Raw evidence files and dataset versions are retained for the life of the project to preserve reproducibility. A request to delete a saved scenario is honoured by deleting its `PolicyScenario` and run rows.

## 7. Incident response
1. Detect (monitor alert, log anomaly, report). 2. Contain: block the source at Nginx, or stop Gunicorn. 3. Assess: review `/activity/`, Nginx and journald logs; verify evidence integrity by re-hashing raw files (`pytest -k checksums`) and `verify_reproducibility`. 4. Recover: restore from the last good backup. 5. Rotate `DJANGO_SECRET_KEY` and database passwords if exposure is possible. 6. Record what happened and what changed. Because there is no login, abuse takes the form of excess load or scenario spam; the throttle and scenario cap are the first controls, and Nginx rate limiting the second.
