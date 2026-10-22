# 2026-10-22 예약 요청부터 Sandbox 결제까지 검증

## 현재 판정

**사용자 요청으로 결제 7번을 정상 관리자 취소 API에서 취소했고 Sandbox USD 90 전액 환불을 완료했다. 현재 예약 CANCELED·결제 REFUNDED·refundStatus=COMPLETED이며, PayPal 환불 상세도 COMPLETED다. 01:47:13~01:47:18 UTC 실제 고객 인증 API에서 진행 목록 totalCount=0·items=[]와 종료 목록의 취소/환불 이력 보존을 확인했다.** 앞서 서비스 반영 후 실제 캡처 1건·PG 조회 복구에 따른 PAID/DONE까지 검증한 뒤 이 정리 요청을 수행했다. 실제 서명 웹훅 수신 성공은 계속 미검증이며, 아래의 PAID·승인 대기·422/415·미반영 기록은 각 시각의 이력이다.

## 01:46~01:47 UTC 사용자 요청 — 관리자 취소·전액 환불·진행 건수 0 확인

사용자는 현재 결제된 테스트 예약을 관리자 취소·환불하고 진행 중인 건이 없도록 정리하도록 명시적으로 요청했다. 실행 대상은 기존 승인된 테스트 고객의 **결제 7번·예약 `35b12620-7ae0-4bfd-b23f-cd075229ea7b` 한 건**이다. 실제 DB `RIDERLOG_V2_DATA_TEST`·PayPal SANDBOX·기존 테스트 지점/모델·동일 고객을 재확인했다. 사전 조회에서 다른 진행 예약이나 활성 렌탈 계약은 없었고, 7번만 APPROVED/PAID·USD 90·기존 환불 없음이었다. PayPal 판매자·금액·완료 캡처를 직접 재검증한 뒤 변경 전 원본을 0700 디렉터리의 0600 파일로 백업했다.

| 실제 검사 | 기대 | 실제 | 판정 |
| --- | --- | --- | --- |
| 테스트 대표 로그인 → 관리자 CANCEL → 로그아웃 | 승인된 정상 API로 취소 | 모두 HTTP 200; CANCEL 1회·BRANCH_FAULT·ADMIN_REFUND_100_PERCENT·환불 요청액 USD 90 | 통과 |
| 기존 서버 환불 처리 | 관리자 취소 시 100% 환불 | 서버 환불 시도 1회, SQL REFUNDED·환불액 90.00·refundStatus=COMPLETED·환불 ID 있음 | 통과 |
| 실제 PayPal 환불 상세 GET | 같은 환불의 완료·금액 확인 | HTTP 200·COMPLETED·USD 90.00, Debug ID `f1848698fa6db` | 통과 |
| 취소·재고 반영 | 예약 취소·차량 해제 | CANCELED·RELEASED·assigned_vehicle_id 없음 | 통과 |
| 취소 주체·환불률·기록 보존 | ADMIN·100%·기존 결제/이력 보존 | 기대와 일치; 주문/캡처/판매자/금액/최초 요청 시각/paid_at·기존 이력 보존 | 통과 |
| 다른 결제·진행 건수 | 다른 결제 변경 없음·동일 고객 진행 0 | 다른 결제 행 불변, 진행 예약 0·활성 계약 0 | 통과 |
| 실제 고객 Firebase 인증 → 백엔드 로그인 → 결제 상태 | 환불 완료·재캡처 불가 | 모두 HTTP 200, REFUNDED/DONE/canCapture=false·refundedAmount=90·refundStatus=COMPLETED | 통과 |
| 고객 예약 상세 | 취소·환불 내역 | HTTP 200, item.reservationStatus=CANCELED·item.payment.paymentStatus=REFUNDED·refundStatus=COMPLETED | 통과 |
| 고객 `/ongoing` | 진행 내역 없음 | HTTP 200·totalCount=0·items=[] | 통과 |
| 고객 `/completed` | 취소 이력 유지 | HTTP 200, 해당 예약의 CANCELED/REFUNDED 내역 존재 | 통과 |
| 고객 로그아웃·서비스 헬스 | 정상 종료·서비스 유지 | 모두 HTTP 200, PID 326499 유지 | 통과 |

최초 관리자 취소 응답의 refundStatus=REQUESTED는 환불 요청 접수 상태였다. 이후 기존 백그라운드 환불 처리·DB 재조회·PayPal GET으로 COMPLETED를 확인했으며 요청 접수만으로 완료 처리하지 않았다. 이 환불은 실제 Sandbox API 처리이며 모의 테스트가 아니다. 추가 캡처·신규 주문·전체 결제/환불 작업 실행은 없었고 Live API·설정/스키마·서비스 재시작·Firebase 배포도 실행하지 않았다. 취소 경로는 별도 결제/예약 의사결정 FCM을 발송하는 경로가 아니며 푸시 발송 테스트도 하지 않았다.

