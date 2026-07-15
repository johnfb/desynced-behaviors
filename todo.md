# Outstanding work

Plain checked-in todo list (preferred over the CLI's session-scoped Task tool, which is
stored under `~/.claude/tasks/<session-id>/` and isn't visible from a different session).
Update this file directly as items are picked up/finished.

## Next game release (experimental changelog reviewed 2026-07-14)

- [ ] **Work through `upcoming-changes.md`'s "Impact review" section when the release
      lands.** The experimental changelog (1.0.17919–1.0.18044) is copied there with a full
      cross-reference against this repo appended: deployed-behavior audits (Observer's
      `value_type` dispatch first, then the `is_empty`-on-destroyed-refs sweep,
      `for_signal_match` num-comparison in Check Avoidance, GOTO semantics), toolkit/wire
      impacts (the new branched-`Return` call pins are the big one; mass
      deprecation/auto-convert of `set_number`/`combine_coordinate`/etc.; removed ops that
      break argcache on old corpus data), `instructions_index.md` regeneration, and the
      standing first step: update the extract, run the full test suite. Note: the
      portable-radar timing bug is absent from the changelog — expect it still broken.

## Mining Leader / Follower review

- [x] **Fix `$Offset` reset asymmetry in Miner Follower V2.0's `v_arrow_down` empty-signal
      path.** Resolved/superseded 2026-07-11: reviewed the current `Mining Follower V2.0` (BSF
      decompile via the new CLI) node-by-node. The out-of-range dispatch (`is_empty($Signal)`)
      still has the same shape (`Empty` → straight to the formation-following entry, `Has Value`
      → clears `$Offset` first) but `$AnchorPos` is unconditionally recomputed fresh on every
      entry regardless of branch, so a stale `$Offset` only ever affects *which* relative slot
      within the formation you reuse, not correctness of the follow itself. Not worth a code
      change; no longer tracked as an open bug.
- [x] **Add a proactive leash-distance check before committing a candidate in `v_resource`.**
      Confirmed 2026-07-11: still no proactive check ahead of the reactive per-tick one, same as
      described — reviewed and judged an acceptable, minor inefficiency (one extra tick or two
      before self-correcting) rather than something worth the extra instructions. Not pursuing.
- [x] **Confirm intentionality of the Equal-case merge in `v_arrow_down`'s Max-Range check.**
      Confirmed 2026-07-11: current `Mining Follower V2.0`'s distance `check_number` still merges
      `Equal` with the `Larger` ("get closer") branch. Reviewed in context and it's the correct,
      sensible simplification — no separate handling needed for exact-distance-match.
- [x] **Wire the Async Radar sub into Mining Leader V3.2.** Done — the behavior reviewed this
      session is `Mining Leader V4.0`, which has `Async Radar` fully wired in as a real `sub`
      (component auto-detection with per-tier polling cadence, `State`/`NextState` hand-off into
      the main state machine). Round-tripped clean through the BSF pipeline; only issue found in
      the whole behavior was a misplaced comment (cosmetic, not fixed in-repo since this project
      doesn't hold a copy of the player's own behavior to edit).
- [x] **Review the Mining Hauler behavior.** Done 2026-07-11: `Fendersons Transport V2.0`
      pasted and reviewed node-by-node (150 nodes, 1 sub). State machine keyed directly off
      `@visual` (doubles as both icon and state register); shared `Async Transit` sub used by
      emergency/pickup-transit/dropoff-transit; dual-purpose signal protocol (`num==0`=
      available for pickup, `num>0`=wants delivery). Two of my own branch-direction misreads
      caught and corrected against raw wire data before concluding (`match(...,v_droppeditem)`'s
      fallthrough-vs-declared-arg wiring; `dodrop`'s default `c=2` auto-subtracting the target's
      current stock, ruling out an apparent over-delivery issue at `n146`). No bugs found.

## Observer redesign (`observer_redesign.md`)

- [x] **Redesign `Async Radar`'s calling interface to remove the filter/result attribution
      ambiguity.** Done 2026-07-13. `State*`/`NextState` replaced with `Tag*`/`Pending Tag*`/
      `Next Tag` — deliberately no result-queueing of any kind (a queue-and-delay-one-tick fix
      for the fallback path was fully worked out and rejected by the user as a workaround, not
      a fix; a memory-array-based queue/stack was also considered and rejected, since arrays
      are global across the whole call stack — real collision risk, plus a per-call cost even
      for callers that never need disambiguation). The design that stuck: only the *identity*
      needs shadowing in software (`Pending Tag`, a single small value); the actual result data
      never does, since it's read live off the physical register (or computed fresh in
      fallback mode) every time. See `observer_redesign.md`'s "Async Radar subroutine" section
      for the full mechanism and rationale. `library/mining_leader.dcs` was rebuilt around it
      by the user directly (see next item) — real-caller validation, not just a design on
      paper.
