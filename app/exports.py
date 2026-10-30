"""Exports of a finished run (#8): the Excel workbook, the PDF report, the builder CSV, and the images the PDF and
extensions (app/extensions) share.

House rules for the workbook: gridlines hidden on every sheet, never frozen panes; numbers stay numbers (formats,
not text); every sheet states the market-data day and the jump version it came from.
Charts are drawn with matplotlib in the tool's Tokyo Night tokens (the same fan and drawdown the room shows).
"""
import csv
import datetime as dt
import io
import math

INK, INK2, MUTE, PANEL, BG, FRAME = "#c0caf5", "#a9b1d6", "#565f89", "#1f2335", "#1a1b26", "#3b4261"
PALETTE = ["#e0af68", "#bb9af7", "#9ece6a", "#f7768e", "#7dcfff", "#ff9e64", "#73daca", "#7aa2f7"]


def _stamp(res, rec):
    inp = res.get("inputs", {})
    return dict(data_day=inp.get("data_day") or inp.get("created") or "", data_downloaded=inp.get("data_downloaded") or "",
                jump_version=inp.get("jump_version") or "frozen inputs", machine=rec.get("machine"), gpu=res.get("gpu"),
                bank=res["config"]["bank"], finished=rec.get("ended") or res.get("created"))


def _name(r):
    return " / ".join(r["path"][1:]) or r["path"][0]


def shares(res, budget=100000.0, trade_as=None, prices=None):
    """Builder lines: dollars = effective weight x budget; shares = dollars / price, rounded DOWN to two decimals,
    so the total never exceeds the budget (#8). prices: {ticker: (price, time)} incl. trade-as tickers."""
    trade_as, prices = trade_as or {}, prices or {}
    out = []
    for r in res["rows"]:
        if r["kind"] != "asset":
            continue
        t = r["name"]
        buy = trade_as.get(t) or t
        p, when = prices.get(buy, (None, None))
        dollars = r["effective"] * budget
        n = math.floor(dollars / p * 100) / 100 if p else None
        out.append(dict(ticker=t, trade_as=buy if buy != t else "", price=p, price_time=when, weight=r["effective"],
                        target=dollars, shares=n, spent=(n * p) if n is not None else 0.0,
                        futures_unmapped=t.endswith("=F") and not trade_as.get(t)))
    return out


def builder_csv(lines):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ticker", "trade_as", "shares", "dollars", "price", "price_time"])
    for x in lines:
        w.writerow([x["ticker"], x["trade_as"] or x["ticker"], "" if x["shares"] is None else f"{x['shares']:.2f}",
                    f"{x['spent']:.2f}", "" if x["price"] is None else x["price"], x["price_time"] or ""])
    return buf.getvalue().encode()


# ------------------------------------------------------------------ the workbook

