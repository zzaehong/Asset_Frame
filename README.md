# Asset_Frame

1명(저장소 소유자)이 쓰는 자산배분 실험 도구입니다. 여러 자산군으로 만든 배분 전략을 같은 기준으로
비교합니다. 요구사항은 [PRD v0.4](PRD.md), 진행 순서는 [로드맵](docs/roadmap.md)에 있습니다. 현재 마일스톤은 M1(자산배분 실험실)이며,
M1(자산배분 실험실)이 구현되어 있습니다: 데이터 층, 분석 층, 백테스트 층, 월간 리포트.

## 구현됨

지금 구현된 것은 데이터 층, 위험 분석 층, 전략 8개 백테스트, 오프라인 대화형 대시보드입니다(M1 전체). 아래 항목은 모두 옆에 적은 테스트로 확인됩니다.

| 기능 | 확인 테스트 |
|---|---|
| Source Registry(공식 원천만 허용, Tiingo·KRX·FRED 사용 가능, ECOS 계획) | `tests/test_source_registry.py` |
| CLI: `sources` 출력, 수집 명령은 API 키가 없으면 실행 거부 | `tests/test_cli.py` |
| Tiingo 메타데이터·EOD(raw OHLCV, CRSP 조정종가)·배당·분할 수집 | `tests/test_tiingo_connector.py` |
| KRX ETF·주식 일별 가격, 종목 기본정보 수집 | `tests/test_krx_connector.py` |
| FRED `DTB3` 수집: 결측 "."은 NULL, 부분·비정상 응답 거부 | `tests/test_fred_connector.py` |
| 원본 bytes 불변 저장, SHA-256, API 키 마스킹 | `tests/test_raw_store.py` |
| HTTP 오류 응답 보존, 재시도·호출 간격 제어 | `tests/test_transport.py` |
| 가격 품질 검사와 충돌값 격리(평균하지 않음) | `tests/test_price_quality.py` |
| SQLite 저장: 왕복 조회, 재수집 시 새 버전 추가, 격리 가격 별도 저장 | `tests/test_sqlite_repository.py` |
| 유니버스 v3 설정 31개: 티커 중복 금지, 자산군당 앵커 1개, 세분은 같은 자산군 앵커를 세분 | `tests/test_universe.py` |
| `ingest-universe`: 10년 구간 겹쳐 수집, 실패 티커부터 재시작, 저장된 티커는 새 날짜만 수집(전체 재수집과 같은 지수). `universe verify`: ±31일 `ok`만 설정에 기록 | `tests/test_universe.py` |
| 총수익 지수·월간 수익률(손 계산 표본), snapshot 연결, 현금 대용, 앵커 보존, `eligible_assets` 13개월, 일간 ±25% 이상치 표시 | `tests/test_returns.py` |
| 위험 지표(연율 변동성, 최대낙폭, 95% 역사적 VaR), 36개월 상관행렬, 위험기여도(손 계산 표본·분산 일치 검증) | `tests/test_analytics.py` |
| 전략 8개 설정 검증(벤치마크 2, 고정 비중 2, 동일가중, 추정 비중 3)과 `min_variance` 상한 민감도 변형 2개(20·40%), 월간·분기·밴드 리밸런싱, 편입 자격 13개월·비중 재배분(coverage), 성과 지표(CAGR·샤프·소르티노·칼마·정보비율) 손 계산 검증, 36개월 창 추정 전략 | `tests/test_backtest.py` |
| 추정 비중: 역변동성, 위험균등(위험기여도 동일 검증), 상한 있는 최소분산(닫힌 해·격자 탐색 비교) | `tests/test_allocation.py` |
| 위기 구간(2008·2020·2022) 누적 수익률·최대낙폭과 부분 구성 표시, 현금도 일반 자산으로 담김(평균 비중·대용 구간), 오프라인 대시보드 한 파일(외부 로드 없음, 데이터가 스크립트를 닫지 못함) | `tests/test_dashboard.py` |
| 대시보드 안의 포트폴리오 실험실·롤링 상관 엔진이 파이썬 엔진과 같은 값을 냄(노드가 없으면 건너뜀) | `tests/test_dashboard_engine.py` |
| FRED 거시 시리즈(INDPRO·UNRATE·CPIAUCSL·CFNAIMA3)를 최초 발표값과 발표일로 저장(`output_type=4`), USREC은 현재 값, 승인 안 된 시리즈 거부 | `tests/test_fred_connector.py` |
| `regime`: Sahm 지표·INDPRO/CFNAI 침체 규칙·L3 4분면·주식채권 상관 국면, 발표일 이후 값만 쓰는 월말 replay, NBER 대비 채점(손 계산 표본) | `tests/test_regime_rules.py`, `tests/test_regime_replay.py` |
| 해시 체인 원장: 연속 `seq`·이전 해시, 수정·삭제 거부(트리거), 변조·누락 탐지, 같은 키 중복 방지, 국면 월 기록의 live·replay 구분 | `tests/test_ledger.py` |
| 예측·채점: 모멘텀(12-1)·무작위·사용자 순위와 상관 부호 확률을 원장에 기록(월당 모델별 1건), 3개월 뒤 순위 IC·상·하위 스프레드·Brier 채점, MDE 표시, 잘못된 입력 거부 | `tests/test_prediction.py` |
| 대용 펀드 이력: 상장 전 구간을 같은 시장 펀드로 이어 붙임(대상 첫 달 이전만, 항상 대용 표시), 겹침 36개월·등급별 상관 기준 미달이면 사용 안 함, 일간 지수 연결, 기존 월간 수익률과 분리 저장, 설정 검증 | `tests/test_proxy.py`, `tests/test_proxy_jobs.py`, `tests/test_proxies_config.py` |
| 자산별 배당수익률: 최근 12개월 분배금÷기준일 종가, 분할 후 분배금 보정, 중복 배당락일 1회 계산, 이력 12개월 미만이면 표시 안 함, 실험실 자산 행에 표시 | `tests/test_dividend.py`, `tests/test_dashboard.py` |
| 앱의 개별주 선택 저장·수집: 티커 검증(형식·중복·50종목·삽입 시도)과 잘못된 입력 시 파일 불변, 파일 텍스트가 JS와 같음, CLI 자식 프로세스 실행·로그·종료 코드, 실행 중 잠금 시 시작 거부, 이 앱이 시작한 수집만 중단 | `app/Tests/AssetFrameCoreTests/StockSelectionTests.swift`, `app/Tests/AssetFrameCoreTests/CollectRunnerTests.swift`, `tests/test_dashboard_engine.py` |
| 자동 갱신: 단계가 실패해도 나머지 계속·요약·알림, 수집 실패 시 원장 기록 건너뜀, 단계 선택·알 수 없는 이름 거부, 동시 실행 잠금(죽은 pid 교체), `.env`는 비어 있는 변수만 채우고 값을 반환하지 않음, launchd plist(시각 검증·비밀 없음)·등록·해제·상태 | `tests/test_update.py`, `tests/test_schedule.py` |
| API 키 조회: 환경변수 우선·비어 있으면 키체인, 값이 명령줄·오류 메시지에 나오지 않음, macOS 외에서는 키체인을 건드리지 않음, 앱의 키체인 저장·교체·삭제·공백 제거(Swift) | `tests/test_secrets.py`, `app/Tests/AssetFrameCoreTests/KeychainTests.swift` |
| 개별주 관찰 목록: stocks.toml 검증(없으면 선택 없음, 형식·중복·ETF 겹침·50종목 한도), 선택 종목만 주식으로 수집하고 재실행 시 이어받기, 후보·수집 상태 요약, 대시보드가 만드는 stocks.toml 텍스트가 파이썬 로더와 일치(선택 없으면 수집 명령이 요청 전에 중단) | `tests/test_stocks.py`, `tests/test_stock_candidates.py`, `tests/test_dashboard_engine.py`, `tests/test_cli.py` |
| 차트 지표(SMA·EMA·RSI·MACD·스토캐스틱·거래량 비율)와 기간별 수익률: 손 계산 fixture, 이력 부족은 None, 고가·저가 보정, 최근 일수 자르기 | `tests/test_indicators.py`, `tests/test_chart_jobs.py` |
| 차트 규칙 신호(4개 투표 합계, 임계 ±2, 스토캐스틱 교차 5거래일 유지, 히스토그램 잡음 처리), 월말 신호별 1·3·6개월 과거 성과 | `tests/test_chart_signal.py`, `tests/test_chart_jobs.py` |
| 거시 판단(국면별 강했던·약했던 자산, 독립 표본 5 미만 제외, 자격 4개 미만이면 제안 안 함, 곡선·정책금리·달러 경고와 자료 없음) | `tests/test_regime_actions.py`, `tests/test_dashboard.py` |
| 신호 원장 기록(월별 1회)·채점(차트 3개월·거시 6개월, 한 번만)·집계 | `tests/test_signal_log.py` |
| 긴 기간 국면: 1962년부터 월말 replay(INDPRO/CPI 기준 4분면 `regime_ip_v1` 포함, 달러지수 연결), 월 날짜 달라도 같은 달로 맞춤 | `tests/test_regime_rules.py`, `tests/test_regime_long.py`, `tests/test_regime_performance.py`, `tests/test_regime_market.py` |
| 주식시장 하락장(SPY 총수익 −20% 진입·저점 +20% 종료, `equity_bear_v1`)과 타임라인 표시 | `tests/test_regime_equity.py`, `tests/test_dashboard.py` |
| 금리 곡선(10년−3개월·10년−2년), 정책금리, 달러지수 수집과 월말 맥락(`macro_market_v1`), 타임라인 표시 | `tests/test_regime_market.py`, `tests/test_fred_connector.py` |
| 국면별 과거 성과(월말 상황 라벨 뒤 1·3·6·12·24·36개월 누적 수익률의 평균·중앙값·범위·오른 비율·독립 표본 수, `regime_performance_v2`), 대시보드 payload의 `regime` 항목 | `tests/test_regime_performance.py`, `tests/test_dashboard.py` |
| Mac 앱(`app/`, 읽기 전용): 파이썬이 쓴 해시 체인 검증과 변조·삭제 탐지, 원장 항목 해석, 성적표 평균, 데이터 상태 쿼리, 읽기 전용 연결 | `app/Tests/AssetFrameCoreTests/LedgerTests.swift` |
| `backup`: SQLite 일관 복사(최근 4개 유지)와 raw 파일 추가 복사(기존 파일은 덮어쓰지 않음) | `tests/test_backup.py` |
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
| `BACKUP_PATH` | `backup` 명령의 복사 위치(저장소 밖) | `~/Backups/Asset_Frame` |
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
uv run asset-frame ingest-universe          # 처음엔 전체 이력(Starter 기준 약 3.6시간), 이후엔 새 날짜만
uv run asset-frame ingest-universe --full   # 전체 이력을 다시 받음
uv run asset-frame universe verify          # 상장일 검증. ok만 config/universe.toml에 기록
uv run asset-frame ingest-fred --series DTB3
uv run asset-frame ingest-proxies           # config/proxies.toml의 대용 펀드 이력(약 1시간, 75초 간격)
uv run asset-frame ingest-stocks            # config/stocks.toml에 고른 개별주만 수집(대시보드 "개별주 선택" 탭에서 만든 파일, 최대 50종목, 약 2시간)
uv run asset-frame update                    # 모든 갱신을 한 번에(FRED·ETF·개별주 가격 → 수익률 → 월말 국면 기록 → 대시보드 → 백업, --steps·--dry-run)
uv run asset-frame schedule install          # 매일 07:30 자동 갱신 등록(macOS launchd, --hour·--minute), status·uninstall도 있음
uv run asset-frame build-returns            # monthly_return, return_anomaly에 새 빌드 추가 + 대용 월·겹침 검사 저장
uv run asset-frame universe status          # 콘솔 표 + var/reports/universe_status.csv
uv run asset-frame universe analyze         # var/reports/analysis_risk.csv, analysis_correlation.csv
uv run asset-frame dashboard                # var/reports/dashboard.html: 오프라인 대화형 대시보드(서버 불필요)
uv run asset-frame regime                   # var/reports/regime_replay.csv: 국면 규칙 replay와 NBER 채점
uv run asset-frame ledger record-regime     # 최근 월의 국면 판독을 원장에 live로 추가(--replay: 전체 월을 replay로)
uv run asset-frame ledger predict-models    # 모멘텀·무작위 모델의 최근 월 예측을 원장에 추가
uv run asset-frame ledger predict --ranking SPY,GLD,... --positive-prob 0.6 --note "근거"  # 내 예측
uv run asset-frame ledger score             # 3개월이 지난 예측 채점
uv run asset-frame ledger scoreboard        # 모델별 성적표(표본 수·MDE 포함)
uv run asset-frame ledger record-signals     # 최근 월말의 차트 신호·거시 제안을 원장에 추가(영구 기록)
uv run asset-frame ledger score-signals      # 차트 3개월·거시 6개월이 지난 신호 채점
uv run asset-frame ledger signal-scoreboard  # 신호 적중률·스프레드(채점한 월 수 포함)
uv run asset-frame ledger verify            # 해시 체인 검증, head 해시 출력
uv run asset-frame backup                   # var의 DB·raw를 BACKUP_PATH로 복사(수집 후 실행)
uv run asset-frame backtest                 # var/reports/backtest_performance.csv, backtest_monthly.csv
uv run asset-frame backtest --window-months 24   # 위험 추정 창 민감도(파일명에 _w24)
```

- `ingest-universe`는 Tiingo Starter 한도(시간당 50회, `config/sources.toml`)에 맞춰 요청 사이를
  75초 띄웁니다. 요금제가 다르면 `--min-interval-seconds`로 바꿉니다. 중간에 실패하면 같은 명령을
  다시 실행합니다. 같은 `--end-date`로 끝난 티커는 건너뜁니다.
  가격이 이미 저장된 티커는 마지막 저장일 10일 전부터만 받습니다(티커당 요청 2회). Tiingo는 수집할
  때마다 `adjClose` 전체를 다시 계산하므로, 겹치는 날짜가 있어야 새 구간이 기존 지수에 이어집니다.
- `universe verify`의 `mismatch`는 설정 파일을 바꾸지 않습니다. 사람이 확인합니다.
- 계산 규칙(월말 기준, 대용 근사, 버전)은 [개념 레지스트리](docs/concepts/README.md)에 있습니다.

### 자동 갱신

`asset-frame schedule install`이 매일 07:30에 `asset-frame update`를 실행하도록 launchd에 등록합니다([ADR-0012](docs/adr/0012-scheduled-update.md)). 로그는 `var/logs/update.log`, 상태는 `schedule status`로 봅니다. 월말 국면 기록은 수집이 모두 성공했을 때만 원장에 추가되고, 예측·신호 기록과 채점은 자동화하지 않습니다. Mac이 자고 있으면 깨어난 뒤 한 번 실행하고, 꺼져 있으면 건너뜁니다. 스케줄은 저장소의 현재 브랜치 코드를 그대로 실행하니 브랜치를 바꿀 때 유의하세요. 키는 `.env`(스케줄 실행이 읽음) 또는 키체인에서 가져옵니다.

### Mac 앱

```bash
app/build_app.sh --install   # app/build/AssetFrame.app을 만들고 ~/Applications에도 복사(이 Mac 전용 임시 서명)
```

`~/Applications/AssetFrame.app`은 Launchpad·Spotlight·Finder에서 일반 앱처럼 열립니다. 빌드할 때 이 저장소 경로를 앱에 넣어 두므로 폴더를 고르거나 환경변수를 줄 필요가 없습니다. 우선순위는 `ASSET_FRAME_HOME` → "폴더 선택…"으로 고른 폴더 → 빌드 때 넣은 경로입니다. 저장소를 옮겼다면 다시 빌드하세요. API 키는 앱의 "API 키" 화면에서 macOS 키체인에 저장할 수 있습니다(값은 다시 표시하지 않음, [ADR-0011](docs/adr/0011-api-keys-in-macos-keychain.md)). CLI는 환경변수가 있으면 그것을, 없으면 키체인을 읽습니다. 터미널이 키체인 키를 처음 읽을 때 접근 허용 창이 뜨면 "항상 허용"을 누르세요. 수집은 파이썬 CLI가 하고, 앱은 "개별주 선택" 화면에서 선택을 `config/stocks.toml`에 저장하고 "저장하고 지금 수집"으로 `asset-frame update --steps stocks,dashboard`를 시작할 수 있습니다([ADR-0013](docs/adr/0013-app-saves-stock-selection-and-starts-collection.md), 이미 갱신이 돌고 있으면 시작하지 않음). 앱은 DB를 읽기 전용으로 열고, 데이터는 위 CLI로 갱신한 뒤 ⌘R로 다시 읽습니다. 설계는 [ADR-0008](docs/adr/0008-mac-app-read-only.md)입니다.

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
cd app && swift test   # Mac 앱 코어(macOS, Xcode 필요)
```

## 제한

- 자동매매와 주문 기능은 없고 만들지 않습니다.
- 공식 API·공식 배포 파일만 수집합니다. 크롤링과 비공식 금융 라이브러리는 쓰지 않습니다.
- 백테스트는 거래비용·세금을 반영하지 않습니다. 국면·원장·갈아타기는 M2 이후입니다.
