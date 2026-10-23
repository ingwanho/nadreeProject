# 추가 테스트 지점 — 앱 테스트 데이터와 진행 순서

2026-10-23 기준. 고객 앱·관리자 앱에서 사용할 추가 테스트 지점 정보다. API 주소는 `https://na-dree.com`이며, API 필드·인증·채팅 연결 방식은 기존 계약을 따른다.

## 지점과 로그인 계정

| 항목 | 값 |
| --- | --- |
| 지점명 | Nadree 테스트 2호점 |
| shopId / spotMasterId | `7da0fa0c-af0e-4785-9068-3616f6383828` |
| 지점 코드 | `NR_TEST_20260921-ORG01-SP01` |
| 상위 테스트 조직 | `00000000-0000-4000-8000-000000000101` |
| 주소 | Jl. Sunset Road No. 102, Kuta, Bali (Nadree Test Branch 2) |
| 좌표 | 위도 `-8.7021`, 경도 `115.1715` |
| 지점 연락 이메일 | `nadree.test.branch2@example.com` |
| 계약 기간 | 2026-10-23 ~ 2027-12-31 |
| 배송 방식 | `START_AND_RETURN` |

| 계정 | 로그인 ID / 이메일 | 역할 |
| --- | --- | --- |
| 지점 대표 | `nadree.test.branch2.admin@example.com` | `rental_primary_admin` |
| 일반관리자 | `nadree.test.branch2.staff@example.com` | `rental_manager` |

두 계정 모두 새 지점에 직접 소속되어 있으며 로그인 가능하다. 일반관리자는 이메일 가입 승인 대기를 거쳐 승인됐다. 대표 가입에 사용한 일회성 지점 코드는 소진됐다.

비밀번호는 서버의 접근 제한 파일 `/srv/nadree-api/build/test-runtime/branch2-setup-2026-10-23/credentials.private.json`에 별도로 보관한다. 서버 접근 권한이 있는 담당자를 통해 확인한다. 문서·메신저·앱 로그에 비밀번호나 로그인 토큰을 복사하지 않는다.

검증용 로그인 세션은 종료했다. 앱에서는 위 계정으로 로그인부터 진행한다. 기존 테스트 대표·고객 계정도 검증 중 세션이 교체됐으므로 401이 발생하면 다시 로그인한다.

## 차량·QR·가격

금액 단위는 USD다. 차량은 모두 대여 가능 상태로 등록했다.

| 번호판 | 차량 ID | 모델 ID | 가격 | QR 원문 | 장비 |
| --- | --- | --- | --- | --- | --- |
| `DK-B2-BASIC-125` | `a31ae675-1725-4cde-bd27-1a3da03071b4` | `NRTEST-WEB-MODEL-125` | BASIC 28/일 | `testQr223123` | QR_ONLY |
| `DK-B2-PREMIUM-125` | `6f6820a3-e747-4644-a2bd-b70798f1db39` | `NRTEST-WEB-MODEL-125` | PREMIUM 48/일 | `testQr556456` | QR_WITH_SENSOR |
| `DK-B2-BASE-155` | `ccde8261-0c90-4eca-9dd4-225a5676ffe6` | `NRTEST-MODEL-155` | 공통 BASE 35/일 | `testQrB2Base155` | QR_ONLY |
| `DK-B2-NODELIVERY` | `97fa6a64-27a7-4426-b413-00f8f2ec95fc` | `NRTEST-WEB-MODEL-ND` | BASIC 28/일, 배송 미지원 | `testQrB2NoDelivery` | QR_ONLY |

센서 연결 차량의 sensorId는 `NRTEST-B2-SENSOR-001`이다. 센서 연결 데이터 조회만 확인했으며 실제 센서 통신·위치 수신은 별도 검증 대상이다.

125cc BASIC은 새 지점의 `100~125cc` 구간 가격 28을 적용한다. 155cc는 지점 BASIC 구간 밖이므로 공통 BASE 가격 35를 적용한다. PREMIUM은 고정 단가 48을 적용한다.

QR 조회에는 해시 대신 위 원문을 보낸다. 예:

```http
POST /nadreego/vehicle/qr/validate
Authorization: Bearer <새 지점 관리자 access token>
Content-Type: application/json

{"qrCode":"testQr556456"}
```

이 요청은 `QR_WITH_SENSOR`와 연결 센서를 반환한다. 기존 지점의 `testQr123123`을 새 지점 계정으로 조회하면 `404 QR_NOT_FOUND`가 정상이다.

## 배송과 견적

| 배송 요금표 | deliveryRegionId | 시작 배송 | 반납 배송 | 왕복 |
| --- | --- | --- | --- | --- |
| Kuta | `990000001` | 12 | 12 | 24 |
| Canggu | `990000002` | 16 | 16 | 32 |

