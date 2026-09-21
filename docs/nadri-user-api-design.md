# 나드리 고객 사용자 API 설계 초안

최종 수정일: 2026-09-18  
상태: **고객 API 1~11·FCM 토큰 및 예약 업무 알림 구현 완료(로컬 검증), PayPal·FCM 서비스 계정 실연동 및 운영 DB 적용 대기**

이 문서는 관리자 앱인 나드리고 API와 분리된 **나드리 고객 앱 전용 사용자 API** 설계다. 기존 RiderLog의 운전자 기능과 `MSP_DRIVER` 및 운전자 관련 테이블은 이 API에서 조회하거나 변경하지 않는다. 사용자 프로필은 독립적인 `MSP_RENTAL_USER`에, 인증 세션은 `MSP_RENTAL_USER_REFRESH_TOKEN`에 기록한다.

## 1. 설계 범위

| 번호 | API | 목적 |
|---:|---|---|
| 1 | `POST /api/v1/nadri/user/login` | `UID`로 기존 사용자를 찾거나 새 렌탈 사용자를 생성한 뒤 로그인 응답 반환 |
| 2 | `PATCH /api/v1/nadri/user/profile` | 로그인 사용자의 이름·나이·성별·국적 갱신 |
| 3 | `POST /api/v1/nadri/rental/availability` | 대여 기간·배기량·배송 조건에 맞는 지점·차량 모델·가격 조회 |
| 4 | `POST /api/v1/nadri/rental/request` | 선택한 지점·모델·기간·가격·배송정보로 예약 요청 생성 |
| 5 | `POST /api/v1/nadri/rental/payment/order` | 생성된 예약의 서버 확정 금액으로 PayPal 주문 생성 |
| 6 | `POST /api/v1/nadri/rental/payment/capture` | 고객 승인 후 PayPal 주문 캡처 요청 및 결제 상태 반환 |
| 7 | `GET /api/v1/nadri/rental/ongoing` | 현재 진행 중인 렌트·예약 목록 조회 |
| 8 | `GET /api/v1/nadri/rental/completed` | 반납 완료된 렌트 목록 조회 |
| 9 | `POST /api/v1/nadri/rental/request/cancel` | 결제 전 예약 요청 취소 |
| 10 | `POST /api/v1/nadri/user/logout` | 고객 access·refresh token 폐기. GET도 호환 지원 |
| 11 | `POST /api/v1/nadri/user/refresh` | 고객 refresh token 회전 및 access token 재발급. GET도 호환 지원 |

URL은 나드리고 관리자 API의 `/nadreego/admin/*`와 충돌하지 않도록 `/nadri/user/*`와 `/nadri/rental/*` 네임스페이스로 분리한다.

차량 상세 조회 API는 별도로 만들지 않는다. 검색 응답의 `price.pricingTiers`에 해당 모델에 적용된 배기량 요금 티어를 함께 넣어 한 번의 조회로 지점·모델·가격·티어를 확인하도록 한다.

## 2. 공통 데이터 매핑

| 앱 요청 필드 | 저장 컬럼 | 규칙 |
|---|---|---|
| `UID` | `MSP_RENTAL_USER.uid_token` | 1~36자, 공백만 입력할 수 없음. 앱이 제공하는 사용자 식별자 |
| `NAME` | `MSP_RENTAL_USER.name` | 최대 100자 |
| `Age` | `MSP_RENTAL_USER.age` | 정수 0~150 |
| `GENDER` | `MSP_RENTAL_USER.gender` | `M`, `F`, `OTHER` 중 하나 |
| `NATIONALITY` | `MSP_RENTAL_USER.nationality` | ISO 3166-1 alpha-2 대문자 두 글자(예: `KR`) |
| `fcmToken` | `MSP_RENTAL_USER.fcm_token` | 앱이 발급한 최신 FCM 토큰. 선택 입력이며 갱신 시각도 저장 |

요청 필드의 대소문자는 앱 계약에 맞춰 위 표와 같이 유지한다. 응답은 기존 나드리 API 규칙에 맞춰 `uidToken`, `name`, `age`, `gender`, `nationality`를 사용한다.

## 3. API 1 — UID 로그인·신규 사용자 생성

### 요청

`POST /api/v1/nadri/user/login`

```json
{
  "UID": "app-user-001",
  "fcmToken": "<customer-device-fcm-token>"
}
```

헤더에는 `Content-Type: application/json`을 사용한다. 신규 생성 시 프로필 값은 함께 받지 않으며, API 2에서 별도로 갱신한다.

### 처리 규칙

1. `MSP_RENTAL_USER.uid_token = UID`를 행 잠금으로 조회한다.
2. 행이 있으면 해당 사용자 프로필을 반환하고 `isNewUser=false`로 응답한다.
3. 행이 없으면 `uid_token`만 INSERT하고 `name`, `age`, `gender`, `nationality`는 NULL로 둔다.
4. 동시에 같은 UID가 생성된 경우 기본키 충돌로 실패시키지 않고 기존 행을 다시 조회해 동일한 로그인 응답을 반환한다.
5. 어떤 단계에서도 `MSP_DRIVER` 또는 `MSP_DRIVER_SPOT_HISTORY`를 조회·변경하지 않는다.
6. 로그인 상태 유지를 위해 UID를 subject로 하는 나드리 고객용 access token과 고객 전용 refresh token을 발급한다. 관리자용 토큰과 issuer·audience·저장 테이블을 분리한다.
7. 로그인 시 해당 UID의 기존 활성 고객 refresh token을 폐기하고 새 토큰을 하나만 저장한다.
8. 로그인 응답을 만들 때 `MSP_RESERVATION.uid_token`을 조회해 `reservation_status`가 `REQUESTED`, `APPROVED`, `HANDED_OVER`인 진행 중 요청을 함께 조회한다. `RETURNED`, `REJECTED`, `CANCELED`, `EXPIRED`는 제외한다.
9. 진행 중 요청은 지점·모델·기간·배송 유형·가격 요약을 `user.ongoingRequests` 배열에 넣는다. 배송 주소는 본인 로그인 응답에만 포함하며 푸시나 로그에는 복사하지 않는다.
10. 연결된 `MSP_RENTAL_PAYMENT`가 있으면 최신 결제 시도의 `paymentId`, `paymentStatus`, PayPal 주문·캡처 ID, 결제 금액·통화를 `ongoingRequests[].payment`에 함께 반환한다. 결제 시도가 없으면 `payment`는 `null`이다.
11. `ongoingRequests[].paymentAvailability`는 예약 상태와 결제 상태를 조합해 반환한다. `REQUESTED`는 `WAITING_APPROVAL`, `APPROVED`인데 결제 시도가 없거나 완료되지 않았으면 `PAYMENT_REQUIRED`, 결제 주문 생성·캡처 대기 중이면 `CREATED` 또는 `PENDING`, 결제 완료면 `PAID`다. 고객 앱은 `PAYMENT_REQUIRED`일 때만 API 5를 호출한다.
12. 요청에 `fcmToken`이 있으면 `MSP_RENTAL_USER.fcm_token`과 갱신 시각을 저장한다. 토큰은 응답이나 로그에 포함하지 않는다.

### 성공 응답 — 기존 사용자

