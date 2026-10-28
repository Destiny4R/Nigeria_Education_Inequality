#!/usr/bin/env python
"""Restore a backup made by scripts/backup.py into a target directory/database and VERIFY it.

  python scripts/restore.py BACKUP_DIR [--target DIR]

SQLite : copies database.sqlite3 to TARGET/db.sqlite3.
MySQL  : pipes database.sql into the database named by DB_NAME (the database must exist and be empty; password via MYSQL_PWD).
Files are extracted under TARGET.  Verification: every checksum in MANIFEST.json must match, and for SQLite the main table row counts must match.
Exit status is non-zero if anything fails to verify.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from pathlib import Path


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("backup")
    ap.add_argument("--target", default=".")
    a = ap.parse_args(argv)
    b, target = Path(a.backup), Path(a.target)
    man = json.loads((b / "MANIFEST.json").read_text())
    bad = [n for n, h in man["files"].items() if sha256(b / n) != h]
    if bad:
        print("CHECKSUM MISMATCH:", bad, file=sys.stderr)
        return 2
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(b / "files.tar.gz") as t:
        t.extractall(target, filter="data")                      # 'data' filter refuses absolute paths, links and path traversal
    if man["db_engine"] == "mysql":
        env = {**os.environ, "MYSQL_PWD": os.environ.get("DB_PASSWORD", "")}
        with open(b / "database.sql", "rb") as fh:
            subprocess.run(["mysql", "-h", os.environ.get("DB_HOST", "127.0.0.1"), "-P", os.environ.get("DB_PORT", "3306"), "-u", os.environ["DB_USER"],
                            os.environ.get("DB_NAME", "eduineq")], env=env, stdin=fh, check=True)
    else:
        shutil.copy2(b / "database.sqlite3", target / "db.sqlite3")
        con = sqlite3.connect(target / "db.sqlite3")
        try:
            for name, n in man.get("table_counts", {}).items():
                got = con.execute(f'select count(*) from "{name}"').fetchone()[0]
                if got != n:
                    print(f"ROW COUNT MISMATCH {name}: backup {n} restored {got}", file=sys.stderr)
                    return 3
        finally:
            con.close()
    print(f"Restored and verified: {len(man['files'])} files checksummed" + (f", {len(man.get('table_counts', {}))} tables compared" if man.get("table_counts") else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
