#!/usr/bin/env python3
"""Prune favicon asset files that are not listed in domains.txt."""

from __future__ import annotations

import argparse
from pathlib import Path

from favicon_download import parse_and_validate_entries


def load_allowed_domains(input_path: Path) -> set[str]:
    lines = input_path.read_text(encoding="utf-8").splitlines()
    entries, _, errors = parse_and_validate_entries(lines)
    if errors:
        print("Input validation failed:")
        for err in errors:
            print(f"  - {err}")
        raise SystemExit(1)
    return {entry.domain for entry in entries}


def prune_domain_files(root: Path, allowed_domains: set[str], dry_run: bool) -> tuple[int, int]:
    deleted = 0
    kept = 0
    if not root.exists():
        return deleted, kept

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        domain = path.stem
        if domain in allowed_domains:
            kept += 1
            continue

        print(f"[delete] {path}")
        if not dry_run:
            path.unlink()
        deleted += 1

    # Clean up empty directories after file deletion.
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            if dry_run:
                print(f"[empty-dir] {path}")
            else:
                path.rmdir()

    return deleted, kept


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Delete files from favicon/ico and favicon/png directories "
            "if domain is not in domains.txt."
        )
    )
    parser.add_argument(
        "-i",
        "--input",
        default="domains.txt",
        help="Path to domain list file (default: domains.txt).",
    )
    parser.add_argument(
        "--favicon-dir",
        default="favicon/ico",
        help="Favicon directory to prune (default: favicon/ico).",
    )
    parser.add_argument(
        "--png-dir",
        default="favicon/png",
        help="PNG directory to prune (default: favicon/png).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without deleting.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return 1

    allowed_domains = load_allowed_domains(input_path)
    if not allowed_domains:
        print("No valid domains in input file.")
        return 1

    total_deleted = 0
    total_kept = 0
    for target in (Path(args.favicon_dir), Path(args.png_dir)):
        deleted, kept = prune_domain_files(target, allowed_domains, args.dry_run)
        total_deleted += deleted
        total_kept += kept

    action = "would delete" if args.dry_run else "deleted"
    print(f"Done. Kept: {total_kept}, {action}: {total_deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
