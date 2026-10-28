"""Shared helpers: state standardisation, number parsing, checksums, JSON conversion."""
import json

import numpy as np
import pandas as pd
import pytest

from src.common import canonical_state, parse_number, sha256_text, stable_json, states_reference, to_jsonable, zone_group


def test_reference_list_is_36_states_plus_fct():
    ref = states_reference()
    assert len(ref) == 37
    assert ref.state.is_unique
    assert "FCT" in set(ref.state)
    assert set(ref.zone) == {"NC", "NE", "NW", "SE", "SS", "SW"}
    assert ref.zone.value_counts().to_dict() == {"NW": 7, "NC": 7, "SS": 6, "SW": 6, "NE": 6, "SE": 5}


@pytest.mark.parametrize("raw,expected", [
    ("Akwa-Ibom", "Akwa Ibom"), ("cross-river", "Cross River"), ("Nassarawa", "Nasarawa"), ("FCT-Abuja", "FCT"),
    ("  Federal Capital Territory ", "FCT"), ("*Rivers", "Rivers"), ("LAGOS", "Lagos"),
])
def test_canonical_state_aliases(raw, expected):
    assert canonical_state(raw) == expected


@pytest.mark.parametrize("raw", ["National", "nigeria", "Total", "Atlantis", "", None, float("nan")])
def test_canonical_state_rejects_non_states(raw):
    assert canonical_state(raw) is None


@pytest.mark.parametrize("raw,val,marker", [
    ("1,234", 1234.0, ""), ("45.5%", 45.5, ""), ("12*", 12.0, ""), ("33?", 33.0, "uncertain"), ("7 (map)", 7.0, ""),
])
def test_parse_number(raw, val, marker):
    v, m = parse_number(raw)
    assert v == val and m == marker


def test_parse_number_blank_and_garbage():
    assert np.isnan(parse_number("")[0]) and parse_number("")[1] == "blank"
    assert np.isnan(parse_number("abc")[0]) and parse_number("abc")[1] == "unparseable"
    assert np.isnan(parse_number(None)[0])


def test_zone_group():
    assert zone_group("NW") == "North" and zone_group("SS") == "South"


def test_stable_json_is_order_independent():
    assert stable_json({"b": 1, "a": [1, 2]}) == stable_json({"a": [1, 2], "b": 1})
    assert sha256_text(stable_json({"x": 1})) == sha256_text('{"x":1}')


def test_to_jsonable_removes_nan_and_numpy():
    obj = {"a": np.float64("nan"), "b": np.int64(3), "c": np.array([1.0, np.inf]), "d": pd.DataFrame({"x": [1, 2]}), "e": (1, 2)}
    out = to_jsonable(obj)
    assert out == {"a": None, "b": 3, "c": [1.0, None], "d": [{"x": 1}, {"x": 2}], "e": [1, 2]}
    json.dumps(out, allow_nan=False)   # must be valid strict JSON (MySQL JSON columns reject NaN)


def test_round_floats_removes_last_bit_noise_but_keeps_real_differences():
    from src.common import round_floats, stable_json
    a = {"x": 4.064419237834969, "y": [0.2415204715320498, -3.9794561347699107], "z": 0.0, "s": "txt"}
    b = {"x": 4.064419237834958, "y": [0.24152047153205647, -3.9794561347699036], "z": 0.0, "s": "txt"}
    assert stable_json(round_floats(a)) == stable_json(round_floats(b))
    assert stable_json(round_floats({"x": 4.0644192})) != stable_json(round_floats({"x": 4.0644193}))


def test_nasarawa_code_NA_is_not_read_as_missing():
    """Regression: pandas parses the literal state code 'NA' as NaN unless keep_default_na=False."""
    from src.common import states_reference
    ref = states_reference()
    assert ref["state_code"].notna().all() and ref["state_code"].is_unique
    assert ref.loc[ref.state == "Nasarawa", "state_code"].iloc[0] == "NA"
