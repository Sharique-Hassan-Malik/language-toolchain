"""Headless Chrome driver construction.

Two robustness choices:

  * **Driver resolution via Selenium Manager.** Selenium ≥ 4.6 ships a manager
    that downloads the matching chromedriver automatically. Always using
    `webdriver-manager` frequently fetches a driver that doesn't match the Chrome
    that `setup-chrome` installed — a classic "session not created: version
    mismatch" failure. Here Selenium Manager is tried first, with
    `webdriver-manager` kept only as a fallback if it happens to be installed.

  * **Optional DNS override.** The hostname→IP pin is only applied when
    configured (see `config.DNS_OVERRIDE`), so a stale IP no longer forces every
    run to fail — clearing the variable falls back to normal DNS.

Selenium is imported lazily so the rest of the package can be imported (and
unit-tested) without Selenium installed.
"""

from __future__ import annotations

from scraper.config import DNS_OVERRIDE, DOWNLOAD_DIR, HEADLESS


def build_driver(download_dir: str = DOWNLOAD_DIR, headless: bool = HEADLESS):
    """Return ``(driver, wait)`` — a Chrome driver set up for silent PDF
    downloads and a 60-second `WebDriverWait`."""
    import os

    from selenium import webdriver
    from selenium.webdriver.support.ui import WebDriverWait

    os.makedirs(download_dir, exist_ok=True)

    options = webdriver.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--dns-prefetch-disable")
    if DNS_OVERRIDE:                                    # optional; empty disables it
        options.add_argument(f"--host-resolver-rules={DNS_OVERRIDE}")

    options.add_experimental_option("prefs", {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "plugins.always_open_pdf_externally": True,
        "profile.default_content_setting_values.automatic_downloads": 1,
    })

    driver = _make_chrome(options)
    driver.set_page_load_timeout(180)
    return driver, WebDriverWait(driver, 60)


def _make_chrome(options):
    """Prefer Selenium Manager (built into Selenium ≥ 4.6); fall back to
    webdriver-manager only if it is installed."""
    from selenium import webdriver

    try:
        return webdriver.Chrome(options=options)       # Selenium Manager resolves the driver
    except Exception as exc:
        try:
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            print(f"Selenium Manager failed ({exc}); falling back to webdriver-manager.")
            return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        except Exception:
            raise
