#!/usr/bin/env python3
"""zapc — Zap compiler CLI."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from zap import compile_and_run, parse, type_check, compile_program
from zap.lexer import LexError
from zap.parser import ParseError
from zap.type_checker import TypeErrorZap
from zap.vm import ZapRuntimeError


def main() -> None:
    ap = argparse.ArgumentParser(prog="zapc", description="Zap compiler and runner")
    ap.add_argument("file", help="Source file (.zap)")
    ap.add_argument("--dis", action="store_true", help="Print disassembly instead of running")
    args = ap.parse_args()

    src = Path(args.file).read_text()

    try:
        prog = parse(src)
        type_check(prog)
        code = compile_program(prog)
    except (LexError, ParseError, TypeErrorZap) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.dis:
        print(code.disassemble())
        return

    try:
        from zap.vm import run
        run(code)
    except ZapRuntimeError as e:
        print(f"runtime error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
