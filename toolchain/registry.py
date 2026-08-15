"""Which modules are here, what they need, and how to run each on its own.

Static data. Reading it imports nothing, so `lang modules` works without a JDK,
Node, or anything else a particular module happens to need, and a module that
cannot run here says why.
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

MODULES_ROOT = Path(__file__).resolve().parents[1] / "modules"


@dataclass(frozen=True)
class ModuleSpec:
    name: str
    title: str
    summary: str
    language: str
    source_root: str          # relative to the module folder
    standalone: str
    needs_tool: str = ""      # an executable that must be on PATH

    @property
    def path(self) -> Path:
        return MODULES_ROOT / self.name

    @property
    def root(self) -> Path:
        return self.path / self.source_root if self.source_root else self.path


MANIFEST: tuple[ModuleSpec, ...] = (
    ModuleSpec(
        name="compiler",
        title="Zap compiler",
        summary="A small statically-typed language: lexer, parser, type checker, "
                "and two backends — a stack VM and WebAssembly.",
        language="Python + Rust",
        source_root="python",
        standalone="python scripts/zapc.py ../examples/fibonacci.zap",
    ),
    ModuleSpec(
        name="wasm-runtime",
        title="WebAssembly runtime",
        summary="Binary parser, validator and interpreter: the thing the "
                "compiler's WebAssembly backend targets.",
        language="Python",
        source_root="",
        standalone="python -c \"from wasm.runtime import load_file\"",
    ),
    ModuleSpec(
        name="profiler",
        title="Sampling profiler",
        summary="Stack-sampling profiler with an interactive flame graph — used "
                "here to profile the runtime executing compiled code.",
        language="Python",
        source_root="",
        standalone="python profile.py scripts/demo_workload.py",
    ),
    ModuleSpec(
        name="resolver",
        title="Dependency resolver",
        summary="Version-constraint solving as SAT, with a CDCL solver and "
                "conflict explanations rather than a backtracking guess.",
        language="Python",
        source_root="",
        standalone="python resolve.py",
    ),
    ModuleSpec(
        name="multiplexer",
        title="Terminal multiplexer",
        summary="Split panes, windows, scrollback and session persistence over "
                "pseudoterminals — tmux's model, from the syscalls up.",
        language="Python",
        source_root="",
        standalone="python main.py",
    ),
    ModuleSpec(
        name="regex",
        title="Regex engine",
        summary="Parser, NFA compiler and a Pike VM — linear time on the "
                "patterns that make backtracking engines hang.",
        language="Java",
        source_root="",
        standalone="./build.sh && java -cp out regex.Main",
        needs_tool="javac",
    ),
    ModuleSpec(
        name="parser-combinators",
        title="Parser combinators",
        summary="A combinator library with backtracking control and error "
                "reporting — the front end of a language, as a library.",
        language="JavaScript",
        source_root="",
        standalone="npm test",
        needs_tool="node",
    ),
)

_BY_NAME = {spec.name: spec for spec in MANIFEST}


def specs() -> list[ModuleSpec]:
    return list(MANIFEST)


def spec(name: str) -> ModuleSpec:
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(
            f"unknown module {name!r}; choose from {', '.join(sorted(_BY_NAME))}"
        ) from None


def unavailable(spec_: ModuleSpec) -> str:
    """Why this module cannot run here, or an empty string."""
    if not spec_.path.is_dir():
        return "not present in this repository"
    if spec_.needs_tool and shutil.which(spec_.needs_tool) is None:
        return f"needs {spec_.needs_tool} on PATH"
    return ""


def add_to_path(name: str) -> Path:
    """Put a module's source root on `sys.path` — each is its own."""
    root = spec(name).root
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root
