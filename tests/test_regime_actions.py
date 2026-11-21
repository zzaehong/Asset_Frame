from asset_frame.regime.actions import macro_actions, quadrant_actions, warnings


def stats(mean: float, independent: int = 10, hit: float = 0.6) -> dict:
    return {"6": {"n": independent * 6, "independent": independent, "mean": mean, "hit_rate": hit}}


def performance(assets: dict[str, dict]) -> dict:
    return {
        "all": {"months": 100, "assets": {t: stats(0.03) for t in assets}},
        "axes": {"quadrant": {"up_up": {"months": 60, "assets": assets}}},
    }


def test_top_and_bottom_three_by_mean_with_ties_broken_by_ticker() -> None:
    assets = {
        t: stats(m)
        for t, m in zip("ABCDEFG", [0.07, 0.05, 0.05, 0.01, -0.01, -0.04, -0.06], strict=True)
    }
    result = quadrant_actions(performance(assets), "quadrant", list("ABCDEFG"))["up_up"]
    assert [e["ticker"] for e in result["strong"]] == ["A", "B", "C"]
    assert [e["ticker"] for e in result["weak"]] == ["G", "F", "E"]
    assert result["eligible"] == 7 and result["baseline"]["A"] == 0.03


def test_assets_with_few_independent_outcomes_are_not_ranked() -> None:
    assets = {t: stats(0.01 * i) for i, t in enumerate("ABCDE")}
    assets["F"] = stats(9.9, independent=4)  # looks great but too thin
    result = quadrant_actions(performance(assets), "quadrant", list("ABCDEF"))["up_up"]
    assert result["eligible"] == 5 and "F" not in [e["ticker"] for e in result["strong"]]
    assert len(result["strong"]) == 2  # 5 eligible: min(3, 5 // 2)


def test_too_little_history_gives_no_suggestion() -> None:
    assets = {t: stats(0.01 * i) for i, t in enumerate("ABC")}
    result = quadrant_actions(performance(assets), "quadrant", list("ABC"))["up_up"]
    assert result["strong"] == [] and result["weak"] == [] and result["eligible"] == 3


def test_missing_axis_or_assets_are_empty() -> None:
    assert quadrant_actions(performance({}), "nope", ["A"]) == {}
    assert quadrant_actions(performance({"A": {}}), "quadrant", ["A"])["up_up"]["eligible"] == 0


def test_warning_thresholds() -> None:
    latest = {"spread_10y3m": -0.2, "fed_funds_change_6m": 1.0, "dollar_change_6m": 0.049}
    assert [w["state"] for w in warnings(latest)] == ["warn", "warn", "ok"]
    latest = {"spread_10y3m": 0.0, "fed_funds_change_6m": 0.99, "dollar_change_6m": 0.05}
    assert [w["state"] for w in warnings(latest)] == ["ok", "ok", "warn"]


def test_missing_readings_are_na_not_ok() -> None:
    assert [w["state"] for w in warnings(None)] == ["na", "na", "na"]
    assert [w["state"] for w in warnings({"spread_10y3m": None})][0] == "na"


def test_macro_actions_bundles_axes_and_warnings() -> None:
    assets = {t: stats(0.01 * i) for i, t in enumerate("ABCDEF")}
    result = macro_actions(performance(assets), ["quadrant"], list("ABCDEF"), {"spread_10y3m": 1.0})
    assert result["calc_version"] == "macro_action_v1" and "up_up" in result["axes"]["quadrant"]
    assert result["warnings"][0]["state"] == "ok"
