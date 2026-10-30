"""The portfolio: a tree of subportfolios and assets with every input, limit and setting (#2, #7, #14).

Shape (JSON, one file per portfolio in the library):
  {"id", "name", "version",
   "run": {"horizon_weeks": 12, "rf": null, "jump_version": "latest"},          run-wide settings
   "assets": {ticker: {"equilibrium": 0.1388, "view": VIEW | null, "exclude_idio_jump": false,
                       "trade_as": null}},
   "tree": NODE}
  NODE (group):  {"kind": "group", "name", "children": [NODE...], "limits": LIMITS, "portfolio_limits": LIMITS,
                  "settings": {key: value}, "inherit": {key: true}, "view": VIEW | null, "color_slot": int}
  NODE (asset):  {"kind": "asset", "ticker", "limits": LIMITS, "portfolio_limits": LIMITS}
  LIMITS:        {"min": {"on": bool, "value": x}, "max": {"on": bool, "value": x}}   (shares, 0..1)
  VIEW:          see mso.views (subportfolio views are typed in returns)

limits are a share of the parent; portfolio_limits a share of the whole portfolio, enforced at the top
search (there every inner mix is frozen, so they cap the share of the top-level child holding the node).
A setting is either set on the node, inherited from the parent when its inherit toggle is on, or the app
default; resolve() says which (#7).
"""
import copy
import uuid

from mso.views import ViewError, model_view

# App defaults (#7, #10). The concentration penalty is 0.20 at the Portfolio, off inside subportfolios.
DEFAULTS = {
    "cvar_floor": -0.40,          # soft maximum-loss preference over the horizon
    "floor_strictness": "soft",   # soft: penalty floor_weight x breach; hard: a breach is rejected
    "floor_weight": 5.0,
    "tail": 0.05,                 # tail level of CVaR and CDaR
    "concentration": None,        # None: 0.20 at the Portfolio, 0 inside (resolved by level)
    "window": 5,                  # search stops when the incumbent gains < tol over `window` generations
    "tol": 0.0002,
    "maxgen": 80,
    "pop_per_dim": 30,
}
SETTINGS = list(DEFAULTS)
ROOT_CONCENTRATION, INNER_CONCENTRATION = 0.20, 0.0
RUN_DEFAULTS = {"horizon_weeks": 12, "rf": None, "jump_version": "latest", "bands": None}


class PortfolioError(ValueError):
    pass


def limit_value(limits, side):
    v = (limits or {}).get(side) or {}
    return float(v["value"]) if v.get("on") and v.get("value") is not None else None


def asset(ticker, mn=None, mx=None):
    return {"kind": "asset", "ticker": ticker, "limits": _limits(mn, mx), "portfolio_limits": _limits(None, None)}


def group(name, children, mn=None, mx=None, **kw):
    return {"kind": "group", "name": name, "children": children, "limits": _limits(mn, mx),
            "portfolio_limits": _limits(None, None), "settings": {}, "inherit": {}, "view": None, **kw}


def _limits(mn, mx):
    return {"min": {"on": mn is not None, "value": mn}, "max": {"on": mx is not None, "value": mx}}


def new(name, assets, tree=None):
    """A portfolio; without a tree every asset sits directly under the Portfolio (a flat portfolio)."""
    tree = tree or group("Portfolio", [asset(t) for t in assets])
    return {"id": uuid.uuid4().hex[:12], "name": name, "version": 1, "run": dict(RUN_DEFAULTS),
            "assets": assets, "tree": tree}


def _pct(x):
    if x is None:
        return None
    if isinstance(x, str):
        x = x.strip()
        if not x:
            return None
        return float(x.replace("%", "")) / 100.0 if "%" in x else float(x)
    return float(x)


