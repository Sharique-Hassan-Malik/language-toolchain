"""
Zap compiler — tokenize, parse, type-check, compile and execute.

Full pipeline:
    from zap import compile_and_run
    lines = compile_and_run(source_code)
"""

from .lexer        import tokenize, Token, TT, LexError
from .ast_nodes    import Program
from .parser       import parse, ParseError
from .type_checker import type_check, TypeErrorZap
from .codegen      import compile_program, CompiledProgram
from .vm           import run as run_program, ZapRuntimeError

__all__ = [
    "tokenize", "Token", "TT", "LexError",
    "Program",
    "parse", "ParseError",
    "type_check", "TypeErrorZap",
    "compile_program", "CompiledProgram",
    "run_program", "ZapRuntimeError",
    "compile_and_run",
]


def compile_and_run(src: str) -> list[str]:
    """Convenience: run source through the entire pipeline and return output lines."""
    prog = parse(src)
    type_check(prog)
    code = compile_program(prog)
    return run_program(code)
