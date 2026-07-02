# Desynced Behavior Source Format

This documents the schema that `dsc_codec.py` decodes a behavior clipboard string
(`.dsc`, and entries in `data.behaviors`) into, and that you must produce (as a
Python `dict`/`list`) to encode a new one. It is the missing layer between
[`instructions_index.md`](instructions_index.md) (what each instruction does and
its argument order) and `dsc_codec.py` (string ⟷ dict transport).

Reverse-engineered from `data/library.lua`'s `GetFactionBehaviorAsm` (the
function that compiles this exact source form into runtime bytecode) and
cross-checked line-for-line against `observer.dsc`. This is the *source* form —
the same shape the in-game visual editor saves — not the compiled bytecode;
the game recompiles it from this form every time it's loaded (cached by
revision), so you never need to hand-produce bytecode.

## Top-level envelope

A behavior decodes to a dict whose keys are 0-based instruction indices (as
rendered by `dsc_codec.py`; Lua itself stores it as a 1-based array), plus a
few sibling metadata keys:

```jsonc
{
  "0": { "op": "unlock" },
  "1": { "0": { "num": 1 }, "op": "wait" },
  // ... more instructions ...
  "name": "Observer"
}
```

- `name` — display name shown in the library UI.
- `type` — `"C"` for a behavior/code entry (`"B"` is used for blueprints
  elsewhere in the library and is unrelated to instructions).
- `parameters` (optional) — present only if this behavior is meant to be
  called as a sub-behavior (via the `call`/`load_behavior` instructions).
  An array, one entry per parameter slot; a truthy entry marks that slot as
  an output parameter, falsy/`false` marks it as input. See "Parameters"
  below.
- `pnames` (optional) — parallel array of display names for `parameters`.
- `keepvars` (optional) — if set, local-variable memory slots persist
  across calls instead of being reset. Rarely needed for a fresh behavior.

You will not typically need `parameters`/`pnames`/`keepvars` for a
top-level, non-parameterized behavior like a bot's main program — `name`
plus the instruction list is enough (see `observer.dsc`).

## Instruction record shape

Each instruction is a dict:

```jsonc
{ "op": "<instruction id>", "0": <arg0>, "1": <arg1>, ..., "next": <int|false>, "cmt": "<note>", "nx": <float>, "ny": <float> }
```

- **`op`** — the instruction id, exactly as it appears in `data.instructions`
  and in `instructions_index.md` (e.g. `"scan"`, `"set_reg"`, `"domove"`).
- **Numbered keys `"0"`, `"1"`, ...** — one per entry in that instruction's
  `args` list in `instructions_index.md`, **in the same order**, regardless
  of whether the entry is `in`, `out`, or `exec`. Omit a key entirely to
  leave that argument unset/unused (fine for optional/`(extra param)`
  entries; usually required for anything the description calls mandatory).
- **`next`** (optional) — where execution goes after this instruction
  finishes, *if it doesn't take one of its own `exec` branches*. See
  "Branch and fall-through resolution" below. Not present on every
  instruction — only needed when you want it to differ from the default.
- **`cmt`** (optional) — a free-text note attached to the node in the visual
  editor. Purely cosmetic; every instruction can have one (separate from the
  dedicated `cmt`/"Comment" instruction, which is a freestanding note node).
- **`nx`, `ny`** (optional) — canvas (x, y) position of the node in the
  visual editor. Purely cosmetic layout data; omit them and the editor will
  just place the node at the origin when you open it — the behavior still
  runs correctly.

## Argument value encoding

What you put in a numbered slot depends on what that argument represents:

| Kind | Encoding | Example |
|---|---|---|
| Literal number | `{ "num": N }` | `{ "num": 10 }` |
| Literal item/frame/component/tech/signal id | `{ "id": "item_xxx" }` | `{ "id": "v_enemy_faction" }` |
| Literal coordinate | `{ "coord": [x, y] }` | `{ "coord": [5, -2] }` |
| Frame register | plain negative int `-1` to `-4` | `-4` (see table below) |
| Local variable | any string | `"A"`, `"CNT"`, `"Self"` |
| Behavior parameter | plain positive int `1..N` | only valid if `parameters` has ≥N entries |
| Faction (shared) register | `{ "fr": <id> }` | `{ "fr": "some_key" }` |
| `exec` branch target | plain int = instruction index to jump to; omit = fall through to the next instruction; `false` = stop, take no further action on this path | `11` |

