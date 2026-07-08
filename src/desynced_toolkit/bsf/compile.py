"""BsfBehavior -> real Lua table (the "assembler" pass). The reverse of bsf/decompile.py."""

from __future__ import annotations

from .argcache import ArgCache, arg_pin_names
from .decompile import DYNAMIC_ARG_OPS
from .ir import BsfBehavior, BsfNode
from .values import to_lua


def _call_positions(b: BsfBehavior, node: BsfNode) -> dict[str, int]:
    """Mirror of decompile.py's `_call_arg_names`, run in reverse: resolve each of a
    call/load_behavior node's arg names back to its real wire position, by re-deriving the
    same target-pnames lookup decompile.py used (never cached -- recomputed fresh here from
    the current `b`, same "always recompute" policy as everything else in this module)."""
    sub = node.hidden.get("sub")
    target_params = None
    if isinstance(sub, (int, float)) and not isinstance(sub, bool):
        if sub == -1:
            target_params = b.params
        elif sub > 0 and int(sub) - 1 < len(b.subs):
            target_params = b.subs[int(sub) - 1].params

    positions: dict[str, int] = {}
    if target_params:
        for i, p in enumerate(target_params, start=1):
            positions[p.name] = i
    for name in node.args:
        if name not in positions and name.startswith("arg"):
            try:
                positions[name] = int(name[3:])
            except ValueError:
                pass
    return positions


def _resolve_branch_target(target, positions: dict[str, int], is_last: bool):
    """`target` is what BsfNode.branches[pin] holds: a NODE_ID, "STOP", or None. Returns the
    raw wire value to write (an int position, or False), or the sentinel `_OMIT` meaning "don't
    set this key at all".

    The implicit-fallthrough case (`None`) never needs an explicit value -- the engine's own
    dispatcher advances to the physically next instruction on its own when a key is simply
    absent. `"STOP"` is ambiguous by construction (behavior_source_format.md's decompiler
    collapses an explicit `false` and "fell off the true end of the array" into the same `STOP`
    representation, since the real dispatcher treats them identically -- see `resolve_branch`)
    -- when this node is genuinely the last one in the compiled order, omitting the key
    reproduces that same "fell off the end" case exactly (and matches how real .dcs files are
    usually encoded); anywhere else in the middle of the array, `false` must be written
    explicitly, since simply having a next instruction physically follow would otherwise change
    the meaning to "fall through to it"."""
    if target is None:
        return _OMIT
    if target == "STOP":
        return _OMIT if is_last else False
    return positions[target]


_OMIT = object()


def _compile_one(engine, b: BsfBehavior, argcache: ArgCache, lua) -> "lupa._LuaTable":
    # Fresh id->position map, local to this call -- never threaded into a recursive `subs` call,
    # so nested sub-behaviors never leak into each other's (or the parent's) node-id namespace.
    positions = {node_id: i for i, node_id in enumerate(b.order, start=1)}

    last_pos = len(b.order)

    prog = lua.table()
    for node_id, pos in positions.items():
        node = b.nodes[node_id]
        is_last = pos == last_pos
        t = lua.table()
        t["op"] = node.op

        if node.op in DYNAMIC_ARG_OPS:
            arg_positions = _call_positions(b, node)
            for name, value in node.args.items():
                t[arg_positions[name]] = to_lua(value, lua)
        else:
            arg_pos = {}
            for i, atype, pin in arg_pin_names(node.op, argcache):
                if atype != "exec":
                    arg_pos[pin] = i
                elif pin in node.branches:
                    resolved = _resolve_branch_target(node.branches[pin], positions, is_last)
                    if resolved is not _OMIT:
                        t[i] = resolved
            for name, value in node.args.items():
                t[arg_pos[name]] = to_lua(value, lua)

        next_resolved = _resolve_branch_target(node.branches.get("next"), positions, is_last)
        if next_resolved is not _OMIT:
            t["next"] = next_resolved

        for field_name, value in node.hidden.items():
            t[field_name] = value

        prog[pos] = t

    prog["name"] = b.name

    if b.params:
        parameters = lua.table()
        pnames = lua.table()
        for i, p in enumerate(b.params, start=1):
            parameters[i] = p.is_output
            pnames[i] = p.name
        prog["parameters"] = parameters
        prog["pnames"] = pnames

    if b.keepvars:
        prog["keepvars"] = True

    if b.subs:
        deps = lua.table()
        for i, sub in enumerate(b.subs, start=1):
            deps[i] = _compile_one(engine, sub, argcache, lua)
        prog["dependencies"] = deps

    return prog


def compile_behavior(engine, b: BsfBehavior, argcache: ArgCache | None = None):
    argcache = argcache or ArgCache(engine)
    return _compile_one(engine, b, argcache, engine.lua)


def compile_dcs(engine, b: BsfBehavior, type_char: str = "C") -> str:
    table = compile_behavior(engine, b)
    return engine.encode_dcs(type_char, table)
