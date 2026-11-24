# 프론트 요청 처리 결과 — 예약·Walk-in·인계

2026-11-24 후속 개정. 기준은 `134cc08` 이후 로컬 변경이다. **코드·Swagger·격리 검증 기준이며, 운영 서버 적용 완료 보고가 아니다.** 서버 적용은 [적용 안내](handover-server-apply-2026-11-24.md)를 따른다. 요청 원본과 확정 기획은 프로젝트 상위 폴더에 보관한다.

## 반영 범위

| 요청 | 처리 결과 |
| --- | --- |
| 날짜·자동 종료 | 발리 날짜, 종료일 포함, 미승인 `NO_RESPONSE`, 미픽업 `EXPIRED`, 실제 렌트의 다음 날 `OVERDUE` |
| 알림 | 발리 09:00 예약일·반납일·첫 연체일 알림, 동일 이벤트/날짜 중복 방지, 인계 시작·폼 제출·고객 완료 알림 제거 |
| 지점 | 계층 응답 `directVehicleCount`, `includeSelf`, 비활성 부모의 하위 지점도 유효 비활성 |
| QR·최근 내역 | 전역 사용 여부 재검증 유지, 타 지점 상세 비공개, 시작일 역순 최근 3건과 과거 배정 포함 |
| Walk-in | 새 응답은 `WALK_IN`, 기존 `ONSITE`는 읽기 호환, 당일 반납 1일 허용 |
| 가격 | 승인 `finalPrice` 하나, USD 고정, 배송비·보증금 포함 전체 금액. 확정된 인계 가격은 차량 가격 변경과 분리 |
| 정비·간편대여 | 종료일과 최종 QR 일치 검증. 정비는 기간 종료 후 해제, 간편대여는 실제 QR 반납 전까지 점유 |
| 인계 기록 | 기존 폼·자료·양측 상태, 렌탈 당시 SNS 보존, 동의 완료 시각·본인·인계 ID 반환 |
| 저장소 | 비공개 S3 직접 업로드·실파일 검증·임시 GET URL 재발급. 네이티브 앱에 웹페이지 추가 불필요 |
| 고객 계정 없는 대여 | **사용자 최종 정정에 따라 이력 저장 안 함.** 고객·예약·계약·계약 이력 행을 만들지 않음 |

새 REST 경로는 차량 최근 이력 조회 1개다. 나머지는 기존 경로의 입력·응답·검증 및 배치를 보완했다. 렌트 연장·주소 경계 판정·추가 결제 기능은 이번 범위에 추가하지 않았다.

## 날짜와 화면 상태

업무 시간대는 `Asia/Makassar`다. `startDate`와 `returnDate`가 같으면 1일이며 일수는 `returnDate - startDate + 1`이다. 신규 견적은 이 기준을 사용하며 기존 저장 견적을 일괄 재계산하지 않는다.

| 조건 | 서버 응답·동작 |
| --- | --- |
| 미승인, 시작일 다음 날~종료일 | `REQUESTED`, `latePickupWarning:true`. 유효 기간·재고 등 검증을 통과한 승인 또는 기존 거절 가능 |
| 미승인, 종료일 다음 날 00:00부터 | `NO_RESPONSE`, 배정 해제, 승인·거절·고객 취소·인계 불가 |
| 승인/구 고객 인수 대기, 종료일까지 | `APPROVED` / `HANDOVER_PENDING` 유지. 시작일 이후 지연 픽업 경고 |
| 승인/구 고객 인수 대기, 종료일 다음 날부터 | `EXPIRED`, 미회수 배정은 유지, `vehicleRecoveryRequired:true`, `RECOVER_VEHICLE` |
| 실제 인계 완료, 종료일 당일 | 예약 `HANDED_OVER`, 대여 `ON_RENT` |
| 실제 인계 완료, 종료일 다음 날부터 미반납 | 예약 `HANDED_OVER`, 대여 `OVERDUE`, `RETURN` 유지 |
| 실제 반납 성공 | 예약·계약 `RETURNED`, 실제 반납 시각으로 점유 종료 |

