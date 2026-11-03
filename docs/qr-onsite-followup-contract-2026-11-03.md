# QR 현장 신청·고객 인수 추가 요청 처리 계약

2026-11-03 추가 인수서(`qr-onsite-backend-handoff (1).md`) 반영. **이 문서는 계약이며 실제 적용 증거는 별도 결과 문서를 따른다.** 사용자 양 앱 준비 확인 후 **07:35 UTC `254507d` 서버 전환을 완료**했다. 신규 테이블 적용·구 OFF env 제거·75개 경로/close 확인 및 시험 QR_ONLY 차량 2대 등록은 [최종 배포 결과](qr-onsite-final-server-deployment-result-2026-11-03.md)에 정리했다. [기존 결과](qr-onsite-receipt-server-result-2026-11-03.md)의 false는 이전 코드 적용 이력이며, 실제 앱 공동 시험은 계속 별도다.

## 1. 확정된 동작과 변경 범위

일반 예약과 현장 신청 모두 관리자 앱 인계 절차 완료 → HANDOVER_PENDING → 관광객의 명시적 receive → HANDED_OVER/ON_RENT를 사용한다. 관리자 절차 완료가 실제 차량·열쇠 전달 확인을 대신하지 않는다. 관리자 완료 시각은 handedOverAt, 고객 수령 확정·실제 계약 시작 시각은 receivedAt/actual_start_time이다. 기한·실물 회수·외부 수납 정책은 유지한다.

NADREE_CUSTOMER_RECEIPT_ENABLED 설정과 즉시 대여 전환 분기를 제거했다. 오래된 env에 false가 남아 있어도 새 코드는 이를 끄기 설정으로 사용하지 않는다. receiptRequired=true 요청 필드는 유지하며 누락은 409 CLIENT_UPDATE_REQUIRED다. 기존에 이미 ON_RENT였던 계약은 재인수를 요구하지 않는다. 기존 PAYPAL 거래의 결제 상태 재검증·환불 경로는 보존한다.

사용자 확인에 따라 **MSP_RENTAL_ONSITE_REQUEST 1개 테이블**을 추가했다. 과거 요청 결과 테이블 제외 방침에 대한 이번 예외이며, 확정 거절된 키의 늦은 요청을 차단하기 위한 기록이다. 기존 예약 3컬럼·QR/결제 구조를 다시 바꾸지 않는다. 로컬에서는 실제 DB 적용·설정 변경·재시작·테스트 데이터 쓰기를 실행하지 않았다.

## 2. QR 원문 발급·전달

실제 발급 원문은 고정 대문자 접두사 `NDR-` + 대소문자를 구분하는 영문·숫자 8자리, 총 12자다. 예: **NDR-Ab12Cd34**. `NDR-ab12Cd34`는 다른 원문이다.

- QR 이미지에는 유효한 HTTP(S) URL 뒤 `#NDR-Ab12Cd34`처럼 전체 원문을 넣는다. 원문을 퍼센트 인코딩하지 않는다. `example.com`은 형식 예시이며 실제 발급 도메인은 프론트의 발급 주소를 사용한다.
- 두 앱은 URL의 `#` 뒤 전체 값을 추출하고 직접 입력도 같은 값을 사용한다. API에는 `{"qrCode":"NDR-Ab12Cd34"}`를 보낸다. 차량 등록은 같은 원문을 qrToken에 넣는다.
- 과거 시험 QR은 앱 호환 대상이 아니다. 새 규격 테스트 QR/차량을 준비한다. 등록 요청 준비 파일은 [onsite-qr-test-requests.json](../deployment/onsite-qr-test-requests.json)이다. 이 파일은 실행 결과나 QR 발급 완료 증거가 아니다. 대상 지점·현재 모델 이름·중복 여부를 확인하고 승인된 테스트 환경에서 body만 실제 등록 API에 전달한다. sensorId 없는 QR_ONLY 차량 2대용이며 가격은 기존 BASE/BASIC을 사용한다.
- 서버의 원문 입력 1~4,096자와 HMAC-SHA256/64자 해시 저장은 유지한다. 새 12자 규격은 실제 발급 기준이며 서버 입력을 임의로 URL 디코딩·대소문자 변환하지 않는다. 실제 인쇄/스캔·두 앱 인식은 공동 검증 대상이다.

