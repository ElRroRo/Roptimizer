import os
import glob, sys, json, urllib.request
from playwright.sync_api import sync_playwright
EXE = glob.glob(os.path.expanduser("~/.cache/")
      + "ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")[0]
OUT, RUN = sys.argv[1], sys.argv[2]
api = lambda path: json.load(urllib.request.urlopen("http://127.0.0.1:8797/api" + path))
errs = []
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("console", lambda m: errs.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    pg.goto(f"http://127.0.0.1:8797/results.html?run={RUN}#builder", wait_until="networkidle"); pg.wait_for_timeout(1200)
    print("money panel:", pg.text_content("#p-money")[:160])
    box = pg.query_selector("[data-ta='BTC=F']"); box.fill("IBIT"); box.press("Tab"); pg.wait_for_timeout(4000)
    row = pg.eval_on_selector("[data-ta='BTC=F']", "i => i.closest('tr').textContent")
    print("BTC=F row with IBIT:", " ".join(row.split()))
    pid = api(f"/runs/{RUN}")["portfolio_id"]
    print("saved trade_as:", api(f"/portfolios/{pid}")["assets"]["BTC=F"]["trade_as"])
    pg.screenshot(path=f"{OUT}/shares.png")
    box = pg.query_selector("[data-ta='BTC=F']"); box.fill(""); box.press("Tab"); pg.wait_for_timeout(1500)
    print("cleared:", api(f"/portfolios/{pid}")["assets"]["BTC=F"]["trade_as"])
    b.close()
print("ERRORS:", len(errs)); print("\n".join(errs[:10]))
