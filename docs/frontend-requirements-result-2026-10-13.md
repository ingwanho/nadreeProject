# 앱·웹 프론트 요구사항 처리 결과 전달서

작성일: 2026-10-13  
대상: 고객 앱·관리자 앱·웹 프론트 개발자

## 1. 전달 범위와 현재 상태

현재까지 확정된 요구사항의 백엔드 반영 내용과 서버 검증 결과를 정리했다. API·DB 변경은 서버에 적용됐으며 QR 테스트 데이터 생성과 정상 조회도 완료됐다. 프론트 연동 테스트를 진행할 수 있다. 단, 모든 기능의 실제 업무 흐름이 검증 완료됐다는 의미는 아니다.

**PayPal 결제 확정·환불·웹훅 최종 검증은 별도 진행한다.** 이번 전달에서 PayPal 검증 완료를 전제로 하지 않는다. 위치조회, App Check·실기기 푸시, 앱·웹 화면 검증도 별도다.

이 문서의 최신 정책이 과거 전달서의 고객 당일 취소 금지·관리자 당일 취소 허용·초대코드 승인 대기·센서 코드 기반 QR 조회 안내보다 우선한다. 상세 요청/응답 필드는 현재 Swagger 및 채팅 계약을 따른다.

| 접속 대상 | 주소/값 |
| --- | --- |
| API | https://na-dree.com |
| Swagger | https://na-dree.com/docs |
| OpenAPI | https://na-dree.com/openapi.json |
| 고객 API | /api/v1/nadree |
| 관리자 API | /nadreego |
| 채팅 Firebase 프로젝트 | bail-472405 |
| Functions 리전 | asia-southeast2 (자카르타) |

## 2. 요구사항별 반영 내용

아래의 ‘반영’은 구현/배포 범위다. 실제 서버에서 확인한 범위는 7절에 별도로 구분했다.

| 구분 | 처리 내용 | 프론트 적용 사항 |
| --- | --- | --- |
| 고객 인증 | Firebase ID token 검증, 고객 access/refresh 발급·회전·폐기 반영 | 로그인에는 Firebase ID token, 이후 업무 API에는 고객 access token 사용 |
| 회원 탈퇴 | 조건 없는 탈퇴, Firebase 계정 삭제 및 기존 세션 무효화, 거래 이력 보존 | API 성공 후 로컬 토큰/캐시 정리. 탈퇴를 예약 취소·환불로 표시하지 않기 |
| 예약·결제 기한 | 최초 유효 승인+72시간과 렌탈 시작 시각 중 빠른 시각 적용 | 서버 반환 기한을 사용하고 기기에서 승인+72시간만 계산하지 않기 |
| 취소·환불 | 고객/관리자 정책 분리, 취소 요청자·환불률 기록 | 아래 최신 정책 적용. 금액·요청자·환불률을 클라이언트가 지정하지 않기 |
| 결제 안전성 | 진행 중 결제 확인·주문 재사용·중복 청구 방지·응답 유실 복구·늦은/중복 청구 전액 환불 로직 | 오류별 기존 결제 조회/운영 확인 처리. 실제 PG 최종 검증은 별도 |
| 관리자 가입 | 지점 가입코드면 해당 지점 대표 즉시 활성화, 대표 이메일이면 일반관리자 승인 대기 | 두 가입 흐름과 대기 화면 구분. 상위 회사 권한 자동 부여 아님 |
| 고객 관리 | 지점 권한 범위의 고객 목록·상세·이력 조회 | 페이지 처리, 없는 연락처 null 처리. 여권·FCM·세션 정보 제공하지 않음 |
| 알림함 | 지점 공통 목록·미읽음 수·읽음 처리 | shopId 지정. 지점 공통 읽음과 채팅 개인 읽음을 구분 |
| 매장·예약 위치 | 매장 조회/수정, 예약 위치 스냅샷, 대표의 인계 전 위치 정정·이력 | 매장 수정이 기존 예약에 자동 전파되지 않음 |
| 관리자 변경 | 직원 제거·대표 양도 시 기존 채팅 세션 회수 | 현재 역할로 세션 재발급. 퇴사자는 접근 불가, 이전 대표는 일반관리자 권한 |
| 차량 QR | QR 전용/QR+센서 모두 지원, 차량 등록 QR 필수·센서 선택 | QR 원문 전송. 센서 코드와 혼용 금지. 상세는 4절 |
| 채팅 | 신규 Functions·Rules·인덱스·만료 스케줄 배포 확인 | 직접 소속 지점 관리자 열람, 대표만 답변. 상세는 5절 |
| 웹 가격·배송 | BASIC/PREMIUM·가격 범위·배송 테스트 데이터와 응답 제공 | 실시간 서버 계산값 사용. 회사 공통 가격은 테스트 값이며 운영 정책 추후 확정 |
| 여권 | 서버 업로드를 인계 필수 조건에서 제외 | 업로드 완료 여부로 인계를 막지 않기. 신규 여권 기능은 이번 범위 아님 |

