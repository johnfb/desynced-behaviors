"""Minimal proof-of-concept compiler: a small subset of Python syntax (parsed via the stdlib
`ast` module) -> a genuine Lua table in the source-level shape `behavior_format.md` documents
(1-based instruction list, `op` string key plus 1-based positional args per instruction -- the
same shape `dsc_wire.decode_dsc()` hands back, not a Python dict standing in for one).

Supported so far (deliberately small -- this is a first proof, not full coverage):
  - `x = <int literal>` / `x = y`                       -> set_reg
  - `x = a + b` / `a - b` / `a * b` / `a // b`           -> add/sub/mul/div
  - `if a > b: ... else: ...` / `if a < b: ... else: ...` -> check_number, using the same
    "point the untaken branch's exec pin at a skip target" shape a human would hand-author,
    not the `check_number`-equal-case idiom (there's no `else` clause to spare here).

Not yet supported: while/for loops, function calls, sub-behavior parameters, jump/label,
sequence, coordinates -- see the project's task list for what's next.
"""

from __future__ import annotations

import ast

_BINOP_TO_INSTR = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.FloorDiv: "div"}


class CompileError(Exception):
    pass


class AstCompiler:
    def __init__(self, lua) -> None:
        self._lua = lua
        self._instrs: list = []  # Lua tables, in order (Python list is just our own bookkeeping)

    def _new_instr(self, op: str) -> "lupa._LuaTable":
        t = self._lua.table()
        t["op"] = op
        return t

    def _emit(self, t) -> int:
        idx = len(self._instrs)
        self._instrs.append(t)
        return idx

    def _operand(self, node: ast.expr):
        if isinstance(node, ast.Name):
            return node.id  # a plain Lua string once assigned into a table
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            lit = self._lua.table()
            lit["num"] = node.value
            return lit
        raise CompileError(f"unsupported operand: {ast.dump(node)}")

    def compile_source(self, source: str, name: str = "compiled"):
        tree = ast.parse(source)
        self._compile_body(tree.body)
        prog = self._lua.table()
        for i, instr in enumerate(self._instrs, start=1):
            prog[i] = instr
        prog["name"] = name
        return prog

    def _compile_body(self, stmts: list[ast.stmt]) -> None:
        for stmt in stmts:
            self._compile_stmt(stmt)

    def _compile_stmt(self, stmt: ast.stmt) -> None:
        if isinstance(stmt, ast.Assign):
            self._compile_assign(stmt)
        elif isinstance(stmt, ast.If):
            self._compile_if(stmt)
        else:
            raise CompileError(f"unsupported statement: {ast.dump(stmt)}")

    def _compile_assign(self, stmt: ast.Assign) -> None:
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            raise CompileError("only single Name assignment targets are supported")
        target = stmt.targets[0].id
        value = stmt.value
        if isinstance(value, ast.BinOp) and type(value.op) in _BINOP_TO_INSTR:
            op = _BINOP_TO_INSTR[type(value.op)]
            t = self._new_instr(op)
            t[1] = self._operand(value.left)
            t[2] = self._operand(value.right)
            t[3] = target
            self._emit(t)
        elif isinstance(value, (ast.Name, ast.Constant)):
            t = self._new_instr("set_reg")
            t[1] = self._operand(value)
            t[2] = target
            self._emit(t)
        else:
            raise CompileError(f"unsupported assignment value: {ast.dump(value)}")

    def _compile_if(self, stmt: ast.If) -> None:
        test = stmt.test
        if not (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and len(test.comparators) == 1
        ):
            raise CompileError(
                "only a single comparison (a > b / a < b) is supported in `if`"
            )
        op = test.ops[0]
        if isinstance(op, ast.Gt):
            true_key = 1  # If Larger
        elif isinstance(op, ast.Lt):
            true_key = 2  # If Smaller
        else:
            raise CompileError("only > and < comparisons are supported in `if`")

        # `check_number` has no "If Equal" slot (see behavior_format.md's "check_number's
        # 'equal' case") -- equality is carried by the instruction's own fallthrough/`next`,
        # same as an omitted If Larger/If Smaller. So the FALSE branch of the Python `if`
        # (`stmt.orelse`, which for both `a > b` and `a < b` is exactly "not true, including
        # equal") must be the one compiled as the physically-next fallthrough -- not whichever
        # comparison direction happens to be tested. Only the TRUE branch needs an explicit
        # (forward-patched) jump target.
        check_t = self._new_instr("check_number")
        check_t[3] = self._operand(test.left)
        check_t[4] = self._operand(test.comparators[0])
        check_idx = self._emit(check_t)

        self._compile_body(stmt.orelse)
        skip_t = self._new_instr("nop")
        skip_idx = self._emit(skip_t)  # `next` patched below, once "after" is known
        true_start = len(self._instrs)
        check_t[true_key] = true_start + 1  # raw 1-based Lua position
        self._compile_body(stmt.body)
        after = len(self._instrs)
        skip_t["next"] = after + 1
