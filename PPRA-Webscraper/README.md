# PPRA Tender Scraper

Automated tool that scrapes the **Public Procurement Regulatory Authority (PPRA)
Pakistan** website for tenders in a chosen sector, downloads the attached PDFs,
builds a styled Excel report, highlights keyword matches, and emails the results
via the Gmail API — running unattended on GitHub Actions every hour.

Built as a set of small, testable modules, with the failure modes that quietly
break an unattended scraper handled explicitly (see
**[Troubleshooting](#troubleshooting)**).

---

## Features

- Headless Chrome scraper with retry logic and an **optional** DNS override for PPRA's unreliable server
- Angular-aware waits (spinner detection) for the SPA frontend
- Automatic PDF download, renamed to the tender number (with filesystem-safe sanitising)
- Case-insensitive keyword detection, with optional whole-word matching, bolded in both the Excel report and the email
- Styled Excel output — auto-width columns, wrap-text, proportional row heights
- Gmail API email with the Excel report and matched PDFs attached
- **CI-safe Gmail auth**: never opens a browser on the runner; fails with a clear, actionable message instead of hanging
- Configurable from environment variables / repo variables — keywords, sector, DNS rule, page limit — **no code edits needed**
- On/Off toggle via a repository variable, and a weekly keep-alive commit to stop GitHub disabling the schedule
- A **unit-tested core** (`pytest`) for the keyword, filename, Excel and email logic — runnable without a browser or Gmail

---

## Quick Start

```bash
git clone https://github.com/Sharique-Hassan-Malik/PPRA-Webscraper.git
cd PPRA-Webscraper
pip install -r scraper/requirements.txt
```

Run it (always as a module, from the repo root — the code is a `scraper` package):

```bash
python -m scraper.main                 # full run: scrape → Excel → email
python -m scraper.main --no-email       # scrape + Excel only (no Gmail needed)
python -m scraper.main --max-pages 1    # quick test: only the first page
```

Outputs:
- `scraper/ppra_info_comm_tech.xlsx` — the tender report
- `ppra_pdfs/` — downloaded PDF documents

> **Note:** `python scraper/main.py` (running the file directly) will fail with
> `No module named 'scraper'` — the code is a package and must be run with `-m`.

---

## Configuration (no code edits)

Everything below is read from an environment variable, so in CI you set them as
repository **Variables** (or Secrets); locally you `export` them.

| Variable | Default | Purpose |
|---|---|---|
| `PPRA_KEYWORDS` | `Bank,University` | comma-separated keywords to match on Tender Details |
| `PPRA_WHOLE_WORD` | `false` | `true` = match whole words only (`Bank` ≠ `Embankment`) |
| `PPRA_SECTOR` | `Info and Comm Tech` | which PPRA sector to scrape |
| `PPRA_DNS_OVERRIDE` | `MAP ppra.gov.pk 210.56.8.55` | Chrome host-resolver rule; **set to `""` to disable** and use normal DNS |
| `PPRA_MAX_PAGES` | `0` | cap pages scraped (`0` = all) |
| `PPRA_HEADLESS` | `true` | `false` to watch a real browser locally |
| `GMAIL_SENDER` / `GMAIL_RECIPIENT` | — | email addresses |

Keywords can still be edited directly in `scraper/config.py` if you prefer.

---

## Troubleshooting

An unattended scraper tends to break in a few well-known ways. Each one is
handled here:

| Symptom | Root cause | How it is handled |
|---|---|---|
| **Email stops after ~a week** | The Gmail OAuth app is in "**Testing**" status, whose refresh tokens Google **expires after 7 days**. | The auth error now says exactly this and how to fix it; a successful refresh is written back to `token.json`. Long-term fix: set the app to *In production*. |
| **CI job hangs / times out** | Calling `run_local_server()` on a bad token tries to open a browser on the headless runner. | Interactive auth runs **only** via `--auth` locally; in CI a bad token raises a clear error instead of hanging. |
| **Every run fails to connect** | The DNS work-around pinned `ppra.gov.pk` to a fixed IP; if PPRA moves servers that IP is wrong for good. | `PPRA_DNS_OVERRIDE` is optional and overridable — set it to `""` to fall back to normal DNS, or to a fresh `MAP host ip`. |
| **`session not created: version mismatch`** | `webdriver-manager` fetched a chromedriver that didn't match the installed Chrome. | Uses **Selenium Manager** (built into Selenium ≥ 4.6) to resolve the driver; `webdriver-manager` is only a fallback. |
| **A matched PDF isn't attached** | Tender numbers contain `/` (e.g. `TS123/2025`), so `os.rename` to `TS123/2025.pdf` failed silently. | Filenames are sanitised (`TS123-2025.pdf`); covered by a test. |
| **`No module named 'scraper'` in Actions** | Running `python scraper/main.py` directly breaks package imports. | The workflow runs `python -m scraper.main`. |

---

## Gmail API Setup

1. In the [Google Cloud Console](https://console.cloud.google.com/) create a project and enable the **Gmail API**.
2. **APIs & Services → Credentials → Create Credentials → OAuth client ID → Desktop app**; download it as `scraper/credentials.json`.
3. Generate the token locally (opens a browser once for consent):

   ```bash
   python -m scraper.main --auth
   ```

   This writes `scraper/token.json`. (Add your address as a **Test user** on the
   consent screen — but see the 7-day expiry note above; for a long-lived setup,
   publish the app to *In production*.)

If the CI token ever expires, re-run `--auth` locally and update the `TOKEN_JSON`
secret with the new base64.

---

## GitHub Actions Setup

Add these under **Settings → Secrets and variables → Actions**:

| Secret | Value |
|--------|-------|
| `CREDENTIALS_JSON` | base64 of `scraper/credentials.json` |
| `TOKEN_JSON` | base64 of `scraper/token.json` |
| `GMAIL_SENDER` | your Gmail address |
| `GMAIL_RECIPIENT` | recipient address |

Encode (Linux/macOS): `base64 scraper/token.json | tr -d '\n'`
· (Windows PowerShell): `certutil -encode token.json token_b64.txt`.

**This does not auto-run when you push.** The workflows ship
under **`github/workflows/`** (no leading dot) — a folder GitHub ignores — so
nothing runs until you deliberately activate it. There are two off-by-default
gates:

1. **Activate the folder** — rename it so GitHub sees it:
   ```bash
   mv github .github
   ```
2. **Turn on the schedule** — even after activating, the hourly run stays off
   until you set the repo Variable:
   ```
   Settings → Secrets and variables → Actions → Variables
   SCRAPER_ENABLED = true
   ```

Until you do both, only a **manual** run is possible (*Actions → PPRA Tender
Scraper → Run workflow*), which is always available regardless of the switch.

> Keep the repository **private** while `CREDENTIALS_JSON` / `TOKEN_JSON` are set,
> since a leaked token can send mail as you.

### On/Off toggle (after activating)

- **Enable scheduled runs:** repo Variable `SCRAPER_ENABLED = true`.
- **Pause:** set it to anything else (or delete it) — it's off unless it's exactly `true`.
- **Manual run:** *Actions → PPRA Tender Scraper → Run workflow* (untick *Enabled* to skip a single run).

---

## Testing

The scraping and emailing need a live PPRA session and OAuth credentials, but the
logic behind the common failures is pure and unit-tested — and the suite
runs **without** Selenium or the Google libraries installed (they're imported
lazily):

```bash
pip install pytest pandas openpyxl
pytest tests/
```

```
tests/test_scraper.py ......... (9 passed)
```

It covers keyword matching (case-insensitive + whole-word), filename sanitising,
the de-duplicated HTML/email body, the Gmail message (valid, skips missing
attachments), and the styled Excel output. Without `pandas` installed the one
Excel test is skipped rather than failing.

---

## Project Structure

```
PPRA-Webscraper/
├── github/workflows/      scheduler.yml + keep-alive.yml  (dormant: rename to .github to activate)
├── scraper/
│   ├── config.py          all settings, read from env vars
│   ├── browser.py         headless Chrome (Selenium Manager; optional DNS rule)
│   ├── scraper.py         navigation, pagination, row + PDF extraction
│   ├── util.py            pure helpers: tender-number + filename sanitising
│   ├── reporter.py        keyword detection + styled Excel (pure logic testable)
│   ├── emailer.py         CI-safe Gmail auth + message building
│   ├── main.py            CLI entry point (--no-email / --max-pages / --auth)
│   └── requirements.txt
├── tests/test_scraper.py  the unit-tested core
├── ARCHITECTURE.md
└── README.md
```

---

## License

MIT — see [`LICENSE`](./LICENSE).
