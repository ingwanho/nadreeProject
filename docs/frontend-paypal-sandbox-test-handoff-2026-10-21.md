# 프론트 전달 — PayPal Sandbox 수정 결과와 테스트 순서

작성일: 2026-10-21

대상: 고객 결제 화면 및 관리자 예약 승인 담당자

API: `https://na-dree.com`

Swagger: `https://na-dree.com/docs`

## 1. 어디부터 테스트하면 되나요?

**기존 결제 5번이 아닌 새 결제 6번부터 테스트합니다.** 서버에서 새 예약 요청·관리자 승인·Sandbox 주문 생성까지 실제로 완료했습니다. 프론트는 예약을 다시 만들지 말고, 먼저 **결제 6번 소유 고객으로 로그인 → 결제 상태 조회 → 구매자 승인 → 앱 복귀 → 캡처 → 최종 PAID 확인** 순서로 진행합니다.

**5번과 6번의 소유 고객은 동일합니다.** 같은 고객·기간·모델·가격 조건으로 새 예약을 생성한 것입니다. 이전 테스트 고객으로 다시 로그인하면 되며, 다른 UID나 관리자 토큰으로 고객 결제를 조회하지 않습니다.

서버의 최신 확인 시점은 **2026-10-20 15:01 UTC / 2026-10-21 00:01 한국 시간**입니다. 아래 상태는 그 시점의 기록이며, 테스트를 시작할 때 반드시 API로 현재 상태와 결제 기한을 다시 확인합니다.

| 항목 | 사용할 값 / 확인된 상태 |
| --- | --- |
| 결제 ID | `6` |
| 예약 ID / bookingId | `a70ec730-4b8d-4bdd-b075-f2ac4611bd72` |
| 지점 ID / shopId | `00000000-0000-4000-8000-000000000101` |
| 모델 ID | `NRTEST-WEB-MODEL-125` |
| 렌탈 기간 | `2026-10-31` ~ `2026-11-02` |
| 선택 조건 | PREMIUM · 픽업 · 배송 미사용 |
| 결제 금액 | `90 USD` |
| 예약 상태 | `APPROVED` |
| 서버 결제 상태 | `CREATED` |
| PayPal 주문 상태 | `PAYER_ACTION_REQUIRED` |
| 프론트 다음 동작 | `nextAction=APPROVE` |
| 구매자 승인·캡처·환불 | 새 결제 6번에서는 아직 실행하지 않음 |

기존 결제 5번과 연결된 예약은 정상 취소됐습니다. 결제 상태는 `CANCELED`, 환불은 `NOT_REQUIRED`이며 기존 주문·요청·예약 이력은 보존했습니다. **5번의 캡처를 재시도하거나 데이터를 초기화하지 않습니다.**

## 2. 해결·보완된 내용

| 이전 증상 | 반영 내용 / 현재 확인 범위 |
| --- | --- |
| Sandbox OAuth `401 invalid_client` | 설정 수정 후 OAuth HTTP 200 확인. 새 주문 생성과 PayPal 주문 조회도 성공했습니다. |
| 판매자 연결 중 `PAYPAL_REFERRAL_INVALID` | Sandbox/Live별 공식 API self 링크 호스트를 검증하도록 보완. 실제 온보딩 start HTTP 200 확인. |
| 예약 승인 중 불필요한 `409 RESERVATION_CHANGED` | 다른 승인 대기 예약을 잘못 갱신하던 배정 저장 로직 보완. 새 테스트 예약 승인 HTTP 200 확인. 실제 동시 변경에 대한 409 검사는 유지합니다. |
| 주문 생성 전 판매자 조회의 인증 오류 | 플랫폼 판매자 조회에서는 판매자용 assertion을 제외하고, 주문·캡처·환불의 판매자 인증은 유지합니다. 새 Sandbox 주문 생성 HTTP 200 확인. |
| 구매자 승인 후 `PAYPAL_APPROVAL_URL_MISSING` | `APPROVED` 주문은 승인 링크가 없어도 정상이며 `approvalUrl=null`을 허용합니다. 별도 캡처가 필요합니다. |
| 프론트가 다음 결제 단계를 판단하기 어려움 | order/capture/status 응답에 `paypalOrderStatus`, `nextAction`, `canCapture` 추가. 아래 동작표를 사용합니다. |
| 승인 전 캡처 요청이 처리 중 상태를 남김 | 최초 캡처 기록 전에 승인 상태·판매자 권한을 확인하도록 보완. 격리 회귀에서 확인했습니다. |

