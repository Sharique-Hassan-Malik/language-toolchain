"""Small pure helpers, kept dependency-free so they can be unit-tested without
Selenium or any of the report/email stack installed."""

from __future__ import annotations

import re

# characters that are illegal (or troublesome) in a filename on Linux/Windows
_ILLEGAL_FS = r'[/\\:*?"<>|\r\n\t]'


def normalize_tender_no(raw: str) -> str:
    """Clean a raw tender-number cell: drop the stray 'View Invoice' text the
    PPRA table injects, and collapse surrounding whitespace."""
    return re.sub(r"\s+", " ", raw.replace("View Invoice", "")).strip()


def pdf_filename(tender_no: str, ext: str = ".pdf") -> str:
    """A safe on-disk filename for a tender's PDF.

    PPRA tender numbers routinely contain a slash (e.g. ``TS123/2025``). Using
    ``f"{tender_no}.pdf"`` directly would make ``os.rename`` treat the slash as a
    directory separator and fail silently — meaning the PDF is never attached to
    the email. Sanitising the number to a flat filename avoids that.
    """
    safe = re.sub(_ILLEGAL_FS, "-", tender_no).strip().strip("-")
    return f"{safe or 'tender'}{ext}"
