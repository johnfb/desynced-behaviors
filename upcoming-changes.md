## Experimental 1.0.17919
### Additions
- Add icon to 'Foundation' object type radar filter that is distinct from the foundation unit type icon
- Make behavior instruction search also match the English names even in other languages as well as make it ignore spaces (so "canequip" will find "Can Equip")
- Make tooltips close by pressing Esc
### Changes
- Show "Destroyed Object" instead of nothing on a register or behavior value that contains a target reference that has been destroyed
- For a bot that isn't connected or without "Deliver Items" set, require items requested by the player via the unit interface to be delivered by an order carrier in the same network (instead of having the bot go pick it up by itself, even across logistics networks)
- Clarify register selection category names ('Object Type' became 'Filter Value', 'Value' became 'Label Value')
### Behaviors
- Find certain instructions by a list alternative names (i.e. "set" or "assign" will also find the 'Copy' instruction)
- Instead of stopping a behavior on a crash (i.e. exceeding unlock step limit or call depth), keep it paused so the failure can be inspected in the behavior editor
- Rework behavior unlocking: Add extra options to the unlock instruction to allow specifying the instruction limit and 2 modes 'Pause on limit' and 'Continue next tick'
- Rework behavior unlocking: When starting a server besides disabling unlocking, a maximum limit of allowed unlocked instructions can be set
- New instruction 'Return': For called sub-behaviors with an optional branch name which enables diverting the logic to a different path on the outer call node
- Updated instruction 'Divide': Add rounding mode selection and return a second value containing the remainder of the division
- Deprecated behavior instruction 'Modulo': Due to Divide now optionally returning the remainder, existing nodes will automatically convert
- Updated instruction 'Signal Filter': Add more comparison modes ("Number Any Bit Match", "Number All Bits Match", "Fully Equal", "Data Equal", "Destroyed References")
- Updated instruction 'Signal Filter': Rework internal logic and make numerical checks consistent with 'Compare Number' (infinite is larger than anything, not is smaller than anything)
- Updated instruction 'Combine': Renamed from 'Combine Register', will be listed when searching for 'Set Number', 'Set Data' or 'Combine Coordinate'
- Deprecated instructions: 'Set Number', 'Set Data' or 'Combine Coordinate', will automatically convert into 'Combine'
- Updated instruction 'Separate': Renamed from 'Separate Register' will be listed when searching for 'Separate Coordinate', 
- Updated instruction 'Separate': Add a "Coordinate" output parameter (in addition to the existing separate X/Y parameters)
- Deprecated instructions: 'Separate Coordinate', will automatically convert into 'Separate'
- Updated instruction 'Compare': Renamed from 'Compare Register' and clarified description
- Updated instruction 'Compare Type': Renamed from 'Compare Item' and clarified description
- Removed instructions 'Is Unit A' and 'Is a': Will automatically get converted to 'Compare Type'
- Added instruction 'Compare Data': Compares the data part (identifier, target reference or coordinate) of two values
- Removed instruction 'Compare Unit': Will automatically get converted to 'Compare Data'
- Updated instruction 'Stop Behavior': Renamed from "Exit", show in list when searching for 'Exit', 'Abort' or 'Quit'
- Updated instruction 'Data Type Switch': Added 'Target Reference' branch pin, make any unused pin continue with 'No Match'
- Updated instruction 'Target Type Switch': Renamed from 'Unit Type', added branch pins for Wall/Gate/Foundation/Dropped Item/Resource/Destroyed Object, make any unused pin continue with 'No Match'
- Updated instruction 'Is Empty': Will no longer match a target reference that has been destroyed
## Experimental 1.0.17925
### Changes
- Make remaining loop type behavior instructions match others, to clear an output argument if not looping once, otherwise keep the last result ('Loop Units (Range)', 'Loop Research', 'Loop Research Unlocks', 'Loop Research Ingredients', 'Loop Recipe Ingredients', 'Loop Repair Ingredients', 'Loop Signal', 'Loop Nearby Resources')
- Allow inventory instructions ('Count Slots', 'Loop Inventory Slots', 'Inventory Total') to be used on dropped items and lootable explorables
### Fixes
- Fix numerical comparison used by behavior instructions 'Switch' and 'Loop Signal' to always treat infinite as a number larger than anything else
- Fix behavior instruction 'Unequip Component' to not allow unequipping of integrated components
- Fix behavior instruction 'Is Equipped' to not log a Lua error when getting passed a wrong value that doesn't specify a component identifier
## Experimental 1.0.17933
### Additions
- Performance statistics for behaviors: Adds a new special view in the 'Library' window with statistics for instructions executed per second as well a line of text with stats at the top when editing a behavior main routine
- Add view options to behavior editor to control camera zoom/height as well as allow the main editor to be made transparent to show the game view behind it
- Behavior instruction 'Place Construction': Add support for placing multi blueprints
- Behavior instruction 'Place Construction': Add output value 'Target Reference' with a reference to the placed construction site (first if placing a multi blueprint)
### Changes
- Rework behavior unlocking: When an unlocked behavior ends and restarts, reset unlock state and wait 1 tick
### Fixes
- Fix Lua errors getting logged when viewing tooltips in the tech tree and unit interface while the unit is getting destroyed or upgraded
- Don't make pressing Esc hide a tooltip that was already hidden via Lua code
## Experimental 1.0.17971
### Changes
- Allow Assembler to be produced in Human Factory
- Allow Metal Bar, Metal Plate and Reinforced Plate to be produced in Reforming Pool
- Allow Power Petal and Phase Leaf to be produced in Pylon
- Changed recipe of Alien Factory, Hybrid Worker
### Behaviors
- Overhaul of instruction categories (into "Flow", "Logic", "Loops", "Values", "Units", "Movement", "Inventory", "Logistics", "Components", "Production", "Communication", "World", "Memory")
- Allow many instructions to operate not only on one's own faction but also units of allied factions, unlocked explorables and dropped items ("Get Space for Item", "Check Space for Item", "Get Health", "Get Shield", "Get Battery", "Check Health", "Check Battery", "Get Unit Info", "Get Unit Power Info", "Count Items", "Have Item", "Can Equip", "Has Like Component")
- New instruction 'Get Grid Info': Returns power grid information at a location
- Removed instruction 'Get Grid Efficiency': Will automatically get converted to 'Get Power Grid Info' - Breaking changes: Will no longer return a target reference to the unit, just the number
- New instruction 'Loop Ingredients': Loop over ingredients required for production, construction, research or repair (with option to get remaining, total or single step amounts)
- Removed instruction 'Loop Repair Ingredients': Will automatically get converted to 'Loop Ingredients'
- Removed instruction 'Loop Recipe Ingredients': Will automatically get converted to 'Loop Ingredients'
- Removed instruction 'Loop Research Ingredients': Will automatically get converted to 'Loop Ingredients'
- Behavior instruction 'Compare Data': Remove pin "If Empty" as it isn't really relevant to the instruction and there is likely no real use case for it anyway
- Fix instruction 'Drop Off Items' to limit dropping off only into owned or allied units/buildings and unlocked explorables
- Behavior instruction 'Get Unit Info': Can now check a type identifier of a unit as well as a target reference to a non-owned unit
- Behavior instruction 'Loop Products': Renamed from 'Loop Producer Items'
- New behavior instruction 'Loop Researched': Loops through everything of a given type (components, items, units, etc.) the faction has researched, with option to only return what can be made in available production components
- Removed behavior instruction 'Loop Unlocked Components': Will automatically get converted to 'Loop Researched'
- Behavior instruction 'Check Altitude': Don't hide the "No Visibility" pin behind extra options
- Behavior instruction 'Wait Component': Don't hide the "Not Working" pin behind extra options
- In the behavior editor improve the tooltip on optional pins hidden by default behind extra options
### Fixes
- Remove audio track on Stage Games Logo video to avoid capture software picking up audio noise (i.e. Steam game video capture)
- Fix logging of a Lua error when switching the selection with a shortcut group key while looking at the Blight Magnifier tooltip
- Fix behavior potentially being unable to start after removing a parameter of a called sub-behavior which uses branched returns
- Fix behavior editor interface explanation not highlighting the name/description correctly since 1.0.17933
- Fix dynamic tooltips getting stuck in memory while invisible if opened and closed in the same frame (sometimes leading to endless logging of Lua errors)
- Fix for System Index appearing empty and causing a Lua error to be logged when opened in the same frame as a tooltip
- Enable Unicode console text output on the dedicated by default without the need to specify -UTF8Output in the server command line
## Experimental 1.0.17996
### Additions
- Add windowed mode to behavior editor (limited view which still allows map and unit control)
- Added new guided behavior tutorials (accessible via the behavior help welcome screen)
- Added faction wide memory as an option for all memory behavior instructions (and also in the Memory Viewer window in the behavior editor)
- In the Memory Viewer, add deleting of a single array besides just the 'Clear All' button
- Added game option to disable story related popups
### Behaviors
- New instruction 'Check Logistics'
- Instruction 'Set Logistics': Added option "Connect To Logistics Network"
- Removed instructions 'Connect', 'Disconnect', 'Enable Transport Route', 'Disable Transport Route': Will automatically get converted to 'Set Logistics'
- Fix Instruction 'Mine': Avoid it resetting a miner component's progress when setting to a specific resource node target reference
- Fix instruction 'Mine': Don't jump to 'Cannot Mine' branch when being able to mine but already is mining the same target
- Fix previously removed instruction 'Get Grid Efficiency' to correctly convert old behaviors to use 'Get Grid Info' instead of it becoming an invalid instruction (bug in 1.0.17971)
- Instruction 'Check Blight': Add 'No Visibility' pin to match 'Check Altitude', add option to check for near blight (blight gas can be extracted there)
- Instruction 'Check Altitude': Add option to check for increased wind (high enough for increased wind power)
### Changes
- Don't show contents of a dropped item in a register with a target reference if the player faction has no visibility on it
### Fixes
- Automatically end debug inspecting in behavior editor if the inspected target is destroyed or converted (i.e. Command Center deployment)
- Fix various spelling mistakes in tech descriptions, story popups and behavior instruction details
- Fix 'Carry Items' not getting applied when pasting settings onto a building with an Item Transporter equipped
## Experimental 1.0.18020
### Changes
- Keep items reserved on the ground when placing a new construction over it (avoids items and components for relocation getting absorbed)
- Clear the GOTO register after picking up the last of a dropped item (avoid showing 'Destroyed Object')
- Clear the target register of a weapon component after destroying a target (avoid showing 'Destroyed Object')
- Clear the mining status register of a mining component after clearing a node (avoid showing 'Destroyed Object')
### Behaviors
- New instruction 'Loop Coordinate': Loops through coordinates in a range (given minimum and maximum) around a unit or coordinate
- New instruction 'Category Switch': Diverts the program depending on the category of the passed value
- New instruction 'Memory Sift': Remove multiple items of a memory array matching a filter
- Instructions 'Notify' and 'Set Signpost': Add support for custom tags like {My Tag} which allows embedding additional values
- Instruction 'Break': Add a count number option to break out of multiple loops at once
- Instruction 'Data Type Switch' and 'Target Type Switch': Put all pins behind the expandable extra options so normally it only shows pins which are in use
- Instruction 'Get Item Info': Breaking change, the value for Charge Time is now in simulation ticks and not rounded to seconds
- Instruction 'Loop Equipped Components': Make it return the index (if multiple are equipped) alongside the component identifier (usable input for many other instructions)
- Instruction 'Loop Equipped Components': Change second return value to be the socket index (0 for integrated components) instead of just the loop iteration count
- Instruction 'Equip Component': The 'Socket Index' argument can now also be given as a component identifier (and index if multiple are equipped) to swap with an equipped component
- Fix instruction 'Check Altitude': Instruction broke in version 1.0.17996 and wrongfully checked blightness instead of altitude
- Fix instruction 'Separate': Outputs 'Coordinate' and 'Data' were incorrectly written to output 'Y' (since 1.0.17919)
- Fix instruction 'Memory Length': Not only return identifier keys with the number but also target reference and coordinate keys
- Fix memory reading behavior instructions set to Local Arrays still using Faction Arrays if no local arrays exist
- Revert instruction 'Sort Storage': Was accidentally deleted in the previous patch 1.0.17996
### Fixes
- Fix Deployer component wrongfully spawning a component when deploying a Human Tank unit which was acquired after the built-in Tank Turret component was removed
- Show stats for the built-in Tank Turret component in the tooltip of the Human Tank unit
- Prevent clicking a behavior notification from revealing the location of an otherwise hidden enemy unit
- Prevent equipped Deployer component losing its "One-Time Use" state when the unit it is equipped on itself is acquired and re-deployed or relocated
## Experimental 1.0.18021 Hotfx
### Fixes
- Fix internal API change to Tool.NewRegisterObject and register:Init to correctly set a number even if the value was empty, affecting a few instructions
- Fix behavior instruction 'Bitwise Op' which stopped accepting empty values as its first argument
## Experimental 1.0.18044
### Changes
- Treat the movement distance number of the GOTO register set to infinity as infinitely large (not 0)
- Make a drone which has its GOTO register explicitly set to 1 not automatically dock (until now docking was done with both 1 and the default 0)
- Behavior instruction 'Lock Item Slots': When locking all slots, instead of being limited to storage slots, make it affect slots matching the type of the item being set (i.e. Storage or Gas)
- Behavior instruction 'Unlock Item Slots': When unlocking all slots, instead of being limited to storage slots, make it affect slots of all types
### Fixes
- Fix visibility and power range visualization circles becoming stuck when switching the selected unit (i.e. by pressing a shortcut group key or back space or shift-clicking a register with a target reference) while hovering a component socket or item slot
- Make hovering an item slot show an arrow of the order related to the hovered item slot instead of visualizing any order that targets the currently selected unit/building
- Show range of light components in the tooltip and visualize it in the world when hovering the mouse on an equipped light component
- Trigger blight discovery even if the faction has no player logged in
- Fix unequipping a Blight Charger component on alien and bug units disabling their inherent blight shielding
- Make behavior editor Memory Viewer window slightly wider so the 10th item of each row doesn't get cut off
- Fix multiplayer state potentially going out of sync when a unit docks/is possessed then undocks/is unpossessed in a different 60x60 map chunk
- Avoid logging Lua error 'entity isn't placed on the map' when a worm attacks then immediately gets possessed or docked
- Fix GOTO queueing to multiple dropped items aborting after picking up the first one since ver. 1.0.18020


