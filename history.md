# History

Resolved `todo.md` items, archived here instead of deleted so the design rationale and
in-game findings behind past decisions stay available. Mirrors `todo.md`'s topical section
headers — this file is **not** ordered by date, release, or commit; a section appears here
only if it has resolved items to hold. Current/open work stays in `todo.md`; check there for
present state, this file for how something got decided.

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
- [x] **Verify the arm-once fix in-game.** Confirmed 2026-07-14, both halves: with no node in
      radar range the leader random-walks (the empty resource delivery reaching
      `v_transport_route` — previously a stand-still-forever deadlock), and with a node in
      radar range but outside visibility the radar path delivers it and the leader approaches
      (previously impossible: every-tick re-arming kept the scan from ever completing, so
      only the visibility fallback could deliver).

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

## Combat Squad (`combat_squad_spec.md`)

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
- [x] **Confirm the §2.4 self-healing anchor lookup assumption empirically.** Confirmed
      2026-07-11: `for_entities_in_range` scan of a single resource node returned `Result=1`
      before depletion, `Result=0` on an identical rescan right after the node was mined to
      exactly 0 — destroyed/depleted entities really do drop out of faction-wide scans.
- [x] **Test the full squad (Captain, Gunner, Healer, Power provider) against a real bug
      camp.** Done 2026-07-22: several hours of mixed-composition live play, Gunner behavior
      deployed across Scouts, Dashbots, Haulers, Mark V, human tank frames, and Command Center
      bots with different turrets. Overall behavior held up well; occasional member losses,
      concentrated on Scout/Dashbot gunners closing too near an enemy before disengaging — not
      seen on the other frames running the same behavior. Follow-up (hypothesis: panic-
      disengage range needs to scale with frame speed) tracked as its own open item above,
      and folded into `combat_squad_spec.md` §5/§7.
- [x] **Gunner spread on rally (anti-bunch).** Resolved 2026-07-22 via `library/formation-hold.bsf`,
      a new sub called from `squad-gunner.bsf`'s two entity-anchored RALLY paths. Sidesteps the
      ring-vs-emergent design fork entirely (no need to resolve whether member enumeration order
      is stable): each member rolls a random offset from the anchor once (persisted via a
      pass-by-reference `Offset` parameter) and holds that slot, re-homing only when drifted past
      a tolerance. See `combat_squad_spec.md` §7 for the shipped shape and its accepted limits (no
      collision avoidance, RALLY-paths-only scope). Two real implementation bugs surfaced and were
      fixed during the in-game import/export/review cycle, both about `sequence()`'s block-stack
      semantics — confirmed against the real engine source (`data/instructions.lua`,
      `data/components.lua`), not guessed:
      1. `sequence()` genuinely calls `BeginBlock`/pushes a frame onto `state.blocks`, the same
         family as a loop instruction. The only sanctioned way to jump out of it before natural
         exhaustion is `last()` (Break), which does `table.remove(blocks)` *before* jumping to the
         Last pin. A bare `jump()` added to route the RALLY branches around the shared `domove`
         tail skipped that removal — leaking one block frame per RALLY tick and hitting "Behavior
         exceeded loop recursion limit" after the real 40-deep cap. Fixed by letting both RALLY
         branches fall through normally (`POP`) so the sequence's own machinery closes the block,
         and branching on a pre-cleared `$RallyAnchor` register at the sequence's actual Last pin
         instead of adding a side-door exit.
      2. A second, unrelated mis-wiring introduced while manually simplifying `formation-hold.bsf`
         in the in-game editor (removing its now-redundant internal `sequence()`/`wait()` wrapper,
         found unnecessary once the caller's own per-tick `wait(1)` already provided the only
         throttle needed) — user-diagnosed and fixed directly; not a block-stack issue.
      `c_behavior:on_update`'s stepping loop (`components.lua`) confirms a dead/nil
      `state.counter` resolves via a synchronous `while not inst do ... end` retry, so a
      `sequence()` with only 2 of 4 stages wired is not itself defective — the leak was strictly
      from bypassing the block's own closing mechanism, not from stage count.

## `desynced_toolkit` / BSF infrastructure

### Node-id readability overhaul (user, 2026-07-20)

Motivated directly by the user being tired of instructions being referred to by the
compiler-assigned `n<pos>` id, which renumbers every time nodes serialize in a different
order (the exact instability behind `feedback_node_references_user_vocabulary` and
`feedback_resave_reencodes_unrelated_wiring`). Extends the "make node ids optional" bullet
under Local behavior-library storage in `todo.md` — that bullet holds the fuller motivation;
these are the concrete work items that came out of it. Terminology: "node id" is BSF's
`NODE_ID` token (`n27`), **not** the real `jump`/`label` instruction — this whole group is
about the per-node identity token, not computed dispatch.

