# 2026-10-19 서버 적용 상태·요구사항 검증 결과

## 2026-10-20 05:49 UTC 판매자 조회 인증 보완·재시작 완료(실제 결제 재시도 없음)

사용자의 “수정하고 재시도 말고 서버 재실행만” 승인에 따라 `app/paypal.py`의 플랫폼 판매자 상세·tracking 조회에서 `merchant_auth=False`를 명시했다. 공통 요청 메서드는 이때만 `PayPal-Auth-Assertion`을 추가하지 않는다. 플랫폼 Bearer 인증·Partner 설정·판매자 수취/이메일/OAuth 권한 검사는 유지했다. 결제 주문·캡처·환불은 기본값으로 기존 판매자 assertion을 유지하고 판매자 지정 클라이언트의 ID도 바꾸지 않는다. DB·env·기존 결제 ID/상태/요청 식별자는 변경하지 않았다.

`tests/test_merchant_accounts.py`에서 판매자 지정/기본 클라이언트의 권한 조회 및 동의 부족 차단 회귀를 확장했다. tracking 조회 후 같은 판매자 클라이언트의 모의 주문·캡처·환불에는 정확한 판매자 assertion이 남는 테스트도 추가했다. 수정 전 회귀에서 판매자 지정 조회의 불필요한 헤더를 재현했고, 수정 후 관련 `test_merchant_accounts.py`, `test_paypal_onboarding.py`, `test_payment_safety.py`, `test_refunds.py` **81 passed, 0 failed, 0 skipped(13.35초)**다. 임시 DB/MockTransport를 사용했으며 실제 PG/고객/푸시는 사용하지 않았다. 전체 회귀를 다시 실행한 결과는 아니다.

`nadree-api.service` 재시작 후 **PID 2709814, active/running**, 05:49:54 UTC 공개 `/health/live` **HTTP 200**을 확인했다. 수정은 작업 트리에 있고 별도 커밋하지 않았다. 기존 미커밋 변경은 보존했다. `git diff --check`도 통과했다.

요청대로 실제 `/payment/order`·OAuth·판매자 조회·온보딩 업무 요청은 재시도하지 않았다. 실제 주문 생성/성공 여부는 이번 변경으로 새로 검증한 것이 아니며 미검증이다. 실제 기존 결제 시도 5번은 삭제·초기화·수정하지 않았다. 이번에는 원인에 대한 코드 수정·격리 검증·서비스 재시작만 완료했다.

## 2026-10-20 05:46 UTC payment/order PAYPAL_SERVICE_UNAVAILABLE 원인 진단

사용자의 원인 확인 요청으로 실제 주문 POST는 재실행하지 않고 승인 테스트 지점·모델의 결제 시도와 PayPal 읽기 전용 API를 대조했다. 대상 DB는 RIDERLOG_V2_DATA_TEST, 결제 ID 5, 예약 `0b50df14-7e3f-4ece-b46b-8ebe783d8d9f`다. 결제는 SANDBOX/CREATED, order_requested_at 05:36:23 UTC, 주문 ID·캡처 ID·캡처 요청 시각이 없다. 이는 외부 요청 식별자를 먼저 커밋하는 현재 코드 경로와 일치한다. DB에 주문 ID가 없다는 사실만으로 PayPal 주문이 절대 생성되지 않았다고 단정하지 않는다.

현재 코드의 `nadree_payment_order`는 판매자 지정 클라이언트로 `verify_merchant`를 호출한다. 지정 클라이언트의 공통 `call`은 판매자 인증용 `PayPal-Auth-Assertion`을 모든 요청에 붙인다. 따라서 플랫폼이 자신의 연동 판매자를 조회하는 GET에도 판매자 assertion이 붙는다. 실제 같은 판매자의 조회를 비교했다.

| 검사 | HTTP | 오류 코드 | PayPal Debug ID |
| --- | --- | --- | --- |
| 판매자 지정 클라이언트 OAuth | 200 | 없음 | `ca4d5b96acaff` |
| 판매자 assertion이 있는 merchant-integrations GET | **401** | **AUTHORIZATION_ERROR** | `ca4d5b96c1da8` |
| 플랫폼 기본 클라이언트 OAuth | 200 | 없음 | `ca4d5b96dc916` |
| 판매자 assertion이 없는 동일 merchant-integrations GET | **200** | 없음 | `ca4d5b96efbf8` |

플랫폼 기본 조회는 `verify_merchant`의 payments_receivable·이메일 확인·OAuth 권한 검사까지 통과했다. 따라서 이번 재현에서 OAuth 키 오류나 판매자 미연결이 원인은 아니다. 판매자 지정 클라이언트의 플랫폼 권한 조회에 잘못된 인증 컨텍스트가 적용돼 주문 생성 전 401이 발생하며, 공통 `call`의 HTTPError 처리에서 HTTP 500 PAYPAL_SERVICE_UNAVAILABLE로 변환된다. 최초 사용자 실패 요청 자체의 upstream Debug ID는 보존되어 있지 않으며 위 ID는 원인 확인용 GET 재현의 값이다.

필요한 최소 보완은 merchant-integrations 등 플랫폼 권한 조회에서 판매자 assertion을 붙이지 않도록 하고, 실제 판매자 주문·캡처·환불 요청의 인증/판매자 검증은 유지하는 것이다. 판매자 지정 클라이언트에서도 해당 조회의 플랫폼 인증이 유지되는 회귀가 필요하다. 이번에는 원인 진단만 했으며 코드 변경·재시작·DB 변경·주문 생성·캡처·환불은 하지 않았다. 기존 결제 시도는 삭제/초기화하지 않았다. 재시도 시 기존 요청 식별자·리플레이 기한·PG 상태 확인 규칙을 유지해야 한다.

진단 기록: `build/test-runtime/payment-order-diagnostic-2026-10-20.json`. Secret·Authorization/Assertion 헤더 값·access token·판매자 ID 원문·개인정보는 출력하거나 기록하지 않았다.

## 2026-10-20 05:22 UTC RESERVATION_CHANGED 재현·수정·격리 검증

기준 HEAD `8818bb749535ca1378353c91ea13005a3dbd3125` 위 작업 트리에서 수정했다. 기존 PayPal 링크 검증 수정 및 관련 문서/테스트의 미커밋 변경은 보존했다. 실제 서비스는 재시작하지 않았고 실제 승인·예약/DB 데이터 변경도 하지 않았다. 이 절은 서버 실반영 완료 판정이 아니다.

### 실제 대상 읽기 전용 확인

DB가 `RIDERLOG_V2_DATA_TEST`임을 확인하고 승인된 지점 `00000000-0000-4000-8000-000000000101`, 모델 `NRTEST-WEB-MODEL-125`의 활성 예약만 조회했다. **4건 모두 REQUESTED/SOFT_HOLD, assigned_vehicle_id=NULL**이었다. 기간은 서로 다른 구간으로, 겹치는 기간이 아니어도 모델 전체의 대기 신청이 계산 대상에 포함되므로 같은 문제가 발생할 수 있다. 사용자 UID·개인정보는 조회하지 않았다. 최소 상태/기간 기록은 `build/test-runtime/reservation-changed-readonly-2026-10-20.json`에 보관했다.

### 원인 및 수정

`compute_assignment`가 다른 대기 신청의 용량을 보호하려고 가상 배정을 생성한다. `apply_assignments`는 그 결과를 순회하며 차량이 미지정인 신청에도 APPROVED 및 이동 가능 상태 전용 UPDATE를 실행한다. REQUESTED는 해당 WHERE에 맞지 않아 rowcount=0, RESERVATION_CHANGED가 된다. 이 상황은 실제 동시 변경 없이도 발생한다.

`app/availability.py`의 `apply_assignments`에서 **스냅샷 상태가 REQUESTED인 예약만 저장 대상에서 제외**했다. `compute_assignment`의 대기 신청 포함 조건·solver는 변경하지 않았다. 현재 승인 대상은 기존 `booking_action` 경로에서 따로 APPROVED/PROVISIONAL로 저장한다. 기존 APPROVED 예약의 재배정과 UPDATE rowcount 기반 상태 변경 검사는 그대로 유지했다. DB 스키마·API 요청/응답·PayPal 권한/판매자 검증 변경은 없다.

