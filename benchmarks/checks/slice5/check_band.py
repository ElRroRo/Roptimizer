import os
import glob, sys
from playwright.sync_api import sync_playwright
EXE = glob.glob(os.path.expanduser("~/.cache/")
      + "ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")[0]
OUT, RUN = sys.argv[1], sys.argv[2]
errs = []
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("console", lambda m: errs.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    pg.goto(f"http://127.0.0.1:8797/results.html?run={RUN}#results", wait_until="networkidle"); pg.wait_for_timeout(1200)
    print("registered panels:", pg.evaluate("Object.keys(PANELS)"))
    pg.click("[data-menu='5']"); pg.wait_for_timeout(300)
    print("menu:", pg.eval_on_selector_all("#pmenu button", "bs => bs.map(b => b.textContent.trim())"))
    pg.click("#pmenu [data-put='band']"); pg.wait_for_timeout(600)
    pg.evaluate("sel = 'Portfolio/Equities/Technology'; draw()"); pg.wait_for_timeout(800)
    pg.screenshot(path=f"{OUT}/band.png")
    print("slot 5 text:", (pg.text_content("#slot-5") or "")[:200])
    b.close()
print("ERRORS:", len(errs)); print("\n".join(errs[:10]))
