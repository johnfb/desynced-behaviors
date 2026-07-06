"""Render a real corpus behavior into three candidate textual notations (DOT,
Mermaid, and a compact custom listing) for comparing tree-vs-graph
representations concretely, rather than in the abstract.

Usage: uv run python3 scripts/render_examples.py <dsc_file> <behavior_path> <out_prefix>
Example: uv run python3 scripts/render_examples.py \
    corpus/discord_behaviors/83c5f19f875b2575_C_Hedgehog_s_Upgrader.dsc \
    root.dependencies.0 /tmp/small
"""

import sys
from pathlib import Path

import lupa.lua54 as lupa

from desynced_toolkit import assets, dsc_wire
from desynced_toolkit.lua_runtime import LupaEngine

GAME_DATA = Path(__file__).resolve().parent.parent.parent / "desynced-game-data"


def to_py(t, seen=None):
    if lupa.lua_type(t) != "table":
        return t
    seen = seen if seen is not None else set()
    if id(t) in seen:
        return "<cycle>"
    seen = seen | {id(t)}
    keys = list(t.keys())
    if keys and all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1)):
        return [to_py(v, seen) for v in (t[k] for k in sorted(keys))]
    return {k: to_py(t[k], seen) for k in keys}


def navigate(root, path: str):
    node = root
    parts = path.split(".")[1:]  # skip "root"
    for p in parts:
        node = node[int(p)] if p.isdigit() else node[p]
    return node


def arg_type_name_desc(argdef):
    if isinstance(argdef, list):
        return (argdef + [None, None, None])[:3]
    if isinstance(argdef, dict):
        return argdef.get(1), argdef.get(2), argdef.get(3)
    return None, None, None


def resolve_value(v, nparams: int) -> str:
    if isinstance(v, str):
        return f"var:{v}"
    if isinstance(v, bool):
        return "false" if v is False else str(v)
    if isinstance(v, int):
        if v < 0:
            return f"framereg[{-v}]"
        if 1 <= v <= nparams:
            return f"param{v}"
        return str(v)
    if isinstance(v, dict):
        if "num" in v and len(v) == 1:
            return f"num:{v['num']}"
        if "coord" in v:
            c = v["coord"]
            return f"coord:({c.get('x') if isinstance(c, dict) else c[0]},{c.get('y') if isinstance(c, dict) else c[1]})"
        if "id" in v:
            return f"id:{v['id']}"
        return f"literal:{v}"
    if v is None:
        return "?"
    return str(v)


class ArgCache:
    def __init__(self, engine):
        self.engine = engine
        self._cache = {}

    def get(self, op):
        if op not in self._cache:
            d = self.engine.data.instructions[op]
            args = to_py(d.args) if d is not None and d.args is not None else []
            self._cache[op] = args if isinstance(args, list) else []
        return self._cache[op]


def label_key(val):
    """Normalize a jump/label 'Label' argument value to a hashable key for
    matching -- computed dispatch matches on the id/num value at runtime, not
    on a raw instruction index (see behavior_format.md's jump/label pair)."""
    if isinstance(val, dict):
        if "id" in val:
            return ("id", val["id"])
        if "num" in val:
            return ("num", val["num"])
        return None
    if isinstance(val, (str, int, float)):
        return ("lit", val)
    return None