### 수정 전후 격리 증거

신규 `tests/test_pending_reservation_approval.py`는 실제 신청 API·재고 계산·solver·승인 API·이력 저장을 격리 DB에서 실행한다. 외부 PayPal 판매자 확인만 모의 처리하며 실제 PG/FCM으로 요청하지 않는다.

- **수정 전:** 동일 기간의 대기 신청 3건 중 하나를 승인하는 첫 사례에서 HTTP 409 `RESERVATION_CHANGED`를 재현했다(기대 200, 1 failed, 첫 실패에서 중단).
- **수정 후:** 신규 테스트 8개 포함 관련 테스트 39개 모두 통과, 실패/건너뜀 0, 15.84초. 실행 파일은 `test_pending_reservation_approval.py`, `test_nadri_flow.py`, `test_vehicle_transfer.py`, `test_cancellation_policy.py`, `test_location_correction.py`다.
- 신규 회귀는 같은 기간 신청 3건 및 다른 기간 신청 4건에서 승인 순서를 바꾸어 검사한다. 승인 대상은 APPROVED/PROVISIONAL, 다른 신청은 모든 DB 필드가 이전과 동일하며 잘못된 VEHICLE_REASSIGNED 이력이 생기지 않음을 확인했다.
- 차량 3대에 같은 기간 신청 3건이 점유한 뒤 한 건을 승인해도 네 번째 신청은 RENTAL_UNAVAILABLE로 차단된다. 따라서 대기 신청의 재고 점유는 유지된다.
- 기존 승인 예약이 다른 차량으로 실제 재배정되고 이력이 1건 생성되는 사례도 통과했다. 다른 대기 신청은 차량 미배정 상태로 유지됐다.
- 승인 스냅샷 이후 실제 저장 상태가 달라 UPDATE 조건을 충족하지 않으면 여전히 RESERVATION_CHANGED가 발생하는 검사를 통과했다.
- `git diff --check` 통과. 전체 회귀 재실행이나 실제 MySQL/운영 동시성 검사 결과로 확대하지 않는다. 기존 의존성 deprecation 경고 2건은 실패가 아니다.

기존 승인 대상 데이터 조회 외에 실제 예약 승인·생성·취소·차량 배정·푸시·결제·환불·서비스 재시작은 실행하지 않았다. 다음 실반영은 API 재시작과 별도 승인된 테스트 예약의 실제 승인/외부 영향 확인이 필요하다. 프론트 변경은 필요하지 않다.

**최신 확인 — 2026-10-20 01:02 UTC:** PayPal referral self 링크 호스트 검증을 수정하고 회귀 56개 통과 후 API 재시작 완료. 리턴 URL 반영·실제 온보딩 start HTTP 200과 state/actionUrl/expiresAt/paymentEnvironment 응답을 확인했다. 아래 00:57~00:58 UTC의 미반영·500 실패는 해소됐다. 판매자 동의·앱 복귀·verify 저장·결제 성공은 별도 미검증이다.

## 2026-10-20 00:57 UTC 추가 확인: 리턴 URL 파일 설정 완료·서비스 미반영

`.env`의 PayPal 온보딩 리턴 URL은 존재하고 현재 HTTPS·query/fragment 없음 등 서버 형식 조건을 충족한다. 실제 URL은 문서나 출력에 남기지 않았다. 그러나 실행 중 `nadree-api.service` PID 2539433의 환경에는 리턴 URL이 없으며 파일과 불일치한다.

승인된 테스트 대표 계정으로 실제 API를 확인했다. 로그인 HTTP 200, 테스트 지점 판매자 상태 조회 HTTP 200·미연결, 온보딩 `/start`는 **HTTP 503 `PAYPAL_ONBOARDING_RETURN_URL_REQUIRED`**, 로그아웃 HTTP 200이다. 따라서 파일 설정 완료를 실행 중 API 반영 완료로 판단할 수 없다.

다음 작업은 API 재시작 후 파일·프로세스 설정 일치와 실제 `/start`의 PayPal actionUrl/state 발급 여부를 재검증하는 것이다. 이번 요청은 확인이므로, 앞서 사용자가 서비스 재시작에 별도 승인을 요구한 제한에 따라 재시작은 수행하지 않았다. 판매자 연결·저장·결제·환불·푸시는 실행하지 않았다. 테스트 로그인·로그아웃은 기존 테스트 대표의 세션에 영향을 주는 동작이다. 프론트 복귀 화면·실기기·동일 세션 verify 성공은 아직 미검증이다.

기록: `build/test-runtime/paypal-return-url-2026-10-20.json`. 토큰·비밀번호·state·개인정보는 기록하지 않았다.

### 2026-10-20 00:58 UTC 승인된 재시작·온보딩 재검사

사용자 승인에 따라 API를 재시작했다. PID 2673544, active/running이며 시작 직후 헬스체크 502는 재확인에서 200으로 전환됐다. 리턴 URL은 현재 파일과 실행 프로세스에서 일치하고 설정됨을 확인했다. 실제 URL·인증값은 출력하지 않았다.

- 실제 테스트 대표 로그인 HTTP 200, `/nadreego/shop/paypal-onboarding/start` **HTTP 500 `PAYPAL_REFERRAL_INVALID`**, 로그아웃 HTTP 200.
- 원인 확인용 Sandbox referral 발급 요청의 PayPal 응답은 **HTTP 201 / 오류 없음 / Debug ID `f149304926d6b`**다. 판매자 동의나 DB 연결 저장은 하지 않았다.
- PayPal이 실제 반환한 `action_url`은 HTTPS `www.sandbox.paypal.com`으로 기존 검증 조건에 맞는다. `self`는 HTTPS **`api.sandbox.paypal.com`**, 경로는 `/v2/customer/partner-referrals/`로 시작한다.
- 현재 서버는 `self.netloc`가 요청 base인 **`api-m.sandbox.paypal.com`**과 정확히 같아야 한다고 검사하므로, 응답받은 `api.sandbox.paypal.com` 링크를 거절한다. 즉 리턴 URL 설정은 반영됐고 PayPal 링크 발급도 성공했으나 서버의 self 링크 호스트 검증에서 실패한다.

필요한 최소 수정은 환경별로 검증된 PayPal API 호스트만 명시적으로 허용하고 HTTPS·인증정보 없음·포트·경로 검증을 유지하는 것이다. 허용한 self 링크에서는 경로만 추출해 기존 고정 base로 후속 요청하는 구조를 유지한다. 임의 호스트나 Sandbox/Live 혼용을 허용해서는 안 된다. 실제 `api.sandbox.paypal.com` 응답 및 악성/다른 환경 호스트 거절 회귀를 추가한 뒤 재시작·실제 start 재검사가 필요하다. 이번 승인은 재시작·검사이므로 코드 수정은 수행하지 않았다.

온보딩 동의 후 앱 복귀·동일 관리자 세션 verify·판매자 저장·결제는 아직 미검증이다. 검사 종료 시 로그아웃했으므로 이번 발급 state를 이후 연결 검증에 재사용하면 안 된다. 실제 인수는 새 start와 유지된 같은 세션으로 진행해야 한다.

기록: `build/test-runtime/paypal-return-url-retest-2026-10-20.json`, `build/test-runtime/paypal-referral-link-diagnostic-2026-10-20.json`. state·action URL 원문·referral 식별자·토큰·Secret은 저장하지 않았다.

### 2026-10-20 01:02 UTC 수정 적용·실제 온보딩 start 통과

사용자의 수정·테스트 승인으로 `app/paypal.py`에서 referral `self` 링크의 허용 호스트를 환경별로 명시했다. Sandbox는 `api-m.sandbox.paypal.com` 및 실제 응답에서 확인된 `api.sandbox.paypal.com`, Live는 대응하는 `api-m.paypal.com` 및 `api.paypal.com`만 허용한다. HTTPS·기존 referral 경로·사용자정보 없음·포트 없음·query/fragment 없음 검사를 유지/명시했고, 이후 요청은 반환 링크의 경로만 사용해 기존 고정 API base로 보낸다. actionUrl의 환경별 호스트 검사도 유지했다. CORS·리턴 URL 값·DB·Firebase 설정은 변경하지 않았다. Live 허용 조건은 모의 테스트로만 검사했으며 실제 Live 요청은 하지 않았다.

