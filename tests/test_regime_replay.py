from datetime import date

from asset_frame.regime.replay import RegimeRow, replay, score

NO_RULES = dict(sahm=None, indpro_yoy=None, cfnai_ma3=None, quadrant=None)


def row(month: int, recession: bool, flag: bool | None) -> RegimeRow:
    return RegimeRow(
        month_end=date(2020, month, 28),
        indpro_sahm=flag,
        cfnai_sahm=None,
        stock_bond_correlation=None,
        correlation_regime=None,
        nber_recession=recession,
        **NO_RULES,
    )


def test_score_counts_detection_false_alarms_and_lag() -> None:
    rows = (
        row(1, False, True),  # false alarm
        row(2, True, False),  # episode starts, missed
        row(3, True, True),  # first flag: 1 month after the start
        row(4, True, True),
        row(5, False, False),
        row(6, False, None),  # rule had no inputs: not scored
    )

    result = score(rows, "indpro_sahm")

    assert (result.months, result.recession_months, result.detected) == (5, 3, 2)
    assert result.false_alarms == 1
    assert result.episodes == ((date(2020, 2, 28), 1),)


def test_score_reports_a_missed_episode_and_an_open_one() -> None:
    missed = score((row(1, True, False), row(2, False, False)), "indpro_sahm")
    assert missed.episodes == ((date(2020, 1, 28), None),)
    open_episode = score((row(11, True, False), row(12, True, True)), "indpro_sahm")
    assert open_episode.episodes == ((date(2020, 11, 28), 1),)


def test_replay_uses_only_released_values_and_marks_missing_inputs() -> None:
    unrate = [(date(2006 + i // 12, i % 12 + 1, 1), date(2030, 1, 1), 4.0) for i in range(20)]
    series = {"INDPRO": [], "UNRATE": unrate, "CPIAUCSL": [], "CFNAIMA3": []}

    rows = replay(series, {date(2007, 2, 1): True}, {}, [date(2007, 1, 31), date(2007, 2, 28)])

    assert [r.sahm for r in rows] == [None, None]  # nothing released yet
    assert [r.nber_recession for r in rows] == [False, True]
    assert rows[0].stock_bond_correlation is None
