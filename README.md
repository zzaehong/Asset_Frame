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

프로젝트의 요구사항과 설계는 [PRD](PRD.md), [프로젝트 개요](Project_Overview.md)에서 확인할 수 있습니다.

## 빠른 시작

권장 환경은 WSL2 Ubuntu 24.04, Python 3.13, `uv`입니다. 코드는 Python 3.12와 3.13에서 동작하도록 설정되어 있습니다.

```bash
cp .env.example .env
uv sync --dev --frozen
```

PostgreSQL에 대상 자산과 CIK 식별자를 등록한 뒤 SEC submissions를 수집합니다.

```bash
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

PostgreSQL에 대상 자산과 OpenDART 고유번호 식별자를 등록한 뒤 기간별 공시목록을 수집합니다.

```bash
uv run asset-frame collect-opendart \
  --corp-code 00126380 \
  --asset-id <registered-asset-uuid> \
  --start-date 2026-01-01 \
  --end-date 2026-08-21
```

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

- Tiingo·ECOS·FRED connector는 아직 구현하지 않았습니다.
- KRX 가격은 수정주가가 아닌 거래소 원가격으로 저장합니다.
- 현재 구현된 connector와 CLI는 SEC EDGAR submissions, KRX 종목·가격 및 OpenDART 공시목록 수집 경로입니다.
- FastAPI와 위험 계산 엔진은 아직 구현하지 않았습니다.
- PostgreSQL adapter는 공급원, raw snapshot, 자산 식별자, SEC 공시, KRX 가격과 격리 기록을 연결합니다.
- 기본적·기술적·ETF·AI 문서 분석의 세부 기준은 투자자산운용사 자격 체계 매핑 후 확정합니다.
- 이 프로젝트는 투자자문, 수익 보장, 자동매매 도구가 아닙니다.

## 핵심 규칙

1. 공식 API 또는 제공자가 명시적으로 배포한 파일만 자동 수집합니다.
2. 웹 크롤링과 비공식 데이터 라이브러리를 구현하거나 의존하지 않습니다.
3. 숫자는 결정론적 코드가 계산하고, AI는 허용된 문서의 의미 구조화만 담당합니다.
4. 데이터 충돌은 평균하지 않고 격리합니다.
5. 모든 결과에는 기준시각, 입력 계보, 계산 버전, 한계가 따라야 합니다.
6. 최종 판단은 사용자에게 남겨둡니다.