---

# Impact review against this repo (written 2026-07-14, against the changelog above)

Cross-referenced against `library/*.dcs` (op-usage counts from decompiled exports), the design
docs, `behavior_format.md`, and project memory. Ordered by how much of our stuff each touches.

## Likely behavioral changes to deployed behaviors — audit after update

- **`is_empty` no longer matches destroyed references** (17919). 25 uses across `library/`.
  Most consume fresh instruction outputs (safe), but any "did my target die" check via
  `is_empty` silently flips. **Baseline measured in-game 2026-07-14 (Dangling Ref Test v3)**:
  on current stable, an entity-only destroyed reference reads as *empty* (num≠0 refs read
  non-empty — the num dominates), so today `is_empty` genuinely works as a death-detector and
  this change breaks it — the audit direction is working → broken. Migration targets: Target
  Type Switch's new 'Destroyed Object' pin or Signal Filter's 'Destroyed References' mode. Related cluster: registers now *display* "Destroyed Object",
  Signal Filter gains a "Destroyed References" mode, Target Type Switch gains a 'Destroyed
  Object' pin, and the engine now auto-clears GOTO/weapon-target/mining-status registers on
  target destruction (18020) — the dangling-reference story in
  `reference_dangling_entity_reg_infinite` (entity=nil, num=REG_INFINITE) needs re-testing
  wholesale; the auto-clearing changes may also settle its open eager-vs-lazy question.
