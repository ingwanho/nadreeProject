# 앱·웹 프론트 전달 — 최종 백엔드 변경 완료 내용

작성일: 2026-10-19

대상: 고객 앱·웹, 관리자 앱·웹 담당자. 10월 16~19일 변경을 전달받지 않은 경우 이 문서부터 확인합니다. 아래 항목에 대해서는 과거 수동 merchant ID 입력, 온보딩 상태 테이블, 요청 키 복구 등의 중간 설계보다 이 문서가 우선합니다.

API 기준 주소: `https://na-dree.com`  
Swagger: `https://na-dree.com/docs`  
OpenAPI: `https://na-dree.com/openapi.json`

## 2026-10-20 추가 전달 — 고객 결제 복귀

고객 결제 화면의 기준 복귀 URL은 `https://na-dree.com/api/v1/nadree/rental/payment/return`이다. 백엔드 코드에 신규 주문의 복귀 설정을 추가했으며 이 추가 변경의 서버 배포 여부는 별도 확인한다. 관리자 판매자 연결용 `/nadreego/shop/paypal-onboarding/return`과 구분한다.

1. 기존 `POST /api/v1/nadree/rental/payment/order`의 paymentId/paypalOrderId를 보관하고 approvalUrl을 연다.
2. WebView가 확정된 복귀 origin/path로 이동하는 것을 감지한다. `cancelled=true`이면 결제 화면 취소로 처리하고 캡처를 호출하지 않는다. 예약은 자동 취소하지 않는다.
3. 승인 복귀의 token을 보관한 paypalOrderId와 대조한 후 고객 인증으로 `POST /api/v1/nadree/rental/payment/capture`, `{"paymentId": 보관한_ID}`를 호출한다. token 불일치는 캡처하지 않고 상태를 확인한다.
4. 서버의 캡처 응답·결제 상태 조회로 PAID를 확인한 뒤 결제 완료를 표시한다. PENDING/응답 유실은 조회로 확인하며 새 결제를 반복 생성하지 않는다.

서버는 신규 주문을 생성할 때 성공 return_url과 취소 cancel_url(`기준주소?cancelled=true`)을 PayPal에 전달한다. `approve` 또는 `payer-action` 링크는 기존 approvalUrl에 담으므로 응답 필드명 변경은 없다. URL만으로 결제를 확정하는 신규 API는 없다. 실제 결제·취소·화면 종료는 앱에서 검증한다. 이미 생성된 주문에는 이 설정이 소급되지 않는다.

## 1. 완료 상태와 연동 준비 상태

- 백엔드 코드·Swagger·필요한 DB 컬럼 적용 및 API 재시작 완료. 서버 보고서에서 마이그레이션 pending 없음, live/ready 200을 확인했습니다.
- Sandbox OAuth 인증 오류는 해결됐고, 웹훅 목록·상세 조회 및 콜백 주소 일치를 확인했습니다.
- 웹훅 누락 이벤트 5개는 **담당자의 적용 완료 안내를 반영**했습니다. 이번 전달문서 작성 시 원격 재조회는 하지 않았습니다. 이는 실제 결제·환불 웹훅 수신 성공을 의미하지 않습니다.
- 기본 자동 회귀 314개 통과. 격리 MySQL 포함 320개 및 별도 Firestore 4개, 총 324개의 Python 테스트가 통과했습니다. 실제 공개 HTTP/스키마 검사 21개와 테스트 계정 API 검사 33개도 통과했습니다.
- 실제 PayPal 판매자 연결·구매자 승인·캡처·환불·서명 웹훅 수신, 앱 복귀, 실제 회원탈퇴·채팅·App Check·기기 푸시 인수는 아직 완료하지 않았습니다.

**프론트 구현을 시작할 수 있는 상태이며, 실제 결제 운영 개시 승인 또는 전체 종단 테스트 완료 안내는 아닙니다.**

## 2. 화면별 반영 요약

