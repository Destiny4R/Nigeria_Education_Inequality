"""Project package.

MySQL driver: production should install ``mysqlclient`` (see requirements-production.txt).  Where it cannot be compiled
(no MySQL client headers), the pure-Python PyMySQL driver is used through its MySQLdb-compatible shim."""
import os

if os.environ.get("DB_ENGINE", "").strip().lower() == "mysql":
    try:
        import MySQLdb  # noqa: F401
    except ImportError:
        import pymysql

        pymysql.version_info = (2, 2, 1, "final", 0)     # satisfy Django's minimum-version check for the shim
        pymysql.install_as_MySQLdb()
