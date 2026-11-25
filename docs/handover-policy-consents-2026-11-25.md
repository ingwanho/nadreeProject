# 인계별 개인정보처리방침·이용약관 동의 시각

> 2026-11-25 서버 적용 완료: nullable 2컬럼·기존 7건 NULL 보존·API 재시작, 관련 격리 68개·실제 HTTP 50개를 확인했다. [실제 적용·검증 결과](handover-policy-consents-server-verification-2026-11-25.md). 아래 서버 미적용 표기는 최초 로컬 전달 당시 이력이다.

2026-11-25 사용자 요청을 로컬 코드·Swagger·마이그레이션에 반영했다. **이번 추가는 서버 미적용**이며, 11월 24일 서버 적용 완료 보고와 구분한다. 프로필이나 별도 테이블에 복제하지 않고 `MSP_RENTAL_HANDOVER`에 저장한다.

## 저장 항목

| DB 컬럼 | 응답 필드 | 의미 |
| --- | --- | --- |
| `privacy_policy_agreed_at` DATETIME NULL | `privacyPolicyAgreedAt` | 해당 인계의 개인정보처리방침 최초 동의 시각 |
| `terms_agreed_at` DATETIME NULL | `termsAgreedAt` | 해당 인계의 이용약관 최초 동의 시각 |

동의하지 않았거나 기록이 없는 값은 `null`이다. 두 컬럼을 추가해 인계 테이블은 35→37컬럼이 된다. 시각은 서버 UTC·초 단위로 저장하며 고객이 시각을 지정할 수 없다. 행의 `uid_token`이 동의한 고객이고 `handover_id`가 동의 대상이다. 기존 행은 NULL로 유지하며 서명 시각이나 생성 시각으로 추정해 채우지 않는다.

기존 `signatureStatus`·`signatureCompletedAt`는 인계 동의/서명 단계의 완료 기록으로 유지한다. 새 API가 서명·영상·고객 상태를 완료 처리하지 않는다. 이번 추가로 렌트 시작의 필수 조건을 늘리지 않으며, 별도 동의 철회·약관 버전·원문 저장 기능은 추가하지 않는다.

## 저장 API

**POST `/api/v1/nadree/rental/handovers/{handover_id}/consents`**

- 인증: 고객 로그인으로 발급받은 Nadree 고객 access token. 관리자 토큰으로 대신 저장할 수 없다.
- 대상: 본인의 인계를 실제로 시작한 후, 렌트 시작/인계 취소 전. 폼·영상 완료 전에도 기록할 수 있다.
- 요청: 아래 두 필드 중 하나 이상을 명시적인 JSON `true`로 전달한다. 두 개를 함께 보내거나 따로 호출할 수 있다. 생략한 필드는 변경하지 않는다.
- 거절: 빈 본문, `false`, `null`, 숫자·문자열 불리언, 고객 지정 동의 시각·UID 등 정의되지 않은 필드는 422다. 미동의 항목은 보내지 않는다.

```http
POST /api/v1/nadree/rental/handovers/{handover_id}/consents
Authorization: Bearer <Nadree customer access token>
Content-Type: application/json
```

```json
{
  "privacyPolicyAgreed": true,
  "termsAgreed": true
}
```

각각 동의한다면 먼저 `{"privacyPolicyAgreed":true}`, 나중에 `{"termsAgreed":true}`를 보낸다. 처음 두 항목을 함께 저장하면 같은 서버 시각을 쓴다. 이미 기록된 항목을 다시 보내도 최초 시각을 덮어쓰지 않는다. 같은 인계의 지점·예약·인계 잠금 아래 다시 읽고 쓰므로 경합 요청도 기존 잠금 순서를 따른다. 별도 요청 ID는 필요하지 않다.

성공은 기존 `HandoverResult` 전체 형식인 HTTP 200, `status:"success"`, `item`을 반환한다. 다음은 추가 필드만 발췌한 예시다.

```json
{
  "privacyPolicyAgreedAt": "2026-11-25T04:00:00Z",
  "termsAgreedAt": "2026-11-25T04:00:00Z"
}
```

