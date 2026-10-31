#!/usr/bin/env python3
"""Keep server.json in step with the version in pyproject.toml.

pyproject.toml is the single source of truth (semantic-release bumps it).
This copies that version into every version field of server.json, including
the tag on each OCI image reference.

Usage:
    python scripts/sync_version.py                 # rewrite server.json
    python scripts/sync_version.py --check         # fail if anything is out of step
    python scripts/sync_version.py --check v1.3.0  # ...or differs from this tag
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
SERVER_JSON = ROOT / "server.json"


def project_version() -> str:
    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def server_versions(server: dict) -> dict[str, str]:
    """Every version recorded in server.json, keyed by where it lives."""
    found = {"server.json version": server["version"]}
    for pkg in server["packages"]:
        if pkg["registryType"] == "oci":
            found[pkg["identifier"]] = pkg["identifier"].rsplit(":", 1)[1]
        else:
            found[f'{pkg["registryType"]} {pkg["identifier"]}'] = pkg["version"]
    return found


def write(version: str) -> None:
    server = json.loads(SERVER_JSON.read_text())
    server["version"] = version
    for pkg in server["packages"]:
        if pkg["registryType"] == "oci":
            image = pkg["identifier"].rsplit(":", 1)[0]
            pkg["identifier"] = f"{image}:{version}"
        else:
            pkg["version"] = version
    SERVER_JSON.write_text(json.dumps(server, indent=2) + "\n")
    print(f"server.json set to {version}")


def check(expected: str) -> int:
    found = {"pyproject.toml": project_version()}
    found.update(server_versions(json.loads(SERVER_JSON.read_text())))
    bad = {k: v for k, v in found.items() if v != expected}
    for k, v in bad.items():
        print(f"::error::{k} is {v}, expected {expected}")
    if not bad:
        print(f"All versions match {expected}")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--check":
        expected = argv[1].removeprefix("v") if len(argv) > 1 else project_version()
        return check(expected)
    write(project_version())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
