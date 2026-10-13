# PayPal Sandbox 연결·API 검증 결과

사용자 요청: 현재 서버의 테스트용 env 설정으로 PayPal 관련 API를 검증한다. 수행일 2026-10-13 UTC. **인증·주문 생성·조회 연결은 성공했지만 캡처·환불까지 정상 작동한다고 판정하지 않는다.** Merchant ID 확인은 사용자 지시에 따라 제외했으며 실제 구매자 승인 상태가 아직 CREATED이므로 캡처·환불 성공은 미검증이다.

## 실제 PayPal 연결 확인

서버 Settings가 SANDBOX임을 확인하고 `https://api-m.sandbox.paypal.com`만 사용했다. Client ID/Secret, OAuth access token, env 원문, 비밀번호는 출력하거나 이 문서에 기록하지 않았다. LIVE 접속·키 변경은 하지 않았다.

| 항목 | 실제 결과 |
| --- | --- |
| OAuth client_credentials | HTTP 200, access token 발급 확인(값 비노출) |
| 설정된 웹훅 등록 조회 | HTTP 200, 설정 ID가 현재 앱 목록에 존재 |
| 웹훅 주소 | https://na-dree.com/nadreego/paypal/webhook와 일치 |
| 백엔드 주문 생성 API → 실제 Sandbox | HTTP 200, USD 1.00 주문 1건 생성 |
| PayPal 주문 직접 조회 | 성공, 통화 USD·금액 1.00 확인 |
| Merchant ID | 실제 주문 판매자와 설정 값 불일치. 사용자 요청으로 정상 검증 범위에서 제외, 검사 해제/임의 설정 변경 안 함 |
| 구매자 승인·캡처 | 승인 완료 답변 뒤 두 번 확인하고 최종 조회까지 했으나 PayPal 상태는 CREATED, capture 없음. 실제 캡처 요청은 보내지 않음 |
| 실제 환불 | 캡처가 없어 요청하지 않음 |

사용자에게 Sandbox 구매자 승인 링크를 전달했지만 PayPal API에서는 APPROVED로 바뀌지 않았다. 사용자 답변만으로 승인 성공을 표시하지 않는다. 보존된 미결제 주문을 이후 승인 상태부터 재확인하여 이어서 사용할 수 있다. 승인 완료 화면을 거쳐 PayPal API가 APPROVED를 반환해야 캡처 검증이 가능하다. 주문 만료 시 임의로 재생성하지 말고 상태와 기존 시도를 먼저 확인한다.

## 백엔드 API 검증 방식과 결과

정상 주문 생성·재사용·상태 조회는 **현재 코드의 FastAPI TestClient + 별도 SQLite DB + 실제 서버의 PayPal Sandbox 설정**으로 실행했다. 공유 RIDERLOG_V2_DATA_TEST의 기존 예약/결제는 사용하거나 변경하지 않았다. 격리 DB에만 승인 상태의 합성 예약·USD 1.00 결제 행을 만들어 본문·권한·업무 로직·실제 PG 연결을 검증했다. 격리 테스트용 서명 JWT를 사용했으며 실제 서버 Auth 검사는 변경하지 않았다. FCM은 격리 앱의 전송 없는 대역을 사용했다.

PayPal-Request-Id가 기존 서버 결제 ID와 겹치지 않도록 테스트 payment ID를 별도 큰 정수로 발급했다. 처음 만든 주문만 유지하며 API 재요청으로 결제 행/주문을 추가하지 않았다. 격리 DB 결제 행은 최종 1개다.

| 경로/업무 | 실제 서버 HTTP 검증 | 격리 백엔드 + 실제 Sandbox 검증 |
| --- | --- | --- |
| POST /api/v1/nadree/rental/payment/order | 무인증 401 | 생성 200, 동일 주문 재사용 200·order ID 동일, 잘못된 입력 422·타 고객 404 |
| POST /api/v1/nadree/rental/payment/capture | 무인증 401 | 무인증 401·없는 payment 404·입력 오류 422·타 고객 404. 승인 후 성공은 미검증 |
| GET /api/v1/nadree/rental/payment/{paymentId} | 무인증 401 | 본인 200, USD 1.00/원 주문 ID 확인, 타 고객 404 |
| POST /nadreego/paypal/webhook | 서명 누락 400 | 서명 누락 400. 실제 유효 서명·정산·재전송 종단은 미검증 |
| 고객/관리자 취소 → 환불 | 이번에 실제 서버 취소 안 함 | 자동 테스트 대역으로 검증. 실제 Sandbox 환불 성공은 미검증 |
| app.refund_recovery / app.jobs payments | 공유 DB 작업·타이머 실행 안 함 | 자동 테스트 대역으로 복구·재시도 검증. 실제 PG 복구는 미검증 |