결제 단계 보완 코드는 서버 재시작·health/live HTTP 200까지 확인됐습니다. 관련 전체 격리 회귀는 서버 기록 기준 **377 passed / 12 skipped / 0 failed**입니다. 건너뛴 항목은 MySQL 8개·Firestore 에뮬레이터 4개이며 이 숫자를 실제 PayPal 결제 성공 건수로 해석하지 않습니다.

**실제 완료 범위는 새 주문 생성·조회 및 구매자 승인 대기까지입니다.** 새 주문의 실제 구매자 승인·캡처·서명 웹훅 정산·환불·실기기 복귀는 프론트 연동 테스트에서 이어서 확인해야 합니다.

## 3. 테스트에 필요한 계정과 인증

- 고객 앱: **기존 결제 5번과 새 결제 6번을 소유한 동일 고객**으로 로그인합니다. UID와 로그인 정보는 비공개로 공유받은 기존 테스트 정보를 사용합니다. 이 문서에는 포함하지 않습니다.
- PayPal 승인 화면: 별도로 준비한 **Sandbox 구매자 테스트 계정**을 사용합니다. 고객 앱 계정과 PayPal 구매자 계정은 서로 다른 인증입니다. 판매자 연결용 계정과도 구분합니다.
- 관리자 앱: 기존 결제 6번 테스트에서는 재승인할 필요가 없습니다. 처음부터 새 예약을 만드는 별도 시나리오에서만 승인 권한이 있는 테스트 관리자 계정이 필요합니다.
- PayPal Client Secret·플랫폼 자격증명은 백엔드 전용입니다. 프론트에 넣거나 PayPal 캡처 API를 직접 호출하지 않습니다.

서버 테스트 종료 시 고객·관리자 로그아웃을 완료했습니다. 예전 access token을 재사용하지 말고 다시 로그인합니다. `FIREBASE_REAUTHENTICATION_REQUIRED`가 나오면 Firebase SDK에서 재인증한 뒤 로그인합니다. 단순 ID Token 갱신만으로 이전 인증 시각이 새로워지는 것은 아닙니다.

고객 백엔드 로그인 계약:

```http
POST /api/v1/nadree/user/login
Authorization: Bearer <현재 고객의 Firebase ID Token>
Content-Type: application/json

{"UID":"<해당 Firebase ID Token과 동일한 고객 UID>"}
```

이 응답의 **백엔드 `accessToken`**을 아래 결제 API의 Bearer에 사용합니다. Firebase ID Token·관리자 access token과 혼용하지 않습니다. 이후 예시의 `CUSTOMER_ACCESS_TOKEN`은 이 값을 로컬 변수에 설정했다는 전제입니다. 비밀값을 문서나 테스트 결과에 복사하지 않습니다.

## 4. 기존 결제 6번 테스트 순서

### 1단계 — 상태와 소유권부터 확인

```sh
API_BASE_URL='https://na-dree.com'
PAYMENT_ID=6

curl -sS "${API_BASE_URL}/api/v1/nadree/rental/payment/${PAYMENT_ID}" \
  -H "Authorization: Bearer ${CUSTOMER_ACCESS_TOKEN}"
```

확인할 핵심 필드 예시입니다. 전체 응답이 아니며, 실제 상태는 실행 시점 응답을 우선합니다.

```json
{
  "status": "success",
  "paymentId": 6,
  "reservationId": "a70ec730-4b8d-4bdd-b075-f2ac4611bd72",
  "paymentStatus": "CREATED",
  "paypalOrderStatus": "PAYER_ACTION_REQUIRED",
  "nextAction": "APPROVE",
  "canCapture": false,
  "totalPrice": 90,
  "currency": "USD"
}
```

- `paymentId`·예약 ID·금액·통화·`paymentDeadline`을 확인합니다.
- 응답의 `paypalOrderId`와 `approvalUrl`을 해당 결제에 묶어 보관합니다.
- `APPROVE`이면 아래 구매자 승인 단계로 이동합니다. 이미 `CAPTURE`이면 승인 화면을 다시 열지 않습니다.
- `WAIT`·`REVIEW`·`NONE`이면 캡처하거나 새 주문을 만들지 말고 5절의 동작표를 따릅니다.
- 404라면 고객 계정·결제 소유권을 먼저 확인합니다. 다른 고객의 결제를 볼 수 없도록 차단하는 것이 정상입니다.

