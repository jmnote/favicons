#!/usr/bin/env python3
"""
Download favicons for domains listed in a text file.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


USER_AGENT = "favicon-downloader/1.0"
DEFAULT_TIMEOUT = 10
MAX_HTML_BYTES = 1024 * 1024
DEFAULT_OUTPUT_DIR = "favicon/ico"
DEFAULT_RECORD_FILE = "favicon_records.txt"
LEGACY_RECORD_FILE = "favicon_records.tsv"
KNOWN_EXTS = (".ico", ".png", ".svg")
STATUS_PENDING = "pending"
STATUS_OK = "ok"
STATUS_SAME_AS_MAIN = "same_as_main"
STATUS_FAIL = "fail"
DONE_STATUSES = {STATUS_OK, STATUS_SAME_AS_MAIN}
VALID_STATUSES = {STATUS_PENDING, STATUS_OK, STATUS_SAME_AS_MAIN, STATUS_FAIL}


@dataclass
class DomainEntry:
    line_no: int
    indent: str
    domain: str
    status: str = STATUS_PENDING
    source_url: str = ""
    extra_svg_url: str = ""


@dataclass
class DownloadRecord:
    status: str = STATUS_PENDING
    source_url: str = ""
    extra_svg_url: str = ""


class IconLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "link":
            return

        attr_map = {k.lower(): (v or "") for k, v in attrs}
        rel = attr_map.get("rel", "").lower()
        href = attr_map.get("href", "").strip()
        if href and "icon" in rel:
            self.links.append((href, rel))


def extract_host(entry: str) -> str | None:
    parsed = urlparse(entry if "://" in entry else f"https://{entry}")
    host = parsed.netloc or parsed.path.split("/", 1)[0].strip()
    host = host.strip().strip(".").lower()
    return host or None


def is_subdomain(host: str, parent: str) -> bool:
    return host != parent and host.endswith(f".{parent}")


def normalize_status(value: str) -> str:
    status = value.strip().lower().replace(" ", "_")
    return status or STATUS_PENDING


def is_done_status(status: str) -> bool:
    return status in DONE_STATUSES


def parse_and_validate_entries(
    lines: Iterable[str],
) -> tuple[list[DomainEntry], dict[str, str], list[str]]:
    entries: list[DomainEntry] = []
    subdomain_parents: dict[str, str] = {}
    errors: list[str] = []

    current_main: str | None = None
    prev_main: str | None = None
    prev_sub: str | None = None
    seen_mains: list[str] = []

    for line_no, raw in enumerate(lines, start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = raw[: len(raw) - len(raw.lstrip())]
        domain_text = stripped.split()[0]

        host = extract_host(domain_text)
        if not host:
            errors.append(f"line {line_no}: invalid domain/URL '{domain_text}'")
            continue

        entry = DomainEntry(
            line_no=line_no,
            indent=indent,
            domain=host,
        )

        is_indented = bool(indent)
        if is_indented:
            if current_main is None:
                errors.append(
                    f"line {line_no}: subdomain '{host}' must be placed under a main domain."
                )
                continue
            if not is_subdomain(host, current_main):
                errors.append(
                    f"line {line_no}: '{host}' is indented but not a subdomain of '{current_main}'."
                )
                continue
            if prev_sub is not None and host < prev_sub:
                errors.append(
                    f"line {line_no}: subdomains under '{current_main}' are not in ABC order "
                    f"('{prev_sub}' should not come before '{host}')."
                )
            prev_sub = host
            subdomain_parents[host] = current_main
            entries.append(entry)
            continue

        # Unindented lines are treated as main domains.
        required_parent: str | None = None
        if current_main and is_subdomain(host, current_main):
            required_parent = current_main
        parent_candidates = [main for main in seen_mains if is_subdomain(host, main)]
        if parent_candidates:
            candidate_parent = max(parent_candidates, key=len)
            if required_parent is None or len(candidate_parent) > len(required_parent):
                required_parent = candidate_parent
        if required_parent is not None:
            errors.append(
                f"line {line_no}: subdomain '{host}' must be indented under '{required_parent}'."
            )
        if prev_main is not None and host < prev_main:
            errors.append(
                f"line {line_no}: main domains are not in ABC order "
                f"('{prev_main}' should not come before '{host}')."
            )

        current_main = host
        prev_main = host
        prev_sub = None
        seen_mains.append(host)
        entries.append(entry)
    return entries, subdomain_parents, errors


def load_records(path: Path) -> tuple[dict[str, DownloadRecord], list[str]]:
    records: dict[str, DownloadRecord] = {}
    errors: list[str] = []
    if not path.exists():
        return records, errors

    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        normalized = re.sub(r"\s+", " ", stripped.lower())
        if (
            normalized.startswith("domain ")
            and " status" in normalized
            and "source_url" in normalized
        ):
            continue

        if "\t" in raw:
            columns = [col.strip() for col in raw.split("\t")]
        else:
            columns = [col.strip() for col in re.split(r"\s{2,}", stripped, maxsplit=3)]
        if not columns or not columns[0]:
            continue

        domain_text = columns[0].strip()
        host = extract_host(domain_text)
        if not host:
            errors.append(f"records line {line_no}: invalid domain '{domain_text}'")
            continue

        status = normalize_status(columns[1]) if len(columns) > 1 else STATUS_PENDING
        source_url = columns[2].strip() if len(columns) > 2 else ""
        extra_svg_url = columns[3].strip() if len(columns) > 3 else ""
        if source_url == "-":
            source_url = ""
        if extra_svg_url == "-":
            extra_svg_url = ""
        if status not in VALID_STATUSES:
            errors.append(
                f"records line {line_no}: invalid status '{status}'. "
                f"Use one of {sorted(VALID_STATUSES)}."
            )
            continue

        records[host] = DownloadRecord(
            status=status, source_url=source_url, extra_svg_url=extra_svg_url
        )
    return records, errors


def format_record_line(
    domain: str,
    record: DownloadRecord,
    domain_width: int,
    status_width: int,
    include_extra_svg: bool,
) -> str:
    fields = [
        domain.ljust(domain_width),
        record.status.ljust(status_width),
        record.source_url or "-",
    ]
    if include_extra_svg:
        fields.append(record.extra_svg_url or "-")
    return "  ".join(fields)


def save_records(path: Path, records: dict[str, DownloadRecord], domain_order: list[str]) -> None:
    ordered_domains: list[str] = []
    seen: set[str] = set()

    for domain in domain_order:
        if domain in records and domain not in seen:
            ordered_domains.append(domain)
            seen.add(domain)

    for domain in sorted(records.keys()):
        if domain not in seen:
            ordered_domains.append(domain)
            seen.add(domain)

    include_extra_svg = any(records[domain].extra_svg_url for domain in ordered_domains)
    domain_width = max([len("domain"), *[len(domain) for domain in ordered_domains]])
    status_width = max([len("status"), *[len(records[domain].status) for domain in ordered_domains]])

    header_fields = [
        "domain".ljust(domain_width),
        "status".ljust(status_width),
        "source_url",
    ]
    if include_extra_svg:
        header_fields.append("extra_svg_url")

    lines = ["  ".join(header_fields)]
    for domain in ordered_domains:
        lines.append(
            format_record_line(
                domain,
                records[domain],
                domain_width=domain_width,
                status_width=status_width,
                include_extra_svg=include_extra_svg,
            )
        )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def to_base_urls(entry: str) -> list[str]:
    host = extract_host(entry)
    if not host:
        return []
    return [f"https://{host}"]


def host_label(entry: str) -> str:
    host = extract_host(entry) or entry.strip().strip("/")
    host = re.sub(r"[^A-Za-z0-9._-]+", "_", host)
    return host or "unknown"


def is_ico_bytes(data: bytes) -> bool:
    # ICO/CUR file header.
    return len(data) >= 4 and data[:4] in (b"\x00\x00\x01\x00", b"\x00\x00\x02\x00")


def is_favicon_ico_url(url: str) -> bool:
    return Path(urlparse(url).path).name.lower() == "favicon.ico"


def looks_like_svg(data: bytes) -> bool:
    head = data[:2048].decode("utf-8", errors="ignore").lower()
    return "<svg" in head


def detect_image_extension(data: bytes, content_type: str | None) -> str | None:
    if is_ico_bytes(data):
        return ".ico"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith(b"BM"):
        return ".bmp"
    if looks_like_svg(data):
        return ".svg"

    # Accept only actual image types indicated by server metadata.
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime == "image/svg+xml":
        return ".svg"
    return None


def fetch_bytes(url: str) -> tuple[bytes, str | None]:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
        data = resp.read()
        content_type = resp.headers.get("Content-Type")
    if not data:
        raise ValueError("empty response body")
    return data, content_type


def fetch_html(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
        content_type = (resp.headers.get("Content-Type") or "").lower()
        if "html" not in content_type:
            return ""
        raw = resp.read(MAX_HTML_BYTES)
    return raw.decode("utf-8", errors="ignore")


def dedupe_urls(urls: Iterable[str]) -> list[str]:
    # Keep order, remove duplicates.
    seen: set[str] = set()
    deduped: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def resolve_icon_links(base_url: str) -> list[tuple[str, str]]:
    html = fetch_html(base_url)
    if not html:
        return []

    parser = IconLinkParser()
    parser.feed(html)

    resolved: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for href, rel in parser.links:
        abs_url = urljoin(base_url + "/", href)
        if abs_url in seen_urls:
            continue
        seen_urls.add(abs_url)
        resolved.append((abs_url, rel))
    return resolved


def icon_link_candidates(base_url: str) -> list[str]:
    return [url for url, _ in resolve_icon_links(base_url)]


def save_icon_if_absent(
    output_dir: Path, label: str, ext: str, data: bytes
) -> tuple[Path, bool]:
    out_path = output_dir / f"{label}{ext}"
    if out_path.exists():
        return out_path, False
    out_path.write_bytes(data)
    return out_path, True


def existing_icon_paths(output_dir: Path, label: str) -> dict[str, Path]:
    existing: dict[str, Path] = {}
    for ext in KNOWN_EXTS:
        path = output_dir / f"{label}{ext}"
        if path.exists():
            existing[ext] = path
    return existing


def is_same_file_content(path: Path, data: bytes) -> bool:
    if not path.exists():
        return False
    try:
        if path.stat().st_size != len(data):
            return False
        return path.read_bytes() == data
    except OSError:
        return False


def is_same_as_parent_domain(
    entry: str,
    ext: str,
    data: bytes,
    source_url: str,
    subdomain_parents: dict[str, str],
    saved_paths: dict[str, dict[str, Path]],
) -> bool:
    parent_main = subdomain_parents.get(entry)
    if not parent_main:
        return False

    parent_path = saved_paths.get(parent_main, {}).get(ext)
    if parent_path and is_same_file_content(parent_path, data):
        print(f"[skip] {entry} -> same as main domain '{parent_main}' ({source_url})")
        return True
    return False


def ico_candidates(base_url: str, errors: list[str]) -> list[str]:
    candidates: list[str] = []
    default_favicon_ico = urljoin(base_url + "/", "favicon.ico")
    try:
        links = resolve_icon_links(base_url)
        shortcut_icon_urls = [url for url, rel in links if "shortcut" in rel]
        other_icon_urls = [url for url, rel in links if "shortcut" not in rel]

        # Prefer HTML shortcut icon links before probing /favicon.ico.
        candidates.extend(shortcut_icon_urls)
        candidates.append(default_favicon_ico)
        candidates.extend(other_icon_urls)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        errors.append(f"{base_url}: {exc}")
        candidates.append(default_favicon_ico)
    return dedupe_urls(candidates)


def try_download_ico(base_url: str, errors: list[str]) -> tuple[bytes, str, str] | None:
    for ico_url in ico_candidates(base_url, errors):
        try:
            data, content_type = fetch_bytes(ico_url)
            if not is_ico_bytes(data):
                # Some sites serve PNG payloads at /favicon.ico.
                if is_favicon_ico_url(ico_url):
                    ext = detect_image_extension(data, content_type)
                    if ext == ".png":
                        return data, ".png", ico_url
                continue
            return data, ".ico", ico_url
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            errors.append(f"{ico_url}: {exc}")
            continue
    return None


def try_download_svg_or_png(base_url: str, errors: list[str]) -> tuple[bytes, str, str] | None:
    candidates: list[str] = [
        urljoin(base_url + "/", "favicon.svg"),
        urljoin(base_url + "/", "favicon.png"),
    ]
    try:
        candidates.extend(icon_link_candidates(base_url))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        errors.append(f"{base_url}: {exc}")

    for icon_url in dedupe_urls(candidates):
        try:
            data, content_type = fetch_bytes(icon_url)
            ext = detect_image_extension(data, content_type)
            if ext not in {".svg", ".png"}:
                continue
            return data, ext, icon_url
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            errors.append(f"{icon_url}: {exc}")
            continue
    return None


def try_download_shortcut_svg(base_url: str, errors: list[str]) -> tuple[bytes, str] | None:
    try:
        links = resolve_icon_links(base_url)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        errors.append(f"{base_url}: {exc}")
        return None

    shortcut_urls = [url for url, rel in links if "shortcut" in rel]
    for icon_url in dedupe_urls(shortcut_urls):
        try:
            data, content_type = fetch_bytes(icon_url)
            ext = detect_image_extension(data, content_type)
            if ext == ".svg":
                return data, icon_url
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            errors.append(f"{icon_url}: {exc}")
            continue
    return None


def download_favicon_for_entry(entry: str) -> tuple[bytes, str, str] | None:
    base_urls = to_base_urls(entry)
    if not base_urls:
        print(f"[skip] invalid entry: {entry}")
        return None

    errors: list[str] = []

    # Step 1: try ICO first.
    for base in base_urls:
        result = try_download_ico(base, errors)
        if result:
            return result

    # Step 2: only if ICO is not found, try SVG/PNG.
    for base in base_urls:
        result = try_download_svg_or_png(base, errors)
        if result:
            return result

    print(f"[fail] {entry}")
    for err in errors[-5:]:
        print(f"  - {err}")
    return None


def download_shortcut_svg_for_entry(entry: str) -> tuple[bytes, str] | None:
    base_urls = to_base_urls(entry)
    if not base_urls:
        return None

    errors: list[str] = []
    for base in base_urls:
        result = try_download_shortcut_svg(base, errors)
        if result:
            return result
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download favicons for domains listed in a file."
    )
    parser.add_argument(
        "-i",
        "--input",
        default="domains.txt",
        help="Path to text file with domains/URLs (default: domains.txt).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to save downloaded icons (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "-r",
        "--record",
        default=DEFAULT_RECORD_FILE,
        help=f"Path to record file (default: {DEFAULT_RECORD_FILE}).",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Input file not found: {input_path}")
        return 1

    entries, subdomain_parents, validation_errors = parse_and_validate_entries(
        input_path.read_text(encoding="utf-8").splitlines()
    )
    if validation_errors:
        print("Input validation failed:")
        for err in validation_errors:
            print(f"  - {err}")
        return 1

    if not entries:
        print("No valid domains/URLs found in input file.")
        return 1

    record_path = Path(args.record)
    record_source_path = record_path
    default_record_requested = args.record == DEFAULT_RECORD_FILE
    legacy_record_path = Path(LEGACY_RECORD_FILE)
    if (
        default_record_requested
        and not record_path.exists()
        and legacy_record_path.exists()
    ):
        record_source_path = legacy_record_path
        print(
            f"[info] Using legacy record file '{legacy_record_path}' "
            f"and migrating to '{record_path}'."
        )

    records, record_errors = load_records(record_source_path)
    if record_errors:
        print(f"Record file validation failed: {record_source_path}")
        for err in record_errors:
            print(f"  - {err}")
        return 1

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    success = 0
    saved_paths: dict[str, dict[str, Path]] = {}
    for entry in entries:
        domain = entry.domain
        label = host_label(domain)
        record = records.get(domain, DownloadRecord())

        if is_done_status(record.status):
            existing_paths = existing_icon_paths(output_dir, label)
            if existing_paths:
                saved_paths.setdefault(domain, {}).update(existing_paths)
                print(
                    f"[skip] {domain} -> status={record.status} in {record_source_path.name}"
                )
                records[domain] = record
                success += 1
                continue
            print(
                f"[redo] {domain} -> status={record.status}, but no file in {output_dir}"
            )

        record.extra_svg_url = ""
        result = download_favicon_for_entry(domain)
        if not result:
            record.status = STATUS_FAIL
            record.source_url = ""
            records[domain] = record
            continue

        data, ext, source_url = result
        if is_same_as_parent_domain(
            domain, ext, data, source_url, subdomain_parents, saved_paths
        ):
            record.status = STATUS_SAME_AS_MAIN
            record.source_url = source_url
            records[domain] = record
            success += 1
            continue

        out_path, wrote = save_icon_if_absent(output_dir, label, ext, data)
        saved_paths.setdefault(domain, {})[ext] = out_path
        if wrote:
            print(f"[ok] {domain} -> {out_path} ({source_url})")
        else:
            print(f"[skip] {domain} -> already exists ({out_path})")
        record.status = STATUS_OK
        record.source_url = source_url
        records[domain] = record
        success += 1

        # Also save shortcut-icon SVG when present.
        if ext == ".svg":
            continue

        extra_svg = download_shortcut_svg_for_entry(domain)
        if not extra_svg:
            continue

        svg_data, svg_source_url = extra_svg
        record.extra_svg_url = svg_source_url
        records[domain] = record
        if is_same_as_parent_domain(
            domain, ".svg", svg_data, svg_source_url, subdomain_parents, saved_paths
        ):
            continue

        existing_svg = saved_paths.get(domain, {}).get(".svg")
        if existing_svg and is_same_file_content(existing_svg, svg_data):
            continue

        svg_path, wrote_svg = save_icon_if_absent(output_dir, label, ".svg", svg_data)
        saved_paths.setdefault(domain, {})[".svg"] = svg_path
        if wrote_svg:
            print(f"[extra] {domain} -> {svg_path} ({svg_source_url})")
        else:
            print(f"[skip] {domain} -> svg already exists ({svg_path})")

    save_records(record_path, records, [entry.domain for entry in entries])
    print(f"Done. Success: {success}/{len(entries)}")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
