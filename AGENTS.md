# AGENTS.md

## 1. Project Overview

1명(저장소 소유자)이 쓰는 개인용 자산배분 실험 도구다. 여러 자산군으로 만든 배분 전략을 같은 기준으로 비교하고, 이후 가설 원장으로 예측을 채점한다. 제품 목표·범위·데이터 원칙은 [PRD](PRD.md)에 있다. 현재 구현은 M2-4(예측·채점)까지와 M5의 읽기 전용 Mac 앱이다. 진행 순서는 [로드맵](docs/roadmap.md)을 따른다.

---

## 2. Documentation Hierarchy

변경 전 다음 문서를 순서대로 확인한다.

1. `PRD.md` — 제품 목표, 데이터 원칙, 범위 통제 (Source of Truth)
2. `docs/roadmap.md` — 마일스톤 진행과 결정 대기
3. `docs/adr/` — 채택된 중요 결정과 근거
4. `README.md` — 구현된 기능, 설치, 실행 방법
5. `docs/concepts/` — 구현한 금융 개념의 정의·공식·근사
6. `AGENTS.md` — AI agent 작업 규칙

`docs/dependency-sources.toml`은 dependency와 주요 개발 도구의 공식 문서·변경 이력 registry다. Git 작업은 [`docs/git_flow.md`](docs/git_flow.md)만 따른다.

문서, 구현, 사용자의 최신 지시가 충돌하면 임의로 하나를 고르지 않는다. 충돌 위치와 영향을 설명하고 확인한다. 같은 내용을 여러 문서에 중복 기록하지 않는다.

---

## 3. Product Principles

데이터 원칙과 범위 통제는 [PRD](PRD.md) 4절·11절이다. 변경하려면 ADR이 필요하다. 이 문서는 PRD에 없는 금지 사항만 추가한다.

- 어떤 프로세스에도 주문 권한을 주지 않는다.
- HTML 크롤링, 웹 스크래핑, 브라우저 자동화, 비공식·역공학 API를 쓰지 않는다. `yfinance`, `pykrx`, `FinanceDataReader` 같은 비공식 금융 라이브러리도 쓰지 않는다.
- 검증 URL은 사용자 확인용이다. 자동 수집하지 않는다.
- README에 "구현됨"으로 적는 항목은 테스트로 확인된 것만 허용하고, 항목마다 테스트 파일을 적는다. 구현되지 않은 기능은 적지 않는다.

---

## 4. Development Environment

- 개발 셸: WSL2 Ubuntu 24.04(또는 macOS), Python 3.13 목표·3.12 호환, 패키지 관리 `uv`
- 구조: `src/` + `tests/`. 런타임 의존성 없음(표준 라이브러리만). Mac 앱은 `app/`(Swift Package, 외부 패키지 없음, [ADR-0008](docs/adr/0008-mac-app-read-only.md))이며 DB를 읽기 전용으로만 연다. 앱에 계산·기록 로직을 복제하지 않는다.
- 저장: SQLite(`DATABASE_PATH`), 원본은 불변 로컬 파일(`RAW_STORE_PATH`)
- 글로벌 `pip install` 금지. `.venv`는 `uv`로 관리한다. dependency는 `pyproject.toml`, 정확한 버전은 `uv.lock`이 담당한다.
- secret은 `.env` 또는 secret manager로만 주입한다.

```bash
cp .env.example .env
uv sync --dev --frozen
```

---

## 5. Development Principles

- 기존 구조와 문서를 먼저 이해한 뒤 작성한다. 요구사항을 충족하는 가장 단순한 구현을 택하고 요청 범위를 넓히지 않는다.
- architecture나 데이터 계약을 크게 바꿔야 하면 먼저 영향과 대안을 제시한다.
- 계산 함수는 순수 함수로 두고, 외부 서비스·라이브러리는 adapter 경계 뒤에 둔다. domain·analytics는 외부 API response 모델에 의존하지 않는다.
- 외부 API transport는 주입 가능하게 만들고, unit test에서 실제 네트워크를 호출하지 않는다.
- 불확실한 API나 라이브러리 사용법은 추측하지 않는다(7절).
- 정상 경로와 함께 실패·누락·충돌·stale 경로를 구현하고 테스트한다.
- 새 데이터 공급자는 Source Registry와 source policy test를 함께 추가한다.
- 파생 지표에는 입력의 의미·단위·기준시점·계산 버전을 연결한다.
- fixture에 secret, 계좌정보, 재배포가 제한된 원문을 넣지 않는다.
- 현재 작업과 무관한 문제는 섞지 않고 따로 보고한다.

---

## 6. Task Workflow

### 시작 전

1. `git status --short`, `git branch --show-current`로 상태를 확인한다.
2. `rg`로 관련 문서·코드·테스트를 찾고, PRD의 관련 요구사항과 ADR을 확인한다.
3. 여러 계층을 바꾸거나 데이터 계약에 영향이 있으면 계획을 먼저 제시한다.

### 끝난 뒤

검증 명령은 [`docs/git_flow.md`](docs/git_flow.md) 5절에 있다. 추가로 `git diff --check`, `git diff --stat`로 의도하지 않은 파일과 secret이 없는지 확인한다. 실행하지 못한 검증은 통과한 것처럼 쓰지 않고 이유와 남은 위험을 적는다.

