# 현장·외부 결제 전환 — 고객 앱·관리자 앱 전달 사항

작성일: 2026-10-28. 이번 변경은 신규 예약의 온라인 결제 단계를 생략하고, 관리자 승인으로 예약을 확정하는 정책이다. **예약 확정은 수납 완료가 아니다.** 현장 수납 확인과 외부 환불은 지점에서 별도로 관리한다.

**2026-10-28 07:03 UTC 서버 적용 완료.** API를 재시작했고 공개 차량 조회에서 `newReservationPaymentMethod=EXTERNAL`, `onlinePaymentEnabled=false` 및 새 OpenAPI 계약을 확인했다. 기존 테스트 계정으로 신규 예약부터 테스트할 수 있다. 기존 API 경로·로그인·예약 요청 형식·가격·배송·QR 원문 전달 방식은 유지한다. 이번 서버 반영에서는 계정 로그인·실제 예약 생성·수납·환불·푸시를 실행하지 않았다.

## 1. 공통 처리 기준

| 구분 | `paymentMethod=EXTERNAL` | `paymentMethod=PAYPAL` |
| --- | --- | --- |
| 의미 | 현장·외부 결제 예약 | 기존 온라인 결제 예약 |
| 예약 확정 | 관리자 승인으로 `APPROVED` | 기존 승인·온라인 결제 정책 유지 |
| 고객 온라인 결제 화면 | 표시하지 않음 | 온라인 중단 중에는 표시하지 않음 |
| 수납 완료 판단 | 이 API에서 판단하지 않음 | 저장된 실제 결제 상태 사용 |
| 인계 | 예약 기간·권한·QR·차량·재고 등 기존 조건 검사 | 위 조건과 실제 정상 결제·미환불 상태 검사 |
| 취소·환불 | 예약 취소만 처리. 외부 수납의 환불은 지점에서 관리 | 기존 PG 환불 정책과 처리 상태 유지 |
| 결제 기한 | 없음 | 기존 예약에 저장·계산되는 기한 유지 |

결제 방식은 예약 생성 당시 확정되어 유지된다. 이후 온라인 기능을 재개해도 `EXTERNAL` 예약을 PayPal 예약으로 바꾸지 않는다. 클라이언트는 예약 생성·수정 요청에 `paymentMethod`를 추가하지 않는다. 임의 필드 전달은 `422 INVALID_INPUT`이다.

`onlinePaymentEnabled`는 온라인 기능의 사용 가능 여부이고 수납 상태가 아니다. 예약별 `paymentMethod`를 먼저 확인한다. 전역 기능이 다시 켜져도 `EXTERNAL` 예약에는 PayPal 버튼을 만들지 않는다. 예약에 연결되지 않은 기존 방문 렌탈은 `paymentMethod=null`일 수 있다.

## 2. 고객 앱 흐름

```text
차량 조회·가격 확인 → 예약 요청(REQUESTED)
→ 관리자 승인(APPROVED, 예약 확정)
→ 지점 안내에 따른 현장·외부 결제
→ 예약 기간에 관리자 QR 인계(HANDED_OVER / ON_RENT)
→ 관리자 반납 처리(RETURNED)
```

관리자 승인 직후 “예약 확정”으로 표시한다. 승인만으로 “결제 완료” 또는 “렌트 시작”으로 표시하지 않는다. 수납 확인을 위한 새 버튼·수납 등록 API·외부 결제 자동 확인 기능은 제공하지 않는다.

고객 인증은 기존 Firebase 인증 → 백엔드 로그인 → access/refresh 사용 방식을 유지한다. 고객 API 경로는 `/api/v1/nadree/rental`이다. QR 인계·반납은 관리자 앱에서 수행한다.

### 차량 조회와 예약 생성

`POST /availability` 응답 최상위에 다음 필드를 추가한다. 상품 선택 전에 결제 방식을 안내할 수 있다.

```json
{
  "status": "success",
  "newReservationPaymentMethod": "EXTERNAL",
  "onlinePaymentEnabled": false,
  "items": []
}
```

`items`는 기존 차량·가격·배송 조회 결과다. 견적 금액, 가격 옵션, 통화, 배송 주소·요금표 선택은 기존 계약대로 전달한다. 현장 결제라고 금액을 0으로 보내지 않는다.

`POST /request` 요청 형식은 유지한다. 응답의 주요 필드는 다음과 같다. 이 예시는 일부 필드만 표시한다.

