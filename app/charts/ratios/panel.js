// Chart module "ratios" (app/charts/ratios): every usual evaluation ratio of the selected part, beside the
// Portfolio's. Computed in mso/report.py on the held-out paths; the numerator is the expected excess return over
// 12 weeks (er - rf), as in UPI. Only UPI drives the search: the rest are for reading.
registerPanel("ratios", {
  title: "Ratios", sub: () => "on paths no search saw; only UPI is optimized", follows: true,
  draw(el) {
    const s = selRow(), P = R0.rows[0], two = idOf(s) !== idOf(P), rf = DATA.config.rf_12w;
    const R = [
      ["Return per unit of risk"],
      ["sharpe_ann", "Sharpe, annualized", 2, "excess return over volatility, × √(52/12)"],
      ["sortino_ann", "Sortino, annualized", 2, "excess return over downside deviation (below the risk-free rate), × √(52/12)"],
      ["sharpe", "Sharpe, 12 weeks", 3, "the same on the 12-week horizon"],
      ["sortino", "Sortino, 12 weeks", 3, ""],
      ["upi", "UPI (optimized)", 3, "excess return over CDaR 5%: what the search maximizes"],
      ["starr", "STARR", 3, "excess return over CVaR 5% (the conditional Sharpe)"],
      ["calmar", "Calmar", 3, "excess return over the average worst drawdown"],
      ["martin", "Martin", 3, "excess return over the Ulcer index (depth and length of drawdowns)"],
      ["omega", "Omega", 2, "expected gain over the risk-free rate ÷ expected shortfall below it"],
      ["rachev", "Rachev", 2, "mean of the best 5% of outcomes ÷ mean of the worst 5%"],
      ["Shape of the 12-week outcome"],
      ["skew", "Skewness", 2, "negative: the left tail is longer"],
      ["kurt", "Excess kurtosis", 2, "above 0: fatter tails than the normal"],
      ["p_loss", "Chance of a loss", "%", "share of paths below zero at 12 weeks"],
      ["p_below_rf", "Chance of trailing cash", "%", `share of paths below the risk-free ${rf == null ? "rate" : pct(rf, 2)}`],
      ["downside_dev", "Downside deviation", "%", "root mean square of the shortfall below the risk-free rate"],
      ["avg_mdd", "Average worst drawdown", "%", "mean over paths of each path's worst fall from its peak"],
      ["ulcer", "Ulcer index", "%", "root mean square drawdown along each path, averaged"],
    ];
    const f = (m, k, dp) => (m[k] == null ? `<span class="mu">—</span>` : dp === "%" ? pct(m[k], 1) : num(m[k], dp));
    const rows = R.map(([k, label, dp, what]) => (label == null
      ? `<tr class="g"><td class="l" colspan="${two ? 4 : 3}">${k}</td></tr>`
      : `<tr><td class="l">${label}</td><td>${f(s.metrics, k, dp)}</td>${two ? `<td>${f(P.metrics, k, dp)}</td>` : ""}<td class="l mu" style="white-space:normal;font-size:12px;padding-block:3px">${what}</td></tr>`)).join("");
    const old = s.metrics.partial ? `<p class="mu" style="padding:8px 10px;margin:0">This run is older than the ratios: Sharpe and STARR are worked out from its figures, the rest show after a new run.</p>` : "";
    el.innerHTML = `<div style="position:absolute;inset:0;overflow:auto">${old}<table style="font-variant-numeric:tabular-nums"><thead><tr><th class="l">Ratio</th><th>${esc(s.name)}</th>${two ? `<th>${esc(P.name)}</th>` : ""}<th class="l">What it is</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  },
});