격리 회귀는 `test_paypal_onboarding.py`, `test_merchant_accounts.py`, `test_refunds.py` **56 passed, 0 skipped, 0 failed (8.38초)**다. 별칭 호스트·기존 호스트, 후속 경로와 고정 base 유지, Sandbox/Live 교차 거절, 악성 호스트·HTTP·사용자정보·비정상 포트·잘못된 경로·query/fragment 거절을 포함한다. 전체 회귀 재실행은 아니다. `git diff --check` 통과.

API 재시작 후 PID 2674550, active/running, 공개 `/health/live` **HTTP 200**. 실제 승인 테스트 대표의 로그인 **200**, `/nadreego/shop/paypal-onboarding/start` **200**, 로그아웃 **200**. 실행 중 리턴 URL은 파일과 일치한다. start 응답의 **state 존재·Sandbox actionUrl 호스트·expiresAt 존재·paymentEnvironment=SANDBOX**를 확인했으며 값 원문은 출력하거나 저장하지 않았다. 변경 코드는 작업 트리에 있고 별도 커밋하지 않았다.

판정: 리턴 URL 설정 반영 및 PayPal 링크 발급→백엔드 start 응답 구간은 실제 통과. 판매자 로그인·동의, Android/iOS 앱 복귀, 같은 세션의 verify, 지점 판매자 저장·결제·환불은 미검증이다. 이번 테스트는 종료 시 로그아웃했으므로 발급된 state로 후속 verify를 진행하지 않는다. 실제 연결은 새 start를 발급받고 같은 관리자 세션을 유지해 수행해야 한다.

최신 실제 결과는 `build/test-runtime/paypal-return-url-retest-2026-10-20.json`에 갱신했다. 앞선 500 결과는 이 문서의 이전 검사 절에 별도 보존했다.

최신 보완 결과(05:09 UTC): 고객 이력의 관리자 FK 충돌을 코드에서 수정하고 재시작했다. 판매자 미연결 상태의 실제 예약 신청 HTTP 200, REQUESTED 저장, 중복 차단·상세 조회 통과. 10절의 실패는 11절의 재검증으로 해소됐다.

최종 서버 확인: **2026-10-19 02:31:46 UTC**. 실제 인증/API 검사 기록 02:07:27 UTC, 공개/가격 검사 기록 02:08:28 UTC, 서비스/로그/작업 등록 기록 02:28:39 UTC. 기준 문서는 [최신 전체 인수서](nadree-full-change-handoff.md)의 2026-10-18 정책 및 **2026-10-19 앱 복귀 역할 분담**이다.

검증 대상 HEAD는 `ba23d26580d25bb23621fe021e2af885a6633932`다. 점검 시작 시 `f69474000e6ea21cf30363b52920c20f2ae7cd30`였고 중단 사이 최신 HEAD로 바뀌었다. 두 커밋의 차이는 인수 문서 1개뿐이며 Python 실행 코드·설정·테스트 변경은 없다. f694740의 커밋 시각은 01:18:47 UTC, API 시작 시각은 01:37:57 UTC다. 이 보고서는 프로세스 경로·시각·저장소 코드 대조 결과이며 별도 버전 응답 API에서 Git SHA를 받은 것은 아니다.

**기본 회귀 314 passed/10 skipped를 재현했다. 격리 MySQL 포함 회귀는 320 passed/4 skipped, 별도 Firestore 4개도 통과했다. 실제 HTTP/공개 스키마 검사 21개와 승인 계정 API 검사 33개가 통과했고, 추가 격리 배송·종료 조회 검사 20개도 통과했다. 최신 재검사에서 Sandbox OAuth와 웹훅 목록·상세 조회는 통과했다. 웹훅 이벤트 5개 누락은 승인 후 추가했고 상세 재조회에서 누락 0개를 확인했다. 복귀 URL은 설정 대기이며 실제 판매자 연결·결제·환불·App Check·탈퇴 종단 인수는 미검증이다. 테스트 개수를 전체 실연동 완료로 해석하지 않는다.**

## 1. 배포·설정·마이그레이션

| 검사 | 기대 | 실제 | 판정 |
| --- | --- | --- | --- |
| 실행 서비스 | 기존 서비스·독립 실행 경로 유지 | nadree-api.service, ec2-user, /srv/nadree-api, .venv/bin/uvicorn app.main:app, port 8008 | 통과 |
| 프로세스·코드 경로 | 배포 경로와 일치 | /proc/MainPID/cwd도 /srv/nadree-api. PID 2509709 유지 | 통과 |
| live/ready | 200 | 모두 200, 기존 MFA_FLOW_NOT_IMPLEMENTED 제한 유지 | 통과·제한 유지 |
| Swagger/OpenAPI | 최신 경로 공개 | /docs, /openapi.json 200. tierCreate·예약 직접 조회·판매자 start/verify·기존 merchant·탈퇴 경로 확인 | 통과(스키마 확인) |
| 마이그레이션 | pending 없음 | app.migrate를 읽기 전용으로 시작/종료 시 실행, 모두 No pending changes | 통과 |
| 서버 env 반영 | 파일과 실행 설정 일치 | Settings 전체 비교 일치. DB/Redis/JWT/암호화/QR/FCM·Auth/PayPal Client/Secret/Webhook/Partner 설정 존재 | 통과(유무 확인) |
| 복귀 URL | 프론트 확정 전 미설정 허용 | 설정 없음. 값 추가·대체 안 함 | 설정 대기 |
| DB 대상 | 의도한 테스트 DB | RIDERLOG_V2_DATA_TEST | 통과 |
| 판매자 컬럼 | 기존 지점/결제 컬럼 사용 | MSP_SPOT_RENT의 paypal_merchant_id/paypal_environment, MSP_RENTAL_PAYMENT의 paypal_merchant_id 존재 | 통과(구조 확인) |
| 제외 테이블 | 요청 결과·개인정보 작업·온보딩 신규 테이블 없음 | 실제 테이블 이름과 현재 metadata에서 해당 전용 테이블 미발견. 이번 작업에서 생성 안 함 | 통과 |
| 제외 타이머 | 온보딩/개인정보 전용 작업 없음 | 로컬 systemd에서 해당 타이머 미발견 | 통과(로컬 등록 범위) |
| 기존 결제·환불 복구 | 기존 운영 작업 유지 | 로컬 nadree-payments.service/timer는 LoadState=not-found. 검사한 systemd/cron에서 payments/all/refund_recovery 직접 등록 미발견 | **운영 동작 미검증** |
| 채팅 작업 | 기존 작업 유지 | nadree-chat-sync.service/timer 등록 유지, 중복 설치·재시작 안 함 | 통과(등록 확인) |
| 서비스 오류 로그 | 예상 오류 외 신규 장애 없음 | 재시작 이후 Traceback/DB 오류/Firebase 초기화 오류 0. HTTP 5xx 1건은 이번 start의 예상된 503과 일치 | 통과 |

결제 복구는 로컬 등록이 없다는 사실만 확인했다. 외부 스케줄러·별도 래퍼 등록은 확인하지 못했으므로 자동 복구가 실행 중이라고 표시하지 않는다. 기존 작업을 중지/삭제하거나 새 타이머를 설치하지 않았다. 운영자가 실행 주체·주기·최근 성공 기록을 확인해야 한다.

설정은 유무·일치 여부만 확인했으며 env 원문·키·토큰·비밀번호를 출력/기록하지 않았다. 부모 명세 `/srv/rental-project-master.md`, `/srv/rental-api-review-decisions.md`는 이 서버에 없어 직접 대조하지 못했다. 추가 구현·실제 DB 스키마 변경·서비스 재시작·Firebase 배포·보안 완화는 하지 않았다.

## 2. 격리 회귀·추가 시나리오

운영/공유 DB를 자동 테스트 대상으로 사용하지 않았다. 기본 실행은 /tmp 작업 경로, 깨끗한 환경, 저장소 PYTHONPATH, env 파일이 없는 상태로 실행했다. 확장 실행은 네트워크 비활성 임시 MySQL 8.4.6의 nadree_w02_test_* DB 및 SQLite fixture를 사용했다. Firebase는 demo-nadree-chat/로컬 Firestore, PG·FCM·계정 삭제는 대역이다.

