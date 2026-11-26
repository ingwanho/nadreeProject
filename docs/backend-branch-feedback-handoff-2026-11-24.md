# 프론트 요청 처리 결과 — 예약·Walk-in·인계

> **2026-11-25 최종 정정·서버 적용 완료:** 두 정책 동의 시각은 회원정보에 저장한다. 가입/로그인 POST `/api/v1/nadree/user/login` 또는 기존 PATCH `/api/v1/nadree/user/profile`에 `privacyPolicyAgreed:true`·`termsAgreed:true`를 보내고 로그인/프로필 응답의 `user.privacyPolicyAgreedAt`·`user.termsAgreedAt`로 조회한다. 기존 실제 시각 이관·보존 검증과 인계 컬럼 삭제, 구 인계 API 404·응답 필드 제거를 확인했다. 관련 격리91개·실제 HTTP41개 기록이 기대 결과를 충족했으며 실제 신규/NULL 회원 최초 저장은 격리 검증과 구분한다. [최신 프론트 전달·테스트 순서](frontend-member-policy-consents-2026-11-25.md), [실제 서버 결과](member-policy-consents-server-verification-2026-11-25.md). 아래 인계 단위 적용 보고는 이전 계약의 이력이다.

> **2026-11-25 추가 — 서버 적용 완료:** 인계별 개인정보처리방침·이용약관 동의 시각과 고객 본인 POST `/api/v1/nadree/rental/handovers/{handover_id}/consents`를 배포했다. `privacyPolicyAgreed:true`·`termsAgreed:true` 중 하나 이상을 보내고 `privacyPolicyAgreedAt`·`termsAgreedAt`를 확인한다. 최초 서버 시각은 재요청 시 유지하며 고객 프로필·기존 서명·렌트 시작 조건은 유지한다. 기존 인계 7건의 두 시각은 NULL로 보존했다. 관련 격리 68건·실제 HTTP 50개 검사 기록의 기대 결과 충족을 확인했다. [프론트 전달·호출 순서·남은 확인](frontend-handover-policy-consents-2026-11-25.md), [서버 결과](handover-policy-consents-server-verification-2026-11-25.md). 아래 나머지 서버 결과는 11월24일 기준이며 검증 수를 합산하지 않는다.

2026-11-24 서버 반영 결과 포함 개정. **테스트 DB를 사용하는 서비스 서버에 DB·API·Firebase·배치 적용을 완료했고, 프론트 연동 테스트를 진행할 수 있다.** 배포 업무 코드는 `7217997`, 서버 결과 문서는 `c5c1bbb` 기준이다. 최종 서버 확인은 2026-11-24 **07:31:15 UTC / 발리 15:31:15**이며, 아래 상태는 이 보고 시점 기준이다. 이 문서 갱신 과정에서 서버를 재배포하거나 새 업무 요청을 실행한 것은 아니다.

