from __future__ import annotations

import argparse
import csv
import os
from collections.abc import Sequence
from dataclasses import astuple, fields
from datetime import UTC, date, datetime
from pathlib import Path

from asset_frame.analytics.dividend import trailing_dividend_yield
from asset_frame.analytics.risk import WINDOW_MONTHS
from asset_frame.backtest.engine import CALC_VERSION as BACKTEST_CALC_VERSION
from asset_frame.backtest.jobs import BENCHMARKS, run_backtest
from asset_frame.backtest.strategies import load_strategies
from asset_frame.connectors.fred import FRED_SOURCE_ID, SUPPORTED_SERIES
from asset_frame.connectors.krx import KRX_SOURCE_ID, KrxDataset
from asset_frame.connectors.tiingo import TIINGO_SOURCE_ID, tiingo_asset_id
from asset_frame.domain.models import AssetType, SourceDefinition
from asset_frame.ingestion.fred_service import FredCollector
from asset_frame.ingestion.krx_service import KrxCollector
from asset_frame.ingestion.tiingo_service import TiingoEodCollector
from asset_frame.ingestion.transport import RateLimitedRetryTransport, UrllibHttpTransport
from asset_frame.ingestion.universe_service import ingest_universe
from asset_frame.ledger.chain import first_broken_seq
from asset_frame.prediction.jobs import (
    record_human_prediction,
    record_predictions,
    score_due,
    scoreboard,
)
from asset_frame.proxies import ProxySpec, load_proxies, proxy_universe
from asset_frame.proxy_jobs import build_proxy_returns, spliced_levels
from asset_frame.regime.jobs import (
    first_release_series,
    record_regime,
    run_regime,
    run_regime_long,
)
from asset_frame.regime.market import EXTENSION_SERIES, MAX_AGE_DAYS
from asset_frame.regime.replay import RULES, ip_quadrants, score
from asset_frame.report.dashboard import LongContext, build_payload, render_dashboard
from asset_frame.returns.series import total_return_index
from asset_frame.sources.registry import load_source_registry
from asset_frame.storage.backup import backup
from asset_frame.storage.ledger import LedgerStore
from asset_frame.storage.raw import FileRawStore
from asset_frame.storage.research import ResearchStore
from asset_frame.storage.sqlite import SqliteIngestionRepository
from asset_frame.universe import UniverseAsset, load_universe
from asset_frame.universe_jobs import (
    StatusRow,
    analyze_universe,
    build_returns,
    universe_status,
    verify_universe,
)