Local variables are the easy path for anything you don't need to persist
outside the behavior: pick any string name, use it consistently as both an
`out` target and later `in` source, and the game allocates the storage slot
for you when it compiles the behavior. There's no fixed register table to
manage by hand.

### Frame registers

Exactly 4 exist (hardcoded bound in `library.lua`), addressed as negative
integers. Mapping confirmed from `data/instructions.lua` (`GetRegisterOrComponentRegister`):

| Value | Register |
|---|---|
| `-1` | Signal |
| `-2` | Visual |
| `-3` | Store |
| `-4` | Goto |

(`observer.dsc` clears both at reset: `set_reg` with target `-3` and `-4`.)

### Parameters (sub-behaviors only)

If you're writing a reusable sub-behavior meant to be invoked via `call`
(id `call`, name "Call") or `load_behavior` (name "Load Behavior") rather
than run as a bot's main program, declare top-level `parameters` (and
optionally `pnames`) — one entry per input/output the sub-behavior exposes.
Inside that behavior's own instructions, reference parameter *N* with the
plain positive integer `N` (1-based) instead of a variable name or frame
register. Callers then supply/receive those parameters as extra trailing
arguments on the `call`/`load_behavior` node, one per declared parameter,
in order (see "Variable-length argument instructions" below) — this part
of the UI/library plumbing (`ui/Program.lua`) is more involved than a
single-behavior use case needs; if you only need one bot's own program,
skip `parameters` entirely.

## Branch and fall-through resolution

Every "what happens next" value — whether it's the instruction-level `next`
field or the value in an `exec`-typed argument slot — resolves the same way:

- **omitted / not present** → fall through to the next instruction in
  sequence (index + 1)
- **an integer** → jump to that instruction index
- **`false`** (or an index beyond the end of the instruction list) → stop;
  don't continue down this path this tick

Instructions with more than one `exec` argument (e.g. `check_number`'s
"If Larger" / "If Smaller") branch based on which condition the instruction's
own logic decides is true at runtime — you supply a target (or leave it to
fall through, or set `false`) for each, and only the one that actually
matches fires. Instructions with zero `exec` args just use the top-level
`next` field (or its default) unconditionally.

## Hidden literal fields (`make_asm`)

A few instructions take one configured value that isn't a normal wired
argument — it's set once on the node itself (a dropdown, text box, or
sub-behavior picker in the visual editor) and shows up as a plain named
field alongside `op`, not a numbered key. Enumerated from every `make_asm`
in `data/instructions.lua` (field name, and the default if omitted):

| Instruction id | Field | Default | Meaning |
|---|---|---|---|
| `call` | `sub` | `false` | id of the library behavior to call |
| `load_behavior` | `sub` | `false` | id of the library behavior to load remotely |
| `domove` | `c` | `1` | `1` = Synchronous, `2` = Asynchronous |
| `moveaway_range` | `c` | `1` | movement mode, as above |
| `scout` | `c` | `1` | movement mode, as above |
| `dodrop` | `c` | `2` | drop mode |
| `dopickup` | `c` | `2` | pickup mode |
| `request_item` | `c` | `2` | request mode |
| `request_wait` | `c` | `2` | wait mode |
| `for_producers_items` | `c` | `1` | iteration mode |
| `bitwise_op` | `c` | `1` | selected bitwise operator |
| `lock_slots` | `c` | `1` | lock mode |
| `for_signal_match` | `c` | `1` | match mode |
| `count_item` | `c` | `1` | count mode |
| `get_unit_info` | `c` | `1` | which info field to read |
| `get_unit_power_info` | `c` | `1` | which info field to read |
| `get_item_info` | `c` | `1` | which info field to read |
| `count_slots` | `c` | `1` | count mode |
| `notify` | `txt` | `false` | notification text |
| `set_signpost` | `txt` | `false` | signpost text |

