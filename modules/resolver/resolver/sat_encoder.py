"""
SAT encoding of package dependency resolution.

Each package version is assigned a boolean variable:
    var(name, version) → int (1-indexed, positive = installed, negative = not installed)

Clauses encode:
    1. At-most-one (AMO) — at most one version of each package can be installed.
    2. At-least-one (ALO) — if a package is required, at least one version must
       be chosen (but only for the root requirements).
    3. Dependency implication — if package P version V is chosen, then at
       least one version of each of P's dependencies must also be chosen.
    4. Conflict clause (CDCL) — learned clauses that rule out combinations
       of assignments that have been proven impossible.

Clause format: list of integers where a positive integer means the variable
must be True and a negative integer means it must be False.
A clause is satisfied if at least one of its literals is True.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from resolver.version import PackageIndex, PackageVersion, Requirement, Version, _normalise_name


@dataclass
class Variable:
    var_id:  int      # 1-indexed positive integer
    name:    str      # normalised package name
    version: Version


class SATEncoder:
    """
    Translates a package resolution problem into a set of CNF clauses.
    """

    def __init__(self, index: PackageIndex):
        self._index = index
        self._vars:  dict[tuple[str, str], Variable] = {}
        self._next_id = 1

    # ── Variable management ───────────────────────────────────────────────

    def var(self, name: str, version: Version) -> Variable:
        key = (_normalise_name(name), str(version))
        if key not in self._vars:
            v = Variable(var_id=self._next_id, name=_normalise_name(name), version=version)
            self._vars[key] = v
            self._next_id += 1
        return self._vars[key]

    def all_variables(self) -> list[Variable]:
        return list(self._vars.values())

    def num_vars(self) -> int:
        return self._next_id - 1

    # ── Clause generation ─────────────────────────────────────────────────

    def encode(self, root_requirements: list[Requirement]) -> list[list[int]]:
        """
        Build the full initial clause set for the given root requirements.

        Returns a list of clauses (each clause is a list of literal integers).

        Variables are created in a separate first pass. An AMO clause set is
        only correct if it ranges over *every* version of a package that the
        solver can select, so no clause may be emitted while variables are
        still appearing.
        """
        clauses: list[list[int]] = []

        # ── Pass 1: create every variable ────────────────────────────────
        #
        # Requirements are keyed by name *and* constraint. Two constraints on
        # the same package ("pkg>=2.0" and "pkg<2.0") select different
        # candidates, so collapsing them on the name alone drops one set of
        # versions from the encoding.
        queue: list[Requirement] = list(root_requirements)
        visited_reqs: set[tuple[str, str]] = set()

        while queue:
            req = queue.pop()
            key = (_normalise_name(req.name), str(req))
            if key in visited_reqs:
                continue
            visited_reqs.add(key)

            for pkg in self._index.candidates(req):
                self.var(pkg.name, pkg.version)
                for dep in pkg.dependencies:
                    if (_normalise_name(dep.name), str(dep)) not in visited_reqs:
                        queue.append(dep)

        # ── Pass 2: clauses ──────────────────────────────────────────────
        # Every variable now exists, so clause generation cannot create more.
        # Grouping and ordering are by variable id, which makes the output
        # identical from run to run regardless of hash seed.
        by_package: dict[str, list[Variable]] = {}
        for v in self._vars.values():
            by_package.setdefault(v.name, []).append(v)
        for pkg_vars in by_package.values():
            pkg_vars.sort(key=lambda v: v.var_id)

        for pkg_name in sorted(by_package):
            pkg_vars = by_package[pkg_name]

            # AMO: not (v_i and v_j) for all i < j
            for i in range(len(pkg_vars)):
                for j in range(i + 1, len(pkg_vars)):
                    clauses.append([-pkg_vars[i].var_id, -pkg_vars[j].var_id])

            # Dependency implications: if pkg@v is selected, its deps must hold
            for pv in self._index.versions(pkg_name):
                key = (_normalise_name(pkg_name), str(pv.version))
                if key not in self._vars:
                    continue
                v = self._vars[key]
                for dep in pv.dependencies:
                    dep_cands = self._index.candidates(dep)
                    dep_lits = [
                        self._vars[(_normalise_name(d.name), str(d.version))].var_id
                        for d in dep_cands
                        if (_normalise_name(d.name), str(d.version)) in self._vars
                    ]
                    if not dep_lits:
                        # Nothing can satisfy this dependency — forbid the version
                        clauses.append([-v.var_id])
                        continue
                    # v → (dep_v1 OR dep_v2 OR ...)
                    clauses.append([-v.var_id] + dep_lits)

        # ALO for root requirements: at least one satisfying version
        for req in root_requirements:
            lits = [
                self._vars[(_normalise_name(c.name), str(c.version))].var_id
                for c in self._index.candidates(req)
                if (_normalise_name(c.name), str(c.version)) in self._vars
            ]
            if not lits:
                clauses.append([])   # contradiction: nothing satisfies it
                continue
            clauses.append(lits)

        return clauses
