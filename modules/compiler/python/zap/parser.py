"""Recursive descent parser for Zap. Produces a typed AST."""

from __future__ import annotations
from .ast_nodes import *
from .lexer import Token, TT, tokenize


class ParseError(Exception):
    pass


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self._t = tokens
        self._pos = 0

    # ── helpers ───────────────────────────────────────────────────────────────

    def _cur(self) -> Token:
        return self._t[self._pos]

    def _peek(self) -> Token:
        idx = min(self._pos + 1, len(self._t) - 1)
        return self._t[idx]

    def _at(self, *types: TT) -> bool:
        return self._cur().ty in types

    def _advance(self) -> Token:
        tok = self._t[self._pos]
        self._pos += 1
        return tok

    def _eat(self, ty: TT) -> Token:
        tok = self._cur()
        if tok.ty != ty:
            raise ParseError(
                f"Line {tok.line}: expected {ty.name}, got {tok.ty.name} ({tok.value!r})"
            )
        return self._advance()

    # ── top level ─────────────────────────────────────────────────────────────

    def parse_program(self) -> Program:
        decls: list[FnDecl | Stmt] = []
        while not self._at(TT.EOF):
            if self._at(TT.FN):
                decls.append(self._fn())
            else:
                decls.append(self._stmt())
        return Program(decls)

    def _fn(self) -> FnDecl:
        line = self._cur().line
        self._eat(TT.FN)
        name = self._eat(TT.IDENT).value
        self._eat(TT.LPAREN)
        params: list[tuple[str, str]] = []
        if not self._at(TT.RPAREN):
            params.append(self._param())
            while self._at(TT.COMMA):
                self._advance()
                params.append(self._param())
        self._eat(TT.RPAREN)
        self._eat(TT.ARROW)
        ret = self._type()
        body = self._block()
        return FnDecl(name, params, ret, body, line)

    def _param(self) -> tuple[str, str]:
        name = self._eat(TT.IDENT).value
        self._eat(TT.COLON)
        return (name, self._type())

    def _type(self) -> str:
        tok = self._cur()
        if tok.ty == TT.T_INT:  self._advance(); return "int"
        if tok.ty == TT.T_BOOL: self._advance(); return "bool"
        if tok.ty == TT.T_VOID: self._advance(); return "void"
        raise ParseError(f"Line {tok.line}: expected type, got {tok.value!r}")

    def _block(self) -> Block:
        self._eat(TT.LBRACE)
        stmts: list[Stmt] = []
        while not self._at(TT.RBRACE, TT.EOF):
            stmts.append(self._stmt())
        self._eat(TT.RBRACE)
        return Block(stmts)

    # ── statements ────────────────────────────────────────────────────────────

    def _stmt(self) -> Stmt:
        match self._cur().ty:
            case TT.LET:    return self._let()
            case TT.RETURN: return self._return()
            case TT.IF:     return self._if()
            case TT.WHILE:  return self._while()
            case TT.PRINT:  return self._print()
            case _:         return self._expr_stmt()

    def _let(self) -> LetStmt:
        line = self._cur().line
        self._eat(TT.LET)
        name = self._eat(TT.IDENT).value
        self._eat(TT.COLON)
        ty = self._type()
        self._eat(TT.EQ)
        val = self._expr()
        self._eat(TT.SEMI)
        return LetStmt(name, ty, val, line)

    def _return(self) -> ReturnStmt:
        line = self._cur().line
        self._eat(TT.RETURN)
        val = None if self._at(TT.SEMI) else self._expr()
        self._eat(TT.SEMI)
        return ReturnStmt(val, line)

    def _if(self) -> IfStmt:
        line = self._cur().line
        self._eat(TT.IF)
        cond = self._expr()
        then = self._block()
        else_ = None
        if self._at(TT.ELSE):
            self._advance()
            else_ = self._block()
        return IfStmt(cond, then, else_, line)

    def _while(self) -> WhileStmt:
        line = self._cur().line
        self._eat(TT.WHILE)
        cond = self._expr()
        body = self._block()
        return WhileStmt(cond, body, line)

    def _print(self) -> PrintStmt:
        line = self._cur().line
        self._eat(TT.PRINT)
        self._eat(TT.LPAREN)
        val = self._expr()
        self._eat(TT.RPAREN)
        self._eat(TT.SEMI)
        return PrintStmt(val, line)

    def _expr_stmt(self) -> ExprStmt:
        line = self._cur().line
        e = self._expr()
        self._eat(TT.SEMI)
        return ExprStmt(e, line)

    # ── expressions (precedence climbing) ────────────────────────────────────

    def _expr(self) -> Expr:
        return self._assign()

    def _assign(self) -> Expr:
        if self._at(TT.IDENT) and self._peek().ty == TT.EQ:
            line = self._cur().line
            name = self._advance().value
            self._advance()  # consume '='
            return AssignExpr(name, self._assign(), line)
        return self._or()

    def _or(self) -> Expr:
        left = self._and()
        while self._at(TT.OR):
            line = self._cur().line
            self._advance()
            left = BinOp("||", left, self._and(), line)
        return left

    def _and(self) -> Expr:
        left = self._eq()
        while self._at(TT.AND):
            line = self._cur().line
            self._advance()
            left = BinOp("&&", left, self._eq(), line)
        return left

    def _eq(self) -> Expr:
        left = self._cmp()
        while self._at(TT.EQ_EQ, TT.BANG_EQ):
            line = self._cur().line
            op = self._advance().value
            left = BinOp(op, left, self._cmp(), line)
        return left

    def _cmp(self) -> Expr:
        left = self._add()
        while self._at(TT.LT, TT.GT, TT.LT_EQ, TT.GT_EQ):
            line = self._cur().line
            op = self._advance().value
            left = BinOp(op, left, self._add(), line)
        return left

    def _add(self) -> Expr:
        left = self._mul()
        while self._at(TT.PLUS, TT.MINUS):
            line = self._cur().line
            op = self._advance().value
            left = BinOp(op, left, self._mul(), line)
        return left

    def _mul(self) -> Expr:
        left = self._unary()
        while self._at(TT.STAR, TT.SLASH):
            line = self._cur().line
            op = self._advance().value
            left = BinOp(op, left, self._unary(), line)
        return left

    def _unary(self) -> Expr:
        if self._at(TT.BANG):
            line = self._cur().line
            self._advance()
            return UnaryOp("!", self._unary(), line)
        if self._at(TT.MINUS):
            line = self._cur().line
            self._advance()
            return UnaryOp("-", self._unary(), line)
        return self._call()

    def _call(self) -> Expr:
        prim = self._primary()
        if isinstance(prim, IdentExpr) and self._at(TT.LPAREN):
            line = self._cur().line
            self._advance()
            args: list[Expr] = []
            if not self._at(TT.RPAREN):
                args.append(self._expr())
                while self._at(TT.COMMA):
                    self._advance()
                    args.append(self._expr())
            self._eat(TT.RPAREN)
            return CallExpr(prim.name, args, line)
        return prim

    def _primary(self) -> Expr:
        tok = self._cur()
        if tok.ty == TT.INT:
            self._advance(); return IntLit(int(tok.value), tok.line)
        if tok.ty == TT.TRUE:
            self._advance(); return BoolLit(True, tok.line)
        if tok.ty == TT.FALSE:
            self._advance(); return BoolLit(False, tok.line)
        if tok.ty == TT.IDENT:
            self._advance(); return IdentExpr(tok.value, tok.line)
        if tok.ty == TT.LPAREN:
            self._advance()
            e = self._expr()
            self._eat(TT.RPAREN)
            return e
        raise ParseError(
            f"Line {tok.line}: unexpected token {tok.ty.name} ({tok.value!r})"
        )


def parse(src: str) -> Program:
    return Parser(tokenize(src)).parse_program()
