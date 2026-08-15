"""A WebAssembly backend for Zap: AST → a real `.wasm` binary.

The existing backend targets Zap's own stack VM, which is a fine place to stop
if the VM is the destination. It is not: the WebAssembly runtime in this same
repository can execute a module, and until now there was nothing to hand it
except fixtures.

Emitting from the **AST**, not from the VM bytecode, is the whole design
decision. Zap's bytecode is flat with signed jump offsets; WebAssembly has no
arbitrary jumps, only structured `block`/`loop`/`br`. Recovering structure from
offsets is a control-flow-graph problem, and the structure is right there in the
AST — `IfStmt` and `WhileStmt` map onto `if/else/end` and `block/loop/br_if`
almost directly.

Types: Zap's `int` and `bool` are both `i32`, with `bool` normalised to 0 or 1
because WebAssembly's comparisons produce exactly that and its `if` tests
non-zero.

`print` becomes an import — `env.print(i32) -> ()` — since a pure module has no
way to reach the outside. The runtime supplies it.

    from zap.wasm_backend import compile_to_wasm
    binary = compile_to_wasm(parse(source))
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .ast_nodes import (
    AssignExpr,
    BinOp,
    Block,
    BoolLit,
    CallExpr,
    ExprStmt,
    FnDecl,
    IdentExpr,
    IfStmt,
    IntLit,
    LetStmt,
    PrintStmt,
    Program,
    ReturnStmt,
    UnaryOp,
    WhileStmt,
)

MAGIC = b"\x00asm"
VERSION = b"\x01\x00\x00\x00"

I32 = 0x7F
FUNC_TYPE = 0x60
EMPTY_BLOCK = 0x40           # a block that produces no value

ENTRY = "__main__"
PRINT_MODULE = "env"
PRINT_NAME = "print"


class WasmBackendError(Exception):
    """Something in the program has no WebAssembly translation."""


# ---------------------------------------------------------------------------
# LEB128
# ---------------------------------------------------------------------------

def uleb(value: int) -> bytes:
    """Unsigned LEB128 — every length and index in the format uses it."""
    if value < 0:
        raise ValueError(f"uleb of negative {value}")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def sleb(value: int) -> bytes:
    """Signed LEB128 — i32 constants and block types."""
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        done = (value == 0 and not byte & 0x40) or (value == -1 and byte & 0x40)
        out.append(byte if done else byte | 0x80)
        if done:
            return bytes(out)


def _vec(items: list[bytes]) -> bytes:
    """A WebAssembly vector: count, then the elements."""
    return uleb(len(items)) + b"".join(items)


def _section(section_id: int, payload: bytes) -> bytes:
    return bytes([section_id]) + uleb(len(payload)) + payload


def _name(text: str) -> bytes:
    encoded = text.encode("utf-8")
    return uleb(len(encoded)) + encoded


# ---------------------------------------------------------------------------
# Instructions used
# ---------------------------------------------------------------------------

OP = {
    "unreachable": 0x00, "block": 0x02, "loop": 0x03, "if": 0x04, "else": 0x05,
    "end": 0x0B, "br": 0x0C, "br_if": 0x0D, "return": 0x0F, "call": 0x10,
    "drop": 0x1A,
    "local.get": 0x20, "local.set": 0x21, "local.tee": 0x22,
    "i32.const": 0x41,
    "i32.eqz": 0x45, "i32.eq": 0x46, "i32.ne": 0x47,
    "i32.lt_s": 0x48, "i32.gt_s": 0x4A, "i32.le_s": 0x4C, "i32.ge_s": 0x4E,
    "i32.add": 0x6A, "i32.sub": 0x6B, "i32.mul": 0x6C, "i32.div_s": 0x6D,
    "i32.and": 0x71, "i32.or": 0x72,
}

_BINARY = {
    "+": "i32.add", "-": "i32.sub", "*": "i32.mul", "/": "i32.div_s",
    "==": "i32.eq", "!=": "i32.ne",
    "<": "i32.lt_s", ">": "i32.gt_s", "<=": "i32.le_s", ">=": "i32.ge_s",
    "&&": "i32.and", "||": "i32.or",
}


@dataclass
class _Fn:
    """One function being emitted."""

    name: str
    params: list[str]
    returns_value: bool
    locals: dict[str, int] = field(default_factory=dict)
    body: bytearray = field(default_factory=bytearray)

    def local_index(self, name: str) -> int:
        try:
            return self.locals[name]
        except KeyError:
            raise WasmBackendError(f"unknown variable {name!r} in {self.name}") from None

    def declare(self, name: str) -> int:
        if name not in self.locals:
            self.locals[name] = len(self.locals)
        return self.locals[name]

    @property
    def extra_locals(self) -> int:
        """Locals beyond the parameters, which WebAssembly declares separately."""
        return len(self.locals) - len(self.params)


class WasmEmitter:
    """AST in, module bytes out."""

    def __init__(self, program: Program) -> None:
        self.program = program
        self.functions: list[_Fn] = []
        # Index 0 is the imported print; the module's own functions follow.
        self.func_index: dict[str, int] = {PRINT_NAME: 0}
        self.signatures: dict[str, tuple[int, bool]] = {}

    # -- entry point ---------------------------------------------------------

    def emit(self) -> bytes:
        declarations = [d for d in self.program.decls if isinstance(d, FnDecl)]
        top_level = [d for d in self.program.decls if not isinstance(d, FnDecl)]

        for offset, decl in enumerate(declarations, start=1):
            self.func_index[decl.name] = offset
            self.signatures[decl.name] = (len(decl.params), decl.return_type != "void")
        self.func_index[ENTRY] = len(declarations) + 1
        self.signatures[ENTRY] = (0, False)

        for decl in declarations:
            self.functions.append(self._emit_function(decl))
        self.functions.append(self._emit_entry(top_level))

        return self._assemble()

    # -- functions -----------------------------------------------------------

    def _emit_function(self, decl: FnDecl) -> _Fn:
        fn = _Fn(
            name=decl.name,
            params=[name for name, _ in decl.params],
            returns_value=decl.return_type != "void",
        )
        for name, _ in decl.params:
            fn.declare(name)
        self._block(fn, decl.body)

        # A function whose last statement is not `return` still has to leave a
        # value on the stack for the validator. `unreachable` says the path
        # cannot be taken rather than inventing a zero.
        if fn.returns_value and not fn.body.endswith(bytes([OP["return"]])):
            fn.body.append(OP["unreachable"])
        fn.body.append(OP["end"])
        return fn

    def _emit_entry(self, statements: list) -> _Fn:
        fn = _Fn(name=ENTRY, params=[], returns_value=False)
        for statement in statements:
            self._statement(fn, statement)
        fn.body.append(OP["end"])
        return fn

    # -- statements ----------------------------------------------------------

    def _block(self, fn: _Fn, block: Block) -> None:
        for statement in block.stmts:
            self._statement(fn, statement)

    def _statement(self, fn: _Fn, node) -> None:
        if isinstance(node, LetStmt):
            self._expr(fn, node.value)
            fn.body.append(OP["local.set"])
            fn.body += uleb(fn.declare(node.name))

        elif isinstance(node, ReturnStmt):
            if node.value is not None:
                self._expr(fn, node.value)
            fn.body.append(OP["return"])

        elif isinstance(node, PrintStmt):
            self._expr(fn, node.value)
            fn.body.append(OP["call"])
            fn.body += uleb(self.func_index[PRINT_NAME])

        elif isinstance(node, IfStmt):
            self._expr(fn, node.cond)
            fn.body.append(OP["if"])
            fn.body.append(EMPTY_BLOCK)
            self._block(fn, node.then_block)
            if node.else_block is not None:
                fn.body.append(OP["else"])
                self._block(fn, node.else_block)
            fn.body.append(OP["end"])

        elif isinstance(node, WhileStmt):
            # block { loop { cond; eqz; br_if 1(exit); body; br 0(again) } }
            # The outer block is the branch target for leaving the loop; WebAssembly
            # branches only outwards, so the exit has to be a label already open.
            fn.body.append(OP["block"])
            fn.body.append(EMPTY_BLOCK)
            fn.body.append(OP["loop"])
            fn.body.append(EMPTY_BLOCK)
            self._expr(fn, node.cond)
            fn.body.append(OP["i32.eqz"])
            fn.body.append(OP["br_if"])
            fn.body += uleb(1)
            self._block(fn, node.body)
            fn.body.append(OP["br"])
            fn.body += uleb(0)
            fn.body.append(OP["end"])
            fn.body.append(OP["end"])

        elif isinstance(node, ExprStmt):
            self._expr(fn, node.expr)
            if self._leaves_value(node.expr):
                fn.body.append(OP["drop"])

        else:
            raise WasmBackendError(f"no WebAssembly translation for {type(node).__name__}")

    # -- expressions ---------------------------------------------------------

    def _expr(self, fn: _Fn, node) -> None:
        if isinstance(node, IntLit):
            fn.body.append(OP["i32.const"])
            fn.body += sleb(node.value)

        elif isinstance(node, BoolLit):
            fn.body.append(OP["i32.const"])
            fn.body += sleb(1 if node.value else 0)

        elif isinstance(node, IdentExpr):
            fn.body.append(OP["local.get"])
            fn.body += uleb(fn.local_index(node.name))

        elif isinstance(node, BinOp):
            try:
                opcode = _BINARY[node.op]
            except KeyError:
                raise WasmBackendError(f"unsupported operator {node.op!r}") from None
            self._expr(fn, node.left)
            self._expr(fn, node.right)
            fn.body.append(OP[opcode])

        elif isinstance(node, UnaryOp):
            if node.op == "-":
                # No i32.neg exists; 0 - x is the idiom.
                fn.body.append(OP["i32.const"])
                fn.body += sleb(0)
                self._expr(fn, node.operand)
                fn.body.append(OP["i32.sub"])
            elif node.op == "!":
                self._expr(fn, node.operand)
                fn.body.append(OP["i32.eqz"])
            else:
                raise WasmBackendError(f"unsupported unary {node.op!r}")

        elif isinstance(node, CallExpr):
            for argument in node.args:
                self._expr(fn, argument)
            try:
                index = self.func_index[node.name]
            except KeyError:
                raise WasmBackendError(f"call to unknown function {node.name!r}") from None
            fn.body.append(OP["call"])
            fn.body += uleb(index)

        elif isinstance(node, AssignExpr):
            self._expr(fn, node.value)
            # `tee` stores and leaves the value, so assignment is an expression
            # here exactly as it is in Zap.
            fn.body.append(OP["local.tee"])
            fn.body += uleb(fn.declare(node.name))

        else:
            raise WasmBackendError(f"no WebAssembly translation for {type(node).__name__}")

    def _leaves_value(self, node) -> bool:
        if isinstance(node, CallExpr):
            params, returns = self.signatures.get(node.name, (0, True))
            return returns
        return True

    # -- module assembly -----------------------------------------------------

    def _assemble(self) -> bytes:
        # Type section: the print import, then one signature per function.
        types: list[bytes] = [
            bytes([FUNC_TYPE]) + _vec([bytes([I32])]) + _vec([])      # print(i32)
        ]
        type_index: dict[str, int] = {}
        for fn in self.functions:
            signature = (
                bytes([FUNC_TYPE])
                + _vec([bytes([I32])] * len(fn.params))
                + _vec([bytes([I32])] if fn.returns_value else [])
            )
            if signature in types:
                type_index[fn.name] = types.index(signature)
            else:
                type_index[fn.name] = len(types)
                types.append(signature)

        type_section = _section(1, _vec(types))

        import_section = _section(2, _vec([
            _name(PRINT_MODULE) + _name(PRINT_NAME) + bytes([0x00]) + uleb(0)
        ]))

        function_section = _section(3, _vec([uleb(type_index[fn.name]) for fn in self.functions]))

        export_section = _section(7, _vec([
            _name(fn.name) + bytes([0x00]) + uleb(self.func_index[fn.name])
            for fn in self.functions
        ]))

        bodies: list[bytes] = []
        for fn in self.functions:
            local_decls = _vec([uleb(fn.extra_locals) + bytes([I32])] if fn.extra_locals else [])
            body = local_decls + bytes(fn.body)
            bodies.append(uleb(len(body)) + body)
        code_section = _section(10, _vec(bodies))

        return (
            MAGIC + VERSION
            + type_section + import_section + function_section
            + export_section + code_section
        )


def compile_to_wasm(program: Program) -> bytes:
    """Compile a parsed Zap program to a WebAssembly module."""
    return WasmEmitter(program).emit()
