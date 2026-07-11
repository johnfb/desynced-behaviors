# Blight Magnifier / Overclock Economics and a Coordinated Miner-Drone Design

A worked-out design doc covering two things built in the same session: (1) the
real math behind overclock modules, building base efficiency, and the
oversized-socket bonus, applied to picking building layouts for Blight
Magnifiers; (2) a full drone-mining behavior — reservoir-sampled node
selection, Signal-register-based coordination to avoid oversubscribing one
node, and a corrected understanding of what the native engine already does
for you — written directly in `behavior_source_format.md`'s graph grammar as
a real test of that format's usability for original authoring, not just
decompiling.

## Part 1: Component efficiency math

### The core formula

Confirmed directly in `get_work_time` (`data/components.lua:7405-7416`), the
only Lua-visible implementation of this — used by Blight Extractor and Blight
Magnifier specifically, since both are "self-timed work" components rather
than generic recipe-driven producers:

```
eff_boost = frame.component_boost (the building's own intrinsic bonus)
          + sum of every c_moduleefficiency-family component's `boost`,
            any size, anywhere on the building (additive, confirmed via
            SumModuleBoosts, utilities.lua:584)
          + faction.component_boost - 100 (Re-Simulator global bonus, usually 0)
          + 50  if this specific component sits in a socket LARGER than its
                own attachment_size, else 0 (flat, not scaled by how much
                bigger — Medium-in-Large and Small-in-Large both just get +50)

speed multiplier = (100 + eff_boost) / 100
```

Overclock modules (`c_moduleefficiency*`, `components.lua:357-396`) come in
four sizes — Internal +20%, Small +50%, Medium +100%, Large +150% — cost no
power, and their effect is building-wide, not confined to their own socket.
Every building has 2-4 Internal sockets (confirmed via `data/visuals.lua`
socket lists) that never compete with production-component placement, so
filling them with Internal Overclock Modules is close to a free lunch.

**Socket size ordering** (`ui/utilities.lua:197-199`,
`attachment_sizenums`): Internal=1, Small=2, Medium=3, Large=4. A socket
accepts any component of its own size or smaller; the +50 oversocket bonus
only fires when the *component* is smaller than the *socket* it's actually
placed in.

### The mistake made and corrected: opportunity cost is not always 100pp

Early in this analysis a shortcut formula was used — "sacrificing one
Medium/Large slot for an Overclock Module instead of a magnifier always costs
exactly 100 percentage points, regardless of socket size" — derived from the
fact that Large-OC (150%) minus Medium-OC (100%) exactly equals the
oversocket bonus (50%). **This shortcut is only true when there is exactly
one magnifier in the building.** With two or more magnifiers, it breaks,
because the +50 oversocket bonus is *per-component* (only the one magnifier
literally sitting in the Large socket gets it) while an Overclock Module's
boost is *shared building-wide* (every magnifier benefits equally). Spreading
one Large socket's +150% across several magnifiers beats letting one of them
keep a private +50%, once there's more than one magnifier to spread it over.

The concrete case this bit: for `f_building3x2a` ("Building 3x2, 1L3M"), the
shortcut predicted an all-4-magnifier configuration would win (13.20x). The
correct per-slot brute-force enumeration (every Medium/Large socket
independently either "magnifier" or "Overclock-of-its-max-size", summing each
magnifier's own `eff_boost` including its own personal oversocket bonus if
applicable) gives the real optimum: **3 magnifiers + 1 Large Overclock =
12.90x**, beating all-4-magnifiers' **11.70x**. The lesson generalizes:
*any* building with a Large socket and 2+ magnifiers needs brute-force
per-slot enumeration, not a shortcut — the Large socket should hold an
Overclock Module whenever more than one magnifier is in play, never a
magnifier itself.

### Corrected building table