`latePickupWarning`은 고객 목록·상세·QR 및 관리자 예약/차량/캘린더의 해당 예약 정보에 사용한다. 새 인계의 시작 가능 여부는 `canStartRental`/`canHandOver`와 차단 사유로 판단한다. 날짜가 유효하다는 것만으로 필수 폼·영상·사진·동의 검사를 생략할 수 없다.

조회는 날짜에 따른 유효 상태를 계산하고, 쓰기는 지점 잠금 아래 최신 날짜·상태를 다시 검사한다. `app.jobs lifecycle`은 매분 저장 상태를 정리한다. 서버가 중단됐다면 다음 실행에서 지난 종료일을 정리하며 앱 실행에 의존하지 않는다. 자정 정각 실행 보장은 아니며 정상 배치는 보통 1분 이내, 쓰기/조회는 배치 지연 중에도 기간을 검사한다.

과거 `EXPIRED` 중 마지막 만료 직전 상태가 `REQUESTED`이고 승인 이력이 없으며 실제 인계 시각도 없는 건만 `--backfill-no-response`로 바꾼다. 증빙이 없는 옛 만료 건을 임의 전환하지 않는다. 이 일괄 작업에는 종료 알림·오전 알림이 없다.

### 미픽업 회수

기존 `POST /nadreego/booking/{booked_no}/receipt-recovery`를 재사용한다. 직접 소속 지점 관리자만 가능하다.

```json
{"qrCode":"NDR-Ab12Cd34","vehicleReturned":true,"reason":"Vehicle and keys physically checked"}
```

만료 건은 회수 후에도 `EXPIRED`를 유지하고 배정과 해당 예약의 보호만 해제한다. `vehicleRecoveryRequired:false`를 반환한다. 다른 진행 렌트가 있으면 `409 RECEIPT_HOLD_INCONSISTENT`로 막고, 다른 정비·간편대여·별도 보호는 보존한다. 따라서 응답 `vehicleStatus`가 항상 `AVAILABLE`인 것은 아니다. 물리적 회수 API는 만료 건의 환불을 새로 요청하지 않는다. 앱 밖 수납·환불은 지점 업무다. 기간 내 구 `HANDOVER_PENDING` 회수 취소의 기존 정책은 유지한다.

## 알림과 재접속

| 이벤트 | 시점 | 대상 |
| --- | --- | --- |
| `RESERVATION_REQUESTED` | 접수 즉시 | 직접 지점 활성 관리자 |
| `RESERVATION_START_UNAPPROVED` | 시작일 발리 09:00 | 관리자 |
| `RESERVATION_PICKUP_DUE` | 시작일 발리 09:00 | 승인됐으나 미인계인 고객 |
| `RENTAL_RETURN_DUE` | 실제 렌트 종료일 발리 09:00 | 관리자·고객 |
| `RENTAL_OVERDUE_STARTED` | 종료일 다음 날 발리 09:00 | 관리자 |
| `UNTRACKED_RETURN_DUE` / `UNTRACKED_OVERDUE_STARTED` | 간편대여 종료일 / 다음 날 발리 09:00 | 관리자 |

`HANDOVER_STARTED`, `HANDOVER_FORM_SUBMITTED`, `HANDOVER_CUSTOMER_COMPLETED`는 FCM·업무 알림 모두 생성하지 않는다. 예약 승인/거절 안내, 구 인수 확인 요청, 수정 제안 관련 알림은 기존 동작을 유지한다. 수정 제안 UI는 후속 앱 업데이트에서 사용해도 된다.

동일 대상·이벤트·발리 날짜를 기존 이력/알림 키로 중복 방지한다. 실제 발송과 재시도 직전에 상태·종료일·수신 토큰을 재확인해 취소·반납·기간 변경으로 유효하지 않은 푸시는 보내지 않는다. 09:00 이후 새로 생성한 Walk-in/대여에는 이미 지난 오전 알림을 소급하지 않는다. 당일 배치 지연은 당일 안에서 따라잡으며 지난 날짜 알림은 재발송하지 않는다.

