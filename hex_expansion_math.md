# Hex-Ring Expansion Math — Reference

Coordinate math for a behavior that expands a power-pole network outward from an origin in a
hexagonal spiral, one ring at a time, checking each candidate point against the logistics network
before building. Worked out in conversation. `HexAt` below is implemented and validated in-game
as a reusable sub-behavior (`hexat_test.dcs`, `tests/data/` — a `HexAt(R, T, Origin, d_half) ->
Result` sub-behavior plus a test harness that calls it for every `R=0..5, T=0..6R-1` and logs the
result); the living, actively-used copy is `library/hexat.dcs`, a superset of that fixture (see
"Deployed copy" under the Forward section); `HexIndexOf` also has a `.dcs` now (`HexIndexOf_test_1.dcs`, `tests/data/`), validated by
running both routines through the real game Lua (`tests/test_hex_expansion.py`), though not yet
loaded/run in the actual game client itself. Two routines:

- `HexAt(R, T, Origin, d_half)` — given a ring number `R` and a running index `T` within that
  ring, returns the world coordinate of that lattice point.
- `HexIndexOf(Coord, Origin, d_half)` — the inverse: given an arbitrary world coordinate, returns
  the `(R, T)` of the nearest lattice point, so a bot can reconcile a real (possibly
  terrain-nudged) position back into the canonical sequence.

Both are pure integer/fixed-point — see "Why integer-only" below.

## Why integer-only

`Divide` (`data/instructions.lua:1884`) is the only Math-category instruction whose `explain`
text calls out non-integer behavior at all: "stores the **floored integer** result." `Add`/
`Subtract`/`Multiply` don't mention any rounding. The simplest explanation is that number
registers are integer-only, so Add/Sub/Multiply never had anything to call out (integer in →
integer out), while Divide is the one op that can produce a fraction mathematically and so needed
the callout. There is no Sin/Cos/Floor/Round/Abs/Max instruction in the Math category either.

Consequences:
- No literal decimal constants (e.g. `0.8660254` for √3⁄2) can be stored in a register as-is.
- `floor(a/b)` is free — it's just what `Divide` already does natively.
- `abs(x)` and `max(a,b,c)` have no native instruction; build from `Compare Number` branches
  (negate via `Subtract(0, x)` when `x < 0`; pairwise compare for max of three).
- Full floating-point (e.g. mantissa/exponent emulation) is unnecessary here — there's exactly
  one irrational constant (√3⁄2) with known fixed magnitude and bounded operand ranges, so a
  single fixed-point scale factor suffices. Mantissa/exponent emulation earns its keep only when
  ranges are unknown/huge and renormalization is required after every op.

## Parameters vs. hardcoded constants

As originally worked out below, `d`/`d_half`/`SCALE`/`K` were all "design-time constants, chosen
once when the behavior is authored." The implemented `HexAt` (`hexat_test.dcs`) splits that
differently — only some of these are actually fixed at authoring time; the rest are runtime
parameters of the sub-behavior, in this declared order (`pnames`):

```
Runtime parameters, supplied fresh by the caller on every call:
  R, T      — ring number and running index, as originally designed
  Origin    — coordinate; no longer assumed to be a single fixed constant
  d_half    — HALF the pole spacing (see below for why d_half, not d)
  Result    — output parameter, holds the returned coordinate

Computed once per call from d_half, not itself a parameter:
  d = d_half * 2

Hardcoded literals baked directly into HexAt's instructions, never exposed to the caller at all:
  SCALE = 10000
  K     = 8660           # round(0.8660254 * SCALE), i.e. √3⁄2 scaled
```

`Den = 2 * d * K` (`HexIndexOf`-only, see that section below) is **not** a design-time constant
either, once `d_half` is a runtime parameter: since `d = d_half * 2` varies per call, `Den` has to
be recomputed per call too (`Den = 4 * d_half * K`) — only `SCALE`/`K` themselves stay fixed.

**Why the parameter is `d_half`, not `d`:** the original design required "`d` MUST be even" as a
caller-side discipline, to make the `d*r/2` term exact (`d*r/2 = (d/2)*r`). The implementation
turns that into a structural guarantee instead of a documented caveat: the caller only ever
supplies `d_half` (any integer), and `HexAt` derives `d = d_half * 2` internally — which is
unconditionally even no matter what integer `d_half` is. There is no longer any way to pass an
odd `d` by mistake, because `d` itself is never a caller-visible value.

`K`/`SCALE` still handle the one irrational constant (√3⁄2) via fixed-point: multiply up, divide
down exactly once, at the final coordinate, so rounding error never compounds across rings. They
stay hardcoded rather than parameters since nothing about them varies per call.

Axial hex directions (integer, `d`-independent):

```
dir[0]=(1,0)  dir[1]=(1,-1)  dir[2]=(0,-1)  dir[3]=(-1,0)  dir[4]=(-1,1)  dir[5]=(0,1)
```