| 대상 | 반영할 내용 |
| --- | --- |
| 관리자 가격 설정 | BASIC 배열 저장, 동일 cc 구간 수정, BASE 잔여 구간 적용 |
| 고객 상품 검색·예약 | 응답의 priceOptionId·totalPrice 사용, 배송비 중복 합산 금지 |
| 고객 배송 입력 | 배송 요금표 지역 선택, 편도/왕복 구분, 주소 그대로 저장 |
| 고객 예약 내역 | 종료 목록에 취소·거절·만료 포함, 예약 ID 직접 조회 |
| 고객 취소 | 시작일 전 90% 환불, 당일 0% 환불로 취소 가능(인계 전) |
| 관리자 취소 | 지점 귀책 전용, 당일 포함 인계 전 100% 환불 |
| 관리자 가입 | 대표 이메일은 승인 대기, 일회성 지점 코드는 대표 즉시 가입 |
| 관리자 판매자 연결 | PayPal URL 로그인·연결 동의 → 서버 검증·저장 → 화면 종료 |
| 탈퇴·채팅 | 기존 탈퇴 계약 유지, 신규 정리 상태 필드 없음, 캐시 정리 |

고객 API와 관리자 API의 인증 토큰을 혼용하지 않습니다. 관리자 API는 관리자 Bearer 인증, 고객 보호 API는 고객 Bearer 인증을 사용합니다. 상품 availability는 토큰 없이 조회 가능합니다. 필수값·응답 전체 형식은 배포된 Swagger를 기준으로 합니다.

## 3. 가격 정책·가격 설정 API

### 3.1 BASE / BASIC / PREMIUM

- BASE: 서비스 공통 기본 가격 구간입니다. 운영 정책상 약 4개의 큰 cc 구간을 정할 예정이며, 이번 변경에서 실제 공통 구간·금액을 새로 확정한 것은 아닙니다.
- BASIC: 해당 지점이 설정한 cc 구간에만 BASE보다 우선 적용합니다. BASIC이 없는 구간은 BASE를 그대로 사용합니다. 상위 지점의 BASIC을 상속하지 않습니다.
- PREMIUM: 차량별 고정 일단가를 사용합니다. PREMIUM이 아닌 차량은 차량 cc에 맞는 BASE/BASIC 가격을 적용합니다.
- 기존 예약에 저장된 금액·선택은 이후 가격표 변경으로 덮어쓰지 않습니다.

설명용 예시이며 실제 테스트 서버 가격이 아닙니다.

| 설정 | 실제 적용 |
| --- | --- |
| BASE 1~50cc = 10 USD만 있음 | 1~50cc 모두 10 USD |
| 위 BASE + BASIC 1~25cc = 12 USD | 1~25cc는 12 USD, 26~50cc는 BASE 10 USD |
| 위 설정 + BASIC 26~50cc = 15 USD | 1~25cc는 12 USD, 26~50cc는 15 USD |

즉, **BASIC이 BASE 전체 구간을 덮지 않아도 등록한 부분은 적용**됩니다. BASE는 여러 구간일 수 있고 동일한 규칙을 각 구간에 적용합니다.

### 3.2 배열 저장·동일 구간 갱신

`POST /nadreego/shop/tierCreate`

```json
[
  {"spotCode":"실제_지점코드", "minCc":1, "maxCc":25, "price":12, "type":"BASIC"},
  {"spotCode":"실제_지점코드", "minCc":26, "maxCc":50, "price":15, "type":"BASIC"}
]
```

- 기존 단건 객체와 1~100개 배열을 모두 지원합니다. 배열은 같은 지점만 가능합니다.
- 같은 지점에서 minCc/maxCc가 정확히 같으면 수정, 없으면 추가합니다.
- 배열 전체 성공 또는 전체 롤백입니다. 요청에서 생략한 기존 티어는 삭제하지 않습니다.
- 각 BASIC 구간은 하나의 BASE 안에 포함돼야 하며 BASIC끼리 부분 중첩할 수 없습니다.
- 기존 넓은 BASIC을 세분화하려면 기존 구간을 삭제한 뒤 새 배열을 등록합니다. 삭제 후에는 BASE가 적용되며 삭제·등록 두 API가 하나의 트랜잭션인 것은 아닙니다.
- 단건 응답은 `tier`, 배열 응답은 `tiers[]`이며 각 결과의 `action`은 `CREATED` 또는 `UPDATED`입니다.

조회: `GET /nadreego/shop/tierCreate?spotCode=...`  
삭제: `POST /nadreego/shop/tierDelete` — 본문은 Swagger 참조.

