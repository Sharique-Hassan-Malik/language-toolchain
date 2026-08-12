# SAT-Based Python Dependency Resolver

A Python package dependency resolver that encodes the problem as a Boolean
satisfiability (SAT) instance and solves it with a CDCL (Conflict-Driven
Clause Learning) solver built from scratch — mirroring how pip's own resolver
works internally.

---

## Features

- PEP 440 version parsing and comparison (epochs, pre/post/dev releases)
- All constraint operators: `==`, `!=`, `<`, `<=`, `>`, `>=`, `~=`, `===`
- Package name normalisation (PEP 503)
- SAT encoding: AMO, ALO and dependency implication clauses
- CDCL solver with 1-UIP conflict analysis, VSIDS heuristic, Luby restarts
- Pure backtracking solver for comparison
- PyPI JSON API fetcher with disk caching
- Human-readable UNSAT explanations (which constraints conflict)
- Lock file generation
- 45+ offline pytest tests — no network required

---

## Requirements

Python 3.11+ — no runtime dependencies.

```bash
pip install pytest   # for running tests only
```

---

## Usage

### Resolve from CLI

```bash
# Offline (built-in fixture index)
python resolve.py requests>=2.28 flask>=3.0 --offline

# With live PyPI fetch
python resolve.py requests>=2.28 flask>=3.0

# From requirements.txt
python resolve.py -r requirements.txt
```

### Generate a lock file

```bash
python resolve.py requests flask --offline --lock requirements.lock
```

### JSON output

```bash
python resolve.py requests>=2.28 --offline --json | python -m json.tool
```

### Verbose output

```bash
python resolve.py requests>=2.28,<3.0 --offline --verbose
```

### Use pure backtracking solver

```bash
python resolve.py requests>=2.28 --offline --backtracking
```

---

## Example Output

```
Resolved:
  certifi==2023.7.22
  requests==2.28.0
  urllib3==1.26.14
```

On conflict:

```
Resolution failed: No solution exists.
  requests>=3.0: no versions satisfy constraint (available: 2.31.0, 2.28.0)
```

---

## Programmatic API

```python
from resolver.version import PackageIndex, PackageVersion, Version, Requirement
from resolver.resolver import DependencyResolver

index = PackageIndex()
index.add(PackageVersion("requests", Version("2.28.0"), dependencies=[
    Requirement.parse("urllib3>=1.21.1,<3"),
]))
index.add(PackageVersion("urllib3", Version("1.26.14")))

resolver = DependencyResolver(index)
result   = resolver.resolve([Requirement.parse("requests>=2.0")])

if result.success:
    for pkg in result.packages:
        print(pkg)   # requests==2.28.0 / urllib3==1.26.14
else:
    print(result.error)
```

---

## Running Tests

```bash
python -m pytest tests/ -v
```

---

## Architecture Summary

```
Requirement specs
       │
       ▼
PackageIndex (versions + deps)
       │
       ▼
SATEncoder
  AMO:  ¬v_i ∨ ¬v_j  (at most one version per package)
  ALO:  v_1 ∨ v_2 ∨ … (at least one version for roots)
  Dep:  ¬v_p ∨ v_d1 ∨ v_d2 ∨ …  (if p is chosen, dep satisfied)
       │
       ▼
CDCLSolver
  BCP → VSIDS decision → conflict analysis (1-UIP)
  → learned clause → backjump → Luby restart
       │
       ▼
ResolutionResult  {name: version}  OR  UNSAT + explanation
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full SAT encoding, CDCL
algorithm details and version model.

---

## Project Structure

```
dep_resolver/
├── resolve.py
├── resolver/
│   ├── version.py
│   ├── sat_encoder.py
│   ├── cdcl.py
│   ├── resolver.py
│   └── fetcher.py
├── tests/
│   └── test_resolver.py
└── scripts/
```
