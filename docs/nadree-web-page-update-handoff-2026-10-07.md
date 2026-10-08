# 나드리 웹페이지 업데이트 전달 문서

최종 수정일: 2026-10-07

웹페이지에서 렌탈 API를 확인할 수 있도록 추가한 테스트 데이터와 프론트 연동 사항만 정리한 문서입니다. 관리자 앱 전용 변경사항과 여권 이미지 API 내용은 포함하지 않습니다.

## 1. 접속 정보

| 항목 | 값 |
|---|---|
| API 기본 주소 | `https://na-dree.com` |
| Swagger UI | `https://na-dree.com/docs` |
| OpenAPI JSON | `https://na-dree.com/openapi.json` |
| 고객 API prefix | `/api/v1/nadree` |
| 웹 Origin | `https://www.riderlog-lte.com:50045` |

웹 배포 주소가 바뀌면 백엔드 `.env`의 Origin도 정확히 변경해야 합니다.

```env
NADREE_CORS_ORIGINS=https://www.riderlog-lte.com:50045
```

현재 CORS는 쿠키를 사용하지 않는 방식입니다. `Authorization`, `Content-Type`, `X-Refresh-Token`, `X-FCM-Token` 헤더를 허용하며 `credentials: omit` 기준으로 호출합니다.

## 2. 웹 테스트 데이터

`migrations/test_seed_web_requirements.sql`을 적용하면 아래 데이터가 생성됩니다. 테스트 DB에서만 사용하며, 모든 데이터는 `NRTEST-WEB-*` 식별자를 사용합니다.

| 구분 | 식별자 | 내용 |
|---|---|---|
| 테스트 지점 | `00000000-0000-4000-8000-000000000101` | `shopId`, `spotMasterId` 공통 값 |
| 웹 모델 | `NRTEST-WEB-MODEL-125` | Honda Vario Web Test 125, 125cc, 배송 가능 |
| 웹 BASIC 차량 | `NRTEST-WEB-BASIC-125` | BASIC 가격, 대여 가능 |
| 웹 PREMIUM 차량 | `NRTEST-WEB-PREMIUM-125` | PREMIUM 가격, 일일 45 USD, 대여 가능 |
| 배송 미지원 모델 | `NRTEST-WEB-MODEL-ND` | SYM Cruiser No Delivery Test, 125cc |
| 배송 미지원 차량 | `NRTEST-WEB-NODELIVERY` | 배송 요청 시 오류 확인용 |
| Kuta 배송지역 | `NRTEST-KUTA` / `990000001` | 시작 10 + 반납 10 = 왕복 20 USD |
| Canggu 배송지역 | `NRTEST-CANGGU` / `990000002` | 시작 15 + 반납 15 = 왕복 30 USD |

모델 이미지 값은 웹에서 바로 확인할 수 있는 테스트용 `placehold.co` URL입니다.

## 3. 고객 인증

고객 API는 Firebase ID Token과 Nadree access token을 사용합니다.

```http
POST /api/v1/nadree/user/login
Authorization: Bearer <firebase-id-token>
Content-Type: application/json
```

```json
{
  "UID": "<firebase-token의 uid>"
}
```

로그인 응답의 `accessToken`을 이후 고객 API에 사용합니다.

```http
Authorization: Bearer <nadree-user-access-token>
```

Firebase 테스트 계정이 실제로 생성되어 있어야 하며, 임의의 `NRTEST-USER-001` 값을 Firebase Token의 UID와 다르게 보내면 안 됩니다.

## 4. 차량·가격 조회

### 4.1 BASIC/PREMIUM 조회

```http
POST /api/v1/nadree/rental/availability
Content-Type: application/json
```

```json
{
  "startDate": "2026-10-10",
  "returnDate": "2026-10-13",
  "cc": 125,
  "deliveryRequested": true,
  "pickupLocation": "Canggu Test Area, Bali",
  "returnLocation": "Canggu Test Area, Bali"
}
```

`NRTEST-WEB-MODEL-125`의 예상 가격은 다음과 같습니다.

| 선택 | 일일 가격 | 3일 대여료 | Canggu 왕복 포함 총액 |
|---|---:|---:|---:|
| BASIC | 25 USD | 75 USD | 105 USD |
| PREMIUM | 45 USD | 135 USD | 165 USD |

응답의 `price.totalOptions`는 `[105, 165]`가 되며, 프론트는 이 배열에 없는 임의의 금액을 전송하면 안 됩니다. 배송을 선택하지 않으면 총액은 `[75, 135]`입니다.

응답에서 확인할 주요 값:

```json
{
  "modelId": "NRTEST-WEB-MODEL-125",
  "model": {
    "brand": "Honda",
    "modelName": "Vario Web Test 125",
    "cc": 125,
    "modelImageKey": "https://placehold.co/640x480/png?text=NRTEST-WEB-125"
  },
  "price": {
    "currency": "USD",
    "dailyFrom": 25,
    "dailyTo": 45,
    "deliveryTotalFee": 30,
    "totalOptions": [105, 165],
    "totalFrom": 105,
    "totalTo": 165
  }
}
```

### 4.2 배송 미지원 확인

