# 위험기여도 (`risk_contribution`)

- 분류: 분산투자기법
- 상태: implemented
- 구현: `src/asset_frame/analytics/risk.py` — `covariance_matrix`, `risk_contributions`; `src/asset_frame/analytics/allocation.py` — `inverse_volatility_weights`, `equal_risk_contribution_weights`
- 테스트: `tests/test_analytics.py`, `tests/test_allocation.py`
- 출력: `asset-frame universe analyze` → `var/reports/analysis_risk.csv`, `analysis_correlation.csv`

## 정의

포트폴리오 분산 중 각 자산이 차지하는 몫이다. 몫을 모두 더하면 1이다.

## 공식

RC_i = w_i × (Σw)_i / (wᵀΣw), Σ = 표본 공분산(ddof=1, 36개월 창)

## 구현상의 선택

- CSV의 `equal_weight_risk_share`는 1단계 자산군 앵커(12개)를 동일가중했을 때의 값이다(`equal_weight` 전략). 36개월 창이 모두 있는 앵커만 포함한다.
- 비중이 같아도 위험 몫은 다르다는 것을 보는 용도다.
- 위험균등 전략: `inv_vol`은 비중이 1/σ에 비례한다. `erc`는 위험기여도가 모두 같아지는 비중이며 좌표 하강으로 푼다(`equal_risk_contribution_weights`). 상관이 없으면 두 전략이 같다. 수렴하지 않으면 오류를 낸다.
- 현금(BIL)은 변동성이 매우 낮아 두 전략 모두 현금에 비중이 크게 쏠린다(2026-10 기준 inv_vol 73%, erc 84%). PRD의 "자산군 앵커" 정의를 그대로 따른 결과이고, 현금은 다른 자산과 같은 하나의 자산이라는 결정(로드맵 3절)에 따라 빼지 않는다.
- 공분산은 추정 오차가 크다. 36개월에 자산 12개이면 표본이 적다(민감도 분석은 M1-3).

## 교재와 다른 점

- 교재의 오일러 분해와 같다. 롱온리 비중만 다룬다.
