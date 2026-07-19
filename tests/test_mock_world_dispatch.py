"""Mock world Phase 2 (mock_world_spec.md): the Interpreter's op dispatch now drives the world /
sensing ops end-to-end -- get_location, get_closest_entity, read_signal, value_type, match, and the
block-producing sensing loops (for_entities_in_range). Each behavior is authored in BSF, compiled by
the real compiler, and run through the real instruction funcs over a MockWorld-backed component
(comp.owner is a genuine mock entity). The dispatch itself is metadata-driven, so these also guard
the generic marshaller (in/out/exec + hidden make_asm args)."""

from desynced_toolkit import Interpreter, MockWorld
from desynced_toolkit.bsf.argcache import ArgCache
from desynced_toolkit.bsf.compile import compile_behavior
from desynced_toolkit.bsf.parse_text import parse_behavior


def _compile(engine, text):
    b = parse_behavior(text, ArgCache(engine))
    return compile_behavior(engine, b)


def _run(engine, w, owner, text, params=None):
    comp = w.add_component(owner, "c_behavior")
    prog = _compile(engine, text)
    interp = Interpreter(engine, prog, params=params, comp=comp)
    interp.run()
    return interp


def test_get_location_self(engine):
    w = MockWorld(engine)
    owner = w.spawn("f_bot_1m_c", "player", 7, 3)
    interp = _run(
        engine,
        w,
        owner,
        "behavior T(Out*):\n"
        "n1: get_location(Coord=Out)\n",  # Unit omitted -> self
    )
    coord = interp.read_param(1).coord
    assert (coord.x, coord.y) == (7, 3)


def test_get_closest_entity_finds_enemy(engine):
    w = MockWorld(engine)
    player = w.faction("player")
    bugs = w.faction("bugs")
    w.set_trust(player, bugs, "ENEMY")
    owner = w.spawn("f_bot_1m_c", player, 0, 0, visibility_range=40)
    w.spawn("f_bot_1m_c", player, 3, 0)  # friendly, closer -- must be skipped
    enemy = w.spawn("f_bot_1m_c", bugs, 12, 0)
    w.spawn("f_bot_1m_c", bugs, 30, 0)  # farther enemy

    interp = _run(
        engine,
        w,
        owner,
        "behavior T(Out*):\n"
        "n1: get_closest_entity(Filter=v_enemy_faction, Output=Out)\n",
    )
    assert interp.read_param(1).entity.eid == enemy.eid


def test_distance_metrics_through_real_funcs(engine):
    """Pins the settled distance semantics through the REAL instruction funcs (not just the
    Map primitives): get_closest_entity's winner is the straight-line-nearest (Euclidean), and
    get_distance reads back the unobstructed grid path length (octile) -- both user-observed
    in-game 2026-07-19; see world.lua's distance-model note."""
    w = MockWorld(engine)
    player = w.faction("player")
    bugs = w.faction("bugs")
    w.set_trust(player, bugs, "ENEMY")
    owner = w.spawn("f_bot_1m_c", player, 0, 0, visibility_range=40)
    w.spawn("f_bot_1m_c", bugs, 8, 7)  # Chebyshev/path-length would pick this one
    b = w.spawn("f_bot_1m_c", bugs, 10, 3)  # Euclidean-nearest (10.44 < 10.63)

    interp = _run(
        engine,
        w,
        owner,
        "behavior T(Out*, Dist*):\n"
        "n1: get_closest_entity(Filter=v_enemy_faction, Output=Out)\n"
        "n2: get_distance(Target=Out, Distance=Dist)\n",
    )
    assert interp.read_param(1).entity.eid == b.eid
    # path length to (10,3): 10 + 3*(sqrt(2)-1) = 11.24 -> 11 (Euclidean would round to 10)
    assert interp.read_param(2).num == 11


def test_read_signal_of_found_unit(engine):
    w = MockWorld(engine)
    owner = w.spawn("f_bot_1m_c", "player", 0, 0, visibility_range=40)
    mate = w.spawn("f_bot_1m_c", "player", 8, 0)
    mate.SetRegister(mate, 1, engine.new_value(num=42))  # FRAMEREG_SIGNAL = 1

    interp = _run(
        engine,
        w,
        owner,
        "behavior T(Out*):\n"
        "n1: get_closest_entity(Filter=v_bot, Output=$u)\n"
        "n2: read_signal(Unit=$u, Result=Out)\n",
    )
    assert interp.read_param(1).num == 42


