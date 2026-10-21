#!/usr/bin/env python3
"""Keep Railway's source fetch pinned to the checked-out framework revision."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sync_pin(root: Path = ROOT, *, check: bool = False) -> str:
    result = subprocess.run(
        ["git", "-C", str(root / "framework"), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    revision = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError("framework HEAD must resolve to a full commit SHA")
    # Refuse to pin a directory that Git resolved to the parent repository.
    tracked = subprocess.run(
        ["git", "-C", str(root / "framework"), "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    if Path(tracked.stdout.strip()).resolve() != (root / "framework").resolve():
        raise RuntimeError("initialize the framework submodule first")
    pin_file = root / "framework-revision.txt"
    original = pin_file.read_text(encoding="utf-8") if pin_file.exists() else ""
    updated = revision + "\n"
    if check and updated != original:
        raise RuntimeError("Railway pin is stale; run python3 scripts/pin_railway_framework.py")
    if not check and updated != original:
        pin_file.write_text(updated, encoding="utf-8")
    return revision


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        print(f"Railway framework: {sync_pin(check=args.check)}")
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