```json
{
  "status": "success",
  "reservationId": "<reservation-id>",
  "bookingId": "<reservation-id>",
  "bookedNo": "BO<reservation-id>",
  "reservationStatus": "REQUESTED",
  "vehicleAssignmentStatus": "SOFT_HOLD",
  "paymentMethod": "EXTERNAL",
  "onlinePaymentEnabled": false,
  "paymentAvailability": "WAITING_APPROVAL",
  "paymentStatus": null,
  "paymentDeadline": null,
  "canPay": false,
  "canCapture": false
}
```

**예약 생성 응답의 `paymentStatus`가 `null`일 수 있도록 앱 모델을 수정해야 한다.** 승인 대기는 `reservationStatus=REQUESTED` 또는 `paymentAvailability=WAITING_APPROVAL`로 판단한다.

### 승인 후 목록·상세

다음 응답에 결제 방식과 온라인 가능 여부가 포함된다.

- `GET /ongoing`
- `GET /completed`
- `GET /reservations/{reservationId}`
- 로그인 응답의 `user.ongoingRequests`

현장 예약이 승인된 경우 목록 항목 또는 상세 `item`의 핵심 값은 다음과 같다.

```json
{
  "reservationStatus": "APPROVED",
  "paymentMethod": "EXTERNAL",
  "onlinePaymentEnabled": false,
  "paymentAvailability": "EXTERNAL_PAYMENT",
  "paymentStatus": null,
  "payment": null,
  "paymentDeadline": null,
  "canPay": false,
  "canCapture": false,
  "cannotPayReason": "ONLINE_PAYMENT_NOT_REQUIRED"
}
```

`EXTERNAL_PAYMENT`는 현장·외부 결제 방식이라는 뜻이다. 미수금 확정·무료·수납 완료를 의미하지 않는다. `payment=null`도 정상이다. `paymentId`를 만들어 넣거나 `PAID`로 바꾸지 않는다. 종료 내역은 `reservationStatus`·`rentalStatus`로 구분하고, 결제 방식만으로 진행 중 예약이라고 판단하지 않는다.

### 제거하거나 변경할 화면 동작

- 현장 예약의 “결제하기”, PayPal 승인 화면, capture 요청·재시도·결제 폴링을 제거한다.
- 결제 카운트다운, “3일 이내 결제”, 미결제 자동 취소 문구를 표시하지 않는다.
- 기존 가격·배송비·예약 상태·인계·반납 내역은 계속 표시한다.
- 현장 예약의 취소 확인 문구에는 PayPal 90%·0% 자동 환불을 안내하지 않는다. 외부 수납 환불은 지점 문의로 안내한다.

`POST /request/cancel`은 기존 본인 소유·인계 전 조건을 유지한다. 현장 예약의 정상 취소 응답은 `refundStatus=NOT_REQUIRED`, `refundRequestedAmount=0`, `refundReason=EXTERNAL_PAYMENT_MANAGED_BY_SHOP`이다. 이를 “외부 결제 환불 완료”로 표시하지 않는다. 예약 취소 시 배정은 해제된다.

## 3. 관리자 앱 흐름

`POST /nadreego/booking/action`의 요청은 유지한다.

```json
{ "bookedNo": "BO<reservation-id>", "action": "APPROVE" }
```

현장 예약은 PayPal 판매자 미연결 상태에서도 승인할 수 있다. 승인 전에 판매자 연결 화면으로 보내는 앱 자체 검사를 제거한다. 기존 관리자 권한·지점 범위·재고·차량 배정 검사는 유지된다.

승인 응답의 `data`, `POST /nadreego/booking/select`의 각 항목, `POST /nadreego/main/calendar`의 예약 이벤트에 다음 필드를 제공한다.

| 필드 | 처리 |
| --- | --- |
| `paymentMethod` | 현장·외부 결제와 기존 온라인 예약 구분 |
| `onlinePaymentEnabled` | 온라인 기능 사용 가능 여부 |
| `canHandOver` | 현재 배정 차량을 기준으로 조회 시점에 인계 가능한지 |
| `handoverBlockedReason` | 인계 불가 사유. 가능하면 `null` |
| `availableActions` | 목록·캘린더의 허용 액션. `RENT_APPROVE`가 있을 때 인계 동작 제공 |

