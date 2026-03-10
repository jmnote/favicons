# favicons

## Commands

- `make download`
  - Downloads icons into `./favicon/ico`
  - Uses `./favicon_records.txt` as state
- `make png`
  - Generates PNG variants from `./favicon/ico` into:
    - `./favicon/png/16`
    - `./favicon/png/32`
    - `./favicon/png/orig`
  - Requires `Pillow` (`pip install pillow`)
  - SVG conversion also needs `CairoSVG` (`pip install cairosvg`)
- `make prune`
  - Deletes files not listed in `domains.txt` from `./favicon/ico` and `./favicon/png`

## Input (`domains.txt`)

- One domain per line
- Main domain: no indent
- Subdomain: indented under its main domain
- Main domains and subdomains must each be ABC-sorted

Example:

```text
google.com
  maps.google.com
naver.com
  terms.naver.com
```

## Record File (`favicon_records.txt`)

Fixed-width text columns:

1. `domain`
2. `status` (`pending`, `ok`, `same_as_main`, `fail`)
3. `source_url`
4. `extra_svg_url` (optional)

If status is `ok` or `same_as_main`, that domain is skipped on the next run.
If `favicon_records.txt` does not exist but `favicon_records.tsv` exists, it is loaded once and migrated automatically.

Example:

```text
domain          status  source_url
apple.com       ok      https://apple.com/favicon.ico
chatgpt.com     ok      https://chatgpt.com/cdn/assets/favicon-l4nq08hd.svg
```

## Download Rules

1. Validate `domains.txt`
2. For each domain, skip if record status is done (`ok` / `same_as_main`)
3. Download using HTTPS only:
   - Try ICO candidates first:
     - shortcut icon links
     - `/favicon.ico`
     - other icon links
   - If `/favicon.ico` returns PNG bytes, save as `.png`
   - If ICO is not found, fallback to PNG/SVG candidates
4. Save to `./favicon/ico/<domain>.<ext>` (no overwrite)
5. If subdomain icon bytes are same as main domain icon, mark `same_as_main`
6. If shortcut icon has SVG, save extra `.svg`
7. Update `favicon_records.txt`

## Flow

```mermaid
flowchart TD
    A[Read domains.txt] --> B[Validate input]
    B --> C[Load favicon_records.txt]
    C --> D[For each domain]
    D --> E{Status done}
    E -->|Yes| D
    E -->|No| F[Download favicon]
    F --> G[Save favicon and update status]
    G --> H[Save extra shortcut SVG if found]
    H --> D
    D --> I[Write favicon_records.txt]
    I --> J[Done]
```