## 3. 신청 결과 — 예약 상태와 요청 상태를 구분

고객 경로 접두사: `/api/v1/nadree/rental`. 기존 고객 Bearer 인증을 사용한다. POST `/onsite/requests`의 필수 입력은 기존 qrCode·returnDate·clientRequestId·quoteToken 그대로다. **재시도에는 quoteToken까지 같은 원본 본문을 보존한다.** 요청 키는 고객 UID별 16~64자 소문자 영숫자·`_`·`-`이며 소문자 UUID를 권장한다.

requestStatus는 신청 접수 결과다. ACCEPTED는 예약이 접수됐다는 뜻이며 관리자 APPROVED나 대여 시작을 뜻하지 않는다. 실제 예약 진행 상태는 item.reservationStatus와 item.rentalStatus다.

| requestStatus | 의미 | requestFinal | canStartNewRequest | 앱 처리 |
| --- | --- | --- | --- | --- |
| ACCEPTED | 해당 키의 예약이 존재 | true | false | item의 예약을 표시. 중복 신규 신청으로 바꾸지 않음 |
| REJECTED | 키가 영속적으로 거절/종료됨. 이 키로 나중에 예약 생성 불가 | true | true | 기존 처리 중 항목 정리 후 필요 시 새 견적·새 키 |
| PROCESSING | 같은 키의 처리 잠금을 다른 요청이 보유 | false | false | 키·원본 본문 보존, 잠시 뒤 같은 키로 확인 |
| UNKNOWN | 아직 기록 없음, 중단된 처리, 조회 장애 등으로 결과를 확정할 수 없음 | false | false | 성공/거절로 표시하지 않고 키 유지, 결과 조회·동일 본문 재시도 또는 명시적 종료 |

retrySameRequest는 REJECTED에서 false, 그 밖에는 기본 true다. 이미 접수된 키에 다른 본문을 보낸 REQUEST_KEY_REUSED는 retrySameRequest=false다. 오류 응답에 결과 필드가 없는 401/422/429/5xx·비JSON 응답·통신 장애도 확정 거절로 해석하지 않는다. 인증 갱신이나 입력 정정이 필요해도 기존의 불명 요청을 새 키로 무조건 바꾸지 않는다.

**전환 중 구서버의 CUSTOMER_RECEIPT_NOT_ENABLED:** 구버전은 해당 검사를 예약 생성 전에 실행하며 그 HTTP 호출을 나중에 예약으로 처리하는 작업도 만들지 않는다. 이전에 같은 키를 보낸 적 없는 최초 단일 전송이라는 조건에서는 그 호출의 미생성을 보장한다. 다만 구서버는 키의 영속 거절을 남기지 않으므로 다른 지연 요청까지 영구 차단하는 결과는 아니다. 이전에 결과 불명·중복 전송이 있었다면 현재 앱처럼 키를 유지해야 한다. 새 최종 코드에서는 이 오류와 설정이 제거됐고, 키 종료 보장은 저장된 REJECTED 또는 close의 확정 결과로 제공한다.

### 경로별 HTTP 계약