def xlsx(res, rec, model, lines, budget):
    import xlsxwriter
    st = _stamp(res, rec)
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    title = wb.add_format({"bold": True, "font_size": 13})
    mute = wb.add_format({"font_color": "#666666", "italic": True})
    head = wb.add_format({"bold": True, "bottom": 1, "text_wrap": True, "valign": "bottom"})
    pct = wb.add_format({"num_format": "0.00%"})
    pctb = wb.add_format({"num_format": "0.00%", "bold": True})
    num4 = wb.add_format({"num_format": "0.0000"})
    num3 = wb.add_format({"num_format": "0.000"})
    money = wb.add_format({"num_format": "#,##0.00"})
    sh2 = wb.add_format({"num_format": "0.00"})
    bold = wb.add_format({"bold": True})

    def sheet(name, cols):
        ws = wb.add_worksheet(name)
        ws.hide_gridlines(2)                      # gridlines hidden on every sheet; panes are never frozen
        ws.write(0, 0, f"{rec.get('portfolio_name', 'Portfolio')}: {name}", title)
        ws.write(1, 0, f"Run {rec['id']} on the {('Colab A100' if st['machine'] == 'a100' else 'laptop')} ({st['gpu']}), "
                       f"finished {st['finished']}; market data of {st['data_day']} {st['data_downloaded']}; "
                       f"jump database {st['jump_version']}; {st['bank']:,}-path bank; 12-week figures on held-out paths.", mute)
        for i, (c, w) in enumerate(cols):
            ws.write(3, i, c, head)
            ws.set_column(i, i, w)
        ws.set_row(3, 30)
        return ws

    # 1. the tree
    ws = sheet("Tree", [("Part", 34), ("Share of parent", 11), ("Effective weight", 11), ("Expected 12w", 11), ("Volatility 12w", 11),
                        ("VaR 5%", 10), ("CVaR 5%", 10), ("CDaR 5%", 10), ("UPI", 8), ("Implied (annual)", 11),
                        ("Blended (annual)", 11), ("Binding limits", 40), ("Search", 30)])
    for i, r in enumerate(res["rows"]):
        m, y = r.get("metrics") or {}, 4 + i
        fmt_name = bold if r["kind"] == "group" else None
        ws.write(y, 0, "    " * (len(r["path"]) - 1) + r["name"], fmt_name)
        ws.write_number(y, 1, r["share"], pct)
        ws.write_number(y, 2, r["effective"], pctb if r["kind"] == "group" else pct)
        for j, k in enumerate(("er_12w", "vol_12w", "var", "cvar", "cdar")):
            if m.get(k) is not None:
                ws.write_number(y, 3 + j, m[k], pct)
        if m.get("upi") is not None:
            ws.write_number(y, 8, m["upi"], num3)
        if r.get("implied_annual") is not None:
            ws.write_number(y, 9, r["implied_annual"], pct)
            ws.write_number(y, 10, r["blended_annual"], pct)
        s = r.get("search") or {}
        if s.get("binding"):
            ws.write(y, 11, "; ".join(b["text"] for b in s["binding"]))
        if s:
            ws.write(y, 12, f"{s.get('generations', 0)} generations, {s.get('stopped', '')}")

    # 1b. the evaluation ratios (mso/report.py; none but UPI is optimized)
    RAT = [("sharpe_ann", "Sharpe (annualized)", num3), ("sortino_ann", "Sortino (annualized)", num3), ("sharpe", "Sharpe 12w", num3),
           ("sortino", "Sortino 12w", num3), ("upi", "UPI", num3), ("starr", "STARR", num3), ("calmar", "Calmar", num3),
           ("martin", "Martin", num3), ("omega", "Omega", num3), ("rachev", "Rachev", num3), ("skew", "Skewness", num3),
           ("kurt", "Excess kurtosis", num3), ("p_loss", "Chance of a loss", pct), ("p_below_rf", "Chance below risk-free", pct),
           ("downside_dev", "Downside deviation", pct), ("avg_mdd", "Average worst drawdown", pct), ("ulcer", "Ulcer index", pct)]
    ws = sheet("Ratios", [("Part", 34)] + [(label, 11) for _, label, _ in RAT])
    ws.write(2, 0, "Numerators are the expected 12-week excess return over the risk-free rate, as in UPI; Omega and Rachev "
                   "are the simulated distribution's own. Annualized by the square root of 52/12. Only UPI drives the search.", mute)
    rf = res.get("rf_12w")
    for i, r in enumerate(res["rows"]):
        m, y = dict(r.get("metrics") or {}), 4 + i
        if "sharpe" not in m and rf is not None:          # a run older than the ratios: the two its figures give exactly
            ex = m["er_12w"] - rf
            m.update(sharpe=ex / m["vol_12w"] if m["vol_12w"] > 0 else None, starr=ex / -m["cvar"] if m["cvar"] < 0 else None)
            m["sharpe_ann"] = None if m["sharpe"] is None else m["sharpe"] * (52 / 12) ** 0.5
        ws.write(y, 0, "    " * (len(r["path"]) - 1) + r["name"], bold if r["kind"] == "group" else None)
        for j, (k, _, f) in enumerate(RAT):
            if m.get(k) is not None:
                ws.write_number(y, 1 + j, m[k], f)

    # 2. the builder
    ws = sheet("Builder", [("Asset", 10), ("Trade as", 10), ("Price", 12), ("Price time", 22), ("Weight", 10), ("Target $", 14),
                           ("Shares", 12), ("Spent $", 14)])
    ws.write(2, 0, f"Portfolio size ${budget:,.0f}; shares rounded down to two decimals, so the total never exceeds it.", mute)
    for i, x in enumerate(lines):
        y = 4 + i
        ws.write(y, 0, x["ticker"])
        ws.write(y, 1, x["trade_as"] or ("set a trade-as ticker (futures)" if x["futures_unmapped"] else ""))
        if x["price"] is not None:
            ws.write_number(y, 2, x["price"], money)
        ws.write(y, 3, x["price_time"] or "")
        ws.write_number(y, 4, x["weight"], pct)
        ws.write_number(y, 5, x["target"], money)
        if x["shares"] is not None:
            ws.write_number(y, 6, x["shares"], sh2)
        ws.write_number(y, 7, x["spent"], money)
    y = 4 + len(lines)
    ws.write(y, 6, "Spent", bold)
    ws.write_formula(y, 7, f"=SUM(H5:H{y})", money)
    ws.write(y + 1, 6, "Left over", bold)
    ws.write_formula(y + 1, 7, f"={budget}-H{y + 1}", money)

    # 3. assets: metrics, betas and the volatility model
    ws = sheet("Assets", [("Asset", 10), ("Effective weight", 11), ("Posterior (annual)", 11), ("Expected 12w", 11), ("Volatility 12w", 11),
                          ("CVaR 5%", 10), ("CDaR 5%", 10), ("Crash beta", 9), ("Rally beta", 9), ("Co-jump", 9),
                          ("Heston v0", 10), ("Heston theta", 10), ("kappa", 8), ("xi", 8), ("rho", 8), ("Fit", 40)])
    T = model.get("tickers") or []
    post = dict(zip(T, model.get("posterior_annual") or []))
    jb = model.get("jump_betas") or {}
    crash, rally = dict(zip(T, jb.get("crash") or [])), dict(zip(T, jb.get("rally") or []))
    cj = dict(zip(T, model.get("cojump_mults") or []))
    H = model.get("heston") or {}
    for i, r in enumerate([r for r in res["rows"] if r["kind"] == "asset"]):
        y, t, m = 4 + i, r["name"], r["metrics"]
        ws.write(y, 0, t)
        ws.write_number(y, 1, r["effective"], pct)
        if t in post:
            ws.write_number(y, 2, post[t], pct)
        for j, k in enumerate(("er_12w", "vol_12w", "cvar", "cdar")):
            ws.write_number(y, 3 + j, m[k], pct)
        for j, d in enumerate((crash, rally, cj)):
            if t in d:
                ws.write_number(y, 7 + j, d[t], num3)
        h = H.get(t) or {}
        for j, k in enumerate(("v0", "theta", "kappa", "xi", "rho")):
            if h.get(k) is not None:
                ws.write_number(y, 10 + j, h[k], num4)
        ws.write(y, 15, "; ".join(h.get("at_bound") or []) or ("" if h.get("source", "fit") == "fit" else h["source"]))

    # 4. inputs with their sources
    ws = sheet("Inputs", [("Asset or subportfolio", 30), ("Equilibrium (annual)", 12), ("View", 14), ("Below / above", 16),
                          ("Horizon (months)", 10), ("Idiosyncratic jumps", 12), ("Trade as", 10)])
    P = res.get("portfolio") or {}
    y = 4
    for t, a in (P.get("assets") or {}).items():
        ws.write(y, 0, t)
        if a.get("equilibrium") is not None:
            ws.write_number(y, 1, a["equilibrium"], pct)
        v = a.get("view")
        if v:
            ws.write(y, 2, f"{'price ' + format(v['value'], ',.2f') if v.get('form') == 'price' else format(v['value'], '.2%')}")
            ws.write(y, 3, f"-{v.get('minus')} / +{v.get('plus')} ({v.get('unit_minus') or v.get('unit', 'points')})")
            ws.write_number(y, 4, float(v.get("horizon_months", 12)))
        ws.write(y, 5, "exempt" if a.get("exclude_idio_jump") else "on")
        ws.write(y, 6, a.get("trade_as") or "")
        y += 1
    y += 1
    ws.write(y, 0, "Settings of each search (value, source)", bold)
    y += 1
    for r in res["rows"]:
        s = (r.get("search") or {}).get("settings")
        if not s:
            continue
        ws.write(y, 0, _name(r), bold)
        ws.write(y, 1, "; ".join(f"{k} {v['value']} ({v['source']})" for k, v in s.items()))
        y += 1

    # 5. the run record
    ws = sheet("Run", [("Field", 26), ("Value", 60)])
    rows = [("Run id", rec["id"]), ("Portfolio", rec.get("portfolio_name")), ("Machine", f"{st['machine']} ({st['gpu']})"),
            ("Queued", rec.get("queued")), ("Started", rec.get("started")), ("Finished", rec.get("ended")),
            ("Wall time, s", rec.get("wall_s")), ("Scenario bank, paths", res["config"]["bank"]),
            ("Searched paths", res["config"]["train"]), ("Draw per generation", res["config"].get("draw")),
            ("Searches", res.get("searches")), ("Seed", res.get("seed")), ("Market data", f"{st['data_day']} {st['data_downloaded']}"),
            ("Jump database", st["jump_version"]), ("Risk-free over 12 weeks", res.get("rf_12w"))]
    if rec.get("colab"):
        c = rec["colab"]
        rows += [("Colab session", c.get("session")), ("CU measured", c.get("cu_measured") if c.get("cu_measured") is not None
                                                        else "not booked by Colab yet"), ("CU at 5.30 CU/h", c.get("cu_at_rate"))]
    for i, (k, v) in enumerate(rows):
        ws.write(4 + i, 0, k, bold)
        if isinstance(v, (int, float)) and v is not None:
            ws.write_number(4 + i, 1, v)
        else:
            ws.write(4 + i, 1, "" if v is None else str(v))
    wb.close()
    return buf.getvalue()


