"""BsfBehavior -> Mermaid flowchart, for at-a-glance structural review (secondary to the BSF
text listing -- see behavior_source_format.md's "Visualization" section). Renders one
behavior/sub level's own nodes; call again on each `b.subs[i]` for a sub-behavior's own diagram.

Design, settled after two rejected drafts (both user-reviewed against a real rendered diagram,
not just described in prose):

- **Every declared exec pin gets a real, labeled edge -- connected or not.** An early draft
  only drew edges for pins actually present in `node.branches`; a node with an unconnected pin
  (or a pin never even added to the dict by hand-built IR) then looked identical to a node that
  simply doesn't have that pin at all, which is genuinely misleading -- you can't tell "this op
  doesn't have an If Smaller pin" from "this op has one and it's just not wired." Fixed by
  walking `data.instructions[op].args` (`arg_pin_names`, hence needing `argcache` as a real
  parameter now) rather than only `node.branches`.
- **A `POP` pin (see `argcache.resolve_branch`/`ir.py`'s `Branch` type for the rename from the
  misleading "STOP") routes to its own small, local marker node, not one shared terminal.** The
  very first draft sent every `POP` edge in the whole diagram into one shared node; on a real
  13-node graph this created several long edges all converging on one point -- pure visual
  noise for information that (per behavior_source_format.md's "Loop-type instructions" section)
  isn't even trying to say anything more specific than "this pin doesn't go anywhere in *this*
  graph." A dedicated small marker per (node, pin) keeps each such edge short and local, with no
  implied relationship between unrelated dead ends.
- **Not attempted at all: labeling what a `POP` resolves to** (continue which loop, return to a
  caller, restart). Per `behavior_source_format.md`'s "Loop-type instructions" section this is
  genuinely undecidable in general and would misrepresent resolved-but-uninteresting cases as
  needing a computed label just as much as truly ambiguous ones -- a marker just means "this pin
  pops," nothing more, matching the same restraint the text listing already applies.
- **The top-level "next" pin's own label is real, per-op data, not a generic placeholder.**
  `data.instructions[op].exec_arg` (a real field this project had not previously read, found via
  user correction): `false` means the op has no next pin at all -- `exit`/`restart`/`last` are
  never given one here either, matching the real editor exactly, since it's nonsensical to wire
  anything after them; a `{1, "Name", desc}` table names it for real (`check_number`'s `{1, "If
  Equal", ...}`); absent keeps the generic "next" (`argcache.next_pin_name`).
- **A pin is only ever labeled if the op has more than one -- and then *every* one of them is,
  unconditionally, including a plain implicit fallthrough.** Matches the real in-game editor
  (user-confirmed): it labels every pin when a node has several, and never labels a pin that's
  the only one a node has -- there's nothing to disambiguate. An earlier draft only labeled a
  pin when it happened to be wired explicitly or to a pop, leaving `check_number`'s "If Equal"
  silently unlabeled whenever it was left as a plain fallthrough -- wrong, since "If Equal" is
  one of three real pins on that node and needed disambiguating regardless of how it's wired.
  The edge itself is still always drawn either way -- an unlabeled pin isn't an invisible one,
  it just doesn't need a name next to it."""

from __future__ import annotations

from .argcache import ArgCache, arg_pin_names
from .ir import BsfBehavior
from .render_text import _jump_label_targets, render_value


def _next_in_order(node_id: str, order: list[str]) -> str | None:
    idx = order.index(node_id)
    return order[idx + 1] if idx + 1 < len(order) else None


def render_mermaid(b: BsfBehavior, argcache: ArgCache, title: str | None = None) -> str:
    jump_targets = _jump_label_targets(b.nodes)
    lines = [f"%% {title or b.name}", "flowchart TD"]

    node_lines = []
    edge_lines = []
    marker_lines = []
    pop_count = 0

    for node_id in b.order:
        node = b.nodes[node_id]
        args_str = ", ".join(f"{name}={render_value(v, b.params)}" for name, v in node.args.items())
        label = f"{node_id}: {node.op}({args_str})".replace('"', "'")
        node_lines.append(f'  n{node_id}["{label}"]')

        pins = [(pin, node.branches.get(pin)) for _, atype, pin in arg_pin_names(node.op, argcache) if atype == "exec"]
        # data.instructions[op].exec_arg: `false` means no top-level "next" pin exists at all
        # (exit/restart/last -- the real editor draws none, matching that wiring anything after
        # them is nonsensical); a table names it for real (check_number's "If Equal"); absent
        # keeps the generic "next". Never guessed -- read straight from live data.
        next_pin = argcache.next_pin_name(node.op)
        if next_pin is not None:
            pins.append((next_pin, node.branches.get("next")))

        # Only label a pin at all when this op has more than one -- matches the real editor,
        # which never bothers naming a node's only pin (nothing to disambiguate) but always
        # names every pin once there's more than one, wired or not.
        show_labels = len(pins) > 1

        for pin, target in pins:
            edge_label = pin if show_labels else None
            if target is None:
                nxt = _next_in_order(node_id, b.order)
                if nxt is not None:
                    arrow = f"-->|{edge_label}|" if edge_label else "-->"
                    edge_lines.append(f"  n{node_id} {arrow} n{nxt}")
                    continue
                target = "POP"  # falls off the true end with nothing wired -- a real pop
            if target == "POP":
                pop_count += 1
                marker_id = f"pop{pop_count}"
                marker_lines.append(f'  {marker_id}((" ")):::popMarker')
                arrow = f"-.->|{edge_label}|" if edge_label else "-.->"
                edge_lines.append(f"  n{node_id} {arrow} {marker_id}")
            else:
                arrow = f"-->|{edge_label}|" if edge_label else "-->"
                edge_lines.append(f"  n{node_id} {arrow} n{target}")

        if node_id in jump_targets:
            edge_lines.append(f"  n{node_id} -.->|jump→label| n{jump_targets[node_id]}")

    lines.extend(node_lines)
    lines.extend(marker_lines)
    lines.extend(edge_lines)
    if marker_lines:
        lines.append("  classDef popMarker fill:#888,stroke:#888,stroke-width:0px")
    return "\n".join(lines)
