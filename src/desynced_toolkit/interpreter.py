"""Runs a behavior given as a genuine Lua table (the shape `dcs_wire.decode_dcs()` hands back,
and `bsf.compile_behavior` produces directly) by delegating each leaf instruction's execution
to the real `data/instructions.lua` via `LupaEngine`, while keeping the branch/block control-flow
driver in Python (the same model validated against real in-game logs in `sim_common.py` earlier
in this project -- `sequence`/`for_number`'s block-stack semantics are simulated here rather than
routed through the real `InstBeginBlock`, which would require also reusing the real per-tick
dispatcher in data/library.lua; a later phase, not done yet). `jump`/`label` and every arithmetic/
branch/coordinate instruction run as the genuine, unmodified game Lua.

Indexing throughout is genuine 1-based Lua (`instr[1]`, `instr[2]`, ...), matching exactly what
the game itself stores and what `Tool.GetClipboard()` would hand a real Lua caller -- there is no
Python-dict 0-based rendering step anywhere in this module (that convention only ever existed as
`dsc_codec.py`'s -- now retired -- own choice for JSON/Python display, per `dcs_wire.py`'s module
docstring).
"""

from __future__ import annotations

import lupa.lua54 as lupa

from .lua_runtime import LupaEngine, Memory


def _is_table(v) -> bool:
    return lupa.lua_type(v) == "table"


def _field(instr, key, default=None):
    v = instr[key]
    return default if v is None else v


def _resolve_next(instr, key, default):
    raw = instr[key] if key is not None else instr["next"]
    if raw is None:
        return default
    if raw is False:
        return None
    return raw - 1


def _seq_targets(instr, i: int):
    targets = []
    for key in (1, 2, 3, 4):
        v = instr[key]
        if v is False:
            continue
        t = _resolve_next(instr, key, i + 1)
        targets.append(lambda t=t: t)
    v5 = instr[5]
    if v5 is not False:
        t = _resolve_next(instr, 5, i + 1)
        targets.append(lambda t=t: t)
    return targets


