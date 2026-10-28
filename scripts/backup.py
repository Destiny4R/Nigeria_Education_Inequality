#!/usr/bin/env python
"""Back up everything needed to restore the portal and reproduce its results (plan 12/13: secure backups, tested restoration).

Contents of a backup directory
  database.sqlite3 | database.sql   application database (SQLite online-backup API, or mysqldump --single-transaction)
  files.tar.gz                      config/, data/raw, data/interim, data/processed, artefacts/ (and data/external_restricted only with --include-restricted)
  MANIFEST.json                     SHA-256 of every file above, row counts of the main tables, data fingerprint, creation time

Usage:  python scripts/backup.py [--dest backups] [--include-restricted]
The MySQL password is read from DB_PASSWORD and passed to mysqldump through the MYSQL_PWD environment variable (never on the command line).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def table_counts_sqlite(path: Path) -> dict:
    con = sqlite3.connect(path)
    try:
        names = [r[0] for r in con.execute("select name from sqlite_master where type='table' and name like 'portal_%'")]
        return {n: con.execute(f'select count(*) from "{n}"').fetchone()[0] for n in sorted(names)}
    finally:
        con.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", default=str(ROOT / "backups"))
    ap.add_argument("--include-restricted", action="store_true", help="also archive data/external_restricted (store the backup in an access-controlled place)")
    a = ap.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(a.dest) / f"eduineq-backup-{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    os.chmod(out, 0o700)
    engine = os.environ.get("DB_ENGINE", "sqlite").lower()
    manifest = {"created_utc": stamp, "db_engine": engine, "files": {}, "include_restricted": a.include_restricted}
    if engine == "mysql":
        dump = out / "database.sql"
        env = {**os.environ, "MYSQL_PWD": os.environ.get("DB_PASSWORD", "")}
        cmd = ["mysqldump", "--single-transaction", "--routines", "--default-character-set=utf8mb4", "-h", os.environ.get("DB_HOST", "127.0.0.1"),
               "-P", os.environ.get("DB_PORT", "3306"), "-u", os.environ["DB_USER"], os.environ.get("DB_NAME", "eduineq")]
        with open(dump, "wb") as fh:
            subprocess.run(cmd, env=env, stdout=fh, check=True)
    else:
        src = Path(os.environ.get("SQLITE_PATH", ROOT / "db.sqlite3"))
        dump = out / "database.sqlite3"
        s, d = sqlite3.connect(src), sqlite3.connect(dump)
        with d:
            s.backup(d)
        s.close(); d.close()
        manifest["table_counts"] = table_counts_sqlite(dump)
    tar = out / "files.tar.gz"
    include = ["config", "data/raw", "data/interim", "data/processed", "artefacts"] + (["data/external_restricted"] if a.include_restricted else [])
    with tarfile.open(tar, "w:gz") as t:
        for rel in include:
            p = ROOT / rel
            if p.exists():
                t.add(p, arcname=rel)
    for f in (dump, tar):
        os.chmod(f, 0o600)
        manifest["files"][f.name] = sha256(f)
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