- **`value_type` ('Data Type Switch') gains a 'Target Reference' pin; unused pins now continue
  to 'No Match'** (17919, 18020). Observer's `Config` classification (`observer_redesign.md`,
  the load-bearing `instructions.lua:737` analysis) depends on exactly which pin a unit-valued
  `Config` takes — a new Target Reference pin plausibly captures it before the 'Unit' pin.
  **Re-verify Observer's follow mode first thing after updating.** `unit_type` ('Target Type
  Switch') gains six pins — a fresh instance of the schema-evolution gotcha (old behaviors'
  omission of the new pins is not authorial).
- **Unlocked behavior end/restart now resets unlock state and waits 1 tick** (17933), and
  crashes pause instead of stopping (17919). Changes `behavior_format.md` § "Stopping a
  behavior" (the "restart does not yield, can spin forever under unlock" claim), the
  STOP/dead-end and sequence-cascade notes, and `reference_jump_vs_pop_block_stack_leak`
  (recursion-limit crash now pauses for inspection instead of stopping). Our deployed
  behaviors all have explicit `wait` hubs, so the +1 tick is likely benign — but it's a
  timing change to every POP-to-empty auto-restart.
- **GOTO register semantics** (18020/18044): auto-clear after picking up the last of a dropped
  item; movement-distance num of infinity now means "infinitely far" (was 0); GOTO=1 no longer
  auto-docks drones; multi-dropped-item GOTO queueing fixed. Touches
  `reference_goto_register_semantics` and the Hauler's pickup flow. Sharp edge: a dangling
  reference (num=REG_INFINITE) accidentally written to `@goto` used to mean distance 0 and now
  means infinite — Mining Leader writes composite entity+num into `@goto`
  (`set_number(Value=Target, Number=3, Result=@goto)`), so any path that could land a
  destroyed ref there behaves differently.