| 실행 검사 | 실제 결과 | 해석 |
| --- | --- | --- |
| 기본 전체 pytest, 외부 MySQL/Firestore 설정 없음 | **314 passed, 10 skipped**, 70.93초, 기존 의존성 경고 2종 | 문서 기준 재현 |
| MySQL 포함 전체 29개 파일, 파일별 프로세스 | **320 passed, 4 skipped**, 실패 파일 없음 | MySQL 동시성 6개 추가 통과. 공유 DB 잠금 인수와 다름 |
| Firestore 통합 별도 실행 | **4 passed** | 기본/확장 회귀에서 건너뛴 동일 4개를 에뮬레이터에서 통과 |
| Firestore Rules | **4 passed**, 실패 0 | 고객/직접 직원 읽기, 쓰기 금지, 세션/쿼리 범위 제한 |
| callable 업무 핸들러 5개·만료 함수 | 통과 | 실제 Python 핸들러·합성 인증을 demo Firestore로 연결. HTTP App Check 종단과 다름 |
| 추가 배송·종료 조회 API 시나리오 | **20개 검사 통과** | 합성 주소·별도 SQLite. pytest 개수에 합산하지 않음 |

10개 건너뜀은 MySQL 6개와 Firestore 4개이며, 확장 회귀의 4개는 tests/test_chat_firestore.py다. 명시적 demo 프로젝트/에뮬레이터 설정이 없으면 실제 Firebase에 접근하지 않도록 skip한다. 이번 실행들을 합치면 해당 Python 테스트 324개가 실행돼 통과한 것이며, 반복 실행한 결과를 더해 테스트 수를 부풀리지 않는다. 기본 회귀·확장 회귀·에뮬레이터 모두 최종 정상 종료했다.

대표 실행 명령/기록:

```sh
# cwd=/tmp, env -i로 운영 env를 상속하지 않음
PYTHONPATH=/srv/nadree-api PYTHONDONTWRITEBYTECODE=1 \
  /srv/nadree-api/.venv/bin/python -m pytest /srv/nadree-api/tests \
  -q -p no:cacheprovider --tb=short -c /srv/nadree-api/pyproject.toml

# 실제 DB는 읽기 전용 계획만 조회
sudo -u ec2-user env PYTHONPATH=/srv/nadree-api \
  /srv/nadree-api/.venv/bin/python -m app.migrate
```

기본 로그는 build/test-runtime/baseline-2026-10-19.log, 확장 로그는 regression-2026-10-19-final.log, 에뮬레이터 로그는 emulator-2026-10-19.log다. 중단 전 regression-2026-10-19.log는 완료 결과로 사용하지 않았다.

## 3. 요구사항별 기대/실제 결과

아래의 ‘격리 통과’는 코드 읽기만 했다는 뜻이 아니라 실제 테스트 실행 결과다. 실제 서비스와 외부 실연동 여부를 별도로 표시한다.

| 항목 | 기대 | 실제 검증 | 판정·남은 범위 |
| --- | --- | --- | --- |
| 가용성·가격 | 승인 테스트 모델과 가격 옵션 제공 | 실제 availability 200. 테스트 지점/웹 모델 존재, priceOptionId/totalPrice 포함. BASIC DB 기대 일단가 25 일치, PREMIUM 응답이 DB 고정 단가와 일치 | 실제 읽기 통과 |
| BASIC 부분 우선·BASE 잔여·PREMIUM | 1~25 BASIC 우선, 나머지 BASE, PREMIUM 고정 | test_pricing_batch에서 부분 분할·경계 cc·고정 가격 실행 통과 | 격리 통과. 실제 DB에 새 BASE/부분 티어를 만들지는 않음 |
| 배열·동일 구간 수정 | UPDATED 저장, 중첩/중복 거절, 전체 원자성 | 실제 기존 테스트 BASIC 1행을 배열로 일시 +1 수정, GET으로 저장 확인 후 원값 복구·GET 확인. 중복 배열 422 TIER_BATCH_DUPLICATE_RANGE, 부분 중첩 409 TIER_RANGE_OVERLAP | 실제 수정/복구 통과. 신규/다중 항목·실패 원자성은 격리 통과 |
| 예약 생성·중복 | 요청 생성, 60초 이내 409 DUPLICATE_RENTAL_REQUEST | 기본 흐름 및 추가 배송 API에서 생성·행 저장·같은 요청 재전송 거절 통과 | 격리 통과. 실제 생성은 미검증(아래 영향 제한) |
| 다른 고객 예약 | 소유자 외 404 | 실제 승인 고객으로 다른 승인 시드 예약 직접 조회 404 RESERVATION_NOT_FOUND. 격리에서도 타 고객 접근 거절 | 실제/격리 통과 |
| 배송 | 주소 저장·선택 요금표 사용, 구역 추정 없음 | 합성 주소의 지역명과 무관하게 선택 ID 요금 적용. START_ONLY 회수비 0, 왕복 서로 다른 주소 보존, 다중 요금표 미선택 409 DELIVERY_REGION_REQUIRED. DB 저장값 확인 | 격리 API 통과. 실제 주소 판정/지리 검증은 범위 제외 |
| 이메일 직원 가입 | REQUESTED/PENDING_APPROVAL, 승인 전 관리권한 없음 | test_admin_signup 및 관련 권한 테스트 통과 | 격리 통과. 실제 새 계정 생성·권한 부여는 안 함 |
| 지점 코드 가입 | 대표 즉시 ACTIVE, 코드 1회 소진 | 격리 지점 생성→가입→코드 NULL→재사용 404 INVITE_CODE_NOT_FOUND, 직접 지점 권한 확인 | 격리 통과. 실제 기존 코드 소진 안 함 |
| 고객 취소 | 인계 전 시작일 전 90%, 당일부터 0%, 0%는 PG 환불 없음 | test_cancellation_policy의 날짜 경계·미결제·인계/권한 차단·환불 호출 검증 통과 | 격리 통과. 실제 PG 환불 미검증 |
| 지점 귀책 관리자 취소 | 당일 포함 인계 전 100%, BRANCH_FAULT만 | 당일/정확한 날짜 경계·인계 후 거절·반복/환불 정책 테스트 통과 | 격리 통과. 실제 기존 예약 취소 안 함 |
| 고객/관리자 조회 권한 | 서로 다른 인증 영역·지점 범위 | 실제 고객 Firebase 인증→로그인→profile/ongoing/completed 200, 대표·직원 로그인·main·알림 조회 200 | 실제 조회 통과 |
| 종료 내역 | 반납·취소·거절·만료 포함 | 추가 격리 API에서 4종 목록 포함, 각 본인 직접 조회 200·타 고객 404 확인 | 격리 통과. 실제 고객 종료 목록은 200이지만 빈 데이터여서 4종 실데이터 인수는 미검증 |

실제 쓰기는 사용자가 기존 시드 파일 기준으로 지정한 테스트 관리자·고객·지점만 사용했다. 가격은 기존 BASIC 값으로 복구됐고 신규 가격 행·공통 BASE는 추가하지 않았다. 승인 시도는 merchant 미연결로 409에서 차단됐으며 기존 예약은 승인/거절/취소로 바꾸지 않았다. 새 회원·지점·초대코드도 만들지 않았다.

예약/취소 실제 성공 요청은 기존 지점의 FCM 수신 토큰이 존재해 실제 푸시를 발생시킬 수 있으므로 수행하지 않았다. 실제 인증 검사를 풀거나 FCM 설정을 끄는 대신 격리 API로 검증했다. 마지막에 세 테스트 계정을 정상 로그아웃했다. 로그인/로그아웃의 기존 세션 및 채팅 세션 회수는 정상 인증 경로의 부수 효과이며, 계정 삭제·채팅 메시지 작성·방/업무 데이터 수정은 하지 않았다.

