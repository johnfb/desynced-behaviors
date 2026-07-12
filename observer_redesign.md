# Observer Redesign: Two-Task Architecture

Design doc for reworking `library/observer.dcs`, written before touching any `.dcs`/BSF —
same "spec first" convention `blight_magnifier_mining.md` and `combat_squad_spec.md` used.
Not yet implemented.

**Status (paused 2026-07-12):** Task 1 (sensing loop) authoring was in progress and is
paused, not abandoned. While working out the exact node-by-node calling convention against
`Async Radar`, traced a real correctness issue: `Async Radar`'s hardware path (one-poll
pipeline lag — a completion's `Result` reflects the *previous* call's filters) and its
fallback path (`get_closest_entity`, zero lag — reflects the *current* call's filters) can't
both be attributed correctly by a caller using one fixed rule, and the caller has no visible
way to tell which path just ran. A same-call-lag fix confined to `async_radar.dcs`'s fallback
branch (queue-and-delay-one-tick, matching the hardware path's lag) was worked out in detail
and is captured in this session's history, but **the user considers this a workaround, not a
fix**, and wants to reconsider `Async Radar`'s calling interface itself before building
anything further on top of it — see `todo.md`'s new "Async Radar interface redesign" item for
the actual next step and why it now also involves `library/mining_leader.dcs` (the only
current caller). Task 1's design in this doc (the 4-stage `S_ENEMY`→`S_DAMAGED`→`S_INFECTED`→
`S_DROPPED` cascade, `$CycleId`/`$CycleFoundAny` handoff to Task 2, etc.) is still believed
correct at the *architecture* level — what's blocked is the low-level mechanics of correctly
consuming a single poll result once the interface changes, so expect this doc's Task 1
section to need a revisit once that's settled, not a rewrite from scratch. Task 2 (movement
loop) was never started.

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

