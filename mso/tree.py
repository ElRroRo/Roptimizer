"""The tree engine (#2, #7, #10): every subportfolio is searched on its own, frozen, then treated as one
asset by the level above, in post-order (innermost first).

- A frozen subportfolio's path in each scenario is its children's paths at the frozen weights, so a level is
  scored on the asset bank through a mixing matrix M (child -> asset) and effective weights A = M @ W.
- Limits: each child's min / max share of its parent; whole-portfolio limits on any node, enforced at the
  top search, where they bound the share of the top-level child that holds the node.
- Settings per subportfolio (mso.portfolio.resolve): CVaR floor and strictness, tail level, concentration
  penalty (0.20 at the Portfolio on effective weights, off inside), search window / tolerance / cap / population.
- Subportfolio views: a child subportfolio's implied return (its assets' posterior returns at its frozen mix,
  uncertainty sqrt(w' M w)) is blended Black-Litterman-style with its view when its parent searches; siblings
  move through the correlated uncertainty. The mix inside never changes.
- Edge cases: one child gets 100% with no search; a fully pinned subportfolio (every min = max) uses the
  entered mix; an empty subportfolio or impossible limits stop the run before any search.
- Sensitivity band (optional): each search repeated K times with the asset posterior returns drawn from
  N(mu, M), lower levels frozen at their single answers; the spread is reported on the share of parent.
"""
import time
import zlib

import numpy as np

from mso import portfolio as pf
from mso import report, search
from mso.views import model_view


class TreeError(ValueError):
    pass


def node_seed(seed, path):
    """A reproducible seed per search, from the run seed and the node's path."""
    return int(np.random.SeedSequence([int(seed), zlib.crc32(" / ".join(path).encode())]).generate_state(1)[0])


def _horizon(annual, steps):
    return (1.0 + np.asarray(annual, dtype=float)) ** (steps / 52.0) - 1.0


