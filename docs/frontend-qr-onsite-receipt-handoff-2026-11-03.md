# 프론트 전달 — QR 현장 신청·고객 인수 확인

> **최신 추가 요청 처리:** [새 프론트 계약](qr-onsite-followup-contract-2026-11-03.md)에 NDR 12자 원문, 요청 결과 4상태·확정 종료 API, 관리자 누락 필드·오류 예시, 인수 절차 상시화를 정리했다. 새 코드는 서버 미적용이며 아래 false 설정 안내는 이전 서버 적용 당시 기록이다. 양 앱은 최신 계약을 기준으로 연결한다.

작성일: 2026-11-03. 대상: 고객 앱·관리자 앱·공통 예약 응답을 사용하는 웹 담당자.

**백엔드 배포와 DB 적용은 완료됐습니다. 현재 고객 인수 기능은 비활성(`NADREE_CUSTOMER_RECEIPT_ENABLED=false`)입니다.** 양 앱의 새 계약 연결과 승인된 테스트 환경 준비 후 활성화를 요청해 주세요. 현재 서버에 새 QR 흐름의 성공 요청을 보내 바로 시험할 수 있는 상태는 아닙니다.

이 문서는 가져온 [서버 적용·검증 결과](qr-onsite-receipt-server-result-2026-11-03.md)와 해당 코드의 API 계약을 대조해 정리했습니다. API 주소는 `https://na-dree.com`, 최신 스키마·예시는 [Swagger](https://na-dree.com/docs)와 [OpenAPI](https://na-dree.com/openapi.json)에서 확인합니다.

## 1. 적용 완료와 검증 범위

| 구분 | 확인 결과 |
| --- | --- |
| 배포 코드 | `e31008c`의 QR 현장 신청·고객 인수 변경사항 적용 |
| DB | 예약 3컬럼·인덱스 2개·상태 CHECK 적용, 잔여 마이그레이션 0개 |
| 기존 데이터 | 기존 예약 29건의 기존 컬럼 값 보존, 일괄 상태 전환·시드 재실행 없음 |
| 실제 서비스 | API 재시작 후 로컬·공개 health/live·health/ready·Swagger·OpenAPI 200 |
| 신규 경로 | 6개 등록과 요청/응답 필드, 무인증 차단 확인 |
| 만료 작업 | 전용 receipts 타이머 설치·정상 실행. 실제 만료 대상 처리 0건 |
| 격리 테스트 | **572 통과 / 14 건너뜀 / 실패·오류 0개**. QR 신규 테스트는 18 통과·MySQL 동시성 2개 제외 |
| 기능 설정 | 고객 인수 false, 기존 신규 예약 결제 방식 EXTERNAL·온라인 checkout 중단 유지 |
| 남은 검증 | 실제 인증 후 신청→승인→인계→인수→반납, 앱 화면, 실기기 FCM/App Check |

건너뛴 14개는 전용 MySQL 환경이 필요한 10개와 Firestore 에뮬레이터 4개입니다. 실제 서비스의 경로·인증 차단 확인과 격리 환경의 업무 성공 검증을 구분합니다. 서버 결과 확인 과정에서 새로운 결제·환불·고객 예약이나 시험 푸시를 실행하지 않았습니다.

## 2. QR 원문과 URL 처리

URL 뒤에 넣는 값은 차량 등록에 사용하는 **동일 QR 원문**입니다. 고객용·관리자용 식별 코드를 따로 만들지 않습니다. URL 뒤 값의 규격을 정하는 것은 원문 발급 기준에 관한 내용입니다.

예를 들어 다음과 같이 연결합니다. URL은 설명용이며 실제 발급 주소를 뜻하지 않습니다.

| 단계 | 값 |
| --- | --- |
| 차량 등록의 qrToken | `testQr123123` |
| QR 이미지에 담은 문자열 예시 | `https://example.com/vehicle#testQr123123` |
| 프론트가 추출한 원문 | `testQr123123` |
| 고객·관리자 API 입력 | `{"qrCode":"testQr123123"}` |

프론트는 발급한 QR 형식에 맞춰 원문을 추출하고 URL을 자동으로 열지 않습니다. 직접 입력도 같은 원문을 사용합니다. 서버는 받은 qrCode를 URL에서 다시 추출하지 않고 등록 원문과 비교합니다. QR 입력 때문에 별도 서버 매핑이나 추가 DB 변경은 필요하지 않습니다.

현재 API 원문 길이는 **1~4,096자**, 대소문자·공백을 그대로 구분합니다. 서버 조회를 위해 원문을 대문자/소문자로 바꾸거나 임의로 잘라 보내지 않습니다. 서버는 기존 HMAC-SHA256 해시 조회를 사용하므로 프론트가 DB 해시를 계산하거나 보내지 않습니다. QR은 차량 식별 수단이고 예약 권한은 로그인 고객·본인 예약·배정 차량으로 별도 검사합니다. 센서 없는 차량도 같은 QR 흐름을 사용합니다.

## 3. 고객 앱 연결

아래 고객 경로에는 모두 `/api/v1/nadree/rental` 접두사를 붙입니다. 기존 고객 `Authorization: Bearer <accessToken>`을 사용합니다.

| 메서드·경로 | 입력과 처리 |
| --- | --- |
| POST `/qr/lookup` | qrCode. 예약 상세에서 진입하면 reservationId도 전달. 차량·매장·본인 예약·availableActions 확인 |
| POST `/onsite/quote` | qrCode, returnDate. startDate·가격·통화·quoteToken·quoteExpiresAt 확인 |
| POST `/onsite/requests` | qrCode, returnDate, clientRequestId, quoteToken. 성공 응답의 item.reservationId/bookedNo 보존 |
| GET `/onsite/requests/{client_request_id}` | 결과 유실·앱 재시작 시 본인 접수 확인 |
| POST `/reservations/{reservation_id}/receive` | qrCode. 고객이 Receive motorcycle 버튼을 명시적으로 누를 때만 호출 |

기존 `/availability`, `/request`의 일반 사전 예약 당일 신청 금지는 유지합니다. 별도 현장 신청은 발리 당일 시작, 반납일은 다음 날부터 30일 뒤까지입니다. 스캔 차량에 고정하고 PICKUP으로 처리합니다. 가격·통화는 서버 견적을 표시하며 새 현장 신청에 온라인 결제를 연결하지 않습니다.

견적은 10분 유효하고 발리 날짜가 바뀌면 신규 접수에 사용할 수 없습니다. 제출 시 가격·재고를 다시 검사합니다. 신청 예시는 아래와 같으며 날짜는 실제 견적 응답에 맞춥니다.

```json
{
  "qrCode": "testQr123123",
  "returnDate": "2026-11-05",
  "clientRequestId": "11111111-2222-4333-8444-555555555555",
  "quoteToken": "<견적 응답의 quoteToken>"
}
```

clientRequestId는 고객별 유일한 **16~64자 소문자 영숫자·하이픈·밑줄**입니다. 소문자 UUID를 전송 전에 저장하세요. 같은 키·내용의 재요청은 같은 예약을 반환하며 내용 변경은 REQUEST_KEY_REUSED입니다. 성공한 접수는 견적 만료 후에도 같은 키로 확인할 수 있습니다. 조회 장애·5xx를 미접수로 판단해 다른 키로 중복 신청하지 않습니다.

신청 버튼 후 목록으로 이동하더라도 로컬 처리 중 항목과 서버가 접수한 REQUESTED 예약을 구분합니다. 기존 ongoing/completed/상세를 사용하고, QR 조회나 알림 선택만으로 인수를 완료하지 않습니다. 본인 예약 후보가 여럿이면 RESERVATION_SELECTION_REQUIRED에 따라 예약 선택 후 reservationId를 지정해 다시 조회합니다.

## 4. 관리자 앱 연결

기존 관리자 인증과 직접 소속 지점 권한을 사용합니다.

| 메서드·경로 | 연결 내용 |
| --- | --- |
| POST `/nadreego/booking/action` | 기존 APPROVE/REJECT 유지 |
| POST `/nadreego/vehicle/qr/validate` | 기존 qrCode 유지. data.currentBooking/currentRental/availableActions 확인 |
| POST `/nadreego/rent/approve` | 새 인수 흐름에서는 bookedNo, qrCode와 **receiptRequired=true** 전달 |
| POST `/nadreego/booking/{booked_no}/receipt-recovery` | 인수/회수 대기 차량·열쇠 실물 확인 후 qrCode, vehicleReturned=true, reason 전달 |
| POST `/nadreego/vehicle/return` | 고객 인수가 완료된 대여의 기존 반납 처리 |

```json
{
  "bookedNo": "BO<reservationId>",
  "qrCode": "testQr123123",
  "receiptRequired": true
}
```

기능 활성 시 관리자 인계 성공은 `data.reservationStatus=HANDOVER_PENDING`입니다. 이 단계에서 렌탈 계약이나 ON_RENT 화면을 만들지 않습니다. 기능 활성 상태에서 receiptRequired가 없는 구버전 인계 요청은 CLIENT_UPDATE_REQUIRED로 차단됩니다. 현재처럼 false인 상태에서 새 앱이 receiptRequired=true를 보내는 것도 차단하므로, 활성화 전에 성공 테스트로 판정하지 않습니다.

booking/select items[], 차량 목록 currentBooking, QR 검증 data.currentBooking, 캘린더 events[]에서 새 인수 필드를 사용합니다. 관리자 인계·일반 액션은 canHandOver/availableActions를 따르고, 회수 대기는 RECOVER_VEHICLE을 처리합니다. 회수 확인 전 일반 반납·취소·차량 이동·QR 해제 등으로 보호를 우회하지 않습니다. 기존 센서 위치 조회는 유지합니다.

## 5. 양쪽 앱의 상태·기한 표시

| 상황 | 예약 / 계약 | 화면 기준 |
| --- | --- | --- |
| 접수 | REQUESTED / 없음 | 승인 대기 |
| 관리자 승인 | APPROVED / 없음 | 인계 대기 |
| 관리자 인계 | HANDOVER_PENDING / 없음 | 고객 인수 대기 |
| 고객 인수 성공 | HANDED_OVER / ON_RENT | 대여 중 |
| 관리자 반납 | RETURNED / RETURNED | 반납 완료 |
| 인계 후 미인수 만료 | EXPIRED / 없음 | 차량 회수 필요. 대여 가능으로 표시하지 않음 |

`handedOverAt`은 관리자 인계 시각, `receivedAt`과 계약 actual_start_time은 고객 인수 확정 시각입니다. canReceive/receiptBlockedReason/receiptDeadline을 기준으로 고객 버튼과 안내를 표시합니다. `requestType=ONSITE`와 requestDeadline은 현장 신청의 구분·당일 마감을 나타냅니다.

모든 날짜 경계는 **Asia/Makassar(발리 UTC+8)**입니다. 현장 요청은 당일 승인·인계하고, 사전 예약은 시작일에 인계합니다. 인계일 다음 날 00:00부터 고객 인수는 불가능합니다. 만료 작업이 늦어도 API가 차단합니다. 인계 후 미인수 차량은 배정·DISABLED 보호를 유지하고, 차량·열쇠 실물 회수 확인 후에만 해제합니다. vehicleRecoveryRequired와 RECOVER_VEHICLE을 지원해 주세요.

기존 진행 중인 HANDED_OVER/ON_RENT 계약은 재인수를 요구하지 않습니다. 웹 상품 탐색은 기존 검색·일반 요청 API를 유지하며, 공통 예약 상태를 표시하는 화면이 있다면 HANDOVER_PENDING을 대여 중과 구분합니다.

## 6. 인수 안내 푸시

관리자 인계 커밋 후 고객에게 CUSTOMER_RECEIPT_REQUIRED를 발송합니다. 같은 인계 재시도로 안내 큐를 반복 생성하지 않으며, 기기 미등록·발송 실패가 인계 상태를 되돌리지 않습니다. 실제 기기 수신은 아직 별도 검증 대상입니다.

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

알림은 로그인 → 본인 예약 상세 재조회 → 현재 상태 화면으로 연결합니다. 알림 선택으로 receive를 자동 호출하지 않습니다. 지연 도착했거나 이미 인수/만료된 알림도 서버 최신 상태를 표시합니다. 푸시가 없어도 예약 목록·상세에서 인수할 수 있어야 합니다.

## 7. 테스트 시작 순서와 남은 작업

1. **현재:** Swagger/응답 모델 확인, 고객·관리자 앱의 원문 추출·호출·상태·버튼·재시도 구현을 진행합니다. 새 기능은 false이므로 신규 진입의 CUSTOMER_RECEIPT_NOT_ENABLED를 장애나 접수 성공으로 취급하지 않습니다.
2. 양 앱 준비 후 테스트 고객·직접 소속 관리자·해당일 사용 가능한 차량을 정하고, 승인된 테스트 환경의 기능 활성화를 요청합니다. 이번 서버 적용 작업에서는 true로 바꾸지 않았습니다.
3. 활성 환경에서 QR 조회 → 당일 견적 → clientRequestId 저장 → 신청 → 관리자 승인 → 관리자 인계 → 고객 인수 → 관리자 반납을 순서대로 확인합니다. 사전 예약도 시작일 인계 → 고객 인수 → 반납을 별도로 확인합니다.
4. 다른 고객/차량·인계 전 수령·중복 클릭·응답 유실·견적 만료/가격 변경·발리 자정 이후 차단·보호 차량의 재배정 금지·실물 회수를 확인합니다.
5. 실기기 푸시와 App Check, 지연 알림·알림 거부 상황을 공동 검증합니다. 백엔드의 전용 MySQL 동시성 10개·Firestore 4개도 별도로 완료합니다.

JSON의 QR·날짜·예약 ID는 형식 예시입니다. 예시 QR의 현재 재고·활성 상태나 과거 테스트 예약의 오늘 인계 가능성을 보장하지 않습니다. 특히 10월 29일 준비했던 예약은 11월 1일 반납 예정이었던 과거 기록이므로 신규 흐름의 현재 테스트 예약으로 바로 재사용하지 않습니다. 실제 테스트 날짜에 맞는 정상 요청으로 준비합니다.

상세 요청/응답·오류·복구 계약은 [통합 전달서](qr-onsite-receipt-handoff-2026-11-03.md), 실제 적용 시각·검증 증거·미검증 범위는 [서버 결과](qr-onsite-receipt-server-result-2026-11-03.md)를 기준으로 합니다. 이번 전달을 위해 서버 설정이나 업무 코드를 추가 변경하지 않았습니다.