Ring `R` has `6R` points split into 6 sides of `R` points each. Side `k`'s starting corner is
always `R * dir[(k+4) mod 6]` — collapsing the per-side axial offset formula
`q = R*dir[(k+4)%6].q + t*dir[k].q` (and same for `r`) down to pure `±R±t` per side (worked out
below), no multiplication needed there.

## Forward: `HexAt(R, T, Origin, d_half) → Result`

`T` runs `0 .. 6R-1` and encodes both side and position-in-side: `k = floor(T/R)` (0..5, which
side), `t = T mod R` (0..R-1, position along that side). Advancing to the next point is a flat
counter: `T+1` if `T+1 < 6R`, else `R+1, T=0` — this also bootstraps `(0,0) → (1,0)` correctly
with no special-casing.

Implemented and in-game-validated (`hexat_test.dcs`, 92/92 `(R, T)` cases across `R=0..5`
matched by hand). Pseudocode below now mirrors the actual instruction graph, including a couple
of implementation quirks called out inline — see "As implemented" notes:

```
# R == 0 case: check_number has no "If Equal" pin, only "If Larger"/"If Smaller" (see
# behavior_format.md's "check_number's implicit equal case"). Point both at the general-case
# work below, and let the plain fallthrough be the R == 0 case:
check_number(Value=R, Compare=<omitted, defaults 0>,
             If Larger  -> general_case,
             If Smaller -> general_case)
return origin                                # falls through here only when R == 0 exactly

general_case:
k = floor(T / R)          # 1 Divide
t = T - k*R                 # 1 Multiply + 1 Subtract (cheaper than a separate Modulo)

Jump(k)                     # computed jump table -- Jump's target is a runtime value match
                             # against Label's own value (data/instructions.lua:522/534), not a
                             # compile-time dict-key jump -- validated in-game with plain
                             # numeric label ids 0..5, dispatching correctly for every k

Label(0): q = t - R;   r = R;      # falls into shared_tail below, no Jump needed
Label(1): q = t;       r = R - t;  Jump(shared_tail)
Label(2): q = R;       r = -t;     Jump(shared_tail)
Label(3): q = R - t;   r = -R;     Jump(shared_tail)
Label(4): q = -t;      r = t - R;  Jump(shared_tail)
Label(5): q = -R;      r = t;      Jump(shared_tail)

shared_tail:                  # d, Origin split recomputed here -- see "As implemented" below
d = d_half * 2
OrigX, OrigY = Separate Coordinate(Origin)

Sequence:                     # forks into independent X/Y chains, then combines -- see below
  First:  X    = OrigX + d*q + d_half*r
  Second: Ynum = OrigY*SCALE + d*r*K
  Third:  Y    = floor((2*Ynum + SCALE) / (2*SCALE))     # round-half-up, 1 Divide
  Last:   Result = Combine Coordinate(X, Y)
```

**As implemented, two differences from the original design worth flagging:**
- **`Label(0)` is written as the shared tail itself**, not a 6th branch that jumps to a separate
  `done` label — `k=0` falls straight through from setting `q, r` into the `d`/`Separate
  Coordinate`/`Sequence` block. Every *other* branch (`k=1..5`) explicitly jumps back up into
  that same block. Net effect: `d = d_half * 2` and the `Origin` split are recomputed on every
  call for `k=1..5` (redundant but harmless — cheap ops, not worth a separate `done` label for a
  6-way dispatch).
- **The final X/Y/combine step is a `sequence` fork**, not flat sequential pseudocode: `First`
  computes `X`, `Second`/`Third` compute `Ynum` then `Y`, `Last` combines. Each leg ends with its
  own dead-end (`next: false`), which `sequence` chains through in order (see
  "Block-type instructions" in `behavior_format.md`) rather than a single straight-line
  computation. This is how the in-game visual graph came out, not a hard requirement — a
  flat chain would compute the same result.

Verified by hand for `R=1, T=0..5` against the original per-side derivation (reproduces
`dir[4], dir[5], dir[0], dir[1], dir[2], dir[3]` in order, i.e. the six neighbors of the origin);
then re-verified against all 92 `(R, T)` pairs the in-game test harness actually logged.

### Deployed copy (`library/hexat.dcs`)

The living, in-game copy re-exported to `library/` is the same routine as the `hexat_test.dcs`
fixture with two additive enhancements — the shared arithmetic core (every `k`-branch, the
`Sequence` X/Y fork, the round-half-up) is byte-for-byte identical, and lint/round-trip are clean:

- **`Origin` may be a unit *or* a coordinate.** Before the `Separate Coordinate`, a `value_type`
  switch on `Origin` routes a unit through `get_location` (resolving it to its coordinate — note
  the multi-tile "center tile, rounds up on ties" semantics that applies) and a coordinate through
  a plain copy; every other value type dead-ends (`POP`). Both live paths then feed the identical
  downstream math via a scratch coord, so the fixture's coordinate-only behavior is unchanged and
  the routine now additionally accepts a unit handle as the origin.
