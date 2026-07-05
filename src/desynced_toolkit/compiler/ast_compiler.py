"""Compiler: a Python-syntax subset (parsed via the stdlib `ast` module) -> a genuine Lua table
in the source-level shape `behavior_format.md` documents (1-based instruction list, `op` string
key plus 1-based positional args per instruction -- the same shape `dsc_wire.decode_dsc()` hands
back, not a Python dict standing in for one).

Supported (grew out of compiling `hex_expansion_math.md`'s revised `HexIndexOf` -- see
`tests/test_hexindexof_compiled.py`):
  - `x = <int literal>` / `x = y`                          -> set_reg
  - arbitrarily nested `+ - * // ` and unary `-`            -> add/sub/mul/div, with sub-expressions
    hoisted into fresh temporary locals (`__t1`, `__t2`, ...) as needed
  - `if`/`elif`/`else` on `>` `<` `==` `!=`, including `a and b` (both must hold) conditions
  - `if <cond>: continue` (no `else`) inside a loop, compiling to an explicit `false`-wired exec
    branch rather than real instructions -- the idiom this project's hand-authored behaviors
    already use for "not a match, try the next one" (see hex_expansion_math.md's HexIndexOf)
  - `for x in range(a, b):` / `break`                       -> for_number / last (Break)
  - `jump(value)` / `label(value)` as bare statements       -> jump / label (computed dispatch)
  - `a, b = separate_coordinate(x)`                         -> separate_coordinate
  - `x = combine_coordinate(a, b)`                          -> combine_coordinate
  - `abs(x)`, `max(a, b, ...)`                              -> macro-expanded into the
    check_number-guarded idioms `hex_expansion_math.md` documents (no native instruction for
    either), by synthesizing an equivalent `if`/assignment AST and recursing -- not new codegen

Not yet supported: function defs/sub-behavior parameters, `sequence`, coordinate/id/entity
literals, `while`, general boolean expressions beyond a top-level `and` chain (no `or`, no
nesting) -- see the project's task list for what's next.
"""

from __future__ import annotations

import ast

_BINOP_TO_INSTR = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.FloorDiv: "div"}

# Per comparison op: which check_number exec keys (1=If Larger, 2=If Smaller) mean "condition is
# false", and whether the false case also needs the instruction's own top-level `next` set (the
# "equal" outcome has no numbered key of its own -- see behavior_format.md's check_number notes).
# Whichever pin(s) are NOT listed as "false" are left unset, defaulting to fallthrough -- which is
# exactly the "true"/pass case, since every un-wired pin defaults to the same next-instruction
# position regardless of role.
#   Gt  (a>b):  false = smaller-or-equal -> key 2 (If Smaller) + top `next` (equal)
#   Lt  (a<b):  false = larger-or-equal  -> key 1 (If Larger)  + top `next` (equal)
#   GtE (a>=b): false = smaller only     -> key 2 (If Smaller); equal is part of "true"
#   LtE (a<=b): false = larger only      -> key 1 (If Larger);  equal is part of "true"
#   NotEq:      false = equal            -> top `next` only
#   Eq:         false = not equal        -> keys 1 and 2 (both explicit branches)
_CMP_FAIL = {
    ast.Gt: ([2], True),
    ast.Lt: ([1], True),
    ast.GtE: ([2], False),
    ast.LtE: ([1], False),
    ast.NotEq: ([], True),
    ast.Eq: ([1, 2], False),
}

_TUPLE_CALL_INSTRS = {
    "separate_coordinate": {"in_count": 1, "out_count": 2, "op": "separate_coordinate"},
}
_SINGLE_CALL_INSTRS = {
    "combine_coordinate": {"in_count": 2, "op": "combine_coordinate"},
}


class CompileError(Exception):
    pass


