# 나드리 고객 앱 프론트 연동 인수서

최종 수정일: 2026-09-28

이 문서는 나드리 고객 앱이 현재 백엔드와 연동할 때 필요한 규칙을 한 곳에 정리한 인수 문서입니다. 관리자 앱인 나드리고 API와 고객 앱 API를 혼용하지 않아야 합니다.

## 1. 기본 정보

| 항목 | 값 |
|---|---|
| 운영 기본 주소 | `https://na-dree.com` |
| Swagger | `https://na-dree.com/docs` |
| OpenAPI JSON | `https://na-dree.com/openapi.json` |
| 고객 API prefix | `/api/v1/nadree` |
| 관리자 API prefix | `/nadreego` |
| 고객 시간 기준 | 발리 `Asia/Makassar` |
| 결제 통화 | `USD` |

고객 앱은 `/nadreego` 관리자 경로를 호출하지 않습니다. 차량 위치용 Firebase 프로젝트와 FCM·고객 Firebase 인증용 Firebase 프로젝트도 서로 다릅니다.

## 2. 이번 백엔드 작업 내용

### 인증

- 고객 로그인 시 Firebase ID Token을 검증합니다.
- Firebase ID Token은 FCM 발송에 사용하는 Firebase 프로젝트와 같은 프로젝트에서 발급되어야 합니다.
- 토큰의 Firebase `uid`와 요청 body의 `UID`가 다르면 로그인하지 않습니다.
- Firebase ID Token 자체는 DB에 저장하지 않습니다.
- 로그인 성공 후 Nadree 전용 access token과 refresh token을 발급합니다.

### 응답 식별자 매핑

- `shopId`와 `spotMasterId`는 같은 지점의 영구 식별자입니다.
- `bookingId`와 `reservationId`는 같은 예약 식별자입니다.
- `bookedNo`는 화면 표시용 번호입니다. 내부 조회 키로 사용하지 않습니다.
- `spotCode`와 `unitCode`는 표시·검색용 지점 코드입니다.
- 차량 번호판과 개별 `vehicleId`는 고객 앱 응답에 노출하지 않습니다.

### 결제 상태 복구

결제 주문·캡처 응답이 유실된 경우를 위해 다음 API를 추가했습니다.

```http
GET /api/v1/nadree/rental/payment/{paymentId}
Authorization: Bearer <nadree-access-token>
```

본인 결제 건만 조회할 수 있습니다. 결제 상태는 DB와 검증된 PayPal 웹훅을 기준으로 반환합니다. `PENDING`이면 캡처를 즉시 다시 호출하지 말고 잠시 후 이 API를 다시 호출합니다.

### FCM 수신자

- 예약 요청·결제 완료 알림은 해당 지점에 직접 연결된 활성 대표·일반관리자에게 전송합니다.
- 동일 FCM 토큰이 수신자 목록에 중복되면 한 번만 전송합니다.
- 고객 승인·거절·결제 기한·결제 완료 알림은 고객 토큰으로 전송합니다.
- 로그아웃 요청에 현재 기기의 `X-FCM-Token`을 함께 보내고 저장된 값과 일치하면 FCM 토큰을 삭제합니다. 헤더를 보내지 않으면 세션만 로그아웃합니다.
- 현재 DB 구조는 계정 행마다 최신 FCM 토큰 1개를 보관합니다. 한 계정의 여러 기기에서 동시에 수신해야 하면 별도 기기 토큰 테이블이 필요하므로 별도 협의가 필요합니다.

## 3. 인증 흐름

### 3.1 Firebase 로그인 후 Nadree 로그인

프론트는 먼저 Firebase 클라이언트 SDK로 로그인하고 Firebase ID Token을 얻습니다.

```http
POST /api/v1/nadree/user/login
Authorization: Bearer <firebase-id-token>
Content-Type: application/json
```

```json
{
  "UID": "firebase-user-uid",
  "fcmToken": "current-device-fcm-token"
}
```

