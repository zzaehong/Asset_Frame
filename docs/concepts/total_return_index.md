# 총수익 지수 (`total_return_index`)

- 분류: 투자운용결과분석
- 상태: implemented
- 구현: `src/asset_frame/returns/series.py` — `total_return_index`
- 테스트: `tests/test_returns.py`

## 정의

배당을 재투자했다고 가정한 누적 가치다. 첫 거래일을 1로 두고, 가격 변화와 분배금을 모두 반영한다.

## 공식

일간 총수익률 r_t = A_t / A_{t-1} − 1 (A는 Tiingo `adjClose`, CRSP 방식 배당·분할 조정 종가)

지수 I_0 = 1, I_t = I_{t-1} × (1 + r_t)

## 구현상의 선택

- Tiingo는 새 배당이 생길 때마다 `adjClose` 전체 이력을 다시 계산한다. 그래서 수집 시점(snapshot)이 다르면 같은 날의 `adjClose` 값도 다르다.
- 따라서 r_t는 **t−1일과 t일을 모두 포함하는 snapshot 하나 안에서만** 계산하고, 그런 snapshot이 여럿이면 가장 늦게 수집한 것을 쓴다. 지수는 그 r_t를 연쇄해서 곱한다. 서로 다른 snapshot의 가격을 직접 나누지 않는다.
- `ingest-universe`는 10년 단위 구간을 10일씩 겹쳐 요청하므로, 연속한 두 거래일은 항상 같은 snapshot에 함께 들어 있다. 그렇지 않은 경우가 생기면 조용히 넘어가지 않고 `UnlinkedPriceError`로 해당 자산의 계산을 멈춘다.
- 계산은 `Decimal`, 유효숫자 28자리로 하고 반올림하지 않는다.
- 일간 수익률의 절댓값이 25%를 넘으면 `return_anomaly`에 기록한다. 계산에서 빼지 않는다. 분할 조정 누락 의심을 사람이 확인하기 위한 표시다.

## 교재와 다른 점

- 교재의 총수익률은 (기말가격 − 기초가격 + 분배금) / 기초가격으로, 분배금을 받은 날 그대로 재투자한다고 본다. 여기서는 그 재투자 계산을 Tiingo의 조정 종가가 대신한다. 세금과 거래비용은 반영하지 않는다(M4에서 다룬다).
