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


def test_compiled_output_roundtrips_through_dsc_wire(engine):
    compiled = AstCompiler(engine.lua).compile_source("x=3\ny=4\nz=x+y\n")
    dsc_str = engine.encode_dsc("C", compiled)
    _, decoded = engine.decode_dsc(dsc_str)
    interp = Interpreter(engine, decoded)
    interp.run()
    assert interp.mem.read("z").num == 7