승인 액션 응답에는 `availableActions`가 없으며 `data.canHandOver`를 사용하거나 목록을 다시 조회한다. `APPROVED`만 보고 인계 버튼을 만들지 않는다. 예약 시작 전에는 현장 예약도 `OUTSIDE_RESERVATION_PERIOD`로 인계할 수 없다.

차량 목록의 `currentBooking`에도 결제 방식과 인계 가능 여부를 제공한다. 관리자 고객 이력의 항목에도 결제 방식이 추가된다. 캘린더에서 다른 하위 지점을 조회한 경우 현재 관리자 지점으로 실행할 수 없는 인계 액션은 제공하지 않는다.

인계는 기존 `POST /nadreego/rent/approve`에 `bookedNo`와 QR 원문인 `qrCode`를 전달한다. 저장된 QR 해시를 보내지 않는다. QR 전용 차량과 QR+센서 차량을 모두 지원하며, 센서 없는 차량도 정상 인계할 수 있다. 호출 시 서버가 모든 조건을 다시 검증하므로 조회 이후 차량·예약이 바뀌면 오류에 따라 새로 조회한다. 호환 차량으로 재배정하는 기존 QR 처리도 실제 요청에서 다시 검증한다.

인계 전 관리자 지점 귀책 취소는 기존 `action=CANCEL`을 사용한다. 현장 예약은 PG 환불 없이 취소·재고 해제·채팅 종료를 처리한다. 실제 현장 수납의 환불 여부는 지점에서 별도 확인한다.

### 판매자 연결 화면

`GET /nadreego/shop/paypal-merchant?spotMasterId=...`에 `onlinePaymentEnabled`와 `newReservationPaymentMethod`가 추가된다. 온라인 중단 중에는 연결 시작·완료 처리 버튼을 숨긴다. 저장된 과거 판매자 정보 조회와 기존 직접 대표의 연결 해제 경로는 보존한다. 판매자 연결 정보를 현장 예약의 승인 필수 조건으로 사용하지 않는다.

## 4. 기존 온라인 예약·구버전 호출 처리

전환 이전 온라인 예약은 `PAYPAL`로 유지된다. 현장 예약으로 임의 변경하거나 실제 결제 상태를 덮어쓰지 않는다. 미결제 온라인 예약을 현장 방식으로 진행하려면 기존 거래 상태를 확인하고 정상 취소 후 새 예약을 요청한다. 고객이 자동으로 취소·재신청하도록 구현하지 않는다.

온라인 중단 중에는 구버전 앱·웹의 다음 호출도 서버에서 차단한다.

| 호출 | HTTP·오류 코드 | 앱 처리 |
| --- | --- | --- |
| 현장 예약에 주문 생성·capture 요청 | `409 ONLINE_PAYMENT_NOT_REQUIRED` | 온라인 결제 동작 종료, 예약 상세 조회 |
| 기존 온라인 예약의 주문 생성·capture·재시도 | `409 ONLINE_PAYMENT_DISABLED` | 자동 재시도 중단, 기존 거래 조회·지점 문의 |
| 판매자 연결 start·verify | `409 ONLINE_PAYMENT_DISABLED` | 연결 흐름 종료 |
| 현장 예약에 예상 밖 결제 기록 존재 | `409 PAYMENT_STATE_INCONSISTENT` | 자동 상태 수정·인계·환불 시도 금지, 운영 확인 |
| 잘못된 예약 결제 방식 저장값 | `409 RESERVATION_PAYMENT_METHOD_INVALID` | 우회하지 않고 운영 확인 |

인증 누락·소유권·다른 지점 오류는 기존 401/403/404 처리를 유지한다. 온라인 기능이 다시 켜져도 현장 예약의 주문·capture는 허용되지 않는다.

기존 `GET /api/v1/nadree/rental/payment/{paymentId}`는 유지한다. 온라인 중단 중에는 DB 기록만 반환하고 PayPal 요청을 보내지 않는다.

