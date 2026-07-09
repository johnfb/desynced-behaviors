"""BsfBehavior -> BSF text, per behavior_source_format.md's grammar (the "Values"/"Control
edges"/"Dynamic jump/label dispatch" sections in particular). No text is stored anywhere in the
IR -- everything here is a pure function of the graph, recomputed fresh every render, including
the jump->label display annotation (see `_jump_label_targets`: caching this anywhere would risk
a stale annotation surviving a label rename or a `Label=` edit)."""

from __future__ import annotations

from .argcache import ArgCache, written_param_slots
from .ir import BsfBehavior, BsfNode, BsfParam
from .values import BsfValue, Coord, Fr, FrameReg, IdLit, Num, Param, Unknown, Var

_SYMBOLIC_FRAME_REGS = {-1: "goto", -2: "store", -3: "visual", -4: "signal"}


def _fmt_num(n: int | float) -> str:
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    return str(n)


def _param_name(slot: int, params: list[BsfParam]) -> str:
    """3-tier resolution per behavior_source_format.md's Values table: a real pname when the
    slot is covered by `params`, else the generic `param<i>`/`slot<i>(undeclared)` fallback --
    `BsfParam.name` already carries the resolved pname-or-param<i> distinction from decompile
    time, so only the "not covered at all" case needs handling here."""
    if 1 <= slot <= len(params):
        return params[slot - 1].name
    return f"slot{slot}(undeclared)"


def render_value(v: BsfValue, params: list[BsfParam]) -> str:
    if isinstance(v, Num):
        return _fmt_num(v.n)
    if isinstance(v, Coord):
        base = f"coord({_fmt_num(v.x)}, {_fmt_num(v.y)})"
        return f"{base}[num={_fmt_num(v.num)}]" if v.num is not None else base
    if isinstance(v, IdLit):
        return f"{v.id}[num={_fmt_num(v.num)}]" if v.num is not None else v.id
    if isinstance(v, Var):
        return f"${v.name}"
    if isinstance(v, Param):
        return _param_name(v.slot, params)
    if isinstance(v, FrameReg):
        sym = _SYMBOLIC_FRAME_REGS.get(v.slot)
        return f"@{sym}" if sym else f"@{-v.slot}"
    if isinstance(v, Fr):
        base = f"fr({v.name})"
        return f"{base}[num={_fmt_num(v.num)}]" if v.num is not None else base
    if isinstance(v, Unknown):
        # Rare escape hatch (behavior_source_format.md doesn't define surface syntax for a
        # value shape it doesn't enumerate) -- not guaranteed round-trippable through
        # parse_text.py. None of the 6 real fixtures this pipeline is validated against hit
        # this path; flagged here rather than silently producing unparseable-looking output.
        return f"!unknown({v.raw!r})"
    raise TypeError(f"unrecognized BsfValue: {v!r}")


def _literal_key(v: BsfValue):
    # IdLit's `num` is a real, distinguishing part of the value here, not incidental -- a real
    # user behavior (Mining Leader V3.2) uses one label id (`v_broken`) with different `num`
    # suffixes (bare, `[num=1]`, `[num=10]`) as three genuinely different jump targets, reusing
    # one visual-editor label icon as a "family" of sub-entry-points. Keying on `v.id` alone
    # (found 2026-07-09) silently conflated all three into one dict entry, so every jump to any
    # of them resolved to whichever label happened to be inserted last.
    if isinstance(v, IdLit):
        return ("id", v.id, v.num)
    if isinstance(v, Num):
        return ("num", v.n)
    return None


def _jump_label_targets(nodes: dict[str, BsfNode]) -> dict[str, str]:
    """Best-effort static jump->label resolution, scoped to one behavior/sub's own node set
    (never across a sub-behavior boundary). Only attempted when a `jump`'s `Label` arg is a
    literal (IdLit/Num) -- a variable/parameter/register Label genuinely can't be resolved
    without running the program, per the spec."""
    label_defs: dict[tuple, str] = {}
    for node in nodes.values():
        if node.op == "label" and "Label" in node.args:
            key = _literal_key(node.args["Label"])
            if key is not None:
                label_defs[key] = node.id
    targets = {}
    for node in nodes.values():
        if node.op == "jump" and "Label" in node.args:
            key = _literal_key(node.args["Label"])
            if key is not None and key in label_defs:
                targets[node.id] = label_defs[key]
    return targets


