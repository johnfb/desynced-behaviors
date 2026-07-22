"""Tests over the personal deployed behaviors in library/ -- these depend on this repo's own
directory layout (library/*.bsf) and so live here rather than in blz-desynced-toolkit, unlike
the toolkit's own fixture-based tests (tests/data/*.dcs) which moved there with the package.

library/ is a bsf/library.py by-reference store (`desynced-bsf import`/`export`), not a flat pile
of self-contained files: a shared sub-behavior (Async Radar Set/Get, called from both Observer and
Mining Leader) lives in its own file, referenced by name from each caller instead of duplicated --
see todo.md's "Local behavior-library storage" for why. Every `*.bsf` file here, referenced or not,
is still an independently valid `behavior NAME(...):` document; parsing one that contains a `from`
reference needs `base_dir=LIBRARY_DIR` to resolve it. Blueprints (wire type 'B', e.g.
magnifier_lattice) aren't BSF-decompilable and stay as .dcs."""

import math
from pathlib import Path

import pytest

from blz.desynced_toolkit import Interpreter, MockWorld
from blz.desynced_toolkit.bsf.argcache import ArgCache
from blz.desynced_toolkit.bsf.compile import compile_behavior
from blz.desynced_toolkit.bsf.lint import lint_behavior
from blz.desynced_toolkit.bsf.parse_text import parse_behavior

REPO_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_DIR = REPO_ROOT / "library"

D_HALF = 5
ORIGIN = (0, 0)
SCALE = 10000
K = 8660


def _ref_hexat(R, T, d_half=D_HALF, origin=ORIGIN):
    """Same closed-form reference as blz-desynced-toolkit's test_hex_expansion.py."""
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


@pytest.fixture(scope="module")
def argcache(engine):
    return ArgCache(engine)


def test_lint_clean_on_all_library_behaviors(engine, argcache):
    checked = 0
    for f in sorted(LIBRARY_DIR.glob("*.bsf")):
        b = parse_behavior(f.read_text(), argcache, base_dir=LIBRARY_DIR)
        assert lint_behavior(b, argcache) == [], f.name
        checked += 1
    assert checked >= 1


def test_hexat_unit_origin_runs_via_mock_world(engine):
    """Mock world Phase 2 payoff (mock_world_spec.md): the deployed library/hexat.dcs's unit-Origin
    path -- value_type(Origin) -> Unit branch -> get_location -> separate_coordinate -- was
    unrunnable through the Interpreter until the op dispatch grew those ops (Phase 2) and the mock
    world could supply a real entity to read a location from (Phase 1). With a MockWorld-backed comp
    and Origin bound to a live unit, HexAt computes the same coordinate as passing that unit's own
    coord directly (the closed-form reference, origin = the unit's tile)."""
    argcache = ArgCache(engine)
    b = parse_behavior((LIBRARY_DIR / "hexat.bsf").read_text(), argcache, base_dir=LIBRARY_DIR)
    prog = compile_behavior(engine, b)

    w = MockWorld(engine)
    ux, uy = -14, 51
    unit = w.spawn("f_bot_1m_c", "player", ux, uy)
    owner = w.spawn("f_bot_1m_c", "player", 0, 0, visibility_range=200)
    comp = w.add_component(owner, "c_behavior")
    new_value = engine.lua.globals().NewValue

    # R > 0 so it takes the get_location path rather than n1's R==0 "return Origin" shortcut.
    for R, T in [(3, 5), (5, 29), (8, 40)]:
        # Origin (param 4) is a live UNIT entity -> value_type routes to the Unit branch.
        # Parameters are component registers under the real dispatcher, so the entity value is
        # just another param (a Lua Value passes through Interpreter's params coercion).
        interp = Interpreter(
            engine,
            prog,
            params={1: R, 2: T, 4: new_value(0, None, None, unit), 5: D_HALF},
            comp=comp,
        )
        interp.run()
        result = interp.read_param(3)
        assert (result.coord.x, result.coord.y) == _ref_hexat(R, T, origin=(ux, uy))
