"""toolchain — a language, a runtime that executes it, and the tools around it.

    from toolchain.pipeline import build_and_run
    result = build_and_run(source, target="wasm", compare=True)

Seven modules, each usable on its own. This package is the pipeline that runs
a `.zap` file through the compiler, out as WebAssembly, into this repository's
own runtime, under this repository's own profiler.
"""

from . import pipeline, registry

__version__ = "1.0.0"
__all__ = ["pipeline", "registry"]