응답 예시는 다음과 같습니다.

```json
{
  "status": "success",
  "isNewUser": true,
  "accessToken": "<nadree-access-token>",
  "refreshToken": "<nadree-refresh-token>",
  "user": {
    "uidToken": "firebase-user-uid",
    "name": null,
    "age": null,
    "gender": null,
    "nationality": null,
    "ongoingRequests": []
  }
}
```

`Authorization`에 Firebase ID Token을 보내는 것은 로그인 요청에서만 사용합니다. 로그인 이후 고객 API에는 Nadree access token을 사용합니다.

### 3.2 고객 access token 사용

```http
Authorization: Bearer <nadree-access-token>
```

access token의 기본 유효시간은 1시간입니다. refresh token은 다음 헤더로 보냅니다.

```http
X-Refresh-Token: <nadree-refresh-token>
```

`POST /api/v1/nadree/user/refresh` 성공 시 access token과 refresh token이 모두 교체됩니다. 프론트는 두 값을 함께 저장해야 하며 이전 refresh token을 재사용하면 안 됩니다.

사용자 refresh token은 UID당 활성 1개입니다. 같은 UID로 다시 로그인하면 이전 refresh token은 폐기됩니다.

### 3.3 로그아웃

```http
POST /api/v1/nadree/user/logout
Authorization: Bearer <nadree-access-token>
X-Refresh-Token: <nadree-refresh-token>
```

로그아웃 성공 후 저장된 access·refresh token을 삭제합니다. 현재 기기의 `X-FCM-Token`을 보내 저장된 토큰과 일치하면 FCM 토큰도 삭제합니다. 헤더를 보내지 않으면 FCM 토큰은 유지됩니다.

## 4. 고객 API 호출표

| 기능 | 메서드 | 경로 | 인증 | 프론트 주의사항 |
|---|---|---|---|---|
| 로그인·회원 생성 | POST | `/api/v1/nadree/user/login` | Firebase ID Token | body 필드는 `UID` 대문자 유지 |
| 프로필 수정 | PATCH | `/api/v1/nadree/user/profile` | Nadree access | `NAME`, `Age`, `GENDER`, `NATIONALITY` 대소문자 유지 |
| 프로필 조회 | GET | `/api/v1/nadree/user/profile` | Nadree access | 로그인한 사용자의 최신 프로필 조회 |
| 차량·지점·가격 조회 | POST | `/api/v1/nadree/rental/availability` | 없음 | 로그인 전 호출 가능, 서버 가격을 그대로 사용 |
| 예약 요청 | POST | `/api/v1/nadree/rental/request` | Nadree access | `spotMasterId`와 `modelId`를 사용 |
| PayPal 주문 생성 | POST | `/api/v1/nadree/rental/payment/order` | Nadree access | 관리자 승인 후에만 호출 |
| PayPal 캡처 | POST | `/api/v1/nadree/rental/payment/capture` | Nadree access | `paymentId`만 전송 |
| 결제 상태 복구 | GET | `/api/v1/nadree/rental/payment/{paymentId}` | Nadree access | 응답 유실·`PENDING` 상태 확인용 |
| 진행 중 목록 | GET | `/api/v1/nadree/rental/ongoing` | Nadree access | `page`, `pageSize` 사용 |
| 완료 목록 | GET | `/api/v1/nadree/rental/completed` | Nadree access | `page`, `pageSize` 사용 |
| 결제 전 예약 취소 | POST | `/api/v1/nadree/rental/request/cancel` | Nadree access | body에 `reservationId` 사용 |
| 로그아웃 | POST | `/api/v1/nadree/user/logout` | access + refresh | 일치하는 `X-FCM-Token`을 보내면 현재 FCM 토큰 삭제 |
| 토큰 갱신 | POST | `/api/v1/nadree/user/refresh` | refresh | 새 access·refresh로 교체 |

