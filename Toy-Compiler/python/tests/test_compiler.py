"""Tests for the Zap Python compiler — lexer, parser, type checker and VM."""

from __future__ import annotations
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from zap import compile_and_run, parse, type_check, compile_program, run_program
from zap.lexer import tokenize, TT, LexError
from zap.parser import ParseError
from zap.type_checker import TypeErrorZap
from zap.vm import ZapRuntimeError


# ── helpers ───────────────────────────────────────────────────────────────────

def run(src: str) -> list[str]:
    return compile_and_run(src)


# ── lexer ─────────────────────────────────────────────────────────────────────

def test_lex_integer():
    toks = tokenize("42")
    assert toks[0].ty == TT.INT
    assert toks[0].value == "42"


def test_lex_keywords():
    src = "fn let return if else while print true false int bool void"
    expected = [
        TT.FN, TT.LET, TT.RETURN, TT.IF, TT.ELSE, TT.WHILE,
        TT.PRINT, TT.TRUE, TT.FALSE, TT.T_INT, TT.T_BOOL, TT.T_VOID,
    ]
    toks = [t for t in tokenize(src) if t.ty != TT.EOF]
    assert [t.ty for t in toks] == expected


def test_lex_operators():
    src = "== != <= >= && || ->"
    types = [t.ty for t in tokenize(src) if t.ty != TT.EOF]
    assert types == [TT.EQ_EQ, TT.BANG_EQ, TT.LT_EQ, TT.GT_EQ, TT.AND, TT.OR, TT.ARROW]


def test_lex_line_comment():
    toks = [t for t in tokenize("// ignored\n42") if t.ty != TT.EOF]
    assert len(toks) == 1 and toks[0].value == "42"


def test_lex_unknown_char():
    with pytest.raises(LexError):
        tokenize("@")


# ── parser ────────────────────────────────────────────────────────────────────

def test_parse_let():
    prog = parse("let x: int = 5;")
    from zap.ast_nodes import LetStmt, IntLit
    stmt = prog.decls[0]
    assert isinstance(stmt, LetStmt)
    assert stmt.name == "x" and stmt.ty == "int"
    assert isinstance(stmt.value, IntLit) and stmt.value.value == 5


def test_parse_fn_decl():
    prog = parse("fn add(a: int, b: int) -> int { return a + b; }")
    from zap.ast_nodes import FnDecl
    fn = prog.decls[0]
    assert isinstance(fn, FnDecl)
    assert fn.name == "add"
    assert fn.params == [("a", "int"), ("b", "int")]
    assert fn.return_type == "int"


def test_parse_if_else():
    prog = parse("if true { print(1); } else { print(0); }")
    from zap.ast_nodes import IfStmt
    assert isinstance(prog.decls[0], IfStmt)
    assert prog.decls[0].else_block is not None


def test_parse_while():
    prog = parse("let i: int = 0; while i < 3 { i = i + 1; }")
    from zap.ast_nodes import WhileStmt
    assert isinstance(prog.decls[1], WhileStmt)


def test_parse_call():
    prog = parse("let x: int = foo(1, 2);")
    from zap.ast_nodes import LetStmt, CallExpr
    stmt = prog.decls[0]
    assert isinstance(stmt.value, CallExpr)
    assert stmt.value.name == "foo" and len(stmt.value.args) == 2


def test_parse_error_missing_semi():
    with pytest.raises(ParseError):
        parse("let x: int = 5")


# ── type checker ──────────────────────────────────────────────────────────────

def test_type_error_bad_let():
    with pytest.raises(TypeErrorZap):
        prog = parse("let x: bool = 5;")
        type_check(prog)


def test_type_error_undefined_var():
    with pytest.raises(TypeErrorZap):
        prog = parse("print(undeclared);")
        type_check(prog)


def test_type_error_wrong_arg():
    with pytest.raises(TypeErrorZap):
        src = "fn f(x: int) -> int { return x; } print(f(true));"
        prog = parse(src)
        type_check(prog)


def test_type_error_return_mismatch():
    with pytest.raises(TypeErrorZap):
        src = "fn f() -> int { return true; }"
        prog = parse(src)
        type_check(prog)


def test_type_error_non_bool_condition():
    with pytest.raises(TypeErrorZap):
        prog = parse("if 1 { print(1); }")
        type_check(prog)


# ── compiler + VM ─────────────────────────────────────────────────────────────

def test_arithmetic():
    assert run("print(2 + 3 * 4);") == ["14"]


def test_unary_neg():
    assert run("print(-5);") == ["-5"]


def test_boolean_not():
    assert run("print(!false);") == ["true"]


def test_let_and_assign():
    src = "let x: int = 10; x = x + 1; print(x);"
    assert run(src) == ["11"]


def test_if_true_branch():
    assert run("if true { print(1); } else { print(0); }") == ["1"]


def test_if_false_branch():
    assert run("if false { print(1); } else { print(0); }") == ["0"]


def test_while_loop():
    src = "let i: int = 0; while i < 3 { print(i); i = i + 1; }"
    assert run(src) == ["0", "1", "2"]


def test_function_call():
    src = "fn double(x: int) -> int { return x * 2; } print(double(7));"
    assert run(src) == ["14"]


def test_recursive_fib():
    src = """
fn fib(n: int) -> int {
    if n <= 1 { return n; }
    return fib(n - 1) + fib(n - 2);
}
print(fib(10));
"""
    assert run(src) == ["55"]


def test_comparison_operators():
    assert run("print(3 < 5);")  == ["true"]
    assert run("print(5 <= 5);") == ["true"]
    assert run("print(6 > 5);")  == ["true"]
    assert run("print(4 >= 5);") == ["false"]


def test_equality():
    assert run("print(3 == 3);") == ["true"]
    assert run("print(3 != 4);") == ["true"]


def test_logical_and_or():
    assert run("print(true && false);") == ["false"]
    assert run("print(true || false);") == ["true"]


def test_disassemble_produces_output():
    prog = parse("print(1 + 2);")
    type_check(prog)
    code = compile_program(prog)
    dis = code.disassemble()
    assert "PUSH_INT" in dis
    assert "PRINT" in dis


def test_division():
    assert run("print(10 / 3);") == ["3"]


def test_nested_calls():
    src = """
fn square(x: int) -> int { return x * x; }
fn sum_sq(a: int, b: int) -> int { return square(a) + square(b); }
print(sum_sq(3, 4));
"""
    assert run(src) == ["25"]


def test_runtime_error_div_zero():
    with pytest.raises(ZapRuntimeError):
        src = "print(1 / 0);"
        prog = parse(src)
        type_check(prog)
        code = compile_program(prog)
        run_program(code)
