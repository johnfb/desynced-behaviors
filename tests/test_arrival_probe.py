"""The ArrivalProbe instrument (tests/data/arrival_probe.bsf, compiled copy alongside) run
against the mock world's PROVISIONAL arrival model.

STATUS: the expected values below are what world.lua's provisional model predicts (arrived iff
get_distance(unit, target) <= range, floored at 1 for an entity target) -- they are NOT in-game
measurements yet. This is an instrument-with-pending-results fixture in the range_probe.bsf
tradition: once the probe has been run in the real game, replace these expectations with the
measured golden numbers and reword this docstring (and, if the game disagrees with the model,
fix world.lua's `arrival_tolerance`/`arrived` to match -- that is the entire point of the
probe). See mock_world_spec.md's RequestStateMove open item."""

from pathlib import Path

from desynced_toolkit import MockWorld

DATA_DIR = Path(__file__).parent / "data"


def test_arrival_probe_against_provisional_model(engine):
    dcs = (DATA_DIR / "arrival_probe.dcs").read_text().strip()
    w = MockWorld(engine)
    e = w.spawn("f_bot_1s_adw", "player", 0, 0)  # Engineer at the origin; coord target = (10, 0)
    target = w.spawn("f_bot_1m_c", "player", 0, 10)  # entity target 10 NORTH (off the coord path)
    interp = w.attach_behavior(
        e, dcs, params={1: engine.lua.globals().NewValue(0, None, None, target)}
    )
    for _ in range(600):
        w.step(1)
        if interp._finished:
            break
    assert interp._finished

    # decode the print stream into (marker, distance, stop) triples + the done marker
    cases, current = {}, []
    done = False
    for p in w.prints:
        v = p.value
        if v.coord is not None:
            current.append(("coord", (int(v.coord.x), int(v.coord.y))))
        else:
            current.append(("num", int(v.num)))
        if len(current) >= 3 and current[-3][0] == "num" and current[-3][1] in (
            100, 102, 105, 200, 202, 205,
        ):
            marker = current[-3][1]
            cases[marker] = (current[-2][1], current[-1][1])
        if current[-1] == ("num", 999):
            done = True
    assert done
    assert ("num", 888) not in current  # no case hit the path-blocked marker

    # PROVISIONAL expectations (see module docstring): {marker: (distance readout, stop tile)}
    assert cases == {
        100: (0, (10, 0)),  # coord, range 0: stops ON the tile
        102: (2, (8, 0)),  # coord, range 2: first tile with get_distance <= 2
        105: (5, (5, 0)),
        200: (1, (0, 9)),  # entity, range 0: adjacent (its tile can't be entered)
        202: (2, (0, 8)),
        205: (5, (0, 5)),
    }