One earlier mistake in identifying buildings, worth stating plainly since it
propagated through an entire round of math before being caught: **the
building named "Building 2x1 (1M)" (`f_building2x1d`, 100% intrinsic boost)
is a 2-tile building** (`v_base2x1d`'s `tile_size = {1, 2}`), not a 1-tile
building — it was mislabeled as "1x1" for a few iterations by conflating it
with the *separate*, unrelated 1-tile `f_building1x1a` ("Building 1x1 (1M)",
0% boost) and `f_building1x1h` ("Defense Block", 50% boost, also 1 tile).
Always check `tile_size` in the frame's `visual` entry directly — the name
suffix ("1x1"/"2x1"/"2x2"/"3x2") is normally reliable but a frame's *actual*
footprint is only confirmed by its visual def.

Per-tile throughput (`output × (cellsize - footprint) / (200 × cellsize)`,
where `cellsize = (w+4)(h+4)` is the gapless-tiling cell for Chebyshev range 2
— see "Range is Chebyshev distance" below) for the best-total-output
configuration of each real building layout:

| Building | Footprint | Best-total output | Throughput/total-land |
|---|---|---|---|
| **3x2 (1L3M) — `f_building3x2a`** | 6 (3×2) | 12.90 (3 mag + 1 Large OC) | **0.0553** |
| 2x2 (2M1L) [C/D] — `f_building2x2c` | 4 | 7.20 (2 mag + 1 Large OC) | 0.032 |
| 2x2 (2M1L) [A] | 4 | 6.80 | 0.0302 |
| 2x2 (3M) — `f_building2x2b` | 4 | 6.30 (3 mag) | 0.028 |
| 3x2 (2M2S) | 6 | 5.20 (2 mag) | 0.0223 |
| 2x2 (1M3S) | 4 | 3.60 (1 mag, forced) | 0.016 |
| 2x1 (2M) — `f_building2x1c` | 2 | 4.00 (2 mag) | 0.0187 |
| 2x1 (1M1L) | 2 | 3.30 (2 mag, best split) | 0.0154 |
| 2x1 (2S1M) | 2 | 2.90 (1 mag, forced) | 0.0135 |
| 2x1 (1M) — `f_building2x1d` | 2 | 2.40 (1 mag, forced) | 0.0112 |
| 1x1 (1L) — `f_building1x1b` | 1 | 1.90 (1 mag, personal oversocket) | 0.0091 |
| Defense Block — `f_building1x1h` | 1 | 1.70 | 0.0082 |
| 1x1 (1M) — `f_building1x1a` | 1 | 1.40 | 0.0067 |

The small 1-tile buildings are the *worst* choice by true land-throughput,
despite having the best coverage-area-to-footprint ratio — their magnifier
density is too thin to make up for it. **`f_building3x2a` is the best
building for this purpose, full stop** — both for raw total output and for
throughput per unit of land, because its 100% intrinsic boost and 4 Internal
sockets more than compensate for its worse area-to-footprint ratio.

### Range is Chebyshev distance, confirmed in-game

User-confirmed: Magnifier `range = 2` means a square region extending 2
tiles in *every* direction from the building's footprint (a 5×5 square
centered on a 1×1 building) — Chebyshev/king-move distance, not Euclidean. A
useful consequence: Chebyshev-range squares tile the plane with **zero gaps
and zero overlap** when buildings are spaced exactly `(footprint + 2×range)`
apart on a grid, unlike circular (Euclidean) coverage, which would need
either gaps or overlap. For `f_building3x2a` (3×2 footprint), that's a 7×6
tiling cell — 6 tiles for the building, 36 for resource nodes, fully
covered, no waste.

### TICKS_PER_SECOND = 5

User-confirmed as a stable engine constant, unlikely to ever change (many
things would break). Not found in Lua source (native constant, same category
as `REG_INFINITE`). Cancels out of any ratio comparing two tick-based rates
(e.g. magnifier regen supply vs. mining demand), so it mattered less than
initially assumed for the throughput math above — it matters for converting
to real seconds, not for the relative comparisons.

## Part 2: Miner-drone behavior design

### Native mechanics confirmed this session (source-cited, several corrected mid-session)

- **Mining recipe rates** (`data/items.lua:661-673`, `blight_crystal`):
  `c_miner` = 50 ticks/unit, `c_adv_miner` = 25 ticks/unit (Advanced Miner
  Drone is 2x faster) — always prefer the Advanced Miner Drone. Stack size
  20.
- **A resource node mined to exactly 0 can never be revived.**
  `AddResourceHarvestItemAmount` (`utilities.lua:575-582`, its own comment:
  `-- make sure result is > 0!!`) guards on `num > 0` before adding anything
  — once a node's remaining register hits 0, the Magnifier's regen call
  silently no-ops forever. This is why a "never mine below a floor" behavior
  isn't just an optimization, it's what keeps the node alive at all.