def run(G, inputs, portfolio, train, steps, seed, draw=1_000_000, bands=0, on_event=None, rf_h=None,
        trace=False, noise=0):
    """Search the whole tree on the device bank G (first `train` rows searchable, the rest held out).
    Returns {"rows": [...], "effective": {ticker: w}, "searches": n, "wall_s": s}."""
    emit = on_event or (lambda kind, **kw: None)
    T = list(inputs["tickers"])
    N = len(T)
    tree = portfolio["tree"]
    if sorted(pf.tickers(portfolio)) != sorted(T):
        missing, extra = set(pf.tickers(portfolio)) - set(T), set(T) - set(pf.tickers(portfolio))
        raise TreeError(f"the tree's assets are not the inputs' assets (tree only: {sorted(missing)}, "
                        f"inputs only: {sorted(extra)})")
    found = pf.blockers(portfolio)
    if found:
        raise TreeError("the portfolio cannot run:\n  - " + "\n  - ".join(found))
    er_assets = search.horizon_returns(inputs["drift"], steps)                  # the simulator's own drift
    mu = np.asarray(inputs.get("posterior_annual") or [], dtype=float)
    Mpost = np.asarray(inputs.get("posterior_cov") or [], dtype=float)
    has_post = mu.shape == (N,) and Mpost.shape == (N, N)
    if rf_h is None:
        rf_h = (1 + inputs["rf_rate"]) ** (steps / 52) - 1
    settings = pf.resolve(tree)
    rows, t_run, n_search = [], time.perf_counter(), [0]
    rng_bands = np.random.default_rng(np.random.SeedSequence([int(seed), 7]))
    VAL = None
    if trace:                                         # held-out paths, to score each generation's incumbent
        from mso.xp import cp
        VAL = cp.ascontiguousarray(G[train:].transpose(2, 0, 1))

    def child_name(c):
        return c.get("name") or c["ticker"]

    def views_blend(kids, mixes, mu_draw=None):
        """Annual implied return and uncertainty of each child, blended with subportfolio views."""
        m = mu if mu_draw is None else mu_draw
        imp = np.array([m @ x for x in mixes])
        cov = np.array([[x @ Mpost @ y for y in mixes] for x in mixes])
        idx = [i for i, c in enumerate(kids) if c["kind"] == "group" and c.get("view")]
        if not idx:
            return imp, imp, cov
        P = np.zeros((len(idx), len(kids)))
        q, om = np.zeros(len(idx)), np.zeros(len(idx))
        for r, i in enumerate(idx):
            P[r, i] = 1.0
            q[r], sd, _ = model_view(kids[i]["view"])
            om[r] = sd ** 2
        S = P @ cov @ P.T + np.diag(om)
        blended = imp + cov @ P.T @ np.linalg.solve(S, q - P @ imp)
        return imp, blended, cov

    def walk(node, path, depth):
        if node["kind"] == "asset":
            v = np.zeros(N)
            v[T.index(node["ticker"])] = 1.0
            return v, None
        kids = node["children"]
        sub = [walk(c, path + (child_name(c),), depth + 1) for c in kids]
        mixes = [m for m, _ in sub]
        M = np.column_stack(mixes)
        st = {k: v for k, (v, _) in settings[path].items()}
        lo = np.array([pf.limit_value(c.get("limits"), "min") or 0.0 for c in kids])
        hi = np.array([1.0 if pf.limit_value(c.get("limits"), "max") is None else pf.limit_value(c.get("limits"), "max")
                       for c in kids])
        squeezes = []
        if depth == 0:
            lo, hi, squeezes = _portfolio_limits(node, kids, mixes, lo, hi, T)
        # children's horizon returns; with a subportfolio view among them, the blend's shift is added on top
        er_h = er_assets @ M
        implied = blended = None
        if any(c["kind"] == "group" and c.get("view") for c in kids):
            if not has_post:
                raise TreeError(f"{' / '.join(path)}: a subportfolio view needs the posterior uncertainty; "
                                f"build the inputs from a portfolio, not a snapshot")
            implied, blended, _ = views_blend(kids, mixes)
            er_h = er_h + (_horizon(blended, steps) - _horizon(implied, steps))
        obj = search.Objective(alpha=float(st["tail"]), cvar_floor=float(st["cvar_floor"]), rf_h=rf_h,
                               hhi=float(st["concentration"]), floor_weight=float(st["floor_weight"]),
                               hard_floor=st["floor_strictness"] == "hard")
        cfg = search.SearchConfig(pop_per_dim=int(st["pop_per_dim"]), tol=float(st["tol"]),
                                  window=int(st["window"]), maxgen=int(st["maxgen"]), draw=draw,
                                  trace=trace, noise=noise)
        name = " / ".join(path)
        if len(kids) == 1:
            if lo[0] > 1 + 1e-12 or hi[0] < 1 - 1e-12:
                raise TreeError(f"{name}: one member must take 100%, which its limits forbid")
            w, rec = np.ones(1), dict(generations=0, stopped="one member: 100%, no search", history=[])
        elif np.all(np.abs(hi - lo) < 1e-12):
            if abs(lo.sum() - 1) > 1e-9:
                raise TreeError(f"{name}: a fixed mix must add up to 100% (it adds up to {lo.sum():.1%})")
            w, rec = lo.copy(), dict(generations=0, stopped="fixed mix (every minimum = maximum), no search", history=[])
        else:
            n_search[0] += 1
            emit("search_start", search=name, children=[child_name(c) for c in kids])

            def on_gen(g, inc, scored, s, replaced, stop, name=name):
                emit("generation", search=name, gen=g, incumbent=inc, scored=scored, s=round(s, 2),
                     replaced=replaced, stop=stop)
            rec = search.search(name, G, M, er_h, obj, cfg, node_seed(seed, path), lo, hi, train, on_gen)
            w = np.asarray(rec.pop("weights"))
            if trace:
                Wt = np.asarray(rec["trace"]).T
                rec["held_out_trace"] = search.score(VAL, M @ Wt, er_h @ Wt, obj).tolist()
            if bands:
                if not has_post:
                    raise TreeError(f"{name}: a sensitivity band needs the posterior uncertainty; "
                                    f"build the inputs from a portfolio, not a snapshot")
                rec["band"] = _band(name, G, M, kids, mixes, obj, cfg, seed, path, lo, hi, train, bands,
                                    mu, Mpost, views_blend, steps, rng_bands, emit)
            emit("search_done", search=name, generations=rec["generations"], stopped=rec["stopped"],
                 incumbent=rec.get("incumbent"))
        rec["binding"] = _binding(kids, w, lo, hi)
        rec["squeezes"] = squeezes
        rec["settings"] = {k: dict(value=v, source=src) for k, (v, src) in settings[path].items()}
        node["_share_of"] = dict(zip(range(len(kids)), w.tolist()))
        node["_mix"] = M @ w
        node["_search"] = rec
        node["_implied"] = None if implied is None else dict(
            implied=implied.tolist(), blended=blended.tolist())
        return node["_mix"], rec

    try:
        walk(tree, (tree["name"],), 0)
    except BaseException:
        for n, _, _ in pf.walk(tree):                 # a failed run leaves the caller's portfolio as it was
            for k in ("_share_of", "_mix", "_search", "_implied"):
                n.pop(k, None)
        raise

    def collect(node, eff, path, share):
        e = eff * share
        if node["kind"] == "asset":
            mix = np.zeros(N)
            mix[T.index(node["ticker"])] = 1.0
        else:
            mix = node["_mix"]
        row = dict(name=child_name(node), kind=node["kind"], path=list(path), share=float(share), effective=float(e),
                   limits=node.get("limits"), portfolio_limits=node.get("portfolio_limits"), mix=mix)
        if node["kind"] == "group":
            row["search"] = node["_search"]
            if node.get("view"):
                row["view"] = node["view"]
        rows.append(row)
        for i, c in enumerate(node.get("children", [])):
            s = node["_share_of"][i]
            cr = collect(c, e, path + (child_name(c),), s)
            if node.get("_implied"):
                cr["implied_annual"] = node["_implied"]["implied"][i]
                cr["blended_annual"] = node["_implied"]["blended"][i]
            band = node["_search"].get("band")
            if band:
                cr["band"] = dict(sd=band["sd"][i], p10=band["p10"][i], p90=band["p90"][i], k=band["k"])
        return row

    collect(tree, 1.0, (tree["name"],), 1.0)
    walk = collect = None                             # break the closures' self-reference, which holds G and VAL
    for n, _, _ in pf.walk(tree):                     # the scratch fields are not part of the portfolio
        for k in ("_share_of", "_mix", "_search", "_implied"):
            n.pop(k, None)
    return dict(rows=rows, effective=dict(zip(T, rows[0]["mix"].tolist())), searches=n_search[0],
                wall_s=round(time.perf_counter() - t_run, 1))


