"""Type checker for Zap. Walks the AST and enforces static types."""

from __future__ import annotations
from .ast_nodes import *


class TypeErrorZap(Exception):
    pass


class Scope:
    def __init__(self, parent: Scope | None = None) -> None:
        self._vars: dict[str, str] = {}
        self.parent = parent

    def define(self, name: str, ty: str) -> None:
        self._vars[name] = ty

    def lookup(self, name: str) -> str | None:
        if name in self._vars:
            return self._vars[name]
        return self.parent.lookup(name) if self.parent else None


class TypeChecker:
    def __init__(self) -> None:
        # fn_name -> ([param_types], return_type)
        self._fns: dict[str, tuple[list[str], str]] = {}
        self._scope = Scope()
        self._return_type = "void"

    def check(self, program: Program) -> None:
        # Pass 1: collect all function signatures so calls can be forward-referenced.
        for decl in program.decls:
            if isinstance(decl, FnDecl):
                self._fns[decl.name] = (
                    [ty for _, ty in decl.params],
                    decl.return_type,
                )
        # Pass 2: check bodies.
        for decl in program.decls:
            if isinstance(decl, FnDecl):
                self._check_fn(decl)
            else:
                self._check_stmt(decl)

    # ── functions ─────────────────────────────────────────────────────────────

    def _check_fn(self, fn: FnDecl) -> None:
        saved_ret = self._return_type
        self._return_type = fn.return_type
        self._scope = Scope(self._scope)
        for name, ty in fn.params:
            self._scope.define(name, ty)
        for stmt in fn.body.stmts:
            self._check_stmt(stmt)
        self._scope = self._scope.parent
        self._return_type = saved_ret

    def _check_block(self, block: Block) -> None:
        self._scope = Scope(self._scope)
        for stmt in block.stmts:
            self._check_stmt(stmt)
        self._scope = self._scope.parent

    # ── statements ────────────────────────────────────────────────────────────

    def _check_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, LetStmt):
            got = self._check_expr(stmt.value)
            if got != stmt.ty:
                raise TypeErrorZap(
                    f"Line {stmt.line}: let {stmt.name}: declared {stmt.ty}, got {got}"
                )
            self._scope.define(stmt.name, stmt.ty)

        elif isinstance(stmt, ReturnStmt):
            ty = "void" if stmt.value is None else self._check_expr(stmt.value)
            if ty != self._return_type:
                raise TypeErrorZap(
                    f"Line {stmt.line}: return {ty} in {self._return_type!r} function"
                )

        elif isinstance(stmt, IfStmt):
            ct = self._check_expr(stmt.cond)
            if ct != "bool":
                raise TypeErrorZap(f"Line {stmt.line}: if condition must be bool, got {ct}")
            self._check_block(stmt.then_block)
            if stmt.else_block:
                self._check_block(stmt.else_block)

        elif isinstance(stmt, WhileStmt):
            ct = self._check_expr(stmt.cond)
            if ct != "bool":
                raise TypeErrorZap(f"Line {stmt.line}: while condition must be bool, got {ct}")
            self._check_block(stmt.body)

        elif isinstance(stmt, PrintStmt):
            self._check_expr(stmt.value)

        elif isinstance(stmt, ExprStmt):
            self._check_expr(stmt.expr)

    # ── expressions ───────────────────────────────────────────────────────────

    def _check_expr(self, expr: Expr) -> str:
        if isinstance(expr, IntLit):
            return "int"
        if isinstance(expr, BoolLit):
            return "bool"
        if isinstance(expr, IdentExpr):
            ty = self._scope.lookup(expr.name)
            if ty is None:
                raise TypeErrorZap(f"Line {expr.line}: undefined variable '{expr.name}'")
            return ty
        if isinstance(expr, AssignExpr):
            existing = self._scope.lookup(expr.name)
            if existing is None:
                raise TypeErrorZap(f"Line {expr.line}: undefined variable '{expr.name}'")
            got = self._check_expr(expr.value)
            if existing != got:
                raise TypeErrorZap(
                    f"Line {expr.line}: cannot assign {got} to {existing} variable '{expr.name}'"
                )
            return existing
        if isinstance(expr, BinOp):
            return self._check_binop(expr)
        if isinstance(expr, UnaryOp):
            return self._check_unary(expr)
        if isinstance(expr, CallExpr):
            return self._check_call(expr)
        raise TypeErrorZap(f"Unknown expression kind: {type(expr).__name__}")

    def _check_binop(self, e: BinOp) -> str:
        lt = self._check_expr(e.left)
        rt = self._check_expr(e.right)
        if e.op in ("+", "-", "*", "/"):
            if lt != "int" or rt != "int":
                raise TypeErrorZap(f"Line {e.line}: {e.op} requires int operands, got {lt} and {rt}")
            return "int"
        if e.op in ("<", ">", "<=", ">="):
            if lt != "int" or rt != "int":
                raise TypeErrorZap(f"Line {e.line}: {e.op} requires int operands")
            return "bool"
        if e.op in ("==", "!="):
            if lt != rt:
                raise TypeErrorZap(f"Line {e.line}: {e.op} requires matching types, got {lt} and {rt}")
            return "bool"
        if e.op in ("&&", "||"):
            if lt != "bool" or rt != "bool":
                raise TypeErrorZap(f"Line {e.line}: {e.op} requires bool operands")
            return "bool"
        raise TypeErrorZap(f"Unknown binary operator '{e.op}'")

    def _check_unary(self, e: UnaryOp) -> str:
        ty = self._check_expr(e.operand)
        if e.op == "!":
            if ty != "bool":
                raise TypeErrorZap(f"Line {e.line}: '!' requires bool operand, got {ty}")
            return "bool"
        if e.op == "-":
            if ty != "int":
                raise TypeErrorZap(f"Line {e.line}: unary '-' requires int operand, got {ty}")
            return "int"
        raise TypeErrorZap(f"Unknown unary operator '{e.op}'")

    def _check_call(self, e: CallExpr) -> str:
        if e.name not in self._fns:
            raise TypeErrorZap(f"Line {e.line}: undefined function '{e.name}'")
        param_types, ret = self._fns[e.name]
        if len(e.args) != len(param_types):
            raise TypeErrorZap(
                f"Line {e.line}: '{e.name}' expects {len(param_types)} args, got {len(e.args)}"
            )
        for i, (arg, expected) in enumerate(zip(e.args, param_types)):
            got = self._check_expr(arg)
            if got != expected:
                raise TypeErrorZap(
                    f"Line {e.line}: arg {i} of '{e.name}': expected {expected}, got {got}"
                )
        return ret


def type_check(program: Program) -> None:
    TypeChecker().check(program)