# ------------------------------------------------------------------ images (the PDF, and extensions that share a run)

def _fig(w, h):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 8, "text.color": INK, "axes.labelcolor": INK2,
                         "xtick.color": MUTE, "ytick.color": MUTE, "axes.edgecolor": FRAME})
    fig, ax = plt.subplots(figsize=(w, h), dpi=160)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    return fig, ax, plt


def fan_png(row, label="Portfolio"):
    fig, ax, plt = _fig(5.2, 2.8)
    f = row["fan"]
    x = list(range(len(f["0.5"])))
    pc = lambda q: [100 * (v - 1) for v in f[q]]
    ax.fill_between(x, pc("0.05"), pc("0.95"), color=INK2, alpha=0.18, lw=0)
    ax.fill_between(x, pc("0.25"), pc("0.75"), color=INK2, alpha=0.32, lw=0)
    ax.plot(x, pc("0.5"), color=INK, lw=1.4)
    ax.axhline(0, color=FRAME, lw=0.8)
    ax.set_title(f"{label}: outcome fan over 12 weeks, 5-95th percentiles (%)", loc="left", fontsize=8.5)
    ax.set_xlabel("weeks")
    for q in ("0.05", "0.5", "0.95"):
        v = pc(q)[-1]
        ax.annotate(f"{v:+.1f}%", (x[-1], v), xytext=(4, 0), textcoords="offset points", fontsize=7.5, color=INK, va="center")
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()


