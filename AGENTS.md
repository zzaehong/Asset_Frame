# AGENTS.md

## 1. Project Overview

이 프로젝트는 한국·미국 주식과 ETF를 대상으로 하는 개인용 투자 의사결정 지원 도구다.

목표는 수익을 예측하거나 매수·매도 결론을 대신 내리는 것이 아니다. 공식 원천에서 확인할 수 있는 사실과 재현 가능한 계산을 바탕으로 자산을 여러 관점에서 보여주고, 사용자가 위험·불확실성·판단 변경 조건을 인식하고 관리하도록 돕는다.

현재 구현 기준선은 `v0.1 Data & Risk Foundation`이다.

---

## 2. Documentation Hierarchy

변경 전 다음 문서를 순서대로 확인한다.

1. `docs/PRD.md` — 제품 요구사항, 범위, 수용 기준
2. `docs/PROJECT_OVERVIEW.md` — 현재 구조, 구현 상태, 다음 개발 순서
3. `docs/adr/` — 이미 채택된 중요 기술·제품 결정과 근거
4. `README.md` — 설치, 실행, 사용 방법
5. `AGENTS.md` — AI agent의 개발 및 작업 규칙

`docs/dependency-sources.toml`은 Python dependency와 주요 개발 도구의 공식 문서, 변경 이력, 공식 소스 저장소를 관리하는 기계 판독 가능한 registry다.

`docs/PRD.md`는 제품 요구사항의 Source of Truth다. 중요한 설계 결정은 `docs/adr/`에 기록한다.

문서, 현재 구현, 사용자의 최신 지시 사이에 충돌이 있으면 임의로 하나를 선택하지 않는다. 충돌 위치와 영향을 설명하고 사용자에게 확인한다. 동일한 내용을 여러 문서에 중복 기록하지 않는다.

---

## 3. Non-negotiable Product Principles

다음 원칙은 별도의 제품 결정 없이 변경하지 않는다.

- 이 제품은 투자 추천기가 아니라 위험 인식과 판단 기록을 돕는 도구다.
- 매수·매도·보유 점수, 목표주가, 수익 보장 표현을 만들지 않는다.
- 자동 수집은 공식 API, 규제기관 벌크 데이터, 제공자가 명시적으로 배포한 공식 파일로 제한한다.
- HTML 크롤링, 웹 스크래핑, 브라우저 자동화 수집, 비공식·역공학 API를 사용하지 않는다.
- `yfinance`, `pykrx`, `FinanceDataReader` 등 비공식 금융 데이터 라이브러리를 사용하지 않는다.
- 검증 URL은 사용자 확인용 링크이며 해당 페이지를 자동 수집하지 않는다.
- 사용자가 보는 사실과 계산은 원천, 수집시각, 원본 해시, 계산 버전으로 추적 가능해야 한다.
- 공급원 충돌값은 평균하지 않고 `quarantined`로 격리한다.
- 수치 계산은 결정론적 코드가 담당하고 AI는 허용된 문서의 의미 구조화만 담당한다.
- AI 결과는 원문 URL과 근거 구간이 없으면 확정 사실로 취급하지 않고 `unknown`을 사용한다.
- 사용자 투자정책에 대한 검사는 사용자가 명시한 한도만 사용한다. 숨은 임계치나 가중치를 추가하지 않는다.
- 분석 규칙을 추가할 때 투자자산운용사 자격 체계의 근거, 제품상의 해석, 계산 공식을 함께 기록한다.

---

## 4. Development Environment

기준 개발 환경은 다음과 같다.

- Host: Windows
- Development shell: WSL2 Ubuntu 24.04 LTS
- Target Python: 3.13
- Compatibility Python: 3.12
- Package manager: `uv`
- Container: Docker Desktop + WSL Integration, Docker Compose
- Project layout: `src/` + `tests/`
- API: FastAPI
- Target canonical store: PostgreSQL
- Raw store: 불변 로컬 파일 스냅샷

명령은 특별한 이유가 없으면 WSL의 프로젝트 루트에서 실행한다.