- **Out-of-range `T` wraps around the ring** (added 2026-07-18): `k = floor(T/R) mod 6` and
  `t = (T - k*R) mod R`. For the nominal range `T ∈ 0..6R-1` both modulos are no-ops; any
  `T ≥ 6R` — e.g. an ever-incrementing counter that never resets — wraps back around the ring
  instead of landing on a non-existent `Label`. Robustness, not a math change. **The `t` modulo's
  divisor is `R`, not 6** — `t` is the position *along* a side (`0..R-1`), so only the side index
  `k` wraps mod 6. A first draft used `modulo(t, 6)`, which passes rings 1–6 coincidentally
  (`t < 6` there) and breaks from ring 7 on, *including for in-range `T`* — worse than no `t`
  modulo at all. (Since `%` is floored, negative `T` should also wrap correctly, but only
  `T ≥ 0` has been verified.)

The coordinate path was re-validated against the closed-form reference with wraparound
(`T` swept through two full extra ring cycles per `R`, rings 0–9, zero mismatches — the arithmetic
core, additions stripped, run through the real Lua via `Interpreter`); the unit path can't yet be
driven by `Interpreter` (`value_type`/`get_location` aren't in its leaf dispatch) but is
structurally just a coordinate resolution ahead of that same validated math.

The routine was also exercised **in-game 2026-07-18** as the waypoint generator for the
movement-model measurement (see `mock_world_spec.md`'s tick-step note): a test behavior walked an
Engineer around all six `R=1` ring corners at `d_half=5` (`T = 0..5` via the `modulo` wrap),
and every corner in the resulting debug log landed exactly on the closed-form position for the
ring around origin `(-14, 51)` — E `(-4,51)`, NE `(-9,60)`, NW `(-19,60)`, W `(-24,51)`,
SW `(-19,42)`, SE `(-9,42)`. First live-navigation use of `HexAt` output, on top of the earlier
self-test-harness validation.

## Inverse: `HexIndexOf(Coord, Origin, d_half) → (R, T)`

Converts the input coordinate to fractional axial, rounds to the nearest actual hex lattice point
using cube rounding (rounding `q` and `r` independently can pick the wrong hex), then reads off
which ring/side/step it landed on. Rounding is deferred to the last possible step — all
intermediate values are carried as exact-integer numerators over a shared denominator `Den`, per
the "rational ratios partway through" approach (avoids any premature precision loss, and lets the
cube-rounding error comparison work on exact integers instead of fractions).

**Not yet implemented or in-game-validated** (unlike `HexAt` — see `hexat_test.dcs`). The
pseudocode below was revised in a second pass (user-driven review) that caught four real
inefficiencies in the first draft and ruled out one further idea (using `switch` for region
detection — see inline note at that spot), none of which change the result. Still carried over by
analogy from `HexAt`'s proven idioms, not independently confirmed in-game.

Signature matches `HexAt`'s convention (see previous section): takes `d_half`, not `d` — `d` and
`Den` are both derived internally from it, never caller-visible, same reasoning as `HexAt`.

```
Den = (4*K) * d_half                  # `d` itself is never needed: the original draft computed
                                       # d = d_half*2 only to feed Den = 2*d*K = 4*d_half*K. Since
                                       # 4*K is a fixed literal (34640), Den is one Multiply against
                                       # a precomputed constant -- no intermediate `d` at all.

Delta   = Coord - Origin              # coordinate (-) coordinate: component-wise subtract, confirmed
                                       # semantics (behavior_format.md's "coordinate (+) coordinate"
                                       # rule, via formation-hold.dcs). Replaces splitting Coord and
                                       # Origin separately (2x Separate Coordinate) then subtracting
                                       # each component (2x Subtract) -- 4 instructions -- with 1
                                       # Subtract on the coordinates themselves.
dx, dy  = Separate Coordinate(Delta)  # 1 Separate Coordinate. Total: 2 instructions instead of 4.

# rational axial coords, all over shared denominator Den:
q_num  = 2*K*dx - SCALE*dy
r_num  = 2*SCALE*dy
yc_num = -q_num - r_num              # cube constraint x+y+z=0, exact

# round each (round-half-up, 1 Divide each) -- these three are independent of one another, a
# candidate for a `sequence` fork (First/Second/Third) the way HexAt forked its X/Ynum/Y legs:
rx = floor((2*q_num  + Den) / (2*Den))
ry = floor((2*yc_num + Den) / (2*Den))
rz = floor((2*r_num  + Den) / (2*Den))

# cube-rounding correction -- compare integer residuals directly, no division needed to compare.
# abs(x) has no native instruction (see "Why integer-only"); every use here is the same
# check_number-guarded negate:
#   Abs(x): check_number(Value=x, Compare=0, If Smaller -> return 0 - x); return x
err_x = Abs(rx*Den - q_num)
err_y = Abs(ry*Den - yc_num)
err_z = Abs(rz*Den - r_num)

# check_number only has "If Larger"/"If Smaller", no "If Equal" -- same equal-idiom HexAt used
# for its R==0 guard applies to each ">" test below (an exact tie falls through as "not larger"):
#
# Only rx and rz are ever read again (q, r below) -- ry itself is dead past this point, the same
# way standard axial (q, r) drops the redundant cube `y` (y = -x-z is always derivable). The
# standard 3-way cube-round correction (this is the textbook algorithm, unmodified) picks whichever
# of rx/ry/rz has the largest rounding error and recomputes *that one* from the other two, to
# restore the x+y+z=0 constraint exactly. When ry is the one with the largest error, its premise is
# "rx and rz's own independent roundings were already the trustworthy pair" -- which is exactly the
# case where nothing needs correcting here, since only rx/rz are ever read. So the
# middle case collapses to a true no-op (not just an unread assignment):
if err_x > err_y and err_x > err_z:  rx = -ry - rz
elif err_z >= err_y:                  rz = -rx - ry
# else (err_y strictly largest): rx, rz already correct -- nothing to do, no instructions needed.

q, r = rx, rz
R = max(abs(q), abs(r), abs(q+r))    # pairwise Compare Number, per "Why integer-only"
if R == 0: return (0, 0)             # same check_number equal-idiom as HexAt's R==0 guard

# Region detection, rewritten as a for_number SEARCH LOOP over candidate side k=0..5, using the
# same jump/label computed-dispatch idiom HexAt already validated in-game for its own (forward)
# k=0..5 dispatch. The first draft's own comment argued jump/label couldn't apply here because
# "k is exactly what's being solved for" -- true for using jump/label as the OUTER dispatch (you
# can't jump to an unknown k), but that doesn't rule out combining it with a loop that *enumerates*
# candidate k values and only uses jump/label to pick each candidate's arithmetic, exactly as below.
#
# NOT the `switch` instruction (a live option worth ruling out explicitly): `switch`
# (data/instructions.lua ~3261) resolves each Case via `GetId`/`test_id`, comparing a value's *id*
# field for unit/item/frame/tech filtering -- it has no numeric-equality mode at all, so it cannot
# test "does this arithmetic expression equal R", no matter how many Case slots are chained or
# nested.
#
# The six sides' gate equalities (q==±R / r==±R / q+r==±R) and `t` formulas are irreducibly
# different arithmetic, same as HexAt's forward direction -- that part doesn't collapse. What does
# collapse from 6 duplicated copies down to 1 is the `t in [0, R-1]` range check and the "not a
# match, try next side" plumbing: inside a loop body, an exec pin wired to `false` (not omitted --
# see behavior_format.md's gotcha on that distinction) pops back to the loop, which just advances
# to the next iteration -- free "continue" semantics, no explicit "jump to next region" wiring.
# `last` (Break) then jumps straight to the loop's own Done pin once a match is found.

for_number(0, 5) -> k:                        # Value = k, this iteration's candidate side
  Jump(k)                                     # computed dispatch, same idiom as HexAt's Jump(k)

  Label(0): check_number(r,   R, IfLarger->false, IfSmaller->false); t = q + R  # falls into tail
  Label(1): check_number(q+r, R, IfLarger->false, IfSmaller->false); t = q;     Jump(tail)
  Label(2): check_number(q,   R, IfLarger->false, IfSmaller->false); t = -r;    Jump(tail)
  Label(3): check_number(r,  -R, IfLarger->false, IfSmaller->false); t = R - q; Jump(tail)
  Label(4): check_number(q+r,-R, IfLarger->false, IfSmaller->false); t = -q;    Jump(tail)
  Label(5): check_number(q,  -R, IfLarger->false, IfSmaller->false); t = r;     Jump(tail)

  tail:                                        # written once, shared by all 6 labels
    check_number(t, 0,   IfSmaller->false)     # t < 0     -> not this side, next iteration
    check_number(t, R-1, IfLarger->false)      # t > R-1   -> not this side, next iteration
    last()                                     # match: break straight to the loop's Done pin

Done:                                          # reached via `last` (match found), or after k=5's
                                                # iteration runs out with no match -- should be
                                                # unreachable for a valid (q,r), but is now a free
                                                # defensive fallback the old flat cascade didn't have
  T = k*R + t
  return (R, T)
```

## Graph-native rendering experiment (`behavior_source_format`, 2026-07-07)

As a test of `behavior_source_format.md`'s graph-native grammar against real
data (not hand-picked examples), both `HexAt` and the *currently encoded*
`HexIndexOf` (the pre-revision flat cascade in `HexIndexOf_test_1.dcs`, not
the `for_number`/`jump`/`label` redesign above) were decoded via
`dcs_wire.py` and run through `scripts/render_examples.py`'s graph
extraction, then hand-translated from that script's still-prefixed
`num:`/`var:`/`id:` output into this format's actual bare-value surface
syntax (resolved parameter names from each sub-behavior's real `pnames`,
`$`-prefixed locals, bare numbers/ids) — the prototype's own gap here is
already tracked in `behavior_source_format.md`'s "Status" section, not fixed
by this exercise. Every instruction index, arg, and edge below is the real
encoded data, not a re-derivation from the prose pseudocode above.

### `HexAt`, as encoded (`hexat_test.dcs`)

```
sub HexAt(R, T, Result, Origin, d_half):
1: check_number(Value=R)                          >3 (If Larger) >3 (If Smaller)
2: set_reg(Value=Origin, Target=Result)            >STOP (next)
3: div(From=T, Num=R, Result=$k)
4: mul(To=$k, Num=R, Result=$kR)
5: sub(From=T, Num=$kR, Result=$t)
6: jump(Label=$k)                                  >STOP (next)
7: label(Label=0)
8: sub(From=$t, Num=R, Result=$q)
9: set_reg(Value=R, Target=$r)
10: mul(To=d_half, Num=2, Result=$d)
11: separate_coordinate(Coordinate=Origin, X=$OrigX, Y=$OrigY)
12: sequence()                                     >17 (Second) >21 (Third) >STOP (Fourth) >24 (Last)
13: mul(To=$q, Num=$d, Result=$dq)
14: mul(To=$r, Num=d_half, Result=$dhr)
15: add(To=$dq, Num=$dhr, Result=$dsum)
16: add(To=$OrigX, Num=$dsum, Result=$X)           >STOP (next)
17: mul(To=$r, Num=8660, Result=$rK)
18: mul(To=$rK, Num=$d, Result=$drK)
19: mul(To=$OrigY, Num=10000, Result=$OrigYScale)
20: add(To=$OrigYScale, Num=$drK, Result=$Ynum)    >STOP (next)
21: mul(To=$Ynum, Num=2, Result=$Ynum2)
22: add(To=$Ynum2, Num=10000, Result=$YnumAdj)
23: div(From=$YnumAdj, Num=20000, Result=$Y)       >STOP (next)
24: combine_coordinate(X=$X, Y=$Y, Result=Result)  >STOP (next)
25: label(Label=1)
26: set_reg(Value=$t, Target=$q)
27: sub(From=R, Num=$t, Result=$r)                 >10 (next)
28: label(Label=2)
29: set_reg(Value=R, Target=$q)
30: sub(From=0, Num=$t, Result=$r)                 >10 (next)
31: label(Label=3)
32: sub(From=R, Num=$t, Result=$q)
33: sub(From=0, Num=R, Result=$r)                  >10 (next)
34: label(Label=4)
35: sub(From=0, Num=$t, Result=$q)
36: sub(From=$t, Num=R, Result=$r)                 >10 (next)
37: label(Label=5)
38: sub(From=0, Num=R, Result=$q)
39: set_reg(Value=$t, Target=$r)                   >10 (next)
```

### `HexIndexOf`, as encoded (`HexIndexOf_test_1.dcs`, pre-revision cascade)

```
sub HexIndexOf(Coord, Origin, d_half, R, T):
1: mul(To=d_half, Num=2, Result=$d)
2: mul(To=$d, Num=8660, Result=$dK)
3: mul(To=$dK, Num=2, Result=$Den)
4: mul(To=$Den, Num=2, Result=$Den2)
5: separate_coordinate(Coordinate=Coord, X=$Cx, Y=$Cy)
6: separate_coordinate(Coordinate=Origin, X=$Ox, Y=$Oy)
7: sub(From=$Cx, Num=$Ox, Result=$dx)
8: sub(From=$Cy, Num=$Oy, Result=$dy)
9: mul(To=$dx, Num=17320, Result=$q_num_a)
10: mul(To=$dy, Num=10000, Result=$q_num_b)
11: sub(From=$q_num_a, Num=$q_num_b, Result=$q_num)
12: mul(To=$dy, Num=20000, Result=$r_num)
13: sub(From=0, Num=$q_num, Result=$neg_q_num)
14: sub(From=$neg_q_num, Num=$r_num, Result=$yc_num)
15: mul(To=$q_num, Num=2, Result=$q_num2)
16: add(To=$q_num2, Num=$Den, Result=$q_num2d)
17: div(From=$q_num2d, Num=$Den2, Result=$rx)
18: mul(To=$yc_num, Num=2, Result=$yc_num2)
19: add(To=$yc_num2, Num=$Den, Result=$yc_num2d)
20: div(From=$yc_num2d, Num=$Den2, Result=$ry)
21: mul(To=$r_num, Num=2, Result=$r_num2)
22: add(To=$r_num2, Num=$Den, Result=$r_num2d)
23: div(From=$r_num2d, Num=$Den2, Result=$rz)
24: mul(To=$rx, Num=$Den, Result=$rxDen)
25: sub(From=$rxDen, Num=$q_num, Result=$diff_x)
26: check_number(Value=$diff_x, Compare=0)         >28 (If Smaller)
27: set_reg(Value=$diff_x, Target=$err_x)          >29 (next)
28: sub(From=0, Num=$diff_x, Result=$err_x)
29: mul(To=$ry, Num=$Den, Result=$ryDen)
30: sub(From=$ryDen, Num=$yc_num, Result=$diff_y)
31: check_number(Value=$diff_y, Compare=0)         >33 (If Smaller)
32: set_reg(Value=$diff_y, Target=$err_y)          >34 (next)
33: sub(From=0, Num=$diff_y, Result=$err_y)
34: mul(To=$rz, Num=$Den, Result=$rzDen)
35: sub(From=$rzDen, Num=$r_num, Result=$diff_z)
36: check_number(Value=$diff_z, Compare=0)         >38 (If Smaller)
37: set_reg(Value=$diff_z, Target=$err_z)          >39 (next)
38: sub(From=0, Num=$diff_z, Result=$err_z)
39: check_number(Value=$err_x, Compare=$err_y)     >40 (If Larger) >41 (If Smaller) >41 (next)
40: check_number(Value=$err_x, Compare=$err_z)     >46 (If Larger) >41 (If Smaller)
41: check_number(Value=$err_y, Compare=$err_z)     >44 (If Larger)
42: sub(From=0, Num=$rx, Result=$neg_rx_a)
43: sub(From=$neg_rx_a, Num=$ry, Result=$rz)       >48 (next)
44: sub(From=0, Num=$rx, Result=$neg_rx_b)
45: sub(From=$neg_rx_b, Num=$rz, Result=$ry)       >48 (next)
46: sub(From=0, Num=$ry, Result=$neg_ry_a)
47: sub(From=$neg_ry_a, Num=$rz, Result=$rx)
48: set_reg(Value=$rx, Target=$q)
49: set_reg(Value=$rz, Target=$r)
50: check_number(Value=$q, Compare=0)              >52 (If Smaller)
51: set_reg(Value=$q, Target=$absq)                >53 (next)
52: sub(From=0, Num=$q, Result=$absq)
53: check_number(Value=$r, Compare=0)              >55 (If Smaller)
54: set_reg(Value=$r, Target=$absr)                >56 (next)
55: sub(From=0, Num=$r, Result=$absr)
56: add(To=$q, Num=$r, Result=$qr)
57: check_number(Value=$qr, Compare=0)             >59 (If Smaller)
58: set_reg(Value=$qr, Target=$absqr)              >60 (next)
59: sub(From=0, Num=$qr, Result=$absqr)
60: check_number(Value=$absq, Compare=$absr)       >62 (If Smaller)
61: set_reg(Value=$absq, Target=$m1)               >63 (next)
62: set_reg(Value=$absr, Target=$m1)
63: check_number(Value=$m1, Compare=$absqr)        >65 (If Smaller)
64: set_reg(Value=$m1, Target=R)                   >66 (next)
65: set_reg(Value=$absqr, Target=R)
66: check_number(Value=R, Compare=0)               >68 (If Larger) >68 (If Smaller)
67: set_reg(Value=0, Target=T)                     >STOP (next)
68: check_number(Value=$r, Compare=R)              >75 (If Larger) >75 (If Smaller)
69: add(To=$q, Num=R, Result=$qR0)
70: sub(From=R, Num=1, Result=$Rm1)
71: check_number(Value=$qR0, Compare=0)            >75 (If Smaller)
72: check_number(Value=$qR0, Compare=$Rm1)         >75 (If Larger)
73: set_reg(Value=0, Target=$k)
74: set_reg(Value=$qR0, Target=$t)                 >105 (next)
75: check_number(Value=$qr, Compare=R)             >81 (If Larger) >81 (If Smaller)
76: sub(From=R, Num=1, Result=$Rm1_1)
77: check_number(Value=$q, Compare=0)              >81 (If Smaller)
78: check_number(Value=$q, Compare=$Rm1_1)         >81 (If Larger)
79: set_reg(Value=1, Target=$k)
80: set_reg(Value=$q, Target=$t)                   >105 (next)
81: check_number(Value=$q, Compare=R)              >88 (If Larger) >88 (If Smaller)
82: sub(From=0, Num=$r, Result=$negr2)
83: sub(From=R, Num=1, Result=$Rm1_2)
84: check_number(Value=$negr2, Compare=0)          >88 (If Smaller)
85: check_number(Value=$negr2, Compare=$Rm1_2)     >88 (If Larger)
86: set_reg(Value=2, Target=$k)
87: set_reg(Value=$negr2, Target=$t)               >105 (next)
88: sub(From=0, Num=R, Result=$negR3)
89: check_number(Value=$r, Compare=$negR3)         >96 (If Larger) >96 (If Smaller)
90: sub(From=R, Num=$q, Result=$Rmq3)
91: sub(From=R, Num=1, Result=$Rm1_3)
92: check_number(Value=$Rmq3, Compare=0)           >96 (If Smaller)
93: check_number(Value=$Rmq3, Compare=$Rm1_3)      >96 (If Larger)
94: set_reg(Value=3, Target=$k)
95: set_reg(Value=$Rmq3, Target=$t)                >105 (next)
96: check_number(Value=$qr, Compare=$negR3)        >103 (If Larger) >103 (If Smaller)
97: sub(From=0, Num=$q, Result=$negq4)
98: sub(From=R, Num=1, Result=$Rm1_4)
99: check_number(Value=$negq4, Compare=0)          >103 (If Smaller)
100: check_number(Value=$negq4, Compare=$Rm1_4)    >103 (If Larger)
101: set_reg(Value=4, Target=$k)
102: set_reg(Value=$negq4, Target=$t)              >105 (next)
103: set_reg(Value=5, Target=$k)
104: set_reg(Value=$r, Target=$t)
105: mul(To=$k, Num=R, Result=$kR)
106: add(To=$kR, Num=$t, Result=T)                 >STOP (next)
```

### What the graph form surfaced that the tree pseudocode didn't

- **The dead `ry` branch is now pointed at, not just described.** Instructions
  44-45 (`ry = -rx - rz`) sit in the "`err_y` is the strictly-largest error"
  arm of the cube-rounding correction (reached only via instruction 41's `If
  Larger` edge) and recompute `$ry` — a value nothing downstream ever reads
  again (only `$rx`/`$rz` feed `$q`/`$r` at 48-49). The prose pseudocode
  above already reasoned this out abstractly ("the middle case collapses to
  a true no-op"), but that reasoning was about a *revised* design, not this
  file — seeing it as two concrete, named, still-live instructions in the
  real encoded graph confirms the conclusion applies to what's actually
  running today, not just to a hypothetical rewrite. The fix is visible as a
  one-line edit at this granularity: rewire 41's `If Larger` straight to 48
  and delete 44-45.
- **The 4-instruction coordinate split-then-subtract (5-8) is a real, present
  cost, not a hypothetical one.** `separate_coordinate(Coord)` (5),
  `separate_coordinate(Origin)` (6), then two `sub`s (7, 8) — exactly the
  shape the "Inverse" section's revision proposes collapsing to a single
  coordinate-level `sub` followed by one `separate_coordinate` (2
  instructions). Both the "before" and "after" are now visible as literal
  instruction counts at literal indices, not prose claiming a savings.
- **`Den`'s three chained multiplies (1-3) are visibly the same shape the
  revision's `Den = (4*K)*d_half` collapses to one against.** `$d =
  d_half*2` (1), `$dK = $d*8660` (2), `$Den = $dK*2` (3) — multiplying out,
  `$Den = d_half * 2 * 8660 * 2 = d_half * 34640`, exactly `4*K` (`4*8660 =
  34640`) times `d_half`, cross-validating the revision's precomputed
  literal against the real encoded constants rather than re-deriving it from
  scratch. `$Den2 = $Den*2` (4) is a distinct, still-needed value (the
  round-half-up formula's doubled denominator) — the revision only folds 1-3
  into one multiply, not this one.
- **The six region blocks (69-74, 75-80, 81-87, 88-95, 96-102, 103-104) are
  visibly the same control topology repeated, not just "irreducibly
  different arithmetic" (the prose pseudocode's framing).** Every block
  except the last opens with a gate `check_number` whose both branches jump
  to the *next* block's start (`>75`, `>81`, `>88`, `>96`, `>103`), followed
  by up to two range `check_number`s doing the same thing, then a `set_reg`
  pair. Laid out with real indices, the "try next candidate on any failure"
  pattern the redesign's `for_number`/`false`-continue loop targets is a
  visibly identical five-times-repeated edge shape — something flat
  `if`/`elif` prose (or even the informal `Label(k): ...; Jump(tail)` shape
  used elsewhere in this file) reads as "a cascade" but doesn't make
  countable the way explicit `>N` edges to five different literal indices
  do.
- **Those explicit forward indices (75, 81, 88, 96, 103) are also a real,
  newly-visible maintenance liability.** Inserting or deleting one
  instruction anywhere in this span breaks every one of them, since each is
  a raw position, not a name. A `for_number`/`false`-continue loop needs no
  such index at all — `false` just pops back to the loop. This cost is
  invisible in tree pseudocode (which never has to talk about raw
  instruction positions) and only shows up once the format forces real
  indices into the open.
- **The last region (103-104) has *zero* checks — and the loop redesign
  reproduces this for free, no special-casing cost involved.** It's an
  unconditional `k=5; t=r`, correctly exploiting that the previous five
  checks already partition all cases exhaustively. A first pass at this
  section wrongly worried that the proposed `for_number(0,5)` loop would be
  forced to spend an extra `check_number(k, 5)` to reproduce that saving —
  but that's not how `jump`/`label` dispatch works: `label(5)`'s own body,
  reached only when `k` is genuinely `5`, already *is* the discriminator,
  exactly the same way each of `HexAt`'s six labels gets its own distinct
  arithmetic with no "which k is this?" check inside it. `label(5)`'s body
  can be `k=5; t=r` with no gate/range-check tail at all, same as the
  real flat cascade — the loop's own iteration bookkeeping (this is the last
  value in `0..5`) is what routes to `Done` afterward, not an explicit
  `last()`/break or an added check. So this instruction span confirms the
  loop redesign matches the flat cascade's cost exactly here, not a
  regression risk — worth stating plainly since an earlier draft of this
  section got it backwards.
- **The `check_number`-guarded `abs()` idiom appears six separate times
  (26-28, 31-33, 36-38, 50-52, 53-55, 57-59), each a near-identical 3
  instructions.** The tree pseudocode collapsed all of these into one
  `Abs(x)` macro-call notation, which is honest about the *logic* being
  repeated but hides *how many times* — the graph form makes the count (6 ×
  3 = 18 instructions) countable at a glance. Whether extracting this into a
  callable sub-behavior (`call`) is a net win is a genuinely open question
  this project hasn't characterized yet (real `call` overhead isn't
  documented anywhere in this repo) — flagged here as a new candidate, not a
  decided optimization.
- **A real ambiguity in the tree pseudocode's own notation, resolved by the
  graph form's edge syntax.** `HexAt`'s prose (`Label(1): ... Jump(shared_tail)`)
  reuses the word "Jump" for two different things: the outer `jump(Label=$k)`
  at instruction 6 is a real computed-dispatch instruction (confirmed by the
  encoded data: no static `jump→label` annotation is possible here since
  `$k` is a runtime variable, not a literal — exactly the case
  `behavior_source_format.md`'s "Dynamic `jump`/`label` dispatch" section
  describes), but labels 1-5's own "`Jump(shared_tail)`" is *not* a second
  real `jump`/`label` instruction pair at all — the encoded data shows it's
  just an ordinary explicit `>10 (next)` exec edge (instructions 27, 30, 33,
  36, 39 all wire straight back to instruction 10). The tree notation's
  reuse of "Jump" for both a genuine dynamic dispatch and a plain static
  exec edge is exactly the kind of conflation `>N (PinName)` vs. a named
  `jump` node is designed to make impossible.

Taken together, this is the experiment's actual result: the graph-native
form did not just re-express the same design more verbosely — it turned
several prose claims (the dead `ry` branch, the coordinate-split cost, the
`Den` constant-folding) into directly-verifiable facts about the real
encoded instructions, and it made a wrong worry about the loop redesign
(the region-5 special-casing cost) checkable and correctable in the same
pass, rather than left standing as a plausible-sounding but incorrect
concern.

## Open items / not yet decided

- Overflow headroom: `SCALE=10000` keeps `d*r*K` and similar products well under the int32 ceiling
  (~2.1×10^9) for `d` in the low hundreds and `R` in the hundreds of rings; revisit if the spiral
  is expected to run into the thousands of rings.
- Terrain-nudge behavior when the ideal `HexAt` point is unbuildable (candidate offset pattern,
  retry count) — not yet worked out.
- Whether a nudged-away-from-ideal placement should feed back into planning the *next* point from
  the ideal grid position or the actual nudged one — not yet decided.
- `HexIndexOf_test_1.dcs` (`tests/data/`) predates the pseudocode revision above — it implements
  the original flat region-gate cascade (with `d`, the 4-instruction coordinate split, and the
  dead `ry` branch all still present), not the `for_number`/`jump`/`label` restructuring. The
  in-game/test validation below applies to that earlier design; the revised pseudocode is
  design-only until it's rebuilt and re-exported through the same loop.
- `HexIndexOf` now has a `.dcs` (`HexIndexOf_test_1.dcs`, `tests/data/`, round-tripping through
  `HexAt`) and is validated by `desynced-toolkit`'s `tests/test_hex_expansion.py`, which runs both
  routines through the real `data/instructions.lua` via `Interpreter` (217 `(R, T)` cases up to
  `R=8`) — a much stronger check than the original hand-rolled Python re-implementation this was
  first verified against. **Now also loaded and run in the actual game client**: spot-checked
  (not exhaustive) output at several log points was correct. User's reaction to the generated
  node graph itself, though: poor organization/readability — too many single-use temp variables
  cluttering the view, everything clumped together with no grouping/separation (comments helped,
  structure didn't). **Planned follow-up (not yet done):** user will hand-rewrite/reorganize
  `HexIndexOf` in the in-game editor for clarity, then export it back here for a diff against the
  current `HexIndexOf_test_1.dcs` — same build → load → observe → fix → export → diff loop as
  `hexat.dcs` → `hexat2.dcs` earlier in this project. Whatever changes shake out should inform how
  future hand-authored/generated instruction sequences in this project get structured (fewer
  single-use temps, deliberate grouping) — see `combat_squad_spec.md`'s pattern of separating
  design spec from implementation for how that doc records this kind of thing.
