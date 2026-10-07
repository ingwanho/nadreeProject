# Nadree API 테스트 전달 문서

최종 수정일: 2026-10-01

이 문서는 서버와 테스트 DB가 준비된 상태에서 Swagger를 이용해 나드리 고객 앱과 나드리고 관리자 API를 검증하기 위한 실행 문서입니다.

## 1. 접속 정보

| 항목 | 값 |
|---|---|
| API 기본 주소 | `https://na-dree.com` |
| Swagger UI | `https://na-dree.com/docs` |
| OpenAPI JSON | `https://na-dree.com/openapi.json` |
| ReDoc | `https://na-dree.com/redoc` |
| 상태 확인 | `/health/live`, `/health/ready` |
| 업무 시간대 | `Asia/Makassar`(발리) |
| 결제 통화 | `USD` |

Swagger의 `Try it out`을 사용하거나 같은 요청을 Postman·앱에서 호출합니다. 관리자 API prefix는 `/nadreego`, 고객 API prefix는 `/api/v1/nadree`입니다.

## 2. 테스트 데이터 식별자

`NRTEST-` 접두사가 붙은 행만 테스트 데이터입니다. 운영 데이터와 섞이지 않도록 테스트 요청에는 아래 값을 사용합니다.

웹 고객 API의 추가 시나리오가 필요하면 `migrations/test_seed_web_requirements.sql`을 `test_seed_rental_scenarios.sql` 이후 실행합니다. `NRTEST-WEB-MODEL-125`는 BASIC/PREMIUM 가격을 함께 제공하고, `NRTEST-WEB-MODEL-ND`는 배송 미지원 모델입니다. `NRTEST-CANGGU` 주소와 기존 `NRTEST-KUTA` 주소를 사용해 배송지역 일치·불일치도 확인할 수 있습니다.

| 구분 | 값 | 예상 내용 |
|---|---|---|
| 테스트 지점 | `00000000-0000-4000-8000-000000000101` | `shopId`, `spotMasterId` 공통 값 |
| 125cc 모델 | `NRTEST-MODEL-125` | Honda Vario 125, 일일 25 USD |
| 155cc 모델 | `NRTEST-MODEL-155` | Yamaha NMAX 155, 일일 35 USD |
| 차량 301 | `NRTEST-VEHICLE-301` | 대여 가능 |
| 차량 302 | `NRTEST-VEHICLE-302` | 정비 상태 |
| 차량 303 | `NRTEST-VEHICLE-303` | 진행 중 렌트 |
| 차량 304 | `NRTEST-VEHICLE-304` | 미래 승인 예약 |
| 웹 BASIC/PREMIUM 모델 | `NRTEST-WEB-MODEL-125` | 125cc, BASIC/PREMIUM 동시 가격, 테스트 이미지 URL |
| 웹 배송 미지원 모델 | `NRTEST-WEB-MODEL-ND` | 125cc, 배송 요청 시 `DELIVERY_NOT_SUPPORTED` |
| 웹 BASIC 차량 | `NRTEST-WEB-BASIC-125` | `NRTEST-WEB-MODEL-125`의 BASIC 가격 |
| 웹 PREMIUM 차량 | `NRTEST-WEB-PREMIUM-125` | `NRTEST-WEB-MODEL-125`의 PREMIUM 일일 45 USD |
| 웹 배송 미지원 차량 | `NRTEST-WEB-NODELIVERY` | 배송 미지원 모델의 대여 가능 차량 |
| 웹 추가 배송지역 | `NRTEST-CANGGU` | `Canggu Test Area`, 왕복 30 USD |

### 예약 상태 샘플

| 예약 ID | 상태 | 용도 |
|---|---|---|
| `NRTEST-RES-REQ-001` | `REQUESTED` | 관리자 승인 대기·고객 취소 |
| `NRTEST-RES-APP-001` | `APPROVED` | 승인 후 결제 주문 생성 |
| `NRTEST-RES-PENDING-001` | `APPROVED` | `PENDING` 결제 상태 조회 |
| `NRTEST-RES-REJECT-001` | `REJECTED` | 거절 이력 |
| `NRTEST-RES-CANCEL-001` | `CANCELED` | 취소·환불 불필요 |
| `NRTEST-RES-EXPIRED-001` | `EXPIRED` | 결제 기한 만료 |
| `NRTEST-RES-HAND-001` | `HANDED_OVER` | 진행 중 렌트·결제 완료 |
| `NRTEST-RES-RETURN-001` | `RETURNED` | 완료 렌트·환불 완료 |

