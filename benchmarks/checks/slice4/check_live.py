"""Builder -> review -> Run (laptop) -> live progress -> results -> diagnostics, in headless Chromium."""
import os
import glob, sys, time
from playwright.sync_api import sync_playwright
EXE = glob.glob(os.path.expanduser("~/.cache/")
      + "ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")[0]
OUT, PID = sys.argv[1], sys.argv[2]
errs = []
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("console", lambda m: errs.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    pg.goto(f"http://127.0.0.1:8797/builder.html?p={PID}", wait_until="networkidle")
    pg.evaluate("localStorage.setItem('mso.machine', 'laptop')")
    pg.goto(f"http://127.0.0.1:8797/builder.html?p={PID}#review", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    pg.screenshot(path=f"{OUT}/live-review.png")
    print("review state:", pg.text_content("#state"), "| run title:", pg.eval_on_selector("#rv-run", "b => b.title"))
    pg.click("#rv-run")
    pg.wait_for_url("**/results.html?run=*", timeout=30000)
    print("progress page:", pg.url)
    t0 = time.time(); shot = False
    while time.time() - t0 < 600:
        pg.wait_for_timeout(2000)
        if "#results" in pg.url:
            break
        sub = pg.text_content("#prog-sub") if pg.query_selector("#prog-sub") else ""
        if not shot and "generation" in (pg.text_content("#st-search") or ""):
            pg.screenshot(path=f"{OUT}/live-progress.png"); shot = True
            print("mid-run:", sub, "|", pg.text_content("#st-search"), "|", pg.text_content("#st-bank"))
    pg.wait_for_timeout(2500)
    print("after the run:", pg.url, "| meta:", pg.text_content("#meta")[:140])
    pg.screenshot(path=f"{OUT}/live-results.png")
    pg.goto(pg.url.replace("#results", "#diag"), wait_until="networkidle"); pg.wait_for_timeout(1500)
    pg.screenshot(path=f"{OUT}/live-diag.png")
    b.close()
print("ERRORS:", len(errs)); print("\n".join(errs[:15]))