- `tiers`: 원설정(BASE+BASIC), 편집·삭제 기준.
- `effectiveTiers`: 빈 구간을 BASE로 보완한 실제 적용 구간, 표시용.
- `effectiveTiers`의 분할된 BASE 조각을 저장·삭제용 원구간으로 사용하지 않습니다.
- GET에서 spotCode 생략은 공통 BASE만 조회합니다. POST에서 생략하면 로그인 관리자의 직접 지점을 사용합니다.
- 가격 설정 금액은 정수 USD입니다. 결제·환불은 USD 센트 단위를 사용합니다.

주요 오류: `422 TIER_BATCH_DUPLICATE_RANGE`, `422 TIER_BATCH_SPOT_MISMATCH`, `409 TIER_RANGE_OVERLAP`, `409 TIER_BASE_NOT_UNIQUE`.

## 4. 고객 상품 검색·예약 요청

`POST /api/v1/nadree/rental/availability`

```json
{
  "startDate":"2026-10-20",
  "returnDate":"2026-10-22",
  "cc":125,
  "deliveryRequested":false
}
```

날짜는 실행 시점의 유효한 미래 기간으로 변경합니다. 테스트 모델은 `NRTEST-WEB-MODEL-125`(BASIC/PREMIUM), `NRTEST-WEB-MODEL-ND`(배송 미지원)입니다. 해당 기간 재고에 따라 조회 결과는 달라질 수 있습니다.

응답에서 `canRequest`, `cannotRequestReason`을 확인하고, 선택한 `price.pricingTiers[]`의 `priceOptionId`와 `totalPrice`를 보관합니다. 같은 금액이어도 BASIC/PREMIUM은 서로 다른 옵션일 수 있으므로 금액만으로 선택을 구분하지 않습니다.

`POST /api/v1/nadree/rental/request`

```json
{
  "spotMasterId":"조회된_shopId",
  "modelId":"조회된_modelId",
  "startDate":"2026-10-20",
  "returnDate":"2026-10-22",
  "priceOptionId":"조회된_priceOptionId",
  "totalPrice":50,
  "currency":"USD",
  "deliveryRequested":false
}
```

위 ID·50 USD는 형식 설명용입니다. **실제 availability의 선택 옵션 ID와 총액을 그대로 사용**하고 문자열을 직접 합성하지 않습니다. 날짜·지점·모델·배송 조건을 바꾸면 다시 조회합니다. totalPrice에는 배송비가 포함돼 있습니다.

구버전의 priceOptionId 생략은 해당 총액에 맞는 옵션이 하나일 때만 허용합니다. 새 프론트는 명시적으로 전달합니다. 오류는 `409 PRICE_OPTION_REQUIRED`, `PRICE_OPTION_INVALID`, `PRICE_QUOTE_MISMATCH`이며 가격 재조회·재선택으로 처리합니다.

관리자 조회의 `reservation.selectedPriceOption` 및 `reservation.pricingTiers`는 현재 가격이 아닌 예약 당시 저장된 선택입니다.

### 중복·응답 유실 처리

- 동일 고객·지점·모델·기간에 60초 이내 생성된 REQUESTED/APPROVED 예약이 있으면 `409 DUPLICATE_RENTAL_REQUEST`입니다.
- 생성 버튼 중복 클릭을 막고, 네트워크 응답 유실 시 무조건 재요청하지 않습니다. 진행/종료 목록과 예약 직접 조회로 확인합니다.
- 장기 멱등성이 아닙니다. 60초 이후 같은 요청이 새 예약이 될 수 있습니다.
- `Idempotency-Key` 기반 30일 결과 복구와 `/rental/requests/{requestId}` 조회 API는 **제공하지 않습니다**.

## 5. 배송 입력·요금

availability/request에 다음을 사용합니다.

| 필드 | 의미 |
| --- | --- |
| deliveryRequested | 배송 사용 여부 |
| deliveryRegionId | 지점 배송 요금표의 지역 ID, 실제 주소 판정 결과가 아님 |
| deliveryRequestType | START_ONLY 또는 START_AND_RETURN |
| pickupLocation | 전달 주소, 배송 시 필수, 최대 500자·공백만 입력 불가 |
| returnLocation | 왕복 시 회수 주소, 최대 500자·공백만 입력 불가 |