FCM의 기기 전달이나 외부 전송의 정확히 1회 전달을 보장하는 것은 아니다. 기존 제한 재시도를 사용하며, 앱은 `eventId`가 있는 오전 알림을 중복 표시하지 않고 `reservationId`/`bookedNo`/`rentalContractId`/`vehicleId`로 상세를 재조회한다. 관리자 업무 알림은 기존 `/nadreego/notifications` 목록·개수·읽음 API로 확인하며 읽음은 지점 공통이다. 고객용 새 알림함 API는 추가하지 않았다.

## 지점·QR·최근 렌탈

`GET /api/v1/organizations/spots/hierarchy`는 기본적으로 본인 제외 모든 하위 계층을 반환한다. `includeSelf=true`는 본인 포함, `is_active=-1/0/1`은 전체/유효 비활성/유효 활성이다. 기존 `offset`, `limit`, `search`, `unit_type`, `has_manager` 필터를 유지한다.

각 항목의 `directVehicleCount`는 현재 직접 소속 링크가 있는 렌탈 차량의 고유 ID 수다. 정비·비활성 차량을 포함하고 해제 링크·삭제 차량·하위 지점의 차량을 제외한다. `parentSpotMasterId`와 기존 권한 필드를 유지한다. 비활성 부모 아래는 저장된 자식 플래그와 관계없이 비활성으로 응답·취급한다. 권한·조회 실패를 0대로 대체하지 않는다.

QR 등록 가능 여부는 `POST /nadreego/vehicle/qr/availability`의 `assignment: OWN_SHOP / OTHER_SHOP / UNASSIGNED`와 `canRegister`로 판단한다. 기존 비활성·만료 QR 행도 자동으로 재사용 가능하다고 보지 않는다. `OTHER_SHOP`에는 타 지점명·차량번호·고객 정보를 넣지 않는다. 등록 시 전역 잠금·유일성 검사를 다시 수행한다.

본인 지점 차량은 기존 `POST /nadreego/vehicle/qr/validate`의 `data.recentRentals` 또는 새 `GET /nadreego/vehicle/{vehicle_id}/rental-history`로 최근 3건을 조회한다. 미래 예약·진행·완료·취소를 포함하며 시작일 내림차순, 동률이면 `bookedNo` 내림차순이다. 배정 변경 전 차량에 연결된 이력도 포함하고 `vehicleAssociation:PREVIOUS_ASSIGNMENT`로 구분한다. 현재 연결은 `CURRENT`다. 고객 계정 없는 대여는 기록하지 않으므로 이 목록에 없다. 새 GET은 직접 지점 외 차량/미존재 차량 모두 `404 VEHICLE_NOT_FOUND`다.

## 정비·고객 계정 없는 간편대여

최종 제출에 QR을 다시 보내고 차량번호와 일치하는지 확인한다. 화면에서 조회한 `stateVersion`과 새 UUID `clientRequestId`를 보내며, 응답 유실 시 새 UUID로 재요청하지 않는다. 현재 상태를 재조회하고 같은 요청을 재시도한다.

```json
{
  "vehicleNumber":"TEST-125", "action":"START", "endDate":"2026-11-28",
  "qrCode":"NDR-Ab12Cd34", "clientRequestId":"b86244b4-2f68-41fa-98c2-8d356189e1b8",
  "expectedStateVersion":0
}
```

경로는 `POST /nadreego/vehicle/untracked-rent`다. 오늘 종료도 허용하며 과거 종료일은 거절한다. 기존 예약·실제 대여·정비·회수 보호와 충돌하면 실패한다. 성공 시 현재 `untrackedRentId`와 증가한 `stateVersion`을 반환한다.

