# 대용 펀드 이력 (`proxy_history`)

- 분류: 데이터 품질 · 투자운용결과분석
- 상태: implemented
- 구현: `src/asset_frame/returns/proxy.py`(순수 함수), `proxy_jobs.py`, `proxies.py`, `config/proxies.toml`
- 데이터: Tiingo 일간 조정종가(뮤추얼펀드), 가격 기준은 [ADR-0002](../adr/0002-tiingo-eod-price-basis.md)와 같다
- 실행: `asset-frame ingest-proxies` → `asset-frame build-returns`(겹침 검사와 대용 월 저장)
- 테스트: `tests/test_proxy.py`, `tests/test_proxies_config.py`
- 계산 버전: `proxy_v1`

## 정의

- **대용 월:** 대상 ETF의 첫 수익률 달 **이전**의 대용 펀드 월수익률. 기존 `monthly_return`과 분리된 `proxy_return`에 저장하고 `proxy:<펀드>:<가격 버전>`으로 출처를 남긴다.
- **겹침 검사:** 대상과 대용이 모두 있는 달의 월수익률 상관, 연 추적 차이 = mean(대용−대상)×12, 월 평균 절대 차이.
- **사용 기준(고정):** 겹침 36개월 이상이고 상관이 등급 기준 이상. `index` 0.97, `close` 0.90, `rough` 제한 없음(사용자가 거친 대용임을 알고 고른 금광주 펀드).
- **일간 지수 연결:** 하락장 계산용 SPY 일간 총수익 지수는 대용 지수를 대상 첫날 수준에 맞춰 곱하고 이어 붙인다.

## 한계

- 대용 펀드의 보수·구성·만기가 ETF와 달라 추적 오차가 있다. 금광주 펀드는 금 가격이 아니라 금광 주식이라 금과 다르게 움직인다.
- 과거 시장 구조(금리 수준, 거래비용)가 지금과 달라 긴 기간의 결과는 참고용이다.
- 상관이 기준에 못 미친 대용은 쓰지 않고 이유를 기록한다.
