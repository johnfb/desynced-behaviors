"""Phase 2 of the BSF pipeline (see /home/johnfb/.claude/plans/moonlit-nibbling-sonnet.md):
BsfBehavior <-> BSF text. Builds on Phase 1's already-proven compile_behavior as the equivalence
oracle (see test_bsf_ir_roundtrip.py) rather than a separate deep-equality helper."""

from pathlib import Path

import pytest

from desynced_toolkit.bsf.argcache import ArgCache
from desynced_toolkit.bsf.compile import compile_behavior
from desynced_toolkit.bsf.decompile import decompile_dcs
from desynced_toolkit.bsf.ir import BsfBehavior, BsfNode, BsfParam
from desynced_toolkit.bsf.parse_text import parse_behavior
from desynced_toolkit.bsf.render_text import render_behavior
from desynced_toolkit.bsf.values import Coord, Fr, IdLit, Num, Param, Var
from desynced_toolkit.lua_util import to_py

DATA_DIR = Path(__file__).parent / "data"

REAL_DCS_FILES = [
    "observer.dcs",
    "beacon.dcs",
    "beacon2.dcs",
    "formation-hold.dcs",
    "hexat_test.dcs",
    "HexIndexOf_test_1.dcs",
    "keepvars_clear.dcs",
    "keepvars_keep.dcs",
    "deprecated_haul_to_signal.dcs",
]


@pytest.mark.parametrize("fname", REAL_DCS_FILES)
def test_fixture_roundtrips_through_text(engine, fname):
    raw = (DATA_DIR / fname).read_text().strip()
    argcache = ArgCache(engine)
    b1 = decompile_dcs(engine, raw)
    text = render_behavior(b1, argcache)
    b2 = parse_behavior(text, argcache)
    assert to_py(compile_behavior(engine, b1, argcache)) == to_py(compile_behavior(engine, b2, argcache))


def test_jump_label_annotation_literal_vs_dynamic(engine):
    label_node = BsfNode(id="n1", op="label", args={"Label": IdLit("v_state_a")})
    jump_lit = BsfNode(id="n2", op="jump", args={"Label": IdLit("v_state_a")})
    jump_dyn = BsfNode(id="n3", op="jump", args={"Label": Var("Dynamic")})
    behavior = BsfBehavior(
        name="JumpTest",
        nodes={"n1": label_node, "n2": jump_lit, "n3": jump_dyn},
        order=["n1", "n2", "n3"],
    )
    argcache = ArgCache(engine)
    text = render_behavior(behavior, argcache)
    lines = text.split("\n")
    n2_line = next(line for line in lines if line.startswith("n2:"))
    n3_line = next(line for line in lines if line.startswith("n3:"))
    assert ">n1 (jump→label)" in n2_line  # literal Label, resolved statically
    assert "jump→label" not in n3_line  # dynamic Label ($Dynamic), never resolved

    reparsed = parse_behavior(text, argcache)
    # the annotation is display-only -- must not leak into the IR as a real branch
    assert "jump→label" not in reparsed.nodes["n2"].branches
    assert reparsed.nodes["n2"].args["Label"] == IdLit("v_state_a")
    assert reparsed.nodes["n3"].args["Label"] == Var("Dynamic")


def test_fr_value_with_and_without_num(engine):
    n1 = BsfNode(id="n1", op="set_reg", args={"Value": Fr("MyBand"), "Target": Var("x")})
    n2 = BsfNode(id="n2", op="set_reg", args={"Value": Fr("MyBand", 5), "Target": Var("y")})
    behavior = BsfBehavior(name="FrTest", nodes={"n1": n1, "n2": n2}, order=["n1", "n2"])
    argcache = ArgCache(engine)
    text = render_behavior(behavior, argcache)
    assert "fr(MyBand)" in text
    assert "fr(MyBand)[num=5]" in text

    reparsed = parse_behavior(text, argcache)
    assert reparsed.nodes["n1"].args["Value"] == Fr("MyBand", None)
    assert reparsed.nodes["n2"].args["Value"] == Fr("MyBand", 5)


