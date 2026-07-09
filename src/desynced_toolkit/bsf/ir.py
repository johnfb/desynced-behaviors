"""The BSF intermediate representation: a behavior as a graph of nodes with named args and
explicit/implicit branch targets, matching behavior_source_format.md's grammar directly (not a
pre-rendered string, and not tied to wire positions -- see "Node identity vs. wire position" in
the spec for why). `bsf/decompile.py` builds this from a real Lua table, `bsf/compile.py` turns
it back into one; `bsf/render_text.py`/`bsf/render_mermaid.py` render it; `bsf/parse_text.py`
builds it from BSF text."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .values import BsfValue

# A branch target: an explicit destination node id, "POP" (explicit `false` or falling off the
# true end of the instruction array -- both are real dead ends, rendered identically per the
# spec), or None for a plain implicit fallthrough (no branch_note at all in BSF text). "POP" is
# named for what it actually does -- pop the current context frame (the innermost active loop
# iteration or call invocation), never a bare "halt" -- not "STOP", which this format used
# until user correction: the auto-restart-from-Program-Start behavior when the frame stack is
# completely empty isn't a separate third case either, just the unremarkable, automatic
# consequence of popping with nothing left. Recomputed fresh at compile time from the current
# `order` every time -- never cached/baked in anywhere.
Branch = str | Literal["POP"] | None


@dataclass
class BsfParam:
    name: str  # pnames[i] if present, else "param{i}"
    # No direction field here on purpose. The wire format's own `parameters[i]` bit turned out
    # (user-confirmed, not guessed) to be a UI-drawing hint for the visual editor -- which side
    # of a `call` node's box a pin is drawn on -- not a distinction the runtime evaluation
    # itself makes. For a format meant for editing and refactoring, trusting a stored bit that
    # can silently go stale after an edit is the wrong call; `argcache.written_param_slots`
    # computes "is this slot ever written to" fresh from the actual node bodies every time it's
    # needed (render_text.py's `*` display, compile.py's regenerated `parameters[i]`), the same
    # never-cache policy already used for the `jump->label` annotation.


@dataclass
class BsfNode:
    id: str
    op: str
    args: dict[str, BsfValue] = field(default_factory=dict)
    # make_asm "hidden literal" fields (behavior_format.md's "Hidden literal fields" table:
    # call/sub, domove/c, notify/txt, dodrop/c, etc.) -- plain named keys on the instruction
    # table that are NOT part of data.instructions[op].args, so ArgCache never sees them. Raw
    # values (already resolved for `call`'s `sub`, see decompile.py), re-emitted verbatim.
    hidden: dict[str, object] = field(default_factory=dict)
    # Keyed by the real exec pin name (e.g. "If Larger"), or "next" for the top-level field.
    branches: dict[str, Branch] = field(default_factory=dict)


@dataclass
class BsfBehavior:
    name: str
    params: list[BsfParam] = field(default_factory=list)
    desc: str | None = None
    keepvars: bool = False
    nodes: dict[str, BsfNode] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)  # node ids in source/emission order
    subs: list["BsfBehavior"] = field(default_factory=list)
