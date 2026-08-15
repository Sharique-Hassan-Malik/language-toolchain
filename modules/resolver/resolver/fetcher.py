"""
PyPI package index fetcher.

Builds a PackageIndex by fetching metadata from the PyPI JSON API:
    https://pypi.org/pypi/<package>/json

The fetcher caches responses to disk (under cache_dir) to avoid redundant
network requests.  A simple in-memory cache prevents re-fetching packages
that have already been resolved in the current session.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from pathlib import Path

from resolver.version import (
    PackageIndex, PackageVersion, Requirement, Version, _normalise_name
)


class PyPIFetcher:
    """
    Fetches package metadata from PyPI and populates a PackageIndex.

    For each package, it fetches the top-level JSON which includes all
    available versions and their dependencies (via the 'requires_dist' field
    of each distribution's metadata).
    """

    PYPI_URL = "https://pypi.org/pypi/{name}/json"

    def __init__(self, cache_dir: str = ".pypi_cache", timeout: float = 10.0):
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._timeout   = timeout
        self._mem_cache: dict[str, dict] = {}

    def fetch(self, index: PackageIndex, names: list[str], max_versions: int = 20):
        """
        Fetch metadata for the given package names and their transitive
        dependencies, adding them all to index.

        max_versions: maximum number of versions to fetch per package
        (fetching newest first to keep the index small).
        """
        seen: set[str] = set()
        queue = [_normalise_name(n) for n in names]

        while queue:
            name = queue.pop(0)
            if name in seen or index.has(name):
                continue
            seen.add(name)

            data = self._get_json(name)
            if data is None:
                continue

            versions_data = data.get("releases", {})
            all_versions = sorted(
                versions_data.keys(),
                key=lambda v: _safe_version(v),
                reverse=True,
            )[:max_versions]

            for ver_str in all_versions:
                files = versions_data.get(ver_str, [])
                if not files:
                    continue
                # Prefer wheel metadata; fall back to sdist
                meta_file = next(
                    (f for f in files if f.get("packagetype") == "bdist_wheel"),
                    files[0],
                )
                requires_dist = meta_file.get("requires_dist") or []

                deps: list[Requirement] = []
                for req_str in requires_dist:
                    # Skip environment markers (e.g. "pytest; extra == 'test'")
                    if ";" in req_str:
                        continue
                    try:
                        deps.append(Requirement.parse(req_str))
                    except ValueError:
                        pass

                try:
                    pkg = PackageVersion(
                        name=_normalise_name(name),
                        version=Version(ver_str),
                        dependencies=deps,
                    )
                    index.add(pkg)
                except Exception:
                    pass

            # Queue dep names for fetching
            for pv in index.versions(name):
                for dep in pv.dependencies:
                    dep_name = _normalise_name(dep.name)
                    if dep_name not in seen:
                        queue.append(dep_name)

    # ── Internal ──────────────────────────────────────────────────────────

    def _get_json(self, name: str) -> dict | None:
        if name in self._mem_cache:
            return self._mem_cache[name]

        cache_file = self._cache_dir / f"{name}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
                self._mem_cache[name] = data
                return data
            except (json.JSONDecodeError, OSError):
                pass

        url = self.PYPI_URL.format(name=name)
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "dep-resolver/1.0 (github.com/example)"},
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode())
            cache_file.write_text(json.dumps(data))
            self._mem_cache[name] = data
            return data
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            return None


def _safe_version(ver_str: str) -> "Version":
    try:
        return Version(ver_str)
    except Exception:
        return Version("0")