- START_ONLY: 전달 주소 필수, 회수 주소 null/생략, 회수 배송비 0.
- START_AND_RETURN: 양쪽 주소 필수. 서로 다른 주소도 저장합니다.
- type을 생략하면 회수 주소가 있는 경우 왕복, 없으면 편도로 해석합니다. 배송을 사용하지 않으면 type은 생략합니다.
- 활성 배송 요금표가 하나면 지역 ID 생략 가능, 여러 개면 선택해야 합니다.
- `409 DELIVERY_REGION_REQUIRED`, `DELIVERY_REGION_NOT_SUPPORTED`, `DELIVERY_NOT_SUPPORTED`를 처리합니다. 공개 검색에서는 지원하지 않는 상품이 제외될 수 있습니다.
- 관리자 응답의 `delivery.pickupLocation`/`returnLocation`은 실제 저장 주소입니다. 기존 `startAddress`/`returnAddress`는 마스킹 호환 필드입니다.

**주소·좌표로 실제 배송구역을 판정하는 기능은 제외했습니다.** 지역명 문자열 매칭도 하지 않습니다. ‘해당 주소 배송 가능 검증 완료’로 안내하지 않습니다. 기존 예약 위치 정정의 권한·이전값 충돌·이력은 유지하지만 ‘같은 장소인지’의 지리 검증을 추가하지 않았습니다.

## 6. 예약 조회·취소·환불 표시

### 조회

- `GET /api/v1/nadree/rental/ongoing`: 진행 내역.
- `GET /api/v1/nadree/rental/completed`: 반납뿐 아니라 취소·거절·만료 포함.
- 목록은 page/pageSize(최대 100)를 사용합니다.
- `GET /api/v1/nadree/rental/reservations/{reservationId}`: 상태에 관계없이 본인 예약 직접 조회. 응답은 `status`와 `item`, 다른 고객 예약은 404입니다.
- 관리자 `POST /nadreego/booking/select`: `bookedNo` 정확 일치 필터 추가. `bookingId=reservationId`, 예약의 `bookedNo`는 `BO`+예약 ID입니다.

### 취소 정책

| 실행자 | 시작일 전 | 렌탈 시작일 당일부터 | 조건 |
| --- | --- | --- | --- |
| 고객 | 실제 결제액 90% 환불 | 취소 가능, 환불 0% | 인계 전 REQUESTED/APPROVED |
| 관리자 | 실제 결제액 100% 환불 | 실제 결제액 100% 환불 | 지점 귀책, 인계 전 APPROVED |

날짜 기준은 서버 업무 시간대(기본 Asia/Makassar)의 시작일 00:00입니다. 기기 시간대·24시간 전 기준으로 계산하지 않습니다. 인계 후 취소 불가, 미결제 및 0% 취소에는 PG 환불을 요청하지 않습니다. 결제 처리 중에는 취소가 차단될 수 있습니다.

고객: `POST /api/v1/nadree/rental/request/cancel`

```json
{"reservationId":"실제_예약ID", "reason":"고객 취소 사유"}
```

관리자: `POST /nadreego/booking/action`

```json
{
  "bookedNo":"BO실제_예약ID",
  "action":"CANCEL",
  "cancellationReasonType":"BRANCH_FAULT",
  "reason":"지점 귀책 사유"
}
```

관리자 고객 사유 대리 취소는 제공하지 않습니다. cancellationReasonType은 BRANCH_FAULT만 허용하며 생략해도 같은 정책입니다. APPROVE/REJECT 요청에는 보내지 않습니다. 환불률·취소 실행자를 클라이언트가 임의로 지정하지 않습니다.

- 관리자 결제 조회의 `refundRequestedAmount`는 환불 목표액, `refundedAmount`는 실제 누적 환불액입니다. `refundStatus`와 함께 표시합니다.
- 취소 요청 성공과 PayPal 환불 완료를 같은 것으로 표시하지 않습니다. 반영된 상태를 재조회합니다.
- 결제 진행/대사 오류는 가능한 경우 `paymentId`를 제공합니다. 고객 `GET /api/v1/nadree/rental/payment/{paymentId}`로 확인하고 새 청구를 무조건 만들지 않습니다.
- 늦은 실제 결제·중복 추가 청구의 전액 환불 방어 로직은 유지하지만 실제 Sandbox 자금 처리 인수는 별도입니다.