- **`c_behavior` (Behavior Controller) is an ordinary Internal-sized
  component** (`components.lua:3883-3889`, *"Additional small, low-powered
  programmable device. Can be added to units and buildings without an
  integrated behavior controller"*), not something exclusive to "robot" race
  frames with an intrinsic slot. Any frame with a free Internal socket — the
  Miner Drone and Advanced Miner Drone both have 2 (`visuals.lua:557-577`,
  their `c_miner`/`c_adv_miner` is marked `"hidden"` and doesn't consume a
  socket) — gets the full visual Program editor by socketing one in.
- **`drone_range` only gates the native, automatic port-side job-dispatch
  system, not a Program-controlled unit.** `c_miner:on_update`'s own
  auto-target search (`components.lua:2351`) uses
  `owner.has_movement and owner.visibility_range or miner_range` —
  `drone_range` never appears in it at all. A drone with its own Behavior
  Controller isn't leashed to its port's range; it's bounded by whatever its
  own Program does.
- **The store register auto-delivers cargo with no range limit at all**, and
  — the refinement added late in this session — **it automatically resumes
  the previous mining target once storage completes, and kicks in whenever
  nothing else is actively controlling the unit**, including with *no*
  Program installed at all (confirmed: manually setting the mine-target and
  store-target registers via the UI, unconnected to any logistics network,
  is sufficient for a perpetual mine → go-store-when-full →
  auto-resume-same-target cycle with zero scripting). This meant an earlier
  draft of the mining sub-loop (which re-invoked the `mine` instruction every
  recheck cycle) was doing unnecessary work — `mine` only needs to be called
  once, to establish the target; after that the native cycle runs itself,
  and the Program's only remaining job is periodically checking whether the
  live remaining amount has crossed the 100-unit floor, at which point it
  should switch targets.
- **Drone-holding components (`c_drone_port`, `c_drone_comp`, etc.) can be
  nested inside other moving units** — user-confirmed working in-game,
  correcting an earlier guess (based on there being no Lua-visible precedent
  for a mobile anchor point) that this might not function correctly.
- **The Goto frame register (`@goto`, `FRAMEREG_GOTO`) is a sibling
  mechanism to the store register above — persistent, native, no `domove`
  call needed.** User-confirmed (2026-07-10, reviewing two real deployed
  behaviors — "Mining Leader V3.2" and its follower "Miner V1.3.4," both
  drive `@goto` directly rather than calling `domove`): writing an
  entity-or-coordinate-plus-`num` value straight to `@goto` sets a
  *persistent* move-to intent the native per-tick unit AI keeps re-pursuing
  on its own — including continuing to track a moving target — until
  something else overrides it (an explicit `domove` call, or a controlling
  component like the miner). `num` is the arrival tolerance, exactly
  matching `domove`'s own "Target" argument semantics (`instructions.lua`'s
  own arg description: "the number specifies the range in which to be
  in") — confirmed these are conceptually the same *value* even though
  they're mechanically separate: `domove`'s own `func`
  (`instructions.lua:5111-5135`) calls native `ent:MoveTo`/
  `comp:RequestStateMove` directly with the target and range, and does
  **not** touch `FRAMEREG_GOTO` at all — writing the register directly is a
  genuinely different, parallel mechanism, not a documented alias for
  calling `domove`. User also noted `@goto` has additional semantics when
  the "transport route" option is enabled — not yet investigated, flagged
  for later if it becomes relevant.
- **Drones can be produced by a plain Robotics Factory**, not only by
  drone-port-family components — `c_robotics_factory = 100` is already
  listed as an equally-valid crafting station in both `f_drone_miner_a`'s and
  `f_drone_adv_miner`'s `production_recipe` (`frames.lua:1883`, `1903`),
  alongside `c_drone_port`/`c_drone_comp`/`c_drone_launcher`. Nothing about
  the drone-mining design requires building anything port-shaped at all.
- **A resource node's own registers cannot be written to from a Program.**
  The only remote-write instruction, `set_reg_remotely`
  (`instructions.lua:6849`), gates through `GetAdjacentFactionEntityOrSelf`
  (`instructions.lua:302-316`), which requires the target to be same-faction
  (a neutral resource node never qualifies) *and* physically touching
  (unless the caller is specifically an AutoBase controller, which gets a
  same-logistics-network exception instead). This ruled out an earlier idea
  of marking a node "claimed" by writing directly to it — that capability
  only exists in the engine's own native Lua (e.g. the Magnifier's
  `entity:SetRegisterNum(...)` calls), not in the player-facing instruction
  set. Reading an arbitrary entity's data (e.g. `Get Resource Num`) has no
  such restriction — only *writing* to something you don't own is gated.
  Writing to your *own* other components (`set_comp_reg`, "Set to
  Component") is unrestricted, since it never takes a target-entity argument
  at all — it only ever resolves against `comp.owner`.
- **`FRAMEREG_SIGNAL` + `faction:GetEntitiesWithRegister` is a real,
  purpose-built, faction-wide (no range limit at all) coordination
  mechanism**, exposed via the `Loop Signal` instruction
  (`for_signal_match`, `instructions.lua:2417-2508`) — exactly the
  "broadcast which node I'm working on, let others check for oversubscription"
  mechanism this design needed, once the direct-node-write idea above was
  ruled out. A drone writes its own Signal register to `{entity =
  target_node}` (a write to itself, always legal); any other drone runs
  `Loop Signal` with that same entity as the query and gets every faction
  unit (anywhere on the map) currently signaling it, with a simple iteration
  count deciding "already oversubscribed."
- **`mine` does not itself block the calling behavior.** Its `func`
  (`instructions.lua:5547-5651`) falls through without `SetStateSleep`/
  `return true` on the happy path; movement/mining progress is driven
  entirely by `c_miner`'s own separate on_update cycle. What *does* throttle
  execution is the per-tick dispatcher itself
  (`c_behavior:on_update`, `components.lua:4027-4090`): a "locked" behavior
  (`state.limit or 1`) runs exactly one instruction per tick regardless,
  which naturally paces a `mine → check → loop` cycle correctly. An
  "Unlocked" behavior has no such throttle — the same loop would spin
  uselessly fast, seeing an unchanged value every iteration (mining doesn't
  advance within the instruction dispatch itself), and would hit
  `"Unlocked behavior exceeded instruction limit for a single step"`. An
  explicit `wait` between establishing the mine target and rechecking it is
  correct insurance regardless of lock state, not just an unlocked-mode fix.
- **`mine`'s real value over driving the miner's register directly**: it
  bundles four decisions as explicit branches your Program can react to
  (path blocked → `Cannot Mine`; unpowered → `Cannot Mine`; already carrying
  the requested amount → `Full`; no cargo space → `Full`) that a raw
  register write (via a Link Editor wire or `set_comp_reg`) does not surface
  to your own instruction flow — the underlying component still behaves
  sensibly either way, but only `mine` tells *you* about it. It also applies
  to every `c_miner` component on the entity at once and avoids redundant
  register writes via its own before/after comparison.
- **`mine`'s `Num` argument is checked against total current inventory
  (`owner:CountItem`), not "amount extracted from a specific target"**
  (`instructions.lua:5601-5610`). This makes it a poor fit for enforcing a
  per-node floor: the store-register auto-deliver cycle above resets
  `CountItem` every time cargo is delivered, so a `Num` threshold sized to
  "stop once this node hits the floor" can fire early (leftover cargo of the
  same item from elsewhere already counts toward it) or effectively never
  fire from a single node's depletion (a mid-mining delivery resets the
  counter before the threshold is reached). Considered and rejected as the
  stopping mechanism for the floor design below — see the register-link
  bullet immediately after this one.
