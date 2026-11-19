# 위험기여도 (`risk_contribution`)

- 분류: 분산투자기법
- 상태: implemented
- 구현: `src/asset_frame/analytics/risk.py` — `covariance_matrix`, `risk_contributions`
- 테스트: `tests/test_analytics.py`
- 출력: `asset-frame universe analyze` → `var/reports/analysis_risk.csv`, `analysis_correlation.csv`

## 정의

포트폴리오 분산 중 각 자산이 차지하는 몫이다. 몫을 모두 더하면 1이다.

## 공식

RC_i = w_i × (Σw)_i / (wᵀΣw), Σ = 표본 공분산(ddof=1, 36개월 창)

## 구현상의 선택

- CSV의 `equal_weight_risk_share`는 1단계 자산군 앵커(12개)를 동일가중했을 때의 값이다(`equal_weight` 전략). 36개월 창이 모두 있는 앵커만 포함한다.
- 비중이 같아도 위험 몫은 다르다는 것을 보는 용도다. 위험균등 전략(`erc`)의 비중 계산은 M1-3에서 한다.
- 공분산은 추정 오차가 크다. 36개월에 자산 12개이면 표본이 적다(민감도 분석은 M1-3).

## 교재와 다른 점

- 교재의 오일러 분해와 같다. 롱온리 비중만 다룬다.
