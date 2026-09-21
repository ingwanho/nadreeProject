# W00~W02 구현 기록

작성일: 2026-09-14. 대상: 독립 `nadree api` 서버. 상위 검토 문서 번호가 아니라 구현 작업 그룹 W00~W02다.

최종 수정일: 2026-09-21.

## 완료 표시와 요약

- **완료**: 아래에 적힌 기본 기능의 코드 구현과 로컬 자동 테스트를 마쳤다. 실제 MySQL·Redis·SMTP 연동, MFA 흐름, 앱 연결 및 운영 배포 완료를 뜻하지 않는다.
- **부분 완료**: 구현한 기능은 있지만 일부 요청 필드나 작업이 남아 있다.
- **보류**: 저장 기준 등이 정해지지 않아 업무 처리를 제공하지 않는다. 권한 검사·503 응답만으로 완료 처리하지 않는다.

| 그룹 | 완료된 범위 | 부분 완료·보류 | 그룹 전체 상태 |
| --- | --- | --- | --- |
| W00 | 기반 코드·로컬 테스트·이번 범위의 마이그레이션 준비 **완료** | 실제 의존 서비스 연동·DB 적용/재적용 검증 대기 | **부분 완료** |
| W01 | **7 / 7개 API 구현 완료**: 01·02·03·04·05·06·07 | DB 적용·호환 암호화 키·MFA·실연동 별도 대기 | **부분 완료** |
| W02 | **8 / 8개 명세 API + 가입 접수 구현 완료**: 17·23·28·29·30·31·32·33 및 `/nadreego/admin/signup` | DB 적용·MySQL 동시성·실연동 대기 | **부분 완료** |

**API 합계: 구현 완료 15개 / 부분 완료 0개 / 보류 0개.** API 개수 기준 집계이며 전체 개발 공수나 출시 준비율을 의미하지 않는다. W00은 API 개수에 포함하지 않는다.

## 진행표

모든 API의 실제 서비스 연동은 별도 대기 상태다. 아래 상태는 코드 구현·로컬 검증 기준이며, 개별 제한은 마지막 열에 구분한다.

| 그룹/API | 구현 내용 | 구현 상태 | 제한·남은 조건 |
| --- | --- | --- | --- |
| W01 / 01 로그인 | bcrypt 확인, 새 서버 JWT·refresh 저장, 선택 FCM 갱신 | **완료** | 관리자 ID별 활성 세션 최대 3개. 네 번째 로그인 시 가장 오래된 세션 폐기. MFA 흐름 미구현, 설정 계정은 우회하지 않고 `MFA_REQUIRED` |
| W01 / 02 갱신 | refresh 회전, 만료·폐기 검사, 원래 인증 시각 유지 | **완료** | 관리자 세션별 회전. MySQL 동시 갱신 검증 대기 |
| W01 / 03 로그아웃 | 토큰 쌍 검증·세션 폐기·FCM 토큰 보존 | **완료** | 공통 실연동 검증 대기 |
| W01 / 04 지점 체크 | 초대 코드 정확 비교·지점/계약 활성 확인 | **완료** | 초대 코드 발급·소비·가입 승인 기능은 아님 |
| W01 / 05 본인 수정 | 이름·이메일·비밀번호·FCM·전화번호 암호화 저장, 민감 변경 재인증 | **완료** | phone VARCHAR(200) 계획·저장 테스트 완료. 실제 DB 적용·호환 Fernet 키·MySQL 이메일 동시 변경 검증 필요 |
| W01 / 06 FCM | 자신의 최신 토큰·갱신 시각 저장 | **완료** | 예약·승인·결제 완료 후 커밋 뒤 발송, 실패 재시도는 W09 작업으로 구현 |
| W01 / 07 비밀번호 찾기 | 이메일 요청으로 임시 비밀번호 발송, 해시 변경·세션 폐기 | **완료** | 메일 대역 테스트 완료. SMTP 실발송 미검증, 아래 보안·전달 한계 유지 |
| W02 / 17 대표 변경 | 현재 지점 잠금·역할 재조회·기존 대표/새 대표 일괄 변경 | **완료** | MySQL 동시성 검증 대기 |
| W02 / 23 샵 수정 | 샵명·주소·연락처·배송 방식·소개·연락 이메일, 정규 조직 행도 반영 | **완료** | introduction/contact_email 저장·길이·다른 지점 불변 검증 완료. 실제 DB 적용·앱 연동 대기 |
| W02 / 28 하위조직 조회 | 내 지점 하위·같은 계약만, 검색/유형/활성/담당자 필터·offset/limit | **완료** | 담당자는 현재 지점의 활성 대표 이름 |
| W02 / 29 하위조직 생성 | 대표 전용·부모 범위·계약 날짜·조직 코드·정규 테이블·렌탈 지점 행·대표용 일회성 invite_code | **완료** | MySQL 동시 생성 검증 대기 |
| W02 / 30 관리자 목록 | 현재 지점 활성 렌탈 관리자와 현재 role | **완료** | 공통 실연동 검증 대기 |
| W02 / 31 관리자 삭제 | 일반 렌탈 role 제거·새 서버 세션 폐기·FCM 제거 | **완료** | 공유 계정·웹 role·공유 scope는 삭제하지 않음 |
| W02 / 32 신청 조회 | 대표의 현재 지점 REQUESTED 조회, 하위 조회 선택, 기존 admins(email/name) 응답 | **완료** | 실제 DB 적용 대기 |
| W02 / 33 신청 승인/거절 | 신청 잠금·계정 재검증·일반 role/소속/scope·처리자/시각 일괄 반영 | **완료** | 중복·타 지점·비활성 계정·롤백 로컬 검증 완료. MySQL 동시성·접수·앱 연동 대기 |