- **Components explicitly defer to a register link rather than fighting
  it.** The guard `if not comp:RegisterIsLink(1) then ... end` (or
  equivalent) recurs roughly 15 times across `components.lua`, always
  gating a component's own convenience writes/clears to register 1 — e.g.
  `c_miner`'s own entity-to-id conversion (`components.lua:2432`, `:2442`).
  When the register is link-driven, the component either leaves it alone
  entirely or, in a couple of cases (`components.lua:9323`), flags a
  register error instead of clearing it itself. Practically: wiring a
  behavior's declared output parameter directly to a component's register
  via the Link Editor (one-to-many — a single linked parameter can drive
  every `c_miner`/`c_adv_miner` on an entity at once, confirmed working by
  the user from prior hands-on use) gives a Program more reliable control
  over register 1 than going through `mine`. Writing to the link is
  indistinguishable, from `c_miner`'s side, from a player manually editing
  the register; clearing it (writing `nil`) hits the same plain `if not
  reg1_num then ... return comp:SetStateSleep() end` shutdown path
  (`components.lua:2259-2263`) as any other empty-register case — with none
  of `mine`'s `Num`/`CountItem` coupling above, and none of its per-call
  entity-equality dedup-on-write behavior (`instructions.lua:5615-5635`,
  which silently drops a `Num` change on a call that keeps the same target
  entity/id — a real trap for a "detect the stop, bump the limit, keep
  going" design built directly on top of `mine`).
- **"Loop Nearby Resources" (`for_count_resources`) aggregates by resource
  *type*** (total amount summed across all matching nodes in range), **not
  per individual node** — the wrong instruction for candidate-by-candidate
  scanning, a mistake made mid-session while first describing this design in
  prose and only caught once actually building the graph (see below). The
  correct per-entity iterator is **"Loop Units (Range)"**
  (`for_entities_in_range`, `instructions.lua:869-897`) with
  `Filter=v_resource`.

### The MinerDrone behavior (real BSF, compiled and validated)

**Rewritten 2026-07-11** in `behavior_source_format.md`'s real, current
grammar (the earlier pseudocode below predated the actual `desynced_toolkit
.bsf` parser/compiler) and, unlike the original draft, genuinely **compiled
and round-tripped through the real toolkit**: `bsf compile` → real `.dcs` →
`bsf decompile` byte-identical, confirmed against raw wire data (not just
the decompiler's own rendering), and the mermaid render collapses to a
single connected component from Program Start — a real structural sanity
check, not just "it didn't crash." Saved as `miner_drone.dcs` (workspace
root) — not yet tested in-game.

This revision also adds the second parameter (`Resource` — which item type
to mine, doubling as the signal id to watch for building demand, same
single-parameter convention `Fendersons Transport`'s Hauler already
established for its own `Resource` param) and the outer building-seek loop,
closing two of the "Known gaps" the original draft left open.

Three real bugs were caught and fixed authoring this version, all worth
recording since they're easy to reintroduce by hand:

1. **A genuine deadlock in the (separately-authored) `MagnifierSignal`
   companion behavior, caught by the user**: an earlier draft used a single
   200-cap threshold to drive *both* the power-management decision (should
   the magnifier keep regenerating) *and* the drone-invitation signal
   (should drones come mine here). An abundant, never-mined area (every
   node already above 200) would conclude "nothing needs regen" and clear
   its own signal *and* shut down — permanently starving itself of drones,
   since nothing would ever flip that condition back. Fixed by tracking two
   independent flags per poll cycle (`$NeedsRegen` against the 200 cap,
   `$Mineable` against the 100 floor) and gating power and signal off each
   independently — see `MagnifierSignal` below.
2. **Omitting a loop instruction's own `Done` pin does not "skip past the
   loop body"** — confirmed directly against a minimal compiled test case
   (not just documentation): an omitted `Done` resolves to the wire
   position immediately following *the loop instruction itself* (its own
   body's first instruction), per the same universal omission-is-positional
   convention documented in `behavior_format.md`'s "Branch and fall-through
   resolution" — there is no loop-aware special case. All three
   `for_signal_match`/`for_entities_in_range` loops in the first draft of
   this behavior (and the one in `MagnifierSignal`) omitted `Done` assuming
   it would naturally fall through to after the loop; all four needed an
   explicit numeric target instead. This is exactly why the mermaid render
   initially split into 4 (`MinerDrone`)/2 (`MagnifierSignal`) disconnected
   components — forward-reachability from Program Start genuinely couldn't
   reach the rest of the graph through a `Done` pin pointing back into its
   own loop body — and collapsing back to one component after the fix is
   the concrete confirmation the fix was real, not cosmetic.
3. **A real signal-protocol collision with `Mining Leader`/`Mining
   Follower`, caught by the user**: the first draft had `MinerDrone`'s Seek
   loop search for `{id: Resource, num: 0}` (matching `MagnifierSignal`'s
   own broadcast), using `for_signal_match`'s default "Match" filter mode —
   which only checks `id`, never `num` at all. But `Mining Leader`'s own
   `Monitor mine` state (`set_reg(Value=Resource, Target=@signal)`) and the
   Hauler-facing pickup convention `Fendersons Transport` depends on
   *already* use `num=0` on this exact same `Resource` id to mean "I'm
   offering this for pickup" — a completely different, mobile-squad-facing
   meaning. A drone would have genuinely traveled toward a roaming mining
   gang mid-pickup-broadcast, mistaking it for a stationary mining site.
   Fixed by reserving `num=-1` exclusively for the drone-facing "come mine
   here" signal (never used by the Hauler-facing `num=0`/`num>0`
   pickup/dropoff convention) and using `for_signal_match`'s "Exact" filter
   mode (`c=2`) to match it precisely — confirmed in the compiled wire data
   (`"c": 2`), not just the source text.
4. **A silent arg-clobber caught by this project's own round-trip
   discipline**: `is_same_grid` (added for the grid constraint below)
   genuinely declares two args both literally named "Unit" in the game data.
   Writing `is_same_grid(Unit=$Self, Unit=$Cand)` in BSF text — repeating
   the bare name instead of using the occurrence-disambiguated `Unit2` — let
   the second assignment silently overwrite the first in `parse_node`'s args
   dict. It compiled and round-tripped with *no error at all*; the decoded
   wire showed `$Cand` in position 1 and **nothing** in position 2 — `$Self`
   silently discarded. Since `is_same_grid` treats an empty second unit as
   "no match," this would have rejected every candidate, always, with a
   clean compile. Caught because the *decompiled* text visibly had one arg
   instead of two, prompting a raw wire-data check — see
   `reference_bsf_duplicate_arg_name_silent_clobber` (project memory) for
   the general pattern. Fixed by using `Unit2` for the second occurrence,
   matching the same disambiguation convention `for_entities_in_range`'s
   `Filter`/`Filter2`/`Filter3` already established.

**A hard constraint, not a preference, discovered discussing this with the
user**: drones have no capacitor and become extremely slow the moment they
leave their power grid's coverage — so a drone must *never* travel to a
target outside its own grid, not just prefer to stay within it. This
applies to both candidate searches: a `MagnifierSignal` building found via
Seek, and — less obviously, but still a real risk given `Range=5` — a
resource node found via the local Mine search, if the node happens to sit
just past the grid's edge. `is_same_grid(Unit, Unit2)` (checks
`power_grid_index` on both entities, falling back to coordinate-based grid
lookup for non-grid-connected entities — which is *why* it also happens to
reject Mining Leader/Follower on its own, since a roaming bot has no
`power_grid_index` at all) gates both.

```
behavior MinerDrone(Resource, MineTarget*):
  desc: "Find a building broadcasting demand for Resource via the drone-only signal (id=Resource, num=-1 -- deliberately distinct from the Hauler-facing num=0/num>0 pickup/dropoff convention Mining Leader/Follower and Fendersons Transport already use on this same Resource id, so a roaming mining squad offering pickup is never mistaken for a stationary mining site), travel there, then reservoir-sample a nearby resource node of that type above the 100-unit floor (skipping oversubscribed nodes via Signal broadcast), mine it down to the floor by driving the register-linked MineTarget parameter directly (link MineTarget to register 1 of every c_miner/c_adv_miner on this drone via the Link Editor -- no mine() call), then repeat. Both candidate searches reject anything outside this drone's own power grid -- drones have no capacitor and become extremely slow off-grid, so leaving grid coverage is never acceptable, not just suboptimal. Falls back to re-picking a building whenever no valid local candidate is found."

n1: label(Label=v_arrow_right, cmt="Seek: find a building signaling demand for Resource")
n2: set_reg(Value=0, Target=$BldRoll)
n3: set_reg(Target=$Bldg)
n4: get_self(Unit Reference=$Self)
n5: set_number(Value=Resource, Number=-1, Result=$SeekSig, cmt="Drone-only signal value -- num=-1 never collides with the Hauler-facing num=0 (pickup)/num>0 (dropoff) convention")
n6: for_signal_match(Signal=$SeekSig, Unit=$Cand, c=2)  >n12 (Done)
n7: is_same_grid(Unit=$Self, Unit2=$Cand)  >POP (Different)
n8: random_number(Min=1, Max=1000, Result=$Roll)
n9: check_number(Value=$Roll, Compare=$BldRoll)  >POP (If Smaller) >POP (If Equal)
n10: set_reg(Value=$Roll, Target=$BldRoll)
n11: set_reg(Value=$Cand, Target=$Bldg)  >POP (next)
n12: is_empty(Value=$Bldg)  >n14 (Has Value)
n13: wait(Time=20)  >n1 (next)
n14: set_number(Value=$Bldg, Number=4, Result=@goto)
n15: wait(Time=5)
n16: get_distance(Target=$Bldg, Distance=$Dst)
n17: check_number(Value=$Dst, Compare=8)  >n15 (If Larger)
n18: label(Label=c_radar, cmt="Mine: reservoir-sample a nearby node of the right type")
n19: set_reg(Value=0, Target=$BestRoll)
n20: set_reg(Target=$Best)
n21: for_entities_in_range(Range=5, Filter=v_resource, Filter2=Resource, Unit=$Node)  >n33 (Done)
n22: is_same_grid(Unit=$Self, Unit2=$Node)  >POP (Different)
n23: get_resource_num(Resource=$Node, Result=$Amt)
n24: check_number(Value=$Amt, Compare=100)  >POP (If Smaller) >POP (If Equal)
n25: set_reg(Value=0, Target=$Count)
n26: for_signal_match(Signal=$Node, Unit=$SigUnit)  >n28 (Done)
n27: add(To=$Count, Num=1, Result=$Count)  >POP (next)
n28: check_number(Value=$Count, Compare=2)  >POP (If Larger)
n29: random_number(Min=1, Max=1000, Result=$Roll)
n30: check_number(Value=$Roll, Compare=$BestRoll)  >POP (If Smaller) >POP (If Equal)
n31: set_reg(Value=$Node, Target=$Best)
n32: set_reg(Value=$Roll, Target=$BestRoll)  >POP (next)
n33: is_empty(Value=$Best)  >n35 (Has Value)
n34: jump(Label=v_arrow_right)  >POP (next) >n1 (jump→label)
n35: set_reg(Value=$Best, Target=@signal)
n36: set_reg(Value=$Best, Target=MineTarget)
n37: wait(Time=5)
n38: get_resource_num(Resource=$Best, Result=$Amt2)
n39: check_number(Value=$Amt2, Compare=100)  >n37 (If Larger)
n40: set_reg(Target=MineTarget)
n41: set_reg(Target=@signal)
n42: jump(Label=c_radar)  >POP (next) >n18 (jump→label)
```

Notes on the design:
- **`n4`**: `$Self` computed once at Program Start (not re-fetched per
  candidate) and reused by both grid checks below.
- **`n1`-`n17` ("Seek")**: reservoir-samples among faction entities
  broadcasting `{id: Resource, num: -1}` (a `MagnifierSignal` building
  signaling demand — see below; the reserved `num=-1` and "Exact" filter
  mode are the fix for bug 3 above), rejecting any candidate not on the
  drone's own power grid (`n7`, bug 4's fix — the actual grid-safety
  constraint) before even rolling the reservoir sample. Waits 20 ticks and
  retries if none found, otherwise travels there (`@goto`, arrival
  tolerance 4) and waits until within distance 8 before proceeding — a
  generous tolerance since the target is a building, not a point, and
  footprint size varies.