```json
{
  "status": "success",
  "isNewUser": false,
  "accessToken": "<nadri-user-access-token>",
  "refreshToken": "<nadri-user-refresh-token>",
  "user": {
    "uidToken": "app-user-001",
    "name": "홍길동",
    "age": 31,
    "gender": "M",
    "nationality": "KR",
    "ongoingRequests": [
      {
        "reservationId": "res-20261001-0001",
        "bookedNo": "BOres-20261001-0001",
        "reservationStatus": "REQUESTED",
        "vehicleAssignmentStatus": "SOFT_HOLD",
        "paymentAvailability": "WAITING_APPROVAL",
        "spot": {
          "spotMasterId": "spot-master-001",
          "spotName": "꾸따 지점"
        },
        "model": {
          "modelId": "model-125-001",
          "brand": "Honda",
          "modelName": "Vario 125",
          "cc": 125
        },
        "startDate": "2026-10-01",
        "returnDate": "2026-10-04",
        "deliveryRequestType": "START_AND_RETURN",
        "pickupLocation": "Jl. Raya Kuta No. 10, Badung",
        "returnLocation": "Jl. Raya Kuta No. 10, Badung",
        "price": {
          "currency": "USD",
          "totalFrom": 400000,
          "totalTo": 400000
        },
        "payment": null
      }
    ]
  }
}
```

### 성공 응답 — 신규 사용자

```json
{
  "status": "success",
  "isNewUser": true,
  "accessToken": "<nadri-user-access-token>",
  "refreshToken": "<nadri-user-refresh-token>",
  "user": {
    "uidToken": "app-user-001",
    "name": null,
    "age": null,
    "gender": null,
    "nationality": null,
    "ongoingRequests": []
  }
}
```

`ongoingRequests`는 로그인 시점의 간단한 조회 결과다. 예약 상태가 바뀌거나 새 요청이 생성되면 다음 로그인 또는 API 7에서 다시 조회한다. 전체 목록의 페이지 이동·결제 상세·실제 렌트 시각은 API 7 응답을 사용한다. 각 항목의 `price`는 예약 생성 시 저장한 서버 검증 견적을 사용하고, PREMIUM 범위 예약은 `totalFrom`·`totalTo`를 함께 반환한다.

### 오류

| HTTP | 오류 코드 | 조건 |
|---:|---|---|
| 422 | `INVALID_UID` | UID 누락·공백·길이 초과 |
| 503 | `RENTAL_USER_STORAGE_UNAVAILABLE` | 사용자 테이블 조회·생성 불가 |

## 4. API 2 — 사용자 프로필 갱신

### 요청

`PATCH /api/v1/nadri/user/profile`

```http
Authorization: Bearer <nadri-user-access-token>
Content-Type: application/json
```

```json
{
  "NAME": "홍길동",
  "Age": 31,
  "GENDER": "M",
  "NATIONALITY": "KR",
  "fcmToken": "<customer-device-fcm-token>"
}
```

### 처리 규칙

1. Bearer token의 subject인 `uid_token`으로 `MSP_RENTAL_USER`를 잠근 뒤 조회한다.
2. 요청에 포함된 필드만 갱신하고 생략한 필드는 기존 값을 유지한다.
3. 명시적 `null`은 허용하지 않는다. 값을 지우는 별도 정책은 후속 결정한다.
4. 프로필 필드 또는 `fcmToken` 중 하나 이상은 반드시 보내야 한다.
5. `updated_at`은 실제 변경 시각으로 갱신한다.
6. `MSP_DRIVER`와의 동기화나 운전자 정보 변경은 수행하지 않는다.
7. `fcmToken`이 있으면 최신 앱 토큰과 갱신 시각을 저장한다.

### 성공 응답

```json
{
  "status": "success",
  "user": {
    "uidToken": "app-user-001",
    "name": "홍길동",
    "age": 31,
    "gender": "M",
    "nationality": "KR"
  }
}
```

### 오류

| HTTP | 오류 코드 | 조건 |
|---:|---|---|
| 401 | `INVALID_NADRI_USER_TOKEN` | 토큰 누락·위조·만료 |
| 404 | `RENTAL_USER_NOT_FOUND` | 토큰 subject에 해당하는 사용자 없음 |
| 422 | `EMPTY_PROFILE_UPDATE` | 갱신 필드가 없거나 null |
| 422 | `INVALID_PROFILE_FIELD` | 이름·나이·성별·국적 형식 오류 |

## 5. API 3 — 렌탈 차량 가용성·가격 조회

### 요청

`POST /api/v1/nadri/rental/availability`

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

| 필드 | 타입 | 필수 | 규칙 |
|---|---|:---:|---|
| `startDate` | `string` | 예 | `YYYY-MM-DD`, 영업 기준 대여 시작일 |
| `returnDate` | `string` | 예 | `YYYY-MM-DD`, `startDate`보다 뒤인 반납일 |
| `cc` | `integer` | 예 | 차량 모델의 `MSP_VEHICLE_MODEL.cc`와 일치하는 배기량. 0보다 커야 함 |
| `deliveryRequested` | `boolean` | 예 | 배송 사용 여부 |
| `pickupLocation` | `string` | 배송 사용 시 | 차량 전달 주소. 최대 500자. 배송 요청 시 필수 |
| `returnLocation` | `string` | 선택 | 차량 반환 수거 주소. 최대 500자. 보내지 않으면 `null`로 저장 |

배송을 사용하지 않으면 두 위치 필드는 보내지 않거나 `null`로 보낸다. 현재 MVP에서는 주소 문자열을 배송지역 마스터와 대조한다. 좌표·주소 정규화가 필요해지는 경우 별도 필드 확장으로 처리한다.

### 조회·집계 규칙

1. `startDate`부터 `returnDate` 전날까지를 대여 구간으로 계산한다. 대여 일수는 두 날짜의 차이이며, 날짜 구간은 `[startDate, returnDate)`로 처리한다.
2. 활성 상태인 `MSP_SPOT_MASTER`와 `MSP_VEHICLE_MODEL` 중 `cc`가 정확히 일치하는 모델만 후보로 삼는다.
3. `MSP_MODEL_DAILY_INVENTORY`의 `spot_master_id + model_id + target_date`를 기준으로 대여 구간 전체의 `available_qty`가 1 이상인 모델만 남긴다. 예약·계약·정비 변경이 재고 스냅샷에 아직 반영되지 않은 경우에는 서버의 최신 점유 검증을 추가하되, 검색 결과의 기준 행은 개별 차량이 아니다.
4. `MSP_VEHICLE` 또는 `MSP_RENTAL_VEHICLE`를 응답 단위로 사용하지 않는다. 차량의 번호판·`vehicleId`를 노출하지 않으며, 가용 결과를 `spot_master_id + model_id`로 묶어 한 항목으로 반환한다.
5. `deliveryRequested=false`이면 지점 방문 수령 조건으로 계산하고 배송비는 0원이다.
6. `deliveryRequested=true`이면 다음을 모두 확인한다.
   - `MSP_SPOT_RENT.delivery_service_type`이 `NONE`이 아님
   - 모델의 `is_delivery_supported=1`
   - 픽업 주소가 해당 지점의 활성 `MSP_SPOT_DELIVERY_REGION`에 속함. 반납 주소를 보내는 경우에는 같은 배송지역에 속해야 함
   - `START_ONLY` 지점은 시작 배송만, `START_AND_RETURN` 지점은 시작·반납 배송을 지원함
