"""BSF text -> BsfBehavior. The reverse of bsf/render_text.py -- the genuinely new direction
(behavior_source_format.md's own "Status" section: this never existed before this pipeline).

Needs `ArgCache` (unlike an earlier draft, which needed none at all): resolving a branch note's
top-level "next" pin back to the structural `branches["next"]` key requires knowing the op's
real per-op display name for it (`argcache.next_pin_name` -- e.g. `check_number`'s "If Equal"
is not literally the text "next"). Everything else here still only builds the abstract,
named-arg IR: knowing an op's real argument *positions* remains exclusively a bsf/compile.py
concern.

Three real gaps in the base grammar (behavior_source_format.md as written) are worth flagging
up front, all resolved with minimal, explicitly-flagged extensions rather than blocking on a
grammar change -- see render_text.py's `render_hidden_value`/`render_node`/`_render_into`
docstrings for the symmetric render-side notes:
  - parameter direction has no surface syntax at all -- resolved with a trailing `*` marking a
    parameter written to somewhere in the behavior's own body (computed fresh from usage by
    `argcache.written_param_slots` whenever it's needed, not stored anywhere -- the wire
    format's own `parameters[i]` bit is a UI-drawing hint, not a runtime distinction, user-
    confirmed). This module only ever strips a trailing `*` on read, never stores or trusts it.
  - make_asm "hidden literal fields" (call's `sub`, domove's `c`, notify's `txt`, the universal
    `cmt`) have no surface syntax at all -- resolved by treating them as ordinary lowercase-
    named `name=value` pairs in the same arg list, with a quoted-string literal form (also not
    in the base grammar) for their string-valued cases.
  - the top-level "next" pin's real per-op name/existence (`data.instructions[op].exec_arg`,
    e.g. `check_number`'s "If Equal", or no pin at all for `exit`/`restart`/`last`) isn't
    something the grammar's generic `(next)` fallback captures -- resolved by resolving a
    parsed pin name against `argcache.next_pin_name(op)` and mapping it back to the structural
    "next" key when it matches, rather than storing it under the display name verbatim.
"""

from __future__ import annotations

import re

from .argcache import ArgCache
from .decompile import HIDDEN_FIELD_TABLE
from .ir import BsfBehavior, BsfNode, BsfParam
from .values import BsfValue, Coord, Fr, FrameReg, IdLit, Num, Param, Var

_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")
_SLOT_UNDECLARED_RE = re.compile(r"^slot(\d+)\(undeclared\)$")
_HEADER_RE = re.compile(r"^(behavior|sub)\s+(.+)\((.*)\):\s*$")
_DESC_RE = re.compile(r'^desc:\s*"(.*)"\s*$')
_BRANCH_RE = re.compile(r">\s*(\S+?)\s*\(([^)]*)\)")
_SYMBOLIC_FRAME_REGS = {"goto": -1, "store": -2, "visual": -3, "signal": -4}


def _mask_quotes(s: str) -> str:
    """Return a same-length version of `s` with every `"..."` span's contents (including the
    quote characters themselves) replaced by a neutral placeholder. Used only to decide *where*
    to split/stop structural scanning below -- callers always slice/return substrings of the
    original `s`, never the mask. Needed because a hidden field's free-text value (`cmt`, `txt`)
    can itself contain `(`, `)`, `,`, or `=` -- a real bug caught while round-tripping
    `beacon.dcs`'s own comments, which contain exactly this."""
    out = list(s)
    in_quotes = False
    for i, c in enumerate(s):
        if c == '"' and (i == 0 or s[i - 1] != "\\"):
            in_quotes = not in_quotes
            out[i] = "Q"
        elif in_quotes:
            out[i] = "x"
    return "".join(out)


def _find_close_paren(s: str, start: int) -> int:
    """`s[start]` is the character right after an already-consumed opening `(` (depth 1).
    Returns the index of its matching `)`."""
    masked = _mask_quotes(s)
    depth = 1
    i = start
    while i < len(s):
        if masked[i] == "(":
            depth += 1
        elif masked[i] == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise SyntaxError(f"unmatched '(' in: {s!r}")


def _split_top_level(s: str, sep: str) -> list[str]:
    """Split on `sep`, but only where it appears outside any `(...)`/`[...]` nesting or a
    quoted string -- a value like `coord(-5, 6)[num=3]` has commas of its own that a naive
    split would misparse, and so can a `cmt="..."` free-text value."""
    if not s.strip():
        return []
    masked = _mask_quotes(s)
    parts, depth, start = [], 0, 0
    for i, c in enumerate(masked):
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == sep and depth == 0:
            parts.append(s[start:i])
            start = i + 1
    parts.append(s[start:])
    return parts


def _split_first_top_level_eq(s: str) -> tuple[str, str]:
    masked = _mask_quotes(s)
    depth = 0
    for i, c in enumerate(masked):
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == "=" and depth == 0:
            return s[:i].strip(), s[i + 1 :].strip()
    raise SyntaxError(f"expected '=' in arg: {s!r}")


def _parse_number(s: str) -> int | float:
    s = s.strip()
    return float(s) if "." in s else int(s)


def _split_num_suffix(s: str) -> tuple[str, int | float | None]:
    if s.endswith("]") and "[num=" in s:
        base, _, rest = s.rpartition("[num=")
        return base, _parse_number(rest[:-1])
    return s, None