## 7. 관리자 가입 정책 — 기존 확정 방식 유지

`POST /nadreego/admin/signup`의 전체 필수 항목은 Swagger를 따릅니다.

- representativeEmail 방식: 대표에게 일반관리자 가입 요청을 보내고 PENDING_APPROVAL/REQUESTED 상태로 대기합니다. 승인 전 관리 권한을 부여하지 않습니다.
- inviteCode 방식: 하위지점 생성 시 발급된 코드로 해당 지점 대표관리자가 즉시 ACTIVE로 가입합니다. 별도 승인 대기 없이 requestId/requestStatus는 null입니다.
- 코드는 가입 성공 시 소진되는 일회성입니다. 하위지점 생성 때만 발급하며 추가 발급·재발급 API/UI는 제공하지 않습니다. 사용한 코드는 재사용할 수 없습니다.
- 코드 가입이 상위 회사 전체의 대표 권한을 주는 것은 아닙니다.

## 8. 관리자 PayPal 판매자 연결·앱 복귀

### 8.1 기본 규칙

- 플랫폼은 공통 인증정보를 사용하고 판매자 ID는 지점별로 저장합니다. 여러 지점에서 같은 판매자 ID를 사용할 수 있습니다.
- 판매자 ID가 없는 지점은 APPROVE가 `409 SHOP_PAYPAL_MERCHANT_REQUIRED`로 차단됩니다. 예약 요청·거절은 유지합니다.
- 프론트는 연결 필요 안내와 버튼을 표시합니다. 백엔드가 연결 화면을 직접 열거나 연결 완료 후 예약을 자동 승인하지 않습니다.
- 연결·해제는 **해당 지점 직접 대표관리자만** 가능합니다. 일반관리자는 대표에게 요청하도록 안내합니다. 상위 대표의 하위지점 관리 권한이 판매자 연결 권한까지 부여하지는 않습니다.
- ID가 있어도 환경 불일치나 실제 PayPal 수취 권한 문제는 승인·결제에서 차단됩니다.

### 8.2 연결 API 순서

**① URL 발급** — 관리자 Bearer 인증

`POST /nadreego/shop/paypal-onboarding/start`

```json
{"spotMasterId":"실제_지점ID"}
```

응답의 `state`, `actionUrl`, `expiresAt`, `paymentEnvironment`를 사용합니다. state는 30분 동안 유효하며 발급받은 대표의 로그인 세션·지점·환경에 묶입니다. 새 start는 새 URL을 발급합니다.

**② PayPal 연결 화면**

actionUrl을 열어 판매자가 PayPal에 로그인하고 나드리를 통한 결제·환불 처리 권한에 동의합니다. 고객의 결제 승인과는 별개인 판매자 계정 연결 절차입니다.

**③ 앱 복귀 후 검증·저장**

`POST /nadreego/shop/paypal-onboarding/verify`

```json
{"spotMasterId":"실제_지점ID", "state":"복귀시_전달된_state"}
```

같은 관리자 로그인 세션을 유지해야 합니다. 서버가 state와 현재 권한을 검증하고 PayPal 서버에서 판매자 ID·권한을 확인한 뒤 저장합니다. 클라이언트가 merchantId나 merchantIdInPayPal을 저장 요청값으로 보내지 않습니다.

성공 응답의 필드는 `status`, `spotMasterId`, `merchantId`, `paymentEnvironment`입니다.

**④ 저장 성공 확인 후 연결 화면 종료**

PASS처럼 기존 관리자 앱 화면으로 돌아오는 UI를 프론트에서 구현합니다. 플랫폼별로 화면 전환 순서는 달라질 수 있지만 **verify 저장 성공 전에는 연결 완료로 표시하지 않습니다**. 실패·사용자 취소를 구분하고, 성공 후 필요하면 예약 승인을 별도로 재요청합니다.

### 8.3 프론트에 요청하는 복귀 설정

