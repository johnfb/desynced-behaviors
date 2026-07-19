"""Python facade over ``world.lua`` -- the mock world for behavior testing (mock_world_spec.md).

Phase 1 scope: construct factions/entities/tiles and expose the engine-native sensing primitives
(``Map.FindClosestEntity``, ``:MatchFilter``, ``faction:IsSeen``) that the real instruction funcs
call. Movement resolution and multi-entity stepping (``step``) are Phase 3.

Doctrine (CLAUDE.md): world *state* lives in Lua tables whose ``.def`` is the real
``data.frames``/``data.components`` def; Python only *orchestrates* (spawn, mutate, assert). Nothing
here reimplements an instruction or a filter decision -- those stay in the reused game Lua.
"""

from __future__ import annotations

from importlib import resources

from .lua_runtime import LupaEngine

_WORLD_LUA = (
    resources.files(__package__).joinpath("world.lua").read_text(encoding="utf-8")
)


class MockWorld:
    """A populated, steppable mock world sharing one :class:`LupaEngine`.

    Loads ``world.lua`` into the engine's Lua runtime and resets the registry, so a single
    session-scoped engine can host many independent ``MockWorld`` instances (one per test).
    """

    def __init__(self, engine: LupaEngine) -> None:
        if engine.data.frames is None or engine.data.frames.f_bot_1m_c is None:
            raise RuntimeError(
                "MockWorld needs the Data registries loaded "
                "(LupaEngine(..., load_data_registries=True), the default)"
            )
        self.engine = engine
        self.lua = engine.lua
        self.lua.execute(_WORLD_LUA)
        self._World = self.lua.globals().World
        self._Map = self.lua.globals().Map
        self._World.Reset()

    # -- factions -------------------------------------------------------------------------------

    def faction(self, name: str, is_world: bool = False):
        """Get-or-create a faction table. Same name returns the same table."""
        return self._World.MakeFaction(name, is_world)

    def set_trust(self, a, b, level: str) -> None:
        """Set symmetric trust between two factions. `level` is "ALLY"/"ENEMY"/"NEUTRAL"."""
        self._World.SetTrust(a, b, level)

    # -- entities -------------------------------------------------------------------------------

    def spawn(
        self,
        def_id: str,
        faction: str = "player",
        x: int = 0,
        y: int = 0,
        **overrides,
    ):
        """Spawn an entity of real frame/def ``def_id``. ``faction`` may be a name (get-or-created)
        or a faction table. ``overrides`` set location or any state field (e.g.
        ``visibility_range=40``, ``is_damaged=True``, ``is_construction=True``)."""
        fac = self.faction(faction) if isinstance(faction, str) else faction
        ov = self.lua.table_from(overrides) if overrides else None
        return self._World.Spawn(def_id, fac, x, y, ov)

    def add_component(self, entity, comp_id: str):
        """Attach a real component ``comp_id`` to ``entity``; returns the component table."""
        return self._World.AddComponent(entity, comp_id)

    @property
    def entities(self):
        """Live list of spawned entity tables."""
        return [e for _, e in self._World.registry.items()]

    # -- tiles ----------------------------------------------------------------------------------

    def set_tile(
        self,
        x: int,
        y: int,
        *,
        plateau_delta: float | None = None,
        blight_delta: float | None = None,
        landscape_blocked: bool | None = None,
    ) -> None:
        """Author a tile's terrain. Signed deltas: >= 0 means on-plateau / in-blight. Unspecified
        fields keep their open-valley / no-blight / passable defaults."""
        fields = {}
        if plateau_delta is not None:
            fields["plateau_delta"] = plateau_delta
        if blight_delta is not None:
            fields["blight_delta"] = blight_delta
        if landscape_blocked is not None:
            fields["landscape_blocked"] = landscape_blocked
        self._World.SetTile(x, y, self.lua.table_from(fields))

    # -- sensing primitives (direct access; Phase 2 wires these through instruction dispatch) ---

    def distance(self, a, b) -> int:
        """``Map.GetDistance`` between two entities/coords: floored straight-line Euclidean
        (settled in-game by the RangeProbe run; see world.lua's distance-model note)."""
        return int(self._Map.GetDistance(a, b))

    def find_closest(self, owner, range_: int, filter_mask=None):
        """``Map.FindClosestEntity`` with a bare filter mask and no fine predicate -- for testing
        the broad-phase spatial + MatchFilter path directly. A falsy ``filter_mask`` (including the
        ``0`` PrepareFilterEntity returns for an impossible combination) is passed as *no mask*
        (matches any entity in range); build a real mask via :meth:`prepare_filter`."""
        return self._Map.FindClosestEntity(owner, range_, None, filter_mask or None)

    def prepare_filter(self, *filters):
        """Run the real ``PrepareFilterEntity`` over ``(id, num, id, num, ...)`` filter pairs,
        returning ``(mask, override_range)``. Feed the mask to :meth:`find_closest`/MatchFilter."""
        tbl = self.lua.table_from(list(filters))
        return self.lua.globals().PrepareFilterEntity(tbl)

    def is_seen(self, faction, entity) -> bool:
        return bool(faction.IsSeen(faction, entity))
