import os
import glob, sys, json, urllib.request
from playwright.sync_api import sync_playwright
EXE = glob.glob(os.path.expanduser("~/.cache/")
      + "ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")[0]
OUT, PID = sys.argv[1], sys.argv[2]
api = lambda path: json.load(urllib.request.urlopen("http://127.0.0.1:8797/api" + path))
errs = []
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("console", lambda m: errs.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    pg.goto(f"http://127.0.0.1:8797/jumpdb.html?p={PID}", wait_until="networkidle"); pg.wait_for_timeout(1500)
    pg.screenshot(path=f"{OUT}/jumpdb.png")
    print("meta:", pg.text_content("#meta"))
    print("pool header:", pg.text_content("#p-pool").split("×")[0][:120] if pg.query_selector("#p-pool") else "")
    first = pg.query_selector("[data-tog]"); t = first.get_attribute("data-tog"); first.click(); pg.wait_for_timeout(1500)
    print(f"dropped {t}: server pool has it?", t in api("/jumpdb/pool")["tickers"], "| size", len(api("/jumpdb/pool")["tickers"]))
    pg.click(f"[data-tog='{t}']"); pg.wait_for_timeout(1500)
    print(f"put back {t}: server pool has it?", t in api("/jumpdb/pool")["tickers"], "| size", len(api("/jumpdb/pool")["tickers"]))
    ov = pg.query_selector("[data-ov='IBHK:crash']"); ov.fill("0.5"); ov.press("Tab"); pg.wait_for_timeout(1200)
    print("override IBHK crash 0.5 on the server:", api("/betas?tickers=IBHK")["IBHK"]["crash_beta"], api("/betas?tickers=IBHK")["IBHK"]["crash_source"])
    ov = pg.query_selector("[data-ov='IBHK:crash']"); ov.fill(""); ov.press("Tab"); pg.wait_for_timeout(1200)
    print("override cleared:", api("/betas?tickers=IBHK")["IBHK"]["crash_source"])
    pg.click("#pin"); pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(1500)
    print("after Pin:", pg.text_content("#meta"), "| portfolio run:", api(f"/portfolios/{PID}")["run"].get("jump_version"))
    pg.click("#pin"); pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(1500)
    print("after Unpin:", api(f"/portfolios/{PID}")["run"].get("jump_version"))
    b.close()
print("ERRORS:", len(errs)); print("\n".join(errs[:10]))
