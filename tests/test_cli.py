from pathlib import Path

import pytest

from asset_frame.cli import _required_environment, main


def test_required_environment_rejects_missing_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_TEST_VALUE", raising=False)

    with pytest.raises(SystemExit):
        _required_environment("MISSING_TEST_VALUE")


def test_sources_lists_the_four_registered_sources(capsys: pytest.CaptureFixture[str]) -> None:
    main(["sources"])

    lines = capsys.readouterr().out.splitlines()
    assert sorted(line.split("\t")[0] for line in lines) == [
        "ecos",
        "fred",
        "krx-open-api",
        "tiingo-eod",
    ]


def test_ingest_commands_require_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    monkeypatch.delenv("KRX_API_KEY", raising=False)
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    with pytest.raises(SystemExit, match="TIINGO_API_KEY"):
        main(
            [
                "ingest-tiingo",
                "--ticker",
                "SPY",
                "--asset-type",
                "etf",
                "--start-date",
                "2026-01-02",
                "--end-date",
                "2026-01-05",
            ]
        )
    with pytest.raises(SystemExit, match="KRX_API_KEY"):
        main(["ingest-krx", "--dataset", "etf_prices", "--date", "2026-01-05"])
    with pytest.raises(SystemExit, match="FRED_API_KEY"):
        main(["ingest-fred", "--series", "DTB3"])
    with pytest.raises(SystemExit, match="TIINGO_API_KEY"):
        main(["ingest-universe"])


def test_ingest_stocks_with_nothing_selected_stops_before_any_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)  # would fail first if it got that far
    empty = tmp_path / "stocks.toml"
    empty.write_text("schema_version = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "asset_frame.cli.STOCKS_PATH", empty
    )  # the user's own selection is not a fixture

    with pytest.raises(SystemExit, match="no stocks selected"):
        main(["ingest-stocks"])