- 글로벌 `pip install`을 사용하지 않는다.
- `.venv`는 `uv`로 관리한다.
- dependency는 `pyproject.toml`, 정확한 해결 버전은 `uv.lock`으로 관리한다.
- secret은 `.env` 또는 적절한 secret manager에서만 주입한다.
- Docker가 필요한 검증은 먼저 `docker version`과 `docker compose version`으로 연결 상태를 확인한다.
- 실행 환경에 Docker가 없다고 해서 사용자의 Docker 환경도 없다고 단정하지 않는다. 검증하지 못한 범위만 정확히 보고한다.

기본 준비 명령:

```bash
cp .env.example .env
uv sync --dev --frozen
```

---

## 5. Development Principles

- 기존 프로젝트 구조와 문서를 먼저 이해한 뒤 코드를 작성한다.
- 요구사항을 충족하는 가장 단순한 구현을 우선한다.
- 요청 범위를 임의로 확대하지 않는다.
- 기존 기능과 사용자의 변경사항을 불필요하게 수정하지 않는다.
- 새로운 dependency는 필요성과 대안을 검토한 뒤에만 추가한다.
- 불확실한 내용, 외부 API, 라이브러리 사용법을 추측하지 않는다.
- architecture나 데이터 계약을 크게 바꿔야 하면 먼저 영향과 대안을 제시한다.
- 계산 함수는 가능한 한 순수 함수로 유지한다.
- 외부 서비스와 라이브러리는 adapter 또는 service 경계 뒤에 둔다.
- domain과 analytics 계층이 외부 API response 모델에 직접 의존하지 않게 한다.
- 외부 API transport는 주입 가능하게 설계하고 unit test에서 실제 네트워크를 호출하지 않는다.

---

## 6. Task Workflow

### Before implementation

1. 작업 트리와 현재 브랜치를 확인한다.

   ```bash
   git status --short
   git branch --show-current
   ```

2. `rg --files`와 `rg`로 관련 문서, 코드, 테스트를 찾는다.
3. `docs/PRD.md`의 관련 요구사항과 수용 기준을 확인한다.
4. `docs/PROJECT_OVERVIEW.md`와 관련 ADR을 확인한다.
5. 기존 테스트와 coding convention을 확인한다.
6. dependency 작업이면 `pyproject.toml`, `uv.lock`, `docs/dependency-sources.toml`, 현재 dependency tree를 확인한다.

   ```bash
   uv lock --check
   uv tree --locked
   ```

7. 여러 계층을 변경하거나 데이터 계약에 영향을 주면 구현 계획을 먼저 제시한다.

### During implementation

1. 필요한 파일과 계층만 변경한다.
2. 기존 naming, typing, error handling convention을 유지한다.
3. 정상 경로와 함께 실패·누락·충돌·stale 경로를 구현한다.
4. 새 데이터 공급자는 Source Registry와 source policy test를 모두 추가한다.
5. 파생 지표에는 입력 데이터의 의미, 단위, 기준시점, 계산 버전을 연결한다.
6. 테스트 fixture에 secret, 계좌정보, 재배포가 제한된 원문을 포함하지 않는다.
7. unrelated issue를 발견하면 현재 작업에 섞지 않고 별도로 보고한다.

### After implementation

1. 변경 파일과 의도하지 않은 생성 파일을 확인한다.

   ```bash
   git status --short
   git diff --check
   git diff --stat
   git diff
   ```

2. lockfile과 dependency 환경을 확인한다.

   ```bash
   uv lock --check
   uv sync --dev --frozen
   ```

3. 테스트와 정적 검사를 실행한다.

   ```bash
   uv run pytest
   uv run ruff check .
   uv run ruff format --check .
   ```

4. 변경 범위에 따라 CLI/API smoke test를 실행한다.

   ```bash
   uv run investment-decision sources
   uv run investment-decision risk --input examples/risk-analysis-input.json
   ```

5. Docker 구성을 변경했다면 가능한 환경에서 다음을 확인한다.

   ```bash
   docker compose config
   docker compose up --build
   ```

6. 실행하지 못한 검증은 통과한 것처럼 표현하지 않고 이유와 남은 위험을 보고한다.

---

## 7. Dependency Accuracy Protocol

AI agent는 라이브러리 API를 모델의 기억이나 일반적인 예제에만 의존해 사용하지 않는다. 다음 절차로 정확성을 높인다.

### 7.1 Before adding a dependency

