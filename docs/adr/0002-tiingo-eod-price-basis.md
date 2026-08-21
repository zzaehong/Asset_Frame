# ADR-0002: Tiingo EOD 가격과 기업행동 저장 기준

- 상태: 채택
- 날짜: 2026-08-21

## 맥락

Tiingo EOD는 같은 거래일에 raw OHLCV, 배당·분할을 반영한 CRSP 방식 조정 가격,
현금배당과 분할계수를 함께 제공한다. 원가격과 조정가격을 섞으면 공급원 비교와 위험 계산의
의미가 달라지며, 기업행동이 뒤늦게 반영되면 과거 조정가격도 바뀔 수 있다.

## 결정

- `open`, `high`, `low`, `close`, `volume`에는 Tiingo의 raw 값을 저장한다.
- `adjusted_close`에는 Tiingo의 `adjClose`를 저장하고 `price_basis`는
  `raw_with_crsp_adjusted_close`로 기록한다.
- `adjOpen`, `adjHigh`, `adjLow`, `adjVolume`은 canonical schema가 지원하기 전까지 raw
  snapshot에만 보존한다.
- `divCash > 0`은 배당 기업행동으로, `splitFactor != 1`은 분할 기업행동으로 저장한다.
  분할계수는 Tiingo 문서의 `splitTo / splitFrom` 의미를 그대로 보존한다.
- 기업행동이 포함된 기간을 갱신할 때는 조정 이력이 바뀔 수 있으므로 요청 기간 전체를 새 raw
  snapshot으로 다시 수집한다. 기존 snapshot을 덮어쓰지 않는다.
- raw와 adjusted 중 어느 가격을 분석 기본값으로 사용할지는 위험 엔진 구현 전에 별도 결정한다.

## 결과

원가격과 조정종가의 의미를 구분하고 기업행동 계보를 보존할 수 있다. 반면 조정 OHLC와 조정
거래량은 당분간 canonical query에서 직접 사용할 수 없으며 raw snapshot을 다시 파싱해야 한다.