7. 배송비는 지점·배송지역 설정의 `start_delivery_fee`와 `return_delivery_fee`를 사용한다. 응답 가격에는 대여료와 배송비를 모두 포함한다.
8. `BASIC` 요금은 지점의 CC 티어를 적용한다. 공통 티어를 적용하면 `tierType=BASE`, 지점별 세부 티어를 적용하면 `tierType=BASIC`으로 표시한다. `PREMIUM` 차량은 `priceType=PREMIUM`으로 표시하고 CC 구간은 `null`로 둔다.
9. `price.pricingTiers`에는 해당 지점·모델에 적용 가능한 티어를 모두 넣는다. 같은 모델에 BASIC과 PREMIUM이 함께 있거나 여러 요금 규칙이 적용되면 배열 원소를 추가하고, `dailyFrom`·`dailyTo`와 총액 범위는 후보 요금의 최저·최고를 계산해 산출한다. `PREMIUM` 차량의 일 요금이 차량별로 다르면 예약 시 실제 차량 배정으로 최종 확정한다.
10. 조건에 맞는 항목이 없거나 배송 가능한 지점이 없으면 오류 대신 `200`과 빈 `items` 배열을 반환한다. 잘못된 날짜·배기량·필수 위치 누락만 `4xx` 오류로 반환한다.

### 성공 응답

응답의 최상위 결과는 `spot`, `model`, `price` 세 묶음만 제공한다. `items`의 각 원소가 한 지점·한 모델을 뜻한다.

`spot.location`은 차량을 수령·반납하는 샵의 위치다. `MSP_SPOT_MASTER`의 주소·우편번호·위도·경도를 사용하며, 요청으로 받은 고객의 `pickupLocation`·`returnLocation`과는 별도 값이다.

```json
{
  "status": "success",
  "items": [
    {
      "spot": {
        "spotMasterId": "spot-master-001",
        "unitCode": "CONTRACT-ORG01",
        "spotName": "꾸따 지점",
        "phone": "+62-361-000000",
        "location": {
          "address": "Jl. Raya Kuta No. 10, Badung",
          "zipCode": "80361",
          "latitude": -8.718000,
          "longitude": 115.168000
        }
      },
      "model": {
        "modelId": "model-125-001",
        "brand": "Honda",
        "modelName": "Vario 125",
        "cc": 125,
        "vehicleType": "SCOOTER",
        "modelImageKey": "models/vario-125.jpg"
      },
      "price": {
        "currency": "USD",
        "rentalDays": 3,
        "dailyFrom": 100000,
        "dailyTo": 100000,
        "rentalFrom": 300000,
        "rentalTo": 300000,
        "pricingTiers": [
          {
            "priceType": "BASIC",
            "tierType": "BASIC",
            "minCc": 101,
            "maxCc": 150,
            "dailyPriceFrom": 100000,
            "dailyPriceTo": 100000
          }
        ],
        "deliveryStart": 50000,
        "deliveryReturn": 50000,
        "deliveryTotal": 100000,
        "totalFrom": 400000,
        "totalTo": 400000
      }
    }
  ]
}
```

`BASIC`처럼 모델 내 일 요금이 같으면 `dailyFrom`과 `dailyTo`(및 총액 범위)가 같은 값이다. `PREMIUM` 요금이 차량별로 다르면 두 값이 달라지고 `pricingTiers`의 해당 원소에도 요금 범위를 표시한다. 앱은 `totalFrom`을 “최저가부터”로 표시할 수 있다. 응답에는 차량 수, 차량 번호, 차량 ID 또는 별도 차량 상세 객체를 추가하지 않는다.

`price.pricingTiers` 원소의 필드는 다음과 같이 정의한다.

| 필드 | 의미 |
|---|---|
| `priceType` | `BASIC` 또는 `PREMIUM` |
| `tierType` | `BASE`(공통 CC 티어), `BASIC`(지점 CC 티어), PREMIUM이면 `null` |
| `minCc`, `maxCc` | BASIC·BASE 티어의 배기량 구간. PREMIUM이면 `null` |
| `dailyPriceFrom`, `dailyPriceTo` | 해당 티어의 적용 일 요금 범위. 단일 요금이면 두 값이 같음 |

### 오류

| HTTP | 오류 코드 | 조건 |
|---:|---|---|
| 422 | `INVALID_RENTAL_DATE_RANGE` | 날짜 형식 오류 또는 반납일이 시작일보다 빠르거나 같음 |
| 422 | `INVALID_ENGINE_CC` | `cc` 누락·0 이하·정수 아님 |
| 422 | `DELIVERY_LOCATION_REQUIRED` | 배송 사용인데 픽업·반납 위치 중 하나 이상 누락 |

### 인증 및 범위

로그인 전 차량 탐색을 허용할 수 있도록 이 조회 API의 고객 토큰 필수 여부는 구현 전 확정한다. 토큰을 선택적으로 운영하더라도 사용자 데이터는 읽거나 변경하지 않는다. 이 API는 `MSP_DRIVER`와 `MSP_DRIVER_SPOT_HISTORY`를 조회·변경하지 않으며, 차량 단위 데이터는 내부 가용성 계산에만 사용하고 외부에는 지점·모델·가격만 반환한다.

## 6. API 4 — 렌트 요청 생성

### 요청

`POST /api/v1/nadri/rental/request`

```http
Authorization: Bearer <nadri-user-access-token>
Content-Type: application/json
```

```json
{
  "spotMasterId": "spot-master-001",
  "modelId": "model-125-001",
  "startDate": "2026-10-01",
  "returnDate": "2026-10-04",
  "totalPrice": 400000,
  "currency": "USD",
  "deliveryRequested": true,
  "pickupLocation": "Jl. Raya Kuta No. 10, Badung",
  "returnLocation": "Jl. Raya Kuta No. 10, Badung"
}
```

| 필드 | 타입 | 필수 | 규칙 |
|---|---|:---:|---|
| `spotMasterId` | `string` | 예 | API 3에서 선택한 지점 ID |
| `modelId` | `string` | 예 | API 3에서 선택한 차량 모델 ID |
| `startDate` | `string` | 예 | `YYYY-MM-DD` |
| `returnDate` | `string` | 예 | `startDate`보다 뒤인 반납일 |
| `totalPrice` | `integer` | 예 | API 3에서 확인한 총액. 서버가 재계산해 검증하며 그대로 신뢰하지 않음 |
| `currency` | `string` | 예 | API 3 가격의 통화 코드와 일치해야 함. MVP 표시·결제 통화는 `USD` |
| `deliveryRequested` | `boolean` | 예 | `false`는 지점 픽업, `true`는 시작·반납 배송 요청 |
| `pickupLocation` | `string` | 배송 사용 시 | 차량 전달 주소. 최대 500자. 배송 요청 시 필수 |
| `returnLocation` | `string` | 선택 | 차량 반환 수거 주소. 최대 500자. 보내지 않으면 `null`로 저장 |

### 예약 생성 처리

