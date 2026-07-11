-- Minimal stand-ins for the engine-side primitives that data/instructions.lua needs but doesn't
-- define itself.
--
-- IMPORTANT, discovered the hard way: `Get`/`Set`/`GetNum` are NOT external engine globals --
-- instructions.lua itself aliases them to its own `InstGet`/`InstSet`/`InstGetNum` (search for
-- "Local references for shorter names" near the top of the file), which resolve every argument
-- through `GetStack` into a uniform integer addressing scheme: `state.mem[j]` for locals/literal
-- constants, `comp.owner:GetRegister(n)` for the 4 frame registers, `CallRadio(...)` for
-- shared/faction registers (not stubbed here yet). So `InstGet`/`InstSet`/`GetStack` are reused
-- UNMODIFIED from the real file -- only the things genuinely missing from this extract are
-- stubbed: the `Value` type's arithmetic operators (confirmed engine-side, not in this extract),
-- and a fake `comp`/`comp.owner`/`Tool` sufficient to drive that addressing scheme.
--
-- Compiled-arg convention this harness uses (ours -- not yet the real GetFactionBehaviorAsm
-- output, see project notes): every instruction arg is a plain Lua integer. Positive integers
-- are `state.mem[]` slots (used for BOTH local variables and literal constants -- the harness's
-- Python-side `Memory` class allocates these, mirroring what the real compiler would do).
-- Negative integers 1..4 select a frame register (Signal/Visual/Store/Goto, per
-- behavior_format.md's table) via `comp.owner:GetRegister`.

-- Confirmed 2026-07-11 via a real in-game test (a behavior with plain `set_reg(Value=N,
-- Target=Result)` calls for N = 0, 1, -2147483647, -2147483648, read back from the Result
-- parameter's UI display) cross-checked against `ui/RegisterSelection.lua`'s own display/parse
-- code three independent ways: the display formatter itself (`self.input.text = (not reg_num
-- and "") or (reg_num == REG_INFINITE and "\xe2\x88\x9e") or (reg_num == REG_NOT and "\xe2\x89\xa0") or tostring(reg_num)`,
-- confirming empty/0/1 as plain text and only these two exact values get the special symbols),
-- the text-input clamp boundary (`math.max(math.min(tonumber(...), 2147483647), REG_NOT+1)` --
-- ordinary typed numbers clamp to [REG_NOT+1, 2147483647], i.e. these two sentinels sit just
-- outside the normal typeable range), and the button tooltips ("Set infinite"/"Set not equal").
-- These are INT32-scale values, not Lua's own 64-bit math.maxinteger/mininteger -- a previous
-- version of this file guessed the latter (right shape, wrong magnitude and, for REG_NOT, wrong
-- sign relative to REG_INFINITE: REG_NOT is the smaller-magnitude sentinel, not the larger).
-- This also retroactively confirms every real behavior reviewed this project that uses the
-- literal `-2147483648` for a "Range"/"Amount" argument (Mining Leader's `Check Emergency`,
-- Fendersons Transport's `dopickup`) was genuinely writing REG_INFINITE, not just "a very large
-- negative number that happens to trip some fallback."
REG_INFINITE = -2147483648
REG_NOT = -2147483647

Value = {}
Value.__index = Value

local function is_value(v)
	return type(v) == "table" and getmetatable(v) == Value
end

-- Field layout confirmed from direct field access in InstGet{Coord,Id,Entity} (`state.mem[j].coord`
-- /`.id`/`.entity`) and InstSet callers constructing raw tables directly (e.g. combine_coordinate's
-- `Set(comp, state, out_coord, { coord = { new_x, new_y } })`, an ARRAY-style coord -- as opposed
-- to the hash-style `{x=,y=}` this doc's own source-literal convention uses). `coord` is normalized
-- to hash style `{x=,y=}` on the way in so downstream `.coord.x`/`.coord.y` access (as
-- separate_coordinate does) works regardless of which shape a caller constructed.
local function normalize_coord(c)
	if c == nil then return nil end
	if c.x ~= nil then return c end
	return { x = c[1], y = c[2] }
end

function NewValue(num, coord, id, entity, item)
	return setmetatable({ num = num or 0, coord = normalize_coord(coord), id = id, entity = entity, item = item }, Value)
end

-- Always builds a FRESH Value, even when `v` is already one -- confirmed against real callers'
-- own comments (set_number's func: "Tool.NewRegisterObject(Get(comp, state, val)) -- copy to
-- avoid changing from"), i.e. `Tool.NewRegisterObject`/`coerce` are relied on elsewhere in
-- data/instructions.lua specifically to decouple a stored copy from its source register. A first
-- version of this stub short-circuited `is_value(v) -> return v` (same reference), which is a
-- real bug: e.g. `memory_insert` pushing a variable's current value onto an array, followed by
-- that same variable's slot later being overwritten in place via `Value:Init()` (any subsequent
-- `set_reg`/`add`/`memory_remove` into it), would silently corrupt the already-pushed array
-- entry too, since it was the same Lua table, not an independent copy. Caught 2026-07-10 building
-- a Fibonacci-via-memory-array test fixture that reuses a pushed value: the sequence came out as
-- powers of 2 instead of Fibonacci numbers, because the "old" value got overwritten in place
-- before the "new" value's own push read it back.
local function coerce(v)
	if is_value(v) then return NewValue(v.num, v.coord, v.id, v.entity, v.item) end
	if type(v) == "number" then return NewValue(v) end
	if type(v) == "table" then
		-- a raw table (not a Value) built directly by some instruction func, e.g.
		-- combine_coordinate's `{ coord = { new_x, new_y } }` -- same fields, not yet a Value
		return NewValue(v.num, v.coord, v.id, v.entity, v.item)
	end
	error("cannot coerce to Value: " .. tostring(v))
end

-- `state.mem[j]` slots are mutable "register object" boxes: InstSet calls `:Init(val)` on the
-- EXISTING slot object to overwrite its contents in place (rather than replacing the table
-- entry), so other references to the same slot see the update without needing to re-fetch it.
function Value:Init(val)
	val = coerce(val)
	self.num, self.coord, self.id, self.entity, self.item = val.num, val.coord, val.id, val.entity, val.item
	return self
end

-- Confirmed rules (add/sub, empirically tested in-game -- see behavior_format.md's "Composite
-- values and the `num` field"): coordinate+coordinate combines both parts; coordinate+bare-number
-- broadcasts the number onto both axes and preserves the coordinate's own `num`; entity/item+
-- bare-number adds `num` normally, the reference passes through. mul/div are NOT confirmed to
-- follow the same rules (behavior_format.md flags this explicitly) -- this stub applies the same
-- broadcast logic to them too as the best available guess; treat that part as unverified.
local function combine(a, b, numOp, coordOp)
	a, b = coerce(a), coerce(b)
	local a_data, b_data = a.coord or a.id or a.entity or a.item, b.coord or b.id or b.entity or b.item
	if a.coord and b.coord then
		return NewValue(numOp(a.num, b.num), { x = coordOp(a.coord.x, b.coord.x), y = coordOp(a.coord.y, b.coord.y) })
	elseif a.coord and not b_data then
		return NewValue(a.num, { x = coordOp(a.coord.x, b.num), y = coordOp(a.coord.y, b.num) })
	elseif b.coord and not a_data then
		return NewValue(b.num, { x = coordOp(a.num, b.coord.x), y = coordOp(a.num, b.coord.y) })
	elseif a.id or a.entity or a.item then
		return NewValue(numOp(a.num, b.num), nil, a.id, a.entity, a.item)
	elseif b.id or b.entity or b.item then
		return NewValue(numOp(a.num, b.num), nil, b.id, b.entity, b.item)
	else
		return NewValue(numOp(a.num, b.num))
	end
end

-- Needed for `jump`'s func, which compares two freshly-`Get()`'d Value objects with plain `==`
-- (`label == Get(comp, state, asm[i][3])`) -- without this, two distinct Value tables holding the
-- same literal number would never compare equal (Lua's default table `==` is identity, not
-- value, comparison). Field-wise equality (unconfirmed against real engine semantics, but the
-- only sensible reading of "same label id").
Value.__eq = function(a, b)
	if a.num ~= b.num then return false end
	if (a.coord == nil) ~= (b.coord == nil) then return false end
	if a.coord and (a.coord.x ~= b.coord.x or a.coord.y ~= b.coord.y) then return false end
	return a.id == b.id and a.entity == b.entity and a.item == b.item
end

Value.__add = function(a, b) return combine(a, b, function(x, y) return x + y end, function(x, y) return x + y end) end
Value.__sub = function(a, b) return combine(a, b, function(x, y) return x - y end, function(x, y) return x - y end) end
Value.__mul = function(a, b) return combine(a, b, function(x, y) return x * y end, function(x, y) return x * y end) end
Value.__idiv = function(a, b) return combine(a, b, function(x, y) return x // y end, function(x, y) return x // y end) end

function InstError(comp, state, err)
	error("InstError: " .. tostring(err))
end

Tool = {}
function Tool.NewRegisterObject(v)
	if v == nil then return NewValue(0) end
	return coerce(v)
end

-- Frame registers (Signal=1, Visual=2, Store=3, Goto=4, per InstGet's `comp.owner:GetRegister(-j)`
-- for `-99 <= j <= 0`) backed by a plain array on a fake `owner` entity.
local Owner = {}
Owner.__index = Owner
function Owner:GetRegister(n) return self.registers[n] or NewValue(0) end
function Owner:SetRegister(n, v) self.registers[n] = coerce(v) end
function Owner:GetRegisterNum(n) return (self.registers[n] or NewValue(0)).num end
function Owner:GetRegisterCoord(n) local r = self.registers[n] return r and r.coord end
function Owner:GetRegisterId(n) local r = self.registers[n] return r and r.id end
function Owner:GetRegisterEntity(n) local r = self.registers[n] return r and r.entity end

-- `wait`'s func (data/instructions.lua) calls `comp:SetStateSleep(t)` and returns `true` when it
-- actually slept (t > 0) -- the real per-tick dispatcher reads this to know to stop running this
-- component for the rest of the current tick. `t` defaults to 1 when omitted (a handful of real
-- callers in data/components.lua use `comp:SetStateSleep()` with no argument at all).
local CompMeta = {}
CompMeta.__index = CompMeta
function CompMeta:SetStateSleep(t)
	self.sleep = t or 1
end

function NewComp()
	return setmetatable({ owner = setmetatable({ registers = {} }, Owner), sleep = 0 }, CompMeta)
end

-- `state.stk = 0` (a plain number, not a table) is GetStack's simplest case: a flat, top-level
-- behavior with no sub-behavior call stack. Under this, GetStack(state, i) resolves any i > 0 to
-- `(i, true)` i.e. `state.mem[i]` (locals + literal constants, uniformly), and any i <= 0 falls
-- through unchanged to InstGet/InstSet's own register-address branches.
--
-- `limit` defaults to 1 -- data.instructions.unlock/.lock's own `explain` text: "By default,
-- behaviors will run one instruction per tick" (limit=1); `unlock` raises it to 10000, `lock`
-- resets it back to 1 (see data/instructions.lua:497-514).
function NewState()
	return { counter = nil, stk = 0, mem = {}, revid = 1, limit = 1 }
end

-- `unlock`'s func checks `Map.GetSettings().block_unlocked_behaviors` (a server-side setting
-- that can disable the instruction entirely) before touching `state.limit` -- stubbed to always
-- report "not blocked" since this harness has no map/server-settings concept.
Map = {}
function Map.GetSettings()
	return { block_unlocked_behaviors = false }
end

-- `jump`'s func scans `GetCachedBehaviorAsm(state.revid)` for a matching `label` instruction --
-- the real compiled-asm array shape isn't reused here (that lives in `GetFactionBehaviorAsm`,
-- data/library.lua, not yet integrated); this harness just needs `asm[i][1] == "label"` and
-- `asm[i][3]` (the label's own arg) to work, so `CurrentAsm` is built by the Python-side driver
-- to satisfy exactly that shape: `{op_name, nil, arg0, arg1, ...}` per instruction, 1-based.
CurrentAsm = nil
function GetCachedBehaviorAsm(revid)
	return CurrentAsm
end

-- The shared global table every data/*.lua file populates (data.instructions, data.components,
-- ...). Only `instructions` is loaded by this harness so far.
data = { instructions = {} }

-- Only top-level (non-func-body) call in data/instructions.lua that needs a real stand-in.
Comp = {}
function Comp:RegisterComponent(...) end
