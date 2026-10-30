"""View arithmetic (#14): what the model uses from a view as the manager typed it.

A view is typed as a target price or as a return, with a horizon (12 months by default). As in the
accepted builder (#12), the return box is an annual return, and a target price is the price at the view's
horizon, annualised by compounding: annual = (P_target / P_now) ** (12 / h) - 1. Uncertainty has a separate
- and + side, each in annual return points or in dollars around the target price (converted the same way),
with no defaults. The typed value is the manager's MOST LIKELY value; a lopsided range is converted with the
exact split-normal moments
    mean = m + sqrt(2/pi) (s+ - s-),   sd = sqrt((1 - 2/pi) (s+ - s-)^2 + s+ s-)
where m is the most likely annual return and s-, s+ the two sides in annual points.
Worked example from #14: price $180, target $200 (-$10 / +$20) -> most likely +11.1%, model uses +15.5% +/- 8.5.
Each side may have its own unit ("unit_minus" / "unit_plus"; "unit" sets both).
"""
import math


class ViewError(ValueError):
    """A view the model cannot use (a run blocker): it names the asset or subportfolio."""


def _annual_from_price(p, price_now, h):
    if p <= 0:
        raise ViewError(f"a price of {p:.2f} cannot be annualised")
    return (float(p) / float(price_now)) ** (12.0 / h) - 1.0


def sides(view, price_now=None):
    """(m, s_minus, s_plus): the most likely annual return and the two sides in annual points."""
    form = view.get("form", "return")
    h = float(view.get("horizon_months", 12))
    if form == "price":
        if not price_now:
            raise ViewError("a target-price view needs the current price")
        target = float(view["value"])
        m = _annual_from_price(target, price_now, h)
    elif form == "return":
        m = float(view["value"])
        target = float(price_now) * (1 + m) ** (h / 12.0) if price_now else None
    else:
        raise ViewError(f"unknown view form {form!r}")
    out = []
    for side, sign in (("minus", -1), ("plus", 1)):
        u = view.get(side)
        if u is None:
            raise ViewError(f"the view has no {'-' if side == 'minus' else '+'} uncertainty (no defaults, #14)")
        u = float(u)
        if u < 0:
            raise ViewError("an uncertainty cannot be negative")
        unit = view.get(f"unit_{side}") or view.get("unit", "points")
        if unit == "dollars":
            if target is None:
                raise ViewError("an uncertainty in dollars needs the current price")
            out.append(abs(_annual_from_price(target + sign * u, price_now, h) - m))
        else:
            out.append(u)
    return m, out[0], out[1]


def model_view(view, price_now=None):
    """(mean, sd, most_likely) in annual terms, as the Black-Litterman blend uses them."""
    m, s_minus, s_plus = sides(view, price_now)
    mean = m + math.sqrt(2.0 / math.pi) * (s_plus - s_minus)
    sd = math.sqrt((1.0 - 2.0 / math.pi) * (s_plus - s_minus) ** 2 + s_plus * s_minus)
    if sd <= 0:
        raise ViewError("a view needs some uncertainty on at least one side")
    return mean, sd, m
