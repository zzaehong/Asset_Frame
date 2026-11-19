# 정보비율과 추적오차 (`information_ratio`)

- 분류: 투자운용결과분석
- 상태: implemented
- 구현: `src/asset_frame/backtest/metrics.py` — `relative`
- 테스트: `tests/test_backtest.py`
- 출력: `asset-frame backtest` → `var/reports/backtest_performance.csv`, `backtest_monthly.csv`

## 정의

벤치마크 대비 초과수익을 추적오차로 나눈 값이다. 추적오차는 벤치마크와의 수익률 차이의 변동성이다.

## 공식

active_t = R_t − B_t, TE = std(active) × √12, IR = mean(active) × 12 / TE, excess CAGR = CAGR(R) − CAGR(B)

## 구현상의 선택

- 벤치마크는 SPY 100%와 60/40 두 가지이고, 같은 리밸런싱 규칙을 적용한 벤치마크와 비교한다.
- 비교 구간은 모든 전략이 의도한 비중을 다 담는(coverage 1) 구간이다.
- 벤치마크와 같은 시계열이면 추적오차가 0이라 정보비율은 없음이다.

## 교재와 다른 점

- 이 프로젝트의 성공 기준(PRD 2절)은 상대 기준이라 벤치마크 대비 값을 함께 낸다.
