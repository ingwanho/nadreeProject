# 최종 변경 — 회원가입·회원정보의 개인정보처리방침/이용약관 동의

**2026-11-25 사용자 최종 정정에 따른 로컬 변경이며 서버 미적용이다.** 앞서 배포한 인계 단위 동의 방식을 회원 단위로 변경한다. 인계용 저장 API를 중단하고 인계의 두 컬럼도 삭제한다. 기존 기록의 실제 동의 시각을 회원정보로 이관한 뒤 삭제하도록 마이그레이션을 준비했다.

## 저장·조회 기준

| 회원정보 컬럼 | 응답 필드 | 의미 |
| --- | --- | --- |
| `MSP_RENTAL_USER.privacy_policy_agreed_at` | `user.privacyPolicyAgreedAt` | 회원의 개인정보처리방침 최초 동의 시각 |
| `MSP_RENTAL_USER.terms_agreed_at` | `user.termsAgreedAt` | 회원의 이용약관 최초 동의 시각 |

둘 다 nullable DATETIME이며 미기록은 `null`이다. 서버 UTC·초 단위로 저장하고, 동의한 항목의 최초 시각을 재요청으로 덮어쓰지 않는다. 생략한 항목은 유지한다. 사용자가 시각을 지정하거나 `false`로 철회하는 API는 추가하지 않는다.

신규 가입/기존 회원에게 두 항목을 함께 또는 따로 저장할 수 있다. 기존 가입 흐름의 호환을 위해 두 필드 자체는 선택 입력이며, 보내지 않았다고 자동 동의 처리하지 않는다. 기존 렌트의 폼·영상·서명·시작 조건은 유지한다. 회원 탈퇴 시 두 시각도 여권번호 등 회원정보와 함께 비우며 재가입 시 자동 복원하지 않는다.

## 회원가입·로그인 API

관광객 회원은 Firebase 인증 후 기존 **POST `/api/v1/nadree/user/login`**의 최초 로그인에서 생성된다. 별도 회원가입 API를 만들지 않는다.

```http
POST /api/v1/nadree/user/login
Authorization: Bearer <Firebase ID token>
Content-Type: application/json
```

```json
{
  "UID": "FIREBASE_CUSTOMER_UID",
  "privacyPolicyAgreed": true,
  "termsAgreed": true
}
```

UID와 Firebase 인증이 일치하고 로그인 검증이 성공했을 때만 기록한다. 기존 `fcmToken`도 함께 보낼 수 있다. 고객이 실제 체크한 항목만 명시적인 JSON `true`로 보낸다. `false`, `null`, 문자열·숫자 불리언은 422다.

로그인 응답의 기존 `user`에 `privacyPolicyAgreedAt`, `termsAgreedAt`를 추가했다. 반복 로그인에서 필드를 생략하거나 이미 동의한 항목을 다시 true로 보내도 최초 시각을 유지한다. 토큰/기존 계정 생성·재인증 정책은 그대로다.

## 여권·면허번호와 같은 프로필 수정

**PATCH `/api/v1/nadree/user/profile`**에 고객 로그인으로 발급받은 **Nadree 고객 access token**을 사용한다. 여권·면허번호와 두 동의를 함께 저장하거나 동의만 전송할 수 있다.

```http
PATCH /api/v1/nadree/user/profile
Authorization: Bearer <Nadree customer access token>
Content-Type: application/json
```

```json
{
  "passportNumber": "TEST-PASSPORT",
  "driverLicenseNumber": "TEST-LICENSE",
  "privacyPolicyAgreed": true,
  "termsAgreed": true
}
```

개인정보처리방침만 먼저 기록하려면 `{"privacyPolicyAgreed":true}`, 이후 약관은 `{"termsAgreed":true}`로 각각 호출한다. 서버는 두 시각을 각각 보존한다. 여권·면허번호는 기존 암호화 방식과 업데이트 계약을 사용한다. 하나의 프로필 수정에서 오류가 나면 동의만 따로 커밋하지 않는다.

인증한 본인의 회원정보만 변경한다. 프로필 본문에 다른 UID나 `privacyPolicyAgreedAt`·`termsAgreedAt` 같은 시각을 보내면 422다. 관리자 토큰으로 대신 수정할 수 없다.

**GET `/api/v1/nadree/user/profile`**과 로그인·프로필 수정 응답의 `user`에서 조회한다. 다음은 새 응답 필드만 발췌한 가상 예시다.

```json
{
  "privacyPolicyAgreedAt": "2026-11-25T04:00:00Z",
  "termsAgreedAt": "2026-11-25T04:00:05Z"
}
```

화면은 UTC를 원하는 표시 시간대로 변환한다. NULL은 시각 미기록이며, 과거의 거부 이력으로 단정하지 않는다. 인계별로 다시 저장하거나 인계 ID를 요구하지 않는다.

## 중단·삭제하는 기존 계약

- **POST `/api/v1/nadree/rental/handovers/{handover_id}/consents`를 라우트와 Swagger에서 제거한다.** 새 배포 후에는 404이며 회원가입·프로필 API로 변경해야 한다.
- 인계 상세·목록·예약/렌트의 handover 진행 정보에서 `privacyPolicyAgreedAt`·`termsAgreedAt`를 제거한다. 회원 프로필의 `user` 필드를 조회한다.
- 인계의 `privacy_policy_agreed_at`·`terms_agreed_at` 컬럼을 이관 후 삭제한다. 기존 `signatureStatus`·`signatureCompletedAt`·행위자/인계 ID는 유지한다.
- 동의 원문·약관 버전·새 테이블·새 요청 ID는 추가하지 않는다.

