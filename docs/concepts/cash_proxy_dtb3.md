# 현금 수익률 대용 (`cash_proxy_dtb3`)

- 분류: 분산투자기법(현금 자산군의 장기 이력)
- 상태: implemented
- 구현: `src/asset_frame/returns/series.py` — `cash_proxy_returns`, `splice_cash`
- 데이터: FRED `DTB3`(3-Month Treasury Bill Secondary Market Rate, Discount Basis, 일별, %) — `asset-frame ingest-fred --series DTB3`
- 테스트: `tests/test_returns.py`, `tests/test_fred_connector.py`

## 정의

현금 앵커 BIL은 2007년에 상장했다. 그 전 구간의 현금 수익률을 3개월 국채 할인율로 대신 만든다.

## 공식 (근사)

R_m ≈ (그 달 DTB3 일별 값의 평균 %) / 100 / 12

- 값이 없는 날(FRED의 ".", DB에서는 NULL)은 평균에서 뺀다. 0으로 바꾸지 않는다. 그 달에 값이 하나도 없으면 대용 수익률을 만들지 않는다.
- 같은 날짜가 여러 번 수집되었으면 가장 최근에 수집한 값을 쓴다(현재 빈티지). ALFRED 빈티지는 M2에서 쓴다.

## 이음 규칙

- BIL의 첫 월간 수익률 이전 달에만 대용 값을 쓰고, `is_proxy = true`로 표시한다.
- 그 이후에는 대용 값이 있어도 BIL만 쓴다.
- 대용 월의 `source_price_version`은 `fred:DTB3:<snapshot ID>` 형식이다.

## 교재와 다른 점 (이 근사의 한계)

- **할인율 ≠ 수익률.** DTB3는 할인율(discount basis)이다. 실제 보유수익률(투자수익률, bond-equivalent yield)은 할인율보다 약간 높다. 이 차이를 보정하지 않는다.
- **단순 ÷12.** 연율을 12로 나누는 단순 근사이며, 월 복리나 실제 일수(act/360)를 반영하지 않는다.
- **월평균.** 그 달에 금리가 크게 움직였으면 월평균은 실제 보유 수익률과 다를 수 있다.
- **ETF와의 차이.** BIL은 1~3개월 만기이고 운용보수가 빠진다. 대용 값에는 보수가 없다. 그래서 이음 시점 전후의 수준 차이가 생길 수 있다.

현재 금리 수준(연 2~5%)에서 이 근사의 월간 오차는 작다고 보지만 정량적으로 확인하지 않았다. BIL과 대용 값이 겹치는 기간의 비교는 M1-2에서 할 수 있다.
