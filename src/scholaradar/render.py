from __future__ import annotations

import importlib
import logging

log = logging.getLogger(__name__)


def browser_available() -> bool:
    try:
        importlib.import_module("playwright.sync_api")
    except ImportError:
        return False
    return True


def render_page(url: str, user_agent: str, timeout_seconds: float = 30.0, wait_ms: int = 3000) -> bytes | None:
    if not browser_available():
        log.warning("render requested for %s but playwright is not installed (uv sync --extra browser; playwright install chromium)", url)
        return None
    sync_api = importlib.import_module("playwright.sync_api")
    with sync_api.sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=user_agent)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_seconds * 1000))
            except sync_api.TimeoutError:
                log.info("render: %s did not finish loading in %.0fs, using what rendered so far", url, timeout_seconds)
            try:
                page.wait_for_load_state("networkidle", timeout=int(timeout_seconds * 1000 / 2))
            except sync_api.TimeoutError:
                pass
            page.wait_for_timeout(wait_ms)
            html = page.content()
        except sync_api.Error as exc:
            log.warning("render failed for %s: %s", url, str(exc).splitlines()[0][:160])
            return None
        finally:
            browser.close()
    return html.encode("utf-8")