def dd_png(row, label="Portfolio"):
    fig, ax, plt = _fig(5.2, 2.6)
    h = row["dd_hist"]
    e, c = h["edges"], h["counts"]
    mids = [100 * (a + b) / 2 for a, b in zip(e[:-1], e[1:])]
    ax.bar(mids, c, width=100 * (e[1] - e[0]) * 0.92, color=INK2, alpha=0.7)
    cd = 100 * row["metrics"]["cdar"]
    ax.axvline(cd, color="#f7768e", lw=1.2, ls="--")
    ax.annotate(f"CDaR {cd:.1f}%", (cd, max(c) * 0.9), xytext=(4, 0), textcoords="offset points", color="#f7768e", fontsize=7.5)
    ax.set_title(f"{label}: worst drawdown per simulated path over 12 weeks (%)", loc="left", fontsize=8.5)
    ax.set_yticks([])
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()


def table_png(res, max_rows=28):
    """The results-tree table as an image (for extensions that share a run)."""
    rows = res["rows"][:max_rows]
    fig, ax, plt = _fig(6.6, 0.24 * len(rows) + 0.6)
    ax.axis("off")
    cols = ["Part", "Share", "Effective", "Exp 12w", "CVaR", "CDaR", "UPI"]
    cell = [["  " * (len(r["path"]) - 1) + r["name"], f"{r['share']:.1%}", f"{r['effective']:.2%}",
             f"{r['metrics']['er_12w']:+.2%}", f"{r['metrics']['cvar']:.1%}", f"{r['metrics']['cdar']:.1%}",
             "" if r["metrics"].get("upi") is None else f"{r['metrics']['upi']:.3f}"] for r in rows]
    t = ax.table(cellText=cell, colLabels=cols, loc="upper left", cellLoc="right", colLoc="right",
                 colWidths=[0.34, 0.1, 0.12, 0.11, 0.1, 0.1, 0.08])
    t.auto_set_font_size(False)
    t.set_fontsize(7.5)
    for (i, j), c in t.get_celld().items():
        c.set_edgecolor(FRAME)
        c.set_facecolor(PANEL if i else BG)
        c.get_text().set_color(INK if i else INK2)
        if j == 0:
            c.get_text().set_horizontalalignment("left")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# ------------------------------------------------------------------ the PDF report