### 취소 정책 — 결제 완료 건 기준

| 실행자 | 렌트 시작일 전 | 시작일 당일부터 |
| --- | --- | --- |
| 고객 | 인계 전 취소 가능, 90% 환불 | 인계 전 취소 가능, 0% 환불 |
| 관리자 | 인계 전 APPROVED 예약 취소 가능, 100% 환불 | 취소 불가 |

고객은 본인의 REQUESTED/APPROVED 예약에 한한다. 날짜는 서버 업무 시간대(기본 Asia/Makassar) 기준이며 ‘시작 시각 24시간 전’이 아니다. 미결제 건은 환불할 금액이 없다. 인계 완료 건은 위 취소 흐름으로 처리하지 않는다.

- 고객: `POST /api/v1/nadree/rental/request/cancel`
- 관리자: `POST /nadreego/booking/action`, `action=CANCEL`
- 취소 성공과 PG 환불 완료는 다르다. 응답의 환불 상태와 실제 환불액을 조회해 표시한다.
- 결제 안내·취소 확인창은 ‘고객 시작일 전 10% 공제, 당일부터 인계 전 취소 시 환불 없음’으로 안내한다. 관리자 취소에 10% 공제를 적용하지 않는다.

### 주요 추가/변경 관리자 경로

| 용도 | 메서드·경로 |
| --- | --- |
| 고객 목록/상세/이력 | GET /nadreego/customers, /nadreego/customers/{customer_id}, /nadreego/customers/{customer_id}/history |
| 알림 목록/미읽음 | GET /nadreego/notifications, /nadreego/notifications/unread-count |
| 알림 읽음 | POST /nadreego/notifications/{notification_id}/read |
| 매장 정보 | GET /nadreego/shop/profile |
| 예약 위치 정정 | POST /nadreego/booking/location-correction |
| 정정 이력 | GET /nadreego/booking/{booked_no}/location-corrections |
| 직원 제거/대표 양도 | POST /nadreego/shop/adminDelete, /nadreego/admin/roleChange |

위치 정정은 같은 장소의 주소/핀 오류 보정이며 실제 매장 이전·배송 목적지/요금 변경 기능이 아니다. `LOCATION_SNAPSHOT_CHANGED`이면 최신 예약을 다시 조회한다.

## 3. 고객 앱·웹 공통 연동

- 로그인: `POST /api/v1/nadree/user/login`에 body의 UID와 일치하는 Firebase ID token을 Bearer로 전달한다.
- 이후 고객 API는 로그인 응답의 서비스 access token을 사용한다. 관리자 토큰과 혼용하지 않는다.
- `FIREBASE_REAUTHENTICATION_REQUIRED`는 실제 Firebase 재인증이 필요하다. 단순 토큰 갱신만 반복하지 않는다.
- availability: `POST /api/v1/nadree/rental/availability`. 1~30일 대여 범위와 현재 서버가 허용하는 날짜를 사용한다. 과거 문서의 고정 날짜를 그대로 재사용하지 않는다.
- 예약: `POST /api/v1/nadree/rental/request`. 선택한 지점·모델·배송 옵션 및 서버가 반환한 유효 금액을 사용한다.
- 가격의 currency, rentalDays, dailyFrom/dailyTo, totalFrom/totalTo, totalOptions, pricingTiers 등을 사용하고 운영 가격을 하드코딩하지 않는다.
- 진행/완료 목록은 `/api/v1/nadree/rental/ongoing`, `/api/v1/nadree/rental/completed`를 사용한다. 예약·결제·환불 상태를 프론트가 임의로 확정하지 않는다.
- CORS는 문서의 웹 Origin에 대한 사전 요청 성공을 확인했다. 실제 배포 Origin이 바뀌면 스킴·호스트·포트를 백엔드에 전달한다. 쿠키 인증을 가정하지 않는다.

