# 변동성 (`volatility`)

- 분류: 리스크관리
- 상태: implemented
- 구현: `src/asset_frame/analytics/risk.py` — `annualized_volatility`
- 테스트: `tests/test_analytics.py`
- 출력: `asset-frame universe analyze` → `var/reports/analysis_risk.csv`, `analysis_correlation.csv`

## 정의

월간 총수익률의 표준편차를 연율로 나타낸 값이다.

## 공식

σ = s × √12, s = 표본 표준편차(ddof=1)

## 구현상의 선택

- 입력은 월간 총수익률이다. 일간 변동성보다 단기 변동을 덜 보여 준다.
- 자산의 전체 이력에 계산하며, 이력 길이(`months`)를 같이 출력한다. 짧은 이력의 값은 비교에 조심한다.
- 현금 대용(DTB3) 월도 수익률에 포함된다.

## 교재와 다른 점

- 교재는 표본/모집단 구분 없이 설명하는 경우가 많다. 여기서는 ddof=1로 고정했다.
- 연율화는 월 수익률이 독립이라는 가정(√12)에 기댄다. 자기상관이 있으면 틀어진다.
