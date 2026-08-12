"""Configuration for the PPRA scraper.

Everything that would otherwise be hard-coded (the keyword list, the DNS
work-around, the sector, page limits) is settable from an environment variable,
so the behaviour can be changed from GitHub repository variables/secrets without
editing code.
"""

import os

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(os.getcwd(), "ppra_pdfs")
EXCEL_PATH   = os.path.join(BASE_DIR, "ppra_info_comm_tech.xlsx")

CREDENTIALS_PATH = os.path.join(BASE_DIR, "credentials.json")
TOKEN_PATH       = os.path.join(BASE_DIR, "token.json")

# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

PPRA_URL = "https://ppra.gov.pk/#/tenders/sectorwisetenders"
SECTOR   = os.environ.get("PPRA_SECTOR", "Info and Comm Tech")

HEADLESS = os.environ.get("PPRA_HEADLESS", "true").lower() != "false"

# Retry settings for PPRA's frequently-unreachable server.
NAV_RETRIES = int(os.environ.get("PPRA_NAV_RETRIES", "5"))
NAV_DELAY   = int(os.environ.get("PPRA_NAV_DELAY", "15"))    # seconds between attempts
ROW_RETRIES = int(os.environ.get("PPRA_ROW_RETRIES", "3"))

# 0 = scrape every page; set a small number to limit a local test run.
MAX_PAGES = int(os.environ.get("PPRA_MAX_PAGES", "0"))

# DNS work-around. PPRA's DNS resolution is intermittently broken, so the
# hostname can be pinned to a fixed IP. Such an IP is *not stable* — if PPRA
# moves servers it becomes wrong and every run fails to connect, which is a
# common reason a scraper like this silently stops working. It is therefore:
#   - optional  (set PPRA_DNS_OVERRIDE="" to disable and use normal DNS), and
#   - overridable (set PPRA_DNS_OVERRIDE to a fresh "MAP host ip" rule).
DNS_OVERRIDE = os.environ.get("PPRA_DNS_OVERRIDE", "MAP ppra.gov.pk 210.56.8.55")

# PDF download polling.
DOWNLOAD_TIMEOUT = int(os.environ.get("PPRA_DOWNLOAD_TIMEOUT", "30"))

# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------

# Configurable without a code edit: set PPRA_KEYWORDS to a comma-separated list,
# e.g. PPRA_KEYWORDS="Bank,University,Hospital". Matching is case-insensitive and
# applied to the Tender Details column.
KEYWORDS = [
    kw.strip()
    for kw in os.environ.get("PPRA_KEYWORDS", "Bank,University").split(",")
    if kw.strip()
]

# Match whole words only ("Bank" will NOT match "Embankment"). The default is a
# plain substring match; set PPRA_WHOLE_WORD=true for the stricter behaviour.
WHOLE_WORD = os.environ.get("PPRA_WHOLE_WORD", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

SUBJECT_MATCH    = "PPRA Tender Report — {n} match(es) found"
SUBJECT_NO_MATCH = "PPRA Tender Report — No matches"
