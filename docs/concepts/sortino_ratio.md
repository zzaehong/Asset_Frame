# 소르티노 비율 (`sortino_ratio`)

- 분류: 투자운용결과분석
- 상태: implemented
- 구현: `src/asset_frame/backtest/metrics.py` — `performance`
- 테스트: `tests/test_backtest.py`
- 출력: `asset-frame backtest` → `var/reports/backtest_performance.csv`, `backtest_monthly.csv`

## 정의

샤프 비율에서 분모를 하방 위험(목표 수익률 아래로 떨어진 변동)만으로 바꾼 값이다.

## 공식

DD = sqrt(mean(min(R_t − R_f,t, 0)²)), Sortino = mean(R_t − R_f,t) × 12 / (DD × √12)

## 구현상의 선택

- 최소 허용 수익률(MAR)은 무위험 수익률이다. 전체 달 수로 평균 낸다(손실이 난 달만의 평균이 아니다).
- 손실이 난 달이 없으면 없음이다.

## 교재와 다른 점

- MAR을 0으로 두는 교재도 있다. 여기서는 샤프와 같은 기준(현금 초과)에 맞췄다.
