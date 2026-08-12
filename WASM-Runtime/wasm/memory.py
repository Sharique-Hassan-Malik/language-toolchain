"""
WebAssembly linear memory.

Memory is addressed in bytes, allocated in 64 KiB pages. The spec allows
a maximum of 65536 pages (4 GiB). We cap the default maximum at 256 pages
(16 MiB) for practicality; callers can raise the limit.

load_* / store_* methods handle alignment, byte order (little-endian) and
sign extension per the spec.
"""

from __future__ import annotations

import struct


PAGE_SIZE     = 65536       # 64 KiB
MAX_PAGES     = 65536       # spec maximum
DEFAULT_MAX   = 256         # conservative default for the interpreter


class MemoryError(Exception):
    pass


class Memory:
    def __init__(self, min_pages: int = 0, max_pages: int | None = None):
        self._max   = max_pages if max_pages is not None else DEFAULT_MAX
        self._pages = 0
        self._data  = bytearray()
        if min_pages:
            self.grow(min_pages)

    # ── growth ──────────────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        """Current size in pages."""
        return self._pages

    @property
    def byte_size(self) -> int:
        return len(self._data)

    def grow(self, delta: int) -> int:
        """
        Attempt to grow by delta pages.
        Returns the previous size in pages, or -1 on failure.
        """
        prev = self._pages
        new  = prev + delta
        if new > self._max or new > MAX_PAGES:
            return -1
        self._data.extend(bytes(delta * PAGE_SIZE))
        self._pages = new
        return prev

    # ── address check ────────────────────────────────────────────────────────

    def _check(self, addr: int, size: int) -> None:
        if addr + size > len(self._data):
            raise MemoryError(
                f"out-of-bounds memory access at {addr:#010x}+{size} "
                f"(memory size {len(self._data)} bytes)"
            )

    # ── loads ────────────────────────────────────────────────────────────────

    def load_i32(self, addr: int, offset: int = 0) -> int:
        ea = addr + offset; self._check(ea, 4)
        v = struct.unpack_from("<I", self._data, ea)[0]
        return _i32(v)

    def load_i64(self, addr: int, offset: int = 0) -> int:
        ea = addr + offset; self._check(ea, 8)
        v = struct.unpack_from("<Q", self._data, ea)[0]
        return _i64(v)

    def load_f32(self, addr: int, offset: int = 0) -> float:
        ea = addr + offset; self._check(ea, 4)
        return struct.unpack_from("<f", self._data, ea)[0]

    def load_f64(self, addr: int, offset: int = 0) -> float:
        ea = addr + offset; self._check(ea, 8)
        return struct.unpack_from("<d", self._data, ea)[0]

    def load_i8_s(self, addr: int, offset: int = 0) -> int:
        ea = addr + offset; self._check(ea, 1)
        v = self._data[ea]
        return v - 256 if v >= 128 else v

    def load_i8_u(self, addr: int, offset: int = 0) -> int:
        ea = addr + offset; self._check(ea, 1)
        return self._data[ea]

    def load_i16_s(self, addr: int, offset: int = 0) -> int:
        ea = addr + offset; self._check(ea, 2)
        v = struct.unpack_from("<H", self._data, ea)[0]
        return v - 65536 if v >= 32768 else v

    def load_i16_u(self, addr: int, offset: int = 0) -> int:
        ea = addr + offset; self._check(ea, 2)
        return struct.unpack_from("<H", self._data, ea)[0]

    def load_i32_s(self, addr: int, offset: int = 0) -> int:
        ea = addr + offset; self._check(ea, 4)
        return struct.unpack_from("<i", self._data, ea)[0]

    def load_i32_u(self, addr: int, offset: int = 0) -> int:
        ea = addr + offset; self._check(ea, 4)
        return struct.unpack_from("<I", self._data, ea)[0]

    # ── stores ───────────────────────────────────────────────────────────────

    def store_i32(self, addr: int, value: int, offset: int = 0) -> None:
        ea = addr + offset; self._check(ea, 4)
        struct.pack_into("<I", self._data, ea, value & 0xFFFFFFFF)

    def store_i64(self, addr: int, value: int, offset: int = 0) -> None:
        ea = addr + offset; self._check(ea, 8)
        struct.pack_into("<Q", self._data, ea, value & 0xFFFFFFFFFFFFFFFF)

    def store_f32(self, addr: int, value: float, offset: int = 0) -> None:
        ea = addr + offset; self._check(ea, 4)
        struct.pack_into("<f", self._data, ea, value)

    def store_f64(self, addr: int, value: float, offset: int = 0) -> None:
        ea = addr + offset; self._check(ea, 8)
        struct.pack_into("<d", self._data, ea, value)

    def store_i8(self, addr: int, value: int, offset: int = 0) -> None:
        ea = addr + offset; self._check(ea, 1)
        self._data[ea] = value & 0xFF

    def store_i16(self, addr: int, value: int, offset: int = 0) -> None:
        ea = addr + offset; self._check(ea, 2)
        struct.pack_into("<H", self._data, ea, value & 0xFFFF)

    # ── raw access ────────────────────────────────────────────────────────────

    def read_bytes(self, addr: int, length: int) -> bytes:
        self._check(addr, length)
        return bytes(self._data[addr:addr + length])

    def write_bytes(self, addr: int, data: bytes) -> None:
        self._check(addr, len(data))
        self._data[addr:addr + len(data)] = data

    def fill(self, addr: int, value: int, length: int) -> None:
        self._check(addr, length)
        self._data[addr:addr + length] = bytes([value & 0xFF] * length)

    def copy(self, dst: int, src: int, length: int) -> None:
        self._check(src, length)
        self._check(dst, length)
        self._data[dst:dst + length] = self._data[src:src + length]


# ── Integer wrap/sign helpers ─────────────────────────────────────────────

def _i32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v


def _i64(v: int) -> int:
    v &= 0xFFFFFFFFFFFFFFFF
    return v - 0x10000000000000000 if v >= 0x8000000000000000 else v