프론트는 현재 7번을 결제 진행 대상으로 사용하지 않는다. 취소·환불 내역으로 표시하고 진행 목록은 비어 있어야 한다. 예약 상세의 기존 `paymentAvailability`는 환불된 이력에서도 PAID로 나올 수 있으므로, 취소/환불 표시는 `reservationStatus`와 중첩 `payment.paymentStatus`·`payment.refundStatus`를 기준으로 한다. 실제 진행 여부는 `/ongoing` 0건으로 확인했다. 웹훅 수신/자동 정산 검증의 기존 제한은 이번 환불 성공과 구분한다.

근거: `build/test-runtime/payment-7-admin-cancel-refund-2026-10-22/result.json`, `customer-api-verification-result.json`, `before.private.json`(원본 백업). 마지막 두 파일도 같은 접근 제한 디렉터리 아래에 있다. 코드 추가 구현·새 자동 회귀 실행 없이 기존 배포 API와 실제 Sandbox 결과를 검증한 작업이다.

## 01:22~01:40 UTC 서비스 적용·캡처·조회 복구 실제 결과

사용자의 서비스 반영·테스트 요청 범위에서 `nadree-api.service`를 1회 재시작했다. 실행 경로 `/srv/nadree-api`, 사용자 ec2-user, 가상환경 `.venv`, PID는 10470에서 326499로 변경됐고 active/running이다. 저장소 HEAD는 `14ec67b1a513ca0c405bfa5f7a1dbbd3246dabae`이며, 이번 수정은 해당 HEAD 위의 미커밋 작업 트리로 반영했다. HEAD만으로 로드된 코드를 단정하지 않고 새 프로세스와 실제 경로 응답을 함께 확인했다.

| 실제 검사 | 기대 | 실제 | 판정 |
| --- | --- | --- | --- |
| 01:21:57~01:22:02 서비스 재시작 | active/running·헬스 정상 | 재시작 1회, local live/ready·public live 모두 HTTP 200 | 통과 |
| 공개 결제 복귀·취소 복귀·OpenAPI | 고정 GET이 숫자 ID 검증을 거치지 않음 | 두 복귀 모두 HTTP 200 HTML, OpenAPI 200 및 신규 경로 존재 | 통과 |
| 실행 프로세스와 설정 파일 대조 | Test DB·Sandbox·자격 설정 일치 | DB URL·환경·Client ID/Secret 일치 여부만 확인, 모두 true | 통과; 비밀값 미기록 |
| 같은 7번의 캡처 재시도 사전 검사 | APPROVED·기존 캡처 없음·같은 요청 허용 | PG APPROVED·0건, API RETRY_CAPTURE/canCapture=true | 통과 |
| 01:23 실제 POST `/payment/capture` | HTTP 200·PG 캡처 완료 | HTTP 200, PayPal 주문/캡처 COMPLETED·USD 90·캡처 1건 | 통과 |
| 캡처 식별자·재시도 보호 | 원래 주문·요청 시각 보존 | 최초 capture_requested_at=01:08:19 UTC 유지, 같은 `nadree-capture-7`·주문, SQL/PG 캡처 ID 일치 | 통과 |
| 캡처 직후 서버 최종 반영 | 검증된 정산 근거로 PAID | SQL PENDING·캡처 ID 있음·paid_at 없음, API WAIT | 웹훅 반영 지연 확인 |
| 현재 앱 웹훅 설정·PG 이벤트 조회 | 기존 콜백·완료 구독·이벤트 확인 | 콜백 일치·기존 15개 구독 유지·필수 2개 누락 없음, PG 완료 이벤트 1개 존재 | 조회 통과; 수신 성공을 뜻하지 않음 |
| 01:29:54 완료 이벤트 지정 재전송 1회 | 기존 웹훅으로 재전송 접수 | HTTP 202, Debug ID `ca4e4bbdffb1b`; 01:36까지 해당 수신/DB 이벤트 없음 | 접수 통과·실제 전달 미확인 |
| 공개 웹훅에 서명 없는 진단 POST | 인증 없는 이벤트 거절 | HTTP 400, 결제 반영 없음 | 보안 차단 통과; 실제 PayPal 전송 아님 |
| 01:39 조회 복구 사전 검사 | 판매자·금액·캡처·기한·예약 검증 | 모두 일치, 정상 기한 내 캡처·타 결제 시도/취소/환불 없음 | 통과 |
| 01:39:29~01:39:31 해당 7번만 기존 복구 처리 | PG 조회 증거로 정상 정산 | SQL PAID·paid_at 있음, 기존 이벤트 테이블 API_QUERY/PROCESSED, 내부 알림함 1건 추가 | 통과; 실제 서명 웹훅과 구분 |
| 01:40:55~01:40:59 실제 고객 인증 조회 | 결제 PAID/DONE·예약 상세 완료 | 로그인·결제 상태·예약 상세·헬스·로그아웃 모두 200, PAID/DONE/canCapture=false, `item.payment.paymentStatus=PAID`·`item.paymentAvailability=PAID` | 통과 |