### 2단계 — 응답의 approvalUrl로 구매자 승인

`nextAction=APPROVE`일 때 **이번 상태 응답의 `approvalUrl`**을 고객 앱 WebView 등 기존 결제 화면으로 엽니다. 예전에 공유한 5번 승인 링크나 하드코딩한 PayPal 주문 링크를 사용하지 않습니다.

Sandbox 구매자 계정으로 로그인해 구매자 승인을 완료합니다. 이 단계의 `APPROVED`는 구매자 승인이지 서버 결제 완료가 아닙니다.

### 3단계 — 고객 결제 복귀 URL 감지

고객 결제의 기준 복귀 주소:

```text
https://na-dree.com/api/v1/nadree/rental/payment/return
```

WebView에서 **HTTPS origin과 path가 정확히 일치하는 이동**을 감지합니다. 단순 문자열 포함 여부로 비교하지 않습니다.

1. `cancelled=true`이면 결제 화면 취소로 처리합니다. 캡처와 예약 취소 API를 자동 호출하지 않습니다.
2. 승인 복귀이면 query의 `token`을 보관한 `paypalOrderId`와 대조합니다. 누락·불일치 시 캡처하지 않고 상태 확인·오류 안내를 합니다.
3. 일치해도 바로 성공 화면을 표시하지 않습니다. 같은 결제 ID로 상태 API를 다시 조회합니다.
4. 최신 응답이 `canCapture=true`이고 `nextAction=CAPTURE` 또는 `RETRY_CAPTURE`일 때만 다음 단계로 진행합니다.

이 복귀 주소는 앱이 감지하는 목적지이며 **새로운 GET 결제 완료·캡처 API가 아닙니다.** 일반 브라우저에서 주소를 직접 여는 것으로 결제를 완료하거나, 별도 완료 페이지가 있다고 가정하지 않습니다. 실제 앱 복귀·화면 종료는 프론트에서 처리합니다.

### 4단계 — 같은 paymentId로 명시적 캡처

**3단계의 허용 조건을 확인한 뒤에만 실행합니다.** 요청 중 결제 버튼을 비활성화하고 동일 결제에 대한 동시 호출을 막습니다.

```sh
curl -sS -X POST "${API_BASE_URL}/api/v1/nadree/rental/payment/capture" \
  -H "Authorization: Bearer ${CUSTOMER_ACCESS_TOKEN}" \
  -H 'Content-Type: application/json' \
  --data '{"paymentId":6}'
```

- 캡처는 Sandbox 자금 처리를 실행하는 단계입니다. 상태 조회와 다릅니다.
- 신규 order를 생성하거나 다른 paymentId로 바꾸지 않습니다.
- HTTP 200이어도 `paymentStatus=PENDING`일 수 있습니다. 완료로 표시하지 말고 상태 조회로 이어갑니다.
- 타임아웃·5xx가 발생하면 즉시 재청구하지 않습니다. 먼저 GET 상태를 확인하고 `RETRY_CAPTURE`일 때만 동일 paymentId로 명시적 재시도를 제공합니다. 재시도 키는 서버가 관리합니다.

### 5단계 — 최종 PAID 확인

1단계와 같은 GET 상태 API를 호출합니다. **서버 응답의 `paymentStatus=PAID`를 확인한 뒤** 최초 결제 완료 화면을 표시합니다.

`paypalOrderStatus=APPROVED`·`COMPLETED`, 캡처 ID 존재, 복귀 URL 도착, HTTP 200 중 하나만으로 완료 처리하지 않습니다. `PENDING`·`WAIT`이면 웹훅/정산 반영을 기다립니다.

폴링은 **5초 이상 간격**, 조회 중복 방지, 화면 이탈 시 중단을 권장합니다. PG 조회가 필요한 상태 API에는 고객별 **30회/분** 제한이 있습니다. 짧은 대기 후에도 확정되지 않으면 처리 중으로 안내하고 담당자에게 전달합니다. 무한 자동 캡처나 order 반복 호출로 해결하지 않습니다.

## 5. nextAction별 화면·버튼 처리

