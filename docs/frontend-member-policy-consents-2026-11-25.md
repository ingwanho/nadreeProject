# 프론트 전달 — 회원가입·프로필의 개인정보처리방침/이용약관 동의

> **2026-11-26 번호 처리 후속 변경·서버 적용 완료:** 프로필 두 번호의 명시적 삭제 표현을 JSON null로 확정·배포했다. `driverLicenseNumber`는 국제운전면허 번호이며 동의 버전 관리는 이후 추가한다. 서버 격리67개·실제 HTTP63개 기록의 기대 결과 충족과 기존 동의 시각/인계 기록 보존을 확인했다. [서버 결과 포함 번호 처리 전달 문서](frontend-profile-numbers-handoff-2026-11-26.md)를 함께 따른다. 아래 11월25일 동의 시각 기능의 서버 적용 근거와 구분한다.

**2026-11-25 서버 반영 완료.** 고객 앱은 회원가입·로그인과 프로필에서 두 동의를 저장하고 조회할 수 있다. 이전 인계용 동의 API와 인계 응답의 동의 필드는 제거했으므로 아래 계약으로 연동한다.

공개 API는 `https://na-dree.com`이며 [Swagger](https://na-dree.com/docs)와 [OpenAPI](https://na-dree.com/openapi.json)에 반영됐다. 이 문서는 [회원 동의 서버 적용 결과](member-policy-consents-server-verification-2026-11-25.md)를 기준으로 작성했다. 적용 코드는 `4a8ba54`와 이관 순서 보완이며, 해당 소스·결과가 저장소의 `18870c2`에 반영됐다. 서버 최종 확인 시각은 **2026-11-25 10:23:54 UTC / 한국 19:23:54 / 발리 18:23:54**다. 문서 작성 과정에서 서버를 다시 배포하거나 새 업무 요청을 실행하지 않았다.

## 1. 저장 위치와 동작

| 동의 항목 | 요청 필드 | 회원 응답 필드 | 회원 테이블 컬럼 |
| --- | --- | --- | --- |
| 개인정보처리방침 | `privacyPolicyAgreed` | `user.privacyPolicyAgreedAt` | `MSP_RENTAL_USER.privacy_policy_agreed_at` |
| 이용약관 | `termsAgreed` | `user.termsAgreedAt` | `MSP_RENTAL_USER.terms_agreed_at` |

- 두 컬럼 모두 추가·적용됐으며, 인계 ID 없이 회원 단위로 저장한다.
- 고객이 실제 동의한 항목만 JSON 불리언 `true`로 보낸다. 두 항목을 함께 또는 따로 보낼 수 있다.
- 서버가 각 항목의 **최초 동의 시각**을 UTC 초 단위로 기록한다. 같은 항목을 다시 보내도 최초 시각을 유지한다.
- 필드를 생략하면 기존 값을 유지하며, 기존 값이 없으면 `null`로 남는다. 생략을 동의로 처리하지 않는다.
- 호환을 위해 두 요청 필드는 선택 입력이다. 이번 변경으로 가입·렌트에 새로운 필수 동의 검사를 추가하지 않았다.
- 클라이언트가 동의 시각을 지정하거나 `false`로 철회하는 기능은 없다. 회원 탈퇴 시 두 값도 초기화하며 재가입 시 자동 복원하지 않는다.

## 2. 회원가입·로그인에서 저장

관광객 회원가입은 Firebase 인증 후 아래 API에 **최초 로그인할 때 회원을 생성하는 기존 방식**이다. 별도 회원가입 API는 없다.

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

본문 `UID`는 Firebase 토큰의 UID와 일치해야 한다. 기존 `fcmToken`도 함께 보낼 수 있다. Firebase 인증과 로그인 검증에 성공한 경우에만 동의를 기록한다. 기존 회원의 로그인에도 같은 필드를 사용할 수 있다.

응답의 기존 `accessToken`, `refreshToken`, `isNewUser`, `user` 구조는 유지하며, `user`에 두 시각이 포함된다. 이후 프로필 API에는 이 로그인에서 받은 **Nadree 고객 access token**을 사용한다.

여권·운전면허번호는 기존 프로필 수정 API에서 저장한다. 로그인 본문에 두 문서번호를 새로 추가한 것은 아니다. 가입 화면에서 함께 입력받는다면 로그인 후 아래 프로필 API로 저장한다.

## 3. 프로필에서 저장·조회

```http
PATCH /api/v1/nadree/user/profile
Authorization: Bearer <Nadree customer access token>
Content-Type: application/json
```

동의만 저장하는 예시:

```json
{
  "privacyPolicyAgreed": true,
  "termsAgreed": true
}
```

기존 여권·운전면허번호와 함께 저장하는 예시:

```json
{
  "passportNumber": "TEST-PASSPORT",
  "driverLicenseNumber": "TEST-LICENSE",
  "privacyPolicyAgreed": true,
  "termsAgreed": true
}
```

한 항목만 저장하려면 `{"privacyPolicyAgreed": true}` 또는 `{"termsAgreed": true}`로 호출한다. 해당 회원 본인의 정보만 수정할 수 있으며 관리자 토큰으로 대신 저장할 수 없다.

조회는 **GET `/api/v1/nadree/user/profile`**에 같은 고객 access token을 사용한다. 로그인·프로필 수정·프로필 조회 응답 모두 `user`에서 확인한다. 다음은 추가 필드만 발췌한 가상 응답이며, 나머지 기존 필드도 반환된다.

```json
{
  "status": "success",
  "user": {
    "privacyPolicyAgreedAt": "2026-11-25T10:30:00Z",
    "termsAgreedAt": "2026-11-25T10:30:05Z"
  }
}
```

미기록 항목은 `null`이다. UTC 시각을 화면의 표시 시간대로 변환하고, 앱 재실행 시 프로필을 조회해 상태를 복원한다. 기존 데이터의 `null`을 명시적인 동의 거부 이력으로 단정하지 않는다.

## 4. 제거된 인계용 동의 연동

| 이전 연동 | 변경 후 |
| --- | --- |
| POST `/api/v1/nadree/rental/handovers/{handover_id}/consents` | 라우트·Swagger에서 제거, 실제 서버 **404** 확인 |
| 인계 상세·목록·예약/렌트의 `handover` 내부 동의 시각 | 두 필드 제거, 회원 프로필의 `user`에서 조회 |
| 인계 테이블의 동의 컬럼 2개 | 실제 기록을 회원정보로 이관·검증한 뒤 삭제 완료 |

기존 인계의 `signatureStatus`, `signatureCompletedAt`와 서명 완료 API는 유지한다. 회원 동의를 저장했다고 인계 서명·영상이 자동 완료되거나 렌트 시작 조건이 충족되는 것은 아니다. 회원 동의와 인계 서명 진행 상태는 각각 기존 흐름에 맞춰 처리한다.

## 5. 입력 오류와 인증 확인

| 조건 | 응답 |
| --- | --- |
| 동의 필드에 `false`, `null`, 문자열, 숫자 전송 | 422 `INVALID_INPUT` |
| 클라이언트가 동의 시각 필드를 전송하거나 프로필에 UID 전송 | 422 `INVALID_INPUT` |
| 빈 객체로 프로필 수정 | 422 `EMPTY_PROFILE_UPDATE` |
| 로그인 UID와 Firebase 토큰 UID 불일치 | 401 `FIREBASE_UID_MISMATCH` |
| 로그인 시 Firebase ID token 누락 | 401 `FIREBASE_ID_TOKEN_REQUIRED` |
| 프로필에 관리자 토큰 또는 무인증 요청 | 401 `INVALID_NADRI_USER_TOKEN` |

체크하지 않은 항목을 `false`나 `null`로 직렬화하지 말고 요청에서 생략한다. API 요청에 토큰 원문이나 개인정보를 로그로 남기지 않는다.

## 6. 서버 적용·검증 결과

2026-11-25 서버 보고 기준으로 다음을 완료했다.

- DB 전체 백업 후 회원 동의 컬럼 2개 추가 → 두 항목의 실제 최초 시각 이관 → 보존 검증 → 인계 동의 컬럼 2개 삭제. 재계획은 **잔여 0개**다.
- 기존 인계 11행 중 실제 동의가 있던 각 2행을 같은 고객의 항목별 최초 시각으로 이관했다. 회원 28명 중 1명에 기록됐고 나머지 27명은 두 값이 `null`로 유지됐다.
- 회원·인계·예약·계약·결제 행 수와 기존 인계 서명·다른 업무 데이터는 보존됐다. 이관 회원 1명의 `updated_at`만 DB 자동 갱신됐다.
- 회원 **15컬럼**, 인계 **35컬럼**, Swagger **105경로·111메서드**를 확인했다. API 재시작 후 로컬·공개 상태/명세 8회 조회가 모두 200이었다.
- 관련 **격리 검사 91개 통과**. 별도 MySQL 이관·동시 로그인/프로필 저장 검사도 포함한다.
- 실제 API **41개 HTTP 검사 기록**이 기대 결과를 충족했다. 기존 고객의 로그인·프로필 저장/조회·재요청 시 최초 시각 유지, 잘못된 입력·인증 차단, 구 인계 API 404와 응답 필드 제거를 확인했다. 오류 응답도 의도한 검증 결과이며 41개가 모두 성공 HTTP라는 뜻은 아니다.
- env·암호화 키·Firebase·S3 설정 변경은 없다.

실제 HTTP 시험 고객은 이미 동의가 이관된 기존 고객이었다. **실제 신규 가입 또는 두 값이 NULL인 회원의 최초 저장은 아직 시험하지 않았고, 해당 동작은 격리 테스트로 확인했다.** 실제 회원 탈퇴/재가입·문서번호와 동의 동시 수정, 앱 화면·App Check·실기기 푸시와 새 동의 후 전체 렌트 흐름도 별도 확인 대상이다.

## 7. 프론트 적용·테스트 순서

1. 기존 인계용 `consents` 호출과 `handover` 내부 두 시각 참조를 제거한다.
2. 가입 화면에서 실제 체크한 항목을 로그인 API의 `true` 필드로 보낸다. 기존 회원의 추가 동의는 프로필 PATCH를 사용한다.
3. 로그인/PATCH 응답과 GET 프로필의 `user`에서 두 시각을 확인한다. 재전송·재로그인 이후에도 최초 시각이 유지되는지 확인한다.
4. 승인된 별도 신규/NULL 동의 테스트 고객으로 최초 저장을 확인한다. 기존 고객의 이관된 동의 시각을 지워서 시험하지 않는다.
5. 무인증·관리자 토큰·잘못된 값 전송이 위 오류로 차단되는지 확인한다. 토큰 종류가 다른 로그인과 프로필 요청을 구분한다.
6. 기존 인계 폼·영상·서명·렌트 시작 화면이 회원 동의 변경 후에도 기존 절차대로 진행되는지 확인한다.

세부 구현·이관 규칙은 [회원 정책 동의 계약](member-policy-consents-2026-11-25.md), 실제 실행 근거와 미검증 전체 목록은 [서버 적용 결과](member-policy-consents-server-verification-2026-11-25.md)를 따른다.
