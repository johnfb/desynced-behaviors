# Combat Squad — Design Spec (v2: Captain architecture)

**Supersedes the v1 Beacon/Scout/Gunner/Support design** (2026-07-14; v1 and its
`beacon.dcs`/`beacon2.dcs` implementations are git history — see "Lineage" at the end). Note
on filenames throughout this doc: `library/` was converted from raw `.dcs` to a by-reference
`.bsf` text store on 2026-07-22 (see the toolkit's own `CLAUDE.md`/this repo's `history.md`),
so every `library/*.dcs` reference below now resolves to the same-stem `.bsf` file.
Redesigned from real in-game squad experiments: v1 squads **scattered and trickled into
fights one at a time**, taking heavy damage and long fights against targets they should have
deleted, and coordination only worked when the coordinator personally had visual range on the
engagement. §1 grounds *why* in engine source — eyes-on is a hard mechanical requirement, not
a preference — and the rest of the design follows from it.

## 1. Design foundation

### 1.1 The visibility lock (the load-bearing engine fact)

A weapon component (`c_turret` family, `components.lua` `c_turret:on_update`) takes a
**manual target in its own register 1**, and that register is a rich command channel:

| Register 1 holds | Weapon behavior |
|---|---|
| entity | manual priority target; the unit also **pursues it** (`RequestStateMove` toward it, even while shooting something else in range) — and this pursuit **overrides `@goto`** (live-confirmed): an armed unit does not move on GOTO until its weapon register is cleared |
| coordinate (+ `num`) | attack-move to that point, `num` = approach radius |
| `v_powereddown` | hold fire (also clears the weapon's own register 2) |
| `v_lock_locked` | **Hold Position**: locks movement in place, auto-acquire keeps firing — a firing-line mode, not a kiting one |
| id (+ `num == REG_NOT`) | auto-acquire preference filter (inverted when `REG_NOT`) |

But the manual target only takes effect through this gate:

```lua
if manual_target and owner:IsInRangeOf(manual_target, search_radius) then
    if owner.faction:IsVisible(manual_target) then
        attack_target = manual_target
```

**A manual target becomes the actual attack target only while the faction can *see* it.**
Without faction vision on the target, every gunner silently falls back to individual
auto-acquire — each locks whatever wanders into its own trigger radius, which is exactly the
scatter-and-trickle failure observed. So the squad brain's first job is not target selection;
it is **maintaining the vision lock** that makes coordinated targeting exist at all.

### 1.2 The two design rules that follow

1. **The Captain personally watches the fight** from standoff: visibility 40 (equal to the
   Small Radar's `range = 40` scan distance, but continuous and passive), keeping ≥30 from
   all enemies — a 10-tile sensing margin, using the same `moveaway_range` standoff idiom
   Observer already proved.
2. **Nobody advances until the squad is assembled** (the rally gate, §4). Arrival
   synchronization is enforced by an explicit gate, never assumed from pathfinding.

## 2. Composition & loadouts

| Role | Frame | Fit | Notes |
|---|---|---|---|
| **Captain** (1) | Mark V (`f_bot_1m_c`: base vis 15, speed 5, 600 HP) | Medium Visibility Module (+15) + 2× Internal Visibility Module (+5 each) → **vis 40 exactly** | Unarmed by default; every remaining socket free for speed/armor |
| **Gunners** | Mark V or Hauler (`f_bot_1m_b`: speed 4, 350 HP); optionally a tank frame or two | weapons + Portable Shield Generators | Shield generators (`c_shield_generator`/`c_shield_generator2`) are **Internal** — tank frames trade shield capacity for hull, hence "a couple at most" |
| **Healers** | Hauler or Mark V | AOE Repair Component (`c_repairer_aoe`, Medium socket) | AOE repair works passively in radius — the behavior is mostly positioning |
| **Power providers** | Large Tank Frame (`f_human_large_tankframe`: 1400 HP, speed 4, 1 Large + 2 Internal sockets — human tech) | Large Power Field (`c_large_power_relay`, Large socket, unlocked by `t_power_units`) + Micro Reactor (`c_micro_reactor`, Internal, fuel-rod powered) + Behavior Controller (`c_behavior`, Internal) — both Internals spoken for | **Human frame, so no integrated controller** (integrated behavior controllers are robot-race only: `frame_def.race == "robot"` in the engine's own check — human and alien frames always need an explicit `c_behavior`). Speed 4 matches Hauler gunners — won't drag the rally gate |

Visibility modules stack additively onto the frame's base `visibility_range`
(`SumModuleBoosts(owner, "c_modulevisibility", ...)`), so the Captain loadout above is exact,
and alternative combinations reaching ≥40 are equivalent.

**Fuel logistics**: power providers monitor their fuel-rod inventory and broadcast a delivery
demand using the established hauler convention (signal id = the fuel item, `num > 0` = wants
delivery) — served by the already-deployed Fendersons Transport with no changes.

## 3. Membership & command protocol

Both directions run over Signal registers; the "radio channel" **is the Captain entity
itself**.

- **Membership (member → Captain)**: every squad member statically sets its own `@signal` to
  the Captain entity (done once by the member's own behavior, from its `Captain` parameter).
  The Captain enumerates its live squad fresh every pass with
  `for_signal_match(Signal = <self>)` — the retained v1 mechanism: no stored roster, no
  anchor to die; destroyed members drop out of the scan natively (confirmed in-game:
  destroyed/depleted entities vanish from faction-wide queries). Matching *by* the entity is
  deliberate exact-entity matching — the fallback-match hazard from the hauler work applies
  to id-based matching accidentally hitting embedded entities, not to this.
  Multi-squad separation is free by construction: each squad's channel is its own Captain.
  **The beacon's `num` is a bitfield** carried alongside the entity (num coexists with the
  entity — composite semantics), maintained with `bitwise_op` (which preserves the entity part:
  it copies the register and overwrites only `num`):

  | Bit | Value | Meaning | Set when | Cleared when |
  |---|---|---|---|---|
  | 1 | 1 | **Contact** — enemy in this member's visual range | member sees any enemy | member sees none |
  | 2 | 2 | **Retreat latch** — member is disengaging | retreat condition first trips (low battery / hull damage) | back to full health |

  The bitfield replaced an earlier plain `num=1` contact flag once the retreat latch (bit 2)
  was added: a member retreating *while still in contact* broadcasts `num = 3`, which an
  exact-num match on `1` would silently reject — losing exactly the reports that matter most.
  So the Captain **must not** filter on `num`. It enumerates members with plain Match mode
  (`for_signal_match`, `c=1`, num ignored) and tests the relevant bit per member with
  `check_bit` (1-based: bit 1 = value 1, bit 2 = value 2; clearing bit *N* is `AND 15−2^(N−1)`,
  i.e. `AND 14` / `AND 13` for a two-bit field — **not** `16−N`, an off-by-one that looks
  plausible for two bits). Because Match writes the loop's Unit output on *every* iteration
  before the bit test runs, "found a member with this bit" needs a **separate found-flag**
  written only inside the bit-set branch and pre-cleared before the loop — reusing the loop's
  Unit register as the found indicator reports the last member scanned, never "none."
- **Command (Captain → members)**: the Captain's own `@signal` is the single command
  register. Members read it directly at any range with `read_signal(Unit = Captain)`
  (`data.instructions.read_signal`, works on any owned unit). One value, dispatched by
  `value_type`:

| Captain's `@signal` | Meaning | Member response |
|---|---|---|
| **enemy** entity | **ENGAGE** | write it into own weapon component register 1 (`set_comp_reg`) → native focus fire + group pursuit (§1.1) |
| **non-enemy** entity (normally the Captain itself) | **RALLY, mobile** | move to that unit (`@goto` takes an entity natively); weapon register cleared → auto-acquire self-defense only, no pursuit |
| coordinate | **RALLY at a fixed point** (used by RETREAT → Home) | move to the point (`@goto`); weapon register cleared |
| empty | **HOLD** | clear weapon register; hold position (after a timeout with no readable Captain: return home — Captain-lost fallback) |

**The enemy filter on the entity row is mandatory, learned by live fire**: the first in-game
test dispatched on `value_type` alone, treating *any* entity command as a kill order — and the
Captain's rally broadcast is itself an entity, so the squad's opening act was focus-firing its
own Captain. Every member behavior must gate the engage path on
`match(Unit = cmd, Filter = v_enemy_faction)`, with the Failed branch routed to the
rally-on-unit response, never to a dead end (a dead-ended Failed silently disables rallying
instead).

Assembly per squad is one manual step per member: set its `Captain` parameter.

## 4. Captain state machine

`jump`/`label` computed dispatch off a `$State` register, the house idiom.

- **PATROL/IDLE** — no threat in vis 40. Broadcast: empty (HOLD). Listens for enemy
  broadcasts (Observers, other Captains) and approaches the one whose **reporter is
  closest** — scan-all-keep-nearest, not take-first, which ping-ponged the squad between
  Observers on opposite map sides instead of sweeping the local area clean first
  (live-observed; the local Observer rebroadcasting "one more, just out of range" is
  exactly the nearby signal that should win).
  **Heal gate**: before approaching the next signal-reported enemy, hold until no member is
  still recovering. The Captain scans the roster and checks each member's **retreat bit (bit
  2)**; if any member has it set, it keeps broadcasting HOLD (squad clusters on it and heals)
  and re-checks next tick instead of advancing. The gate rides the gunner's own retreat latch
  rather than the Captain independently polling `get_health`, so it respects each member's own
  (unit/tech-dependent) panic threshold and clears exactly when that member decides it has
  recovered (bit 2 clears at full health). It sits **only** on the "no enemy in my own vision"
  branch — an enemy walking into the Captain's vision takes the RALLY path first, so healing
  never blocks reacting to an immediate threat, only proactive new-fight-seeking. Because the
  Healer is faction-wide and Observer-driven (§5), a damaged member anywhere gets a healer
  dispatched to it, so the gate releases without the squad having to carry its own healer;
  a squad with *no* repair coverage at all will hold in PATROL until damage is cleared some
  other way (hull has no passive regen), which is a safe failure — it never freezes an active
  fight (there is no gate in ENGAGE).
- **RALLY** — threat spotted (`get_closest_entity(v_enemy_faction)` — visibility *is* the
  sensor at vis 40; no radar needed). Broadcast **the Captain itself** as a mobile rally
  point (simplification adopted during the first live test — the Captain already holds
  standoff, so "converge on me" is always a safe staging point and needs no geometry).
  **Gate**: count members within the gather radius of the staging point vs. the live roster
  size (both derived fresh from the membership scan) — advance only when the assembled
  fraction crosses the threshold (a percentage of the live roster, not a fixed count, so
  attrition never deadlocks the gate).
- **ENGAGE** — select target = **closest enemy to the staging point** (peels the cluster
  edge inward, keeping the squad maximally far from everything it isn't currently shooting).
  Broadcast the target entity. While engaged, the Captain maintains: its own standoff (≥30
  from nearest enemy, `moveaway_range`), the vision lock (keep the current target within vis
  40 — reposition closer if it nears the edge), and target liveness — a destroyed target's
  reference blanks its entity part (settled semantics: entity goes, num survives verbatim),
  which triggers re-selection. If living members' spread around the target exceeds a
  threshold for too long, drop back to RALLY rather than let a trickle develop.
  **Victory requires the squad's agreement, not just the Captain's eyes** (live-observed
  failure: the fight drifted beyond vis 40 and the Captain declared victory and walked off
  mid-battle): with nothing in its own vision, the Captain first scans for members whose
  beacon carries the **contact bit** (bit 1) — any hit means "rally on that member and close in
  to restore the vision lock," never PATROL. Target reselection during ENGAGE is deliberately
  *not* heal-gated — the gate lives in PATROL (above), so recovery happens between fights, not
  mid-battle.
- **RETREAT** — live roster below a floor, or the Captain itself pressed under its standoff
  with no escape vector: broadcast RALLY at home.

**Captain death**: members' `read_signal` stops resolving; after a timeout they clear weapon
registers and return home (member-side fallback, §3's HOLD row).

## 5. Member behaviors

- **Gunner** (deliberately tiny — the complexity budget all lives in the Captain):
  `read_signal(Captain)` → `value_type` dispatch per §3's table → loop. Plus the
  Captain-lost timeout. Auto-acquire covers self-defense during rally/transit without
  creating pursuit (pursuit only comes from an entity in the weapon register — §1.1 — which
  is exactly why RALLY leaves it empty).
- **Healer** (implemented, `library/healer.bsf` — diverged from the original squad-follower
  sketch): a **standalone, faction-wide** repair drone, *not* a squad member. It does not
  enlist on any Captain's channel, follow the command channel, or read ENGAGE targets; it runs
  independently and services every squad (and every damaged friendly) at once. Loop: if an
  enemy is in its own vision, flee home (move to Home within `Range`) — the healer never
  fights and never tanks. Otherwise pick a heal target = the **closest damaged own-faction
  unit**, found *both* by direct vision (`get_closest_entity(v_damaged, v_own_faction)`) **and
  by `for_signal_match(v_damaged)`** — this is how it consumes the **Observer's damage
  broadcasts**, so it homes on damaged units far outside its own sight. Infected friendlies
  (`v_infected`) are serviced the same way. It moves to the chosen target within `Range`,
  usually **3** — set by the **virus cure's range 3** (the tighter of the healer's two tools),
  which also keeps the target well inside the **range-5 `c_repairer_aoe`** heal radius, so one
  standoff distance covers both curing infection and repairing hull. It
  repairs passively in radius; with nothing to do it idle-wanders near
  Home (a bounded random walk, reset by a tick counter). `Target` is a persistent parameter
  (`keepvars`) so an in-progress heal survives across ticks. **This is what releases the
  Captain's PATROL heal gate**: damaged gunners broadcast via the Observer, roaming healers
  converge and repair them to full, their retreat bit clears, and the gate opens — no
  squad-local healer required. (Not audited line-by-line here; deployed and working per the
  author. The nearest-by-distance accumulation idiom in the two signal-scan loops is the one
  part worth a careful read if it ever misbehaves.)
- **Power provider** (revised after live testing): follows the command channel like a member
  but **does not enlist in the roster** — its `@signal` is reserved for the fuel-rod demand
  broadcast (§2), and the gate should count fighters anyway. During ENGAGE it parks **just
  behind the gun line** (pursuit stops gunners at their weapon's `attack_radius`, ~15 for
  beam cannons; ~17 for the field), because a Hybrid Beam Cannon charging outside a power
  field draws more than the frame capacitor delivers (100/tick vs the capacitor's 50/tick —
  data values are per-tick, the UI shows per-second ×5: 500/s vs 250/s) and the gunner
  **cannot move** while charging (live-observed, numbers reconciled against data) — power coverage belongs at the firing positions, not at the
  Captain's standoff. Otherwise it loiters in the squad cluster.
- **Gunner self-preservation** (added after live testing): retreat to the Captain's aura on
  battery < 80% or any hull damage, and **panic-disengage when any enemy closes within ~5**
  — pursuit parks at attack radius and never backs off on its own, and death-explosion
  enemies (Larva) punish adjacency hard. Every retreat clears the weapon register first
  (weapon target overrides `@goto`). The panic destination is **`2×Captain − Enemy`** (the
  enemy point-reflected through the Captain) — a bounded point behind friendly lines, never
  a direction: `moveaway_range` is enemy-relative, so a fast chaser (Malacostra) steered
  fleeing gunners into enemy lines and hundreds of tiles off-map (live-observed); the
  reflected point instead drags the chaser into massed fire. Degenerate case: an enemy
  standing on the Captain makes the reflection ≈ the Captain itself — acceptable, standoff
  has already failed at that point.
  The retreat itself is **latched** in the beacon (bit 2, §3): the retreat condition sets the
  bit, and it clears only at full health — not the moment the trigger stops. Without the latch,
  a unit whose retreat floor is *current* HP (a tanky frame ignoring chip damage) would
  re-engage the instant it crossed the floor and flap across it under fire; the latch gives the
  hysteresis "retreat below X, resume only at full." A member still in contact while retreating
  broadcasts both bits (`num = 3`) — the reason the Captain can't exact-match the beacon (§3).

  **Live-observed loss pattern (several hours of mixed-composition play, 2026-07-22):** the
  full set (Captain, Gunner, Power-provider, Observer, Healer) held up well; occasional member
  losses, concentrated on Scout and Dashbot frames running the Gunner behavior specifically —
  the same behavior also ran unmodified on Haulers, Mark V, human tank frames, and Command
  Center bots with various turrets without the same pattern. Reported cause: these frames get
  too close before disengaging. Candidate (unconfirmed) mechanisms:
  - **Reaction-time margin via speed — retracted.** The original hypothesis assumed Scouts/
    Dashbots are fast relative to Mark V, so they'd outrun the fixed ~5-tile panic-disengage
    range. **Wrong direction**: Scouts and Dashbots are slower than the Mark V, not faster
    (user correction, 2026-07-22). Kept here only as a record of a ruled-out mechanism.
  - **Congestion blocking the retreat path (user hypothesis, 2026-07-22)**: the squad bunches
    up to get within a short-range turret's attack radius, and when a member's panic-disengage
    fires, its `@goto` retreat move has to path out through that same cluster — under ground
    occupancy (≤1 unit/tile, no pushing, a stopped unit only yields to a mover one at a time —
    the same jamming mechanic already flagged for the rally gate, `todo.md`'s "Gunner spread on
    rally" item) the retreat can be blocked or delayed even though the trigger fired correctly
    and on time. This reframes the loss as a **movement/pathing failure downstream of a working
    trigger**, not a threshold-tuning problem — scaling the panic-disengage range or the health
    threshold wouldn't fix a retreat move that can't get out. Shorter-range turrets make the
    gun-line cluster tighter to begin with, which is the likely reason this shows up on Scout/
    Dashbot gunners specifically rather than beam-cannon gunners standing off at range 15.
  - **Loadout compounding (user hypothesis)**: light frames typically carry smaller turrets
    with shorter range, so the engagement itself already sits closer to the enemy than a
    beam-cannon gunner's — less standoff buffer before panic-disengage even triggers. Combined
    with a light frame's smaller HP/shield pool, a single heavy hit (or one incoming volley)
    can exceed the frame's *entire* health bar before the retreat latch (§5, bit 2) has a
    chance to set — an alpha-strike kill, not a gradual whittle-down the panic threshold was
    designed to catch. Also compounds with the congestion mechanism above: a blocked retreat
    path turns "should have retreated in time" into "took the alpha strike while stuck." If
    this or the congestion mechanism dominates, scaling panic-disengage range alone won't help;
    the fix would need to key off the frame's HP/shield pool relative to expected incoming
    damage, and/or solve the underlying pathing jam, not just react earlier.

  Recorded as two hypotheses, not a confirmed mechanism. See §7 for the follow-up.

## 6. Tuning constants (initial values, all expected to move)

| Constant | Initial | Why |
|---|---|---|
| Captain visibility | 40 | = Small Radar scan range; the design's fixed point |
| Captain standoff | 30 | 10-tile margin inside vis |
| Gather radius | 8 | staging-point assembly circle |
| Gate threshold | ~80% of live roster | absorb stragglers without deadlocking on losses |
| Re-rally spread | ~15 from target | trickle detector |
| Captain-lost timeout | ~25 ticks (5 s) | member fallback |
| Fuel-rod floor | TBD | power-provider resupply trigger |
| Gunner health panic | any hull damage (HP < 100) | retreat trigger; unit/tech-dependent — expose as a parameter (see §7) |
| Gunner battery floor | 80% | retreat trigger; scales with weapon/frame power draw |
| Panic-disengage range | ~5 | melee / Larva death-blast adjacency |
| Rally offset | ~5 | member spacing off the Captain / rally unit |
| Heal-gate criterion | no member's retreat bit set | PATROL gate before new-fight-seeking; rides the gunner's own latch (clears at that member's full health), not a Captain-side health poll |
| Healer `Range` | 3 | heal/cure standoff = virus cure range 3 (tighter tool); keeps target inside the range-5 AOE heal too |

## 7. Open items

- ~~`c_repairer_aoe` radius/power draw — pin when authoring the Healer.~~ Healer implemented
  (`library/healer.bsf`) as a standalone Observer-driven repair drone (§5), superseding the
  squad-follower sketch; `Range` is exposed as a parameter, usually 3 (virus cure range; keeps
  targets inside the range-5 AOE heal — §5/§6). Only the idle-wander tuning remains eyeballed.
- Staging-point geometry (threat-side offset math) — work out in BSF, integer-only.
- ~~**Gunner spread on rally (anti-bunch).**~~ Resolved 2026-07-22 — see `library/formation-hold.bsf`
  and its call from `squad-gunner.bsf`'s two entity-anchored RALLY paths (empty command = hold
  around the Captain; non-enemy `Unit` command = rally on that unit). Instead of the ring/
  self-index-vs-emergent fork this item originally posed, the shipped fix sidesteps the whole
  enumeration-order-stability question: each member independently rolls a random offset from the
  anchor the first time its own `Offset` parameter is empty, then keeps it (pass-by-reference —
  the sub writes into the caller's own register) and just re-homes on `Anchor + Offset` every
  call, moving only when drifted past `Tolerance`. No coordination, ranking, or Captain-side
  slot assignment needed. Radius=5/Tolerance=2 are first-pass constants (§6 territory), chosen so
  every roll stays within the Captain's own gather-radius-8 check. **Not** a collision-free
  assignment like the ring design would have been — `random_coordinate` samples independently
  per axis with no minimum-distance floor, so two members can still roll adjacent or (rarely)
  coincident slots; accepted as a probabilistic improvement over "everyone converges on the same
  tile," not a guarantee. Scope is the RALLY paths only — the Coord-anchored fixed-point rally
  (RETREAT → Home) still uses a bare point (Formation Hold needs a live entity Anchor), and
  ENGAGE positioning is weapon-pursuit-driven (§1.1), not `@goto`, so Formation Hold doesn't
  apply there directly. Applies to **ground** squads; an all-flyer squad can converge on one tile
  regardless (flyers stack). Whether this incidentally eases the retreat-path congestion
  hypothesis from §5 (a less-dense rally cluster should leave more room for a panicking member to
  path out) is plausible but unverified — that failure mode occurs during ENGAGE, which this
  change doesn't touch.
- Whether RALLY should ever hold fire outright (`v_powereddown` pass-through) instead of
  allowing auto-acquire self-defense — leaning no; self-defense without pursuit is safe.
- Overkill management (whole squad dumping into an almost-dead target) — v1's known
  limitation, unaddressed; acceptable for v2, revisit with real fights.
- **Alien units as squad members**: the Reformation Core (`c_alien_sc` on a Re-Simulator,
  engineer sacrifice) synthesizes 1 Small + 4 Internal components onto a garage-dockable
  alien unit without using its native sockets — enough for a Behavior Controller + shields
  (+ a visibility module), making augmented alien combat units (e.g. Obsidian Soldiers)
  viable gunners under the same command protocol. Not designed here; noted as real.
- **Parameterize the member routines for portability** — one Gunner (and Power-provider)
  behavior should serve different weapons, frames, and tech levels by exposed parameter, not a
  hand-edited copy per variant. Weapon range is already derived at runtime (`get_item_info`) —
  that is the pattern to extend to the rest of the currently-hardcoded knobs. Most important is
  the **unit health panic level**: today it is "any hull damage" (HP < 100), which is right only
  for a tanky/shielded unit — a fragile low-tech frame wants a lower floor before it abandons
  the line, and a heavily-armored one wants to fight through chip damage rather than thrash back
  to the aura, so the correct threshold is unit- and tech-dependent and must be a parameter.
  Promote alongside it the battery floor, the panic-disengage distance, and the rally offset
  (all in §6). The range-derived engage / gun-line / vision-lock constants are the same problem
  seen from the weapon side — see the early-tech variant item in `todo.md`.
  **Sharpened by the live loss pattern (§5):** Scout/Dashbot losses, not seen on Hauler/Mark V/
  tank/Command-Center gunners running the same behavior, are not explained by frame speed —
  Scouts and Dashbots are *slower* than the Mark V, so the original "outruns its own reaction
  time" hypothesis is retracted. Two mechanisms remain live, both pointing away from a pure
  threshold-tuning fix: the frame's own weapon range (light frames typically carry
  shorter-range turrets, so they already engage closer to begin with — less standoff before
  panic-disengage even triggers) and squad congestion (the cluster needed to get a short-range
  turret in range can physically block a panicking member's retreat path under ground
  occupancy — same jamming mechanic as the rally-gate item above, but hitting the retreat move
  instead of the assembly move). Either can compound with the frame's thin HP/shield pool into
  an alpha-strike kill the panic threshold — tuned for gradual damage — never gets a chance to
  catch. If congestion is the dominant mechanism, no threshold change fixes it; the fix is
  clearing/preventing the retreat-path jam (the anti-bunch fix above, extended to cover
  mid-fight retreat, not just rally assembly). Fix direction pending confirmation of which
  mechanism(s) actually apply — see §5's live-observed note.
- **Next-release interactions** (see `upcoming-changes.md`): `is_empty`-based death checks
  invert (use the entity-blank check via the settled dangling-ref semantics, and migrate to
  Target Type Switch's 'Destroyed Object' pin when it lands); `compare_unit` is removed
  (auto-converts to 'Compare Data'); 'Loop Signal' comparison rework — retest the membership
  scan after the update. The scan now runs in plain Match mode (`c=1`, num ignored) with a
  per-member `check_bit`, so it no longer depends on Loop Signal's num-comparison semantics at
  all — the rework should not affect it, but confirm the Match mode itself is unchanged.
- Implementation order: Captain and Gunner first (they are the closed loop), in BSF —
  both deployed (`library/squad-captain.bsf`, `library/squad-gunner.bsf`). Healer
  deployed too (`library/healer.bsf`, standalone/Observer-driven — §5). **Power provider now
  deployed too** (`library/squad-power.bsf`) — matches §5's design exactly: reserves its own
  `@signal` for fuel-rod resupply demand (never enlists in the roster), parks at distance 17
  during ENGAGE (just behind the ~15-range gun line), retreats via the `2×Captain − Enemy`
  point-reflection under 10 tiles, and defaults to loitering near the Captain otherwise.
  **All four have now run a real bug-camp test** — several hours of mixed-composition live
  play (2026-07-22), Gunner behavior deployed across Scouts, Dashbots, Haulers, Mark V, human
  tank frames, and Command Center bots with different turrets. Overall behavior held up;
  occasional member losses, concentrated on Scout/Dashbot gunners — see the live-observed
  finding in §5 and the sharpened parameterization item above.

## Lineage

v1 (Beacon/Scout/Gunner/Support, stationary base-side coordinator, radio-channel orders,
shortlist/reservoir target reporting) is preserved in git history along with its partial
implementation (`../blz-desynced-toolkit/tests/data/beacon.dcs`, `beacon2.dcs` — still valid
as codec/BSF test fixtures, now living in the toolkit repo after the 2026-07-22 split;
obsolete as designs). Two v1 mechanisms survive into v2: the self-healing
Signal-pointing membership scan (§3, was v1 §2.4) and the integrated-behavior-controller
socket fact (§2, was v1 §2.5 — corrected in passing: it is **robot-race frames only**, not
"all frames"; human/alien units always need an explicit `c_behavior`). v1's reporting/dedup machinery dissolved entirely — with the
Captain being the sensor, there is nothing to report, only commands to issue.
