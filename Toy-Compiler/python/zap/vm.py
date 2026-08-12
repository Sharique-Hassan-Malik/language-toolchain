"""Stack-based virtual machine for Zap bytecode."""

from __future__ import annotations
from dataclasses import dataclass, field
from .codegen import Op, Instr, FnChunk, CompiledProgram

Value = int | bool


@dataclass
class Frame:
    chunk:  FnChunk
    ip:     int            = 0
    locals: dict[str, Value] = field(default_factory=dict)
    stack:  list[Value]      = field(default_factory=list)


class ZapRuntimeError(Exception):
    pass


class VM:
    def __init__(
        self,
        program: CompiledProgram,
        output: list[str] | None = None,
    ) -> None:
        self._prog   = program
        self._output = output if output is not None else []
        self._frames: list[Frame] = []

    def run(self, entry: str | None = None) -> None:
        ep = entry or self._prog.entry
        if ep not in self._prog.functions:
            raise ZapRuntimeError(f"Entry point '{ep}' not found")
        self._push_frame(ep, [])
        self._execute()

    def _push_frame(self, fn: str, args: list[Value]) -> None:
        chunk = self._prog.functions[fn]
        frame = Frame(chunk=chunk)
        for name, val in zip(chunk.params, args):
            frame.locals[name] = val
        self._frames.append(frame)

    def _execute(self) -> None:
        while self._frames:
            frame = self._frames[-1]
            if frame.ip >= len(frame.chunk.code):
                self._frames.pop()
                continue
            instr = frame.chunk.code[frame.ip]
            frame.ip += 1
            if self._step(frame, instr):
                return

    def _step(self, frame: Frame, ins: Instr) -> bool:
        op  = ins.op
        stk = frame.stack

        match op:
            case Op.PUSH_INT:  stk.append(int(ins.arg))
            case Op.PUSH_BOOL: stk.append(bool(ins.arg))
            case Op.LOAD:
                v = frame.locals.get(ins.arg)
                if v is None:
                    raise ZapRuntimeError(f"Undefined variable '{ins.arg}'")
                stk.append(v)
            case Op.STORE:
                frame.locals[ins.arg] = stk.pop()

            case Op.ADD:  b, a = stk.pop(), stk.pop(); stk.append(a + b)
            case Op.SUB:  b, a = stk.pop(), stk.pop(); stk.append(a - b)
            case Op.MUL:  b, a = stk.pop(), stk.pop(); stk.append(a * b)
            case Op.DIV:
                b, a = stk.pop(), stk.pop()
                if b == 0: raise ZapRuntimeError("Division by zero")
                stk.append(a // b)
            case Op.NEG: stk.append(-stk.pop())

            case Op.EQ:  b, a = stk.pop(), stk.pop(); stk.append(a == b)
            case Op.NEQ: b, a = stk.pop(), stk.pop(); stk.append(a != b)
            case Op.LT:  b, a = stk.pop(), stk.pop(); stk.append(a < b)
            case Op.GT:  b, a = stk.pop(), stk.pop(); stk.append(a > b)
            case Op.LEQ: b, a = stk.pop(), stk.pop(); stk.append(a <= b)
            case Op.GEQ: b, a = stk.pop(), stk.pop(); stk.append(a >= b)

            case Op.AND: b, a = stk.pop(), stk.pop(); stk.append(bool(a) and bool(b))
            case Op.OR:  b, a = stk.pop(), stk.pop(); stk.append(bool(a) or  bool(b))
            case Op.NOT: stk.append(not bool(stk.pop()))

            case Op.JMP:       frame.ip += int(ins.arg)
            case Op.JMP_FALSE:
                if not bool(stk.pop()): frame.ip += int(ins.arg)

            case Op.CALL:
                args = list(reversed([stk.pop() for _ in range(ins.arg2)]))
                self._push_frame(ins.arg, args)

            case Op.RET:
                ret_val = stk.pop() if stk else False
                self._frames.pop()
                if self._frames:
                    self._frames[-1].stack.append(ret_val)

            case Op.PRINT:
                val = stk.pop()
                s = "true" if val is True else ("false" if val is False else str(int(val)))
                self._output.append(s)
                print(s)

            case Op.POP:
                if stk: stk.pop()

            case Op.HALT:
                self._frames.clear()
                return True

        return False


def run(program: CompiledProgram, entry: str | None = None) -> list[str]:
    output: list[str] = []
    VM(program, output).run(entry)
    return output
