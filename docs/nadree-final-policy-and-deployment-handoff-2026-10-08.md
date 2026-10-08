# 나드리 최종 정책·배포·프론트 전달서

최종 수정일: 2026-10-08

대상 서비스: Nadree API

운영 기본 주소: `https://na-dree.com`

## 1. 최종 확정 정책

### 결제·환불

- 고객은 렌트 시작일 전까지 본인의 REQUESTED/APPROVED 예약을 직접 취소할 수 있습니다.
- 결제 완료 후 고객 취소는 결제금액의 90%를 환불합니다(10% 수수료).
- 관리자 취소는 결제금액의 100%를 환불합니다. 기존 인계 전 APPROVED 예약 제한은 유지합니다.
- 환불액은 USD 센트 단위로 반올림하여 계산합니다.
- 업무 시간대(기본 Asia/Makassar) 기준 렌트 시작일 00:00부터 고객 취소 자체를 차단합니다. 미결제도 동일합니다.
- 고객 당일 취소는 HTTP 409 `CUSTOMER_CANCELLATION_DEADLINE_PASSED`입니다. 관리자 취소에는 이 날짜 제한을 적용하지 않습니다.
- 환불 목표금액은 `MSP_RENTAL_PAYMENT.refund_requested_amount`에 기록합니다.
- PayPal 환불 최종 결과는 PayPal 웹훅으로 확정합니다.

### 결제 마감

- 결제 마감은 관리자 승인 이력의 `APPROVED` 시각부터 정확히 72시간입니다.
- 마감 이후 PayPal 주문 생성과 결제 캡처는 `409 PAYMENT_DEADLINE_EXPIRED`로 거절합니다.
- 결제 응답에 다음 필드를 제공합니다.

```json
{
  "paymentDeadline": "2026-10-04T10:00:00+08:00",
  "canPay": true,
  "cannotPayReason": null
}
```

### 예약 기간

- 가용성 조회·예약 요청·관리자 캘린더의 최대 기간은 30일입니다.
- 반납일은 시작일보다 늦어야 합니다.

### 회원 탈퇴

- 로그인 시 Firebase 계정 삭제·비활성화·토큰 폐기 여부를 확인합니다. 기존 Firebase 토큰을 사용한 탈퇴 계정 재접속을 차단합니다.
- `401 FIREBASE_REAUTHENTICATION_REQUIRED`이면 서비스 토큰을 삭제하고 Firebase 재인증을 진행합니다. 단순 ID 토큰 갱신만으로는 해결되지 않습니다. 로그아웃 이후 로그인에도 적용됩니다.
- 인증 시각은 탈퇴·로그아웃 시각보다 뒤의 초여야 합니다. 정상적인 새 UID 가입은 허용하고 이전 UID의 이력은 자동 이전하지 않습니다.
- 추가 DB 변경·환경변수는 없습니다. 소스 배포와 API 재시작 후 Firebase 실연동으로 탈퇴 → 이전 토큰 거절 → 재가입을 확인해야 합니다. 서비스 계정의 Authentication 사용자 조회 권한도 확인합니다.

- 예약·결제·렌탈 진행 여부와 관계없이 회원 탈퇴를 허용합니다.
- 렌탈·결제 이력은 보존합니다.
- 프로필 정보, FCM 토큰, 고객 access/refresh 세션을 폐기합니다.
- 운영 Firebase 설정이 있으면 기존 FCM Firebase 프로젝트의 Authentication UID도 삭제합니다.

### 채팅 권한

| 관리자 역할 | 채팅 조회 | 새 채팅 알림 | 답변 |
|---|---:|---:|---:|
| 대표관리자 `rental_primary_admin` | 가능 | 가능 | 가능 |
| 일반관리자 `rental_manager` | 가능 | 가능 | 불가 |

대상 지점에 직접 연결된 활성 관리자만 채팅 알림 수신 대상입니다. 일반관리자는 채팅 내용을 확인할 수 있지만 메시지를 전송할 수 없습니다.

### Firebase 프로젝트

- 고객 Firebase Authentication, FCM, 채팅 Firestore/Callable Functions는 기존 `NADREE_FCM_*` 프로젝트를 사용합니다.
- 차량 위치 탐색만 `NADREE_FIRESTORE_PROJECT` 및 `NADREE_LOCATION_FIREBASE_*` 프로젝트를 사용합니다.
- 채팅 전용 환경변수는 추가하지 않습니다.

## 2. 백엔드에 반영된 내용

- `DELETE /api/v1/nadree/user/account` 회원 탈퇴 API 추가
- 결제 응답에 `paymentDeadline`, `canPay`, `cannotPayReason` 추가
- 결제 응답에 `refundRequestedAmount` 추가
- 고객 취소 시 90%, 관리자 취소 시 100% 환불 목표금액 저장
- 렌트일 당일 및 이후 고객 취소 차단
- PayPal 환불 실행 시 저장된 환불 목표금액만 요청
- 결제 주문·캡처 API에 72시간 마감 검증 추가
- 관리자 캘린더 기간을 최대 30일로 변경
- Swagger/OpenAPI 예시와 프론트 인수 문서 갱신

회원 탈퇴 API 예시:

```http
DELETE /api/v1/nadree/user/account
Authorization: Bearer <nadree-access-token>
```

```json
{
  "status": "success",
  "deleted": true
}
```

## 3. 프론트엔드 전달사항

### 결제 화면

- `canPay=true`일 때만 결제 버튼을 활성화합니다.
- `paymentDeadline`을 결제 마감 안내에 사용합니다.
- `PAYMENT_DEADLINE_EXPIRED` 수신 시 결제 버튼을 숨기고 예약 만료 상태를 표시합니다.
- `PENDING` 캡처 결과는 즉시 재호출하지 않고 결제 상태 조회 API를 호출합니다.

