"""Phase 4 of the BSF plan (see /home/johnfb/.claude/plans/moonlit-nibbling-sonnet.md): a real,
full exercise of the dcs <-> BSF text pipeline -- decode a real behavior, read it as BSF text,
make a deliberate edit, recompile, re-encode, and confirm the edit took effect and nothing else
broke. This is the concrete proof point for the actual deliverable ("try a full end to end
exercise" in the user's own words), not just a unit test of one direction.

Scope boundary, stated plainly: this proves the pipeline round-trips and produces a valid,
re-decodable .dcs string. Actually pasting the result into the live game is a follow-up step for
whoever wants to do that, not exercised here."""

import math
from pathlib import Path

from desynced_toolkit import Interpreter
from desynced_toolkit.bsf import bsf_to_dcs, dcs_to_bsf
from desynced_toolkit.bsf.compile import compile_behavior
from desynced_toolkit.bsf.decompile import decompile_dcs
from desynced_toolkit.lua_util import to_py

DATA_DIR = Path(__file__).parent / "data"

D_HALF = 5
ORIGIN = (0, 0)
SCALE = 10000
K = 8660


def _ref_hexat(R, T, d_half=D_HALF, origin=ORIGIN):
    """Same closed-form reference as test_hex_expansion.py -- reused here (not re-derived) to
    confirm the embedded HexAt sub-behavior still computes correctly after the top-level
    behavior around it was edited."""
    d = d_half * 2
    if R == 0:
        return origin
    k = math.floor(T / R)
    t = T - k * R
    dirs = {0: (t - R, R), 1: (t, R - t), 2: (R, -t), 3: (R - t, -R), 4: (-t, t - R), 5: (-R, t)}
    q, r = dirs[k]
    x = origin[0] + d * q + d_half * r
    ynum = origin[1] * SCALE + d * r * K
    y = math.floor((2 * ynum + SCALE) // (2 * SCALE))
    return (x, y)


def _strip_layout(v):
    if isinstance(v, dict):
        return {k: _strip_layout(x) for k, x in v.items() if k not in ("nx", "ny", "cmt")}
    if isinstance(v, list):
        return [_strip_layout(x) for x in v]
    return v


def test_end_to_end_reorder_edit_on_hexat_test(engine):
    raw = (DATA_DIR / "hexat_test.dcs").read_text().strip()
    text = dcs_to_bsf(engine, raw)

    # A real, deliberate edit -- swap the two debug_print lines that print R and T, wired purely
    # by implicit fallthrough. This specifically exercises the reorder/fallthrough-recompute
    # machinery (see test_bsf_text_roundtrip.py's dedicated reorder tests) as part of a real
    # decode->edit->recompile loop, not just a bare literal-value tweak.
    original_pair = "n7: debug_print(Print Value=R)\nn8: debug_print(Print Value=T)"
    assert original_pair in text
    edited_text = text.replace(
        original_pair,
        "n8: debug_print(Print Value=T)\nn7: debug_print(Print Value=R)",
    )
    assert edited_text != text

    new_dcs = bsf_to_dcs(engine, edited_text)
    _, orig_table = engine.decode_dcs(raw)
    _, new_table = engine.decode_dcs(new_dcs)
    orig_py = _strip_layout(to_py(orig_table))
    new_py = _strip_layout(to_py(new_table))

    # The edit's actual effect: wire position 7 (right after n6's unlock) now prints T instead
    # of R, and position 8 now prints R instead of T -- the implicit fallthrough correctly
    # followed the reorder, rewiring n6->n8->n7->n9. R/T are declared params (slots 1/2), so
    # `Print Value=R`/`=T` compile to the bare param-slot ints 1/2, not string literals.
    assert orig_py[7]["op"] == "debug_print" and orig_py[7][1] == 1  # R
    assert orig_py[8]["op"] == "debug_print" and orig_py[8][1] == 2  # T
    assert new_py[7]["op"] == "debug_print" and new_py[7][1] == 2  # T
    assert new_py[8]["op"] == "debug_print" and new_py[8][1] == 1  # R

    # Nothing else changed: every other instruction is untouched, and the embedded HexAt
    # sub-behavior -- never touched by this edit -- is byte-identical.
    assert orig_py["dependencies"] == new_py["dependencies"]
    other_orig = {k: v for k, v in orig_py.items() if k not in (7, 8)}
    other_new = {k: v for k, v in new_py.items() if k not in (7, 8)}
    assert other_orig == other_new

    # And the embedded HexAt sub-behavior still runs correctly through the real interpreter
    # against the closed-form reference (test_hex_expansion.py's own oracle) -- a spot-check,
    # not the full 217-case sweep that test already covers, confirming the edit to the
    # top-level harness didn't corrupt anything reachable through the recompiled dependency.
    b = decompile_dcs(engine, new_dcs)
    recompiled = compile_behavior(engine, b)
    hexat = recompiled["dependencies"][1]
    for R, T in [(0, 0), (3, 5), (5, 29), (8, 40)]:
        interp = Interpreter(engine, hexat, params={1: R, 2: T, 4: ORIGIN, 5: D_HALF})
        interp.run()
        result = interp.read_param(3)
        assert (result.coord.x, result.coord.y) == _ref_hexat(R, T)


def test_hexat_unit_origin_runs_via_mock_world(engine):
    """Mock world Phase 2 payoff (mock_world_spec.md): the deployed library/hexat.dcs's unit-Origin
    path -- value_type(Origin) -> Unit branch -> get_location -> separate_coordinate -- was
    unrunnable through the Interpreter until the op dispatch grew those ops (Phase 2) and the mock
    world could supply a real entity to read a location from (Phase 1). With a MockWorld-backed comp
    and Origin bound to a live unit, HexAt computes the same coordinate as passing that unit's own
    coord directly (the closed-form reference, origin = the unit's tile)."""
    from desynced_toolkit import MockWorld

    repo_root = Path(__file__).parent.parent
    b = decompile_dcs(engine, (repo_root / "library" / "hexat.dcs").read_text().strip())
    prog = compile_behavior(engine, b)

    w = MockWorld(engine)
    ux, uy = -14, 51
    unit = w.spawn("f_bot_1m_c", "player", ux, uy)
    owner = w.spawn("f_bot_1m_c", "player", 0, 0, visibility_range=200)
    comp = w.add_component(owner, "c_behavior")
    new_value = engine.lua.globals().NewValue

    # R > 0 so it takes the get_location path rather than n1's R==0 "return Origin" shortcut.
    for R, T in [(3, 5), (5, 29), (8, 40)]:
        interp = Interpreter(engine, prog, params={1: R, 2: T, 5: D_HALF}, comp=comp)
        # Origin (param slot 4) is a live UNIT entity -> value_type routes to the Unit branch.
        interp.state.mem[4] = new_value(0, None, None, unit)
        interp.run()
        result = interp.read_param(3)
        assert (result.coord.x, result.coord.y) == _ref_hexat(R, T, origin=(ux, uy))