위 정상/오류 경로의 **격리 API 검사 11개가 모두 통과**했고 실제 서비스의 인증/서명 누락 검사 **4개가 통과**했다. 실제 도메인의 정상 결제 종단 검증을 완료했다는 뜻은 아니다. 실제 주문은 CREATED인 채 보존했으며 구매자 자금 캡처·환불·실제 푸시는 발생시키지 않았다.

## 자동 회귀 테스트

PayPal 관련 7개 파일을 파일별 pytest 프로세스로 다시 실행했다. 임시 SQLite fixture·네트워크 비활성 임시 MySQL을 사용했고 외부 PayPal/FCM은 대역만 사용했다. **59 passed, 실패 파일 없음.**

- test_payment_safety.py: 중복/기존 결제 차단, 주문·캡처 응답 유실과 멱등 식별자, 재전송 기한, 뒤늦은/추가 청구 환불, 역순 웹훅, 불명 결과의 만료 차단, 환불 실패/보류 복구.
- test_refunds.py: 환불 상태·요청·반복 처리.
- test_webhook_replay.py: 서명/시간·재전송·멱등 처리.
- test_jobs.py: 결제 복구/만료 작업.
- test_nadri_flow.py: 예약·주문·캡처·웹훅·인계·반납의 업무 흐름.
- test_cancellation_policy.py: 고객 90%/0%, 관리자 시작일 전 100%, 날짜·인계·소유권·중복 취소 제한.
- test_payment_deadline_policy.py: 승인+72시간과 시작일 경계.

이 59개는 실제 Sandbox 환불이나 실패/응답 유실을 외부에서 발생시킨 테스트가 아니다. 기존 TestClient 의존성 경고는 유지된다. 로그는 `build/test-runtime/latest-paypal-regression.log`에 보관했고 임시 MySQL 종료도 확인했다.

## 발견한 설정 차이와 필요한 후속 작업

1. Merchant ID가 실제 Sandbox 판매자와 일치하지 않는다. source의 snapshot은 **PAYPAL_MERCHANT_MISMATCH**로 거절한다. 사용자가 이후 추가하겠다고 하여 이번에는 설정·검사를 바꾸지 않았다. 정상 결제 완료/웹훅 정산 인수 전에는 Client ID/Secret을 발급한 Sandbox Business 계정의 Merchant ID를 맞춰야 한다.
2. 현재 웹훅 구독은 CHECKOUT.ORDER.APPROVED, PAYMENT.CAPTURE.COMPLETED, PAYMENT.CAPTURE.DENIED, PAYMENT.CAPTURE.PENDING, PAYMENT.CAPTURE.REFUNDED 5개다. 실제 PayPal 이벤트 유형 목록과 코드 SUPPORTED를 비교하면 **PAYMENT.CAPTURE.DECLINED, PAYMENT.CAPTURE.REVERSED, PAYMENT.REFUND.PENDING, PAYMENT.REFUND.FAILED** 4개는 제공되는 이벤트인데 현재 구독돼 있지 않다. 해당 경로의 자동 수신 검증은 미완료다. 구독 변경은 실행하지 않았으며 이벤트 추가는 정확한 대상 확인 후 별도 승인 작업이다.
3. 구매자 승인 상태가 CREATED이다. PayPal checkout 화면에서 Sandbox Personal 계정으로 최종 승인 후 실제 APPROVED를 확인해야 캡처·캡처 조회·전액 환불·환불 조회를 진행할 수 있다. 웹훅 정산 검사는 Merchant ID 설정 이후 따로 수행한다.

결제 타이머를 켜거나 기존 결제 4건을 복구하지 않았다. 기존 자동 작업 보류는 유지되며 테스트 키라고 해서 공유 DB의 과거 고객/결제를 임의 사용하지 않았다. API 서비스 재시작·env 변경·Firebase 배포·사용자 삭제·권한 변경도 이번 PayPal 검증에서 수행하지 않았다.

## 상태 보존과 재개

`build/paypal-sandbox-2026-10-13/integration/`에 격리 DB와 미결제 주문의 상태/승인 URL을 mode 600 파일로 보존했다. 상위 테스트 디렉터리는 접근을 제한했고 env 키·OAuth token은 저장하지 않았다. `state.private.json`에는 재개에 필요한 테스트 주문/예약/payment 식별자만 있으며 원문을 문서에 복사하지 않는다.

준비·읽기 검사·최종 상태 결과는 동일 디렉터리의 prepare-results.json, readonly-results.json, final-readonly.json과 build/test-runtime/paypal-connection-results.json이다. 초기 준비 검사에서 Merchant 불일치로 실패 표시된 항목은 제외 지시 이후에도 사실로 유지한다. 정상 작업 전체 통과로 덮어쓰지 않는다.