def render_hidden_value(v: object) -> str:
    """behavior_source_format.md's grammar has no surface syntax at all for make_asm's "hidden
    literal fields" (call's `sub`, domove's `c`, notify's `txt`, the universal `cmt`) -- a real
    gap, not a deliberate omission (see decompile.py's HIDDEN_FIELD_TABLE; 2 of the 6 real
    fixtures this pipeline is validated against need `call`'s `sub` to round-trip at all).
    Minimal, explicitly-flagged extension used here: render hidden fields as ordinary
    lowercase-named `name=value` pairs in the same arg list, with a quoted-string literal form
    (undefined elsewhere in the grammar) for string values (`sub`'s external-library-id case,
    `txt`/`cmt`'s free text) -- simpler and more robust than trying to resolve `call`'s target
    to a bare name token (the one illustrative example in the spec does this, but that requires
    cross-referencing sibling `sub` blocks not yet parsed at that point in a single top-to-bottom
    pass; deferred, noted for reconsideration)."""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return _fmt_num(v)
    if isinstance(v, str):
        return '"' + v.replace('"', '\\"') + '"'
    return repr(v)


def render_node(node: BsfNode, params: list[BsfParam], jump_targets: dict[str, str], argcache: ArgCache) -> str:
    parts = [f"{name}={render_value(v, params)}" for name, v in node.args.items()]
    parts += [f"{name}={render_hidden_value(v)}" for name, v in node.hidden.items()]
    args_str = ", ".join(parts)
    notes = []
    for pin, target in node.branches.items():
        if target is None:
            continue
        display_pin = pin
        if pin == "next":
            # data.instructions[op].exec_arg: `false` means this op has no top-level "next"
            # pin at all (exit/restart/last -- the real editor draws no pin, wiring anything
            # after them is nonsensical), a table names it for real (check_number's "If
            # Equal"), absent keeps the generic "next". Never guessed -- read straight from
            # live data.
            display_pin = argcache.next_pin_name(node.op)
            if display_pin is None:
                continue
        notes.append(f">{target} ({display_pin})")
    if node.id in jump_targets:
        notes.append(f">{jump_targets[node.id]} (jump→label)")
    line = f"{node.id}: {node.op}({args_str})"
    if notes:
        line += "  " + " ".join(notes)
    return line


def _render_into(b: BsfBehavior, lines: list[str], keyword: str, argcache: ArgCache) -> None:
    # behavior_source_format.md's `param := NAME` has no room for a parameter's direction at
    # all -- another real gap (see render_hidden_value's docstring for the sibling one).
    # Minimal extension: a trailing `*` marks a parameter written to somewhere in this
    # behavior's own body. Computed fresh here from `written_param_slots`, never stored on
    # `BsfParam` -- the wire's own `parameters[i]` bit turned out to be a UI-drawing hint (which
    # side of a `call` node a pin is drawn on), not a runtime distinction, so trusting a stored
    # bit here would let it silently go stale after an edit that adds or removes a write.
    written = written_param_slots(b, argcache)
    params_str = ", ".join(p.name + ("*" if (i + 1) in written else "") for i, p in enumerate(b.params))
    lines.append(f"{keyword} {b.name}({params_str}):")
    if b.desc:
        lines.append(f'  desc: "{b.desc}"')
    if b.keepvars:
        lines.append("  keepvars: true")
    if b.keeparrays:
        lines.append(f'  keeparrays: "{b.keeparrays}"')
    lines.append("")
    jump_targets = _jump_label_targets(b.nodes)
    for node_id in b.order:
        lines.append(render_node(b.nodes[node_id], b.params, jump_targets, argcache))
    for sub in b.subs:
        lines.append("")
        _render_into(sub, lines, keyword="sub", argcache=argcache)


def render_behavior(b: BsfBehavior, argcache: ArgCache) -> str:
    lines: list[str] = []
    _render_into(b, lines, keyword="behavior", argcache=argcache)
    return "\n".join(lines)