### 완료 기준과 최종 보고

다음을 확인한다. 요구사항 충족, 불변 원칙 준수, 테스트·lint·format 통과, lockfile 일치, 직접 dependency의 registry 등록, 금융 계산의 가격 기준·단위·기간·tolerance 명시, 충돌·누락·실패 경로 테스트, secret 없음.

최종 보고에는 ① 변경사항 ② 실행한 테스트와 결과 ③ 검증하지 못한 사항 ④ trade-off와 남은 위험 ⑤ 다음 작업을 넣는다.

---

## 7. Dependency Accuracy

런타임 dependency는 지금 없다. 추가할 때와 라이브러리 API를 쓸 때 다음을 따른다.

- **추가 전:** 표준 라이브러리나 기존 dependency로 안 되는지, 책임이 하나인지, 같은 역할의 라이브러리가 없는지, 공식 문서·유지보수·Python 3.12/3.13 지원·라이선스를 확인한다. 금융 데이터 접근용은 공식 API나 공식 SDK만 쓴다. 코드보다 먼저 `docs/dependency-sources.toml`에 항목을 추가하고 registry test를 갱신한다.
- **API 근거:** registry의 공식 문서, 실제로 lock된 버전, 해당 버전의 공식 reference 순으로 확인한다. 불명확하면 설치본의 signature·type hint를 직접 본다. 블로그·Q&A·생성형 예제는 대체물이 아니다. 근거를 찾지 못하면 구현을 추측하지 말고 멈춰서 알린다.
- **변경:** `uv add`, `uv lock --check`, `uv tree --locked`로만 바꾸고 `uv.lock`을 수동 편집하지 않는다. upgrade는 기능 변경과 분리해 한 번에 하나씩 하고 changelog를 확인한다.
- **격리:** 외부 타입과 예외는 adapter 안에서 domain 모델과 오류로 바꾼다. 핵심 계산이 pandas 같은 라이브러리에 묶이지 않게 한다.
- **테스트:** 라이브러리 동작은 contract·fixture·golden·edge·failure 테스트로 확인한다. unit test는 네트워크와 API 키 없이 돌아야 한다. 실제 API 확인은 별도 integration으로 분리한다.
- **금융 계산:** 가격 기준(raw·adjusted·total return), 통화·단위, 거래일 캘린더·시간대, 결측·중복 처리, 표준편차 `ddof`, 연환산 계수, NaN 전파와 반올림·tolerance를 문서와 테스트에 명시한다. 핵심 지표는 손 계산 fixture를 `pytest.approx`로 검증하고, 결과에 `calculation_version`과 입력 lineage를 연결한다.

---

## 8. Data and Analysis Rules

- 새 공급원은 `authority`, `access_method`, `role`, 문서·약관·확인 URL을 등록한다. 외부 문서 URL과 약관은 검토일을 함께 둔다.
- API key가 URL query에 있으면 저장·로그 전에 마스킹한다.
- 원본 response는 수정하지 않고 content hash와 함께 보관한다. parser가 바뀌어도 기존 snapshot을 덮어쓰지 않는다.
- 공급원 값이 다르면 시간대·가격 기준·기업행동·거래 세션을 먼저 확인한다. 해결되지 않은 충돌은 canonical store에 올리지 않는다.
- 같은 입력·파라미터·계산 버전은 같은 결과를 반환해야 한다. 사실·계산 결과·가정·사용자 정책은 다른 필드로 둔다. 적은 표본과 알려지지 않은 가격 기준 같은 한계는 결과에 표시한다.

---

## 9. Security and Destructive Operations

API key, password, token, private key, 계좌번호, 주문 권한, 불필요한 개인정보를 코드·fixture·Git·로그·최종 응답에 남기지 않는다. `.env.example`에는 이름과 설명만 둔다.

실행 전에 대상·영향·복구 가능성을 확인하는 작업: `sudo`, `rm -rf`, `git reset --hard`, `git clean`, `git push --force`, `docker system prune`, DB migration·`DROP`·`TRUNCATE`·대량 `DELETE`, raw snapshot·canonical history 삭제, 외부 API의 write·order·account scope 사용.

---

## 10. AI Agent Behavior

비판적이고 객관적인 개발 파트너로 행동한다. 먼저 이해하고 그다음 수정하며, 작은 변경과 명확한 경계를 선호한다. 변경 이유와 trade-off를 설명한다. 오류·실패한 테스트·검증하지 못한 범위를 숨기지 않는다. 수익성이 좋아 보인다는 이유로 검증되지 않은 분석 규칙을 채택하지 않는다. 선택지가 생기면 영향과 권장안을 함께 낸다.

---

## 11. Documentation Rules

- 기존 문서를 먼저 확인하고 중복 문서를 만들지 않는다.
- 제품 요구사항은 `PRD.md`, 진행 상황은 `docs/roadmap.md`, 중요한 결정과 trade-off는 `docs/adr/`, 설치·실행은 `README.md`에 기록한다.
- 프로젝트에서 얻은 일반 지식과 개인적 통찰을 프로젝트 문서에 섞지 않는다.
- 코드가 명확하면 주석을 추가하지 않는다.
- 병합이 끝날 때마다 `docs/roadmap.md`를 갱신한다. 로드맵 아티팩트는 더 쓰지 않는다(2026-11-21 사용자 결정, 삭제함).
