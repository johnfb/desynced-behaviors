"""Minimal proof-of-concept compiler: a small subset of Python syntax (parsed via the stdlib
`ast` module) -> the instruction-dict format `dsc_codec.py`/behavior_format.md document.

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
    def __init__(self) -> None:
        self._instrs: list[dict] = []

    def _emit(self, rec: dict) -> int:
        idx = len(self._instrs)
        self._instrs.append(rec)
        return idx

    @staticmethod
    def _operand(node: ast.expr):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return {"num": node.value}
        raise CompileError(f"unsupported operand: {ast.dump(node)}")

    def compile_source(self, source: str, name: str = "compiled") -> dict:
        tree = ast.parse(source)
        self._compile_body(tree.body)
        out = {str(i): rec for i, rec in enumerate(self._instrs)}
        out["name"] = name
        return out

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
            self._emit(
                {
                    "0": self._operand(value.left),
                    "1": self._operand(value.right),
                    "2": target,
                    "op": op,
                }
            )
        elif isinstance(value, (ast.Name, ast.Constant)):
            self._emit({"0": self._operand(value), "1": target, "op": "set_reg"})
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
            larger_body, smaller_body = stmt.body, stmt.orelse
        elif isinstance(op, ast.Lt):
            larger_body, smaller_body = stmt.orelse, stmt.body
        else:
            raise CompileError("only > and < comparisons are supported in `if`")

        check_idx = self._emit(
            {
                "2": self._operand(test.left),
                "3": self._operand(test.comparators[0]),
                "op": "check_number",
            }
        )
        # "If Larger" branch falls through naturally (physically next instruction); compile it
        # first, then a `nop` to skip over the "If Smaller" branch once it's done.
        self._compile_body(larger_body)
        skip_idx = self._emit(
            {"op": "nop"}
        )  # `next` patched below, once we know where "after" is
        smaller_start = len(self._instrs)
        self._instrs[check_idx]["1"] = (
            smaller_start + 1
        )  # If Smaller -> here (raw 1-based)
        self._compile_body(smaller_body)
        after = len(self._instrs)
        self._instrs[skip_idx]["next"] = after + 1