```json
{"vehicleNumber":"TEST-125","action":"END","qrCode":"NDR-Ab12Cd34","untrackedRentId":"b86244b4-2f68-41fa-98c2-8d356189e1b8","vehicleReturned":true}
```

END 또는 기존 `POST /nadreego/vehicle/return`에 같은 QR·`untrackedRentId`·`vehicleReturned:true`를 보내 실제 반납한다. 이전 대여 ID로 새 대여를 종료할 수 없다. 종료일이 지나도 현재 상태는 `UNTRACKED_RENT`, 표시용 `rentalStatus:OVERDUE`이며 실제 반납 전까지 점유한다. 미래 예약은 예정 종료일 다음 날부터 접수할 수 있지만 미반납 당일 신규 대여/인계는 차단한다. 필요하면 기존 차량 변경 API로 다른 적합 차량에 재배정하고 지점에서 고객에게 안내한다.

정비는 `POST /nadreego/vehicle/repair`에 기존 `vehicleNumber`, `date`, `reason`과 **`qrCode`, `clientRequestId`, `expectedStateVersion`**를 보낸다. 종료일 다음 날 서버 배치로 해제한다. 현재 작업 ID·상태 버전은 차량 상태 행에만 보관하며 **간편대여·정비 이력이나 영구 요청 결과 저장소는 추가하지 않는다.** 따라서 과거 모든 요청의 영구 재전달을 약속하지 않는다. 완료 후 오래된 START도 버전이 달라지면 재실행하지 않는다.

## 승인과 새 인계 흐름

1. 고객이 차량 선택/QR → Walk-in 견적·요청. 사전예약은 기존 요청 API를 사용한다. 새 값은 `WALK_IN`이지만 URL의 `/onsite`는 유지한다.
2. 관리자 `POST /nadreego/booking/action`: `{"bookedNo":"BO...","action":"APPROVE","finalPrice":75}`. `currency`는 보내지 않는다. USD 정수 0~2,147,483,647이며 전체 수납액이다. 앱은 종료일 포함 일수×일일금액, 보증금 0으로 기본값을 표시할 수 있다. 승인된 값에 배송비를 다시 더하지 않는다.
3. 승인 시 인계 준비 행을 만들고 고객만 기존 `/reservations/{reservation_id}/handover`로 실제 시작한다. 먼저 사진 업로드/검토 시작을 한 관리자를 담당자로 고정한다.
4. 고객 폼 PATCH → submit → 실제 영상 업로드/complete → signature/complete. 여권번호·숙소·헬멧 수 필수, 헬멧 0 허용. 면허번호·SNS는 선택이다. 폼 PATCH에서는 부분 저장을 허용하고 submit에서 필수값을 검사한다.
5. 관리자 `EXTRA_PHOTO`는 **고객이 차량 옆에 서 있는 사진**으로 필수다. 여권·면허 사진은 선택이다. 서버는 사진 형식·크기·업로드 완료를 확인하며 사진 장면을 자동 판별하지 않는다. 폼 제출 후 담당자가 확인할 수 있다.
6. 양측 완료·필수 자료·동의·기간·최신 재고 검사를 모두 통과하면 담당자만 기존 `/nadreego/rent/approve`로 실제 렌트를 시작한다.

상세의 `form`, `finalPrice`, `handover`, `media`와 기존 예약 ID/`BO...` 식별을 유지한다. 인계 시작 전에는 번호가 프로필에서 보이고 폼 저장 시 회원번호·SNS도 함께 갱신한다. 폼 제출 시 **SNS는 해당 인계에 암호화 보존**하며 이후 프로필 SNS 변경으로 과거 렌트 값을 바꾸지 않는다. 미제출 폼은 현재 프로필을 미리 보여줄 수 있다.

서명 이미지/필기는 받지 않는다. `signatureStatus`, `signatureCompletedAt`, `signatureActorUid`, `signatureHandoverId`로 완료 사실·행위자·시각·대상을 확인한다. 폼 버전·동의 버전·별도 수정안 ID는 추가하지 않았다. 관리자 수정안을 거부하면 인계만 취소하고 `restartHandoverId`로 재시작하며 예약·가격은 유지한다.

