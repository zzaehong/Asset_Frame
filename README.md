# Asset_Frame

1명(저장소 소유자)이 쓰는 개인용 투자 도구입니다. 제품 목표와 설계는 **재정의 중**이며,
지금은 공식 원천의 ETF·주식 가격을 수집해 저장하는 데이터 층만 있습니다. 상태와 데이터 원칙은
[PRD](PRD.md)에 있습니다.

## 구현됨

지금 구현된 것은 **데이터 층**뿐입니다. 아래 항목은 모두 옆에 적은 테스트로 확인됩니다.

| 기능 | 확인 테스트 |
|---|---|
| 공식 원천만 허용하는 Source Registry(Tiingo·KRX 사용 가능, FRED·ECOS 계획) | `tests/test_source_registry.py` |
| `asset-frame sources`: 등록된 공급원 4개 출력 | `tests/test_cli.py` |
| `ingest-tiingo`, `ingest-krx`: API 키가 없으면 실행 거부 | `tests/test_cli.py` |
| Tiingo 미국 ETF·주식 메타데이터, EOD raw OHLCV + CRSP 조정종가, 배당·분할 수집 | `tests/test_tiingo_connector.py` |
| KRX ETF·주식 일별 가격, 종목 기본정보(ticker·ISIN) 수집 | `tests/test_krx_connector.py` |
| 원본 bytes의 content-addressed 불변 저장, SHA-256, API 키 마스킹 | `tests/test_raw_store.py` |
| HTTP 오류 응답 보존, 재시도·호출 간격 제어 transport | `tests/test_transport.py` |
| 가격 품질 검사와 충돌값 격리(평균하지 않음) | `tests/test_price_quality.py` |
| SQLite 저장: 저장→조회 왕복, 같은 날짜 재수집 시 새 버전 추가, 격리 가격 별도 저장 | `tests/test_sqlite_repository.py` |
| 직접 의존성의 공식 문서 registry 등록 | `tests/test_dependency_registry.py` |

## 빠른 시작

Python 3.12 또는 3.13과 `uv`가 필요합니다. 런타임 의존성은 없습니다(표준 라이브러리만 사용).

```bash
cp .env.example .env
uv sync --dev --frozen
uv run asset-frame sources
```

| 환경변수 | 용도 | 기본값 |
|---|---|---|
| `DATABASE_PATH` | SQLite 파일 경로 | `var/asset_frame.sqlite3` |
| `RAW_STORE_PATH` | 원본 응답 저장 경로 | `var/raw` |
| `TIINGO_API_KEY` | `ingest-tiingo` | 없음(필수) |
| `KRX_API_KEY` | `ingest-krx` | 없음(필수) |
| `FRED_API_KEY`, `ECOS_API_KEY` | 현재 사용하는 코드 없음 | 사용 안 함 |

환경변수는 셸에서 주입합니다. CLI는 `.env`를 자동으로 읽지 않습니다.

```bash
set -a; . ./.env; set +a

# 미국 ETF EOD. 자산 유형은 추측하지 않고 지정한다.
uv run asset-frame ingest-tiingo --ticker SPY --asset-type etf \
  --start-date 2021-01-01 --end-date 2026-11-16

# 한국 ETF 일별 가격(시장 전체의 기준일 snapshot)
uv run asset-frame ingest-krx --dataset etf_prices --date 2026-11-16
```

`ingest-krx --dataset`은 `kospi_prices`, `kosdaq_prices`, `etf_prices`, `kospi_assets`,
`kosdaq_assets` 중 하나입니다.

## 데이터 규칙

- Tiingo OHLCV는 raw 값, `adjusted_close`는 CRSP 방식 배당·분할 조정 종가입니다
  ([ADR-0002](docs/adr/0002-tiingo-eod-price-basis.md)). KRX 가격은 수정주가가 아닌 거래소
  원가격입니다.
- `price_observations`는 덮어쓰지 않습니다. 같은 (자산, 거래일, 공급원)을 다시 수집하면
  `fetched_at`과 `raw_snapshot_id`가 다른 새 행이 추가됩니다.
- 검증에 실패한 가격은 `price_quarantine`에 이유와 함께 저장되고 가격 테이블에 들어가지
  않습니다.
- 스키마는 코드 안의 `CREATE TABLE IF NOT EXISTS`로 만듭니다(`src/asset_frame/storage/sqlite.py`).

## 검증

```bash
uv run pytest            # 네트워크·API 키 없이 실행됨
uv run ruff check .
uv run ruff format --check .
```

## 제한

- 자동매매와 주문 기능은 없고 만들지 않습니다.
- 공식 API·공식 배포 파일만 수집합니다. 크롤링과 비공식 금융 라이브러리는 쓰지 않습니다.
- 가격을 읽는 분석 코드는 아직 없습니다. 지금은 수집과 저장만 합니다.
