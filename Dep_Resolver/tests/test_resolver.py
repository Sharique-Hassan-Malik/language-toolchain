"""
Test suite for the dependency resolver.

All tests run offline — no network calls.

Run with:
    python -m pytest tests/test_resolver.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from resolver.version import (
    Version, Constraint, Requirement, PackageVersion, PackageIndex, _normalise_name,
)
from resolver.cdcl import CDCLSolver, SolverResult, _luby
from resolver.sat_encoder import SATEncoder
from resolver.resolver import DependencyResolver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pv(name: str, version: str, deps: list[str] | None = None) -> PackageVersion:
    return PackageVersion(
        name=name,
        version=Version(version),
        dependencies=[Requirement.parse(d) for d in (deps or [])],
    )


def _index(*pkgs: PackageVersion) -> PackageIndex:
    idx = PackageIndex()
    for p in pkgs:
        idx.add(p)
    return idx


# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

class TestVersion:

    def test_simple_ordering(self):
        assert Version("1.0.0") < Version("2.0.0")
        assert Version("1.9")   < Version("1.10")
        assert Version("2.0")   > Version("1.99")

    def test_equality(self):
        assert Version("1.2.3") == Version("1.2.3")
        assert Version("1.0")   != Version("1.0.1")

    def test_patch_ordering(self):
        assert Version("1.0.0") < Version("1.0.1")
        assert Version("1.0.9") < Version("1.0.10")

    def test_pre_release_ordering(self):
        assert Version("1.0a1") < Version("1.0b1")
        assert Version("1.0b1") < Version("1.0rc1")
        assert Version("1.0rc1") < Version("1.0")

    def test_epoch(self):
        assert Version("1!1.0") > Version("9.9.9")

    def test_hashable(self):
        s = {Version("1.0"), Version("1.0")}
        assert len(s) == 1

    def test_sortable(self):
        versions = [Version("1.2"), Version("0.9"), Version("1.10"), Version("1.3")]
        assert sorted(versions) == [
            Version("0.9"), Version("1.2"), Version("1.3"), Version("1.10")
        ]

    def test_str(self):
        assert str(Version("1.2.3")) == "1.2.3"


# ---------------------------------------------------------------------------
# Constraint
# ---------------------------------------------------------------------------

class TestConstraint:

    def test_ge(self):
        c = Constraint.parse(">=2.0")
        assert c.satisfied_by(Version("2.0"))
        assert c.satisfied_by(Version("3.0"))
        assert not c.satisfied_by(Version("1.9"))

    def test_gt(self):
        c = Constraint.parse(">2.0")
        assert c.satisfied_by(Version("2.1"))
        assert not c.satisfied_by(Version("2.0"))

    def test_le(self):
        c = Constraint.parse("<=2.0")
        assert c.satisfied_by(Version("2.0"))
        assert not c.satisfied_by(Version("2.1"))

    def test_lt(self):
        c = Constraint.parse("<2.0")
        assert c.satisfied_by(Version("1.9"))
        assert not c.satisfied_by(Version("2.0"))

    def test_eq(self):
        c = Constraint.parse("==1.2.3")
        assert c.satisfied_by(Version("1.2.3"))
        assert not c.satisfied_by(Version("1.2.4"))

    def test_ne(self):
        c = Constraint.parse("!=1.2.3")
        assert c.satisfied_by(Version("1.2.4"))
        assert not c.satisfied_by(Version("1.2.3"))

    def test_compatible(self):
        c = Constraint.parse("~=2.3")
        assert c.satisfied_by(Version("2.3"))
        assert c.satisfied_by(Version("2.4"))
        assert not c.satisfied_by(Version("3.0"))
        assert not c.satisfied_by(Version("2.2"))

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            Constraint.parse("??1.0")


# ---------------------------------------------------------------------------
# Requirement
# ---------------------------------------------------------------------------

class TestRequirement:

    def test_parse_simple(self):
        r = Requirement.parse("requests")
        assert r.name == "requests"
        assert len(r.constraints) == 0

    def test_parse_with_constraint(self):
        r = Requirement.parse("requests>=2.0")
        assert r.name == "requests"
        assert len(r.constraints) == 1

    def test_parse_multiple_constraints(self):
        r = Requirement.parse("requests>=2.0,<3.0")
        assert len(r.constraints) == 2

    def test_parse_extras(self):
        r = Requirement.parse("requests[security]>=2.0")
        assert r.name == "requests"
        assert "security" in r.extras

    def test_name_normalisation(self):
        r = Requirement.parse("My_Package")
        assert r.name == "my-package"

    def test_allows(self):
        r = Requirement.parse("requests>=2.0,<3.0")
        assert r.allows(Version("2.5.0"))
        assert not r.allows(Version("3.0.0"))
        assert not r.allows(Version("1.9.9"))

    def test_str(self):
        r = Requirement.parse("requests>=2.0")
        assert "requests" in str(r)
        assert "2.0" in str(r)


# ---------------------------------------------------------------------------
# PackageIndex
# ---------------------------------------------------------------------------

class TestPackageIndex:

    def test_add_and_retrieve(self):
        idx = _index(_pv("requests", "2.28.0"), _pv("requests", "2.27.0"))
        vers = idx.versions("requests")
        assert len(vers) == 2

    def test_newest_first(self):
        idx = _index(_pv("pkg", "1.0"), _pv("pkg", "2.0"), _pv("pkg", "1.5"))
        vers = idx.versions("pkg")
        assert str(vers[0].version) == "2.0"

    def test_candidates_filters(self):
        idx = _index(_pv("pkg", "1.0"), _pv("pkg", "2.0"), _pv("pkg", "3.0"))
        req = Requirement.parse("pkg>=1.5,<3.0")
        cands = idx.candidates(req)
        assert len(cands) == 1
        assert str(cands[0].version) == "2.0"

    def test_has(self):
        idx = _index(_pv("requests", "2.0"))
        assert idx.has("requests")
        assert not idx.has("flask")

    def test_normalised_lookup(self):
        idx = _index(_pv("My_Package", "1.0"))
        assert idx.has("my-package")
        assert idx.has("My_Package")


# ---------------------------------------------------------------------------
# CDCL SAT solver
# ---------------------------------------------------------------------------

class TestCDCL:

    def test_trivial_sat(self):
        # Single variable, must be true
        solver = CDCLSolver(1, [[1]])
        result, asgn = solver.solve()
        assert result == SolverResult.SAT
        assert asgn[1] is True

    def test_trivial_unsat(self):
        # x AND NOT x
        solver = CDCLSolver(1, [[1], [-1]])
        result, _ = solver.solve()
        assert result == SolverResult.UNSAT

    def test_empty_clause_is_unsat(self):
        solver = CDCLSolver(1, [[]])
        result, _ = solver.solve()
        assert result == SolverResult.UNSAT

    def test_two_variable_sat(self):
        # x1 OR x2
        solver = CDCLSolver(2, [[1, 2]])
        result, asgn = solver.solve()
        assert result == SolverResult.SAT
        assert asgn.get(1, False) or asgn.get(2, False)

    def test_unit_propagation(self):
        # x1, NOT x1 OR x2  →  x2 must be True
        solver = CDCLSolver(2, [[1], [-1, 2]])
        result, asgn = solver.solve()
        assert result == SolverResult.SAT
        assert asgn[2] is True

    def test_3sat_satisfiable(self):
        # Classic 3-SAT: (x1 OR x2 OR x3) AND (NOT x1 OR x2) AND (NOT x2 OR x3)
        solver = CDCLSolver(3, [[1, 2, 3], [-1, 2], [-2, 3]])
        result, asgn = solver.solve()
        assert result == SolverResult.SAT

    def test_conflict_and_backtrack(self):
        # Forces a conflict at depth > 1
        # x1 → x2, x1 → NOT x2, x1 must be chosen → UNSAT
        clauses = [
            [1],          # x1 = True
            [-1, 2],      # x1 → x2
            [-1, -2],     # x1 → NOT x2
        ]
        solver = CDCLSolver(2, clauses)
        result, _ = solver.solve()
        assert result == SolverResult.UNSAT

    def test_amo_constraint(self):
        # At-most-one of x1, x2, x3; plus x1 OR x2 OR x3
        # Should be SAT with exactly one variable True
        clauses = [
            [1, 2, 3],
            [-1, -2], [-1, -3], [-2, -3],
        ]
        solver = CDCLSolver(3, clauses)
        result, asgn = solver.solve()
        assert result == SolverResult.SAT
        assert sum(asgn.get(v, False) for v in [1, 2, 3]) == 1

    def test_luby_sequence(self):
        assert _luby(1) == 1
        assert _luby(2) == 1
        assert _luby(3) == 2
        assert _luby(4) == 1
        assert _luby(7) == 4


# ---------------------------------------------------------------------------
# DependencyResolver
# ---------------------------------------------------------------------------

class TestDependencyResolver:

    def test_simple_resolution(self):
        idx = _index(
            _pv("requests", "2.28.0", ["urllib3>=1.21"]),
            _pv("urllib3", "1.26.0"),
        )
        result = DependencyResolver(idx).resolve([Requirement.parse("requests>=2.0")])
        assert result.success
        names = {p.name for p in result.packages}
        assert "requests" in names
        assert "urllib3" in names

    def test_picks_compatible_version(self):
        idx = _index(
            _pv("pkg", "3.0"), _pv("pkg", "2.0"), _pv("pkg", "1.0")
        )
        result = DependencyResolver(idx).resolve([Requirement.parse("pkg>=1.5,<3.0")])
        assert result.success
        assert any(p.version == "2.0" for p in result.packages)

    def test_no_matching_version(self):
        idx = _index(_pv("pkg", "1.0"))
        result = DependencyResolver(idx).resolve([Requirement.parse("pkg>=2.0")])
        assert not result.success

    def test_missing_package(self):
        idx = PackageIndex()
        result = DependencyResolver(idx).resolve([Requirement.parse("nonexistent")])
        assert not result.success

    def test_transitive_deps(self):
        idx = _index(
            _pv("a", "1.0", ["b>=1.0"]),
            _pv("b", "1.0", ["c>=1.0"]),
            _pv("c", "1.0"),
        )
        result = DependencyResolver(idx).resolve([Requirement.parse("a")])
        assert result.success
        names = {p.name for p in result.packages}
        assert names == {"a", "b", "c"}

    def test_version_conflict(self):
        # req1 needs pkg>=2.0, req2 needs pkg<2.0 — no valid pkg version
        idx = _index(
            _pv("req1", "1.0", ["pkg>=2.0"]),
            _pv("req2", "1.0", ["pkg<2.0"]),
            _pv("pkg", "1.9"),
            _pv("pkg", "2.1"),
        )
        result = DependencyResolver(idx).resolve([
            Requirement.parse("req1"), Requirement.parse("req2"),
        ])
        assert not result.success

    def test_diamond_dependency(self):
        # A → B, A → C, B → D>=1.0, C → D>=1.5
        idx = _index(
            _pv("a", "1.0", ["b", "c"]),
            _pv("b", "1.0", ["d>=1.0"]),
            _pv("c", "1.0", ["d>=1.5"]),
            _pv("d", "2.0"), _pv("d", "1.5"), _pv("d", "1.0"),
        )
        result = DependencyResolver(idx).resolve([Requirement.parse("a")])
        assert result.success
        d_pkg = next(p for p in result.packages if p.name == "d")
        assert Version(d_pkg.version) >= Version("1.5")

    def test_install_set(self):
        idx = _index(_pv("requests", "2.28.0", ["urllib3>=1.0"]), _pv("urllib3", "1.26.0"))
        result = DependencyResolver(idx).resolve([Requirement.parse("requests")])
        assert result.success
        iset = result.install_set()
        assert "requests" in iset
        assert "urllib3" in iset

    def test_backtracking_solver_simple(self):
        idx = _index(_pv("pkg", "1.0"), _pv("pkg", "2.0"))
        result = DependencyResolver(idx).resolve_backtracking(
            [Requirement.parse("pkg>=1.5")]
        )
        assert result.success
        assert any(p.version == "2.0" for p in result.packages)

    def test_backtracking_solver_unsat(self):
        idx = _index(_pv("pkg", "1.0"))
        result = DependencyResolver(idx).resolve_backtracking(
            [Requirement.parse("pkg>=2.0")]
        )
        assert not result.success

    def test_multiple_root_requirements(self):
        idx = _index(
            _pv("flask", "3.0.0", ["werkzeug>=2.3"]),
            _pv("werkzeug", "3.0.0"),
            _pv("requests", "2.28.0"),
        )
        result = DependencyResolver(idx).resolve([
            Requirement.parse("flask>=3.0"),
            Requirement.parse("requests>=2.0"),
        ])
        assert result.success
        names = {p.name for p in result.packages}
        assert "flask" in names
        assert "requests" in names
        assert "werkzeug" in names

    def test_result_str(self):
        idx = _index(_pv("pkg", "1.0"))
        result = DependencyResolver(idx).resolve([Requirement.parse("pkg")])
        assert "pkg" in str(result)

    def test_normalise_name(self):
        assert _normalise_name("My_Package") == "my-package"
        assert _normalise_name("my.package") == "my-package"
        assert _normalise_name("my--package") == "my-package"
