# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

This repo is tooling, documentation, and design work built *on top of* an extract of the base game data assets for **Desynced** (by The Desynced Team), a factory/automation game with programmable robots — the Lua scripts, textures, sounds, and other assets that define game behavior. There is no build system for the game data itself — it's a read-only reference for analyzing and understanding game mechanics.

**The game data extract lives outside this repo**, at `/home/johnfb/workspaces/desynced-game-data/` (moved out on 2026-07-04 to stop ~560MB of vendored, untracked game assets from cluttering a tooling project — see `desynced-toolkit` below for the actual thing being built here). Every path mentioned in this doc as if it were local (`data/instructions.lua`, `ui/ui.lua`, `main.zip`, etc.) is **relative to that external directory**, not this repo's root. Both Bash and Read can reach it directly via absolute path without any special setup; use `/add-dir /home/johnfb/workspaces/desynced-game-data` if a given session needs it added explicitly. `desynced_toolkit.assets.open_asset_source(...)` (this repo's own code) takes that directory (or its `main.zip`) as a plain argument — nothing is hardcoded.

The entry point manifest is `def.json` (in the external directory), which defines all packages and their load order.

## Package Architecture

The game uses a package system. Each package has an `entry` Lua file that sets `package.includes` (a list of files to load in order) and lifecycle callbacks:

- `package:init()` — runs at startup, registers data definitions into global tables
- `package:init_ui()` — UI-only initialization
- `package:setup_scenario(settings)` — called before scenario starts
- `package:validate_data()` — dev-mode data integrity checks
- `package:on_update(ver)` — migration logic for saved games upgrading from old versions

The packages defined in `def.json`:

| Package | Entry | Type | Purpose |
|---|---|---|---|
| `Data` | `data/data.lua` | Data | All game definitions (items, frames, components, etc.) |
| `UI` | `ui/ui.lua` | UI | In-game HUD, menus, input bindings |
| `FrontEnd` | `frontend/frontend.lua` | Scenario | Main menu and lobby |
| `Freeplay` | `scenarios/freeplay.lua` | Scenario | Primary open-world game mode |
| `Versus` | `scenarios/versus.lua` | Scenario | PvP scenario |
| `Resim/Registers1/Registers2/Signals/Nomad/TowerD` | `scenarios/*.lua` | Challenge | Puzzle/challenge scenarios |

## Core Data Definitions (`data/`)

All game definitions are registered into global `data.*` tables. Each definition file documents its own schema at the top as a comment block.

**Key definition tables:**

- `data.frames` — Entity "frames" (the physical body of a unit or building). Built with `Frame:RegisterFrame(id, def)`. Frame definitions include movement speed (non-zero = unit/bot), health, slots, initial components, and lifecycle callbacks (`on_placed`, `on_destroy`, `on_interact`).
- `data.components` — Attachable components that go into frame sockets. Define behavior, production recipes, power consumption, registers, and event callbacks (`on_add`, `on_remove`, `on_update`, `on_trigger`, `on_take_damage`).
- `data.items` — Inventory items with stack sizes and recipes.
- `data.instructions` — The visual programming instruction set. Each instruction has `func(comp, state, cause, ...)` implementing its behavior. Instructions are categorized: Flow, Unit, Global, Math, Move, Component, AutoBase.
- `data.behaviors` — Pre-encoded behavior programs (stored as base62-encoded strings).
- `data.techs` — Technology tree nodes with uplink recipes and unlock lists.
- `data.explorables` — Procedurally placed world events/encounters. Each explorable implements `GetRelevancy(x, y, info)` and `SpawnExplorable(x, y)`.
- `data.values` — Enum-like named values (colors, radar filter types, alien signals).
- `data.visuals` / `data.visualassets` — Visual representations and socket positions.
- `data.fx` — Sound/particle effects.
- `data.biomes`, `data.landfeatures`, `data.cliffs` — World generation parameters.
- `data.puzzles` — Minigame puzzle definitions.

**Recipe helpers** (defined in `data/utilities.lua`):
- `CreateProductionRecipe(ingredients, producers, amount)` — manufactured items/components
- `CreateMiningRecipe(miners)` — mined resources
- `CreateUplinkRecipe(ingredients, ticks)` — research via uplink
- `CreateConstructionRecipe(ingredients, ticks)` — placed buildings

## Faction & Entity System

The game world is divided into **factions**: `player` (human-controlled), `world` (neutral explorables), `bugs`, `alien`, `anomaly`. Trust relationships between factions determine hostility. Faction-level data persists in `faction.extra_data`.