- [x] **Make node ids optional — decompiler emits one only when a pin actually targets the
      node; parser/compiler accept id-less node lines.** Done 2026-07-20. `BsfNode.id_explicit`
      gates the `id:` prefix in `render_text.py`; `decompile.py` sets it to "is this node
      referenced" (shared `referenced_node_ids` helper) and renames referenced nodes to
      role-derived ids; `parse_text.py` accepts an id-less `op(...)` line, synthesizing a hidden
      `__nN` internal id (reserved prefix, rejected as an author id or branch target). Round-trips
      unaffected (compiled tables are position-derived). Covered by `test_bsf_optional_ids.py`.
      Original scope note below preserved. A node reached solely by positional
      fallthrough gets no id. Only genuine connection points (jump/branch/`>node` targets,
      `call`-target nodes, resolved `jump→label` destinations) get one. Minimizes diff churn
      (inserting/removing a fallthrough-only node renumbers nothing) and deliberately stops
      agents/users referring to instructions by an unstable id — most instructions won't have
      one, forcing references into the stable vocabulary (display name, `cmt`, enclosing
      `label` section). Touches `render_text.py` (suppress the id on non-targeted nodes),
      `parse_text.py` (accept a node line with no `NODE_ID:` prefix), and the grammar in
      `behavior_source_format.md`. Note: a node still needs a synthesizable internal identity
      even when id-less (for graph edges/IR) — only the *text surface* omits it.
