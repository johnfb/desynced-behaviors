# Outstanding work

Plain checked-in todo list (preferred over the CLI's session-scoped Task tool, which is
stored under `~/.claude/tasks/<session-id>/` and isn't visible from a different session).
Update this file directly as items are picked up/finished.

## Mining Leader / Follower review

- [ ] **Fix `$Offset` reset asymmetry in Miner Follower V2.0's `v_arrow_down` empty-signal
      path.** At `n30` (`is_empty($Signal)`), only the "Has Value" branch (→n32) clears
      `$Offset` before entering `v_moving`. The implicit "Empty" fallthrough goes straight to
      `n31` and reuses a stale `$Offset` instead of rolling a fresh one — same underlying bug
      as the one already fixed in `v_resource`'s failure path (`n49`), just not applied to this
      rarer trigger.
- [ ] **Add a proactive leash-distance check before committing a candidate in `v_resource`.**
      `n46-50` accepts whatever `get_closest_entity(Filter=$Signal)` returns and commits
      immediately, with no `get_distance(Target=Target, Source=Forman, ...)` check against
      `Max Range` first. The reactive per-tick check in `Begin` (`n13-14`) still eventually
      catches an out-of-leash pick, but only after the follower has already started walking
      toward it.
- [ ] **Confirm intentionality of the Equal-case merge in `v_arrow_down`'s Max-Range check.**
      Original `Miner V1.3.4`'s `n31` wired `If Smaller` and `If Equal` to different targets
      (Equal got its own signal-tolerance approach). `Mining Follower V2.0`'s `n28` only wires
      `If Smaller` — Equal now falls through with Larger to the same flat-tolerance approach.
      Likely a harmless cleanup; confirm rather than assume.
- [ ] **Wire the Async Radar sub into Mining Leader V3.2.** Design-complete and confirmed
      working (register-4 fix, State/NextState mechanism) but never actually swapped in — the
      whole motivation for building it was to fix the Search state's blocking-during-`scan`
      problem.
- [ ] **Review the Mining Hauler behavior.** User said they'd share it as a third reference
      example alongside Leader/Follower; deferred to focus on leader/follower first, never
      actually pasted. Blocked on the user providing the `.dcs`.

## Magnifier / drone-swarm design (root task, not started)

- [ ] **Update `MinerDrone` with a second parameter** (which resource to mine + which signal
      to watch), building on the existing register-linked design in
      `blight_magnifier_mining.md`.
- [ ] **Author the `MagnifierSignal` building behavior** — broadcast "come mine here" (the
      `num=0` serving convention) when any node in range is below the 200 cap, turn itself off
      via `shutdown`/`turnon` when all nodes are full (mechanism already verified against
      source: toggling the whole building's power stops the magnifier's own regen without
      affecting the Behavior Controller).
- [ ] **Compile/validate `MinerDrone` against real Lua.** Still only hand-authored directly
      against `behavior_source_format.md`'s grammar (per the doc's own "Known gaps" section) —
      never run through `desynced_toolkit`'s own compile/decode pipeline, round-tripped through
      `dcs_wire.py`, or tested in-game.
- [ ] **Integrate `MinerDrone` with an outer building-selection/travel routine.** It currently
      only handles "given you're already in a good area, pick and mine nodes there" — not
      *which* area to travel to first. Intended integration point (per `blight_magnifier_mining.md`):
      building-side Signal broadcast, drones pick among currently-signaling buildings and
      travel there before running the existing procedure.
- [ ] **Tune the hardcoded oversubscription cap (2) and floor (100) in `MinerDrone`**
      empirically once it's actually running — currently just reasonable-guess constants, not
      derived.

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
- [ ] **Confirm the §2.4 self-healing anchor lookup assumption empirically.** Assumes destroyed
      entities drop out of `GetEntitiesWithRegister` queries the same way they drop out of
      `Loop Units (Range)` — consistent with how every other faction-wide query in this
      codebase behaves, but not directly observed in a running game yet.
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
- [ ] **Investigate `@goto`'s "transport route" option semantics.** User noted `@goto` has
      additional behavior when this option is enabled on the target; not yet investigated,
      flagged for later if it becomes relevant.

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
