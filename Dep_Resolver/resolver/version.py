"""
Version and constraint model.

Versions follow PEP 440 (simplified — epoch, pre/post/dev releases are
supported in parsing but ordering uses the standard tuple comparison).

Constraint operators supported:
    ==  !=  <  <=  >  >=  ~=  (compatible release)
    ===  (arbitrary equality — treated as == for our purposes)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import total_ordering
from typing import Iterator


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(
    r"^v?(?:(\d+)!)?"                  # epoch
    r"(\d+(?:\.\d+)*)"                 # release
    r"(?:[-_\.]?(a|alpha|b|beta|rc|c|preview)[-_\.]?(\d+))?"  # pre
    r"(?:[-_\.]?(post|rev|r)[-_\.]?(\d+))?"                    # post
    r"(?:[-_\.]?(dev)[-_\.]?(\d+))?$"                          # dev
    , re.IGNORECASE
)

_PRE_ORDER = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "rc": 2, "c": 2, "preview": 2}


@total_ordering
class Version:
    """Comparable, hashable version number."""

    def __init__(self, version_str: str):
        self._raw = version_str.strip()
        self._key  = self._parse(self._raw)

    def _parse(self, s: str) -> tuple:
        m = _VERSION_RE.match(s)
        if not m:
            # Fall back to treating the string as a dot-separated int tuple
            parts = re.sub(r"[^0-9.]", "", s).split(".")
            return (0,) + tuple(int(p) for p in parts if p), (3, 0), 0, 0

        epoch   = int(m.group(1) or 0)
        release = tuple(int(x) for x in m.group(2).split("."))

        pre_label = m.group(3)
        pre_num   = int(m.group(4) or 0)
        pre = (_PRE_ORDER.get((pre_label or "").lower(), 3), pre_num) if pre_label else (3, 0)

        post = int(m.group(6) or 0) if m.group(5) else -1
        dev  = int(m.group(8) or 0) if m.group(7) else float("inf")

        return (epoch, release, pre, post, dev)

    def __str__(self) -> str:
        return self._raw

    def __repr__(self) -> str:
        return f"Version({self._raw!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Version):
            return self._key == other._key
        return NotImplemented

    def __lt__(self, other: "Version") -> bool:
        if isinstance(other, Version):
            # Compare tuples element by element, padding release tuples
            sk = self._normalised_key()
            ok = other._normalised_key()
            return sk < ok
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._key)

    def _normalised_key(self):
        epoch, release, pre, post, dev = self._key
        # Pad release to length 4 for comparison
        release = release + (0,) * max(0, 4 - len(release))
        return (epoch, release, pre, post, dev)


# ---------------------------------------------------------------------------
# Constraint
# ---------------------------------------------------------------------------

_OP_RE = re.compile(r"^(===|~=|==|!=|<=|>=|<|>)\s*(.+)$")


@dataclass(frozen=True)
class Constraint:
    """A single version constraint such as '>=1.0' or '~=2.3'."""
    operator: str
    version:  Version

    @classmethod
    def parse(cls, spec: str) -> "Constraint":
        m = _OP_RE.match(spec.strip())
        if not m:
            raise ValueError(f"Cannot parse constraint: {spec!r}")
        op, ver_str = m.group(1), m.group(2)
        return cls(operator=op, version=Version(ver_str))

    def satisfied_by(self, version: Version) -> bool:
        op, v = self.operator, self.version
        if op in ("==", "==="):
            # Wildcard: ==1.* matches any 1.x
            if self._raw_ver.endswith(".*"):
                prefix = self._raw_ver[:-2]
                return str(version).startswith(prefix)
            return version == v
        if op == "!=":
            if self._raw_ver.endswith(".*"):
                prefix = self._raw_ver[:-2]
                return not str(version).startswith(prefix)
            return version != v
        if op == "<":  return version < v
        if op == "<=": return version <= v
        if op == ">":  return version > v
        if op == ">=": return version >= v
        if op == "~=":
            # Compatible release: >=v, ==v.* (drop last component)
            parts = str(v).split(".")
            if len(parts) < 2:
                return version >= v
            prefix = ".".join(parts[:-1])
            return version >= v and str(version).startswith(prefix + ".")
        return False

    @property
    def _raw_ver(self) -> str:
        return str(self.version)

    def __str__(self) -> str:
        return f"{self.operator}{self.version}"


# ---------------------------------------------------------------------------
# Package requirement
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Requirement:
    """
    A parsed dependency requirement: package name + set of version constraints.
    e.g. "requests>=2.0,<3.0" → Requirement("requests", [>=2.0, <3.0])
    """
    name:        str
    constraints: tuple[Constraint, ...]
    extras:      tuple[str, ...] = ()

    @classmethod
    def parse(cls, spec: str) -> "Requirement":
        spec = spec.strip()
        # Extract extras: name[extra1,extra2]>=1.0
        extras: tuple[str, ...] = ()
        extra_m = re.match(r"^([A-Za-z0-9_.-]+)\[([^\]]+)\](.*)$", spec)
        if extra_m:
            name    = extra_m.group(1)
            extras  = tuple(e.strip() for e in extra_m.group(2).split(","))
            rest    = extra_m.group(3)
        else:
            m    = re.match(r"^([A-Za-z0-9_.-]+)(.*)", spec)
            if not m:
                raise ValueError(f"Cannot parse requirement: {spec!r}")
            name = m.group(1)
            rest = m.group(2)

        name = _normalise_name(name)
        constraints: list[Constraint] = []
        for part in rest.split(","):
            part = part.strip()
            if part:
                constraints.append(Constraint.parse(part))

        return cls(name=name, constraints=tuple(constraints), extras=extras)

    def allows(self, version: Version) -> bool:
        return all(c.satisfied_by(version) for c in self.constraints)

    def __str__(self) -> str:
        c = ",".join(str(c) for c in self.constraints)
        return f"{self.name}{c}"


# ---------------------------------------------------------------------------
# Package metadata
# ---------------------------------------------------------------------------

@dataclass
class PackageVersion:
    """One specific release of a package."""
    name:         str
    version:      Version
    dependencies: list[Requirement] = field(default_factory=list)

    def __str__(self) -> str:
        return f"{self.name}=={self.version}"


@dataclass
class PackageIndex:
    """
    In-memory index of available packages and their versions.
    Mirrors what pip would fetch from PyPI's simple API.
    """
    _packages: dict[str, list[PackageVersion]] = field(default_factory=dict)

    def add(self, pkg: PackageVersion):
        name = _normalise_name(pkg.name)
        self._packages.setdefault(name, []).append(pkg)

    def versions(self, name: str) -> list[PackageVersion]:
        """Return all known versions for a package, newest first."""
        pkgs = self._packages.get(_normalise_name(name), [])
        return sorted(pkgs, key=lambda p: p.version, reverse=True)

    def has(self, name: str) -> bool:
        return _normalise_name(name) in self._packages

    def candidates(self, req: Requirement) -> list[PackageVersion]:
        """Versions of req.name that satisfy req's constraints, newest first."""
        return [p for p in self.versions(req.name) if req.allows(p.version)]


def _normalise_name(name: str) -> str:
    """PEP 503 — lowercase and collapse runs of [-_.] to '-'."""
    return re.sub(r"[-_.]+", "-", name).lower()