SOURCES_PATH = Path("config/sources.toml")
UNIVERSE_PATH = Path("config/universe.toml")
REPORT_DIR = Path("var/reports")
STRATEGIES_PATH = Path("config/strategies.toml")
PROXIES_PATH = Path("config/proxies.toml")
MARKET_INPUT_SERIES = (*MAX_AGE_DAYS, *EXTENSION_SERIES)
STATUS_CSV_PATH = REPORT_DIR / "universe_status.csv"
DEFAULT_DATABASE_PATH = "var/asset_frame.sqlite3"
DEFAULT_RAW_STORE_PATH = "var/raw"
DEFAULT_BACKUP_PATH = "~/Backups/Asset_Frame"
# Tiingo Starter plan allows 50 requests/hour (config/sources.toml); 75 s keeps us at 48.
TIINGO_STARTER_INTERVAL_SECONDS = 75.0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="asset-frame")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("sources", help="list registered data sources")

    tiingo_parser = subparsers.add_parser(
        "ingest-tiingo", help="collect Tiingo metadata and EOD prices"
    )
    tiingo_parser.add_argument("--ticker", required=True)
    tiingo_parser.add_argument("--asset-type", required=True, choices=("equity", "etf"))
    tiingo_parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    tiingo_parser.add_argument("--end-date", required=True, type=date.fromisoformat)

    krx_parser = subparsers.add_parser("ingest-krx", help="collect an approved KRX dataset")
    krx_parser.add_argument(
        "--dataset", required=True, choices=[item.name.lower() for item in KrxDataset]
    )
    krx_parser.add_argument("--date", required=True, type=date.fromisoformat)

    universe_ingest_parser = subparsers.add_parser(
        "ingest-universe",
        help="collect Tiingo history for every universe ticker (only new days if stored)",
    )
    universe_ingest_parser.add_argument(
        "--end-date", type=date.fromisoformat, default=datetime.now(UTC).date()
    )
    universe_ingest_parser.add_argument(
        "--min-interval-seconds", type=float, default=TIINGO_STARTER_INTERVAL_SECONDS
    )
    universe_ingest_parser.add_argument(
        "--full", action="store_true", help="download the whole history again"
    )

    universe_parser = subparsers.add_parser("universe", help="universe verification and status")
    universe_commands = universe_parser.add_subparsers(dest="universe_command", required=True)
    universe_commands.add_parser("verify", help="compare inception dates with Tiingo data")
    universe_commands.add_parser("status", help="print per-ticker data status")
    universe_commands.add_parser("analyze", help="risk table and 36-month correlation matrix")

    proxy_ingest_parser = subparsers.add_parser(
        "ingest-proxies",
        help="collect Tiingo history for the proxy funds in config/proxies.toml",
    )
    proxy_ingest_parser.add_argument(
        "--end-date", type=date.fromisoformat, default=datetime.now(UTC).date()
    )
    proxy_ingest_parser.add_argument(
        "--min-interval-seconds", type=float, default=TIINGO_STARTER_INTERVAL_SECONDS
    )

    fred_parser = subparsers.add_parser("ingest-fred", help="collect a FRED series")
    fred_parser.add_argument("--series", required=True, choices=SUPPORTED_SERIES)

    subparsers.add_parser("build-returns", help="compute monthly total returns")
    subparsers.add_parser("dashboard", help="write the offline interactive dashboard")
    regime_parser = subparsers.add_parser(
        "regime", help="replay regime rules and score them against NBER (diagnostic)"
    )
    regime_parser.add_argument(
        "--long", action="store_true", help="replay from 1962 with proxy-extended returns"
    )
    ledger_parser = subparsers.add_parser("ledger", help="append-only hash-chained ledger")
    ledger_commands = ledger_parser.add_subparsers(dest="ledger_command", required=True)
    ledger_commands.add_parser("verify", help="check the hash chain and print the head hash")
    record_parser = ledger_commands.add_parser(
        "record-regime", help="append the latest month's regime reading (live)"
    )
    record_parser.add_argument(
        "--replay", action="store_true", help="append every replayed month as `replay` instead"
    )
    ledger_commands.add_parser(
        "predict-models", help="append model predictions for the latest month"
    )
    predict_parser = ledger_commands.add_parser("predict", help="append your own prediction")
    predict_parser.add_argument(
        "--ranking", required=True, help="tickers best to worst, comma-separated"
    )
    predict_parser.add_argument(
        "--positive-prob", type=float, required=True, help="P(SPY-IEF 36m correlation > 0)"
    )
    predict_parser.add_argument("--note", required=True, help="one-line reason")
    ledger_commands.add_parser("score", help="score predictions whose 3 months have passed")
    ledger_commands.add_parser("scoreboard", help="per-model scores with sample size and MDE")
    subparsers.add_parser("backup", help="copy the database and raw files to BACKUP_PATH")
    backtest_parser = subparsers.add_parser(
        "backtest", help="compare strategies under three rebalancing rules"
    )
    backtest_parser.add_argument(
        "--window-months", type=int, default=WINDOW_MONTHS, help="risk estimation window"
    )

    arguments = parser.parse_args(argv)
    if arguments.command == "sources":
        _print_sources()
    elif arguments.command == "ingest-tiingo":
        _ingest_tiingo(
            arguments.ticker, arguments.asset_type, arguments.start_date, arguments.end_date
        )
    elif arguments.command == "ingest-krx":
        _ingest_krx(arguments.dataset, arguments.date)
    elif arguments.command == "ingest-universe":
        _ingest_universe(arguments.end_date, arguments.min_interval_seconds, arguments.full)
    elif arguments.command == "ingest-proxies":
        _ingest_proxies(arguments.end_date, arguments.min_interval_seconds)
    elif arguments.command == "universe" and arguments.universe_command == "verify":
        _verify_universe()
    elif arguments.command == "universe" and arguments.universe_command == "analyze":
        _analyze_universe()
    elif arguments.command == "universe":
        _print_universe_status()
    elif arguments.command == "ingest-fred":
        _ingest_fred(arguments.series)
    elif arguments.command == "build-returns":
        _build_returns()
    elif arguments.command == "dashboard":
        _dashboard()
    elif arguments.command == "regime":
        _regime(arguments.long)
    elif arguments.command == "ledger":
        _ledger(arguments)
    elif arguments.command == "backup":
        _backup()
    elif arguments.command == "backtest":
        _backtest(arguments.window_months)


