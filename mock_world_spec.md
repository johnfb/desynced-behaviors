# Mock World for Behavior Testing — Design Spec

**Status:** design only, not started. Work state lives in `todo.md` (§ `desynced_toolkit` / BSF
infrastructure), not here.

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
   `FRAMEREG_GOTO` target, advance `.location` toward it by `def.movement_speed` (clamped to the
   goal). This is what makes `need_move` eventually return `false`, so arrival-gated logic (the
   RALLY assembly gate, `domove`'s "wait then repeat" loop) becomes testable over ticks rather than
   resolving instantly.
3. **Drain `Map.Defer` callbacks.**
4. *(Deferred — combat phase, not in first version.)* Resolve weapon `on_update` / damage.

Each behavior-carrying entity gets its own `Interpreter` instance (its own `state`/`comp`/`Memory`)
but shares the one `LupaEngine` and the one Lua world registry, so their sensing/commands interact.

## Phasing (first usable version = Phases 0–3, sensing + movement)

**Phase 0 — spike: load the Data package under the stub.** Today only `instructions.lua` loads.
`FilterEntity` needs `data.all` plus real `data.frames`/`data.components`/`data.items`/`data.values`.
Determine the minimal include subset from `data/data.lua`'s `package.includes` (expected around
`utilities → values → items → components → frames`, plus whatever populates `data.all`) and the
extra load-time stubs each file needs — `Frame:RegisterFrame`, the recipe helpers
(`CreateProductionRecipe`, …), etc. These mostly just *store* definitions into `data.*` tables at
load time (the interesting callbacks like `on_update` are stored, not run), so it is largely
mechanical. **Deliverable:** `data.frames`/`data.components`/`data.all` populated, existing test
suite still green. **This is the largest unknown — do it first; it de-risks everything after.**

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
`get_closest_entity`-driven RALLY broadcast.

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

- **Phase 0 feasibility is the primary risk.** If loading `components.lua`/`frames.lua` drags in a
  long tail of load-time engine calls, the minimal-subset approach may need more stubs than
  expected. Mitigation: it is the first phase, and the failure mode is verbose-but-mechanical, not
  conceptual.
- **`faction:IsSeen` fidelity.** The squad design turns entirely on the vision lock; too-simple a
  vision model could make a test pass for the wrong reason. Start simple, but treat the vision
  model as a place to invest if squad tests feel unconvincing.
- **`Map.GetDistance` tile semantics.** Real `get_distance` on an entity means closest-tile, and
  center-tile after a `get_location` (rounds up on ties) — see the project memory on this. The mock
  should reproduce at least the single-tile-entity case exactly and document any multi-tile
  simplification.
- **Reusing the real block stack.** `todo.md` already tracks replacing the Python-simulated
  `sequence`/`for_number` block driver with the real `InstBeginBlock`/`GetFactionBehaviorAsm`. The
  world loops (`for_entities_in_range`/`for_signal_match`) ride that same driver, so that item and
  this one touch the same code — sequence them together if both are picked up.
- **Combat (Phase 4)** is explicitly out of the first version; revisit once sensing/movement tests
  exist and it is clear how much of ENGAGE they already cover.
