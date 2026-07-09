"""bsf/render_mermaid.py: a pin is labeled only when its op has more than one -- matching the
real in-game editor (user-confirmed), which never bothers naming a node's only pin but always
names every pin once a node has several, wired or not. The edge itself is always drawn either
way; only the label is conditional."""

from desynced_toolkit.bsf.argcache import ArgCache
from desynced_toolkit.bsf.ir import BsfBehavior, BsfNode
from desynced_toolkit.bsf.render_mermaid import render_mermaid
from desynced_toolkit.bsf.values import Num, Var


def _compare_number_demo():
    a = BsfNode(id="A", op="check_number", args={"Value": Var("x"), "Compare": Var("y")})
    a.branches["If Larger"] = "B"
    a.branches["If Smaller"] = "POP"
    # "next" (If Equal) left as a plain implicit fallthrough -- C is physically next.
    c = BsfNode(id="C", op="set_reg", args={"Value": Num(2), "Target": Var("x")})
    b = BsfNode(id="B", op="set_reg", args={"Value": Num(1), "Target": Var("x")})
    return BsfBehavior(name="CompareNumberDemo", nodes={"A": a, "B": b, "C": c}, order=["A", "C", "B"])


def test_multi_pin_op_labels_every_pin_including_implicit_fallthrough(engine):
    mmd = render_mermaid(_compare_number_demo(), ArgCache(engine))
    assert "nA -->|If Larger| nB" in mmd
    assert "nA -.->|If Smaller|" in mmd
    # The real point of this test: check_number has 3 real pins (If Larger, If Smaller, If
    # Equal), so even though "If Equal" is a plain implicit fallthrough (not explicitly wired),
    # it must still be labeled -- an earlier draft left it silently unlabeled here.
    assert "nA -->|If Equal| nC" in mmd


def test_single_pin_op_edges_stay_unlabeled_but_present(engine):
    mmd = render_mermaid(_compare_number_demo(), ArgCache(engine))
    # set_reg has exactly one exec pin (the generic "next") -- never labeled, matching the real
    # editor not bothering to name a node's only pin -- but the edges must still be drawn.
    assert "nC --> nB" in mmd
    assert "nC -->|" not in mmd
    pop_lines = [line for line in mmd.split("\n") if line.strip().startswith("nB -.->")]
    assert len(pop_lines) == 1
    assert "|" not in pop_lines[0]  # unlabeled -- no pin name text on this edge
    assert "pop" in pop_lines[0]  # but the dashed edge to its marker is still there


def test_exit_restart_last_draw_no_next_edge_at_all(engine):
    argcache = ArgCache(engine)
    node = BsfNode(id="n1", op="exit")
    behavior = BsfBehavior(name="ExitTest", nodes={"n1": node}, order=["n1"])
    mmd = render_mermaid(behavior, argcache)
    outgoing = [line for line in mmd.split("\n") if line.strip().startswith("n1 ")]
    assert outgoing == []
