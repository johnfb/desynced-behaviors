"""Decompile a real behavior out of a .dcs clipboard string into real BSF text and a Mermaid
flowchart, via the `desynced_toolkit.bsf` package (see behavior_source_format.md for the
grammar). This script used to own the decoding/graph-extraction logic itself as a one-way
prototype; that logic has since grown into the real `bsf` package (decompile + compile + text
parse/render + mermaid render, see the BSF implementation plan) and this script is now a thin
CLI wrapper over it.

Usage: uv run python3 scripts/render_examples.py <dcs_file> <behavior_path> <out_prefix>
Example: uv run python3 scripts/render_examples.py \
    corpus/discord_behaviors/83c5f19f875b2575_C_Hedgehog_s_Upgrader.dcs \
    root.dependencies.0 /tmp/small

Writes <out_prefix>.bsf.txt (the real BSF listing) and <out_prefix>.mmd (Mermaid flowchart).
"""

import sys
from pathlib import Path

from desynced_toolkit import assets
from desynced_toolkit.bsf.decompile import decompile_behavior
from desynced_toolkit.bsf.render_mermaid import render_mermaid
from desynced_toolkit.bsf.render_text import render_behavior
from desynced_toolkit.lua_runtime import LupaEngine

GAME_DATA = Path(__file__).resolve().parent.parent.parent / "desynced-game-data"


def navigate(root, path: str):
    node = root
    parts = path.split(".")[1:]  # skip "root"
    for p in parts:
        node = node[int(p)] if p.isdigit() else node[p]
    return node


def main():
    dcs_path, behavior_path, out_prefix = sys.argv[1], sys.argv[2], sys.argv[3]

    src = assets.open_asset_source(str(GAME_DATA))
    engine = LupaEngine(src)

    raw = Path(dcs_path).read_text().strip()
    _, table = engine.decode_dcs(raw)
    behavior_table = navigate(table, behavior_path) if behavior_path != "root" else table

    b = decompile_behavior(engine, behavior_table)

    bsf_text = render_behavior(b)
    mmd_src = render_mermaid(b)

    Path(f"{out_prefix}.bsf.txt").write_text(bsf_text)
    Path(f"{out_prefix}.mmd").write_text(mmd_src)

    print(f"{len(b.nodes)} nodes, {len(b.subs)} sub-behaviors -> wrote {out_prefix}.{{bsf.txt,mmd}}")


if __name__ == "__main__":
    main()
