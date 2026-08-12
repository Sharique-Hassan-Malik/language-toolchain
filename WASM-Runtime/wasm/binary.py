"""
Low-level binary reader for the WebAssembly binary format.

Implements:
  - Unsigned LEB128 (variable-length 7-bit integer encoding)
  - Signed LEB128 (used for i32/i64 constants and some offsets)
  - Raw byte and fixed-width reads
  - UTF-8 string (length-prefixed)
  - f32 and f64 via struct
"""

from __future__ import annotations

import struct
from typing import Any


class BinaryReader:
    def __init__(self, data: bytes):
        self._data = data
        self._pos  = 0

    # ── position / slicing ─────────────────────────────────────────────────

    @property
    def pos(self) -> int:
        return self._pos

    @property
    def remaining(self) -> int:
        return len(self._data) - self._pos

    def eof(self) -> bool:
        return self._pos >= len(self._data)

    def peek(self) -> int:
        if self.eof():
            raise EOFError("peek past end of buffer")
        return self._data[self._pos]

    def slice(self, length: int) -> bytes:
        if self._pos + length > len(self._data):
            raise EOFError(f"slice({length}) at {self._pos} exceeds buffer length {len(self._data)}")
        view = self._data[self._pos : self._pos + length]
        self._pos += length
        return view

    def sub_reader(self, length: int) -> "BinaryReader":
        return BinaryReader(self.slice(length))

    # ── raw reads ──────────────────────────────────────────────────────────

    def read_byte(self) -> int:
        if self.eof():
            raise EOFError("read_byte past end")
        b = self._data[self._pos]
        self._pos += 1
        return b

    def read_u32_le(self) -> int:
        return struct.unpack_from("<I", self.slice(4))[0]

    def read_f32(self) -> float:
        return struct.unpack_from("<f", self.slice(4))[0]

    def read_f64(self) -> float:
        return struct.unpack_from("<d", self.slice(8))[0]

    # ── LEB128 ─────────────────────────────────────────────────────────────

    def read_u32(self) -> int:
        """Unsigned LEB128, capped at 32 bits."""
        return self._read_uleb128(max_bits=32)

    def read_u64(self) -> int:
        return self._read_uleb128(max_bits=64)

    def read_i32(self) -> int:
        """Signed LEB128, sign-extended to 32 bits."""
        return self._read_sleb128(bits=32)

    def read_i64(self) -> int:
        return self._read_sleb128(bits=64)

    def _read_uleb128(self, max_bits: int) -> int:
        result = 0
        shift  = 0
        while True:
            byte    = self.read_byte()
            result |= (byte & 0x7F) << shift
            shift  += 7
            if not (byte & 0x80):
                break
            if shift >= max_bits:
                raise ValueError(f"LEB128 overflow at {self._pos}")
        return result

    def _read_sleb128(self, bits: int) -> int:
        result = 0
        shift  = 0
        while True:
            byte    = self.read_byte()
            result |= (byte & 0x7F) << shift
            shift  += 7
            if not (byte & 0x80):
                break
            if shift >= bits:
                raise ValueError(f"Signed LEB128 overflow at {self._pos}")
        # Sign-extend
        if (byte & 0x40) and shift < bits:
            result |= -(1 << shift)
        return result

    # ── higher-level ────────────────────────────────────────────────────────

    def read_name(self) -> str:
        length = self.read_u32()
        return self.slice(length).decode("utf-8")

    def read_vec(self, reader_fn) -> list:
        count = self.read_u32()
        return [reader_fn(self) for _ in range(count)]
