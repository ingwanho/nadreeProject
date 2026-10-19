# Nadree 전체 변경사항 및 인수 문서

## 2026-10-18 최신 변경 — 프론트 전달 및 서버 적용

이 절이 아래 과거 정책·2026-10-16 수동 판매자 설정 문서보다 우선한다. **로컬 구현이며 서버 DB·실제 PayPal·Firebase에는 미적용**이다. 회사별 BASE 관리, 주소의 실제 배송구역 자동 판정, 가입코드 추가 발급/재발급은 이번 범위에서 제외한다.

### 프론트에 전달할 확정 정책

- BASE는 서비스 공통 기본 cc 가격이다. 약 4개 큰 구간을 운영 정책으로 정할 예정이며 이번 코드가 임의 가격이나 구간을 새로 생성하지 않는다.
- BASIC은 해당 지점의 cc 구간만 BASE보다 우선한다. 예: BASE 1~50cc/10 USD와 BASIC 1~25cc/12 USD가 있으면 1~25cc는 12 USD, 26~50cc는 BASE 10 USD다. BASE 전체를 BASIC으로 채울 필요는 없다. 중간 상위 지점 BASIC을 상속하지 않는다.
- PREMIUM은 차량별 고정 일단가다. PREMIUM 아닌 차량은 cc로 BASE/BASIC을 선택한다. 가격 설정은 정수 USD, 결제·환불은 USD 센트 단위다. 기존 확정 예약 금액에 가격 변경을 소급하지 않는다.
- representativeEmail 가입은 일반관리자 승인 요청(PENDING_APPROVAL/REQUESTED)이며 대표 승인 후 활성화된다. inviteCode 가입은 그 지점 대표관리자로 즉시 ACTIVE, requestId/requestStatus=null이다. 코드는 하위지점 생성 시만 자동 생성하고 가입 성공 트랜잭션에서 NULL로 소진한다. 추가 발급·재발급 API/UI는 제공하지 않는다.
- 관리자 CANCEL은 지점 귀책 전용: 당일 포함 인계 전 APPROVED에 대해 실제 결제 총액 100% 환불. 고객 사유 대리 취소는 지원하지 않으며 cancellationReasonType은 BRANCH_FAULT만 허용한다(생략해도 동일 정책). 고객 취소는 인계 전 시작일 전 90%, 당일부터 0%로 유지한다. 인계 후 취소 불가, 미결제/0% PG 환불 호출 없음.
- 실제 주소·좌표·placeId로 배송구역 안/밖을 판정하는 기능은 지역 정책 미확정으로 제외했다. 지역명 문자열 추정도 제거했다. 주소는 보관하되 배송 가능 구역으로 검증했다는 문구를 표시하지 않는다. 같은 장소인지의 지리적 자동 판정도 제공하지 않으며 기존 대표의 위치 정정 권한·이전값 충돌 검사·감사 이력은 유지한다.

### 가격 API

POST `/nadreego/shop/tierCreate`는 기존 단건 또는 동일 지점의 1~100개 배열을 받는다.

```json
[
  {"spotCode":"지점코드", "minCc":1, "maxCc":25, "price":12, "type":"BASIC"},
  {"spotCode":"지점코드", "minCc":26, "maxCc":50, "price":15, "type":"BASIC"}
]
```

배열 응답은 `{"status":"success","tiers":[...]}`이고 각 항목에 `action=CREATED|UPDATED`가 있다. 동일 지점·시작/끝 cc가 같으면 수정, 없으면 추가한다. 배열 전체가 한 트랜잭션이며 생략된 기존 티어를 삭제하지 않는다. 요청 내부 동일 구간 중복은 422 TIER_BATCH_DUPLICATE_RANGE, 지점 혼합은 422 TIER_BATCH_SPOT_MISMATCH, 부분 겹침은 409 TIER_RANGE_OVERLAP, 하나의 BASE 안에 속하지 않으면 409 TIER_BASE_NOT_UNIQUE다. 기존 넓은 BASIC을 세분화할 때는 기존 BASIC을 삭제한 뒤 새 구간 배열을 등록한다. 삭제 후에는 BASE로 복귀한다.

GET 같은 경로의 `tiers`는 편집용 원설정(BASE+BASIC), `effectiveTiers`는 겹침 없이 실제 적용되는 구간이다. **effectiveTiers의 BASE 잔여 구간을 저장/삭제용 원구간으로 사용하지 않는다.** spotCode 생략은 공통 BASE만, 지정하면 해당 지점을 조회한다. POST에서 spotCode 생략은 로그인 관리자의 직접 지점이다. 직접 지점 일반관리자와 허용 하위 지점 대표의 기존 가격 권한을 유지한다.

고객 availability의 `price.pricingTiers[]`에 `priceOptionId`와 배송비 포함 `totalPrice`를 추가했다. 예: BASIC:10, PREMIUM:10은 금액이 같아도 다른 선택이다. 프론트는 문자열을 직접 합성하지 말고 받은 값을 request의 priceOptionId로 보낸다. 식별자의 범위는 요청한 지점·모델·기간의 최신 견적이다. 구버전에서 옵션을 생략하면 총액에 맞는 옵션이 정확히 하나일 때만 허용한다. 모호하면 409 PRICE_OPTION_REQUIRED, 선택이 무효면 PRICE_OPTION_INVALID, 금액 변경은 PRICE_QUOTE_MISMATCH다. 예약 생성 때 옵션·재고·금액을 재검증하고 선택 스냅샷을 저장한다. 관리자 reservation.selectedPriceOption/pricingTiers는 현재 차량 정보가 아니라 예약 당시 선택이다.

### 배송·조회 계약

고객 availability/request의 pickupLocation·returnLocation은 최대 500자 주소 문자열(공백만 불가)이다. deliveryRegionId는 선택할 지점 요금표 지역 ID이며 지리 검증 결과가 아니다. 활성 요금표가 하나면 생략 가능, 여러 개면 선택 필요(예약 시 409 DELIVERY_REGION_REQUIRED). 지점이 지원하지 않는 ID는 DELIVERY_REGION_NOT_SUPPORTED다. 공개 검색은 해당 배송 조건을 지원하지 않는 상품을 제외한다.

deliveryRequestType=START_ONLY면 전달 주소 필수·반환 주소 null/생략, 회수비 0이다. START_AND_RETURN이면 양쪽 주소 필수이며 서로 다른 주소 문자열도 저장한다(지리 판정 없음). 명시적 type 생략 시 반환 주소가 있으면 왕복, 없으면 편도로 해석한다. 배송 자체가 false면 type은 보내지 않는다. 지점 START_ONLY는 왕복을 거절한다. totalPrice에는 배송비가 이미 포함되므로 프론트에서 다시 더하지 않는다. 관리자 delivery.pickupLocation/returnLocation으로 실제 목적지를 제공하고 기존 마스킹 startAddress/returnAddress는 호환용으로 유지한다.