def pdf(res, rec, model, lines, budget, changed=None):
    """1-2 pages: the run record, the tree, the fan and the drawdown, the builder, the inputs, what changed."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    st = _stamp(res, rec)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"{rec.get('portfolio_name')}: run {rec['id']}")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=14, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=10.5, spaceBefore=6, spaceAfter=3)
    small = ParagraphStyle("s", parent=ss["Normal"], fontSize=7.8, leading=10, textColor=colors.HexColor("#444444"))
    grid = TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 7.4), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.4),
                       ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                       ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f5f8")]),
                       ("TOPPADDING", (0, 0), (-1, -1), 1.2), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.2)])
    root = res["rows"][0]
    m = root["metrics"]
    story = [Paragraph(f"{rec.get('portfolio_name')}", h1),
             Paragraph(f"Run {rec['id']} on the {'Colab A100' if st['machine'] == 'a100' else 'laptop'} ({st['gpu']}), finished "
                       f"{st['finished']}. Market data of {st['data_day']} {st['data_downloaded']}; jump database {st['jump_version']}; "
                       f"{st['bank']:,}-path bank, figures on the {res['config']['bank'] - res['config']['train']:,} paths no search saw. "
                       f"12-week expected return {m['er_12w']:+.2%}, volatility {m['vol_12w']:.2%}, CVaR 5% {m['cvar']:.2%}, "
                       f"CDaR 5% {m['cdar']:.2%}, UPI {m['upi']:.3f}.", small)]
    story += [Paragraph("The tree", h2)]
    wrap = ParagraphStyle("w", parent=small, fontSize=6.8, leading=8)
    data = [["Part", "Share", "Effective", "Exp. 12w", "Vol.", "CVaR", "CDaR", "UPI", "Binding limits"]]
    for r in res["rows"]:
        rm, s = r["metrics"], r.get("search") or {}
        data.append(["  " * (len(r["path"]) - 1) + r["name"], f"{r['share']:.1%}", f"{r['effective']:.2%}", f"{rm['er_12w']:+.2%}",
                     f"{rm['vol_12w']:.1%}", f"{rm['cvar']:.1%}", f"{rm['cdar']:.1%}", "" if rm.get("upi") is None else f"{rm['upi']:.3f}",
                     Paragraph("; ".join(b["text"] for b in s.get("binding") or []), wrap)])
    t = Table(data, repeatRows=1, colWidths=[42 * mm, 14 * mm, 16 * mm, 16 * mm, 13 * mm, 14 * mm, 14 * mm, 13 * mm, 40 * mm])
    t.setStyle(grid)
    story += [t, Spacer(1, 4)]
    story += [Image(io.BytesIO(fan_png(root)), width=91 * mm, height=49 * mm), Image(io.BytesIO(dd_png(root)), width=91 * mm, height=45 * mm)]
    story += [Paragraph(f"Builder: ${budget:,.0f}, shares rounded down to two decimals", h2)]
    data = [["Asset", "Trade as", "Price", "Weight", "Target $", "Shares", "Spent $"]]
    for x in lines:
        data.append([x["ticker"], x["trade_as"] or ("set one (futures)" if x["futures_unmapped"] else ""),
                     "" if x["price"] is None else f"{x['price']:,.2f}", f"{x['weight']:.2%}", f"{x['target']:,.0f}",
                     "" if x["shares"] is None else f"{x['shares']:.2f}", f"{x['spent']:,.2f}"])
    spent = sum(x["spent"] for x in lines)
    data.append(["", "", "", "", "", "Left over", f"{budget - spent:,.2f}"])
    t = Table(data, repeatRows=1)
    t.setStyle(grid)
    story += [t]
    story += [Paragraph("Inputs", h2)]
    data = [["Asset", "Equilibrium", "View", "Below / above", "Idiosyncratic jumps"]]
    for tk, a in ((res.get("portfolio") or {}).get("assets") or {}).items():
        v = a.get("view")
        data.append([tk, "" if a.get("equilibrium") is None else f"{a['equilibrium']:.2%}",
                     "" if not v else (f"price {v['value']:,.2f}" if v.get("form") == "price" else f"{v['value']:.2%}"),
                     "" if not v else f"-{v.get('minus')} / +{v.get('plus')}", "exempt" if a.get("exclude_idio_jump") else "on"])
    t = Table(data, repeatRows=1)
    t.setStyle(grid)
    story += [t]
    if changed is not None:
        story += [Paragraph("What changed since the previous run", h2)]
        story += [Paragraph("; ".join(f"{c['what']}: {c['before']} → {c['after']}" for c in changed) or "Nothing in the inputs.", small)]
    story += [Spacer(1, 4), Paragraph(f"Written {dt.datetime.now():%Y-%m-%d %H:%M} by Roptimizer.", small)]
    doc.build(story)
    return buf.getvalue()