상품 상세의 별도 이미지/영업시간/패키지 전용 API, placeId·좌표 기반 정밀 배송지역 판정, 범용 Idempotency-Key 예약 복구 API는 이번 결과로 완료가 입증된 항목이 아니다. 기존 웹 전달서의 별도 범위와 구분하며, 현재 제공되는 필드 이상의 동작이 필요하면 계약을 확인한다. 결제 주문 재사용 로직과 범용 예약 멱등 API를 혼동하지 않는다.

## 4. QR 연동 및 실제 적용된 테스트 데이터

```http
POST /nadreego/vehicle/qr/validate
Authorization: Bearer <관리자 access token>
Content-Type: application/json

{"qrCode":"testQr123123"}
```

| 전송할 QR 원문 | vehicleId | equipmentType | sensorId / sensorStatus |
| --- | --- | --- | --- |
| testQr123123 | NRTEST-QR-ONLY-001 | QR_ONLY | null / NOT_LINKED |
| testQr456456 | NRTEST-QR-SENSOR-001 | QR_WITH_SENSOR | NRTEST-SENSOR-QR-001 / LINKED |

두 QR 모두 대표·일반관리자 정상 조회를 실제 서버에서 확인했다. 테스트 지점은 `00000000-0000-4000-8000-000000000101`이다.

- 응답은 기존 `status/errorCode/data` 구조를 유지한다. data의 vehicleId, qrId, qrStatus, equipmentType, sensorId, sensorStatus, vehicle, availableActions를 사용한다.
- 프론트는 스캔 원문을 그대로 전달한다. 서버가 해시를 계산하므로 프론트에 QR 비밀키가 필요하지 않다. 센서 코드/ID/클라이언트 계산 해시로 대체하지 않는다.
- 차량 생성 `POST /nadreego/vehicle/create`에는 원문 `qrToken`이 필수이고 `sensorId`는 선택/null이다.
- QR 조회 후 변경은 기존 API의 차량번호 등 기존 요청 규격을 유지한다. availableActions는 화면 안내이며 변경 권한을 보장하는 토큰이 아니다.
- 미등록/다른 지점 QR은 `QR_NOT_FOUND`, 비활성은 `QR_INACTIVE`, 만료는 `QR_EXPIRED`를 처리한다.
- `/nadreego/sensor/qr/resolve`는 사용하지 않는다. 센서가 없어도 QR 조회는 가능하며 위치조회는 센서 보유 차량만 별도 대상이다.

웹 테스트 기본 모델은 `NRTEST-WEB-MODEL-125`, 배송 미지원 모델은 `NRTEST-WEB-MODEL-ND`다. 배송지역은 Kuta `990000001`, Canggu `990000002`를 사용하며 현재 가용성과 금액은 API로 다시 확인한다. 테스트 비밀번호·토큰은 이 문서에 포함하지 않으며 별도 보호 경로로 전달한다.

## 5. 채팅 연동

고객: `POST /api/v1/nadree/user/chat/session`에 고객 Bearer와 `X-Refresh-Token`을 전달한다. 관리자: `POST /nadreego/chat/session`에 관리자 Bearer를 전달한다. 반환된 firebaseCustomToken으로 채팅 Firebase에 로그인한다. 새 세션은 이전 채팅 세션을 무효화하므로 화면별로 중복 발급하지 않는다.

| Callable | 요청 주요 필드 |
| --- | --- |
| ensureInquiryChat | shopId, 선택 productId(해당 지점 modelId) |
| ensureBookingChat | bookingId(BO 접두어 없는 reservationId) |
| sendChatMessage | roomId, messageId, text |
| markChatRead | roomId, messageId |
| getChatUnreadSummary | shopId |

- 일반관리자는 직접 소속 지점의 열람·알림·개인 읽음만 가능하고 대표관리자만 답변한다. 상위 회사의 하위 지점 업무 권한이 채팅에 자동 상속되지 않는다.
- Firestore 직접 쓰기는 금지한다. 방은 `chatRoomAccess`, 메시지는 방 하위 `messages`, 개인 읽음은 `reads`를 사용한다.
- 전송 재시도에는 동일 messageId와 본문을 재사용한다. 종료된 read_only 방에서는 전송 UI를 비활성화한다.
- setChatStatus/notifyBookingChatMessage는 앱 호출 대상으로 사용하지 않는다. expireInactiveInquiries는 서버 스케줄이다.
- 배포 및 업무 세션 발급은 확인했지만 유효 App Check를 포함한 실제 callable·실기기 메시지/푸시는 별도 연동 검증이 필요하다.