- [x] **Warn (lint) when a declared node id has nothing pointing at it.** Done 2026-07-20.
      `lint.py` flags an `id_explicit` node that nothing references, with two exemptions: the
      Program Start entry node, and `label` nodes (a dispatch target by nature — decompile now
      always keeps a label's descriptive id for the same reason). The human-anchor interaction is
      resolved per the `cmt`-paragraph decision: human notes go through `cmt`, so the warning is
      unconditional (message points there). Also fixed a message-quality regression optional ids
      introduced across all lint rules — an id-less node is now described as "the `<op>()` at
      listing position N" instead of its meaningless synthesized `__nN`. Covered by two new tests
      in `test_bsf_validation.py`.
- [x] **Decompiler produces more descriptive ids than `n<line/pos>`.** Done 2026-07-20, in the
      same `decompile.py` pass as the optional-id item: `label` nodes → `label_<slug of Label>`,
      others → their op, occurrence-suffixed on collision (`test_bsf_optional_ids.py`). Still-open
      follow-up: fully wire-order-independent disambiguation, sequenced with the canonical-
      decompile item under Local behavior-library storage. Decision notes preserved below. Derive
      the emitted id from something durable and human-meaningful rather than wire position.
      **Decided
      2026-07-20 (user-confirmed): name a node after its own role, NOT after what jumps to
      it.** The user's first instinct was "shorthand describing what jumps there," but that
      reintroduces the churn this whole overhaul kills: (a) real behaviors have arbitrary
      control-flow fan-in, so a join point has no single incoming edge to name it after, and
      (b) naming a node after its predecessor's pin means editing the *predecessor* renames the
      *target* — instability relocated, not removed. Role-based naming instead reads best where
      ids are actually read most — the reference site: `>engage_target (If Larger)` explains
      itself and stays stable when the compare is edited. Scheme: op display name + short
      disambiguator, scoped by enclosing `label` section (`engage_target`, `search_scan`,
      `search_scan2`). **One special case that *is* stable "what jumps there": a real `label`
      node takes its id from its `Label` value** (`state_transport_route`) — for a label the
      dispatch key genuinely is its identity. The predecessor info the user wanted is still
      worth surfacing, but as a **back-reference annotation in `--annotate` mode** (`# ← If
      Larger from compare_dist`), computed fresh on render, never baked into the id. Hard
      requirement unchanged: ids must stay stable across the editor's untouched-node reordering
      (same durability the canonical-decompile item under Local behavior-library storage needs
      — sequence the two together). Remaining: the exact disambiguator/collision-suffix rule.
- [x] **Allow a BSF instruction to span multiple physical lines, terminated by `;`.** Done
      2026-07-20. `parse_text.py` groups physical lines into one logical node (`_consume_node`),
      terminating a multi-line node at a top-level `;` via a triple-quote/single-quote/comment/
      bracket-aware scanner (`_scan_delims`); single-line nodes stay bare and newline-terminated
      (backward compatible). Whitespace stays non-semantic (the parser never counts indentation).
      Multi-line-without-`;`, content-after-`;`, and unterminated quotes/parens are all hard
      errors. Wrapped arg lists and branch-notes-on-their-own-lines both work. Covered by
      `test_bsf_multiline.py`. **The id-on-its-own-line layout is also done (2026-07-20).** The
      decompiler now emits each id'd node's id on the line above its instruction (so bodies align
      at column 0, reading like assembly labels); the parser accepts both the own-line and the
      inline `id: op(...)` forms. The "open design question" flagged earlier — how a bare `foo:`
      line coexists with `label` sections — was a conflation (user): a `foo:` id-declaration line
      and a `label(...)` op are syntactically disjoint (`identifier:` vs `identifier(`), and the
      annotate "label section" is just cosmetic whitespace, so there was nothing to reconcile.
      Dangling/duplicate/id+inline declarations are parse errors. Covered by
      `test_bsf_optional_ids.py`. Original notes preserved. So a
      descriptive id can sit on its own line *above* the instruction while the instruction
      bodies still line up in a column (a long id no longer shoves its `op(...)` to the right),
      and a node's args/branch-notes/comment can wrap for readability. **Terminator decided
      2026-07-20 (user-confirmed): `;`, and its real job is to keep whitespace non-semantic.**
      The tempting alternative — significant indentation (Python-style, no terminator) — would
      give the layout directly but makes whitespace load-bearing, a bad trade for a format built
      for machine/agent editing and diffing; rejected. With `;`, the **parser scans for the
      terminator and never counts spaces**, so indentation and blank lines stay purely cosmetic
      (matches the grammar's existing promise that blank lines are non-structural) and the
      *renderer* does the column alignment. Rules to pin: (1) `;` is required **only** for a node
      that spans multiple lines or carries a `cmt` block — a node written entirely on one line
      stays bare and newline-terminated, so every existing file parses unchanged (backward
      compatible); (2) a missing `;` on a multi-line node is a hard parse error with a line
      number, not silent recovery (strict-by-design). Touches the `parse_text.py` tokenizer,
      `render_text.py` layout, and the grammar block in `behavior_source_format.md`.
- [x] **Give node comments (`cmt`) a first-class multi-line paragraph syntax.** Done 2026-07-20.
      `cmt` renders as a triple-quoted block under the node's branch notes (compact for a
      single-line body, expanded for multi-line), terminated by `;`; parse handles both plus the
      legacy inline `cmt="..."` form, and a body containing `"""` falls back to inline
      automatically. A `#`/`;` inside the body is literal content (the reason a block was chosen
      over `#`-lines). Covered by `test_bsf_multiline.py`. Original notes preserved. Every node can
      carry a `cmt`; in the in-game editor it renders as a paragraph *under* the node, wrapped to
      node width — BSF should let it be authored/rendered as a free-form paragraph too, not
      today's single-quoted `cmt="..."` hidden-field one-liner. **Hazard to avoid (design
      discussion 2026-07-20): do NOT use a `#`-prefix for this** — `#` already means a
      throwaway comment that is dropped on parse and never emitted, whereas `cmt` is *structural
      data* that round-trips to the wire and shows in-game; the two must stay visually distinct,
      so `#`-lines-as-cmt is out. **Decided 2026-07-20 (user-confirmed): extend the existing
      `cmt=` to a triple-quoted block** (`cmt="""…multi-line…"""`), kept **explicit** (the `cmt=`
      stays, so the field mapping is unambiguous — no bare `"""…"""`-block form), rendered under
      the node's branch notes and closed by the `;` terminator from the item above — lowest new
      concept (it's the same `cmt` arg, multiline), stays distinct from `#`, no significant
      whitespace. Rejected alternatives: heredoc (`cmt <<END … END`) — more robust to a comment
      literally containing `"""` but a whole new syntactic device, over-engineered for how rare
      that is; indented block — reintroduces semantic whitespace; bare `"""…"""` block with no
      `cmt=` — cleaner visually but loses the explicit field mapping a strict format wants.
      Resolves the "human-anchor node" open question in
      the warn-on-unreferenced-id item above: with real paragraph `cmt` available, human notes
      go through `cmt` and ids are reserved for genuine jump targets, so that lint warning can be
      unconditional.

**Mock world for behavior testing (`mock_world_spec.md`) — Phases 0-3.** Extend the
`Interpreter` with a populated, steppable environment so multi-unit behaviors (the combat
squad, `combat_squad_spec.md`) can be tested end-to-end. Scope of first version: sensing +
movement, not combat/damage (decided). Approach: world state in Lua tables (entities carry the
real `data.frames`/`data.components` def), Python-orchestrated; reuse the real instruction
funcs and `FilterEntity`/`PrepareFilterEntity`, mock only the engine-native leaves
(`Map.FindClosestEntity`, `comp:RequestStateMove`, `faction:IsSeen`, entity fields/methods).
Phases in the spec: **0** — load the Data package under the stub (biggest unknown, do first);
**1** — engine-native primitives in a new `world.lua`; **2** — extend the op dispatch for the
world instructions (also unblocks `library/hexat.dcs`'s unit-Origin path:
`value_type`/`get_location`/`modulo`); **3** — movement + multi-entity `MockWorld.step`. Phase 4
(combat) remains open — see `todo.md`.

- [x] **Phase 0 — load the Data registries under the stub.** Done 2026-07-18. `LupaEngine`
      now loads the real `utilities/values/items/components/frames` (the empirically-determined
      minimal include subset — the intervening `library/actions/biomes/behaviors/puzzles` aren't
      needed at load) before `instructions.lua`, and builds `data.all` (merge of
      values/items/components/frames, each def tagged `data_name`) exactly as the engine does
      post-load. `data.frames`, `data.components`, `data.items`, `data.values`, and `data.all`
      are populated, and `FilterEntity`/`PrepareFilterEntity` are live. Load is on by default
      (~29 ms, once per session fixture); `load_data_registries=False` keeps the bare
      instructions-only runtime. New engine-native stubs added: `FF_*`/`FRAMEREG_*` constants
      (FF_ layout self-consistent for PrepareFilterEntity↔mock MatchFilter, not engine-exact —
      documented why in `engine_stub.lua`), `TICKS_PER_SECOND`, `blight_threshold` in
      `Map.GetSettings`, empty `FactionAction`/`EntityAction`/`UIMsg`/`Delay` handler tables, a
      no-op `GetFactionBehaviorAsm`, and an auto-vivifying `data` table. Covered by new tests in
      `test_lua_runtime.py`; full suite green.
- [x] **Phase 1 — engine-native primitives in `world.lua`.** Done 2026-07-19. New
      `world.lua` (loaded after instructions.lua) supplies the mocked leaves: the entity registry
      with `Map.FindClosestEntity`/`GetDistance`/`GetEntitiesInRange`/`GetEntityAt`/`Defer`, the
      tile record + `GetPlateauDelta`/`GetBlightnessDelta`/`GetTileData`/`CountTiles`, and the
      Entity/Faction/Component metatables (frame+component register banks, `:MatchFilter`,
      `faction:IsSeen`/`IsVisible`/`GetTrust`/`GetPowerGridIndexAt`, `:GetLocationXY`/`CountItem`/
      `FindComponent`/`IsTouching`). Entity `.def` IS the real `data.frames`/`data.components`
      table. `MatchFilter` splits a real `PrepareFilterEntity` mask into frametype (low bits) +
      relative-faction (high bits) and agrees with it by construction; every finer type/faction
      discrimination still bottoms out in the reused `FilterEntity`. Python facade
      `desynced_toolkit.MockWorld` (spawn/add_component/faction/set_trust/set_tile + direct
      sensing helpers); `World.Reset()` on construction isolates instances on the session engine.
      `test_mock_world.py` covers the primitives *and* an end-to-end run of the unmodified real
      `get_closest_entity` func over the mock (returns the right nearest enemy, skipping friendly/
      out-of-range) — the proof the mocked surface satisfies a real func's contract. Distance
      model mostly settled 2026-07-19 (see `mock_world_spec.md`'s distance-metrics item, pinned
      by tests): "closest" selection is Euclidean and `Map.GetDistance` is the unobstructed
      grid path length / octile (both user-observed in-game); range *gates* are floored
      Euclidean (settled by the in-game `range_probe.bsf` run, 2026-07-19 — see the RangeProbe
      item below). Remaining modeling choices flagged in `world.lua`:
      vision is Euclidean "within any own entity's visibility_range" (bubble shape unverified);
      readout rounding rule unverified; no power-grid/base_id-family model yet.
- [x] **Phase 2 — extend the interpreter op dispatch.** Done 2026-07-19. Replaced the
      `interpreter.py` `else: raise` with a **metadata-driven generic dispatcher**: it reads each
      op's real `data.instructions[op].args` directions (in/out/exec), marshals the positional args
      (value args → mem slots / nil; exec args → raw 1-based branch targets / False, omitted →
      next node — the same 3-way rule `check_number`'s hand arm uses), prepends any hidden
      `make_asm` arg (the `c` field — domove's Sync/Async, bitwise_op's op, for_signal_match's
      mode; reuses the real `make_asm` for the default), calls the genuine func, and resolves its
      `state.counter` branch decision uniformly. Covers get_location/get_distance/get_health/
      get_closest_entity/read_signal/set_comp_reg/get_comp_reg/value_type/match/check_bit/
      bitwise_op/domove/… in one arm. The two **block-producing sensing loops**
      (for_entities_in_range/for_signal_match) get a shared `_enter_block_loop` mirroring
      `_enter_for_number`, but the real `func` builds the iterator via real
      `Map.FindClosestEntity`/`GetEntitiesWithRegister` + `FilterEntity`; since their `BeginBlock`
      is a file-local alias for the real `InstBeginBlock` block-stack driver (which the Python
      interpreter deliberately doesn't use — see the InstBeginBlock item below), `LupaEngine`
      repoints that one shared upvalue cell to a `MockBeginBlock` stub (via `debug.setupvalue`)
      that just returns the iterator, letting the Python block driver run `.next`/`.last`.
      `Interpreter` gained an optional `comp=` param so a MockWorld component (comp.owner = a real
      mock entity) can back the sensing ops. Tests: `test_mock_world_dispatch.py` (get_location,
      get_closest_entity, read_signal, match exec-branch, value_type, both loops) + the spec's
      explicit payoff `test_hexat_unit_origin_runs_via_mock_world` in `test_bsf_end_to_end.py`
      (deployed `library/hexat.dcs`'s value_type→get_location Unit path, previously unrunnable).
      Full suite green. *(The MockBeginBlock upvalue patch described here was retired the next
      day when Phase 3 adopted the real block-stack driver outright.)*
- [x] **Phase 3 — movement + multi-entity stepping.** Done 2026-07-19, with a user-chosen
      scope expansion: the golden fixture needs `call`, and rather than teach the Python tier
      call frames, the whole simulated tier was replaced by the **real machinery** (see the
      InstBeginBlock item below, closed the same day). Movement in `world.lua` (per-rule
      provenance in its movement-section header): integer tiles + fractional internal progress
      at `movement_speed/TICKS_PER_SECOND` per tick, √2 per diagonal step, diagonal-first-
      then-straight direction (read off the golden log), no pathfinding (blocked step ⇒
      `repeat_blocked`/Path Blocked pin, flagged), arrival gate
      (`get_distance ≤ range`, floored at 1 for entity targets) confirmed in-game by the
      ArrivalProbe run (see below),
      `@goto` as persistent native move-to, ground occupancy shared with `Map.CountTiles`
      (flyers stack/overfly), frame-derived `flying` bit. `MockWorld`: `attach_behavior`
      (accepts table or raw `.dcs`), `step(n)` = tick++ → behaviors → movement → deferred,
      `prints` capture stream (tick+entity attributed, values snapshotted — storing live
      register boxes was a real bug this work caught). **Acceptance test green**
      (`test_movement_circuit_golden.py`): exact 56/56 tile sequence, deltas ±1 (±2 only on
      direction-change steps), 4 of 5 legs tick-exact, total 157+3 decomposed in the test
      docstring. Unit tests in `test_mock_world_movement.py`.
- [x] **Movement-rate model measured in-game.** Done 2026-07-18: an Engineer walked a
      closed `HexAt`-corner circuit (R=1, d_half=5) under a logging behavior printing each
      location change with a Simulation Tick stamp. Pins Phase 3's per-tick advance: sub-tile
      progress accumulates along the *Euclidean* path (a diagonal step costs ≈√2 — the mock
      must step diagonally, never axis-by-axis), movement is 8-connected single-tile teleports
      (integer coords only, instrument-confirmed), base `movement_speed` reproduced within 1%
      (63.3 tiles / 157 ticks → 2.02 tiles/s vs. def 2), and `TICKS_PER_SECOND = 5` confirmed
      by wall clock. Results in `mock_world_spec.md` (tick-step note) and the
      `reference_movement_speed_model` memory. Still unmeasured: `need_move`'s arrival
      radius / `range` tolerance (this test re-issued moves itself on exact tile match, so it
      deliberately couldn't observe it). The behavior + real log are checked in as
      `tests/data/movement_circuit_test.dcs` / `movement_circuit_test_ingame.log` — designated
      (user, 2026-07-18) as Phase 3's golden differential fixture: the mock must reproduce the
      real log's tile sequence and tick totals from the same `.dcs` (details in
      `mock_world_spec.md`, Phase 3).
- [x] **Run the ArrivalProbe in-game to settle the sync-move arrival tolerance.** Done
      2026-07-20: `tests/data/arrival_probe.bsf` run with a 2x2 Command Center as the entity
      target. The measured log (`tests/data/arrival_probe_ingame.log`) **confirms the model** —
      arrived ⟺ `get_distance ≤ range`, entity targets floored at 1: coordinate cases read 0/2/5,
      entity cases 1/2/5 (range 0 floored to 1). No change to `world.lua`'s
      `arrival_tolerance`/`arrived` was needed. `test_arrival_probe.py` is now a golden
      differential (coordinate cases match the log tile-for-tile; entity cases match its arrival
      gate — the stop tile diverges only because the mock approaches a point target where the game
      approached a 2x2 footprint, the pre-flagged no-pathfinding divergence). Settled
      `mock_world_spec.md`'s last open movement item; the squad RALLY gate is unblocked.
- [x] **Run the RangeProbe in-game to settle the range-gate metric.** Done 2026-07-19, same
      day: measured minimal detecting ranges (3,0)=3, (2,2)=2, (3,2)=3, (3,3)=4, (4,3)=5,
      (6,3)=6 — **floored Euclidean** exactly (in range R ⟺ floor(dist) ≤ R); Chebyshev,
      floored-octile, and round/ceil Euclidean each contradicted by at least one row. The
      magnifier's 5×5 square at range 2 is the floor artifact of this circular gate at small
      radius. Follow-up report closed the `@store` question too: **the `get_distance` readouts
      were identical to the minimal detecting ranges at every offset** — so gate and readout are
      one function, `get_distance` = floor(straight-line Euclidean), and the (6,3)=6 row refuted
      the interim "unobstructed path length" model (octile ≈ 7.24 would have read 7). `world.lua`
      (one distance function now), the pinned tests (both probe columns are in-game golden
      values), `mock_world_spec.md`, `blight_magnifier_mining.md`, and the
      `reference_distance_metrics` memory all updated.
- [x] **Reuse the real `InstBeginBlock`/`GetFactionBehaviorAsm` in `interpreter.py`.** Done
      2026-07-19, folded into mock-world Phase 3 (user chose this over Python-simulated `call`
      frames when the golden fixture forced the question): the real `data/library.lua` now loads
      with the Data registries (before components.lua/instructions.lua — both capture load-time
      local aliases of these globals), behaviors install through the real `UploadBehavior`
      (dependency unpack with `call.sub` remapping, content-hash dedup into
      `faction.extra_data.library`, `SetBehavior` state init — parameters are component
      registers, the real `state.stk` model), and execution is `behavior_runtime.lua`'s port of
      the `c_behavior:on_update` dispatch loop delegating every dead end to the real
      `c_behavior_on_end` (extracted from the real function's upvalue). The whole simulated tier
      — per-instruction arg translation, Python block stack, `Memory` slot allocation for
      programs, the `CurrentAsm`/`MockBeginBlock` shims — is gone; `Interpreter` is now
      activation scheduling only. `call` works for the first time (by-reference params, shared
      arrays, depth cap — pinned in `test_interpreter_call.py`), and `wait`'s sleep semantics
      were corrected off the dispatcher's own source (sleep N = resume N ticks later; the old
      model was off by one). One deliberate harness deviation retained and documented: top-level
      fall-off halts ("restart") instead of looping forever.
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

### Library storage converted to BSF text (user, 2026-07-22)

Second, independent motivator for BSF beyond by-reference subs (see the still-open bullet
under Local behavior-library storage in `todo.md`): a checked-in `.dcs` is a single base62
line, so `git diff` on a re-export is meaningless. The node-id readability overhaul above
already made decompile output stable/reviewable, so no further BSF-pipeline work was needed
to act on it — this was a straight storage-format conversion.

- [x] **Convert `library/*.dcs` to `library/*.bsf`.** Done 2026-07-22: every type-`C` behavior
      batch-decompiled via the existing `desynced-bsf decompile` CLI, verified round-trip-clean
      via `semantic-diff` against the original `.dcs` (only diffs were `\r\n`→`\n` normalization
      inside multi-line `cmt` text, pre-existing pipeline behavior unrelated to this change), then
      the `.dcs` files removed. `magnifier_lattice` stays `.dcs` (blueprint, wire type `'B'`, not
      BSF-decompilable). `tests/test_library_behaviors.py` updated to `parse_behavior` the `.bsf`
      files directly instead of `decompile_dcs`-ing raw `.dcs`. New workflow: in-game edit → copy
      → `desynced-bsf decompile` → overwrite `.bsf` (readable diff); to push a `.bsf` back into
      the game, `desynced-bsf compile` → paste. **Explicit, deliberate tradeoff (user decision):**
      compiling resets the editor's hand-arranged node layout (`nx`/`ny` isn't modeled in BSF —
      the "BSF envelope/sidecar layer" item), so this is BSF-only storage, not a
      layout-preserving dual `.dcs`+`.bsf` sidecar. Considered and rejected: keeping `.dcs` as
      the lossless source of truth with a generated `.bsf` sidecar (avoids layout loss entirely,
      but two files to keep in sync, and the `.dcs` diff stays opaque in `git log`/GitHub even
      though the sidecar one is readable); a `.gitattributes` `textconv` driver alone (display-only,
      doesn't produce an on-disk reviewable file, which is what was asked for).

### Local behavior-library storage: by-reference `library/` store (user, 2026-07-22)

Immediately superseded the previous entry's flat-inline BSF conversion: the user's actual intent
was the fuller idea already scoped under Local behavior-library storage in `todo.md` — a
`blz.desynced_toolkit.bsf` change providing real import/export CLI tooling, not just a one-time
storage-format swap. Delivered in the toolkit repo first (`bsf/library.py`, a new `sub NAME from
"path.bsf"` grammar in `parse_text.py`/`render_text.py`, `desynced-bsf import`/`export`
subcommands — see that repo's own history for the design), then applied here by reconstructing
`library/` from the original `.dcs` exports (recovered from git history, since the flat-BSF
conversion had already deleted them) via the new `import` command instead of a straight decompile.

- [x] **Reconstruct `library/` as a by-reference store.** Every original `.dcs` re-imported in
      ascending file-mtime order (oldest export first), so a later, fresher re-export of a shared
      sub naturally wins any conflict — the same resolution a human would reach by eye. Found a
      real, previously-invisible bug in the *checked-in data itself* this way: `observer.dcs`
      (exported 2026-07-14 03:30) embeds an `Async Radar Set`/`Async Radar Get` copy that is
      genuinely stale relative to `mining_leader.dcs` (2026-07-18) and the standalone
      `async-radar-get.dcs`/`async-radar-set.dcs` exports (2026-07-14 04:13, ~43 minutes after
      Observer's) — both agree on `c_portable_radar[num=5]` and an improved `desc`, while only
      Observer's checked-in copy still has `num=2` and the older, shorter `desc`. Reimporting in
      chronological order picked the correct (num=5, current) content automatically, and
      `import`'s stale-caller warning flagged `observer.bsf`'s reference so this was visible
      rather than silently overwritten in either direction. **Open question this raises for
      `todo.md`'s Observer redesign section:** its `Async Radar Set` cached-radar-period item
      frames `num=5` as a *future* workaround "after the next game update, if [the underlying bug
      is] not [fixed]" — but the num=5 content already existed as of 2026-07-14 04:13 and was
      still current as of 2026-07-18, which reads as the workaround already having been applied
      live, ahead of that todo item's own framing. Not resolved here (needs the user to confirm
      what's actually live/intended) — flagged rather than silently rewritten.
- [x] **Found and fixed a real bug in `blz.desynced_toolkit.bsf.library.import_dcs` while doing
      this reconstruction**: its stale-caller scan skipped the current import's own top-level
      output path, on the assumption a top-level import target is never also referenced as
      someone else's sub. False for exactly the `Async Radar Set`/`Get` shape — each is
      independently useful standalone (hence its own top-level import) *and* a shared sub of
      Observer/Mining Leader. Fixed in the toolkit repo (removed the skip; a file excluding itself
      via the existing `exclude` set was already sufficient), with a regression test
      (`test_reimporting_a_standalone_behavior_flags_callers_that_reference_it`) built directly
      from this real scenario.
- [x] **Filenames**: every top-level import kept its pre-existing filename stem via `--name`
      (`mining_leader`, `hauler`, etc.) rather than the tool's own default (slugging the
      behavior's *declared* name, which would have produced churn-prone, version-string-bearing
      names like `mining-leader-v4-0.bsf` every time the in-game "V4.0" label changes). Newly
      split-out sub files (`async-transit.bsf`, `check-emergency.bsf`, `check-avoidance.bsf`) kept
      the tool's default naming since there was no prior convention to preserve. **Reversed
      2026-07-22 (user)**: this was a unilateral tooling choice, not a user decision, and the user
      rejected it once surfaced — `mining_leader.bsf`/`mining_follower.bsf`/`hauler.bsf` were
      re-imported without `--name`, landing on the tool's default slugged names
      (`mining-leader-v4-0.bsf`, `mining-follower-v2-0.bsf`, `fendersons-transport-v2-0.bsf`); the
      stem-preserving pair `miner_drone.bsf`/`magnifier_signal.bsf` (left over from an import that
      ran without `--name` alongside the already-present stem-named file) was removed in favor of
      the default-named `minerdrone.bsf`/`magnifiersignal.bsf`. Current convention: let the import
      tool's default naming stand.
- [x] **`tests/test_library_behaviors.py` updated** for the reference grammar: both
      `parse_behavior` calls now pass `base_dir=LIBRARY_DIR` so `observer.bsf`/`mining_leader.bsf`'s
      `from` references resolve; the lint test still runs (unchanged in spirit) over every
      `*.bsf` file, referenced-elsewhere or not, since each remains an independently valid
      `behavior NAME(...):` document.

## Repository split & `blz` namespacing

- [x] **Split this repo into a shareable toolkit and a me-specific repo, and rename the toolkit
      under the `blz` namespace** (user, 2026-07-16; done 2026-07-22). Now two repos:
      - *Shareable* — `../blz-desynced-toolkit/` (`blz-desynced-toolkit` package, importable as
        `blz.desynced_toolkit`): the wire codec, BSF pipeline, Lua-backed interpreter/runtime,
        its full test suite (`tests/`, `tests/data/`), and the format/spec docs moved into that
        repo's `docs/` subdirectory (`behavior_format.md`, `behavior_source_format.md`,
        `instructions_index.md`, `mock_world_spec.md`). Has its own `CLAUDE.md`.
      - *Me-specific* — this repo, now holding only `library/`, the corpus tooling (`scripts/`,
        `corpus/`), the personal design docs (`hex_expansion_math.md`, `observer_redesign.md`,
        `blight_magnifier_mining.md`, `combat_squad_spec.md`), and a slim `tests/` exercising
        `library/` behaviors against the toolkit dependency (the two tests that read `library/`
        moved out of the toolkit's test files into `tests/test_library_behaviors.py` here).
      Namespace-packaged under `blz` per the user's PEP 420 namespace-package convention
      (`pyproject.toml`'s `[tool.uv.build-backend] module-name = "blz.desynced_toolkit"`, no
      `__init__.py` in `src/blz/`); `python -m desynced_toolkit.bsf` → `python -m
      blz.desynced_toolkit.bsf`, all internal imports and CLAUDE.md updated in both repos.
      **Open design decision, resolved:** dependency mechanism is a plain `tool.uv.sources` local
      path dependency (`{ path = "../blz-desynced-toolkit", editable = true }`) — not a submodule,
      matching the sibling-directory convention already used for `desynced-game-data`. Both
      repos' test suites pass post-split; the CLI (`python -m blz.desynced_toolkit.bsf`) verified
      working from both repos. Both repos are separate git repos now (`blz-desynced-toolkit`
      freshly `git init`'d) with GitLab remotes added.

## Dev tooling

- [x] **Set up `ruff` (format + lint) and `mypy` (type checking) for `blz.desynced_toolkit`**
      (done 2026-07-22, in `../blz-desynced-toolkit/`). Both added as dev dependencies with
      checked-in config (`pyproject.toml`'s `[tool.ruff]`/`[tool.mypy]`); `ruff check`/`ruff
      format`/`mypy` all clean, 633 tests still pass. `mypy` needed `explicit_package_bases`
      + `mypy_path = "src"` to resolve the `blz` namespace package (otherwise a false "Source
      file found twice under different module names" error) and `ignore_missing_imports` for
      `lupa.*` (compiled extension, no stubs). Real findings fixed: an `F821 undefined name
      'lupa'` (missing import, not `TYPE_CHECKING` — this project's convention is an
      unconditional `import lupa.lua54 as lupa`, matching every other module), a handful of
      loop-variable-reuse-across-different-typed-loops mypy false positives (renamed vars), and
      one genuine `int|float` -> `int` narrowing bug in `values.py`'s `from_lua`.
      **Not done:** `scripts/analyze_corpus.py` and the rest of this (me-specific) repo's own
      `scripts/`/`tests/` — this pass only covered the toolkit repo; the placeholder-less
      f-string finding originally noted for `analyze_corpus.py` is still live here if this repo
      ever gets the same treatment.