- **`n18`-`n32` ("Mine")**: the original reservoir-sampling/oversubscription
  logic, with two additions — `Filter2=Resource` on the
  `for_entities_in_range` call, filtering to nodes of the specific
  requested item type (the same confirmed-working two-filter AND mechanism
  `Mining Leader`'s `Check Emergency` sub already uses with
  `v_own_faction`+`v_damaged` — **not independently confirmed** whether a
  resource node's yielded item type is itself a valid filter value this way,
  worth checking in-game before trusting it in a mixed-resource-type area)
  — and the same `is_same_grid` rejection (`n22`) applied to resource-node
  candidates, since even a local `Range=5` search could turn up something
  just past the grid's edge. (This loop's own `@signal=$Node`/`Loop Signal`
  oversubscription channel is entity-based, not id-based, so it was never
  at risk of the same num=0 collision bug 3 describes — only the
  building-seeking channel was.)
- **`n33`-`n34`**: no candidate found locally → back to **Seek** (`n1`), not
  a local wait-and-retry — the actual outer-loop integration the original
  draft's "Known gaps" flagged as not yet built.
- **`n35`-`n41`**: unchanged in intent from the original draft — broadcast
  the claim, drive `MineTarget` directly (no `mine()` call), poll down to
  the floor, then clear the link (genuinely halting the native auto-resume
  cycle, not just abandoning it — see the original revision note below for
  why this matters) and the signal claim.