**Entity registers** are the core of the programming system. Frames have a fixed number of registers (FRAMEREG_GOTO, FRAMEREG_STORE, etc.) that hold typed values (entities, items, numbers, signals). The visual behavior editor programs these by constructing instruction sequences.

**Behaviors** are programs attached to components (particularly `c_behavior` and `c_autobase`). The `data/library.lua` handles compiling encoded behavior strings into bytecode (`GetFactionBehaviorAsm`) and caching them.

## Action System

The game uses typed action dispatchers:

- `PlayerAction.*` — actions sent by a player, validated server-side
- `EntityAction.*` — actions applied to a specific entity
- `FactionAction.*` — actions applied to a faction
- `MapMsg.*` — broadcast map-wide messages
- `UIMsg.*` — UI-only callbacks (run only on local client)
- `Chat.*` — multiplayer chat message handlers
- `Delay.*` — deferred map-tick callbacks
- `MapRun.*` — simulation-side broadcast

## Explorable System

Explorables are the world's discoverable encounters. The file `data/explorables.lua` contains `Explorable_SpawnAt(x, y, discoverer, filter)` which selects an explorable by weighted `GetRelevancy` scores based on tile data (blightness, elevation, richness), player faction level, and save state. Individual explorable definitions are in `data/explorables/`.

## Technology Tree

Defined in `data/techs.lua` and split across `data/tech/tech_*.lua` by faction (robots, blight, alien, human, virus). Tech categories are in `data.tech_categories`. Each tech has `require_tech`, `unlocks` (array of ids it enables), and an `uplink_recipe`.

## Scenarios

Each scenario (in `scenarios/`) extends the base `Data` package:
- `freeplay.lua` — primary game mode; includes tutorial, events, codex entries, and explorable config for the open world
- `versus.lua` — PvP with fixed maps (map data in `scenarios/map_data/`)
- Challenge scenarios (`registers1`, `registers2`, `signals1`, `nomad1`, `towerdefense`, `resimulator`) — self-contained puzzles with specific win conditions

## UI Architecture (`ui/`)

`ui/ui.lua` is the entry point. Key subsystems:
- `widgets.lua` / `utilities.lua` — base UI helpers
- `Program.lua` — visual behavior/instruction editor
- `BlueprintEditor.lua` / `LinkEditor.lua` — blueprint and register linking UI
- `Library.lua` — saved behavior library management
- `FrameView.lua` / `BuildView.lua` — entity inspection and build menus
- `Tech.lua` / `Codex.lua` — tech tree and in-game encyclopedia

Input bindings use `Input.BindAction(name, event, handler)`. Default bindings are in `InputDefaultActionMappings` at the bottom of `ui/ui.lua`.

## Factions in the World

| Faction ID | Description |
|---|---|
| `player` / `player_N` | Human-controlled player factions |
| `world` | Neutral world entities (resources, explorables) |
| `bugs` | Hostile creatures; hostility controlled by `peaceful` setting (0=none, 1=passive, 2=aggressive, 3=swarm) |
| `alien` | Ancient alien civilization ruins and units |
| `anomaly` | The robot anomaly faction (AI opponent) |

## Asset Layout

(All paths below are under the external game-data directory — see "What This Is".)

- `textures/` — PNG icons organized by category (items, frames, components, effects, codex images)
- `sounds/` — Audio assets
- `skin/` — UI skin assets (buttons, panels, icons)
- `languages/` — Localization files for 12 languages
- `scenarios/maps/` — Heightmap TGA files for versus/challenge maps

## `desynced-toolkit` (`pyproject.toml`, `src/desynced_toolkit/`)