def _print_sources() -> None:
    for source in load_source_registry(SOURCES_PATH):
        kinds = ",".join(kind.value for kind in source.data_kinds)
        print(
            f"{source.id}\t{source.implementation_status.value}\t"
            f"{'enabled' if source.enabled else 'disabled'}\t{source.authority}\t{kinds}"
        )


def _ingest_tiingo(ticker: str, asset_type_name: str, start_date: date, end_date: date) -> None:
    api_key = _required_environment("TIINGO_API_KEY")
    collector = TiingoEodCollector(
        source=_source(TIINGO_SOURCE_ID),
        transport=UrllibHttpTransport(),
        raw_store=_raw_store(),
        repository=_repository(),
    )
    result = collector.collect(
        ticker=ticker,
        asset_type=AssetType(asset_type_name),
        api_key=api_key,
        start_date=start_date,
        end_date=end_date,
    )
    print(
        f"collected Tiingo {ticker.upper()}: {result.accepted_prices} prices, "
        f"{result.quarantined_prices} quarantined, "
        f"{result.corporate_actions} corporate actions; asset {result.asset.id}"
    )


def _ingest_krx(dataset_name: str, business_date: date) -> None:
    api_key = _required_environment("KRX_API_KEY")
    collector = KrxCollector(
        source=_source(KRX_SOURCE_ID),
        transport=UrllibHttpTransport(),
        raw_store=_raw_store(),
        repository=_repository(),
    )
    count = collector.collect(
        dataset=KrxDataset[dataset_name.upper()], business_date=business_date, api_key=api_key
    )
    print(f"collected {count} KRX {dataset_name} rows for {business_date.isoformat()}")


def _ingest_universe(end_date: date, min_interval_seconds: float, full: bool) -> None:
    api_key = _required_environment("TIINGO_API_KEY")
    collector = TiingoEodCollector(
        source=_source(TIINGO_SOURCE_ID),
        transport=RateLimitedRetryTransport(
            UrllibHttpTransport(), minimum_interval_seconds=min_interval_seconds
        ),
        raw_store=_raw_store(),
        repository=_repository(),
    )
    result = ingest_universe(
        load_universe(UNIVERSE_PATH),
        collector=collector,
        store=_research_store(),
        api_key=api_key,
        end_date=end_date,
        full=full,
    )
    print(
        f"universe ingest through {end_date}: {len(result.collected)} collected, "
        f"{len(result.skipped)} already done, {len(result.failed)} failed"
    )
    if result.failed:
        raise SystemExit("rerun the same command to resume failed tickers")


