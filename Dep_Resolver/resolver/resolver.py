"""
High-level dependency resolver.

The resolver translates a set of root requirements + a package index into
either a complete installation set (every package at a specific version) or
a proof that no valid installation exists.

Two modes are supported:
    resolve()     — use the CDCL SAT solver (complete, finds UNSAT proof)
    resolve_bt()  — pure backtracking without clause learning (simpler, for comparison)
"""

from __future__ import annotations

from dataclasses import dataclass

from resolver.version import PackageIndex, PackageVersion, Requirement, _normalise_name
from resolver.sat_encoder import SATEncoder
from resolver.cdcl import CDCLSolver, SolverResult


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ResolvedPackage:
    name:    str
    version: str
    source:  str = "resolved"  # "required", "dependency"

    def __str__(self) -> str:
        return f"{self.name}=={self.version}"


@dataclass
class ResolutionResult:
    success:  bool
    packages: list[ResolvedPackage]
    error:    str = ""
    # Diagnostic: which conflicts were found
    conflicts: list[str] = None

    def __post_init__(self):
        if self.conflicts is None:
            self.conflicts = []

    def install_set(self) -> dict[str, str]:
        """Return {name: version} for all resolved packages."""
        return {p.name: p.version for p in self.packages}

    def __str__(self) -> str:
        if not self.success:
            return f"UNSAT: {self.error}"
        lines = [f"  {p}" for p in sorted(self.packages, key=lambda x: x.name)]
        return "Resolved:\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------

class DependencyResolver:
    """
    Resolves package dependencies using a CDCL SAT solver.

    Usage:
        index = PackageIndex()
        index.add(PackageVersion("requests", Version("2.28.0"), deps=[...]))
        ...
        resolver = DependencyResolver(index)
        result   = resolver.resolve([Requirement.parse("requests>=2.0")])
    """

    def __init__(self, index: PackageIndex):
        self._index = index

    def resolve(self, requirements: list[Requirement]) -> ResolutionResult:
        """
        Resolve requirements using the CDCL SAT solver.
        Returns a ResolutionResult with the complete installation set or
        an UNSAT explanation.
        """
        encoder = SATEncoder(self._index)
        clauses = encoder.encode(requirements)

        if any(len(c) == 0 for c in clauses):
            unsat_reqs = self._diagnose_unsat(requirements)
            return ResolutionResult(
                success=False,
                packages=[],
                error=f"No solution exists. Conflicting requirements: {unsat_reqs}",
                conflicts=unsat_reqs,
            )

        solver = CDCLSolver(encoder.num_vars(), clauses)
        result, assignment = solver.solve()

        if result == SolverResult.UNSAT:
            unsat_reqs = self._diagnose_unsat(requirements)
            return ResolutionResult(
                success=False,
                packages=[],
                error=f"No valid installation set exists. Conflicts: {unsat_reqs}",
                conflicts=unsat_reqs,
            )

        # Extract selected packages from the assignment
        packages = []
        root_names = {_normalise_name(r.name) for r in requirements}

        for var in encoder.all_variables():
            if assignment.get(var.var_id, False):
                source = "required" if var.name in root_names else "dependency"
                packages.append(ResolvedPackage(
                    name=var.name,
                    version=str(var.version),
                    source=source,
                ))

        return ResolutionResult(success=True, packages=packages)

    def resolve_backtracking(self, requirements: list[Requirement]) -> ResolutionResult:
        """
        Pure backtracking resolver without clause learning.
        Simpler but may be exponentially slower on hard instances.
        Useful for comparison and testing.
        """
        assignment: dict[str, str] = {}
        if self._bt(list(requirements), assignment, set()):
            packages = [
                ResolvedPackage(
                    name=name,
                    version=ver,
                    source="required" if any(
                        _normalise_name(r.name) == name for r in requirements
                    ) else "dependency",
                )
                for name, ver in assignment.items()
            ]
            return ResolutionResult(success=True, packages=packages)
        return ResolutionResult(
            success=False, packages=[],
            error="No valid installation set found (backtracking).",
        )

    # ── Internal ──────────────────────────────────────────────────────────

    def _bt(
        self,
        requirements: list[Requirement],
        assignment: dict[str, str],
        visited: set[str],
    ) -> bool:
        if not requirements:
            return True

        req = requirements[0]
        rest = requirements[1:]
        name = _normalise_name(req.name)

        # Already assigned — check compatibility
        if name in assignment:
            from resolver.version import Version
            if req.allows(Version(assignment[name])):
                return self._bt(rest, assignment, visited)
            return False

        # Try each candidate version (newest first)
        for pkg in self._index.candidates(req):
            ver_str = str(pkg.version)
            assignment[name] = ver_str
            new_reqs = rest + [
                d for d in pkg.dependencies
                if _normalise_name(d.name) not in visited
            ]
            new_visited = visited | {name}
            if self._bt(new_reqs, assignment, new_visited):
                return True
            del assignment[name]

        return False

    def _diagnose_unsat(self, requirements: list[Requirement]) -> list[str]:
        """Return human-readable strings describing why resolution failed."""
        issues = []
        for req in requirements:
            candidates = self._index.candidates(req)
            if not candidates:
                all_vers = self._index.versions(req.name)
                if not all_vers:
                    issues.append(f"{req.name}: package not found in index")
                else:
                    available = [str(p.version) for p in all_vers[:5]]
                    issues.append(
                        f"{req}: no versions satisfy constraint "
                        f"(available: {', '.join(available)})"
                    )
        return issues
