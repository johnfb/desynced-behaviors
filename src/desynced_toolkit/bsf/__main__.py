"""CLI for round-tripping a real .dcs clipboard string through BSF text -- see
behavior_source_format.md for the grammar. Meant to sit directly in a shell pipeline with the
game's own clipboard, e.g. (with `cb` a wrapper script for `xclip -selection clipboard`):

    cb -o | python -m desynced_toolkit.bsf decompile > mybehavior.bsf
    # ...edit mybehavior.bsf by hand...
    python -m desynced_toolkit.bsf compile < mybehavior.bsf | cb -i

Only handles a top-level behavior/program clipboard item (.dcs type char 'C', the "Copy
Program" action in the in-game editor) -- a blueprint ('B', with components/frames around it)
decodes to a different table shape that decompile_behavior does not expect.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from desynced_toolkit import LupaEngine, open_asset_source
from desynced_toolkit.bsf import bsf_to_dcs, dcs_to_bsf, semantic_diff_dcs

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_GAME_DATA_DIR = REPO_ROOT.parent / "desynced-game-data"


def _make_engine(game_data: str | None) -> LupaEngine:
    game_data_dir = game_data or os.environ.get("DESYNCED_GAME_DATA", str(DEFAULT_GAME_DATA_DIR))
    if not os.path.exists(game_data_dir):
        print(
            f"error: game data extract not found at {game_data_dir}\n"
            "(set --game-data or the DESYNCED_GAME_DATA env var)",
            file=sys.stderr,
        )
        sys.exit(1)
    return LupaEngine(open_asset_source(game_data_dir))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m desynced_toolkit.bsf")
    parser.add_argument("--game-data", help="path to the game data extract (default: sibling desynced-game-data dir, or $DESYNCED_GAME_DATA)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_decompile = sub.add_parser("decompile", help="stdin: .dcs string -> stdout: BSF text")
    p_decompile.add_argument("--input", type=argparse.FileType("r"), default=sys.stdin)
    p_decompile.add_argument("--output", type=argparse.FileType("w"), default=sys.stdout)

    p_compile = sub.add_parser("compile", help="stdin: BSF text -> stdout: .dcs string")
    p_compile.add_argument("--input", type=argparse.FileType("r"), default=sys.stdin)
    p_compile.add_argument("--output", type=argparse.FileType("w"), default=sys.stdout)
    p_compile.add_argument("--type", default="C", help="wire type char to encode (default: C, a behavior/program)")

    p_diff = sub.add_parser(
        "semantic-diff",
        help="two .dcs files -> stdout: human-readable diff, ignoring wire-position-only encoding differences",
    )
    p_diff.add_argument("old", type=argparse.FileType("r"), help="path to the earlier .dcs file")
    p_diff.add_argument("new", type=argparse.FileType("r"), help="path to the later .dcs file")

    args = parser.parse_args(argv)
    engine = _make_engine(args.game_data)

    if args.command == "decompile":
        dcs_str = args.input.read().strip()
        bsf_text = dcs_to_bsf(engine, dcs_str)
        args.output.write(bsf_text)
    elif args.command == "compile":
        bsf_text = args.input.read()
        dcs_str = bsf_to_dcs(engine, bsf_text, args.type)
        args.output.write(dcs_str)
        args.output.write("\n")
    elif args.command == "semantic-diff":
        old_dcs = args.old.read().strip()
        new_dcs = args.new.read().strip()
        report = semantic_diff_dcs(engine, old_dcs, new_dcs)
        print(report if report else "(no semantic differences)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