현재 테스트 결제 데이터는 `PENDING`, `PAID`, `FAILED`, 환불 완료 `PAID/COMPLETED` 상태를 포함합니다. `paymentId` 숫자는 DB 재생성 시 바뀔 수 있으므로 예약 ID로 조회한 실제 응답값을 사용합니다.

## 3. 인증 준비

### 관리자

테스트 관리자 계정은 시드 SQL에 생성된 계정을 사용합니다.

- 대표 관리자: `nadree.test.admin@example.com`
- 일반 관리자: `nadree.test.manager@example.com`
- 테스트 비밀번호: `Nadree-Test-123!`

관리자 로그인:

```http
POST /nadreego/admin/login
Content-Type: application/json
```

```json
{
  "email": "nadree.test.admin@example.com",
  "password": "Nadree-Test-123!"
}
```

응답의 `accessToken`은 `Authorization: Bearer <accessToken>`으로 사용하고, `refreshToken`은 `X-Refresh-Token` 헤더로 사용합니다. 테스트가 끝난 뒤 관리자 로그아웃을 호출합니다.

### 고객

고객 로그인은 Firebase ID Token 검증이 필수입니다.

```http
POST /api/v1/nadree/user/login
Authorization: Bearer <firebase-id-token>
Content-Type: application/json
```

```json
{
  "UID": "NRTEST-USER-001",
  "fcmToken": "실제 테스트 기기에서 발급한 FCM 토큰"
}
```

Firebase 토큰의 `uid`와 body의 `UID`가 정확히 같아야 합니다. Firebase 프로젝트에 `NRTEST-USER-001` 사용자가 없으면 서버에 임의의 UID를 보내지 말고, Firebase 테스트 계정의 실제 UID를 사용해 로그인한 뒤 해당 UID의 테스트 데이터를 별도로 준비해야 합니다. 시드 SQL의 `test-customer-fcm-token-*` 값은 형식 확인용이며 실제 푸시 수신에는 사용할 수 없습니다.

## 4. 실행 순서

### 4.1 서버 상태

```http
GET /health/live
GET /health/ready
```

예상 결과:

```json
{
  "status": "ok"
}
```

`/health/ready`는 `status=ok`여야 합니다. `MFA_FLOW_NOT_IMPLEMENTED`는 현재 알려진 제한사항이며 테스트 차단 오류가 아닙니다.

### 4.2 고객 차량·가격 조회

```http
POST /api/v1/nadree/rental/availability
Content-Type: application/json
```

```json
{
  "startDate": "2026-10-10",
  "returnDate": "2026-10-13",
  "cc": 125,
  "deliveryRequested": false
}
```

확인할 항목:

- `items`가 비어 있지 않음
- `shopId`와 `spot.spotMasterId`가 테스트 지점 ID와 일치
- `model.modelId`가 `NRTEST-MODEL-125`
- `price.currency`가 `USD`
- `price.rentalDays`가 3
- `price.dailyFrom`와 `price.dailyTo`가 25
- `price.totalFrom`와 `price.totalTo`가 75

배송 조회도 확인합니다.

```json
{
  "startDate": "2026-10-10",
  "returnDate": "2026-10-13",
  "cc": 125,
  "deliveryRequested": true,
  "pickupLocation": "Kuta Test Area",
  "returnLocation": "Kuta Test Area"
}
```

배송 응답에는 배송 지역 ID가 있고, 시작 배송비 10, 반납 배송비 10, 합계 20이 반환되어야 합니다.

### 4.3 예약 요청과 관리자 알림

availability 응답에서 받은 `spotMasterId`, `modelId`, `price.totalFrom`를 그대로 사용합니다.

```http
POST /api/v1/nadree/rental/request
Authorization: Bearer <nadree-access-token>
Content-Type: application/json
```

```json
{
  "spotMasterId": "00000000-0000-4000-8000-000000000101",
  "modelId": "NRTEST-MODEL-125",
  "startDate": "2026-10-25",
  "returnDate": "2026-10-28",
  "totalPrice": 75,
  "currency": "USD",
  "deliveryRequested": false
}
```