복구는 `app.payment_recovery`와 같은 기존 `event_client.snapshot → save_event(API_QUERY) → process_event` 흐름을 **7번에만** 적용했다. 전체 결제를 순회하는 `reconcile_payments()`나 결제 타이머를 실행하지 않았다. 접근 제한된 변경 전 백업을 먼저 생성했으며 다른 결제 행·해당 예약 행·원래 주문/요청 시각·판매자/금액 보존을 대조했다. 추가 캡처·주문·환불·FCM 발송은 0회다. 기존 복구 로직에 따른 테스트 지점 내부 결제 알림함만 1건 추가됐다. PAID 직접 SQL 덮어쓰기나 서명 웹훅 위조, 인증 검사 완화는 없다.

01:36 읽기 전용 감사에서 PayPal 주문 GET·캡처 GET은 모두 HTTP 200/COMPLETED이고 서버 예외·공급자 오류는 없었다. PayPal 이벤트 상세 API는 이번 응답에 전송 상태/시도별 HTTP 결과를 제공하지 않아 실제 배달 실패 사유를 확정하지 못했다. 콘솔 자료는 이 원인 확인을 위한 보조 자료이며, **앱 화면 없이도 PG 상태 조회와 백엔드 API의 최종 결제 완료는 검증 가능하다.** 현재 웹훅 전달 누락 원인 및 자동 복구 운영 등록은 후속 확인 사항이다. 재전송 202를 수신 성공으로 표시하지 않는다.

최종 공개 결제 API 핵심 응답은 다음과 같다. `paypalOrderStatus=null`은 이 PAID 조회에서 PayPal을 다시 호출하지 않았다는 뜻이며, 별도 PG 직접 조회에서는 COMPLETED를 확인했다.

```json
{
  "paymentId": 7,
  "paymentStatus": "PAID",
  "paypalOrderStatus": null,
  "nextAction": "DONE",
  "canCapture": false,
  "approvalUrl": null,
  "refundStatus": "NONE",
  "currency": "USD",
  "totalPrice": 90
}
```

01:40 당시 프론트는 7번을 결제 완료로 표시할 수 있었다. 이후 사용자의 정리 요청으로 위 최신 절과 같이 취소·전액 환불했으므로 현재는 취소/환불 이력으로 표시한다. 추가 capture나 새 order 요청은 하지 않는다. 결제 완료만으로 예약 인계·렌탈 시작을 수행하지 않았다. 브라우저 복귀 페이지는 중립 안내이며 자동 캡처나 앱 열기를 수행하지 않는다. App Check·실기기 복귀·푸시 수신은 이번 결과에 포함하지 않는다.

근거: `build/test-runtime/payment-return-capture-fix-service-result.json`, `reservation-payment-flow-2026-10-22/capture-after-fix-result.json`, `payment-7-after-deploy-audit.json`, `payment-7-webhook-resend-result.json`, `payment-7-recovery-preflight-readonly-result.json`, `reservation-payment-flow-2026-10-22/scoped-api-query-recovery-result.json`, `reservation-payment-flow-2026-10-22/paid-api-verification-final-result.json`. 앞의 모두 `build/test-runtime/` 아래 접근 제한 자료다. 최초 API 검증 스크립트는 예약 상세의 중첩 필드를 최상위로 잘못 읽어 중단했으나, 실제 응답 계약에 맞춰 수정 후 재검증했다. 이는 제품 API 실패로 계산하지 않으며 최초 결과도 보존했다.

## 코드 보완 완료 — 이후 위 서비스 반영·실연동 검증 완료

2026-10-22 사용자 요청으로 다음을 수정했다. 아래 코드 작성 단계에는 DB 변경·PayPal 요청·서비스 재시작·환경 설정 변경이 없었으며, 후속 적용·실제 요청은 위 최신 절을 따른다.