공개 HTTP/스키마 검사 **21개 통과**, 실제 승인 계정 검사 **33개 통과·설정 대기 1개·미검증 표시 1개**다. Swagger 경로 존재 확인은 업무 성공 검증의 대체 근거가 아니다. 실제 결과에는 HTTP 코드/오류 코드/통과 여부만 보관하고 응답 프로필·주소·토큰은 저장하지 않았다.

## 4. PayPal 판매자 연결

| 검사 | 기대/실제 | 판정 |
| --- | --- | --- |
| 지점 ID 없음 | 실제 APPROVE가 409 SHOP_PAYPAL_MERCHANT_REQUIRED. 격리에서는 상태 REQUESTED 유지·REJECT 200 확인 | 실제 승인 차단·격리 거절 통과 |
| 임의 ID 입력 | 실제 대표 PUT가 409 PAYPAL_ONBOARDING_REQUIRED, 직원은 403 PRIMARY_ADMIN_REQUIRED | 실제 통과, 연결값 변경 없음 |
| 직접 지점 대표만 연결 | 실제 직원 start 403. 다른 지점 대표/상위 대표 제한은 격리 실행 통과 | 실제 직원 차단·격리 통과 |
| 기존 컬럼·동일 ID 여러 지점 | 기존 컬럼 존재, 격리 start/verify에서 root/child 동일 판매자 저장·재전송·연결 해제 확인 | 구조 확인·격리 통과. 실제 연결 성공은 미검증 |
| Sandbox/Live 분리·원거래 판매자 | 격리에서 환경 불일치 차단·기존 결제 ID 보존·해제 후 원거래 환불 대상 유지 확인 | 격리 통과 |
| state 경계 | 실제 HTTP로 변조/다른 세션·지점·환경 400 PAYPAL_ONBOARDING_STATE_INVALID, 만료 410 PAYPAL_ONBOARDING_STATE_EXPIRED | 실제 부정적 경계 통과 |
| 복귀 URL | 실제 대표 start가 503 PAYPAL_ONBOARDING_RETURN_URL_REQUIRED | **설정 대기, 예상 결과** |
| 실제 Sandbox 인증 | 설정 반영·재시작 후 OAuth HTTP 200, 02:51:44 UTC 재확인도 200 | **통과(이전 401 해소)** |
| 실제 판매자 연결·결제·환불·서명 웹훅 정산 | 이번에 start 발급/복귀/판매자 저장·자금 처리를 하지 않음 | **미검증** |

실제 state 오류 테스트는 검증용 합성·변조 state를 현재 승인 관리자 인증으로 보낸 것이다. URL 미설정으로 정상 start state를 발급받아 실제 PayPal을 왕복한 결과와 구분한다. 실제 연결값·환경값·키·복귀 URL은 수정하지 않았다.

OAuth 401의 관측 원인은 PayPal의 invalid_client다. Sandbox 앱의 Client ID/Secret 조합 또는 환경 일치 여부 확인이 필요하지만 정확히 어느 값이 잘못됐는지는 이번 결과만으로 확정하지 않는다. LIVE endpoint로 바꿔 시험하거나 인증/판매자 검증을 우회하지 않았다. 웹훅 등록/판매자 이벤트 구독 재조회는 **미실행**이며 웹훅 자체의 실패로 판단하지 않는다. 이전 날짜의 인증 성공 결과를 현재 성공으로 사용하지 않는다.

### OAuth 요청·설정 재확인 — 2026-10-19 02:39:28 UTC

- 실행 중 `nadree-api.service`의 PID는 2509709이고 작업 경로는 `/srv/nadree-api`다. 서비스의 EnvironmentFile은 `/srv/nadree-api/.env`다. 실행 프로세스의 Client ID/Secret과 현재 파일에서 로드한 설정이 모두 일치했다.
- 두 설정은 각각 파일 및 프로세스 환경에서 한 번씩 존재했다. 누락·앞뒤 공백·CR/LF 줄바꿈은 없고 dotenv 구문 오류도 없었다. 다른 값으로 덮어쓰인 징후는 확인되지 않았다.
- 현재 `PayPalClient`의 HTTP 클라이언트로 OAuth 요청을 재현하고 전송 시점 요청을 검사했다. 실제 목적지는 `https://api-m.sandbox.paypal.com/v1/oauth2/token`, 메서드는 POST였다. HTTP Basic의 두 값은 실행 중 설정의 Client ID/Secret과 일치했고, 폼은 `grant_type=client_credentials`였다. 헤더·인증 값·응답 토큰은 출력하거나 저장하지 않았다.
- 원격 응답: **HTTP 401 / 오류 코드 `invalid_client` / PayPal Debug ID `f923072aff6ce`**.
- 웹훅 조회는 실행하지 않았다. 키 수정과 서비스 재시작도 하지 않았다. 파일과 실행 설정이 일치하므로 이번 결과를 미반영 설정 문제로 판단하지 않는다.
- 후속 작업: PayPal Developer의 **Sandbox REST 앱**에서 Client ID와 Secret이 동일 앱의 유효한 한 쌍인지 비공개로 확인한다. 401만으로 어느 값이 잘못됐거나 폐기됐는지, Live 키인지까지 확정할 수 없다. 사용자 승인에 따라 키를 수정한 경우 재시작 후 같은 OAuth 검사를 반복할 수 있다. 인증 검사는 우회하지 않는다.

검사 기록: `build/test-runtime/paypal-oauth-diagnostic-2026-10-19.json` (설정 진단 불리언·개수 및 허용된 응답 메타데이터만 저장).

**최신 재검사 — 2026-10-19 02:50:03 UTC: OAuth 통과.** 사용자 설정 수정 후 파일의 Sandbox Client ID/Secret 존재·공백·줄바꿈 조건을 확인했다. 실행 중 Client ID가 파일과 달라 기존 승인 범위에서 `nadree-api.service`를 재시작했다. 새 PID 2521781, active/running, 공개 `/health/live` HTTP 200을 확인했다. 재시작 후 두 자격증명이 파일과 실행 프로세스에서 일치했고 중복·누락·공백·줄바꿈은 없었다. Sandbox URL·HTTP Basic·grant_type 검사도 통과했다. **HTTP 200 / 오류 코드 없음 / PayPal Debug ID `f870441c0ae8b`**. 이전 OAuth 실패는 이 최신 결과로 해소됐다. 웹훅 조회·실제 판매자 연결·결제·환불은 이번 재검사에서 실행하지 않았으므로 해당 항목의 성공을 의미하지 않는다. 키·Authorization·access token은 출력하거나 저장하지 않았다.

재검사(2026-10-19 02:48:30 UTC): **HTTP 401 / 오류 코드 `invalid_client` / PayPal Debug ID `f851264c255ce`**。 이번에는 현재 파일에서 로드한 Client ID/Secret과 실행 프로세스 설정이 모두 불일치했다. `.env`에서 정확한 변수명 `NADREE_PAYPAL_CLIENT_SECRET`의 할당이 0개로 확인됐다(이전 검사에서는 1개). 실행 중 프로세스에는 기존 값이 존재한다. 파일 설정이 변경된 상태이므로 이전의 설정 일치 판정은 이번 시점에 적용되지 않는다. 키 값이나 변수명을 임의 수정하지 않았고, 불완전한 설정으로 서비스 재시작도 하지 않았다. 웹훅 조회는 미실행이다. 비공개로 해당 변수명과 값의 저장을 완료한 후 설정 반영·재검사가 필요하다.

재검사(2026-10-19 02:44:14 UTC): **HTTP 401 / 오류 코드 `invalid_client` / PayPal Debug ID `f923639ef3d45`**. 파일과 실행 중 설정 일치, 누락·공백·줄바꿈·중복 없음, Sandbox URL·Basic 인증·grant_type 정상임을 다시 확인했다. 웹훅 조회·설정 변경·서비스 재시작은 수행하지 않았다.

재검사(2026-10-19 02:42:32 UTC): 사용자의 설정 적용·재시작 완료 안내 후 다시 확인했다. 현재 파일과 실행 프로세스의 Client ID/Secret은 여전히 일치하며 누락·공백·줄바꿈·중복이 없었다. Sandbox URL·Basic 인증·grant_type 검사도 통과했다. 원격 응답은 **HTTP 401 / 오류 코드 `invalid_client` / PayPal Debug ID `f2876551da837`**였다. 웹훅 조회는 미실행이다. 관측 PID는 앞선 검사와 같은 2509709로, 두 검사 사이 재시작 여부를 이 결과로 입증하지는 않는다. 설정 변경이나 추가 재시작은 수행하지 않았다.