### 네이티브 앱 사진·영상

기존 인계 `media/uploads` API에 `clientFileId`, 종류, MIME, 크기를 보내면 `url`과 `fields`를 받는다. **모든 fields와 파일을 multipart POST로 S3에 직접 전송**하고 API의 해당 업로드 `complete`를 호출한다. 2단계 업로드가 끝나야 READY다. 영상은 MP4 최대 50MiB·10초, 사진은 JPEG/PNG/WebP 최대 10MiB다. 서버는 실제 파일의 크기·형식과 영상 최대 10초를 검사하고 확정 비공개 키로 복사한다. 같은 완료 재요청은 저장 결과를 재사용한다.

자료 조회 API의 임시 URL로 사진/영상을 표시한다. URL을 DB/프로필에 영구 저장하지 않고 만료되면 API에서 재발급한다. 네이티브 HTTP 업로드에는 브라우저 CORS 설정이 필요 없다. 웹 관리자나 WebView JavaScript에서 직접 업로드할 때만 S3 버킷 CORS와 실제 프론트 origin을 별도로 설정한다.

## 오류·복구와 적용

| HTTP / errorCode | 처리 |
| --- | --- |
| 401 인증 오류 | 기존 로그인/갱신 절차 |
| 403 권한 오류 / 404 소유 범위 외 객체 | 화면 권한·소속 재확인, 객체 존재 추정 금지 |
| 409 `RESERVATION_STATE_INVALID` | 목록·상세 새로고침, 같은 작업 강제 반복 금지 |
| 409 `VEHICLE_RECEIPT_HOLD` | 실물 확인 후 회수 절차 |
| 409 `VEHICLE_STATE_CHANGED` / `UNTRACKED_RENT_CHANGED` | QR·현재 작업 ID·상태 버전 재조회 |
| 409 `REQUEST_KEY_REUSED` | 같은 키에 다른 내용 금지 |
| 409 `HANDOVER_NOT_READY` / `MEDIA_NOT_READY` | 최신 진행 상태·필수 자료 확인 |
| 422 `INVALID_INPUT` | 필수값·범위·폐기된 입력 필드 수정 |
| 503 PII/미디어/외부 서비스 오류 | 동일 식별자로 현재 결과 확인 후 재시도, 신규 요청 남발 금지 |

전체 고정 오류 정의는 프로젝트의 `rental-api-error-codes-2026-11-24.md`와 구현 JSON을 사용한다. 예시는 가상 값이다. 앱 종료·뒤로 가기만으로 취소하지 않는다. Walk-in 접수 응답이 유실되면 기존 request-outcomes 조회/close 계약, 인계는 기존 ID 상세 조회, 간편대여/정비는 QR·상태 버전으로 복구한다.

서버 DB·별도 인계 키·API 재시작·예약 배치·Firebase 종료 상태를 먼저 적용한 뒤 두 앱의 새 승인·사진·영상·동의 흐름을 맞춘다. 실제 기기 FCM, 실제 MySQL 경합, 실제 S3 최종 시나리오는 서버·앱 공동 검증 결과로 별도 기록한다.

## 로컬 검증 근거

최종 전체 회귀는 **956 passed / 23 skipped**, 기존 의존성·자원 경고 14건이다. 날짜 경계·늦은 인계 시작 차단·회수 보호·무이력 간편대여·과거 반납 ID 차단·SNS 당시 값·키 분리·동의·알림 최신 상태 확인을 포함한다. Swagger는 105경로/111메서드이며 API 엑셀의 JSON 예시 197개와 일치한다. DB 엑셀의 인계35컬럼과 시각화 SQL 3개도 대조했다. 오류 목록은 고정 정의 316종이고 전부 운영 재현했다는 의미는 아니다. 실제 서버 반영·외부 환경 검증은 별도 결과로 확인한다.
