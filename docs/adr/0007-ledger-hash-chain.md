# ADR-0007: 원장 해시 체인 형식

- 상태: 채택
- 날짜: 2026-11-19
- 관련: [ADR-0005](0005-hypothesis-ledger.md) 결정 4(해시 체인, replay·live 분리)를 구현하는 형식

## 결정

- 원장은 운영 SQLite의 `ledger_entry` 테이블이다(새 의존성 없음). 항목은 `seq`(1부터 연속), `entry_type`, `payload`(정규 JSON), `created_at`(UTC), `prev_hash`, `entry_hash`를 갖는다.
- `entry_hash = SHA-256(정규 JSON [seq, prev_hash, entry_type, payload, created_at])`. 첫 항목의 `prev_hash`는 `0` 64개다. 정규 JSON은 키 정렬, 공백 없음, 비ASCII 유지다.
- `BEFORE UPDATE`·`BEFORE DELETE` 트리거가 수정과 삭제를 거부한다. 같은 `entry_key`는 한 번만 들어간다(재실행 중복 방지).
- `kind`는 payload 안에 둔다. `live`는 그 달 판단 직후 기록한 항목, `replay`는 과거 월을 사후에 재현한 항목이다. 둘은 키가 달라 공존하며, 보고서에서 합산하지 않는다.
- 항목 종류는 M2-3에서 `regime_observation`뿐이다. 예측과 채점은 M2-4에서 `prediction`·`score`로 추가한다.

## 결과와 한계

- 항목을 고치거나 지우면 이후 해시가 어긋나고(`ledger verify`가 첫 어긋난 번호를 출력), 중간 삭제는 `seq` 틈으로 드러난다.
- **DB 파일을 가진 사람은 체인 전체를 새로 계산해 바꿀 수 있다.** 이 해시 체인은 실수와 부분 변조를 감지할 뿐이다. 이를 막으려면 `ledger verify`가 출력하는 head 해시를 DB 밖(노트·메시지 등)에 가끔 적어 두어야 한다.
- `live`의 시점 보증은 약하다. `record-regime`을 판단 달이 끝난 뒤 늦게 실행하면 `created_at`이 그만큼 늦다. `created_at`이 그대로 남아 늦은 기록은 구별된다.
- 백업(`backup`)은 DB를 그대로 복사하므로 원장도 함께 복사된다.
