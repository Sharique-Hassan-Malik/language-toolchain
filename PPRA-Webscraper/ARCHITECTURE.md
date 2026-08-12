# Architecture — PPRA Tender Scraper

## Overview

A Python automation tool that scrapes the Public Procurement Regulatory
Authority (PPRA) Pakistan website for a chosen sector's tenders, downloads the
attached PDFs, produces a styled Excel report and emails the results via the
Gmail API — running unattended on GitHub Actions.

The organising principle is a **pure / impure split**: the code
that talks to the outside world (Selenium, the filesystem, the Gmail API) is kept
separate from the pure logic (keyword matching, filename sanitising, HTML/email
construction, Excel styling). The pure logic has no heavy imports at module load
— Selenium and the Google libraries are imported *lazily*, inside the functions
that use them — so it can be unit-tested with nothing but the standard library
(plus pandas/openpyxl for the one Excel test).

---

## Pipeline

```
GitHub Actions (hourly cron)  ──►  python -m scraper.main
        │
        ▼
browser.py     build_driver()        headless Chrome, Selenium Manager,
        │                            optional DNS rule, silent PDF downloads
        ▼
scraper.py     run_scrape()          safe_navigate → select_sector → paginate;
        │                            per row: extract fields + download PDFs
        │                            (util.py sanitises tender no. → filename)
        ▼  list[dict] tender_data
        ├──► reporter.py  detect_keywords()  → matched_map, html_messages
        ├──► reporter.py  save_excel()       → ppra_info_comm_tech.xlsx
        └──► emailer.py   send_report()      → Gmail API → recipient inbox
```

---

## Modules

### `scraper/config.py`
The single source of truth, and every value is read from an environment variable
with a sensible default — keywords, sector, the DNS rule, the page cap, headless
mode, retry counts. That is what lets behaviour change from GitHub repository
variables without a code edit.

### `scraper/util.py` (pure)
Dependency-free helpers, unit-tested directly:
- **`normalize_tender_no()`** strips the stray `View Invoice` text PPRA injects into the tender-number cell and collapses whitespace.
- **`pdf_filename()`** turns a tender number into a filesystem-safe filename. PPRA tender numbers contain `/` (e.g. `TS123/2025`); writing `f"{tender_no}.pdf"` directly would make `os.rename` treat the slash as a directory separator and fail silently — the PDF then never gets attached. Sanitising to `TS123-2025.pdf` avoids it.

### `scraper/browser.py`
Builds the headless Chrome driver. Two reliability choices:
- **Selenium Manager** (built into Selenium ≥ 4.6) resolves the matching chromedriver; `webdriver-manager` is only a fallback. This avoids the frequent "session not created: version mismatch" failures an always-webdriver-manager path produces.
- The **`--host-resolver-rules` DNS pin is optional** (`config.DNS_OVERRIDE`); an empty value falls back to normal DNS, so a stale pinned IP can't permanently break every run.

Selenium is imported inside `build_driver`, so importing the package doesn't require Selenium.

### `scraper/scraper.py`
Navigation and extraction. `safe_navigate` retries the load `NAV_RETRIES` times; `select_sector` walks the paginated sidebar to find the sector; `wait_for_spinner` blocks on Angular's `ngx-spinner-overlay` so Selenium never reads a half-loaded table; `scrape_current_page` reads each `<tr>`'s cells and triggers its PDF downloads, polling the download directory by diffing the file set until a new file appears. `run_scrape` accepts a `max_pages` cap for quick local runs.

### `scraper/reporter.py`
- **`matched_keywords` / `highlight` / `detect_keywords`** (pure) — case-insensitive keyword matching with an optional whole-word mode, de-duplicated per tender, producing the bolded HTML paragraphs for the email. No heavy imports.
- **`save_excel`** — writes the workbook with pandas/openpyxl (imported lazily) and post-processes: auto-width columns, wrap-text, proportional row heights, bold Tender Details on matched rows.

### `scraper/emailer.py`
- **`build_message`** (pure) — a base64url Gmail message with the HTML body and attachments; **missing attachment paths are skipped** rather than crashing on the first missing file.
- **`get_credentials(allow_interactive)`** — loads `token.json` and refreshes if needed, writing the refreshed token back. It is **CI-safe**: it never runs the browser OAuth flow unless `allow_interactive` is set (a local `--auth` run). In CI a missing/expired token raises `_auth_help(...)`, which names the likely cause (the 7-day "Testing"-status refresh-token expiry) and the fix, instead of hanging on `run_local_server()`.
- **`authenticate_interactive()`** — the local-only browser flow, invoked by `python -m scraper.main --auth`.

### `scraper/main.py`
The CLI entry point (`--no-email`, `--max-pages`, `--auth`). It imports the heavy modules lazily *after* argument parsing, so `--help` and `--auth` work without a full environment. It must be run as a module (`python -m scraper.main`) so the `scraper` package resolves.

---

## Reliability measures

| Failure | Cause | Fix |
|---|---|---|
| email dies after ~7 days | OAuth "Testing" refresh-token expiry | actionable error + refresh-and-persist; docs recommend publishing the app |
| CI job hangs | `run_local_server()` on a headless runner | interactive auth gated behind `--auth`; CI raises instead |
| all runs fail to connect | stale pinned PPRA IP | DNS override made optional/overridable |
| driver version mismatch | `webdriver-manager` vs installed Chrome | Selenium Manager first |
| PDF not attached | `/` in tender number broke rename | filename sanitising (`util.pdf_filename`) |
| `No module named 'scraper'` | running the file directly | workflow runs `python -m scraper.main` |

---

## Testability

`tests/test_scraper.py` exercises the pure core — filename/tender-number
sanitising, keyword matching (incl. whole-word), the de-duplicated email body,
the Gmail message (valid MIME, missing attachments skipped), and the styled Excel
output. Because the impure dependencies are imported lazily, the suite runs with
only the standard library present; the Excel test uses `pytest.importorskip` so
it is skipped rather than failed when pandas is absent.

---

## Automation (dormant by default)

The workflows ship under **`github/workflows/`** — not `.github/workflows/` — so
GitHub does not register them and **nothing runs on push**. Activation is a
deliberate two-step opt-in: rename the folder
to `.github`, then set the repo Variable `SCRAPER_ENABLED = true`.

- **`scheduler.yml`** — hourly cron, but the job runs **only** when
  `SCRAPER_ENABLED == 'true'` (default off), or on a manual `workflow_dispatch`.
  It decodes the `CREDENTIALS_JSON`/`TOKEN_JSON` secrets into `scraper/`, then
  runs `python -m scraper.main`.
- **`keep-alive.yml`** — a weekly empty commit so GitHub doesn't disable the
  schedule after 60 days of inactivity (only relevant once activated).
