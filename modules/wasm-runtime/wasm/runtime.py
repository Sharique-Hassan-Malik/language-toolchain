"""
WebAssembly runtime — public API.

    from wasm.runtime import load_file, load_bytes

    inst = load_file("hello.wasm")
    result = inst.call("add", 3, 4)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from wasm.instance import ModuleInstance
from wasm.parser import parse


def load_bytes(
    data:    bytes,
    imports: dict[str, dict[str, Any]] | None = None,
) -> ModuleInstance:
    """Parse and instantiate a wasm binary from raw bytes."""
    module = parse(data)
    return ModuleInstance(module, imports)


def load_file(
    path:    str | Path,
    imports: dict[str, dict[str, Any]] | None = None,
) -> ModuleInstance:
    """Parse and instantiate a wasm binary from a file path."""
    data = Path(path).read_bytes()
    return load_bytes(data, imports)
