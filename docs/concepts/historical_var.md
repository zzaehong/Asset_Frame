# 역사적 VaR (`historical_var`)

- 분류: 리스크관리
- 상태: implemented
- 구현: `src/asset_frame/analytics/risk.py` — `historical_var`
- 테스트: `tests/test_analytics.py`
- 출력: `asset-frame universe analyze` → `var/reports/analysis_risk.csv`, `analysis_correlation.csv`

## 정의

과거 월간 수익률 분포에서 하위 5% 지점의 손실이다. "한 달 동안 95% 확률로 이 손실을 넘지 않는다"를 과거 자료로 추정한 값이다. 양수가 손실이다.

## 공식

정렬한 n개 수익률의 위치 h = (n−1)(1−0.95)를 선형 보간한 값 q에 대해 VaR = −q

## 구현상의 선택

- 신뢰수준 95%, 보유기간 1개월, 분포 가정 없음(역사적 방법)이다.
- 표본이 21개보다 적으면 하위 5% 지점이 최악 관측치에 가까워 불안정하다. `months`를 같이 본다.
- 꼬리 손실의 크기는 알려 주지 않는다(기대부족액은 계산하지 않는다).

## 교재와 다른 점

- 분위수 보간법에 따라 값이 조금 다르다. 여기서는 선형 보간(위치 (n−1)p)을 쓴다.
