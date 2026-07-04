"""Runs a `dsc_codec.py`-decoded instruction dict (the JSON source-level format documented in
behavior_format.md) by delegating each leaf instruction's execution to the real
`data/instructions.lua` via `LupaEngine`, while keeping the branch/block control-flow driver in
Python (the same model validated against real in-game logs in `sim_common.py` earlier in this
project -- `sequence`/`for_number`'s block-stack semantics are simulated here rather than routed
through the real `InstBeginBlock`, which would require also reusing the real per-tick dispatcher
in data/library.lua; a later phase, not done yet). `jump`/`label` and every arithmetic/branch/
coordinate instruction run as the genuine, unmodified game Lua.
"""

from __future__ import annotations

from .lua_runtime import LupaEngine, Memory


def _resolve_next(instr: dict, key: str | None, default):
    raw = instr.get(key) if key is not None else instr.get("next")
    if raw is None:
        return default
    if raw is False:
        return None
    return raw - 1


def _seq_targets(instr: dict, i: int):
    targets = []
    for key in ("0", "1", "2", "3"):
        v = instr.get(key)
        if v is False:
            continue
        t = _resolve_next(instr, key, i + 1)
        targets.append(lambda t=t: t)
    v4 = instr.get("4")
    if v4 is not False:
        t = _resolve_next(instr, "4", i + 1)
        targets.append(lambda t=t: t)
    return targets