| nextAction | 프론트 동작 | 캡처 |
| --- | --- | --- |
| `APPROVE` | 이번 응답의 approvalUrl로 구매자 승인 화면 열기 | 금지 |
| `CAPTURE` | 같은 paymentId로 캡처 진행 | canCapture=true일 때 가능 |
| `RETRY_CAPTURE` | 상태 확인 후 같은 paymentId로 명시적 재시도. 무한 자동 재시도 금지 | canCapture=true일 때 가능 |
| `WAIT` | 처리 중 안내·GET 상태 조회. 새 주문 생성 금지 | 금지 |
| `DONE` | paymentStatus에 맞는 결제/환불 상태 표시 | 추가 캡처 금지 |
| `REVIEW` | 버튼 중지·운영 담당자 대조 요청 | 금지 |
| `NONE` | 현재 결제 진행 동작 없음. 기한·예약/결제 종료 상태 확인 | 금지 |

`DONE`에는 `PAID`뿐 아니라 `PARTIALLY_REFUNDED`·`REFUNDED`도 포함됩니다. 무조건 “결제 성공”으로 표시하지 않습니다.

기존 `canPay`는 결제 가능 상태를 나타내는 기존 필드이며 캡처 재시도 판정 필드가 아닙니다. **기존 결제의 캡처/재시도 버튼은 `canCapture`와 `nextAction`으로 판단합니다.** `canPay=false`여도 `RETRY_CAPTURE/canCapture=true`일 수 있습니다. 반대로 `approvalUrl=null`만으로 캡처를 허용하면 안 됩니다.

재시도 허용 시간은 **최초 capture_requested_at부터 5시간 이내**이며 결제 기한 등 다른 제한도 함께 적용됩니다. 프론트가 시간을 재설정하거나 `PENDING`을 초기화하지 않습니다. 최종 허용 여부는 매번 서버가 다시 검사합니다.

## 6. 처음부터 새 예약으로 테스트해야 하는 경우

6번 소유 고객으로 로그인할 수 없거나 기한이 지난 경우, 임의 UID로 6번을 사용하지 않습니다. 기존 거래를 담당자와 대조한 후 별도 테스트 예약 생성 여부를 정합니다. **6번 정상 흐름을 확인하려는 테스트와 새 예약 생성 테스트를 섞지 않습니다.**

새 예약 생성이 합의됐을 때의 순서:

1. 토큰 없이 `POST /api/v1/nadree/rental/availability`로 유효한 미래 기간·125cc·배송 미사용 조건을 조회합니다.
2. 테스트 지점/모델 응답의 선택 옵션에서 `priceOptionId`와 `totalPrice`를 가져옵니다. 기존 테스트의 USD 90을 새 견적에 무조건 재사용하지 않습니다.
3. 고객 Bearer로 `POST /api/v1/nadree/rental/request`를 호출합니다. 지점·모델·기간·금액·통화·가격 옵션·배송 조건을 함께 전달합니다.
4. 관리자 Bearer로 `POST /nadreego/booking/action`에 `{"bookedNo":"BO<새 reservationId>","action":"APPROVE"}`를 전달합니다. 예약 응답의 bookedNo가 있으면 그 값을 사용합니다.
5. 고객 Bearer로 아래 주문 API를 호출합니다.

```http
POST /api/v1/nadree/rental/payment/order
Authorization: Bearer <고객 백엔드 accessToken>
Content-Type: application/json

{"reservationId":"<새로 승인된 reservationId>"}
```

6. 응답의 **새 paymentId/paypalOrderId**를 보관하고 4절의 승인·복귀·캡처·상태 확인 흐름을 진행합니다. 이 경우 6번 ID를 하드코딩하지 않습니다.

승인 단계에서 `SHOP_PAYPAL_MERCHANT_REQUIRED`이면 해당 지점 대표의 기존 PayPal 온보딩 start → 판매자 로그인·동의 → 동일 관리자 세션 verify로 연결·저장한 뒤 예약 승인을 별도로 재요청합니다. Merchant ID를 프론트가 직접 저장하는 방식이 아닙니다. 결제 6번은 이미 예약 승인·주문 생성이 끝났으므로 이 단계를 다시 할 필요가 없습니다.

고객 결제 복귀 `/api/v1/nadree/rental/payment/return`과 관리자 판매자 연결 복귀 `/nadreego/shop/paypal-onboarding/return`은 서로 다른 흐름입니다. 관리자 복귀에서는 verify를, 고객 승인 복귀에서는 상태 확인 후 capture를 사용합니다.

## 7. 오류·중단 상황 처리

