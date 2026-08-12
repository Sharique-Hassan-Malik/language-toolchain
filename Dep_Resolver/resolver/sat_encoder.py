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
        """
        clauses: list[list[int]] = []
        seen_packages: set[str] = set()

        # BFS over the dependency graph to build all variables and clauses
        queue: list[Requirement] = list(root_requirements)
        visited_reqs: set[str] = set()

        while queue:
            req = queue.pop()
            norm = _normalise_name(req.name)
            if norm in visited_reqs:
                continue
            visited_reqs.add(norm)

            candidates = self._index.candidates(req)

            if not candidates:
                # No versions satisfy this requirement — immediate UNSAT
                # Encode as an empty clause (contradiction)
                clauses.append([])
                continue

            # Create variables for all candidate versions
            for pkg in candidates:
                self.var(pkg.name, pkg.version)

            # Recurse into dependencies
            for pkg in candidates:
                for dep in pkg.dependencies:
                    dep_norm = _normalise_name(dep.name)
                    if dep_norm not in visited_reqs:
                        queue.append(dep)

        # Now generate clauses for all packages we know about
        all_pkg_names: set[str] = {v.name for v in self._vars.values()}

        for pkg_name in all_pkg_names:
            all_versions = self._index.versions(pkg_name)
            pkg_vars = [
                self.var(pkg_name, p.version)
                for p in all_versions
                if (_normalise_name(pkg_name), str(p.version)) in {
                    k for k in self._vars
                }
            ]
            if not pkg_vars:
                continue

            # AMO: not (v_i and v_j) for all i < j
            for i in range(len(pkg_vars)):
                for j in range(i + 1, len(pkg_vars)):
                    clauses.append([-pkg_vars[i].var_id, -pkg_vars[j].var_id])

            # Dependency implications: if pkg@v is selected, its deps must be satisfied
            for pv in self._index.versions(pkg_name):
                key = (_normalise_name(pkg_name), str(pv.version))
                if key not in self._vars:
                    continue
                v = self._vars[key]
                for dep in pv.dependencies:
                    dep_cands = self._index.candidates(dep)
                    if not dep_cands:
                        # This version is impossible — forbid it
                        clauses.append([-v.var_id])
                        continue
                    # v → (dep_v1 OR dep_v2 OR ...)
                    dep_lits = [self.var(d.name, d.version).var_id for d in dep_cands]
                    clauses.append([-v.var_id] + dep_lits)

        # ALO for root requirements: at least one satisfying version must be chosen
        for req in root_requirements:
            candidates = self._index.candidates(req)
            if not candidates:
                clauses.append([])   # contradiction
                continue
            lits = [self.var(c.name, c.version).var_id for c in candidates]
            clauses.append(lits)

        return clauses