def _portfolio_limits(root, kids, mixes, lo, hi, T):
    """Whole-portfolio limits become bounds on the share of the top-level child holding the node: its
    effective weight is share_c x its frozen weight inside c."""
    squeezes = []
    for node, path, _ in pf.walk(root):
        if node is root:
            continue
        mn, mx = pf.limit_value(node.get("portfolio_limits"), "min"), pf.limit_value(node.get("portfolio_limits"), "max")
        if mn is None and mx is None:
            continue
        top = next(i for i, c in enumerate(kids) if node is c or any(node is n for n, _, _ in pf.walk(c)))
        if node["kind"] == "asset":
            inside = float(mixes[top][T.index(node["ticker"])])
        else:
            inside = _inside_share(kids[top], node)
        who = " / ".join(path)
        cname = kids[top].get("name") or kids[top]["ticker"]
        if mx is not None:
            bound = mx / inside if inside > 0 else 1.0
            if bound < hi[top]:
                hi[top] = bound
                squeezes.append(f"{who} at most {mx:.1%} of the Portfolio caps {cname} at {bound:.1%} "
                                f"(it is {inside:.1%} of {cname})")
        if mn is not None:
            if inside <= 0:
                raise TreeError(f"{who}: a whole-portfolio minimum of {mn:.1%} is impossible, it is 0% of {cname}")
            bound = mn / inside
            if bound > lo[top]:
                lo[top] = bound
                squeezes.append(f"{who} at least {mn:.1%} of the Portfolio floors {cname} at {bound:.1%} "
                                f"(it is {inside:.1%} of {cname})")
    if lo.sum() > 1 + 1e-12 or hi.sum() < 1 - 1e-12 or np.any(lo > hi + 1e-12):
        raise TreeError("whole-portfolio limits make the Portfolio infeasible: " + "; ".join(squeezes))
    return lo, hi, squeezes


def _inside_share(top_child, node):
    """A subportfolio's share of a top-level child: the product of the frozen shares down the path."""
    def go(n, acc):
        if n is node:
            return acc
        for i, c in enumerate(n.get("children", [])):
            r = go(c, acc * n["_share_of"][i])
            if r is not None:
                return r
        return None
    r = go(top_child, 1.0)
    return 0.0 if r is None else float(r)


def _binding(kids, w, lo, hi):
    out = []
    for c, wi, l, h in zip(kids, w, lo, hi):
        nm = c.get("name") or c["ticker"]
        if l > 0 and abs(wi - l) < 1e-6:
            out.append(dict(child=nm, at="min", limit=float(l), text=f"{nm} at its {l:.1%} minimum"))
        elif h < 1 and abs(wi - h) < 1e-6:
            out.append(dict(child=nm, at="max", limit=float(h), text=f"{nm} at its {h:.1%} maximum"))
    return out


def _band(name, G, M, kids, mixes, obj, cfg, seed, path, lo, hi, train, k, mu, Mpost, views_blend, steps, rng, emit):
    """K repeats of one search with the asset posterior returns drawn from N(mu, M) (#6); the children's
    returns (and any subportfolio-view blend) are recomputed from each draw."""
    ws = []
    for r in range(k):
        mu_d = rng.multivariate_normal(mu, Mpost)
        imp, blended, _ = views_blend(kids, mixes, mu_draw=mu_d)
        er = _horizon(mu_d, steps) @ M + (_horizon(blended, steps) - _horizon(imp, steps))
        emit("band", search=name, repeat=r + 1, of=k)
        rec = search.search(f"{name} (band {r + 1}/{k})", G, M, er, obj, cfg, node_seed(seed, path + (f"band{r}",)),
                            lo, hi, train)
        ws.append(rec["weights"])
    ws = np.asarray(ws)
    return dict(k=k, sd=ws.std(axis=0, ddof=1).tolist(), p10=np.percentile(ws, 10, axis=0).tolist(),
                p90=np.percentile(ws, 90, axis=0).tolist(), weights=ws.tolist())


def metrics(VAL, result, er_assets, alpha, rf_h):
    """Held-out metrics, fan and histograms for every row (mutates result['rows'])."""
    mixes = np.column_stack([r["mix"] for r in result["rows"]])
    for r, m in zip(result["rows"], report.row_metrics(VAL, mixes, er_assets, alpha, rf_h)):
        r.update(m)
        r["mix"] = r["mix"].tolist()
    return result
