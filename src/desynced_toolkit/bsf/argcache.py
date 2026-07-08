"""Live-Lua-backed lookup of each op's real argument list (type/name/desc), and the shared
3-way exec-branch resolution rule. `data.instructions[op].args` (via a `LupaEngine`) is the
sole authoritative source for this -- never `instructions_index.md`, which is auto-generated
FROM this same data for humans and is not meant to be parsed by tooling."""

from __future__ import annotations

from ..lua_util import to_py


def arg_type_name_desc(argdef):
    """An arg definition entry is either a positional list (`{type, name, desc}`) or a dict
    with the same fields keyed 1/2/3 -- both real shapes seen in `data.instructions`."""
    if isinstance(argdef, list):
        return (argdef + [None, None, None])[:3]
    if isinstance(argdef, dict):
        return argdef.get(1), argdef.get(2), argdef.get(3)
    return None, None, None


class ArgCache:
    """Caches each op's `data.instructions[op].args` list (converted to plain Python), keyed by
    op name, so repeated lookups across many instructions don't re-walk the Lua table."""

    def __init__(self, engine):
        self.engine = engine
        self._cache = {}

    def get(self, op):
        if op not in self._cache:
            d = self.engine.data.instructions[op]
            args = to_py(d.args) if d is not None and d.args is not None else []
            self._cache[op] = args if isinstance(args, list) else []
        return self._cache[op]


def arg_pin_names(op: str, argcache: "ArgCache") -> list[tuple[int, str, str]]:
    """Returns `[(position, atype, pin_name), ...]` for op's declared args, in position order.
    A few real ops declare two args with the *same* display name at different positions (e.g.
    `for_signal_match` has an "in" Signal at position 1 and an "out" Signal at position 3) --
    BSF represents every arg as a unique `Name=value` pair, so the 2nd+ occurrence of a given
    base name is disambiguated with its own position as a suffix. Both decompile.py and
    compile.py call this (never duplicate the rule inline), so the same op always gets the same
    name<->position mapping in both directions without needing to store anything extra in the
    IR."""
    seen = set()
    result = []
    for i, argdef in enumerate(argcache.get(op), start=1):
        atype, aname, _ = arg_type_name_desc(argdef)
        base = aname or f"arg{i}"
        name = base if base not in seen else f"{base}{i}"
        seen.add(base)
        result.append((i, atype, name))
    return result


def resolve_branch(val, idx, insts):
    """Resolve one exec-typed slot's raw wire value (the top-level `next` field, or a numbered
    exec arg like check_number's "If Larger") to the value `BsfNode.branches[pin]` should hold,
    per behavior_source_format.md's "Control edges" 3-way rule:

    - explicit int wire position -> returned as-is (an int); the caller maps this to the
      destination node's NODE_ID once the full idx->id table is built.
    - explicit `False` -> "STOP" (a real, meaningful authorial choice -- pop to the enclosing
      loop/call context, or restart from Program Start if neither is active; never a bare "halt"
      on its own).
    - omitted entirely (val is None) -> `None` if the physically-next instruction exists (a
      plain implicit fallthrough -- BSF renders no annotation for this at all), else "STOP"
      (falling off the true end of the array is a real dead end too, handled identically to an
      explicit `False` by the real dispatcher).

    `insts` is the raw idx->instruction-dict mapping for the *current* behavior/sub being
    decompiled, used only to check whether idx+1 exists."""
    if type(val) is int:
        return val
    if val is False:
        return "STOP"
    if idx + 1 in insts:
        return None
    return "STOP"
