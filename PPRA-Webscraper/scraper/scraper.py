"""
PPRA tender scraper.

Navigates the sector-wise tender listing, paginates through all pages,
extracts tender metadata from each row and downloads attached PDF documents.
"""

from __future__ import annotations

import os
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from scraper.config import (
    PPRA_URL, SECTOR, DOWNLOAD_DIR, MAX_PAGES,
    NAV_RETRIES, NAV_DELAY, ROW_RETRIES, DOWNLOAD_TIMEOUT,
)
from scraper.util import normalize_tender_no, pdf_filename


# ---------------------------------------------------------------------------
# Spinners and waits
# ---------------------------------------------------------------------------

def wait_for_spinner(wait) -> None:
    """Block until Angular's loading overlay is gone."""
    try:
        wait.until(EC.invisibility_of_element_located(
            (By.XPATH, "//div[contains(@class,'ngx-spinner-overlay')]")
        ))
    except TimeoutException:
        pass


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def safe_navigate(driver, wait, url: str = PPRA_URL) -> None:
    """
    Navigate to `url` with up to NAV_RETRIES attempts.
    Exits the process if all attempts fail — the GitHub Actions log will
    capture the error and the run will be marked as failed.
    """
    for attempt in range(1, NAV_RETRIES + 1):
        try:
            print(f"[Attempt {attempt}/{NAV_RETRIES}] Navigating to {url}")
            driver.get(url)
            print("Page loaded.")
            return
        except Exception as exc:
            print(f"Attempt {attempt} failed: {exc}")
            if attempt == NAV_RETRIES:
                driver.quit()
                raise SystemExit("All navigation attempts failed.")
            time.sleep(NAV_DELAY)


def select_sector(driver, wait, sector: str = SECTOR) -> None:
    """
    Click the correct sector link in the sidebar.
    The sector list itself may be paginated, so the function advances the
    sidebar's own pagination if the target sector is not visible on the
    current page.
    """
    while True:
        wait_for_spinner(wait)
        try:
            link = wait.until(EC.element_to_be_clickable(
                (By.XPATH, f"//a[contains(text(),'{sector}')]")
            ))
            driver.execute_script("arguments[0].click();", link)
            return
        except TimeoutException:
            try:
                wait_for_spinner(wait)
                next_btn = wait.until(EC.element_to_be_clickable(
                    (By.XPATH, "//li[@class='page-item']/a[contains(text(),'Next')]")
                ))
                driver.execute_script("arguments[0].click();", next_btn)
                wait_for_spinner(wait)
            except TimeoutException:
                driver.quit()
                raise SystemExit(f"Sector '{sector}' not found.")


def get_total_pages(driver, wait) -> int:
    try:
        xpath = "//small[contains(text(),'Total Pages')]/strong"
        text  = wait.until(EC.presence_of_element_located((By.XPATH, xpath))).text.strip()
        return int(text)
    except Exception:
        return 1


def advance_to_next_page(driver, wait) -> bool:
    """Click Next; return False if there is no Next button."""
    wait_for_spinner(wait)
    try:
        btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//a[contains(text(),'Next')]")
        ))
        driver.execute_script("arguments[0].click();", btn)
        time.sleep(1)
        return True
    except TimeoutException:
        return False


# ---------------------------------------------------------------------------
# Row scraping
# ---------------------------------------------------------------------------

def _download_row_pdfs(driver, cols, tender_no: str, download_dir: str) -> None:
    """Trigger all PDF downloads in the fourth column of a tender row."""
    fourth_col  = cols[3]
    before_files = set(os.listdir(download_dir))
    icons = fourth_col.find_elements(
        By.XPATH, ".//i[contains(@class,'fa-file-download')]"
    )
    for icon in icons:
        try:
            parent_a = icon.find_element(By.XPATH, "./parent::a")
            if parent_a.get_attribute("href") == "javascript:void(0)":
                continue

            new_path = os.path.join(download_dir, pdf_filename(tender_no))
            if os.path.exists(new_path):
                continue

            driver.execute_script("arguments[0].click();", icon)

            # Poll until a new file appears in the download directory
            deadline = time.time() + DOWNLOAD_TIMEOUT
            new_file = None
            while time.time() < deadline:
                after_files = set(os.listdir(download_dir))
                diff = after_files - before_files
                if diff:
                    new_file = diff.pop()
                    break
                time.sleep(0.5)

            if new_file:
                old_path = os.path.join(download_dir, new_file)
                ext      = os.path.splitext(new_file)[1] or ".pdf"
                # sanitise: tender numbers contain '/', which would break rename
                os.rename(old_path, os.path.join(download_dir, pdf_filename(tender_no, ext)))
        except Exception:
            pass


def scrape_current_page(driver, download_dir: str = DOWNLOAD_DIR) -> list[dict]:
    """
    Extract tender data from all rows on the currently visible page.
    Returns a list of row dicts.
    """
    rows_xpath = "//tr[contains(@class, 'ng-star-inserted')]"
    rows       = driver.find_elements(By.XPATH, rows_xpath)
    page_data: list[dict] = []

    for i in range(len(rows)):
        for attempt in range(ROW_RETRIES):
            try:
                rows = driver.find_elements(By.XPATH, rows_xpath)
                row  = rows[i]
                cols = row.find_elements(By.TAG_NAME, "td")

                if len(cols) < 6:
                    break

                tender_no = normalize_tender_no(cols[1].text)
                page_data.append({
                    "Sr No":              cols[0].text.strip(),
                    "Tender No":          tender_no,
                    "Tender Details":     cols[2].text.strip(),
                    "Advertisement Date": cols[4].text.strip(),
                    "Closing Date":       cols[5].text.strip(),
                })

                _download_row_pdfs(driver, cols, tender_no, download_dir)
                break

            except Exception:
                time.sleep(1)
                if attempt == ROW_RETRIES - 1:
                    break

    return page_data


# ---------------------------------------------------------------------------
# Full scrape
# ---------------------------------------------------------------------------

def run_scrape(driver, wait, download_dir: str = DOWNLOAD_DIR,
               max_pages: int = MAX_PAGES) -> list[dict]:
    """
    Navigate PPRA, select the configured sector and scrape its pages.
    Returns the full list of tender dicts. `max_pages` (0 = all) caps the number
    of pages, which is handy for a quick local test run.
    """
    wait_for_spinner(wait)
    select_sector(driver, wait)
    wait_for_spinner(wait)
    wait.until(EC.presence_of_element_located(
        (By.XPATH, "//tr[contains(@class, 'ng-star-inserted')]")
    ))

    total_pages = get_total_pages(driver, wait)
    if max_pages and max_pages > 0:
        total_pages = min(total_pages, max_pages)
    print(f"Scraping {total_pages} page(s)"
          + (f" (capped at {max_pages})" if max_pages else "") + " ...")

    all_data: list[dict] = []
    for page in range(1, total_pages + 1):
        print(f"Scraping page {page}/{total_pages} ...")
        all_data.extend(scrape_current_page(driver, download_dir))
        if page < total_pages:
            if not advance_to_next_page(driver, wait):
                break

    return all_data
