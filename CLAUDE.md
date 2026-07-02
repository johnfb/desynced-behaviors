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

## Sibling Tooling Repos

Two external repos are checked out alongside this one for investigating behavior/blueprint encoding (the base62-encoded strings in `data.behaviors` and player clipboard strings):

- `desynced-compiler/` (git clone of [ttm02/desynced-compiler](https://github.com/ttm02/desynced-compiler)) — Python. Compiles Python source into a Desynced clipboard string for pasting into the game's behavior editor. Entry point `main.py` (reads hardcoded `sample_input.py`); `decode.py` / `convert.py` / `read_instruction_table.py` are also present.
- `desynced-tools/` (git clone of [ribrdb/desynced-tools](https://github.com/ribrdb/desynced-tools)) — **Node.js/TypeScript**, this is the one to use for investigations. Provides `ds-disas` (blueprint/behavior string → assembly), `ds-as` (assembly → clipboard string), and `js2ds` (JS/TS → assembly). Core logic in `assembler.ts`, `compile.ts`, `dsconvert.js`, `data.ts`; instruction metadata in `instructions.json`.
  - `npm install` + `npm run generate` (runs `scripts/geninstr.ts`) have been run. Run tools directly via `npx ts-node <script>.ts <args>`, e.g. `npx ts-node disas.ts file.dsc`.
  - `scripts/dumped-game-data.json` is normally a manual export from a live game + "Data Dump" mod (see comment at top of `scripts/geninstr.ts`) and was stale — its `instructions` section had only 128 entries vs. this workspace's `data/instructions.lua` which has 193+ (missing e.g. `is_empty`, causing `ds-disas` to crash with `Cannot read properties of undefined (reading 'execArgs')`).
  - **Workaround applied:** `scripts/extract_instructions_from_lua.lua` loads `data/instructions.lua` directly via a real Lua interpreter (`lua5.4` is installed) and dumps `name`/`desc`/`category`/`args`/`exec_arg` for every instruction as JSON — no live game/mod needed. `scripts/patch-instructions-from-workspace.js` runs that and replaces just the `instructions` key of `scripts/dumped-game-data.json` with the fresh export (everything else in the dump — components/frames/items/values/visuals — is left untouched). Re-run `npm run generate` afterward. Already applied once; `scripts/dumped-game-data.json` in the working tree currently reflects the patched (193-instruction) data.
  - **Consequence:** since the workspace's Lua data is *ahead* of the dump the project's own test snapshots were written against, 3 of the 35 `npm test` cases now fail: `numeric_compare.ts`/`inlining.ts` snapshots differ because `domove` gained a real "Path Blocked" exec pin, and `test1.ts` throws (`Cannot read properties of undefined (reading 'extraArg')` in `compile.ts:2434`) because the `solve()`/match-type union renamed `"Entity"` → `"Unit"`, tripping what looks like a **pre-existing** latent bug in the switch-statement compiler unrelated to this workaround. Also, disassembling a real behavior string (`observer.dsc` at the workspace root) now gets past the `is_empty` crash but hits a **separate, pre-existing** bug in `decompile/disasm.ts`'s `renderArg` (`arg.value.num!.toString()` on a completely empty value, decompile/disasm.ts:351) when an instruction (e.g. `check_number`) has an entirely-omitted optional argument slot — not caused by the data patch, just newly reachable because disassembly gets further now. None of this was fixed; it's flagged here for whoever picks this up next.
  - **Known caveat:** `instructions.json` (the opcode table used by `ds-disas`/`ds-as`) is generated from a manual game-data dump (see comment at top of `scripts/geninstr.ts`) and only has 127 instructions, while this workspace's `data/instructions.lua` defines 198. Disassembling real behavior strings that use newer opcodes (e.g. `is_empty`, confirmed missing) crashes `Disassembler` with `Cannot read properties of undefined (reading 'execArgs')` in `decompile/disasm.ts`. Regenerating `instructions.json` requires a running game copy with the "Data Dump" mod — not currently available in this environment.