15개 경로의 기본 기능과 관리자 가입 접수·하위지점 초대 소비 코드를 로컬 검증했다. 05·23도 승인된 저장 컬럼 기준으로 검증했다. DB 설정이 없으면 `DATABASE_NOT_CONFIGURED`, 마이그레이션 미적용·키 미설정 시 저장 오류가 발생하므로 실제 운영 가능을 뜻하지 않는다.

## W00 세부 진행

| 작업 | 상태 | 확인한 범위·남은 조건 |
| --- | --- | --- |
| 독립 실행·설정·상태 확인 기반 | **완료** | FastAPI, 비밀값 없는 설정 예시, 의존성 고정, health·OpenAPI 구성 |
| DB·날짜 공통 코드 | **완료** | 트랜잭션·롤백·스키마 조회, UTC 저장·발리 영업 날짜의 로컬 검증. 실제 MySQL 연결·행 잠금 검증은 별도 |
| 인증·권한·오류 공통 코드 | **완료** | JWT·현재 DB 세션·역할·지점 범위 검사와 오류 응답의 로컬 검증. MFA 연동·기존 서버 회귀는 별도 |
| 이번 범위의 마이그레이션 준비 | **완료** | 관리자 FCM 2컬럼·기존 phone VARCHAR(200) 확장·MSP_SPOT_RENT 8컬럼·MSP_RENTAL_ADMIN_REQUEST 8컬럼·렌탈 역할 행·고객 refresh token 테이블에 대한 적용 도구·SQL·읽기 전용 계획 테스트. 알림 큐 테이블은 제외하며 렌탈 18테이블 전체 마이그레이션 완료를 뜻하지 않음 |
| 로컬 자동 테스트·명세 대조 | **완료** | 145개 테스트 통과, 기존 15개 API와 관리자 가입 접수 경로의 구현·응답 검증 통과 |
| 실제 서비스 연동·운영 준비 | **대기** | MySQL·Redis·SMTP, 마이그레이션 적용/재적용, MFA·앱·기존 서버 연결 및 운영 DB 적용 미완료 |

## 이번 사용자 결정

- 사용자 추가 승인으로 이전 신청 테이블 보류 결정을 변경했다. MSP_RENTAL_ADMIN_REQUEST에 신청 대기·승인·거절을 별도로 저장한다. 비활성 관리자나 기존 초대 토큰을 임의로 신청 대기로 해석하지 않는다. 실제 공유 DB 적용은 수행하지 않는다.
- 비밀번호 찾기는 기존 이메일·status 계약을 유지한다. 일회용 링크·확인 API·새 저장 테이블은 이번에 추가하지 않는다.
- 고객 프로필의 `GENDER`는 `M/F/OTHER`, `NATIONALITY`는 ISO 3166-1 alpha-2 대문자 코드로 검증한다. 나드리 고객 access token은 1시간 유효하며 고객 refresh token은 UID당 활성 1개를 별도 테이블에 저장한다.
- 관리자 ID별 활성 refresh 세션은 최대 3개로 제한하고 네 번째 로그인 시 가장 오래된 세션을 폐기한다.
- DB 계획 v2.24는 지점 소개·연락 이메일과 렌탈 사용자 분리(uid_token 기반), 고객 refresh token을 반영한 18테이블 설계다. MSP_ADMIN은 FCM 2컬럼 추가와 기존 phone VARCHAR(200) 확장이 예정되어 있다. 기존 001·002 SQL은 유지하고 마이그레이션 도구가 필요한 ALTER만 계획한다. 200자 이상인 phone은 축소하지 않는다. 나머지 미구현 업무 테이블은 해당 구현 때 준비한다.