1. Bearer token의 subject에서 `MSP_RENTAL_USER.uid_token`을 확인하고, 요청의 사용자 식별자를 별도로 받지 않는다.
2. `spotMasterId`와 `modelId`가 활성 상태이고 API 3에서 선택 가능한 조합인지 확인한다. 고객은 `vehicleId`나 차량 번호를 보낼 수 없다.
3. 날짜를 지점 영업 시간대(`Asia/Makassar`)의 시작·종료 시각으로 정규화해 `start_datetime`·`end_datetime`에 저장한다.
4. 배송을 사용하지 않으면 `delivery_request_type=PICKUP`, 배송지역·주소·배송비 스냅샷은 NULL 또는 0으로 저장한다. 배송을 사용하면 현재 MVP에서는 `START_AND_RETURN`으로 처리하며 픽업 주소는 필수이고 반납 주소는 선택이다.
5. 배송 요청 시 픽업 주소가 활성 배송지역에 속하는지 확인한다. 반납 주소를 함께 보내면 같은 배송지역에 속하는지도 확인한다. `MSP_SPOT_RENT.delivery_service_type`, `MSP_VEHICLE_MODEL.is_delivery_supported`, `MSP_SPOT_DELIVERY_REGION.is_delivery_enabled`를 모두 검증하며, 배송지역 ID는 주소 검증 결과로 서버가 결정한다.
6. API 3와 동일한 요금 티어·대여일수·배송비로 서버가 총액을 다시 계산한다. BASIC처럼 확정된 단일 가격은 `totalPrice`와 정확히 일치해야 한다. PREMIUM 가격 범위는 `totalPrice`가 서버가 산출한 범위 안에 있어야 하며, 실제 차량 배정 시 최종 금액을 다시 확정한다.
7. 기간 전체의 지점·모델 가용성을 다시 확인한다. 조회 이후 재고가 변경됐으면 요청을 만들지 않고 `RENTAL_UNAVAILABLE`을 반환한다.
8. 검증을 통과하면 `MSP_RESERVATION`을 다음 상태로 생성한다.
   - `uid_token`: 로그인 사용자 UID
   - `spot_master_id`, `model_id`: 선택한 지점·모델
   - `reservation_status=REQUESTED`
   - `vehicle_assignment_status=SOFT_HOLD`
   - `assigned_vehicle_id`: 필요할 때만 서버 내부 가배정으로 저장하며 API 응답에는 노출하지 않음
   - `delivery_request_type`, `delivery_region_id`, 주소 및 배송비 스냅샷: 배송 요청에 맞춰 저장
9. 동일 사용자·지점·모델·기간·배송조건 요청이 최초 성공 접수 후 60초 이내 반복되면 기존 예약을 재생성하지 않고 중복 오류를 반환한다. 동시 요청은 트랜잭션·공유 잠금으로 한 건만 성공시킨다.
10. 예약 생성과 결제 주문 생성은 분리한다. 예약 성공 응답은 `paymentStatus=WAITING_APPROVAL`을 반환하며, 고객 앱은 관리자가 예약을 `APPROVED`로 승인한 뒤에만 API 5를 호출해 결제 주문을 만든다. `REQUESTED` 상태에서 API 5를 호출하면 결제 페이지용 주문을 만들지 않고 오류를 반환한다.

### 최초 가용성 조회 JSON 저장

새 컬럼을 추가하지 않고 `MSP_RESERVATION.required_criteria_json`에 서버가 확정한 원본을 저장한다. 이 JSON은 고객이 보낸 값과 서버 검증 결과를 분리해 보존한다.

```json
{
  "source": "nadri.rental.availability",
  "availabilityRequest": {
    "startDate": "2026-10-01",
    "returnDate": "2026-10-04",
    "cc": 125,
    "deliveryRequested": true,
    "pickupLocation": "Jl. Raya Kuta No. 10, Badung",
    "returnLocation": "Jl. Raya Kuta No. 10, Badung"
  },
  "selected": {
    "spotMasterId": "spot-master-001",
    "modelId": "model-125-001"
  },
  "quote": {
    "currency": "USD",
    "requestedTotal": 400000,
    "calculatedTotalFrom": 400000,
    "calculatedTotalTo": 400000,
    "pricingTiers": [
      {
        "priceType": "BASIC",
        "tierType": "BASIC",
        "minCc": 101,
        "maxCc": 150,
        "dailyPriceFrom": 100000,
        "dailyPriceTo": 100000
      }
    ]
  }
}
```

관리자 승인 시에는 이 JSON을 기준으로 저장된 가격과 현재 가격을 재검증하고, 승인된 가격을 서버 계산값으로 갱신한다. 기존 승인 로직과의 호환을 위해 승인 시 JSON 상위에 `priceType`·`dailyPrice`를 서버가 추가할 수 있으며, 고객이 보낸 가격이나 JSON을 승인 가격으로 직접 신뢰하지 않는다.

### 성공 응답

```json
{
  "status": "success",
  "reservationId": "res-20261001-0001",
  "bookedNo": "BOres-20261001-0001",
  "reservationStatus": "REQUESTED",
  "vehicleAssignmentStatus": "SOFT_HOLD",
  "spotMasterId": "spot-master-001",
  "modelId": "model-125-001",
  "totalPrice": 400000,
  "currency": "USD",
  "deliveryRequestType": "START_AND_RETURN",
  "paymentStatus": "WAITING_APPROVAL"
}
```

`paymentStatus=WAITING_APPROVAL`은 결제 테이블의 결제 상태가 아니라 결제 가능 조건을 나타낸다. `REQUESTED` 예약 생성 시에는 `MSP_RENTAL_PAYMENT` 행과 PayPal 주문을 만들지 않는다. 관리자가 `APPROVED`로 승인한 뒤 API 5에서 결제 시도를 생성한다. 예약 생성이 커밋되면 해당 지점의 활성 대표·일반관리자에게 `RESERVATION_REQUESTED` FCM을 발송하며, 알림 큐에는 기록하지 않는다.

### 오류

| HTTP | 오류 코드 | 조건 |
|---:|---|---|
| 401 | `INVALID_NADRI_USER_TOKEN` | 고객 토큰 누락·위조·만료 |
| 404 | `SPOT_OR_MODEL_NOT_FOUND` | 지점·모델이 없거나 비활성 상태 |
| 409 | `RENTAL_UNAVAILABLE` | 요청 기간에 지점·모델 가용 재고 없음 |
| 409 | `PRICE_QUOTE_MISMATCH` | 서버 재계산 가격과 요청 총액 불일치 |
| 409 | `DUPLICATE_RENTAL_REQUEST` | 동일 요청을 60초 이내 재전송 |
| 409 | `DELIVERY_NOT_SUPPORTED` | 지점·모델·배송지역이 배송 조건을 지원하지 않음 |
| 422 | `INVALID_RENTAL_REQUEST` | 날짜·총액·통화 형식 오류 |
| 422 | `DELIVERY_LOCATION_REQUIRED` | 배송 요청인데 픽업·반납 위치 누락 |

## 7. API 5 — PayPal 결제 주문 생성

### 요청

`POST /api/v1/nadri/rental/payment/order`

```http
Authorization: Bearer <nadri-user-access-token>
Content-Type: application/json
```

```json
{
  "reservationId": "res-20261001-0001"
}
```

금액·통화·PayPal 주문 ID는 고객이 보내지 않는다. 서버가 예약에 저장된 서버 검증 견적과 현재 가격을 다시 확인해 결제 금액을 결정한다. 이 API는 관리자가 승인한 예약(`reservation_status=APPROVED`)에 대해서만 호출할 수 있으며, 아직 승인되지 않은 예약에는 결제 페이지용 주문을 생성하지 않는다.

