# 지점별 PayPal 판매자 연결 변경

2026-10-16. 로컬 구현이며 서버 DB·PayPal 설정·실제 결제에는 적용하지 않았다.

## 정책과 저장 구조

나드리는 Platform 앱 한 세트로 입점 판매자의 결제를 처리한다. 지점마다 판매자 ID를 저장하고 동일 ID를 여러 지점에서 사용할 수 있다. 회원가입/지점 생성 시 필수 입력하지 않으며 별도 API로 설정한다. 회사 공통값의 자동 상속·전체 지점 일괄 수정은 하지 않는다.

| 테이블 | nullable 추가 컬럼 | 목적 |
| --- | --- | --- |
| MSP_SPOT_RENT | paypal_merchant_id VARCHAR(13) | 지점의 판매자 ID. UNIQUE 없음 |
| MSP_SPOT_RENT | paypal_environment VARCHAR(10) | 저장 당시 SANDBOX/LIVE. 환경 전환 후 잘못된 ID 사용 방지 |
| MSP_RENTAL_PAYMENT | paypal_merchant_id VARCHAR(13) | 결제 생성 당시 판매자. 지점 설정 변경으로 갱신하지 않음 |

과거 결제의 판매자를 현재 지점이나 기존 env로 추정해서 채우지 않는다. 기존 결제에 값이 없으면 PAYMENT_MERCHANT_RECONCILIATION_REQUIRED로 안전하게 중단한다. 기존 거래는 실제 PayPal 수취인·환경을 확인한 별도 이관이 필요하다. 따라서 이 변경은 기존 결제 자동 복구/환불에 영향이 있으며 무조건 재시작만 해서는 안 된다.

## 프론트 설정 API

`PUT /nadreego/shop/paypal-merchant`, 관리자 Bearer 인증. 대표관리자만 자기 지점/허용 하위 지점 변경 가능하다. 일반관리자는 변경 불가다.

```json
{"spotMasterId":"00000000-0000-4000-8000-000000000101","merchantId":"SELLER1234567"}
```

위 ID는 형식 예시일 뿐 실제 연결된 판매자가 아니다. 실제 ID는 영문 대문자·숫자 13자리이며 빈 값/임의 추가 필드는 422로 거절한다. `merchantId:null`은 연결 설정 해제다. 동일 ID의 여러 지점 등록은 허용한다.

설정할 때 PayPal의 merchant-integrations API로 해당 플랫폼에 부여된 결제/환불 권한, payments_receivable, primary_email_confirmed 및 판매자 ID를 확인한다. 실패하면 기존 값을 보존한다. 이 API는 PayPal 계정 생성이나 판매자 동의를 대신하지 않는다. 판매자는 PayPal에서 먼저 플랫폼 연결/권한 부여를 완료해야 한다. 연결 링크 생성 UI/API 및 플랫폼 수수료·지급 지연은 이번 범위에서 추가하지 않았다.

성공 응답:

```json
{"status":"success","spotMasterId":"00000000-0000-4000-8000-000000000101","merchantId":"SELLER1234567","paymentEnvironment":"SANDBOX"}
```

`GET /nadreego/shop/paypal-merchant?spotMasterId=...`로 같은 구조를 조회한다. 일반관리자는 직접 지점만, 대표는 허용 하위 지점도 조회 가능하다. 조회 응답은 저장된 설정이며 실시간 PayPal 정상 상태를 보증하지 않는다.

## 예약 승인과 결제

- 고객 예약 요청: 기존 흐름 유지. Merchant ID 입력을 고객에게 요구하지 않는다.
- 관리자 APPROVE: 예약 지점의 ID가 없으면 `409 SHOP_PAYPAL_MERCHANT_REQUIRED`. 프론트 문구: **해당 차량 지점의 Merchant ID가 없어 예약을 승인할 수 없습니다. 지점의 PayPal 결제 정보를 먼저 설정해 주세요.**
- 환경 불일치: `409 SHOP_PAYPAL_ENVIRONMENT_MISMATCH`. 현재 서버 환경에 맞는 판매자를 다시 연결한다.
- 실패한 승인은 REQUESTED 상태를 유지하며 차량 배정·승인 이력·승인 알림을 생성하지 않는다.
- REJECT: Merchant ID 없이도 기존대로 가능하다.
- 주문 생성/캡처: 지점 설정을 다시 확인한다. 주문에 실제 판매자 payee를 지정하고 플랫폼 인증정보 및 PayPal-Auth-Assertion을 사용한다. 구매자 요청의 임의 수취인 지정은 받지 않는다.
- 판매자 수취 가능 여부는 새 주문 외부 요청 및 캡처 전에도 확인한다. 영구 연결 상태라고 가정하지 않는다. PayPal 장애 시 검사를 생략하지 않는다.
- 이미 시작한 결제의 재사용·캡처·환불·웹훅·복구는 결제 행의 원래 판매자 ID를 기준으로 한다. 지점 ID 변경이 기존 거래의 수취인을 바꾸지 않는다.
- 지점 연결 해제 후 새 결제는 차단하지만 기존 결제의 환불은 원래 판매자 기준으로 유지한다.
- 예약 승인 차단은 결제 설정 확인이지 실제 PayPal 결제 완료 보장이 아니다. 기존 취소·환불률·결제 기한 정책은 변경하지 않았다.