def _ingest_proxies(end_date: date, min_interval_seconds: float) -> None:
    api_key = _required_environment("TIINGO_API_KEY")
    collector = TiingoEodCollector(
        source=_source(TIINGO_SOURCE_ID),
        transport=RateLimitedRetryTransport(
            UrllibHttpTransport(), minimum_interval_seconds=min_interval_seconds
        ),
        raw_store=_raw_store(),
        repository=_repository(),
    )
    specs = load_proxies(PROXIES_PATH, load_universe(UNIVERSE_PATH))
    result = ingest_universe(
        proxy_universe(specs),
        collector=collector,
        store=_research_store(),
        api_key=api_key,
        end_date=end_date,
        asset_type=AssetType.MUTUAL_FUND,
    )
    print(
        f"proxy ingest through {end_date}: {len(result.collected)} collected, "
        f"{len(result.skipped)} already done, {len(result.failed)} failed"
    )
    if result.failed:
        raise SystemExit("rerun the same command to resume failed funds")


def _verify_universe() -> None:
    checks = verify_universe(
        load_universe(UNIVERSE_PATH),
        store=_research_store(),
        raw_root=Path(os.getenv("RAW_STORE_PATH") or DEFAULT_RAW_STORE_PATH),
        config_path=UNIVERSE_PATH,
    )
    for check in checks:
        print(
            f"{check.ticker}\t{check.status}\texpected={check.expected.strftime('%Y-%m')}\t"
            f"provider_start={check.provider_start or '-'}\t"
            f"first_price={check.first_price_date or '-'}"
        )
    mismatches = [check.ticker for check in checks if check.status == "mismatch"]
    print(f"ok {len(checks) - len(mismatches)}, mismatch {len(mismatches)}")
    if mismatches:
        print("mismatch rows were not written to config; review: " + " ".join(mismatches))