고객 GET `/api/v1/nadree/rental/completed`에 반납 외 취소·거절·만료가 포함된다. 기존 page/pageSize(최대 100)를 사용한다. GET `/api/v1/nadree/rental/reservations/{reservationId}`는 상태와 무관하게 본인 예약을 직접 조회한다. 관리자 POST `/nadreego/booking/select`에 bookedNo 정확 일치 필터를 추가했다. 예약 ID와 bookingId는 동일하며 bookedNo=BO+예약 ID다. 관리자 JWT를 고객 조회에 사용하지 않는다.

### 예약 중복 검증 — 별도 테이블 없음

사용자 결정으로 요청 결과 테이블·Idempotency-Key 저장·30일 결과 재현 및 GET `/api/v1/nadree/rental/requests/{requestId}`는 제외한다. 기존 MSP_RESERVATION에서 동일 고객·지점·모델·기간의 60초 이내 REQUESTED/APPROVED 예약을 확인하여 409 DUPLICATE_RENTAL_REQUEST를 반환한다. 고객 및 모델 잠금과 재고 검증은 유지한다.

이는 장기 멱등성 보장이 아니다. 응답 유실 시 무조건 재전송하지 말고 본인 진행/종료 예약 목록을 조회하여 확인한다. reservationId를 알면 예약 직접 조회를 사용한다. 60초 이후에는 같은 요청도 새 예약이 될 수 있으므로 프론트에서 재전송을 제한해야 한다. 다중 서버 MySQL 동시성은 서버에서 별도 검증한다.

### PayPal 판매자 연결 — 별도 테이블 없음

#### 2026-10-19 앱 복귀 역할 분담 — 프론트 전달

- 대상은 관리자 앱이다. PASS처럼 PayPal 로그인·판매자 연결 동의 후 기존 앱 화면으로 돌아오는 UX를 프론트에서 구현한다. 백엔드는 별도 홈페이지나 임의 복귀 URL을 만들지 않으며 이번 작업에서 실제 env 값을 추가·변경하지 않는다.
- 앱 복귀 링크와 연결 화면 종료 처리는 프론트 담당이다. 현재 지원하는 HTTPS App Link/Universal Link 등 복귀 방식을 정하고, 사용할 HTTPS URL을 서버 담당자에게 전달한다. 커스텀 스킴을 선택하면 현재 HTTPS 제한과 호환되는지 사전 협의가 필요하다.
- PayPal 완료/앱 복귀만으로 저장 성공으로 판단하지 않는다. 프론트가 state와 기존 관리자 인증으로 verify를 호출하고, 서버의 판매자 검증·DB 저장 성공 응답을 받은 뒤 연결 화면을 종료하고 기존 화면에 완료 상태를 표시한다. 실패·취소는 완료로 표시하지 않는다. 예약 승인은 별도 재요청이다.
- 백엔드는 현재 start/verify 계약을 유지한다. `NADREE_PAYPAL_ONBOARDING_RETURN_URL`을 제거하는 결정이 아니라 프론트 확정 전 설정을 보류하는 결정이다. URL을 전달받으면 실제 연동 전에 서버 설정에 반영해야 한다. 미설정 상태의 start는 `503 PAYPAL_ONBOARDING_RETURN_URL_REQUIRED`이며, URL 없이 자동 복귀되는 것으로 안내하지 않는다.
- 인수 확인: 실제 Android/iOS에서 복귀, state 전달, 같은 관리자 로그인 세션 유지, verify 성공 후 화면 종료, 실패·사용자 취소 처리를 확인한다. 현재 프론트 구현·기기 검증은 완료로 간주하지 않는다.

사용자 결정으로 온보딩 테이블·상태 복구 CLI·전용 타이머는 제외한다. 기존 MSP_SPOT_RENT.paypal_merchant_id에 검증된 판매자를 저장하며 같은 ID를 여러 지점에 허용한다. Sandbox/Live 혼동 방지용 paypal_environment와 원거래 환불 대상을 보존하는 MSP_RENTAL_PAYMENT.paypal_merchant_id는 기존 설계대로 유지한다. 추가 세션 컬럼은 없다.

프론트 흐름:

1. 예약 APPROVE 시 ID가 없으면 409 SHOP_PAYPAL_MERCHANT_REQUIRED. 예약 상태는 REQUESTED로 유지하고 거절은 가능하다. 프론트는 ‘PayPal 판매자 연결이 필요합니다’와 연결 버튼을 표시한다. 일반관리자는 직접 지점 대표에게 연결을 요청한다.
2. 직접 지점 대표가 POST `/nadreego/shop/paypal-onboarding/start`, `{ "spotMasterId":"..." }`를 호출한다. 응답의 actionUrl을 연다. URL 발급을 승인 오류 처리 안에서 자동 실행하거나 백엔드가 UI를 띄우지는 않는다.
3. start 응답은 state/actionUrl/expiresAt/paymentEnvironment다. state는 서버가 서명한 30분 유효값이며 관리자 로그인 세션·지점·환경·PayPal tracking ID에 연결된다. DB에 저장하지 않는다. 반복 start는 새 연결 URL을 발급한다. 이미 ID가 있으면 SHOP_PAYPAL_ALREADY_CONNECTED다.
4. PayPal 로그인·동의 후 프론트가 정하여 env에 반영한 HTTPS 앱 복귀 주소로 이동한다. 별도 홈페이지 화면을 보여줄 필요는 없다. 프론트는 복귀 query의 state와 관리자 인증으로 POST `/nadreego/shop/paypal-onboarding/verify`, `{ "spotMasterId":"...", "state":"..." }`를 호출한다. 서버는 서명·만료·현재 대표 권한을 확인하고 PayPal tracking 조회로 판매자 ID 및 수취/이메일/플랫폼 권한을 검증한 뒤 지점 컬럼에 저장한다. 브라우저 merchantId/merchantIdInPayPal 값을 직접 저장하지 않는다.
5. verify 성공 응답은 spotMasterId/merchantId/paymentEnvironment다. 프론트에서 기존 승인 요청을 다시 실행한다. 연결 완료만으로 예약을 자동 승인하지 않는다.

저장값 조회는 기존 GET `/nadreego/shop/paypal-merchant?spotMasterId=...`, 연결 해제는 PUT 같은 경로에 `{ "spotMasterId":"...", "merchantId":null }`이다. 임의 판매자 ID 입력은 거절한다. 새 /status·/refresh API는 제외한다. Sandbox ID가 남은 채 Live로 전환하면 환경 불일치로 승인/결제를 차단하며 대표가 기존 연결을 해제하고 Live로 다시 연결해야 한다.

state 만료는 410 PAYPAL_ONBOARDING_STATE_EXPIRED, 변조/다른 지점·환경·로그인 세션은 400 PAYPAL_ONBOARDING_STATE_INVALID다. 대표가 재로그인했거나 state를 잃으면 start부터 다시 진행한다. 동일 판매자 verify 재전송은 허용하지만 다른 저장 판매자를 덮어쓰지는 않는다. 별도 저장 상태가 없으므로 미완료 연결 자동 복구·state 개별 취소는 제공하지 않는다. 연결 해제 후에도 유효 state를 가진 같은 대표 세션의 명시적 verify는 재연결할 수 있으므로 프론트는 해제 시 state를 폐기하고 자동 재전송하지 않는다. 복귀 페이지는 state를 로그·분석도구에 보내지 않고 처리 후 URL에서 제거한다.

