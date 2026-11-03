# 프론트 전달 — QR 현장 신청·고객 인수 확인

작성일: 2026-11-03. 대상: 고객 앱·관리자 앱·공통 예약 응답을 사용하는 웹 담당자.

**최종 변경 배포 완료. 고객 인수는 현재 필수 동작이며 별도 활성화 요청은 필요하지 않습니다.** 커밋 `254507d`를 2026-11-03 07:34:55 UTC에 시작했고, 실제 서비스는 health 제외 75개 경로와 새 close API를 제공합니다. 기존 `NADREE_CUSTOMER_RECEIPT_ENABLED` 설정은 제거됐으며 false로 즉시 대여를 복구하는 방식은 없습니다.

API 주소는 `https://na-dree.com`입니다. 최신 요청/응답과 상태별 예시는 [Swagger](https://na-dree.com/docs), [OpenAPI](https://na-dree.com/openapi.json), [추가 요청 처리 계약](qr-onsite-followup-contract-2026-11-03.md)을 사용합니다. 실제 적용 시각·서버 증거·미검증 범위는 [최종 배포 결과](qr-onsite-final-server-deployment-result-2026-11-03.md)를 기준으로 합니다.

## 1. 현재 적용 상태와 검증 범위

| 구분 | 확인 결과 |
| --- | --- |
| 배포 계약 | 요청 결과 4상태·영속 거절·close, 고객 인수 필수 절차와 관리자 표시 보완 적용 |
| 실제 서비스 | 로컬·공개 health/live·health/ready·Swagger·OpenAPI 200, 75개 경로 및 close 확인 |
| 서버 데이터 | 신규 요청 결과 저장 적용·잔여 마이그레이션 0개, 기존 예약 29건 보존 |
| 인수 절차 | 관리자 인계 후 HANDOVER_PENDING, 본인 고객 receive 성공 후에만 HANDED_OVER/ON_RENT |
| 공동 QR 차량 | 최상위 테스트 지점에 아래 QR_ONLY 차량 2대 실제 등록·관리자 QR 조회 200 확인 |
| 격리 테스트 | **588 통과 / 15 건너뜀 / 실패·오류 0개**. 인수/회수 20개·요청 결과 11개 통과 |
| 남은 검증 | 실제 고객 신청→승인→인계→인수→반납 왕복, 양 앱 화면·인쇄 QR 인식·실기기 FCM/App Check |

건너뛴 15개는 전용 MySQL 환경이 필요한 11개와 Firestore 에뮬레이터 4개입니다. 격리 업무 성공·실제 관리자 QR 조회·실제 고객 전체 흐름 검증은 서로 구분합니다. 이번 서버 배포에서 실제 고객 예약·인수·회수·결제·환불·시험 푸시는 실행하지 않았습니다.

## 2. QR 원문과 실제 시험 차량

새 발급 원문은 고정 대문자 접두사 **NDR- + 대소문자를 구분하는 영문·숫자 8자리**, 총 12자입니다. 고객·관리자는 차량 등록 시 사용한 같은 원문을 보냅니다. `NDR-Ab12Cd34`와 `NDR-ab12Cd34`는 다른 값입니다.

| 단계 | 값 |
| --- | --- |
| 차량 등록 qrToken | `NDR-Ab12Cd34` |
| QR 이미지 문자열 형식 예시 | `https://example.com/#NDR-Ab12Cd34` |
| 두 앱이 # 뒤에서 추출한 전체 원문 | `NDR-Ab12Cd34` |
| 고객·관리자 API 입력 | `{"qrCode":"NDR-Ab12Cd34"}` |

**example.com은 형식 예시이며 실제 인쇄·발급용 도메인은 아직 확정되지 않았습니다.** 실제 발급 URL의 # 뒤에 전체 NDR 원문을 퍼센트 인코딩 없이 넣습니다. 두 앱은 URL을 자동으로 열지 않고 # 뒤 전체 값을 추출하며 직접 입력도 같은 원문을 사용합니다. 서버는 URL 추출·대소문자 변환·임의 자르기를 하지 않습니다. API 원문 입력 범위 1~4,096자는 유지하며 새 12자 규격은 발급 기준입니다.

DB 해시를 계산하거나 전송하지 않습니다. 서버가 기존 HMAC-SHA256으로 원문을 조회합니다. QR은 차량 식별 수단이며 로그인·본인 예약·정확한 배정 차량은 별도로 검증합니다. 센서 없는 차량도 지원합니다. 과거 testQr 계열 예시를 새 규격 공동 시험에 사용하지 않습니다.

다음 차량은 **기존 최상위 테스트 지점 `00000000-0000-4000-8000-000000000101`에 실제 등록**되어 있습니다.

| 항목 | 차량 1 | 차량 2 |
| --- | --- | --- |
| 번호판 | DK-NDR-ONLY-001 | DK-NDR-ONLY-002 |
| vehicleId | a2e47c5a-d968-4bb7-8736-c215ab65e154 | 7bb04647-c051-45c5-b31c-4b4dc5ba37f5 |
| QR 원문 | `NDR-Ab12Cd34` | `NDR-Ef56Gh78` |
| 모델 | NRTEST-WEB-MODEL-125 | NRTEST-WEB-MODEL-125 |
| 배기량 / 장비 | 125cc / QR_ONLY·센서 없음 | 125cc / QR_ONLY·센서 없음 |
| 등록 후 상태 | AVAILABLE / QR ACTIVE | AVAILABLE / QR ACTIVE |

실제 관리자 QR 조회는 두 차량 모두 200, 원문을 일괄 대문자로 바꾼 조회는 404였습니다. 가격은 기존 BASE/BASIC 설정과 조회 시점의 서버 견적을 사용합니다. 등록 후 앱 사용으로 재고·QR 상태가 바뀔 수 있으므로 시험 직전 다시 조회합니다. 인쇄 QR·두 앱의 카메라 인식 성공은 아직 검증하지 않았습니다.

시험 준비 과정에서 최상위 테스트 대표가 로그인 후 로그아웃했습니다. **관리자 앱은 해당 테스트 대표 계정으로 다시 로그인**해야 합니다. 비밀번호·토큰은 이 문서에 넣지 않습니다.

## 3. 고객 앱의 현장 신청·결과 복구

고객 경로에는 모두 `/api/v1/nadree/rental` 접두사를 붙이고 기존 `Authorization: Bearer <accessToken>`을 사용합니다.

| 메서드·경로 | 입력과 처리 |
| --- | --- |
| POST `/qr/lookup` | qrCode. 예약 상세에서는 reservationId도 전달. 본인 예약·vehicleMatch·availableActions 확인 |
| POST `/onsite/quote` | qrCode, returnDate. startDate·가격·통화·quoteToken·quoteExpiresAt 표시 |
| POST `/onsite/requests` | qrCode, returnDate, clientRequestId, quoteToken. requestStatus와 item을 함께 판정 |
| GET `/onsite/requests/{client_request_id}` | 응답 유실·앱 재시작 후 본인 키의 결과 조회 |
| POST `/onsite/requests/{client_request_id}/close` | 본문 없음. 사용자가 불명 요청을 명시적으로 종료할 때 호출 |
| POST `/reservations/{reservation_id}/receive` | qrCode. 고객이 차량 인수 확인 버튼을 명시적으로 누를 때만 호출 |

기존 `/availability`, `/request`의 사전 예약 당일 신청 금지는 유지합니다. 별도 현장 신청은 발리 당일 시작, 반납일은 다음 날부터 30일 뒤까지입니다. 스캔 차량에 고정하고 PICKUP·EXTERNAL로 처리하며 온라인 결제를 연결하지 않습니다.

견적은 10분 유효하고 발리 날짜가 바뀌면 신규 접수에 사용할 수 없습니다. 제출 시 가격·재고를 다시 검사합니다. 아래 날짜는 예시이며 실제 견적 응답에 맞춥니다.

```json
{
  "qrCode": "NDR-Ab12Cd34",
  "returnDate": "2026-11-05",
  "clientRequestId": "11111111-2222-4333-8444-555555555555",
  "quoteToken": "<견적 응답의 quoteToken>"
}
```

clientRequestId는 고객별 유일한 16~64자 소문자 영숫자·하이픈·밑줄입니다. **최초 전송 전에 키와 quoteToken까지 포함한 원본 본문을 저장**합니다. 같은 키의 재시도에는 원본 본문을 사용합니다. 다른 본문은 REQUEST_KEY_REUSED이며 이미 접수된 예약을 덮어쓰지 않습니다. 성공한 접수는 견적 만료·날짜 변경 뒤에도 기존 키로 복구할 수 있습니다.

### 요청 상태와 HTTP 판정

requestStatus는 접수 결과이며 예약 승인·대여 상태가 아닙니다. 실제 예약은 item.reservationStatus·item.rentalStatus로 표시합니다.

| requestStatus | requestFinal / canStartNewRequest | 앱 처리 |
| --- | --- | --- |
| ACCEPTED | true / false | item의 실제 예약 표시. 관리자 승인이나 대여 시작으로 표시하지 않음 |
| REJECTED | true / true | 키가 영속 종료됨. 필요하면 새 견적·새 키로 신청 |
| PROCESSING | false / false | 키·원본 본문 유지, 잠시 뒤 같은 키 결과 확인 |
| UNKNOWN | false / false | 성공/거절로 표시하지 않음. 결과 조회·동일 본문 재시도 또는 명시적 close |

| 경로·HTTP | 의미 |
| --- | --- |
| 신청 POST 200 | ACCEPTED + item, 신규 접수 또는 성공 재시도 |
| 신청 POST 202 / 결과 GET 202 | PROCESSING, Retry-After: 2. 확정 종료 아님 |
| 신청 POST 4xx + REJECTED | 업무 거절이 저장됨. 같은 키로 지연 제출·새 견적 제출해도 생성 불가 |
| 결과 GET 200 | ACCEPTED 또는 REJECTED. **200만 보고 접수 성공으로 판정하지 않음** |
| 결과 GET 404 ONSITE_REQUEST_NOT_FOUND | UNKNOWN. 키 종료나 늦은 신청 불가를 보장하지 않음 |
| 결과 GET 503 ONSITE_REQUEST_OUTCOME_UNKNOWN | UNKNOWN. 처리 중단 등으로 아직 결과 불명 |
| 상태 필드 없는 401/422/429/5xx·비JSON·통신 장애 | 확정 거절로 해석하지 않고 기존 키 보존 |

REJECTED의 retrySameRequest는 false입니다. REQUEST_KEY_REUSED도 retrySameRequest=false이며 기존 ACCEPTED 결과를 바꾸지 않습니다. 앱의 로컬 처리 중 항목과 서버 REQUESTED 예약을 구분하고, 결과가 불명인 상태에서 다른 키를 자동 발급해 중복 신청하지 않습니다.

close는 아직 예약이 없으면 REJECTED/ONSITE_REQUEST_CLOSED로 키를 종료합니다. 이후 늦게 온 POST도 그 키로 예약을 만들 수 없습니다. 이미 ACCEPTED라면 기존 item을 반환하고 예약을 취소하지 않습니다. 예약 취소는 기존 `/request/cancel`을 사용합니다. close가 202·5xx이거나 응답이 유실되면 확정 종료로 표시하지 않고 GET 또는 같은 close로 확인합니다. 다른 고객의 키에는 영향을 주지 않습니다.

**불명 요청을 버리고 새 신청으로 바꾸려면 close의 REJECTED/requestFinal=true를 확인한 뒤 새 견적·새 clientRequestId를 발급**합니다. 기존 신청을 이어가려면 키와 원래 quoteToken을 유지합니다. 결과 기록은 자동 TTL로 지워지지 않으므로 키를 재활용하지 않습니다.

## 4. 관리자 앱 연결

기존 관리자 인증과 직접 소속 지점의 쓰기 권한을 사용합니다. receiptRequired=true는 필수이며 별도 앱 빌드 플래그를 추가하지 않습니다.

| 메서드·경로 | 연결 내용 |
| --- | --- |
| POST `/nadreego/booking/action` | APPROVE/REJECT와 기존 bookedNo 유지 |
| POST `/nadreego/vehicle/qr/validate` | qrCode. data.currentBooking/currentRental/availableActions 확인 |
| POST `/nadreego/rent/approve` | bookedNo, qrCode, **receiptRequired=true** |
| POST `/nadreego/booking/{booked_no}/receipt-recovery` | 차량·열쇠 실물 확인 후 qrCode, vehicleReturned=true, reason |
| POST `/nadreego/vehicle/return` | 고객 인수가 완료된 계약의 기존 반납 처리 |

```json
{
  "bookedNo": "BO<reservationId>",
  "qrCode": "NDR-Ab12Cd34",
  "receiptRequired": true
}
```

관리자 인계 성공은 `data.reservationStatus=HANDOVER_PENDING`입니다. 이 단계에는 계약이 없으므로 ON_RENT로 표시하지 않습니다. 본인 고객 receive 성공 후에만 대여 중입니다. receiptRequired를 누락한 구버전 인계 요청은 409 CLIENT_UPDATE_REQUIRED로 차단됩니다. 새 앱 버전 헤더로 로그인·조회 전체를 차단하는 방식은 아닙니다.

| 관리자 화면·API | 레코드 위치·식별자 |
| --- | --- |
| 예약 목록/번호 상세 `POST /nadreego/booking/select` | items[].reservationId/vehicleId/bookedNo, 기존 reservation·rental·vehicle 구조 유지 |
| 홈 `GET /nadreego/main` | todayWork[]. 같은 ID·인수 필드·액션·canHandOver와 reservation/rental/vehicle 제공 |
| 캘린더 `POST /nadreego/main/calendar` | items[].events[]. reservationId/bookedNo·인수 필드·액션, 상태는 event.status |
| 차량 목록 `POST /nadreego/vehicle/select` | items[].currentBooking, 예약 없으면 null |
| 관리자 QR 검증 | data.currentBooking은 차량 목록과 같은 구조. data.vehicleId/vehicle/currentRental 유지 |

currentBooking의 availableActions는 예약 액션이고 차량 목록 최상위 availableActions는 차량 변경 액션입니다. REQUESTED는 APPROVE/REJECT, 인계 가능한 APPROVED는 RENT_APPROVE, 인수/회수 대기는 RECOVER_VEHICLE, ON_RENT/OVERDUE 계약은 RETURN을 사용합니다. canHandOver와 availableActions는 조회 시점의 판정이며 쓰기 API가 다시 검사합니다.

회수 전에는 일반 반납·취소·차량 이동·QR 해제로 보호를 우회하지 않습니다. 홈의 과거 회수 대기를 유지하고, 캘린더는 endAt=null/endAtType=OPEN/isBlocking=true인 보호 이벤트를 임의로 종료하지 않습니다. 상위 지점의 하위 지점 읽기 캘린더에는 직접 실행할 회수 액션이 없습니다.

## 5. 상태·인수 기한·오류 표시

| 상황 | 예약 / 계약 | 화면 기준 |
| --- | --- | --- |
| 접수 | REQUESTED / 없음 | 승인 대기 |
| 관리자 승인 | APPROVED / 없음 | 인계 대기 |
| 관리자 인계 | HANDOVER_PENDING / 없음 | 고객 인수 대기 |
| 고객 인수 성공 | HANDED_OVER / ON_RENT | 대여 중 |
| 관리자 반납 | RETURNED / RETURNED | 반납 완료 |
| 현장 당일 미인계 만료 | EXPIRED / 없음 | 현장 신청 종료, 배정 해제 |
| 인계 후 미인수 만료 | EXPIRED / 없음 | 배정·DISABLED 보호 유지, 실물 회수 필요 |
| 직원 실물 회수 | CANCELED / 없음 | 보호 해제·배정 해제 |

handedOverAt은 관리자 인계 시각, receivedAt과 actual_start_time은 고객 인수 확정 시각입니다. requestType은 ADVANCE/ONSITE, requestDeadline은 현장 신청일 마감이며 사전 예약은 null입니다. 단계 전 시각은 null을 허용합니다.

모든 날짜 경계는 **Asia/Makassar(발리 UTC+8)**입니다. 현장 요청은 당일 승인·인계하고 사전 예약은 시작일에 인계합니다. 인계일 다음 날 00:00부터 고객 인수는 불가능하며 배치 전후 모두 RECEIPT_DEADLINE_EXPIRED입니다. EXPIRED여도 차량 회수 전에는 대여 가능으로 표시하지 않습니다.

고객은 동일 예약·HANDOVER_PENDING·canReceive=true·vehicleMatch=ASSIGNED·CONFIRM_RECEIPT를 확인하고 버튼에서만 receive를 호출합니다. 예약 후보가 여럿이면 RESERVATION_SELECTION_REQUIRED에 따라 예약 선택 후 reservationId를 지정해 다시 조회합니다. GET `/reservations/{reservation_id}`의 본인 최신 상태를 최종 기준으로 사용합니다. 이번 서버 변경이 앱에 자동 새로고침을 추가하는 것은 아니므로, 자동 조회가 없는 화면에는 명시적 새로고침 경로를 제공합니다.

| 오류 | 앱 처리 |
| --- | --- |
| 404 RESERVATION_NOT_FOUND / QR_NOT_FOUND | 본인 예약·등록 원문 재확인. 다른 고객 존재를 추정하지 않음 |
| 409 RESERVATION_VEHICLE_MISMATCH | 정확한 배정 차량 확인 |
| 409 NOT_AWAITING_RECEIPT | 인계 전·취소·반납 등 현재 상태 확인 |
| 409 RECEIPT_DEADLINE_EXPIRED | 당일 마감 또는 만료 후 실물 회수 절차 안내 |
| 409 QR_INACTIVE / 410 QR_EXPIRED | QR 활성·만료 상태 재확인 |
| 409 RECEIPT_HOLD_INCONSISTENT | 인수 성공으로 표시하지 말고 운영 확인 |
| 409 VEHICLE_RECEIPT_HOLD / RESERVATION_STATE_INVALID | 일반 동작 재시도 대신 관리자 최신 상태·허용 액션 조회 |

같은 인계 재시도는 기존 기한을 반환하고 인수 성공 재시도는 같은 계약을 반환합니다. 이미 ON_RENT인 기존 계약은 재인수를 요구하지 않습니다. 웹의 공통 예약 화면도 HANDOVER_PENDING과 대여 중을 구분해야 합니다.

## 6. 인수 안내 푸시

관리자 인계 커밋 후 CUSTOMER_RECEIPT_REQUIRED를 발송합니다. 같은 인계 재시도로 안내 큐를 반복 생성하지 않으며 기기 미등록·발송 실패가 인계를 되돌리지 않습니다. 실기기 수신 성공은 아직 별도 검증 대상입니다.

```json
{
  "type": "CUSTOMER_RECEIPT_REQUIRED",
  "eventId": "receipt:<reservationId>",
  "reservationId": "<reservationId>",
  "bookedNo": "BO<reservationId>",
  "reservationStatus": "HANDOVER_PENDING",
  "receiptDeadline": "2026-11-03T16:00:00Z"
}
```

알림 진입은 로그인 → 본인 예약 상세 재조회 → 현재 상태 화면으로 연결하며 receive를 자동 호출하지 않습니다. 지연·기인수·만료 알림도 최신 서버 상태를 표시합니다. 푸시 미수신·알림 거부 상태에서도 목록·상세에서 인수할 수 있어야 합니다.

## 7. 양 앱 공동 시험 순서와 남은 검증

1. 기존 승인된 테스트 고객과 최상위 테스트 대표로 새로 로그인합니다. 위 QR 차량의 현재 재고·상태를 재확인합니다. 비밀번호·토큰을 앱 로그나 전달 문서에 복사하지 않습니다.
2. 두 앱의 URL # 추출·직접 입력에서 동일한 NDR 원문이 qrCode로 전달되는지 확인합니다. 실제 인쇄용 URL 도메인과 카메라 인식은 별도로 확정·시험합니다.
3. QR 조회 → 당일 견적 → 키·원본 본문 저장 → 신청 결과 ACCEPTED → 관리자 승인 → receiptRequired=true 인계 → 고객 인수 → 관리자 반납 순서로 시험합니다. 사전 예약은 시작일 인계 흐름을 별도로 시험합니다.
4. UNKNOWN·404·202·응답 유실에서는 키를 유지하고 조회/동일 본문 재시도를 확인합니다. 새 신청 전 close REJECTED를 확인하고, 이미 ACCEPTED인 close가 예약을 취소하지 않는지도 시험합니다.
5. 다른 고객/차량·인계 전 수령·중복 클릭·견적 만료/가격 변경·발리 자정 이후 차단·보호 차량 재배정 금지·실물 회수를 확인합니다.
6. 실기기 푸시·App Check·알림 거부/지연 상황을 공동 검증합니다. MySQL 동시성 11개와 Firestore 에뮬레이터 4개는 별도 환경에서 완료해야 합니다.

현재 서버는 새 계약으로 동작하지만 **실제 고객의 전체 업무 왕복과 두 앱·실기기 인수 시험은 아직 미검증**입니다. 이 문서의 등록 정보나 JSON 예시가 이미 생성된 예약·인수·반납을 의미하지 않습니다. 10월 29일 준비한 과거 예약을 오늘 인계용으로 재사용하지 않고 실제 테스트 날짜와 서버 견적을 사용합니다.

현재 결과는 [최종 배포 결과](qr-onsite-final-server-deployment-result-2026-11-03.md), 상세 계약은 [추가 요청 처리 계약](qr-onsite-followup-contract-2026-11-03.md)을 우선합니다. [이전 e31008c 적용 결과](qr-onsite-receipt-server-result-2026-11-03.md)는 과거 배포 이력으로 보존하며 현재 기능 상태 안내로 사용하지 않습니다. 이 문서 갱신으로 서버 설정·업무 코드·DB·서비스를 추가 변경하지 않았습니다.