def _print_universe_status() -> None:
    rows = universe_status(load_universe(UNIVERSE_PATH), store=_research_store())
    header = [field.name for field in fields(StatusRow)]
    table = [header] + [[_cell(value) for value in astuple(row)] for row in rows]
    widths = [max(len(line[column]) for line in table) for column in range(len(header))]
    for line in table:
        print("  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)))
    STATUS_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with STATUS_CSV_PATH.open("w", newline="") as csv_file:
        csv.writer(csv_file).writerows(table)
    print(f"wrote {STATUS_CSV_PATH}")


def _analyze_universe() -> None:
    analysis = analyze_universe(load_universe(UNIVERSE_PATH), store=_research_store())
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    risk_path = REPORT_DIR / "analysis_risk.csv"
    with risk_path.open("w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            ["ticker", "months", "volatility", "max_drawdown", "var_95", "equal_weight_risk_share"]
        )
        for row in analysis.assets:
            share = analysis.risk_contribution.get(row.ticker)
            writer.writerow(
                [
                    row.ticker,
                    row.months,
                    *(_ratio(v) for v in (row.volatility, row.max_drawdown, row.var_95, share)),
                ]
            )
    tickers = sorted({first for first, _ in analysis.correlation})
    correlation_path = REPORT_DIR / "analysis_correlation.csv"
    with correlation_path.open("w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["", *tickers])
        for first in tickers:
            writer.writerow(
                [first, *(_ratio(analysis.correlation[first, second]) for second in tickers)]
            )
    print(f"as of {analysis.as_of}, window {analysis.window_months} months")
    if analysis.excluded:
        print(f"excluded from the window statistics: {', '.join(analysis.excluded)}")
    print(f"wrote {risk_path}\nwrote {correlation_path}")


def _backtest(window_months: int) -> None:
    universe = load_universe(UNIVERSE_PATH)
    result = run_backtest(
        load_strategies(STRATEGIES_PATH, universe),
        _float_returns(_research_store()),
        cash_ticker=_cash_ticker(universe),
        window_months=window_months,
    )
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "" if window_months == WINDOW_MONTHS else f"_w{window_months}"
    performance_path = REPORT_DIR / f"backtest_performance{suffix}.csv"
    with performance_path.open("w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        header = [
            "strategy",
            "rule",
            "start",
            "end",
            "months",
            "cagr",
            "volatility",
            "sharpe",
            "sortino",
            "calmar",
            "max_drawdown",
            "mean_monthly_turnover",
        ]
        for name in BENCHMARKS:
            header += [f"{name}_excess_cagr", f"{name}_tracking_error", f"{name}_information_ratio"]
        header.append("calc_version")
        writer.writerow(header)
        for row in result.rows:
            p = row.performance
            line = [
                row.strategy,
                row.rule,
                row.start,
                row.end,
                p.months,
                *(
                    _ratio(v)
                    for v in (
                        p.cagr,
                        p.volatility,
                        p.sharpe,
                        p.sortino,
                        p.calmar,
                        p.max_drawdown,
                        row.mean_turnover,
                    )
                ),
            ]
            for name in BENCHMARKS:
                rel = row.versus.get(name)
                line += (
                    [
                        _ratio(rel.excess_cagr),
                        _ratio(rel.tracking_error),
                        _ratio(rel.information_ratio),
                    ]
                    if rel
                    else ["", "", ""]
                )
            writer.writerow([*line, BACKTEST_CALC_VERSION])
    monthly_path = REPORT_DIR / f"backtest_monthly{suffix}.csv"
    with monthly_path.open("w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["strategy", "rule", "month", "total_return", "coverage", "turnover"])
        for (strategy_id, rule), results in result.months.items():
            for item in results:
                writer.writerow(
                    [
                        strategy_id,
                        rule,
                        item.month,
                        f"{item.total_return:.6f}",
                        f"{item.coverage:.4f}",
                        f"{item.turnover:.4f}",
                    ]
                )
    print(
        f"common period {result.common_months[0]} .. {result.common_months[-1]} "
        f"({len(result.common_months)} months)"
    )
    print(f"wrote {performance_path}\nwrote {monthly_path}")


def _dashboard() -> None:
    universe = load_universe(UNIVERSE_PATH)
    store = _research_store()
    strategies = load_strategies(STRATEGIES_PATH, universe)
    returns = _float_returns(store)
    cash_ticker = _cash_ticker(universe)
    months, _ = store.latest_build()
    specs = load_proxies(PROXIES_PATH, universe)
    macro_points = {
        series_id: [
            (p.observation_date, None if p.value is None else float(p.value))
            for p in store.macro_points(series_id)
        ]
        for series_id in MARKET_INPUT_SERIES
    }
    try:
        regime_rows, _ = run_regime(store)
        quadrants_ip = ip_quadrants(first_release_series(store), [r.month_end for r in regime_rows])
    except SystemExit as error:
        print(f"regime section skipped: {error}")
        regime_rows, quadrants_ip = (), None
    long_context = None
    if regime_rows:
        try:
            long_rows, long_ip, long_returns = run_regime_long(store)
            long_context = LongContext(
                long_rows,
                long_ip,
                long_returns,
                spliced_levels(specs, store=store, ticker="SPY"),
                macro_points,
            )
        except SystemExit as error:
            print(f"long-history section skipped: {error}")
    payload = build_payload(
        run_backtest(strategies, returns, cash_ticker=cash_ticker),
        analyze_universe(universe, store=store),
        universe=universe,
        strategies=strategies,
        returns=returns,
        proxy_months={t: [m for m, is_proxy in rows if is_proxy] for t, rows in months.items()},
        cash_ticker=cash_ticker,
        generated_on=datetime.now(UTC).date(),
        regime_rows=regime_rows,
        quadrants_ip=quadrants_ip,
        equity_levels=[
            (point.trading_date, float(point.level))
            for point in total_return_index(store.price_points(tiingo_asset_id("SPY")))
        ],
        macro_points=macro_points,
        long_context=long_context,
        proxies=_proxy_summary(store, specs),
        dividends=_dividend_summary(store, universe),
    )
    _write_report("dashboard.html", render_dashboard(payload))


def _dividend_summary(store: ResearchStore, universe: Sequence[UniverseAsset]) -> dict[str, dict]:
    summary = {}
    for asset in universe:
        dividends, splits, latest, first = store.dividend_inputs(tiingo_asset_id(asset.ticker))
        if latest is None or first is None:
            continue
        result = trailing_dividend_yield(dividends, splits, latest[1], latest[0], first)
        if result is not None:
            summary[asset.ticker] = {
                "yield": float(result.dividend_yield),
                "annual": float(result.annual_per_share),
                "payments": result.payments,
                "as_of": result.as_of.isoformat(),
                "calc_version": result.calc_version,
            }
    return summary


def _proxy_summary(store: ResearchStore, specs: tuple[ProxySpec, ...]) -> list[dict]:
    proxy_months = store.latest_proxy_returns()
    name_of = {spec.target: spec.name for spec in specs}
    summary = []
    for row in store.latest_proxy_checks():
        months = sorted(proxy_months.get(row.ticker, {}))
        summary.append(
            {
                "ticker": row.ticker,
                "proxy": row.proxy_ticker,
                "name": name_of.get(row.ticker, ""),
                "fidelity": row.fidelity,
                "used": row.used,
                "reason": row.reason,
                "overlap_months": row.overlap_months,
                "correlation": None if row.correlation is None else round(row.correlation, 3),
                "tracking_difference": None
                if row.annual_tracking_difference is None
                else round(row.annual_tracking_difference, 4),
                "first_month": months[0].isoformat() if months else None,
                "last_month": months[-1].isoformat() if months else None,
                "months": len(months),
            }
        )
    return summary


def _write_report(name: str, html: str) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / name
    path.write_text(html, encoding="utf-8")
    print(f"wrote {path}")


def _cash_ticker(universe: tuple[UniverseAsset, ...]) -> str:
    return next(asset.ticker for asset in universe if asset.group == "cash")


def _float_returns(store: ResearchStore) -> dict[str, dict[date, float]]:
    return {
        ticker: {month: float(value) for month, value in by_month.items()}
        for ticker, by_month in store.latest_returns().items()
    }


def _ratio(value: float | None) -> str:
    return "" if value is None else f"{value:.4f}"


def _ingest_fred(series_id: str) -> None:
    api_key = _required_environment("FRED_API_KEY")
    collector = FredCollector(
        source=_source(FRED_SOURCE_ID),
        transport=UrllibHttpTransport(),
        raw_store=_raw_store(),
        repository=_repository(),
    )
    count = collector.collect(series_id=series_id, api_key=api_key)
    print(f"collected {count} FRED {series_id} observations")


def _build_returns() -> None:
    result, computed_at = build_returns(load_universe(UNIVERSE_PATH), store=_research_store())
    months = sum(len(items) for items in result.returns.values())
    anomalies = sum(len(items) for items in result.anomalies.values())
    print(f"built {months} monthly returns, {anomalies} anomalies at {computed_at}")
    for ticker, reason in result.failures.items():
        print(f"{ticker}: not built ({reason})")
    if not any(item.is_proxy for items in result.returns.values() for item in items):
        print("no DTB3 cash proxy months: run `asset-frame ingest-fred --series DTB3` first")
    _build_proxy_returns()


def _build_proxy_returns() -> None:
    specs = load_proxies(PROXIES_PATH, load_universe(UNIVERSE_PATH))
    store = _research_store()
    returns, checks, calc_version = build_proxy_returns(specs, store=store)
    store.save_proxy_build(
        returns,
        checks,
        proxy_by_target={spec.target: (spec.proxy, spec.fidelity) for spec in specs},
        calc_version=calc_version,
    )
    months = sum(len(items) for items in returns.values())
    print(f"built {months} proxy months for {len(returns)} of {len(specs)} targets")
    for row in checks:
        correlation = "-" if row.correlation is None else f"{row.correlation:.3f}"
        tracking = (
            "-"
            if row.annual_tracking_difference is None
            else f"{row.annual_tracking_difference:+.2%}"
        )
        verdict = "USED" if row.used else f"not used: {row.reason}"
        print(
            f"  {row.ticker:<5} <- {row.proxy_ticker:<6} {row.fidelity:<6} "
            f"overlap {row.overlap_months:>3} corr {correlation} tracking {tracking}/yr {verdict}"
        )


def _cell(value: object) -> str:
    return "-" if value is None else str(value)


def _source(source_id: str) -> SourceDefinition:
    return next(source for source in load_source_registry(SOURCES_PATH) if source.id == source_id)


def _regime(long: bool = False) -> None:
    store = _research_store()
    if long:
        rows, _, _ = run_regime_long(store)
        scores = tuple(score(rows, rule) for rule in RULES)
    else:
        rows, scores = run_regime(store)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / ("regime_replay_long.csv" if long else "regime_replay.csv")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow([field.name for field in fields(rows[0])])
        writer.writerows(astuple(row) for row in rows)
    print(f"wrote {path} ({len(rows)} months)")
    for result in scores:
        print(
            f"{result.rule}: scored {result.months} months, NBER recession months "
            f"{result.recession_months}, detected {result.detected}, false alarms "
            f"{result.false_alarms}"
        )
        for start, lag in result.episodes:
            print(
                f"  episode {start:%Y-%m}: first flag {'never' if lag is None else lag} months in"
            )


def _ledger(arguments: argparse.Namespace) -> None:
    command = arguments.ledger_command
    ledger = LedgerStore(_database_path())
    if command == "record-regime":
        rows, _ = run_regime(_research_store())
        appended, skipped = record_regime(ledger, rows, replay_all=arguments.replay)
        print(f"appended {appended}, already in ledger {skipped}")
    elif command in ("predict-models", "predict", "score"):
        returns = _float_returns(_research_store())
        if "SPY" not in returns:
            raise SystemExit("no monthly returns: run `asset-frame build-returns`")
        month_ends = sorted(returns["SPY"])
        anchors = [
            a.ticker for a in load_universe(UNIVERSE_PATH) if a.level == 1 and a.role == "anchor"
        ]
        if command == "predict-models":
            print(f"appended {record_predictions(ledger, returns, anchors, month_ends)}")
        elif command == "predict":
            try:
                new = record_human_prediction(
                    ledger,
                    anchors,
                    month_ends,
                    [t.strip().upper() for t in arguments.ranking.split(",")],
                    arguments.positive_prob,
                    arguments.note,
                )
            except ValueError as error:
                raise SystemExit(str(error)) from error
            print("appended" if new else f"already predicted for {month_ends[-1]}")
        else:
            print(f"scored {score_due(ledger, returns, month_ends)}")
    elif command == "scoreboard":
        for board in scoreboard(ledger):
            print(
                f"{board.model}: scored {board.scored}, mean IC {_ratio(board.mean_ic)} "
                f"(MDE {_ratio(board.ic_mde) or 'n/a: <5 samples'}), "
                f"mean top-bottom spread {_ratio(board.mean_spread)}, "
                f"mean Brier {_ratio(board.mean_brier)}"
            )
    entries = ledger.entries()
    broken = first_broken_seq(entries)
    if broken is not None:
        raise SystemExit(f"ledger chain broken at entry {broken}")
    head = entries[-1].entry_hash if entries else "(empty)"
    print(f"ledger ok: {len(entries)} entries, head {head}")


def _backup() -> None:
    destination = Path(os.getenv("BACKUP_PATH") or DEFAULT_BACKUP_PATH).expanduser()
    raw_root = Path(os.getenv("RAW_STORE_PATH") or DEFAULT_RAW_STORE_PATH)
    target, copied = backup(_database_path(), raw_root, destination, date.today())
    print(f"database -> {target}\nraw files copied: {copied}")


def _database_path() -> Path:
    return Path(os.getenv("DATABASE_PATH") or DEFAULT_DATABASE_PATH)


def _repository() -> SqliteIngestionRepository:
    return SqliteIngestionRepository(_database_path())


def _research_store() -> ResearchStore:
    return ResearchStore(_database_path())


def _raw_store() -> FileRawStore:
    return FileRawStore(Path(os.getenv("RAW_STORE_PATH") or DEFAULT_RAW_STORE_PATH))


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"required environment variable is missing: {name}")
    return value
