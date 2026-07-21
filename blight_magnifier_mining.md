# Blight Magnifier / Overclock Economics and a Coordinated Miner-Drone Design

A worked-out design doc covering two things built in the same session: (1) the
real math behind overclock modules, building base efficiency, and the
oversized-socket bonus, applied to picking building layouts for Blight
Magnifiers; (2) a full drone-mining behavior — reservoir-sampled node
selection, Signal-register-based coordination to avoid oversubscribing one
node, and a corrected understanding of what the native engine already does
for you — written directly in `behavior_source_format.md`'s graph grammar as
a real test of that format's usability for original authoring, not just
decompiling.

## Part 1: Component efficiency math

### The core formula

Confirmed directly in `get_work_time` (`data/components.lua:7405-7416`), the
only Lua-visible implementation of this — used by Blight Extractor and Blight
Magnifier specifically, since both are "self-timed work" components rather
than generic recipe-driven producers:

```
eff_boost = frame.component_boost (the building's own intrinsic bonus)
          + sum of every c_moduleefficiency-family component's `boost`,
            any size, anywhere on the building (additive, confirmed via
            SumModuleBoosts, utilities.lua:584)
          + faction.component_boost - 100 (Re-Simulator global bonus, usually 0)
          + 50  if this specific component sits in a socket LARGER than its
                own attachment_size, else 0 (flat, not scaled by how much
                bigger — Medium-in-Large and Small-in-Large both just get +50)

speed multiplier = (100 + eff_boost) / 100
```

**Critical correction, 2026-07-11 — the boost is applied natively, whether or
not any Lua code calls `get_work_time`.** Originally assumed (and told to the
user as "confirmed real, not a glitch") that Overclock modules do nothing for
`c_miner`/`c_adv_miner`, reasoning that neither component's Lua ever
references `get_work_time`/`eff_boost` — only `SetStateStartWork` with a raw,
unboosted time value. That reasoning is wrong. `c_blight_magnifier:on_update`
*also* passes the raw, unboosted `self.magnify_time` straight into
`SetStateStartWork` — `get_work_time` is called only in its tooltip's
`get_ui`, never in the actual timer logic — yet a real in-game measurement
(pause/unequip/re-equip/unpause, reading the progress widget) confirmed the
*actual* cycle time reflects the full boost. Cross-checked the same way on
the mining drone: `c_miner` declares `get_ui = true` (the generic
engine-default tooltip, no custom Lua tooltip code at all, let alone a
`get_work_time` call) — and its tooltip *and* a stopwatch test both showed a
genuinely faster real cycle time with an Overclock Module equipped. Both
components pass a raw tick count into a native call and get a boosted result
back; `get_work_time`'s Lua-side formula is a *prediction* of what the native
code will do (used by components with a bespoke tooltip), not the mechanism
that applies it. **Conclusion: Overclock modules do speed up mining after
all** — the earlier "pointless on a mining drone" verdict was wrong and
should not be repeated.

Also corrected: `base_work_time` (e.g. `magnify_time = 200`) is in **ticks**,
not seconds — `get_work_time` returns `base_work_time / TICKS_PER_SECOND` as
its first value. A tooltip showing `X` seconds is already-divided; the raw
field on the component definition is not.

