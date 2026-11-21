import os
import sys
import threading
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lumen import server

ART_DIR = Path(r"%USERPROFILE%\.gemini\antigravity\brain\1a76a60b-5a44-447e-8b6f-705091664e6b")


def test_monitor_ui():
    httpd = server.serve()
    port = httpd.server_port
    url = f"http://127.0.0.1:{port}/"

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        page.goto(url, wait_until="networkidle")

        monitor_btn = page.locator("#open-monitor")
        assert monitor_btn.is_visible()

        monitor_btn.click()
        page.wait_for_timeout(700)

        popover = page.locator("#sys-monitor-pop")
        assert popover.is_visible()

        shot_path_full = ART_DIR / "monitor_panel_full.png"
        shot_path_pop = ART_DIR / "monitor_panel_popover.png"

        popover.screenshot(path=str(shot_path_pop))
        page.screenshot(path=str(shot_path_full))
        print("Screenshots salvas!")

        browser.close()

    print("Sucesso!")


if __name__ == "__main__":
    test_monitor_ui()
    os._exit(0)
