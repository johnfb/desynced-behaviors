# Observer Redesign: Two-Task Architecture

Design doc for reworking `library/observer.dcs`, written before touching any `.dcs`/BSF —
same "spec first" convention `blight_magnifier_mining.md` and `combat_squad_spec.md` used.

**Status (2026-07-13): implemented, reviewed, and checked in as `library/observer.dcs`.**
Both tasks are done. Getting here required resolving a real blocker first: `Async Radar`'s
filter/result attribution ambiguity, fixed by redesigning its interface
(`State*`/`NextState` replaced by `Tag*`/`Pending Tag*`/`Next Tag`, deliberately with **no
result-queueing of any kind** — an earlier "queue-and-delay-one-tick" fix was rejected by the
user as a workaround, not a solution) — see "`Async Radar` subroutine" below for the final
interface and "Validated against a real caller" for how `library/mining_leader.dcs` was
rebuilt around it, catching two real bugs along the way. Task 1 (sensing loop) was then
authored, compiled, and — after the user rebuilt its state transitions directly in-game into
a priority-lock cascade rather than the round-robin this doc originally sketched — reviewed
and had one real bug fixed (the Dropped stage's cycle-completion bookkeeping wasn't shared
between its found/empty branches). Task 2 (movement loop) was authored, then substantially
rewritten by the user directly in-game (`value_type`-based `Config` classification, genuine
directional-bias random walking, tuned standoff constants) and reviewed clean, no bugs found.
See each task's own section below for the actual implemented design, not just the original
plan.

## Background

The current `observer.dcs` is one linear per-tick pass: `unlock() -> wait(1) -> [scan for
enemy, then damaged, then infected, then dropped item, reporting/pinging as it goes] ->
[movement: random-walk or follow Config]`. Both "sensing" and "movement" already happen
every tick, just glued together sequentially with no real separation of concerns, and
sensing calls the `scan` (Radar) instruction directly — a synchronous, immediate scan every
single tick regardless of what hardware is actually equipped.

The user just added `library/async_radar.dcs` ("Async Radar") as a reusable subroutine, and
wants the redesigned Observer to (1) call that instead of `scan` directly, and (2) be
structured as two clearly-separated, concurrently-running tasks rather than one linear pass.
Desynced behaviors have no real threading — "concurrent" here means both tasks' state is
advanced once per tick, each driven by its own persisted state variables (the same
explicit-state-machine idiom `MinerDrone`/`MagnifierSignal` already use), not true
parallelism.

## `Async Radar` subroutine — what it actually does