## 5. 차량 조회·예약 요청

### 5.1 가용성 조회

```http
POST /api/v1/nadree/rental/availability
```

```json
{
  "startDate": "2026-10-01",
  "returnDate": "2026-10-04",
  "cc": 125,
  "deliveryRequested": false
}
```

배송을 선택하면 `pickupLocation`이 필수입니다. 반납 위치를 사용하는 경우 `returnLocation`도 보냅니다.

```json
{
  "startDate": "2026-10-01",
  "returnDate": "2026-10-04",
  "cc": 125,
  "deliveryRequested": true,
  "pickupLocation": "Jl. Raya Kuta No. 10, Badung",
  "returnLocation": "Jl. Raya Kuta No. 10, Badung"
}
```

날짜는 날짜만 보내며, 반납일은 시작일보다 늦어야 하고 최대 30일 범위입니다. 총액·배송비를 프론트에서 재계산하지 말고 응답의 `price`를 사용합니다.

응답 항목에는 다음 값이 포함됩니다.

```json
{
  "shopId": "spot-master-001",
  "modelId": "model-125-001",
  "spot": {
    "shopId": "spot-master-001",
    "spotMasterId": "spot-master-001",
    "spotCode": "CT1-ORG01-SP01",
    "spotName": "꾸따 지점"
  },
  "model": {
    "modelId": "model-125-001",
    "brand": "Honda",
    "modelName": "Vario 125",
    "cc": 125
  },
  "price": {
    "currency": "USD",
    "rentalDays": 3,
    "dailyFrom": 20,
    "dailyTo": 20,
    "deliveryTotal": 0,
    "totalFrom": 60,
    "totalTo": 60,
    "pricingTiers": []
  }
}
```

가용 차량이 없으면 오류 대신 `200`과 빈 `items`를 반환합니다.

### 5.2 예약 요청

```http
POST /api/v1/nadree/rental/request
Authorization: Bearer <nadree-access-token>
```

```json
{
  "spotMasterId": "spot-master-001",
  "modelId": "model-125-001",
  "startDate": "2026-10-01",
  "returnDate": "2026-10-04",
  "totalPrice": 60,
  "currency": "USD",
  "deliveryRequested": false
}
```

프론트가 화면에서 `shopId`를 사용하더라도 요청 body에는 `spotMasterId`를 보내야 합니다. `totalPrice`는 availability 응답에서 선택한 서버 계산 금액을 그대로 보냅니다. 고객이 임의 금액을 만들 수 없습니다.

예약 성공 시 주요 상태는 다음과 같습니다.

```json
{
  "status": "success",
  "reservationId": "res-001",
  "bookingId": "res-001",
  "bookedNo": "BOres-001",
  "reservationStatus": "REQUESTED",
  "paymentAvailability": "WAITING_APPROVAL",
  "paymentStatus": "WAITING_APPROVAL",
  "shopId": "spot-master-001",
  "spotMasterId": "spot-master-001",
  "modelId": "model-125-001"
}
```

같은 사용자·지점·모델·기간 요청이 60초 안에 다시 들어오면 `DUPLICATE_RENTAL_REQUEST`가 반환됩니다. 다른 사용자가 같은 마지막 차량을 먼저 예약하면 `RENTAL_UNAVAILABLE`이 반환됩니다.

## 6. 예약·결제 상태 처리

### 예약 상태

| 상태 | 프론트 표시·처리 |
|---|---|
| `REQUESTED` | 관리자 승인 대기. 결제 버튼을 표시하지 않음 |
| `APPROVED` | 결제 가능. `paymentAvailability=PAYMENT_REQUIRED`일 때 주문 생성 |
| `HANDED_OVER` | 렌트 진행 중. 고객 예약 취소 불가 |
| `RETURNED` | 완료 이력 |
| `REJECTED` | 관리자 거절 |
| `CANCELED` | 취소됨 |
| `EXPIRED` | 승인 후 결제 기한 만료로 자동 취소 |