MVP에서는 차량 조회 화면과 PayPal 청구 통화를 모두 `USD`로 고정한다. 가격 원본도 USD 기준으로 관리하며, 고객이 통화나 결제 금액을 임의로 지정할 수 없도록 서버가 금액을 검증한다. 지원 통화와 수취 계정 설정은 [PayPal 공식 통화 안내](https://developer.paypal.com/api/codes/currency/)를 기준으로 확인한다.

### 처리 규칙

1. Bearer token의 subject가 해당 예약의 `MSP_RESERVATION.uid_token`과 일치하는지 확인한다.
2. 예약 상태가 `APPROVED`인지 확인한다. `REQUESTED`, `REJECTED`, `CANCELED`, `EXPIRED`, `HANDED_OVER` 상태에는 주문을 만들지 않는다. 결제 완료만으로 예약을 자동 승인하지 않는다.
3. API 4에서 저장한 `required_criteria_json`과 현재 지점·모델·기간·배송비를 재검증한다. 가격이 바뀌었거나 저장된 `finalTotal`이 서버가 계산한 개별 `totalOptions`에 없으면 주문을 만들지 않고 새 견적을 요구한다.
4. `MSP_RENTAL_PAYMENT`에 `reservation_id`, `payment_provider=PAYPAL`, 현재 환경, 서버 확정 `total_price`·`currency`, `payment_status=CREATED`를 저장한다. `rental_contract_id`는 NULL이다.
5. 서버가 PayPal Orders v2의 `POST /v2/checkout/orders`를 `intent=CAPTURE`로 호출하고, 구매 단위 하나와 예약 ID를 reference로 사용한다. PayPal 주문 생성·캡처는 서버가 수행하며 브라우저에서 PayPal 비밀값을 사용하지 않는다.
6. PayPal 주문 생성 성공 후 `paypal_order_id`를 결제 행에 저장하고 승인 링크를 반환한다. PayPal 주문 생성 실패 시 결제 행을 `FAILED`로 남기고 예약은 유지한다.
7. 이미 유효한 `CREATED`, `PENDING`, `PAID`인 같은 예약 결제 시도가 있으면 새 주문을 만들지 않고 기존 결제 정보를 반환한다. PayPal 주문이 만료됐거나 내부 미결제 만료 작업으로 `CANCELED`가 된 시도만 새 결제 시도를 만들 수 있다.
8. `PayPal-Request-ID`는 결제 시도별로 고정해 네트워크 재시도에서 중복 주문을 방지한다.

### 성공 응답

```json
{
  "status": "success",
  "paymentId": 1001,
  "reservationId": "res-20261001-0001",
  "paymentStatus": "CREATED",
  "paypalOrderId": "5O190127TN364715T",
  "approvalUrl": "https://www.sandbox.paypal.com/checkoutnow?token=5O190127TN364715T",
  "totalPrice": 400000,
  "currency": "USD"
}
```

`CREATED`는 PayPal 주문이 만들어졌다는 의미이며 결제 완료가 아니다. 고객이 `approvalUrl` 또는 PayPal SDK에서 승인한 후 API 6을 호출한다. PayPal은 주문 생성 후 승인된 주문을 캡처하는 별도 단계를 사용한다. [PayPal 주문 생성·캡처 공식 안내](https://developer.paypal.com/platforms/checkout/standard/integrate)

### 오류

| HTTP | 오류 코드 | 조건 |
|---:|---|---|
| 401 | `INVALID_NADRI_USER_TOKEN` | 고객 토큰 누락·위조·만료 |
| 404 | `RESERVATION_NOT_FOUND` | 본인 예약이 아니거나 예약 없음 |
| 409 | `PAYMENT_QUOTE_CHANGED` | 서버 재계산 금액·통화가 저장 견적과 다름 |
| 409 | `RESERVATION_NOT_APPROVED_FOR_PAYMENT` | 관리자가 예약을 승인하기 전이거나 출고 단계로 이미 진행됨 |
| 409 | `PAYMENT_ALREADY_PAID` | 해당 예약에 완료 결제가 이미 있음 |
| 409 | `PAYMENT_RESERVATION_STATE_INVALID` | 취소·거절·만료·인계 예약 등 결제할 수 없는 상태 |
| 503 | `PAYPAL_NOT_CONFIGURED` | PayPal 환경 설정 누락 |
| 503 | `PAYPAL_SERVICE_UNAVAILABLE` | PayPal 주문 생성 실패 |

## 8. API 6 — PayPal 주문 캡처

### 요청

`POST /api/v1/nadri/rental/payment/capture`

```json
{
  "paymentId": 1001
}
```

고객은 PayPal 주문 ID·캡처 ID·금액·통화를 보내지 않는다. 서버가 결제 행에 저장된 주문 ID와 서버 확정 금액을 사용한다.

### 처리 규칙

1. `paymentId`로 결제 행과 연결 예약을 잠그고, 연결 예약의 고객 UID가 현재 토큰과 일치하는지 확인한다.
2. 연결 예약이 존재하면 예약 상태가 `APPROVED`인지 확인한다. 승인 후 취소·거절·만료됐거나 이미 `HANDED_OVER`이면 캡처하지 않는다. 이미 `PAID`, `REFUNDED`, `PARTIALLY_REFUNDED`이면 현재 상태를 그대로 반환한다.
3. 결제 상태가 `CREATED` 또는 재시도 가능한 `PENDING`인지 확인한다.
4. 서버가 PayPal `POST /v2/checkout/orders/{paypalOrderId}/capture`를 호출한다. 캡처 요청도 동일한 결제 시도의 `PayPal-Request-ID`를 사용한다.
5. PayPal 응답에서 캡처 ID를 확인해 저장하되, 최종 `PAID` 판정은 서명 검증된 `PAYMENT.CAPTURE.COMPLETED` 웹훅을 기준으로 한다. 캡처 응답이 먼저 오면 내부 상태는 `PENDING`으로 반환할 수 있다.
6. 결제 실패·거절은 해당 결제 행을 `FAILED`로 기록하고 예약을 자동 취소하지 않는다. 결제 재시도는 API 5에서 새 결제 시도를 만든다.
7. 결제 상태가 `PAID`가 되어도 관리자 예약 승인(`APPROVED`)이나 차량 출고를 자동 실행하지 않는다. 다만 최종 예약 출고 API는 `APPROVED`와 `PAID`를 모두 확인해야 한다.

### 성공 응답

```json
{
  "status": "success",
  "paymentId": 1001,
  "reservationId": "res-20261001-0001",
  "paymentStatus": "PENDING",
  "paypalOrderId": "5O190127TN364715T",
  "paypalCaptureId": "8MC585209K746392H",
  "totalPrice": 400000,
  "currency": "USD"
}
```

웹훅 처리 후 로그인 응답과 별도 예약 조회의 `paymentStatus`가 `PAID`로 갱신된다. 결제·환불 웹훅은 기존 `/nadreego/paypal/webhook`을 재사용하며, 고객 토큰으로 웹훅을 호출하지 않는다.

### 오류

| HTTP | 오류 코드 | 조건 |
|---:|---|---|
| 401 | `INVALID_NADRI_USER_TOKEN` | 고객 토큰 누락·위조·만료 |
| 404 | `PAYMENT_NOT_FOUND` | 본인 결제 건이 없음 |
| 409 | `RESERVATION_NOT_APPROVED_FOR_PAYMENT` | 연결 예약이 승인 상태가 아님 |
| 409 | `PAYMENT_STATE_INVALID` | 캡처할 수 없는 결제 상태 |
| 409 | `PAYPAL_ORDER_MISMATCH` | PayPal 주문과 내부 결제 금액·통화·환경 불일치 |
| 503 | `PAYPAL_SERVICE_UNAVAILABLE` | PayPal 캡처 호출 실패 |

## 9. API 7 — 진행 중 렌트·예약 목록 조회

### 요청

`GET /api/v1/nadri/rental/ongoing`

```http
Authorization: Bearer <nadri-user-access-token>
```

쿼리 파라미터는 `page`(기본 1, 1 이상)와 `pageSize`(기본 20, 최대 100)만 사용한다. 로그인 응답의 `ongoingRequests`는 요약용이고, 이 API가 진행 목록의 정본이다.

### 포함·병합 규칙

1. 현재 사용자의 `MSP_RESERVATION` 중 `reservation_status IN ('REQUESTED','APPROVED','HANDED_OVER')`을 조회한다.
2. 현재 사용자의 `MSP_RENTAL_CONTRACT` 중 `contract_status IN ('ON_RENT','OVERDUE')`이고 `actual_end_time IS NULL`인 계약을 조회한다.
3. 예약과 계약이 `reservation_id`로 연결되어 있으면 하나의 `RENTAL` 항목으로 병합한다. 출고 전 예약은 `RESERVATION` 항목으로 남기고, 예약 없이 시작한 당일 렌트는 `RENTAL` 항목으로 반환한다.
4. `REQUESTED`·`APPROVED` 예약의 시작 시각, 또는 렌트 계약의 실제 시작 시각을 기준으로 현재 진행 항목을 정렬한다. 실제 렌트가 있는 항목을 먼저 표시하고, 동률이면 시작 시각 오름차순·식별자 오름차순을 사용한다.
5. 동일 예약·계약을 중복 반환하지 않으며 `totalCount`도 병합 후 항목 수를 센다.
6. `RETURNED`, `REJECTED`, `CANCELED`, `EXPIRED` 예약과 `RETURNED`, `CANCELED` 계약은 포함하지 않는다.
7. 예약이 연결된 계약은 예약의 `startDate`·`returnDate`를 사용하고, 예약 없는 당일 렌트는 계약의 `actual_start_time` 현지 날짜와 `planned_end_date`를 사용한다. 지점은 예약의 `spot_master_id`, 당일 렌트는 계약의 `pickup_spot_master_id`를 기준으로 조회한다.
8. `paymentAvailability`는 `WAITING_APPROVAL`, `PAYMENT_REQUIRED`, `CREATED`, `PENDING`, `PAID` 중 하나로 반환한다. `APPROVED` 예약에 결제 행이 없거나 완료되지 않았으면 `PAYMENT_REQUIRED`이며, 이때만 고객 앱이 API 5를 호출할 수 있다.

### 성공 응답

```json
{
  "status": "success",
  "items": [
    {
      "recordType": "RENTAL",
      "reservationId": "res-20261001-0001",
      "rentalContractId": "rent-20261001-0001",
      "reservationStatus": "HANDED_OVER",
      "rentalStatus": "ON_RENT",
      "paymentAvailability": "PAID",
      "spot": {
        "spotMasterId": "spot-master-001",
        "spotName": "꾸따 지점",
        "location": {
          "address": "Jl. Raya Kuta No. 10, Badung",
          "zipCode": "80361",
          "latitude": -8.718,
          "longitude": 115.168
        }
      },
      "model": {
        "modelId": "model-125-001",
        "brand": "Honda",
        "modelName": "Vario 125",
        "cc": 125,
        "vehicleType": "SCOOTER",
        "modelImageKey": "models/vario-125.jpg"
      },
      "startDate": "2026-10-01",
      "returnDate": "2026-10-04",
      "actualStartTime": "2026-10-01T09:10:00+08:00",
      "actualEndTime": null,
      "delivery": {
        "deliveryRequestType": "START_AND_RETURN",
        "pickupLocation": "Jl. Raya Kuta No. 10, Badung",
        "returnLocation": "Jl. Raya Kuta No. 10, Badung",
        "deliveryTotalFee": 100000
      },
      "price": {
        "currency": "USD",
        "totalFrom": 400000,
        "totalTo": 400000
      },
      "payment": {
        "paymentId": 1001,
        "paymentStatus": "PAID",
        "paypalOrderId": "5O190127TN364715T",
        "paypalCaptureId": "8MC585209K746392H",
        "totalPrice": 400000,
        "currency": "USD"
      }
    }
  ],
  "page": 1,
  "pageSize": 20,
  "totalCount": 1,
  "hasNext": false
}
```

`RESERVATION` 항목은 `rentalContractId`와 `actualStartTime`이 `null`이다. 예약과 계약이 연결된 항목은 계약의 실제 상태·시각을 함께 반환한다. 개별 차량 ID·번호판은 반환하지 않고 지점·모델 단위 정보만 제공한다. 주소는 본인 인증 응답이므로 포함할 수 있지만, 로그·푸시 payload에는 복사하지 않는다. `price`는 예약에 저장된 서버 검증 견적을 사용하고, 예약 없는 당일 렌트는 결제 행의 확정 금액을 사용한다. `payment`는 현재 PayPal 환경의 최신 결제 시도를 사용한다.

### 오류

| HTTP | 오류 코드 | 조건 |
|---:|---|---|
| 401 | `INVALID_NADRI_USER_TOKEN` | 고객 토큰 누락·위조·만료 |
| 422 | `INVALID_PAGE_PARAMETER` | `page`·`pageSize`가 허용 범위를 벗어남 |
| 503 | `RENTAL_HISTORY_UNAVAILABLE` | 예약·계약 목록 조회 불가 |

## 10. API 8 — 완료된 렌트 목록 조회

### 요청

`GET /api/v1/nadri/rental/completed`

```http
Authorization: Bearer <nadri-user-access-token>
```

쿼리 파라미터는 API 7과 같은 `page`(기본 1)·`pageSize`(기본 20, 최대 100)를 사용한다. 완료 목록은 반납이 끝난 실제 렌트 이용내역을 대상으로 한다.

### 포함·정렬 규칙

1. 현재 사용자의 `MSP_RENTAL_CONTRACT` 중 `contract_status=RETURNED`이고 `actual_end_time IS NOT NULL`인 계약만 조회한다.
2. 예약과 연결된 계약은 예약 정보와 계약 정보를 하나의 `RENTAL` 항목으로 반환한다. 연결 예약의 상태가 `RETURNED`가 아니더라도 계약 반납 완료가 확인되면 계약 상태를 기준으로 포함한다.
3. 예약 없이 시작한 당일 렌트도 `reservationId=null`인 `RENTAL` 항목으로 포함한다.
4. `CANCELED`, `REJECTED`, `EXPIRED` 예약만 존재하고 실제 렌트 계약이 없는 요청은 완료 렌트 목록에서 제외한다. 이는 취소·거절 요청 이력과 반납 완료 렌트 이력을 구분하기 위한 현재 MVP 정책이다.
5. `actual_end_time DESC`를 기본 정렬로 사용하고, 동률이면 `rental_contract_id DESC`로 정렬한다. 병합된 항목은 한 번만 세어 `totalCount`에 반영한다.
6. 예약이 연결된 계약은 예약의 지점·모델·배송·가격 스냅샷을 사용하고, 예약 없는 당일 렌트는 계약의 수령 지점과 결제 행의 확정 금액을 사용한다.

### 성공 응답

응답 envelope와 항목 필드는 API 7과 같다. 완료된 항목은 `recordType=RENTAL`, `rentalStatus=RETURNED`, `actualEndTime`에 실제 반납 시각을 반환한다.

```json
{
  "status": "success",
  "items": [
    {
      "recordType": "RENTAL",
      "reservationId": "res-20260901-0001",
      "rentalContractId": "rent-20260901-0001",
      "reservationStatus": "RETURNED",
      "rentalStatus": "RETURNED",
      "paymentAvailability": "PAID",
      "spot": {
        "spotMasterId": "spot-master-001",
        "spotName": "꾸따 지점",
        "location": {
          "address": "Jl. Raya Kuta No. 10, Badung",
          "zipCode": "80361",
          "latitude": -8.718,
          "longitude": 115.168
        }
      },
      "model": {
        "modelId": "model-125-001",
        "brand": "Honda",
        "modelName": "Vario 125",
        "cc": 125,
        "vehicleType": "SCOOTER",
        "modelImageKey": "models/vario-125.jpg"
      },
      "startDate": "2026-09-01",
      "returnDate": "2026-09-04",
      "actualStartTime": "2026-09-01T09:10:00+08:00",
      "actualEndTime": "2026-09-04T17:30:00+08:00",
      "delivery": {
        "deliveryRequestType": "PICKUP",
        "pickupLocation": null,
        "returnLocation": null,
        "deliveryTotalFee": 0
      },
      "price": {
        "currency": "USD",
        "totalFrom": 400000,
        "totalTo": 400000
      },
      "payment": {
        "paymentId": 1001,
        "paymentStatus": "PAID",
        "paypalOrderId": "5O190127TN364715T",
        "paypalCaptureId": "8MC585209K746392H",
        "totalPrice": 400000,
        "currency": "USD"
      }
    }
  ],
  "page": 1,
  "pageSize": 20,
  "totalCount": 1,
  "hasNext": false
}
```

결제 정보가 없거나 결제 시도가 실패한 렌트도 이용내역 자체는 반환하며 `payment`는 `null` 또는 현재 결제 상태로 표시한다. 완료 목록의 결제·환불 상태는 예약·계약 상태와 별도로 제공한다.

### 오류

| HTTP | 오류 코드 | 조건 |
|---:|---|---|
| 401 | `INVALID_NADRI_USER_TOKEN` | 고객 토큰 누락·위조·만료 |
| 422 | `INVALID_PAGE_PARAMETER` | `page`·`pageSize`가 허용 범위를 벗어남 |
| 503 | `RENTAL_HISTORY_UNAVAILABLE` | 완료 렌트 목록 조회 불가 |

## 11. 예약 취소와 환불

### API 9 — 결제 전 예약 요청 취소

`POST /api/v1/nadri/rental/request/cancel`

```json
{
  "reservationId": "res-20261001-0001",
  "reason": "일정 변경"
}
```

고객 토큰의 UID가 예약의 `uid_token`과 일치할 때만 호출할 수 있다. 예약 상태가 `REQUESTED` 또는 `APPROVED`이고 출고 계약이 없을 때만 취소할 수 있다. 결제 행이 `CREATED`이면 결제 행을 `CANCELED`로 바꾸고, 예약과 차량 가배정을 `CANCELED/RELEASED`로 바꾼다. 결제 상태가 `PENDING`이면 캡처 결과가 확정될 때까지 취소하지 않고 `PAYMENT_IN_PROGRESS`를 반환한다. 이미 결제 완료된 예약은 이 API에서 취소하지 않고 `PAYMENT_REFUND_ADMIN_ONLY`를 반환한다.

PayPal 캡처가 진행 중인 `PENDING` 결제는 환불할 수 없으므로 `PAYMENT_IN_PROGRESS`로 거절한다. 해당 결제가 완료된 뒤 관리자가 취소·환불을 처리한다. PayPal은 캡처가 보류 중일 때 환불을 허용하지 않는다. [PayPal 공식 오류 안내](https://developer.paypal.com/api/payments/v2/errors/pending_capture/)

### 관리자 취소와 환불

기존 `POST /nadreego/booking/action`에 `action=CANCEL`을 사용한다. 관리자는 출고 전 `APPROVED` 예약을 취소할 수 있다. 결제 완료(`PAID` 또는 부분 환불 상태)이고 환불 잔액이 있으면 예약을 먼저 `CANCELED`로 저장하고 결제 행을 `refund_status=REQUESTED`로 기록한다. 응답의 `refundStatus`가 `REQUESTED`이면 PayPal 환불 요청이 비동기로 시작된다. 환불 실패는 예약 취소를 되돌리지 않으며 `FAILED`로 남겨 재시도 대상으로 삼는다.

서버는 PayPal 캡처 ID를 사용해 `POST /v2/payments/captures/{capture_id}/refund`를 호출하고 `PayPal-Request-Id`를 결제 건에 고정한다. 환불 금액은 총액에서 이미 환불된 금액을 뺀 잔액이며 고객이 지정하지 않는다. PayPal 환불은 원래 결제 수단으로 돌아가고, 최종 환불 여부는 서명 검증된 `PAYMENT.CAPTURE.REFUNDED` 웹훅으로 확정한다. [PayPal 환불 공식 안내](https://developer.paypal.com/checkout/refund-payment)

결제·환불 웹훅 상태는 다음처럼 저장한다.

| 이벤트 | `refund_status` | 결제 상태 |
|---|---|---|
| `PAYMENT.REFUND.PENDING` | `PENDING` | 캡처 상태 유지 |
| `PAYMENT.CAPTURE.REFUNDED` | `COMPLETED` | 전액이면 `REFUNDED`, 일부면 `PARTIALLY_REFUNDED` |
| `PAYMENT.REFUND.FAILED` | `FAILED` | 캡처 상태 유지 |

`MSP_RENTAL_PAYMENT`의 `refund_status`, `paypal_refund_id`, 요청 시각·관리자·사유 컬럼은 `migrations/004_payment_refund.sql`로 추가한다. PayPal 웹훅은 기존 `/nadreego/paypal/webhook`을 계속 사용한다. [PayPal 공식 이벤트 목록](https://developer.paypal.com/api/rest/webhooks/event-names/)

## 12. API 10 — 나드리 사용자 로그아웃

`POST /api/v1/nadri/user/logout`을 사용한다. 기존 앱의 호환을 위해 같은 경로의 `GET`도 지원한다. access token은 항상 확인하며, `X-Refresh-Token`을 보낸 경우에는 access token과 쌍을 검증한 뒤 고객 refresh token을 폐기한다. refresh token을 생략한 기존 호출은 해당 UID의 활성 고객 refresh token을 모두 폐기한다. `MSP_RENTAL_USER.user_access_revoked_at`도 갱신해 해당 시각 이전에 발급된 고객 access token을 무효화한다. access token의 기본 유효시간은 1시간이다. 앱이 보낸 FCM 토큰은 `MSP_RENTAL_USER.fcm_token`에 보관하며 로그아웃 때 삭제하거나 변경하지 않는다.

프로필 입력은 신규 가입 직후에도 API 2 `PATCH /api/v1/nadri/user/profile`을 그대로 사용한다. 로그아웃 오류 시 사용자 데이터나 FCM 토큰은 변경하지 않는다.

## 13. API 11 — 고객 refresh token 갱신

`POST /api/v1/nadri/user/refresh`를 사용한다. 호환을 위해 같은 경로의 `GET`도 지원하며, `X-Refresh-Token` 헤더만 사용한다. 고객 토큰은 `nadri.rt.` 접두사를 사용하고 `MSP_RENTAL_USER_REFRESH_TOKEN`에서 해시로 조회한다.

활성·미만료 토큰만 갱신할 수 있다. UID별 행 잠금으로 같은 토큰의 동시 갱신을 직렬화하고, 성공하면 기존 해시를 새 값으로 교체한다. 원래 `issued_at`을 access token의 인증 시각으로 유지하되, 로그아웃 폐기 시각과 같은 초에 다시 로그인한 경우에는 폐기 시각 다음 초로 보정한다. refresh token의 절대 만료 기간은 갱신하지 않는다. 이미 사용했거나 폐기·만료된 토큰은 `401 INVALID_REFRESH_TOKEN`을 반환한다.

```json
{
  "status": "success",
  "accessToken": "<new-nadri-user-access-token>",
  "refreshToken": "<new-nadri-user-refresh-token>"
}
```

관리자 refresh token은 기존 `MSP_REFRESH_TOKEN`에 저장하되 `user_agent=nadree-api/v1`로 이 서버 세션만 구분한다. 관리자 ID별 활성 세션은 최대 3개이며 네 번째 로그인 시 가장 오래된 활성 세션을 폐기한다. 고객 refresh token은 별도 `MSP_RENTAL_USER_REFRESH_TOKEN`에 저장한다.

## 14. 저장·보안 원칙

- API 1·2는 `MSP_RENTAL_USER`와 고객 refresh token 테이블을 사용한다. API 3·7·8은 렌탈 조회 테이블을 읽고, API 4는 `MSP_RESERVATION`을 생성한다.
- `MSP_RENTAL_USER.uid_token`을 예약·계약의 논리 사용자 키로 사용한다.
- 예약 요청은 `MSP_RESERVATION.required_criteria_json`에 최초 가용성 조회 조건과 서버 검증 가격을 함께 저장한다.
- 결제 API는 기존 `MSP_RENTAL_PAYMENT`에 예약별 결제 시도를 저장하고, PayPal 주문·캡처 ID와 서버 확정 금액·통화를 연결한다. 결제 전용 새 테이블이나 예약 결제 상태 컬럼은 추가하지 않는다.
- PayPal 웹훅은 기존 `MSP_PAYPAL_WEBHOOK_EVENT`와 `/nadreego/paypal/webhook`을 사용해 결제 상태를 갱신한다.
- 관리자·고객 FCM 토큰은 앱이 전달한 최신 값을 저장하고 응답·로그에 노출하지 않는다. 예약 요청은 관리자에게, 승인·거절은 고객에게, 결제 확정은 관리자와 고객에게 커밋 후 FCM으로 전달한다. 알림 큐 테이블이나 Firebase 데이터베이스는 사용하지 않으며, 발송 실패는 업무 트랜잭션을 되돌리지 않는다.
- 기존 `MSP_DRIVER`, `MSP_DRIVER_SPOT_HISTORY`의 컬럼·인덱스·데이터는 변경하지 않는다.
- UID와 access token은 평문 로그에 남기지 않으며, 사용자 응답에는 필요한 프로필만 포함한다.
- 신규 사용자는 로그인 시 UID 행만 생성하고, 프로필 입력은 API 2의 명시적 요청에서만 저장한다.
- 고객 refresh token은 평문을 저장하지 않고 UID당 활성 토큰 1개만 유지한다. 로그인·갱신·로그아웃은 기존 고객 토큰을 조건부로 폐기한다.

## 15. 운영 전 확인할 항목

1. 앱이 실제로 보내는 필드명을 `UID`로 고정할지 `uid`로 변경할지 확정한다.
2. MVP는 모든 예약·반납·정비 날짜를 발리 `Asia/Makassar` 시간대로 처리한다. 국가 확장 시 지점별 시간대·영업시간·휴무일을 추가 설계한다.
3. 나드리 고객용 JWT 만료 시간과 issuer·audience 값을 확정한다.
4. 프로필 갱신에서 명시적 null로 값을 삭제할 수 있는지 결정한다.
5. 차량 조회 API의 고객 토큰을 필수로 할지, 로그인 전에도 허용할지 결정한다.
6. `cc`를 정확히 일치시킬지 범위 검색으로 확장할지 결정한다. 현재 설계는 정확히 일치시킨다.
7. MVP 표시·결제 통화와 가격 원본은 `USD`로 고정한다. 환율 스냅샷은 저장하지 않으며, 위치 주소의 정규화·좌표 수집 방식만 구현 전에 확정한다.
8. 렌트 요청의 `deliveryRequested=true`는 MVP에서 왕복 배송(`START_AND_RETURN`)으로 고정한다. 픽업 주소는 필수이고 반납 주소 입력은 선택이다.
9. PREMIUM/BASIC 가격은 서버가 계산한 개별 `totalOptions` 중 하나만 접수한다. 화면의 범위 표시는 유지하지만 범위 사이 임의 금액은 거절한다.
10. MVP에서는 관리자 예약 승인 대기시간을 두지 않는다. 예약 요청은 승인 또는 거절될 때까지 유지하고, 새 요청의 `hold_expires_at`은 `NULL`로 저장한다. 기존 컬럼은 하위 호환을 위해 유지한다.
11. 관리자·고객 FCM 토큰 저장과 예약 요청·승인/거절·결제 확정 FCM 발송은 구현되어 있다. 새 Firebase 프로젝트 서비스 계정과 운영 앱 토큰을 등록한 뒤 Sandbox에서 수신을 확인한다. 발송은 커밋 후 best-effort이며 일시 오류는 최대 5회·1시간 범위로 제한 재시도하고, 만료 토큰만 자동 삭제한다.
12. PayPal 주문 생성·캡처 API의 Sandbox와 Live 자격증명, Webhook ID, USD 수취 계정 ID를 환경별로 등록한다.
13. 결제 완료 후에도 관리자 승인을 별도로 유지할지 확인한다. 현재 설계는 결제와 예약 승인을 분리한다.
14. 완료 목록은 현재 `RETURNED` 렌트만 포함하고, 실제 렌트 없이 종료된 `CANCELED`·`REJECTED`·`EXPIRED` 예약은 제외한다. 종료된 예약 요청도 사용자에게 보여줄 필요가 있으면 별도 범위를 확정한다.
15. 진행·완료 목록의 기본 페이지 크기(현재 20)와 최대 페이지 크기(현재 100)를 앱 요구사항에 맞춰 확정한다.
16. 고객 refresh token의 절대 수명은 관리자와 같은 기본 30일이며, 한 UID의 동시 기기 세션을 1개로 제한한다.
17. `python -m app.jobs maintenance|payments|inventory|all`을 운영 작업 소유자가 실행한다. 발리 현지 종료일 다음 날 정비를 해제하고, 미결제 PayPal 예약과 180일 일별 재고를 재계산한다.
