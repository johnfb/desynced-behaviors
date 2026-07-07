"""`compiler.AstCompiler`: the small Python-syntax-subset compiler, and the equality-handling
regression this project actually hit (`if a > b` used to route `a == b` into the wrong branch --
see the compiler's own `_compile_if` comment for the root cause)."""

import pytest

from desynced_toolkit import AstCompiler, Interpreter


def _run(engine, code, var="w"):
    compiled = AstCompiler(engine.lua).compile_source(code)
    interp = Interpreter(engine, compiled)
    interp.run()
    return interp.mem.read(var).num


@pytest.mark.parametrize(
    "a,b,op,expected",
    [
        (
            5,
            5,
            ">",
            2,
        ),  # equal -> else, for BOTH comparison directions (the actual bug)
        (5, 5, "<", 2),
        (7, 5, ">", 1),
        (3, 5, ">", 2),
        (7, 5, "<", 2),
        (3, 5, "<", 1),
    ],
)
def test_if_else_equality_handling(engine, a, b, op, expected):
    code = f"a={a}\nb={b}\nif a {op} b:\n    w=1\nelse:\n    w=2\n"
    assert _run(engine, code) == expected


def test_if_no_else(engine):
    assert _run(engine, "w=0\na=7\nb=5\nif a > b:\n    w=1\n") == 1
    assert _run(engine, "w=0\na=3\nb=5\nif a > b:\n    w=1\n") == 0


def test_arithmetic_and_branch_demo(engine):
    code = "x=3\ny=4\nz=x+y\nif z>5:\n    w=z-1\nelse:\n    w=z+100\n"
    compiled = AstCompiler(engine.lua).compile_source(code)
    interp = Interpreter(engine, compiled)
    interp.run()
    assert interp.mem.read("z").num == 7
    assert interp.mem.read("w").num == 6


def test_compiled_output_roundtrips_through_dcs_wire(engine):
    compiled = AstCompiler(engine.lua).compile_source("x=3\ny=4\nz=x+y\n")
    dcs_str = engine.encode_dcs("C", compiled)
    _, decoded = engine.decode_dcs(dcs_str)
    interp = Interpreter(engine, decoded)
    interp.run()
    assert interp.mem.read("z").num == 7


def test_nested_arithmetic_expressions(engine):
    # a+b+c and unary negation both require hoisting sub-expressions into temporaries -- the
    # original compiler could only handle a single flat `a op b`.
    assert _run(engine, "a=2\nb=3\nc=4\nw=2*a*b-c\n") == 8
    assert _run(engine, "a=5\nw=0-a\n") == -5


def test_and_chain_condition(engine):
    code = "a=5\nb=3\nc=5\nw=0\nif a > b and a > c:\n    w=1\nelif b >= c:\n    w=2\nelse:\n    w=3\n"
    assert _run(engine, code) == 3  # a>b true, a>c false(equal) -> elif: b>=c false -> else


def test_abs_and_max_builtins(engine):
    assert _run(engine, "x=0-7\nw=abs(x)\n") == 7
    assert _run(engine, "w=abs(7)\n") == 7
    assert _run(engine, "w=max(2,9,5)\n") == 9
    assert _run(engine, "w=max(9,2,5)\n") == 9


def test_for_loop_sum_and_break_and_continue(engine):
    assert _run(engine, "total=0\nfor k in range(0, 6):\n    total = total + k\n", "total") == 15

    code = (
        "found=-1\nfor k in range(0, 10):\n"
        "    sq = k*k\n    if sq > 30:\n        found = k\n        break\n"
    )
    assert _run(engine, code, "found") == 6

    code = (
        "total=0\nfor k in range(0, 10):\n"
        "    half = k // 2\n    doubled = half*2\n"
        "    if doubled != k:\n        continue\n    total = total + k\n"
    )
    assert _run(engine, code, "total") == 20  # sum of even 0..9


def test_jump_label_computed_dispatch_inside_loop(engine):
    code = (
        "total=0\nfor k in range(0, 3):\n"
        "    jump(k)\n"
        "    label(0)\n    total = total + 100\n    jump(999)\n"
        "    label(1)\n    total = total + 10\n    jump(999)\n"
        "    label(2)\n    total = total + 1\n"
        "    label(999)\n"
    )
    assert _run(engine, code, "total") == 111


def test_coordinate_ops(engine):
    compiled = AstCompiler(engine.lua).compile_source(
        "delta = coord_in - origin_in\ndx, dy = separate_coordinate(delta)\n"
        "combined = combine_coordinate(dx, dy)\n"
    )
    interp = Interpreter(engine, compiled)
    interp.state.mem[interp.mem.var("coord_in")] = engine.new_value(0, coord=(7, -3))
    interp.state.mem[interp.mem.var("origin_in")] = engine.new_value(0, coord=(2, 5))
    interp.run()
    assert (interp.mem.read("dx").num, interp.mem.read("dy").num) == (5, -8)
    combined = interp.mem.read("combined").coord
    assert (combined.x, combined.y) == (5, -8)