### 결제 흐름

1. 예약 요청 성공 후 관리자의 승인을 기다립니다.
2. 진행 목록에서 `paymentAvailability=PAYMENT_REQUIRED`인지 확인합니다.
3. 승인 전에는 `/payment/order`를 호출하지 않습니다.
4. 주문 생성 응답의 `approvalUrl` 또는 PayPal SDK로 결제를 진행합니다.
5. 고객 승인 후 `/payment/capture`에 `paymentId`만 전송합니다.
6. `PENDING`이면 캡처를 다시 즉시 호출하지 않고 `/payment/{paymentId}`를 조회합니다.
7. 웹훅 처리 후 `PAID`로 바뀌면 출고 가능한 상태가 됩니다.

주문 생성 성공의 `CREATED`와 캡처 직후의 `PENDING`은 결제 완료가 아닙니다. 최종 완료 여부는 PayPal 웹훅으로 갱신됩니다.

### 결제 전 예약 취소

```http
POST /api/v1/nadree/rental/request/cancel
Authorization: Bearer <nadree-access-token>
```

```json
{
  "reservationId": "res-001",
  "reason": "일정 변경"
}
```

결제가 완료된 예약은 고객 취소 API에서 환불하지 않습니다. 결제 완료 후 취소·환불은 관리자 처리 영역입니다. 캡처가 진행 중인 `PENDING` 상태에서 취소하면 `PAYMENT_IN_PROGRESS`가 반환될 수 있습니다.

## 7. 목록 화면 구현 규칙

- `/ongoing`과 `/completed`는 `page` 기본값 1, `pageSize` 기본값 20, 최대 100입니다.
- 목록 항목의 지점·모델 ID는 최상위 `shopId`, `spotMasterId`, `modelId`를 우선 사용합니다.
- 예약이 있는 렌트는 `reservationId`와 `bookingId`가 함께 존재합니다.
- 예약 없는 현장 렌트는 `bookingId`가 없고 `rentalContractId`와 `bookedNo`를 사용합니다.
- `paymentAvailability`와 `payment.paymentStatus`를 구분합니다. 결제 버튼 표시 여부는 `paymentAvailability`를 기준으로 합니다.
- 앱이 백그라운드에서 복귀하거나 FCM을 수신하면 목록을 다시 조회합니다. FCM 도착만으로 예약·결제 상태를 확정하지 않습니다.

## 8. FCM 이벤트 처리

| 이벤트 | 수신자 | 주요 data |
|---|---|---|
| `RESERVATION_REQUESTED` | 해당 지점 관리자 전체 | `reservationId`, `bookedNo`, `reservationStatus=REQUESTED` |
| `RESERVATION_APPROVED` | 고객 | `reservationId`, `bookedNo`, `reservationStatus=APPROVED` |
| `RESERVATION_REJECTED` | 고객 | `reservationId`, `bookedNo`, `reservationStatus=REJECTED` |
| `PAYMENT_DEADLINE_2_DAY` | 고객 | `reservationId`, `daysRemaining=2` |
| `PAYMENT_DEADLINE_1_DAY` | 고객 | `reservationId`, `daysRemaining=1` |
| `RESERVATION_PAYMENT_EXPIRED` | 고객 | `reservationId`, `reservationStatus=EXPIRED` |
| `PAYMENT_COMPLETED` | 해당 지점 관리자 전체와 고객 | `reservationId`, `paymentId`, `paymentStatus=PAID` |

푸시 알림은 best-effort입니다. 푸시가 누락되어도 화면은 목록·결제 상태 API로 최신 상태를 다시 확인해야 합니다.

## 9. 오류 처리

모든 오류는 다음 형식입니다.

```json
{
  "status": "fail",
  "errorCode": "ERROR_CODE"
}
```

프론트에서 우선 처리해야 하는 오류는 다음과 같습니다.