기존 결제 중 판매자 ID가 없는 행은 읽기 전용 집계에서 4개다. 마이그레이션은 이를 임의 추정/보충하지 않는다. 격리 테스트는 seller가 없는 기존 결제를 PAYMENT_MERCHANT_RECONCILIATION_REQUIRED로 차단함을 확인했다. 이 4개 실제 거래의 판매자/복구 상태는 별도 대조가 필요하며 수정·환불·재시도하지 않았다.

## 5. 탈퇴·채팅·App Check

| 항목 | 실제 실행 근거 | 판정 |
| --- | --- | --- |
| 탈퇴 프로필/FCM·세션 | test_nadri_auth에서 DELETE 성공 응답, 프로필/FCM 비움, access/refresh 차단, 이전 auth_time 재사용 거절 확인 | 격리 통과 |
| Firebase 삭제·채팅 회수 | 외부 호출 대역의 순서/대상, 서비스 실패 시 503·SQL 폐기/성공 오표시 방지 확인 | 격리 통과. 실제 삭제 종단 미검증 |
| 전용 개인정보 작업 테이블 없음 | 실제 이름 점검·현재 metadata와 기존 처리 확인 | 통과(구조). 신규 테이블 생성 없음 |
| 대표 답변·일반관리자 읽기 | MemoryStore/Firestore 에뮬레이터/실제 함수 업무 핸들러에서 대표 전송 성공·직원 전송 거절/열람 허용·다른 지점 차단 | 격리/에뮬레이터 통과. 실제 메시지 종단 미검증 |
| App Check | 문서 지정 고객/관리자 비공개 JSON 미제공·해당 경로 파일 없음 | 미검증. 비활성화/위조 등록/보안 완화 안 함 |

실제 회원 삭제는 별도 승인 대상이므로 기존 고객 UID를 삭제하지 않았다. 승인된 실제 폐기용 계정과 App Check 비공개 자료 없이 해당 종단을 실행하지 않는다. Firebase 삭제 후 SQL 실패 같은 분산 처리의 부분 성공은 기존 인수 문서의 운영 확인 항목이며 새 작업 테이블·자동 정리 타이머로 대체하지 않았다. 실제 채팅 본문/거래 주소의 후속 삭제도 이번 범위가 아니다.

## 6. 실패·설정 대기·미검증과 후속 작업

1. **해소 — Sandbox OAuth 401 invalid_client:** 설정 반영·승인된 재시작 후 HTTP 200 확인. 추가 키 수정은 필요하다고 판단하지 않는다. 웹훅 이벤트 누락도 02:58 UTC 사용자 승인 후 보완·재조회 완료했다.
2. **설정 대기 — 앱 복귀 URL:** 프론트가 HTTPS App Link/Universal Link 등 실제 복귀 주소를 확정하여 서버 담당자에게 전달한다. 임의 URL을 넣지 않았다. 주소 확정·설정·현재 관리자 세션 유지 후 실제 start→복귀→verify 성공을 다시 확인한다.
3. **운영 동작 미검증 — 결제 복구 작업:** 로컬 systemd unit 없음·검사한 cron 직접 등록 없음. 외부 스케줄러가 있다면 주체/주기/최근 성공 결과를 제공해야 한다. 없으면 설치 대상·처리할 승인 테스트 거래·실제 PG/알림 영향을 검토한 뒤 별도 승인한다. 기존 작업 삭제/중지는 하지 않았다.
4. **미검증 — 실제 PG·탈퇴·App Check·기기:** Partner 권한·검증된 판매자·구매자 승인·테스트 거래, 승인된 폐기용 계정 및 보호된 App Check 자료로 별도 인수한다. 이번 모의·에뮬레이터 통과를 실제 외부 성공으로 표시하지 않는다.
5. **미검증 — 실제 가입코드 소진/새 계정·예약 생성/취소/배송 저장:** 운영 데이터·권한·알림을 변경하지 않도록 격리에서 수행했다. 별도 지정한 소모 가능한 지점/계정/차량 및 푸시 영향 승인이 있으면 실제 서비스에서도 이어서 확인할 수 있다.

프론트 확인 사항:

- 앱 복귀 화면·링크·종료 처리는 프론트 담당. PayPal 완료/복귀 자체를 성공으로 표시하지 않고 state와 **같은 관리자 세션**으로 verify 성공 후 종료한다. 실패·취소를 구분하고 예약 승인은 별도 재요청한다.
- HTTPS 복귀 주소는 query/fragment 없이 확정해 전달한다. custom scheme은 현재 HTTPS 제한과 먼저 협의한다. state를 로그·분석도구에 남기지 않고 URL에서 제거한다. 만료/다른 세션이면 start부터 다시 진행한다.
- priceOptionId/배송 포함 totalPrice는 응답 값을 사용하고 임의 합성·배송비 중복 가산을 하지 않는다. effectiveTiers는 편집용 원구간이 아니며 tiers를 저장/삭제에 사용한다.
- 응답 유실은 새 요청을 무조건 보내지 말고 진행/종료 목록·본인 예약 직접 조회로 확인한다. 중복 검사는 60초이며 장기 멱등/요청 결과 저장 테이블은 없다.
- 주소는 지리 검증 결과가 아니다. 배송 요금표 선택을 구역 판정처럼 표시하지 않는다. 관리자 취소는 지점 귀책 100%이며 고객 취소 90%/0%와 분리한다.
- 탈퇴/로그아웃 시 클라이언트 캐시를 비우고 App Check·Android/iOS 복귀·실기기 푸시는 별도로 확인한다.

## 7. 결과 파일

### OAuth 해소 후 추가 검증 — 2026-10-19

현재 코드 `ba23d26580d25bb23621fe021e2af885a6633932` 기준, 02:51:44 UTC에 Sandbox 읽기 전용 검사를 수행했다.

| 검사 | 기대 | 실제 | 판정 |
| --- | --- | --- | --- |
| OAuth | HTTP 200 | HTTP 200, 오류 없음, Debug ID `ca4cc7b93398f` | 통과 |
| 웹훅 목록 | HTTP 200 및 현재 설정 ID 존재 | HTTP 200, 설정 ID 존재, Debug ID `ca4cc7b979b4d` | 통과 |
| 웹훅 상세 | HTTP 200, 현재 API 콜백 일치 | HTTP 200, `https://na-dree.com/nadreego/paypal/webhook` 일치, Debug ID `ca4cc7b9bfcad` | 통과 |
| 이벤트 구독 | 서버 처리 이벤트 구독 | 아래 5개 누락, 와일드카드 구독 없음 | 실패(설정 불일치) |
| 앱 복귀 URL | 프론트 확정값 설정 | 미설정 | 설정 대기 |
| Partner 설정 | 유무·형식 확인 | Merchant ID 존재·13자리 형식 충족, Attribution ID 존재 | 형식 확인만. 실제 Partner 권한 미검증 |

누락 이벤트는 `CHECKOUT.PAYMENT-APPROVAL.REVERSED`, `PAYMENT.CAPTURE.DECLINED`, `PAYMENT.CAPTURE.REVERSED`, `PAYMENT.REFUND.FAILED`, `PAYMENT.REFUND.PENDING`이다. 해당 이벤트가 현재 구독을 통해 전달되지 않아 승인 철회·캡처 거절/취소·환불 보류/실패의 이벤트 기반 반영이 누락될 수 있다. 별도 조회·복구 작업이 모두 대체한다고 판단하지 않는다. **수정안은 현재 Sandbox 앱에서 조회된 기존 웹훅 한 개에 이 5개 구독만 추가하고 콜백·기존 구독을 보존하는 것이다. 신규 웹훅 생성·삭제나 Live 변경은 필요하지 않다. 이번 작업에서는 설정 변경을 실행하지 않았으며 승인 후 적용한다.**