신규 계약은 로컬 **105경로/111메서드(health 포함)**다. 기존 서버 보고의 106경로/112메서드·인계37컬럼은 이번 변경 이전 상태다. 새 서버 적용 후 회원15컬럼·인계35컬럼이 된다.

## 기존 데이터 이관과 서버 적용

기존 인계에 명시적으로 기록된 두 동의 시각만 이관한다. 고객별 각 항목의 가장 이른 시각과 기존 회원 시각 중 이른 값을 회원정보에 보존한다. 서명·생성 시각으로 동의를 추정하지 않는다. 기존 인계 행·서명·다른 업무 필드는 삭제하지 않는다.

마이그레이션은 다음 순서다.

1. 회원 테이블에 nullable DATETIME 2컬럼을 추가한다.
2. 고객별 각 항목의 최초 실제 동의 시각을 회원정보에 복사한다.
3. 원본의 모든 동의 시각이 대응 회원의 같은 항목에 보존됐는지 확인한 뒤 해당 인계 컬럼을 삭제한다.

원본 동의에 대응 회원이 없으면 계획 단계에서 중단한다. 이관이 누락됐거나 회원의 시각이 원본보다 늦으면 실행 단계에서 원본 컬럼 삭제를 거부한다. 중간에 일부 항목만 완료돼도 다시 계획해 나머지를 진행할 수 있다. MySQL DDL 전체 롤백을 보장하는 것은 아니므로 부분 적용 상태를 확인한다.

서버는 반드시 **DB 전체·회원/인계의 기존 두 시각·업무 행 수를 비공개 백업하고 API 쓰기를 중지한 상태**에서 이관/삭제한다. 실제 DB를 확인한 뒤 실행한다. 현재 승인된 테스트 DB가 `RIDERLOG_V2_DATA_TEST`인 경우의 예시다.

```bash
cd /srv/nadree-api
git status --short
git pull --ff-only origin main
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
```

기존 서버가 회원13컬럼·인계37컬럼이면 이번 계획은 추가 2개·이관 2개·삭제 2개가 나온다. 다른 미적용 항목이 있으면 먼저 대조한다. 백업과 계획 확인 후:

```bash
sudo systemctl stop nadree-api
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST'
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
sudo systemctl start nadree-api
sudo systemctl status nadree-api --no-pager
```

`app.migrate`의 이관·검증 순서를 사용하고 시각화 SQL·수동 DROP·`create_all`로 대체하지 않는다. env·암호화 키·Firebase·S3·타이머 설정 변경은 없다. 이관 후 구 코드를 단순 재시작하면 이미 삭제한 인계 컬럼을 참조하므로, 실패 시 새 쓰기를 중지하고 스키마/이관 상태를 확인해 현재 계약에 맞춰 복구한다. 동의 데이터를 임의 초기화하지 않는다.

## 프론트와 서버 확인

서버 적용 전 기존 API는 새 로그인/프로필 필드를 모를 수 있다. 새 계약의 Swagger를 확인한 뒤 앱 입력을 전환하고 기존 인계용 동의 호출을 제거한다.

- 가입/로그인에서 동의 저장·반복 로그인·동의 필드 생략 후 최초 시각 유지.
- 프로필에서 여권/면허번호와 동의 동시 저장, 동의 하나씩 저장, GET으로 상태 복구.
- false/null/문자열/숫자/클라이언트 시각·다른 UID 거절, 관리자·무인증 차단.
- 기존 고객의 실제 동의 이관값과 NULL 유지, 인계 두 컬럼 삭제·기존 행/서명/업무 보존.
- 구 인계용 POST가 404이고, handover 응답에는 두 필드가 없는지 확인.
- 회원 탈퇴 후 두 시각 제거, 재가입 시 이전 동의를 자동 복원하지 않는지 확인.

이번 작업은 로컬 구현·격리 검증이며 실제 서버의 데이터 이관·컬럼 삭제·재시작을 실행하지 않았다. 11월25일의 인계용 동의 서버 검증 보고는 이전 계약의 이력으로 보존한다.

## 이번 로컬 검증

회원 동의·이관·인증·기존 인계·명세·스키마·기반 API 관련 **89 passed**, 전체 회귀 **979 passed / 23 skipped / 14 warnings**다. 별도 환경의 MySQL/Firestore/S3 실행 조건 23건은 이번에 실제 실행한 것으로 표시하지 않는다. 로그인/프로필 저장·재요청 불변·엄격한 입력·탈퇴/재가입·구 API 제거와 SQLite 이관의 최초 값/원본 보존·삭제 차단·부분 완료 후 재개·대상 회원 누락 차단을 확인했다. MySQL에서의 실제 이관/컬럼 삭제와 동시 가입/프로필 경합은 서버 적용 때 추가 검증한다. API 엑셀은 현재 OpenAPI **111메서드·197개 JSON 예시**와 대조했다. 회원15컬럼·인계35컬럼을 DB 엑셀/시각화 SQL 3개에 반영했고, 기존 토큰 폐기 기준 컬럼의 명세 누락도 실제 기존 코드대로 보완했다.
