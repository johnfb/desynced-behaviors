"""Runs the *real* `data/instructions.lua` (from the game extract) inside an embedded Lua
runtime (via ``lupa``), with just enough engine-side stand-ins (``engine_stub.lua``) to actually
call each instruction's `func`. See ``engine_stub.lua``'s module docstring for the important
discovery that shaped this design: `Get`/`Set`/`GetNum` are local aliases *within*
instructions.lua for its own `InstGet`/`InstSet`/`InstGetNum`, which this harness reuses
unmodified rather than reimplementing -- only the genuinely-external engine primitives (the
`Value` type's arithmetic, and a fake `comp`/`comp.owner`/`Tool`) are stubbed.
"""

from __future__ import annotations

from importlib import resources

import lupa

from .assets import AssetSource, get_package_manifest, resolve_include


class LupaEngine:
    def __init__(self, source: AssetSource, package_id: str = "Data") -> None:
        self.lua = lupa.LuaRuntime(unpack_returned_tuples=True)
        stub = (
            resources.files(__package__)
            .joinpath("engine_stub.lua")
            .read_text(encoding="utf-8")
        )
        self.lua.execute(stub)

        pm = get_package_manifest(source, package_id)
        instructions_path = resolve_include(pm.entry_dir, "instructions.lua")
        self.lua.execute(source.read_text(instructions_path))

        self.data = self.lua.globals().data
        self._new_state = self.lua.globals().NewState
        self._new_comp = self.lua.globals().NewComp
        self._new_value = self.lua.globals().NewValue
        self._table = self.lua.table
        # `Get`/`GetNum` are local aliases *inside* instructions.lua for these (see
        # engine_stub.lua's docstring) -- the globals are what's reachable from outside.
        self._inst_get = self.lua.globals().InstGet
        self._inst_get_num = self.lua.globals().InstGetNum

    def new_state(self):
        return self._new_state()

    def new_comp(self):
        return self._new_comp()

    def new_value(
        self, num: int = 0, coord: tuple[int, int] | None = None, id_: str | None = None
    ):
        lua_coord = self._table(x=coord[0], y=coord[1]) if coord is not None else None
        return self._new_value(num, lua_coord, id_)

    def get_value(self, comp, state, arg):
        return self._inst_get(comp, state, arg)

    def get_num(self, comp, state, arg) -> int:
        return self._inst_get_num(comp, state, arg)

    def call(self, op: str, comp, state, *args):
        """Calls data.instructions[op].func(comp, state, cause=None, *args) directly."""
        instr = self.data.instructions[op]
        if instr is None:
            raise KeyError(f"no such instruction: {op}")
        return instr.func(comp, state, None, *args)


# Frame register name -> the negative-int arg convention already documented in
# behavior_format.md (Signal=-1, Visual=-2, Store=-3, Goto=-4).
FRAME_REGISTERS = {"Signal": -1, "Visual": -2, "Store": -3, "Goto": -4}


class Memory:
    """Allocates `state.mem[]` slots for literals and named local variables. Mirrors (a simple
    version of) what the real compiler (`GetFactionBehaviorAsm`, not yet reused here) would do
    when interning a behavior's locals/constants into its flat runtime memory array."""

    def __init__(self, engine: LupaEngine, state) -> None:
        self.engine = engine
        self.state = state
        self._next_slot = 1
        self._vars: dict[str, int] = {}

    def _alloc(self) -> int:
        slot = self._next_slot
        self._next_slot += 1
        return slot

    def literal(
        self, num: int = 0, coord: tuple[int, int] | None = None, id_: str | None = None
    ) -> int:
        slot = self._alloc()
        self.state.mem[slot] = self.engine.new_value(num, coord, id_)
        return slot

    def var(self, name: str) -> int:
        if name not in self._vars:
            slot = self._alloc()
            self.state.mem[slot] = self.engine.new_value(0)
            self._vars[name] = slot
        return self._vars[name]

    def read(self, slot_or_name: int | str):
        slot = self.var(slot_or_name) if isinstance(slot_or_name, str) else slot_or_name
        return self.state.mem[slot]