- `app/customer_rentals.py`: 고정 GET `/api/v1/nadree/rental/payment/return`을 숫자 결제 ID 경로보다 먼저 등록했다. 승인/취소 후 브라우저 복귀에 HTTP 200 HTML 안내를 반환한다. 인증·DB·PG 호출 없이 안내만 하며, 쿼리로 승인/PAID를 확정하거나 자동 캡처하지 않는다. token/PayerID를 본문에 반영하지 않으며 캐시 금지·Referrer-Policy를 지정했다. 기존 숫자 결제 조회의 고객 인증은 유지한다.
- `app/paypal.py`: `capture_order`가 빈 JSON 본문을 전송해 Content-Type: application/json을 보내도록 수정했다. 동일 주문 ID·PayPal-Request-Id·판매자 assertion·OAuth 요청 형식은 보존했다. DB 상태·최초 캡처 시각·재시도 기한을 변경하지 않았다.
- `tests/test_payment_return_url.py`, `tests/test_paypal_capture_request.py`: 신규 9개 회귀를 추가했다. 승인/취소/조작 쿼리 복귀, DB 없이 안내 제공, 결제 조회 인증 유지, 모의 Sandbox/Live HTTP JSON 요청, 실제 API 코드의 캡처 결과 저장 및 중복 캡처 방지를 검사한다. Live 모드는 HTTP 모의 전송만 사용하며 실제 Live API는 호출하지 않는다.
- `tests/test_foundation.py`: 고정 공개 HTML 경로 추가를 OpenAPI 계약 검사에 반영했다. 기존 고객 인증이나 private API의 보안 조건을 완화하지 않았다.

수정 후 관련 회귀는 **63 passed, 0 failed, 0 skipped(17.17초)**다. OpenAPI 경로 계약 검사 갱신까지 포함한 전체 격리 회귀도 **386 passed, 12 skipped, 0 failed(93.28초)**로 완료했다. 건너뜀은 별도 Firestore 4개·MySQL 8개이며 실제 외부 서비스를 테스트하지 않았다. 로그/JUnit은 `build/test-runtime/payment-return-capture-fix-full-regression-2026-10-22.log`와 같은 이름의 `.xml`이다. 기존 build 폴더의 “현재 결함이 재현되어야 통과”하는 진단 스크립트는 수정 전 증거이며 수정 후 회귀로 재사용하지 않는다.

코드 작성 후 사용자 승인으로 서비스를 재시작하고 최신 PG 상태·기존 요청 시각/키·허용 조건을 재확인해 위 실제 캡처 재시도와 조회 복구를 완료했다. 실제 422/415 해소는 공개 복귀 GET 200과 capture POST 200으로 확인했다.

## 01:09 UTC 후속 실연동 — 확인된 실패 2건

사용자가 PayPal 승인 후 `INVALID_INPUT`을 보고해 최근 실제 요청 경로와 결제 7번을 읽기 전용 대조했다. 01:06:48 UTC에 PayPal 주문 GET 200/APPROVED·캡처 0건, 구매자 정보 있음·**구매자와 판매자 ID는 다름**을 확인했다. 승인 미완료 대기는 이 시점에 해소됐다.

| 실제 검사 | 기대 | 실제 | 판정 |
| --- | --- | --- | --- |
| 01:05:35 승인 후 GET `/api/v1/nadree/rental/payment/return` | 프론트 복귀 처리 또는 유효한 착지 응답 | 422 INVALID_INPUT, 쿼리 이름은 token/PayerID | 실패: 복귀 처리 |
| 원인 코드·격리 재현 | 고정 return 경로가 결제 ID 경로와 구분 | 고정 라우트 없음. `/payment/{paymentId}`의 int 검증이 문자열 return을 거절. 동일 422 재현 | 결함 확인 |
| 01:08:16 캡처 전 본인 상태 조회 | APPROVED/CAPTURE/canCapture=true | HTTP 200, SQL CREATED·PayPal APPROVED·CAPTURE·true, approvalUrl null | 통과 |
| 01:08:19 실제 capture API 1회 | PayPal 캡처 결과와 ID 반환 | HTTP 500 PAYPAL_SERVICE_UNAVAILABLE | 실패: 원격 요청 |
| 01:08:20 공급자 진단 | JSON 미디어 타입으로 캡처 | PayPal **415 UNSUPPORTED_MEDIA_TYPE**, Debug ID `f8502753f2396` | 실패 원인 확인 |
| 실제 요청 코드·격리 HTTP 대조 | capture POST에 application/json 지정 | 현재 `PayPalClient.capture_order`가 JSON 본문/Content-Type 없이 호출. 모의 전송에서도 헤더 없음 확인 | 결함 확인 |
| JSON 헤더만 추가한 검토용 모의 요청 | 같은 주문·키로 JSON 미디어 타입 전달 | 모의 공급자 201·COMPLETED, 동일 키 보존 | 수정 방향 검증; 실제 수정/PG 성공 아님 |
| 01:09:19 읽기 전용 PG·SQL 재조회 | 성공/실패를 실제 상태로 구분 | PG APPROVED·캡처 0건, SQL PENDING·capture_requested_at=01:08:19·캡처 ID/paid_at 없음 | 결제 성공 확인 안 됨 |