- **`n42`**: on finishing one node, loop back to **Mine** (`n18`) to try
  another node in the same area *first*, only escalating to **Seek** if
  `n33` finds nothing at all — avoids re-picking a building every time a
  single node depletes.

**Revision note (2026-07-10, preserved from the original draft):** an
earlier version called the `mine` instruction once to establish the target
and relied entirely on the confirmed native auto-store/auto-resume cycle
from there. Indexing `data/` into a code knowledge graph and tracing
`c_miner:on_update`'s actual stop conditions (`components.lua:2254-2536`)
found a real bug: none of its four real stop conditions (register 1
cleared, requested amount reached, inventory full, node destroyed) cover
"the Program decided to abandon this node" — clearing only the Signal
broadcast left the native auto-resume cycle mining the abandoned node,
unsupervised, straight through the 100-unit floor and potentially to
permanent depletion (`AddResourceHarvestItemAmount`'s `num > 0` guard,
cited above). A `mine(Resource=nil)`-style explicit clear was investigated
and rejected: `mine`'s only real "stop" path requires the raw compiled
argument to be entirely *absent*, not confirmed producible from an
unconnected pin in the visual editor; a `mine`-`Num`-threshold alternative
was also considered and rejected (see the `Num`/`CountItem` bullet in
"Native mechanics confirmed" above). The fix: drive `c_miner`'s register 1
through a genuine register link (`MineTarget`, wired via the Link Editor
directly to register 1 of every `c_miner`/`c_adv_miner` on the drone)
rather than through `mine` at all — a technique the user confirmed using
successfully before that session.

