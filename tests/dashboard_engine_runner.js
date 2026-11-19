// Runs the dashboard engine on JSON from stdin; used by tests/test_dashboard_engine.py.
const Engine = require("../src/asset_frame/report/dashboard_engine.js");
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const counts = Engine.prefixCounts(input.returns);
const out = {runs: {}};
for (const [name, weights] of Object.entries(input.targets)) {
  for (const rule of input.rules) out.runs[name + "|" + rule] = Engine.run(input.calendar, input.returns, counts, weights, rule).map(
    (r) => ({i: r.i, ret: r.ret, coverage: r.coverage, turnover: r.turnover}));
}
const s = input.series;
out.performance = Engine.performance(s.mine, s.cash);
out.relative = Engine.relative(s.mine, s.bench);
out.max_drawdown = Engine.maxDrawdown(s.mine);
const cols = Engine.windowColumns(input.returns, input.risk.tickers, input.risk.end, input.risk.window);
out.correlation = Engine.correlationMatrix(cols);
out.risk = Engine.riskContributions(input.risk.weights, cols);
out.rolling = Engine.rollingCorrelation(input.returns[input.roll.a], input.roll.b ? input.returns[input.roll.b] : [], input.roll.window);
console.log(JSON.stringify(out));
