# 월간 총수익률 (`monthly_return`)

- 분류: 투자운용결과분석
- 상태: implemented
- 구현: `src/asset_frame/returns/series.py` — `month_ends`, `monthly_returns`, `eligible_assets`
- 테스트: `tests/test_returns.py`
- 저장: SQLite `monthly_return(ticker, month_end, total_return, is_proxy, source_price_version, computed_at, calc_version)`

## 정의

한 달 동안의 총수익률이다. 전월 말 대비 당월 말의 총수익 지수 변화율이다.

## 공식

R_m = I(당월 말) / I(전월 말) − 1

## 구현상의 선택

- **월말:** SPY 거래일을 달력으로 쓰고, 각 달의 마지막 SPY 거래일을 월말로 본다.
- **자산의 월말 값:** 그 달 안에서 월말 이전의 마지막 자기 거래일 값을 쓴다. 그 달에 거래가 없으면 그 달과 다음 달의 수익률을 만들지 않는다(결측으로 남긴다).
- **첫 달:** 상장한 달은 전월 말 값이 없으므로 수익률을 만들지 않는다. 상장 다음 달이 첫 수익률이다.
- **최근 달:** SPY 달력의 가장 최근 달은 아직 끝나지 않았을 수 있으므로 계산하지 않는다. 다음 달 거래일이 수집되면 계산된다.
- **버전:** 빌드마다 같은 `computed_at`으로 전체를 새로 추가한다. 이전 빌드를 지우지 않는다. `source_price_version`에는 그 달 수익률에 쓰인 가격 snapshot ID를 적는다. `calc_version`은 `monthly_return_v1`이다.
- **편입 자격:** `eligible_assets(as_of)`는 판정월 말까지 월간 수익률이 13개 이상인 자산이다. 현금은 DTB3 대용 월도 개수에 포함한다.
- **앵커 보존:** 자산마다 독립적으로 계산하고, 자산 사이에 공유하는 것은 SPY 달력뿐이다. 그래서 세분 자산을 넣거나 빼도 앵커 수익률은 바이트 단위로 같다(테스트로 확인).

## 교재와 다른 점

- 교재는 월말 종가를 단순히 쓴다. 여기서는 SPY 달력의 월말과 자산의 마지막 거래일이 다를 수 있어 위 규칙으로 정했다.
- 월간 수익률을 연율화하지 않는다. 산술·기하 평균 선택은 M1-2(분석 층)에서 정한다.