예상 결과:

- `reservationStatus=REQUESTED`
- `paymentAvailability=WAITING_APPROVAL`
- `bookingId`와 `reservationId`가 동일
- `bookedNo`는 `BO` + reservationId
- 해당 지점의 활성 관리자 전체에 `RESERVATION_REQUESTED` FCM 전송

같은 요청을 60초 이내 재전송하면 `DUPLICATE_RENTAL_REQUEST`, 재고를 다른 요청이 먼저 점유하면 `RENTAL_UNAVAILABLE`을 확인합니다.

### 4.4 관리자 승인·거절

새로 만든 예약의 `bookedNo`를 사용합니다.

```http
POST /nadreego/booking/action
Authorization: Bearer <admin-access-token>
Content-Type: application/json
```

승인:

```json
{
  "bookedNo": "BO<reservationId>",
  "action": "APPROVE"
}
```

예상 결과는 `reservationStatus=APPROVED`, `vehicleAssignmentStatus=PROVISIONAL`입니다. 고객에게 승인 FCM이 전송되고 결제 가능 상태가 됩니다.

거절 테스트는 아직 승인하지 않은 다른 `REQUESTED` 예약으로 별도 실행합니다.

```json
{
  "bookedNo": "BO<reservationId>",
  "action": "REJECT",
  "reason": "차량 운영 사정"
}
```

### 4.5 결제 전 취소

`REQUESTED` 또는 `APPROVED`이면서 결제가 완료되지 않은 예약에서 실행합니다.

```http
POST /api/v1/nadree/rental/request/cancel
Authorization: Bearer <nadree-access-token>
Content-Type: application/json
```

```json
{
  "reservationId": "<reservationId>",
  "reason": "일정 변경"
}
```

예상 결과는 `reservationStatus=CANCELED`, `refundStatus=NOT_REQUIRED`입니다. `PAID` 또는 캡처 완료 예약에서 고객 취소를 시도하면 `PAYMENT_REFUND_ADMIN_ONLY`가 반환되어야 합니다.

### 4.6 PayPal Sandbox 결제

결제는 관리자 승인 이후에만 가능합니다.

```http
POST /api/v1/nadree/rental/payment/order
Authorization: Bearer <nadree-access-token>
Content-Type: application/json
```

```json
{
  "reservationId": "<approved-reservationId>"
}
```

확인할 항목:

- `paymentStatus=CREATED`
- `approvalUrl`이 Sandbox PayPal 주소임
- `currency=USD`
- 서버 저장 금액과 availability 견적이 동일함

PayPal Sandbox 결제 승인 후:

```http
POST /api/v1/nadree/rental/payment/capture
Authorization: Bearer <nadree-access-token>
Content-Type: application/json
```

```json
{
  "paymentId": 〈주문 생성 응답의 paymentId〉
}
```

캡처 직후 `PENDING`이면 캡처를 즉시 반복하지 않고 아래 조회 API로 확인합니다.

```http
GET /api/v1/nadree/rental/payment/{paymentId}
Authorization: Bearer <nadree-access-token>
```

PayPal 웹훅 주소는 다음과 같습니다.

```text
https://na-dree.com/nadreego/paypal/webhook
```

실제 Sandbox 웹훅 이벤트가 도착한 뒤 `PAID`로 확정되는지, 동일 이벤트를 재전송해도 중복 결제·중복 알림이 발생하지 않는지 확인합니다.

승인 전 주문 생성은 다음 오류여야 합니다.

```text
RESERVATION_NOT_APPROVED_FOR_PAYMENT
```

### 4.7 진행 중·완료 목록

```http
GET /api/v1/nadree/rental/ongoing?page=1&pageSize=20
Authorization: Bearer <nadree-access-token>
```

```http
GET /api/v1/nadree/rental/completed?page=1&pageSize=20
Authorization: Bearer <nadree-access-token>
```

시드 사용자 기준 예상 결과:

- 진행 중 목록에 `NRTEST-RES-HAND-001`과 승인 대기·결제 대기 예약이 표시됨
- 완료 목록에 `NRTEST-RES-RETURN-001`이 표시됨
- 완료 건의 `price.currency=USD`, `payment.refundStatus=COMPLETED`

