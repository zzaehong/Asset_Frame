# 환경변수와 미설정 시 제한

실제 값은 `.env`에만 두고 Git에는 커밋하지 않습니다. `asset-frame environment-status`는 값이나
길이를 노출하지 않고 설정 여부만 출력합니다. `current`는 이미 구현된 경로, `planned`는 후속
connector 구현 전에 미리 예약한 이름입니다.

| 환경변수 | 용도 | 없을 때 불가능한 작업 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL 접속 | 작업 준비·실행·상태 조회, 유니버스 선정, canonical/raw metadata 저장, Data Console 실행 |
| `KRX_API_KEY` | KRX OPEN API 인증 | KRX 종목 기본정보 및 KOSPI·KOSDAQ·ETF 실데이터 수집, KRX backfill 실행 |
| `TIINGO_API_KEY` | Tiingo EOD 인증 | 미국 종목 가격·기업행동 수집, discovery 가격 수집, 5년 backfill 실행 |
| `SEC_USER_AGENT` | SEC Fair Access 식별 문자열(비밀키 아님) | SEC ticker→CIK 매핑과 submissions 수집 |
| `OPENDART_API_KEY` | OpenDART 인증 | corp code 매핑과 공시목록 수집 |
| `FRED_API_KEY` | FRED 인증(후속 구현) | 미국 거시 시계열 실수집 |
| `ECOS_API_KEY` | 한국은행 ECOS 인증(후속 구현) | 한국 거시 시계열 실수집 |
| `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` | 네이버 뉴스 API 인증(후속 구현) | 최근 한국 뉴스 제목·요약·매체·시각·URL 수집 |

GDELT는 API 키가 필요하지 않습니다. 다만 connector가 아직 구현되지 않아 최근 해외 뉴스
메타데이터 수집은 현재 불가능합니다. 뉴스는 짧은 최근 기간의 메타데이터만 저장하고 기사
본문은 저장하지 않는 정책을 유지합니다.

키가 없어도 가능한 작업은 fixture 기반 parser·품질·작업 재시도 테스트, schema 구현과
PostgreSQL 로컬 통합 테스트입니다. `DATABASE_URL`만 준비되면 외부 API를 호출하지 않는 작업
준비와 상태 조회도 가능합니다. `RAW_STORE_PATH`는 원본 저장 위치를 바꾸는 선택 설정이며,
현재 CLI의 `--raw-store` 기본값은 `var/raw`입니다.

상태 확인:

```bash
uv run asset-frame environment-status
```

키 발급과 이용 조건은 각 공식 공급원(KRX OPEN API, Tiingo, SEC Fair Access, OpenDART,
FRED, 한국은행 ECOS, 네이버 개발자센터)에서 확인합니다.
