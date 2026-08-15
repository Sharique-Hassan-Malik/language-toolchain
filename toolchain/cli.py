"""`lang` — one command over the toolchain.

    lang modules                       what is here, and how to run each alone
    lang build prog.zap -o prog.wasm   compile to WebAssembly
    lang run prog.zap                  compile and execute on our own runtime
    lang run prog.zap --compare        …and check the VM agrees
    lang run prog.zap --profile        …and report where the runtime spent time

Each module keeps its own CLI. `lang` is the pipeline that joins them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import registry
from .pipeline import build_and_run, compile_source


def _wrap(text: str, width: int) -> list[str]:
    words, lines, line = text.split(), [], []
    for word in words:
        if sum(len(w) + 1 for w in line) + len(word) > width and line:
            lines.append(" ".join(line))
            line = []
        line.append(word)
    if line:
        lines.append(" ".join(line))
    return lines


def _cmd_modules(args: argparse.Namespace) -> int:
    print()
    for spec in registry.specs():
        why = registry.unavailable(spec)
        print(f"  {spec.name:20} {spec.language:16} {'ready' if not why else why}")
        print(f"  {'':20} {spec.title}")
        for line in _wrap(spec.summary, 72):
            print(f"  {'':20} {line}")
        print(f"  {'':20} cd modules/{spec.name}"
              f"{'/' + spec.source_root if spec.source_root else ''} && {spec.standalone}")
        print()
    return 0


def _cmd_build(args: argparse.Namespace) -> int:
    source = Path(args.source).read_text(encoding="utf-8")
    try:
        _, artifact = compile_source(source, target="wasm")
    except Exception as exc:  # noqa: BLE001
        print(f"lang: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    out = Path(args.output or Path(args.source).with_suffix(".wasm"))
    out.write_bytes(artifact)
    print(f"  {args.source} → {out}  ({len(artifact)} bytes)")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    source = Path(args.source).read_text(encoding="utf-8")
    result = build_and_run(
        source,
        target=args.target,
        profile=args.profile,
        compare=args.compare,
        interval=args.interval,
    )

    print()
    for stage in result.stages:
        state = stage.detail if stage.ok else f"FAILED — {stage.error}"
        print(f"  {stage.name:12} {stage.elapsed * 1000:8.2f} ms   {state}")

    if result.output:
        print()
        for line in result.output:
            print(f"  {line}")

    if result.profile:
        print(f"\n  profile — {result.profile['samples']} samples, hottest frames:")
        for entry in result.profile["hottest"]:
            print(f"    {entry['share']:6.1%}  {entry['frame']}")
        print("\n  These are the *runtime's* frames, not your program's: what a")
        print("  sampling profiler sees while an interpreter runs your code is")
        print("  where the interpreter spends its time.")

    if args.emit and result.wasm:
        Path(args.emit).write_bytes(result.wasm)
        print(f"\n  WebAssembly → {args.emit}")

    if args.json:
        payload = {
            "target": result.target,
            "output": result.output,
            "stages": [
                {"name": s.name, "ms": round(s.elapsed * 1000, 3),
                 "detail": s.detail, "error": s.error}
                for s in result.stages
            ],
            "profile": result.profile,
        }
        text = json.dumps(payload, indent=2)
        if args.json == "-":
            print(text)
        else:
            Path(args.json).write_text(text, encoding="utf-8")

    print()
    return 0 if result.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lang",
        description="A compiler, the runtime it targets, and the tools around them.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("modules", help="the modules and their own CLIs")

    build = sub.add_parser("build", help="compile a .zap file to WebAssembly")
    build.add_argument("source")
    build.add_argument("-o", "--output", help="output path (default: alongside the source)")

    run = sub.add_parser("run", help="compile and execute")
    run.add_argument("source")
    run.add_argument("--target", default="wasm", choices=["wasm", "vm"])
    run.add_argument("--compare", action="store_true",
                     help="also run on the VM and check the two agree")
    run.add_argument("--profile", action="store_true",
                     help="sample the runtime while it executes")
    run.add_argument("--interval", type=float, default=0.001, metavar="SECONDS")
    run.add_argument("--emit", metavar="FILE", help="also write the .wasm")
    run.add_argument("--json", metavar="FILE", nargs="?", const="-")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "modules":
        return _cmd_modules(args)
    if args.command == "build":
        return _cmd_build(args)
    return _cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
