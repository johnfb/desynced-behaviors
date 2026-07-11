# Outstanding work

Plain checked-in todo list (preferred over the CLI's session-scoped Task tool, which is
stored under `~/.claude/tasks/<session-id>/` and isn't visible from a different session).
Update this file directly as items are picked up/finished.

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
- [ ] **Tune the hardcoded oversubscription cap (2) and floor (100) in `MinerDrone`**
      empirically once it's actually running — currently just reasonable-guess constants, not
      derived.
- [ ] **(Idea, not started) Mining Leader/Foreman for slot-less Human Miner Mechs.** User idea
      2026-07-11: Human Miner Mechs have no Internal socket for a behavior controller, so they
      can't run a `MinerDrone`-style Program of their own. Mechanism now grounded in source
      (`instructions.lua:302`, `GetAdjacentFactionEntityOrSelf`): `set_reg_remotely`/
      `get_reg_remotely` normally require the target to be physically touching, *except* when the
      calling component's `def.key == "autobase"` — that branch instead only requires the same
      `GetPowerGridIndexAt` grid index on both ends, no adjacency at all. `c_autobase`
      (`components.lua:4116`) *is* the "AI Behavior Controller" component (Internal, alien tech).
      So: a small structure/unit fitted with an AI Behavior Controller plus a Power Field
      (`c_power_relay`, `components.lua:1007`) extending grid coverage to a squad of Human Miner
      Mechs could run a Program that scans idle mechs on the same grid and remotely writes mining
      targets into their registers via `set_reg_remotely` — no physical adjacency needed, only
      shared grid membership. Not designed in detail or built — just confirmed mechanically
      plausible.

## Combat Squad (`combat_squad_spec.md`)

- [ ] **Rewrite the Beacon/Scout/Gunner/Support pseudocode (§5) directly in real BSF syntax.**
      Currently a hand-invented, Python-like pseudocode (`loop:`/`->`/`goto loop`), not the
      actual `behavior_source_format.md` grammar — same category of rewrite as the
      `hex_expansion_math.md` item below.
- [ ] **Implement Scout, Gunner, and Support as real, compiled `.dcs` behaviors.** Only Beacon
      has an actual implementation so far (`beacon.dcs`/`beacon2.dcs`, hand-authored via
      `instructions_index.md` + `behavior_format.md`) — the other three roles are still
      spec-only pseudocode.
- [ ] **Test `beacon.dcs`/`beacon2.dcs` in-game.** Round-trip-verified against the codec, but
      per `CLAUDE.md`'s own note, "Not yet tested in-game."
- [x] **Confirm the §2.4 self-healing anchor lookup assumption empirically.** Confirmed
      2026-07-11: `for_entities_in_range` scan of a single resource node returned `Result=1`
      before depletion, `Result=0` on an identical rescan right after the node was mined to
      exactly 0 — destroyed/depleted entities really do drop out of faction-wide scans.
- [ ] **(Future extension, explicitly out of scope so far)**: grow the Beacon into a
      multi-slot `c_autobase` building that auto-produces/replenishes squad units, taking
      advantage of `c_autobase`'s exemption from the ordinary remote-write adjacency
      restriction to push orders/equipment directly to squad members instead of only
      broadcasting over Radio.

## Hex Expansion (`hex_expansion_math.md`)

- [ ] **Rewrite the compiled `HexIndexOf` directly in BSF**, retiring its current
      `ast_compiler.py`-based Python-like-pseudocode compilation path — explicitly flagged as
      separate, later, not-yet-started follow-on work in both `CLAUDE.md` and
      `behavior_source_format.md`. (`ast_compiler.py` itself is slated for retirement in favor
      of BSF and shouldn't be used as a design reference for this, only possibly as a test
      oracle.)
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
      but the block-stack driving itself (`sequence`/`for_number`) and the compiler frontend
      are not. (Separate from the `ast_compiler.py`-to-BSF retirement above — this is about
      `interpreter.py`'s own runtime fidelity, which isn't going away.)
- [ ] **Add automated test coverage for the corpus/analysis scripts** (`scripts/
      collect_clipboard_corpus.py`, `collect_steam_forum.py`, `analyze_corpus.py`,
      `render_examples.py`). Currently exercised only by direct manual runs and one real live
      edit — not covered by `uv run pytest tests/` at all, a gap explicitly flagged in
      `CLAUDE.md` as "worth closing before relying on them for more than ad hoc use."
- [ ] **Require explicit pin wiring in BSF text for any op with 2+ declared exec pins** (user
      idea, 2026-07-11, prompted by hitting the loop-`Done`-omission bug twice in one session —
      see `feedback_bsf_loop_done_pin_omission` memory). Currently an omitted pin silently means
      "physically next," which is safe/unambiguous for a single-pin op but easy to get wrong for
      a multi-pin one (forgetting a second pin exists because the first one is visible and looks
      complete). Proposed design: for any op with only one exec pin, keep today's behavior
      unchanged (omission still fine, matches how `render_mermaid.py` already only bothers
      labeling a pin when there's more than one). For any op with 2+ exec pins, require every one
      of them to be explicitly written as one of `POP` / a label / a new `NEXT` token (meaning
      "physically next in this behavior's own `order`," spelled out instead of invisible).
      Touches `render_node`/`parse_node` (a new `NEXT` token in the parser) — real grammar
      change, not a wire-format change (the wire keeps its own compact-encoding omission
      regardless, per the earlier "Node identity vs. wire position" decision). Breaks every
      existing fixture's expected text in `test_bsf_text_roundtrip.py` (mechanically fixable,
      but every test string changes). Not started — deliberately deferred to keep focus on the
      ambiguity-survey work in progress.
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
      checked-in `ruff` config, and decide on `mypy` strictness.

## Tooling / cosmetic, low priority

- [ ] **Add zoom/pan support for large Mermaid graph renders.** Large behavior graphs render
      too small to read comfortably in an Artifact or static SVG. Not blocking current work.
- [ ] **Re-render Mining Leader's component-split diagrams with real `mmdc` output** instead of
      the earlier hand-built SVG approximation (see `feedback_use_real_mermaid_not_handbuilt_svg`
      memory for why that approximation happened in the first place). Offered previously, no
      answer yet on whether it's wanted.