def test_num_suffix_on_coord_and_id(engine):
    n1 = BsfNode(id="n1", op="set_reg", args={"Value": Coord(-5, 6, 3), "Target": Var("x")})
    n2 = BsfNode(id="n2", op="set_reg", args={"Value": IdLit("c_radar", 10), "Target": Var("y")})
    behavior = BsfBehavior(name="NumSuffix", nodes={"n1": n1, "n2": n2}, order=["n1", "n2"])
    argcache = ArgCache(engine)
    text = render_behavior(behavior, argcache)
    assert "coord(-5, 6)[num=3]" in text
    assert "c_radar[num=10]" in text

    reparsed = parse_behavior(text, argcache)
    assert reparsed.nodes["n1"].args["Value"] == Coord(-5, 6, 3)
    assert reparsed.nodes["n2"].args["Value"] == IdLit("c_radar", 10)


def test_param_name_takes_precedence_over_id_literal(engine):
    """A bare identifier is *both* an id-typed literal and a resolved-parameter-name in BSF's
    surface syntax -- the grammar itself is ambiguous here. Resolution rule: check the current
    behavior's own declared params first, fall back to an id literal."""
    argcache = ArgCache(engine)
    text_with_param = "behavior AmbigTest(c_radar):\n\nn1: set_reg(Value=c_radar, Target=$x)\n"
    b = parse_behavior(text_with_param, argcache)
    assert b.nodes["n1"].args["Value"] == Param(1)

    text_without_param = "behavior AmbigTest2():\n\nn1: set_reg(Value=c_radar, Target=$x)\n"
    b2 = parse_behavior(text_without_param, argcache)
    assert b2.nodes["n1"].args["Value"] == IdLit("c_radar")


def test_param_direction_is_recomputed_from_usage_not_trusted_from_text(engine):
    """The `*` a user types (or leaves off) in BSF text is display-only and gets stripped on
    parse, never stored -- compile.py always recomputes `parameters[i]` fresh from what the
    body actually does (argcache.written_param_slots), so a stale or simply-wrong `*` left over
    from a hand-edit can't produce an incorrect wire bit. Two cases, both intentionally
    "lying": a param marked `*` that's only ever read, and a param left unmarked that's
    actually written."""
    argcache = ArgCache(engine)

    lying_output = "behavior LyingOutput(X*):\n\nn1: debug_print(Print Value=X)\n"
    b1 = parse_behavior(lying_output, argcache)
    c1 = compile_behavior(engine, b1, argcache)
    assert list(c1["parameters"].values()) == [False]  # X is only ever read -- * was wrong

    lying_input = "behavior LyingInput(Y):\n\nn1: set_reg(Value=1, Target=Y)\n"
    b2 = parse_behavior(lying_input, argcache)
    c2 = compile_behavior(engine, b2, argcache)
    assert list(c2["parameters"].values()) == [True]  # Y is written -- missing * was wrong


def test_text_level_reorder_changes_implicit_fallthrough(engine):
    argcache = ArgCache(engine)
    text1 = (
        "behavior ReorderText():\n\n"
        "A: set_reg(Value=1, Target=$x)\n"
        "B: set_reg(Value=2, Target=$x)\n"
        "C: set_reg(Value=3, Target=$x)  >A (next)\n"
    )
    b1 = parse_behavior(text1, argcache)
    c1 = compile_behavior(engine, b1, argcache)
    assert c1[1][1]["num"] == 1  # A
    assert c1[2][1]["num"] == 2  # B -- A's implicit fallthrough target
    assert c1[3]["next"] == 1  # C's explicit target -- A's position

    text2 = text1.replace(
        "A: set_reg(Value=1, Target=$x)\nB: set_reg(Value=2, Target=$x)\n",
        "B: set_reg(Value=2, Target=$x)\nA: set_reg(Value=1, Target=$x)\n",
    )
    b2 = parse_behavior(text2, argcache)
    c2 = compile_behavior(engine, b2, argcache)
    assert c2[1][1]["num"] == 2  # B now first
    assert c2[2][1]["num"] == 1  # A now second
    assert set(c2[2].keys()) == {"op", 1, 2}  # A: still no explicit "next"
    assert c2[3]["next"] == 2  # C's explicit target tracked A to its new position