- [x] **Update `mining_leader.dcs` to match the new interface.** Done 2026-07-13, and went
      further than a mechanical port: rebuilt around a single shared `Async Radar` call site in
      the `Begin` hub (called unconditionally every tick) instead of one call site per phase,
      using `switch` to react to both `$Tag` (what was just delivered) and `$PendingTag` (what's
      currently armed) and decide what to request next. This shape eliminates the
      "every call site sharing a `Radar` must consistently thread `Pending Tag`" requirement
      entirely — there's only one call site, nothing else to desync from. Two real bugs were
      found and fixed across two review passes during this rebuild (both rooted in an
      intermediate `$NextState` variable later designed away entirely — a value read before
      ever being written, corrupting dispatch on a later completion).
- [x] **Finish Observer's Task 1 (sensing loop) and Task 2 (movement loop).** Done
      2026-07-13, checked in as `library/observer.dcs`. Task 1: authored, then the user
      rebuilt its state transitions in-game into a priority-lock design (found something at a
      higher-priority stage means stay locked on it (enemy) or reset back to the top
      (damaged/infected), never advance past it; only an empty result advances one step down
      the ladder enemy→damaged→infected→dropped) — one real bug found and fixed (the Dropped
      stage's found/empty branches didn't share cycle-completion bookkeeping). Task 2:
      authored, then substantially rewritten by the user in-game — `value_type`-based
      `Config` classification (verified against source: empty and `Coord` correctly share one
      fallthrough), genuine directional-bias random walking (extrapolating the last observed
      movement vector, closing a gap the original plan left open since `scout_rand_range`
      can't be reused directly), tuned standoff constants (14→20 unstealthed, 5→10 stealthed)
      — reviewed clean, no bugs found. `observer_redesign.md` fully updated to match the
      actual implemented design in both tasks' sections.
- [x] **Harden `Async Radar Get`'s delivery contract.** Done 2026-07-14 (in-game edit,
      re-exported to `library/async-radar-get.dcs` and propagated into the Mining Leader/
      Observer exports automatically by the in-game by-reference subroutine mechanism):
      `get_closest_entity` now reads into a temporary, and `Result`+`Tag` are written
      together, only when a delivery actually happens — fallback hit, authoritative
      fallback-empty in no-radar mode, or radar completion (which delivers even an empty
      result, meaning "scan finished, found nothing"); a charging-radar poll touches neither.
      Closes the "unconsumed result clobbered by the next poll" hazard class root-caused
      during the Mining Leader scan-result bug. One bug caught in review before it shipped:
      the first draft's emptiness guard tested `Result` (the caller's stale value) instead of
      the temporary, which would have permanently disabled the guard after the first-ever
      delivery and turned every subsequent poll into a Tag-signaled delivery of the raw
      fallback. Observer needed no changes — its clear-Tag-then-dispatch consumption pattern
      already treated Tag as a per-call delivery flag.