목록의 `shopId`, `spotMasterId`, `modelId`, `price`, `delivery`, `payment` 필드를 함께 확인합니다.

## 5. 관리자 API 테스트 목록

관리자 access token으로 Swagger에서 다음 순서로 확인합니다.

| 그룹 | 메서드 | 경로 | 확인 내용 |
|---|---|---|---|
| 계정 | POST | `/nadreego/admin/login` | 대표·일반 관리자 로그인, 역할·지점 ID |
| 계정 | GET | `/nadreego/admin/refresh` | refresh token 교체, 이전 토큰 재사용 차단 |
| 계정 | GET | `/nadreego/admin/logout` | 현재 세션만 폐기, FCM 토큰 유지 |
| 계정 | POST | `/nadreego/admin/fcmToken` | 관리자 FCM 토큰 저장 |
| 계정 | POST | `/nadreego/admin/spotcheck` | 초대 코드로 지점 확인 |
| 계정 | POST | `/nadreego/admin/update` | 관리자 프로필 수정 |
| 계정 | POST | `/nadreego/admin/findpswd` | SMTP 설정 시 비밀번호 재설정 |
| 가입 | POST | `/nadreego/admin/signup` | 대표 이메일 또는 초대 코드로 가입 신청 |
| 지점·권한 | GET/POST | `/api/v1/organizations/spots/hierarchy`, `/api/v1/organizations/spots` | 지점 계층 조회·하위 지점 생성 |
| 지점·권한 | GET | `/nadreego/shop/admin` | 지점 관리자 목록 |
| 지점·권한 | POST | `/nadreego/shop/adminDelete` | 일반 관리자 삭제, 대표 관리자 삭제 차단 |
| 지점·권한 | POST | `/nadreego/shop/update` | 샵 정보·배송 서비스 수정 |
| 지점·권한 | GET/POST | `/nadreego/shop/adminRequest`, `/nadreego/shop/adminRequestAction` | 가입 신청 조회·승인·거절 |
| 차량 | POST | `/nadreego/vehicle/create` | 차량 등록, 센서 또는 QR 필수 |
| 차량 | POST | `/nadreego/vehicle/qr/validate` | QR 상태·지점 권한 확인 |
| 차량 | POST | `/nadreego/sensor/delete` | 센서·QR 연결 해제 |
| 차량 | POST | `/nadreego/vehicle/location` | 차량 위치 저장·조회 연동 |
| 차량 | POST | `/nadreego/vehicle/repair` | 정비 기간 설정 |
| 차량 | POST | `/nadreego/vehicle/spotChange` | 차량 지점 이동 |
| 차량 | POST | `/nadreego/brand` | 브랜드·모델 검색 |
| 차량 | POST | `/nadreego/vehicle/select` | 차량 목록 조회 |
| 가격 | POST/GET | `/nadreego/shop/tierCreate` | BASIC 가격 티어 생성·목록 조회 |
| 가격 | POST | `/nadreego/shop/tierDelete` | 가격 티어 삭제 |
| 가격 | POST | `/nadreego/vehicle/priceChange` | 차량 BASIC/PREMIUM 가격 변경 |
| 배송 | GET/POST | `/nadreego/shop/delivery/regions`, `/nadreego/shop/delivery` | 공통 지역·지점 배송 설정 조회 |
| 배송 | POST | `/nadreego/shop/deliveryDelete` | 배송 설정 비활성화 |
| 운영 | GET | `/nadreego/main` | 대시보드 집계 |
| 운영 | POST | `/nadreego/main/calendar` | 차량별 예약·렌트·정비 일정 |
| 운영 | POST | `/nadreego/booking/select` | 예약·렌트 통합 목록 |
| 상태 | POST | `/nadreego/booking/action` | 예약 승인·거절·관리자 취소 |
| 상태 | POST | `/nadreego/rent/approve` | QR 인계 및 렌트 시작 |
| 상태 | POST | `/nadreego/vehicle/return` | QR 반납 및 렌트 종료 |
| PayPal | POST | `/nadreego/paypal/webhook` | 서명 검증·중복 이벤트·결제/환불 상태 반영 |

