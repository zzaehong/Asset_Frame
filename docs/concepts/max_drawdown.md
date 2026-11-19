# 최대낙폭 (`max_drawdown`)

- 분류: 리스크관리
- 상태: implemented
- 구현: `src/asset_frame/analytics/risk.py` — `max_drawdown`
- 테스트: `tests/test_analytics.py`
- 출력: `asset-frame universe analyze` → `var/reports/analysis_risk.csv`, `analysis_correlation.csv`

## 정의

누적 가치가 직전 최고점에서 가장 크게 떨어진 비율이다. 0 또는 음수다.

## 공식

W_t = Π(1 + R_k), 시작값 1. MDD = min_t (W_t / max_{s≤t} W_s − 1)

## 구현상의 선택

- 월말 값만 보므로 달 안에서 더 깊었던 낙폭은 보이지 않는다. 실제 낙폭은 이 값보다 클 수 있다.
- PRD 2절: 전략의 최대낙폭은 같은 기간 벤치마크와 비교하는 상대 기준이다. −20%는 경고 표시일 뿐 탈락 기준이 아니다.

## 교재와 다른 점

- 회복 기간은 계산하지 않는다(M1-3 이후 필요하면 추가).
