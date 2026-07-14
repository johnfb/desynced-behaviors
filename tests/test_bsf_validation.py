"""Strict parse/compile validation, added 2026-07-14 after a probe demonstrated that every
case here was previously either accepted silently (compiling into a *wrong* behavior with no
error at any stage) or rejected with a context-free/misleading error. The silent cases were the
motivation -- see the review notes in behavior_source_format.md's "Validation" section:
  - a typo'd exec pin name compiled with that pin silently unwired
  - a forgotten `$` sigil silently turned a variable into an id literal
  - a duplicate node id silently clobbered its predecessor (and corrupted `order`)
  - a duplicate arg name silently dropped the first value
"""

import pytest

from desynced_toolkit.bsf.argcache import ArgCache
from desynced_toolkit.bsf.compile import BsfCompileError, compile_behavior
from desynced_toolkit.bsf.ir import BsfBehavior, BsfNode
from desynced_toolkit.bsf.parse_text import BsfParseError, parse_behavior
from desynced_toolkit.bsf.render_text import render_behavior
from desynced_toolkit.bsf.values import Num, Var


@pytest.fixture(scope="module")
def argcache(engine):
    return ArgCache(engine)


def _parse(text, argcache):
    return parse_behavior(text, argcache)


def test_typoed_pin_name_rejected_with_valid_pins_listed(argcache):
    with pytest.raises(BsfParseError, match=r"no exec pin named 'Smaller'.*If Smaller"):
        _parse(
            "behavior T():\n\n"
            "n1: check_number(Value=$A, Compare=5)  >n3 (Smaller)\n"
            "n2: set_reg(Value=1, Target=$B)\n"
            "n3: set_reg(Value=2, Target=$B)\n",
            argcache,
        )


def test_unknown_op_rejected_with_suggestion(argcache):
    with pytest.raises(BsfParseError, match=r"unknown instruction op 'set_regg'.*set_reg"):
        _parse("behavior T():\n\nn1: set_regg(Value=1, Target=$B)\n", argcache)


def test_missing_sigil_rejected_as_unknown_id(argcache):
    with pytest.raises(BsfParseError, match=r"unknown identifier 'ScanResult'.*\$ScanResult"):
        _parse("behavior T():\n\nn1: set_reg(Value=ScanResult, Target=$B)\n", argcache)


def test_misspelled_game_id_gets_suggestion(argcache):
    with pytest.raises(BsfParseError, match=r"unknown identifier 'v_resourse'.*v_resource"):
        _parse("behavior T():\n\nn1: set_reg(Value=v_resourse, Target=$B)\n", argcache)


def test_known_game_ids_accepted(argcache):
    b = _parse("behavior T():\n\nn1: set_reg(Value=v_resource, Target=$B)\n", argcache)
    assert b.nodes["n1"].args["Value"].id == "v_resource"


def test_duplicate_node_id_rejected(argcache):
    with pytest.raises(BsfParseError, match=r"line 4: duplicate node id 'n1'"):
        _parse(
            "behavior T():\n\nn1: set_reg(Value=1, Target=$B)\nn1: set_reg(Value=2, Target=$C)\n",
            argcache,
        )


def test_duplicate_arg_name_rejected_with_suffix_hint(argcache):
    with pytest.raises(BsfParseError, match=r"duplicate argument 'Unit'.*Unit2"):
        _parse("behavior T():\n\nn1: is_same_grid(Unit=$A, Unit=$B)\n", argcache)


def test_typoed_arg_name_rejected_with_valid_names(argcache):
    with pytest.raises(BsfParseError, match=r"no argument named 'Valu'.*Value"):
        _parse("behavior T():\n\nn1: set_reg(Valu=1, Target=$B)\n", argcache)


def test_branch_to_unknown_node_rejected(argcache):
    with pytest.raises(BsfParseError, match=r"node 'n1' pin 'If Smaller' targets unknown node 'n9'"):
        _parse(
            "behavior T():\n\n"
            "n1: check_number(Value=$A, Compare=5)  >NEXT (If Larger) >n9 (If Smaller) >NEXT (If Equal)\n"
            "n2: set_reg(Value=1, Target=$B)\n",
            argcache,
        )


# -- multi-exec-pin ops require every pin written (the loop-Done-omission class) -------------


def test_multi_pin_op_with_missing_pins_rejected(argcache):
    with pytest.raises(BsfParseError, match=r"every one must be written.*missing: 'Done'"):
        _parse(
            "behavior T():\n\n"
            "n1: for_number(From=1, To=3, Value=$N)\n"
            "n2: set_reg(Value=$N, Target=$B)  >n1 (next)\n",
            argcache,
        )


def test_multi_pin_op_fully_written_accepted_and_next_is_fallthrough(argcache):
    b = _parse(
        "behavior T():\n\n"
        "n1: for_number(From=1, To=3, Value=$N)  >POP (Done) >NEXT (next)\n"
        "n2: set_reg(Value=$N, Target=$B)  >n1 (next)\n",
        argcache,
    )
    # NEXT = explicit fallthrough = structurally absent, exactly like single-pin omission
    assert "next" not in b.nodes["n1"].branches
    assert b.nodes["n1"].branches["Done"] == "POP"


