# Nadree DB 변경 안내

DB 계획 v2.24는 지점 소개·연락 이메일 2컬럼과 기존 관리자 phone VARCHAR(200) 확장을 포함한다. 고객 refresh token 테이블을 포함한 전체 렌탈 계획은 18개 업무 테이블이며, 이 폴더는 승인된 공통 변경과 결제 환불·고객 인증에 필요한 부분을 다룬다. 알림 큐 테이블은 현재 제외하고, 새 Firebase 프로젝트 연결 후 별도로 설계한다.

| 순서 | 변경 | 조건 |
| --- | --- | --- |
| 1 | `MSP_ADMIN.fcm_token VARCHAR(512) NULL` | 없을 때 추가 |
| 2 | `MSP_ADMIN.fcm_token_updated_at DATETIME NULL` | 없을 때 추가 |
| 3 | `MSP_ADMIN.fcm_token` 인덱스 | 동일 컬럼 인덱스가 없을 때 추가 |
| 4 | `MSP_SPOT_RENT` | 없을 때 기존 001 SQL의 6컬럼 생성 후 아래 소개·연락 이메일 2컬럼을 추가하여 최종 8컬럼. 물리 FK를 임의 추가하지 않음 |
| 5 | `MSP_RENTAL_ADMIN_REQUEST` | 없을 때 [002_rental_admin_request.sql](002_rental_admin_request.sql)의 8컬럼·중복/상태 제약 생성. 이미 있으면 필수 컬럼·지점별 이메일/계정 유일성 확인 |
| 6 | `MSP_ROLE` 대표/일반 코드 2행 | 없을 때만 삽입, 비활성 역할을 임의 재활성화하지 않음 |
| 7 | `MSP_SPOT_RENT.introduction VARCHAR(500) NULL` | 없을 때 추가, 기존 행은 NULL. 이미 있으면 타입·길이 검사 |
| 8 | `MSP_SPOT_RENT.contact_email VARCHAR(200) NULL` | 없을 때 추가, 기존 행은 NULL. 관리자 개인 이메일과 별개 |
| 9 | `MSP_ADMIN.phone VARCHAR(200)` | 기존 VARCHAR 길이가 200 미만일 때만 확장. 200 이상이면 축소하지 않음 |
| 10 | 렌탈 사용자 분리 | [003_rental_user_uid_token.sql](003_rental_user_uid_token.sql)로 MSP_RENTAL_USER를 MSP_DRIVER와 분리하고 렌탈 참조를 uid_token으로 전환 |
| 11 | PayPal 환불 상태 | [004_payment_refund.sql](004_payment_refund.sql)로 결제 행에 환불 요청·환불 ID·환불 상태를 저장 |
| 13 | 나드리 로그아웃 토큰 폐기 시각 | [006_rental_user_logout.sql](006_rental_user_logout.sql)로 고객 access token 폐기 시각을 저장. FCM 토큰은 보존 |
| 14 | 나드리 고객 refresh token | [008_rental_user_refresh_token.sql](008_rental_user_refresh_token.sql)로 관리자 토큰과 분리된 고객 세션을 저장. UID별 활성 토큰은 1개이며 로그인·갱신 시 이전 토큰을 폐기 |

기존 001·002 SQL은 수정하지 않는다. `app.migrate`가 신규 생성/이미 생성된 DB 모두를 검사하여 필요한 ALTER만 실행 계획에 추가한다. 소개·이메일 중 하나만 존재해도 나머지만 추가한다. 기존 phone의 NULL 여부·문자셋·collation·설명은 SQLAlchemy MySQL DDL 생성으로 유지하며, 특수 기본값/생성 컬럼 또는 예상과 다른 타입은 수동 검토를 요구한다. 기존 데이터 변환·재암호화·평문 저장은 하지 않는다. 실제 MySQL에서의 적용/재적용은 별도 검증한다.

기존 DB에 `MSP_RENTAL_NOTIFICATION`이 이미 생성되어 있다면 이 계획은 자동 삭제하지 않는다. 백업과 사용 여부를 확인한 뒤 DB 담당자가 별도 `DROP TABLE` 절차로 제거해야 한다.


