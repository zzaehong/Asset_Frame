# ADR-0001: 데이터 수집 저장 경계

- 상태: 채택
- 날짜: 2026-08-21

## 맥락

가격, 기업행동, 재무사실, 공시, ETF 보유내역, 거시 시계열은 시간 의미와 제약이
서로 다르다. 동시에 모든 canonical 값은 공급원과 불변 원본으로 역추적되어야 한다.

## 결정

- PostgreSQL을 canonical metadata와 정규화된 사실의 저장소로 사용한다.
- 공급자가 반환한 원본 bytes는 content-addressed local raw store에 먼저 저장한다.
- 원본의 SHA-256, 수집시각, 마스킹된 요청 URL, HTTP 상태를 PostgreSQL에 기록한다.
- canonical 테이블은 데이터 종류별로 분리하고 모두 `raw_snapshot_id`를 가진다.
- 검증 실패 또는 공급원 충돌 데이터는 canonical 테이블에 넣지 않고 quality issue로 격리한다.
- transport, raw store, repository를 protocol 경계로 분리하여 unit test에서 네트워크와
  PostgreSQL을 요구하지 않는다.

## 결과

원본 보존과 point-in-time 재현성이 확보되는 대신 local raw store와 PostgreSQL의 백업 및
정합성을 함께 관리해야 한다. raw 파일이 먼저 영속화되고 DB 기록이 실패할 경우 고아 파일이
남을 수 있으며, 이후 reconciliation job에서 탐지하도록 한다.
