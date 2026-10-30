import os
import glob, sys, json
from playwright.sync_api import sync_playwright
EXE = glob.glob(os.path.expanduser("~/.cache/")
      + "ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")[0]
OUT, RUN = sys.argv[1], sys.argv[2]
errs = []
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("console", lambda m: errs.append(f"console.{m.type}: {m.text}") if m.type in ("error",) else None)
    pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    for v in ("results", "progress", "builder", "compare", "diag"):
        pg.goto(f"http://127.0.0.1:8797/results.html?run={RUN}#{v}", wait_until="networkidle")
        pg.wait_for_timeout(1200)
        pg.screenshot(path=f"{OUT}/res-{v}.png")
        errs.append(f"-- {v}: meta = {pg.text_content('#meta')[:120]}")
    b.close()
print("\n".join(errs))