- **`for_signal_match` ('Loop Signal') reworked twice**: numerical comparison now treats
  infinite as larger-than-anything (17925), and the output arg is cleared when the loop runs
  zero times (17925). Mining Leader's `Check Avoidance` matches `v_alert[num=range]` signals —
  num-part comparison rules changing could alter which broadcasts match. Re-test avoidance
  after update.
- **'Mine' fixes** (17996): re-setting the same resource target no longer resets mining
  progress, and no longer bounces to 'Cannot Mine' when already mining it. Good news, but it
  removes the constraint behind `blight_magnifier_mining.md`'s "rely on native
  auto-store/auto-resume, never re-drive the miner every tick" correction — re-driving becomes
  cheap. The doc's rationale prose is now historical.

## Wire-format / toolkit impact (`desynced_toolkit`, `behavior_format.md`, BSF)

- **New 'Return' instruction with branched returns** (17919): a `call` node can now have
  additional exec branch pins named by the sub's Return labels. Biggest format change in the
  batch — `behavior_format.md`'s `call`/`dependencies` section, BSF
  compile/decompile/argcache, and `semantic_diff` all assume a call has one exec path. Must be
  investigated against real exported data before hand-editing any behavior using it.
- **Mass deprecation/auto-convert**: `set_number`/`set_data`/`combine_coordinate` → 'Combine',
  `separate_coordinate` → 'Separate' (+ new Coordinate output), `modulo` → Divide's new
  remainder output, `exit` → renamed 'Stop Behavior', `compare_item` → renamed 'Compare Type',
  new 'Compare Data' (likely the better fit for the Hauler's `.id`-equality check and Mining
  Leader's arm-once guard, someday). `set_number` alone appears 43 times in `library/`. The
  first in-game open+re-save after the update converts a behavior wholesale, so every
  checked-in export goes op-schema-stale at once and `semantic_diff` will report mass changes
  that are really conversions — don't misread that as user edits (cf.
  `feedback_resave_reencodes_unrelated_wiring`, now at op granularity).