다음 질문에 답할 수 있어야 한다.

- 표준 라이브러리나 현재 dependency로 해결할 수 없는가?
- 이 라이브러리가 담당할 책임은 하나로 명확한가?
- 동일한 역할의 라이브러리가 이미 존재하지 않는가?
- 공식 문서, 유지보수 상태, Python 3.12/3.13 지원, 라이선스가 확인되었는가?
- 금융 데이터 접근용이라면 공식 API 또는 공식 공급자 SDK인가?
- dependency를 제거하거나 교체할 때 영향 범위가 adapter 내부로 제한되는가?

단순 편의만으로 dependency를 추가하지 않는다. 특히 데이터 수집을 빠르게 만들기 위한 비공식 금융 라이브러리는 금지한다.

### 7.2 Use official documentation first

라이브러리를 사용하거나 변경할 때 다음 순서로 근거를 찾는다.

1. `docs/dependency-sources.toml`에서 해당 distribution의 공식 문서 위치를 확인한다.
2. `uv.lock` 또는 설치 환경에서 실제 버전을 확인한다.
3. package가 제공하는 공식 agent skill 또는 공식 `llms.txt`가 있으면 우선 사용한다.
4. 그다음 해당 버전의 공식 API reference와 공식 guide를 확인한다.
5. upgrade 작업이면 공식 changelog와 breaking change를 함께 확인한다.
6. 그래도 불명확하면 공식 source repository와 로컬 설치본의 signature/type hint를 확인한다.

기술 검색은 registry에 기록된 공식 domain으로 제한한다. 블로그, Q&A, 검색 요약은 공식 문서가 답하지 못하는 문제를 조사할 때만 보조 자료로 사용하며, 채택한 구현은 다시 공식 API나 설치본으로 검증한다.

FastAPI처럼 설치 버전에 맞춘 공식 agent skill을 package가 제공하는 경우 해당 skill을 선호한다. skill 설치는 프로젝트 tooling을 변경하므로 현재 작업 범위에 포함되는지 먼저 확인한다. 공식 `llms.txt`는 탐색용 index이며, 최종 API 사용법은 연결된 공식 versioned page에서 확인한다.

새 dependency에는 코드보다 먼저 `docs/dependency-sources.toml` 항목을 추가한다. 공식 문서를 찾지 못하거나 현재 버전과 일치하는지 확인할 수 없으면 구현을 추측하지 않고 작업을 중단해 사용자에게 알린다.

네트워크를 사용할 수 없는 환경에서는 registry URL, lock된 버전, 로컬 signature와 package source를 사용한다. 이 경우 공식 웹 문서를 실제로 열어 확인하지 못했다는 사실을 최종 보고에 남긴다.

### 7.3 Verify the installed version and API

1. `uv.lock`에 해결된 실제 버전을 확인한다.
2. 그 버전에 해당하는 공식 문서와 release note를 확인한다.
3. API signature가 불확실하면 로컬 설치본의 type hint, signature, docstring을 직접 확인한다.

예:

```bash
uv run python -c "import importlib.metadata as m; print(m.version('package-name'))"
uv run python -c "import inspect; from package import target; print(inspect.signature(target))"
```

- 블로그, 오래된 Stack Overflow 답변, 생성형 AI 코드 예제는 공식 문서의 대체물이 아니다.
- 최신 공식 문서가 lock된 버전과 다르면 해당 버전의 문서를 찾거나 upgrade를 별도 작업으로 수행한다.
- transitive dependency를 직접 import해야 한다면 먼저 direct dependency로 명시한다.

### 7.4 Add and lock dependencies

의존성은 `uv`로만 변경하며 `uv.lock`을 수동 편집하지 않는다.

```bash
uv add <package>
uv add --dev <package>
uv lock --check
uv tree --locked
```

- runtime dependency와 development dependency를 구분한다.
- `pyproject.toml`에는 호환 범위를, `uv.lock`에는 재현 가능한 정확한 버전을 유지한다.
- dependency 추가·삭제 시 `docs/dependency-sources.toml`과 registry test를 함께 갱신한다.
- 같은 목적의 대형 라이브러리를 동시에 도입하지 않는다. 예외가 필요하면 ADR에 비용과 제거 계획을 기록한다.

