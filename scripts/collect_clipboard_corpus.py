"""Watch the (shared VirtualBox) clipboard and harvest every decodable .dsc
string that appears, for building a real-world behavior/blueprint corpus from
manually copy-pasted Discord forum threads.

Run this yourself in a terminal while browsing the Discord forum, doing
select-all + copy on each thread you want. Ctrl+C to stop.

Usage: uv run python3 scripts/collect_clipboard_corpus.py
"""

import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import lupa.lua54 as lupa

from desynced_toolkit import dsc_wire

CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus" / "discord_behaviors"
CONTEXT_DIR = CORPUS_DIR / "context"
INDEX_PATH = CORPUS_DIR / "index.jsonl"
CANDIDATE_RE = re.compile(r"DS[A-Za-z0-9]{80,}")


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")[:60] or "unnamed"


def get_clipboard() -> str:
    result = subprocess.run(
        ["xclip", "-o", "-selection", "clipboard"],
        capture_output=True,
        text=True,
    )
    return result.stdout


def summarize(table) -> dict:
    keys = list(table.keys())
    int_keys = sorted(k for k in keys if isinstance(k, int))
    other_keys = [k for k in keys if not isinstance(k, int)]
    name = table["name"] if "name" in keys else None
    return {
        "name": name,
        "top_level_int_keys": len(int_keys),
        "other_keys": other_keys,
    }


def main() -> None:
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    lua = lupa.LuaRuntime()

    seen_hashes = set()
    if INDEX_PATH.exists():
        for line in INDEX_PATH.read_text().splitlines():
            if line.strip():
                seen_hashes.add(json.loads(line)["hash"])

    print(f"Watching clipboard. Corpus dir: {CORPUS_DIR}")
    print(f"Already have {len(seen_hashes)} entries. Ctrl+C to stop.")

    last_clip = get_clipboard()
    while True:
        time.sleep(1)
        try:
            clip = get_clipboard()
        except FileNotFoundError:
            print("xclip not found -- is it installed?", file=sys.stderr)
            return
        if clip == last_clip:
            continue
        last_clip = clip

        candidates = CANDIDATE_RE.findall(clip)
        if not candidates:
            continue

        batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        new_items = []
        for cand in candidates:
            h = hashlib.sha256(cand.encode()).hexdigest()[:16]
            if h in seen_hashes:
                continue
            try:
                type_char, table = dsc_wire.decode_dsc(lua, cand)
            except Exception as e:
                print(f"  [skip] undecodable candidate ({len(cand)} chars): {e}")
                continue

            info = summarize(table)
            seen_hashes.add(h)
            new_items.append((h, cand, type_char, info))

        if new_items:
            # One context file per paste (not per behavior) -- the raw clipboard
            # text (thread title, author, description, iteration notes, etc.)
            # surrounding whichever .dsc string(s) it contained. This is the
            # closest thing to a README/commit-message this corpus has, and
            # costs nothing extra to keep since it's already in the paste.
            context_fname = f"{batch_id}.txt"
            (CONTEXT_DIR / context_fname).write_text(clip)

        for h, cand, type_char, info in new_items:
            fname = f"{h}_{type_char}_{safe_name(info['name'] or 'unnamed')}.dsc"
            (CORPUS_DIR / fname).write_text(cand)

            record = {
                "hash": h,
                "file": fname,
                "type_char": type_char,
                "batch_id": batch_id,
                "context_file": f"context/{context_fname}",
                **info,
            }
            with INDEX_PATH.open("a") as f:
                f.write(json.dumps(record) + "\n")

            print(f"  [saved] {type_char} {info['name']!r} ({info['top_level_int_keys']} insts) -> {fname}")

        new_count = len(new_items)

        if new_count == 0:
            print("  (clipboard changed, no new decodable strings)")
        else:
            print(f"  batch {batch_id}: {new_count} new / {len(candidates)} candidates in this paste")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