| 요청 | HTTP·응답 | 의미 |
| --- | --- | --- |
| POST `/onsite/requests` | 200 ACCEPTED + item | 접수 성공 또는 같은 본문의 성공 재시도 |
| POST `/onsite/requests` | 202 PROCESSING, item=null, Retry-After: 2 | 처리 경합. 접수 성공/확정 거절 아님 |
| POST `/onsite/requests` | 400/404/409/410/422 + REJECTED·requestFinal=true | 해당 업무 거절을 저장한 뒤 응답. 이후 같은 키는 거절 유지 |
| GET `/onsite/requests/{client_request_id}` | 200 ACCEPTED + item | 본인 접수 결과 |
| 같은 GET | 200 REJECTED, item=null, errorCode | 저장된 확정 거절. HTTP 200만으로 접수 성공으로 판정하지 않음 |
| 같은 GET | 202 PROCESSING, Retry-After: 2 | 처리 중 |
| 같은 GET | 404 ONSITE_REQUEST_NOT_FOUND + UNKNOWN | 조회 시점에 기록 없음. 늦은 POST의 생성 가능성을 배제하지 않음 |
| 같은 GET | 503 ONSITE_REQUEST_OUTCOME_UNKNOWN + UNKNOWN | 처리 의도는 있으나 실행이 중단돼 결과를 확정할 수 없음 |
| 모든 경로 | 5xx·통신 장애 | UNKNOWN으로 취급. 커밋 후 응답 유실일 수도 있음 |

업무 거절 예시: 견적 만료 `409 ONSITE_QUOTE_EXPIRED`, 가격 변경 `409 ONSITE_QUOTE_CHANGED`, 차량/재고 이용 불가 `409 VEHICLE_UNAVAILABLE`. 차량 불가와 배정 솔버의 재고 충돌은 현재 같은 VEHICLE_UNAVAILABLE을 사용한다. QR 미등록404·비활성409·만료410, 날짜 범위422도 저장된 REJECTED라면 확정 거절이다. Pydantic 입력 검증 422 INVALID_INPUT은 기록 전에 반환될 수 있으므로 상태 필드 없이 이를 키 종료로 판단하지 않는다.

```json
{
  "status": "fail",
  "errorCode": "ONSITE_QUOTE_EXPIRED",
  "clientRequestId": "11111111-2222-4333-8444-555555555555",
  "requestStatus": "REJECTED",
  "requestFinal": true,
  "retrySameRequest": false,
  "canStartNewRequest": true
}
```

성공 후 견적 만료·발리 날짜 변경이 있어도 기존 키의 조회/같은 본문 재전송은 같은 예약이다. 결과 테이블 도입 이전에 접수된 예약도 기존 고객+키로 확인한다. 보장 범위는 같은 서비스 DB·고객 UID이며, 앱의 테스트/실데이터 환경별 요청 보관도 구분한다. 불명 요청을 다른 환경에 새 신청으로 재전송하지 않는다. 결과는 TTL로 삭제하지 않으며 예약·이력과 함께 보존한다. QR 원문·견적 토큰은 결과 테이블에 저장하지 않고 본문 지문만 저장한다. 임의 키 재사용이나 운영 중 테이블 비우기는 허용하지 않는다.

### 결과 불명 요청을 확정 종료하는 추가 API

**POST `/onsite/requests/{client_request_id}/close`**, 본문 없음. 기존 인증을 사용한다. 조회 GET은 키를 닫지 않으며, 닫으려는 고객의 명시적 선택에 이 POST를 사용한다.

- 아직 예약이 없다면 해당 키를 영속 REJECTED/ONSITE_REQUEST_CLOSED로 종료한다. 응답 이후 늦게 도착한 최초 요청이나 재시도도 이 키로 예약을 만들 수 없다.
- 이미 접수됐다면 200 ACCEPTED와 기존 item을 반환한다. 예약을 취소하지 않는다. 실제 예약 취소는 기존 고객 취소 API를 사용한다.
- 같은 키를 처리 중이면 202 PROCESSING이다. 확정 종료로 표시하거나 새 키로 바꾸지 않는다.
- 응답이 유실되면 GET 결과 또는 같은 close를 재시도한다. close는 멱등이며 다른 고객의 키에는 영향을 주지 않는다.

404·결과 불명 뒤 새 신청으로 바꾸려면 **close의 REJECTED/requestFinal=true**를 확인한다. 그 후 새 견적·새 clientRequestId를 발급한다. 기존 신청을 이어가려면 키와 원래 quoteToken을 유지해 조회/재시도한다.

## 4. 관리자 응답 위치와 식별자

