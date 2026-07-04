"""`dsc_wire.py` (the retired `dsc_codec.py`'s replacement) building genuine Lua tables
directly. See its module docstring for why -- this just confirms it still works on every real
`.dsc` file in the repo, and round-trips."""

import lupa
import pytest

REAL_DSC_FILES = [
    "observer.dsc",
    "beacon.dsc",
    "beacon2.dsc",
    "formation-hold.dsc",
    "hexat_test.dsc",
    "HexIndexOf_test_1.dsc",
]


def _to_comparable(v):
    """genuine Lua table -> nested Python dict/list, purely for equality comparison in tests
    (production code never needs this -- see luaconv.py's deletion note in memory for why)."""
    if lupa.lua_type(v) == "table":
        keys = list(v.keys())
        int_keys = [k for k in keys if isinstance(k, int) and not isinstance(k, bool)]
        if (
            int_keys
            and len(int_keys) == len(keys)
            and sorted(int_keys) == list(range(1, len(int_keys) + 1))
        ):
            return [_to_comparable(v[i]) for i in range(1, len(int_keys) + 1)]
        return {k: _to_comparable(v[k]) for k in keys}
    return v


@pytest.mark.parametrize("fname", REAL_DSC_FILES)
def test_decode_real_file(engine, fname):
    s = open(fname).read().strip()
    type_char, table = engine.decode_dsc(s)
    assert type_char == "C"
    assert lupa.lua_type(table) == "table"
    assert table[1] is not None  # at least one instruction
    assert table["name"] is not None


@pytest.mark.parametrize("fname", REAL_DSC_FILES)
def test_roundtrip(engine, fname):
    s = open(fname).read().strip()
    type_char, table = engine.decode_dsc(s)
    encoded = engine.encode_dsc(type_char, table)
    type_char2, table2 = engine.decode_dsc(encoded)
    assert type_char2 == type_char
    assert _to_comparable(table2) == _to_comparable(table)


def test_hexat_test_dsc_shape(engine):
    """Spot-check the specific structure other tests rely on: two embedded dependencies,
    HexAt then HexIndexOf, matching behavior_format.md's `dependencies`/`call` documentation."""
    s = open("HexIndexOf_test_1.dsc").read().strip()
    _, prog = engine.decode_dsc(s)
    deps = prog["dependencies"]
    assert deps[1]["name"] == "HexAt"
    assert deps[2]["name"] == "HexIndexOf"
