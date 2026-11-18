# Asset_Frame

1명(저장소 소유자)이 쓰는 자산배분 실험 도구입니다. 여러 자산군으로 만든 배분 전략을 같은 기준으로
비교합니다. 요구사항은 [PRD v0.4](docs/PRD.md)에 있습니다. 현재 마일스톤은 M1(자산배분 실험실)이며,
구현된 것은 그 첫 단계인 데이터 층(M1-1)까지입니다.

## 구현됨

지금 구현된 것은 **데이터 층**뿐입니다. 분석·전략·리포트는 아직 없습니다. 아래 항목은 모두 옆에 적은 테스트로 확인됩니다.

| 기능 | 확인 테스트 |
|---|---|
| 공식 원천만 허용하는 Source Registry(Tiingo·KRX·FRED 사용 가능, ECOS 계획) | `tests/test_source_registry.py` |
| `asset-frame sources`: 등록된 공급원 4개 출력 | `tests/test_cli.py` |
| `ingest-tiingo`, `ingest-krx`, `ingest-universe`, `ingest-fred`: API 키가 없으면 실행 거부 | `tests/test_cli.py` |
| Tiingo 미국 ETF·주식 메타데이터, EOD raw OHLCV + CRSP 조정종가, 배당·분할 수집 | `tests/test_tiingo_connector.py` |
| KRX ETF·주식 일별 가격, 종목 기본정보(ticker·ISIN) 수집 | `tests/test_krx_connector.py` |
| 원본 bytes의 content-addressed 불변 저장, SHA-256, API 키 마스킹 | `tests/test_raw_store.py` |
| HTTP 오류 응답 보존, 재시도·호출 간격 제어 transport | `tests/test_transport.py` |
| 가격 품질 검사와 충돌값 격리(평균하지 않음) | `tests/test_price_quality.py` |
| SQLite 저장: 저장→조회 왕복, 같은 날짜 재수집 시 새 버전 추가, 격리 가격 별도 저장 | `tests/test_sqlite_repository.py` |
| 유니버스 v3 설정(31개): 티커 중복 금지, 세분 자산은 같은 자산군의 앵커를 세분, 자산군당 앵커 1개(GICS 섹터 9개) | `tests/test_universe.py` |
| `ingest-universe`: 10년 구간을 겹쳐 전체 이력 수집, 실패한 티커부터 재시작 | `tests/test_universe.py` |
| `universe verify`: 상장일 비교(±31일 `ok`, 초과 `mismatch`), `ok`만 설정 파일에 기록 | `tests/test_universe.py` |
| FRED `DTB3` 수집: 결측값 "."은 NULL, 부분·비정상 응답 거부, 원본 SHA-256 보존 | `tests/test_fred_connector.py` |
| 총수익 지수와 월간 총수익률(손 계산 3개월 표본과 일치), 서로 다른 snapshot 연결 | `tests/test_returns.py` |
| 현금 대용: BIL 상장 전은 DTB3, 이후는 BIL만, 대용 월 표시 | `tests/test_returns.py` |
| 앵커 보존: 세분 자산을 넣거나 빼도 앵커 수익률이 바이트 단위로 같음 | `tests/test_returns.py` |
| `eligible_assets`: 판정월까지 월간 수익률 13개 이상 | `tests/test_returns.py` |
| 일간 수익률 ±25% 초과를 이상치로 표시(계산에서 빼지 않음) | `tests/test_returns.py` |
| 개념 레지스트리: 구현된 개념은 모듈·테스트·카드가 있음 | `tests/test_concept_registry.py` |
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
| `TIINGO_API_KEY` | `ingest-tiingo`, `ingest-universe` | 없음(필수) |
| `KRX_API_KEY` | `ingest-krx` | 없음(필수) |
| `FRED_API_KEY` | `ingest-fred` | 없음(필수) |
| `ECOS_API_KEY` | 현재 사용하는 코드 없음 | 사용 안 함 |

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

### 유니버스 월간 수익률 (M1-1)

```bash
uv run asset-frame ingest-universe          # 31개 티커 전체 이력. Starter 요금제 기준 약 3.6시간
uv run asset-frame universe verify          # 상장일 검증. ok만 config/universe.toml에 기록
uv run asset-frame ingest-fred --series DTB3
uv run asset-frame build-returns            # monthly_return, return_anomaly 테이블에 새 빌드 추가
uv run asset-frame universe status          # 콘솔 표 + var/reports/universe_status.csv
```

- `ingest-universe`는 Tiingo Starter 한도(시간당 50회, `config/sources.toml`)에 맞춰 요청 사이를
  75초 띄웁니다. 요금제가 다르면 `--min-interval-seconds`로 바꿉니다. 중간에 실패하면 같은 명령을
  다시 실행합니다. 같은 `--end-date`로 끝난 티커는 건너뜁니다.
- `universe verify`의 `mismatch`는 설정 파일을 바꾸지 않습니다. 사람이 확인합니다.
- 계산 규칙(월말 기준, 대용 근사, 버전)은 [개념 카드](docs/concepts/)에 있습니다.

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
- 수익률 시계열까지만 있습니다. 상관·위험기여도·전략·리포트는 M1-2, M1-3에서 만듭니다.
