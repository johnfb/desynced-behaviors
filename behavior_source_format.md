# Behavior Source Format

A textual, human/LLM-readable representation for Desynced behaviors, designed
to be decompiled *from* and compiled back *to* the real instruction-table
shape `dcs_wire.py` already decodes/encodes (see `behavior_format.md` for
that underlying wire format — this document is the layer above it).

## Why this format, not tree-structured pseudocode

An earlier direction (`compiler/ast_compiler.py`) targeted Python-like syntax
(`if`/`else`, `for`). Empirical analysis of 319 real user-created behaviors
(see project memory / `scripts/analyze_corpus.py`) found this is a poor fit
for a large share of real cases: 20.7% use `jump`/`label` computed dispatch,
which is indirect goto by construction and cannot be expressed as structured
control flow at all, and a further meaningful fraction have control-flow
merge points that don't correspond to simple `if`/`else` reconvergence (a
proper reducibility check would be needed to give an exact number — not yet
done). This format is graph-native instead: every instruction is a node with
an explicit index, and every real control edge — however it converges or
loops — is either explicit or a well-defined implicit default, never forced
into a shape it doesn't have.

This is the primary **read/edit** representation (dense, precise, round-trip
to the real table). A secondary Mermaid rendering (see "Visualization"
below) is generated on demand from the same underlying graph for
at-a-glance structural review — the two are not competing formats, they
serve different purposes off the same data.

## Grammar overview

```
behavior := header instruction+ sub_behavior*

header := "behavior" NAME "(" param_list? ")" ":"
          ("desc:" STRING)?

param_list := param ("," param)*
param := NAME                      -- from pnames[i], or "param<i>" if absent

instruction := INDEX ":" OP "(" arg_list? ")" branch_note*
arg_list := arg ("," arg)*
arg := ARGNAME "=" value

value := NUMBER
       | "coord" "(" NUMBER "," NUMBER ")" ("[" "num" "=" NUMBER "]")?
       | IDENTIFIER ("[" "num" "=" NUMBER "]")?      -- id-typed literal, optionally with num
       | "$" NAME                                    -- variable
       | NAME                                        -- resolved parameter name
       | "@" ("goto" | "store" | "visual" | "signal" | NUMBER)  -- frame register; symbolic name when N is 1-4, else bare @N
       | "fr" "(" NAME ")" ("[" "num" "=" NUMBER "]")?  -- faction (shared) register, resolved by name at runtime

branch_note := ">" (INDEX | "STOP") "(" PINNAME ")"
             -- omitted entirely for a plain implicit fallthrough (see below)

sub_behavior := "sub" NAME "(" param_list? ")" ":" instruction+
              -- one per bundled dependencies[]/subs[] entry
```

## Values

| Real value shape | Source syntax | Notes |
|---|---|---|
| number literal `{num=N}` | `N` | plain. A bare (unwrapped) int is never this shape — see the parameter/slot row below |
| coordinate `{coord={x=,y=}}` | `coord(x, y)` | never the `[x,y]` array form — see `behavior_format.md`'s corruption gotcha |
| id-typed literal `{id="x"}` (item/frame/component/tech/value id) | bare identifier, e.g. `c_behavior`, `v_enemy_faction`, `c_radar` | safe to leave bare — real ids never collide with variable-name convention (below). The syntax does not distinguish which *kind* of id it is (item/frame/component/tech/value) — that's inherent to the underlying value shape itself, not something this format could disambiguate further; look the id up in the real data files (or `instructions_index.md`) if its category matters |
| local variable (string arg value, e.g. `"A"`) | `$A` | `$`-prefixed to stay unambiguous against bare identifiers, even though real behaviors only ever seem to use short letter names |
| parameter (bare positive int) | the real name from `pnames[i]` when `i` is covered by this behavior's own declared `parameters`, else `param<i>` if `parameters` exists but is unnamed, else `slot<i>(undeclared)` | a bare positive int is **only ever** a mem-slot/parameter reference, never a plain number by itself (see the literal row above) — confirmed by direct comparison of the same real behavior copied two different ways (see project memory, 2026-07-06): a node-*selection* clipboard copy (Ctrl+A/Ctrl+C on nodes) can carry a bare int referencing a slot with no `parameters`/`pnames` table at all, while the identical value in a full Library-export copy of the same behavior is accompanied by `parameters={1:true}, pnames={1:"Result"}` and correctly resolves as a named parameter. The `slot<i>(undeclared)` fallback is a real, expected case for partial-selection fragments, not just a defensive placeholder — this is precisely the shape a "copy a portion of a behavior for review/editing" workflow will routinely produce |
| frame register (small negative int) | `@goto` / `@store` / `@visual` / `@signal` for -1/-2/-3/-4; bare `@N` for any other negative value | confirmed via `ui/Skin.lua:680`'s `data.frame_regs` array order (`{Goto, Store, Visual, Signal}`, 1-based) cross-anchored against `ui/FrameView.lua:2413`'s `i == -FRAMEREG_GOTO` comparison — not a guess. See https://wiki.desyncedgame.com/Registers for what each register does at the gameplay level (async goto/store/visual-icon/signal-emit) |
| faction (shared) register `{fr="name"}` | `fr(name)` | shared, named storage visible to every behavior the faction runs, and the backing store for Radio Transmitter/Receiver "band" links — resolved by *name* every access, never a fixed slot index (renaming/reordering a faction's registers doesn't break code that references them). See `behavior_format.md`'s "Faction (shared) registers" section for the full compile-time (`-99-n` synthetic address + `asm.fregs` name table) and runtime (`CallRadio`, name→index re-lookup) mechanism, including the write-guard when a register is currently link-driven by a Transmitter. The name must already exist for the target faction — unlike `$var`, `fr(name)` does not self-declare a new register |
| entity/other runtime-only value | not directly literal-izable; only appears as a register read, never a source literal | n/a |

