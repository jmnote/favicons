#!/usr/bin/env python3
"""
Download favicon images from Google's faviconV2 endpoint.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import urlencode

from download_favicon import detect_image_extension, fetch_bytes, parse_and_validate_entries


GSTATIC_ENDPOINT = "https://t0.gstatic.com/faviconV2"
DEFAULT_SIZES = (16, 32, 64)


def build_gstatic_url(domain: str, size: int) -> str:
    query = urlencode(
        {
            "client": "SOCIAL",
            "type": "FAVICON",
            "fallback_opts": "TYPE,SIZE,URL",
            "url": f"https://{domain}",
            "size": str(size),
        }
    )
    return f"{GSTATIC_ENDPOINT}?{query}"


def parse_sizes(raw: str) -> list[int]:
    out: list[int] = []
    for token in raw.split(","):
        value = token.strip()
        if not value:
            continue
        out.append(int(value))
    return out


def existing_for_domain(size_dir: Path, domain: str) -> Path | None:
    for path in sorted(size_dir.glob(f"{domain}.*")):
        if path.is_file():
            return path
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download gstatic favicon images into gstatic/<size>/ directories."
    )
    parser.add_argument(
        "-i",
        "--input",
        default="domains.txt",
        help="Path to domain list file (default: domains.txt).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="gstatic",
        help="Output directory root (default: gstatic).",
    )
    parser.add_argument(
        "--sizes",
        default="16,32,64",
        help="Comma-separated sizes (default: 16,32,64).",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return 1

    try:
        sizes = parse_sizes(args.sizes)
    except ValueError:
        print(f"Invalid --sizes value: {args.sizes}")
        return 1
    if not sizes:
        sizes = list(DEFAULT_SIZES)

    entries, _, errors = parse_and_validate_entries(
        input_path.read_text(encoding="utf-8").splitlines()
    )
    if errors:
        print("Input validation failed:")
        for err in errors:
            print(f"  - {err}")
        return 1
    if not entries:
        print("No valid domains in input file.")
        return 1

    output_root = Path(args.output)
    domains = [entry.domain for entry in entries]

    success = 0
    skipped = 0
    failed = 0

    for domain in domains:
        for size in sizes:
            size_dir = output_root / str(size)
            size_dir.mkdir(parents=True, exist_ok=True)

            existing = existing_for_domain(size_dir, domain)
            if existing:
                print(f"[skip] {domain} {size}px -> already exists ({existing})")
                skipped += 1
                continue

            url = build_gstatic_url(domain, size)
            try:
                data, content_type = fetch_bytes(url)
                ext = detect_image_extension(data, content_type)
                if not ext:
                    raise ValueError("response is not a recognized image format")

                out_path = size_dir / f"{domain}{ext}"
                out_path.write_bytes(data)
                print(f"[ok] {domain} {size}px -> {out_path}")
                success += 1
            except Exception as exc:
                print(f"[fail] {domain} {size}px -> {exc}")
                failed += 1

    print(f"Done. Success: {success}, Skipped: {skipped}, Failed: {failed}")
    return 0 if success or skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