Swagger의 각 경로 200 응답에는 요청·승인·인수 대기·만료 회수·대여 상태의 named examples를 추가했다. 예시는 화면 연결에 필요한 상태별 필드 중심이며 실제 공통 응답은 기존 계약을 따른다.

| 화면·API | 레코드 위치 | 이번 보완 |
| --- | --- | --- |
| 예약 목록/예약번호 상세 `POST /nadreego/booking/select` | items[] | 최상위 reservationId/vehicleId 추가. 기존 reservation.reservationId·vehicle.vehicleId·bookedNo 유지 |
| 홈 `GET /nadreego/main` | todayWork[] | 목록과 같은 requestType·인수/회수 필드·availableActions·canHandOver·reservation/rental/vehicle 제공. 기존 startAt·vehicleId 유지 |
| 캘린더 `POST /nadreego/main/calendar` | items[].events[] | 기존 계층 유지. event.status가 예약/대여 상태이며 reservationId·bookedNo·인수 필드·액션 사용 |
| 차량 목록 `POST /nadreego/vehicle/select` | items[].currentBooking | reservationId·vehicleId 추가. 예약 없으면 null |
| 차량 QR `POST /nadreego/vehicle/qr/validate` | data.currentBooking | 위 currentBooking과 같은 구조. data.vehicleId/data.vehicle·data.currentRental도 유지 |

예약 레코드의 requestType은 ADVANCE/ONSITE이며 기존 요청은 ADVANCE다. requestDeadline은 현장 신청일 마감이고 사전 예약은 null이다. handedOverAt·receiptDeadline·receivedAt은 단계 전이면 null, vehicleRecoveryRequired는 boolean이다. canHandOver와 availableActions는 표시 시점의 서버 검증 결과다. 동시 변경이 가능하므로 쓰기 요청에서 다시 검증한다.

| 상황 | 예약 레코드 액션 | 필요한 식별·판정 |
| --- | --- | --- |
| REQUESTED | APPROVE / REJECT | reservationId, BO bookedNo |
| APPROVED | RENT_APPROVE가 있고 canHandOver=true일 때 인계 | reservationId, BO bookedNo, vehicleId |
| HANDOVER_PENDING·실물 미회수 EXPIRED | RECOVER_VEHICLE | 같은 식별자와 차량·열쇠 회수 확인 |
| ON_RENT/OVERDUE 계약 | RETURN | vehicleId, rental.rentalContractId, rentalStatus |

currentBooking의 availableActions는 예약 액션이며 차량 목록 최상위 availableActions는 차량 변경 액션이다. QR의 data.availableActions는 보호 중 RECOVER_VEHICLE을 제공한다. 캘린더의 회수 보호 이벤트는 endAt=null/endAtType=OPEN/isBlocking=true이며 원래 예약 기간 뒤에도 보호 표시를 유지한다. 홈도 과거 미회수 보호 예약을 누락하지 않는다.

## 5. 고객 인수·관리자 차단 응답

고객 receive는 기존 POST `/reservations/{reservation_id}/receive`, 입력은 qrCode다. 본인 예약·정확한 배정 차량·관리자 절차 완료·현재 QR 상태·발리 기한을 매번 확인한다. 성공 후 중복 요청은 같은 계약이다.

| HTTP·errorCode | 의미·앱 안내 |
| --- | --- |
| 404 RESERVATION_NOT_FOUND | 본인 예약을 찾지 못함. 다른 고객의 존재 여부를 노출하지 않음 |
| 404 QR_NOT_FOUND | 등록 QR 원문을 찾지 못함 |
| 409 RESERVATION_VEHICLE_MISMATCH | 배정 차량과 다름. 올바른 차량 확인 |
| 409 NOT_AWAITING_RECEIPT | 관리자 처리 전 또는 취소/반납 등 인수 대상 상태가 아님 |
| 409 RECEIPT_DEADLINE_EXPIRED | 인계일 다음 발리 자정부터 인수 불가. 만료 작업 전후 모두 같은 기한 오류 |
| 409 QR_INACTIVE / 410 QR_EXPIRED | QR 활성·만료 상태 확인 필요 |
| 409 RECEIPT_HOLD_INCONSISTENT | 서버 보호 상태가 일치하지 않음. 인수 성공으로 표시하지 않고 운영 확인 |

