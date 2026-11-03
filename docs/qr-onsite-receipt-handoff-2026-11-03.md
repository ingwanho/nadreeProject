# 공용 QR 현장 신청·고객 인수 확인 전달서

2026-11-03. 로컬 코드·Swagger·마이그레이션 계획 작성 완료. 서버 DB 변경·배포·실제 앱/FCM 검증은 별도다. 현장 신청은 항상 EXTERNAL이며 온라인 결제 중단 정책을 유지한다.

## 공용 QR 규칙

고객·관리자는 기존 차량 QR 원문을 동일하게 `qrCode`로 보낸다. 1~4,096자이며 대소문자·공백을 구분한다. 서버는 그대로 기존 `NADREE_QR_HASH_KEY`로 HMAC-SHA256 처리해 64자 `MSP_VEHICLE_QR.qr_code_hash`와 비교한다. QR과 센서 코드는 별개이며 센서 없는 차량도 지원한다.

고객 전용 코드·10자 제한·대소문자 무시·URL `#` 자동 추출은 도입하지 않는다. 스캔값이 URL이면 전체 원문을 보낸다. 등록 원문 일부만 잘라 보내면 조회되지 않는다. 직접 입력도 같은 원문을 사용한다. 발급·변경·폐기는 기존 차량 API를 사용하며 신규 QR 매핑 컬럼은 없다. QR만으로 인수 권한을 부여하지 않고 고객 Bearer 인증·본인 예약·배정 차량을 검사한다. 다른 고객 예약이나 UID를 노출하지 않는다.

## API와 테스트 순서

고객 접두사는 `/api/v1/nadree/rental`, 인증은 기존 `Authorization: Bearer <accessToken>`이다. 날짜 예시는 실제 테스트 날짜로 바꾼다.

| 순서 | 메서드·경로 | 입력·결과 |
| --- | --- | --- |
| 1 | POST `/qr/lookup` | `{"qrCode":"testQr123123"}`, 예약 상세에서는 reservationId 추가. 차량·매장·본인 예약·허용 액션 반환 |
| 2 | POST `/onsite/quote` | `{"qrCode":"testQr123123","returnDate":"2026-11-05"}` → 가격·통화·quoteToken·quoteExpiresAt |
| 3 | POST `/onsite/requests` | 위 입력 + clientRequestId + quoteToken → 기존 상세 형태 `{"status":"success","item":{...}}`, REQUESTED |
| 4 | 관리자 POST `/nadreego/booking/action` | 기존 bookedNo + action=APPROVE 또는 REJECT |
| 5 | 관리자 POST `/nadreego/rent/approve` | bookedNo + qrCode + `receiptRequired:true` → data.reservationStatus=HANDOVER_PENDING |
| 6 | 고객 POST `/reservations/{reservation_id}/receive` | `{"qrCode":"testQr123123"}` → item.reservationStatus=HANDED_OVER, item.rentalStatus=ON_RENT |
| 7 | 관리자 POST `/nadreego/vehicle/return` | 기존 qrCode → RETURNED |

신청 예시:

```json
{
  "qrCode": "testQr123123",
  "returnDate": "2026-11-05",
  "clientRequestId": "11111111-2222-4333-8444-555555555555",
  "quoteToken": "<직전 견적 응답의 quoteToken>"
}
```

기존 일반 `/availability`, `/request`의 당일 신청 금지는 유지한다. 별도 현장 신청은 발리 당일 시작, 다음 날부터 30일 뒤까지 반납일을 선택한다. 스캔 차량에 고정하고 배송은 PICKUP이다. 기존 BASE/BASIC/PREMIUM 가격·매장 위치·예약 재고를 검증한다. 견적은 10분이며 발리 날짜가 바뀌면 새 신청에 사용할 수 없다. 제출 시 가격·재고를 다시 검사하고 가격 변경은 ONSITE_QUOTE_CHANGED로 새 견적을 요구한다. 주문·capture·가짜 PAID/수납 행은 만들지 않는다.

앱은 서버 접수 전 처리 중 UI와 실제 REQUESTED 예약을 구분한다. 접수 결과는 기존 고객 ongoing/completed/상세 및 관리자 booking/select·캘린더에서 조회한다.