하나만 동의하면 다른 필드는 NULL을 유지한다. 최초 기록 후 정상 재요청은 값을 유지하고 추가 알림을 보내지 않는다. 이미 렌트를 시작했거나 인계를 취소했다면 쓰기 재요청도 409이며 상세 조회로 저장 결과를 확인한다.

조회 위치:

- 고객/관리자 인계 상세와 관리자 인계 목록의 진행 정보에 두 필드를 반환한다.
- 고객 예약·렌트 상세의 `item.handover.privacyPolicyAgreedAt`, `item.handover.termsAgreedAt`에서도 확인한다. 관리자 예약 상세도 기존 handover 진행 정보에 포함한다.
- 고객 프로필 API에는 추가하지 않는다. 인계를 새로 시작하거나 거부 후 새 인계를 생성하면 새 행의 동의 시각은 다시 NULL이다.

| HTTP | errorCode | 처리 |
| --- | --- | --- |
| 401 | 기존 고객 인증 오류 | 고객 로그인/토큰 확인 |
| 404 | `HANDOVER_REQUIRED` | 미존재 또는 타 고객 인계. 객체 존재를 추정하지 않음 |
| 409 | `HANDOVER_CLOSED` | 미시작·취소·렌트 시작·예약 만료 등으로 쓰기 불가. 최신 상세 재조회 |
| 422 | `INVALID_INPUT` | 하나 이상의 true 불리언만 전달 |
| 503 | `HANDOVER_SCHEMA_UPDATE_REQUIRED` | DB 마이그레이션 적용 확인 |

새 오류 코드는 추가하지 않고 기존 오류 계약을 사용한다. 예시의 날짜·ID·토큰 자리표시자는 실제 테스트 계정 정보가 아니다.

## 서버 적용

환경 변수·암호화 키·S3·Firebase·Rules·인덱스·타이머 변경은 없다. 기존 키를 유지한다. 서버에서는 실제 대상 DB와 백업을 확인하고, 이번 신규 계획에 위 nullable 2컬럼이 나오는지 검토한다. 다른 미적용 변경이 함께 나오면 먼저 내용을 확인한다.

```bash
cd /srv/nadree-api
git pull --ff-only origin main
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
```

다음은 기존 승인된 테스트 DB 기준이다. 다른 DB 이름에는 그대로 실행하지 않는다. 공유 DB에 시각화 SQL이나 `create_all`은 실행하지 않는다.

```bash
sudo systemctl stop nadree-api
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST'
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
sudo systemctl start nadree-api
sudo systemctl status nadree-api --no-pager
```

재계획 0개·health/ready·Swagger를 확인한다. 적용 후 명세는 **106경로/112메서드(health 포함)**다. 승인된 테스트 고객으로 새 인계 시작 → 한 항목 저장 → 나머지 저장 → 같은 요청 재전달 → 고객/관리자/예약 상세 조회를 확인한다. 최초 시각 불변, 관리자/다른 고객 차단, 미시작/취소/렌트 시작 후 409도 확인한다. 기존 인계의 NULL을 일괄 채우지 않는다.

이번 작업에서 서버 마이그레이션·재시작·실제 업무 검증은 실행하지 않았다. 기존 서버 보고의 979개 격리/108개 업무 기록은 11월 24일 코드의 증거이며 이번 새 API의 배포 근거가 아니다.

## 로컬 검증

관련 인계·동의·Swagger·마이그레이션·기반 API 검사 **67 passed**, 최종 전체 회귀 **971 passed / 23 skipped / 14 warnings**다. 최초 서버 시각·각각 저장·중복 불변·상세 조회·오입력/권한/닫힌 인계 차단과 기존 행 NULL 보존을 격리 SQL/API에서 확인했다. 기존 시작 검사는 그대로 통과한다. API 엑셀 **112메서드·199개 JSON 예시**를 현재 OpenAPI와 대조했으며, DB 명세·시각화 SQL 3개는 인계37컬럼을 기준으로 맞췄다. 실제 서버 DB·앱 공동 연동과 새 API의 MySQL 경합은 이번 로컬 통과와 구분해 검증한다.