A real Python package (managed with `uv` — `uv run`, `uv add`, `uv format`; venv at `.venv/`), begun as a Python-syntax-like compiler/decompiler for behaviors, with runtime semantics backed by `lupa` (an embedded real Lua interpreter) running the **actual, unmodified `data/instructions.lua`** rather than hand-reimplemented-in-Python semantics — the source of most bugs found earlier in this project (see `behavior_format.md`'s revision history). Everything past the wire-bytes layer works with **genuine Lua tables** (1-based, via `lupa`) rather than a Python dict standing in for one — see `dsc_wire.py` below for why that's not just a style preference.

- `assets.py` — loads package files from either an extracted directory or directly out of a zip (e.g. `main.zip`) via stdlib `zipfile`, no extraction to disk needed *for the library*. (This is a Python-level abstraction only: Claude's own Read/Grep/Bash tools still can't see inside a zip, so ad hoc extraction remains the move for interactive exploration in conversation.)
- `dsc_wire.py` — the base62 + optional-zlib + custom-MessagePack-variant codec for Desynced "DS" clipboard strings (`data.behaviors` entries, player clipboard strings like `observer.dsc`). **Replaces the project's original standalone `dsc_codec.py` script** (deleted from the repo root — its logic lives here now), with one real change: `decode_dsc`/`encode_dsc` build/consume genuine Lua tables (via a `lupa.LuaRuntime`) instead of a Python `dict`/`list` rendering. This isn't just tidiness — `Tool.GetClipboard()`/`Tool.SetClipboard(item, type)` (`ui/Library.lua`) are the *real* functions that do this conversion in the actual game, confirmed engine-native (no Lua source for base62/msgpack/clipboard access anywhere in this extract), so a genuine Lua table *is* the most-real representation available; the old tool's 0-based Python dict rendering was an artifact of JSON/Python convenience, not something intrinsic to the format, and it caused a real bug (`decode_dsc()`'s native return used `int` keys while hand-built/JSON dicts used `str` keys — every `dsc_codec.py decode <file>` CLI example elsewhere in this project only ever *looked* string-keyed because that was `json.dumps` doing the coercion for display, not the decoder itself). Building straight into Lua's own 1-based array convention removes that whole class of bug along with the representation layer that caused it. Still the same base62/zlib/msgpack-variant bytes on the wire — cross-validated against the retired tool's own output across all real `.dsc` files in this repo (exact structural match both directions) before it was deleted, and against the official [StageGames/DesyncedJavaScriptUtils](https://github.com/StageGames/DesyncedJavaScriptUtils) `dsconvert.js` reference implementation before that (two real bugs found in *their* encoder, documented in `dsc_wire.py`'s module docstring, deliberately not reproduced). It does **not** use a standard MessagePack library (repurposes type bytes `0xc1`/`0xc4`/`0xc5` for non-standard meanings) and has no instruction-metadata layer or disassembler — string ⟷ Lua-table transport only.
- `engine_stub.lua` / `lua_runtime.py` — the `lupa`-backed runtime. Key discovery, documented in both files: `Get`/`Set`/`GetNum` are **not** external engine globals as `behavior_format.md` originally assumed — they're local aliases *within* `instructions.lua` itself for real `InstGet`/`InstSet`/`InstGetNum`/`InstBeginBlock` functions also defined in that file, resolving arguments through a `GetStack`-based unified integer addressing scheme (`state.mem[]` for locals/literals, `comp.owner:GetRegister()` for frame registers). These are reused **verbatim, unmodified** — only the genuinely-external pieces are stubbed: the `Value` type's arithmetic (confirmed engine-side), a `comp`/`comp.owner`/`Tool.NewRegisterObject` stand-in, and `GetCachedBehaviorAsm` (needed for `jump`/`label`). `LupaEngine.decode_dsc`/`encode_dsc` wrap `dsc_wire.py` for the `Tool.GetClipboard`/`SetClipboard`-equivalent conversion (see above for why they're exposed as plainly-named methods rather than bound onto those exact Lua names — the real functions read/write the OS clipboard with no string argument, which isn't what we're simulating).
- `interpreter.py` — runs a behavior given as a genuine Lua table (1-based, the shape `dsc_wire.decode_dsc()` hands back and `compiler` produces directly — no Python dict anywhere in this module) by delegating each leaf instruction to the real Lua (via `lua_runtime.py`) while keeping the branch/block control-flow driver in Python (the same model `behavior_format.md`'s "Block-type instructions" section documents, validated against real in-game logs earlier in this project). Validated: the real `HexAt` sub-behavior (decoded straight from `HexIndexOf_test_1.dsc` via `dsc_wire.py`) run through this interpreter matches the known-good reference for all 91 in-domain `(R, T)` cases, with every arithmetic/branch/coordinate instruction executing genuine game Lua. One honesty note found during review: `check_number`'s *value reads* are real (`InstGetNum`), but its *branch decision* is currently re-derived in Python rather than reading the real func's `state.counter` result (which is intentionally fed `nil` targets) — behaviorally equivalent today (confirmed `REG_INFINITE` handling coincides either way) but not literally "delegated," unlike `jump`, which is.
- `compiler/ast_compiler.py` — first-cut compiler using Python's own `ast` module to parse a small subset of Python syntax (assignment, `+ - * //`, `if a > b / a < b: ... else: ...`) directly into a genuine Lua table (takes a `lupa.LuaRuntime` to build it). A real equality-handling bug was found and fixed during review: the `if a > b` form used to route the `a == b` case into the wrong branch (fixed by always compiling the Python `else` as the physically-next fallthrough, regardless of which comparison direction is being tested — see the instruction's own comment for why). Confirmed to round-trip through `dsc_wire.py`'s encode/decode cycle.

**Not done yet:** reusing the real `GetFactionBehaviorAsm` compiler from `data/library.lua` (this harness has its own simplified stand-in for now); a decompiler; broader language coverage (loops, function defs as sub-behaviors/parameters, more instructions); a real test suite (nothing under `tests/` yet).

## Design Docs Built on This Data

`instructions_index.md` (workspace root) is an auto-generated reference of every entry in `data.instructions` (`data/instructions.lua`) — visual-editor name, op id, and argument list (in/out/exec, in declaration order, with filter type tags). Regenerate by re-parsing that file if it changes. `behavior_format.md` (workspace root) is the companion reverse-engineered spec for the *wire* format a behavior decodes into/from — register/slot addressing, branch and fall-through resolution, `make_asm`/hidden-literal (`c`) fields, and variable-length-arg instructions — cross-checked line-for-line against `observer.dsc`. It predates `desynced_toolkit.dsc_wire` and was originally written against the retired `dsc_codec.py`'s 0-based Python dict rendering; its description of the *actual wire format* (register addressing, branch resolution, hidden literals, etc.) is still accurate, but where it talks about "dsc_codec.py" or 0-based dict keys as if that's how the data is held in memory, that's the old tool's rendering choice, not the format itself — `dsc_wire.py` now hands back the same information as genuine 1-based Lua tables instead. Together with `instructions_index.md`, these are the missing layer between the wire bytes (transport only, no instruction semantics) and hand-authoring a new behavior; read both before writing or editing any `.dsc` content by hand.

`combat_squad_spec.md` (workspace root) is a hand-written behavior design spec (squad AI roles: Beacon/Scout/Gunner/Support) built from real instructions in `data/instructions.lua` and components in `data/components.lua` — a consumer of this extract, not part of the extract itself. `observer.dsc` is a companion example behavior clipboard string it references, decodable via `desynced_toolkit.dsc_wire` (or, historically, the now-retired `dsc_codec.py`). `beacon.dsc` is a hand-authored implementation of the spec's §5.1 Beacon role (built using `instructions_index.md` + `behavior_format.md`, round-trip-verified against the codec) — target selection is implemented via reservoir sampling rather than the spec's literal shortlist-array pseudocode (a proven equivalent that avoids Memory-array instructions and an unconfirmed `REG_INFINITE` literal), and exact-dedup of duplicate reports is intentionally omitted (no native set/contains instruction exists; the spec's own §7 already treats near-tie imprecision as acceptable). Not yet tested in-game.

`hex_expansion_math.md` (workspace root) is a hand-worked-out coordinate-math spec for a hexagonal-spiral power-pole expansion behavior (`HexAt(origin, R, T) -> coord` and its inverse `HexIndexOf`), built against the integer-only constraints of the Math instructions. `HexAt` is implemented and validated in-game: `hexat_test.dsc` (workspace root) is a self-contained `.dsc` bundling both a reusable `HexAt(R, T, Origin, d_half) -> Result` sub-behavior (via the top-level `dependencies` mechanism documented in `behavior_format.md`) and a test harness that calls it for every `R=0..5, T=0..6R-1` and `debug_print`s the result; `hexat_test_log.txt` is the captured log from that run. Cross-checked by hand against `hex_expansion_math.md`'s formulas for all 92 logged `(R, T)` cases with zero mismatches. This round of building/loading/fixing/re-exporting against the real game is also what surfaced and corrected several wrong assumptions in `behavior_format.md` (coordinate-literal encoding, `exit`/`restart`/block-scoped `next: false` semantics, the `call`/`dependencies` embedding mechanism, the `jump`/`label` computed-dispatch pair) — read `behavior_format.md` itself for the details rather than re-deriving them. `HexIndexOf` now has a `.dsc` too: `HexIndexOf_test_1.dsc` (workspace root) bundles a `HexIndexOf(Coord, Origin, d_half) -> (R, T)` sub-behavior alongside `HexAt` as a second embedded dependency, plus a harness that round-trips `HexAt`'s output back through `HexIndexOf` for every `R=0..5, T=0..6R-1` and `debug_print`s both pairs for comparison. Self-checked with an independent Python re-implementation of the instruction semantics before handoff (exact round-trip plus ~19.5k off-lattice/random coordinates against the cube-rounding math), but **not yet loaded/run in-game** — treat it like `beacon.dsc`/`beacon2.dsc` (built and self-verified, real-engine confirmation still pending).

`main.zip` (in the external game-data directory, ~290MB) is a full pristine zip of this same asset tree (matches `def.json` + all package directories) — likely the raw download this extract was populated from. `desynced_toolkit.assets.open_asset_source()` can load directly from it (see "What This Is" and the `desynced-toolkit` section).
