# Nadree 전체 변경사항 및 인수 문서

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

## 8. FCM 정책

FCM 토큰은 앱이 전달한 값을 계정의 최신 토큰으로 저장합니다. 이번 정책은 계정당 기기 하나이며, 로그아웃해도 토큰을 삭제하지 않습니다.

| 이벤트 | 수신자 |
|---|---|
| 예약 요청 | 해당 지점과 상위 지점 범위의 활성 관리자 전체 |
| 예약 승인 | 관광객 |
| 예약 거절 | 관광객 |
| 결제 기한 2일/1일 전 | 관광객 |
| 결제 기한 만료 | 관광객 |
| 결제 완료 | 관광객 및 해당 지점 관리자 전체 |

관리자 수신자는 대상 지점과 상위 scope의 활성 `rental_primary_admin`/`rental_manager`를 조회합니다. 같은 토큰이 여러 계정에 있으면 한 번만 발송합니다. FCM 발송 실패가 예약·결제 트랜잭션 자체를 실패시키지 않도록 비즈니스 처리와 알림 결과를 분리합니다.

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
- 로그아웃 시 FCM 토큰을 삭제하지 않습니다.
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

- 전체 자동 테스트: 156 passed, 6 skipped, 3 warnings 기준으로 통과했습니다.
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