## 관리자 가입 요청 처리

- **32·33 완료 (코드·로컬 검증)**: 기존 GET adminRequest와 POST adminRequestAction(email/action)을 유지한다. 신청 테이블·컬럼 정의는 [상위 DB 계획](../../rental-project-master.md#db-msp_rental_admin_request)이 정본이다.
- 목록은 현재 대표의 지점 REQUESTED만 접수 시각·신청 ID 오름차순으로 반환한다. 처리 후 목록에서 제외하며 신청이 없으면 `admins: []`다. 비활성 계정을 신청으로 추정하지 않는다.
- 승인은 신청 상태·활성 계정·이메일·현재 지점/계약·기존 렌탈 역할을 재검증한다. 소속 연결·일반 role·manage scope·처리자/시각을 한 트랜잭션으로 저장한다. 다른 지점 이동·대표 승격·계정 재활성화·MFA 변경은 하지 않는다. 거절은 신청 행만 변경한다.
- 신청 없음/타 지점은 `ADMIN_REQUEST_NOT_FOUND`(404), 이미 처리한 신청은 `ADMIN_REQUEST_ALREADY_PROCESSED`(409)다. 실패 시 새 role/scope/소속이 남지 않도록 롤백한다.
- 같은 지점의 이메일/계정 신청은 각각 UNIQUE다. 완료 행을 자동 재개하지 않는다. 거절 후 재신청·복수 신청 이력은 별도 후속 설계이며 이번 email/action 계약만으로 지원한다고 보지 않는다.
- **가입 접수 구현**: `POST /nadreego/admin/signup`이 `loginId/email/password/name/phone`과 대표 이메일 또는 inviteCode를 받아 RiderLog 호환 MSP_ADMIN 계정을 만들고 MSP_RENTAL_ADMIN_REQUEST를 REQUESTED로 저장한다. inviteCode는 신청 성공 시 NULL로 소비되며 승인 전에는 role/scope를 쓰지 않는다. 하위지점 신청은 대표 이메일과 spotMasterId를 함께 사용해 승인한다.

## 인증 계약

| 대상 | 헤더 |
| --- | --- |
| 로그인·비밀번호 찾기 | 인증 토큰 없음 |
| 갱신 | `X-Refresh-Token` 필수. 만료된 access token 때문에 갱신을 차단하지 않음 |
| 로그아웃 | `Authorization: Bearer <accessToken>` + `X-Refresh-Token`, 선택 `X-FCM-Token` |
| 본인 수정 | Bearer 필수. 이메일/비밀번호 변경 시 해당 세션의 `X-Refresh-Token`과 최근 5분 이내 비밀번호 로그인 필요 |
| 그 밖의 이번 보호 API | Bearer 필수. refresh token을 매 요청마다 요구하지 않음 |

- access 기본 15분, refresh 절대 수명 30일. 갱신해도 최초 비밀번호 로그인 시각과 절대 수명을 늘리지 않는다. 앱은 refresh 요청을 직렬화하고 새 토큰을 함께 교체한다.
- 나드리 고객 access 기본 1시간. 고객 refresh token은 `MSP_RENTAL_USER_REFRESH_TOKEN`에서 회전하며 UID당 활성 토큰 1개만 유지한다.
- `MSP_REFRESH_TOKEN.user_agent = nadree-api/v1`로 이 서버 세션을 구분한다. 토큰 원문은 저장하지 않고 SHA-256 해시만 저장한다. 기존 서버 JWT를 자동 수락하지 않는다.
- 모든 보호 요청에서 관리자 활성·DB 세션·현재 역할을 검사한다. 지점 업무는 추가로 `primary_spot_master_id`, manage scope, 지점·계약 활성/날짜를 검사한다.
- 이메일/비밀번호 변경 및 비밀번호 찾기는 해당 관리자의 공유 DB refresh token을 폐기한다. 기존 웹 access JWT까지 즉시 폐기되는지는 기존 서버의 검증·캐시 정책과 별도로 확인해야 한다.
- 전화번호는 기존 Fernet 방식만 지원한다. 입력 원문 최대 20자는 유지하고, 저장 컬럼은 사용자 승인에 따라 VARCHAR(200)으로 확장한다. 키 미설정·미확장 DB·암호문 길이 초과 시 오류를 반환하며 평문 대체·잘라 저장·API 호출 중 자동 스키마 변경은 하지 않는다.
- 이메일은 `MSP_ADMIN.email`만 변경하고 공유 로그인 식별자 `login_id`는 유지한다. 기존 email 컬럼은 UNIQUE가 아니므로 모호한 로그인은 거절하며 새 서버 이메일 변경은 MySQL named lock으로 직렬화한다. 다른 서버도 같은 이메일 정책을 적용해야 전역 일관성이 보장된다.

## 비밀번호 찾기 주의사항

현재 계약상 **메일 소유권 확인 전에 기존 비밀번호가 변경될 수 있다**. 임시 비밀번호 이메일도 계정의 중요 정보를 포함하므로 일회용 링크보다 안전하다고 보지 않는다. 사용자 결정에 따라 이 방식은 유지하되 다음을 구현했다.

- 충분한 무작위 임시 비밀번호, bcrypt 저장, 원문을 응답·로그에 포함하지 않음.
- IP·이메일 단위 제한 및 계정 단위 5분 재요청 제한. 알 수 없거나 모호하거나 비활성인 계정은 비밀번호를 바꾸지 않고 같은 success 형식 반환.
- SMTP 인증서 검증·시간 제한. 전송 실패 시 DB 변경과 세션 폐기를 롤백.
- SMTP 수락과 DB COMMIT은 하나의 원자적 작업이 아니다. SMTP 수락 후 DB 실패·네트워크 결과 불명 시 전달된 임시 비밀번호가 저장되지 않을 수 있다. 현재 구조에 outbox를 추가하지 않았으며 정확히 한 번 발송·최종 배달을 보장하지 않는다.
- 실제 SMTP 계정과 발신 도메인 설정·전달 확인은 아직 수행하지 않았다. 현재 설정이 없으면 `MAIL_NOT_CONFIGURED`다.

## 권한과 잠금

대표 코드는 `rental_primary_admin`, 일반 코드는 `rental_manager`를 새 서비스에서 사용한다. 기존 RiderLog의 6개 역할 상수와 정규화는 변경하지 않았다. 기존 account_type과 웹 role을 렌탈 role로 덮어쓰지 않는다.

- 대표 역할은 주 소속 지점에만 적용한다. 다른 scope가 있다는 이유만으로 모든 지점의 대표가 되지 않는다.
- 하위 생성·대표 변경·관리자 삭제·가입 요청 처리 및 현재 샵 수정은 대표 전용이다. 샵 수정의 일반관리자 허용 범위는 후속 결정 전까지 제한한다.
- MySQL 연결 격리 수준은 READ COMMITTED. 지점 변경 작업은 지점 행을 `FOR UPDATE`로 잠그고 권한을 다시 확인한다. 대표 변경은 기존 대표가 정확히 1명인지 검사한다.
- 계정 쓰기는 관리자 행, 세션 행 순서로 잠근다. 동일 refresh 경합은 한 요청만 회전에 성공하도록 조건부 갱신한다.
- 다른 서버의 대표 변경·관리자 소속 변경·조직 코드 발급도 같은 잠금 규칙을 따라야 한다. 이번 코드만으로 공유 DB 전체의 대표 1명 제약이나 기존 서버와의 동시 쓰기 검증이 끝난 것은 아니다.
- 최초 대표/렌탈 일반 role 배정·기존 지점 sidecar 연결은 운영 절차 확인 후 수행한다. 임의의 기존 계정을 대표로 승격하지 않는다.

## 오류·저장 제한

성공 본문은 기존 API별 형식이며 status는 문자열 `success`다. 오류는 HTTP 상태와 `{"status":"fail","errorCode":"..."}`로 반환하고 비밀번호·토큰·SQL 값은 포함하지 않는다.

주요 코드: `AUTH_REQUIRED`, `INVALID_CREDENTIALS`, `INVALID_REFRESH_TOKEN`, `TOKEN_PAIR_MISMATCH`, `MFA_REQUIRED`, `PRIMARY_ADMIN_REQUIRED`, `SPOT_ACCESS_DENIED`, `SPOT_CONTRACT_INACTIVE`, `RATE_LIMITED`, `SCHEMA_MAPPING_REQUIRED`.

샵 소개·이메일은 사용자 승인으로 MSP_SPOT_RENT.introduction VARCHAR(500) NULL 및 contact_email VARCHAR(200) NULL에 연결했다. 실제 DB에 컬럼이 없으면 503으로 요청 전체를 거절한다. 입력 생략 시 기존 값을 유지하며 명시적 null·입력 길이 초과는 거절한다. 주소 등 입력 상한보다 실제 DB 컬럼이 짧으면 저장 전에 422로 거절한다.

## 검증 결과

- **완료 (로컬 자동 테스트)**: 2026-09-21 재검증, `python -m pytest -q` 기준 **145 passed, 6 skipped**, SQLite·대역 기반 검증 통과. 관리자 가입 접수·하위지점 초대 소비·정비 만료·승인 후 결제 기한 알림·미결제 예약 만료·일별 재고 재실행을 포함한다. 관리자 3세션 상한·고객 access/refresh token 회전·로그아웃 폐기, 관리자·고객 refresh token 분리, 앱 FCM 토큰 저장·로그아웃 보존, 프로필 코드 검증과 기존 phone·샵 저장도 포함한다.
- **완료 (명세 대조)**: `scripts/validate_w02_spec.py`로 W01·W02 15개 경로·Method·응답 예시의 MD·엑셀 일치 및 의존성 33개 버전 고정 확인.
- MySQL 동시성 6개 테스트는 별도 테스트 DB 미설정으로 skip. 기존 4개에 동일 신청 승인/거절 경합·동일 계정의 서로 다른 지점 동시 승인 2개를 추가했다. 이전 확인 시 로컬 MySQL 9.2 실행 파일은 `libabsl_bad_optional_access.2407.0.0.dylib` 누락으로 실행되지 않았다. 시스템 라이브러리·기존 DB를 임의 변경하지 않았다.
- 실제 Redis Lua 실행·SMTP 전달·MFA·기존 서버 회귀·운영 앱 연결은 미검증. SQLite 테스트를 MySQL 행 잠금 검증으로 대체하지 않는다.
- W09 작업은 `app.jobs`의 정비 만료·승인 후 3일 결제 기한 알림·미결제 예약 만료·일별 재고 upsert로 구현했으며, 운영 cron/systemd 등록과 실제 MySQL 실행은 미검증이다.
- Starlette/httpx·anyio 관련 의존 라이브러리 deprecation 경고 2개가 있으며 기능 테스트 실패는 아니다. 검증한 버전은 `requirements.lock`에 고정했다.

MySQL 테스트는 빈 전용 DB에만 실행한다. 아래 환경 변수는 운영 URL과 별개이며 DB 이름이 `nadree_w02_test_`로 시작하지 않거나 기존 테이블이 있으면 거절한다. 테스트가 생성한 테이블은 종료 시 정리된다.

```sh
# Secret manager/environment: NADREE_TEST_MYSQL_URL points to an empty disposable test database.
.venv/bin/python -m pytest -m mysql -q
```

`/health/live`는 프로세스 실행만 의미한다. `/health/ready`는 신청 테이블을 포함한 DB·기본 스키마·역할·JWT·Redis·SMTP 설정을 검사하고 알려진 제한을 `limitations`에 표시한다. ready가 성공해도 최초 가입 접수·앱 연동이나 MFA까지 완료됐다는 뜻은 아니다.

## 참조

- [FastAPI dependency 종료 시점](https://fastapi.tiangolo.com/advanced/advanced-dependencies/): 응답 전 트랜잭션 종료에 `scope="function"` 사용.
- [SQLAlchemy Session](https://docs.sqlalchemy.org/en/20/orm/session_basics.html): 트랜잭션 경계.
- [MySQL 격리 수준](https://dev.mysql.com/doc/refman/8.4/en/innodb-transaction-isolation-levels.html), [named lock](https://dev.mysql.com/doc/refman/8.4/en/locking-functions.html): DB 동시성 구현 근거.

업무 입력·응답 정본은 상위 MD·엑셀이며 이 문서는 새 서버의 구현 상태와 제약을 기록한다. W03 이후 기능을 이번에 구현한 것으로 표시하지 않는다.