class Interpreter:
    def __init__(
        self, engine: LupaEngine, prog, params: dict[int, object] | None = None
    ) -> None:
        self.engine = engine
        self.prog = prog
        self.n = 0
        while prog[self.n + 1] is not None:
            self.n += 1
        self.state = engine.new_state()
        self.comp = engine.new_comp()
        self.mem = Memory(engine, self.state)
        # reserve mem slots 1..N for declared parameters (matching the source format's own
        # convention of plain positive ints for parameter references) -- every slot needs a
        # real Value object up front (even output params with no initial value), since InstSet
        # mutates the existing slot in place via `:Init()` rather than replacing it
        parameters = prog["parameters"]
        n_params = 0
        if parameters is not None:
            while parameters[n_params + 1] is not None:
                n_params += 1
        for idx in range(1, n_params + 1):
            self.state.mem[idx] = self.engine.new_value(0)
        self.mem._next_slot = n_params + 1
        for idx, value in (params or {}).items():
            self.state.mem[idx] = self._value_for(value)
        self._build_current_asm()
        self._i = 0
        self._blocks: list[dict] = []
        self._finished = False

    def _value_for(self, py_value):
        if isinstance(py_value, tuple):
            return self.engine.new_value(0, coord=py_value)
        return self.engine.new_value(py_value)

    def _translate_arg(self, v):
        """Lua arg value -> Lua-callable arg (a mem slot int, or a negative frame-register int)."""
        if _is_table(v):
            num = _field(v, "num", 0)
            coord_t = v["coord"]
            coord = (coord_t["x"], coord_t["y"]) if coord_t is not None else None
            id_ = v["id"]
            return self.mem.literal(num=num, coord=coord, id_=id_)
        if isinstance(v, str):
            return self.mem.var(v)
        if isinstance(v, bool):
            raise ValueError(f"unexpected bool value arg: {v}")
        if isinstance(v, int):
            return v  # already a mem slot (param) or frame register
        if v is None:
            return self.mem.literal(num=0)
        raise ValueError(f"unrecognized arg: {v!r}")

    def _instr_args(self, instr):
        """All present positional (integer-keyed) values on an instruction, in order --
        includes exec-target ints/False for instructions like check_number/sequence, which is
        fine: only `jump`'s asm-scan (matching by value equality) ever reads these back, and it
        only ever matches against a `label` instruction's own single arg."""
        args = []
        k = 1
        while True:
            v = instr[k]
            if v is None and instr[k + 1] is None and k > 1:
                # allow a single gap (mirrors dcs_wire's own array/hash boundary tolerance)
                break
            if v is None and k == 1:
                break
            args.append(v)
            k += 1
        return args

    def _build_current_asm(self) -> None:
        """`jump`'s func scans GetCachedBehaviorAsm(state.revid) -- build the matching array
        (1-based, `{op, nil, arg0, arg1, ...}` per instruction) using the SAME mem-slot
        translation that instruction execution itself uses, so Get()-equality in `jump` lines up
        with the slots instructions actually read/write."""
        t = self.engine.lua.table
        rows = []
        for i in range(self.n):
            instr = self.prog[i + 1]
            raw_args = self._instr_args(instr)
            args = [self._translate_arg(a) for a in raw_args if not isinstance(a, bool)]
            op = instr["op"]
            rows.append(t("label" if op == "label" else op, None, *args))
        self.engine.lua.globals().CurrentAsm = t(*rows)

    def _enter_for_number(self, instr, i: int, blocks: list[dict]):
        """`for_number`'s block-stack driving is simulated in Python (same tier as `sequence`,
        per this module's docstring -- reusing the real `InstBeginBlock`/per-tick dispatcher is
        deferred, see CLAUDE.md), but the per-iteration advance/termination decision -- including
        the documented `Step` auto-direction quirk (behavior_format.md) and `REG_INFINITE`
        wraparound -- is genuinely delegated to the real `data.instructions.for_number.next`/
        `.last`, the same way `check_number`/`jump` delegate their own branch decisions above.
        Returns a 0-based instruction index to jump to, or None (caller should call dead_end())."""
        from_a = self._translate_arg(instr[1])
        to_a = self._translate_arg(instr[2])
        step_raw = instr[3]
        step_a = self._translate_arg(step_raw) if step_raw is not None else False
        val_raw = instr[4]
        val_a = self.mem.var(val_raw) if isinstance(val_raw, str) else val_raw
        done_0based = _resolve_next(instr, 5, i + 1)
        exec_done_raw = False if done_0based is None else done_0based + 1

        instr_def = self.engine.data.instructions["for_number"]
        reg_infinite = self.engine.lua.globals().REG_INFINITE

        def call_last():
            instr_def.last(self.comp, self.state, it, from_a, to_a, step_a, val_a, exec_done_raw)
            return None if self.state.counter is False else int(self.state.counter) - 1

        nfrom = self.engine.get_num(self.comp, self.state, from_a)
        nto = self.engine.get_num(self.comp, self.state, to_a)
        nstep = self.engine.get_num(self.comp, self.state, step_a) if step_a is not False else None
        if nfrom == reg_infinite or nstep == 0:
            it = None  # never touched -- func's own early-exit skips BeginBlock entirely
            self.state.counter = exec_done_raw
            return None if self.state.counter is False else int(self.state.counter) - 1

        # Port of `for_number.func`'s own initial-offset formula (behavior_format.md's "Step
        # auto-direction"): `.next` always advances by step before checking/writing, so the seed
        # value is one step before the first real iteration.
        initial = nfrom + (
            -nstep if nstep is not None else (-1 if (nfrom <= nto or nto == reg_infinite) else 1)
        )
        it = self.engine.lua.table(initial)
        body_start = i + 1

        def advance():
            finished = instr_def.next(
                self.comp, self.state, it, from_a, to_a, step_a, val_a, exec_done_raw
            )
            if not finished:
                return False, body_start
            return True, call_last()

        finished, target = advance()
        if finished:
            return target
        blocks.append({"kind": "loop", "advance": advance, "break_": call_last})
        return target  # == body_start

    def _dead_end(self):
        blocks = self._blocks
        while blocks:
            block = blocks[-1]
            if block["kind"] == "loop":
                finished, target = block["advance"]()
                if not finished:
                    return target
                blocks.pop()
                if target is not None:
                    return target
                continue
            if block["thunks"]:
                return block["thunks"].pop(0)()
            blocks.pop()
            if block["done"] is not None:
                return block["done"]
        return None

    def _step(self) -> str:
        """Executes exactly one real instruction (matching one `steps += 1` unit from this
        method's pre-refactor single-shot form) and returns one of `"finished"` / `"waited"` /
        `"continue"`. Resolving a dead end (an out-of-range `i`, chasing block pops via
        `_dead_end`) is free -- it never consumes a step itself, only whatever real instruction
        it eventually lands on does -- matching [[reference_sequence_unconnected_stages_free]].
        Position (`self._i`) and the block stack (`self._blocks`) persist across calls so a
        caller (`run`/`run_ticks`) can resume execution rather than restart it."""
        if self._finished:
            return "finished"
        i = self._i
        while not (0 <= i < self.n):
            # Falling off the true end of the instruction array without ever hitting an
            # explicit `next=false` still has to pop any enclosing block (a loop body whose
            # last instruction is also the program's last instruction, e.g.) -- matching
            # behavior_format.md's "next: false means... pops back to the enclosing block",
            # which applies to any dead end, not just an explicit `false`.
            nxt = self._dead_end()
            if nxt is None:
                self._finished = True
                return "finished"
            i = nxt
        instr = self.prog[i + 1]
        op = instr["op"]
        nexti = i + 1
        slept = False

        if op == "unlock":
            self.engine.call("unlock", self.comp, self.state)
        elif op == "lock":
            self.engine.call("lock", self.comp, self.state)
        elif op in ("label", "nop"):
            pass
        elif op == "wait":
            time_arg = self._translate_arg(instr[1])
            slept = bool(self.engine.call("wait", self.comp, self.state, time_arg))
        elif op == "sequence":
            self._blocks.append({"kind": "sequence", "thunks": _seq_targets(instr, i), "done": None})
            nxt = self._dead_end()
            if nxt is None:
                self._finished = True
                return "finished"
            self._i = nxt
            return "continue"
        elif op == "exit":
            self._finished = True
            return "finished"
        elif op == "check_number":
            value_arg = self._translate_arg(instr[3])
            compare_arg = self._translate_arg(instr[4])
            # Genuinely delegate the branch decision to the real func (matching `jump`,
            # below) rather than re-deriving it in Python: resolve If Larger/If Smaller to
            # raw 1-based asm targets (or `False`) ourselves, pass those straight through as
            # the func's own `if_larger`/`if_smaller` args, and let its actual logic --
            # including the real `REG_INFINITE` handling -- decide `state.counter`.
            larger_target = _resolve_next(instr, 1, i + 1)
            smaller_target = _resolve_next(instr, 2, i + 1)
            larger_raw = False if larger_target is None else larger_target + 1
            smaller_raw = False if smaller_target is None else smaller_target + 1
            self.state.counter = None
            self.engine.call(
                op,
                self.comp,
                self.state,
                larger_raw,
                smaller_raw,
                value_arg,
                compare_arg,
            )
            if self.state.counter is False:
                nxt = self._dead_end()
                if nxt is None:
                    self._finished = True
                    return "finished"
                self._i = nxt
                return "continue"
            if self.state.counter is not None:
                self._i = int(self.state.counter) - 1
                return "continue"
            # neither branch fired (Value == Compare, per the real func's own comparison) --
            # it leaves state.counter untouched for this case, so resolve the instruction's
            # own fallthrough/`next` ("Equal") ourselves, same as `jump`'s fallback below
            nexti = _resolve_next(instr, None, i + 1)
            if nexti is None:
                nxt = self._dead_end()
                if nxt is None:
                    self._finished = True
                    return "finished"
                self._i = nxt
                return "continue"
            self._i = nexti
            return "continue"
        elif op == "jump":
            label_arg = self._translate_arg(instr[1])
            self.state.lastcounter = i + 1
            self.state.counter = None
            self.engine.call(op, self.comp, self.state, label_arg)
            if self.state.counter is not None:
                self._i = int(self.state.counter) - 1
                return "continue"
            nexti = _resolve_next(instr, None, i + 1)
        elif op == "for_number":
            target = self._enter_for_number(instr, i, self._blocks)
            if target is None:
                nxt = self._dead_end()
                if nxt is None:
                    self._finished = True
                    return "finished"
                self._i = nxt
                return "continue"
            self._i = target
            return "continue"
        elif op == "last":
            if not self._blocks or self._blocks[-1]["kind"] != "loop":
                raise RuntimeError("last (Break) requires an enclosing for_number loop")
            block = self._blocks.pop()
            target = block["break_"]()
            if target is None:
                nxt = self._dead_end()
                if nxt is None:
                    self._finished = True
                    return "finished"
                self._i = nxt
                return "continue"
            self._i = target
            return "continue"
        elif op in ("add", "sub", "mul", "div"):
            a = self._translate_arg(instr[1])
            b = self._translate_arg(instr[2])
            res_slot = (
                self.mem.var(instr[3]) if isinstance(instr[3], str) else instr[3]
            )
            self.engine.call(op, self.comp, self.state, a, b, res_slot)
        elif op == "set_reg":
            a = self._translate_arg(instr[1])
            target_slot = (
                self.mem.var(instr[2]) if isinstance(instr[2], str) else instr[2]
            )
            self.engine.call("set_reg", self.comp, self.state, a, target_slot)
        elif op == "memory_insert":
            idx_arg = self._translate_arg(instr[1])
            val_arg = self._translate_arg(instr[2])
            self.engine.call(op, self.comp, self.state, idx_arg, val_arg)
        elif op == "memory_remove":
            idx_arg = self._translate_arg(instr[1])
            out_slot = (
                self.mem.var(instr[2]) if isinstance(instr[2], str) else instr[2]
            )
            self.engine.call(op, self.comp, self.state, idx_arg, out_slot)
        elif op == "combine_coordinate":
            a = self._translate_arg(instr[1])
            b = self._translate_arg(instr[2])
            res_slot = (
                self.mem.var(instr[3]) if isinstance(instr[3], str) else instr[3]
            )
            self.engine.call(op, self.comp, self.state, a, b, res_slot)
        elif op == "separate_coordinate":
            a = self._translate_arg(instr[1])
            x_slot = (
                self.mem.var(instr[2]) if isinstance(instr[2], str) else instr[2]
            )
            y_slot = (
                self.mem.var(instr[3]) if isinstance(instr[3], str) else instr[3]
            )
            self.engine.call(op, self.comp, self.state, a, x_slot, y_slot)
        elif op == "debug_print":
            # No real log to write to here -- just surface it on stdout so a script driving
            # the Interpreter directly (as opposed to a pytest assertion reading `mem` back)
            # can observe it, matching what the in-game log would show.
            val = self.engine.get_value(self.comp, self.state, self._translate_arg(instr[1]))
            print(f"[debug_print] num={val.num} coord={val.coord} id={val.id}")
        else:
            raise RuntimeError(f"unhandled op {op}")

        if instr["next"] is not None:
            nexti2 = _resolve_next(instr, None, None)
            if nexti2 is None:
                nxt = self._dead_end()
                if nxt is None:
                    self._finished = True
                    return "finished"
                self._i = nxt
                return "continue"
            nexti = nexti2
        self._i = nexti
        return "waited" if slept else "continue"

    def run(self, max_steps: int = 20000) -> None:
        """Runs to completion (or `exit`), ignoring tick/lock-state timing entirely -- a `wait`
        along the way doesn't pause this, it's just one more step. For tick-accurate stepping
        (respecting `state.limit`/lock/unlock and honoring `wait` as a real per-tick pause), use
        `run_ticks` instead."""
        steps = 0
        while True:
            result = self._step()
            if result == "finished":
                return
            steps += 1
            if steps > max_steps:
                raise RuntimeError("runaway")

    def run_ticks(self, n: int, max_steps: int = 100000) -> None:
        """Simulates `n` real game ticks, honoring the actual lock/unlock/wait model (see
        data.instructions.unlock/.lock/.wait's own `explain` text, confirmed 2026-07-10): by
        default (no `unlock()` reached yet) `state.limit == 1`, so each tick executes exactly one
        instruction -- an implicit `wait(1)` after every step. `unlock()` raises the per-tick
        budget to 10000 (checked fresh after every instruction, so it can take effect within the
        same tick it runs in); `lock()` resets it to 1. An explicit `wait(t)` stops the current
        tick immediately (via `comp.sleep`, set by the real `wait` func's `comp:SetStateSleep`),
        counting down `t` ticks (executing nothing) before instructions resume."""
        steps = 0
        for _ in range(n):
            if self._finished:
                return
            sleep = self.comp["sleep"] or 0
            if sleep > 0:
                self.comp["sleep"] = sleep - 1
                continue
            executed = 0
            while True:
                limit = self.state["limit"] or 1
                if executed >= limit:
                    break
                result = self._step()
                executed += 1
                steps += 1
                if steps > max_steps:
                    raise RuntimeError("runaway")
                if result in ("finished", "waited"):
                    break

    def read_param(self, idx: int):
        return self.engine.get_value(self.comp, self.state, idx)