def from_csv(path, name=None):
    """A v4.1 portfolio CSV as a flat portfolio (#11): equilibrium_return -> equilibrium; analyst_view -> a
    12-month return view with view_volatility as the same number of points on both sides; a blank view is
    no view; exclude_idio_jump = 1 exempts the asset; trade-as tickers start empty."""
    import pandas as pd
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    truthy = {"1", "1.0", "true", "yes", "y", "t"}
    assets = {}
    for _, r in df.iterrows():
        t = r["ticker"].strip()
        if not t:
            continue
        v, sd = _pct(r.get("analyst_view")), _pct(r.get("view_volatility"))
        view = None
        if v is not None:
            view = {"form": "return", "value": v, "horizon_months": 12, "unit": "points", "minus": sd, "plus": sd}
        assets[t] = {"equilibrium": _pct(r["equilibrium_return"]), "view": view,
                     "exclude_idio_jump": str(r.get("exclude_idio_jump", "")).strip().lower() in truthy,
                     "trade_as": None}
    return new(name or f"Portfolio (from {path.rsplit('/', 1)[-1]})", assets)


# ------------------------------------------------------------------ walking and settings

def walk(node, path=()):
    """(node, path, parent) for every node, parents before children."""
    stack = [(node, (node.get("name") or node.get("ticker"),), None)]
    while stack:
        n, p, parent = stack.pop(0)
        yield n, p, parent
        for c in n.get("children", []):
            stack.append((c, p + (c.get("name") or c.get("ticker"),), n))


def resolve(tree):
    """{path: {key: (value, source)}} for every group: set here / from <parent> / default."""
    out = {}

    def go(node, path, parent_vals, parent_name, depth):
        vals = {}
        for k in SETTINGS:
            if k in (node.get("settings") or {}):
                vals[k] = (node["settings"][k], "set here")
            elif (node.get("inherit") or {}).get(k) and parent_vals is not None:
                vals[k] = (parent_vals[k][0], f"from {parent_name}")
            else:
                d = DEFAULTS[k]
                if k == "concentration":
                    d = ROOT_CONCENTRATION if depth == 0 else INNER_CONCENTRATION
                vals[k] = (d, "default")
        out[path] = vals
        for c in node.get("children", []):
            if c["kind"] == "group":
                go(c, path + (c["name"],), vals, node["name"], depth + 1)

    go(tree, (tree["name"],), None, None, 0)
    return out


def tickers(portfolio):
    return [n["ticker"] for n, _, _ in walk(portfolio["tree"]) if n["kind"] == "asset"]


# ------------------------------------------------------------------ validation (the pre-run blockers)

def blockers(portfolio, prices=None):
    """Everything that stops a run before it starts, each naming the asset or subportfolio (#7, #14)."""
    out = []
    tree = portfolio.get("tree")
    if not tree or tree.get("kind") != "group":
        return ["the portfolio has no tree"]
    seen = {}
    for node, path, parent in walk(tree):
        where = " / ".join(path)
        if node["kind"] == "asset":
            t = node["ticker"]
            if t in seen:
                out.append(f"{t} appears twice ({seen[t]} and {where}); an asset appears at most once")
            seen[t] = where
            a = portfolio["assets"].get(t)
            if a is None:
                out.append(f"{t}: no inputs (equilibrium return)")
                continue
            if a.get("equilibrium") is None:
                out.append(f"{t}: no equilibrium return")
            if a.get("view"):
                try:
                    model_view(a["view"], (prices or {}).get(t) or 1.0)
                except ViewError as e:
                    out.append(f"{t}: {e}")
            continue
        kids = node.get("children", [])
        if not kids:
            out.append(f"{where}: empty subportfolio")
            continue
        lo = [limit_value(c.get("limits"), "min") or 0.0 for c in kids]
        hi = [1.0 if limit_value(c.get("limits"), "max") is None else limit_value(c.get("limits"), "max") for c in kids]
        for c, l, h in zip(kids, lo, hi):
            if l > h + 1e-12:
                out.append(f"{where} / {c.get('name') or c.get('ticker')}: minimum {l:.1%} above maximum {h:.1%}")
        if sum(lo) > 1 + 1e-12:
            out.append(f"{where}: the children's minimums add up to {sum(lo):.1%} (more than 100%)")
        if sum(hi) < 1 - 1e-12:
            out.append(f"{where}: the children's maximums add up to {sum(hi):.1%} (less than 100%)")
        if node.get("view"):
            try:
                model_view(node["view"])
            except ViewError as e:
                out.append(f"{where}: {e}")
        for k, v in (node.get("settings") or {}).items():
            if k not in DEFAULTS:
                out.append(f"{where}: unknown setting {k!r}")
    return out


def copy_of(portfolio):
    return copy.deepcopy(portfolio)
