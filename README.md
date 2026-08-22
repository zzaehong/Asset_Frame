# Asset_Frame

수익을 예측하거나 매수·매도 점수를 만드는 대신, 공식 원천의 근거와 재현 가능한 계산으로 자산의 여러 관점과 위험을 보여주는 개인용 투자 의사결정 지원 도구입니다.

현재는 `v0.1 Data & Risk Foundation`의 데이터 수집 기반을 구현하고 있습니다.

- 공식 원천만 허용하는 파일 기반 Source Registry
- 원본 bytes의 content-addressed 불변 저장과 수집별 metadata·SHA-256 계보
- PostgreSQL의 자산 식별자, 가격, 기업행동, 재무사실, 공시, ETF 보유, 거시 시계열 모델
- 가격 품질 검사와 공급원 충돌의 `quarantined` 판정
- SEC EDGAR submissions connector와 주입 가능한 HTTP·저장소 경계
- KRX KOSPI·KOSDAQ 기본정보와 KOSPI·KOSDAQ·ETF 일별 가격 수집 CLI
- OpenDART 기업별 공시목록 수집과 페이지별 원본 계보
- Tiingo 미국 주식·ETF 기본정보, EOD 원가격·조정종가와 기업행동 수집
- SEC ticker→CIK와 KRX ticker→OpenDART corp code의 공식 목록 기반 정확 일치 매핑
- 공급원·데이터 종류별 수집 실행 성공/실패/처리 건수와 stale 상태 조회
- PostgreSQL의 공급원·자산·수집 실행·raw snapshot을 보여주는 읽기 전용 FastAPI Data Console

프로젝트의 요구사항과 설계는 [PRD](PRD.md), [프로젝트 개요](Project_Overview.md)에서 확인할 수 있습니다.

## 빠른 시작

권장 환경은 WSL2 Ubuntu 24.04, Python 3.13, `uv`입니다. 코드는 Python 3.12와 3.13에서 동작하도록 설정되어 있습니다.

```bash
cp .env.example .env
uv sync --dev --frozen
```

Tiingo 등으로 등록한 미국 ticker를 SEC 공식 회사 목록의 CIK에 연결한 뒤 SEC
submissions를 수집합니다.

```bash
uv run asset-frame collect-sec-identifiers
uv run asset-frame collect-sec \
  --cik 320193 \
  --asset-id <registered-asset-uuid>
```

승인된 KRX API는 시장 전체의 기준일 snapshot으로 수집합니다.

```bash
uv run asset-frame collect-krx --dataset kospi_assets --date 2026-08-19
uv run asset-frame collect-krx --dataset kosdaq_assets --date 2026-08-19
uv run asset-frame collect-krx --dataset kospi_prices --date 2026-08-19
uv run asset-frame collect-krx --dataset kosdaq_prices --date 2026-08-19
uv run asset-frame collect-krx --dataset etf_prices --date 2026-08-19
```

KRX로 등록한 국내 ticker를 OpenDART 공식 고유번호 파일의 corp code에 연결한 뒤 기간별
공시목록을 수집합니다.

```bash
uv run asset-frame collect-opendart-identifiers
uv run asset-frame collect-opendart \
  --corp-code 00126380 \
  --asset-id <registered-asset-uuid> \
  --start-date 2026-01-01 \
  --end-date 2026-08-21
```

자산 유형을 명시하여 Tiingo 기본정보와 EOD 가격을 함께 수집합니다.

```bash
uv run asset-frame collect-tiingo \
  --ticker AAPL \
  --asset-type equity \
  --start-date 2021-01-01 \
  --end-date 2026-08-21
```

Tiingo metadata에는 자산 유형과 통화가 없으므로 `--asset-type`은 추측하지 않고 사용자가
`equity` 또는 `etf`로 지정합니다. 이 경로는 미국 자산만 대상으로 하며 통화는 USD로 저장합니다.
OHLCV는 raw 값, `adjusted_close`는 Tiingo의 CRSP 방식 배당·분할 조정 종가입니다.

수집 상태는 공급원과 데이터 종류별 마지막 성공시각을 기준으로 확인합니다. stale 임계값은
숨은 기본값을 사용하지 않고 호출자가 시간 단위로 지정합니다.

```bash
uv run asset-frame source-status \
  --source-id tiingo-eod \
  --data-kind price \
  --max-age-hours 48
```

`config/data-spike.toml`은 한국·미국 주식과 ETF 각 5개씩 총 20개 표본을 고정합니다. 이 목록은
투자 추천이 아니라 분할, 배당, 특수 ticker, 인버스, 채권·원자재 ETF 등 수집 경계 사례를
재현하기 위한 테스트 대상입니다. 다음 명령은 DB 등록과 필수 식별자 준비 상태를 나눠
보여줍니다. 미국 자산은 CIK, 국내 주식은 DART corp code를 요구하며 국내 ETF에는 적용되지
않는 DART corp code를 강제하지 않습니다.

```bash
uv run asset-frame data-spike-status
```

## 분석 유니버스와 저장량 관측

