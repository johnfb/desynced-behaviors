# Combat Squad Behavior — Design Spec

Companion system to `observer.dsc`. Defines cooperating behaviors — **Beacon**, **Scout**,
**Gunner**, **Support** — that let multiple independent squads roam the whole map hunting for
threats and fight as a coordinated group, on top of the faction-wide sensor network your
**Observer**-equipped units (power poles, mining squads, roamers) already provide. Built entirely
from real instructions in `data/instructions.lua` and components in `data/components.lua`.

Design corrections applied across this revision:

1. **Observers are not part of the squad — they're shared faction infrastructure.** You already
   run `observer.dsc` on units all over the map, reporting enemies/damaged/infected/lootable via
   each unit's own `Signal` register. A squad's Beacon doesn't need dedicated scouts wired in —
   it just listens to whatever nearby Observers (anyone's) are already reporting, faction-wide,
   for free.
2. **Scout is a separate, armed role from Observer.** Scouts also report, using the identical
   convention Observers use, but their job is fighting small stuff and screening the perimeter.
3. **The squad must not fixate on one target.** The Beacon re-evaluates *every* current report
   each tick, and a mechanical backstop (turret auto-defense + personal safety checks) keeps
   individual units from getting blindsided regardless of what the squad is nominally focused on.
4. **The Beacon is a safe, stationary asset inside the base, not a patrol anchor.** The squad
   roams the *entire map*; it does not hold near the Beacon or lease its range of operation to a
   distance-from-Beacon check.
5. **Target selection minimizes travel time, with random tie-breaking.** So that multiple
   independent squads, seeing the same faction-wide report set, have a good chance of splitting
   up across different targets instead of all converging on one "best" threat.

---

## 1. Roles

| Role | Loadout | Job |
|---|---|---|
| **Observer** *(already exists, unmodified)* | `observer.dsc`, wherever you already run it | Faction-wide sensing: reports enemies/damaged/infected/lootable via its own `Signal` register. Not squad-owned. |
| **Beacon** | Stationary building, integrated behavior, `c_radio_transmitter` | Sits safely inside the base. Pure comms/aggregation node: reads faction-wide threat reports, picks a target to minimize the squad's travel time, broadcasts it on the squad's Radio band. Never leaves, never fights. |
| **Scout** | Fast frame, weapon, low HP | Mobile picket that actively drives the squad's map-wide roam (via the engine's own `Scout` explore instruction). Reports contacts the same way Observers do, fights only what it can safely beat, flees the rest. |
| **Gunner** | Medium turret, internal slots all shields | Trails the Scouts while idle; holds turret range on whatever the squad is engaging, anywhere on the map; retreats to heal on real damage; power-gated. |
| **Support** | `c_repairer` and/or `c_power_cell` | Follows Gunners closely enough to keep them powered and repaired; never fights. |

---

## 2. Coordination mechanism

Two different engine systems are used for two different data-flow shapes, and mixing them up is
what made earlier drafts of this spec overcomplicated.

### 2.1 Many-to-one: Observer/Scout reports → Beacon (via Signal)

`Loop Signal (Match)` (`data/instructions.lua:2419`) queries `comp.faction:GetEntitiesWithRegister(...)`
— faction-wide, not vision-limited, not adjacency-limited. Querying with `in_signal = { id =
"v_enemy_faction" }` returns **every entity in the faction whose own `Signal` register currently
holds an entity reference that itself matches the `v_enemy_faction` filter** — i.e. every unit
(Observer, Scout, anyone) currently broadcasting "I see an enemy," without that broadcaster
needing to tag itself with anything. This is exactly what `observer.dsc` already produces: it
scans for `v_enemy_faction` / `v_damaged` / `v_infected` and writes the found entity into its own
`Signal` register (then pings). The read side and write side were already designed as a matched
pair. Same trick works for `v_damaged`, `v_infected`, `v_droppeditem`/`v_can_loot`, etc.

Register-structure note, since it explains why reports carry only an entity and nothing else: a
register holds a number and *one* of {identifier, entity reference, coordinate} — never two —
per `Combine Register`'s own doc string (`data/instructions.lua:1693`). So a report is just
`{ entity = spotted }`; the `id=v_enemy_faction` in the *query* does the classification, not a
tag on the broadcaster.

