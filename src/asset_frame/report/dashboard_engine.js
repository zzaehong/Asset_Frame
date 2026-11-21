// Backtest and risk functions for the dashboard's portfolio lab. No DOM access.
// Mirrors src/asset_frame/backtest/engine.py, backtest/metrics.py and analytics/risk.py; the
// differential test in tests/test_dashboard_engine.py runs both on the same data.
const Engine = (() => {
  const MIN_HISTORY = 13;
  const BAND = 0.05;
  const PERIODS = 12;
  const QUARTER_STARTS = [1, 4, 7, 10];

  // counts[t][i] = how many returns of t exist before calendar index i
  function prefixCounts(returns) {
    const counts = {};
    for (const [ticker, values] of Object.entries(returns)) {
      const prefix = new Array(values.length + 1).fill(0);
      for (let i = 0; i < values.length; i++) prefix[i + 1] = prefix[i] + (values[i] == null ? 0 : 1);
      counts[ticker] = prefix;
    }
    return counts;
  }

  const sameKeys = (a, b) => {
    const ka = Object.keys(a), kb = Object.keys(b);
    return ka.length === kb.length && ka.every((k) => k in b);
  };

  function due(rule, monthNumber, held, target) {
    if (rule === "monthly") return true;
    if (rule === "quarterly") return QUARTER_STARTS.includes(monthNumber);
    return Object.keys(target).some((t) => Math.abs(held[t] - target[t]) > BAND);
  }

  // target: {ticker: weight>=0}, normalised here. Returns one entry per month the portfolio exists.
  function run(calendar, returns, counts, target, rule) {
    const total = Object.values(target).reduce((s, w) => s + w, 0);
    const wanted = {};
    for (const [t, w] of Object.entries(target)) if (w > 0 && returns[t]) wanted[t] = w / total;
    const tickers = Object.keys(wanted);
    const out = [];
    let held = null;
    for (let i = 0; i < calendar.length; i++) {
      const usable = tickers.filter((t) => counts[t][i] >= MIN_HISTORY && returns[t][i] != null);
      const coverage = usable.reduce((s, t) => s + wanted[t], 0);
      if (!usable.length || coverage <= 0) { held = null; continue; }
      const next = {};
      for (const t of usable) next[t] = wanted[t] / coverage;
      const initial = held === null;
      let turnover = 0;
      if (initial || !sameKeys(held, next) || due(rule, Number(calendar[i].slice(5, 7)), held, next)) {
        if (!initial) {
          const union = new Set([...Object.keys(held), ...Object.keys(next)]);
          let moved = 0;
          for (const t of union) moved += Math.abs((next[t] || 0) - (held[t] || 0));
          turnover = moved / 2;
        }
        held = next;
      }
      let portfolio = 0;
      for (const t of Object.keys(held)) portfolio += held[t] * returns[t][i];
      out.push({i, ret: portfolio, coverage, turnover, weights: {...held}});
      const drifted = {};
      for (const t of Object.keys(held)) drifted[t] = (held[t] * (1 + returns[t][i])) / (1 + portfolio);
      held = drifted;
    }
    return out;
  }

  const mean = (a) => a.reduce((s, v) => s + v, 0) / a.length;
  function stdev(a) {
    const m = mean(a);
    return Math.sqrt(a.reduce((s, v) => s + (v - m) ** 2, 0) / (a.length - 1));
  }
  const prod = (a) => a.reduce((p, v) => p * v, 1);

  function maxDrawdown(r) {
    let wealth = 1, peak = 1, worst = 0;
    for (const v of r) { wealth *= 1 + v; peak = Math.max(peak, wealth); worst = Math.min(worst, wealth / peak - 1); }
    return worst;
  }
  function drawdownSeries(r) {
    let wealth = 1, peak = 1;
    return r.map((v) => { wealth *= 1 + v; peak = Math.max(peak, wealth); return wealth / peak - 1; });
  }
  const cagr = (r) => prod(r.map((v) => 1 + v)) ** (PERIODS / r.length) - 1;

  function performance(r, cash) {
    const excess = r.map((v, k) => v - cash[k]);
    const spread = stdev(excess);
    const downside = Math.sqrt(excess.reduce((s, v) => s + Math.min(v, 0) ** 2, 0) / excess.length);
    const dd = maxDrawdown(r);
    const g = cagr(r);
    return {
      months: r.length, cagr: g, volatility: stdev(r) * Math.sqrt(PERIODS),
      sharpe: spread > 0 ? (mean(excess) * Math.sqrt(PERIODS)) / spread : null,
      sortino: downside > 0 ? (mean(excess) * Math.sqrt(PERIODS)) / downside : null,
      calmar: dd < 0 ? g / Math.abs(dd) : null, max_drawdown: dd,
    };
  }
  function relative(r, bench) {
    const active = r.map((v, k) => v - bench[k]);
    const spread = stdev(active);
    return {
      excess_cagr: cagr(r) - cagr(bench), tracking_error: spread * Math.sqrt(PERIODS),
      information_ratio: spread > 0 ? (mean(active) * Math.sqrt(PERIODS)) / spread : null,
    };
  }

  function pearson(a, b) {
    const ma = mean(a), mb = mean(b);
    let sab = 0, saa = 0, sbb = 0;
    for (let k = 0; k < a.length; k++) { sab += (a[k] - ma) * (b[k] - mb); saa += (a[k] - ma) ** 2; sbb += (b[k] - mb) ** 2; }
    return saa === 0 || sbb === 0 ? null : sab / Math.sqrt(saa * sbb);
  }
  function covariance(a, b) {
    const ma = mean(a), mb = mean(b);
    let s = 0;
    for (let k = 0; k < a.length; k++) s += (a[k] - ma) * (b[k] - mb);
    return s / (a.length - 1);
  }

  // Columns for each ticker over calendar indices [end-window+1, end]; tickers lacking any month are dropped.
  function windowColumns(returns, tickers, end, window) {
    const start = end - window + 1;
    if (start < 0) return {};
    const out = {};
    for (const t of tickers) {
      const col = returns[t] ? returns[t].slice(start, end + 1) : null;
      if (col && col.every((v) => v != null)) out[t] = col;
    }
    return out;
  }
  function correlationMatrix(cols) {
    const names = Object.keys(cols);
    return {names, matrix: names.map((a) => names.map((b) => pearson(cols[a], cols[b])))};
  }
  function riskContributions(weights, cols) {
    const names = Object.keys(weights).filter((t) => cols[t]);
    const w = names.map((t) => weights[t]);
    const cov = names.map((a) => names.map((b) => covariance(cols[a], cols[b])));
    const marginal = cov.map((row) => row.reduce((s, c, j) => s + c * w[j], 0));
    const variance = w.reduce((s, wi, i) => s + wi * marginal[i], 0);
    if (!(variance > 0)) return null;
    const shares = {};
    names.forEach((t, i) => { shares[t] = (w[i] * marginal[i]) / variance; });
    return {shares, volatility: Math.sqrt(variance * PERIODS)};
  }
  function rollingCorrelation(a, b, window) {
    const out = new Array(a.length).fill(null);
    for (let end = window - 1; end < a.length; end++) {
      const xs = a.slice(end - window + 1, end + 1), ys = b.slice(end - window + 1, end + 1);
      if (xs.every((v) => v != null) && ys.every((v) => v != null)) out[end] = pearson(xs, ys);
    }
    return out;
  }

  const TICKER = /^[A-Z]{1,5}(-[A-Z])?$/;
  // The text of config/stocks.toml for a selection (see asset_frame.stocks.load_stocks).
  function stocksToml(tickers) {
    const lines = ["# 수집할 개별주 목록 (ADR-0010). 대시보드 \"개별주 선택\" 탭에서 만든 내용이다.", "schema_version = 1"];
    for (const ticker of tickers) {
      if (!TICKER.test(ticker)) throw new Error("invalid ticker: " + ticker);
      lines.push("", "[[stocks]]", `ticker = "${ticker}"`);
    }
    return lines.join("\n") + "\n";
  }

  return {MIN_HISTORY, BAND, stocksToml, prefixCounts, run, performance, relative, maxDrawdown, drawdownSeries,
    cagr, correlationMatrix, windowColumns, riskContributions, rollingCorrelation, pearson};
})();
if (typeof module !== "undefined") module.exports = Engine;