한국과 미국의 분석 대상을 같은 규칙으로 관리하기 위해 최근 60개 유효 거래일의
`close × volume` 중앙 거래대금을 사용합니다. 국가별 주식 500개와 ETF 최대 150개를
선정하며, Data Spike의 기존 20개 표본은 각 한도 안에서 항상 포함합니다. 이 순위는 데이터
수집 범위를 정하는 운영 규칙이며 투자 점수나 추천이 아닙니다.

`db/init/002_analysis_universe.sql`을 적용한 PostgreSQL에서 다음 명령을 실행합니다.

```bash
uv run asset-frame build-universe --country KR --as-of 2026-08-21
uv run asset-frame build-universe --country US --as-of 2026-08-21
```

raw store와 PostgreSQL의 저장량은 다음 명령으로 확인합니다. 기본 10GB는 초기 운영 경고
기준일 뿐 수집을 중단하는 hard limit가 아닙니다. 실제 데이터 가치와 로컬 여유 공간을 확인해
`config/analysis-universe.toml`에서 조정합니다.

```bash
uv run asset-frame data-budget-status
```

향후 뉴스 수집은 최근의 제목·요약·매체·시각·원문 URL 같은 API 메타데이터만 짧게
보존하고 기사 본문은 수집하지 않습니다. 공시는 정기 재무보고와 분석에 필요한 주요 사건
공시를 우선하며 모든 공시 유형의 본문을 무차별 저장하지 않습니다.

## 로컬 Data Console

`.env`의 `DATABASE_URL`을 주입한 뒤 다음 명령으로 읽기 전용 대시보드를 실행합니다.

```bash
set -a
. ./.env
set +a
uv run uvicorn asset_frame.web.app:app --host 127.0.0.1 --port 8000
```

브라우저에서 `http://127.0.0.1:8000`을 열면 다음 데이터를 확인할 수 있습니다.

- 활성 공급원과 공급원별 최근 실행 상태
- 자산 수, 가격·공시·raw snapshot·격리 이슈 건수
- ticker, ISIN, CIK, DART corp code, 거래소 식별자
- 전체·주식·ETF 유형별 자산 목록과 가격·공시 수집 기간
- 종목별 OHLCV·가격 기준 상세와 페이지 단위 공식 공시 원문 링크
- 최근 수집 실행의 성공·실패와 수신·수락·격리 건수
- raw snapshot의 수집시각, HTTP 상태, 크기, SHA-256, 저장 경로

JSON API와 schema는 `http://127.0.0.1:8000/docs`에서 확인할 수 있습니다. 현재 화면에는 인증이
없으므로 개인 PC의 loopback 주소인 `127.0.0.1`에만 바인딩합니다. 외부 네트워크에 공개하려면
인증, HTTPS, 접근 로그와 secret 검토가 먼저 필요합니다. Dashboard repository는 각 DB transaction을
`READ ONLY`로 설정하며 화면에서 수집이나 데이터 변경을 실행하지 않습니다.

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Docker가 준비된 환경에서는 다음 명령으로 PostgreSQL과 초기 스키마를 실행할 수 있습니다.

```bash
docker compose up -d --wait
```

PostgreSQL schema는 `db/init/001_core.sql`, 공급원 설정은 `config/sources.toml`에 있습니다.

## 현재 제한

- ECOS·FRED connector는 아직 구현하지 않았습니다.
- KRX 가격은 수정주가가 아닌 거래소 원가격으로 저장합니다.
- 현재 구현된 connector와 CLI는 SEC EDGAR submissions, KRX 종목·가격, OpenDART 공시목록 및 Tiingo 미국 EOD 수집 경로입니다.
- 규제기관 식별자 매핑은 ticker의 대소문자를 정규화한 정확 일치만 사용합니다. 서로 다른
  표기나 우선주 등 공식 목록에서 일치하지 않는 ticker는 추정하지 않고 누락으로 보고합니다.
- Data Spike manifest의 종목 선정은 초기 운영 표본이며, 상장폐지·저유동성 사례 포함 여부는
  실제 5년 수집을 시작하기 전에 별도로 확정해야 합니다.
- Tiingo 조정 OHLC·조정 거래량은 raw snapshot에만 보존하며 분석 기본 가격은 아직 정하지 않았습니다.
- FastAPI Data Console은 데이터 상태 조회만 지원하며 가격 차트·공시 본문·위험 계산은 아직
  구현하지 않았습니다.
- PostgreSQL adapter는 공급원, raw snapshot, 자산 식별자, 공시, KRX·Tiingo 가격,
  Tiingo 기업행동과 격리 기록을 연결합니다.
- 기본적·기술적·ETF·AI 문서 분석의 세부 기준은 투자자산운용사 자격 체계 매핑 후 확정합니다.
- 이 프로젝트는 투자자문, 수익 보장, 자동매매 도구가 아닙니다.

## 핵심 규칙

1. 공식 API 또는 제공자가 명시적으로 배포한 파일만 자동 수집합니다.
2. 웹 크롤링과 비공식 데이터 라이브러리를 구현하거나 의존하지 않습니다.
3. 숫자는 결정론적 코드가 계산하고, AI는 허용된 문서의 의미 구조화만 담당합니다.
4. 데이터 충돌은 평균하지 않고 격리합니다.
5. 모든 결과에는 기준시각, 입력 계보, 계산 버전, 한계가 따라야 합니다.
6. 최종 판단은 사용자에게 남겨둡니다.