def test_match_failed_exec_branch(engine):
    """match sets state.counter to the Failed pin when the unit doesn't match -- exercises the
    generic exec-branch resolution (self is player, so v_enemy_faction fails)."""
    w = MockWorld(engine)
    owner = w.spawn("f_bot_1m_c", "player", 0, 0)
    interp = _run(
        engine,
        w,
        owner,
        "behavior T(Out*):\n"
        "n1: match(Filter=v_enemy_faction)  >n3 (Failed) >NEXT (next)\n"
        "n2: set_reg(Value=1, Target=Out)  >POP (next)\n"
        "n3: set_reg(Value=2, Target=Out)  >POP (next)\n",
    )
    assert interp.read_param(1).num == 2  # took the Failed branch


def test_value_type_coord_branch(engine):
    """value_type dispatches on the value's type (a hidden-arg-free multi-exec op). A coord input
    takes the Coord pin."""
    w = MockWorld(engine)
    owner = w.spawn("f_bot_1m_c", "player", 0, 0)
    interp = _run(
        engine,
        w,
        owner,
        "behavior T(In, Out*):\n"
        "n1: value_type(Data=In)  >POP (Item) >POP (Unit) >POP (Component) "
        ">POP (Tech) >POP (Value) >n3 (Coord) >POP (No Match)\n"
        "n2: set_reg(Value=1, Target=Out)  >POP (next)\n"
        "n3: set_reg(Value=2, Target=Out)  >POP (next)\n",
        params={1: (5, 9)},  # a coord
    )
    assert interp.read_param(2).num == 2  # took the Coord branch


def test_for_entities_in_range_counts_bots(engine):
    """for_entities_in_range is a block-producing loop: its func builds the iterator via real
    Map.FindClosestEntity + FilterEntity, and the Python block driver runs .next/.last. Counts the
    other bots in range (owner excluded)."""
    w = MockWorld(engine)
    owner = w.spawn("f_bot_1m_c", "player", 0, 0, visibility_range=50)
    for x in (5, 10, 15):
        w.spawn("f_bot_1m_c", "player", x, 0)

    interp = _run(
        engine,
        w,
        owner,
        "behavior T(Count*):\n"
        "n1: set_reg(Value=0, Target=Count)\n"
        "n2: for_entities_in_range(Range=50, Filter=v_bot, Unit=$u)  >n4 (Done) >NEXT (next)\n"
        "n3: add(To=Count, Num=1, Result=Count)  >POP (next)\n"
        "n4: exit()\n",
    )
    assert interp.read_param(1).num == 3


def test_for_signal_match_membership_scan(engine):
    """for_signal_match is the other block-producing sensing loop; it enumerates own-faction units
    broadcasting a signal via the real GetEntitiesWithRegister + the func's own id match. Counts the
    two units broadcasting v_transport_route, skipping the one on v_idle and the signal-less owner."""
    w = MockWorld(engine)
    owner = w.spawn("f_bot_1m_c", "player", 0, 0, visibility_range=50)
    for x in (5, 10):
        m = w.spawn("f_bot_1m_c", "player", x, 0)
        m.SetRegister(m, 1, engine.new_value(0, None, "v_transport_route"))
    odd = w.spawn("f_bot_1m_c", "player", 7, 0)
    odd.SetRegister(odd, 1, engine.new_value(0, None, "v_idle"))

    interp = _run(
        engine,
        w,
        owner,
        "behavior T(Count*):\n"
        "n1: set_reg(Value=0, Target=Count)\n"
        "n2: for_signal_match(Signal=v_transport_route, Unit=$u, Signal2=$s)  "
        ">n4 (Done) >NEXT (next)\n"
        "n3: add(To=Count, Num=1, Result=Count)  >POP (next)\n"
        "n4: exit()\n",
    )
    assert interp.read_param(1).num == 2
