"""Analyze every real-world behavior/blueprint in corpus/*/index.jsonl for
control-flow fan-in and data-flow fan-out, to empirically ground the
tree-vs-graph pseudocode representation decision (see project memory/CLAUDE.md
"What This Is" for context -- this is not just a curiosity check).

Finds behaviors wherever they occur (top-level standalone, embedded in a
blueprint's c_behavior component extra_data, nested sub-behaviors under
`subs`/`dependencies`) via a generic structural search rather than hand-coding
per-type-char paths, since real corpus data showed the container shape isn't
uniform.

Usage: uv run python3 scripts/analyze_corpus.py [--json out.json]
"""

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

import lupa.lua54 as lupa

from desynced_toolkit import assets, dsc_wire
from desynced_toolkit.lua_runtime import LupaEngine

CORPUS_ROOT = Path(__file__).resolve().parent.parent / "corpus"
GAME_DATA = Path(
    __import__("os").environ.get(
        "DESYNCED_GAME_DATA",
        Path(__file__).resolve().parent.parent.parent / "desynced-game-data",
    )
)


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


def arg_type(argdef):
    if isinstance(argdef, list):
        return argdef[0] if argdef else None
    if isinstance(argdef, dict):
        return argdef.get(1)
    return None


def looks_like_behavior(node) -> bool:
    if not isinstance(node, dict):
        return False
    int_keys = [k for k in node if isinstance(k, int)]
    if not int_keys:
        return False
    sample = node[min(int_keys)]
    return isinstance(sample, dict) and "op" in sample


def find_behaviors(node, path="root", out=None):
    """Recursively yield (path, behavior_dict) for every behavior-shaped table found."""
    if out is None:
        out = []
    if not isinstance(node, (dict, list)):
        return out
    if looks_like_behavior(node):
        out.append((path, node))
    items = node.items() if isinstance(node, dict) else enumerate(node)
    for k, v in items:
        if isinstance(v, (dict, list)):
            find_behaviors(v, f"{path}.{k}", out)
    return out


class ArgCache:
    def __init__(self, engine: LupaEngine):
        self.engine = engine
        self._cache: dict[str, list] = {}

    def get(self, op: str) -> list:
        if op not in self._cache:
            d = self.engine.data.instructions[op]
            args = to_py(d.args) if d is not None and d.args is not None else []
            self._cache[op] = args if isinstance(args, list) else []
        return self._cache[op]


