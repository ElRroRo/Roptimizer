"""Slice 4's acceptance test in headless Chromium: build from empty, blockers clickable, Refresh data, review, run on
the laptop, then switch to the A100 and run again."""
import os
import glob, sys, time
from playwright.sync_api import sync_playwright
EXE = glob.glob(os.path.expanduser("~/.cache/")
      + "ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell")[0]
OUT, PID = sys.argv[1], sys.argv[2]
errs = []
def say(*a): print(*a, flush=True)
def follow(pg, label, limit):
    t0 = time.time()
    while time.time() - t0 < limit:
        pg.wait_for_timeout(3000)
        if "#results" in pg.url and "running" not in (pg.text_content("#meta") or ""):
            break
    say(f"{label}: {time.time() - t0:.0f} s; url {pg.url.split('/')[-1]}; meta: {pg.text_content('#meta')[:150]}")
    pg.screenshot(path=f"{OUT}/byhand-{label}.png")
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=EXE)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.on("console", lambda m: errs.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    pg.on("pageerror", lambda e: errs.append(f"pageerror: {e}"))
    pg.goto(f"http://127.0.0.1:8797/builder.html?p={PID}", wait_until="networkidle")
    pg.evaluate("localStorage.setItem('mso.machine', 'laptop')")
    pg.reload(wait_until="networkidle"); pg.wait_for_timeout(800)
    pg.click("#addg"); pg.fill("#f-n", "Defensive"); pg.keyboard.press("Tab")
    for t, eq in (("SPY", "8.6"), ("TLT", "5")):
        pg.click("#adda"); pg.fill("#f-t", t); pg.keyboard.press("Tab"); pg.fill("#f-eq", eq); pg.keyboard.press("Tab")
    pg.evaluate("select(ROOT.id)")
    pg.click("#adda"); pg.fill("#f-t", "GLD"); pg.keyboard.press("Tab"); pg.fill("#f-eq", "6"); pg.keyboard.press("Tab")
    pg.wait_for_timeout(1500)
    items = pg.eval_on_selector_all("#checks li", "ls => ls.map(l => l.textContent)")
    say("blockers before Refresh data:", items)
    li = pg.query_selector("#checks li:has-text('GLD')")
    if li:
        li.click(); pg.wait_for_timeout(500)
        say("clicking the GLD blocker selects:", pg.text_content("#insp .ih h2"))
    pg.screenshot(path=f"{OUT}/byhand-built.png")
    pg.wait_for_timeout(1200)   # the save (debounced 700 ms)
    pg.click("#refresh")
    pg.wait_for_load_state("networkidle"); pg.wait_for_timeout(4000)
    say("after Refresh data:", pg.text_content("#state"), "| blockers:", pg.eval_on_selector_all("#checks li", "ls => ls.map(l => l.textContent)"))
    pg.click("#review"); pg.wait_for_timeout(1500)
    say("review:", pg.text_content("#state"), "|", pg.eval_on_selector("#rv-run", "b => b.title"))
    pg.screenshot(path=f"{OUT}/byhand-review.png")
    pg.click("#rv-run"); pg.wait_for_url("**/results.html?run=*", timeout=60000)
    follow(pg, "laptop", 600)
    pg.goto(pg.url.replace("#results", "#progress"), wait_until="networkidle"); pg.wait_for_timeout(1000)
    pg.click("[data-m='a100']"); pg.wait_for_timeout(300)
    say("next machine stored:", pg.evaluate("localStorage.getItem('mso.machine')"))
    pg.click("#again"); pg.wait_for_url("**/builder.html*", timeout=30000); pg.wait_for_timeout(2500)
    say("Run again opened:", pg.url.split('/')[-1], "|", pg.text_content(".top h1"), "|", pg.eval_on_selector("#rv-run", "b => b.title"))
    pg.click("#rv-run"); pg.wait_for_url("**/results.html?run=*", timeout=60000)
    pg.wait_for_timeout(15000); pg.screenshot(path=f"{OUT}/byhand-a100-progress.png")
    say("A100 progress:", pg.text_content("#prog-sub"))
    follow(pg, "a100", 1200)
    b.close()
say("ERRORS:", len(errs)); say("\n".join(errs[:15]))