`MSP_RENTAL_USER`가 이미 있는 DB에는 `008_rental_user_refresh_token.sql`을 적용해 고객 세션 테이블을 추가한다. 기존 관리자 `MSP_REFRESH_TOKEN`이나 `MSP_DRIVER` 관련 테이블은 변경하지 않는다.

실행 순서는 도구가 출력하는 계획을 따른다. 사용자 계정의 역할·소속·MFA·초대 코드는 이 마이그레이션에서 변경하지 않는다. 기존 지점 전체에 렌탈 행이나 과거 계정의 신청을 자동 생성하지 않는다. 비밀번호 링크 저장용 테이블은 추가하지 않는다.

신청 테이블은 기존 MSP_ADMIN 계정을 admin_id로 참조하며, 이메일은 가입 접수 서버가 본인 확인 후 casefold 정규화하여 저장해야 한다. 최초 신청 접수 API·계정 생성 경로는 별도 연동 대상이다. 완료된 신청 행을 삭제하거나 REQUESTED로 재설정하지 않는다. 현재 email/action 계약에서 재신청·복수 이력은 후속 설계 대상이다. 상세는 [DB 계획](../../rental-project-master.md#db-msp_rental_admin_request)을 참조한다.

## 계획 확인

```sh
.venv/bin/python -m app.migrate
```

명시적으로 설정한 `NADREE_DATABASE_URL`만 읽는다. 기본값은 읽기 전용이다. 기존 업무 테이블·필수 컬럼이 없거나 알려진 충돌이 있으면 중단한다. 이는 모든 인덱스·제약·기존 데이터 호환성을 증명하는 검사는 아니므로 실제 `SHOW CREATE TABLE`과 선행 마이그레이션을 별도 검토한다.

## 승인 후 적용

백업·스테이징 테스트·공유 DB 담당자 승인을 받은 뒤에만 아래 명령을 실행한다. `DATABASE_NAME`은 설정한 실제 DB 이름과 같아야 한다. **이번 작업에서는 실행하지 않았다.**

```sh
.venv/bin/python -m app.migrate --apply --confirm-database DATABASE_NAME
.venv/bin/python -m app.migrate
```

- migration named lock으로 이 도구끼리의 동시 적용을 제한한다. 기존 배포 도구도 적용 주체를 하나로 조율해야 한다.
- MySQL DDL은 암묵적 COMMIT을 발생시킬 수 있으므로 전체 롤백을 보장하지 않는다. 실패하면 실제 적용된 스키마를 확인한 뒤 다시 계획을 조회한다.
- 재조회 결과 pending 없음과 실제 스키마·역할 상태를 확인한다. 현재 로컬에서는 MySQL 적용/재적용을 검증하지 못했다.
- 기존 데이터·테이블·컬럼을 자동 삭제하는 down migration은 제공하지 않는다. 복구는 백업 및 변경별 검증으로 진행한다.
- 스키마 변경 후에는 반영된 스키마를 읽도록 새 API 프로세스를 재시작한다.

## 배포 전 확인

`MSP_ADMIN.primary_spot_master_id`, 기존 역할·scope·refresh 테이블, 정규 조직 테이블, 계약 상태·기간이 실제 DB와 맞아야 한다. `unit_name`은 있는 경우에만 함께 기록한다.

관리자 phone은 저장용 200자이고 API 원문 입력 상한은 기존 20자다. 호환되는 `NADREE_FIELD_ENCRYPT_KEY` 설정이 필요하며 암호문이 저장 길이를 넘으면 잘라 저장하지 않고 거절한다. 샵 introduction/contact_email은 이번 계획에 추가했으므로 업무 API 사용 전 실제 DB 적용 여부를 확인한다.

ERDCloud SQL 전체를 운영 DB에 실행하지 않는다. `metadata.create_all/drop_all`은 `tests/`의 격리된 테스트에만 있으며 애플리케이션 시작 시 실행되지 않는다.