def test_single_pin_op_accepts_explicit_next_token(argcache):
    b = _parse("behavior T():\n\nn1: set_reg(Value=1, Target=$B)  >NEXT (next)\nn2: unlock()\n", argcache)
    assert "next" not in b.nodes["n1"].branches


def test_render_emits_next_token_for_all_multi_pin_ops(engine, argcache):
    n1 = BsfNode(id="n1", op="check_number", args={"Value": Num(1), "Compare": Num(2)})
    n1.branches["If Smaller"] = "POP"
    n2 = BsfNode(id="n2", op="set_reg", args={"Value": Num(1), "Target": Var("B")})
    b = BsfBehavior(name="T", nodes={"n1": n1, "n2": n2}, order=["n1", "n2"])
    text = render_behavior(b, argcache)
    n1_line = next(line for line in text.split("\n") if line.startswith("n1:"))
    assert ">NEXT (If Larger)" in n1_line
    assert ">POP (If Smaller)" in n1_line
    assert ">NEXT (If Equal)" in n1_line
    # and the rendered text passes its own completeness rule
    parse_behavior(text, argcache)


def test_pop_and_next_reserved_as_node_ids(argcache):
    with pytest.raises(BsfParseError, match=r"'POP' is a reserved"):
        _parse("behavior T():\n\nPOP: set_reg(Value=1, Target=$B)\n", argcache)


def test_blank_lines_between_nodes_allowed(argcache):
    b = _parse(
        "behavior T():\n\n"
        "n1: set_reg(Value=1, Target=$B)\n"
        "\n"
        "n2: set_reg(Value=2, Target=$C)\n",
        argcache,
    )
    assert b.order == ["n1", "n2"]


def test_header_attributes_accepted_in_any_order(argcache):
    b = _parse(
        'behavior T():\n  keepvars: true\n  desc: "hello"\n\nn1: set_reg(Value=1, Target=$B)\n',
        argcache,
    )
    assert b.keepvars is True and b.desc == "hello"


def test_malformed_header_attribute_rejected(argcache):
    with pytest.raises(BsfParseError, match=r"malformed keepvars"):
        _parse("behavior T():\n  keepvars: yes\n\nn1: set_reg(Value=1, Target=$B)\n", argcache)


def test_pin_wired_twice_rejected(argcache):
    with pytest.raises(BsfParseError, match=r"pin 'If Smaller' wired twice"):
        _parse(
            "behavior T():\n\n"
            "n1: check_number(Value=$A, Compare=5)  >n2 (If Smaller) >POP (If Smaller)\n"
            "n2: set_reg(Value=1, Target=$B)\n",
            argcache,
        )


def test_parse_errors_carry_line_numbers(argcache):
    with pytest.raises(BsfParseError, match=r"line 3:"):
        _parse("behavior T():\n\nn1: set_regg(Value=1)\n", argcache)


def test_desc_with_quotes_and_newline_roundtrips(engine, argcache):
    b = BsfBehavior(
        name="T",
        desc='say "hi" then\nstop',
        nodes={"n1": BsfNode(id="n1", op="set_reg", args={"Value": Num(1), "Target": Var("B")})},
        order=["n1"],
    )
    text = render_behavior(b, argcache)
    b2 = parse_behavior(text, argcache)
    assert b2.desc == b.desc


# -- IR-level (hand-built, bypassing the parser) --------------------------------------------


def _one_node_behavior(node):
    return BsfBehavior(name="T", nodes={node.id: node}, order=[node.id])


def test_compile_rejects_unknown_branch_pin_on_ir(engine, argcache):
    n = BsfNode(id="n1", op="check_number", args={"Value": Num(1), "Compare": Num(2)})
    n.branches["Smaller"] = "POP"  # typo'd key -- was silently dropped before
    with pytest.raises(BsfCompileError, match=r"unknown branch pin 'Smaller'"):
        compile_behavior(engine, _one_node_behavior(n), argcache)


def test_compile_rejects_unknown_op_on_ir(engine, argcache):
    n = BsfNode(id="n1", op="set_regg", args={})
    with pytest.raises(BsfCompileError, match=r"unknown instruction op 'set_regg'"):
        compile_behavior(engine, _one_node_behavior(n), argcache)


def test_compile_rejects_unknown_arg_on_ir(engine, argcache):
    n = BsfNode(id="n1", op="set_reg", args={"Valu": Num(1)})
    with pytest.raises(BsfCompileError, match=r"unknown argument 'Valu'"):
        compile_behavior(engine, _one_node_behavior(n), argcache)


def test_compile_rejects_branch_to_unknown_node_on_ir(engine, argcache):
    n = BsfNode(id="n1", op="set_reg", args={"Value": Num(1), "Target": Var("B")})
    n.branches["next"] = "n9"
    with pytest.raises(BsfCompileError, match=r"node 'n1' pin 'next'.*unknown node 'n9'"):
        compile_behavior(engine, _one_node_behavior(n), argcache)
