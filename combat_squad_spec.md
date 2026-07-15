# Combat Squad — Design Spec (v2: Captain architecture)

**Supersedes the v1 Beacon/Scout/Gunner/Support design** (2026-07-14; v1 and its
`beacon.dcs`/`beacon2.dcs` implementations are git history — see "Lineage" at the end).
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
- **Healer**: position just behind the squad (e.g. offset from staging point away from the
  threat); `c_repairer_aoe` repairs passively in radius. Follows RALLY/HOLD like a gunner,
  ignores ENGAGE targets (never writes a weapon register; it has none).
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
  (weapon target overrides `@goto`).

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

## 7. Open items

- `c_repairer_aoe` radius/power draw — pin when authoring the Healer.
- Staging-point geometry (threat-side offset math) — work out in BSF, integer-only.
- Whether RALLY should ever hold fire outright (`v_powereddown` pass-through) instead of
  allowing auto-acquire self-defense — leaning no; self-defense without pursuit is safe.
- Overkill management (whole squad dumping into an almost-dead target) — v1's known
  limitation, unaddressed; acceptable for v2, revisit with real fights.
- **Alien units as squad members**: the Reformation Core (`c_alien_sc` on a Re-Simulator,
  engineer sacrifice) synthesizes 1 Small + 4 Internal components onto a garage-dockable
  alien unit without using its native sockets — enough for a Behavior Controller + shields
  (+ a visibility module), making augmented alien combat units (e.g. Obsidian Soldiers)
  viable gunners under the same command protocol. Not designed here; noted as real.
- **Next-release interactions** (see `upcoming-changes.md`): `is_empty`-based death checks
  invert (use the entity-blank check via the settled dangling-ref semantics, and migrate to
  Target Type Switch's 'Destroyed Object' pin when it lands); `compare_unit` is removed
  (auto-converts to 'Compare Data'); 'Loop Signal' comparison rework — retest the membership
  scan after the update.
- Implementation order: Captain and Gunner first (they are the closed loop), in BSF, tested
  against a bug camp; Healer/Power provider after.

## Lineage

v1 (Beacon/Scout/Gunner/Support, stationary base-side coordinator, radio-channel orders,
shortlist/reservoir target reporting) is preserved in git history along with its partial
implementation (`tests/data/beacon.dcs`, `beacon2.dcs` — still valid as codec/BSF test
fixtures; obsolete as designs). Two v1 mechanisms survive into v2: the self-healing
Signal-pointing membership scan (§3, was v1 §2.4) and the integrated-behavior-controller
socket fact (§2, was v1 §2.5 — corrected in passing: it is **robot-race frames only**, not
"all frames"; human/alien units always need an explicit `c_behavior`). v1's reporting/dedup machinery dissolved entirely — with the
Captain being the sensor, there is nothing to report, only commands to issue.
