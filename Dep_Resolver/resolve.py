#!/usr/bin/env python3
"""
Python package dependency resolver.

Usage — resolve from inline requirements:
    python resolve.py requests>=2.28 flask>=2.0 "sqlalchemy!=1.4.*"

Usage — resolve from requirements.txt:
    python resolve.py -r requirements.txt

Usage — offline with a local fixture index:
    python resolve.py --offline requests>=2.0

Usage — show resolution details:
    python resolve.py requests>=2.28 --verbose
    python resolve.py requests>=2.28 --backtracking   # use simpler BT solver

Usage — generate a lock file:
    python resolve.py requests flask --lock requirements.lock
"""

import argparse
import json
import sys
from pathlib import Path

from resolver.version import PackageIndex, Requirement
from resolver.resolver import DependencyResolver


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="SAT-based Python dependency resolver",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("requirements", nargs="*",
                   help="Inline requirements (e.g. requests>=2.28 flask)")
    p.add_argument("-r", "--requirements-file", default=None, dest="req_file",
                   help="Read requirements from a file")
    p.add_argument("--offline",      action="store_true",
                   help="Use only built-in fixtures (no network)")
    p.add_argument("--backtracking", action="store_true",
                   help="Use pure backtracking solver instead of CDCL")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--lock",    default=None,
                   help="Write resolved versions to this lock file")
    p.add_argument("--json",    action="store_true",
                   help="Output result as JSON")
    p.add_argument("--max-versions", type=int, default=20, dest="max_versions",
                   help="Max versions per package to fetch (default: 20)")
    return p.parse_args()


def load_requirements(args: argparse.Namespace) -> list[Requirement]:
    specs: list[str] = list(args.requirements)
    if args.req_file:
        for line in Path(args.req_file).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                specs.append(line.split("#")[0].strip())
    if not specs:
        print("No requirements specified.", file=sys.stderr)
        sys.exit(1)
    return [Requirement.parse(s) for s in specs]


def build_index_offline(requirements: list[Requirement]) -> PackageIndex:
    """Return a small hand-crafted index for smoke-testing without network."""
    from resolver.version import PackageVersion, Version
    index = PackageIndex()
    # Minimal fixture: requests + urllib3 + certifi
    deps_r = [Requirement.parse("urllib3>=1.21.1,<3"), Requirement.parse("certifi>=2017.4.17")]
    for ver in ("2.31.0", "2.28.0", "2.20.0"):
        index.add(PackageVersion("requests", Version(ver), dependencies=deps_r))
    for ver in ("2.0.7", "1.26.14", "1.25.11"):
        index.add(PackageVersion("urllib3", Version(ver)))
    for ver in ("2023.7.22", "2022.12.7"):
        index.add(PackageVersion("certifi", Version(ver)))
    # flask + werkzeug + click + jinja2 + itsdangerous + markupsafe
    flask_deps = [
        Requirement.parse("Werkzeug>=2.3.3"),
        Requirement.parse("Jinja2>=3.1.2"),
        Requirement.parse("itsdangerous>=2.1.2"),
        Requirement.parse("click>=8.1.3"),
        Requirement.parse("blinker>=1.6.2"),
    ]
    index.add(PackageVersion("flask", Version("3.0.0"), dependencies=flask_deps))
    index.add(PackageVersion("flask", Version("2.3.3"), dependencies=flask_deps))
    for ver in ("3.0.1", "2.3.3"):
        index.add(PackageVersion("werkzeug", Version(ver)))
    for ver in ("3.1.2",):
        index.add(PackageVersion("jinja2", Version(ver),
                                 dependencies=[Requirement.parse("MarkupSafe>=2.0")]))
    for ver in ("2.1.3",):
        index.add(PackageVersion("itsdangerous", Version(ver)))
    for ver in ("8.1.7",):
        index.add(PackageVersion("click", Version(ver)))
    for ver in ("1.7.1",):
        index.add(PackageVersion("blinker", Version(ver)))
    for ver in ("2.1.3", "2.0.1"):
        index.add(PackageVersion("markupsafe", Version(ver)))
    return index


def main():
    args         = parse_args()
    requirements = load_requirements(args)

    if args.verbose:
        print("Requirements:")
        for r in requirements:
            print(f"  {r}")
        print()

    # Build the package index
    if args.offline:
        index = build_index_offline(requirements)
    else:
        from resolver.fetcher import PyPIFetcher
        index = PackageIndex()
        fetcher = PyPIFetcher()
        names = [r.name for r in requirements]
        print(f"Fetching metadata for: {', '.join(names)} ...")
        fetcher.fetch(index, names, max_versions=args.max_versions)

    # Resolve
    resolver = DependencyResolver(index)
    if args.backtracking:
        result = resolver.resolve_backtracking(requirements)
    else:
        result = resolver.resolve(requirements)

    # Output
    if args.json:
        out = {
            "success": result.success,
            "packages": [{"name": p.name, "version": p.version, "source": p.source}
                         for p in result.packages],
            "error": result.error,
            "conflicts": result.conflicts,
        }
        print(json.dumps(out, indent=2))
        sys.exit(0 if result.success else 1)

    if result.success:
        print(result)
        if args.verbose:
            print(f"\nTotal packages: {len(result.packages)}")
        if args.lock:
            lines = [f"{p.name}=={p.version}\n" for p in
                     sorted(result.packages, key=lambda x: x.name)]
            Path(args.lock).write_text("".join(lines))
            print(f"\nLock file written: {args.lock}")
    else:
        print(f"Resolution failed: {result.error}", file=sys.stderr)
        if result.conflicts:
            for c in result.conflicts:
                print(f"  {c}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