### 7.5 Isolate library-specific code

- 외부 타입과 예외는 connector, adapter, repository 경계 안에서 프로젝트의 domain 모델과 오류로 변환한다.
- 핵심 계산 함수가 pandas, Polars, 공급자 SDK response 객체에 종속되지 않게 한다.
- 라이브러리 호출을 여러 계층에 흩뿌리지 않는다.
- provider별 rate limit, retry, timeout, schema parsing을 공통 domain 계산과 분리한다.

### 7.6 Test library behavior, not only imports

새 라이브러리에는 해당되는 검증을 추가한다.

- contract test: 사용하는 함수의 입력·출력·예외 계약
- fixture test: 공식 API의 비식별·비밀 제거 샘플 응답 파싱
- golden test: 알려진 입력과 기대 계산 결과
- edge case: 빈 데이터, NaN, 무한대, 중복 날짜, 시간대, 단위, 수정 데이터
- failure test: timeout, rate limit, 잘못된 schema, partial response
- differential test: 중요 계산을 독립 공식 또는 신뢰 가능한 기준 구현과 비교

unit test는 네트워크와 API key 없이 재현 가능해야 한다. 실제 API 확인은 별도의 명시적 integration test로 분리한다.

### 7.7 Financial calculation checks

수치 라이브러리를 사용할 때 함수명만 맞는 것으로 완료하지 않는다. 다음 조건을 문서와 테스트에서 확인한다.

- raw, adjusted, total-return 가격 중 무엇을 사용하는가?
- 통화, 단위, 소수점, split·dividend 처리 방식은 무엇인가?
- 거래일 캘린더와 시간대는 무엇인가?
- 결측치, 무거래일, 중복일을 어떻게 처리하는가?
- 표본/모집단 표준편차와 자유도(`ddof`)는 무엇인가?
- 연환산 계수와 수익률 방식은 무엇인가?
- NaN 전파, 반올림, 수치 tolerance는 무엇인가?
- 계산 결과에 `calculation_version`과 입력 lineage가 연결되는가?

핵심 지표는 작은 hand-calculated fixture를 유지하고 `pytest.approx` 또는 명시된 tolerance로 검증한다.

### 7.8 Upgrade one dependency at a time

dependency upgrade는 기능 변경과 분리하고 한 번에 하나씩 수행한다.