| 오류 코드 | 처리 방법 |
|---|---|
| `FIREBASE_ID_TOKEN_REQUIRED` | Firebase ID Token을 포함해 로그인 재시도 |
| `FIREBASE_ID_TOKEN_INVALID` | Firebase 세션을 갱신한 뒤 다시 로그인 |
| `FIREBASE_UID_MISMATCH` | body UID와 Firebase 사용자 UID가 같은지 확인 |
| `INVALID_NADRI_USER_TOKEN` | access token 갱신 후 원래 GET 요청만 재시도 |
| `INVALID_REFRESH_TOKEN` | 로그인 화면으로 이동 |
| `RENTAL_UNAVAILABLE` | 차량 조회를 다시 수행 |
| `DUPLICATE_RENTAL_REQUEST` | 기존 예약 목록을 다시 조회 |
| `PRICE_QUOTE_MISMATCH` | availability를 다시 조회하고 새 가격 사용 |
| `RESERVATION_NOT_APPROVED_FOR_PAYMENT` | 관리자 승인 대기 화면으로 전환 |
| `PAYMENT_QUOTE_CHANGED` | 새 가격 확인 후 주문 재생성 |
| `PAYMENT_STATE_INVALID` | 결제 상태 조회 후 현재 상태에 맞게 표시 |
| `PAYMENT_IN_PROGRESS` | 결제 상태 조회 후 기다림 |
| `PAYMENT_ALREADY_PAID` | 새 주문을 만들지 않고 결제 완료로 표시 |
| `PAYMENT_REFUND_ADMIN_ONLY` | 관리자 취소·환불 절차 안내 |
| `DELIVERY_NOT_SUPPORTED` / `DELIVERY_REGION_NOT_SUPPORTED` | 배송 선택 해제 또는 주소 수정 |

예약 생성·결제 주문·결제 캡처·취소 같은 변경 요청은 네트워크 타임아웃만으로 자동 재전송하지 않습니다. 먼저 기존 예약 목록 또는 결제 상태 API로 결과를 확인합니다.

## 10. 프론트 구현 체크리스트

- [ ] Firebase 로그인 프로젝트가 FCM 발송 프로젝트와 같은지 확인
- [ ] 로그인 요청에 Firebase ID Token과 `UID`를 함께 전송
- [ ] 로그인 이후에는 Firebase 토큰이 아니라 Nadree access token 사용
- [ ] access·refresh token 교체 시 두 값을 함께 저장
- [ ] `shopId`를 예약 요청의 `spotMasterId`로 변환
- [ ] `bookingId`를 결제 주문 요청에 사용하지 않고 `reservationId` 사용
- [ ] 금액과 통화를 프론트에서 계산하지 않고 서버 응답 사용
- [ ] 결제는 `APPROVED`와 `PAYMENT_REQUIRED` 이후에만 시작
- [ ] `PENDING` 캡처를 즉시 재호출하지 않고 결제 상태 조회
- [ ] FCM 수신 후 API로 최신 상태 재조회
- [ ] 로그·분석 이벤트에 Firebase ID Token, access token, refresh token, FCM token을 기록하지 않음
- [ ] `MSP_DRIVER`, `vehicleId`, 차량 번호판을 고객 화면 계약에 사용하지 않음
- [ ] 운영 배포 후 `https://na-dree.com/openapi.json`과 실제 응답 필드를 다시 확인

## 11. 검증 현황

- 로컬 자동 테스트: **156개 통과**
- MySQL 전용 동시성 테스트: **6개 스킵**(별도 테스트 DB 미설정)
- Firebase 실토큰 검증, PayPal Sandbox 결제, 실제 기기 FCM 수신은 운영 환경에서 추가 확인해야 합니다.

백엔드 정본의 상세 규칙은 [나드리 고객 사용자 API 정본](nadri-user-api-design.md)을 참조합니다.