### The MagnifierSignal behavior (real BSF, compiled and validated)

Building-side companion to `MinerDrone`, closing the "author the
`MagnifierSignal` building behavior" gap. Compiled, round-tripped, and
collapses to a single mermaid component the same way `MinerDrone` does.
Saved as `magnifier_signal.dcs` (workspace root) — not yet tested in-game.

```
behavior MagnifierSignal(Resource):
  desc: "Periodically check Resource nodes within range, tracking two INDEPENDENT conditions per node -- needs regen (below the 200 cap) and worth mining (above the 100 floor). Power (shutdown/turnon) follows the regen condition only; the drone-invitation signal (id=Resource, num=0) follows the mining condition only. Keeping these separate avoids a deadlock: an abundant, never-mined area (all nodes already above 200) still needs to invite drones even though it needs no regen at all."

n1: label(Label=v_arrow_right, cmt="Poll nearby Resource nodes; manage power (regen cap) and drone invitation (mining floor) independently")
n2: wait(Time=20)
n3: set_reg(Value=0, Target=$NeedsRegen)
n4: set_reg(Value=0, Target=$Mineable)
n5: for_entities_in_range(Range=2, Filter=v_resource, Filter2=Resource, Unit=$Node)  >n11 (Done)
n6: get_resource_num(Resource=$Node, Result=$Amt)
n7: check_number(Value=$Amt, Compare=200)  >n9 (If Larger) >n9 (If Equal)
n8: set_reg(Value=1, Target=$NeedsRegen)
n9: check_number(Value=$Amt, Compare=100)  >POP (If Smaller) >POP (If Equal)
n10: set_reg(Value=1, Target=$Mineable)  >POP (next)
n11: check_number(Value=$NeedsRegen, Compare=0)  >n13 (If Larger)
n12: shutdown()  >n14 (next)
n13: turnon()
n14: check_number(Value=$Mineable, Compare=0)  >n16 (If Larger)
n15: set_reg(Target=@signal, cmt="Nothing worth mining -- stop broadcasting")  >n18 (next)
n16: set_number(Value=Resource, Number=0, Result=$Sig)
n17: set_reg(Value=$Sig, Target=@signal, cmt="Broadcast: come mine Resource here")
n18: jump(Label=v_arrow_right)  >POP (next) >n1 (jump→label)
```

