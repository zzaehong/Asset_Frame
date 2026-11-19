# 샤프 비율 (`sharpe_ratio`)

- 분류: 투자운용결과분석
- 상태: implemented
- 구현: `src/asset_frame/backtest/metrics.py` — `performance`
- 테스트: `tests/test_backtest.py`
- 출력: `asset-frame backtest` → `var/reports/backtest_performance.csv`, `backtest_monthly.csv`

## 정의

무위험 수익률을 넘긴 초과수익을 총위험(표준편차) 한 단위로 나눈 값이다.

## 공식

S = mean(R_t − R_f,t) × 12 / (std(R_t − R_f,t) × √12), std는 표본(ddof=1)

## 구현상의 선택

- 무위험 수익률은 같은 달의 현금 수익률(BIL, 상장 전은 DTB3 대용)이다. 월별 초과수익으로 계산한다.
- 산술 평균을 쓰므로 복리 성과(CAGR)와 순위가 다를 수 있다. 초과수익의 표준편차가 0이면 없음이다.

## 교재와 다른 점

- 교재는 연 수익률과 연 표준편차로 계산한다. 월별 초과수익에서 연율화한 값이라 근사 차이가 있다.
