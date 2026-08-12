"""
AST node definitions for Zap.

Grammar summary:
    program   = (fn_decl | stmt)*
    fn_decl   = 'fn' IDENT '(' params? ')' '->' type block
    stmt      = let | return | if | while | print | expr ';'
    expr      = assign | or | and | eq | cmp | add | mul | unary | call | primary
    type      = 'int' | 'bool' | 'void'
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Union, Optional


ZapType = str  # "int", "bool" or "void"


@dataclass
class Program:
    decls: list[Union["FnDecl", "Stmt"]]


@dataclass
class FnDecl:
    name: str
    params: list[tuple[str, ZapType]]
    return_type: ZapType
    body: "Block"
    line: int = 0


@dataclass
class Block:
    stmts: list["Stmt"]


# ── Statements ────────────────────────────────────────────────────────────────

@dataclass
class LetStmt:
    name: str
    ty: ZapType
    value: "Expr"
    line: int = 0


@dataclass
class ReturnStmt:
    value: Optional["Expr"]
    line: int = 0


@dataclass
class IfStmt:
    cond: "Expr"
    then_block: Block
    else_block: Optional[Block]
    line: int = 0


@dataclass
class WhileStmt:
    cond: "Expr"
    body: Block
    line: int = 0


@dataclass
class PrintStmt:
    value: "Expr"
    line: int = 0


@dataclass
class ExprStmt:
    expr: "Expr"
    line: int = 0


Stmt = Union[LetStmt, ReturnStmt, IfStmt, WhileStmt, PrintStmt, ExprStmt]


# ── Expressions ───────────────────────────────────────────────────────────────

@dataclass
class IntLit:
    value: int
    line: int = 0


@dataclass
class BoolLit:
    value: bool
    line: int = 0


@dataclass
class IdentExpr:
    name: str
    line: int = 0


@dataclass
class BinOp:
    op: str
    left: "Expr"
    right: "Expr"
    line: int = 0


@dataclass
class UnaryOp:
    op: str
    operand: "Expr"
    line: int = 0


@dataclass
class CallExpr:
    name: str
    args: list["Expr"]
    line: int = 0


@dataclass
class AssignExpr:
    name: str
    value: "Expr"
    line: int = 0


Expr = Union[IntLit, BoolLit, IdentExpr, BinOp, UnaryOp, CallExpr, AssignExpr]