```bash
uv lock --upgrade-package <package>
uv tree --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

- release note와 breaking change를 확인한다.
- adapter, schema, serialization, 수치 결과의 회귀를 확인한다.
- major upgrade나 계산 결과가 바뀌는 upgrade는 ADR 또는 명시적 변경 기록을 남긴다.
- 이유 없이 전체 dependency를 일괄 최신화하지 않는다.

---

## 8. Data and Analysis Rules

### Data ingestion

- 새 공급원은 `authority`, `access_method`, `role`, 문서·약관·확인 URL을 등록한다.
- API key가 URL query에 포함되면 저장·로그 전에 마스킹한다.
- 원본 response는 수정하지 않고 content hash와 함께 보관한다.
- parser가 변경되어도 기존 raw snapshot을 덮어쓰지 않는다.
- 공급원 값이 다르면 시간대, 가격 기준, 기업행동, 거래 세션을 먼저 확인한다.
- 해결되지 않은 충돌은 canonical store에 승격하지 않는다.

### Deterministic analytics

- 같은 입력, 파라미터, 계산 버전은 같은 결과를 반환해야 한다.
- 사실, 계산 결과, 가정, 사용자 정책을 서로 다른 필드로 유지한다.
- 적은 표본과 알려지지 않은 가격 기준 등 한계를 결과에 표시한다.
- 기술지표를 보편적인 매수·매도 규칙으로 변환하지 않는다.

### AI document analysis

- 허용된 공시, IR, 공식 문서와 API가 제공한 뉴스 메타데이터만 사용한다.
- JSON schema, 원문 URL, 근거 구간, 모델·프롬프트 버전을 기록한다.
- AI에게 재무비율, 시장가격, 목표주가, 최종 결정을 계산하게 하지 않는다.
- 모델이 표현한 자신감을 데이터 신뢰도로 사용하지 않는다.

---

## 9. Git Rules

commit은 논리적으로 의미 있는 작업 단위로 작성한다.

예:

```text
feat: add SEC submissions ingestion
fix: quarantine conflicting close prices
refactor: isolate source policy validation
test: add maximum drawdown edge cases
docs: define dependency accuracy protocol
```

사용자의 명시적인 요청 없이 다음 작업을 수행하지 않는다.

- `git push`
- branch 삭제
- history rewrite
- force push
- 기존 commit 수정

다음 destructive command도 명시적인 요청 없이 실행하지 않는다.

```bash
git reset --hard
git clean -fd
git push --force
```

기존 작업 트리가 dirty하면 사용자의 변경을 보존한다. 관련 없는 변경을 되돌리거나 commit에 섞지 않는다.

---

## 10. Security and Destructive Operations

다음 정보를 source code, fixture, Git repository, 로그, 최종 응답에 저장하거나 노출하지 않는다.

- API keys
- passwords
- access tokens
- private keys
- 계좌번호와 주문 권한
- 기타 credentials 또는 불필요한 개인정보

Secret은 environment variable 또는 secret manager로 주입한다. `.env.example`에는 이름과 설명만 두고 실제 값을 넣지 않는다.

다음 작업은 실행 전에 대상, 영향, 복구 가능성을 확인한다.

- `sudo`, `rm -rf`
- `git reset --hard`, `git clean`, `git push --force`
- `docker compose down -v`, `docker system prune`
- database migration, `DROP`, `TRUNCATE`, 대량 `DELETE`
- raw snapshot 또는 canonical history 삭제
- 외부 API의 write, order, account scope 사용

이 프로젝트의 데이터 수집 프로세스에는 주문 권한을 부여하지 않는다.

---

## 11. AI Agent Behavior

AI agent는 단순 코드 생성기가 아니라 비판적이고 객관적인 개발 파트너로 행동한다.

- 먼저 이해하고 그다음 수정한다.
- 작은 변경과 명확한 경계를 선호한다.
- 변경 이유와 trade-off를 설명할 수 있어야 한다.
- 오류, 실패한 테스트, 검증하지 못한 범위를 숨기지 않는다.
- 라이브러리나 API 사용법이 불확실하면 추측 대신 설치 버전과 공식 문서를 확인한다.
- 수익성이 좋아 보인다는 이유로 검증되지 않은 분석 규칙을 채택하지 않는다.
- 현재 작업과 직접 관련 없는 개선은 수정하지 않고 별도 제안으로 보고한다.
- 사용자에게 필요한 선택지가 생기면 영향과 권장안을 함께 제시한다.

---

## 12. Documentation Rules

- 기존 문서를 먼저 확인하고 중복 문서를 만들지 않는다.
- 제품 요구사항 변경은 `docs/PRD.md`에 반영한다.
- 중요 architecture와 trade-off 변경은 `docs/adr/`에 기록한다.
- 설치·실행·사용 방법 변경은 `README.md`에 반영한다.
- 프로젝트를 통해 얻은 일반 지식과 개인적 통찰을 프로젝트 문서에 섞지 않는다.
- 코드 자체가 명확하면 불필요한 주석을 추가하지 않는다.
- 외부 문서 URL과 공급자 약관은 검토일을 함께 관리한다.

---

## 13. Completion Criteria

작업 완료 전에 다음을 확인한다.

- 요구사항과 요청 범위를 충족했는가?
- 불변 제품 원칙을 위반하지 않았는가?
- 관련 테스트가 통과했는가?
- lint와 format check가 통과했는가?
- dependency와 lockfile이 일치하는가?
- direct dependency가 공식 문서 registry에 등록되어 있는가?
- 외부 라이브러리 API를 실제 설치 버전 기준으로 검증했는가?
- 금융 계산의 가격 기준, 단위, 기간, tolerance가 명시되었는가?
- 데이터 충돌·누락·실패 경로가 테스트되었는가?
- 의도하지 않은 파일 변경이나 secret이 없는가?
- `git diff`를 확인했는가?
- 실행하지 못한 검증과 남은 위험을 기록했는가?

최종 보고에는 다음을 포함한다.

1. 변경사항
2. 실행한 테스트와 결과
3. 검증하지 못한 사항
4. 중요한 trade-off와 남은 위험
5. 필요한 다음 작업