Decompiled signature: `Async Radar(Radar*, Next Tick*, Filter 1, Filter 2, Filter 3,
Result*, State*, NextState)`. `Radar`/`Next Tick`/`State` are read *and* written every call,
so the caller must own them as its own persistent locals (a `call`ed subroutine's own
internals are always freshly allocated per call — this can't hold state internally).

What it does, per call:

1. **Auto-detect and cache the equipped radar/sensor component**, only once (cheap
   `is_equipped`/`check_number` check first; skips straight to step 2 if `Radar` already
   holds a valid, still-equipped component). Priority: `c_radar` > `c_small_radar` >
   `c_portable_radar` > `c_radar_array` (common radars), falling back to `c_radar_suite` >
   `c_alien_sensor` > `c_alien_sensor_wide` > `c_sensor_spike_comp` (advanced sensors) only
   if none of the common ones are equipped. Each match stores the component id **with its
   own real hardware refresh cadence baked into the value's `num` field**:
   `c_radar[num=10]`, `c_portable_radar[num=2]`, `c_radar_array[num=10]`,
   `c_radar_suite[num=10]`, `c_alien_sensor[num=5]`, `c_alien_sensor_wide[num=3]`,
   `c_sensor_spike_comp[num=5]`. If nothing at all is equipped, the whole call is a no-op
   (pops out immediately, doesn't even reach the polling logic below).
2. **Poll gate**: reads `simulation_tick()` and compares to `Next Tick`; if the hardware's
   own cadence hasn't elapsed yet, the call is a cheap no-op (pops out).
3. Once the cadence has elapsed: **reads register 4 (Result) off the actual radar
   component** — i.e. whatever the *engine itself* found on its own last internal scan,
   using whatever filters were written into registers 1-3 on the *previous* call — into the
   `Result` out-param. Then **writes the caller's current `Filter 1/2/3` into registers
   1-3** (arming the hardware for its *next* internal cycle), sets
   `Next Tick = now + Radar's own num`, and finally sets `State := NextState`.

So it's a real producer/consumer handshake against engine-native hardware state, not a
polled wrapper around `scan`: the calling behavior never blocks, and the actual scan cost
happens on the component's own schedule. The load-bearing consequence for Task 1's design:
**`State` becoming equal to whatever `NextState` you last passed is the only reliable
"a fresh Result just landed" edge** — there's a one-poll pipeline lag (the `Result` you read
back corresponds to the filters you set on the *previous* completed call, not the current
one), so Task 1 needs a "did `State` change since last tick" edge-check, not just a
level-check.

### Gap: units with no radar at all

Many of the mobile units this runs on won't have any radar/sensor component equipped at
all (radar-less by design, or the socket is spent on something else). The original `scan`
instruction handles this natively — no radar equipped silently degrades to a visible-range
search, equivalent to `get_closest_entity`. `Async Radar` as built doesn't: if none of the 8
known component ids match, it dead-ends out of the sequence with `Radar` still at its
default (empty/0) value, `State`/`Result` never touched. Called every tick from Task 1,
`State` would just never change — Task 1's edge-detect would never fire, and the entire
priority cascade would stall forever on `S_ENEMY` for any radar-less unit.

Fixing this **inside `async_radar.dcs`** (per the user's preference, and it's the right call
architecturally — any future caller of this subroutine gets the fallback for free, and
Task 1/Observer doesn't need two different calling conventions).

**Revised approach (superseding two earlier drafts of this section — first a cached
"confirmed none" sentinel, then an 8-`is_equipped`-OR-chain gate):** there's a real, purpose-
built instruction for exactly this, `has_like_component` (`data/instructions.lua:3812`),
initially missed. It does genuine family/prototype matching, not exact-id matching like
`is_equipped`:

```lua
basecomp = GetId(in_comp)
basedef  = data.components[basecomp]
baseid   = (basedef and basedef.base_id) or basecomp
findcomp = entity:FindComponent(baseid, true)   -- true = match by base_id, not exact id
```

Every component definition gets a `base_id` set at registration time
(`Comp:RegisterComponent`, `data/components.lua:169`: `comp.base_id = self.base_id or
self.id or id`), which propagates down the entire inheritance chain. Tracing the real
registrations: `c_portable_radar` is the root (`Comp:RegisterComponent(...)`, so its own
`base_id` = itself); `c_small_radar` derives from it; `c_radar`, `c_radar_array`,
`c_radar_suite`, `c_alien_sensor_wide`, `c_sensor_spike_comp` all derive from `c_small_radar`;
`c_alien_sensor` derives from `c_portable_radar` directly. **All 8 end up with the identical
`base_id = "c_portable_radar"`.** Since `has_like_component` resolves *whatever you pass* to
its `base_id` before searching, it doesn't matter which of the 8 you pass as `Component` —
`has_like_component(Component=c_radar)` and `has_like_component(Component=c_sensor_spike_comp)`
ask the exact same question: "does this unit have anything from the `c_portable_radar`
family equipped." (Same mechanism independently confirmed via `reveal_if_stealthed`'s
`owner:FindComponent("c_stealth", true)` for the Stealth family — not a one-off.)

This replaces the whole 8-way OR-chain with **one instruction call**:

- **New gate, `has_like_component(Component=c_radar)` (or any of the 8 — arbitrary; picking
  `c_radar` since that's the one these units are actually planned to carry), as a wrapper
  *around* the entire existing `sequence()` block (today's `n1`-`n40`), not inside it.** It
  still has to sit outside, not as a new stage within the existing sequence — `sequence`'s
  `Last` stage always runs once you're inside the block at all (confirmed from
  `behavior_format.md`'s block semantics: every wired stage runs to its own dead end, "and
  finally jumps to `Last`" unconditionally), so there's no way to enter the sequence and skip
  `Last`'s real hardware-register logic from inside it. Gating from outside sidesteps that
  entirely. `has_like_component` declares one `exec` pin, `Failed` (fires when nothing in the
  family is found); the default/fallthrough is the *found* case.
  - **Default/fallthrough (found)** → fall through into the existing `sequence()` block
    exactly as it is today, completely unmodified. (The old Stage "Second"/"Third" cascade
    still needs its own per-type `is_equipped` checks afterward — `has_like_component` only
    answers "is something in the family equipped," not *which* specific one, and the
    specific id + its own cadence `num` still needs picking and caching into `Radar`.)
  - **`Failed`** → the fallback: `get_closest_entity(Filter 1/2/3)` straight into `Result`,
    `State := NextState`, and stop — **`Radar`/`Next Tick` are never written**, so there's
    nothing to undo once a radar actually gets equipped; the very next call's gate simply
    starts passing and control flows into the untouched original logic, which sees `Radar`
    still at its untouched default and detects+caches fresh, same as a first-ever call. No
    extra state, no reset needed, no periodic-recheck timer required — the "recheck" *is*
    just every tick's gate.

This preserves the exact same call contract (`Filter 1-3` in, `Result`/`State` out, edge-
detect on `State`) for every caller regardless of which path fired, so Task 1 needs no
awareness of whether the unit actually has a radar, this tick or ever.

### As actually implemented, and reviewed

The user built this directly into `library/async_radar.dcs` before I got to it. Decompiled
and traced node-by-node against real engine semantics; it's correct, and one part is better
than the plan above: rather than duplicating the fallback at both the gate and inside the
sequence, the two failure paths **converge on one shared fallback** via a clean signal —

- `n1: has_like_component(Component=c_portable_radar)` (the actual root id used; confirmed
  above it doesn't matter which of the family is passed) gates entry from outside the
  sequence, `Failed` → jumps straight to the fallback, `Radar`/`Next Tick` untouched, exactly
  as designed.
- Inside the sequence, when Stage "Third" exhausts all 4 advanced-sensor checks with no
  match, the new `n22: set_reg(Target=Radar)` (no `Value`) writes a genuinely empty register
  into `Radar` — confirmed against `InstGet` (`data/instructions.lua:126`): an unwired arg
  resolves via `Tool.NewRegisterObject()`, a real empty register object with `is_empty=true`,
  not merely a numeric 0 (that's the *separate* `GetNum`-on-omitted-arg case documented
  elsewhere in this project's memory — a different code path). Stage "Third" then dead-ends
  normally into `Last`.
- `Last` now opens with `n31: is_empty(Value=Radar)` — `Has Value` → the real hardware
  polling logic (unchanged); default/empty → falls straight into the *same* fallback node
  `n1`'s `Failed` pin uses. One fallback implementation, two paths converging on it, no
  duplicated logic.

**One real gap found, not yet fixed:** the component family is bigger than the 8 ids in the
cascade. Every `RegisterComponent` chained off this family was re-grepped, turning up a 9th
member missed originally: `c_scout_radar = c_portable_radar:RegisterComponent("c_scout_radar",
{...})` (`data/components.lua:4270`), which inherits the identical `base_id =
"c_portable_radar"` the same way the other 7 do. Consequence: `has_like_component` at `n1`
treats a unit with *only* a Scout Radar equipped as "has one," lets it into the sequence,
where it fails both Stage 2 and Stage 3, hits the `n22` fallback path, and ends up on
`get_closest_entity` (native visibility range) every tick forever — not a stall (the
`is_empty` convergence handles it gracefully), but a silent loss of Scout Radar's actual
30-tile scan range. Not a one-line fix either: Scout Radar defines its own `registers = {
Filter, Result }` (2 registers), not the `Filter1/Filter2/Filter3/Result` (4-register) layout
the other 7 share and that `Last`'s hardware branch hardcodes register indices 1-4 against —
proper support would need its own special-cased register-index branch, not just another line
in the priority cascade. **Resolved as intentional, not a bug**: the user confirmed Scout
Radar was always meant to be unsupported and added a top-level `desc` plus inline `cmt`s
directly on `async_radar.dcs` documenting the fallback-to-visibility-range behavior at `n1`,
`n22`, `n33`, and `n45`, so this is now self-documenting in the `.dcs` itself rather than
only recorded here.

## Task 1: sensing loop

A 4-stage cyclic state machine wrapped around one `Async Radar` call per tick, mirroring
today's priority order:

`S_ENEMY -> S_DAMAGED -> S_INFECTED -> S_DROPPED -> (wrap) S_ENEMY -> ...`

Filters per stage (unchanged from today's cascade): `S_ENEMY = v_enemy_faction`,
`S_DAMAGED = v_damaged, v_own_faction`, `S_INFECTED = v_infected, v_own_faction`,
`S_DROPPED = v_droppeditem`.

Each tick: call `Async Radar` with `Filter 1-3` = the *current* stage's filters, `NextState`
= the next stage in the cycle, `State`/`Radar`/`Next Tick` = Observer's own persistent
locals. Compare `State` before vs. after the call:

- **No change** → still waiting on this stage's poll (or radar hardware missing entirely);
  nothing else to do this tick.
- **Changed** → a fresh `Result` for the *current* stage just arrived. If `Result` is
  non-empty: `set_reg` it onto `@visual`/`@signal` (same convention as today); if the stage
  was `S_ENEMY`, also `ping(Target=Result)`. No separate ping-throttle counter is needed —
  polls for `S_ENEMY` can only complete once per full hardware cadence anyway (2-10 ticks
  depending on equipment), which already lands in the "every second or two" the user asked
  for. Then advance to the next stage for next tick's call.
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