- [x] **Fix Mining Leader's resource-scan starvation.** Done 2026-07-14: the `c_small_radar`
      case-1 branch re-armed `Async Radar Set` every tick while waiting for the resource scan
      (`$Tag` stays enemy until a delivery arrives), and every `Set` call resets
      `Next Tick := now + period` — so the radar-path resource delivery could never become
      ready (period 10 with small radars, so strictly worse after the fleet upgraded away
      from portables' period 2). Only the visibility-range fallback ever delivered, and a
      stationary leader with nothing visible deadlocked outright: no delivery could flip
      `$Tag` to `v_resource`, so it couldn't even reach `v_transport_route` to wander. Fixed
      with a one-node arm-once guard (`compare_item($NextTag, v_resource) → If Equal → POP`)
      between the `is_moving` check and the arm.
- [x] **Update `Async Radar Set`/`Get`'s `desc` fields to state the contract explicitly.**
      Done 2026-07-14, in-game, re-exported to `library/async-radar-{set,get}.dcs`. Both
      descs verified to round-trip cleanly through the BSF text layer, including Set's
      embedded double quotes (`"already armed"` inside the quoted desc string).
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
- [x] **Verify the arm-once fix in-game.** Confirmed 2026-07-14, both halves: with no node in
      radar range the leader random-walks (the empty resource delivery reaching
      `v_transport_route` — previously a stand-still-forever deadlock), and with a node in
      radar range but outside visibility the radar path delivers it and the leader approaches
      (previously impossible: every-tick re-arming kept the scan from ever completing, so
      only the visibility fallback could deliver).

## Local behavior-library storage (`desynced_toolkit`)

- [ ] **(Idea, not started, 2026-07-12) Build a local mirror of the in-game behavior library,
      instead of only ever working with one-off `.dcs`/BSF files.** Motivating fact: `call`'s
      `sub` field referencing a *saved-library* behavior is an opaque id the game assigns when
      you save it there, which isn't recoverable from a plain "Copy Program" clipboard export
      (confirmed while trying to hand-author a `call` into Observer's Task 1 — the exported
      `library/async_radar.dcs` table has no such id, only `name`/`desc`/`parameters`/
      `pnames`/instructions) — and the user confirmed the in-game editor's own copy/paste
      always embeds subroutines rather than referencing them by id when you copy a behavior
      that has any, meaning **the id form is effectively only used in the game's own internal
      save format**, not something this project's tooling can currently produce a working
      reference to at all. Proposed direction: a local "library" store that mirrors the
      in-game one (behaviors saved as BSF files, each with references to others by name/id
      rather than always embedding), plus an import/export script pair, plus two
      `desynced_toolkit.bsf` changes: (1) a decompiler option to write an embedded
      (`dependencies`-array) sub-behavior out as its own separate BSF file with a reference
      left in the parent's text instead of inlining it, (2) a matching compiler change to
      resolve such file references back into embedded `dependencies` entries (or, longer-term,
      real library-id references once/if this project's local store can track real assigned
      ids) when producing the final `.dcs`. Not designed in detail yet — flagged by the user
      as one of two things to think about next, alongside the `Async Radar` interface
      redesign above. **Motivation confirmed harder 2026-07-14:** in-game, library
      subroutines are genuinely by-reference — editing one updates *and restarts* every
      behavior calling it, with no per-caller action; embedding happens only at
      clipboard-export time. So every checked-in *caller* export silently goes stale the
      moment a shared sub is edited in-game, even though the caller itself changed nothing.
      Seen live: one in-game edit to `Async Radar Get` propagated into three separate
      `library/` exports (and Observer's export picked up the earlier
      `memory_insert`→`memory_set` fix its checked-in copy had been missing).

## Magnifier / drone-swarm design

- [x] **Update `MinerDrone` with a second parameter** (which resource to mine + which signal
      to watch). Done 2026-07-11: `Resource` param added, doubling as both the mining-type
      filter and the signal id watched for building demand.
- [x] **Author the `MagnifierSignal` building behavior.** Done 2026-07-11 — see
      `blight_magnifier_mining.md`. Caught and fixed a real deadlock during authoring: power
      management (200-cap regen) and drone invitation (100-floor mining) must be independent
      conditions, not one shared threshold (an abundant, never-mined area would otherwise
      never invite drones at all).
- [x] **Compile/validate `MinerDrone` against real Lua.** Done 2026-07-11 — rewritten in the
      real, current BSF grammar and actually compiled/decompiled/round-tripped through
      `desynced_toolkit.bsf` (not just hand-authored prose this time). Caught a second real bug
      this way: an omitted loop `Done` pin resolves to the position right after the loop
      *instruction itself* (its own body start), not "after the loop" — all three loop
      instructions in the first draft had this wrong; confirmed via a minimal compiled test
      case and by the mermaid render collapsing from 4 disconnected components to 1 once fixed.
      Still not tested in-game.
- [x] **Integrate `MinerDrone` with an outer building-selection/travel routine.** Done
      2026-07-11 — reservoir-samples among buildings broadcasting demand, travels there, then
      runs the local mining loop; only escalates back to re-picking a building when the local
      area has no viable candidate at all (tries another local node first on single-node
      depletion).
- [x] **Tune the hardcoded oversubscription cap (2) in `MinerDrone` — superseded by real math,
      not just empirical tuning.** Resolved 2026-07-11/12: the flat "2" turned out to badly
      undersell what a real dense layout can deliver. Confirmed via a real in-game blueprint
      (`library/magnifier_lattice.dcs`, see `blight_magnifier_mining.md`'s "final confirmed
      design" section) that a fully-tiled node gets regen from 6 big + 2 small buildings
      (2.161 units/s), needing a cap of 6-9 depending on resource, not 2. The mining floor
      (100) is still an untuned guess.
- [ ] **Make the oversubscription cap a build-density-dependent parameter, not a hardcoded
      constant** (user idea, 2026-07-11). Since the right cap varies a lot by layout (2 for one
      shared building up to 9 for the dense lattice), `MinerDrone` should read it from whatever
      `MagnifierSignal` broadcasts (e.g. packed into the demand signal's own `num`) rather than
      assume a fixed value. Not yet implemented.
- [x] **Overclock modules were wrongly declared "pointless on mining drones" — reversed.**
      Confirmed 2026-07-11 via two independent real in-game stopwatch tests (magnifier cycle
      time, mining drone cycle time) that `SetStateStartWork` applies the `eff_boost`
      calculation natively regardless of whether the calling component's Lua ever references
      `get_work_time` — the original "pointless" claim rested on the opposite, now-disproven
      assumption. See `reference_setstatestartwork_native_boost` memory and
      `blight_magnifier_mining.md`'s corrected "core formula" section.
- [x] **Fix the roaming-Mining-Leader-depletes-managed-nodes problem.** Done 2026-07-11/12:
      `library/mining_leader.dcs` now has a `Check Avoidance` subroutine (`for_signal_match` on
      `v_alert`, `get_distance` with an explicit `Source`, `check_number` against the
      broadcaster's own `num`-as-range) checked both when picking a resource target and when
      choosing a random patrol destination. One real regression caught and fixed during this:
      the random-walk path validated its candidate destination but never actually applied it to
      `@goto`, silently never moving — fixed, confirmed via semantic-diff (exactly one node
      added, nothing else touched).
- [x] **Found: `is_same_grid` fails outright when the second unit is a non-owned/world-faction
      entity** (e.g. a resource node) passed directly. Traced to source
      (`instructions.lua:4192-4211`): every fallback branch not requiring matching factions
      instead calls `GetCoord` on the raw entity, which fails for a non-owned entity reference.
      Fix: `get_location(Unit=X, Coord=$C)` first, then check `$C` instead of `X` directly. Live
      bug found in `MinerDrone`'s node-search loop (`is_same_grid(Unit=$Self, Unit2=$Node)`).
      User has an uncommitted local edit to `library/miner_drone.dcs` as of 2026-07-11 — not yet
      reviewed to confirm it applies this exact fix.
- [x] **`for_signal_match` can accidentally match a unit through the signal value's embedded
      `entity` field** — not the intended signal-broadcasting unit itself, but something it
      references — caused Fendersons Transport haulers to interact with `MinerDrone`'s own
      resource-node-referencing broadcast (oversubscription counting) and with `Observer`'s
      dropped-item-referencing broadcast (unrelated telemetry, `Observer` runs on both mobile
      scouts and stationary power-pole buildings). Fixed 2026-07-12, took four attempts to land
      on the right one — `v_mineable` alone missed dropped items; `v_resource` alone looked
      right from its bitmask but has a narrower per-entity check (`FilterEntity`'s `fnum==7`:
      `def.type=="Resource" or def.name=="Scattered Resource"`) that silently excludes ordinary
      dropped items; two sequential `match` checks (`v_droppeditem` then `v_resource`) worked
      but needed two instructions. **Final fix (user's own insight): a single
      `compare_item(Value 1=Resource, Value 2=$Signal) → If Different → reject`** — checks
      whether the signal's own `.id` field equals `Resource`, which is only ever true for a
      genuine direct id-based broadcast; every entity-embedded-fallback match leaves `.id`
      unset (mutual-exclusivity with `.entity`), so this one equality check rejects any
      fallback match regardless of what entity type got embedded, with no dependency on
      enumerating types at all. Applied and checked in to `library/hauler.dcs` (`n43`, `n79`).
      See `blight_magnifier_mining.md`'s hauler section for the full trace.
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

- [ ] **Early-tech squad variant** (user, 2026-07-15): make the squad behavior set work with
      Cubs/Dashbots/Haulers carrying Small Advanced Turrets or Pulse Lasers (~half the beam
      cannon's 15 range) — parameterize the range-derived constants (gunner engage/panic
      distances, provider gun-line offset ~17, Captain vision-lock band 30-38 all assume
      range-15 weapons). Loadout note at current tech: swapping one gunner shield for a power
      cell covers the charge deficit without the provider.

- [x] **Redesign the squad architecture (v2: Captain).** Done 2026-07-14, driven by the
      user's real squad experiments (v1 squads scattered and trickled into fights one at a
      time; coordination only worked with coordinator eyes-on). Root cause found in source:
      a weapon's manual target (its register 1) only becomes the attack target while the
      faction can *see* it (`c_turret:on_update`'s `faction:IsVisible` gate) — no vision =
      silent per-gunner auto-acquire = scatter. `combat_squad_spec.md` fully rewritten:
      unarmed Captain (Mark V + visibility modules = vis 40 = Small Radar range) stands off
      ≥30 with eyes on the fight, membership = members' `@signal` → Captain entity, commands
      = Captain's `@signal` read via `read_signal`, rally gate before any advance, focus
      fire via each gunner's own weapon register 1. v1's Beacon-era items below are
      superseded; `beacon.dcs`/`beacon2.dcs` stay as test fixtures only.
- [ ] **Implement Captain and Gunner in BSF** (the closed loop), test against a real bug
      camp; then Healer and Power Provider. Constants table and open items in the spec (§6,
      §7) — staging-point geometry and the gate threshold are the two things most likely to
      need in-game tuning. *First drafts authored 2026-07-14 (Squad Captain ~50 nodes, Squad
      Gunner ~15; compile+lint clean, strings handed over), with two v1 simplifications
      chosen deliberately: rally point = the Captain's own position (no staging geometry —
      the Captain already holds standoff), and no mid-fight spread/trickle detector yet.
      Pending the first in-game test.*
- [x] **Confirm the §2.4 self-healing anchor lookup assumption empirically.** Confirmed
      2026-07-11: `for_entities_in_range` scan of a single resource node returned `Result=1`
      before depletion, `Result=0` on an identical rescan right after the node was mined to
      exactly 0 — destroyed/depleted entities really do drop out of faction-wide scans.
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
- [ ] **Reuse the real `InstBeginBlock`/`GetFactionBehaviorAsm`** in `interpreter.py` rather
      than its current Python-simulated block stack and simplified `Memory`/mem-slot
      allocation — `for_number`'s own per-iteration decision is already delegated to real Lua,
      but the block-stack driving itself (`sequence`/`for_number`) is not. (This is about
      `interpreter.py`'s own runtime fidelity — unrelated to the removed `AstCompiler`.)
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
- [ ] **Fix `semantic_diff`'s rendering of a node inserted at a fallthrough boundary**
      (noticed 2026-07-14 verifying the Mining Leader arm-once fix): the insertion itself
      reports fine, but the predecessor's fallthrough pins are additionally reported as
      "pin now resolves to a different node (expected the match of 'n23', got 'n23')" — old-
      and new-file node ids render identically, making the message unreadable, and the pin
      lines are redundant with the reported insertion anyway (the retarget is implied by a
      node having been spliced into the fallthrough chain).
- [x] **Require explicit pin wiring in BSF text for any op with 2+ declared exec pins** (user
      idea, 2026-07-11, prompted by hitting the loop-`Done`-omission bug twice in one session —
      see `feedback_bsf_loop_done_pin_omission` memory). Done 2026-07-14 as designed (single-pin
      ops keep omission; 2+ exec-pin ops require every pin as `>node`/`>POP`/`>NEXT`), as part
      of the agent-ergonomics review that also landed strict parse/compile validation (unknown
      ops/args/pins/ids/targets, duplicates — each previously either a silent miswire or a
      context-free error; bare ids validated against the real game registries so a forgotten
      `$` sigil fails loudly) and a `lint` pass/CLI subcommand (unreachable nodes, literal
      jumps with no matching `(id, num)` label, undeclared param slots; also runs on every CLI
      compile). A prior-art survey (graph data formats, node-editor serializations, community
      Desynced compilers, LLVM/MLIR IR) found nothing to adopt wholesale — the two adopted
      techniques (mandatory explicit successors, a verifier) are exactly what LLVM does for
      machine-edited control flow. See `behavior_source_format.md` § "Explicit-pin rule" /
      § "Validation". The feared test breakage didn't materialize (round-trip tests are
      structural, not golden-string); all fixtures and library exports pass unchanged, and the
      rule immediately surfaced two previously-invisible pins (`switch`'s `Default`,
      `sequence`'s `First`).
- [x] **Investigate `@goto`'s "transport route" option semantics.** Resolved 2026-07-11 via
      source, no in-game test needed: it's not a `@goto` mode at all, it's the separate
      `logistics_transport_route` flag (`enable_transport_route`/`disable_transport_route`
      instructions) that makes a unit continuously shuttle between `@goto` (pickup) and
      `@store` (delivery) instead of moving once. See `blight_magnifier_mining.md`.

## Dev tooling

- [ ] **Set up `ruff` (format + lint) and `mypy` (type checking) for `desynced_toolkit`.**
      Neither is currently installed or configured (only `pytest` is declared as a dev
      dependency in `pyproject.toml`). The stray `.ruff_cache/` directory already in the repo
      isn't from a separately-installed `ruff` — `uv format` (confirmed via `uv format --help`:
      "Additional arguments to pass to Ruff") wraps Ruff directly and has been invoked a couple
      of times already, without ever being added as a project dependency or given a checked-in
      config. `ruff` covers formatting + linting (replacing black/flake8/most of pylint's
      ruleset in one fast tool); `mypy` is the separate, complementary type-checking pass ruff
      doesn't do at all. Add both as explicit dev dependencies in `pyproject.toml`, add a
      checked-in `ruff` config, and decide on `mypy` strictness. (A one-off `uvx ruff check`
      during the 2026-07-14 repo review found a handful of findings — unused imports,
      placeholder-less f-strings in `scripts/analyze_corpus.py`, and two annotation-only
      `F821 undefined name 'lupa'` warnings fixable with a `TYPE_CHECKING` import — cheap to
      burn down when this lands.)

## Tooling / cosmetic, low priority

- [ ] **Add zoom/pan support for large Mermaid graph renders.** Large behavior graphs render
      too small to read comfortably in an Artifact or static SVG. Not blocking current work.
- [ ] **Re-render Mining Leader's component-split diagrams with real `mmdc` output** instead of
      the earlier hand-built SVG approximation (see `feedback_use_real_mermaid_not_handbuilt_svg`
      memory for why that approximation happened in the first place). Offered previously, no
      answer yet on whether it's wanted.