승인·실제 결제 전 PayPal 판매자 권한 검증은 안전상 유지한다. 연결값이 있어도 권한 미완료/철회는 PAYPAL_MERCHANT_NOT_READY, 외부 장애는 오류로 차단된다. 서명 검증된 판매자 웹훅은 현재 PayPal 상태를 재확인하여 권한이 실제로 없어진 동일 환경의 연결 지점 ID/환경을 비운다. 늦은 철회 이벤트라도 현재 권한이 유효하면 유지하며 미연결 지점을 자동 연결하지 않는다. 기존 결제 당시 판매자 ID와 결제·환불 웹훅/복구 작업은 보존한다.

공식 기준: [PayPal 플랫폼 온보딩](https://developer.paypal.com/platforms/checkout/save-payment-methods/onboarding/platform/). 실제 Sandbox 파트너 권한·복귀 페이지·웹훅·결제 검증은 별도다.

### 탈퇴·환불·채팅 — 기존 처리 검증

사용자 결정으로 개인정보 작업 테이블·백그라운드 정리·자동 재시도 타이머 및 cleanupStatus/privacyStatus 응답 추가는 제외한다. 기존 탈퇴 API는 진행 중 거래와 무관하게 Firebase 계정 삭제·채팅 세션 회수를 호출한 후 SQL 프로필/FCM을 비우고 서비스 access/refresh를 폐기한다. 성공 응답은 `{ "status":"success", "deleted":true }`다. 기존 인증 시각을 가진 토큰으로 재가입할 수 없다.

외부 서비스 실패 시 성공으로 표시하지 않고 오류를 반환한다. SQL과 Firebase는 하나의 원자적 트랜잭션이 아니므로 외부 삭제 이후 SQL 실패 등 부분 성공은 운영 확인이 필요하며 자동 복구를 보장하지 않는다. 거래 참조·주소 스냅샷·기존 채팅 본문의 후속 삭제는 이번에 추가하지 않는다. 이름 null만으로 탈퇴를 추정하지 않는다. 기존 여권 기능·정리는 보류한다.

검증 범위는 프로필/FCM 삭제, access/refresh 차단, Firebase 삭제·채팅 회수 호출, 외부 실패 시 성공 오표시 방지 및 기존 거래 보존이다. 실제 Firebase 계정/채팅 연동 검증은 별도다.

관리자 결제 조회의 refundRequestedAmount(목표액), refundedAmount(실제 누적액), refundStatus 구분과 가능한 경우 결제 오류의 paymentId 제공은 유지한다. 채팅 경로·일반관리자 읽기/대표 답변 정책도 유지하며 프론트는 로그아웃/탈퇴 때 로컬 캐시를 비운다.

### 서버 적용 순서 — 아래 명령은 아직 실행하지 않음

1. 사용자 변경을 보존하여 코드 배포. DB 백업과 대상 DB 이름을 먼저 확인한다.
2. ec2-user가 읽을 수 있는 `/srv/nadree-api/.env`의 기존 Platform Client ID/Secret/Webhook/Partner Merchant ID를 확인한다. 복귀 URL은 지금 임의로 추가하지 않는다. 프론트에서 HTTPS 앱 복귀 주소를 전달받은 뒤 실제 연결 테스트 전에 `NADREE_PAYPAL_ONBOARDING_RETURN_URL`에 설정한다. URL에는 query/fragment를 넣지 않는다. 미설정 동안 온보딩 start는 사용할 수 없다. `NADREE_CORS_ORIGINS`에는 필요한 기존 origin을 유지하면서 `https://www.riderlog-lte.com:50045`를 쉼표로 구분해 포함한다.
3. 마이그레이션 계획을 확인한다. 이번 요청 결과·개인정보·온보딩 관련 신규 테이블은 모두 제외했다. 판매자 연결은 기존 지점/결제 컬럼만 사용한다. 이전 미적용 판매자 컬럼 등도 계획에 포함될 수 있다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
```

출력과 DB 백업 확인 후 **실제 env의 DB 이름과 일치할 때만** 아래 테스트 DB 적용 명령을 실행한다. Live DB에는 이 명령을 그대로 사용하지 않는다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST'
sudo systemctl restart nadree-api.service
```

4. PayPal 앱에 판매자 완료·동의 철회 이벤트 구독을 추가하고 기존 결제 이벤트 구독을 유지한다. Sandbox 온보딩→승인→주문→구매자 승인→캡처→고객/관리자 환불→서명 웹훅을 검증한다.
5. 이번 온보딩/개인정보 전용 타이머는 설치하지 않는다. 기존 결제·환불 복구 타이머는 그대로 유지한다. 이전 문서대로 이미 새 타이머를 설치했다면 실제 설치 여부를 확인하여 해당 전용 타이머만 중지하고 운영자에게 변경 이력을 전달한다.
6. 별도 테이블을 이미 다른 서버에 생성했다면 자동 DROP하지 않는다. 기존 데이터 유무와 적용 이력을 확인한다. 이번 코드는 해당 테이블에 의존하지 않는다.

### App Check 디버그 검증 준비

scripts/verify_app_check.py는 등록된 디버그 비밀값을 실제 App Check 토큰으로 교환하고 읽기 전용 getChatUnreadSummary에 정상·누락·위조 토큰을 보내 200/401/401을 확인한다. 검증을 끄는 방식이 아니다. [공식 교환 API](https://firebase.google.com/docs/reference/appcheck/rest/v1/projects.apps/exchangeDebugToken)를 사용한다.

서버의 저장소 밖 0600 비공개 JSON에 projectNumber, appId, apiKey, debugToken, firebaseIdToken, data를 보관한다. firebaseIdToken은 **현재 채팅 세션의 custom token을 Firebase ID token으로 교환한 값**이며 일반 Nadree JWT나 FCM 토큰이 아니다. 고객 data는 `{}`, 관리자 data는 `{ "shopId":"직접지점ID" }`다. 고객/관리자 앱별로 등록된 디버그 토큰을 사용한다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python scripts/verify_app_check.py /srv/nadree-api-private/app-check-customer.json'
```

실제 비밀 파일은 제공되지 않아 외부 검증은 아직 실행하지 않았다. 이 검사는 앱 기기 무결성·FCM 수신·모든 Firestore 쿼리의 인수를 대체하지 않는다. 결과 파일에는 비밀값/응답 원문 없이 HTTP 코드와 통과 여부만 남기고 테스트 종료 후 디버그 토큰을 폐기한다.

### 인수 상태

온보딩 테이블까지 제외한 변경 후 전체 로컬 회귀는 **314 passed, 10 skipped**(별도 MySQL 6·Firestore 4), 기존 의존성 경고 2개다. 판매자 연결은 기존 컬럼만 사용하며 권한 검증·state 변조/만료/다른 세션·지점·환경 차단·연결 해제·웹훅 현재 권한 재확인·중복 판매자 허용을 확인했다. 실행 명령은 `env -u NADREE_TEST_MYSQL_URL -u FIRESTORE_EMULATOR_HOST PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests -q -p no:cacheprovider --tb=short`다. `git diff --check`도 통과했다.

실제 MySQL 잠금·PayPal Sandbox 온보딩/결제·Firebase 계정/채팅 회수·App Check 및 기기 푸시는 서버 인수에서 별도 확인해야 한다. 서버 DB 변경·배포는 실행하지 않았다.

---

2026-10-16 추가 변경: 지점별 PayPal 판매자 설정 API, 미설정 승인 차단, 결제 당시 판매자 보존 및 Platform 요청 분리를 구현했다. 기존 단일 판매자 env 정책을 대체하며 **서버 미적용**이다. [최신 Platform 변경 전달서](spot-paypal-platform-handoff-2026-10-16.md)를 먼저 확인한다.

2026-10-13 실제 서버 후속 기록: 테스트 DB의 미적용 컬럼 4개를 백업 후 적용하고 API를 재시작했다. QR 시드와 결제 타이머/외부 영향 작업은 보류했다. 아래 “서버 미적용”은 로컬 작업 당시 기록이며 최신 실측 상태는 [서버 적용·검증 결과](server-apply-verification-2026-10-13.md)를 따른다.

## 2026-10-13 추가 보완 — 배포 전 확인

이 절은 이번 로컬 변경분이다. 아래 9월 문서의 과거 정책보다 현재 확정 정책과 이 절이 우선한다. 서버 DB·실제 PayPal·Firebase에는 이번 변경을 적용하지 않았다.

### 차량 QR 조회 — 센서 코드와 분리하는 최종 정정

QR은 차량 식별용이고 센서는 선택 장치다. 차량은 QR만 있는 차량과 QR+센서 차량 두 가지다. 이전 센서 코드 기반 QR 조회 안내는 잘못된 가정이므로 폐기하며 `/nadreego/sensor/qr/resolve`도 제거했다. 프론트는 QR 원문을 전달하고 서버는 기존 `NADREE_QR_HASH_KEY`로 HMAC-SHA256을 계산해 `MSP_VEHICLE_QR.qr_code_hash`를 조회한다. 원문을 해시 컬럼에 그대로 저장하거나 프론트에서 해시를 만들어 보내지 않는다. 센서 코드·ID로 대체 조회하지 않는다.

```http
POST /nadreego/vehicle/qr/validate
Authorization: Bearer <관리자 access token>
Content-Type: application/json

{"qrCode":"testQr123123"}
```

성공 예시:

```json
{"status":true,"errorCode":null,"data":{"vehicleId":"example-vehicle-id","qrId":"example-qr-id","qrStatus":"ACTIVE","equipmentType":"QR_ONLY","sensorId":null,"sensorStatus":"NOT_LINKED","vehicle":{"vehicleId":"example-vehicle-id","vehicleNo":"DK-TEST-301","vehicleStatus":"AVAILABLE"},"availableActions":["PRICE_CHANGE","SPOT_CHANGE","REPAIR","QR_DELETE"]}}
```

위 성공 예시는 주요 필드만 표시했다. 센서가 있으면 `equipmentType=QR_WITH_SENSOR`, `sensorStatus=LINKED`, `sensorId`에 연결 센서 ID가 반환된다. 차량 정보에는 모델·번호·상태 등이 포함되며 QR 원문/해시·센서 코드는 노출하지 않는다. 기존 status/errorCode/data와 vehicleId/qrId/qrStatus를 유지하고 필드를 추가했다. 센서 존재 여부로 QR 조회를 거절하지 않는다.

차량 생성은 기존 `POST /nadreego/vehicle/create`에 QR 원문 `qrToken`을 필수로 보낸다. 센서가 없으면 sensorId 생략/null, 있으면 별도로 확보한 센서 ID를 전달한다. 서버는 QR 해시와 차량을 연결하고 센서 지정 시 소속·이미 연결됨·대여 중 여부를 다시 검증한다. 센서를 분리해도 QR 연결은 유지된다. 조회 후 가격·정비·지점·QR/센서 분리 등의 변경은 기존 API를 사용하며 각 API에서 권한과 최신 상태를 검증한다. availableActions는 화면 표시용이고 변경 권한을 부여하는 토큰이 아니다.

미등록/다른 지점 QR은 `404 QR_NOT_FOUND`, 비활성은 `409 QR_INACTIVE`, 만료는 `410 QR_EXPIRED`다. 한 차량에 활성 센서가 여러 개면 `409 SENSOR_STATE_INCONSISTENT`로 잘못된 연결을 숨기지 않는다. 원문 길이 제한은 기존 API와 동일하게 최대 4096자다. URL/JSON 파싱은 하지 않는다.

새 매핑 테이블·DB 컬럼·env·Firebase 변경은 없다. 테스트하려면 동일 서버 키로 생성된 차량 QR 해시와 차량 지점 이력이 필요하다. 기존 차량 생성 API를 통해 테스트 차량을 등록하면 해시가 저장된다. 이번 작업에서 서버 데이터나 기존 QR 해시·키는 변경하지 않았다. 기존 결제/위치 변경분에 필요한 컬럼 4개 적용은 여전히 별도다.

정정 후 전체 로컬 회귀: **266 passed, 10 skipped**(별도 MySQL 6개·Firestore 4개), 기존 의존성 경고 2개. QR 단독/센서 연결 차량 생성·조회·가격 변경, 센서 분리 후 QR 유지, 센서 코드 조회 거절, 다른 지점 접근·중복 QR·비활성/만료 QR 차단을 검증했다. 아래 252개 결과는 QR 보완 전 기록이다. 서버 적용과 실제 MySQL 동시성 검증은 아직 수행하지 않았다.

### 앱·웹 공통 결제 변경

- 주문/캡처 API 경로·요청 필드는 유지한다. 최신 결제 행만 보는 대신 해당 예약·설정된 SANDBOX/LIVE 환경의 모든 결제를 확인한다. 진행 중 주문은 재사용하며 이전 완료 결제·결과 불명 캡처가 있으면 새 청구를 차단한다.
- PG 호출 전 DB에 요청 의도를 저장한다. 주문/캡처 응답 유실은 FAILED로 단정하지 않고 동일 식별자로 복구한다. 최초 요청 후 5시간이 지난 결과 불명 주문/캡처는 자동 POST 재전송하지 않는다. PG 멱등 보존 기간에 안전 여유를 둔 처리다. [PayPal Orders 설명](https://developer.paypal.com/api/rest/integration/orders-api/api-use-cases/advanced/).
- `PAYMENT_ALREADY_PAID`: 기존 결제를 조회한다. `PAYMENT_IN_PROGRESS`: 새 주문을 만들지 말고 기존 결제 상태를 조회한다. `PAYMENT_RECONCILIATION_REQUIRED`: 운영 확인 후 복구한다. `PAYMENT_SCHEMA_UPDATE_REQUIRED`: 서버 마이그레이션을 먼저 확인한다.
- 늦은 실제 청구와 중복 추가 청구는 각각 `refund_reason=LATE_CAPTURE/DUPLICATE_CAPTURE`, `refund_percentage=100`으로 남긴다. 기존 취소 요청자 필드는 보존하며 시스템 처리를 고객/관리자 요청으로 꾸미지 않는다. 유효 원결제는 유지한다. 웹훅 순서가 뒤바뀌면 선행 시도를 확인하기 전 환불 판정을 보류한다.
- PG capture의 create_time을 마감/취소 이력과 비교한다. 단순 웹훅 지연·중복은 늦은 신규 청구로 보지 않는다. 기존 취소 정책은 관리자 시작일 전 100%·당일 취소 불가, 고객 시작일 전 90%·당일 인계 전 취소 0%다.
- `python -m app.jobs payments`가 PG 조회 복구 → 환불 재시도 → 미결제 확인 후 만료를 실행한다. PG 장애/불명 상태는 차량을 임의 해제하지 않는다. 직접 조회 기록은 웹훅 서명 검증 결과와 혼동하지 않도록 `verification_status=API_QUERY`로 구분한다.
- 환불은 동일 요청의 금액·식별자를 고정한다. PENDING은 기존 refund ID를 조회하며 새 환불을 추가하지 않는다. 실패는 조회로 확정한 뒤 새 시도를 만든다. 최대 5회 자동 호출 이후 운영 확인 표시/알림을 남긴다. 요청 결과가 불명인 경우 새 키로 재시도하지 않는다. 환불 재전송은 보존 기간보다 짧은 44일까지 제한한다. [PayPal 멱등 요청](https://developer.paypal.com/api/make-api-requests/), [환불 API](https://developer.paypal.com/api/payments/v2/captures-refund).
- 이 방식은 불필요한 중복 청구를 줄이는 것이며 PG 수수료가 절대 발생하지 않음을 보장하지 않는다.

### 관리자 권한·위치 정정

- 퇴사는 `POST /nadreego/shop/adminDelete`로 렌탈 직원 권한을 제거하는 경우다. 장기 미로그인을 자동 퇴사로 판단하지 않는다. 대표는 먼저 `POST /nadreego/admin/roleChange`로 일반관리자에게 대표권한을 양도한다.
- 두 경로는 기존 채팅 세션을 먼저 회수한다. 회수 실패 시 역할 DB 변경은 롤백한다. 일부 Firebase 회수 후 DB가 롤백되면 사용자는 다시 채팅 세션을 발급받아 현재 DB 권한으로 복구한다. 퇴사자는 재발급 불가, 양도한 대표는 일반관리자 읽기 권한, 새 대표는 답변 권한이다. 직접 MySQL 수정 감시용 별도 서비스는 추가하지 않았다.
- 추가 POST `/nadreego/booking/location-correction`: 대표만 자기/하위 지점의 인계 전 REQUESTED/APPROVED 예약을 수정한다. `bookedNo`, 선택 `spotMasterId`, `changeType=CORRECTION`, `target=PICKUP|RETURN`, `previousLocation`, `correctedLocation`, `reason`을 사용한다.
- 위치 형식은 `{address, zipCode, latitude, longitude}`. 이전 위치가 없으면 `previousLocation=null`이다. 화면의 이전 값이 서버와 다르면 `409 LOCATION_SNAPSHOT_CHANGED`로 거절하므로 최신 예약을 조회한다. 인계 후/종료 예약의 기록은 이 API로 바꾸지 않는다.
- 추가 GET `/nadreego/booking/{booked_no}/location-corrections?spotMasterId=...`: 대표 권한으로 정정 전후 값·작업자·사유·시각을 조회한다. `CORRECTION`은 같은 장소의 주소/핀 보정에만 사용한다. 서버가 실제 장소 동일 여부를 자동 증명하는 기능은 아니다.
- 실제 매장 이전은 기존 `/nadreego/shop/update`를 사용하며 기존 예약에 전파하지 않는다. 위치 정정도 배송 목적지·요금·확정 견적을 변경하지 않는다. Swagger 설명과 테스트용 요청 예시를 반영했다.

### 서버에서 실행할 순서

먼저 현재 서버의 `NADREE_DATABASE_URL`이 의도한 테스트 DB인지, PayPal 환경이 SANDBOX인지 비밀값을 출력하지 않고 확인한다. 별도 스케줄러가 이미 payments/all을 실행한다면 새 타이머를 중복 설치하지 않는다.

1. 코드 pull 후 마이그레이션 계획 조회:

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
```

2. 백업·승인 후 적용. `DATABASE_NAME`은 확인한 실제 대상 DB 이름으로 바꾼다. 이 명령은 DB를 변경한다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate --apply --confirm-database DATABASE_NAME'
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
sudo systemctl restart nadree-api.service
```

3. 승인된 테스트 결제만 있는 환경에서 복구 작업 1회 실행. 이 명령은 실제 PG 환불/DB 상태 변경을 할 수 있다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.jobs payments'
```

4. 기존 결제 스케줄러가 없는 경우에만, 검증 후 타이머 설치:

```sh
sudo install -m 644 /srv/nadree-api/deployment/nadree-payments.service /etc/systemd/system/nadree-payments.service
sudo install -m 644 /srv/nadree-api/deployment/nadree-payments.timer /etc/systemd/system/nadree-payments.timer
sudo systemctl daemon-reload
sudo systemctl enable --now nadree-payments.timer
sudo systemctl status nadree-payments.timer --no-pager
sudo journalctl -u nadree-payments.service -n 60 --no-pager
```

신규 env 값·Firebase Functions/Rules 변경은 이번 보완에 없다. 기존 PayPal/채팅 설정과 권한이 정상이어야 한다.

### 운영 환불 재처리

`PAYMENT_ID`를 해당 테스트/운영 결제의 숫자 ID로 바꾼다. 아래 첫 명령은 DB 읽기만 수행한다. 두 번째는 명시적인 운영 승인 후에만 실행하며 외부 환불이 발생할 수 있다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.refund_recovery PAYMENT_ID'
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.refund_recovery PAYMENT_ID --apply'
```

`--apply`도 임의 금액·기한이 지난 불명 요청의 새 키 생성을 허용하지 않는다. 과거 FAILED/PENDING 환불에 기록이 없거나 요청 식별자 보존 기간이 지났으면 자동 복구 대상이 아니다. PayPal 거래/환불 내역을 먼저 대조하고 수동 처리 범위를 확정한다. DB의 FAILED 표시만 보고 새 환불을 만들지 않는다.

### 서버 검증과 남은 확인

- 이번 변경의 로컬 회귀 결과: **252 passed, 10 skipped**. 건너뛴 항목은 별도 MySQL 6개·Firestore 4개이며 기존 의존성 deprecation 경고 2개가 있다. `git diff --check`도 통과했다. 실제 MySQL 행 잠금 동시성, PayPal Sandbox 승인·캡처·응답 유실·웹훅 역순·환불 실패 복구, Firebase 권한 회수 종단은 서버에서 별도 검증한다.
- 차량 QR 해시 기반 조회로 정정했다. 실제 서버의 등록 QR·차량 지점 이력과 MySQL 동시 연결 방지 검증은 별도이며 예시 데이터가 자동 배포되지는 않는다.
- 차량 이동의 기본 성공·타 지점 차단·예약/활성 렌트 차량 이동 차단을 격리 테스트한다. 실제 센서 동반 이동·동시 재배정 및 실제 DB 계층 제약은 별도 인수 항목이다.
- 앱 화면·App Check·실기기 푸시는 별도 범위다. 위의 배포 명령을 아직 실행하지 않았으며 전체 출시 완료로 판정하지 않는다.

작성 기준: 2026-09-29

이 문서는 Nadree 관광객 앱, NadreeGo 관리자 앱, 공통 백엔드, 기존 RiderLog 연동 범위를 한 문서로 정리한 인수용 문서입니다. 관광객 앱 전용 상세 문서는 `docs/nadree-frontend-handoff.md`에 별도로 유지합니다.

## 1. 시스템 범위

- 관광객 앱 API: `/api/v1/nadree`
- 관리자 앱 API: `/nadreego`
- PayPal 웹훅: `/nadreego/paypal/webhook`
- 상태 확인: `/health/live`, `/health/ready`
- 운영 도메인: `https://na-dree.com`
- Swagger: `https://na-dree.com/docs`
- 기존 RiderLog API와 DB를 공유하지만, 이번 변경은 Nadree 기능을 추가하는 방식입니다.

## 2. 관광객 앱 API

관광객 앱의 기준 명세는 `docs/nadri-user-api-design.md`이며 현재 구현된 주요 메서드는 다음과 같습니다.

| 기능 | 메서드 | 경로 |
|---|---|---|
| Firebase UID 로그인/회원 생성 | POST | `/api/v1/nadree/user/login` |
| 사용자 정보 수정 | PATCH | `/api/v1/nadree/user/profile` |
| 로그아웃 | POST | `/api/v1/nadree/user/logout` |
| 토큰 갱신 | POST | `/api/v1/nadree/user/refresh` |
| 차량·지점·가격 조회 | POST | `/api/v1/nadree/rental/availability` |
| 예약 요청 | POST | `/api/v1/nadree/rental/request` |
| 예약 요청 취소 | POST | `/api/v1/nadree/rental/request/cancel` |
| 진행 중 렌트·예약 목록 | GET | `/api/v1/nadree/rental/ongoing` |
| 완료 렌트 목록 | GET | `/api/v1/nadree/rental/completed` |
| PayPal 결제 주문 생성 | POST | `/api/v1/nadree/rental/payment/order` |
| PayPal 결제 캡처 | POST | `/api/v1/nadree/rental/payment/capture` |
| PayPal 결제 상태 조회 | GET | `/api/v1/nadree/rental/payment/{paymentId}` |

예약·결제와 관련된 응답은 프론트가 임의로 상태를 만들지 말고 응답의 `status`, `paymentStatus`, `refundStatus`를 기준으로 화면을 전환해야 합니다.

진행 중·완료 목록의 각 항목도 차량 조회와 같은 가격 구조를 사용합니다. `price`에는 `currency`, `rentalDays`, `dailyFrom`, `dailyTo`, `rentalFrom`, `rentalTo`, `pricingTiers`, `deliveryStart`, `deliveryReturn`, `deliveryTotal`, `totalOptions`, `totalFrom`, `totalTo`, `requestedTotal`, `calculatedTotalFrom`, `calculatedTotalTo`, `finalTotal`을 포함합니다. `delivery`에는 `deliveryRegionId`, 픽업·반납 주소, 시작·반납·합계 배송비를 포함합니다. 값이 존재하지 않는 현장 렌트 항목은 해당 필드를 `null` 또는 빈 배열로 반환합니다.

## 3. 인증과 토큰

### 관광객

1. 앱은 Firebase Authentication으로 로그인하고 Firebase ID Token을 받습니다.
2. Nadree 로그인 요청 body에는 `UID`를 보내고, Firebase ID Token은 `Authorization: Bearer <firebase-id-token>` 헤더로 보냅니다.
3. 서버는 Firebase Admin SDK로 ID Token을 검증하고 토큰의 `uid`가 요청의 `UID`와 같은지 확인합니다.
4. 검증 성공 시 Nadree 전용 access token과 user refresh token을 발급합니다.
5. 신규 UID면 `MSP_RENTAL_USER`를 만들고, 기존 UID면 정보를 반환합니다.

Firebase ID Token이 없거나 만료됐으면 `CUSTOMER_FIREBASE_AUTH_NOT_CONFIGURED`, `FIREBASE_ID_TOKEN_REQUIRED`, `FIREBASE_ID_TOKEN_INVALID`, `FIREBASE_UID_MISMATCH` 계열 오류를 처리해야 합니다. 운영 환경에서 Firebase 인증 설정이 빠지면 관광객 로그인은 차단됩니다.

### 관리자

- 관리자 인증은 기존 NadreeGo access/refresh token 흐름을 사용합니다.
- 관리자 역할은 `rental_primary_admin`, `rental_manager`입니다.
- 관리자 refresh token은 `MSP_REFRESH_TOKEN`에서 관리하며 관리자 계정과 기기별 세션 제한 정책을 적용합니다.
- 관광객 토큰과 관리자 토큰은 검증 대상과 권한이 다르므로 서로 교차 사용하면 안 됩니다.

## 4. 식별자와 데이터 매핑

- `UID`: Firebase UID이자 `MSP_RENTAL_USER.uid_token`의 외부 식별자입니다.
- `shopId`: `MSP_SPOT_MASTER.spot_master_id`입니다.
- `bookingId`: `MSP_RESERVATION.reservation_id`입니다.
- `bookedNo`: 화면 표시용 예약 번호이며 관계 키로 사용하지 않습니다.
- `spotCode`, `unitCode`: 지점 검색·표시용 코드입니다.
- `spot_master`: 최상위 계약부터 하위 지점까지의 연결 관계를 표현합니다.
- 이번 Nadree API의 지점 관계는 `spot_master_id`를 기준으로 조회하며 별도 `spot_id`를 필수 관계 키로 사용하지 않습니다.
- `MSP_DRIVER`와 기존 RiderLog의 드라이버 흐름은 이번 변경 범위가 아닙니다.

## 5. 관광객 예약 흐름

1. 로그인 후 차량 조회 API에 대여 시작일, 반납일, 배기량/모델 조건, 배송 여부와 픽업·반납 위치를 전달합니다.
2. 서버는 지점·차량 모델 단위로 재고와 예약·렌트 기간을 확인하고 가격, 티어, 배송비, 샵 정보를 반환합니다.
3. 예약 요청 시 조회에 사용한 조건 JSON을 예약에 스냅샷으로 저장합니다.
4. 같은 모델·지점·기간에 동시에 요청이 들어오면 DB 잠금과 가용성 확인을 다시 수행하고 먼저 확정된 요청만 허용합니다.
5. 예약은 `REQUESTED`로 생성되며 관리자 승인 전에는 결제 주문을 만들 수 없습니다.
6. 관리자 승인 시 `APPROVED`가 되고 승인 시각 기준 결제 기한을 계산합니다.
7. 승인 후 PayPal 주문을 생성하고 결제를 완료합니다.
8. 결제 완료 웹훅 확인 후 관리자가 QR로 인계 처리합니다. 인계가 렌트 시작이며 관광객 앱에서 QR을 처리하지 않습니다.
9. 반납 처리 후 `RETURNED` 상태가 됩니다.

### 예약 및 결제 상태

- 예약: `REQUESTED`, `APPROVED`, `REJECTED`, `CANCELED`, `EXPIRED`
- 결제: `CREATED`, `PENDING`, `PAID`, `FAILED`, `CANCELED`
- 환불: `NONE`, `NOT_REQUIRED`, `REQUESTED`, `PENDING`, `COMPLETED`, `FAILED`

결제가 완료되기 전 `REQUESTED` 또는 `APPROVED` 예약은 관광객이 취소할 수 있습니다. 승인 후 결제하지 않으면 결제 기한 만료 시 예약이 자동 취소되어 렌트를 생성할 수 없습니다. 관리자가 승인한 뒤 결제하지 않은 예약을 렌트 생성 API가 통과시키면 안 됩니다. 결제 완료 후 취소는 관리자 취소와 PayPal 환불 흐름으로 처리합니다.

승인 후 결제 기한 안내는 남은 기간 2일, 1일에 각각 FCM으로 보내고, 기한이 지나면 만료 알림을 보냅니다.

## 6. PayPal 연동

- 표시 금액과 결제 금액은 MVP에서 USD 기준입니다.
- 결제 주문은 관리자 승인 이후에만 생성할 수 있습니다.
- 결제 전 예약 취소는 PayPal 결제 전에 처리됩니다.
- 결제 완료는 PayPal API 결과와 웹훅을 함께 확인합니다.
- 웹훅 URL: `https://na-dree.com/nadreego/paypal/webhook`
- 동일 웹훅 재전송은 이벤트 ID 저장, 서명 검증, 결제 상태 전이 검증으로 중복 반영을 막습니다.
- 결제 생성·캡처·환불 요청은 해당 결제와 예약의 소유자 및 상태를 다시 확인합니다.
- 샌드박스 테스트에서는 PayPal Sandbox Client ID/Secret, Webhook ID, 판매자 계정을 서버 환경 변수에 넣습니다.

## 7. 관리자 앱 기능

### 계정과 지점

- 대표 관리자는 상위 계약/지점 생성 시 발급된 초대 코드를 관리합니다.
- 일반 관리자는 대표 관리자 이메일 또는 가입 코드를 입력해 해당 지점 가입 요청을 보냅니다.
- 대표 관리자가 가입 요청을 승인해야 일반 관리자 역할이 활성화됩니다.
- 지점 계층은 `MSP_CONTRACT` → `MSP_ORG` → `MSP_REGION` → `MSP_LOCAL` → `MSP_SPOT` 및 `MSP_SPOT_MASTER` 관계로 관리됩니다.

### 차량과 예약

- 차량 모델, 지점별 재고, 가격 티어, 배송 지역을 관리합니다.
- 관리자 예약 승인·거절 결과는 관광객에게 FCM으로 전달합니다.
- 관리자 앱에서 QR 인계와 반납 처리를 수행합니다. 관광객 앱에는 QR 처리 기능이 없습니다.
- 캘린더는 해당 지점이 보유한 모델/차량의 기간별 예약·렌트·정비 가능 여부를 조회합니다.
- 활성 렌탈 중에는 `PUT /nadreego/rent/passport`로 앱에서 식별정보를 마스킹한 JPEG/PNG를 업로드하고, `GET /nadreego/rent/passport/{bookedNo}`로 같은 지점의 활성 관리자만 조회합니다. 반납 후에는 API 접근을 차단합니다. 원본 이미지나 저장소 키를 응답하지 않습니다.

## 8. FCM 정책

FCM 토큰은 앱이 전달한 값을 계정의 최신 토큰으로 저장합니다. 이번 정책은 계정당 기기 하나이며, 로그아웃 요청에 현재 기기의 `X-FCM-Token`을 보내 저장된 값과 일치하면 토큰을 삭제합니다. 헤더를 보내지 않으면 토큰을 유지합니다.

| 이벤트 | 수신자 |
|---|---|
| 예약 요청 | 해당 지점에 직접 연결된 활성 관리자 |
| 예약 승인 | 관광객 |
| 예약 거절 | 관광객 |
| 결제 기한 2일/1일 전 | 관광객 |
| 결제 기한 만료 | 관광객 |
| 결제 완료 | 관광객 및 해당 지점 관리자 전체 |

관리자 수신자는 대상 지점에 직접 연결된 활성 `rental_primary_admin`/`rental_manager`를 조회합니다. 같은 토큰이 여러 계정에 있으면 한 번만 발송합니다. FCM 발송 실패가 예약·결제 트랜잭션 자체를 실패시키지 않도록 비즈니스 처리와 알림 결과를 분리합니다.

FCM과 Firebase ID Token 검증은 같은 Firebase 프로젝트의 서비스 계정 설정을 사용합니다. 위치 정보 Firebase는 별도 프로젝트/환경 변수로 구분합니다.

## 9. DB와 마이그레이션

주요 Nadree 테이블은 다음과 같습니다.

- `MSP_RENTAL_USER`, `MSP_RENTAL_USER_REFRESH_TOKEN`
- `MSP_RESERVATION`, `MSP_RENTAL_CONTRACT`, `MSP_RENTAL_PAYMENT`
- `MSP_RENTAL_VEHICLE`, `MSP_RENTAL_TIER`, `MSP_MODEL_DAILY_INVENTORY`
- `MSP_SPOT_MASTER`, `MSP_SPOT_RENT`, `MSP_SPOT_DELIVERY_REGION`, `MSP_DELIVERY_REGION`
- PayPal 웹훅 이벤트 저장 테이블

테스트 DB용 렌탈 시나리오 데이터는 `migrations/test_seed_rental_scenarios.sql`에 있습니다. 기존 테스트 지점을 새로 만들지 않고 차량 모델·차량·가격·재고·관광객·예약 상태·렌트 계약·결제 상태·배송 지역만 `NRTEST_*` 식별자로 추가합니다. API 응답의 `shopId`와 `spotMasterId`는 기존 테스트 지점의 `spot_master_id`를 그대로 반환하고, 모델·예약·계약·결제 필드는 시드된 ID와 상태를 동적으로 반환합니다.

주요 시드 상태는 다음과 같습니다.

- `NRTEST-MODEL-125` / `NRTEST-MODEL-155`: 125cc·155cc 모델, USD 일일 요금 25·35
- `NRTEST-VEHICLE-301`: 대여 가능, `302`: 정비, `303`: 진행 중 렌트, `304`: 미래 승인 예약
- `NRTEST-RES-REQ-001`: 승인 대기, `APP-001`: 승인 후 결제 필요, `PENDING-001`: 결제 진행 중
- `NRTEST-RES-HAND-001`: 인계 완료, `RETURN-001`: 반납 완료·환불 완료
- 목록 응답의 `price`와 `delivery`는 위 예약의 저장된 견적·배송 스냅샷을 사용합니다.

알림 전용 테이블과 채팅 테이블은 추가하지 않습니다. FCM 토큰은 기존 사용자·관리자 저장 컬럼을 사용합니다.

운영 DB 적용 전 읽기 전용 계획을 확인합니다.

~~~bash
cd /srv/nadree-api
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
~~~

계획이 맞을 때만 다음처럼 명시적으로 적용합니다.

~~~bash
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST'
~~~

현재 캘린더 최적화용 주요 인덱스는 `MSP_VEHICLE_SPOT_HISTORY.idx_vehicle_spot_current`, `MSP_RESERVATION.idx_reservation_calendar`, `MSP_RENTAL_CONTRACT.idx_rental_contract_calendar`입니다. 인덱스 추가는 RiderLog 기존 테이블 구조나 드라이버 데이터 흐름을 삭제·변경하지 않는 additive 변경입니다.

## 10. RiderLog 영향 범위

- `MSP_DRIVER`는 Nadree에서 새로 수정하거나 대체하지 않습니다.
- 기존 RiderLog API와 RiderLog의 `RiderLog` 기록 흐름은 그대로 유지합니다.
- 공유 DB의 `MSP_ROLE`에서 Nadree 역할을 임의로 삭제하지 않습니다.
- Nadree 예약·결제·사용자 테이블을 추가해도 기존 드라이버, 운행, 사고, 배치 기능의 관계 키를 변경하지 않습니다.
- 배포 전 기존 RiderLog 회귀 테스트와 Nadree 테스트를 함께 실행해야 합니다.

## 11. 프론트엔드 구현 체크리스트

### 관광객 앱

- Firebase 로그인 성공 후 ID Token을 Nadree 로그인 API에 전달합니다.
- `shopId`는 `spotMasterId`, `bookingId`는 `reservationId`로 저장합니다.
- 예약 요청 후에는 관리자 승인 전 결제 버튼을 노출하지 않습니다.
- PayPal 주문 생성 응답의 승인 URL로 이동하고, 앱 복귀 후 결제 상태 API와 웹훅 반영 상태를 확인합니다.
- 결제 완료 전 `REQUESTED`·`APPROVED` 예약 취소를 허용하고, 결제 진행 중·완료 후에는 상태 API 또는 관리자 환불 절차를 안내합니다.
- 결제 완료·승인·거절·만료 FCM을 받으면 예약 목록을 다시 조회합니다.
- 로그아웃 요청에 일치하는 `X-FCM-Token`을 보내면 현재 FCM 토큰을 삭제하고, 헤더를 보내지 않으면 토큰을 유지합니다.
- 오류 응답의 `errorCode`를 기준으로 사용자 메시지를 표시하고 원문 DB 오류를 노출하지 않습니다.

### 관리자 앱

- 대표 관리자와 일반 관리자 역할에 따라 메뉴와 API 권한을 분리합니다.
- 가입 요청 승인 전 일반 관리자의 관리 API 접근을 허용하지 않습니다.
- 예약 승인 후 결제 기한을 표시합니다.
- 결제 완료 전 QR 인계 메뉴를 실행하지 않습니다.
- QR 인계는 관리자 앱에서만 수행하고 인계 완료를 렌트 시작으로 표시합니다.
- 대상 지점의 모든 관리자에게 예약·결제 FCM이 도착하는지 확인합니다.

## 12. 운영 환경 변수

`.env`는 `/srv/nadree-api/.env`에 두고 `ec2-user`가 읽을 수 있도록 소유자와 권한을 설정합니다.

~~~bash
sudo chown ec2-user:ec2-user /srv/nadree-api/.env
sudo chmod 600 /srv/nadree-api/.env
~~~

필수 그룹:

- `NADREE_ENV`, `NADREE_DATABASE_URL`, `NADREE_REDIS_URL`
- `NADREE_JWT_SECRET`, `NADREE_FIELD_ENCRYPT_KEY`
- `NADREE_FCM_*` 및 Firebase Admin 서비스 계정 값
- `NADREE_LOCATION_FIREBASE_*` 위치 Firebase 값
- `NADREE_PAYPAL_*` 및 Webhook 설정
- `NADREE_SMTP_*` 이메일 설정
- `NADREE_PASSPORT_STORAGE_ROOT` (현재 개발용 로컬 저장소 설정; 운영 S3 어댑터·보관/삭제 정책 별도)

서비스는 systemd의 `User=ec2-user`, `WorkingDirectory=/srv/nadree-api`로 실행해야 합니다. `.env`를 읽을 수 없는 `ssm-user`로 마이그레이션이나 수동 실행을 하면 `PermissionError`가 발생하므로 다음처럼 실행합니다.

~~~bash
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
~~~

## 13. 배포 및 점검

~~~bash
cd /srv/nadree-api
sudo systemctl stop nadree-api
git pull --ff-only origin main
sudo chown ec2-user:ec2-user .env
sudo chmod 600 .env
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/pip install -r requirements.lock'
sudo systemctl daemon-reload
sudo systemctl reset-failed nadree-api
sudo systemctl start nadree-api
sudo systemctl status nadree-api --no-pager -l
curl -sS https://na-dree.com/health/live
curl -sS https://na-dree.com/health/ready
~~~

`/health/ready`가 `status: ok`이면 DB, 필수 스키마, 역할 설정이 준비된 상태입니다. `MFA_FLOW_NOT_IMPLEMENTED`는 현재 남아 있는 제한사항이며 Nadree 예약·결제 흐름을 막는 오류가 아닙니다.

## 14. 테스트 현황과 남은 운영 확인

- 전체 자동 테스트: 160 passed, 6 skipped, 2 warnings 기준으로 통과했습니다.
- 스킵 항목은 외부 Firebase, PayPal, 실제 DB/Redis 같은 운영 의존성이 필요한 통합 테스트입니다.
- 실제 운영 전 Firebase ID Token 검증, FCM 발송, PayPal Sandbox 주문·캡처·웹훅·환불, Redis 연결을 각각 확인해야 합니다.
- PayPal 웹훅은 Sandbox 콘솔의 Webhook URL과 이벤트 구독이 실제 도메인으로 저장되어 있어야 합니다.
- 대상 그룹 health check와 `/health/ready`가 모두 정상인지 확인합니다.
- 예약 동시성, 승인 후 결제 기한 만료, 중복 웹훅, 결제 후 관리자 취소·환불을 시나리오로 테스트합니다.

## 15. 알려진 제한사항

- MFA 전체 흐름은 아직 구현되지 않아 readiness에 `MFA_FLOW_NOT_IMPLEMENTED`가 표시됩니다.
- FCM 토큰은 계정당 최신 1개 정책입니다. 한 계정의 여러 기기 동시 수신이 필요해지면 별도 기기 토큰 테이블과 토큰별 폐기 정책을 추가해야 합니다.
- MVP는 발리 기준 고정 시간과 USD 결제를 전제로 합니다. 여러 국가를 지원할 때는 지점 타임존, 영업시간, 환율 스냅샷을 별도로 도입해야 합니다.
- 채팅은 백엔드 범위가 아니며 프론트에서 처리합니다.
- 여권 업로드는 현재 파일시스템 어댑터와 클라이언트의 마스킹 확인 플래그를 사용합니다. 운영 S3/암호화 저장소, 시각적 마스킹 검증, 반납 후 실제 자동 삭제 배치의 승인은 아직 필요합니다.