추가 오류: `PAYPAL_PARTNER_NOT_CONFIGURED`(플랫폼 계정 설정 필요), `PAYPAL_MERCHANT_NOT_READY`(판매자 연결/수취/권한 확인 필요), `PAYPAL_MERCHANT_MISMATCH`(원거래 판매자 불일치), `PAYPAL_MERCHANT_SCHEMA_UPDATE_REQUIRED`(DB 적용 필요). 서버 오류 응답은 기존 status/errorCode 구조이며 문구는 프론트에서 매핑한다.

## 서버 적용 준비

`.env`의 CLIENT_ID/SECRET/WEBHOOK_ID는 같은 환경의 Platform 앱 값으로 맞춘다. 비밀값은 Git·문서·프론트에 전달하지 않는다.

```dotenv
NADREE_PAYPAL_ENVIRONMENT=SANDBOX
NADREE_PAYPAL_CLIENT_ID='Platform 앱 Client ID'
NADREE_PAYPAL_CLIENT_SECRET='같은 앱 Secret'
NADREE_PAYPAL_WEBHOOK_ID='같은 앱 Webhook ID'
NADREE_PAYPAL_PARTNER_MERCHANT_ID='플랫폼 계정의 Merchant ID'
NADREE_PAYPAL_PARTNER_ATTRIBUTION_ID='PayPal에서 발급받은 BN 코드가 있으면 설정'
```

기존 NADREE_PAYPAL_MERCHANT_ID는 더 이상 지점 판매자 기본값으로 사용하지 않는다. Platform 앱을 바꾸면 과거 Merchant 앱 거래를 새 앱으로 자동 이관하는 것이 아니므로 과거 주문 처리 경로를 먼저 확인한다.

적용 순서: 기존 거래 목록/원판매자와 앱 확인 → 백업 및 DB 계획 조회 → 승인된 마이그레이션 → Platform env 확인 → 재시작 → 지점별 API 설정 → 승인/거절/주문 테스트. 이 문서 작성 중 실제 명령은 실행하지 않았다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
# 백업·대상 DB 및 기존 거래 처리 계획 승인 후에만:
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST'
sudo systemctl restart nadree-api.service
```

기존 시드의 모든 지점은 실제 연결된 ID를 자동 부여하지 않는다. 마이그레이션 후 지점 설정 전에는 예약 승인이 차단되는 것이 의도된 동작이다. Live 전환 시 Sandbox 지점 설정을 그대로 사용하지 말고 Live 판매자 연결을 확인해 다시 설정한다.

## 검증 범위

최종 로컬 회귀: **288 passed, 10 skipped**, 기존 TestClient 의존성 경고 2개. 건너뛴 항목은 별도 MySQL 6개·Firestore 4개다. 신규 판매자 연결 관련 테스트 22개 포함, `git diff --check` 통과. 실제 서버나 외부 PG 호출 없이 실행했다.

격리 DB·MockTransport로 설정 권한, 중복 ID, 해제, 승인 차단/거절 허용, 판매자 변경 후 기존 거래 보존, 잘못된 수취인 차단, Platform 요청 헤더와 PayPal 연결 검증을 테스트한다. 실제 Sandbox 판매자 온보딩·주문·캡처·환불·웹훅과 공유 MySQL 마이그레이션은 별도 서버 검증이 필요하다. 이전 10월13일 단일 판매자 검증 결과를 이번 Platform 검증 완료로 재사용하지 않는다.

공식 연동 근거: [Platform Checkout](https://developer.paypal.com/platforms/checkout/standard/integrate), [판매자 연결 확인](https://developer.paypal.com/platforms/checkout/save-payment-methods/onboarding/platform/).