## 중복 요청과 응답 유실

clientRequestId는 고객별 유일한 16~64자 소문자 영숫자·`_`·`-`다. 소문자 UUID를 최초 전송 전에 앱에 저장한다. GET `/onsite/requests/{client_request_id}`로 본인 접수 결과를 조회한다. 미접수는 404 ONSITE_REQUEST_NOT_FOUND이며 통신 장애/5xx를 미접수로 간주하지 않는다.

같은 고객·키·QR·차량·기간·견적 금액/통화의 재전송은 기존 예약을 반환한다. 성공했다면 견적 만료·다음 날짜 이후에도 조회/재전송할 수 있다. 다른 내용에 같은 키를 쓰면 REQUEST_KEY_REUSED다. 미접수이고 견적 만료이면 새 견적을 받는다. 키는 예약 행 보존 기간 동안 유지하며 별도 TTL/결과 테이블은 없다. flag=false여도 접수 결과 GET은 가능하다.

고객 인수 재시도도 같은 본인 예약·QR이면 기존 계약을 반환한다. 최초 인수에는 활성 QR이 필요하며 성공 후에는 당시 QR 해시로 결과를 확인하므로 이후 QR 만료로 계약을 다시 만들지 않는다. GET `/reservations/{reservation_id}`가 최종 결과 기준이다. 알림 선택이나 QR 조회만으로 인수하지 않고 명시적 버튼에서 receive를 호출한다.

## 상태와 기한

시간대는 Asia/Makassar(발리 UTC+8), DB 시각은 기존 UTC 규칙이다.

| 단계 | 예약 / 배정 | 계약 | 차량 |
| --- | --- | --- | --- |
| 접수 | REQUESTED / SOFT_HOLD | 없음 | 기존 상태 |
| 승인 | APPROVED / PROVISIONAL 또는 REALLOCATED | 없음 | 기존 상태 |
| 관리자 인계 | HANDOVER_PENDING / LOCKED | 없음 | DISABLED, 내부 인수 보호 사유 |
| 고객 인수 | HANDED_OVER / LOCKED | ON_RENT | ON_RENT |
| 관리자 반납 | RETURNED / RELEASED | RETURNED | AVAILABLE |
| 현장 당일 미인계 만료 | EXPIRED / RELEASED | 없음 | 기존 상태 |
| 인계 후 미인수 만료 | EXPIRED / LOCKED, 배정 보존 | 없음 | DISABLED 유지 |
| 직원 실물 회수 | CANCELED / RELEASED | 없음 | AVAILABLE |

기능 활성 흐름에서 사전 예약은 시작일에 인계한다. 현장 요청은 신청 당일 승인·인계한다. 인수 마감은 관리자 인계일 다음 날 00:00 미만이다. 다음 자정부터는 배치가 늦어도 API가 RECEIPT_DEADLINE_EXPIRED로 차단한다. actual_start_time/receivedAt은 고객 인수 성공 시각이며 handedOverAt은 관리자 인계 시각이다. 기존 HANDED_OVER/ON_RENT 계약은 재확인하지 않는다.

인수/회수 대기에서는 일반 취소·재인계·반납·다른 예약 배정·차량 이동·QR 해제 등 차량 변경을 막는다. 만료 CLI `.venv/bin/python -m app.jobs receipts`는 전용 타이머로 매분 실행하며 기존 MySQL 작업 잠금을 사용한다. 만료 이력·관리자 알림함 RESERVATION_EXPIRED와 조회 상태를 갱신한다. 기존 jobs all/결제 복구 cron에는 자동 편입하지 않는다. 차량을 자동 회수하거나 AVAILABLE로 바꾸지 않는다.

직접 소속 지점의 쓰기 권한을 가진 직원이 차량·열쇠를 실물 확인한 뒤 보호를 해제한다. QR이 비활성이어도 같은 차량 QR로 회수할 수 있다. EXTERNAL 수납 정산은 매장 업무이며 PG를 호출하지 않는다. 과거 PAYPAL 거래는 기존 관리자 환불 정책·이력을 사용한다.