앱은 선택한 `deliveryRegionId`와 `deliveryRequestType`, 필요한 픽업·반납 주소를 함께 보낸다. 주소 좌표로 배송 구역을 자동 판정하는 흐름은 제공하지 않는다. 배송 미지원 모델은 배송 조건 조회에서 제외되며 직접 배송 예약 요청 시 `409 DELIVERY_NOT_SUPPORTED`를 반환한다.

비예약 기간의 2일 견적은 픽업 BASIC 56 / PREMIUM 96, 155cc BASE 70이다. Canggu 왕복 배송을 선택하면 125cc BASIC 88 / PREMIUM 128이다.

기존 지점과 모델 ID를 공유하지만 가격·배송비는 다르다. 지점·기간·배송 선택이 바뀌면 가용성과 견적을 다시 조회하고, 해당 응답의 `shopId`, `modelId`, `priceOptionId`, `totalPrice`를 함께 사용한다. 다른 지점에서 받은 가격 옵션을 재사용하면 안 된다.

## 예약 샘플

두 샘플의 기간은 발리 기준 **2026-10-30 ~ 2026-11-01**이다. 기존 승인된 테스트 고객 소유이며, 고객 상세 조회는 실제 소유자의 Firebase·백엔드 로그인으로 진행한다.

| 상태 | bookedNo | 내용 |
| --- | --- | --- |
| REQUESTED / SOFT_HOLD | `BO0c318425-7783-4502-adf8-1e1c89e3ab91` | PREMIUM 픽업, USD 96, 미결제 |
| CANCELED / RELEASED | `BOe76118a6-e0e5-4f61-a2f6-3df64fbef291` | BASIC + Canggu 왕복 배송, USD 88, 결제·환불 없음 |

대표·일반관리자의 예약 목록/상세 조회, 고객의 본인 상세 조회를 확인했다. 생성 직후 60초 내 동일 요청 반복은 `DUPLICATE_RENTAL_REQUEST`, 견적 금액 변경은 `PRICE_QUOTE_MISMATCH`로 차단된다.

REQUESTED도 재고를 점유한다. 샘플 기간에는 PREMIUM 한 대가 선점되어 같은 기간의 PREMIUM 신규 요청 옵션이 표시되지 않는 것을 확인했다. 2026-11-05 ~ 2026-11-07 조회에서는 BASIC/PREMIUM 두 옵션이 모두 반환됐다. 가격 옵션은 요청 시점의 재고에 따라 달라지므로 두 가격 옵션 비교는 비예약 기간으로 진행한다.

## 채팅과 지점 권한

- 새 지점 대표는 채팅 답변 가능, 일반관리자는 조회 가능하다.
- 상위 조직의 관리 권한이 하위 지점 채팅에 자동 상속되지는 않는다. 위 직접 소속 계정을 사용한다.
- 관리자 채팅 세션의 shops에는 새 지점이 포함된다. 고객 세션의 `shops=[]`, `managerId=null`은 정상 계약이다. 고객은 예약 ID로 예약방을 연결한다.
- 요청 샘플의 예약방은 `open`, 취소 샘플의 방은 `read_only`로 동기화된 것을 확인했다.
- 다른 지점 프로필·QR 접근 차단을 확인했다. 지점 전환 시 이전 계정의 토큰·구독을 혼용하지 않는다.

앱 로그인 후 FCM 등록·채팅 세션·Firebase 로그인·리스너 연결 순서는 [채팅 세션·FCM 앱 안내](chat-session-fcm-app-handoff-2026-10-22.md)를 따른다.

## 결제 연결과 앱에서 이어서 확인할 사항

새 지점은 **PayPal 판매자 미연결** 상태다. 직접 소속 대표 계정으로 기존 PayPal 판매자 연결 흐름을 완료해야 예약 승인·결제·인계까지 진행할 수 있다. 현재 승인 시 `409 SHOP_PAYPAL_MERCHANT_REQUIRED`, 미승인 예약의 주문 생성 시 `409 RESERVATION_NOT_APPROVED_FOR_PAYMENT`가 정상이다. 기존 지점의 연결 상태가 새 지점에 자동 적용되지는 않는다.

현재까지 실제 API로 계정·권한·가격·배송·QR·예약 요청/취소·채팅 세션을 확인했다. 이 새 지점의 실제 PayPal 연결·결제·환불, 앱 화면, 실기기 App Check·푸시 수신, 실제 차량 인계·센서 위치 수신은 별도 검증 대상이다.

지점 생성 화면에서 사업자번호 `biz_reg_num`은 현재 DB 기준 **20자 이하**로 보낸다. 이 지점의 테스트 값은 `NRTEST-B2-20261023`이다.