- `paymentStateSource=DATABASE`: `paymentStatus`는 서버 저장 상태다.
- `paymentUpdatedAt`: 저장된 결제 갱신 시각이다. 원본 DB 시각은 UTC이며 타임존 오프셋이 없는 ISO 형식일 수 있다.
- `providerStateChecked=false`, `paypalOrderStatus=null`: 해당 조회에서 PayPal 상태를 새로 확인하지 않았다는 뜻이다. PG 실패로 해석하지 않는다.
- `canPay=false`, `canCapture=false`, `approvalUrl=null`: 온라인 중단 중에는 결제를 진행하지 않는다.
- `nextAction=NONE`: 중단된 미캡처 주문에 후속 결제 동작을 제공하지 않는다.
- `nextAction=WAIT`: 이미 요청된 캡처의 정산 반영을 기다리는 경우다. 새 capture 요청 허용이 아니다.
- `nextAction=REVIEW`: 기존 캡처 요청의 결과 확인 등이 필요하다. 재청구하지 않는다.
- `nextAction=DONE`: 저장 상태가 `PAID/PARTIALLY_REFUNDED/REFUNDED`다. 실제 `paymentStatus`와 환불 필드를 함께 표시한다.

이미 청구된 기존 온라인 거래의 웹훅·정산·환불 처리는 보존된다. 앱이 이 기록을 현장 결제 표시로 덮어쓰면 안 된다.

## 5. 알림·채팅과 앱 인수 항목

승인 푸시의 이벤트명 `RESERVATION_APPROVED`는 유지하고 데이터에 `paymentMethod`를 추가한다. 현장 예약의 문구는 예약 확정·현장/외부 결제 안내이며 결제 마감·자동 만료 안내를 보내지 않는다. 앱이 자체 알림 문구를 구성한다면 같은 방식으로 수정한다.

예약 채팅의 인증·세션·Firestore 계약은 유지한다. 요청·승인·인계·취소·반납에 따른 동기화·종료도 기존 흐름을 사용한다.

프론트 인수에서는 다음을 확인한다.

1. 기존 계정으로 현장 예약 생성 → 승인 후 예약 확정 표시. 신규 계정 생성 불필요.
2. 미연결 지점의 대표·일반관리자 승인과 기존 지점 접근 차단.
3. QR_ONLY 및 QR_WITH_SENSOR 차량의 예약 기간 내 인계 → 반납.
4. 결제 버튼·카운트다운·capture/결제 폴링이 실행되지 않음.
5. 취소 후 종료 내역·배정 해제·예약 채팅 종료 표시.
6. 기존 온라인 결제·환불 이력 보존과 중단 오류에서 자동 재시도하지 않음.
7. 서버의 온라인 기능을 재개하더라도 이전 현장 예약은 계속 현장 방식으로 표시.

실제 앱 화면·실기기 푸시 수신·App Check 종단은 이번 서버 격리 검증과 별도 인수 항목이다.

## 6. 지금 사용할 수 있는 테스트 예시

2026-10-28 07:03 UTC 실제 공개 조회에서 기존 테스트 지점의 예약 가능 옵션 5개를 확인했다. 다음은 그중 최상위 테스트 지점의 PREMIUM 예약 예시다. 고객 앱의 기존 테스트 계정으로 로그인한 뒤 호출한다. 예시는 아직 생성하지 않은 예약이며 실제 요청 직전에 availability로 가격·재고를 다시 확인한다.

```http
POST /api/v1/nadree/rental/request
Authorization: Bearer <기존 테스트 고객의 access token>
Content-Type: application/json

{
  "spotMasterId": "00000000-0000-4000-8000-000000000101",
  "modelId": "NRTEST-WEB-MODEL-125",
  "startDate": "2026-11-04",
  "returnDate": "2026-11-06",
  "priceOptionId": "PREMIUM:45",
  "totalPrice": 90,
  "currency": "USD",
  "deliveryRequested": false
}
```

응답은 `paymentMethod=EXTERNAL`, `reservationStatus=REQUESTED`, `paymentStatus=null`이어야 한다. 해당 지점 관리자가 응답의 bookedNo로 APPROVE한 뒤 고객 상세에서 APPROVED/EXTERNAL_PAYMENT를 확인한다. PayPal 주문·구매자 승인·capture는 호출하지 않는다. **QR 인계는 예약 시작 이후에만 가능하며 즉시 인계를 위한 날짜 예외는 추가하지 않았다.**

추가 테스트 2호점도 같은 기간 BASIC 56 USD 또는 PREMIUM 96 USD의 조회 옵션을 확인했다. 기존 [2호점 테스트 정보](test-branch2-app-handoff-2026-10-23.md)의 계정·차량·QR을 사용할 수 있으며, 결제 흐름은 이번 문서가 이전 온라인 안내보다 우선한다. 2호점의 실제 계정 로그인·예약 승인·인계는 이번 재시작 확인에서 실행하지 않았다.