```text
POST /nadreego/booking/BO<reservationId>/receipt-recovery
Authorization: Bearer <관리자 accessToken>
{"qrCode":"testQr123123","vehicleReturned":true,"reason":"차량·열쇠 회수 확인"}
```

## 조회·액션·푸시

추가 필드는 고객 상세 item/목록 items[], 관리자 booking/select items[], 차량 목록 currentBooking, 관리자 QR 검증 data.currentBooking, 캘린더 events[]에 제공한다. 관리자 QR 검증의 data.currentRental과 availableActions도 현재 인수/회수 상태를 반영한다.

- requestType=ADVANCE/ONSITE(기존 행 ADVANCE), requestDeadline=현장 당일 마감/사전 예약 null.
- customerReceiptRequired, handedOverAt, receiptDeadline, receivedAt, canReceive, receiptBlockedReason, vehicleRecoveryRequired. 미도달 시각은 null이다. 인수 완료 뒤 canReceive=false/NOT_AWAITING_RECEIPT다. 마감 후 회수 필요는 배치 전에도 true다.
- 고객 QR vehicleMatch=ASSIGNED/MODEL_PENDING/null. 본인 후보가 여럿이면 RESERVATION_SELECTION_REQUIRED이므로 예약 선택 후 reservationId와 재조회한다.
- 고객 QR availableActions=ONSITE_QUOTE/WAIT_APPROVAL/WAIT_HANDOVER/CONFIRM_RECEIPT. 최신 예약 상세와 함께 화면을 구성한다.
- 관리자 availableActions는 인계 가능 시 RENT_APPROVE, 인수/회수 대기는 RECOVER_VEHICLE이다. 대기 중 RETURN/재인계는 표시하지 않는다. 상위 지점의 하위 지점 읽기 캘린더에는 회수 액션이 없다.
- 관리자 canHandOver는 실제 쓰기 검증을 사용한다. 대시보드는 awaitingReceipt 개수와 todayWork 예약 상태를 제공한다. 캘린더 보호 차량은 기존 예약 기간이 지나도 isBlocking=true/endAt=null/endAtType=OPEN이다.

관리자 인계 커밋 후 기존 FCM 발송기에 CUSTOMER_RECEIPT_REQUIRED를 1회 큐잉한다. 같은 인계 재시도는 중복 큐를 만들지 않는다. 토큰 없음/발송 실패는 인계를 되돌리지 않는다. 새로운 영속 푸시 재시도 큐는 만들지 않았다. 제목 `차량 인수 확인 안내`, 본문은 발리 오늘 종료 전 QR 확인·명시적 인수를 안내한다. QR/해시·민감정보는 전송하지 않는다.

```json
{"type":"CUSTOMER_RECEIPT_REQUIRED","eventId":"receipt:<reservationId>","reservationId":"<reservationId>","bookedNo":"BO<reservationId>","reservationStatus":"HANDOVER_PENDING","receiptDeadline":"2026-11-03T16:00:00Z"}
```

알림 진입 시 로그인·본인 예약·최신 상태를 다시 확인한다. 미수신이어도 목록/상세로 인수할 수 있고 기인수·만료 후 지연 알림은 최신 상태로 표시한다.

주요 오류는 기존 `{"status":"fail","errorCode":"..."}` 형식이다. QR/예약 미발견404, 비활성409, 만료410, 입력422, 호출 제한429, 인증/권한401/403, 설정/스키마 장애503을 구분한다. 신규 업무 오류409: ONSITE_QUOTE_INVALID/MISMATCH/EXPIRED/CHANGED, REQUEST_KEY_REUSED, RESERVATION_VEHICLE_MISMATCH, RESERVATION_SELECTION_REQUIRED, NOT_AWAITING_RECEIPT, RECEIPT_DEADLINE_EXPIRED, VEHICLE_RECEIPT_HOLD, NOT_AWAITING_RECOVERY, RECEIPT_HOLD_INCONSISTENT, CUSTOMER_RECEIPT_NOT_ENABLED, CLIENT_UPDATE_REQUIRED, OUTSIDE_HANDOVER_DAY, ONSITE_REQUEST_EXPIRED. INVALID_ONSITE_PERIOD는422다.

## DB·서버 적용과 복구