QR 인계·반납은 관광객 앱에서 호출하지 않습니다. 시드 SQL에는 서버 QR 해시 키를 알 수 없어 QR 행을 넣지 않았으므로, 해당 API 테스트에는 서버가 발급한 유효 QR 또는 `/nadreego/vehicle/create`로 생성한 QR을 사용합니다.

## 6. 오류·예외 테스트

| 시나리오 | 예상 오류 |
|---|---|
| Firebase ID Token 없이 고객 로그인 | `FIREBASE_ID_TOKEN_REQUIRED` |
| Firebase UID와 body `UID` 불일치 | `FIREBASE_UID_MISMATCH` |
| 만료된 고객 access token | `INVALID_NADRI_USER_TOKEN` 또는 `AUTH_REQUIRED` |
| 만료·재사용된 refresh token | `INVALID_REFRESH_TOKEN` |
| 승인 전 결제 주문 | `RESERVATION_NOT_APPROVED_FOR_PAYMENT` |
| 잘못된 가격으로 예약 요청 | `PRICE_QUOTE_MISMATCH` |
| 같은 예약 요청 중복 | `DUPLICATE_RENTAL_REQUEST` |
| 차량이 이미 점유된 기간 요청 | `RENTAL_UNAVAILABLE` |
| 결제 완료 후 고객 취소 | `PAYMENT_REFUND_ADMIN_ONLY` |
| 캡처 중 결제 취소 | `PAYMENT_IN_PROGRESS` |
| 권한 없는 지점 접근 | `SPOT_REQUIRED`, `FORBIDDEN` 계열 |
| 관리자 역할 없는 계정 로그인 | `RENTAL_ROLE_REQUIRED` |

모든 오류 응답은 다음 형식입니다.

```json
{
  "status": "fail",
  "errorCode": "ERROR_CODE"
}
```

네트워크 타임아웃 후 예약·결제 요청을 무조건 재전송하지 않습니다. 먼저 예약 목록 또는 결제 상태 조회 API로 기존 처리 결과를 확인합니다.

## 7. FCM 확인 목록

실제 기기 FCM 토큰으로 로그인 또는 토큰 등록 후 다음 이벤트를 확인합니다.

| 이벤트 | 수신자 |
|---|---|
| `RESERVATION_REQUESTED` | 해당 지점에 직접 연결된 활성 관리자 |
| `RESERVATION_APPROVED` | 관광객 |
| `RESERVATION_REJECTED` | 관광객 |
| `PAYMENT_DEADLINE_2_DAY`, `PAYMENT_DEADLINE_1_DAY` | 관광객 |
| `RESERVATION_PAYMENT_EXPIRED` | 관광객 |
| `PAYMENT_COMPLETED` | 관광객과 해당 지점 관리자 전체 |

푸시가 도착하지 않아도 데이터 상태가 변경되었는지는 목록·결제 조회 API로 재확인합니다. 로그아웃 요청에 현재 기기의 `X-FCM-Token`을 보내 저장된 값과 일치하면 토큰이 삭제되며, 헤더를 생략하면 토큰은 유지됩니다.

## 8. 테스트 완료 기준

- [ ] `/health/live`, `/health/ready` 정상
- [ ] Swagger의 최신 경로와 Schema로 관리자·고객 인증 성공
- [ ] 테스트 모델·지점·가격·배송 정보 조회 성공
- [ ] 예약 요청과 관리자 FCM 수신 확인
- [ ] 승인·거절·결제 전 취소 확인
- [ ] 활성 렌탈에서 마스킹된 여권 JPEG/PNG 업로드·조회 및 반납 후 접근 차단 확인
- [ ] PayPal Sandbox 주문·캡처·웹훅·중복 이벤트 확인
- [ ] 진행 중·완료 목록의 가격·배송·결제 정보 확인
- [ ] QR 인계 후 `HANDED_OVER`/`ON_RENT`, 반납 후 `RETURNED` 확인
- [ ] 동시 예약 시 한 건만 성공하는지 확인
- [ ] 주요 오류 코드와 권한 차단 확인

테스트 결과에는 요청 시각, API 경로, HTTP 상태 코드, `errorCode` 또는 주요 상태값, PayPal 이벤트 ID를 기록합니다. access token·refresh token·Firebase ID Token·FCM 토큰·PayPal Secret은 결과 문서나 로그에 기록하지 않습니다.