`NRTEST-WEB-MODEL-ND`를 선택하거나 해당 모델이 조회된 뒤 배송 요청을 켜면 다음 오류를 확인할 수 있습니다.

```text
DELIVERY_NOT_SUPPORTED
```

배송을 선택하지 않은 경우에는 배송 미지원 모델도 기본 대여 조회가 가능합니다.

### 4.3 배송지역 불일치 확인

픽업 주소를 Canggu, 반납 주소를 Kuta로 다르게 보내면 다음 오류를 확인할 수 있습니다.

```json
{
  "pickupLocation": "Canggu Test Area, Bali",
  "returnLocation": "Kuta Test Area, Bali"
}
```

예상 오류:

```text
DELIVERY_REGION_NOT_SUPPORTED
```

현재 테스트 구현은 주소에 `Canggu Test Area`, `Kuta Test Area`, `NRTEST-CANGGU`, `NRTEST-KUTA` 문자열이 포함되는지로 배송지역을 판정합니다.

## 5. 예약 요청

availability 응답에서 확인한 `spotMasterId`, `modelId`, `totalOptions` 중 하나를 사용합니다.

```http
POST /api/v1/nadree/rental/request
Authorization: Bearer <nadree-user-access-token>
Content-Type: application/json
```

```json
{
  "spotMasterId": "00000000-0000-4000-8000-000000000101",
  "modelId": "NRTEST-WEB-MODEL-125",
  "startDate": "2026-10-25",
  "returnDate": "2026-10-28",
  "totalPrice": 105,
  "currency": "USD",
  "deliveryRequested": true,
  "pickupLocation": "Canggu Test Area, Bali",
  "returnLocation": "Canggu Test Area, Bali"
}
```

예상 결과:

- `reservationStatus`: `REQUESTED`
- `paymentAvailability`: `WAITING_APPROVAL`
- `deliveryRequestType`: `START_AND_RETURN`
- `price.finalTotal`: 요청한 유효 금액

대여 기간은 1일 이상 30일 이하만 허용됩니다. 동일 사용자가 같은 차량 모델·기간으로 60초 안에 중복 요청하면 `DUPLICATE_RENTAL_REQUEST`가 반환됩니다.

## 6. 결제 연동 순서

관리자 승인 후 기존 결제 API를 사용합니다.

1. `POST /api/v1/nadree/rental/payment/order`
2. 응답의 `approvalUrl`로 PayPal Sandbox 결제
3. `POST /api/v1/nadree/rental/payment/capture`
4. `GET /api/v1/nadree/rental/payment/{paymentId}`로 최종 상태 확인

결제 금액은 프론트에서 임의 계산하지 않고 availability 또는 예약 응답의 서버 계산 값을 사용합니다. 환불 정보는 응답 최상위의 `refundStatus`, `refundedAmount`를 우선 사용합니다.

## 7. Swagger 업데이트 내용

Swagger 예시는 다음 웹 테스트 데이터 기준으로 변경되었습니다.

- 고객 availability 모델: `NRTEST-WEB-MODEL-125`
- BASIC/PREMIUM 총액: `[105, 165]`
- Canggu 배송지역: `990000002`, 시작·반납 각 15 USD
- 배송 미지원 모델·차량
- 관리자 배송지역·차량 목록에 웹 테스트 행 추가
- Swagger 설명에 웹 테스트 모델·차량·배송지역 목록 추가

코드 배포 후 서버를 재시작해야 `/docs`와 `/openapi.json`에 변경된 예시가 표시됩니다.

## 8. 현재 지원 범위와 제한사항

현재 테스트 데이터로 확인할 수 있는 기능:

- 125cc 차량 검색
- BASIC/PREMIUM 가격 선택
- 30일 이내 대여기간 검증
- 배송 가능·배송 미지원 모델 검증
- Kuta/Canggu 배송지역 일치·불일치 검증
- 서버 계산 금액을 사용한 예약 요청
- 승인 후 결제 상태 조회

현재 별도 구현되지 않은 웹 요구사항:

- `Idempotency-Key` 기반 응답 유실 복구 API
- Google Places `placeId` 또는 좌표를 이용한 정밀 배송지역 판정
- 상품 상세의 공식 이미지 URL·영업시간·패키지 설명 전용 필드/API
- 매장 문의·채팅 API

위 항목은 테스트 데이터를 추가하는 것만으로 동작하지 않으며, 별도 API 계약과 백엔드 구현이 필요합니다.

## 9. 테스트 DB 시드 적용

기존 시드 2개를 먼저 적용한 뒤 웹 시드를 적용합니다.

```sh
mysql -h www.riderlog-lte.com \
  -P 50020 \
  -u Datateam \
  -p \
  RIDERLOG_V2_DATA_TEST \
  < migrations/test_seed_web_requirements.sql
```

실행 후 `NRTEST-WEB-MODEL-125`, `NRTEST-WEB-BASIC-125`, `NRTEST-WEB-PREMIUM-125`, `NRTEST-CANGGU`가 조회되면 적용이 완료된 것입니다.

이 SQL은 `RIDERLOG_V2_DATA_TEST` 같은 별도 테스트 DB에서만 실행하고 운영 실데이터 DB에는 실행하지 않습니다.
