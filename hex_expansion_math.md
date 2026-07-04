# Hex-Ring Expansion Math — Reference

Coordinate math for a behavior that expands a power-pole network outward from an origin in a
hexagonal spiral, one ring at a time, checking each candidate point against the logistics network
before building. Worked out in conversation. `HexAt` below is implemented and validated in-game
as a reusable sub-behavior (`hexat_test.dsc`, `tests/data/` — a `HexAt(R, T, Origin, d_half) ->
Result` sub-behavior plus a test harness that calls it for every `R=0..5, T=0..6R-1` and logs the
result); `HexIndexOf` also has a `.dsc` now (`HexIndexOf_test_1.dsc`, `tests/data/`), validated by
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
once when the behavior is authored." The implemented `HexAt` (`hexat_test.dsc`) splits that
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

Implemented and in-game-validated (`hexat_test.dsc`, 92/92 `(R, T)` cases across `R=0..5`
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
  computation. This was simply how the in-game visual graph came out, not a hard requirement — a
  flat chain would compute the same result.

Verified by hand for `R=1, T=0..5` against the original per-side derivation (reproduces
`dir[4], dir[5], dir[0], dir[1], dir[2], dir[3]` in order, i.e. the six neighbors of the origin);
then re-verified against all 92 `(R, T)` pairs the in-game test harness actually logged.

## Inverse: `HexIndexOf(Coord, Origin, d_half) → (R, T)`

Converts the input coordinate to fractional axial, rounds to the nearest actual hex lattice point
using cube rounding (rounding `q` and `r` independently can pick the wrong hex), then reads off
which ring/side/step it landed on. Rounding is deferred to the last possible step — all
intermediate values are carried as exact-integer numerators over a shared denominator `Den`, per
the "rational ratios partway through" approach (avoids any premature precision loss, and lets the
cube-rounding error comparison work on exact integers instead of fractions).

**Not yet implemented or in-game-validated** (unlike `HexAt` — see `hexat_test.dsc`). The
pseudocode below has been reworked to use the same idioms `HexAt` proved out, but hasn't itself
been through the build → load → observe → fix loop, so treat the control-flow restructuring
(the shared `done` tail, the region-gate cascade) as a design carried over by analogy, not as
independently confirmed.

Signature matches `HexAt`'s convention (see previous section): takes `d_half`, not `d` — `d` and
`Den` are both derived internally from it, never caller-visible, same reasoning as `HexAt`.

```
d   = d_half * 2
Den = 2 * d * K                      # = 4 * d_half * K

dx = Coord.x - Origin.x
dy = Coord.y - Origin.y

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
if err_x > err_y and err_x > err_z:  rx = -ry - rz
elif err_y > err_z:                   ry = -rx - rz
else:                                  rz = -rx - ry

q, r = rx, rz
R = max(abs(q), abs(r), abs(q+r))    # pairwise Compare Number, per "Why integer-only"
if R == 0: return (0, 0)             # same check_number equal-idiom as HexAt's R==0 guard

# Region detection: first region whose t lands in [0, R-1] wins (corners satisfy two at once), so
# this stays a Compare-Number cascade with early exit, not a computed jump table -- `k` is exactly
# what's being solved for here, so (per behavior_format.md's note on `jump`/`label`) there's
# nothing to dispatch on until a region has already matched. What *does* carry over from HexAt:
# each region that matches sets k/t and Jumps straight to one shared `done` tail, instead of each
# region duplicating the `T = k*R + t; return` logic the way the original draft of this pseudocode
# inlined it six times.
#
# Each region gate is an equality test (via the same equal-idiom) AND a `t in [0, R-1]` range
# test (two more check_numbers: fail if t < 0, fail if t > R-1); failing either falls through to
# the next region's gate.

region(0): gate r == R,     then (q+R) in [0,R-1];  on pass: k=0; t=q+R;  Jump(done)
region(1): gate q+r == R,   then q     in [0,R-1];  on pass: k=1; t=q;    Jump(done)
region(2): gate q == R,     then (-r)  in [0,R-1];  on pass: k=2; t=-r;   Jump(done)
region(3): gate r == -R,    then (R-q) in [0,R-1];  on pass: k=3; t=R-q;  Jump(done)
region(4): gate q+r == -R,  then (-q)  in [0,R-1];  on pass: k=4; t=-q;   Jump(done)
region(5): gate q == -R,    then r     in [0,R-1];  on pass: k=5; t=r;    # last region, falls through

done:
T = k*R + t
return (R, T)
```

## Open items / not yet decided

- Overflow headroom: `SCALE=10000` keeps `d*r*K` and similar products well under the int32 ceiling
  (~2.1×10^9) for `d` in the low hundreds and `R` in the hundreds of rings; revisit if the spiral
  is expected to run into the thousands of rings.
- Terrain-nudge behavior when the ideal `HexAt` point is unbuildable (candidate offset pattern,
  retry count) — not yet worked out.
- Whether a nudged-away-from-ideal placement should feed back into planning the *next* point from
  the ideal grid position or the actual nudged one — not yet decided.
- `HexIndexOf` now has a `.dsc` (`HexIndexOf_test_1.dsc`, `tests/data/`, round-tripping through
  `HexAt`) and is validated by `desynced-toolkit`'s `tests/test_hex_expansion.py`, which runs both
  routines through the real `data/instructions.lua` via `Interpreter` (217 `(R, T)` cases up to
  `R=8`) — a much stronger check than the original hand-rolled Python re-implementation this was
  first verified against. **Now also loaded and run in the actual game client**: spot-checked
  (not exhaustive) output at several log points was correct. User's reaction to the generated
  node graph itself, though: poor organization/readability — too many single-use temp variables
  cluttering the view, everything clumped together with no grouping/separation (comments helped,
  structure didn't). **Planned follow-up (not yet done):** user will hand-rewrite/reorganize
  `HexIndexOf` in the in-game editor for clarity, then export it back here for a diff against the
  current `HexIndexOf_test_1.dsc` — same build → load → observe → fix → export → diff loop as
  `hexat.dsc` → `hexat2.dsc` earlier in this project. Whatever changes shake out should inform how
  future hand-authored/generated instruction sequences in this project get structured (fewer
  single-use temps, deliberate grouping) — see `combat_squad_spec.md`'s pattern of separating
  design spec from implementation for how that doc records this kind of thing.