| 응답 / 상황 | 처리 |
| --- | --- |
| 401 / FIREBASE_REAUTHENTICATION_REQUIRED | 고객 인증·백엔드 로그인 갱신. 관리자 토큰이나 UID만으로 우회하지 않습니다. |
| 404 / PAYMENT_NOT_FOUND | 결제 ID와 소유 고객을 확인합니다. 임의 계정으로 재시도하지 않습니다. |
| 409 / PAYMENT_STATE_INVALID | 구매자 승인 여부를 상태 API로 확인합니다. 승인 전 캡처를 반복하지 않습니다. |
| 409 / PAYMENT_IN_PROGRESS | 기존 paymentId로 상태 조회. nextAction/canCapture에 따라 대기 또는 같은 결제 재시도만 진행합니다. |
| 409 / PAYMENT_RECONCILIATION_REQUIRED | 자동 재시도 중지·운영 대조. 새 주문·새 요청 키·DB 초기화로 우회하지 않습니다. |
| 409 / PAYMENT_DEADLINE_EXPIRED | 결제 중단. 서버의 기한을 우회하거나 같은 건을 자동 재생성하지 않습니다. |
| PAYPAL_SERVICE_UNAVAILABLE / 5xx / 타임아웃 | 성공·실패를 단정하지 말고 상태 확인. 캡처 성공 여부가 불명확하면 새 결제 생성 금지. |
| PAYPAL_APPROVAL_URL_MISSING | 현재 nextAction 및 오류를 기록해 백엔드에 전달. 임의 승인 링크를 만들지 않습니다. |
| 429 | 조회 빈도를 낮추고 진행 중 요청을 중복 실행하지 않습니다. |

프론트 전달 정보는 발생 시각·단계·paymentId·reservationId·HTTP 상태·errorCode·paymentStatus·paypalOrderStatus·nextAction·canCapture입니다. **access/refresh token, Firebase ID Token, PayPal 승인 링크/token, 비밀번호·Secret, 개인정보는 공유 로그에 넣지 않습니다.** 백엔드 담당자는 해당 시각의 안전한 PayPal 오류 로그에서 HTTP 상태·error_code·PayPal Debug ID를 대조할 수 있습니다.

## 8. 이번 테스트의 완료 기준

- [ ] 기존 5번과 동일 고객으로 재로그인해 결제 6번 상태 조회 성공.
- [ ] 이번 응답의 Sandbox 승인 링크로 구매자 승인.
- [ ] 실제 앱에서 고객 복귀 주소 감지·주문 token 대조 성공.
- [ ] 승인 취소 복귀 시 자동 캡처·자동 예약 취소하지 않음.
- [ ] 승인 후 nextAction/canCapture에 맞춰 같은 paymentId로 캡처.
- [ ] HTTP 200/PENDING을 결제 완료로 오인하지 않고 서버 PAID까지 확인.
- [ ] 응답 유실·중복 탭에서 새 결제를 만들거나 캡처를 무한 반복하지 않음.

환불은 **최초 PAID 흐름을 확인한 다음 별도 테스트 건·담당자 협의로 진행**합니다. 하나의 결제에 고객 취소와 관리자 취소를 모두 적용할 수 없으므로 각각 분리합니다. 기존 고객 시작일 전 90%/당일부터 0%, 관리자 지점 귀책 인계 전 100% 정책은 유지합니다. 신규 주문 생성 성공을 실제 환불 성공으로 표시하지 않습니다.

실제 서명 웹훅 수신·DB 정산은 백엔드 담당자와 함께 확인합니다. App Check·실기기 FCM·회원탈퇴·자동 만료 등 다른 기능의 전체 인수 완료를 뜻하는 문서는 아닙니다.

## 근거 문서

- [서버 실제 적용·검증 결과](server-requirements-verification-2026-10-19.md): 최신 「기존 테스트 예약 취소·신규 Sandbox 주문 생성 완료」 및 「결제 단계·진단 로그·안전한 캡처 재시도 보완」 절.
- [전체 변경 인수 문서](nadree-full-change-handoff.md): 최신 테스트 결제 대상 변경 및 nextAction 계약.
- [기존 앱·웹 프론트 전달서](frontend-final-changes-2026-10-19.md): 가격·배송·가입 등 이번 결제 안내 외 계약.

이 문서는 위 서버 기록과 현재 코드/Swagger 스키마를 대조해 작성했습니다. 문서 작성 과정에서 실제 결제·환불·로그인·DB 변경을 새로 실행하지 않았습니다. 과거 5번 테스트 안내보다 이 문서의 **6번부터 시작하는 안내**를 우선합니다.
