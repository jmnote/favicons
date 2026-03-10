#!/usr/bin/env python3
"""
Generate PNG variants from downloaded favicon files.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - runtime dependency check
    Image = None  # type: ignore[assignment]

try:
    import cairosvg
except ImportError:  # pragma: no cover - optional dependency
    cairosvg = None  # type: ignore[assignment]


EXT_PRIORITY = {
    ".svg": 0,
    ".png": 1,
    ".ico": 2,
    ".webp": 3,
    ".bmp": 4,
    ".gif": 5,
    ".jpg": 6,
    ".jpeg": 6,
}


@dataclass
class SourceFile:
    domain: str
    path: Path
    rank: int


def choose_source_files(input_dir: Path) -> dict[str, SourceFile]:
    chosen: dict[str, SourceFile] = {}

    for path in sorted(input_dir.iterdir()):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in EXT_PRIORITY:
            continue

        domain = path.stem
        candidate = SourceFile(domain=domain, path=path, rank=EXT_PRIORITY[ext])
        current = chosen.get(domain)
        if current is None or candidate.rank < current.rank:
            chosen[domain] = candidate
    return chosen


def open_icon_image(path: Path):
    if Image is None:
        raise RuntimeError("Pillow is required. Install with: pip install pillow")

    ext = path.suffix.lower()
    if ext == ".svg":
        if cairosvg is None:
            raise RuntimeError(
                "CairoSVG is required to convert SVG files. Install with: pip install cairosvg"
            )
        png_bytes = cairosvg.svg2png(url=str(path))
        with Image.open(BytesIO(png_bytes)) as rendered:
            return rendered.convert("RGBA")

    with Image.open(path) as img:
        if ext == ".ico":
            n_frames = getattr(img, "n_frames", 1)
            best = None
            best_area = -1
            for frame_idx in range(n_frames):
                try:
                    img.seek(frame_idx)
                except EOFError:
                    break
                candidate = img.copy()
                area = candidate.width * candidate.height
                if area > best_area:
                    best = candidate
                    best_area = area
            if best is None:
                best = img.copy()
            return best.convert("RGBA")
        return img.convert("RGBA")


def save_variants(image, domain: str, output_root: Path) -> None:
    ori_dir = output_root / "orig"
    s16_dir = output_root / "16"
    s32_dir = output_root / "32"
    for directory in (ori_dir, s16_dir, s32_dir):
        directory.mkdir(parents=True, exist_ok=True)

    ori_path = ori_dir / f"{domain}.png"
    image.save(ori_path, format="PNG")

    resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
    for size, directory in ((16, s16_dir), (32, s32_dir)):
        resized = image.resize((size, size), resample)
        resized.save(directory / f"{domain}.png", format="PNG")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create PNG variants (16/32/original) from favicon files."
    )
    parser.add_argument(
        "-i",
        "--input",
        default="favicon/ico",
        help="Directory containing source favicon files (default: favicon/ico).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="favicon/png",
        help="Directory to write PNG variants (default: favicon/png).",
    )
    args = parser.parse_args()

    if Image is None:
        print("Pillow is required. Install with: pip install pillow", file=sys.stderr)
        return 1

    input_dir = Path(args.input)
    if not input_dir.exists() or not input_dir.is_dir():
        print(f"Input directory not found: {input_dir}", file=sys.stderr)
        return 1

    output_root = Path(args.output)
    sources = choose_source_files(input_dir)
    if not sources:
        print(f"No supported files found in: {input_dir}")
        return 1

    converted = 0
    skipped = 0
    for domain in sorted(sources):
        source = sources[domain]
        try:
            image = open_icon_image(source.path)
            try:
                save_variants(image, domain, output_root)
            finally:
                image.close()
            print(f"[ok] {source.path.name} -> {domain}.png (16/32/orig)")
            converted += 1
        except Exception as exc:
            print(f"[skip] {source.path.name}: {exc}")
            skipped += 1

    print(f"Done. Converted: {converted}, Skipped: {skipped}")
    return 0 if converted else 1


if __name__ == "__main__":
    raise SystemExit(main())