For the numeric `c` fields, check that instruction's `node_ui` in
`data/instructions.lua` (or just try it in the in-game editor) to see what
each integer value corresponds to — the meaning is UI-label-specific and
not worth duplicating here.

## Variable-length argument instructions (`var_args`)

`call`, `load_behavior`, `build`, and `produce` accept extra trailing
positional args beyond their fixed `args` list — one per parameter the
target sub-behavior (for `call`/`load_behavior`) or blueprint (for
`build`/`produce`) declares. Encode each the same way as any other `in`/`out`
argument (literal, register, or variable); the count and in/out-ness must
match the target's own `parameters`/`params` definition. This is an advanced
case — most hand-written behaviors won't need it.

## Worked example

Annotated opening instructions of `observer.dsc` (decode it yourself with
`python3 dsc_codec.py decode observer.dsc` to see the rest):

```jsonc
"0": { "op": "unlock" },                          // run multiple instructions per tick
"1": { "0": { "num": 1 }, "op": "wait" },         // wait 1 tick (Time = literal 1)
"2": {                                            // scan: Filter1, Filter2, Filter3, Result(out), No Result(exec)
  "0": { "id": "v_enemy_faction" },               //   Filter1 = enemy faction
  "3": "A",                                       //   Result -> local var "A"
  "4": 11,                                        //   No Result -> jump to instruction 11
  "op": "scan"
},
"3": { "0": { "id": "v_enemy_faction" }, "1": -3, "op": "set_reg" },  // Store <- enemy faction id (unused marker)
"4": { "0": "A", "1": -4, "op": "set_reg" },      // Goto <- found enemy (var A): move to attack it
"5": {                                            // check_number: IfLarger(exec), IfSmaller(exec), Value(in), Compare(in)
  "0": 8,                                         //   If Larger -> jump to 8
  "2": "CNT", "3": { "num": 0 },                  //   comparing CNT > 0
  "op": "check_number"                            //   (If Smaller omitted -> falls through to 6)
},
"6": { "0": "A", "next": false, "op": "ping" },   // ping the enemy (var A); next=false, stop this path
"7": { "0": "CNT", "1": { "num": 1 }, "2": "CNT", "op": "add" },  // CNT = CNT + 1
"8": {                                            // check_number: CNT vs 10
  "1": false,                                     //   If Smaller -> false, stop
  "2": "CNT", "3": { "num": 10 }, "op": "check_number"
                                                   //   (If Larger omitted -> falls through to 9)
},
"9": { "1": "CNT", "next": false, "op": "set_reg" } // reset CNT (Value omitted = clear), next=false
```

Note how `scan`'s and `check_number`'s numbered keys skip straight to the
`out`/`exec` slots (`"3"`, `"4"`, or `"0"`, `"1"`) when the earlier `in`
slots (`Filter2`, `Filter3`) are left unused — the positions are fixed by
`instructions_index.md`'s `args` order, not by how many you fill in.

## Recommended authoring workflow

There's no assembler/validator for this format — the game's compiler
(`GetFactionBehaviorAsm`) is the only thing that checks it, at load time.
To hand-author safely:

1. Decode an existing behavior close to what you want (`data.behaviors`,
   or `observer.dsc`) with `dsc_codec.py decode` to get a real starting
   structure.
2. Edit the JSON: add/remove/rewire instructions using
   `instructions_index.md` for each instruction's `args` order and this
   file for value/branch encoding.
3. Re-index every instruction key if you insert/delete entries in the
   middle — `exec`/`next` targets are absolute instruction indices, so
   inserting an instruction shifts every index after it and any jump that
   pointed past that point needs updating.
4. Encode with `dsc_codec.py encode`, then immediately decode the result
   again and diff against what you intended — this round-trip is your only
   correctness check outside the game itself.
5. Load it in-game (paste into the behavior library) to confirm it opens
   cleanly in the visual editor and runs as expected.
