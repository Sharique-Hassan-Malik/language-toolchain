"""
Code generator: AST → flat bytecode for the Zap stack VM.

Jump offsets are signed integers relative to the instruction after the jump.
  JMP  n  →  ip += n          (unconditional)
  JF   n  →  if not pop(): ip += n
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Union
from .ast_nodes import *


class Op(Enum):
    PUSH_INT  = auto()
    PUSH_BOOL = auto()
    LOAD      = auto()
    STORE     = auto()
    ADD       = auto()
    SUB       = auto()
    MUL       = auto()
    DIV       = auto()
    EQ        = auto()
    NEQ       = auto()
    LT        = auto()
    GT        = auto()
    LEQ       = auto()
    GEQ       = auto()
    AND       = auto()
    OR        = auto()
    NOT       = auto()
    NEG       = auto()
    JMP       = auto()
    JMP_FALSE = auto()
    CALL      = auto()
    RET       = auto()
    PRINT     = auto()
    POP       = auto()
    HALT      = auto()


_BIN_OPS: dict[str, Op] = {
    "+": Op.ADD, "-": Op.SUB, "*": Op.MUL, "/": Op.DIV,
    "==": Op.EQ, "!=": Op.NEQ,
    "<":  Op.LT, ">":  Op.GT, "<=": Op.LEQ, ">=": Op.GEQ,
    "&&": Op.AND, "||": Op.OR,
}


@dataclass
class Instr:
    op:   Op
    arg:  Union[int, bool, str, None] = None
    arg2: Union[int, None] = None   # CALL only: arg=fn_name, arg2=nargs

    def __repr__(self) -> str:
        if self.arg2 is not None:
            return f"{self.op.name:<12} {self.arg} {self.arg2}"
        if self.arg is not None:
            return f"{self.op.name:<12} {self.arg!r}"
        return self.op.name


@dataclass
class FnChunk:
    params: list[str]
    code:   list[Instr] = field(default_factory=list)


@dataclass
class CompiledProgram:
    functions: dict[str, FnChunk] = field(default_factory=dict)
    entry:     str                = "__main__"

    def disassemble(self) -> str:
        lines: list[str] = []
        for name, chunk in self.functions.items():
            lines.append(f"fn {name}({', '.join(chunk.params)}):")
            for i, ins in enumerate(chunk.code):
                lines.append(f"  {i:4d}  {ins}")
        return "\n".join(lines)


class CodeGen:
    def __init__(self) -> None:
        self._prog  = CompiledProgram()
        self._chunk: FnChunk | None = None

    def compile(self, program: Program) -> CompiledProgram:
        # Collect all function decls first (forward references).
        for decl in program.decls:
            if isinstance(decl, FnDecl):
                self._start_fn(decl.name, [n for n, _ in decl.params])

        for decl in program.decls:
            if isinstance(decl, FnDecl):
                self._compile_fn(decl)
            else:
                self._ensure_main()
                self._compile_stmt(decl)

        self._ensure_main()
        main = self._prog.functions["__main__"]
        if not main.code or main.code[-1].op != Op.HALT:
            main.code.append(Instr(Op.HALT))

        # Determine entry: prefer user-defined 'main', else '__main__'
        if "main" in self._prog.functions:
            self._prog.entry = "main"
        return self._prog

    # ── internals ─────────────────────────────────────────────────────────────

    def _ensure_main(self) -> None:
        if "__main__" not in self._prog.functions:
            self._prog.functions["__main__"] = FnChunk(params=[])
        self._chunk = self._prog.functions["__main__"]

    def _start_fn(self, name: str, params: list[str]) -> None:
        self._prog.functions[name] = FnChunk(params=params)

    def _compile_fn(self, fn: FnDecl) -> None:
        prev = self._chunk
        self._chunk = self._prog.functions[fn.name]
        for stmt in fn.body.stmts:
            self._compile_stmt(stmt)
        code = self._chunk.code
        if not code or code[-1].op != Op.RET:
            code.append(Instr(Op.PUSH_BOOL, False))
            code.append(Instr(Op.RET))
        self._chunk = prev

    def _emit(self, op: Op, arg=None, arg2=None) -> None:
        assert self._chunk is not None
        self._chunk.code.append(Instr(op, arg, arg2))

    def _here(self) -> int:
        return len(self._chunk.code)

    def _patch(self, idx: int, target: int) -> None:
        # offset is from the instruction after the jump to target
        self._chunk.code[idx].arg = target - idx - 1

    # ── statements ────────────────────────────────────────────────────────────

    def _compile_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, LetStmt):
            self._compile_expr(stmt.value)
            self._emit(Op.STORE, stmt.name)

        elif isinstance(stmt, ReturnStmt):
            if stmt.value is not None:
                self._compile_expr(stmt.value)
            else:
                self._emit(Op.PUSH_BOOL, False)
            self._emit(Op.RET)

        elif isinstance(stmt, IfStmt):
            self._compile_expr(stmt.cond)
            jf = self._here()
            self._emit(Op.JMP_FALSE, 0)           # placeholder
            for s in stmt.then_block.stmts:
                self._compile_stmt(s)
            if stmt.else_block:
                jmp = self._here()
                self._emit(Op.JMP, 0)             # skip else block
                self._patch(jf, self._here())
                for s in stmt.else_block.stmts:
                    self._compile_stmt(s)
                self._patch(jmp, self._here())
            else:
                self._patch(jf, self._here())

        elif isinstance(stmt, WhileStmt):
            loop = self._here()
            self._compile_expr(stmt.cond)
            jf = self._here()
            self._emit(Op.JMP_FALSE, 0)
            for s in stmt.body.stmts:
                self._compile_stmt(s)
            back = self._here()
            self._emit(Op.JMP, loop - back - 1)   # back-edge (negative offset)
            self._patch(jf, self._here())

        elif isinstance(stmt, PrintStmt):
            self._compile_expr(stmt.value)
            self._emit(Op.PRINT)

        elif isinstance(stmt, ExprStmt):
            self._compile_expr(stmt.expr)
            if not isinstance(stmt.expr, AssignExpr):
                self._emit(Op.POP)

    # ── expressions ───────────────────────────────────────────────────────────

    def _compile_expr(self, expr: Expr) -> None:
        if isinstance(expr, IntLit):
            self._emit(Op.PUSH_INT, expr.value)
        elif isinstance(expr, BoolLit):
            self._emit(Op.PUSH_BOOL, expr.value)
        elif isinstance(expr, IdentExpr):
            self._emit(Op.LOAD, expr.name)
        elif isinstance(expr, AssignExpr):
            self._compile_expr(expr.value)
            self._emit(Op.STORE, expr.name)
        elif isinstance(expr, BinOp):
            self._compile_expr(expr.left)
            self._compile_expr(expr.right)
            self._emit(_BIN_OPS[expr.op])
        elif isinstance(expr, UnaryOp):
            self._compile_expr(expr.operand)
            self._emit(Op.NOT if expr.op == "!" else Op.NEG)
        elif isinstance(expr, CallExpr):
            for arg in expr.args:
                self._compile_expr(arg)
            self._emit(Op.CALL, expr.name, len(expr.args))


def compile_program(program: Program) -> CompiledProgram:
    return CodeGen().compile(program)