MSP_RESERVATION에 nullable client_request_id VARCHAR(64), handed_over_at DATETIME, receipt_deadline_at DATETIME을 추가한다. 고객+키 UNIQUE, 상태+인수 기한 인덱스, HANDOVER_PENDING 허용 CHECK 변경이 있다. 과거 행/QR/결제 데이터를 변환하지 않는다. 구분·차량 고정·인수 메타데이터는 기존 JSON을 사용한다. 마이그레이션 정본은 app.migrate이며 기존 CHECK 이름/상태를 보존해 확장한다. 부모 ERD SQL은 시각화용이므로 운영에서 실행하지 않는다.

1. DB 백업·공유 서비스 영향 확인 후 코드 배포. `.env`의 NADREE_CUSTOMER_RECEIPT_ENABLED=false 유지.
2. 서비스 계정으로 아래 계획을 확인한 뒤 승인된 DB에만 적용한다. DB명은 실제 env와 일치시킨다.

   ```bash
   sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
   sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST'
   sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
   ```

3. 양 앱에 QR/새 상태/receiptRequired 계약을 연결하고 테스트 환경에서 활성화·공동 검증한다. 활성 시 구버전의 receiptRequired 누락은 CLIENT_UPDATE_REQUIRED다. 비활성일 때 새 앱의 receiptRequired=true도 차단하여 즉시 출고로 오인하지 않는다.
4. 양 앱 준비 후 `.env`에 NADREE_CUSTOMER_RECEIPT_ENABLED=true, API 재시작. 새 일반 예약은 해당 정책을 보존한다. 이후 flag=false로 바꿔도 이미 필요한 건의 고객 확인/실물 회수는 유지한다.
5. 전용 만료 타이머를 설치한다. 기존 결제 타이머와 별개다.

   ```bash
   cd /srv/nadree-api
   sudo install -m 644 deployment/nadree-receipts.service /etc/systemd/system/nadree-receipts.service
   sudo install -m 644 deployment/nadree-receipts.timer /etc/systemd/system/nadree-receipts.timer
   sudo systemctl daemon-reload
   sudo systemctl enable --now nadree-receipts.timer
   sudo systemctl list-timers nadree-receipts.timer
   ```

Firebase Functions·Rules·인덱스·FCM 키 변경/재배포는 필요 없다. 기존 채팅 상태 동기화를 재사용하며 만료 SQL은 기존 동기화가 채팅에 반영한다. 실제 기기 토큰 등록·수신은 공동 검증 대상이다.

복구 시 flag=false로 신규 진입을 막고 진행 건은 현재 코드로 인수/회수한다. 보호 차량이 남은 채로 이전 바이너리를 적용하거나 SQL로 AVAILABLE로 바꾸지 않는다. 진행 건 정리 후 타이머 중단·이전 버전 적용을 판단하며 nullable 컬럼/상태는 보존한다.

## 검증 범위

최종 로컬 전체 회귀: **572 passed / 14 skipped / 0 failed**. 제외 항목은 별도 MySQL·Firestore 환경이 필요한 검사이며 새 현장 중복 제출·고객 인수 동시성 검사 2개도 여기에 포함된다. 기존 테스트 대역 및 라이브러리 경고 14개가 있었다. 신규 고객 응답 예시 5개는 실제 응답 모델로 검증했고, API/DB 엑셀은 재개방·통합 시트·JSON 예시·3컬럼 반영을 확인했다. `git diff --check`도 통과했다.

격리 API·SQL로 견적·원문 대소문자·소유권·요청 중복/유실·견적 만료/가격 변경·인수 전 차단·인수/반납·마감 경계·보호/회수·발송 실패 후 상태 보존을 검사한다. 현장 경로에서 외부 결제 메서드가 호출되면 실패하는 대역으로 PayPal 비호출을 확인한다. 마이그레이션 읽기 전용 계획·기존 상태 보존·MySQL DDL 컴파일도 검사한다.

실제 MySQL 동시 요청/잠금·운영 마이그레이션·앱 화면·실기기 FCM/App Check·양 앱 공동 시나리오는 별도다. SQLite 성공을 실제 동시성·푸시 전달 성공으로 간주하지 않는다.
