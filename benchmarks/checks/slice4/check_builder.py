"""Open the builder and the review in headless Chromium: console errors, page errors, screenshots, state text."""
import os
import glob, sys, json
from playwright.sync_api import sync_playwright
EXE = glob.glob(os.path.expanduser("~/.cache/")
      + "ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")[0]
OUT = sys.argv[1]
errs = []
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("console", lambda m: errs.append(f"console.{m.type}: {m.text}") if m.type in ("error", "warning") else None)
    pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    pg.goto("http://127.0.0.1:8797/builder.html", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    pg.screenshot(path=f"{OUT}/builder.png")
    info = dict(meta=pg.text_content("#meta"), state=pg.text_content("#state"), checks=pg.text_content("#checks"),
                portfolios=pg.eval_on_selector_all("#preset option", "os => os.map(o => o.textContent)"))
    pg.click("#review")
    pg.wait_for_timeout(1500)
    pg.screenshot(path=f"{OUT}/review.png")
    info.update(review_state=pg.text_content("#state"), run_disabled=pg.eval_on_selector("#rv-run", "b => b.disabled"),
                run_title=pg.eval_on_selector("#rv-run", "b => b.title"))
    b.close()
print(json.dumps(info, indent=1)[:2000])
print("ERRORS:", len(errs)); print("\n".join(errs[:20]))