class AstCompiler:
    def __init__(self, lua) -> None:
        self._lua = lua
        self._instrs: list = []  # Lua tables, in order (Python list is just our own bookkeeping)
        self._tmp_counter = 0
        self._loop_depth = 0

    # -- bookkeeping -----------------------------------------------------------------------

    def _new_instr(self, op: str) -> "lupa._LuaTable":
        t = self._lua.table()
        t["op"] = op
        return t

    def _emit(self, t) -> int:
        idx = len(self._instrs)
        self._instrs.append(t)
        return idx

    def _fresh_temp(self) -> str:
        self._tmp_counter += 1
        return f"__t{self._tmp_counter}"

    def _literal(self, value: int):
        lit = self._lua.table()
        lit["num"] = value
        return lit

    def compile_source(self, source: str, name: str = "compiled"):
        tree = ast.parse(source)
        self._compile_body(tree.body)
        prog = self._lua.table()
        for i, instr in enumerate(self._instrs, start=1):
            prog[i] = instr
        prog["name"] = name
        return prog

    # -- statements --------------------------------------------------------------------------

    def _compile_body(self, stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            self._compile_stmt(stmt)

    def _compile_stmt(self, stmt: ast.stmt) -> None:
        if isinstance(stmt, ast.Assign):
            self._compile_assign(stmt)
        elif isinstance(stmt, ast.If):
            self._compile_if(stmt)
        elif isinstance(stmt, ast.For):
            self._compile_for(stmt)
        elif isinstance(stmt, ast.Break):
            self._compile_break(stmt)
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            self._compile_call_stmt(stmt.value)
        else:
            raise CompileError(f"unsupported statement: {ast.dump(stmt)}")

    def _compile_assign(self, stmt: ast.Assign) -> None:
        if len(stmt.targets) != 1:
            raise CompileError("only single-target assignment is supported")
        target_node = stmt.targets[0]
        if isinstance(target_node, ast.Tuple):
            self._compile_tuple_assign(target_node, stmt.value)
            return
        if not isinstance(target_node, ast.Name):
            raise CompileError("only Name (or a Name tuple) assignment targets are supported")
        self._compile_expr_into(target_node.id, stmt.value)

    def _compile_tuple_assign(self, target_node: ast.Tuple, value: ast.expr) -> None:
        if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Name)):
            raise CompileError("tuple assignment requires a call to a known multi-output op")
        spec = _TUPLE_CALL_INSTRS.get(value.func.id)
        if spec is None:
            raise CompileError(f"unknown multi-output call: {value.func.id}")
        targets = []
        for elt in target_node.elts:
            if not isinstance(elt, ast.Name):
                raise CompileError("tuple assignment targets must be plain names")
            targets.append(elt.id)
        if len(targets) != spec["out_count"]:
            raise CompileError(f"{value.func.id} produces {spec['out_count']} outputs")
        if len(value.args) != spec["in_count"]:
            raise CompileError(f"{value.func.id} takes {spec['in_count']} input(s)")
        in_operands = [self._compile_operand(a) for a in value.args]
        t = self._new_instr(spec["op"])
        idx = 1
        for operand in in_operands:
            t[idx] = operand
            idx += 1
        for name in targets:
            t[idx] = name
            idx += 1
        self._emit(t)

    def _compile_break(self, stmt: ast.Break) -> None:
        if self._loop_depth == 0:
            raise CompileError("break outside a loop")
        self._emit(self._new_instr("last"))

    def _compile_call_stmt(self, call: ast.Call) -> None:
        if not isinstance(call.func, ast.Name):
            raise CompileError(f"unsupported statement-call: {ast.dump(call)}")
        name = call.func.id
        if name in ("jump", "label") and len(call.args) == 1:
            t = self._new_instr(name)
            t[1] = self._compile_operand(call.args[0])
            self._emit(t)
            return
        if name in ("unlock", "lock", "exit") and len(call.args) == 0:
            self._emit(self._new_instr(name))
            return
        if name == "debug_print" and len(call.args) == 1:
            t = self._new_instr(name)
            t[1] = self._compile_operand(call.args[0])
            self._emit(t)
            return
        raise CompileError(f"unsupported statement-call: {name}")

    def _compile_for(self, stmt: ast.For) -> None:
        it = stmt.iter
        if not (
            isinstance(it, ast.Call)
            and isinstance(it.func, ast.Name)
            and it.func.id == "range"
            and len(it.args) == 2
        ):
            raise CompileError("only `for x in range(a, b):` loops are supported")
        if not isinstance(stmt.target, ast.Name):
            raise CompileError("loop target must be a plain name")
        if stmt.orelse:
            raise CompileError("for/else is not supported")

        from_operand = self._compile_operand(it.args[0])
        to_node = it.args[1]
        # for_number's `To` is inclusive; range()'s upper bound is exclusive -- fold the -1 at
        # compile time for a literal bound, otherwise emit a real Subtract.
        if isinstance(to_node, ast.Constant) and isinstance(to_node.value, int):
            to_operand = self._literal(to_node.value - 1)
        else:
            to_operand = self._compile_operand(
                ast.BinOp(left=to_node, op=ast.Sub(), right=ast.Constant(1))
            )

        loop_t = self._new_instr("for_number")
        loop_t[1] = from_operand
        loop_t[2] = to_operand
        loop_t[4] = stmt.target.id  # Value (out)
        loop_idx = self._emit(loop_t)

        self._loop_depth += 1
        self._compile_body(stmt.body)
        self._loop_depth -= 1

        after = len(self._instrs)
        loop_t[5] = after + 1  # Done (exec)
        # (loop_idx currently unused past emission -- kept for symmetry/debuggability)
        del loop_idx

    # -- if/elif/else, including `if cond: continue` -----------------------------------------

    def _is_bare_continue(self, block: list[ast.stmt]) -> bool:
        return len(block) == 1 and isinstance(block[0], ast.Continue)

    def _flatten_and(self, test: ast.expr) -> list[ast.Compare]:
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
            conditions = []
            for value in test.values:
                conditions.extend(self._flatten_and(value))
            return conditions
        if isinstance(test, ast.Compare) and len(test.ops) == 1 and len(test.comparators) == 1:
            return [test]
        raise CompileError(f"unsupported condition: {ast.dump(test)}")

    def _compile_if(self, stmt: ast.If) -> None:
        conditions = self._flatten_and(stmt.test)

        if self._is_bare_continue(stmt.body) and not stmt.orelse:
            if self._loop_depth == 0:
                raise CompileError("`continue` outside a loop")
            # `continue` fires when the condition is TRUE -- the opposite of the general case
            # below, where a failing condition is what jumps away. So here it's the PASS
            # outcome (whichever key(s)/top-`next` are NOT the "false" ones) that gets wired
            # to `false`, leaving the "false" outcome to fall through normally (there's no
            # `orelse` to reach -- that's exactly what makes this the continue-shortcut).
            for cond in conditions:
                self._emit_continue_check(cond)
            return

        # General case: every condition must pass (fall through) to reach `body`; any single
        # failure jumps to `orelse` (patched once all conditions and `body` are compiled, since
        # every condition shares the same fail target).
        pending: list[tuple] = []  # (check_t, fail_keys, fail_uses_next)
        for cond in conditions:
            pending.append(self._emit_condition_check(cond))

        self._compile_body(stmt.body)
        skip_t = self._new_instr("nop")
        self._emit(skip_t)
        orelse_start = len(self._instrs)
        for check_t, fail_keys, fail_uses_next in pending:
            for key in fail_keys:
                check_t[key] = orelse_start + 1
            if fail_uses_next:
                check_t["next"] = orelse_start + 1
        self._compile_body(stmt.orelse)
        after = len(self._instrs)
        skip_t["next"] = after + 1

    def _cmp_spec(self, op: ast.cmpop):
        spec = _CMP_FAIL.get(type(op))
        if spec is None:
            raise CompileError(f"unsupported comparison: {ast.dump(op)}")
        return spec

    def _emit_condition_check(self, cond: ast.Compare):
        """General case: emits the check, leaving both the false-branch keys and the top-level
        `next` unset for the caller to patch once `orelse`'s position is known."""
        fail_keys, fail_uses_next = self._cmp_spec(cond.ops[0])
        check_t = self._new_instr("check_number")
        check_t[3] = self._compile_operand(cond.left)
        check_t[4] = self._compile_operand(cond.comparators[0])
        self._emit(check_t)
        return check_t, fail_keys, fail_uses_next

    def _emit_continue_check(self, cond: ast.Compare) -> None:
        """`if cond: continue` shortcut: the PASS outcome (condition true) is what should
        dead-end here -- the complement of the general case's fail-keys/fail-uses-next, since
        every outcome (If Larger, If Smaller, top-level `next` for Equal) is either pass or
        fail and there's no third option."""
        fail_keys, fail_uses_next = self._cmp_spec(cond.ops[0])
        pass_keys = [k for k in (1, 2) if k not in fail_keys]
        pass_uses_next = not fail_uses_next
        check_t = self._new_instr("check_number")
        check_t[3] = self._compile_operand(cond.left)
        check_t[4] = self._compile_operand(cond.comparators[0])
        for key in pass_keys:
            check_t[key] = False
        if pass_uses_next:
            check_t["next"] = False
        self._emit(check_t)

    # -- expressions ---------------------------------------------------------------------------

    def _compile_operand(self, node: ast.expr):
        """Compile `node` to an operand usable directly as an instruction arg -- a Name string or
        a literal table for a plain Name/Constant, otherwise a fresh temp holding the result."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return self._literal(node.value)
        temp = self._fresh_temp()
        self._compile_expr_into(temp, node)
        return temp

    def _compile_expr_into(self, target: str, node: ast.expr) -> None:
        """Compile `node`, writing its result into local variable `target`."""
        if isinstance(node, ast.Name) or (
            isinstance(node, ast.Constant) and isinstance(node.value, int)
        ):
            t = self._new_instr("set_reg")
            t[1] = self._compile_operand(node)
            t[2] = target
            self._emit(t)
        elif isinstance(node, ast.BinOp) and type(node.op) in _BINOP_TO_INSTR:
            left = self._compile_operand(node.left)
            right = self._compile_operand(node.right)
            t = self._new_instr(_BINOP_TO_INSTR[type(node.op)])
            t[1] = left
            t[2] = right
            t[3] = target
            self._emit(t)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            operand = self._compile_operand(node.operand)
            t = self._new_instr("sub")
            t[1] = self._literal(0)
            t[2] = operand
            t[3] = target
            self._emit(t)
        elif isinstance(node, ast.Call):
            self._compile_call_into(target, node)
        else:
            raise CompileError(f"unsupported expression: {ast.dump(node)}")

    def _compile_call_into(self, target: str, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Name):
            raise CompileError(f"unsupported call: {ast.dump(node)}")
        name = node.func.id

        if name == "abs" and len(node.args) == 1:
            x = node.args[0]
            synth = ast.If(
                test=ast.Compare(left=x, ops=[ast.Lt()], comparators=[ast.Constant(0)]),
                body=[
                    ast.Assign(
                        targets=[ast.Name(id=target)],
                        value=ast.BinOp(left=ast.Constant(0), op=ast.Sub(), right=x),
                    )
                ],
                orelse=[ast.Assign(targets=[ast.Name(id=target)], value=x)],
            )
            self._compile_if(synth)
            return

        if name == "max" and len(node.args) >= 2:
            args = node.args
            self._compile_expr_into(target, args[0])
            for arg in args[1:]:
                synth = ast.If(
                    test=ast.Compare(
                        left=arg, ops=[ast.Gt()], comparators=[ast.Name(id=target)]
                    ),
                    body=[ast.Assign(targets=[ast.Name(id=target)], value=arg)],
                    orelse=[],
                )
                self._compile_if(synth)
            return

        spec = _SINGLE_CALL_INSTRS.get(name)
        if spec is not None:
            if len(node.args) != spec["in_count"]:
                raise CompileError(f"{name} takes {spec['in_count']} input(s)")
            operands = [self._compile_operand(a) for a in node.args]
            t = self._new_instr(spec["op"])
            for idx, operand in enumerate(operands, start=1):
                t[idx] = operand
            t[spec["in_count"] + 1] = target
            self._emit(t)
            return

        raise CompileError(f"unsupported call: {name}")
