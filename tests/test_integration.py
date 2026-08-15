"""Cross-module tests — what is only true because these seven are one repo.

Each module's own behaviour is tested in its own folder. What is tested here is
the pipeline: that the compiler's WebAssembly output is a module this
repository's runtime accepts, that it computes the same answers as the
reference VM, and that each module still runs from its own directory.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from toolchain import registry  # noqa: E402
from toolchain.pipeline import build_and_run, compile_source, run_vm, run_wasm  # noqa: E402

EXAMPLES = sorted((registry.spec("compiler").path / "examples").glob("*.zap"))


def _run(source: str) -> list[str]:
    _, binary = compile_source(source, target="wasm")
    return run_wasm(binary)


class TestLayout:
    def test_every_declared_module_exists(self):
        for spec in registry.specs():
            assert spec.path.is_dir(), f"{spec.name} is missing"

    def test_every_module_has_a_readme(self):
        for spec in registry.specs():
            assert (spec.path / "README.md").is_file(), f"{spec.name} has no README"

    def test_no_two_modules_claim_the_same_top_level_module_name(self):
        """A collision only visible once they share a process."""
        seen: dict[str, str] = {}
        for spec in registry.specs():
            for entry in spec.root.glob("*.py"):
                assert entry.stem not in seen, (
                    f"{spec.name}/{entry.name} collides with {seen[entry.stem]}"
                )
                seen[entry.stem] = f"{spec.name}/{entry.name}"

    def test_unknown_module_is_a_clear_error(self):
        with pytest.raises(KeyError, match="unknown module"):
            registry.spec("nope")


class TestWasmBackend:
    def test_emits_a_valid_module_header(self):
        _, binary = compile_source("print(1);", target="wasm")
        assert binary[:4] == b"\x00asm"
        assert binary[4:8] == b"\x01\x00\x00\x00"

    def test_the_runtime_accepts_and_exports_what_was_compiled(self):
        registry.add_to_path("wasm-runtime")
        from wasm.runtime import load_bytes

        _, binary = compile_source(
            "fn sq(n: int) -> int { return n * n; } print(sq(4));", target="wasm"
        )
        instance = load_bytes(binary, imports={"env": {"print": lambda v: None}})
        assert set(instance.exports()) >= {"sq", "__main__"}

    def test_an_exported_function_is_callable_directly(self):
        registry.add_to_path("wasm-runtime")
        from wasm.runtime import load_bytes

        _, binary = compile_source("fn sq(n: int) -> int { return n * n; }", target="wasm")
        instance = load_bytes(binary, imports={"env": {"print": lambda v: None}})
        assert instance.call("sq", 7) == [49]

    @pytest.mark.parametrize(
        "source,expected",
        [
            ("print(42);", ["42"]),
            ("let x: int = 7; print(x * 6);", ["42"]),
            ("print(10 - 3 - 2);", ["5"]),
            ("print(0 - 5);", ["-5"]),
            ("if 1 < 2 { print(1); } else { print(0); }", ["1"]),
            ("if 2 < 1 { print(1); } else { print(0); }", ["0"]),
            ("let i: int = 0; while i < 3 { print(i); i = i + 1; }", ["0", "1", "2"]),
        ],
        ids=["literal", "locals", "left-assoc", "negation", "if-true", "if-false", "while"],
    )
    def test_language_constructs(self, source, expected):
        assert _run(source) == expected

    def test_code_after_an_if_still_runs(self):
        """The regression that the backend found in the runtime.

        The runtime left the instruction pointer *on* the `if` block's `END`,
        and `END` breaks the dispatch loop — so everything after an `if` was
        silently discarded. Nothing in its own fixtures had code after an `if`.
        """
        assert _run("if 1 < 2 { print(1); } print(2); print(3);") == ["1", "2", "3"]

    def test_recursion_works(self):
        source = (
            "fn f(n: int) -> int { if n <= 1 { return n; } return f(n-1) + f(n-2); }"
            "print(f(10));"
        )
        assert _run(source) == ["55"]

    def test_an_untranslatable_construct_is_named(self):
        """A construct with no WebAssembly mapping must say so, not emit junk."""
        registry.add_to_path("compiler")
        from zap.ast_nodes import BinOp, IntLit, PrintStmt, Program
        from zap.wasm_backend import WasmBackendError, compile_to_wasm

        program = Program(decls=[
            PrintStmt(value=BinOp(op="**", left=IntLit(2), right=IntLit(3)))
        ])
        with pytest.raises(WasmBackendError, match=r"\*\*"):
            compile_to_wasm(program)

    def test_a_call_to_an_unknown_function_is_named(self):
        registry.add_to_path("compiler")
        from zap.ast_nodes import CallExpr, PrintStmt, Program
        from zap.wasm_backend import WasmBackendError, compile_to_wasm

        program = Program(decls=[PrintStmt(value=CallExpr(name="nope", args=[]))])
        with pytest.raises(WasmBackendError, match="nope"):
            compile_to_wasm(program)


class TestBackendsAgree:
    """The only real check on a second backend is the first one."""

    @pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
    def test_examples_produce_identical_output(self, path):
        source = path.read_text(encoding="utf-8")
        _, binary = compile_source(source, target="wasm")
        _, bytecode = compile_source(source, target="vm")
        assert run_wasm(binary) == run_vm(bytecode)

    def test_the_pipeline_reports_agreement(self):
        result = build_and_run(
            (registry.spec("compiler").path / "examples" / "fibonacci.zap")
            .read_text(encoding="utf-8"),
            target="wasm",
            compare=True,
        )
        assert result.ok
        assert [s.name for s in result.stages] == ["compile", "execute", "cross-check"]
        assert "agree" in result.stages[-1].detail

    def test_a_compile_error_stops_the_pipeline_with_a_reason(self):
        result = build_and_run("let x: int = ;", target="wasm")
        assert not result.ok
        assert result.failed.name == "compile"
        assert result.failed.error


class TestProfiling:
    def test_profiling_reports_the_runtime_frames(self):
        source = (
            "fn f(n: int) -> int { if n <= 1 { return n; } return f(n-1) + f(n-2); }"
            "print(f(15));"
        )
        result = build_and_run(source, target="wasm", profile=True, interval=0.001)
        assert result.ok
        assert result.profile["samples"] > 0
        frames = " ".join(entry["frame"] for entry in result.profile["hottest"])
        # It profiles the interpreter running the program, so the frames are
        # the runtime's.
        assert "executor.py" in frames


class TestStandalone:
    """Each module runs from its own folder — the reason for the layout."""

    def test_the_compiler_cli_runs_from_its_own_folder(self):
        compiler = registry.spec("compiler")
        completed = subprocess.run(
            [sys.executable, "scripts/zapc.py", "../examples/fibonacci.zap"],
            cwd=compiler.root, capture_output=True, text=True, timeout=180,
        )
        assert completed.returncode == 0, completed.stderr
        assert "55" in completed.stdout

    def test_the_runtime_imports_with_nothing_else_on_the_path(self):
        completed = subprocess.run(
            [sys.executable, "-c", "from wasm.runtime import load_bytes; print('ok')"],
            cwd=registry.spec("wasm-runtime").root,
            capture_output=True, text=True, timeout=120,
        )
        assert completed.returncode == 0, completed.stderr

    @pytest.mark.skipif(shutil.which("javac") is None, reason="no JDK on PATH")
    def test_the_regex_engine_builds(self):
        completed = subprocess.run(
            ["./build.sh"], cwd=registry.spec("regex").path,
            capture_output=True, text=True, timeout=600,
        )
        assert completed.returncode == 0, completed.stderr


class TestCli:
    def test_modules_listing_covers_the_repo(self, capsys):
        from toolchain import cli

        assert cli.main(["modules"]) == 0
        out = capsys.readouterr().out
        for spec in registry.specs():
            assert spec.name in out

    def test_build_writes_a_wasm_file(self, tmp_path, capsys):
        from toolchain import cli

        source = tmp_path / "p.zap"
        source.write_text("print(7);")
        out = tmp_path / "p.wasm"
        assert cli.main(["build", str(source), "-o", str(out)]) == 0
        assert out.read_bytes()[:4] == b"\x00asm"

    def test_run_prints_the_programs_output(self, tmp_path, capsys):
        from toolchain import cli

        source = tmp_path / "p.zap"
        source.write_text("let i: int = 0; while i < 3 { print(i * 2); i = i + 1; }")
        assert cli.main(["run", str(source), "--compare"]) == 0
        out = capsys.readouterr().out
        assert "0" in out and "2" in out and "4" in out
        assert "agree" in out
