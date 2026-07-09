"""Real Lua behavior table -> BsfBehavior. The reverse of bsf/compile.py."""

from __future__ import annotations

import lupa.lua54 as lupa

from .argcache import DYNAMIC_ARG_OPS, ArgCache, arg_pin_names, resolve_branch
from .ir import BsfBehavior, BsfNode, BsfParam
from .values import from_lua

# behavior_format.md's "Hidden literal fields (make_asm)" table: op -> the plain named key
# (not part of data.instructions[op].args, so ArgCache never sees it) that op uses for its one
# configured-on-the-node value.
HIDDEN_FIELD_TABLE = {
    "call": "sub",
    "load_behavior": "sub",
    "domove": "c",
    "moveaway_range": "c",
    "scout": "c",
    "dodrop": "c",
    "dopickup": "c",
    "request_item": "c",
    "request_wait": "c",
    "for_producers_items": "c",
    "bitwise_op": "c",
    "lock_slots": "c",
    "for_signal_match": "c",
    "count_item": "c",
    "get_unit_info": "c",
    "get_unit_power_info": "c",
    "get_item_info": "c",
    "count_slots": "c",
    "notify": "txt",
    "set_signpost": "txt",
}

def _int_keys(table) -> list[int]:
    return sorted(k for k in table.keys() if isinstance(k, int))


def _sub_behaviors_table(table):
    """Both `dependencies` (standalone exported behavior) and `subs` (behavior embedded in a
    blueprint's c_behavior component) have been observed for the same concept in real corpus
    data and have not been reconciled -- treat both as the same thing."""
    keys = set(table.keys())
    if "dependencies" in keys:
        return table["dependencies"]
    if "subs" in keys:
        return table["subs"]
    return None


def _params_from_table(table) -> list[BsfParam]:
    """Slot count and names are trusted straight from the wire declaration (`parameters`'s own
    length, `pnames` for display names) -- but NOT `parameters[i]`'s truthy/falsy bit itself,
    which is only a UI-drawing hint (see `argcache.written_param_slots`'s docstring), not
    something this IR stores at all. Direction is computed fresh from usage wherever it's
    actually needed (rendering, compiling), never here."""
    keys = set(table.keys())
    if "parameters" not in keys:
        return []
    parameters = table["parameters"]
    pnames = table["pnames"] if "pnames" in keys else None
    result = []
    for i in _int_keys(parameters):
        name = pnames[i] if pnames is not None and i in set(pnames.keys()) else f"param{i}"
        result.append(BsfParam(name=name))
    return result


def _call_arg_names(table, inst, argcache: ArgCache) -> dict[int, str]:
    """Resolve display names for a call/load_behavior instruction's dynamic positional args,
    per behavior_source_format.md's 3-way `sub` rule. Returns {position: name}; a position not
    resolvable (no visible pnames) gets the generic `arg{position}` fallback."""
    sub = inst["sub"] if "sub" in set(inst.keys()) else False
    target_pnames = None
    if isinstance(sub, bool):
        pass  # `false`/unset -- nothing to resolve against
    elif isinstance(sub, (int, float)) and sub == -1:
        target_pnames = table["pnames"] if "pnames" in set(table.keys()) else None
    elif isinstance(sub, (int, float)) and sub > 0:
        subs_table = _sub_behaviors_table(table)
        if subs_table is not None and int(sub) in set(subs_table.keys()):
            target = subs_table[int(sub)]
            target_pnames = target["pnames"] if "pnames" in set(target.keys()) else None
    # else: string (external saved-library id) -- genuinely unresolvable, no pnames visible

    names = {}
    for i in _int_keys(inst):
        if target_pnames is not None and i in set(target_pnames.keys()):
            names[i] = target_pnames[i]
        else:
            names[i] = f"arg{i}"
    return names


def decompile_behavior(engine, table, argcache: ArgCache | None = None) -> BsfBehavior:
    """Decompile one real Lua behavior table (as returned by dcs_wire.decode_dcs, or one entry
    of a `dependencies`/`subs` array) into a BsfBehavior graph. Recurses into embedded
    sub-behaviors automatically -- each gets its own independent NODE_ID namespace."""
    argcache = argcache or ArgCache(engine)
    keys = set(table.keys())

    insts = {}
    for idx in _int_keys(table):
        v = table[idx]
        if lupa.lua_type(v) == "table":
            insts[idx] = v

    idx_to_id = {idx: f"n{idx}" for idx in insts}

    nodes: dict[str, BsfNode] = {}
    order: list[str] = []
    for idx in sorted(insts):
        inst = insts[idx]
        inst_keys = set(inst.keys())
        op = inst["op"]
        node_id = idx_to_id[idx]
        node = BsfNode(id=node_id, op=op)

        if op in DYNAMIC_ARG_OPS:
            names = _call_arg_names(table, inst, argcache)
            for i in _int_keys(inst):
                node.args[names[i]] = from_lua(inst[i])
        else:
            for i, atype, pin in arg_pin_names(op, argcache):
                if atype == "exec":
                    # Always resolve, whether the key is present or not -- an absent exec key
                    # still needs the omitted/falls-off-the-end distinction from resolve_branch,
                    # not just a skip (a value arg with an absent key genuinely has nothing to
                    # record, but an exec pin's *absence* is itself meaningful).
                    target = resolve_branch(inst[i] if i in inst_keys else None, idx, insts)
                    node.branches[pin] = idx_to_id[target] if isinstance(target, int) else target
                elif i in inst_keys:
                    node.args[pin] = from_lua(inst[i])

        next_target = resolve_branch(inst["next"] if "next" in inst_keys else None, idx, insts)
        node.branches["next"] = idx_to_id[next_target] if isinstance(next_target, int) else next_target

        hidden_field = HIDDEN_FIELD_TABLE.get(op)
        if hidden_field is not None and hidden_field in inst_keys:
            node.hidden[hidden_field] = inst[hidden_field]
        if "cmt" in inst_keys:
            node.hidden["cmt"] = inst["cmt"]

        nodes[node_id] = node
        order.append(node_id)

    subs = []
    subs_table = _sub_behaviors_table(table)
    if subs_table is not None:
        for i in _int_keys(subs_table):
            subs.append(decompile_behavior(engine, subs_table[i], argcache))

    return BsfBehavior(
        name=table["name"] if "name" in keys else "",
        params=_params_from_table(table),
        desc=None,  # no wire-level field found on any real fixture -- see plan's "Deferred"
        keepvars=bool(table["keepvars"]) if "keepvars" in keys else False,
        nodes=nodes,
        order=order,
        subs=subs,
    )


def decompile_dcs(engine, dcs_str: str) -> BsfBehavior:
    _, table = engine.decode_dcs(dcs_str)
    return decompile_behavior(engine, table)