### 환불 화면

- 예정 환불액: `refundRequestedAmount`
- 실제 반영 환불액: `refundedAmount`
- 환불 상태: `refundStatus`
- 고객 취소 버튼은 렌트 시작일 00:00부터 비활성화하고 서버의 마감 오류도 처리합니다.
- 고객 취소 응답의 `refundRequestedAmount`는 목표 누적 환불액이며 `refundReason`은 `CUSTOMER_REFUND_90_PERCENT`입니다. 미결제는 `NO_COMPLETED_PAYMENT`·0원·`NOT_REQUIRED`입니다.
- 관리자 취소 응답은 `data.refundAmount`와 `data.refundReason=ADMIN_REFUND_100_PERCENT`를 사용합니다.
- 캡처 진행 중 고객 취소는 `PAYMENT_IN_PROGRESS`입니다. 취소 성공이 환불 완료를 뜻하지 않으므로 결제 상태를 조회합니다.
- 기존 `refund_requested_amount` 컬럼이 적용되어 있으면 이번 변경에 추가 마이그레이션·환경변수는 없습니다. 새 소스를 배포하고 API 및 알림 worker를 재시작해야 합니다. 운영 반영은 별도입니다.

### 회원 탈퇴

탈퇴 성공 후 앱에 저장된 access token과 refresh token을 즉시 삭제합니다.

## 4. 운영 서버 적용 순서

### 4.1 최신 코드 배포

다음 변경사항이 운영 서버에 포함되어야 합니다.

```text
app/payment_policy.py
app/customer_rentals.py
app/rentals.py
app/paypal.py
app/firebase_auth.py
app/migrate.py
app/rental_inputs.py
app/rental_schema.py
app/responses.py
migrations/010_refund_policy.sql
```

### 4.2 환경변수 확인

새로운 환경변수는 없습니다. 다음 값만 확인합니다.

- `NADREE_DATABASE_URL`
- `NADREE_FCM_*`
- `NADREE_LOCATION_FIREBASE_*`
- `NADREE_PAYPAL_*`

`.env` 권한은 운영 서비스 사용자 기준으로 유지합니다.

```bash
sudo chown ec2-user:ec2-user /srv/nadree-api/.env
sudo chmod 600 /srv/nadree-api/.env
```

`chmod 644`로 변경하지 않습니다.

### 4.3 마이그레이션 적용

운영 DB 백업 후 `ec2-user`로 실행합니다.

```bash
sudo -u ec2-user -H bash -lc '
  cd /srv/nadree-api
  .venv/bin/python -m app.migrate
'
```

다음과 같이 표시되면 아직 적용 전입니다.

```text
PENDING add MSP_RENTAL_PAYMENT.refund_requested_amount
Read-only plan; no database writes.
```

실제 DB명이 `RIDERLOG_V2_DATA_TEST`인 경우 적용 명령은 다음과 같습니다. 운영 DB명이 다르면 실제 DB명으로 변경합니다.

```bash
sudo -u ec2-user -H bash -lc '
  cd /srv/nadree-api
  .venv/bin/python -m app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST
'
```

적용 후 다시 확인합니다.

```bash
sudo -u ec2-user -H bash -lc '
  cd /srv/nadree-api
  .venv/bin/python -m app.migrate
'
```

최종 결과:

```text
No pending changes.
```

### 4.4 서비스 재시작

```bash
sudo systemctl restart nadree-api
sudo systemctl status nadree-api --no-pager
```

서비스가 `User=ec2-user`로 실행되는지 확인합니다. `ssm-user`로 직접 애플리케이션을 실행하면 권한 600인 `.env`를 읽을 수 없습니다.

## 5. 운영 Swagger 확인

```bash
curl -fsS https://na-dree.com/openapi.json | python3 -c 'import json,sys; d=json.load(sys.stdin); print("/api/v1/nadree/user/account" in d["paths"]); print("refundRequestedAmount" in str(d["components"]["schemas"]["CustomerPayment"]))'
```

두 결과가 모두 `True`이면 회원 탈퇴 API와 환불 필드가 운영 OpenAPI에 반영된 상태입니다.

Swagger UI:

- `https://na-dree.com/docs`
- `https://na-dree.com/redoc`
- `https://na-dree.com/openapi.json`

## 6. Firebase 채팅의 별도 작업

Firestore는 컬렉션을 미리 만들지 않아도 최초 문서 쓰기 시 컬렉션과 문서가 자동 생성됩니다. 단, Firebase Console에서 Firestore Database 자체는 한 번 활성화해야 합니다.

현재 Nadree API 저장소에는 Firebase Functions와 Firestore Rules 소스가 없습니다. 따라서 다음 채팅 기능은 별도 Firebase Functions 프로젝트에 배포해야 합니다.

- `ensureBookingChat`
- `ensureInquiryChat`
- `sendChatMessage`
- `markChatRead`
- `getChatUnreadSummary`

채팅 Functions는 기존 FCM Firebase 프로젝트에 배포하고, 일반관리자의 메시지 전송을 Callable 내부와 Firestore Rules 양쪽에서 차단해야 합니다. 아직 정하지 않은 값은 Firebase Functions 리전입니다.

## 7. 검증 현황

```text
164 passed, 6 skipped, 2 warnings
```

6개 스킵은 별도 MySQL 환경이 필요한 테스트입니다. PayPal Sandbox, 실제 FCM 수신, Firebase Authentication 삭제, Firebase 채팅 Callable은 운영 환경에서 별도 통합 확인이 필요합니다.
