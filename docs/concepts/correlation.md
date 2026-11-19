# 상관계수 (`correlation`)

- 분류: 분산투자기법
- 상태: implemented
- 구현: `src/asset_frame/analytics/risk.py` — `trailing_months`, `aligned_window`, `correlation_matrix`
- 테스트: `tests/test_analytics.py`
- 출력: `asset-frame universe analyze` → `var/reports/analysis_risk.csv`, `analysis_correlation.csv`

## 정의

두 자산의 월간 수익률이 함께 움직이는 정도다. −1에서 1 사이다.

## 공식

피어슨 상관계수 ρ = cov(a, b) / (s_a × s_b)

## 구현상의 선택

- 창은 SPY 월 달력의 마지막 36개월이다(PRD 6절). 36개월이 모두 있는 자산만 계산하고, 모자란 자산은 `excluded`로 알린다.
- 한쪽이 상수 수익률이면 정의되지 않아 빈 칸으로 둔다.
- 상관은 국면에 따라 변한다([로드맵](../roadmap.md) 3.2절의 주식-채권 상관 부호). 이 값은 현재 창의 한 시점이다.

## 교재와 다른 점

- 롤링 시계열 전체가 아니라 가장 최근 창 하나만 출력한다. 시계열은 M2(국면)에서 필요할 때 만든다.
