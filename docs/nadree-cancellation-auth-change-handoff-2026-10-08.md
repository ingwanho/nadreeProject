# 나드리 앱 프론트 취소 환불 및 인증 변경 전달서

작성일: 2026-10-08  
대상: 고객 앱 개발자, 관리자 앱 개발자

최근 변경된 취소·환불 정책, 결제 안내 푸시, 탈퇴·로그아웃 후 인증 정책의 연동 사항이다. 이전 전달 내용 중 고객의 결제 완료 예약 취소 금지, 관리자 취소 90% 환불, 렌트 당일 관리자 환불 불가 안내는 아래 정책으로 대체한다.

앱 화면, API 요청·응답, 오류 처리에 필요한 변경사항만 안내한다. 연동 테스트 시작 전 백엔드 담당자에게 적용 환경을 확인한다.

## 1 취소와 환불 정책

| 구분 | 고객 취소 | 관리자 취소 |
| --- | --- | --- |
| 메서드 | POST | POST |
| 경로 | `/api/v1/nadree/rental/request/cancel` | `/nadreego/booking/action` |
| 인증 | 고객 access token | 관리자 access token |
| 예약 조건 | 본인 예약, REQUESTED 또는 APPROVED, 차량 인계 전 | 관리자 권한 범위 내 APPROVED 예약, 차량 인계 전 |
| 날짜 제한 | 렌트 시작일 전까지 허용 | 고객 취소의 날짜 제한을 적용하지 않음 |
| 결제 완료 건 환불 | 결제금액의 90%, 10% 수수료 공제 | 결제금액의 100% |
| 미결제 건 | 예약 취소만 처리, 환불 불필요 | 예약 취소만 처리, 환불 불필요 |

고객 취소 마감은 서버 업무 시간대 기준 렌트 시작일 00:00이다. 기본 시간대는 `Asia/Makassar`이며, 기기 시간대나 렌트 시작 시각 24시간 전을 기준으로 계산하지 않는다. 당일 및 이후에는 미결제 예약도 고객이 취소할 수 없다.

이미 고객이 취소한 예약을 관리자 취소 API로 다시 취소하여 100%로 변경하는 기능은 아니다. 취소 완료 예약에 대한 추가 환불은 이번 범위에 포함하지 않는다.

### 고객 취소 요청과 응답

```http
POST /api/v1/nadree/rental/request/cancel
Authorization: Bearer <CUSTOMER_ACCESS_TOKEN>
Content-Type: application/json
```

```json
{
  "reservationId": "실제 예약 ID",
  "reason": "일정 변경"
}
```

`reason`은 선택이다. 결제 총액이 100 USD이고 기존 환불이 없는 경우의 응답 예시:

```json
{
  "status": "success",
  "reservationId": "실제 예약 ID",
  "bookedNo": "BO실제 예약 ID",
  "reservationStatus": "CANCELED",
  "refundStatus": "REQUESTED",
  "refundRequestedAmount": 90,
  "refundReason": "CUSTOMER_REFUND_90_PERCENT"
}
```

미결제 건은 `refundStatus=NOT_REQUIRED`, `refundRequestedAmount=0`, `refundReason=NO_COMPLETED_PAYMENT`로 응답한다.

### 관리자 취소 요청과 응답 필드

```http
POST /nadreego/booking/action
Authorization: Bearer <ADMIN_ACCESS_TOKEN>
Content-Type: application/json
```

```json
{
  "bookedNo": "실제 BO 접두사 예약 번호",
  "action": "CANCEL",
  "reason": "지점 사정으로 취소"
}
```

기존 응답 구조의 `data.refundStatus`, `data.refundAmount`, `data.refundReason`을 사용한다. 결제 총액 100 USD인 경우 목표액은 `data.refundAmount=100`, 정책 코드는 `ADMIN_REFUND_100_PERCENT`다. 고객 API와 환불 금액 필드명 및 위치가 다르므로 같은 응답 타입을 그대로 사용하지 않는다.

### 환불 표시와 오류 처리

취소 성공은 예약 취소 완료를 의미하며 PayPal 환불 완료를 보장하지 않는다. 결제 상태를 다시 조회하여 `refundStatus`와 실제 누적 환불액 `refundedAmount`를 표시한다. 목표액은 고객 90%·관리자 100%의 누적 금액이며, 기존 부분 환불이 있으면 서버가 잔액만 요청한다. 프론트에서 환불 금액을 지정하지 않는다.

| HTTP | errorCode | 프론트 처리 |
| --- | --- | --- |
| 409 | `CUSTOMER_CANCELLATION_DEADLINE_PASSED` | 렌트 당일부터 고객 취소 불가 안내 |
| 409 | `PAYMENT_IN_PROGRESS` | 결제 캡처 진행 중임을 안내하고 상태 조회 후 재판단 |
| 409 | `RESERVATION_STATE_INVALID` | 예약 상태 새로 조회, 중복 취소 자동 재전송 금지 |
| 409 | `RESERVATION_ALREADY_HANDED_OVER` | 차량 인계 완료로 취소할 수 없음을 안내 |
| 404 | `RESERVATION_NOT_FOUND` | 예약 없음 또는 본인 예약 아님 처리 |
| 409 | `REFUND_ALREADY_IN_PROGRESS` | 환불 진행 중 안내, 중복 요청 금지 |
| 409 | `PAYMENT_STATE_INCONSISTENT` | 결제 확인 필요 안내, 임의 재결제 금지 및 고객센터 문의 유도 |
| 503 | `REFUND_POLICY_SCHEMA_UPDATE_REQUIRED` | 일시적으로 처리할 수 없음 안내, 자동 재시도 중단 및 백엔드 담당자 전달 |