def test_pop_vs_omission_distinct_through_text_roundtrip(engine):
    argcache = ArgCache(engine)
    a = BsfNode(id="A", op="set_reg", args={"Value": Num(1), "Target": Var("x")})
    a.branches["next"] = "POP"  # explicit -- NOT the true end, B still follows
    b_node = BsfNode(id="B", op="set_reg", args={"Value": Num(2), "Target": Var("x")})
    b_node.branches["next"] = None  # implicit fallthrough; B is last, so this is POP-equivalent
    behavior = BsfBehavior(name="PopTest", nodes={"A": a, "B": b_node}, order=["A", "B"])

    text = render_behavior(behavior, argcache)
    lines = text.split("\n")
    a_line = next(line for line in lines if line.startswith("A:"))
    b_line = next(line for line in lines if line.startswith("B:"))
    assert ">POP (next)" in a_line
    assert ">" not in b_line  # omitted -- no annotation at all

    reparsed = parse_behavior(text, argcache)
    assert reparsed.nodes["A"].branches["next"] == "POP"
    assert reparsed.nodes["B"].branches.get("next") is None

    c1 = compile_behavior(engine, behavior, argcache)
    c2 = compile_behavior(engine, reparsed, argcache)
    assert to_py(c1) == to_py(c2)
    assert c1[1]["next"] is False  # A: explicit False (mid-array pop)
    assert "next" not in set(c1[2].keys())  # B: omitted (true-end pop)


def test_keepvars_and_keeparrays_survive_text_roundtrip(engine):
    """Regression test for a real bug found 2026-07-09: two real behaviors
    (keepvars_clear.dcs/keepvars_keep.dcs), identical instructions/params/vars and differing
    ONLY in `keepvars`, decompiled to byte-for-byte identical BSF text -- render_text.py silently
    never emitted `keepvars`/`keeparrays` and parse_text.py silently never parsed them, even
    though decompile.py/compile.py (the table-level IR layer) already handled `keepvars`
    correctly, and despite `keeparrays` being a real, separate, previously entirely-undocumented
    field (found chasing this same bug down). None of the other 6 fixtures set either field, so
    the existing parametrized round-trip tests never exercised this path."""
    argcache = ArgCache(engine)
    raw_clear = (DATA_DIR / "keepvars_clear.dcs").read_text().strip()
    raw_keep = (DATA_DIR / "keepvars_keep.dcs").read_text().strip()

    b_clear = decompile_dcs(engine, raw_clear)
    b_keep = decompile_dcs(engine, raw_keep)
    assert b_clear.keepvars is False
    assert b_keep.keepvars is True

    text_clear = render_behavior(b_clear, argcache)
    text_keep = render_behavior(b_keep, argcache)
    assert text_clear != text_keep  # the actual bug: these used to render identically
    assert "keepvars" not in text_clear
    assert "keepvars: true" in text_keep

    # full text round trip must preserve the flag, not just the initial render
    reparsed_keep = parse_behavior(text_keep, argcache)
    assert reparsed_keep.keepvars is True
    assert to_py(compile_behavior(engine, b_keep, argcache)) == to_py(compile_behavior(engine, reparsed_keep, argcache))

    reparsed_clear = parse_behavior(text_clear, argcache)
    assert reparsed_clear.keepvars is False


def test_keeparrays_three_states_render_and_parse(engine):
    argcache = ArgCache(engine)
    node = BsfNode(id="n1", op="set_reg", args={"Value": Num(1), "Target": Var("x")})

    b_absent = BsfBehavior(name="Arr", nodes={"n1": node}, order=["n1"])
    assert "keeparrays" not in render_behavior(b_absent, argcache)

    for mode in ("startup", "store"):
        b = BsfBehavior(name="Arr", nodes={"n1": node}, order=["n1"], keeparrays=mode)
        text = render_behavior(b, argcache)
        assert f'keeparrays: "{mode}"' in text
        reparsed = parse_behavior(text, argcache)
        assert reparsed.keeparrays == mode
