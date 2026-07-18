# Mock World for Behavior Testing — Design Spec

**Status:** Phase 0 done (Data registries load under the stub); Phases 1–4 not started. Work state
lives in `todo.md` (§ `desynced_toolkit` / BSF infrastructure), not here.

## Goal

Extend `desynced_toolkit`'s `Interpreter` so a behavior can be run against a **mock world**: a
populated, steppable environment with mock entities the behavior can sense, command, and be
affected by. Enough fidelity to write **automated tests for multi-unit behaviors** — the immediate
target is the combat squad (`combat_squad_spec.md`): a Captain, its gunners, and a hostile, stepped
forward tick by tick, asserting the coordination logic (membership scan, RALLY assembly gate,
PATROL heal-gate, command broadcast, gunner focus-fire dispatch) behaves as designed.

This is **not** a reimplementation of the game world. It is the smallest mock that lets the *real*
instruction funcs run without erroring on a missing entity graph. The scope for the first usable
version is **sensing + movement**, not combat/damage resolution (see "Phasing").

## Governing principle (why this is even tractable)

The `Interpreter` already never reimplements an instruction. Its per-op dispatch in `_step()` is
pure arg-marshalling — resolve each argument to a `state.mem[]` slot or frame-register address, then
call the genuine `data.instructions[op].func(comp, state, cause, ...)`. Control flow (branches,
block stack) is driven in Python; *decisions* (`check_number`, `jump`, `for_number`'s advance) are
delegated back to the real funcs.

So the reason world instructions don't run today is **not** a control-flow gap. It is that their
func bodies call engine-native primitives (`Map.FindClosestEntity`, `comp.faction:IsSeen`,
`comp:RequestStateMove`, …) and traverse an entity graph that `engine_stub.lua` doesn't provide.
The entire task is: **supply those primitives and that graph, backed by real game data, and let the
unchanged instruction funcs run.** Same doctrine as the rest of the project (CLAUDE.md's "reuse the
real Lua, both data and logic") — we mock only the genuinely-external leaves, never a decision the
game already makes.

## What is reusable game Lua vs. what must be mocked

Established by tracing the func bodies of the squad's instructions (`get_closest_entity`,
`for_entities_in_range`, `for_signal_match`, `read_signal`, `get_distance`, `get_health`, `match`,
`domove`, `set_comp_reg`, `get_location`) in `data/instructions.lua`, and `FilterEntity`/
`PrepareFilterEntity` in `data/utilities.lua`.

### Reused unchanged (the point — do not touch)

- **Every instruction `func` body.**
- The argument getters `Get`/`GetNum`/`GetId`/`GetEntity`/`GetCoord` — all local aliases for the
  `InstGet*` functions defined in `instructions.lua` itself (the same reuse `engine_stub.lua`
  already documents for `Get`/`GetNum`). `GetId`/`GetEntity`/`GetCoord` are simply not exposed as
  globals to the harness yet.
- **`FilterEntity` / `PrepareFilterEntity`** (`data/utilities.lua`) — the real radar/match/signal
  filtering logic, including the whole `FilterStringToNum` table (`v_enemy_faction`,
  `v_own_faction`, `v_damaged`, `v_infected`, `v_bot`, `v_building`, …). This is the largest reuse
  win: entity filtering stays real, so any test using a radar/`match`/`for_signal_match` filter
  exercises the exact game predicate.
- The entity/faction helpers already inside `instructions.lua`: `GetSeenEntityOrSelf`,
  `GetFactionEntityOrSelf`, `GetAdjacentFactionEntityOrSelf`.

### The mock surface (genuinely engine-native, C++ — small and countable)

| Kind | Primitives | Mock responsibility |
|---|---|---|
| **Map / global** | `Map.FindClosestEntity(owner, range, pred, filter)`, `Map.GetDistance(a,b)`, `Map.GetEntityAt(x,y)`, `Map.Defer(fn)` | spatial iteration + distance over the entity registry |
| **Entity fields** | `.location`, `.faction`, `.def`, `.visual_def`, `.health`/`.max_health`, `.visibility_range`, `.exists`, `.is_construction`, `.is_damaged`, `.powered_down`, `.state_custom_1`, … | plain fields on the mock entity table |
| **Entity methods** | `:GetRegister(n)`/`:SetRegister(n,v)` (already present on the stub's `Owner`), `:MatchFilter(mask, faction)`, `:MoveTo(target, range)`, `:IsTouching(comp)`, `:FindComponent(id)`, `:CountItem(id)`, `:GetLocationXY()`, `:LookAt(t)` | methods on the entity/component metatables |
| **Component methods** | `comp:RequestStateMove(target, range) -> need_move, repeat_blocked`, component-register `:GetRegister`/`:SetRegister`, `GetComponentFromIndex` | movement resolution + per-component register banks |
| **Faction methods** | `faction:IsSeen(e)`, `faction:IsVisible(e)`, `faction:GetPowerGridIndexAt(e)`, `faction:GetTrust(other)`, and `==` identity | vision / trust / power-grid model |
| **Constants** | `FRAMEREG_SIGNAL/VISUAL/STORE/GOTO`, the `FF_*` frametype flags | globals in the stub |

The two load-bearing primitives are **`Map.FindClosestEntity`** (all sensing routes through it —
`get_closest_entity`, `for_entities_in_range`) and **`comp:RequestStateMove`** (all movement). Get
those two faithful and most of the squad is testable.

Note `FilterEntity`, though reused, bottoms out in rich entity reads (`e.def.type`,
`e.faction.is_world_faction`, `e.visual_def.explorable_race`, `e:GetRegisterId(FRAMEREG_GOTO)`,
state flags). This is why a faithful mock entity must carry the **real** definition table as its
`.def` — see below.

## Architecture

**World state lives in Lua** (tables + metatables), **orchestrated from Python.** Rejected the
alternative (Python entity objects handed to Lua via lupa) because `FilterEntity` and the
instruction funcs do heavy Lua-side field access and pass `Value` objects around; a Python/Lua
object boundary at every `e.def`/`e.faction` access would be constant friction and a faithfulness
risk. Python owns *orchestration* (spawn, step, mutate between steps, assert); Lua owns *state*.

```
MockWorld (Python facade)                  world.lua (new Lua module, loaded after the Data package)
  .spawn(def_id, faction, x, y) ─────────► World.Spawn: builds an entity table whose .def IS the
  .attach_behavior(entity, dcs_or_bsf)     real data.frames[def_id] (components' .def from
  .step(n_ticks)                           data.components); Entity/Component/Faction metatables
  .query(...) / .entities                  provide the engine-native methods above.
  entity.get_register(...) etc.            Map.FindClosestEntity/GetDistance iterate World.registry.
```

The entity's `.def` being the real `data.frames[...]` / `data.components[...]` table is the crux:
`movement_speed`, default `visibility_range`, socket layout, per-component `register_count`, and
every filter-by-type decision then come from real data, not invented numbers.

### A world tick (`MockWorld.step`)

Ordered per step:

1. **Advance each behavior-carrying entity's `Interpreter` by one tick** — the existing
   `run_ticks(1)` already honors the real `lock`/`unlock`/`wait` per-tick budget model.
2. **Resolve movement.** For each entity with a pending `RequestStateMove` goal or a
   `FRAMEREG_GOTO` target, step it toward the goal. **Positions are integer tiles: to behaviors a
   unit is *always* at an exact integer coordinate and teleports tile-to-tile** — the smooth
   in-game motion is animation only (user-confirmed; see the `reference_tile_occupancy_model`
   memory). So the entity `.location` every instruction func reads must stay integer; the mock
   accumulates fractional sub-tile progress *internally* and advances the logical coordinate one
   whole tile at a time when that progress crosses a tile boundary — it never exposes a fraction.
   Per-tick progress is `effective_speed / TICKS_PER_SECOND` tiles: **`def.movement_speed` is
   tiles-per-*second* stored at face value** (confirmed against the stat-display code and user — the
   *opposite* of the per-tick power convention; see `reference_movement_speed_model`), so it divides
   by `TICKS_PER_SECOND` (=5) and is typically fractional (3/5 = 0.6 tile/tick → a unit sits on a
   tile for a couple ticks, then jumps one tile). **Measured in-game 2026-07-18** (an Engineer,
   base `movement_speed = 2`, driven around a closed waypoint circuit by a logging behavior that
   printed each location change with a game-tick stamp): the model holds end-to-end, and the
   sub-tile progress accumulates along the *geometric path* — every observed step was a single
   tile to one of the 8 neighbors (never a multi-tile jump, so the mock must step diagonally too,
   not axis-by-axis), orthogonal steps took alternating 2/3 ticks (mean 2.57 ≈ 1/(2/5) = 2.5)
   while diagonal steps took 3/4 ticks (mean 3.35 ≈ 2.5·√2) — i.e. **a diagonal step costs ≈√2
   tiles of progress** (√2 vs. exactly 1.4 is below this measurement's resolution). Over the whole
   circuit: 63.3 Euclidean tiles in 157 ticks → 2.02 tiles/s, reproducing the base speed within
   1%, where Manhattan (2.39) and Chebyshev (1.75) metrics are clearly wrong. The same log pins
   `TICKS_PER_SECOND` empirically: 157 ticks over 31.40 s of wall clock = 5.000 ticks/s.
   Effective speed = base `movement_speed` + speed
   modules + terrain (flying units ignore terrain; pavement adds a bonus; being unpowered subtracts
   a large penalty except on units with no base power draw). The first-version mock is flat and
   powered, so effective = base + modules; terrain/pavement and the unpowered penalty are later
   refinements (the unpowered penalty is what justifies the squad Power Provider, so it lands with
   combat). This discrete tile advance is what makes `need_move` eventually return `false`, so
   arrival-gated logic (the RALLY assembly gate, `domove`'s "wait then repeat" loop) becomes
   testable over ticks rather than resolving instantly.
3. **Drain `Map.Defer` callbacks.**
4. *(Deferred — combat phase, not in first version.)* Resolve weapon `on_update` / damage.

Each behavior-carrying entity gets its own `Interpreter` instance (its own `state`/`comp`/`Memory`)
but shares the one `LupaEngine` and the one Lua world registry, so their sensing/commands interact.

## Phasing (first usable version = Phases 0–3, sensing + movement)

**Phase 0 — spike: load the Data package under the stub. DONE (2026-07-18).** The minimal include
subset turned out to be exactly the expected `utilities → values → items → components → frames`
(confirmed empirically: the intervening real includes `library/actions/biomes/behaviors/puzzles`
are *not* needed at load). `Frame:RegisterFrame`/`Comp:RegisterComponent` and the recipe helpers
are all defined *inside* those files — no stubs needed for them; the only genuinely-missing
load-time surface was six engine constants/tables. `LupaEngine(load_data_registries=True)` (the
new default) loads that subset before `instructions.lua` and then builds `data.all` (merge of
values/items/components/frames, each def tagged `data_name`) exactly as the engine's post-load step
does. Populated: `data.frames` (177), `data.components` (310), `data.items` (96), `data.values`
(114), `data.all` (697); `FilterEntity`/`PrepareFilterEntity` live. Stubs added to
`engine_stub.lua`: the `FF_*` bit flags (layout self-consistent for PrepareFilterEntity↔the future
mock `MatchFilter`, deliberately *not* reverse-engineered to the engine's exact bits — FilterEntity
keys off its own `FilterStringToNum`, so only those two agree-with-each-other consumers exist),
`FRAMEREG_*`, `TICKS_PER_SECOND`, `blight_threshold` in `Map.GetSettings`, empty
`FactionAction`/`EntityAction`/`UIMsg`/`Delay` handler tables, a no-op `GetFactionBehaviorAsm`, and
an auto-vivifying `data` table. Cost ~29 ms per construction (once per session test fixture).
Covered by new `test_lua_runtime.py` tests; `load_data_registries=False` preserves the old
instructions-only runtime. The predicted long tail of load-time engine calls (see "risks" below)
did not materialize.

**Phase 1 — engine-native primitives in `world.lua`.** Implement the mock-surface table above as
Lua metatables over `World.registry`:
- `Map.FindClosestEntity` = iterate registry, distance-filter by `range`, run the caller's
  predicate (which calls the real `FilterEntity`), keep the closest — matching how the real funcs
  use it.
- `:MatchFilter` = the `FF_*` bitmask test against the prepared filter mask.
- `faction:IsSeen(e)` / `:IsVisible(e)` = start with a simple model (seen if within any
  own-faction entity's `visibility_range`); the squad's whole premise is the vision lock (§1.1 of
  the squad spec), so this must be honest but need not be pixel-accurate initially.
- Define `FRAMEREG_*` and `FF_*` globals — cross-check `FRAMEREG_*` values against
  `ui/RegisterSelection.lua` and `behavior_format.md`, and the `FF_*` flags against
  `data/utilities.lua`'s own definitions.

**Phase 2 — extend the interpreter op dispatch.** Add arg-marshalling arms for the world ops the
squad uses: `get_location`, `get_distance`, `get_health`, `get_closest_entity`, `read_signal`,
`set_comp_reg`/`get_comp_reg`, `value_type`, `modulo`, `check_bit`/`bitwise_op`, `match`, and the
`domove` family. Each arm is a few lines like the existing ones (resolve arg slots, call
`engine.call`). Fold in the block-producing world loops `for_entities_in_range`/`for_signal_match`
— these return `BeginBlock`, so they reuse the existing loop-block driver, the same tier as
`for_number`. **Side benefit:** this alone unblocks the `library/hexat.dcs` unit-Origin path, whose
`value_type`/`get_location`/`modulo` are exactly the currently-unhandled ops (see
`hex_expansion_math.md`, "Deployed copy").

**Phase 3 — movement + multi-entity stepping.** Implement `RequestStateMove`/`MoveTo`/`@goto`
resolution in the tick loop and `MockWorld.step(n)` driving all interpreters plus movement together.
First real test targets: a `for_signal_match` membership scan resolving a live roster, and a
`get_closest_entity`-driven RALLY broadcast. **Golden differential fixture (user-designated):**
the 2026-07-18 movement-measurement behavior and its real in-game debug log are checked in as
`tests/data/movement_circuit_test.dcs` / `movement_circuit_test_ingame.log` — the behavior walks
an Engineer around the six `HexAt` R=1 ring corners, printing each location change with a
Simulation Tick stamp. Phase 3's acceptance test: run the same `.dcs` in the mock (Engineer def,
origin `(-14, 51)`, start on the NW corner `(-19, 60)`) and diff the mock's print stream against
the real log — same tile sequence, same per-step tick deltas (modulo the poll-aliasing jitter of
±1 tick on individual steps; the closed-circuit total of 157 ticks should match near-exactly).
This exercises the whole stack at once: `domove`/arrival re-issue, the Euclidean sub-tile
accumulation, 8-connected stepping, `simulation_tick`, `value_type`/`get_location`/`modulo`
(the `HexAt` unit-Origin path `Interpreter` can't currently drive), `sequence` cascade polling,
and `wait`.

**Phase 4 (deferred, not first version) — combat fidelity.** Optionally run the real weapon
`c_turret:on_update` (`data/components.lua`) plus a minimal HP-decrement/damage model, so ENGAGE
focus-fire, the retreat latch, and victory detection are exercisable end to end. Deferred by
decision: the sensing/rally half is the larger correctness risk and needs no damage model.

## Target test shape

```python
w = MockWorld(engine)
cap = w.spawn("f_bot_1m_c", faction="player", x=0, y=0)
cap.visibility_range = 40
cap.attach_behavior("library/squad-captain.dcs", params={...})

g1 = w.spawn("f_bot_1m_b", faction="player", x=2, y=0)
g1.attach_behavior("library/squad-gunner.dcs", params={"Captain": cap})

enemy = w.spawn("f_bug_larva", faction="bugs", x=35, y=0)

w.step(20)
assert cap.get_register("SIGNAL").entity is enemy            # Captain broadcast ENGAGE
assert g1.weapon_component().get_register(1).entity is enemy # gunner focus-fired it
```

## Open items / risks

- ~~**Phase 0 feasibility is the primary risk.**~~ **Resolved (2026-07-18):** loading the minimal
  subset needed only six small constant/table stubs, no long tail. See the Phase 0 note above.
- **`faction:IsSeen`/`IsVisible` fidelity — the top vision risk, and it has a load-bearing
  *collective* question.** The squad design turns entirely on the vision lock, and specifically on
  vision being *shared across the faction*: the turret target gate is `owner_faction:IsVisible(e)`
  (a faction-level query — `c_turret` target selection, `components.lua`), so the whole Captain
  concept assumes an unarmed high-`visibility_range` Captain seeing an enemy lets a *different*
  gunner fire on it even when that gunner can't see the enemy itself. Confirm this **spotter case**
  in-game before investing in the mock (Captain in vision range of enemy + gunner out of its own
  vision → does the gunner fire? walk Captain away → does it stop?); it validates the architecture
  *and* tells the mock exactly what `IsVisible` should compute (union of members' vision bubbles,
  radius = `visibility_range` in tiles at face value). Too-simple a model could make a test pass for
  the wrong reason. Related but distinct: does `get_closest_entity`/`Map.FindClosestEntity` gate
  *sensing* on faction-seen too, or only on the sensing unit's own geometric `visibility_range`?
- **`RequestStateMove` arrival tolerance (movement rate now measured, not just pinned).** The
  per-tile advance is settled empirically: `def.movement_speed` is tiles/second at face value,
  progress accumulates along the Euclidean path (diagonal step ≈√2), and the 2026-07-18 Engineer
  circuit test reproduced the base speed within 1% (see the tick-step note and
  `reference_movement_speed_model` memory). What's still engine-native and unmeasured is *when*
  `need_move` flips to `false` — the arrival radius, and whether the `range` argument to
  `RequestStateMove` sets it. One cheap in-game test (domove to a known-distance coord; note the
  stop distance and whether `range` widens it) closes it; the RALLY gate's testability depends on
  getting this tolerance right.
- **`Map.GetDistance` tile semantics.** Real `get_distance` on an entity means closest-tile, and
  center-tile after a `get_location` (rounds up on ties) — see the project memory on this. The mock
  should reproduce at least the single-tile-entity case exactly and document any multi-tile
  simplification.
- **Tile occupancy (ground-layer only).** Only one ground unit *or* building occupies a tile, but
  **multiple flyers can share a tile** (user-confirmed) — so occupancy constrains the ground layer
  only. The first sensing+movement version can skip occupancy (a lone unit approaching an enemy
  never contends for a tile), but multi-unit **RALLY** geometry needs it for *ground* squads — the
  anti-scatter gate gathers them onto *adjacent* tiles, not stacked on the rally point — while an
  all-flyer squad can genuinely converge on one tile. Model it before asserting rally-assembly
  behavior for ground units. Ties to the integer-tile teleport model in the movement step above
  (`reference_tile_occupancy_model`).
- **Reusing the real block stack.** `todo.md` already tracks replacing the Python-simulated
  `sequence`/`for_number` block driver with the real `InstBeginBlock`/`GetFactionBehaviorAsm`. The
  world loops (`for_entities_in_range`/`for_signal_match`) ride that same driver, so that item and
  this one touch the same code — sequence them together if both are picked up.
- **Combat (Phase 4)** is explicitly out of the first version; revisit once sensing/movement tests
  exist and it is clear how much of ENGAGE they already cover.