```json
{"status":"fail","errorCode":"RECEIPT_DEADLINE_EXPIRED"}
```

고객 앱은 기존처럼 동일 예약·HANDOVER_PENDING·canReceive=true·vehicleMatch=ASSIGNED·CONFIRM_RECEIPT를 확인하고 버튼에서만 receive를 보낸다. 오류·응답 유실 때 성공으로 표시하지 않는다. GET `/reservations/{reservation_id}`의 본인 최신 상태가 최종 기준이다. 현재 앱이 자동 조회하지 않는 경로에서는 사용자가 상세 새로고침으로 확인할 수 있게 안내한다. 이번 서버 변경이 앱에 자동 조회를 추가하는 것은 아니다.

관리자 일반 취소/승인/거절의 상태 불일치는 409 RESERVATION_STATE_INVALID, 보호 차량 일반 반납·이동·QR 해제 등은 409 VEHICLE_RECEIPT_HOLD다. 인수 대기에서 같은 bookedNo·QR·receiptRequired=true로 관리자 절차를 재요청하면 기존 기한을 반환한다. 고객의 인수 기한을 연장하거나 계약을 중복 생성하지 않는다. 회수 대상 아님은 NOT_AWAITING_RECOVERY, 다른 QR은 RESERVATION_VEHICLE_MISMATCH, 보호 데이터 불일치는 RECEIPT_HOLD_INCONSISTENT다. 오류 후 booking/select의 bookedNo 상세나 QR/currentBooking·캘린더를 다시 조회해 판단한다.

검사 순서에 따라 QR/차량 오류가 상태 오류보다 먼저 반환될 수 있다. 예를 들어 배정 전 receive는 차량 불일치로 차단될 수 있고, 이미 EXPIRED로 바뀐 보호 차량의 관리자 재인계는 VEHICLE_UNAVAILABLE일 수 있다. 인수·재인계 성공으로 추정하지 말고 본인/관리자 상세의 최신 상태와 허용 액션을 기준으로 안내한다.

## 6. 전환·공동 검증

receiptRequired=true는 그대로 유지한다. 양 앱에 별도 빌드 플래그를 추가하지 않는다. 새 백엔드는 설정 OFF로 즉시 대여를 복구하지 않는다. 구버전 관리자의 필드 누락 요청은 계속 CLIENT_UPDATE_REQUIRED로 차단한다.

차단 범위는 인계 쓰기 프로토콜이다. 새 앱 버전 헤더로 로그인·조회 전체를 차단하는 기능은 추가하지 않는다. 인계는 필수 필드와 최신 상태 처리 계약을 지원하는 앱에서 수행한다.

앱과 서버를 맞춘 배포 순서·기존 env 정리·신규 결과 테이블·복구 제한·검증 명령은 [서버 적용 실행서](qr-onsite-final-server-apply-2026-11-03.md)를 따른다. 앱 공동 시험과 전환 완료를 확인한 배포 시점에 새 코드를 적용한다. 소스를 pull했다는 사실만으로 새 기능 운영 활성화나 실제 양 앱 인수를 완료했다고 표시하지 않는다.

## 7. 로컬 검증 결과

전체 격리 회귀 **588 passed / 15 skipped / 0 failed**. 제외는 전용 MySQL 11개(신청/인수/종료 경합 포함)와 Firestore 에뮬레이터 4개다. 기존 라이브러리·테스트 대역 경고 14개는 별도다. 확정 거절 후 지연 생성 차단, close 경합의 API 계약, 처리 도중 예약 쓰기 롤백과 재시도, 기존 접수의 결과 복구, 고객 간 키 격리, 상시 인수, 관리자 홈/QR 식별자·회수 대기 표시를 검사했다. 실제 MySQL 경합과 기기 인수는 이 결과로 대체하지 않는다.