- 앱 복귀 링크·화면 종료·state 수신 처리는 프론트 담당입니다. 백엔드는 별도 홈페이지나 임의 URL을 만들지 않습니다.
- 사용할 **HTTPS 앱 복귀 URL**과 Android/iOS 처리 방식을 확정하여 서버 담당자에게 전달해 주세요. 현재 서버는 HTTPS만 허용하므로 커스텀 스킴은 사전 협의가 필요합니다.
- 서버 담당자가 받은 주소를 `NADREE_PAYPAL_ONBOARDING_RETURN_URL`에 설정합니다. 이 값은 불필요해서 없앤 것이 아니라 **프론트 확정 전 보류**입니다.
- 현재 미설정 상태에서는 start가 `503 PAYPAL_ONBOARDING_RETURN_URL_REQUIRED`를 반환합니다. 연결 UI 자체 구현과 별개로 실제 PayPal 왕복 검증은 설정 후 진행합니다.
- 복귀 기본 URL에는 query/fragment를 넣지 않습니다. 서버가 state를 붙입니다. state는 로그·분석도구에 남기지 않고 URL에서 제거하며, 실패·취소·연결 해제 시 불필요한 보관값을 정리합니다.

### 8.4 조회·해제·예외

조회: `GET /nadreego/shop/paypal-merchant?spotMasterId=...`  
해제: `PUT /nadreego/shop/paypal-merchant`

```json
{"spotMasterId":"실제_지점ID", "merchantId":null}
```

임의 ID 수동 입력은 `409 PAYPAL_ONBOARDING_REQUIRED`입니다. 기존 판매자와 다른 ID로 바꾸려면 해제 후 다시 연결합니다. 현재 지점 연결 변경은 기존 결제의 원판매자 ID를 변경하지 않습니다.

| 오류 | 프론트 처리 |
| --- | --- |
| SHOP_PAYPAL_MERCHANT_REQUIRED | 직접 대표에게 판매자 연결 안내 |
| SHOP_PAYPAL_ALREADY_CONNECTED | 저장값 조회, 필요 시 명시적 해제 후 재연결 |
| SHOP_PAYPAL_ENVIRONMENT_MISMATCH | Sandbox/Live 설정 확인, 현재 환경으로 재연결 |
| PAYPAL_ONBOARDING_INCOMPLETE / PAYPAL_MERCHANT_NOT_READY | PayPal 연결·계정 준비 상태 안내, 성공 처리 금지 |
| 400 PAYPAL_ONBOARDING_STATE_INVALID | state/지점/로그인 세션 확인, 필요 시 새 start |
| 410 PAYPAL_ONBOARDING_STATE_EXPIRED | 기존 state 폐기 후 새 start |
| 503 PAYPAL_ONBOARDING_RETURN_URL_REQUIRED | 복귀 URL 서버 설정 대기 안내 |
| 403 권한 오류 | 직접 대표 계정으로 연결하도록 안내 |

별도 온보딩 상태 테이블·자동 복구 타이머는 없습니다. `/paypal-onboarding/status`, `/paypal-onboarding/refresh`는 제공하지 않습니다. 브라우저를 닫았거나 state를 잃었으면 성공으로 추정하지 말고 저장값을 확인합니다. 새 로그인 세션이나 만료된 state는 새 start가 필요합니다.

state의 개별 취소 저장소도 없습니다. 해제 후 유효한 state로 같은 대표 세션이 verify를 명시적으로 다시 호출하면 재연결될 수 있으므로 해제 후 자동 재전송하지 않습니다.

## 9. 탈퇴·채팅·App Check

- `DELETE /api/v1/nadree/user/account`는 진행 중 거래 여부를 이유로 탈퇴를 제한하지 않습니다. 기존 예약·결제 참조는 보존하며 자동 취소·환불하지 않습니다.
- 성공 응답은 `{"status":"success","deleted":true}`입니다. 프로필/FCM·서비스 토큰 폐기와 Firebase 계정 삭제·채팅 회수의 기존 처리를 유지합니다.
- `cleanupStatus`, `privacyStatus` 추가와 전용 개인정보 정리 테이블·타이머는 제외했습니다. 과거 주소·채팅 본문 후속 삭제가 완료됐다고 표시하지 않습니다.
- 외부 서비스 오류 응답을 탈퇴 성공으로 취급하지 않습니다. 성공·로그아웃 시 로컬 토큰과 개인정보·채팅 캐시를 정리합니다.
- 채팅은 직접 지점 대표가 답변하고 일반관리자는 조회하는 기존 계약을 유지합니다. 이번 문서로 Firebase 컬렉션·callable 경로를 변경하지 않습니다.
- App Check 디버그 검증 도구는 준비됐지만 실제 기기/HTTP 종단 검증은 남아 있습니다. FCM 토큰으로 App Check 토큰을 대체하거나 검증을 끄지 않습니다.
- 여권 기능 및 파일 정리는 기존 보류 정책대로 이번 변경 대상이 아닙니다.

