"""Source to output, through this repository's own parts.

    .zap  →  compiler  →  .wasm  →  wasm-runtime  →  output
                                        ↑
                                    profiler

Each stage is a module that works on its own. This is the file that makes them
one pipeline, and the only place that knows all three exist.

The profiling stage is the one worth explaining. Profiling *the interpreter
while it runs your program* is not the same as profiling your program: what
comes back is where the runtime spends its time — instruction dispatch, stack
handling, call overhead. That is exactly the question you have when you have
written both.
"""

from __future__ import annotations

import contextlib
import io
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import registry


@dataclass
class Stage:
    """One step, and what it cost."""

    name: str
    detail: str = ""
    elapsed: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error


@dataclass
class Result:
    """What a pipeline run produced."""

    source: str = ""
    target: str = "wasm"
    stages: list[Stage] = field(default_factory=list)
    output: list[str] = field(default_factory=list)
    wasm: bytes = b""
    profile: dict[str, Any] | None = None

    def stage(self, name: str) -> Stage:
        step = Stage(name=name)
        self.stages.append(step)
        return step

    @property
    def ok(self) -> bool:
        return all(step.ok for step in self.stages)

    @property
    def failed(self) -> Stage | None:
        return next((s for s in self.stages if s.error), None)


def compile_source(source: str, *, target: str = "wasm") -> tuple[Any, bytes]:
    """Parse, type-check and compile. Returns (program, artifact).

    For `target="wasm"` the artifact is a WebAssembly binary; for `target="vm"`
    it is the compiler's own bytecode object, returned unencoded.
    """
    registry.add_to_path("compiler")
    from zap import compile_program, parse, type_check
    from zap.wasm_backend import compile_to_wasm

    program = parse(source)
    type_check(program)
    if target == "wasm":
        return program, compile_to_wasm(program)
    return program, compile_program(program)


def run_wasm(binary: bytes, *, entry: str = "__main__") -> list[str]:
    """Execute a module on this repository's runtime, capturing what it printed.

    `print` is an import rather than a builtin because a WebAssembly module has
    no way to reach the outside on its own — the host supplies it, and here the
    host is us.
    """
    registry.add_to_path("wasm-runtime")
    from wasm.runtime import load_bytes

    printed: list[str] = []
    instance = load_bytes(binary, imports={"env": {"print": lambda v: printed.append(str(v))}})
    instance.call(entry)
    return printed


def run_vm(compiled: Any) -> list[str]:
    """Execute on the compiler's own stack VM — the reference implementation.

    The VM both prints and returns its output. Returning it is what a caller
    wants; printing it means a cross-check run scribbles the reference output
    over the report, so stdout is captured and discarded here.
    """
    registry.add_to_path("compiler")
    from zap import run_program

    with contextlib.redirect_stdout(io.StringIO()):
        lines = run_program(compiled)
    return [str(line) for line in lines]


def build_and_run(
    source: str,
    *,
    target: str = "wasm",
    profile: bool = False,
    compare: bool = False,
    interval: float = 0.001,
) -> Result:
    """The whole pipeline.

    `compare=True` runs the same program on both backends and reports whether
    they agree — which is the only real check that a second backend is correct,
    and is why the VM stayed rather than being replaced.
    """
    result = Result(source=source, target=target)

    step = result.stage("compile")
    started = time.perf_counter()
    try:
        program, artifact = compile_source(source, target=target)
    except Exception as exc:  # noqa: BLE001 — reported, not raised
        step.error = f"{type(exc).__name__}: {exc}"
        step.elapsed = time.perf_counter() - started
        return result
    step.elapsed = time.perf_counter() - started
    if target == "wasm":
        result.wasm = artifact
        step.detail = f"{len(artifact)} bytes of WebAssembly"
    else:
        step.detail = f"{len(artifact.functions)} function(s) of bytecode"

    step = result.stage("execute")
    started = time.perf_counter()
    try:
        if profile:
            result.output, result.profile = _run_profiled(artifact, target, interval)
        elif target == "wasm":
            result.output = run_wasm(artifact)
        else:
            result.output = run_vm(artifact)
    except Exception as exc:  # noqa: BLE001
        step.error = f"{type(exc).__name__}: {exc}"
        step.elapsed = time.perf_counter() - started
        return result
    step.elapsed = time.perf_counter() - started
    step.detail = f"{len(result.output)} line(s) of output"

    if compare and target == "wasm":
        step = result.stage("cross-check")
        started = time.perf_counter()
        try:
            _, bytecode = compile_source(source, target="vm")
            reference = run_vm(bytecode)
        except Exception as exc:  # noqa: BLE001
            step.error = f"{type(exc).__name__}: {exc}"
        else:
            if reference == result.output:
                step.detail = f"WebAssembly and the VM agree on {len(reference)} line(s)"
            else:
                step.error = (
                    f"backends disagree — VM produced {reference!r}, "
                    f"WebAssembly produced {result.output!r}"
                )
        step.elapsed = time.perf_counter() - started

    return result


def _run_profiled(artifact: Any, target: str, interval: float) -> tuple[list[str], dict[str, Any]]:
    """Run under the sampling profiler and summarise where the time went."""
    registry.add_to_path("profiler")
    from config import ProfilerConfig
    from profiler.sampler import ProfileSession

    with ProfileSession(ProfilerConfig(interval=interval)) as session:
        output = run_wasm(artifact) if target == "wasm" else run_vm(artifact)

    return output, _summarise(session.profile)


def _summarise(data: Any) -> dict[str, Any]:
    """The few numbers worth printing from a profile.

    A flame graph is the right way to *explore* a profile and the wrong thing to
    put in a terminal, so the CLI shows the hottest frames and leaves the graph
    to `profile.py`'s own UI.
    """
    samples = list(getattr(data, "samples", []) or [])
    counts: dict[str, int] = {}
    for snapshot in samples:
        # `stack` is outermost-first, so the frame actually running is last.
        frames = snapshot.stack
        if not frames:
            continue
        top = frames[-1]
        label = f"{top.funcname} ({Path(top.filename).name}:{top.lineno})"
        counts[label] = counts.get(label, 0) + 1

    total = sum(counts.values()) or 1
    hottest = sorted(counts.items(), key=lambda kv: -kv[1])[:8]
    return {
        "samples": len(samples),
        "hottest": [
            {"frame": name, "samples": n, "share": round(n / total, 4)}
            for name, n in hottest
        ],
    }