캡처 시도는 기존 사용자의 전체 흐름 검증 및 구매자 승인 후 **1회 캡처 승인** 범위로 수행했다. 승인 전 차단 검사 1회와 구분해, 이 후속 실행의 실제 capture API 호출은 1회다. 재시도·새 주문·환불·결제 상태 초기화는 하지 않았다. 구매자 승인 자체는 성공했으며 복귀 페이지의 422가 PayPal 구매자 승인을 되돌린 것은 아니다. 5번 최초 실패는 당시 공급자 상세 로그가 없어 이번 7번의 415와 같은 원인이라고 소급 확정하지 않는다.

격리 결함 재현 2개는 **2 passed, 0 failed(2.57초)**로 예상한 두 실패 모드를 확인했다. “2개 통과”는 제품 수정 완료가 아니다. [PayPal 공식 캡처 예제](https://developer.paypal.com/whats-an-order/)도 캡처 POST에 Content-Type: application/json 및 빈 JSON 본문을 제시한다. 이 부분은 소스와 공급자 실제 오류, 격리 HTTP 요청을 함께 근거로 판단했다.

### 진단 당시 최소 수정안 — 후속 코드 보완·서비스 반영 완료

1. 고객 결제 복귀 고정 GET `/payment/return`을 숫자 결제 ID GET보다 먼저 등록한다. 쿼리만으로 승인/PAID를 선언하거나 GET에서 캡처하지 않는다. 앱은 기존 계약대로 복귀 URL을 가로채 본인 결제 상태를 조회하고 명시적으로 capture를 호출한다. 브라우저 직접 복귀에는 오류 대신 중립 안내를 반환할 수 있다.
2. `app/paypal.py:PayPalClient.capture_order`에 JSON 미디어 타입을 추가한다. JSON 빈 본문 방식도 가능하다. 기존 주문 ID·판매자 assertion·같은 paymentId/`nadree-capture-7`·원래 capture_requested_at·5시간 제한은 유지한다.
3. 해당 회귀를 정식 테스트에 추가하고 서비스 반영은 별도 승인 범위로 진행한다. 실제 재시도는 같은 7번을 최신 PG 상태와 대조한 뒤 승인 범위에서만 수행한다. 현재 최초 요청 기준 기한은 **2026-10-22 06:08:19 UTC**이며, 기한 경과를 시각 초기화나 새 키로 우회하지 않는다. 그 전에라도 코드 보완 없이 추가 캡처를 호출하지 않는다.

이 진단 시점에는 애플리케이션 코드 변경·재시작·설정 변경을 하지 않았다. 이후 사용자 수정 요청에 따른 코드 보완은 위 최신 절을 따른다. 근거: `build/test-runtime/payment-7-invalid-input-readonly-result.json`, 접근 제한된 `reservation-payment-flow-2026-10-22/capture-once-result.json`, `test_payment_return_route_reproduction.py`, `test_capture_content_type_reproduction.py`.

## 대상·시각·실행 조건

- 사용자 승인: 결제 5번 소유 테스트 고객의 기존 예약 전체 취소와 예약부터 결제까지 실제 테스트. 이전 승인된 동일 고객·테스트 대표·지점·차량만 사용했다.
- 실제 DB: `RIDERLOG_V2_DATA_TEST`; Sandbox API만 사용했다. 고객 UID·계정 정보·인증 토큰·비밀번호·Secret 원문은 결과에 기록하지 않았다.
- 지점 `00000000-0000-4000-8000-000000000101`, 모델 `NRTEST-WEB-MODEL-125`, 2026-10-31~2026-11-02, PREMIUM·픽업·USD 90.
- 최초 실제 API 실행: 2026-10-22 00:43:52~00:44:08 UTC. 구매자 승인 사전 조회: 00:45:51, 00:46:36 UTC. 후속 서비스 적용·캡처·정산 검증은 01:21:57~01:40:59 UTC.
- 검증 시 저장소 HEAD `14ec67b1a513ca0c405bfa5f7a1dbbd3246dabae`; 최초 서비스 PID 10470, 반영 후 326499. 프로세스가 로드한 커밋을 저장소 HEAD만으로 단정하지 않는다.
- 최초 API 실행 단계에는 코드/설정·DB 스키마·Firebase 배포·재시작·기존 시드 재실행이 없었다. 이후 사용자 승인으로 코드 반영·재시작·테스트 결제 정산을 수행했다. 환경 설정·스키마·Firebase·타이머 변경과 기존 기록 삭제는 없다.
- AGENTS.md와 README, 최신 인수서·실제 라우터를 확인했다. AGENTS.md가 참조하는 부모 `rental-project-master.md`, `rental-api-review-decisions.md`는 현재 서버 경로와 `/srv` 검색에서 찾지 못했다. 이번에는 신규 기능을 구현하지 않고 기존 API를 검증했다.

## 기존 예약 취소 결과

결제 5번과 6번의 연결 예약은 이미 CANCELED였다. 추가로 같은 고객의 REQUESTED 예약 `c5961125-e8f0-46e3-82e4-002a30470cfa` 1건이 있었고, 연결 결제·렌탈 계약은 없었다. 접근 제한 백업 후 고객 정상 취소 API로 해당 예약을 취소했다.

- 취소 HTTP 200, CANCELED, refundStatus=NOT_REQUIRED·환불 요청액 0.
- 반복 취소는 409 RESERVATION_STATE_INVALID.
- 신규 예약 생성 **직전** 고객 ongoing 조회는 HTTP 200, totalCount=0·items=[]였다.
- 이 최초 정리 후 새 테스트 예약을 생성해 한동안 활성 예약 1건이 있었으며, 이후 01:46 관리자 취소·전액 환불까지 마친 **현재 활성 예약은 0건**이다. 기존 기록은 모두 보존했다.

## 실제 API 응답 검사 — 30개 통과

다음 표는 실제 서비스 호출 결과이며, 입력 오류·중복·미승인 차단은 기대 오류를 반환한 경우 통과로 표시했다. 응답 본문 전체를 저장하지 않고 상태·오류 코드·필요한 비식별 업무 필드만 검증했다.

| 검사 | 기대 | 실제 | 판정 |
| --- | --- | --- | --- |
| Firebase 테스트 고객 인증 → 백엔드 로그인 → refresh | 200, access/refresh 발급·갱신 | 모두 200, 두 토큰 발급 확인 | 통과 |
| 승인된 테스트 대표 로그인·양측 로그아웃 | 200 | 모두 200 | 통과 |
| 기존 고객 예약 취소·반복 취소 | 200 취소 / 409 상태 오류 | 기대와 일치 | 통과 |
| 정리 후 ongoing·completed | 200, 진행 건수 0 | 200, ongoing 0건 | 통과 |
| 잘못된 날짜·예약 필수값 누락 | 422 INVALID_INPUT | 기대와 일치 | 통과 |
| 인증 누락·잘못된 고객 토큰 | 401 INVALID_NADRI_USER_TOKEN | 기대와 일치 | 통과 |
| 대상 차량 가용성·PREMIUM 견적 | 200, 요청 가능·USD 90 | 기대와 일치 | 통과 |
| 견적과 다른 금액 91 요청 | 409 PRICE_QUOTE_MISMATCH | 기대와 일치, 예약 생성 안 됨 | 통과 |
| 새 예약 요청·즉시 중복 요청 | 200 REQUESTED / 409 DUPLICATE_RENTAL_REQUEST | 기대와 일치 | 통과 |
| 관리자 승인 전 주문 요청 | 409 RESERVATION_NOT_APPROVED_FOR_PAYMENT | 기대와 일치 | 통과 |
| 고객 예약 상세·관리자 예약 조회 | 승인 전·후 각각 200 | 모두 200 | 통과 |
| 관리자 승인·반복 승인 | 200 APPROVED / 409 RESERVATION_STATE_INVALID | 기대와 일치 | 통과 |
| Sandbox 주문 생성 | 200, CREATED·승인 URL 있음 | 200, 결제 7번, PAYER_ACTION_REQUIRED·APPROVE | 통과 |
| 같은 예약 주문 API 재호출 | 동일 paymentId·주문 재사용 | 같은 7번·같은 주문, 추가 결제 시도 없음 | 통과 |
| 본인 결제 상태 조회 | 200, 공급자 상태·승인 URL 제공 | PAYER_ACTION_REQUIRED·APPROVE·canCapture=false·URL 있음 | 통과 |
| 구매자 승인 전 capture API | 409 PAYMENT_STATE_INVALID, 캡처 체크포인트 미생성 | 기대와 일치, SQL CREATED 유지·capture_requested_at 없음 | 통과 |
| 존재하지 않는 결제 ID 조회 | 404 PAYMENT_NOT_FOUND | 기대와 일치 | 통과 |

새 예약은 `35b12620-7ae0-4bfd-b23f-cd075229ea7b`, 결제는 **7번**이다. **00:44 당시** SQL 재조회에서 이 예약만 활성 APPROVED이고, 해당 예약의 결제 시도는 7번 1건뿐이었다. 그 시점에는 캡처 ID·paid_at·capture_requested_at이 없었고 실제 서버의 미승인 capture API 1회는 승인 전 차단 검사였다. 이후 01:08 캡처 실패와 수정 후 01:23 성공·01:39 정산 결과는 위 최신 절을 따른다.

## 00:45~00:48 초기 구매자 승인 대기 이력

사용자 답변과 별개로 PayPal에서 APPROVED와 기존 캡처 없음을 직접 확인한 뒤 실제 캡처를 1회 수행하도록 준비했다. 두 번의 사전 조회 모두 다음 결과로 멈췄다.

| 시각 UTC | OAuth | 기존 주문 GET | 주문 상태 | 캡처 건수 | 실제 capture API/PayPal capture |
| --- | --- | --- | --- | --- | --- |
| 00:45:51 | 200, Debug ID `ca4e47b505e88` | 200, Debug ID `ca4e47b553bb3` | PAYER_ACTION_REQUIRED | 0 | 0회/0회 |
| 00:46:36 | 200, Debug ID `ca4e47c6a1862` | 200, Debug ID `ca4e47c6f0ef5` | PAYER_ACTION_REQUIRED | 0 | 0회/0회 |

00:48:46 UTC 조회에서도 PAYER_ACTION_REQUIRED였고 구매자 식별정보는 응답에 없었다. **구매자와 판매자가 같은 계정이라고 확인한 것은 아니다.** 서버 설정의 플랫폼 ID와 결제 7번의 판매자 ID는 서로 다름을 비밀값 없이 대조했다. 사용자가 보고 있는 PayPal 화면·로그인 계정은 서버에서 확인할 수 없어 마지막 화면 문구와 Sandbox Personal 여부를 요청했다.

PayPal Sandbox에서 Personal은 구매자, Business는 판매자 역할이다. 하나의 Developer 로그인에서 여러 Sandbox 계정을 관리할 수 있지만, 결제 승인에는 판매자와 다른 구매자 계정을 사용해야 한다. [공식 Sandbox 계정 안내](https://developer.paypal.com/sandbox-testing/accounts), [공식 본인 결제 오류 설명](https://developer.paypal.com/api/errors/cannot-pay-self). 플랫폼·판매자 역할 중복을 현재 대기 상태의 원인으로 단정하지 않는다.

당시 계획은 실제 구매자 APPROVED 확인 → 같은 결제 7번 capture API 1회 → PayPal 캡처·금액·판매자 대조 → 검증된 웹훅/복구에 따른 SQL PAID·paid_at 및 상태 API 확인이었다. 이후 01:08에 캡처 1회를 수행했고 위 최신 절의 415 오류를 확인했다. 사용자 답변이나 단순 복귀 URL 이동만으로 승인/결제 완료를 처리하지 않으며 새 주문·키·PENDING 초기화·인증 완화로 우회하지 않는다.

## 수정 전 자동 회귀 — 격리 환경에서 377 passed / 12 skipped

실제 서버 환경변수와 Firebase 자격증명/에뮬레이터 변수를 제거하고 `/tmp`에서 전체 `tests/`를 실행했다. SQLite와 모의 외부 서비스를 사용했고 실제 DB·PG를 테스트 대상으로 사용하지 않았다.

- 결과: **377 passed, 12 skipped, 0 failed, 0 errors**, pytest 93.49초·실행 프로세스 exit 0.
- 건너뜀: Firestore 에뮬레이터 4건, 별도 폐기 가능한 MySQL DB가 필요한 동시성 6건과 관리자 FK 회귀 2건. 해당 환경을 이번 실행에 제공하지 않아 건너뛰었으며 과거 결과를 합산하지 않았다.
- 예약·가격·배송·중복·승인·취소·결제·환불·인증/권한·PayPal 진단 등이 포함되지만, 모의 캡처/환불 통과를 실제 PayPal 결제 완료로 해석하지 않는다.
- FastAPI/Starlette 테스트 클라이언트 관련 DeprecationWarning 2건이 있었고 테스트 실패는 없었다.

로그와 JUnit: `build/test-runtime/reservation-payment-full-regression-2026-10-22.log`, 같은 이름의 `.xml`.

## 프론트 확인 사항·정정

00:44 주문 생성 당시 새 7번의 실제 상태 응답 핵심 필드는 다음과 같다. 승인 URL 원문은 문서에 복사하지 않았다. 현재 상태는 최신 절의 **PAID/DONE/canCapture=false**이며 이 초기 예시로 덮어 해석하지 않는다.

```json
{
  "paymentId": 7,
  "paymentStatus": "CREATED",
  "paypalOrderStatus": "PAYER_ACTION_REQUIRED",
  "nextAction": "APPROVE",
  "canCapture": false,
  "approvalUrl": "<현재 주문의 Sandbox 구매자 승인 URL>"
}
```

1. 관리자 승인과 PayPal 구매자 승인을 구분한다. order 응답의 APPROVE/approvalUrl로 승인 화면을 연다.
2. 승인 복귀 후 상태를 조회하고 CAPTURE/canCapture=true일 때 같은 paymentId로 명시적으로 capture를 호출한다.
3. **현재 코드는 capture 응답이 성공하더라도 우선 PENDING·캡처 ID를 기록할 수 있다.** 최종 PAID·paid_at 반영은 검증된 PayPal 웹훅 또는 PG 조회 복구의 `process_event`가 수행한다. 앞선 대화에서 capture 호출이 즉시 PAID까지 반영한다고 설명한 부분은 이 실제 코드 기준으로 정정했다.
4. PENDING/WAIT이면 상태를 조회한다. 캡처 ID가 있는 WAIT는 최종 반영을 기다리는 상태일 수 있으며, 과거 6번의 주문 조회 404로 발생한 CREATED/WAIT와 구분해야 한다.
5. 새 7번에는 실제 승인 URL·공급자 상태가 반환됐다. 과거 5·6번과 이전 승인 링크는 취소 이력이므로 사용하지 않는다.

## 실패·미검증과 후속 작업

- 초기 실제 승인 복귀 422와 캡처 415/백엔드 500은 코드 수정·서비스 반영 후 각각 실제 HTTP 200으로 해소했다. 초기 API 검사 30개와 신규 9개 포함 전체 격리 회귀 386개 통과를 실제 캡처 성공과 구분해 기록했다.
- 구매자 실제 승인·PayPal Sandbox 캡처 1건·조회 복구에 따른 최종 PAID·실제 상태 API DONE·예약 상세 완료·내부 결제 알림 저장은 확인했다. **실제 서명 웹훅 수신·자동 정산은 미검증**이며 누락 원인을 확정하지 못했다. PG 조회 복구 성공으로 이 항목을 통과 처리하지 않는다.
- API 조회 복구는 기존 로직을 7번에만 한 번 수행했다. 전체 복구 타이머 설치/활성화는 하지 않았으며, 추후 운영 등록 전에 기존 미정산·환불 대상과 외부 영향을 별도로 검토해야 한다.
- 실제 앱 화면·실기기 복귀·App Check·기기 푸시 수신·외부 지점 계정 접근: 이번 실제 실행 범위에서 미검증. 모의 권한 검증과 구분한다.
- 최초 검증에서는 실제 환불을 실행하지 않았고, 후속 사용자 명시 요청으로 7번의 실제 Sandbox 관리자 취소·전액 환불을 완료했다. 예약 인계/반납·실제 계정 삭제·Live 결제는 실행하지 않았다.
- 기존에 진단한 주문 404가 WAIT로 뭉개지는 응답, 자동 작업 이력 FK, 탈퇴 부분 실패는 이번 검증에서 수정하지 않았다. 관련 이전 진단을 전체 회귀 통과만으로 해소된 것으로 표시하지 않는다.

접근 제한 자료는 `build/test-runtime/reservation-payment-flow-2026-10-22/`(0700)에 보관했다. 변경 전 `before.private.json`, 새 승인 자료 `buyer-approval.private.json`, 실제 API 메타데이터 `result.json`, 최초 캡처 실패 기록 `capture-once-result.json`, 재시도 전 `before-capture-retry.private.json`, 조회 복구 전 `before-scoped-api-query-recovery.private.json`은 각각 0600이다. 인증 토큰·비밀번호·Secret을 파일이나 문서에 저장하지 않았다.