## 10. 웹훅 보완 상태 및 남은 검증

현재 Sandbox 앱의 기존 웹훅에서 다음 5개 구독 보완은 담당자 안내 기준 완료입니다. 기존 콜백은 `https://na-dree.com/nadreego/paypal/webhook`이며 프론트의 앱 복귀 주소와는 다른 서버 통지 주소입니다.

```text
CHECKOUT.PAYMENT-APPROVAL.REVERSED
PAYMENT.CAPTURE.DECLINED
PAYMENT.CAPTURE.REVERSED
PAYMENT.REFUND.FAILED
PAYMENT.REFUND.PENDING
```

프론트가 별도 웹훅 수신 서버를 만들 필요는 없습니다. API 응답과 상태 조회로 결과를 표시합니다. 구독 보완만으로 실제 결제·환불·서명 웹훅 처리가 검증된 것은 아닙니다.

아래 항목은 추가 기능 요청이 아니라 인수·운영 준비 사항입니다.

- 프론트: HTTPS 앱 복귀 주소 전달, 같은 관리자 세션 유지, 저장 성공 후 화면 종료·실패/취소 처리.
- 공동: 지정된 Sandbox 판매자·구매자로 연결 → 승인 → 주문 → 구매자 승인 → 캡처 → 고객/관리자 환불 → 실제 웹훅 상태 반영 확인.
- 공동: 소모 가능한 테스트 데이터와 푸시 영향 범위를 정하여 실제 예약 생성·취소·가입코드 소진·탈퇴·채팅·App Check 검사.
- 서버 운영: 결제·환불 복구 작업의 실행 주체·주기 확인. 서버 보고서에서는 로컬 등록을 찾지 못했으므로 자동 복구 가동을 보장하지 않습니다.
- 서버 운영: 판매자 ID가 없는 과거 결제 4건은 원거래 대조 전 임의 재처리하지 않습니다. 프론트가 현재 지점 판매자로 대체하거나 새 결제를 반복해서 만들지 않습니다.

이번에 제외한 요청 결과·개인정보 작업·온보딩 테이블 3개와 신규 전용 타이머는 프론트 연동의 전제조건이 아닙니다. 기존 결제·환불 복구 작업은 이 제외 항목과 다릅니다.

## 11. 전달 후 프론트 체크리스트

- [ ] 가격 편집은 tiers, 실제 적용 구간 표시는 effectiveTiers 사용.
- [ ] BASIC 배열 저장·정확 구간 수정·중첩 오류 처리.
- [ ] 예약에 선택한 priceOptionId·배송 포함 totalPrice 전달.
- [ ] 편도/왕복 주소 및 배송 요금표 지역 선택 처리.
- [ ] 종료 내역 4종과 예약 ID 직접 조회 반영.
- [ ] 고객 90%/0%, 지점 귀책 관리자 100% 취소 UI 구분.
- [ ] 이메일 승인 대기와 코드 즉시 대표 가입을 구분, 코드 재발급 UI 제외.
- [ ] 판매자 미연결 승인 오류 → 직접 대표 PayPal 연결 버튼 처리.
- [ ] 앱 복귀 URL 전달 및 start → verify → 저장 성공 확인 → 화면 종료 구현.
- [ ] 요청 키 복구·온보딩 status/refresh·개인정보 정리 상태 필드를 사용하지 않음.
- [ ] 실제 Sandbox 및 기기 검증 결과를 모의/격리 테스트와 구분.

근거: 저장소 코드, [전체 인수서](nadree-full-change-handoff.md), [2026-10-19 서버 검증 보고서](server-requirements-verification-2026-10-19.md), 이후 웹훅 5개 적용 완료 안내. 과거 인수서의 ‘서버 미적용’ 및 보고서 중간의 ‘OAuth 실패·웹훅 조회 미실행’은 당시 기록이며 최신 결과와 구분합니다.
