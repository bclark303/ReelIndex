#!/usr/bin/env python3
"""Synchronize duplicated Windows payload files with the canonical sources.

The Docker image consumes backend/ and web/ directly. The Windows installer
needs a self-contained windows/app payload, so this script copies the canonical
sources there and can also verify that a checkout has not drifted.
"""
from __future__ import annotations

import argparse
import filecmp
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAIRS = (
    (ROOT / "backend" / "app", ROOT / "windows" / "app" / "app"),
    (ROOT / "web", ROOT / "windows" / "app" / "web"),
    (ROOT / "web", ROOT / "windows" / "web"),
)


def compare_trees(source: Path, destination: Path) -> list[str]:
    problems: list[str] = []
    if not destination.exists():
        return [f"missing directory: {destination.relative_to(ROOT)}"]
    comparison = filecmp.dircmp(source, destination)
    for name in comparison.left_only:
        problems.append(f"missing: {(destination / name).relative_to(ROOT)}")
    for name in comparison.right_only:
        problems.append(f"extra: {(destination / name).relative_to(ROOT)}")
    for name in comparison.diff_files:
        problems.append(f"different: {(destination / name).relative_to(ROOT)}")
    for child in comparison.common_dirs:
        problems.extend(compare_trees(source / child, destination / child))
    return problems


def sync_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if package copies differ")
    args = parser.parse_args()
    if args.check:
        problems = [problem for source, destination in PAIRS for problem in compare_trees(source, destination)]
        if problems:
            print("Package copies are out of sync:")
            for problem in problems:
                print(f"- {problem}")
            return 1
        print("Windows payload matches canonical backend and web sources.")
        return 0
    for source, destination in PAIRS:
        sync_tree(source, destination)
        print(f"Synced {source.relative_to(ROOT)} -> {destination.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