class Interpreter:
    def __init__(
        self, engine: LupaEngine, instrs: dict, params: dict[int, object] | None = None
    ) -> None:
        self.engine = engine
        self.instrs = instrs
        self.n = len([k for k in instrs if k.isdigit()])
        self.state = engine.new_state()
        self.comp = engine.new_comp()
        self.mem = Memory(engine, self.state)
        # reserve mem slots 1..N for declared parameters (matching the JSON source's own
        # convention of plain positive ints for parameter references) -- every slot needs a
        # real Value object up front (even output params with no initial value), since InstSet
        # mutates the existing slot in place via `:Init()` rather than replacing it
        n_params = len(instrs.get("parameters", []))
        for idx in range(1, n_params + 1):
            self.state.mem[idx] = self.engine.new_value(0)
        self.mem._next_slot = n_params + 1
        for idx, value in (params or {}).items():
            self.state.mem[idx] = self._value_for(value)
        self._build_current_asm()

    def _value_for(self, py_value):
        if isinstance(py_value, tuple):
            return self.engine.new_value(0, coord=py_value)
        return self.engine.new_value(py_value)

    def _translate_arg(self, v):
        """JSON arg -> Lua-callable arg (a mem slot int, or a negative frame-register int)."""
        if isinstance(v, dict):
            num = v.get("num", 0)
            coord = (v["coord"]["x"], v["coord"]["y"]) if "coord" in v else None
            id_ = v.get("id")
            return self.mem.literal(num=num, coord=coord, id_=id_)
        if isinstance(v, str):
            return self.mem.var(v)
        if isinstance(v, bool):
            raise ValueError(f"unexpected bool value arg: {v}")
        if isinstance(v, int):
            return v  # already a mem slot (param) or frame register
        raise ValueError(f"unrecognized arg: {v!r}")

    def _build_current_asm(self) -> None:
        """`jump`'s func scans GetCachedBehaviorAsm(state.revid) -- build the matching array
        (1-based, `{op, nil, arg0, arg1, ...}` per instruction) using the SAME mem-slot
        translation that instruction execution itself uses, so Get()-equality in `jump` lines up
        with the slots instructions actually read/write."""
        t = self.engine.lua.table
        rows = []
        for i in range(self.n):
            instr = self.instrs[str(i)]
            args = [
                self._translate_arg(instr[k])
                for k in sorted((k for k in instr if k.isdigit()), key=int)
                if not isinstance(instr[k], bool)
            ]
            rows.append(
                t("label" if instr["op"] == "label" else instr["op"], None, *args)
            )
        self.engine.lua.globals().CurrentAsm = t(*rows)
        self._asm_args = None  # args already baked into CurrentAsm; reuse below

    def run(self, max_steps: int = 20000) -> None:
        blocks: list[dict] = []

        def dead_end():
            while blocks:
                block = blocks[-1]
                if block["thunks"]:
                    return block["thunks"].pop(0)()
                blocks.pop()
                if block["done"] is not None:
                    return block["done"]
            return None

        i = 0
        steps = 0
        while 0 <= i < self.n:
            steps += 1
            if steps > max_steps:
                raise RuntimeError("runaway")
            instr = self.instrs[str(i)]
            op = instr["op"]
            nexti = i + 1

            if op in ("unlock", "lock", "label", "nop"):
                pass
            elif op == "sequence":
                blocks.append({"thunks": _seq_targets(instr, i), "done": None})
                nxt = dead_end()
                if nxt is None:
                    return
                i = nxt
                continue
            elif op == "exit":
                return
            elif op == "check_number":
                value_arg = self._translate_arg(instr.get("2", {"num": 0}))
                compare_arg = self._translate_arg(instr.get("3", {"num": 0}))
                self.state.counter = None
                self.engine.call(
                    op, self.comp, self.state, None, None, value_arg, compare_arg
                )
                # re-dispatch using OUR semantics (If Larger/If Smaller resolved via the JSON's
                # own next-encoding), not the raw asm-index the real func would set, since we
                # didn't wire it to CurrentAsm's 1-based indices for this instruction
                a = self.engine.get_num(self.comp, self.state, value_arg)
                b = self.engine.get_num(self.comp, self.state, compare_arg)
                if a > b:
                    nexti = _resolve_next(instr, "0", i + 1)
                elif a < b:
                    nexti = _resolve_next(instr, "1", i + 1)
                else:
                    nexti = _resolve_next(instr, None, i + 1)
                if nexti is None:
                    nxt = dead_end()
                    if nxt is None:
                        return
                    i = nxt
                    continue
                i = nexti
                continue
            elif op == "jump":
                label_arg = self._translate_arg(instr["0"])
                self.state.lastcounter = i + 1
                self.state.counter = None
                self.engine.call(op, self.comp, self.state, label_arg)
                if self.state.counter is not None:
                    i = int(self.state.counter) - 1
                    continue
                nexti = _resolve_next(instr, None, i + 1)
            elif op in ("add", "sub", "mul", "div"):
                a = self._translate_arg(instr["0"])
                b = self._translate_arg(instr["1"])
                res_slot = (
                    self.mem.var(instr["2"])
                    if isinstance(instr["2"], str)
                    else instr["2"]
                )
                self.engine.call(op, self.comp, self.state, a, b, res_slot)
            elif op == "set_reg":
                a = self._translate_arg(instr.get("0", {"num": 0}))
                target_slot = (
                    self.mem.var(instr["1"])
                    if isinstance(instr["1"], str)
                    else instr["1"]
                )
                self.engine.call("set_reg", self.comp, self.state, a, target_slot)
            elif op == "combine_coordinate":
                a = self._translate_arg(instr["0"])
                b = self._translate_arg(instr["1"])
                res_slot = (
                    self.mem.var(instr["2"])
                    if isinstance(instr["2"], str)
                    else instr["2"]
                )
                self.engine.call(op, self.comp, self.state, a, b, res_slot)
            elif op == "separate_coordinate":
                a = self._translate_arg(instr["0"])
                x_slot = (
                    self.mem.var(instr["1"])
                    if isinstance(instr["1"], str)
                    else instr["1"]
                )
                y_slot = (
                    self.mem.var(instr["2"])
                    if isinstance(instr["2"], str)
                    else instr["2"]
                )
                self.engine.call(op, self.comp, self.state, a, x_slot, y_slot)
            else:
                raise RuntimeError(f"unhandled op {op}")

            if "next" in instr:
                nexti2 = _resolve_next(instr, None, None)
                if nexti2 is None:
                    nxt = dead_end()
                    if nxt is None:
                        return
                    i = nxt
                    continue
                nexti = nexti2
            i = nexti

    def read_param(self, idx: int):
        return self.engine.get_value(self.comp, self.state, idx)