환불 상태가 `FAILED`인 경우 예약 취소는 되돌아가지 않는다. 환불 확인이 필요하다고 안내하고 고객센터 문의로 연결한다. 환불 완료나 자동 재시도 완료로 표시하지 않는다.

## 2 결제 안내 푸시

예약 승인 후 결제 요청과 결제 기한 2일·1일 전 알림에 다음 문구를 반영했다.

> 결제 후 고객 취소 시 결제금액의 10%가 환불 수수료로 공제됩니다. 렌트 당일부터는 고객 취소가 불가능합니다.

승인 후 결제 기한 72시간은 유지한다. 고객 앱의 결제 확인 화면과 취소 확인창도 같은 정책으로 표시하고, 관리자 취소에 10% 수수료를 적용한다는 안내는 사용하지 않는다.

## 3 로그인과 탈퇴 보안

로그인 경로는 기존 `POST /api/v1/nadree/user/login`을 유지한다. 요청 body의 `UID`와 `Authorization: Bearer <FIREBASE_ID_TOKEN>`을 사용한다. 고객 서비스 access token을 Firebase ID token 대신 보내지 않는다.

- Firebase ID token 검증에 계정 삭제·비활성화·토큰 폐기 여부 확인을 추가했다.
- 검증된 실제 인증 시각인 `auth_time`을 사용한다. 서버가 이 값을 임의로 올려 로그인시키지 않는다.
- `auth_time`이 서버의 탈퇴·로그아웃 시각과 같은 초이거나 이전이면 로그인 요청을 거절한다.
- 탈퇴 후 기존 고객 access·refresh token으로 접근하거나 토큰을 갱신할 수 없다.

### 프론트 인증 오류 처리

| HTTP | errorCode | 처리 |
| --- | --- | --- |
| 401 | `FIREBASE_REAUTHENTICATION_REQUIRED` | 저장된 서비스 토큰을 지우고 Firebase 재인증 후 로그인 API 재호출 |
| 401 | `FIREBASE_ID_TOKEN_INVALID` | 로그인 실패 처리, Firebase 계정 상태에 따라 재로그인 또는 재가입 안내 |
| 401 | `INVALID_NADRI_USER_TOKEN` | 보호 API 접근 중단, 서비스 인증 상태 정리 |
| 401 | `INVALID_REFRESH_TOKEN` | 갱신 반복 중단, 로그인 절차로 전환 |

`FIREBASE_REAUTHENTICATION_REQUIRED`는 ID token을 강제로 갱신하는 것만으로 해결하지 않는다. 사용자 인증 수단을 통한 실제 재인증이 필요하며, 새 인증 시각은 폐기 시각보다 뒤의 초여야 한다. 이 규칙은 탈퇴뿐 아니라 로그아웃 후 로그인에도 적용된다.

### 탈퇴와 재가입

조건 없는 탈퇴 정책은 유지한다. 진행 중 예약·결제가 있다는 이유로 앱에서 탈퇴를 차단하지 않는다. 기존 `DELETE /api/v1/nadree/user/account`를 고객 access token으로 호출하며, 탈퇴 성공 후 앱의 서비스 토큰과 사용자 캐시를 지우고 Firebase 로그아웃을 처리한다. Firebase 계정 삭제는 백엔드에서 수행하므로 앱에서 API 호출 전에 계정을 먼저 삭제하지 않는다. 실패 시 탈퇴 완료 화면을 표시하지 않는다.

예약·결제 이력은 보존되므로 모든 데이터가 즉시 삭제된다고 안내하지 않는다. 탈퇴가 예약 취소 또는 환불 요청을 대신하지 않는다.

정상적으로 생성된 새 UID는 신규 회원으로 처리하고 `isNewUser=true`를 반환한다. 이전 UID의 예약·결제 이력을 새 UID에 자동 이전하지 않는다. 기존 UID가 정상 Firebase 검증과 더 최근의 실제 인증을 통과한 경우에는 기존 DB 행으로 로그인하며 `isNewUser=false`다. 단순히 같은 UID를 보냈다는 이유로 재가입 처리하지 않는다.

## 4 앱 프론트 확인 목록

- 고객 앱: 결제 완료 예약의 시작일 전 취소 버튼과 90% 환불 안내를 반영한다.
- 고객 앱: 업무 시간대 기준 시작일 00:00부터 취소 버튼을 비활성화하고 서버의 마감 오류도 처리한다.
- 관리자 앱: 취소 시 100% 환불과 기존 인계 전 제한을 안내한다.
- 고객 앱: 로그아웃 후 실제 Firebase 재인증, 탈퇴 후 이전 토큰 차단, 새 UID 가입을 확인한다.
- 고객·관리자 앱: 취소 직후 예약 상태를 갱신하고, 환불 요청과 환불 완료를 구분해 표시한다.
- 고객·관리자 앱: 환불 실패·결제 진행 중·중복 취소 오류에서 자동 반복 요청을 하지 않는다.
- 고객 앱: 탈퇴 성공 시 로컬 토큰·사용자 캐시가 제거되고 로그인 화면으로 이동하는지 확인한다.

여권 기능과 웹페이지 전용 변경은 이번 앱 프론트 요청에 포함하지 않는다.
