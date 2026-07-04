"""Confirms the lupa-backed engine correctly drives the *real* `data/instructions.lua` funcs
(add/sub/mul/div/check_number/set_reg/separate_coordinate/combine_coordinate/jump/label),
including the real `REG_INFINITE` handling in `check_number` -- see engine_stub.lua's module
docstring for the `Get`/`Set`/`InstGet`/`InstSet`/`GetStack` discovery this all depends on.
"""

from desynced_toolkit.lua_runtime import Memory


def test_arithmetic(engine):
    state = engine.new_state()
    comp = engine.new_comp()
    mem = Memory(engine, state)

    a = mem.literal(num=3)
    b = mem.literal(num=4)

    res = mem.var("res")
    engine.call("add", comp, state, a, b, res)
    assert mem.read(res).num == 7

    res2 = mem.var("res2")
    engine.call("sub", comp, state, a, b, res2)
    assert mem.read(res2).num == -1

    res3 = mem.var("res3")
    engine.call("mul", comp, state, a, b, res3)
    assert mem.read(res3).num == 12

    c = mem.literal(num=10)
    res4 = mem.var("res4")
    engine.call("div", comp, state, c, a, res4)
    assert mem.read(res4).num == 3  # floor division


def test_coordinate_roundtrip(engine):
    state = engine.new_state()
    comp = engine.new_comp()
    mem = Memory(engine, state)

    c = mem.literal(coord=(5, 9))
    x, y = mem.var("x"), mem.var("y")
    engine.call("separate_coordinate", comp, state, c, x, y)
    assert mem.read(x).num == 5
    assert mem.read(y).num == 9

    out = mem.var("out")
    engine.call("combine_coordinate", comp, state, x, y, out)
    result = mem.read(out)
    assert (result.coord.x, result.coord.y) == (5, 9)


def test_check_number_basic(engine):
    state = engine.new_state()
    comp = engine.new_comp()
    mem = Memory(engine, state)
    a, b = mem.literal(num=5), mem.literal(num=3)

    state.counter = None
    engine.call("check_number", comp, state, 100, 200, a, b)
    assert state.counter == 100  # 5 > 3 -> If Larger

    state.counter = None
    engine.call("check_number", comp, state, 100, 200, b, a)
    assert state.counter == 200  # 3 < 5 -> If Smaller

    state.counter = None
    engine.call("check_number", comp, state, 100, 200, a, a)
    assert state.counter is None  # equal -> neither branch fires


def test_check_number_reg_infinite(engine):
    """`check_number`'s REG_INFINITE special-casing -- genuinely exercised (not just a Python
    stand-in), per the "reuse real Lua logic" principle."""
    state = engine.new_state()
    comp = engine.new_comp()
    mem = Memory(engine, state)
    reg_infinite = engine.lua.globals().REG_INFINITE

    inf = mem.literal(num=reg_infinite)
    five = mem.literal(num=5)

    state.counter = None
    engine.call("check_number", comp, state, 1, 2, inf, five)
    assert state.counter == 1  # inf > 5 -> If Larger

    state.counter = None
    engine.call("check_number", comp, state, 1, 2, five, inf)
    assert state.counter == 2  # 5 < inf -> If Smaller

    state.counter = None
    inf2 = mem.literal(num=reg_infinite)
    engine.call("check_number", comp, state, 1, 2, inf, inf2)
    assert state.counter is None  # inf == inf -> neither branch fires


def test_set_reg(engine):
    state = engine.new_state()
    comp = engine.new_comp()
    mem = Memory(engine, state)
    x = mem.literal(num=42)
    y = mem.var("y")
    engine.call("set_reg", comp, state, x, y)
    assert mem.read(y).num == 42