def analyze_behavior(behavior: dict, argcache: ArgCache) -> dict:
    insts = {k: v for k, v in behavior.items() if isinstance(k, int) and isinstance(v, dict)}
    n = len(insts)

    edges = []  # (source_idx, desc, target)
    terminations = 0
    var_sites = Counter()  # variable name -> occurrence count
    op_counts = Counter()
    free_floating = 0

    def resolve_exec_target(val, idx):
        """Per behavior_format.md: an omitted (nil) exec arg -- top-level
        `next` or a per-instruction slot like check_number's If Larger/If
        Smaller -- independently defaults to falling through to the
        physically next instruction. `false` is real termination (pops to
        the enclosing block; not modeled further here). An explicit int is a
        real jump target."""
        if type(val) is int:
            return val
        if val is False:
            return "TERMINATE"
        if idx + 1 in insts:
            return idx + 1
        return "TERMINATE"  # falls off the true end

    for idx, inst in insts.items():
        op = inst.get("op")
        op_counts[op] += 1
        if inst.get("nx") is not None or inst.get("ny") is not None:
            free_floating += 1

        argdefs = argcache.get(op)
        for i, argdef in enumerate(argdefs, start=1):
            if arg_type(argdef) == "exec":
                tgt = resolve_exec_target(inst.get(i), idx)
                if tgt == "TERMINATE":
                    terminations += 1
                else:
                    edges.append((idx, f"{op}#{i}", tgt))
            elif isinstance(inst.get(i), str):
                var_sites[inst[i]] += 1

        nxt = resolve_exec_target(inst.get("next"), idx)
        if nxt == "TERMINATE":
            terminations += 1
        else:
            edges.append((idx, f"{op}(next)", nxt))

    fanin = Counter()
    for _, _, t in edges:
        fanin[t] += 1
    merge_points = {t: c for t, c in fanin.items() if c > 1}

    return {
        "n_instructions": n,
        "n_exec_edges": len(edges),
        "n_terminations": terminations,
        "n_merge_points": len(merge_points),
        "max_fanin": max(fanin.values()) if fanin else 0,
        "uses_jump_label": bool(op_counts["jump"] or op_counts["label"]),
        "uses_call": op_counts["call"] > 0,
        "n_calls": op_counts["call"],
        "uses_for_number": op_counts["for_number"] > 0,
        "uses_sequence": op_counts["sequence"] > 0,
        "n_free_floating_nodes": free_floating,
        "n_distinct_vars": len(var_sites),
        "var_site_counts": list(var_sites.values()),
        "op_counts": dict(op_counts),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", type=Path, default=None, help="write per-behavior stats to this JSON file")
    args = parser.parse_args()

    src = assets.open_asset_source(str(GAME_DATA))
    engine = LupaEngine(src)
    argcache = ArgCache(engine)
    lua = engine.lua

    records = []
    for index_path in sorted(CORPUS_ROOT.glob("*/index.jsonl")):
        source_dir = index_path.parent
        for line in index_path.read_text().splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            dsc_path = source_dir / rec["file"]
            if not dsc_path.exists():
                continue
            raw = dsc_path.read_text().strip()
            try:
                _, table = dsc_wire.decode_dsc(lua, raw)
            except Exception as e:
                print(f"[skip] {dsc_path}: decode failed: {e}")
                continue

            root = to_py(table)
            behaviors = find_behaviors(root)
            for path, behavior in behaviors:
                stats = analyze_behavior(behavior, argcache)
                stats["corpus_source"] = source_dir.name
                stats["origin_file"] = rec["file"]
                stats["behavior_path"] = path
                stats["name"] = rec.get("name")
                records.append(stats)

    print(f"\nAnalyzed {len(records)} behaviors (including nested sub-behaviors) from {sum(1 for _ in CORPUS_ROOT.glob('*/index.jsonl'))} corpus sources.\n")

    trivial = [r for r in records if r["n_instructions"] == 0]
    real = [r for r in records if r["n_instructions"] > 0]
    print(f"  {len(trivial)} empty/trivial (0 instructions -- likely blueprint containers with no behavior found separately)")
    print(f"  {len(real)} with >=1 instruction\n")

    with_merges = [r for r in real if r["n_merge_points"] > 0]
    print(f"CONTROL-FLOW FAN-IN (the core tree-vs-graph question):")
    print(f"  {len(with_merges)} / {len(real)} behaviors ({100*len(with_merges)/len(real):.1f}%) have >=1 real merge point (instruction with >1 incoming exec edge)")
    if with_merges:
        max_fanins = [r["max_fanin"] for r in with_merges]
        print(f"  max fan-in seen: {max(max_fanins)}; median among behaviors-with-merges: {statistics.median(max_fanins)}")
    total_merge_points = sum(r["n_merge_points"] for r in real)
    print(f"  total merge points across corpus: {total_merge_points}")

    print(f"\nCOMPUTED/NON-STRUCTURED DISPATCH:")
    n_jump = sum(1 for r in real if r["uses_jump_label"])
    print(f"  {n_jump} / {len(real)} ({100*n_jump/len(real):.1f}%) use jump/label computed dispatch")

    print(f"\nCALLS / SUB-BEHAVIORS:")
    n_call = sum(1 for r in real if r["uses_call"])
    print(f"  {n_call} / {len(real)} ({100*n_call/len(real):.1f}%) use call")

    print(f"\nLOOPS:")
    n_for = sum(1 for r in real if r["uses_for_number"])
    n_seq = sum(1 for r in real if r["uses_sequence"])
    print(f"  for_number: {n_for} / {len(real)} ({100*n_for/len(real):.1f}%)")
    print(f"  sequence:   {n_seq} / {len(real)} ({100*n_seq/len(real):.1f}%)")

    print(f"\nFREE-FLOATING NODE POSITIONS (nx/ny set -- user deviated from auto-layout):")
    n_ff = sum(1 for r in real if r["n_free_floating_nodes"] > 0)
    print(f"  {n_ff} / {len(real)} ({100*n_ff/len(real):.1f}%) have at least one explicitly-positioned node")

    print(f"\nDATA-FLOW FAN-OUT (named variable reuse):")
    all_var_sites = [c for r in real for c in r["var_site_counts"]]
    multi_use = [c for c in all_var_sites if c > 1]
    print(f"  {len(all_var_sites)} distinct variables total across corpus; {len(multi_use)} ({100*len(multi_use)/len(all_var_sites):.1f}%) used in >1 place")
    if multi_use:
        print(f"  median use-sites for a multi-use variable: {statistics.median(multi_use)}; max: {max(multi_use)}")

    print(f"\nSIZE DISTRIBUTION:")
    sizes = sorted(r["n_instructions"] for r in real)
    print(f"  min={sizes[0]} median={statistics.median(sizes)} mean={statistics.mean(sizes):.1f} max={sizes[-1]}")

    all_ops = Counter()
    for r in real:
        all_ops.update(r["op_counts"])
    print(f"\nTOP 15 MOST COMMON INSTRUCTIONS ACROSS CORPUS:")
    for op, c in all_ops.most_common(15):
        print(f"  {op}: {c}")

    if args.json:
        args.json.write_text(json.dumps(records, indent=2))
        print(f"\nWrote per-behavior stats to {args.json}")


if __name__ == "__main__":
    main()
