"""BsfBehavior -> Mermaid flowchart, for at-a-glance structural review (secondary to the BSF
text listing -- see behavior_source_format.md's "Visualization" section). Renders one
behavior/sub level's own nodes; call again on each `b.subs[i]` for a sub-behavior's own diagram.

Real design decision made here, not silently inherited from `scripts/render_examples.py`'s
prototype: that prototype dropped `STOP` edges entirely from the diagram (`if dst == "STOP":
continue`), which is a real regression from the spec's "STOP must stay visually distinct from
omission" rule as applied to the text listing. Here, every `STOP` branch gets a real edge into a
single synthetic terminal node per diagram -- an explicit `STOP`, a `>STOP`-equivalent omission
at the true end of `order`, and a jump->label annotation edge are all real, visible arrows;
only an *implicit mid-sequence* fallthrough (an omitted branch whose physically-next node
exists) is unlabeled, matching the "this needs no annotation" rule from the text grammar."""

from __future__ import annotations

from .ir import BsfBehavior
from .render_text import _jump_label_targets, render_value

_STOP_NODE_ID = "STOP"


def _next_in_order(node_id: str, order: list[str]) -> str | None:
    idx = order.index(node_id)
    return order[idx + 1] if idx + 1 < len(order) else None


def render_mermaid(b: BsfBehavior, title: str | None = None) -> str:
    jump_targets = _jump_label_targets(b.nodes)
    lines = [f"%% {title or b.name}", "flowchart TD"]

    needs_stop_node = False
    node_lines = []
    edge_lines = []

    for node_id in b.order:
        node = b.nodes[node_id]
        args_str = ", ".join(f"{name}={render_value(v, b.params)}" for name, v in node.args.items())
        label = f"{node_id}: {node.op}({args_str})".replace('"', "'")
        node_lines.append(f'  n{node_id}["{label}"]')

        for pin, target in node.branches.items():
            if target is None:
                nxt = _next_in_order(node_id, b.order)
                if nxt is not None:
                    edge_lines.append(f"  n{node_id} --> n{nxt}")
                else:
                    needs_stop_node = True
                    edge_lines.append(f"  n{node_id} -->|{pin}| {_STOP_NODE_ID}")
            elif target == "STOP":
                needs_stop_node = True
                edge_lines.append(f"  n{node_id} -->|{pin}| {_STOP_NODE_ID}")
            else:
                edge_lines.append(f"  n{node_id} -->|{pin}| n{target}")

        if node_id in jump_targets:
            edge_lines.append(f"  n{node_id} -.->|jump→label| n{jump_targets[node_id]}")

    lines.extend(node_lines)
    if needs_stop_node:
        lines.append(f'  {_STOP_NODE_ID}(("STOP"))')
    lines.extend(edge_lines)
    return "\n".join(lines)
