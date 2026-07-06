# Behavior Source Format

A textual, human/LLM-readable representation for Desynced behaviors, designed
to be decompiled *from* and compiled back *to* the real instruction-table
shape `dsc_wire.py` already decodes/encodes (see `behavior_format.md` for
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

branch_note := ">" (INDEX | "STOP") "(" PINNAME ")"
             -- omitted entirely for a plain implicit fallthrough (see below)

sub_behavior := "sub" NAME "(" param_list? ")" ":" instruction+
              -- one per bundled dependencies[]/subs[] entry
```

## Values

| Real value shape | Source syntax | Notes |
|---|---|---|
| number literal `{num=N}` or bare int used as a literal | `N` | plain |
| coordinate `{coord={x=,y=}}` | `coord(x, y)` | never the `[x,y]` array form — see `behavior_format.md`'s corruption gotcha |
| id-typed literal `{id="x"}` (item/frame/component/tech/value id) | bare identifier, e.g. `c_behavior`, `v_enemy_faction`, `c_radar` | safe to leave bare — real ids never collide with variable-name convention (below). The syntax does not distinguish which *kind* of id it is (item/frame/component/tech/value) — that's inherent to the underlying value shape itself, not something this format could disambiguate further; look the id up in the real data files (or `instructions_index.md`) if its category matters |

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
| local variable (string arg value, e.g. `"A"`) | `$A` | `$`-prefixed to stay unambiguous against bare identifiers, even though real behaviors only ever seem to use short letter names |
| parameter (positive int ≤ param count) | the real name from `pnames[i]`, or `param<i>` if unnamed | resolved once at the top of the behavior/sub, referenced by name throughout |
| frame register (small negative int) | `@goto` / `@store` / `@visual` / `@signal` for -1/-2/-3/-4; bare `@N` for any other negative value | confirmed via `ui/Skin.lua:680`'s `data.frame_regs` array order (`{Goto, Store, Visual, Signal}`, 1-based) cross-anchored against `ui/FrameView.lua:2413`'s `i == -FRAMEREG_GOTO` comparison — not a guess. See https://wiki.desyncedgame.com/Registers for what each register does at the gameplay level (async goto/store/visual-icon/signal-emit) |
| entity/other runtime-only value | not directly literal-izable; only appears as a register read, never a source literal | n/a |

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

## Computed `jump`/`label` dispatch

`jump(Label=X)` and `label(Label=X)` do not wire a static instruction index
at all — the real dispatch is a runtime value match on `X` (an id or number),
resolved by the actual dispatcher, not stored as an index anywhere in the
table (see `behavior_format.md`'s `jump`/`label` section). The decompiler
resolves this **statically, at decompile time**, by matching every `jump`'s
`Label` value against every `label`'s `Label` value within the same
behavior, and additionally renders the resolved edge:

```
12: jump(Label=v_transport_route)  >3 (jump→label)
```

Both parts are kept: the raw `Label=` value (needed to round-trip an edit —
renaming a label means updating both the `jump` and `label` instructions,
which only makes sense if the actual value is visible and editable) and the
resolved `>3 (jump→label)` annotation (needed for readability — without it, a
reader has to manually search for the matching `label` instruction). If a
`jump`'s label value is itself computed at runtime (e.g. read from a
register rather than a literal) rather than a static literal, static
resolution isn't possible and the `jump→label` annotation is simply omitted
— the raw `Label=` value is still shown.

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

## Known open items — not yet solved, flagged rather than guessed at

- **`sequence`/`for_number` block-body extent.** These are block-type
  instructions whose "body" is not a separate nested list in the real table
  — it's some contiguous run of the same flat instruction array, with scope
  boundaries enforced by a block-stack the real dispatcher maintains
  (`InstBeginBlock` in `data/library.lua`). Determining exactly which
  instructions belong "inside" a given block from the flat array alone is a
  real structuring problem this project's own `interpreter.py` still
  Python-simulates rather than solves generally (see its own "not done yet"
  list). Until solved, this format renders `sequence`/`for_number`
  instructions as plain flat entries like any other (their real exec-arg
  edges, e.g. `Done`, still render correctly per the rules above) — no
  special indented-block syntax is emitted, since inventing one without a
  real extent-detection algorithm behind it would be decorative, not
  functional.
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
logic* (validated by hand against two real corpus behaviors — a 5-instruction
simple case and a 16-instruction case with a real `jump`/`label` loop) — it
predates this document and its literal output syntax (`num:5`, `var:A`,
`id:x` prefixes) does not yet match the cleaner surface syntax finalized here
(bare `5`, `$A`, bare `x`, `[num=N]` composites). That's a cosmetic gap in
the prototype, not a change to the underlying grammar — worth fixing before
the prototype is relied on for anything beyond the comparison it was built
for. Not yet built: the reverse direction (parsing this format back into a real Lua instruction
table for `dsc_wire.py` to encode), integration replacing `ast_compiler.py`,
and the `sequence`/`for_number` block-extent problem above.
