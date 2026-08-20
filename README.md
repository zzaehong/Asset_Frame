# Asset_Frame

수익을 예측하거나 매수·매도 점수를 만드는 대신, 공식 원천의 근거와 재현 가능한 계산으로 자산의 여러 관점과 위험을 보여주는 개인용 투자 의사결정 지원 도구입니다.

현재 버전은 `v0.1 Data & Risk Foundation`입니다. 다음 수직 슬라이스가 실행됩니다.

- 허용된 공식 API·공식 배포 파일만 등록하는 Source Registry
- 비공식 라이브러리와 웹 크롤링을 거부하는 소스 정책
- 원본 JSON의 불변 스냅샷과 SHA-256 계보 기록
- 일별 종가 기반 수익률·변동성·하방편차·최대낙폭·회복기간·Historical VaR 계산
- 사용자가 정한 위험 한도만 검사하는 정책 게이트
- 공급원 충돌 시 값을 평균하지 않고 `quarantined` 처리
- 매수/매도 의견 없이 위험·불확실성·데이터 상태를 반환하는 API와 CLI

프로젝트의 요구사항과 설계는 [PRD](docs/PRD.md), [프로젝트 개요](docs/PROJECT_OVERVIEW.md)에서 확인할 수 있습니다.

## 빠른 시작

권장 환경은 WSL2 Ubuntu 24.04, Python 3.13, `uv`입니다. 코드는 Python 3.12와 3.13에서 동작하도록 설정되어 있습니다.

```bash
cp .env.example .env
uv sync --dev
uv run investment-decision sources
uv run investment-decision risk --input examples/risk-analysis-input.json
uv run uvicorn investment_decision.api.app:app --reload
```

API 문서는 실행 후 `http://127.0.0.1:8000/docs`에서 확인합니다.

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Docker가 준비된 환경에서는 다음 명령으로 API와 PostgreSQL 스키마를 함께 실행할 수 있습니다.

```bash
docker compose up --build
```

## 현재 제한

- KRX·OpenDART·Tiingo 등 API 키가 필요한 실제 수집기는 순차 연결 예정입니다.
- v0.1에서 동작하는 네트워크 커넥터는 키가 필요 없는 SEC EDGAR submissions API입니다.
- PostgreSQL에는 핵심 데이터 계보 스키마만 먼저 정의했으며 애플리케이션 저장소 연결은 다음 단계입니다.
- 기본적·기술적·ETF·AI 문서 분석의 세부 기준은 투자자산운용사 자격 체계 매핑 후 확정합니다.
- 이 프로젝트는 투자자문, 수익 보장, 자동매매 도구가 아닙니다.

## 핵심 규칙

1. 공식 API 또는 제공자가 명시적으로 배포한 파일만 자동 수집합니다.
2. 웹 크롤링과 비공식 데이터 라이브러리를 구현하거나 의존하지 않습니다.
3. 숫자는 결정론적 코드가 계산하고, AI는 허용된 문서의 의미 구조화만 담당합니다.
4. 데이터 충돌은 평균하지 않고 격리합니다.
5. 모든 결과에는 기준시각, 입력 계보, 계산 버전, 한계가 따라야 합니다.
6. 최종 판단은 사용자에게 남겨둡니다.

