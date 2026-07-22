# Outstanding work

Plain checked-in todo list (preferred over the CLI's session-scoped Task tool, which is
stored under `~/.claude/tasks/<session-id>/` and isn't visible from a different session).
Update this file directly as items are picked up/finished. Resolved items move to
`history.md` (same section headers) instead of staying here — check there for the design
rationale and in-game findings behind past decisions.

## Next game release (experimental changelog reviewed 2026-07-14)

**Status note (2026-07-21): 1.0.18055 is still the experimental branch, NOT the release.**
1.0.17871 is the release and stays the default `desynced-game-data` symlink target /
what all work targets until Stage Games actually promotes experimental to release. A
2026-07-21 session did a full dry run against a temporary `desynced-game-data-1.0.18055`
checkout (kept on disk alongside `-1.0.17871`, sibling directories) to see what the update
will actually require — real toolkit code changes were needed, not just a data swap, so this
is NOT a same-day flip when it does land. That work was **reverted** from the tree (it isn't
safe to keep live: some of it, e.g. `world.lua`'s `GetEntitiesWithRegister` signature and
`engine_stub.lua`'s `is_empty` semantics, actively breaks 1.0.17871 compatibility rather than
just adding unused capability) but the findings below remain valid preparation:

- [ ] **When 1.0.18055 (or whatever version actually ships as the release) lands for real**:
      re-apply the dry-run fixes — `engine_stub.lua` needs `Value:Divide` (new rounding-mode/
      remainder `div`), `Tool.NewRegisterObject`'s 2-arg form, `NOLOC`/`L` stubs, a bare-
      coordinate coercion path, and a `.entity`/`.raw_entity` split (`is_empty` no longer
      matches destroyed references, 1.0.17919); `world.lua`'s `GetEntitiesWithRegister` needs
      real id/comparison-mode filtering (moved out of `for_signal_match`'s own Lua that
      release); BSF (`decompile.py`/`compile.py`/`parse_text.py`/`render_mermaid.py`) needs
      bespoke dynamic-Case-pin support for `switch` (confirmed via a real corpus bug: without
      it, `library/mining_leader.dcs`'s `switch` case branches are invisible to both lint and
      Mermaid); `instructions_index.md` needs regenerating (a reusable generator now exists,
      `scripts/generate_instructions_index.py` — use it instead of hand-rolling one again).
      Then work through the rest of `upcoming-changes.md`'s "Impact review" — Observer's
      `value_type` dispatch, the `is_empty`-on-destroyed-refs sweep, `miner_drone`'s
      `for_signal_match` `c=2` (confirmed safe: old mode 2 "Exact" and new mode 2 "Number
      Equal" are the same numeric-equality check, carried through the comparison-mode rework
      unchanged), and the two Get Unit Info sites (confirmed non-issue: both feed from
      `get_self`, never an invalid input). Note: the portable-radar timing bug is absent from
      the changelog — expect it still broken.
- [ ] **Apply a legacy op's real `convert` function during BSF decompile, not just read raw
      positions under whatever `args` schema it's currently aliased to.** Found 2026-07-21
      during the 1.0.18055 dry run auditing Observer (this bug is about `decompile.py`'s own
      logic, not tied to any specific game version — it'll matter again whenever any legacy
      op's schema shifts this way, including possibly already on 1.0.17871 for older-still
      corpus data): `value_type` (auto-converts to `data_type`) has its `args` table aliased
      straight to `data.instructions.data_type.args`, so BSF renders it with the successor's
      *new* pin names — but old wire data was written under `value_type`'s *old* position
      layout, and the real in-game `convert` for this op **reorders** positions, not just
      appends new ones. Net effect: `decompile.py` mislabels old `value_type` nodes' branches
      (confirmed against `library/observer.dcs`'s real wiring under 1.0.18055 — the label
      shown doesn't match the position's actual old-schema meaning, though the underlying
      in-game behavior itself is unaffected, since the game's own compiled ASM is built from
      the *converted* form). Scope for the fix: (1) survey the ~10 other legacy ops whose
      `args` alias another op's table (`equip_component_remotely`/`unequip_component_remotely`
      /`for_unlocked`'s and `for_ingredients`'s parents/`compare_unit`, at a glance) for which
      ones reorder vs. only append — only reordering ones are actually broken today; (2)
      decide whether decompile should call the op's real Lua `convert` function directly
      (reuse-real-Lua doctrine, and it'd also silently normalize the rendered op id, e.g.
      `value_type`→`data_type` — need to decide if that's desired or surprising given this
      project's "BSF text shows what's actually there" norm elsewhere); (3) work out how this
      interacts with `semantic_diff` (a decompile-time convert would make old-vs-resaved diffs
      even quieter, which is probably right, but should be deliberate not incidental).
      Workaround until fixed: re-save the affected behavior in-game first, which applies the
      real conversion before export — a fresh export decompiles correctly today. Full repro
      detail in project memory (`reference_legacy_convert_reorder_decompile_gap`).

## Observer redesign (`observer_redesign.md`)

- [ ] **Revisit `Async Radar Set`'s cached radar periods after the next game update.**
      In-game test 2026-07-14 (Observer + portable radar + out-of-visibility dropped item):
      actual delivery cycle is 5 ticks (`TICKS_PER_SECOND`, the register-write quirk — see
      `reference_portable_radar_tickspersecond_quirk` memory), not the advertised 2, because
      `Set` writes the filter registers on every arm. So `c_portable_radar[num=2]` makes
      Get's ready check pass ~3 ticks early — a premature comp-reg read can deliver a
      spurious "completed empty" (the real result still lands via a later re-read).
      `c_small_radar[num=10]` errs safe (late). User has an outstanding bug report on the
      radar timing and expects a fix next game version — after the update, re-run the
      dropped-item test and either keep the advertised periods (if fixed) or bump portable
      to `num=5` (if not).

## Local behavior-library storage (`desynced_toolkit`)

**`library/` now stores BSF text, not raw `.dcs`** (done 2026-07-22 — see `history.md`'s
"Library storage converted to BSF text"). The remaining open idea below is a further step:
mirroring the game's own *by-reference* subroutine model, not just this repo's storage format.

- [ ] **(Idea, not started, 2026-07-12) Build a local mirror of the in-game behavior library
      that resolves `call`'s `sub` field by name/id reference instead of always embedding the
      subroutine inline.** Motivating fact: `call`'s `sub` field referencing a *saved-library*
      behavior is an opaque id the game assigns when you save it there, which isn't recoverable
      from a plain "Copy Program" clipboard export (confirmed while trying to hand-author a
      `call` into Observer's Task 1 — the exported table has no such id, only
      `name`/`desc`/`parameters`/`pnames`/instructions) — and the in-game editor's own
      copy/paste always embeds subroutines rather than referencing them by id, so **the id form
      is effectively only used in the game's own internal save format**, not something this
      project's tooling can currently produce a working reference to at all. In-game, library
      subroutines are genuinely by-reference — editing one updates *and restarts* every behavior
      calling it, with no per-caller action; embedding happens only at clipboard-export time. So
      every checked-in *caller* export silently goes stale the moment a shared sub is edited
      in-game, even though the caller itself changed nothing. Seen live: one in-game edit to
      `Async Radar Get` propagated into three separate `library/` exports (and Observer's export
      picked up the earlier `memory_insert`→`memory_set` fix its checked-in copy had been
      missing). Proposed direction: two `desynced_toolkit.bsf` changes — (1) a decompiler option
      to write an embedded (`dependencies`-array) sub-behavior out as its own separate BSF file
      with a reference left in the parent's text instead of inlining it, (2) a matching compiler
      change to resolve such file references back into embedded `dependencies` entries (or,
      longer-term, real library-id references once/if this project's local store can track real
      assigned ids) when producing the final `.dcs`. Not designed in detail yet.
      - **Layout caveat, still open:** recompiling BSF→`.dcs` currently drops node `nx`/`ny`
        positions (the "BSF envelope/sidecar layer" item below), so pushing a `library/*.bsf`
        file back into the game via `compile` resets that behavior's hand-arranged editor layout
        even when the logic is unchanged. Accepted tradeoff for now (user decision, 2026-07-22).

## Magnifier / drone-swarm design

- [ ] **Make the oversubscription cap a build-density-dependent parameter, not a hardcoded
      constant** (user idea, 2026-07-11). Since the right cap varies a lot by layout (2 for one
      shared building up to 9 for the dense lattice), `MinerDrone` should read it from whatever
      `MagnifierSignal` broadcasts (e.g. packed into the demand signal's own `num`) rather than
      assume a fixed value. Not yet implemented.
- [ ] **(Idea, mechanism now confirmed in-game) Mining Leader/Foreman for slot-less Human
      Miner Mechs.** User idea 2026-07-11: Human Miner Mechs have no Internal socket for a
      behavior controller, so they can't run a `MinerDrone`-style Program of their own.
      Mechanism grounded in source (`instructions.lua`, `GetAdjacentFactionEntityOrSelf`):
      `set_reg_remotely`/`get_reg_remotely` normally require the target to be physically
      touching, *except* when the calling component's `def.key == "autobase"` — that branch
      instead only requires the same `GetPowerGridIndexAt` grid index on both ends, no
      adjacency at all. `c_autobase` *is* the "AI Behavior Controller" component (Internal,
      alien tech); a Power Field (`c_power_relay`) extends the grid over the squad.
      **Mechanism fully confirmed live 2026-07-14** with a purpose-built `Remote Write Test`
      behavior on the AI Behavior Controller: (a) all four frame registers of a same-grid,
      NON-adjacent unit accept remote writes, and the remote GOTO drives movement normally;
      (b) the off-grid negative control is exact — the gate flips at the boundary, writes are
      inert outside, and resume the instant the unit re-enters (evaluated live per write, not
      cached); (c) writing a resource-node ref into the mech's `c_human_miner` register 1
      makes it walk over and mine, no Program of its own. Two design constraints found doing
      (c): the miner normalizes register 1 to item-id form (`obsidian[num=∞]`) within ticks,
      so assignment verification must read register 2, not entity-compare register 1; and on
      current stable, re-writing the target resets mining progress every time (the exact bug
      fixed in experimental 1.0.17996) — the Foreman must write once per assignment
      (arm-once). Remaining: the actual Foreman behavior design itself. **Scope correction
      (user observation 2026-07-14, confirmed in `frames.lua`/`visuals.lua`): only the
      explorable-awarded "Human Miner Mech" (`f_human_miner`, no sockets at all —
      `explorables/human_building.lua` awards this frame) is slot-less. The *buildable*
      "Miner Mech" (`f_human_adv_miner`) has one Internal socket (plus 3 storage and a
      frame-level `component_boost = 50`), so it can host its own Behavior Controller and
      run a MinerDrone-style program directly — the Foreman is specifically for putting free
      explorable mechs to work, not the only automation path for mobile Obsidian/Laterite
      mining.** **Second scope refinement (2026-07-14): alien units don't need it either** —
      the Drill Spike turns out to have 1 Internal socket of its own (self-hosts a
      controller), and the Reformation Core (`c_alien_sc` on a Re-Simulator; engineer
      sacrifice) can synthesize 1 Small + 4 Internal further components onto any
      garage-dockable alien unit without using native sockets. **The explorable Human Miner
      Mech is the one unit class with no self-hosting path at all — the Foreman's real
      constituency.**
- [ ] **(Idea, not started) Obsidian/Laterite mining design.** Researched 2026-07-12: neither
      resource is mineable by `c_miner`/`c_adv_miner` at all (absent from both items' own
      `mining_recipe` in `data/items.lua`) — the only options are `c_extractor` (Medium socket,
      real placeable component, mines both), or whole dedicated units built around
      `c_human_miner` (explorable-awarded "Human Miner Mech" `f_human_miner`: slot-less;
      buildable "Miner Mech" `f_human_adv_miner`: **one Internal socket** + frame-level
      `component_boost = 50`, so it can run its own program — correction 2026-07-14, see the
      Foreman item above) or `c_alien_miner` (in practice **only the Drill Spike**
      `f_alien_miner` — the data's other carrier, "Alien Unit" `f_alienbot`, has its tech
      unlock commented out in `tech_alien.lua` and is unobtainable, matching the user never
      having seen one; the Drill Spike has **1 Internal socket** of its own (not slot-less —
      correction 2026-07-14) plus a frame-level **`component_boost = 300`**, so it
      self-hosts a Behavior Controller directly and mines far faster than its component
      alone suggests — a fact that should reopen the sparse-vs-dense layout math below; it's
      also garage-dockable and therefore Reformation-augmentable on top, see the Foreman
      item) — `c_virus_claws` also mines Obsidian, on the **Ravager** (`f_gastarid1`,
      player-buildable via the virus tech tree, hive-spawner recipe) — but unsuitable for
      most use: the frame also carries `c_ravager_virus_converter` (hidden/integrated, can't
      be removed or turned off), which auto-converts mined obsidian into infected obsidian
      (user-observed; component named in the frame's own definition). No flying option exists for
      either resource. Also found: the dense 6-big/2-small magnifier lattice built for the
      other four resources badly oversupplies these two (`c_extractor`'s own mining rate is
      much slower than a boosted `c_adv_miner`'s) — regen would run 3-5x faster than 2
      extractors could ever consume. The *sparse* single-building pattern (one 3M1L building
      serving its own dedicated 6 packed nodes, not the dense shared lattice) is a much closer
      match: 1 extractor per node is a near-exact balance for Laterite, and reasonably close
      (with some regen margin) for Obsidian. Not designed into a concrete buildable layout or
      built yet.

## Combat Squad (`combat_squad_spec.md`)

- [ ] **Gunner spread on rally (anti-bunch)** (user, 2026-07-18): members currently `@goto` the
      rally entity directly, so all ground gunners aim at the Captain's single tile and jam under
      ground occupancy — no pushing; a stopped unit only yields to a mover one at a time — making a
      large squad's assembly gate fill slowly (arrivals pile on the approach side, shuffle inward as
      stopped units step aside; live-observed). Fix: give each member a distinct fanned target tile
      (ring/formation offset, radius from roster count, which the Captain can pack into the rally
      entity's `num` for free). Design fork captured in `combat_squad_spec.md` §7: self-index even
      spacing *if* member enumeration order is stable/consistent across members, else emergent
      (keepvars-latched random ring with collision re-roll, or boids separation). One-value
      broadcast means the Captain can't assign slots — must be member-side. Testing any fix
      automatically needs the mock to model ground occupancy + the stopped-unit-yields mechanic
      (`mock_world_spec.md` open items; exact yield rule still unknown). Ground squads only —
      flyers stack, so an all-flyer squad converges on one tile.

- [ ] **Early-tech squad variant** (user, 2026-07-15): make the squad behavior set work with
      Cubs/Dashbots/Haulers carrying Small Advanced Turrets or Pulse Lasers (~half the beam
      cannon's 15 range) — parameterize the range-derived constants (gunner engage/panic
      distances, provider gun-line offset ~17, Captain vision-lock band 30-38 all assume
      range-15 weapons). Loadout note at current tech: swapping one gunner shield for a power
      cell covers the charge deficit without the provider. Extend the same parameterization to
      the member self-preservation knobs — above all the **unit health panic level** (currently
      "any hull damage", right only for a tanky/shielded unit; fragile low-tech frames want a
      lower floor, heavily-armored ones want to fight through chip damage), plus battery floor,
      panic-disengage distance, and rally offset. See `combat_squad_spec.md` §6/§7.

- [ ] **Implement Captain and Gunner in BSF** (the closed loop), test against a real bug
      camp; then Healer and Power Provider. Constants table and open items in the spec (§6,
      §7) — staging-point geometry and the gate threshold are the two things most likely to
      need in-game tuning. *First drafts authored 2026-07-14 (Squad Captain ~50 nodes, Squad
      Gunner ~15; compile+lint clean, strings handed over), with two v1 simplifications
      chosen deliberately: rally point = the Captain's own position (no staging geometry —
      the Captain already holds standoff), and no mid-fight spread/trickle detector yet.
      Pending the first in-game test.*
- [ ] **(Future extension, explicitly out of scope so far)**: a base-side `c_autobase`
      building that auto-produces/replenishes squad units and pushes
      orders/equipment-registers directly to squad members while they're home on the base
      grid (the same-grid remote-write exception, now fully confirmed live — see the Foreman
      item). In the field the Captain's signal protocol takes over; the autobase building is
      the barracks/quartermaster half.

## Hex Expansion (`hex_expansion_math.md`)

- [ ] **Rewrite the revised `HexIndexOf` directly in BSF and restore its executable
      validation.** `AstCompiler` was removed outright on 2026-07-14 (user decision: BSF is
      refined enough that it's unnecessary, possibly harmful as a stray design influence), and
      `tests/test_hexindexof_compiled.py` went with it — which was the only executable form of
      the *revised* (post-readability-review) HexIndexOf design and its 217-case validation.
      The checked-in `HexIndexOf_test_1.dcs` still reflects the original pre-review design, so
      until this rewrite happens the revised design exists only as `hex_expansion_math.md`
      prose plus git history (`git show 'HEAD^{/Remove AstCompiler}'^:tests/
      test_hexindexof_compiled.py` — the `HEXINDEXOF_SRC` constant is the design; use it as
      the reference to transcribe into BSF, never resurrect the compiler). Validate the BSF
      version through `Interpreter` against the same closed-form reference cases
      `tests/test_hex_expansion.py` uses.
- [ ] **Reconcile `HexIndexOf_test_1.dcs` against the revised/compiled design.** The checked-in
      fixture still reflects the *original* pre-review design (with the dead `ry` branch, the
      4-instruction coordinate split, etc.) — the readability-driven redesign (fewer temps,
      `for_number`/`jump`/`label` region dispatch) has been compiled and validated against
      reference math, but not yet reconciled against real in-game data. Plan (per the doc's
      "Open items"): hand-rewrite/reorganize in the in-game editor for clarity, export back,
      diff against the current fixture.
- [ ] **Work out terrain-nudge behavior when the ideal `HexAt` point is unbuildable** — the
      candidate offset pattern and retry count are still undecided.
- [ ] **Decide whether a nudged-away-from-ideal placement should feed the *next* point's
      planning from the ideal grid position or the actual nudged one** — not yet decided.
- [ ] **Revisit `SCALE=10000` overflow headroom** if the spiral is ever expected to run into
      the thousands of rings (currently comfortably under the int32 ceiling for `R` in the
      hundreds).

## `desynced_toolkit` / BSF infrastructure

- [ ] **Add the BSF envelope/sidecar layer**: `nx`/`ny` node positions and full
      blueprint/component wrapping beyond a bare behavior plus its `dependencies`. The pipeline
      round-trips the instruction graph itself; position/comment-adjacent fields outside that
      (`cmt` already works via the hidden-field mechanism; `nx`/`ny` don't yet) aren't modeled.
- [ ] **Build a mock world for behavior testing (`mock_world_spec.md`)** — Phases 0-3 (data-
      registry load, engine-native `world.lua` primitives, interpreter op dispatch, movement/
      multi-entity stepping) are done — see `history.md`. Remaining: Phase 4 (combat/damage),
      explicitly deferred so far.
- [ ] **Add automated test coverage for the corpus/analysis scripts** (`scripts/
      collect_clipboard_corpus.py`, `collect_steam_forum.py`, `analyze_corpus.py`,
      `render_examples.py`). Currently exercised only by direct manual runs and one real live
      edit — not covered by `uv run pytest tests/` at all, a gap explicitly flagged in
      `CLAUDE.md` as "worth closing before relying on them for more than ad hoc use."
- [ ] **Add automated round-trip coverage for `library/*.dcs`** (from the 2026-07-14 repo
      review): tests read fixtures only from `tests/data/`, so the living library exports
      have zero automated coverage — nothing in CI would notice a pipeline regression against
      the real deployed behaviors. A parametrized decode/re-encode over `library/` (plus a
      BSF text round-trip for the type-`C` files, skipping type-`B` blueprints) would close
      it cheaply. Needs care around the by-reference staleness fact above: the fixtures churn
      whenever the user re-exports, so assertions should be structural (round-trips clean),
      never content-pinned. *Partially covered since the BSF validation work:
      `test_lint_clean_on_all_library_behaviors` decompiles + lints every library behavior,
      so decode regressions are caught — the render→parse→compile round-trip half is still
      open.*
- [ ] **A branch note without a `(pin)` name is silently dropped by the BSF parser** (found
      2026-07-19 writing Phase 2 mock-world tests). `_parse_branch_notes` extracts `(target, pin)`
      pairs via `_BRANCH_RE.findall`, so a hand-written bare `>POP` / `>n4` (no ` (pinname)`) matches
      nothing and is discarded with no error — the node silently keeps positional fallthrough instead
      of the intended dead-end/target. The canonical renderer always emits `(pin)`, so round-trips
      are unaffected; only hand-authored BSF hits it. This is exactly the silent-miswire class the
      strict validator exists to prevent, so it should **error** (unknown/absent pin) — or, for a
      single-exec-pin op where the pin is unambiguous, be accepted as shorthand for that pin. Small,
      localized fix in `parse_text.py`.
- [ ] **Fix `semantic_diff`'s rendering of a node inserted at a fallthrough boundary**
      (noticed 2026-07-14 verifying the Mining Leader arm-once fix): the insertion itself
      reports fine, but the predecessor's fallthrough pins are additionally reported as
      "pin now resolves to a different node (expected the match of 'n23', got 'n23')" — old-
      and new-file node ids render identically, making the message unreadable, and the pin
      lines are redundant with the reported insertion anyway (the retarget is implied by a
      node having been spliced into the fallthrough chain).

## Tooling / cosmetic, low priority

- [ ] **Add zoom/pan support for large Mermaid graph renders.** Large behavior graphs render
      too small to read comfortably in an Artifact or static SVG. Not blocking current work.
- [ ] **Re-render Mining Leader's component-split diagrams with real `mmdc` output** instead of
      the earlier hand-built SVG approximation (see `feedback_use_real_mermaid_not_handbuilt_svg`
      memory for why that approximation happened in the first place). Offered previously, no
      answer yet on whether it's wanted.