### Composite values (`num` plus a coord/id/entity)

Per `behavior_format.md`'s composite-value semantics: `coord`/`entity`/`id`
are mutually exclusive on one value, but `num` is a **separate** field that
coexists with any of them (`{coord={x=,y=}, num=N}` is a real, valid, and
fairly common shape — e.g. a coordinate paired with an associated
distance/priority, or an item/component id paired with a quantity). This
format renders that pairing with a `[num=N]` suffix on the base value:

```
coord(-5, 6)[num=3]      -- coordinate (-5, 6) carrying num=3
c_radar[num=10]          -- component id c_radar carrying num=10
```

A bare `N` (no brackets) is reserved for a value that is *only* a number
(the common case: `{num=N}` alone, nothing else set). The bracket form is
only used when a coord/id/entity is present *and* carries a `num` alongside
it — the two are visually distinct on purpose, since they come from
different real value shapes and collapsing them would lose information.

## Control edges

Every exec-typed argument slot (the top-level `next`, plus per-instruction
slots like `check_number`'s "If Larger"/"If Smaller") independently resolves
to one of three cases, per `behavior_format.md`'s documented semantics:

1. **Explicit integer target** → rendered as `>N (PinName)`, using the
   instruction's real pin name from `data.instructions[op].args` (e.g. `If
   Larger`, `Done`) for a slot arg, or `(next)` for the top-level field. This
   is an intentional wire the original author made — always shown.
2. **Explicit `false`** → rendered as `>STOP (PinName)`. This is a real,
   meaningful authorial choice (terminate this path / pop to the enclosing
   block) and must stay visually distinct from omission — collapsing this
   into "no annotation" was a real bug caught while building the corpus
   analysis tooling (see project memory) and must not be repeated here.
3. **Omitted entirely (nil)** → no annotation at all; implicitly falls
   through to the physically next instruction. This is the common case for a
   straight-line instruction sequence and would be pure noise if annotated.

## Dynamic `jump`/`label` dispatch

**`jump`'s target is not statically known in the general case, and that is
the normal, intended way to use it, not an edge case.** The real
`data.instructions.jump` implementation's own `explain` text says so
directly: *"Jumps can be dynamic and passed via parameter or variable"* —
and its `func` confirms this isn't just descriptive copy: it resolves the
`Label` argument's actual value at the moment the instruction executes,
linearly searches the current behavior's compiled instruction list for a
`label` whose own resolved value matches, and jumps there if found. **If no
`label` matches, the function returns without setting `state.counter` at
all, which means execution falls through via the instruction's ordinary
`next` field** — the same implicit/explicit `next` resolution every other
instruction gets (see "Control edges" above). This is a real, named idiom
(confirmed directly by a user of this project): jump to a value representing
a state; if no `label` for that state exists yet, `next` runs the
initialization code for it.

Both `jump` and `label`'s `Label` argument are ordinary `in`-typed values,
rendered with the normal value rules above — so a `Label=` can be a literal
(`v_transport_route`), a variable (`$State`), a parameter, or a frame
register, with no special grammar needed:

```
12: jump(Label=$State)
13: label(Label=$State)     -- unrelated code here does NOT get a resolved edge
```

**Static resolution at decompile time is only ever an opportunistic, best-effort
annotation** — attempted *only* when a `jump`'s `Label` value is a literal
(never for a variable/parameter/register value, where the actual target
depends on runtime program state this decompiler has no visibility into).
When it succeeds, both the raw value and the resolved edge are shown:

```
12: jump(Label=v_transport_route)  >3 (jump→label)
```

The raw `Label=` value is kept even when resolution succeeds (needed to
round-trip an edit — renaming a label means updating both the `jump` and
`label` instructions, which only makes sense if the actual value stays
visible and editable). When `Label` is dynamic, no `jump→label` annotation
is shown at all — but the instruction's separate `next` edge (the real
"no matching label" path) is still rendered normally, exactly as it would be
for any other instruction. A `jump` with a dynamic target and no explicit
`next` wired is not "unresolved" or missing information — it's fully and
correctly described by its raw `Label=` value plus its ordinary implicit
fallthrough, the same as everything else in this format.

## `call` / sub-behaviors

`call`'s argument list is not statically shaped by `data.instructions.call`
the way other instructions are — its arg count and per-slot in/out-ness
depend entirely on the *target* sub-behavior's own declared parameters (this
is a real, confirmed quirk — both real mods examined this project read
special-case `call` in their own instruction-arg-walking code for exactly
this reason, see project memory). `sub` resolves three ways, and each is
rendered differently based on what parameter-name information is actually
available:

| `sub` value | Meaning | Argument naming |
|---|---|---|
| positive int | 1-based index into this clipboard bundle's `dependencies[]`/`subs[]` | resolved against that bundled sub-behavior's own `pnames` — real names available, since the whole bundle is visible to the decompiler at once |
| `-1` | recursive self-call | resolved against the *current* behavior's own `pnames` |
| string | external saved-library id, not bundled in this clipboard string | **not resolvable** — no `pnames` visible to the decompiler at all; falls back to generic `arg1`, `arg2`, ... — this is an honest limitation, not a bug to fix later, since the data genuinely isn't present in the string being decompiled |

Rendered call syntax names the target directly instead of a raw numeric
index, e.g.:

```
7: call(ScanRuins, $A, $B, framereg_result=$C)
```

where `ScanRuins` is the bundled sub-behavior's own declared name (from its
`name` field), not `sub=2`.

## Sub-behaviors (`dependencies[]` / `subs[]`)

Both field names have been observed for the same concept in real corpus
data — `dependencies` at a clipboard's top level for a standalone exported
behavior, `subs` for a behavior embedded inside a blueprint's `c_behavior`
component `extra_data` (see project memory, 2026-07-06). Whether this is a
live-editor-vs-wire-format distinction or a real inconsistency has **not
been reconciled** — treat both as the same concept (an array of embedded
sub-behavior tables) until checked directly. Each bundled sub-behavior
renders as its own `sub NAME(...):` block using its own real `name`, with
instruction indices restarting at 1 (independent numbering per behavior,
matching how the real table addresses them — a `call` target's instruction
indices are only ever meaningful within that specific sub-behavior's own
array).

## Loop-type instructions (`for_number`, `for_component`, `for_signal_match`, etc.)

**Correction, caught by direct user feedback — an earlier draft of this
document treated loop instructions as needing "block-body extent detection,"
which was a misunderstanding.** They don't need any special handling at all
for their own pins: every `for_*` instruction (`for_number`, `for_component`
— "loop over equipped components" — `for_signal`/`for_signal_match`,
`for_entities_in_range`, `for_inventory_item`, and others) has exactly the
same shape as any other multi-pin instruction. Checking the real
`data.instructions.for_number` definition confirms this precisely: its only
*declared* `exec` arg is `Done` ("Finished loop") — the per-iteration path
is the instruction's ordinary top-level `next`, exactly like `check_number`'s
"Equal" case (see "Control edges" above). Both pins render with the existing
rules, no changes needed:

```
4: for_component(Filter=c_radar, Component=$C)  >9 (Done)
```

**The real subtlety is elsewhere: what an unconnected pin means once you're
inside a loop's iteration.** Per direct user correction: control reached via
the per-iteration pin is not a bounded "block" of instructions at all — it's
free to jump, branch, and call like anything else, and the loop is not
considered done, no matter where control flow wanders (even to a `label`
positioned before the loop), until either an explicit `break`/`last`
instruction runs, or control reaches a pin with nothing wired to it at all.
Checked against the real dispatcher to confirm precisely (`data/instructions.lua`'s
`InstBeginBlock`, `data/components.lua`'s `c_behavior_on_end`): a loop
instruction's `func` pushes onto a real runtime stack (`state.blocks`) when
it begins; a dead end — an explicit `false` on any pin, *or* falling off the
true end of the instruction array (both are handled identically, confirmed
by `interpreter.py`'s own fix for exactly this equivalence) — pops the
innermost still-active loop off that stack and re-invokes *its own* `next`
handler to decide whether to continue iterating or finish (call `last`, jump
to `Done`). Only once nothing remains on the block stack does a dead end
fall back to a `call`-return (if inside a called sub-behavior) or a genuine
top-level restart. **An omitted (not `false`) exec arg is unaffected by any
of this** — it's a normal implicit fallthrough to the physically next
instruction regardless of loop context, confirmed by the same dispatcher
code (only a real dead end triggers the block-stack check at all).

This means a `false` pin's real meaning ("stop the behavior" vs. "continue
the innermost enclosing loop" vs. "return to caller") is a **path-dependent
runtime property** (which loops are active on `state.blocks`, which `call`
frames are on `state.returns`, at the moment that specific `false` executes)
— not a fixed property of the instruction's position in the flat array. In
the overwhelming majority of real behaviors this is still staticly
resolvable with a reachability heuristic: for each loop instruction, follow
every edge reachable from its per-iteration pin that doesn't pass through an
explicit `break`/`last` or a nested loop's own `Done` pin, and any `false`
found in that reachable set means "continue this loop," not "stop." This is
not a mathematical guarantee — computed `jump`/`label` dispatch could in
principle make the same instruction reachable both inside and outside a
loop's dynamic scope, which this heuristic can't disambiguate — but it will
be correct for realistic behaviors and is a real, buildable next step, not
an open research problem the way the original (incorrect) "extent
detection" framing suggested. Not yet implemented.

## Known open items

- **Free-floating node position (`nx`/`ny`).** Deliberately excluded from
  this source format — it's a visual-editor layout affordance, not
  behavioral semantics. A future write-back tool will need its own policy
  (e.g. preserve original positions for untouched instructions, only
  auto-layout newly-added ones) — that's a separate concern from this
  format's grammar and not addressed here.

## Visualization (secondary, generated on demand)

The same node/edge graph this format describes can be rendered as a Mermaid
flowchart for at-a-glance structural review (see
`scripts/render_examples.py`'s `to_mermaid` for the current prototype) —
useful when reviewing a behavior's overall shape matters more than editing a
specific instruction, or to sanity-check that an edit didn't change the
shape unexpectedly. This is not an alternate source-of-truth format; it's
generated from the same underlying graph as the primary listing above, never
edited directly, and carries no information the listing doesn't already have.

## Status

This is a specification, not yet a shipped decompiler. `scripts/render_examples.py`
is a working prototype of the underlying *graph extraction and edge-resolution
logic*, exercised for real on a live end-to-end edit (2026-07-06: a user
selected/copied a real 28-instruction fragment from the in-game editor, Claude
read/decoded/rebuilt it — extending it to cover all real `c_turret`-descendant
components with a `[num=charge_time]` composite value on each, per the user's
ask — and the user confirmed the pasted-back result was correct in-game; see
project memory for the full trail). That real test caught and fixed two bugs
in the prototype, both now implemented, not just planned: the `STOP` vs.
plain-omission distinction (see "Control edges" above — an earlier version
silently rendered a real `next: false` termination identically to implicit
fallthrough) and the `[num=N]` composite-value suffix (existed only in this
doc, not in `resolve_value`, until that same session — the underlying data
was always correct, only the display silently dropped a coexisting `num`).
Remaining real gap in the prototype's literal syntax: it still prints
`num:5`/`var:A`/`id:x`-style prefixes instead of this doc's bare-value
surface syntax (`5`/`$A`/`x`) — cosmetic, not a correctness issue, but worth
closing before relying on the prototype for anything beyond ad hoc rendering.
A second, non-cosmetic gap found while documenting faction registers
(2026-07-07) and now fixed: `resolve_value` in `scripts/render_examples.py`
had no case at all for `{"fr": "name"}` — it fell through to the generic
composite-value branch (no `num`/`coord`/`id` key matches) and mislabeled it
`literal:{'fr': 'name'}`, which reads as a fixed value rather than a register
reference. It now renders `fr:name`, matching this prototype's existing
prefixed style (`id:x`, `coord:(x,y)`) rather than this doc's final bare
`fr(name)` surface syntax — still subject to the same not-yet-closed
prefix-vs-bare-syntax gap noted just above.
Not yet built: the reverse direction (parsing this format back into a real Lua instruction
table for `dcs_wire.py` to encode — the live edit above was still constructed
by hand-building Lua tables directly in Python, not by parsing this format's
text), integration replacing `ast_compiler.py`,
and the `sequence`/`for_number` block-extent problem above.