상세 규격: [앱 채팅 연동 안내](chat-app-integration-requirements-2026-10-13.md), [채팅 계약](../chat/chat-contract.md).

## 6. PayPal — 최종 검증 별도 진행

현재 Sandbox 인증, USD 1.00 주문 생성·조회·동일 주문 재사용은 확인했다. 정상 주문 검사는 격리 백엔드와 실제 Sandbox 연결로 수행했으며 실제 서비스 전체 결제 흐름의 완료를 뜻하지 않는다.

결제 확정(캡처)·실제 환불·유효 웹훅 정산·결제 복구 타이머 검증은 별도 진행한다. Merchant ID 불일치와 웹훅 구독 보완, 구매자 승인 상태 확인은 백엔드/운영 측 후속 항목이다. 현재 결제 복구 타이머는 미가동 상태다.

프론트는 기존 order → 구매자 승인 → capture → 상태 조회 흐름을 유지하되 아래 오류를 처리한다.

| 오류 | 처리 |
| --- | --- |
| PAYMENT_ALREADY_PAID | 기존 결제 상태 조회 |
| PAYMENT_IN_PROGRESS | 신규 주문 반복 생성 없이 기존 상태 조회 |
| PAYMENT_RECONCILIATION_REQUIRED | 확인 필요 표시 및 운영 문의, 임의 재결제 금지 |

승인 화면 복귀만으로 결제 성공을 표시하지 않는다. 서버의 결제·환불 상태를 최종 기준으로 사용한다. 관련 로직 구현과 실제 PG 검증 완료는 구분한다.

## 7. 검증 결과와 프론트 확인 요청

다음은 서버 결과 문서에 기록된 범위다. 서로 중복되는 테스트를 단순 합산하지 않는다.

| 범위 | 결과 및 한계 |
| --- | --- |
| 서버 적용 | DB 컬럼 4개 적용, pending 없음, API 재시작·헬스체크 정상 |
| Python 자동 테스트 | 파일별 격리 실행 272개 통과. 단일 프로세스 전체 실행 대기 원인은 별도 미확정 |
| Firebase | 함수 소스·Rules·인덱스·스케줄 일치. 별도 Firestore/Rules 테스트 각 4개 통과 |
| 실제 API/웹 | API 54개·웹 읽기 3개 기대 응답 일치. 오류·권한 차단 검사 포함이며 모든 업무 성공 경로의 실검증은 아님 |
| 실제 QR 후속 | 헬스·인증·정상/오류 조회 15개 통과. 타 지점 QR 실서버 검증은 보류, 격리 테스트로만 확인 |
| PayPal | 관련 회귀 59개, 격리 API 11개, 실제 서비스 오류 검사 4개 통과. 실제 캡처/환불 성공 미검증 |

프론트에서는 다음을 확인해 결과를 전달해 주세요.

1. 고객/관리자 로그인·토큰 갱신·재인증 및 역할별 화면 분리.
2. 웹 가격·배송·날짜 선택과 실제 Origin의 브라우저 CORS.
3. QR 두 종류 조회·선택 센서 처리 및 기존 차량 변경 API 연결.
4. 최신 취소 안내·결제 기한·환불 진행 상태 표시.
5. 채팅 세션·App Check·일반관리자 열람/대표 답변·종료 방 처리·실기기 푸시.
6. 고객 관리·알림함·매장/예약 위치 화면의 응답 필드와 오류 처리.

오류 전달 시 메서드·경로·재현 순서·발생 시각·HTTP 상태·errorCode를 포함하고 인증 토큰·비밀번호·개인정보는 제거한다. 실제 취소·환불·권한 변경·탈퇴 테스트는 지정된 테스트 대상과 합의한 범위에서만 진행한다.

이 전달은 추가 기능 전체 구현이나 출시 인수 완료 선언이 아니다. 위치조회, PayPal 최종 검증, 앱/웹 실기기 인수와 별도로 남은 MFA 제한 등은 각각 후속 관리한다.

근거: [서버 적용·QR 검증 결과](server-apply-verification-2026-10-13.md), [PayPal Sandbox 검증 결과](paypal-sandbox-verification-2026-10-13.md), [전체 변경 상세](nadree-full-change-handoff.md). 과거 기록과 충돌하면 최신 서버 후속 결과 및 이 문서의 확정 정책을 우선한다.
