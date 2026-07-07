"""Scrape a Steam Community discussion thread for shared .dcs behavior/blueprint
strings, pairing each with the comment text (author + description) it came
from. Steam discussion pages are plain server-rendered HTML (no login, no JS
needed) and paginate via a `?ctp=N` query param.

Usage: uv run python3 scripts/collect_steam_forum.py <discussion_url>
"""

import hashlib
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import lupa.lua54 as lupa

from desynced_toolkit import dcs_wire

CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus" / "steam_behaviors"
CONTEXT_DIR = CORPUS_DIR / "context"
INDEX_PATH = CORPUS_DIR / "index.jsonl"
CANDIDATE_RE = re.compile(r"DS[A-Za-z0-9]{80,}")
TAG_RE = re.compile(r"<[^>]+>")

COMMENT_MARKER = 'class="commentthread_comment_text"'
AUTHOR_MARKER = 'class="commentthread_comment_author"'
AUTHOR_LINK_MARKER = "commentthread_author_link"
BDI_RE = re.compile(r"<bdi>(.*?)</bdi>", re.DOTALL)


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")[:60] or "unnamed"


def strip_html(fragment: str) -> str:
    return html.unescape(TAG_RE.sub(" ", fragment)).strip()


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_comments(page_html: str) -> list[tuple[str, str]]:
    """Returns [(author, comment_text), ...] for one page."""
    comments = []
    positions = [m.start() for m in re.finditer(re.escape(COMMENT_MARKER), page_html)]
    for i, pos in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(page_html)
        block = page_html[pos:end]
        text = strip_html(block)

        author = "unknown"
        author_pos = page_html.rfind(AUTHOR_MARKER, 0, pos)
        if author_pos != -1:
            link_pos = page_html.find(AUTHOR_LINK_MARKER, author_pos, pos)
            if link_pos != -1:
                m = BDI_RE.search(page_html, link_pos, pos)
                if m:
                    author = strip_html(m.group(1))[:60] or "unknown"

        comments.append((author, text))
    return comments


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: collect_steam_forum.py <discussion_url>", file=sys.stderr)
        sys.exit(1)

    base_url = sys.argv[1].split("?")[0].rstrip("/") + "/"
    thread_id = base_url.rstrip("/").rsplit("/", 1)[-1]

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    lua = lupa.LuaRuntime()

    seen_hashes = set()
    if INDEX_PATH.exists():
        for line in INDEX_PATH.read_text().splitlines():
            if line.strip():
                seen_hashes.add(json.loads(line)["hash"])

    print(f"Thread: {thread_id}. Already have {len(seen_hashes)} entries in this corpus.")

    page = 1
    total_new = 0
    while True:
        url = f"{base_url}?ctp={page}"
        try:
            page_html = fetch(url)
        except Exception as e:
            print(f"page {page}: fetch failed ({e}), stopping")
            break

        comments = extract_comments(page_html)
        if not comments:
            print(f"page {page}: no comments, stopping")
            break

        page_new = 0
        for author, text in comments:
            candidates = CANDIDATE_RE.findall(text)
            if not candidates:
                continue

            context_fname = f"{thread_id}_p{page}_{safe_name(author)}_{hashlib.sha256(text.encode()).hexdigest()[:8]}.txt"
            context_written = False

            for cand in candidates:
                h = hashlib.sha256(cand.encode()).hexdigest()[:16]
                if h in seen_hashes:
                    continue
                try:
                    type_char, table = dcs_wire.decode_dcs(lua, cand)
                except Exception as e:
                    print(f"  [skip] undecodable ({len(cand)} chars) from {author}: {e}")
                    continue

                keys = list(table.keys())
                int_keys = sorted(k for k in keys if isinstance(k, int))
                name = table["name"] if "name" in keys else None
                other_keys = [k for k in keys if not isinstance(k, int)]

                if not context_written:
                    (CONTEXT_DIR / context_fname).write_text(f"author: {author}\nurl: {url}\n\n{text}")
                    context_written = True

                seen_hashes.add(h)
                page_new += 1
                fname = f"{h}_{type_char}_{safe_name(name or 'unnamed')}.dcs"
                (CORPUS_DIR / fname).write_text(cand)

                record = {
                    "hash": h,
                    "file": fname,
                    "type_char": type_char,
                    "name": name,
                    "top_level_int_keys": len(int_keys),
                    "other_keys": other_keys,
                    "source": f"steam:{thread_id}",
                    "author": author,
                    "url": url,
                    "context_file": f"context/{context_fname}",
                }
                with INDEX_PATH.open("a") as f:
                    f.write(json.dumps(record) + "\n")
                print(f"  [saved] {type_char} {name!r} ({len(int_keys)} insts) by {author} -> {fname}")

        total_new += page_new
        print(f"page {page}: {len(comments)} comments, {page_new} new items")
        page += 1
        time.sleep(1)  # be polite

    print(f"Done. {total_new} new items saved to {CORPUS_DIR}")


if __name__ == "__main__":
    main()