### 2.2 One-to-many: Beacon's order → its own squad (via Radio)

This is the opposite shape — one sender, many listeners, and it must **not** leak between
squads. That's what the Radio system is for (`data/components.lua:4416-4522`):

- `c_radio_transmitter` (equip on the Beacon) has two registers, **Band** and **Value**. Setting
  Band links its Value register into a faction-wide, named-channel table
  (`faction.extra_data.radio_storage`); whatever the Beacon writes to Value is immediately
  readable on that band by anyone.
- `Read Radio(band)` (`data/instructions.lua:2349`) reads the current value of a band —
  **no component required to read**, faction-wide, exactly like `Read Signal`.
- The **Band** value is simply the squad's own Beacon entity reference — no separately chosen id
  needed. Entities are already guaranteed unique, so using the Beacon itself as the channel
  identifier means every squad automatically gets its own collision-free band for free, and any
  squad member can tune in with the same `R1` reference it already holds (§2.3).

### 2.3 Squad "home" reference — a last-resort safety net only

Every squad member still keeps a Custom Register (`R1`) linked once to the Beacon at deploy time
(same mechanism the game uses to auto-fill rally points — `rally_reg = comp:GetRegister(3)`,
`data/components.lua:825`). Since the squad roams the whole map and the Beacon sits safely at
home doing nothing but comms, `R1` is **not** used for day-to-day positioning — only as somewhere
to retreat to if a unit can't find any live squadmate nearby (the rest of the squad is dead or out
of vision range).

### 2.4 Locating the squad — derived fresh every tick, not stored

Picking the *closest* reported threat requires measuring distance from somewhere, but the Beacon
is stationary in the base while the squad could be anywhere on the map — "distance from the
Beacon" is meaningless for this. The fix does **not** need a manually-linked, storable reference
(which would go stale the moment that specific unit died) — instead, the Beacon just asks "who is
currently in my squad and alive" fresh, every tick:

- Gunners and Support keep their own `Signal` register statically set to `{ entity = <this
  squad's Beacon> }`. This is cheap and conflict-free — neither role needs `Signal` for anything
  else (only Scouts use `Signal` dynamically, for sighting reports).
- The Beacon runs `Loop Signal (Match)` with `in_signal = { entity = <self> }` (via `Get Self`) —
  the entity-match mode of the same instruction from §2.1, this time asking "who has *their*
  Signal pointed at *me*." That returns every live Gunner/Support still tagged to this Beacon.
  Filter with `Has Like Component("c_turret")` to prefer a Gunner as the position reference
  (more survivable than Support); if none are alive, fall back to `c_repairer`/`c_power_cell`
  (Support); if the whole squad is gone, there's no position reference for that tick and target
  selection falls back to danger-agnostic/no-distance-weighting (see §5.1).

This is what answers "what if the anchor dies": there is no single anchor to die. Since destroyed
entities don't stay queryable by faction-wide scans (the same assumption `Loop Units (Range)` and
every other faction query already relies on), whichever squad member happens to still be alive
and tagged is simply whoever the query returns that tick — losing today's pick just means next
tick's query returns a different live squadmate instead. No manual re-linking, no explicit
death-detection logic needed.

### 2.5 A note on component slots

All frames get an integrated behavior controller (`c_integrated_behavior`, hidden attachment) by
default — only a handful of special frames opt out (`no_integrated_behavior = true`: mothership,
space-drop pod, wall, gate). So any ordinary building works as a Beacon without needing to spend
a visible component socket on `c_behavior` itself — it only needs one free **Internal** socket
for `c_radio_transmitter`.

---

## 3. Squad Assembly Procedure (one-time, manual, per squad)

1. Build/place the squad's **Beacon**. Equip `c_radio_transmitter`, set its **Band** register to
   itself (`Get Self` → Band) — the Beacon is its own channel id.
2. For every **Scout, Gunner, and Support** in the squad:
   - Link its `R1` custom register → the Beacon. This one link now serves double duty: it's both
     the safety-net fallback location (§2.3) *and* the Radio band to tune in on for orders.
3. Nothing else to configure. Gunners/Support tag their own `Signal` to the Beacon automatically
   as part of their behavior loop (§2.4) — not a manual step. Nothing to configure on Observers —
   they're not squad members, and nothing here changes how they're deployed.

---

## 4. Threat aggregation & multi-threat handling

