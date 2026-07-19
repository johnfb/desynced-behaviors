-- Mock world for behavior testing -- Phase 1: engine-native primitives.
--
-- See mock_world_spec.md. This file supplies the small, countable set of genuinely engine-native
-- (C++-side) leaves that the real instruction funcs and FilterEntity/PrepareFilterEntity call but
-- that engine_stub.lua does not provide: the spatial entity registry (Map.FindClosestEntity /
-- GetDistance / GetEntityAt), per-tile terrain reads, and the Entity/Faction/Component metatable
-- methods (:MatchFilter, faction:IsSeen/:IsVisible/:GetTrust/:GetPowerGridIndexAt, register banks).
-- EVERYTHING above this line -- every instruction func, FilterEntity, the arg getters -- is reused
-- unchanged; this is only the mocked leaves (CLAUDE.md's "reuse the real Lua, both data and logic").
--
-- Loaded after the Data registries + instructions.lua, so `data.*`, FilterEntity, the FF_*/FRAMEREG_*
-- constants (from engine_stub.lua), and Map.GetSettings all already exist. Map is EXTENDED here
-- (Map.GetSettings stays as the stub defined it); World is new.
--
-- State lives in Lua, orchestration in Python (mock_world.py). World.Reset() clears it so a
-- session-scoped engine can host many independent MockWorld instances.

World = { registry = {}, factions = {}, deferred = {}, tiles = {}, next_id = 1 }

function World.Reset()
	World.registry = {}
	World.factions = {}
	World.deferred = {}
	World.tiles = {}
	World.next_id = 1
end

--------------------------------------------------------------------------------------------------
-- Geometry helpers
--------------------------------------------------------------------------------------------------

-- Resolve an entity OR a coordinate value to integer tile x,y. Entities carry `.location` ({x=,y=});
-- a coordinate is a plain `{x=,y=}` (the shape InstGetCoord / a Value's `.coord` hands back). Extra
-- args (some real Map.* signatures take a threshold/radius after the target) are ignored.
local function xy_of(target)
	if target == nil then return nil end
	local loc = target.location
	if loc ~= nil then return loc.x, loc.y end
	if target.x ~= nil then return target.x, target.y end
	-- a component: fall back to its owner entity's location
	if target.owner ~= nil and target.owner.location ~= nil then
		return target.owner.location.x, target.owner.location.y
	end
	return nil
end

-- Distance model -- TWO different metrics, deliberately (see mock_world_spec.md "Open items"):
--
-- * Range GATES (Map.FindClosestEntity / Map.GetEntitiesInRange, below) are CHEBYSHEV. This half is
--   confirmed in-game, not a modeling choice: the Blight Magnifier's range=2 coverage is a
--   user-confirmed square (blight_magnifier_mining.md, "Range is Chebyshev distance"), and its
--   implementation is literally `Map.FindClosestEntity(owner, self.range, ..., FF_RESOURCE)`
--   (components.lua, c_blight_magnifier's on_update; the Virus Duplicator's min-spacing check rides
--   the same call) -- so the native FindClosestEntity's range test is a Chebyshev square, and every
--   sensing instruction routed through it (get_closest_entity, for_entities_in_range) inherits that
--   square sensing area.
-- * Map.GetDistance (the get_distance instruction's backend, a separate native function) is rounded
--   Euclidean -- a MODELING CHOICE still awaiting an in-game get_distance test. The 2026-07-18
--   movement measurement pinned *movement cost* to Euclidean path accumulation (diagonal step
--   ~sqrt(2)), so Euclidean is the consistent guess for the distance readout; Chebyshev is not
--   ruled out for it the way it is for movement.
--
-- Still unverified: which metric orders "closest" among gate-passing candidates (the mock uses
-- rounded-Euclidean GetDistance), and the faction-vision bubble's shape (IsSeen/IsVisible below use
-- Euclidean). For a multi-tile entity the real engine measures to the closest tile (see
-- reference_get_distance_closest_tile) -- first-version mock entities are single-tile, so the
-- distinction does not yet arise.
function Map.GetDistance(a, b)
	local ax, ay = xy_of(a)
	local bx, by = xy_of(b)
	if ax == nil or bx == nil then return REG_INFINITE end
	local dx, dy = ax - bx, ay - by
	return math.floor(math.sqrt(dx * dx + dy * dy) + 0.5)
end

-- Chebyshev distance: the confirmed range-gate metric (see the distance-model note above).
local function cheb_distance(a, b)
	local ax, ay = xy_of(a)
	local bx, by = xy_of(b)
	if ax == nil or bx == nil then return REG_INFINITE end
	return math.max(math.abs(ax - bx), math.abs(ay - by))
end

--------------------------------------------------------------------------------------------------
-- Tiles (see mock_world_spec.md "Tile model"). A tile is a tiny record; defaults are open valley,
-- no blight, passable. Authored per-tile as test input via World.SetTile.
--------------------------------------------------------------------------------------------------

local DEFAULT_TILE = { plateau_delta = -1, blight_delta = -1, landscape_blocked = false }

function World:tile(x, y)
	local row = self.tiles[x]
	if row == nil then return DEFAULT_TILE end
	return row[y] or DEFAULT_TILE
end

function World.SetTile(x, y, fields)
	local row = World.tiles[x]
	if row == nil then row = {} World.tiles[x] = row end
	local t = row[y]
	if t == nil then t = { plateau_delta = -1, blight_delta = -1, landscape_blocked = false } row[y] = t end
	if fields.plateau_delta ~= nil then t.plateau_delta = fields.plateau_delta end
	if fields.blight_delta ~= nil then t.blight_delta = fields.blight_delta end
	if fields.landscape_blocked ~= nil then t.landscape_blocked = fields.landscape_blocked end
	return t
end

-- Signed deltas: >= 0 means on-plateau / in-blight (matches FilterEntity's v_plateau/v_blight tests
-- and the check_altitude/check_blightness instructions). Called three ways in the real funcs:
-- `(entity)`, `(entity, threshold)`, and `(x, y, threshold)` -- so accept an entity/coord OR a
-- literal x,y pair; trailing threshold args are ignored (first-version tiles have no sub-threshold).
local function delta_xy(a, b)
	if type(a) == "number" and type(b) == "number" then return a, b end
	return xy_of(a)
end

function Map.GetPlateauDelta(a, b)
	local x, y = delta_xy(a, b)
	if x == nil then return -1 end
	return World:tile(x, y).plateau_delta
end

function Map.GetBlightnessDelta(a, b)
	local x, y = delta_xy(a, b)
	if x == nil then return -1 end
	return World:tile(x, y).blight_delta
end

function Map.GetTileData(x, y)
	local t = World:tile(x, y)
	-- The engine exposes continuous noise fields here; the mock only tracks what gameplay consumes
	-- via the deltas above, so these are nominal. Widen only if a test needs raw GetTileData.
	return { blightness = t.blight_delta, elevation = t.plateau_delta, richness = 0, variation = 0 }
end

--------------------------------------------------------------------------------------------------
-- Factions
--------------------------------------------------------------------------------------------------

local Faction = {}
Faction.__index = Faction

function World.MakeFaction(name, is_world)
	local f = World.factions[name]
	if f then return f end
	f = setmetatable({ name = name, is_world_faction = is_world or false, trust = {} }, Faction)
	World.factions[name] = f
	return f
end

-- Trust is symmetric here (the game's can differ per direction, but the first-version mock has no
-- one-sided-trust test). Levels are the engine's own strings: "ALLY" / "ENEMY" / "NEUTRAL".
function World.SetTrust(a, b, level)
	a.trust[b] = level
	b.trust[a] = level
end

-- Real call shapes in data/instructions.lua, all three of which must work here:
--   faction:GetTrust(other_faction)        -> "ALLY"/"ENEMY"/"NEUTRAL"  (gettrust's dispatch)
--   faction:GetTrust(entity)               -> same, via the entity's own faction (transfer checks)
--   faction:GetTrust(entity, "ALLY")       -> boolean comparison form (for_inventory_item's
--                                             `comp.faction:GetTrust(ent, "ALLY")`)
-- The "OWN" return for self is a mock invention (the engine's own-faction return value is
-- unobserved); real consumers only ever dispatch on ALLY/ENEMY/NEUTRAL, so anything else falls
-- through their branches, which "OWN" reproduces safely.
function Faction:GetTrust(other, compare)
	local f = other
	if f ~= nil and f.faction ~= nil then f = f.faction end -- an entity: resolve to its faction
	local level
	if f == self then level = "OWN" else level = self.trust[f] or "NEUTRAL" end
	if compare ~= nil then return level == compare end
	return level
end

-- First-version vision model (mock_world_spec.md Phase 1): an entity is "seen" if it is on this
-- faction's own side, or lies within the visibility_range of ANY of this faction's entities. Honest
-- but not fog-of-war-accurate -- the squad's premise is only that the vision lock is real, not
-- pixel-perfect.
function Faction:IsSeen(e)
	if e == nil then return false end
	if e.faction == self then return true end
	for _, w in pairs(World.registry) do
		if w.exists and w.faction == self and (w.visibility_range or 0) > 0 then
			if Map.GetDistance(w, e) <= w.visibility_range then return true end
		end
	end
	return false
end

-- Called two ways in the real funcs: `faction:IsVisible(x, y)` (is_passable) and `faction:IsVisible(e)`.
function Faction:IsVisible(a, b)
	if b ~= nil then
		-- coordinate form: visible if within any own entity's visibility_range
		for _, w in pairs(World.registry) do
			if w.exists and w.faction == self and (w.visibility_range or 0) > 0 then
				if Map.GetDistance(w, { x = a, y = b }) <= w.visibility_range then return true end
			end
		end
		return false
	end
	return self:IsSeen(a)
end

-- Broad-phase signal scan (`for_signal_match`): return own-faction entities that currently hold a
-- non-empty signal register value. The real for_signal_match func re-filters these precisely (by
-- signal id, or an embedded-entity MatchFilter), so this only supplies the candidate set.
function Faction:GetEntitiesWithRegister(reg_index, signal, include_flag)
	local out = {}
	for _, e in pairs(World.registry) do
		if e.exists and e.faction == self then
			local r = e.registers[reg_index]
			if r ~= nil and not (r.num == 0 and r.id == nil and r.entity == nil and r.coord == nil) then
				out[#out + 1] = e
			end
		end
	end
	return out
end

-- Fog-of-war "has this tile been discovered". First-version mock has no fog model -- everything is
-- discovered (check_altitude/check_blightness gate on this).
function Faction:IsDiscovered(coord)
	return true
end

-- Power grid: first-version mock has no grid model, so nil (v_in_powergrid -> false, and the
-- autobase same-grid remote-write path stays inert). An entity/coord may carry a `.power_grid`
-- field to opt into a simple explicit model.
function Faction:GetPowerGridIndexAt(target)
	if target == nil then return nil end
	if target.power_grid ~= nil then return target.power_grid end
	if target.owner ~= nil then return target.owner.power_grid end
	return nil
end

--------------------------------------------------------------------------------------------------
-- Entities
--------------------------------------------------------------------------------------------------

-- Frametype bits for MatchFilter, derived from the real def. The FF_* layout is engine_stub.lua's
-- own self-consistent scheme (documented there): only PrepareFilterEntity (producer) and this
-- consumer share it, so they need only agree with each other. Discriminations FilterEntity makes
-- more finely (bot vs building by movement_speed, scattered-resource by name) ride on FF_OPERATING /
-- FF_DROPPEDITEM and are settled by the real FilterEntity predicate afterward, not here.
local function frametype_bits(e)
	if e.is_construction then return FF_CONSTRUCTION end
	local edef = e.def
	local t = edef.type
	if t == "Resource" then return FF_RESOURCE end
	if t == "DroppedItem" then return FF_DROPPEDITEM end
	if t == "Foundation" then return FF_FOUNDATION end
	return FF_OPERATING
end

-- Entity's faction bit RELATIVE to the querying faction -- the relational half of a filter mask
-- (own/enemy/ally/neutral/world). Matches how PrepareFilterEntity narrows the faction bits and how
-- FilterEntity's own faction predicates read (e.faction.is_world_faction, GetTrust).
local function relative_faction_bit(ef, qf)
	if ef == qf then return FF_OWNFACTION end
	if ef.is_world_faction then return FF_WORLDFACTION end
	local trust = ef:GetTrust(qf)
	if trust == "ALLY" then return FF_ALLYFACTION end
	if trust == "ENEMY" then return FF_ENEMYFACTION end
	return FF_NEUTRALFACTION
end

local Entity = {}
Entity.__index = Entity

-- Frame registers (Signal=1, Visual=2, Store=3, Goto=4) -- same bank the engine_stub Owner models,
-- reachable from InstGet as `comp.owner:GetRegister(1..4)`. Values are coerced through the global
-- Tool.NewRegisterObject (engine_stub) so downstream `.num`/`.coord`/`.id`/`.entity` reads work.
function Entity:GetRegister(n) return self.registers[n] or NewValue(0) end
function Entity:SetRegister(n, v) self.registers[n] = Tool.NewRegisterObject(v) end
function Entity:GetRegisterNum(n) return (self.registers[n] or NewValue(0)).num end
function Entity:GetRegisterCoord(n) local r = self.registers[n] return r and r.coord end
function Entity:GetRegisterId(n) local r = self.registers[n] return r and r.id end
function Entity:GetRegisterEntity(n) local r = self.registers[n] return r and r.entity end

function Entity:GetLocationXY() return self.location.x, self.location.y end
function Entity:GetRangeSquaredTo(other)
	local ax, ay = self.location.x, self.location.y
	local bx, by = xy_of(other)
	if bx == nil then return math.huge end
	local dx, dy = ax - bx, ay - by
	return dx * dx + dy * dy
end

function Entity:CountItem(id) return self.inventory[id] or 0 end

-- Exact-id component lookup. base_id-family matching (has_like_component) and UI-order indexing are
-- later refinements; the sensing/movement phase only needs presence-by-id.
function Entity:FindComponent(id)
	for _, c in ipairs(self.components) do
		if c.id == id then return c end
	end
	return nil
end

-- Adjacency (`ent:IsTouching(comp)`): true when the two entities occupy neighboring tiles
-- (8-connected) or the same tile. Used by the remote-register adjacency gate.
function Entity:IsTouching(comp)
	local other = comp.owner or comp
	local ox, oy = xy_of(other)
	if ox == nil then return false end
	return math.abs(self.location.x - ox) <= 1 and math.abs(self.location.y - oy) <= 1
end

-- mask = PrepareFilterEntity(...)'s combined frametype|faction integer; `faction` is the querying
-- faction. Split the mask: low bits (& FF_ALL) are the frametype constraint, high bits the faction
-- constraint. A 0 mask (PrepareFilterEntity found an impossible combination) matches nothing.
function Entity:MatchFilter(mask, faction)
	if mask == 0 then return false end -- PrepareFilterEntity returns 0 for an impossible combo
	local ft = mask & FF_ALL
	local fc = mask & ~FF_ALL
	-- A 0 sub-part means "unconstrained on that axis": PrepareFilterEntity always leaves both parts
	-- populated (frametype starts FF_ALL, faction starts all-bits), but some internal FilterEntity
	-- calls pass a hand-written faction-only constant (e.g. FF_ENEMYFACTION) with no frametype bits.
	if ft ~= 0 and (frametype_bits(self) & ft) == 0 then return false end
	if fc ~= 0 and (relative_faction_bit(self.faction, faction) & fc) == 0 then return false end
	return true
end

-- Movement (Phase 3 completes resolution in MockWorld.step). For Phase 1 these record the goal and
-- report "still moving" -- enough for the structure to exist; NOT yet a faithful arrival model.
function Entity:MoveTo(target, range)
	self.move_goal = { target = target, range = range or 0 }
end

--------------------------------------------------------------------------------------------------
-- Components (a behavior's `comp`). Minimal here; behavior attachment is Phase 3.
--------------------------------------------------------------------------------------------------

local Component = {}
Component.__index = Component

function Component:GetRegister(n) return self.registers[n] or NewValue(0) end
function Component:SetRegister(n, v) self.registers[n] = Tool.NewRegisterObject(v) end
function Component:GetRegisterNum(n) return (self.registers[n] or NewValue(0)).num end
function Component:GetRegisterCoord(n) local r = self.registers[n] return r and r.coord end
function Component:GetRegisterId(n) local r = self.registers[n] return r and r.id end
function Component:GetRegisterEntity(n) local r = self.registers[n] return r and r.entity end
function Component:SetStateSleep(t) self.sleep = t or 1 end

-- Records a move goal on the OWNER and reports (need_move, repeat_blocked). Phase 3 replaces the
-- always-"need_move=true" with real per-tick tile advance so arrival-gated loops terminate.
function Component:RequestStateMove(target, range)
	self.owner.move_goal = { target = target, range = range or 0 }
	return true, false
end

function Component:FindComponent(id) return self.owner:FindComponent(id) end

--------------------------------------------------------------------------------------------------
-- Spawning
--------------------------------------------------------------------------------------------------

-- Build an entity table whose `.def` IS the real data.frames[def_id] (or any data.all def), so
-- movement_speed / visibility_range / socket layout / type all come from real data. `faction` is a
-- faction table (World.MakeFaction). `overrides` may set location and any state flag / field.
function World.Spawn(def_id, faction, x, y, overrides)
	local def = data.frames[def_id] or data.all[def_id]
	assert(def, "World.Spawn: no such frame/def id: " .. tostring(def_id))
	overrides = overrides or {}

	local e = setmetatable({
		eid = World.next_id, -- stable registry id (lupa makes a fresh proxy per access, so Python
		                     -- identity `is` fails on the same entity; compare `.eid`)
		id = def_id,
		def = def,
		visual_def = {}, -- explorable_race lives here in the real data; empty is the common case
		faction = faction,
		location = { x = x or 0, y = y or 0 },
		registers = {},
		components = {},
		inventory = {},
		exists = true,
		is_construction = false,
		health = def.health_points or 100,
		max_health = def.health_points or 100,
		visibility_range = def.visibility_range or 0,
		-- FilterEntity state flags; all default falsey. A test flips whichever it exercises.
		is_damaged = false,
		state_custom_1 = false, -- infected
		state_unpowered = false,
		powered_down = false,
		is_moving = false,
		state_path_blocked = false,
		state_idle = false,
		state_emergency = false,
		state_broken = false,
		has_extra_data = false,
		lootable = false,
	}, Entity)

	for k, v in pairs(overrides) do e[k] = v end

	World.registry[World.next_id] = e
	World.next_id = World.next_id + 1
	return e
end

-- Attach a component (by real data.components id) to an entity, giving it its own register bank and
-- owner/faction back-references. Returns the component.
function World.AddComponent(entity, comp_id, register_count)
	local def = data.components[comp_id] or data.all[comp_id]
	assert(def, "World.AddComponent: no such component id: " .. tostring(comp_id))
	local c = setmetatable({
		id = comp_id,
		def = def,
		owner = entity,
		faction = entity.faction,
		registers = {},
		sleep = 0,
	}, Component)
	entity.components[#entity.components + 1] = c
	return c
end

--------------------------------------------------------------------------------------------------
-- Map spatial primitives over the registry
--------------------------------------------------------------------------------------------------

-- Closest entity to `owner` within `range` for which `pred(e)` is truthy, applying the broad-phase
-- `filter` mask (MatchFilter) first exactly as the real callers rely on (get_closest_entity's pred
-- only calls FilterEntity, trusting FindClosestEntity to have masked by frametype/faction already).
-- The owner is excluded -- radar returns OTHER units, never self. The range gate is Chebyshev
-- (confirmed in-game via the magnifier -- see the distance-model note above); "closest" ordering
-- among gate-passers uses rounded-Euclidean GetDistance (unverified, flagged there).
function Map.FindClosestEntity(owner, range, pred, filter)
	local best, best_d = nil, nil
	for _, e in pairs(World.registry) do
		if e ~= owner and e.exists then
			local d = Map.GetDistance(owner, e)
			if cheb_distance(owner, e) <= range then
				if (not filter or e:MatchFilter(filter, owner.faction)) and (not pred or pred(e)) then
					if best_d == nil or d < best_d then best, best_d = e, d end
				end
			end
		end
	end
	return best
end

-- All entities within `range` of `center` (entity or coord), optionally masked by a filter and
-- faction. Backs get_entities_in_range / the for_entities_in_range block driver and FilterEntity's
-- own internal Map.GetEntitiesInRange calls. Chebyshev gate, same as FindClosestEntity above.
function Map.GetEntitiesInRange(center, range, filter, faction)
	local out = {}
	for _, e in pairs(World.registry) do
		if e.exists and cheb_distance(center, e) <= range then
			if not filter or e:MatchFilter(filter, faction or (center.faction)) then
				out[#out + 1] = e
			end
		end
	end
	return out
end

-- Ground occupancy: at most one non-flying entity per tile (first-version invariant). Returns the
-- first entity found on the tile.
function Map.GetEntityAt(x, y)
	for _, e in pairs(World.registry) do
		if e.exists and e.location.x == x and e.location.y == y then return e end
	end
	return nil
end

-- Deferred callbacks (EntityAction/Undock/Destroy etc. schedule onto here); MockWorld.step drains
-- them once behaviors have advanced (Phase 3). Exposed for the Python facade to flush.
function Map.Defer(fn)
	World.deferred[#World.deferred + 1] = fn
end

function World.DrainDeferred()
	local q = World.deferred
	World.deferred = {}
	for _, fn in ipairs(q) do fn() end
	return #q
end

-- blocked_landscape, blocked_entity, area_total, area_passable -- the 4 returns is_passable /
-- construction logic read. First arg may be a coord pair or an entity (then the radius follows).
function Map.CountTiles(a, b, layer, single)
	local x, y = xy_of(a)
	if x == nil then x, y = a, b end -- called as (x, y, ...)
	local t = World:tile(x, y)
	local bl = t.landscape_blocked and 1 or 0
	local be = Map.GetEntityAt(x, y) and 1 or 0
	local passable = (bl == 0 and be == 0) and 1 or 0
	return bl, be, 1, passable
end