def build_graph(behavior: dict, argcache: ArgCache):
    nparams = len(behavior.get("parameters") or [])
    insts = {k: v for k, v in behavior.items() if isinstance(k, int) and isinstance(v, dict)}

    nodes = {}  # idx -> label string
    control_edges = []  # (src, dst, label)
    label_defs = {}  # label_key -> instruction idx that defines it
    jump_refs = []  # (jump_idx, label_key)

    def resolve_exec_target(val, idx, aname):
        """Per behavior_format.md: an omitted (nil) exec arg -- whether it's
        the top-level `next` or a per-instruction exec slot like check_number's
        If Larger/If Smaller -- independently defaults to falling through to
        the physically next instruction. `false` means real termination
        (pops to the enclosing block; not modeled further here). An explicit
        int is a real jump target."""
        if type(val) is int:
            return val, aname  # explicit, intentional wire -- keep the real pin name
        if val is False:
            return None, None  # real termination, no edge
        # omitted entirely -> implicit fallthrough, not a meaningful branch
        if idx + 1 in insts:
            return idx + 1, None
        return None, None  # falls off the true end

    for idx, inst in sorted(insts.items()):
        op = inst.get("op")
        argdefs = argcache.get(op)
        parts_in_out = []
        for i, argdef in enumerate(argdefs, start=1):
            atype, aname, _ = arg_type_name_desc(argdef)
            if atype == "exec":
                tgt, label = resolve_exec_target(inst.get(i), idx, aname or f"arg{i}")
                if tgt is not None:
                    control_edges.append((idx, tgt, label))
            else:
                val = inst.get(i)
                if val is not None:
                    parts_in_out.append(f"{aname or i}={resolve_value(val, nparams)}")
                    if op == "label" and aname == "Label":
                        k = label_key(val)
                        if k is not None:
                            label_defs[k] = idx
                    elif op == "jump" and aname == "Label":
                        k = label_key(val)
                        if k is not None:
                            jump_refs.append((idx, k))

        tgt, label = resolve_exec_target(inst.get("next"), idx, None)
        if tgt is not None:
            control_edges.append((idx, tgt, label))

        nodes[idx] = f"{idx}: {op}(" + ", ".join(parts_in_out) + ")"

    # Computed jump -> label edges: resolved statically here by matching the
    # same id/num value within one behavior (the real runtime dispatch is a
    # value comparison, not a stored index -- see behavior_format.md).
    for jump_idx, k in jump_refs:
        target = label_defs.get(k)
        if target is not None:
            control_edges.append((jump_idx, target, "jump→label"))

    return nodes, control_edges


def to_dot(nodes, edges, title) -> str:
    lines = [f'digraph "{title}" {{', "  rankdir=TB;", '  node [shape=box, fontsize=10];']
    for idx, label in nodes.items():
        safe = label.replace('"', '\\"')
        lines.append(f'  n{idx} [label="{safe}"];')
    for src, dst, label in edges:
        attrs = f' [label="{label}"]' if label else ""
        lines.append(f"  n{src} -> n{dst}{attrs};")
    lines.append("}")
    return "\n".join(lines)


def to_mermaid(nodes, edges, title) -> str:
    lines = [f"%% {title}", "flowchart TD"]
    for idx, label in nodes.items():
        safe = label.replace('"', "'")
        lines.append(f'  n{idx}["{safe}"]')
    for src, dst, label in edges:
        if label:
            lines.append(f"  n{src} -->|{label}| n{dst}")
        else:
            lines.append(f"  n{src} --> n{dst}")
    return "\n".join(lines)


def to_compact(nodes, edges, title) -> str:
    """Adjacency-implicit listing: a plain fallthrough to idx+1 is left
    implicit (no annotation needed); anything else (named branch, or a
    fallthrough to a non-adjacent index) is called out explicitly."""
    by_src = {}
    for src, dst, label in edges:
        by_src.setdefault(src, []).append((dst, label))

    lines = [f"# {title}"]
    for idx, label in nodes.items():
        branch_notes = []
        for dst, elabel in by_src.get(idx, []):
            if elabel is None and dst == idx + 1:
                continue  # implicit plain fallthrough, no annotation needed
            tag = elabel if elabel else "next"
            branch_notes.append(f">{dst} ({tag})")
        suffix = "  " + " ".join(branch_notes) if branch_notes else ""
        lines.append(f"{label}{suffix}")
    return "\n".join(lines)


def main():
    dsc_path, behavior_path, out_prefix = sys.argv[1], sys.argv[2], sys.argv[3]

    src = assets.open_asset_source(str(GAME_DATA))
    engine = LupaEngine(src)
    argcache = ArgCache(engine)
    lua = engine.lua

    raw = Path(dsc_path).read_text().strip()
    _, table = dsc_wire.decode_dsc(lua, raw)
    root = to_py(table)
    behavior = navigate(root, behavior_path)

    title = behavior.get("name") or Path(dsc_path).stem
    nodes, edges = build_graph(behavior, argcache)

    dot_src = to_dot(nodes, edges, title)
    mmd_src = to_mermaid(nodes, edges, title)
    compact_src = to_compact(nodes, edges, title)

    Path(f"{out_prefix}.dot").write_text(dot_src)
    Path(f"{out_prefix}.mmd").write_text(mmd_src)
    Path(f"{out_prefix}.compact.txt").write_text(compact_src)

    print(f"{len(nodes)} nodes, {len(edges)} edges -> wrote {out_prefix}.{{dot,mmd,compact.txt}}")


if __name__ == "__main__":
    main()