**`faction.component_boost` is not "usually 0" — it's the Global Overclocking
Boost.** `c_moduleefficiency_g`/`c_moduleefficiency_5` ("Global Overclocking
Boost", repeatable end-game-objective reward, equipped on a Resimulator) is
exactly this term, confirmed by working backward from two independent
real in-game measurements to an exact integer-tick match (see "Regen vs.
mining threshold" below) — each copy adds a flat +5 to `eff_boost`
*everywhere*, building math and mining alike, not just at the one building it
sits on.

Overclock modules (`c_moduleefficiency*`, `components.lua:357-396`) come in
four sizes — Internal +20%, Small +50%, Medium +100%, Large +150% — cost no
power, and their effect is building-wide, not confined to their own socket.
Every building has 2-4 Internal sockets (confirmed via `data/visuals.lua`
socket lists) that never compete with production-component placement, so
filling them with Internal Overclock Modules is close to a free lunch.

**Socket size ordering** (`ui/utilities.lua:197-199`,
`attachment_sizenums`): Internal=1, Small=2, Medium=3, Large=4. A socket
accepts any component of its own size or smaller; the +50 oversocket bonus
only fires when the *component* is smaller than the *socket* it's actually
placed in.

### The mistake made and corrected: opportunity cost is not always 100pp

Early in this analysis a shortcut formula was used — "sacrificing one
Medium/Large slot for an Overclock Module instead of a magnifier always costs
exactly 100 percentage points, regardless of socket size" — derived from the
fact that Large-OC (150%) minus Medium-OC (100%) exactly equals the
oversocket bonus (50%). **This shortcut is only true when there is exactly
one magnifier in the building.** With two or more magnifiers, it breaks,
because the +50 oversocket bonus is *per-component* (only the one magnifier
literally sitting in the Large socket gets it) while an Overclock Module's
boost is *shared building-wide* (every magnifier benefits equally). Spreading
one Large socket's +150% across several magnifiers beats letting one of them
keep a private +50%, once there's more than one magnifier to spread it over.

The concrete case this bit: for `f_building3x2a` ("Building 3x2, 1L3M"), the
shortcut predicted an all-4-magnifier configuration would win (13.20x). The
correct per-slot brute-force enumeration (every Medium/Large socket
independently either "magnifier" or "Overclock-of-its-max-size", summing each
magnifier's own `eff_boost` including its own personal oversocket bonus if
applicable) gives the real optimum: **3 magnifiers + 1 Large Overclock =
12.90x**, beating all-4-magnifiers' **11.70x**. The lesson generalizes:
*any* building with a Large socket and 2+ magnifiers needs brute-force
per-slot enumeration, not a shortcut — the Large socket should hold an
Overclock Module whenever more than one magnifier is in play, never a
magnifier itself.

### Corrected building table

One earlier mistake in identifying buildings, worth stating plainly since it
propagated through an entire round of math before being caught: **the
building named "Building 2x1 (1M)" (`f_building2x1d`, 100% intrinsic boost)
is a 2-tile building** (`v_base2x1d`'s `tile_size = {1, 2}`), not a 1-tile
building — it was mislabeled as "1x1" for a few iterations by conflating it
with the *separate*, unrelated 1-tile `f_building1x1a` ("Building 1x1 (1M)",
0% boost) and `f_building1x1h` ("Defense Block", 50% boost, also 1 tile).
Always check `tile_size` in the frame's `visual` entry directly — the name
suffix ("1x1"/"2x1"/"2x2"/"3x2") is normally reliable but a frame's *actual*
footprint is only confirmed by its visual def.

Per-tile throughput (`output × (cellsize - footprint) / (200 × cellsize)`,
where `cellsize = (w+4)(h+4)` is the gapless-tiling cell for the radius-2
square coverage — see "Range is a square at radius 2" below) for the
best-total-output
configuration of each real building layout:

| Building | Footprint | Best-total output | Throughput/total-land |
|---|---|---|---|
| **3x2 (1L3M) — `f_building3x2a`** | 6 (3×2) | 12.90 (3 mag + 1 Large OC) | **0.0553** |
| 2x2 (2M1L) [C/D] — `f_building2x2c` | 4 | 7.20 (2 mag + 1 Large OC) | 0.032 |
| 2x2 (2M1L) [A] | 4 | 6.80 | 0.0302 |
| 2x2 (3M) — `f_building2x2b` | 4 | 6.30 (3 mag) | 0.028 |
| 3x2 (2M2S) | 6 | 5.20 (2 mag) | 0.0223 |
| 2x2 (1M3S) | 4 | 3.60 (1 mag, forced) | 0.016 |
| 2x1 (2M) — `f_building2x1c` | 2 | 4.00 (2 mag) | 0.0187 |
| 2x1 (1M1L) | 2 | 3.30 (2 mag, best split) | 0.0154 |
| 2x1 (2S1M) | 2 | 2.90 (1 mag, forced) | 0.0135 |
| 2x1 (1M) — `f_building2x1d` | 2 | 2.40 (1 mag, forced) | 0.0112 |
| 1x1 (1L) — `f_building1x1b` | 1 | 1.90 (1 mag, personal oversocket) | 0.0091 |
| Defense Block — `f_building1x1h` | 1 | 1.70 | 0.0082 |
| 1x1 (1M) — `f_building1x1a` | 1 | 1.40 | 0.0067 |

The small 1-tile buildings are the *worst* choice by true land-throughput,
despite having the best coverage-area-to-footprint ratio — their magnifier
density is too thin to make up for it. **`f_building3x2a` is the best
building for this purpose, full stop** — both for raw total output and for
throughput per unit of land, because its 100% intrinsic boost and 4 Internal
sockets more than compensate for its worse area-to-footprint ratio.

### Range is a square at radius 2, confirmed in-game (metric: floored Euclidean)

> **Resolved 2026-07-19 (in-game RangeProbe run — `tests/data/range_probe.bsf`,
> results in `mock_world_spec.md`'s distance-metrics item):** the native range
> gate is **floored Euclidean** (in range `R` ⟺ `floor(dist) ≤ R`), not
> Chebyshev — an earlier version of this heading named the wrong metric. At
> radius 2 the two are indistinguishable: the corner tile sits at 2√2 ≈ 2.83,
> which floors to 2, so a radius-2 floored-Euclidean circle *is* the full 5×5
> square. Everything below that depends only on that radius-2 square — the
> gapless tiling cell, the node spacing, the duplicator's min-spacing
> conclusions — is numerically unchanged; read this section's remaining
> "Chebyshev" phrasing as "the radius-2 square coverage."

User-confirmed: Magnifier `range = 2` means a square region extending 2
tiles in *every* direction from the building's footprint (a 5×5 square
centered on a 1×1 building — per the resolution note above, the floor
artifact of a circular gate at this small radius). A
useful consequence: these radius-2 squares tile the plane with **zero gaps
and zero overlap** when buildings are spaced exactly `(footprint + 2×range)`
apart on a grid — something true circular coverage at larger radii would not
give you. For `f_building3x2a` (3×2 footprint), that's a 7×6
tiling cell — 6 tiles for the building, 36 for resource nodes, fully
covered, no waste.

### TICKS_PER_SECOND = 5

User-confirmed as a stable engine constant, unlikely to ever change (many
things would break). Its *value* is defined nowhere in the Lua source
(engine-native, same category as `REG_INFINITE`) — the Lua files do
reference the `TICKS_PER_SECOND` global throughout (`get_work_time`'s
seconds conversion, `c_portable_radar`'s re-arm quirk), they just never
assign it. Cancels out of any ratio comparing two tick-based rates
(e.g. magnifier regen supply vs. mining demand), so it mattered less than
initially assumed for the throughput math above — it matters for converting
to real seconds, not for the relative comparisons.

### Regen vs. mining threshold — how many drones per node, and the oversubscription cap

Worked out 2026-07-11, doubly confirmed against real in-game measurements
(not just derived). Formula:

```
regen_rate_per_node   = magnifiers_in_range × reward / work_time_per_magnifier
drone_rate(resource)  = TICKS_PER_SECOND / mining_ticks_per_unit(resource)
threshold(drones/node) = regen_rate_per_node / drone_rate(resource)
total_drones(building) = threshold × (resource nodes actually within range)
```

For the 3x2 (1L3M) building (`f_building3x2a`) loaded out as 3 Medium
magnifiers + 1 Large Overclock + 4 Internal Overclock (`eff_boost = 100 +
150 + 4×20 = 330`, matching the building table's "12.90" figure exactly:
3 × (100+330)/100 = 12.9), plus one copy of the Global Overclocking Boost
(+5 everywhere): `eff_boost = 335`,
`tick_boost = (200*100+99+335)//435 = 46` ticks → **9.2s per magnifier
cycle** — an exact match to a real in-game stopwatch measurement (pause,
swap modules, unpause, read the progress widget), not an approximation.
`regen_rate_per_node = 3 × 1 / 9.2 = 0.326 units/s` (reward=1; a node
mid-cycle consuming an Anomaly Particle gets reward=3, tripling this).

Mining ticks/unit are per-resource, from `data/items.lua`'s
`mining_recipe[c_adv_miner]` — these differ by resource and one earlier
session's assumption that they were all "25 ticks" was wrong; always check
the specific item:

| Resource | ticks/unit | drone rate w/ 1 Internal OC + 1 Global OC (eff_boost=25), u/s | threshold drones/node | nodes/drone |
|---|---|---|---|---|
| Metal Ore | 15 | 0.417 (2.4s/unit, exact in-game match) | 0.782 | 1.28 |
| Crystal Chunk | 12 | 0.500 (2.0s/unit) | 0.652 | 1.53 |
| Silica Sand | 15 | 0.417 (2.4s/unit) | 0.782 | 1.28 |
| Blight Crystal | 25 | 0.250 (4.0s/unit) | 1.304 | 0.77 |

**The oversubscription cap of 2 in `MinerDrone` (previously just a guess) is
now a validated choice, not an arbitrary one**: every threshold above is
under 2, and Blight Crystal's 1.304 is the tightest — 2 is the smallest
integer cap that comfortably covers every resource type's real regen supply
without leaving a node's capacity chronically unclaimed. It does mean
Metal/Crystal/Sand have some slack (2 drones is somewhat more than the ~0.78
threshold strictly calls for), a deliberate safety margin rather than a
tight fit.

### Resource-node placement pattern: many small nodes beats surrounding one big node

User question, 2026-07-11: is it better to find one of the world's naturally
occurring 2x2/3x3 "rich" resource deposits (`v_metalrich1/2`, `v_crystal_rich1`,
`v_laterite_node_large1`, etc. — confirmed via `data/visuals.lua`'s
`tile_size` fields) and surround *it* with as many Magnifier buildings as
fit, or use the Virus Duplicator (`c_virus_duplicator`, `components.lua:9204`)
to lay down a pattern of ordinary small nodes within a single building's
range instead?

**Regen doesn't care about a node's footprint size**: the Magnifier's
`on_update` calls `AddResourceHarvestItemAmount(e, reward, 200)` on every
`FF_RESOURCE` entity in range identically — a visually-3x3 rich deposit is
still exactly one entity, capped at exactly 200, getting exactly the same
flat per-cycle reward as a 1x1 duplicated node. Bigger natural deposits only
matter for their one-time starting yield before a Magnifier engages, not for
steady-state regen-fed throughput.

**Correction (2026-07-11, user pushback, both points valid):** an earlier
draft of this section argued extra buildings aimed at one node are
"wasted" past the oversubscription cap of 2. That's too strong. The cap
itself should scale with however much regen a given layout actually
delivers (see "make the oversubscription cap a parameter" below) — nothing
stops you from deploying more drones per node to match a denser building
layout, and multiple buildings *can* all have range reach a single node at
once (Chebyshev-2 only needs to reach *any* tile of it). Verified a concrete
user-proposed layout — 4 big (3x2, 3-magnifier) + 2 small (1x2, 1-magnifier)
buildings all covering one node — geometrically (tile-level placement check,
one building per quadrant + 2 small filling gaps, all at Chebyshev distance
≤2 from the node, zero overlaps) and numerically:
`regen = 4×(3/9.2) + 2×(1/16.4) = 1.426 units/s` (the 1x2 building's own
`eff_boost = 100 + 2×20(Internal OC) + 5(Global OC) = 145` → 16.4s/cycle,
slower per-magnifier than the 3x2's since it lacks the shared-3-ways boost
and the Large Overclock). That pushes the needed cap to 4 (metal/sand), 3
(crystal), 6 (blight crystal) — all higher than the flat "2" this doc
originally settled on.

**What *does* still hold, restated more precisely**: per magnifier invested
(the actual scarce, power-costing resource — Overclock modules are free to
run but each magnifier itself costs `power = -100`), concentrating buildings
on one node is markedly less efficient than spreading them across more
duplicated nodes, because Overclock's building-wide boost is strictly
per-building (`SumModuleBoosts(reg_owner, ...)` sums components sharing one
`comp.owner` frame, never pooling across separate buildings):

| Pattern | Magnifiers used | Nodes served | Regen/magnifier |
|---|---|---|---|
| 1 big building (3M1L), 6 packed nodes | 3 | 6 | **0.652/s** |
| 4 big + 2 small buildings, 1 node | 14 | 1 | 0.102/s |

Roughly a 6-7x gap. Every extra building on an already-covered node pays its
own full construction-and-Overclock cost for a comparatively small marginal
regen increment, when that same building would deliver its *full*
independent rate to a whole new set of nodes elsewhere. So: default to
spreading buildings across many duplicated nodes; concentrating several
buildings on one node is a real, usable option (not "wasted," once the
oversubscription cap is scaled to match), but reach for it only when land or
blighted-terrain area — not building count — is the actual binding
constraint.

**The Virus Duplicator's own spacing rule caps how tightly nodes can be
packed**: placement is blocked whenever `Map.FindClosestEntity(coord, 2, ...,
FF_RESOURCE)` finds *any* existing resource entity within Chebyshev distance
2 of the target spot (`components.lua:9309`) — so nodes must be at least
Chebyshev-3 apart. A regular 3-tile-spaced grid is the densest pattern that
satisfies this (any tighter grid puts some pair within distance 2) and packs
exactly onto one building's own 7×6 Chebyshev-2 coverage cell (3 columns × 2
rows = **6 node slots**), positioned to clear the building's own 3×2
footprint entirely — e.g. columns at offsets {0,3,6} and rows at {1,4} within
the 7-wide/6-tall coverage rectangle, with the building centered at columns
2-4/rows 2-3, leaves all 6 grid points on open ground. With 6 independently-
regenerated nodes instead of 1, total sustainable drones per building scales
by that same factor of 6 (e.g. Blight Crystal: 6 × 1.304 ≈ 7.8 drones instead
of 1.3). The Virus Duplicator itself must physically move within range 1 of
each target coordinate to place a node there (`RequestStateMove(coord, 1)`,
`components.lua:9306`), so filling all 6 slots is a one-at-a-time manual
placement process, not a single action.

**Make the oversubscription cap a parameter, not a hardcoded constant**
(user idea, 2026-07-11): since the right cap depends entirely on how densely
a given site is built out (2 for one shared building, up to 9 for the final
lattice below), `MinerDrone`'s current hardcoded local cap should instead be
read from whatever `MagnifierSignal` broadcasts — e.g. packed into the
demand signal's own `num` field alongside the existing id-as-resource-type
convention — rather than assumed fixed. Not yet implemented.

### The final confirmed design: a real blueprint, `library/magnifier_lattice.dcs`

The user built this directly in-game and pasted the resulting blueprint
(`.dcs` wire type `B`) rather than describing it in prose — decoded via
`LupaEngine.decode_dcs` (blueprints decode to a `{multi, dependencies}`
shape; `desynced_toolkit.bsf`'s own CLI only handles type `C`/behaviors, so
this needed a direct script rather than the `bsf` command). It's one 8-building
unit, meant to be tiled by repeating with a 1-building overlap in whichever
direction you expand it (i.e. shift by exactly one big building's width/height
so the new copy's edge building coincides with the existing structure's edge
building):

| # | Frame | Position (x,y) | Notes |
|---|---|---|---|
| 1-3, 6-8 | `f_building3x2a` (3M1L, 3-wide×2-tall) | (0,0) (3,0) (6,0) (0,3) (3,3) (6,3) | 3× `c_blight_magnifier` + 1× `c_moduleefficiency_l` (Large OC) + 4× `c_moduleefficiency` (Internal OC) each |
| 4-5 | `f_building2x1c` (native 1×2, **rotation=1** → 2-wide×1-tall) | (2,2) (5,2) | 2× `c_blight_magnifier` + 4× `c_moduleefficiency` (Internal OC) |

**Correction to the small-building stats used in this doc up to this point**:
the small building is `f_building2x1c` ("Building 2x1 (**2M**)", `component_boost
= 20`, 2 Medium + 4 Internal sockets) confirmed from its real component list
— not `f_building2x1d` ("Building 2x1 (1M)", `component_boost = 100`, 1
Medium + 2 Internal) assumed earlier from the building table alone without
checking a real placed instance. `f_building2x1c`'s `eff_boost = 20 (component_boost)
+ 4×20 (Internal OC) + 5 (Global OC) = 105` → `tick_boost = (200*100+99+105)//205
= 98` ticks → 19.6s/cycle → with 2 magnifiers, **0.102 units/s per small
building** (was wrongly computed as 0.061/s using the wrong building).

**Node placement rule** (also user-confirmed, not derivable from the
blueprint itself — resource nodes are world-owned entities, never part of a
player blueprint): one node at the center tile of each big building's two
*3-length* edges (top and bottom, for the unrotated 3-wide×2-tall
orientation) — e.g. building `(0,0,3,2)` gets nodes at `(1,-1)` and `(1,2)`
(`1` = the middle of columns 0-2). Adjacent buildings' node positions
coincide (building `(0,3,3,2)`'s own top-edge node is also `(1,2)`), which is
exactly why a 6-building block only produces 9 distinct nodes, not 12.
Verified by direct computation against this exact 8-building unit (no
additional tiling): coverage-per-node comes out to `[2,4,2,3,6,3,2,4,2]` —
four nodes with 2 covering big buildings, two with 3, two with 4, one with
6 — an exact match to the user's own count, confirming both the node-position
rule and the tiling-overlap rule are right.

**Steady-state (fully interior, tiled indefinitely) coverage is 6 big + 2
small per node** — the center node (`cov_big=6`) in the single-unit snapshot
above is already showing what every node converges to once surrounded on all
sides by further copies; the lower counts (2/3/4) are edge-of-snapshot
artifacts of only placing one unit. This supersedes the earlier "4 big + 2
small" figure in this doc, which came from a different, incidentally-thinned
lattice (`(i+2j) mod 3 ≠ 0` on a period-3 grid) explored before this real
blueprint existed — the user's actual design doesn't thin big buildings at
all.

**Final regen and threshold numbers**, using the corrected building stats and
the confirmed 6-big/2-small steady state:

```
regen/node = 6×(3/9.2) + 2×(2/19.6) = 6×0.3261 + 2×0.1020 = 2.161 units/s
```

| Resource | drone rate (u/s) | threshold (drones/node) | cap needed |
|---|---|---|---|
| Metal | 0.417 | 5.19 | 6 |
| Crystal | 0.500 | 4.32 | 5 |
| Sand | 0.417 | 5.19 | 6 |
| Blight Crystal | 0.250 | 8.64 | 9 |

Substantially higher than every earlier estimate in this doc — this lattice
is dense and genuinely high-throughput. Not yet tested in-game as a running
setup (drones + this exact blueprint + duplicated nodes at the confirmed
positions together) — see the oversubscription-cap-as-parameter item above,
now necessary rather than a nice-to-have, since a hardcoded `2` would
leave the large majority of this design's regen capacity unused.

### Obsidian and Laterite: neither is mineable by `c_miner`/`c_adv_miner` at all

Discovered 2026-07-12 while planning the drone economy for these two
resources: both are absent entirely from `c_miner`'s and `c_adv_miner`'s side
of `mining_recipe` in `data/items.lua` — not a range/filter issue, the
components have no recipe entry for either. The only things that can mine
them:

- **`c_extractor`** ("Laser Extractor") — the only *real, placeable*
  option: `attachment_size = "Medium"`, not `Hidden`, so it drops into any
  free Medium socket on a building or mobile unit. Mines both (Obsidian 50
  ticks, Laterite 30 ticks, `data/items.lua`).
- **`c_human_miner`**, built into two dedicated Human-race ground units
  (Human Miner Mech `f_human_miner`, and its upgrade Miner Mech
  `f_human_adv_miner`, both `movement_speed=3`) — `attachment_size =
  "Hidden"`, whole-unit only, can't be equipped elsewhere. ~~Both are
  slot-less~~ **Corrected 2026-07-14 (user observation, confirmed in
  `visuals.lua`): only `f_human_miner` (the explorable-awarded frame) is
  slot-less; the buildable `f_human_adv_miner` has one Internal socket
  (plus a frame-level `component_boost = 50`), so it can host its own
  behavior controller.** The remote-control ("Foreman") idea below is
  therefore specifically for the free explorable mechs and the slot-less
  alien miners.
- **`c_alien_miner`**, built into two Alien-race ground units in the data —
  but in practice only the Drill Spike (`f_alien_miner`) exists: "Alien
  Unit" (`f_alienbot`)'s tech unlock is commented out in `tech_alien.lua`
  (corrections 2026-07-14). The Drill Spike is **not** slot-less: 1 Internal
  socket (self-hosts a Behavior Controller) plus frame-level
  `component_boost = 300` — which likely invalidates this doc's later
  "extractors are much slower" pacing assumption for the alien-miner path;
  and it's garage-dockable, so Reformation-Core synthesis can add 1 Small +
  4 Internal more.
- **`c_virus_claws`** — Obsidian only; carried by the **Ravager**
  (`f_gastarid1`), which *is* player-buildable via the virus tech tree
  (hive-spawner recipe) — corrected 2026-07-14 from "not player-usable."
  Unsuitable for most use though: the conversion of mined obsidian into
  infected obsidian is done by a *separate* integrated component on the
  same frame, `c_ravager_virus_converter` (hidden attachment — can't be
  removed or turned off), not by the claws themselves (user-observed,
  component confirmed in `f_gastarid1`'s definition). (The flying Mothika carrier remains
  hostile-only.)

**No flying frame can mine either resource** — confirmed by checking every
frame carrying one of these four components; none has `cost_modifier = 0`
except the hostile Virus creature.

### Obsidian/Laterite need a much sparser magnifier pattern than the other four resources

The dense 6-big/2-small lattice above (built to feed fast, Overclock-boosted
`c_adv_miner` drones at 0.4-0.5 units/s) badly oversupplies `c_extractor`,
which is much slower (`c_extractor` inherits `c_miner`'s own
`SetStateStartWork` call, so it gets the same native `eff_boost` treatment
confirmed above — computed here with the extractor sharing its own
building's `eff_boost=105`, one Internal-Overclocked small building):

```
Obsidian: 1 extractor = 0.200/s, 2 extractors = 0.400/s
Laterite: 1 extractor = 0.333/s, 2 extractors = 0.667/s
```

Against the dense lattice's 1.956 units/s/node (6 big buildings' regen
alone, since repurposing the small buildings' Medium sockets for extractors
means they no longer regen anything), even 2 extractors fall short by
4.9x (Obsidian) to 2.9x (Laterite) — regen would pin most nodes near the 200
cap almost permanently, wasting most of the invested magnifier capacity.
Matching this properly would need ~6 (Laterite) to ~10 (Obsidian) Medium
sockets' worth of extractors per node — far more than 2 small buildings
provide.

The **sparse** pattern (one 3M1L building serving its own dedicated 6 packed
nodes, not shared with 5 other big buildings — the very first pattern this
doc worked out, `0.326` units/s/node) is a much closer match: 1 extractor
per node is close to exact for Laterite (`0.326` regen vs `0.333` demand,
regen slightly under) and reasonably close for Obsidian (`0.326` vs `0.200`,
some regen margin/slack rather than a mismatch). Not yet turned into a
concrete buildable layout — see `todo.md`'s "Magnifier / drone-swarm design"
section.

### A live behavioral bug found downstream: haulers interacting with units broadcasting a resource node or dropped item

`library/hauler.dcs`'s `for_signal_match(Signal=Resource, ...)` (used to
find drones/buildings broadcasting resource pickup/dropoff demand) can also
match a unit whose *own* broadcast happens to embed a resource-node or
dropped-item entity for an unrelated reason — traced to `for_signal_match`'s
own internal fallback (`instructions.lua:~2498`): a candidate whose signal
value carries an `entity` field gets tested against `FilterEntity` too. Two
concrete real sources of this, both confirmed in-game: (1) `MinerDrone`
itself deliberately broadcasts `set_reg(Value=$Best, Target=@signal)` where
`$Best` is the resource *node* it's mining (for oversubscription counting —
working as intended for that purpose, but a false positive for the hauler);
(2) the `Observer` behavior (`tests/data/observer.dcs`, also loaded on
stationary power-pole buildings, not just mobile scouts) broadcasts
`set_reg(Value=$A, Target=@signal)` where `$A` is the raw result of
`scan(Filter 1=v_droppeditem, ...)` — an entity-embedded *dropped item pile*
reference, for completely unrelated reasons (informational only).

**Getting the fix right took three attempts, worth recording precisely
since the filter names are misleading:**

1. `match(Unit=$Signal, Filter=v_mineable)` (`v_mineable = FF_RESOURCE`) —
   rejects the resource-node case but does nothing for the dropped-item
   case (`v_mineable`'s bitmask has no `FF_DROPPEDITEM` bit).
2. `match(Unit=$Signal, Filter=v_resource)` (`v_resource =
   FF_RESOURCE|FF_DROPPEDITEM`) — looks like it should cover both from the
   bitmask alone, but **doesn't**: `FilterEntity`'s own per-entity check for
   `v_resource` (`fnum==7`, `data/utilities.lua`) is `ok = edef.type ==
   "Resource" or edef.name == "Scattered Resource"` — a narrower,
   *additional* requirement layered on top of the bitmask pre-check. An
   ordinary dropped item pile (`def.type == "DroppedItem"`, not
   `"Resource"`, and not specifically named `"Scattered Resource"`) fails
   this narrower check and is never rejected — confirmed in-game, `v_resource`
   alone still let haulers deliver to Observer.
3. A working intermediate fix: two separate, sequential `match` checks
   (`v_droppeditem` then `v_resource`), since `match`'s multiple filter args
   are AND-combined, not OR — one call can't express "reject if either
   condition holds." This worked (confirmed in-game) but needed two
   instructions and relied on knowing the specific entity types involved.

4. **The actual, final fix — one instruction, and root-cause rather than
   type-enumeration:** `compare_item(Value 1=Resource, Value 2=$Signal) →
   If Different → reject`. This doesn't check entity types at all; it
   checks whether `$Signal.id` equals the `Resource` parameter. Tracing
   why that's sufficient: in `for_signal_match`'s fallback branch
   (`instructions.lua:~2498`), the output's `id` field is always just
   `unit_sig.id` passed through unchanged — and both false-positive sources
   (`MinerDrone`'s node-embedding broadcast, `Observer`'s dropped-item-embedding
   one) only ever set `.entity` on their own signal, never `.id` (the
   engine's entity/id/coord mutual-exclusivity rule means a value with
   `.entity` set has `.id = nil`). So *every* fallback-matched candidate
   has `Signal2.id == nil`, regardless of what type of entity got embedded
   — while a genuine direct broadcast (`MagnifierSignal`'s
   `set_number(Value=Resource, Number=0, Result=$Sig)`) hits
   `for_signal_match`'s direct-match path and has `Signal2.id` genuinely
   equal to `Resource`. One equality check on `.id` separates "real
   id-based broadcast" from "only matched via the entity-embedded
   fallback," with no dependency on enumerating entity types — it would
   keep working even if some future behavior embeds a different kind of
   entity into its own signal for its own unrelated reasons. Applied at
   both the pickup-search (`n43`) and dropoff-search (`n79`) locations in
   `library/hauler.dcs`, replacing the two-`match` intermediate fix;
   verified via semantic-diff to be the only change at each site.

## Part 2: Miner-drone behavior design

### Native mechanics confirmed this session (source-cited, several corrected mid-session)

- **`get_distance` against a multi-tile entity (e.g. a building) measures to
  its closest tile, not a center point** — user-confirmed 2026-07-12, not
  visible from source (`get_distance` just delegates to the native
  `Map.GetDistance`). Caused a real bug in `MinerDrone`: a loose building-approach distance
  check (`Compare=8`) combined with a narrower node-search range
  (`Range=5`) meant the drone's "arrived" state could be satisfied near one
  edge of a large building while nodes on the *opposite* side (footprint
  width + magnifier range further away) sat outside the search range —
  fixed by tightening the dock distance to `Compare=1` and widening the
  search to `Range=8`, regardless of which side the drone approaches from.
  **Contrast, also user-confirmed:** `get_location(Unit=X)` gives a
  *different* point — the entity's center tile (`ent.location`, itself a
  native/opaque property per `get_location`'s own Lua), rounding **up** in
  each dimension when the true center falls between two tiles (any even
  footprint dimension, e.g. 2x2/2x3). So `get_distance` straight on an
  entity and `get_distance` on a coordinate obtained via `get_location`
  first are genuinely different measurements for the same multi-tile
  target — closest-tile vs. center-tile — not interchangeable.
- **Mining recipe rates** (`data/items.lua:661-673`, `blight_crystal`):
  `c_miner` = 50 ticks/unit, `c_adv_miner` = 25 ticks/unit (Advanced Miner
  Drone is 2x faster) — always prefer the Advanced Miner Drone. Stack size
  20.
- **A resource node mined to exactly 0 can never be revived.**
  `AddResourceHarvestItemAmount` (`utilities.lua:575-582`, its own comment:
  `-- make sure result is > 0!!`) guards on `num > 0` before adding anything
  — once a node's remaining register hits 0, the Magnifier's regen call
  silently no-ops forever. This is why a "never mine below a floor" behavior
  isn't just an optimization, it's what keeps the node alive at all.
- **`c_behavior` (Behavior Controller) is an ordinary Internal-sized
  component** (`components.lua:3883-3889`, *"Additional small, low-powered
  programmable device. Can be added to units and buildings without an
  integrated behavior controller"*), not something exclusive to "robot" race
  frames with an intrinsic slot. Any frame with a free Internal socket — the
  Miner Drone and Advanced Miner Drone both have 2 (`visuals.lua:557-577`,
  their `c_miner`/`c_adv_miner` is marked `"hidden"` and doesn't consume a
  socket) — gets the full visual Program editor by socketing one in.
- **`drone_range` only gates the native, automatic port-side job-dispatch
  system, not a Program-controlled unit.** `c_miner:on_update`'s own
  auto-target search (`components.lua:2351`) uses
  `owner.has_movement and owner.visibility_range or miner_range` —
  `drone_range` never appears in it at all. A drone with its own Behavior
  Controller isn't leashed to its port's range; it's bounded by whatever its
  own Program does.
- **The store register auto-delivers cargo with no range limit at all**, and
  — the refinement added late in this session — **it automatically resumes
  the previous mining target once storage completes, and kicks in whenever
  nothing else is actively controlling the unit**, including with *no*
  Program installed at all (confirmed: manually setting the mine-target and
  store-target registers via the UI, unconnected to any logistics network,
  is sufficient for a perpetual mine → go-store-when-full →
  auto-resume-same-target cycle with zero scripting). This meant an earlier
  draft of the mining sub-loop (which re-invoked the `mine` instruction every
  recheck cycle) was doing unnecessary work — `mine` only needs to be called
  once, to establish the target; after that the native cycle runs itself,
  and the Program's only remaining job is periodically checking whether the
  live remaining amount has crossed the 100-unit floor, at which point it
  should switch targets.
- **Drone-holding components (`c_drone_port`, `c_drone_comp`, etc.) can be
  nested inside other moving units** — user-confirmed working in-game,
  correcting an earlier guess (based on there being no Lua-visible precedent
  for a mobile anchor point) that this might not function correctly.
- **The Goto frame register (`@goto`, `FRAMEREG_GOTO`) is a sibling
  mechanism to the store register above — persistent, native, no `domove`
  call needed.** User-confirmed (2026-07-10, reviewing two real deployed
  behaviors — "Mining Leader V3.2" and its follower "Miner V1.3.4," both
  drive `@goto` directly rather than calling `domove`): writing an
  entity-or-coordinate-plus-`num` value straight to `@goto` sets a
  *persistent* move-to intent the native per-tick unit AI keeps re-pursuing
  on its own — including continuing to track a moving target — until
  something else overrides it (an explicit `domove` call, or a controlling
  component like the miner). `num` is the arrival tolerance, exactly
  matching `domove`'s own "Target" argument semantics (`instructions.lua`'s
  own arg description: "the number specifies the range in which to be
  in") — confirmed these are conceptually the same *value* even though
  they're mechanically separate: `domove`'s own `func`
  (`instructions.lua:5111-5135`) calls native `ent:MoveTo`/
  `comp:RequestStateMove` directly with the target and range, and does
  **not** touch `FRAMEREG_GOTO` at all — writing the register directly is a
  genuinely different, parallel mechanism, not a documented alias for
  calling `domove`. **Resolved 2026-07-11, via source, no in-game test
  needed**: "transport route" isn't a special mode of `@goto` itself — it's
  a separate flag (`entity.logistics_transport_route`, toggled by the
  `enable_transport_route`/`disable_transport_route` instructions,
  `instructions.lua:4398-4422`) whose tooltip (`data/data.lua:237`) says it
  plainly: "Continually pick up from Goto and deliver to Store. Requires
  both Goto Register and Store Register to be set." With it enabled, the
  unit shuttles automatically between `@goto` (pickup) and `@store`
  (delivery) instead of just moving to `@goto` once.
- **Drones can be produced by a plain Robotics Factory**, not only by
  drone-port-family components — `c_robotics_factory = 100` is already
  listed as an equally-valid crafting station in both `f_drone_miner_a`'s and
  `f_drone_adv_miner`'s `production_recipe` (`frames.lua:1883`, `1903`),
  alongside `c_drone_port`/`c_drone_comp`/`c_drone_launcher`. Nothing about
  the drone-mining design requires building anything port-shaped at all.
- **A resource node's own registers cannot be written to from a Program.**
  The only remote-write instruction, `set_reg_remotely`
  (`instructions.lua:6849`), gates through `GetAdjacentFactionEntityOrSelf`
  (`instructions.lua:302-316`), which requires the target to be same-faction
  (a neutral resource node never qualifies) *and* physically touching
  (unless the caller is specifically an AutoBase controller, which gets a
  same-logistics-network exception instead). This ruled out an earlier idea
  of marking a node "claimed" by writing directly to it — that capability
  only exists in the engine's own native Lua (e.g. the Magnifier's
  `entity:SetRegisterNum(...)` calls), not in the player-facing instruction
  set. Reading an arbitrary entity's data (e.g. `Get Resource Num`) has no
  such restriction — only *writing* to something you don't own is gated.
  Writing to your *own* other components (`set_comp_reg`, "Set to
  Component") is unrestricted, since it never takes a target-entity argument
  at all — it only ever resolves against `comp.owner`.
- **`FRAMEREG_SIGNAL` + `faction:GetEntitiesWithRegister` is a real,
  purpose-built, faction-wide (no range limit at all) coordination
  mechanism**, exposed via the `Loop Signal` instruction
  (`for_signal_match`, `instructions.lua:2417-2508`) — exactly the
  broadcast-which-node-a-drone-is-working-on mechanism needed to let other drones
  check for oversubscription, once the direct-node-write idea above was
  ruled out. A drone writes its own Signal register to `{entity =
  target_node}` (a write to itself, always legal); any other drone runs
  `Loop Signal` with that same entity as the query and gets every faction
  unit (anywhere on the map) currently signaling it, with a simple iteration
  count deciding "already oversubscribed."
- **`mine` does not itself block the calling behavior.** Its `func`
  (`instructions.lua:5547-5651`) falls through without `SetStateSleep`/
  `return true` on the happy path; movement/mining progress is driven
  entirely by `c_miner`'s own separate on_update cycle. What *does* throttle
  execution is the per-tick dispatcher itself
  (`c_behavior:on_update`, `components.lua:4027-4090`): a "locked" behavior
  (`state.limit or 1`) runs exactly one instruction per tick regardless,
  which naturally paces a `mine → check → loop` cycle correctly. An
  "Unlocked" behavior has no such throttle — the same loop would spin
  uselessly fast, seeing an unchanged value every iteration (mining doesn't
  advance within the instruction dispatch itself), and would hit
  `"Unlocked behavior exceeded instruction limit for a single step"`. An
  explicit `wait` between establishing the mine target and rechecking it is
  correct insurance regardless of lock state, not just an unlocked-mode fix.
- **`mine`'s real value over driving the miner's register directly**: it
  bundles four decisions as explicit branches your Program can react to
  (path blocked → `Cannot Mine`; unpowered → `Cannot Mine`; already carrying
  the requested amount → `Full`; no cargo space → `Full`) that a raw
  register write (via a Link Editor wire or `set_comp_reg`) does not surface
  to your own instruction flow — the underlying component still behaves
  sensibly either way, but only `mine` tells *you* about it. It also applies
  to every `c_miner` component on the entity at once and avoids redundant
  register writes via its own before/after comparison.
- **`mine`'s `Num` argument is checked against total current inventory
  (`owner:CountItem`), not "amount extracted from a specific target"**
  (`instructions.lua:5601-5610`). This makes it a poor fit for enforcing a
  per-node floor: the store-register auto-deliver cycle above resets
  `CountItem` every time cargo is delivered, so a `Num` threshold sized to
  "stop once this node hits the floor" can fire early (leftover cargo of the
  same item from elsewhere already counts toward it) or effectively never
  fire from a single node's depletion (a mid-mining delivery resets the
  counter before the threshold is reached). Considered and rejected as the
  stopping mechanism for the floor design below — see the register-link
  bullet immediately after this one.
- **Components explicitly defer to a register link rather than fighting
  it.** The guard `if not comp:RegisterIsLink(1) then ... end` (or
  equivalent) recurs roughly 15 times across `components.lua`, always
  gating a component's own convenience writes/clears to register 1 — e.g.
  `c_miner`'s own entity-to-id conversion (`components.lua:2432`, `:2442`).
  When the register is link-driven, the component either leaves it alone
  entirely or, in a couple of cases (`components.lua:9323`), flags a
  register error instead of clearing it itself. Practically: wiring a
  behavior's declared output parameter directly to a component's register
  via the Link Editor (one-to-many — a single linked parameter can drive
  every `c_miner`/`c_adv_miner` on an entity at once, confirmed working by
  the user from prior hands-on use) gives a Program more reliable control
  over register 1 than going through `mine`. Writing to the link is
  indistinguishable, from `c_miner`'s side, from a player manually editing
  the register; clearing it (writing `nil`) hits the same plain `if not
  reg1_num then ... return comp:SetStateSleep() end` shutdown path
  (`components.lua:2259-2263`) as any other empty-register case — with none
  of `mine`'s `Num`/`CountItem` coupling above, and none of its per-call
  entity-equality dedup-on-write behavior (`instructions.lua:5615-5635`,
  which silently drops a `Num` change on a call that keeps the same target
  entity/id — a real trap for a "detect the stop, bump the limit, keep
  going" design built directly on top of `mine`).
- **"Loop Nearby Resources" (`for_count_resources`) aggregates by resource
  *type*** (total amount summed across all matching nodes in range), **not
  per individual node** — the wrong instruction for candidate-by-candidate
  scanning, a mistake made mid-session while first describing this design in
  prose and only caught once actually building the graph (see below). The
  correct per-entity iterator is **"Loop Units (Range)"**
  (`for_entities_in_range`, `instructions.lua:869-897`) with
  `Filter=v_resource`.
- **`c_miner`'s register 2 is a live, read-only status readout: the entity
  currently being mined plus its remaining resource amount** — user-reported
  2026-07-11, confirmed against source. The component's own schema
  (`components.lua:2205`) declares it `{ read_only = true, tip = "Resource
  mining" }`; it's written every time mining starts or advances a step
  (`components.lua:2396`, `:2519`) as `comp:SetRegister(2, { entity = target,
  num = target:GetRegisterNum(FRAMEREG_GOTO) })` — a resource node stores its
  own remaining amount in its `FRAMEREG_GOTO` register (confirmed by the
  adjacent `target:SetRegisterNum(FRAMEREG_GOTO, amount - 1)` decrement at
  `components.lua:2517`), so register 2's `num` field is always the node's
  current remaining count, live, with no separate polling instruction needed.
  This is distinct from register 1 (the mine-*target*-setting register
  `MinerDrone` drives via the Link Editor, described above) — register 2 is
  read-only telemetry about whatever register 1 is currently driving the
  component to mine. **Possible simplification for `MinerDrone`, not yet
  acted on**: the current design tracks remaining amount by separately
  calling `get_resource_num` against a remembered `$Best` entity (`n34`/`n35`
  in the current graph) — reading register 2 directly (`get_reg`/component
  register read against this drone's own `c_miner`) could replace that
  separate poll with the component's own live value instead, since it's
  already being kept current by the engine on every mining tick. Left as a
  follow-up, not redesigned here without confirming register-read access
  from a Program to a component's own register works the way this assumes.

### The MinerDrone behavior (real BSF, compiled and validated)

**Rewritten 2026-07-11** in `behavior_source_format.md`'s real, current
grammar (the earlier pseudocode below predated the actual `desynced_toolkit
.bsf` parser/compiler) and, unlike the original draft, genuinely **compiled
and round-tripped through the real toolkit**: `bsf compile` → real `.dcs` →
`bsf decompile` byte-identical, confirmed against raw wire data (not just
the decompiler's own rendering), and the mermaid render collapses to a
single connected component from Program Start — a real structural sanity
check, not just "it didn't crash." Saved as `miner_drone.dcs` (workspace
root) — not yet tested in-game.

This revision also adds the second parameter (`Resource` — which item type
to mine, doubling as the signal id to watch for building demand, same
single-parameter convention `Fendersons Transport`'s Hauler already
established for its own `Resource` param) and the outer building-seek loop,
closing two of the "Known gaps" the original draft left open.

Three real bugs were caught and fixed authoring this version, all worth
recording since they're easy to reintroduce by hand:

1. **A genuine deadlock in the (separately-authored) `MagnifierSignal`
   companion behavior, caught by the user**: an earlier draft used a single
   200-cap threshold to drive *both* the power-management decision (should
   the magnifier keep regenerating) *and* the drone-invitation signal
   (should drones come mine here). An abundant, never-mined area (every
   node already above 200) would conclude "nothing needs regen" and clear
   its own signal *and* shut down — permanently starving itself of drones,
   since nothing would ever flip that condition back. Fixed by tracking two
   independent flags per poll cycle (`$NeedsRegen` against the 200 cap,
   `$Mineable` against the 100 floor) and gating power and signal off each
   independently — see `MagnifierSignal` below.
2. **Omitting a loop instruction's own `Done` pin does not "skip past the
   loop body"** — confirmed directly against a minimal compiled test case
   (not just documentation): an omitted `Done` resolves to the wire
   position immediately following *the loop instruction itself* (its own
   body's first instruction), per the same universal omission-is-positional
   convention documented in `behavior_format.md`'s "Branch and fall-through
   resolution" — there is no loop-aware special case. All three
   `for_signal_match`/`for_entities_in_range` loops in the first draft of
   this behavior (and the one in `MagnifierSignal`) omitted `Done` assuming
   it would naturally fall through to after the loop; all four needed an
   explicit numeric target instead. This is exactly why the mermaid render
   initially split into 4 (`MinerDrone`)/2 (`MagnifierSignal`) disconnected
   components — forward-reachability from Program Start genuinely couldn't
   reach the rest of the graph through a `Done` pin pointing back into its
   own loop body — and collapsing back to one component after the fix is
   the concrete confirmation the fix was real, not cosmetic.
3. **A real signal-protocol collision with `Mining Leader`/`Mining
   Follower`, caught by the user**: the first draft had `MinerDrone`'s Seek
   loop search for `{id: Resource, num: 0}` (matching `MagnifierSignal`'s
   own broadcast), using `for_signal_match`'s default "Match" filter mode —
   which only checks `id`, never `num` at all. But `Mining Leader`'s own
   `Monitor mine` state (`set_reg(Value=Resource, Target=@signal)`) and the
   Hauler-facing pickup convention `Fendersons Transport` depends on
   *already* use `num=0` on this exact same `Resource` id to mean "available
   for pickup" — a completely different, mobile-squad-facing
   meaning. A drone would have genuinely traveled toward a roaming mining
   gang mid-pickup-broadcast, mistaking it for a stationary mining site.
   Fixed by reserving `num=-1` exclusively for the drone-facing "come mine
   here" signal (never used by the Hauler-facing `num=0`/`num>0`
   pickup/dropoff convention) and using `for_signal_match`'s "Exact" filter
   mode (`c=2`) to match it precisely — confirmed in the compiled wire data
   (`"c": 2`), not just the source text.
4. **A silent arg-clobber caught by this project's own round-trip
   discipline**: `is_same_grid` (added for the grid constraint below)
   genuinely declares two args both literally named "Unit" in the game data.
   Writing `is_same_grid(Unit=$Self, Unit=$Cand)` in BSF text — repeating
   the bare name instead of using the occurrence-disambiguated `Unit2` — let
   the second assignment silently overwrite the first in `parse_node`'s args
   dict. It compiled and round-tripped with *no error at all*; the decoded
   wire showed `$Cand` in position 1 and **nothing** in position 2 — `$Self`
   silently discarded. Since `is_same_grid` treats an empty second unit as
   "no match," this would have rejected every candidate, always, with a
   clean compile. Caught because the *decompiled* text visibly had one arg
   instead of two, prompting a raw wire-data check — see
   `reference_bsf_duplicate_arg_name_silent_clobber` (project memory) for
   the general pattern. Fixed by using `Unit2` for the second occurrence,
   matching the same disambiguation convention `for_entities_in_range`'s
   `Filter`/`Filter2`/`Filter3` already established.

**A hard constraint, not a preference, discovered discussing this with the
user**: drones have no capacitor and become extremely slow the moment they
leave their power grid's coverage — so a drone must *never* travel to a
target outside its own grid, not just prefer to stay within it. This
applies to both candidate searches: a `MagnifierSignal` building found via
Seek, and — less obviously, but still a real risk given `Range=5` — a
resource node found via the local Mine search, if the node happens to sit
just past the grid's edge. `is_same_grid(Unit, Unit2)` (checks
`power_grid_index` on both entities, falling back to coordinate-based grid
lookup for non-grid-connected entities — which is *why* it also happens to
reject Mining Leader/Follower on its own, since a roaming bot has no
`power_grid_index` at all) gates both.

> **Grammar note (2026-07-14):** the BSF listings in this document (this `MinerDrone` and the
> `MagnifierSignal` further down) predate the explicit-pin rule — BSF now requires every exec
> pin of a 2+ pin op to be written (`>node`/`>POP`/`>NEXT`, see `behavior_source_format.md`
> § "Explicit-pin rule"), so these listings no longer parse verbatim. They're kept as the
> design record; the live, evolved versions are `library/miner_drone.dcs` /
> `library/magnifier_signal.dcs` — decompile those for current, parseable text.

```
behavior MinerDrone(Resource, MineTarget*):
  desc: "Find a building broadcasting demand for Resource via the drone-only signal (id=Resource, num=-1 -- deliberately distinct from the Hauler-facing num=0/num>0 pickup/dropoff convention Mining Leader/Follower and Fendersons Transport already use on this same Resource id, so a roaming mining squad offering pickup is never mistaken for a stationary mining site), travel there, then reservoir-sample a nearby resource node of that type above the 100-unit floor (skipping oversubscribed nodes via Signal broadcast), mine it down to the floor by driving the register-linked MineTarget parameter directly (link MineTarget to register 1 of every c_miner/c_adv_miner on this drone via the Link Editor -- no mine() call), then repeat. Both candidate searches reject anything outside this drone's own power grid -- drones have no capacitor and become extremely slow off-grid, so leaving grid coverage is never acceptable, not just suboptimal. Falls back to re-picking a building whenever no valid local candidate is found."

n1: label(Label=v_arrow_right, cmt="Seek: find a building signaling demand for Resource")
n2: set_reg(Value=0, Target=$BldRoll)
n3: set_reg(Target=$Bldg)
n4: get_self(Unit Reference=$Self)
n5: set_number(Value=Resource, Number=-1, Result=$SeekSig, cmt="Drone-only signal value -- num=-1 never collides with the Hauler-facing num=0 (pickup)/num>0 (dropoff) convention")
n6: for_signal_match(Signal=$SeekSig, Unit=$Cand, c=2)  >n12 (Done)
n7: is_same_grid(Unit=$Self, Unit2=$Cand)  >POP (Different)
n8: random_number(Min=1, Max=1000, Result=$Roll)
n9: check_number(Value=$Roll, Compare=$BldRoll)  >POP (If Smaller) >POP (If Equal)
n10: set_reg(Value=$Roll, Target=$BldRoll)
n11: set_reg(Value=$Cand, Target=$Bldg)  >POP (next)
n12: is_empty(Value=$Bldg)  >n14 (Has Value)
n13: wait(Time=20)  >n1 (next)
n14: set_number(Value=$Bldg, Number=4, Result=@goto)
n15: wait(Time=5)
n16: get_distance(Target=$Bldg, Distance=$Dst)
n17: check_number(Value=$Dst, Compare=8)  >n15 (If Larger)
n18: label(Label=c_radar, cmt="Mine: reservoir-sample a nearby node of the right type")
n19: set_reg(Value=0, Target=$BestRoll)
n20: set_reg(Target=$Best)
n21: for_entities_in_range(Range=5, Filter=v_resource, Filter2=Resource, Unit=$Node)  >n33 (Done)
n22: is_same_grid(Unit=$Self, Unit2=$Node)  >POP (Different)
n23: get_resource_num(Resource=$Node, Result=$Amt)
n24: check_number(Value=$Amt, Compare=100)  >POP (If Smaller) >POP (If Equal)
n25: set_reg(Value=0, Target=$Count)
n26: for_signal_match(Signal=$Node, Unit=$SigUnit)  >n28 (Done)
n27: add(To=$Count, Num=1, Result=$Count)  >POP (next)
n28: check_number(Value=$Count, Compare=2)  >POP (If Larger)
n29: random_number(Min=1, Max=1000, Result=$Roll)
n30: check_number(Value=$Roll, Compare=$BestRoll)  >POP (If Smaller) >POP (If Equal)
n31: set_reg(Value=$Node, Target=$Best)
n32: set_reg(Value=$Roll, Target=$BestRoll)  >POP (next)
n33: is_empty(Value=$Best)  >n35 (Has Value)
n34: jump(Label=v_arrow_right)  >POP (next) >n1 (jump→label)
n35: set_reg(Value=$Best, Target=@signal)
n36: set_reg(Value=$Best, Target=MineTarget)
n37: wait(Time=5)
n38: get_resource_num(Resource=$Best, Result=$Amt2)
n39: check_number(Value=$Amt2, Compare=100)  >n37 (If Larger)
n40: set_reg(Target=MineTarget)
n41: set_reg(Target=@signal)
n42: jump(Label=c_radar)  >POP (next) >n18 (jump→label)
```

Notes on the design:
- **`n4`**: `$Self` computed once at Program Start (not re-fetched per
  candidate) and reused by both grid checks below.
- **`n1`-`n17` ("Seek")**: reservoir-samples among faction entities
  broadcasting `{id: Resource, num: -1}` (a `MagnifierSignal` building
  signaling demand — see below; the reserved `num=-1` and "Exact" filter
  mode are the fix for bug 3 above), rejecting any candidate not on the
  drone's own power grid (`n7`, bug 4's fix — the actual grid-safety
  constraint) before even rolling the reservoir sample. Waits 20 ticks and
  retries if none found, otherwise travels there (`@goto`, arrival
  tolerance 4) and waits until within distance 8 before proceeding — a
  generous tolerance since the target is a building, not a point, and
  footprint size varies.
- **`n18`-`n32` ("Mine")**: the original reservoir-sampling/oversubscription
  logic, with two additions — `Filter2=Resource` on the
  `for_entities_in_range` call, filtering to nodes of the specific
  requested item type (the same confirmed-working two-filter AND mechanism
  `Mining Leader`'s `Check Emergency` sub already uses with
  `v_own_faction`+`v_damaged`. **Confirmed 2026-07-11** via a real in-game
  test (a bot next to a single Laterite Ore node, `for_entities_in_range`
  count with `Filter2` set to Laterite Ore → `1`, an unset `Filter2` → `1`
  — an empty `Filter2` acts as "no filter," not "match nothing" — and
  `Filter2` set to the wrong item (Metal Ore) → `0`, proving it's a real
  applied constraint rather than being silently ignored) — a resource
  node's yielded item type genuinely is a valid `Filter2` value)
  — and the same `is_same_grid` rejection (`n22`) applied to resource-node
  candidates, since even a local `Range=5` search could turn up something
  just past the grid's edge. (This loop's own `@signal=$Node`/`Loop Signal`
  oversubscription channel is entity-based, not id-based, so it was never
  at risk of the same num=0 collision bug 3 describes — only the
  building-seeking channel was.)
- **`n33`-`n34`**: no candidate found locally → back to **Seek** (`n1`), not
  a local wait-and-retry — the actual outer-loop integration the original
  draft's "Known gaps" flagged as not yet built.
- **`n35`-`n41`**: unchanged in intent from the original draft — broadcast
  the claim, drive `MineTarget` directly (no `mine()` call), poll down to
  the floor, then clear the link (genuinely halting the native auto-resume
  cycle, not just abandoning it — see the original revision note below for
  why this matters) and the signal claim.
- **`n42`**: on finishing one node, loop back to **Mine** (`n18`) to try
  another node in the same area *first*, only escalating to **Seek** if
  `n33` finds nothing at all — avoids re-picking a building every time a
  single node depletes.

**Revision note (2026-07-10, preserved from the original draft):** an
earlier version called the `mine` instruction once to establish the target
and relied entirely on the confirmed native auto-store/auto-resume cycle
from there. Indexing `data/` into a code knowledge graph and tracing
`c_miner:on_update`'s actual stop conditions (`components.lua:2254-2536`)
found a real bug: none of its four real stop conditions (register 1
cleared, requested amount reached, inventory full, node destroyed) cover
"the Program decided to abandon this node" — clearing only the Signal
broadcast left the native auto-resume cycle mining the abandoned node,
unsupervised, straight through the 100-unit floor and potentially to
permanent depletion (`AddResourceHarvestItemAmount`'s `num > 0` guard,
cited above). A `mine(Resource=nil)`-style explicit clear was investigated
and rejected: `mine`'s only real "stop" path requires the raw compiled
argument to be entirely *absent*, not confirmed producible from an
unconnected pin in the visual editor; a `mine`-`Num`-threshold alternative
was also considered and rejected (see the `Num`/`CountItem` bullet in
"Native mechanics confirmed" above). The fix: drive `c_miner`'s register 1
through a genuine register link (`MineTarget`, wired via the Link Editor
directly to register 1 of every `c_miner`/`c_adv_miner` on the drone)
rather than through `mine` at all — a technique the user confirmed using
successfully before that session.

### The MagnifierSignal behavior (real BSF, compiled and validated)

Building-side companion to `MinerDrone`, closing the "author the
`MagnifierSignal` building behavior" gap. Compiled, round-tripped, and
collapses to a single mermaid component the same way `MinerDrone` does.
Saved as `magnifier_signal.dcs` (workspace root) — not yet tested in-game.

```
behavior MagnifierSignal(Resource):
  desc: "Periodically check Resource nodes within range, tracking two INDEPENDENT conditions per node -- needs regen (below the 200 cap) and worth mining (above the 100 floor). Power (shutdown/turnon) follows the regen condition only; the drone-invitation signal (id=Resource, num=0) follows the mining condition only. Keeping these separate avoids a deadlock: an abundant, never-mined area (all nodes already above 200) still needs to invite drones even though it needs no regen at all."

n1: label(Label=v_arrow_right, cmt="Poll nearby Resource nodes; manage power (regen cap) and drone invitation (mining floor) independently")
n2: wait(Time=20)
n3: set_reg(Value=0, Target=$NeedsRegen)
n4: set_reg(Value=0, Target=$Mineable)
n5: for_entities_in_range(Range=2, Filter=v_resource, Filter2=Resource, Unit=$Node)  >n11 (Done)
n6: get_resource_num(Resource=$Node, Result=$Amt)
n7: check_number(Value=$Amt, Compare=200)  >n9 (If Larger) >n9 (If Equal)
n8: set_reg(Value=1, Target=$NeedsRegen)
n9: check_number(Value=$Amt, Compare=100)  >POP (If Smaller) >POP (If Equal)
n10: set_reg(Value=1, Target=$Mineable)  >POP (next)
n11: check_number(Value=$NeedsRegen, Compare=0)  >n13 (If Larger)
n12: shutdown()  >n14 (next)
n13: turnon()
n14: check_number(Value=$Mineable, Compare=0)  >n16 (If Larger)
n15: set_reg(Target=@signal, cmt="Nothing worth mining -- stop broadcasting")  >n18 (next)
n16: set_number(Value=Resource, Number=0, Result=$Sig)
n17: set_reg(Value=$Sig, Target=@signal, cmt="Broadcast: come mine Resource here")
n18: jump(Label=v_arrow_right)  >POP (next) >n1 (jump→label)
```

Notes on the design:
- **`n6`-`n10`**: for every node in range (`Range=2`, matching the
  Magnifier's own Chebyshev range — not independently confirmed that
  `for_entities_in_range`'s range calculation treats a multi-tile
  building's footprint the same way the Magnifier's own native range check
  does), independently mark `$NeedsRegen` (any node `<200`) and `$Mineable`
  (any node `>100`) — both can be true for the same node simultaneously
  (e.g. a node at 150 both still benefits from regen *and* has material
  worth mining right now), which is the point: they're unrelated questions.
- **`n11`-`n13`**: power management, gated on `$NeedsRegen` only.
- **`n14`-`n17`**: drone invitation, gated on `$Mineable` only, entirely
  independent of whichever way the power decision went.

### Known gaps / not yet done

- **Both `MinerDrone` and `MagnifierSignal` have since been loaded, run, and
  hand-edited in the real client** (`library/miner_drone.dcs`,
  `library/magnifier_signal.dcs` — re-exported from the in-game library,
  checked in for reference) — the "not tested in-game" gap this bullet used
  to describe is closed. The building/drone economics have not yet been
  tried as a live, running setup together, though (see the resource-node
  placement pattern above for what's planned).
- **The oversubscription cap (2) in `MinerDrone` is no longer just a guess**
  — see "Regen vs. mining threshold" above, confirmed against real in-game
  measurements. The mining floor (100) and `MagnifierSignal`'s 100/200
  thresholds are still hardcoded, untuned choices.
- **Roaming Mining Leader/Follower squads mining down Magnifier-managed nodes
  to permanent depletion — fixed 2026-07-11.** `library/mining_leader.dcs`
  now has a `Check Avoidance` subroutine (`for_signal_match` on a `v_alert`
  id, `get_distance` with an explicit `Source`, `check_number` against the
  broadcaster's own `num`-as-range) checked both when picking a resource
  target and when choosing a random patrol destination — a building
  broadcasting `v_alert[num=range]` on its `@signal` register (no behavior
  needed, just a manually-set register a blueprint can stamp down) keeps
  squads out. Caught and fixed one real regression while wiring this in: the
  random-walk path validated its candidate destination but never actually
  applied it to `@goto`, so the unit would silently never move — fixed by
  adding the `@goto` write after the avoidance check, confirmed via
  semantic-diff against the pre-fix version (exactly one node added, nothing
  else touched).
- **`MinerDrone`'s outer building-seek loop doesn't account for
  building-level oversubscription** — multiple drones could pick the same
  building simultaneously; nothing analogous to the per-node `Loop Signal`
  claim-counting exists at the building level. Not built yet.
- **`is_same_grid`'s coordinate-based fallback depends on the *calling*
  drone's own position, not just the candidate's.** Confirmed from source
  (`instructions.lua:4192-4211`): when either side isn't itself a
  grid-connected entity, it falls back to comparing `GetPowerGridIndexAt`
  for both positions. A drone that's currently *not* standing within any
  grid's coverage (plausible mid-search, though the whole design intent is
  to never actually leave grid) could see this check spuriously fail even
  against a legitimate in-grid candidate. Not yet a problem in practice
  (the drone should always be within its own grid when this check runs,
  by construction) but worth keeping in mind if this ever needs debugging.
- **`is_same_grid` fails outright when the second unit is a non-owned
  (e.g. world-faction) entity, such as a resource node — user-confirmed
  2026-07-11, a real, live bug in `MinerDrone`'s current `n22`
  (`is_same_grid(Unit=$Self, Unit2=$Node)`).** Tracing why: of
  `is_same_grid`'s four internal branches (`instructions.lua:4198-4203`),
  every one that doesn't require `ent1.faction == ent2.faction` (always
  false for a world-faction resource node against the drone's own faction)
  instead falls back to `GetCoord(comp, state, in_unit2)` — and passing the
  resource node's raw entity reference directly, rather than its
  already-extracted coordinate, makes that fallback fail too (`GetCoord`
  is itself native/non-Lua-visible, so the exact internal reason isn't
  traceable further, but the behavioral fact is confirmed). **Fix:** call
  `get_location(Unit=$Node, Coord=$NodeCoord)` first (already proven to work
  on resource nodes elsewhere, e.g. Mining Leader's own `Target` handling)
  and pass `$NodeCoord`, not `$Node`, as `is_same_grid`'s second argument.
  `MinerDrone`'s building-candidate check (`n7`, `Unit2=$Cand`) is unaffected
  — a signal-broadcasting building is player-owned, so it takes the
  `ent1.faction == ent2.faction` branch instead and never touches
  `GetCoord` at all.

### Future idea, not designed or built: a Mining Leader for slot-less Human Miner Mechs

User idea, 2026-07-11: Human Miner Mechs have no Internal socket for a behavior controller, so
unlike `MinerDrone` they can't run a Program of their own. (Scope corrected 2026-07-14: this
holds only for the explorable-awarded `f_human_miner`; the buildable Miner Mech
`f_human_adv_miner` has an Internal socket — see the component list above. The mechanism below
was also since **confirmed live in-game**, including end-to-end remote-driven mining — see
`todo.md`'s Foreman item for the confirmations and the two design constraints found.) Checked against source for
plausibility rather than left as pure speculation: `set_reg_remotely`/`get_reg_remotely`
(`instructions.lua:6849` on) normally require the source and target to be physically touching
(`GetAdjacentFactionEntityOrSelf`, `instructions.lua:302`), *except* when the calling
component's `def.key == "autobase"` — that branch instead requires only that both ends share
the same `faction:GetPowerGridIndexAt(...)` grid index, no adjacency at all. `c_autobase`
(`components.lua:4116`) *is* the "AI Behavior Controller" component (Internal, alien tech,
`key = "autobase"`). So a structure or unit carrying an AI Behavior Controller plus a Power
Field (`c_power_relay`, `components.lua:1007`, extends grid coverage) could run a Program that
scans idle Human Miner Mechs sharing its grid and remotely drives their registers via
`set_reg_remotely` — no adjacency needed, only shared grid membership. Confirmed mechanically
plausible from source; not designed in detail (what register to drive on the mech, how it picks
targets, oversubscription) or built. Tracked in `todo.md` under "Magnifier / drone-swarm
design."

## What this exercise demonstrated about the toolset itself

This was a deliberate test (the user's explicit framing) of whether Claude
Code can author — not just decompile — a real behavior directly in
`behavior_source_format.md`'s grammar from a natural-language design
discussion, using only `instructions_index.md` + the format spec + targeted
source reads, no existing `.dcs` file as a starting point.

- **Where it worked well**: every instruction name, pin, and semantic
  gotcha needed (the equality-fallthrough idiom, `for_signal_match`'s
  entity-vs-id matching, the loop-dead-end-pops-the-stack rule) came from
  material already read this session or grep'd in seconds — assembling a
  21-instruction graph took no new deep-dive beyond double-checking two
  argument names.
- **Where it caught a real mistake**: writing the actual graph (not just
  describing the plan in prose) is what surfaced the "Loop Nearby Resources"
  vs. "Loop Units (Range)" mixup — a wrong instruction reference that had
  gone unnoticed through several turns of prose description. Concreteness
  forces errors out; a prose plan can hide a wrong instruction reference
  indefinitely.
- **Where it's still fragile**: instruction-index bookkeeping (tracking
  which edges are implicit-adjacent-fallthrough vs. need an explicit
  branch note) was done entirely by hand here. Manageable at 21
  instructions, would get error-prone well before real corpus behaviors'
  typical size — exactly why `behavior_source_format.md` flags the
  parse-back direction as the next real piece of infrastructure needed, not
  a nice-to-have.
- **Reinforces [[feedback_verify_engine_semantics_ingame]] repeatedly, in
  both directions**: several corrections this session came from the user's
  own in-game/gameplay knowledge overriding what static Lua reading alone
  suggested (store-register auto-resume, drone-port nesting working,
  Program-driven units not being bound by `drone_range`) — but at least one
  correction went the other way, with a specific source-code check (`mine`'s
  actual `func`, the dispatcher's `step_limit`) resolving a question neither
  party could have answered from gameplay intuition alone. Both directions
  matter; neither in-game experience nor source-reading alone is
  sufficient on its own.
