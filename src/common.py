"""Shared helpers: project paths, canonical state reference data, number parsing, checksums."""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
CONFIG = ROOT / "config"

# Aliases seen in the raw sources -> canonical names
_ALIASES = {
    "fct-abuja": "FCT", "fct abuja": "FCT", "abuja": "FCT", "federal capital territory": "FCT",
    "akwa-ibom": "Akwa Ibom", "cross-river": "Cross River", "nassarawa": "Nasarawa",
}


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_json(obj) -> str:
    """Deterministic JSON used for hashing configurations and results."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_json_default)


def round_floats(obj, sig: int = 10):
    """Recursively round every float to ``sig`` significant digits.

    Used before hashing numerical results: libraries such as DoWhy/statsmodels can differ in the last 1-2 bits of a float
    between processes (summation order), which is numerical noise, not a different result.  Ten significant digits is far
    finer than any reported precision and far coarser than that noise."""
    if isinstance(obj, dict):
        return {k: round_floats(v, sig) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [round_floats(v, sig) for v in obj]
    if isinstance(obj, (float, np.floating)):
        v = float(obj)
        return v if (v != v or v in (float("inf"), float("-inf")) or v == 0.0) else float(f"{v:.{sig - 1}e}")
    return obj


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        v = float(o)
        return None if np.isnan(v) else round(v, 10)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    return str(o)


@lru_cache(maxsize=1)
def states_reference() -> pd.DataFrame:
    """Canonical list of 36 states + FCT with zone, capital and coordinates."""
    return pd.read_csv(CONFIG / "states.csv", keep_default_na=False)   # "NA" is Nasarawa, not a missing value


def canonical_state(name) -> str | None:
    """Standardise a state label; returns None for National / unknown."""
    if name is None or (isinstance(name, float) and np.isnan(name)):
        return None
    s = str(name).strip().lstrip("*").strip()
    key = s.lower()
    if key in ("national", "nigeria", "total"):
        return None
    key = _ALIASES.get(key, key)
    for st in states_reference()["state"]:
        if st.lower() == key.lower():
            return st
    return None


_NUM = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def parse_number(value):
    """Parse numbers as printed in source tables.

    Returns (float|nan, marker) where marker is '' or one of 'uncertain' (value had a '?'),
    'blank'. Commas and % signs are stripped.
    """
    if value is None:
        return np.nan, "blank"
    if isinstance(value, (int, float, np.integer, np.floating)):
        return (float(value), "") if not pd.isna(value) else (np.nan, "blank")
    s = str(value).strip()
    if s == "":
        return np.nan, "blank"
    marker = "uncertain" if "?" in s else ""
    s2 = s.replace(",", "").replace("%", "").replace("?", "").replace("*", "").strip()
    # strip trailing annotations like "(map)" / "(uncertain)"
    s2 = re.sub(r"\(.*?\)", "", s2).strip()
    m = _NUM.fullmatch(s2)
    if not m:
        return np.nan, "unparseable"
    return float(s2), marker


def load_register() -> dict:
    with open(CONFIG / "source_register.json") as fh:
        return json.load(fh)


def zone_group(zone: str) -> str:
    """North (NC, NE, NW) vs South (SE, SS, SW) - a standard grouping of Nigeria's six zones."""
    return "North" if zone in ("NC", "NE", "NW") else "South"


def to_jsonable(obj):
    """Recursively convert numpy/pandas objects to plain JSON types; NaN/inf -> None (MySQL JSON rejects NaN)."""
    import math
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return to_jsonable(obj.to_dict("records"))
    if isinstance(obj, pd.Series):
        return to_jsonable(obj.to_dict())
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(obj, np.ndarray):
        return to_jsonable(obj.tolist())
    if obj is None or isinstance(obj, (str, int)):
        return obj
    if obj is pd.NaT:
        return None
    return str(obj)
