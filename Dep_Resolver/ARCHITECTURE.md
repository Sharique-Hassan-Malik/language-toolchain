# Architecture — SAT-Based Dependency Resolver

## Overview

A complete Python package dependency resolver that models the problem as a
Boolean satisfiability (SAT) instance and solves it with a CDCL (Conflict-
Driven Clause Learning) solver from scratch.  This mirrors what pip's own
resolver does internally.

---

## Why SAT?

Dependency resolution is NP-complete in the general case.  Framing it as
SAT allows the use of efficient CDCL solvers that in practice handle real
package ecosystems in milliseconds.  The key insight is:

- Each (package, version) pair becomes a boolean variable.
- Dependency constraints become implication clauses.
- At-most-one constraints enforce that only one version per package installs.
- The CDCL solver's conflict analysis produces minimal conflict sets that
  explain *why* a resolution failed.

---

## Pipeline

```
requirements.txt / CLI args
        │
        ▼
Requirement.parse()         PEP 440 version specs → Requirement objects
        │
        ▼
PyPIFetcher.fetch()         (optional) download package metadata from PyPI
        │                   with disk caching under .pypi_cache/
        ▼
PackageIndex                all available (name, version, deps) triples
        │
        ▼
SATEncoder.encode()         translate to CNF clauses:
        │                     • AMO per package (at most one version)
        │                     • ALO for root requirements (at least one version)
        │                     • Dep implications: pkg@v → (dep_v1 OR dep_v2 OR ...)
        │                     • Forbid versions whose deps are unsatisfiable
        ▼
CDCLSolver.solve()          find satisfying assignment or prove UNSAT
        │
        ▼
DependencyResolver          extract selected packages, format result
        │
        ▼
ResolutionResult            {name: version} install set  OR  UNSAT explanation
```

---

## CDCL Solver

The solver implements the standard CDCL algorithm:

### 1. Unit Propagation (BCP)

For every clause with exactly one unset literal and all other literals False,
that literal must be True.  This is applied repeatedly until no more
propagations are possible (fixpoint) or a conflict is detected.

### 2. VSIDS Decision Heuristic

Variables that appear most frequently in recently learned conflict clauses
are chosen next for branching.  Scores are bumped on each conflict and
decayed periodically with a factor of 0.95.

### 3. Conflict Analysis (1-UIP)

When all literals in a clause are False (conflict), the solver walks backwards
along the implication graph to find the "First Unique Implication Point" — the
most recent decision variable whose removal from the conflict clause makes it
a unit clause at the backjump level.  This produces the *minimal* learned clause.

### 4. Backjumping

Instead of chronological backtracking, the solver jumps back to the
second-highest decision level appearing in the learned clause.  This avoids
re-exploring the same failing subtrees.

### 5. Luby Restarts

The solver restarts from level 0 (while retaining learned clauses) following
the Luby sequence: 1, 1, 2, 1, 1, 2, 4, 1, 1, 2, 1, 1, 2, 4, 8, ...
multiplied by a unit factor of 512.  Restarts prevent the solver from spending
too long in an unproductive region of the search space.

---

## SAT Encoding

For a set of packages P with versions v_{p,1}, ..., v_{p,n}:

**Variables**: one boolean var_id per (package, version) pair.

**At-most-one (AMO)**:
```
NOT(v_{p,i}) OR NOT(v_{p,j})   for all i < j in package p
```

**At-least-one (ALO)** for root requirements:
```
v_{p,1} OR v_{p,2} OR ... OR v_{p,n}
```

**Dependency implication**:
```
NOT(v_{p,i}) OR v_{dep,1} OR v_{dep,2} OR ...
```
(If package p version i is selected, at least one version of its dependency
must also be selected.)

**Conflict detection during encoding**:
If a package version's dependency has no satisfying candidates, that version
is immediately forbidden:
```
NOT(v_{p,i})
```

---

## Version Model (PEP 440)

`Version` objects parse and compare version strings including:
- Release segments: `1.2.3`
- Pre-releases: `1.0a1`, `1.0b2`, `1.0rc1`
- Post-releases: `1.0.post1`
- Dev releases: `1.0.dev0`
- Epochs: `1!1.0`

Comparison uses a normalised 5-tuple:
```
(epoch, release_padded, pre, post, dev)
```

Constraint operators: `==`, `!=`, `<`, `<=`, `>`, `>=`, `~=`, `===`

Compatible release (`~=2.3`) expands to `>=2.3, ==2.*`.

---

## Files

```
dep_resolver/
├── resolve.py                  — CLI entry point
├── resolver/
│   ├── version.py              — Version, Constraint, Requirement, PackageIndex
│   ├── sat_encoder.py          — CNF clause generation from package metadata
│   ├── cdcl.py                 — CDCL SAT solver with VSIDS and Luby restarts
│   ├── resolver.py             — DependencyResolver, ResolutionResult
│   └── fetcher.py              — PyPI JSON API fetcher with disk caching
├── tests/
│   └── test_resolver.py        — 45+ offline tests
└── scripts/
    └── __init__.py
```
