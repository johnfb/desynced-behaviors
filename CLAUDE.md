# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

This is an extract of the base game data assets for **Desynced** (by The Desynced Team), a factory/automation game with programmable robots. It contains the Lua scripts, textures, sounds, and other assets that define game behavior. There is no build system — this is a read-only reference for analyzing and understanding game mechanics.

The entry point manifest is `def.json`, which defines all packages and their load order.

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

- `textures/` — PNG icons organized by category (items, frames, components, effects, codex images)
- `sounds/` — Audio assets
- `skin/` — UI skin assets (buttons, panels, icons)
- `languages/` — Localization files for 12 languages
- `scenarios/maps/` — Heightmap TGA files for versus/challenge maps

## Python DSC Codec (`dsc_codec.py`)

Decodes/encodes Desynced "DS" clipboard strings (the base62-encoded strings in `data.behaviors` and player clipboard strings, e.g. `observer.dsc`) — pure Python, stdlib-only (`zlib`, `struct`, `json`), no external dependencies. Usage: `python3 dsc_codec.py decode <file>` / `python3 dsc_codec.py encode <file.json> [type_char]`.

This is the base62 + optional-zlib + custom-MessagePack-variant codec only — DSC-string ⟷ Python `dict`/`list` structure. It does **not** use a standard MessagePack library: the format repurposes existing standard MessagePack type bytes (`0xc1` reserved/unused, `0xc4` bin8, `0xc5` bin16) for incompatible custom meanings, so a spec-compliant msgpack decoder would silently misparse it. It has no instruction-metadata layer and does no assembly text rendering/parsing (no disassembler) — it only round-trips the raw table structure.

Ported from and cross-validated against the official [StageGames/DesyncedJavaScriptUtils](https://github.com/StageGames/DesyncedJavaScriptUtils) `dsconvert.js` reference implementation (decode-vs-decode, encode-then-decode-with-the-other-implementation, both ways) using both `observer.dsc` and a synthetic object covering negative/large integers, deep nesting, and unicode strings. Found and deliberately did **not** reproduce two real bugs in the official reference encoder (documented in `dsc_codec.py`'s module docstring):
  1. Integers outside int32/uint32 range crash the official JS encoder (`Grow(...).setUint64 is not a function` — it calls a nonexistent `DataView` method). `dsc_codec.py` writes a correct signed Int64 instead; the official *decoder* reads it back fine, confirmed.
  2. Strings with multi-byte UTF-8 characters (accents, CJK, etc.) are corrupted by the official encoder — it sizes the length header in JS UTF-16 code units instead of UTF-8 bytes. Confirmed the official *decoder* fails to read back the official *encoder's* own output for such strings. `dsc_codec.py` uses the correct UTF-8 byte length and round-trips correctly through the official decoder.

**Do not use `desynced-compiler/` or `desynced-tools/`.** These were sibling tooling repos (Python `ttm02/desynced-compiler`; Node/TypeScript `ribrdb/desynced-tools`, providing `ds-disas`/`ds-as`) formerly checked out alongside this repo for the same investigation, superseded by `dsc_codec.py` and then **deliberately deleted from disk because their output was out of date and wrong** — not merely inconvenient. (They shipped a stale bundled instruction dump and had real bugs of their own: a compiler crash on a renamed match-type union, and a disassembler crash on an omitted optional argument.) Do not re-clone or re-introduce them; if `dsc_codec.py` doesn't cover something you need (e.g. rendering assembly text), that's a gap to solve fresh, not a reason to reach for these.

## Design Docs Built on This Data

`instructions_index.md` (workspace root) is an auto-generated reference of every entry in `data.instructions` (`data/instructions.lua`) — visual-editor name, op id, and argument list (in/out/exec, in declaration order, with filter type tags). Regenerate by re-parsing that file if it changes. `behavior_format.md` (workspace root) is the companion reverse-engineered spec for the *wire* format `dsc_codec.py` decodes a behavior into/from — register/slot addressing, branch and fall-through resolution, `make_asm`/hidden-literal (`c`) fields, and variable-length-arg instructions — cross-checked line-for-line against `observer.dsc`. Together these two are the missing layer between `dsc_codec.py` (string ⟷ dict transport only, no instruction semantics) and hand-authoring a new behavior; read both before writing or editing any `.dsc` content by hand.

`combat_squad_spec.md` (workspace root) is a hand-written behavior design spec (squad AI roles: Beacon/Scout/Gunner/Support) built from real instructions in `data/instructions.lua` and components in `data/components.lua` — a consumer of this extract, not part of the extract itself. `observer.dsc` is a companion example behavior clipboard string it references, decodable with `dsc_codec.py`. `beacon.dsc` is a hand-authored implementation of the spec's §5.1 Beacon role (built using `instructions_index.md` + `behavior_format.md`, round-trip-verified with `dsc_codec.py`) — target selection is implemented via reservoir sampling rather than the spec's literal shortlist-array pseudocode (a proven equivalent that avoids Memory-array instructions and an unconfirmed `REG_INFINITE` literal), and exact-dedup of duplicate reports is intentionally omitted (no native set/contains instruction exists; the spec's own §7 already treats near-tie imprecision as acceptable). Not yet tested in-game.

`hex_expansion_math.md` (workspace root) is a hand-worked-out coordinate-math spec for a hexagonal-spiral power-pole expansion behavior (`HexAt(origin, R, T) -> coord` and its inverse `HexIndexOf`), built against the integer-only constraints of the Math instructions. `HexAt` is implemented and validated in-game: `hexat_test.dsc` (workspace root) is a self-contained `.dsc` bundling both a reusable `HexAt(R, T, Origin, d_half) -> Result` sub-behavior (via the top-level `dependencies` mechanism documented in `behavior_format.md`) and a test harness that calls it for every `R=0..5, T=0..6R-1` and `debug_print`s the result; `hexat_test_log.txt` is the captured log from that run. Cross-checked by hand against `hex_expansion_math.md`'s formulas for all 92 logged `(R, T)` cases with zero mismatches. This round of building/loading/fixing/re-exporting against the real game is also what surfaced and corrected several wrong assumptions in `behavior_format.md` (coordinate-literal encoding, `exit`/`restart`/block-scoped `next: false` semantics, the `call`/`dependencies` embedding mechanism, the `jump`/`label` computed-dispatch pair) — read `behavior_format.md` itself for the details rather than re-deriving them. `HexIndexOf` has no `.dsc` yet.

`main.zip` (workspace root, ~290MB, untracked) is a full pristine zip of this same asset tree (matches `def.json` + all package directories) — likely the raw download this extract was populated from. Not otherwise referenced by any tooling here.
