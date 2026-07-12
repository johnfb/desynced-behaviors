# Observer Redesign: Two-Task Architecture

Design doc for reworking `library/observer.dcs`, written before touching any `.dcs`/BSF —
same "spec first" convention `blight_magnifier_mining.md` and `combat_squad_spec.md` used.
Not yet implemented.

**Status (resumed 2026-07-13):** The blocker that paused this doc — `Async Radar`'s
filter/result attribution ambiguity — is resolved. The interface was redesigned
(`State*`/`NextState` replaced by `Tag*`/`Pending Tag*`/`Next Tag`, deliberately with **no
result-queueing of any kind** — an earlier "queue-and-delay-one-tick" fix was rejected by the
user as a workaround, not a solution), reviewed twice against the real
`async_radar.dcs`/`mining_leader.dcs` files the user built directly, and two real bugs found
during review were eliminated by a further rebuild of Mining Leader itself (collapsing its
several `Async Radar` call sites down to one shared call in its `Begin` hub). See "`Async
Radar` subroutine" below for the final interface and "Validated against a real caller" for
how the Mining Leader rebuild works. Task 1 (sensing loop)'s design below has been updated to
the new interface and is unblocked. Task 2 (movement loop) still hasn't been started.

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

A 4-stage cyclic state machine wrapped around one `Async Radar` call per tick, mirroring
today's priority order:

`S_ENEMY -> S_DAMAGED -> S_INFECTED -> S_DROPPED -> (wrap) S_ENEMY -> ...`

Filters per stage (unchanged from today's cascade): `S_ENEMY = v_enemy_faction`,
`S_DAMAGED = v_damaged, v_own_faction`, `S_INFECTED = v_infected, v_own_faction`,
`S_DROPPED = v_droppeditem`.

**Needs genuine disambiguation** (multiple different filters cycling through one shared
`Result`/`Tag` pair) — unlike Mining Leader's aliased-shortcut case above, `Tag` and
`Pending Tag` must be two separate persistent locals here, not the same variable.

Each tick: call `Async Radar` with `Filter 1-3` = the *current* stage's filters, `Next Tag` =
that same stage's own distinct tag identity (e.g. one label icon with `num=1..4`, the same
`(id, num)`-as-family idiom Mining Leader's `c_radar[num=1]` already uses),
`Tag`/`Pending Tag`/`Radar`/`Next Tick` = Observer's own persistent locals. React via
`jump(Label=$Tag)`:

- **No match** (`$Tag` still holds whichever stage's identity the *previous* completion
  delivered, or the initial empty value) → nothing new landed this tick; keep submitting the
  same stage's filters/tag next tick, unchanged.
- **Matches the current stage's own tag** → a fresh `Result` for that stage just arrived. If
  non-empty: `set_reg` it onto `@visual`/`@signal` (same convention as today); if the stage
  was `S_ENEMY`, also `ping(Target=Result)` (throttled — see "Resolved decisions" #2). Then
  advance to the next stage in the cycle for the following tick's submission.
- If the stage that just completed was `S_DROPPED` (i.e. we just wrapped back to
  `S_ENEMY`), that's a full-cycle boundary: increment a persistent `$CycleId`, and latch
  whether *any* of the 4 stages this past cycle had a non-empty `Result` into
  `$CycleFoundAny` (OR'd across all 4 stage completions, reset at the start of the new
  cycle).

`$CycleId` and `$CycleFoundAny` are the only two things Task 2 needs to read from Task 1.

## Task 2: movement loop

Gated first by `unit_type(Unit=Self)`: **buildings/construction sites do nothing** (matches
the user's spec directly). Everything below only runs if self is a bot.

**Priority 1 — enemy avoidance, every tick, unconditionally:**
`get_closest_entity(Filter 1=v_enemy_faction)` — this instruction natively uses
`owner.visibility_range`, i.e. *actual visible range*, not radar range, exactly the
distinction the user wants. If it returns an entity: overwrite that value's `num` field with
the desired keep-away distance via `set_number`, then `moveaway_range(Target=that)`.
Confirmed from `data/instructions.lua`: `moveaway_range` already no-ops once the target is
farther than its `num`-field range, so this is safe to call every single tick with no extra
"am I already far enough" state of its own.

The keep-away distance itself is **stealth-dependent** (see "Resolved decisions" #1 below):
most mobile units running this will be unarmed (socket spent on Long-Range Radar instead)
and most are planned to carry the alien Stealth mechanic (in this data's actual naming —
`c_alien_stealth` / `c_integrated_stealth`, not literally called "Cloak" anywhere in
`data/components.lua`), which the user confirmed suppresses enemy engagement entirely
regardless of distance — but not splash damage from fights the unit merely wanders into. So:
check both stealth component ids once per tick (or cache like `Radar`'s own detection, since
stealth doesn't change while running); stealthed → small splash-safety buffer; unstealthed →
the full engagement-range-based standoff.

**Priority 2 — only if no enemy in visible range**, classify `Config`:
`is_empty(Config)` first, then (if not empty) `unit_type(Unit=Config)` — any of the
Bot/Building/Construction pins firing means Config resolved to a real entity (follow
target); the "No Unit" fallthrough with `Config` non-empty means it's a bare coordinate.

- **Config is an entity** → follow it, reusing the exact idiom today's `observer.dcs`
  already uses for this case (`get_distance(Target=Config)`, `check_number` against
  `Config`'s own `num` field, `domove`/`moveaway_range` split at that range) — this directly
  confirms the user's "maybe the num part is the desired max range?" guess; it's already the
  established convention in this same file for exactly this purpose.
- **Config is empty or a coordinate** → the "wait for a clean cycle" logic:
  - A persistent `$WaitTarget` (`= $CycleId + 1`) is (re-)armed any time we're not already
    waiting on one. This is what makes "if we arrived mid-cycle, wait for *another* full
    cycle" work: we never act on a cycle that was already partway done when we started
    caring.
  - While `$CycleId < $WaitTarget`: do nothing (besides Priority 1).
  - Once `$CycleId` reaches `$WaitTarget`, consult `$CycleFoundAny` for the cycle that just
    finished:
    - **found something** → stay put; re-arm `$WaitTarget = $CycleId + 1` and keep
      re-checking every subsequent cycle (so we naturally start moving again once whatever
      we're broadcasting eventually gets handled and a later cycle comes back clean).
    - **found nothing** → take one random step, then re-arm `$WaitTarget` the same way (so
      we don't re-roll again until another full clean cycle, mirroring today's `is_moving()`
      gate against restarting a walk mid-move):
      - `Config` empty: `random_coordinate(Coordinate=Self, Range=<explore radius>)`,
        same as today's random-walk case.
      - `Config` a coordinate: `random_coordinate(Coordinate=Config, Range=<step radius>)`,
        then `Config := Result`. **Note:** `scout_rand_range` can't be reused directly for
        this despite the user's "similar to scout range" framing — confirmed from source,
        it drives `MoveTo` internally and has no output register at all, so there's nothing
        to write back into `Config`. `random_coordinate` centered on `Config` is the closest
        equivalent that actually exposes a coordinate; it won't reproduce
        `scout_rand_range`'s directional-bias term (biasing further in whatever direction
        the last step already went), just a uniform-random offset within range.

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
     substitution, and mostly moot anyway since these units are typically unarmed. Building
     this now as a **fixed constant around the user's own "10-12 tiles, not exactly sure"
     estimate — defaulting to 14 tiles** (a few tiles of margin over the observed range,
     since it's stated as approximate and erring toward more standoff is cheap for a
     non-combat sensing unit). Tune directly once you've watched it in play.
   - **Stealthed** (`c_alien_stealth` or `c_integrated_stealth` equipped): a much smaller
     **splash-safety-only buffer, defaulting to 5 tiles** — there's no generic way to query
     an *enemy's* splash/blast radius from here, so this is a flat guess pending in-game
     tuning, not derived from anything.
   - Weapon-range-if-armed (for the rare armed unit) remains flagged as a deferred follow-up
     refinement rather than silently dropped.
2. **Ping throttling** — explicit minimum interval, not just hardware cadence. A persistent
   `$LastPingTick` local: on an `S_ENEMY` report, only `ping()` if
   `simulation_tick() - $LastPingTick >= <min interval, e.g. ~10-20 ticks>`, then update
   `$LastPingTick`. Needed regardless of which radar is equipped (Portable Radar's 2-tick
   cadence would otherwise ping far more often than "every second or two").
3. **Explore/step radius** — `get_unit_info(c=2)` ("Visibility Range") reused for both the
   `Config`-empty (walk from `Self`) and `Config`-coordinate (step from `Config`) cases,
   matching what today's `observer.dcs` already does for its one random-walk case.
4. **Re-arm granularity after "found something"** — wait for another *full* 4-stage cycle
   (not just the next single stage) before re-checking, consistent with the "wait for a full
   cycle" rule used when first arriving at this branch.