**Signature**: `Async Radar(Radar*, Next Tick*, Filter 1, Filter 2, Filter 3, Result*, Tag*,
Pending Tag*, Next Tag)`. `Radar`/`Next Tick`/`Pending Tag` are read *and* written every call,
so the caller must own them as its own persistent locals (a `call`ed subroutine's own
internals are always freshly allocated per call — this can't hold state internally).

What it does, per call:

1. **Auto-detect and cache the equipped radar/sensor component** — unchanged by the interface
   redesign below; full mechanism (priority cascade, `has_like_component` gate, Scout Radar
   exclusion) is in "No-radar fallback" further down.
2. **Poll gate**: reads `simulation_tick()` and compares to `Next Tick`; if the hardware's
   own cadence hasn't elapsed yet, the call is a cheap no-op (pops out).
3. **Hardware path, once the cadence has elapsed**: reads register 4 (`Result`) *live*,
   directly off the physical radar component — whatever the engine itself computed using
   filters armed on the *previous* completing call. In the same step, `Tag := Pending Tag`
   (its value *before* this call) — since `Pending Tag` only ever gets updated on a
   completing call, to whatever `Next Tag` was submitted *then*, this correctly labels
   `Result` with the identity of the filters that actually produced it, no matter how many
   non-completing calls happened in between. Then writes the caller's current `Filter 1/2/3`
   into registers 1-3 (arming the *next* cycle), sets `Next Tick = now + Radar's own num`,
   and finally `Pending Tag := Next Tag` (queuing this call's own identity for whichever
   future completion delivers *its* result).
4. **Fallback path (no radar)**: `Result` computed synchronously via
   `get_closest_entity(Filter 1/2/3)` from *this same call's* own filters — zero lag — so
   `Tag := Next Tag` directly, no `Pending Tag` involvement needed at all.

### Interface redesign, and why (superseded an earlier `State*`/`NextState` design)

The original design used `State*`/`NextState` as a bare completion echo (`State := NextState`
on every completing call) — fine for a caller with exactly one outstanding query, ambiguous
for one that cycles through several (like Task 1's planned enemy→damaged→infected→dropped
cascade below), because the hardware path has a **one-poll pipeline lag** (`Result` reflects
the *previous* call's filters) while the fallback path has **zero lag** (reflects *this*
call's own filters) — and a caller has no way to observe which path just ran, so no single
fixed attribution rule is correct for both.

Two fixes were explored and rejected before landing on the current design:

- **Queue-and-delay the fallback path by one call** (a `Pending Result*` param, artificially
  matching the hardware path's lag so one uniform rule works everywhere) — technically
  correct, but **the user rejected it outright as a workaround, not a fix**: it fabricates a
  delay that doesn't naturally exist, purely to paper over the interface. It also had a real,
  independently-disqualifying cost: *every* call site sharing a `Radar` would need to
  consistently thread `Pending Result` through, including fire-and-forget calls that don't
  care about the output at all, or silently fork the queue and corrupt whichever call site
  actually relies on it.
- **A memory-array-based queue/stack**, keyed by an `Index` value (the user's own proposal) —
  workable, but memory arrays are global across the *entire call stack*, not scoped per call
  (see [[reference_memory_arrays_global_across_calls]] / `behavior_format.md`'s "Top-level
  envelope" section), so this leans directly into a real collision-risk surface, and costs
  every caller a `Memory Set` or two before every single call — even callers (like Mining
  Leader, see below) that never actually need multi-way disambiguation at all.

**The insight that resolved it**: only the *identity* needs shadowing in software — the
actual result data never does, because it's already sitting in the physical hardware
register (or computed fresh, in fallback mode), and reading it live is always correct.
`Pending Tag` is a single small id value, not a copy of the result data, which is why it
sidesteps both rejected designs' costs: no artificial delay (the register itself *is* the
naturally one-step-behind state — reading it directly is enough), and no global/keyed
storage (an ordinary persistent local, passed exactly like `Radar`/`Next Tick` already are).

**A clean, useful property of this shape**: since parameters are passed by reference, a
caller with only one outstanding query at a time (like Mining Leader) can pass the *same*
variable for both `Tag` and `Pending Tag` at a call site — the internal `Tag := Pending Tag`
step becomes a genuine no-op (same storage, not "the second write wins" — they were never two
different values to begin with), so the net behavior reproduces the *original*
`State`/`NextState` echo exactly. A caller needing real disambiguation (multiple different
in-flight queries, like Task 1) just passes two separate variables instead. Same interface,
no separate "mode" — the caller decides per call site.

**Dispatch idiom**: react to a delivered `Tag` via `jump(Label=Tag)` — a label whose
`(id, num)` literally *is* the expected tag value — not `compare_item`/`check_number`
branching. `jump`'s own "no label matched" behavior already falls through naturally to
"nothing changed, keep waiting," so this costs no more instructions than the label needs
anyway, and stays consistent with this project's established jump/label idiom (Mining
Leader's own `v_broken[num=1]`/`[num=10]`, `HexIndexOf`'s region dispatch) rather than
introducing a more verbose pattern just for this one case.

### No-radar fallback: `has_like_component` + Scout Radar exclusion

Many of the mobile units this runs on won't have any radar/sensor component equipped at all
(radar-less by design, or the socket is spent on something else). The original `scan`
instruction handles this natively — no radar equipped silently degrades to a visible-range
search, equivalent to `get_closest_entity`. Fixed **inside `async_radar.dcs`** (any future
caller of this subroutine gets the fallback for free, no two calling conventions).

There's a real, purpose-built instruction for "does this unit have anything from a component
family equipped," initially missed: `has_like_component` (`data/instructions.lua:3812`). It
does genuine family/prototype matching, not exact-id matching like `is_equipped` — it
resolves whatever `Component` you pass to that component's own `base_id` (set at
`RegisterComponent` time, propagating down the whole inheritance chain), and since all 8
radar/sensor component ids share the identical `base_id = "c_portable_radar"`, it doesn't
matter which one you pass — they all ask the same family-membership question. (Same
mechanism independently confirmed via `reveal_if_stealthed`'s
`owner:FindComponent("c_stealth", true)` for the Stealth family — not a one-off.)

**As implemented in `async_radar.dcs`** (built directly by the user, reviewed node-by-node
against real engine semantics): `has_like_component(Component=c_portable_radar)` gates entry
from *outside* the existing detection `sequence()` block — has to sit outside, since
`sequence`'s `Last` stage always runs once you're inside the block at all, so there's no way
to enter and skip the real hardware-register logic from inside it. `Failed` → jumps straight
to the fallback (`Radar`/`Next Tick` untouched). Inside the sequence, if all 8 known
component checks fail, `set_reg(Target=Radar)` with no `Value` writes a genuinely empty
register into `Radar` (confirmed against `InstGet`: an unwired arg resolves via
`Tool.NewRegisterObject()`, a real empty register with `is_empty=true`, not merely a numeric
0). The hardware branch then opens with `is_empty(Value=Radar)` — `Has Value` → real polling;
empty → falls straight into the *same* fallback node the gate's own `Failed` pin uses. One
fallback implementation, two paths converging on it cleanly, no duplicated logic.

**One real gap, resolved as intentional:** the component family is bigger than the 8 ids in
the cascade — `c_scout_radar` (`data/components.lua:4270`) shares the same `base_id` but was
missed originally, and has an incompatible 2-register layout (`Filter`/`Result` only, not the
other 7's `Filter1/2/3`/`Result`) that can't be added to the shared register-index logic
without its own special case. A unit with *only* Scout Radar equipped passes the family gate
but fails the detection cascade, converging on the same visibility-range fallback (graceful,
not a stall — just a silent loss of Scout Radar's actual 30-tile range). The user confirmed
Scout Radar was always meant to be unsupported and documented this directly in
`async_radar.dcs`'s own `desc` field and inline `cmt`s, so it's self-documenting in the
`.dcs` rather than only recorded here.

### Validated against a real caller: Mining Leader V4.0

Mining Leader (`library/mining_leader.dcs`) was rebuilt around this interface directly by the
user during design review, and the rebuild is informative beyond just confirming the
interface works — it settles on a materially different, better shape than either the
original design or Task 1's own plan below:

- **One shared call site**, in the `Begin` hub, called unconditionally every tick regardless
  of which phase Mining Leader is currently in — not one call site per phase. Each phase
  reacts to whatever that one call delivered (`$Tag`/`$PendingTag`/`$ScanResult`) via
  `switch` (an id-equality dispatch instruction, checked against source since it wasn't
  previously used in this project — falls into a plain id-comparison branch for bare id-value
  tags like these, not its entity-matching branch) to decide what to request next
  (`$NextFilter`/`$NextTag`), rather than each phase owning its own call and its own filter
  wiring.
- **`Tag`/`Pending Tag` genuinely separate** (not aliased) — Mining Leader checks *both* "what's
  currently armed" (`$PendingTag`, to avoid redundantly re-requesting a query already in
  flight) and "what was just delivered" (`$Tag`) each tick, giving it a fully-informed
  decision without ever needing explicit edge-detection bookkeeping of its own.
- **This shape eliminates a whole class of bug for free**: the original multi-call-site
  design needed *every* site sharing a `Radar` to consistently thread `Pending Tag` through,
  and a fire-and-forget call (Mining Leader's old Emergency-handling re-arm) that didn't wire
  it would silently desync the software-side tracking from the physical hardware state. With
  one call site, there's nothing else to desync from.

Two real bugs were found and fixed across two review passes on Mining Leader specifically
along the way (both rooted in an intermediate `$NextState` variable that no longer exists
after the single-call-site rebuild — a dependency-ordering issue where it was read before
ever being written, corrupting dispatch on a later completion). Not narrated in detail here
since the variable itself is gone in the current design; worth recording that the review
process caught real, non-obvious bugs before they'd have shipped, twice — the reason this
whole interface redesign was worth pausing Observer for in the first place.

## Task 1: sensing loop

**Implemented, compiled, and reviewed** (superseding an earlier round-robin-cascade draft of
this section) — built directly by the user in-game, not a plan anymore. It's a **priority-lock
cascade, not a round-robin**: finding something at a higher-priority stage means *staying* on
that stage (enemy) or *resetting back to the top* (damaged, infected), never advancing past it
— only an empty result at a stage advances one step down the priority ladder. Concretely:

- **Enemy** (top priority): found → report, then submit *nothing different* next call — no
  `$NextFilter`/`$NextTag` write at all in that path, so the same enemy filter just keeps
  getting resubmitted. "Keep tracking" is implemented by omission, not a special case. Empty →
  advance filters/tag to Damaged.
- **Damaged**: found → report, then explicitly reset `$NextFilter1/2`/`$NextTag` back to
  enemy. Empty → advance to Infected.
- **Infected**: found → report, then reset back to enemy (reusing Damaged's own "reset to
  enemy" block rather than duplicating it). Empty → advance to Dropped.
- **Dropped** (only reachable at all once enemy/damaged/infected were *all* empty this pass):
  found or empty, either way — report first if found, then **unconditionally** increment
  `$CycleId`, publish `$CycleAccum` into `$CycleFoundAny`, and reset `$CycleAccum` for the
  next pass, before resetting back to enemy. (A real bug here — only the *empty* branch did
  this bookkeeping in an earlier draft, so a found dropped item silently skipped publishing a
  cycle completion and left `$CycleAccum` contaminated for a later pass — found during review,
  fixed by making the bookkeeping the unconditional tail both branches fall into, matching the
  shape the other three stages already use.)

Tags are just the filter constants themselves (`v_enemy_faction`, `v_damaged`, `v_infected`,
`v_droppeditem`) rather than an invented label family — simpler than the original plan below,
since the filters are already unique per stage, nothing extra needed to identify them.

**Needs genuine disambiguation** (multiple different filters used across one shared
`Result`/`Tag` pair) — unlike Mining Leader's aliased-shortcut case above, `Tag` and
`Pending Tag` are two separate persistent locals here, not the same variable. Dispatch is
`jump(Label=$Tag)` after each call: no match (still holding whichever tag the *previous*
completion delivered) → nothing new this tick, keep waiting; a match → handle that stage's
fresh result as described above.

**Why this shape gives Task 2 exactly the guarantee it needs, for free:** because finding
anything in enemy/damaged/infected loops straight back to the top without ever reaching
Dropped, the cycle-completion bookkeeping is *only* ever reached when all three were already
empty this pass. So `$CycleId` advancing with `$CycleFoundAny = false` now means precisely
"all four categories were checked this pass and none of them found anything" — exactly the
"scanned for all four, no result" condition Task 2 needs before considering a random move (see
Task 2's own note below) — no extra coordination needed between the two tasks beyond reading
those two variables, despite Task 1's control flow being considerably more involved than a
flat round-robin.

`$CycleId` and `$CycleFoundAny` are the only two things Task 2 needs to read from Task 1.

## Task 2: movement loop

**Implemented, reviewed, no bugs found** — authored first per the plan below, then
substantially rewritten by the user directly in-game. The rewrite is better than the original
plan in real ways, not just a re-styling; documented here against the actual final shape.

**Structural change**: wrapped in the same `sequence()`-per-tick shape Task 1 already uses,
with the Bot-only gate implemented via the `POP`-vs-`last()` distinction rather than a plain
branch — `unit_type(Unit=Self)`'s `Bot` pin routes to `POP` (ends the sequence's first stage
*normally*, so it auto-advances into the stage holding Task 2's own logic), while
Building/Construction/the default all fall through to an explicit `last()` (breaks straight
to the tag dispatch, skipping Task 2 entirely) — reusing block-stack mechanics rather than an
`if`/`else`. `$Self` and `$Vis` (visibility range, `get_unit_info(c=2)`) are now computed
*once* at init rather than refetched per use — safe for `$Self` (never changes); a real,
accepted tradeoff for `$Vis` (could go stale if a Visibility Range module gets
added/removed mid-run — harmless if it does, just a slightly-off wander radius, not a
functional break).

**`Config` classification now uses `value_type`, not `is_empty` + `unit_type`.** Checked
`data/instructions.lua:737` since it's load-bearing: `value_type` returns without touching
`state.counter` when the value is genuinely empty (`if not value or value.is_empty then
return end`) — a separate, independently-omittable outcome from its declared type pins
(Item/Unit/Component/Tech/Value/Coord). Since neither the empty case nor `Coord` is
explicitly annotated in the real node, both default to the same positionally-next node —
confirmed this is the identical "two independently-omitted pins converge on one fallthrough"
mechanism already relied on elsewhere in `async_radar.dcs`, not a coincidence. So "empty or
coordinate" and "unit" correctly split into the two branches below with one instruction.

**Priority 1 — enemy avoidance, every tick, unconditionally, checked *first* via a jump but
written physically last in the file (stylistic, not a priority change):**
`get_closest_entity(Filter=v_enemy_faction)` (native `visibility_range`, not radar range). If
found: `has_like_component(Component=c_alien_stealth)` (family-match, same mechanism as
`Async Radar`'s own radar-family detection) picks the standoff distance — **tuned in-game to
10 (stealthed) / 20 (not stealthed)**, revised up from this doc's original 5/14 placeholder
guesses — then `moveaway_range`. Finding an enemy skips Priority 2/3 entirely for the tick.

- **`Config` is a unit** → follow it, using the exact distance-vs-`Config`'s-own-`num`-field
  idiom already established in this file: `If Smaller` (too close) → `moveaway_range`;
  `If Equal` → do nothing; default/`Larger` (too far) → `domove`.
- **`Config` is empty or a coordinate** → the "wait for a clean cycle" gate, using
  `$WaitTarget` exactly as planned (armed to `$CycleId + 1` the first time via
  `is_empty($WaitTarget)`, compared against `$CycleId` once armed, re-armed after every
  outcome) — then, once a clean cycle is confirmed (`$CycleFoundAny` empty):
  - **`Config` empty** → `random_coordinate(Coordinate=$Self, Range=$Vis, Result=@goto)` —
    plain undirected wander, written straight to `@goto` (no intermediate temp needed,
    `Result` accepts any writable target directly). **`Config` never gets set in this branch**
    — confirmed intentional, not a gap: an empty `Config` is a stable, permanent "just wander
    around self" mode, mirroring the original `observer.dcs`'s own behavior of never
    "graduating" the empty case into a coordinate one. Directional bias (below) is only
    available once `Config` is deliberately seeded with a starting coordinate.
  - **`Config` is a coordinate** → real directional-bias wandering, closing the gap this doc
    previously flagged as unclosed (`scout_rand_range` itself can't be reused, still true —
    it drives movement internally with no output register). Computes
    `$A = 2·$D − Config` where `$D = get_location(Self)` (current position) and `Config`
    (the position recorded *before* the previous step) — extrapolating the last observed
    movement vector forward — then `random_coordinate(Coordinate=$A, Range=$Vis,
    Result=@goto)` randomizes around that biased point. **`Config` is then set to `$D`
    (current position *before* this move), not the newly computed destination** — checked
    this deliberately since it looks backwards at first: comparing next cycle's position
    against "where I was before this step" gives a real observed-movement vector; storing the
    destination instead would compare "where I am" against "where I just said I'd go," which
    collapses to ~zero once movement actually completes. Grounding the bias in observed
    motion rather than intended motion is also more robust to interrupted/blocked movement.

## Resolved decisions

1. **Enemy-avoidance standoff range** — derived from self, not a fixed constant, and now
   **two-tier based on stealth** per the user's follow-up context: most mobile units running
   this are unarmed (socket given to Long-Range Radar) and most are planned to carry a
   stealth component, which the user confirmed makes enemies never engage regardless of
   distance — but splash damage from nearby fights is still a real risk, so avoidance stays
   worthwhile, just at a smaller buffer.
   - **Not stealthed**: `stats_unit` (`data/instructions.lua` ~line 2752, the table
     `get_unit_info`'s `c` selects into) only has `Durability`/`Visibility Range`/`Movement
     Speed`/socket counts — there's no "weapon range" stat exposed there, and a *weapon's*
     range lives on the item (`stats_item[2]`, via `get_item_info`), which would need
     enumerating equipped items to find — a real separate chunk of work, not a one-line
     substitution, and mostly moot anyway since these units are typically unarmed. Built as a
     fixed constant, originally a 14-tile placeholder guess — **tuned in-game to 20 tiles**
     once actually watched in play.
   - **Stealthed** (`c_alien_stealth` or `c_integrated_stealth` equipped, detected via
     `has_like_component` — the same family-match mechanism `Async Radar` uses for its own
     radar detection, reused here for the stealth family): a much smaller
     **splash-safety-only buffer** — there's no generic way to query an *enemy's*
     splash/blast radius from here, so this was always a flat guess pending in-game tuning,
     not derived from anything; originally 5 tiles, **tuned in-game to 10 tiles**.
   - Weapon-range-if-armed (for the rare armed unit) remains flagged as a deferred follow-up
     refinement rather than silently dropped.
2. **Ping throttling** — explicit minimum interval, not just hardware cadence. A persistent
   `$LastPingTick` local: on an `S_ENEMY` report, only `ping()` if
   `simulation_tick() - $LastPingTick >= <min interval, e.g. ~10-20 ticks>`, then update
   `$LastPingTick`. Needed regardless of which radar is equipped (Portable Radar's 2-tick
   cadence would otherwise ping far more often than "every second or two").
3. **Explore/step radius** — `get_unit_info(c=2)` ("Visibility Range") reused for both the
   `Config`-empty (walk from `Self`) and `Config`-coordinate (step from `Config`) cases,
   matching what today's `observer.dcs` already does for its one random-walk case — now
   cached once at init rather than refetched (see Task 2's own section). The
   `Config`-coordinate case additionally got genuine directional bias in the final
   implementation (see Task 2's section) — closing a gap this item originally left open.
4. **Re-arm granularity after "found something"** — wait for another *full* 4-stage cycle
   (not just the next single stage) before re-checking, consistent with the "wait for a full
   cycle" rule used when first arriving at this branch.