**Squad level (Beacon):** every tick, re-run the Signal query from scratch — don't remember last
tick's pick. Dedupe by entity (multiple Observers may report the same target), then pick the
report that **minimizes travel time** from wherever the squad currently is (§2.4's live position
lookup), breaking near-ties **randomly** rather than deterministically — see §5.1 for the exact
algorithm. Since this is recomputed from scratch every tick, if the squad's chosen target changes
(destroyed, or a closer one appears), the order updates on the very next cycle.

**Individual level (every unit, always-on, independent of the Beacon's order):**
- `c_turret`'s own `acquire_target_func` (`data/components.lua:2808`) fires at *any* enemy inside
  its `trigger_radius` (7 tiles) regardless of what the "Preferred Target" register says — engine
  behavior, not something the script controls. A Gunner nominally chasing the squad's chosen
  target will still shoot back automatically if something else gets close. Covers the worst-case
  "ambushed while distracted" scenario for Gunners specifically, for free.
- Every role also runs its own cheap personal-safety check (`Loop Units (Range)` capped at its
  own vision, filter `v_enemy_faction`) each tick, independent of the Beacon's order, so
  Scouts/Support (no auto-defense component) don't wander obliviously into something nasty while
  the squad's attention is elsewhere.
- Danger-awareness deliberately lives *here*, at the individual level, and not in the Beacon's
  target selection — see §7 for the tradeoff that creates.

---

## 5. Behavior Pseudocode

Instruction names are the exact node names as they appear in the visual editor. Tuning constants
are `ALL_CAPS`; see §6.

### 5.1 Beacon

```
// Beacon — aggregator + order broadcaster. No radar; relies entirely on the faction's
// existing Observer/Scout reports via Signal. Transmits on this squad's Radio band.
// Target selection: minimize travel time from wherever the squad currently is, picking
// randomly among near-ties so multiple squads don't all converge on the same target.
loop:
    // 1. find a live position reference for "where is my squad right now" (§2.4)
    Get Self -> self_ref
    anchor := empty
    Loop Signal (Match) signal={entity: self_ref}, filter=Match
        -> filter results with Has Like Component("c_turret")
        -> anchor := first result (a live Gunner)
    Is Empty(anchor)
        Loop Signal (Match) signal={entity: self_ref}, filter=Match
            -> filter results with Has Like Component("c_repairer")
            -> anchor := first result (a live Support)
    // if still empty, the squad is wiped: anchor stays empty, distance scoring is skipped below

    // 2. gather every current threat report, faction-wide, deduped
    threat_count := 0
    seen         := {}
    best_dist    := infinite
    Memory Remove(index={id:"candidates"}, num=REG_INFINITE)      // clear shortlist from last tick

    Loop Signal (Match) signal={id: "v_enemy_faction"}, filter=Match
        -> for each (reporter, report):
            e := report.entity
            if e not in seen:
                seen.add(e)
                threat_count += 1
                Is Empty(anchor)
                    -> empty: Memory Set(index={id:"candidates"}, value=e)   // no position ref — everything's a candidate
                    -> found:
                        Distance(e, Source=anchor) -> d
                        if d.num < best_dist - TRAVEL_TIME_TOLERANCE:        // clearly closer — new shortlist
                            best_dist := d.num
                            Memory Remove(index={id:"candidates"}, num=REG_INFINITE)
                            Memory Set(index={id:"candidates"}, value=e)
                        elif d.num <= best_dist + TRAVEL_TIME_TOLERANCE:     // within tolerance — join shortlist
                            if d.num < best_dist: best_dist := d.num
                            Memory Set(index={id:"candidates"}, value=e)
                        // else: too far, ignore

    // 3. pick randomly among the shortlist (a single winner if nothing was actually tied)
    Memory Length(index={id:"candidates"}) -> n
    Random Number(1, n.num) -> pick_idx
    Memory Get(index={id:"candidates", num: pick_idx.num}) -> best_target

    Combine Register(Number=threat_count, Data=best_target) -> order
    Set to Component(order, To=<own c_radio_transmitter Value register>)   // self-equipped, no adjacency issue
    // Band register was set to self_ref once (§3) — no need to re-set it here.

    Wait 1
    goto loop
```

### 5.2 Scout

```
// Scout — mobile picket, actively drives the squad's map-wide roam. Reports sightings the same
// way Observers do, fights only what it can safely beat, flees the rest, heals at Support.
main:
    Loop Units (Range) range=<own visibility>, filters=[v_enemy_faction]
        -> found enemy e:
            Get Health(e) -> _, _, max_hp
            Compare Number(max_hp, SMALL_UNIT_HP_THRESHOLD)
                If Smaller:                                 // safe to fight — thin the swarm
                    Combine Register(Data=e) -> report
                    Copy report -> Signal                    // same convention Observers use
                    Move Unit(e, range=LIGHT_WEAPON_RANGE)
                Else:                                        // too dangerous — report and back off
                    Combine Register(Data=e) -> report
                    Copy report -> Signal
                    Move Away (Range) target=e, range=SCOUT_SAFE_MARGIN
        -> nothing found:
            Copy <empty> -> Signal                           // clear last report
            Check Health(if_full -> skip_retreat)
            Get Shield(self) -> shield_pct
            Compare Number(shield_pct, 0)
                If Equal/Smaller:                            // shields down AND actually hurt
                    Loop Units (Range) range=<own visibility>, filters=[v_own_faction, c_repairer]
                        -> nearest support s
                    Read from R1 -> beacon_ref                // fallback only, §2.3
                    Move Unit(s or beacon_ref, range=REPAIR_TRIGGER_RADIUS)
            skip_retreat:
                Scout()                                      // built-in whole-map explorer (§5.2 note below)
    Wait 1
    goto main
```

`Scout` (`data/instructions.lua:5241`, "Sends the unit to explore unknown areas in a spiral
movement around your faction home") is the engine's own map-wide-exploration instruction — it
drifts away from `faction.home_location` if too close, then settles into an outward spiral/loop
biased toward unrevealed tiles. This *is* "roam the whole map" — no custom patrol-radius logic
needed. Caveat: it centers on the single faction-wide `home_location`, not a per-squad point; fine
given the Beacon lives in "the base" anyway, but if you ever run squads out of multiple separate
bases within one faction, they'd all spiral around the same one engine-defined home.

### 5.3 Gunner

```
// Gunner — holds turret range on the squad's priority target, anywhere on the map;
// self-preserving; power-gated. No leash — the squad's whole job is to go wherever it's needed.
main:
    Read from R1 -> beacon_ref                                // this squad's Beacon = both fallback and Radio band
    Copy { entity: beacon_ref } -> Signal                      // static self-tag, cheap, idempotent (§2.4)
    Read Radio(beacon_ref) -> order                            // { entity: target, num: threat_count }

    Is Empty(order.entity)
        -> empty:                                             // nothing known — stick with the roaming pack
            Loop Units (Range) range=<own visibility>, filters=[v_own_faction, c_radar]
                -> nearest scout p
            Move Unit(p, range=FORMATION_RADIUS)               // if none found, just hold position
            Wait 1 ; goto main

    // power gate — no point pushing into range if the turret can't fire
    Check Grid Efficiency(if_full -> has_power)
        Loop Units (Range) range=<own visibility>, filters=[v_own_faction, c_power_cell]
            -> nearest support s
        Move Unit(s, range=NEAR_SUPPORT_RADIUS)                // if none found, just hold position
        Wait 1 ; goto main

    has_power:
    // shield/health gate — retreat only on real damage, not just shield depletion
    Get Shield(self) -> shield_pct
    Compare Number(shield_pct, 0)
        If Larger:
            Move Unit(order.entity, range=TURRET_ATTACK_RADIUS)  // turret auto-fires; also auto-defends vs anything else in its own trigger_radius
        If Equal/Smaller:
            Check Health(if_full -> Move Unit(order.entity, range=TURRET_ATTACK_RADIUS))
            not full:
                Move Away (Range) target=order.entity, range=(TURRET_ATTACK_RADIUS + RETREAT_MARGIN)
                                                                 // Support already tracks the lowest-health
                                                                 // Gunner (§5.4), so it comes to you — no
                                                                 // explicit "seek support" step needed here

    Wait 1
    goto main
```

Note: `c_shield_generator` absorbs damage first and only spills into real HP once `stored` hits 0
(`data/components.lua:2757` `on_take_damage`) — so "shields down" alone isn't the retreat
trigger, "shields down *and* `Check Health` says not full" is.

### 5.4 Support

```
// Support — pure positioning. c_repairer/c_power_cell do their job passively once in range.
main:
    Read from R1 -> beacon_ref                                // this squad's Beacon (fallback location, §2.3)
    Copy { entity: beacon_ref } -> Signal                      // static self-tag, cheap, idempotent (§2.4)

    Loop Units (Range) range=<own visibility>, filters=[v_own_faction, c_turret]
        -> track nearest gunner g (or lowest Get Health percent, if several)

    Is Empty(g)
        -> empty: Move Unit(beacon_ref, range=FORMATION_RADIUS)  // no gunners in sight, hold near home
        -> found: Move Unit(g, range=POWER_TRANSFER_RADIUS - 1)  // stay inside c_power_cell/c_repairer range

    // self-preservation — Support has no weapon and no auto-defense component
    Loop Units (Range) range=<own visibility>, filters=[v_enemy_faction]
        -> found e: Move Away (Range) target=e, range=SUPPORT_SAFE_MARGIN

    Wait 1
    goto main
```

---

## 6. Tuning parameters

| Constant | Meaning | Starting point |
|---|---|---|
| `SMALL_UNIT_HP_THRESHOLD` | Max HP below which a Scout will fight rather than flee | tune to Scout's own weapon DPS |
| `SCOUT_SAFE_MARGIN` | Distance a Scout keeps from anything it won't fight | > typical enemy weapon range |
| `REPAIR_TRIGGER_RADIUS` | Match `c_repairer.trigger_radius` (5) | 5 |
| `FORMATION_RADIUS` | How close idle Gunners/Support stay to the Scout line / Beacon fallback | small, loose-formation sized |
| `NEAR_SUPPORT_RADIUS` | How close a power-starved Gunner moves to Support | ≤ `c_power_cell.transfer_radius` (10) |
| `TURRET_ATTACK_RADIUS` | Match the equipped turret's `attack_radius`/`trigger_radius` (7 for `c_turret`) | 7 (or per turret variant) |
| `RETREAT_MARGIN` | Extra distance added when disengaging | a few tiles beyond attack radius |
| `POWER_TRANSFER_RADIUS` | Match `c_power_cell.transfer_radius` (10) | 10 |
| `SUPPORT_SAFE_MARGIN` | Distance Support keeps from any spotted enemy | generous — it has no way to fight back |
| `TRAVEL_TIME_TOLERANCE` | How close two candidates' distances must be to count as "tied" for random selection | a handful of tiles; too small ≈ always deterministic-nearest, too large ≈ always random |

No `SQUAD_BAND` constant is needed — the Radio band is just the Beacon's own entity reference
(`R1`), so there's nothing to pick or coordinate across squads.

---

## 7. Known limitations / open questions

- **Pure travel-time selection means a trivial nearby target can outrank a genuinely dangerous
  farther one.** That's the explicit tradeoff of "minimize travel time, otherwise random" as the
  *squad-level* rule — danger-awareness isn't gone, it just lives entirely at the *individual*
  level now (turret auto-defense + personal safety checks, §4), not in which target the Beacon
  calls. If squad-level prioritization of dangerous targets matters more than travel time in
  practice, that would mean blending a danger score back into the Beacon's scoring rather than
  using distance as the sole criterion — flag if you want that.
- **Randomized tie-breaking reduces, but doesn't guarantee, squads splitting up.** If only one
  threat is reported, every squad still converges on it (correctly — there's nothing else to
  pick). If several are reported and squads happen to be near each other, they may still land on
  the same pick by chance.
- **The self-healing anchor lookup (§2.4) assumes destroyed entities drop out of
  `GetEntitiesWithRegister` queries the same way they drop out of `Loop Units (Range)`.** That's
  consistent with how every other faction-wide query in this codebase behaves, but hasn't been
  observed directly in a running game — worth confirming empirically once this is built.

## 8. Future extension (not built here)

You mentioned the Beacon could grow into a large multi-slot building that automatically produces
or replenishes squad units — effectively an autobase for the squad. Noted as a natural next step:
`c_autobase` behaviors get to bypass the remote-write adjacency restriction that ordinary
behaviors are subject to, which would let a production-capable Beacon push orders/equipment
directly to squad members instead of only broadcasting over Radio. Out of scope for this pass.