추가 격리 회귀: `test_paypal_onboarding.py`, `test_payment_safety.py`, `test_payment_deadline_policy.py`, `test_refunds.py`, `test_webhook_replay.py`를 `/tmp`에서 `env -i`로 서버 환경변수를 제거하고 실행했다. **50 passed, 0 failed, 0 skipped (9.54초)**. 테스트 DB·모의 PG를 사용했으며 실제 서비스 DB를 대상으로 실행하지 않았다. 판매자 연결/state/권한, 결제 중복·응답 불명·지연/역순 처리, 결제 기한, 취소·환불 정책, 웹훅 서명 시간·재전송/멱등 처리를 검증했다. 샌드박스 내 첫 실행들은 진행 지연으로 중단했고, 권한 승인 후 같은 격리 조건에서 재실행한 최종 결과다. 의존성 deprecation 경고 2건은 실패가 아니다.

실제 판매자 연결은 확정 복귀 URL과 Sandbox 판매자 동의가 필요하다. 실제 주문 승인·캡처·환불 및 서명된 웹훅 수신/정산은 이번에 실행하지 않았고 미검증이다. 현재 변경된 앱의 승인된 거래·판매자 연결 대상이 확정되지 않았으므로 과거 앱의 주문을 재사용하지 않았다. 진행하려면 테스트 판매자·구매자, 소액 거래 대상 및 Sandbox 캡처·환불 영향에 대한 승인이 필요하다. 실제 고객·Live·푸시·회원 삭제는 실행하지 않았다.

원격 조회 기록: `build/test-runtime/paypal-post-oauth-2026-10-19.json`. 비밀값·인증 헤더·access token은 기록하지 않았다.

git에서 제외되는 build/test-runtime 아래에 비밀값 없는 재현 자료를 보관했다.

- baseline-2026-10-19.log / regression-2026-10-19-final.log / emulator-2026-10-19.log
- public-verification-2026-10-19.json: 실제 HTTP/스키마 21개
- live-verification-2026-10-19.json: 통과 33·설정 대기 1·미검증 1
- delivery-api-2026-10-19.json / delivery-terminal-api-2026-10-19.log: 추가 격리 20개
- system-verification-2026-10-19.json: 서비스·등록·오류 건수
- paypal-readonly-2026-10-19.json: 현재 Sandbox OAuth 실패

검증 도구의 경로/표기/컬럼명 조정은 보조 스크립트에만 했고 애플리케이션·마이그레이션·Firebase·서비스 설정은 수정하지 않았다. 실제 테스트 지점 가격 수정/원복과 승인 테스트 계정 인증 외 업무 데이터 쓰기는 하지 않았다. 토큰·비밀번호·실제 프로필·실제 배송 주소·개인정보 응답 원문은 결과 파일이나 이 문서에 넣지 않았다.


## 8. 승인된 Sandbox 웹훅 구독 보완 완료 — 2026-10-19 02:58 UTC