- **Removed (not deprecated) ops** break our argcache resolution for any old `.dcs` still
  using them: `is_unit_a`/`is_a`, `compare_unit`, `get_grid_efficiency`,
  `loop_repair/recipe/research_ingredients`, `loop_unlocked_components`,
  `connect`/`disconnect`/`enable_transport_route`/`disable_transport_route` (→ 'Set
  Logistics'; `blight_magnifier_mining.md` documents the transport-route pair by name). Our
  `tests/data/` fixtures use none of these; the gitignored `corpus/` almost certainly does.
- **'Divide' rounding modes + remainder** (17919): op schema changes under
  `hex_expansion_math.md`'s integer-division-dependent math (7 `div` uses in the hex
  fixtures). The full pytest suite runs against the real `instructions.lua`, so updating the
  extract re-validates HexAt/HexIndexOf automatically — run it before trusting anything.
- **Faction-wide memory arrays** (17996) + local-vs-faction fallback fix (18020): extends
  `reference_memory_arrays_global_across_calls` and the `keeparrays` envelope docs with a
  third scope; confirm Async Radar Set/Get's arrays stay Local.
- **`Tool.NewRegisterObject`/`register:Init` API change** (18021 hotfix): `engine_stub.lua`
  stubs `Tool.NewRegisterObject` — verify the stub matches the new empty-value/number
  semantics when the extract updates.
- **`instructions_index.md`**: wholesale regeneration required (new/removed/renamed ops,
  categories overhauled into Flow/Logic/Loops/Values/…). Pin/display names feed BSF text via
  argcache, so re-exported BSF text will shift too.
- **'Break' gains a count option** (18020): `last` (31 uses) — interpreter's block-stack
  handling and BSF pin data pick this up from the new extract.

## Notable non-impacts and opportunities

- **The portable-radar timing bug (TICKS_PER_SECOND vs charge_time) is NOT mentioned anywhere
  in this changelog** — the hoped-for fix looks unlikely for this release; the todo item's
  post-update re-test should expect it still broken.
- 'Place Construction' now places multi blueprints and returns a Target Reference to the
  placed site (17933) — directly useful for the hex-expansion builder's future placement work.
- Unlock's new instruction-limit modes, the performance-statistics view, crash→pause
  inspection, and the windowed behavior editor all improve the live-debugging story this
  project leans on.
- Renames ('Compare', 'Separate', 'Combine', 'Stop Behavior', 'Target Type Switch', 'Loop
  Products') are display-name churn; op ids in wire data appear unaffected except via the
  deprecation conversions above.

**When the release lands**: update the sibling `desynced-game-data` extract, run
`uv run pytest tests/` (it exercises the real `instructions.lua`), regenerate
`instructions_index.md`, then work through the audits above — Observer's `value_type`
dispatch and the `is_empty`-on-destroyed-refs sweep first.
