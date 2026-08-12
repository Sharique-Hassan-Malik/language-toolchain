#!/usr/bin/env python3
"""PPRA Tender Scraper — entry point.

    python -m scraper.main                 # full run: scrape → Excel → email
    python -m scraper.main --no-email       # scrape + Excel only (no Gmail needed)
    python -m scraper.main --max-pages 1    # quick local test: first page only
    python -m scraper.main --auth           # (local) open a browser to make token.json

Environment (usually set via GitHub Secrets/Variables):
    GMAIL_SENDER, GMAIL_RECIPIENT   — email addresses
    PPRA_KEYWORDS                   — comma-separated keyword list (optional)
    PPRA_DNS_OVERRIDE               — "MAP host ip" rule, or "" to disable (optional)
"""

from __future__ import annotations

import argparse
import os

from scraper.config import (
    DOWNLOAD_DIR, EXCEL_PATH, KEYWORDS, MAX_PAGES,
    SUBJECT_MATCH, SUBJECT_NO_MATCH,
)
from scraper.util import pdf_filename


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrape PPRA tenders and email a report.")
    p.add_argument("--no-email", action="store_true", help="scrape and build the Excel, but do not send email")
    p.add_argument("--max-pages", type=int, default=MAX_PAGES, help="limit pages scraped (0 = all)")
    p.add_argument("--auth", action="store_true",
                   help="run the local browser OAuth flow to create scraper/token.json, then exit")
    return p.parse_args(argv)


def main(argv=None) -> None:
    args = _parse_args(argv)

    # --auth: (re)generate the Gmail token locally, then stop.
    if args.auth:
        from scraper.emailer import authenticate_interactive
        authenticate_interactive()
        return

    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    # -- scrape --------------------------------------------------------------
    from scraper.browser import build_driver
    from scraper.scraper import run_scrape

    driver, wait = build_driver(DOWNLOAD_DIR)
    try:
        tender_data = run_scrape(driver, wait, DOWNLOAD_DIR, max_pages=args.max_pages)
    finally:
        driver.quit()

    print(f"\nScraped {len(tender_data)} tender(s).")

    # -- keyword detection + Excel report ------------------------------------
    from scraper.reporter import detect_keywords, save_excel

    matched_map, html_messages = detect_keywords(tender_data, KEYWORDS)
    save_excel(tender_data, EXCEL_PATH, matched_map)

    matched_pdfs = [
        os.path.join(DOWNLOAD_DIR, pdf_filename(tno))
        for tno in matched_map
        if os.path.exists(os.path.join(DOWNLOAD_DIR, pdf_filename(tno)))
    ]

    # -- email ---------------------------------------------------------------
    if args.no_email:
        print("--no-email set; skipping email.")
        return

    sender    = os.environ.get("GMAIL_SENDER", "")
    recipient = os.environ.get("GMAIL_RECIPIENT", "")
    if not sender or not recipient:
        print("GMAIL_SENDER / GMAIL_RECIPIENT not set — skipping email.")
        return

    if html_messages:
        subject   = SUBJECT_MATCH.format(n=len(html_messages))
        html_body = "".join(html_messages)
    else:
        subject   = SUBJECT_NO_MATCH
        html_body = "<p><b>No tenders matched the configured keywords.</b></p>"

    from scraper.emailer import send_report
    # allow the interactive browser flow only when explicitly enabled (never CI)
    allow_interactive = os.environ.get("PPRA_ALLOW_INTERACTIVE_AUTH") == "1"
    send_report(sender, recipient, subject, html_body, EXCEL_PATH, matched_pdfs,
                allow_interactive=allow_interactive)


if __name__ == "__main__":
    main()