대상은 실행 중 서비스가 설정한 현재 Sandbox 앱의 **기존 웹훅 한 개**다. 사용자 승인에 따라 최신 상세를 읽고 기존 구독과 아래 5개 이벤트의 합집합으로 `/event_types`만 PATCH했다. 변경 직전 상세를 다시 읽어 첫 조회 이후 콜백·구독이 바뀌지 않았는지 확인했다. 적용 방식은 [PayPal 공식 웹훅 API 명세](https://github.com/paypal/paypal-rest-api-specifications/blob/main/openapi/notifications_webhooks_v1.json)의 기존 웹훅 PATCH를 따랐다.

추가한 이벤트:

- `CHECKOUT.PAYMENT-APPROVAL.REVERSED`
- `PAYMENT.CAPTURE.DECLINED`
- `PAYMENT.CAPTURE.REVERSED`
- `PAYMENT.REFUND.FAILED`
- `PAYMENT.REFUND.PENDING`

| 검사 | 실제 결과 | 판정 |
| --- | --- | --- |
| Sandbox OAuth | HTTP 200, 오류 없음, Debug ID `f6530810788fb` | 통과 |
| 기존 웹훅 구독 수정 | HTTP 200, 오류 없음, Debug ID `f164470299fc2` | 통과 |
| 적용 후 상세 재조회 | HTTP 200, 오류 없음, Debug ID `f7075851311b6` | 통과 |
| 웹훅 동일성 | 설정한 기존 웹훅 ID와 동일 | 통과 |
| 콜백 보존 | `https://na-dree.com/nadreego/paypal/webhook` 유지 | 통과 |
| 기존 이벤트 보존 | 기존 10개 모두 보존, 승인된 5개만 추가, 총 15개 | 통과 |
| 승인 이벤트 및 서버 처리 이벤트 | 누락 모두 0개 | 통과 |

새 웹훅 생성·삭제·Live 요청·키 변경·API 재시작·DB 변경은 하지 않았다. 비밀값·Authorization·access token은 출력하거나 저장하지 않았다. 변경 전후 이벤트 목록과 허용된 응답 메타데이터는 `build/test-runtime/paypal-webhook-update-2026-10-19.json`에 기록했다. 복구가 필요할 경우 이 기록의 변경 전 이벤트 10개로 해당 웹훅의 `/event_types`만 되돌릴 수 있으나, 복구 변경은 별도 승인 후 수행한다.

위의 과거 이벤트 누락 실패·승인 대기 기록은 이 최신 완료 결과로 대체된다. 실제 결제·환불·서명된 이벤트 전달과 DB 정산 종단 검증, 실제 판매자 연결 및 앱 복귀 URL 설정 대기는 여전히 별도 미검증/설정 대기다. 구독 설정 성공을 실제 이벤트 처리 성공으로 표시하지 않는다.

## 9. 실제 서버 테스트 데이터 진행 확인 — 2026-10-19 03:00:05 UTC

사용자의 실제 테스트 요청에 따라 DB가 `RIDERLOG_V2_DATA_TEST`인지 재확인하고 기존 승인 테스트 지점·대표·예약만 사용했다. 실제 HTTPS API를 호출했으며 모의 응답이 아니다. 현재 승인 지점의 판매자 ID는 없고 앱 복귀 URL도 미설정이다.

| 실행 검사 | 기대/실제 | 판정 |
| --- | --- | --- |
| 테스트 대표 로그인 | HTTP 200 | 통과 |
| 테스트 지점 판매자 상태 조회 | HTTP 200, 미연결 | 조회 통과·연결 선행 필요 |
| 실제 판매자 연결 시작 | HTTP 503 `PAYPAL_ONBOARDING_RETURN_URL_REQUIRED` | 예상 차단 확인·설정 대기 |
| 기존 테스트 예약 승인 시도 | HTTP 409 `SHOP_PAYPAL_MERCHANT_REQUIRED` | 예상 차단 확인·판매자 연결 대기 |
| 승인 시도 후 예약 보존 | 기존 REQUESTED 유지 | 통과 |
| 실제 웹훅에 서명 없는 요청 | HTTP 400 | 보안 차단 통과·정상 서명 이벤트 수신은 미검증 |
| 테스트 대표 로그아웃 | HTTP 200 | 통과 |

7개 검사에서 기대 응답/상태를 확인했지만, 설정 대기 응답을 정상 판매자 연결·결제 성공으로 계산하지 않는다. 로그인·로그아웃은 해당 테스트 대표의 인증/채팅 세션에 영향을 주는 기존 동작이며 별도 고객이나 일반 운영 계정은 사용하지 않았다. 주문 생성·캡처·환불·푸시 발송은 모두 0건이다. 판매자 ID 수동 주입·임의 복귀 URL·검사 우회는 하지 않았다.

다음 선행 작업은 프론트가 확정한 HTTPS 앱 복귀 URL 설정과 해당 테스트 지점 대표의 Sandbox 판매자 연결 동의다. 이 작업 후 소액 Sandbox 주문 생성→구매자 승인→캡처→환불 및 실제 서명 웹훅/정산 확인을 이어갈 수 있다. 과거 앱의 테스트 주문은 재사용하지 않았다.

기록: `build/test-runtime/paypal-real-preflight-2026-10-19.json`, `build/test-runtime/paypal-real-api-progress-2026-10-19.json`. 비밀번호·토큰·개인정보·Secret은 기록하지 않았다.

## 10. 실제 신규 예약 신청 실패 — 2026-10-19 05:02 UTC

사용자가 테스트 예약 1건 및 테스트 관리자 2명 대상 푸시 가능성을 승인한 뒤 수행했다. DB는 `RIDERLOG_V2_DATA_TEST`, 지점·고객은 기존 승인 대상, 모델은 `NRTEST-WEB-MODEL-125`, 기간은 2026-11-18~2026-11-21, 배송 없음이다. 실제 availability 응답의 BASIC 가격·priceOptionId를 그대로 신청에 사용했다. 점검 종료 시 저장소 HEAD는 `88805bac0833cd8bfad4a40d223705aa7de310c7`로 확인됐으며, 앞 절의 과거 커밋과 구분한다. 실행 프로세스의 Git SHA를 응답으로 확인한 것은 아니다.

| 검사 | 기대 | 실제 | 판정 |
| --- | --- | --- | --- |
| 예약 가능 조회 | 200·신청 가능 | 200·canRequest=true | 통과 |
| 승인 고객 Firebase 인증 및 API 로그인 | 정상 인증·200 | 정상 인증·200 | 통과 |
| 판매자 미연결 신규 신청 | 200·REQUESTED | **409 DATA_CONFLICT** | **실패** |
| 신청 이후 DB | 성공 시 1건 | 해당 테스트 고객·지점·모델의 실행 이후 생성 건수 0 | 신청 저장되지 않음 |
| 고객 로그아웃 | 200 | 200 | 통과 |
| 중복 신청·생성 예약 상세 | 생성 성공 후 검사 | 최초 실패로 실행하지 않음 | 미검증 |

확인한 구조적 원인: 실제 `MSP_RESERVATION_HISTORY.changed_by`에 `MSP_ADMIN.admin_id`를 참조하는 `fk_res_history_admin` FK가 있다. 반면 `nadree_request`는 `reservation_history(..., "REQUESTED", user.uid_token)`을 호출하고 이 함수는 고객 UID를 `changed_by`에 그대로 넣는다. 승인 고객은 MSP_RENTAL_USER에 존재하지만 같은 ID의 MSP_ADMIN은 없다. 따라서 현재 코드의 고객 이력 쓰기가 실제 DB의 관리자 전용 FK를 만족하지 않는다. HTTP에서는 IntegrityError를 포괄적인 DATA_CONFLICT로 변환해 세부 DB 오류를 노출하지 않으므로, 실제 실패 문장의 MySQL 오류번호/제약명을 응답으로 확보한 것은 아니다. 판매자 미연결 오류는 아니며 코드와 실제 DB 계약 간 불일치가 확인됐다.

수정 범위 제안: 공유 DB의 기존 관리자 FK는 보존하고 고객 실행 이력은 `changed_by=NULL`과 기존 `details` JSON의 고객 실행자 정보로 기록하는 방식을 관련 계약과 대조한다. 고객 신청·취소 등 같은 헬퍼를 사용하는 경로 전체를 점검하고 실제 FK를 갖춘 격리 MySQL 회귀를 추가한 뒤 적용한다. 이번 요청은 테스트이므로 코드·스키마·서비스 설정은 변경하지 않았다. 고객 UID를 관리자에 삽입하거나 FK를 제거하는 우회는 하지 않는다.

실제 신청은 1회만 시도했고 실패 후 재시도하지 않았다. 예약이 커밋되지 않아 후속 커밋 이후 FCM dispatch 경로는 실행되지 않았다. 결제·취소·환불은 하지 않았다. 결과 기록은 `build/test-runtime/reservation-request-real-2026-10-19.json`이며 비밀값·개인정보는 저장하지 않았다.

## 11. 고객 예약 이력 보완·실제 재검증 완료 — 2026-10-19 05:09 UTC

사용자의 수정·재검증 승인으로 `app/availability.py`의 이력 헬퍼에 고객 실행 구분을 추가하고 `app/customer_rentals.py`의 신청·취소 두 경로에서 명시했다. 고객은 `changed_by=NULL`, 기존 `details` JSON에 `actorType=CUSTOMER`와 고객 실행자 ID를 기록한다. 관리자는 기존 `changed_by`를 유지한다. 신규 테이블·컬럼·마이그레이션·FK 변경·기존 데이터 수정은 없다. API 입력/응답과 판매자 연결 검사도 유지했다.

추가 회귀는 `tests/test_reservation_history_actor.py`에 작성했다. 실제 API로 판매자 미연결 신청→고객 취소 또는 관리자 거절을 수행하고 고객 실행자 보존과 관리자 FK 호환을 확인한다. SQLite에서는 관리자 FK와 같은 거절 조건의 트리거를, 격리 MySQL에서는 실제 관리자 FK를 사용한다.

- 관련 격리 회귀: 신규 이력 테스트·기존 고객 흐름·취소 정책 **20 passed, 2 skipped**. 두 건은 MySQL 환경 미제공에 따른 것으로 아래 별도 실행했다.
- 네트워크 비활성·새 빈 임시 MySQL 8.4.6: 실제 관리자 FK를 추가한 신규 테스트 **2 passed, 2 deselected**, 5.87초. 임시 서버 종료 완료. 첫 실행의 테스트 추가 테이블 정리 누락으로 두 번째 사례가 차단된 문제를 픽스처 정리로 보완한 뒤, 새 임시 DB에서 두 사례 모두 통과했다. 서비스 DB 스키마에는 이 작업을 실행하지 않았다.
- `git diff --check` 통과. 이 수정으로 전체 회귀를 다시 실행한 것은 아니므로 앞 절의 전체 회귀 개수와 합산하지 않는다.

API 반영: `nadree-api.service` 재시작 후 PID 2539433, active/running 및 공개 `/health/live` HTTP 200. 수정은 저장소 HEAD `88805bac0833cd8bfad4a40d223705aa7de310c7` 위 작업 트리에 있으며 별도 커밋하지 않았다.

실제 재검증 시각은 05:09:33~05:09:37 UTC다. 승인 고객·지점·모델 및 2026-11-18~2026-11-21 기간을 그대로 사용했고, 실제 availability의 BASIC 가격 옵션 **USD 75**를 신청했다.

| 검사 | 실제 결과 | 판정 |
| --- | --- | --- |
| 실제 예약 가능 조회·고객 Firebase 인증/API 로그인 | HTTP 200 | 통과 |
| 판매자 미연결 신규 예약 신청 | HTTP 200, REQUESTED, WAITING_APPROVAL | 통과 |
| 동일 요청 재전송 | HTTP 409 DUPLICATE_RENTAL_REQUEST | 통과 |
| 생성 예약 상세 조회 | HTTP 200 | 통과 |
| DB 저장·고객 이력 | REQUESTED 저장, changed_by NULL, details에 고객 유형·ID 보존 | 통과 |
| 관리자 알림함 | 해당 예약 RESERVATION_REQUESTED 1건 | 통과 |
| 결제 | 해당 예약 결제 레코드 0건, 외부 주문·캡처·환불 없음 | 승인/결제 미실행 |
| 고객 로그아웃 | HTTP 200 | 통과 |
| 최근 서비스 오류 | traceback·FCM dispatch 예외·채팅 동기화 예외 각각 0 | 관측 범위 통과 |

생성된 테스트 예약 ID는 `9393f505-e7f2-4332-991c-28371a6098fb`이며 REQUESTED로 보존했다. 자동 취소·삭제하지 않았다. 사용자 승인 범위의 테스트 관리자 2명 대상 알림/푸시 경로가 실행되는 신청을 수행했다. 알림함 저장과 dispatch 예외 없음은 확인했지만 실제 기기 수신·개별 FCM 전달 성공은 확인하지 않았으므로 통과로 표시하지 않는다. 실제 고객 취소는 이번에 실행하지 않았고 격리 테스트로 검증했다. 실제 결제는 판매자 연결·복귀 URL이 선행되어야 한다.

기록: `build/test-runtime/reservation-request-fixed-2026-10-19.json`. 비밀번호·토큰·고객 식별자 등 개인정보 원문은 결과 문서/로그에 남기지 않았으며, DB 이력의 고객 실행자 보존은 일치 여부만 확인했다.