공개 API는 **`https://na-dree.com`**, [Swagger](https://na-dree.com/docs), [OpenAPI JSON](https://na-dree.com/openapi.json)을 사용한다. 상세 실행 근거는 [서버 적용 결과](backend-branch-feedback-server-verification-2026-11-24.md), 재적용 절차는 [통합 서버 지시서](backend-branch-feedback-server-apply-2026-11-24.md)를 따른다. 요청 원본과 확정 기획은 프로젝트 상위 폴더에 보관한다.

## 서버 반영 완료 내용

| 항목 | 서버 확인 결과 |
| --- | --- |
| DB | `RIDERLOG_V2_DATA_TEST`에 마이그레이션 17개 적용, 잔여 계획 0개. 인계 35컬럼·사용자 서류/SNS·계약 연결·차량 작업 ID/버전·NO_RESPONSE 상태 반영 |
| API | 새 코드로 재시작, 로컬·공개 health/ready/docs/OpenAPI 정상. Swagger 105경로·111메서드(health 포함) |
| 개인정보 | 별도 인계 키 설정과 저장/복호화 검증 완료. 기존 전화번호 키·암호문 보존 |
| 날짜 정리 | 기존 예약·대여 상태 19건 보정, 알림 0건. 미반납 렌트를 강제 반납하거나 회수 보호를 임의 해제하지 않음 |
| 배치 | lifecycle 매분, maintenance 5분 주기 활성화. 중복 receipts 타이머 중지. 기존 결제 복구·개인정보 삭제·채팅 동기화·보존 작업 유지 |
| Firebase | 기존 Python Functions 7개 업데이트, 프로젝트 `bail-472405`·리전 `asia-southeast2` 유지. Rules·인덱스·호출자 IAM 변경 없음 |
| 채팅 종료 | 실제 NO_RESPONSE 예약 5건의 Firestore 접근 링크 closed·채팅방 read_only 확인, 열린 링크/방·누락 0건 |
| 수납 | EXTERNAL 유지. 이번 실제 시험에서 PayPal 결제·환불 호출 없음 |

과거 미승인 요청이 `NO_RESPONSE`, 미픽업 승인이 `EXPIRED`, 미반납 대여가 `OVERDUE`로 보일 수 있다. 기존 목록을 새로 조회하고, 신규 인계 시험은 새 요청과 가용 시험 차량으로 진행한다. 기존 회수 보호 차량을 일반 가용 차량으로 취급하지 않는다.

### 실제 검증된 범위와 남은 확인

서버에서 기본 회귀 956개, Firestore 에뮬레이터 8개, 기본 회귀와 중복을 제외한 S3 통신 대역 3개, 별도 MySQL DB 경합 12개를 합쳐 **고유 979개 격리 검사를 통과**했다. 기본 실행에서 제외한 23개도 해당 환경에서 별도 실행했다.

실제 API·S3 최종 시나리오는 **108개 HTTP·SQL 검사 기록에서 기대 결과를 충족**했다. 예상 오류 응답을 포함한 기록 수이며, 독립 테스트 108개 또는 성공 응답 108개라는 의미는 아니다.

| 기능 | 실제 서버 확인 | 프론트/추가 확인 |
| --- | --- | --- |
| 사전예약·cc 범위·finalPrice 승인 | 실제 견적·신청·승인 통과, 시험 예약 정상 취소 | 앱 가격 기본값·USD 총액 표시 |
| 당일 1일 Walk-in·인계·반납 | 고객 폼→영상→동의→관리자 확인→담당자 시작→QR 반납, 최종 RETURNED | 양 앱 화면과 재접속 복구 |
| 수정 거부·재시작 | 예약/배정/가격 유지, 새 인계 재시작 통과 | 수정 기능 UI 사용 시 기존 인계 ID 전환 |
| 실제 S3 자료 | 업로드 POST 4건 204, GET 200·파일 체크섬 일치. 10초 영상 READY, 10.1초 거절 | 네이티브 촬영·업로드·재생, 웹 업로드 시 CORS |
| SNS·동의 | 프로필 SNS 변경 후 당시 값 유지, 동의 재요청의 저장 시각/고객/인계 ID 불변 | 아래 시각 정밀도 처리 |
| 담당자 권한 | 담당자 아닌 대표의 시작 요청도 403으로 차단 | 담당자와 canStartRental 기준 버튼 표시 |
| 간편대여 | 실제 시작/QR 반납 2회·중복/오래된 ID 차단. 고객·예약·계약·관련 이력 5테이블 증가 0행 | 예정일 경계는 격리 검증, 앱 반납 확인·상태 버전 복구 |
| 날짜·오전 알림 | 실제 기존 자료 보정·배치 반복 정상. 자정/09시·수신자·중복·발송 취소는 격리 통과 | 실제 시간 경계·기기 FCM 수신 |
| 지점·QR·최근 이력 | 본인 지점 QR·최근 3건 정렬 실제 통과 | 직접 차량 수/비활성 계층·타 지점/타 고객 권한은 격리 통과, 실제 계정 조합 추가 확인 |
| 기타 조회·변경 | 숙소 이력 실제 통과 | 정비 API·차량 재배정·모델 이미지 Key/Url 및 이미지 GET은 격리 통과, 이번 실서버 시나리오 미실행 |

최종 시험의 미완료 업무는 0건이고 시험 차량은 AVAILABLE로 정리됐다. 기존 다른 지점/예약의 회수 보호·미반납 상태는 보존했다. **앱 화면·실제 서명 UI·기기 FCM·배포 callable App Check 종단은 아직 공동 확인 대상**이다. 실제 업무 코드 추가 수정 없이 시험 입력의 종료일 포함 금액과 검증 러너의 시각 비교를 바로잡아 재검증한 결과다.

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

**실서버 동의 시각 주의:** 첫 완료 응답에는 소수초가 포함되고, DB의 DATETIME(0)을 다시 조회하면 초 단위로 반환될 수 있다. 실제 시험에서 저장 시각은 재요청으로 변경되지 않았고 표현 차이는 1초 미만이었다. 중복 완료 여부는 시각 문자열 전체 일치로 판단하지 말고, 같은 `signatureHandoverId`·`signatureActorUid`와 `signatureStatus=COMPLETED`를 기준으로 처리한다. 시각은 UTC로 해석해 표시한다.

### 네이티브 앱 사진·영상

기존 인계 `media/uploads` API에 `clientFileId`, 종류, MIME, 크기를 보내면 `url`과 `fields`를 받는다. **모든 fields와 파일을 multipart POST로 S3에 직접 전송**하고 API의 해당 업로드 `complete`를 호출한다. 2단계 업로드가 끝나야 READY다. 영상은 MP4 최대 50MiB·10초, 사진은 JPEG/PNG/WebP 최대 10MiB다. 서버는 실제 파일의 크기·형식과 영상 최대 10초를 검사하고 확정 비공개 키로 복사한다. 같은 완료 재요청은 저장 결과를 재사용한다.

자료 조회 API의 임시 URL로 사진/영상을 표시한다. URL을 DB/프로필에 영구 저장하지 않고 만료되면 API에서 재발급한다. 네이티브 HTTP 업로드에는 브라우저 CORS 설정이 필요 없다. 웹 관리자나 WebView JavaScript에서 직접 업로드할 때만 S3 버킷 CORS와 실제 프론트 origin을 별도로 설정한다.

**실서버 업로드 순서 주의:** S3 업로드 완료 전에 complete를 호출한 시험은 현재 환경에서 `503 MEDIA_STORAGE_UNAVAILABLE`을 반환했다. 객체 단위 S3 권한에서는 없는 객체의 HEAD도 403으로 숨겨질 수 있어, 이를 정확한 미업로드 404로 판별할 수 없었다. 이 503만으로 미업로드·권한 부족·서비스 전체 장애 중 하나를 단정하지 않는다. 앱은 S3 업로드 성공을 확인한 후 complete하고, 실패하면 같은 업로드 ID의 진행 상태와 업로드 결과를 확인한 뒤 재시도한다. 새 인계/업로드 ID를 계속 생성하지 않는다. 업로드 후 complete·조회는 실제 통과했다.

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

서버 DB·별도 인계 키·API 재시작·예약 배치·Firebase 종료 상태 적용은 완료했다. 아래 순서로 두 앱의 연동을 확인하고, 실제 기기·App Check 결과를 별도로 기록한다. 기존 전화번호 키 복구는 이번 인계 키 분리로 해결한 항목이 아니며, 전화번호 기능 확인 시 별도 문제로 구분한다.

## 프론트 연동 테스트 순서

1. 기존 공개 API의 Swagger를 갱신하고 `WALK_IN`, `NO_RESPONSE`, `latePickupWarning`, 담당자·서명·작업 ID/상태 버전 필드를 적용한다. 예시 JSON의 ID·QR·날짜는 가상 값이며 그대로 사용할 시험 자료가 아니다. 승인된 테스트 고객·같은 지점 대표/일반관리자·가용 QR 차량을 사용하고 로그인 정보는 비공개로 공유한다.
2. 고객 앱에서 사전예약과 당일 1일 Walk-in을 각각 새로 요청한다. 관리자는 `finalPrice`만 넣어 승인하고 `currency`는 전송하지 않는다. 승인된 총액에 배송비를 다시 더하지 않는다.
3. 고객이 인계를 시작하고 폼을 제출한다. 여권·숙소·헬멧 수는 필수, 헬멧 0 허용이다. 번호/SNS의 프로필 반영과 인계 당시 SNS 보존을 확인한다.
4. 관리자는 촬영/검토로 담당자를 선점하고 필수 EXTRA_PHOTO를 올린다. 고객은 최대 10초 MP4를 S3에 업로드한 뒤 complete하고 동의를 완료한다. 관리자 폼 검토는 고객 폼 제출 후 가능하며, 고객 영상/동의와 병행할 수 있다.
5. 최신 상세의 `canStartRental`과 담당자 ID를 확인하고 담당자 계정으로 렌트를 시작한다. 대표라도 담당자가 아니면 시작할 수 없다. QR 반납 후 RETURNED와 실제 가용 상태를 재조회한다.
6. 간편대여 START/실제 QR 반납, 응답 유실 후 같은 ID 재시도, 새 대여에 이전 반납 ID를 보냈을 때 차단을 확인한다. 간편대여가 고객/예약/렌트 이력에 나타나지 않는 것이 정상이다.
7. 지점 직접 차량 수·비활성 탭·타 지점 QR 비공개·최근 3건·정비·차량 변경·모델 이미지 표시를 앱에서 확인한다. 서버 격리 통과와 실제 화면 검증을 구분한다.
8. 마지막으로 실제 FCM 수신·딥링크·중복 표시 방지와 Firebase callable의 App Check 종단을 확인한다. 기존 인증/App Check 설정은 유지한다. 웹/WebView JavaScript 업로드를 사용하면 실제 origin에 맞는 S3 CORS도 확인한다.

## 검증 근거

로컬과 서버 기본 회귀는 **956 passed / 23 skipped**이며, 서버에서 별도 환경 23개를 추가 실행해 **고유 979 passed**를 확인했다. 기존 의존성·자원 경고 14건은 유지됐다. 실제 업무는 **108개 검사 기록의 기대 결과 충족**으로 따로 기록했다. 실제 기기 FCM·App Check·시간 경계 등 미검증 범위는 위 표를 따른다.

Swagger 105경로/111메서드와 API 엑셀 JSON 예시 197개의 대조, DB 엑셀의 인계35컬럼·시각화 SQL 3개 대조는 기존 로컬 명세 검증 근거다. 서버에서도 실제 105경로/111메서드·인계35컬럼·마이그레이션 잔여 0개를 확인했다. 고정 오류 정의 316종을 전부 운영 재현했다는 의미는 아니다. 서버 실행·실제/격리 구분·복구와 남은 확인의 원문은 [서버 적용 결과](backend-branch-feedback-server-verification-2026-11-24.md)에 있다. 이 문서 갱신으로 요청/응답 계약이나 업무 코드를 추가 변경하지 않았다.