def parse_value(s: str, params: list[BsfParam]) -> BsfValue:
    s = s.strip()
    if s.startswith("$"):
        return Var(s[1:])
    if s.startswith("@"):
        rest = s[1:]
        if rest in _SYMBOLIC_FRAME_REGS:
            return FrameReg(_SYMBOLIC_FRAME_REGS[rest])
        return FrameReg(-int(rest))
    if s.startswith("fr("):
        close = _find_close_paren(s, 3)
        name = s[3:close]
        remainder = s[close + 1 :]
        num = _parse_number(remainder[5:-1]) if remainder.startswith("[num=") else None
        return Fr(name, num)
    if s.startswith("coord("):
        close = _find_close_paren(s, 6)
        x_str, y_str = _split_top_level(s[6:close], ",")
        remainder = s[close + 1 :]
        num = _parse_number(remainder[5:-1]) if remainder.startswith("[num=") else None
        return Coord(_parse_number(x_str), _parse_number(y_str), num)
    m = _SLOT_UNDECLARED_RE.match(s)
    if m:
        return Param(int(m.group(1)))
    if _NUM_RE.match(s):
        return Num(_parse_number(s))
    base, num = _split_num_suffix(s)
    for i, p in enumerate(params, start=1):
        if p.name == base:
            return Param(i)
    return IdLit(base, num)


def _parse_hidden_value(s: str) -> object:
    s = s.strip()
    if s == "False":
        return False
    if s == "True":
        return True
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1].replace('\\"', '"')
    if _NUM_RE.match(s):
        return _parse_number(s)
    return s


def _parse_branch_notes(s: str, op: str, argcache: ArgCache) -> dict[str, str]:
    next_pin = argcache.next_pin_name(op)
    branches = {}
    for target, pin in _BRANCH_RE.findall(s):
        pin = pin.strip()
        if pin == "jump→label":
            continue  # display-only annotation, recomputed fresh on every render, not real data
        # A pin whose rendered name matches this op's real "next"-pin display name (e.g.
        # check_number's "If Equal") maps back to the structural "next" key -- everything else
        # (a real declared exec arg's own name, e.g. "If Larger") is already its own key.
        key = "next" if (next_pin is not None and pin == next_pin) else pin
        branches[key] = "POP" if target == "POP" else target
    return branches


def parse_node(line: str, params: list[BsfParam], argcache: ArgCache) -> BsfNode:
    node_id, rest = line.split(":", 1)
    node_id = node_id.strip()
    rest = rest.strip()
    op_end = rest.index("(")
    op = rest[:op_end].strip()
    after = rest[op_end + 1 :]
    close = _find_close_paren(after, 0)
    arg_list_str = after[:close]
    branch_notes_str = after[close + 1 :]

    node = BsfNode(id=node_id, op=op)
    hidden_fields = {f for o, f in HIDDEN_FIELD_TABLE.items() if o == op}
    for arg_str in _split_top_level(arg_list_str, ","):
        name, value_str = _split_first_top_level_eq(arg_str)
        if name == "cmt" or name in hidden_fields:
            node.hidden[name] = _parse_hidden_value(value_str)
        else:
            node.args[name] = parse_value(value_str, params)
    node.branches.update(_parse_branch_notes(branch_notes_str, op, argcache))
    return node


def _parse_params(params_str: str) -> list[BsfParam]:
    """The trailing `*` (see render_text.py's `_render_into`) is display-only, recomputed fresh
    from actual usage on every render -- accepted and stripped here, not stored on `BsfParam`,
    so a hand-edit that adds/removes a write to a parameter without remembering to update `*`
    still compiles to the correct `parameters[i]` bit rather than a stale hand-typed one."""
    result = []
    for p in _split_top_level(params_str, ","):
        p = p.strip()
        if not p:
            continue
        result.append(BsfParam(name=p[:-1] if p.endswith("*") else p))
    return result


def _parse_one(lines: list[str], i: int, keyword: str, argcache: ArgCache) -> tuple[BsfBehavior, int]:
    m = _HEADER_RE.match(lines[i])
    if not m or m.group(1) != keyword:
        raise SyntaxError(f"expected {keyword!r} header, got: {lines[i]!r}")
    name = m.group(2).strip()
    params = _parse_params(m.group(3))
    i += 1

    desc = None
    if i < len(lines):
        dm = _DESC_RE.match(lines[i].strip())
        if dm:
            desc = dm.group(1)
            i += 1

    while i < len(lines) and lines[i].strip() == "":
        i += 1

    nodes: dict[str, BsfNode] = {}
    order: list[str] = []
    while i < len(lines) and lines[i].strip() != "" and not lines[i].lstrip().startswith(("sub ", "behavior ")):
        node = parse_node(lines[i], params, argcache)
        nodes[node.id] = node
        order.append(node.id)
        i += 1

    return BsfBehavior(name=name, params=params, desc=desc, nodes=nodes, order=order), i


def parse_behavior(text: str, argcache: ArgCache) -> BsfBehavior:
    lines = text.split("\n")
    i = 0
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    behavior, i = _parse_one(lines, i, keyword="behavior", argcache=argcache)

    subs = []
    while i < len(lines):
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        if i >= len(lines):
            break
        sub, i = _parse_one(lines, i, keyword="sub", argcache=argcache)
        subs.append(sub)
    behavior.subs = subs
    return behavior