Notes on the design:
- **`n6`-`n10`**: for every node in range (`Range=2`, matching the
  Magnifier's own Chebyshev range — not independently confirmed that
  `for_entities_in_range`'s range calculation treats a multi-tile
  building's footprint the same way the Magnifier's own native range check
  does), independently mark `$NeedsRegen` (any node `<200`) and `$Mineable`
  (any node `>100`) — both can be true for the same node simultaneously
  (e.g. a node at 150 both still benefits from regen *and* has material
  worth mining right now), which is the point: they're unrelated questions.
- **`n11`-`n13`**: power management, gated on `$NeedsRegen` only.
- **`n14`-`n17`**: drone invitation, gated on `$Mineable` only, entirely
  independent of whichever way the power decision went.

### Known gaps / not yet done

- **Not tested in-game.** Both behaviors compile, round-trip byte-identical
  through the real toolkit, and collapse to a single connected mermaid
  component — a real structural validation, not just "didn't crash" — but
  neither has been loaded and run in the actual client yet.
- **The `Filter2=<item id>` resource-node type filter** (both behaviors) —
  the two-filter-AND mechanism itself is confirmed working elsewhere
  (`Mining Leader`'s `Check Emergency` sub), but whether a resource node's
  own yielded item type is a valid filter value this way specifically is
  not independently confirmed.
- **The oversubscription cap (2) and floor (100) in `MinerDrone`, and the
  100/200 thresholds in `MagnifierSignal`, are all hardcoded design
  choices**, not derived constants — reasonable starting points, worth
  tuning empirically once these run for real.
- **`MinerDrone`'s outer building-seek loop doesn't account for
  building-level oversubscription** — multiple drones could pick the same
  building simultaneously; nothing analogous to the per-node `Loop Signal`
  claim-counting exists at the building level. Not built yet.
- **`is_same_grid`'s coordinate-based fallback depends on the *calling*
  drone's own position, not just the candidate's.** Confirmed from source
  (`instructions.lua:4192-4211`): when either side isn't itself a
  grid-connected entity, it falls back to comparing `GetPowerGridIndexAt`
  for both positions. A drone that's currently *not* standing within any
  grid's coverage (plausible mid-search, though the whole design intent is
  to never actually leave grid) could see this check spuriously fail even
  against a legitimate in-grid candidate. Not yet a problem in practice
  (the drone should always be within its own grid when this check runs,
  by construction) but worth keeping in mind if this ever needs debugging.

## What this exercise demonstrated about the toolset itself

This was a deliberate test (the user's explicit framing) of whether Claude
Code can author — not just decompile — a real behavior directly in
`behavior_source_format.md`'s grammar from a natural-language design
discussion, using only `instructions_index.md` + the format spec + targeted
source reads, no existing `.dcs` file as a starting point.

- **Where it worked well**: every instruction name, pin, and semantic
  gotcha needed (the equality-fallthrough idiom, `for_signal_match`'s
  entity-vs-id matching, the loop-dead-end-pops-the-stack rule) came from
  material already read this session or grep'd in seconds — assembling a
  21-instruction graph took no new deep-dive beyond double-checking two
  argument names.
- **Where it caught a real mistake**: writing the actual graph (not just
  describing the plan in prose) is what surfaced the "Loop Nearby Resources"
  vs. "Loop Units (Range)" mixup — a wrong instruction reference that had
  gone unnoticed through several turns of prose description. Concreteness
  forces errors out; a prose plan can hide a wrong instruction reference
  indefinitely.
- **Where it's still fragile**: instruction-index bookkeeping (tracking
  which edges are implicit-adjacent-fallthrough vs. need an explicit
  branch note) was done entirely by hand here. Manageable at 21
  instructions, would get error-prone well before real corpus behaviors'
  typical size — exactly why `behavior_source_format.md` flags the
  parse-back direction as the next real piece of infrastructure needed, not
  a nice-to-have.
- **Reinforces [[feedback_verify_engine_semantics_ingame]] repeatedly, in
  both directions**: several corrections this session came from the user's
  own in-game/gameplay knowledge overriding what static Lua reading alone
  suggested (store-register auto-resume, drone-port nesting working,
  Program-driven units not being bound by `drone_range`) — but at least one
  correction went the other way, with a specific source-code check (`mine`'s
  actual `func`, the dispatcher's `step_limit`) resolving a question neither
  party could have answered from gameplay intuition alone. Both directions
  matter; neither in-game experience nor source-reading alone is
  sufficient on its own.
