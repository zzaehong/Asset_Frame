# 연복리수익률과 칼마 비율 (`cagr_calmar`)

- 분류: 투자운용결과분석
- 상태: implemented
- 구현: `src/asset_frame/backtest/metrics.py` — `performance`
- 테스트: `tests/test_backtest.py`
- 출력: `asset-frame backtest` → `var/reports/backtest_performance.csv`, `backtest_monthly.csv`

## 정의

CAGR은 기간 전체를 연 복리로 환산한 수익률이다. 칼마 비율은 CAGR을 최대낙폭의 절댓값으로 나눈 값이다.

## 공식

CAGR = (Π(1+R_t))^(12/n) − 1, Calmar = CAGR / |MDD|

## 구현상의 선택

- 월간 총수익률을 곱해 기하 평균으로 환산한다. 최대낙폭이 0이면 칼마는 없음으로 둔다.
- 최대낙폭은 월말 값 기준이다([max_drawdown](max_drawdown.md)).

## 교재와 다른 점

- 칼마는 보통 36개월 구간을 쓰지만 여기서는 비교 구간 전체를 쓴다.
