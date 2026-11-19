# 거시 지표의 최초 발표값 (`macro_first_release`)

- 분류: 거시경제분석(국면 판단의 입력)
- 상태: implemented
- 구현: `src/asset_frame/connectors/fred.py` — `FIRST_RELEASE_SERIES`, `build_observations_request`. 조회는 `ResearchStore.macro_first_releases`.
- 데이터: FRED `series/observations`, `output_type=4`(initial release only), `realtime_start=1776-07-04`, `realtime_end=9999-12-31` — `asset-frame ingest-fred --series <ID>`
- 테스트: `tests/test_fred_connector.py`

## 정의

거시 지표는 발표 뒤에 개정된다. 과거 시점의 판단을 재현(replay)할 때 현재의 개정값을 쓰면 그때 알 수 없던 정보가 섞인다(look-ahead). 그래서 각 관측월의 **처음 발표된 값**과 **그 발표일**(`realtime_start`)을 함께 저장한다. 시점 t의 판단에는 발표일이 t 이하인 값만 쓴다.

## 시리즈 (FRED 시리즈 페이지에서 2026-11-19 확인)

| ID | 내용 | 단위 | 수집 방식 | 저장된 최초 발표 이력 |
|---|---|---|---|---|
| `INDPRO` | 산업생산지수 | 지수(2017=100), 계절조정 | 최초 발표 | 1927-02~ |
| `UNRATE` | 실업률 | %, 계절조정 | 최초 발표 | 1960-04~ |
| `CPIAUCSL` | 소비자물가지수(전 품목) | 지수(1982-84=100), 계절조정 | 최초 발표 | 1972-08~ |
| `CFNAIMA3` | 시카고 연준 활동지수 3개월 이동평균 | 지수, 계절조정 안 됨 | 최초 발표 | 2011-06~(그 전은 최초 발표 이력 없음) |
| `USREC` | NBER 침체 더미(침체 후 정점~저점) | 0/1 | 현재 값 | 1854~ (평가용, 판단 입력에 쓰지 않음) |

- `SAHMREALTIME`(최초 발표 이력 2019-09~)은 수집만 해 두었고 쓰지 않는다. Sahm 지표는 `UNRATE` 최초 발표값으로 직접 계산한다(M2-2).

## 한계

- **CFNAIMA3의 2011-05 이전**은 point-in-time으로 재현할 수 없다. 2007~2011 구간에서 이 지표를 쓰면 개정값이 섞이므로 "point-in-time 아님"으로 표시해야 한다.
- 오래된 시기의 `realtime_start`는 ALFRED가 복원한 발표일이다. 정확한 발표 시각이 아닌 달력상 발표일로 본다.
- 발표 시차(INDPRO·CPI·UNRATE는 다음 달 중순, CFNAI는 다음 달 말)는 값마다 다르므로 `realtime_start`를 그대로 쓰고 임의의 시차를 가정하지 않는다.
- 결측("." → NULL)은 0으로 바꾸지 않는다.
