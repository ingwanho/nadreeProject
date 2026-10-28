# Nadree API 구현 안내

최종 수정일: 2026-09-28

기존 DB를 공유하는 독립 Python 3.12·FastAPI 서버다. 기존 RiderLog 소스·환경 설정·배포는 변경하지 않는다. 모든 후속 구현 자료는 이 폴더에서 관리한다.

## 현재 상태

2026-10-28 현장·외부 결제 전환 적용: 신규 예약에 결제 방식을 저장하고 관리자 승인으로 확정하며, EXTERNAL 예약은 온라인 결제 없이 기존 기간·QR·권한·재고 검사로 인계한다. 주문/capture/재시도/온보딩은 중단하고 과거 거래·정산·환불을 보존한다. 추가 마이그레이션 없음. 전체 격리 회귀 **550 passed/12 skipped**, **07:03 UTC API 재시작 완료·공개 헬스/준비/Swagger 200·실제 조회 EXTERNAL/온라인 중단 확인**. 기존 테스트 계정으로 신규 예약 테스트 가능하며 실제 요청~인계/반납·앱 인수는 별도다. [앱 전달 문서와 테스트 예시](docs/external-payment-app-handoff-2026-10-28.md), [구현·실제 적용·검증 결과](docs/external-payment-implementation-result-2026-10-28.md).

2026-10-27 채팅 즉시 호출 적용: 신규 Python 함수 `dispatchChatPushEvent`가 메시지별 이벤트 생성을 감지해 OIDC 인증된 백엔드를 호출하고, 30초 작업은 복구를 유지한다. 기존 6개 함수·Rules·인덱스·만료 스케줄·결제 복구를 보존했다. 전체 격리 회귀 508 passed/12 skipped, 배포 소스 3개 일치, 무발송 이벤트의 실제 트리거→백엔드 응답 약 2.24초·SQL 알림/FCM 0건을 확인했다. 실기기 표시는 미검증이다. [실제 적용·검증 기록](docs/chat-push-trigger-deployment-result-2026-10-27.md).

2026-10-27 채팅 푸시 개선 적용: 실제 약 2분이던 실행 간격을 30초 일정·1초 정확도로 변경하고, 푸시를 전체 동기화보다 먼저 처리한다. 기존 서버 전용 이벤트에 수신자별 상태를 저장해 일시 실패를 제한 재시도하며 세션·토큰·권한 변경 시 중단한다. 별도 작업 경로의 격리 회귀 454 passed/12 skipped(MySQL 8·Firestore 에뮬레이터 4), 실제 연속 간격 29.999초·30.000초·작업 오류 0·API 헬스 200을 확인했다. 실제 기기 수신은 미검증이며 [채팅 계약](chat/chat-contract.md)과 [앱 전달 사항](docs/chat-session-fcm-app-handoff-2026-10-22.md)을 따른다.

2026-10-22 자동 정산 복구: 사용자 승인으로 완료 캡처만 API_QUERY로 반영하는 매분 cron을 등록했다. 실제 첫 cron에서 결제 8번 PAID 반영 및 고객 상태 API PAID/DONE을 확인했다. Sandbox/테스트 DB 고정·flock/공유 DB 잠금, 격리 회귀 398 passed/12 skipped. API 재시작·추가 청구·환불·만료·푸시 실행은 없다. 실제 서명 웹훅 전달은 별도 미검증이다. [설치·실제 결과·운영 방법](docs/payment-recovery-cron-deployment-2026-10-22.md).

2026-10-20 고객 PayPal 결제 복귀: 신규 주문에 확정 HTTPS 복귀 주소와 취소 구분(cancelled=true)을 전달하고 payer-action 링크를 지원한다. 기본 주소는 `/api/v1/nadree/rental/payment/return`, 선택 설정은 `NADREE_PAYPAL_PAYMENT_RETURN_URL`이다. 최신 로컬 회귀 352 passed/12 skipped 및 로컬 HTTP 주문 계약 검증 통과. 실제 서버 적용·PayPal/앱 왕복 인수는 별도다. [최신 적용·프론트 계약](docs/nadree-full-change-handoff.md).

2026-10-19 현재 서버 검증: 읽기 전용 마이그레이션 pending 없음, 기본 회귀 314 passed/10 skipped 재현. MySQL 포함 320 passed/4 skipped 및 별도 Firestore 4개 통과. 실제 가격 수정/원복·권한/state 차단은 통과했으나 현재 Sandbox OAuth는 401 invalid_client이며 복귀 URL은 설정 대기다. 실제 PG/탈퇴/App Check 종단과 결제 복구 운영 등록은 별도 확인이 필요하다. [요구사항 검증 결과](docs/server-requirements-verification-2026-10-19.md).

2026-10-18 온보딩 테이블까지 제외한 뒤 로컬 회귀는 314개 통과·10개 건너뜀(MySQL 6·Firestore 4)이다. 신규 기능은 아직 운영 배포/실 PG·Firebase 인수 전이다.

2026-10-18: BASE/BASIC 부분 구간 우선·배열 저장, 가격 옵션 스냅샷, 지점 귀책 당일 관리자 취소, 기존 예약 중복 검증, 종료 내역/직접 조회, PayPal URL 연결·기존 지점 컬럼 저장, 기존 탈퇴 처리 검증, App Check 디버그 검증 도구를 추가했다. 이메일 가입은 승인 대기, 일회성 지점 가입코드는 대표 즉시 활성화로 유지한다. 배송 주소 자동 구역 판정은 사용자 결정으로 제외했다. 요청 결과·개인정보·온보딩 신규 테이블 3개와 전용 타이머는 모두 제외했다. 기존 판매자 컬럼 변경만 유지하며 서버 미적용이다. **최신 계약·프론트 예시·서버 적용은 [전체 인수 문서의 2026-10-18 절](docs/nadree-full-change-handoff.md)을 우선한다.** 실제 MySQL/Firebase/PayPal 연동 인수는 별도다.

2026-10-16 지점별 Platform 판매자 연결: 별도 GET/PUT `/nadreego/shop/paypal-merchant`, 지점별 중복 허용 Merchant ID·환경 저장, 미설정 지점 승인 차단/거절 허용, 결제 당시 판매자 보존 및 판매자별 주문·캡처·환불·웹훅 처리를 추가했다. DB 컬럼 3개·Platform 설정·판매자 연결 확인이 필요하며 **서버 미적용/실제 PG 미검증**이다. [변경 전달서](docs/spot-paypal-platform-handoff-2026-10-16.md).

PayPal Sandbox 후속 검증: 인증·주문 생성/조회 연결 확인, 자동 회귀 59개·격리 API 11개·실제 서비스 오류 응답 4개 통과. Merchant ID 설정과 실제 구매자 승인(APPROVED)이 없어 캡처·환불/정산 성공은 아직 미검증이다. [PayPal 검증 결과](docs/paypal-sandbox-verification-2026-10-13.md).

QR 후속 적용 완료: 사용자 설정 키를 변경하지 않고 테스트 차량 2대·센서 1개와 QR/연결 이력을 추가했다. 대표·일반관리자의 QR_ONLY/QR_WITH_SENSOR 실제 조회와 오류/인증 검사 등 15개가 통과했다. 실제 타 지점 QR 차단은 별도 승인 계정이 없어 보류했다. [최신 QR 적용 결과](docs/server-apply-verification-2026-10-13.md).

2026-10-13 최신 서버 적용: 테스트 DB 컬럼 4개와 API 재시작 완료. 파일별 격리 자동 테스트 272개, 별도 Firestore 4개·Rules 4개·함수 업무 핸들러 통과. 실제 API 검사 54개(임시 QR 키 설정 차단 2개 포함)·웹 읽기 3개는 기대 응답과 일치했다. 실제 QR 성공·결제 타이머/외부 PG·App Check/앱 화면 인수는 보류·미검증이다. [최신 서버 결과](docs/server-apply-verification-2026-10-13.md).

### 2026-10-13 추가 보완 — 로컬 구현, 서버 미적용

QR은 센서 코드가 아니라 차량 식별값이다. 프론트는 `testQr123123` 같은 QR 원문을 기존 `POST /nadreego/vehicle/qr/validate`의 `qrCode`로 전달한다. 서버는 기존 HMAC-SHA256으로 `MSP_VEHICLE_QR.qr_code_hash`를 조회한다. 응답은 차량 정보와 `QR_ONLY`/`QR_WITH_SENSOR`, 선택 센서 ID를 제공한다. 센서 코드 조회 API는 잘못된 가정으로 추가했던 것이므로 제거했다. 차량 생성의 qrToken은 필수·sensorId는 선택이며 센서 없이도 QR 조회·변경이 가능하다. 새 매핑 테이블·컬럼·env·Firebase 변경은 없다.

결제 주문/캡처 전에 예약의 모든 결제 시도와 PG 상태를 확인한다. 외부 호출 전 요청 식별자·시각을 DB에 남겨 응답 유실에도 같은 주문/캡처 요청을 사용한다. 결과 불명 결제는 확정 실패로 취급하거나 예약 만료·새 청구를 허용하지 않는다. 늦은 실제 청구·중복 추가 청구는 전액 환불하며, 단순 웹훅 지연은 기존 고객 90%/0%·관리자 100% 정책을 유지한다. 역순 웹훅은 선행 결제가 확인되기 전 판정을 보류한다.

환불 요청 금액·식별자를 저장하고 자동 복구 작업에서 제한 재시도한다. 응답 불명은 같은 요청만 재전송하며, 확정 실패는 PG 조회로 확인한 뒤 새 시도를 만든다. 최대 5회 후 운영 확인 표시와 알림을 남긴다. 기본 읽기 전용인 `app.refund_recovery`로 건별 확인·안전 재시도가 가능하며 임의 환불액 입력은 제공하지 않는다.

대표관리자의 인계 전 예약 위치 정정·이력 조회 API를 추가했다. 매장 실제 이전은 기존 예약에 전파하지 않고 배송 목적지·금액은 유지한다. 퇴사 직원 제거와 대표권한 양도의 기존 채팅 회수 경로에 실패 롤백 테스트를 추가했다. 장기 미접속 자동 퇴사나 직접 SQL 변경 감시는 추가하지 않는다.

DB 컬럼 4개 추가 및 결제 복구 타이머 적용이 필요하다. 상세 API·예외·서버 명령·남은 검증은 [인수 문서 최신 절](docs/nadree-full-change-handoff.md#2026-10-13-추가-보완--배포-전-확인)에 정리했다. 실제 MySQL 동시성·PayPal Sandbox 실결제·Firebase 종단 검증은 별도다. 아래 과거 미완료 목록 중 이 절에 명시한 구현 항목만 대체한다.

### 이전 배포·검증 기록

2026-10-13 백엔드 실제 검증: 사용자 env 수정과 승인된 API 재시작 후 이전 로그인 503은 해결됐다. 실제 인증·고객/관리자 로그인·채팅 세션·refresh·권한·오류 응답 검사 48개가 모두 통과했다. 격리 API 회귀 219개, Firestore 통합 4개·Rules 4개와 Python 6개 함수의 업무 핸들러도 통과했다. 실제 예약 생성/취소는 격리 검증으로 구분하며 App Check 종단·앱 화면·기기 푸시는 별도 미검증이다. [백엔드 검증 결과](docs/backend-api-verification-2026-10-13.md).

2026-10-13 신규 채팅 실제 적용: 승인된 Node.js 함수 7개를 정리하고 Python callable 5개를 재생성·만료 함수 1개를 갱신했다. bail-472405/asia-southeast2의 Python 6개 ACTIVE, Rules 일치·인덱스 4개 READY, 15분 만료 실행과 API 재시작·단일 동기화 타이머를 확인했다. 최초 동기화는 지점 24개·예약방 8개 생성 성공이다. 전체 Python 회귀 219개 및 별도 Firestore 3개·Rules 4개가 통과했다. 실제 계정·유효 App Check·실기기 푸시/앱 인수는 아직 미검증이다. [실제 적용 결과](docs/chat-new-build-deployment-result-2026-10-13.md)에 완료·잔여 항목을 구분했다.

2026-10-13 채팅 방향 확정: [채팅 계약](chat/chat-contract.md)과 현재 Python 구현을 정본으로 신규 구축한다. 기존 데이터 이전·구버전 호환 코드는 만들지 않는다. 기존 Node.js 채팅 함수 7개의 정리와 Python 함수 6개의 적용은 [신규 구축 실행안](docs/chat-new-build-deployment-plan-2026-10-13.md)의 정확한 목록으로 별도 승인을 받는다. 현재는 운영 적용·실제 앱 연동 인수 전이며 기존 FCM/Auth·차량 위치·채팅 외 데이터와 규칙을 보존한다.

2026-10-12 채팅 추가: 기존 소스가 없다는 사용자 확인에 따라 [채팅 연동 계약](chat/chat-contract.md), 자카르타 `asia-southeast2` Functions·Rules·인덱스, 관리자/고객 채팅 세션 API 및 업무 동기화 코드를 신규 작성했다. 아래 과거 “채팅 소스 미제공” 상태를 대체한다. 기본 비활성이며 실제 Firebase 배포·운영 실연동은 별도다.

### 2026-10-12 변경분 — 부분 구현, 전체 출시 인수 전

이 절의 최신 정책이 아래 과거 진행 기록보다 우선한다. 운영 배포·실제 DB 변경·Firebase/PayPal 실연동 테스트는 실행하지 않았다.

| 취소 실행자 | 시작일 전 | 시작일 당일부터 |
| --- | --- | --- |
| 관리자 | 인계 전 APPROVED 예약 취소, 100% 환불 | 취소 불가 |
| 고객 | 인계 전 REQUESTED/APPROVED 예약 취소, 90% 환불 | 인계 전 취소 가능, 0% 환불·PG 환불 요청 없음 |

날짜 경계는 업무 시간대(기본 Asia/Makassar)다. 기존 결제 행에 `cancellation_requested_by_type`, `cancellation_requested_by_id`, `refund_percentage`를 저장한다. 클라이언트가 요청자·환불률을 지정할 수 없으며 과거 데이터는 추정하여 채우지 않는다.

로컬 코드 반영 범위:

- 결제 기한은 최초 승인+72시간과 렌탈 시작 중 빠른 시각. 확정 예약의 저장된 견적을 사용하고 취소 정책에 맞춰 FCM 문구를 수정했다.
- 지점 생성 시 발급한 일회성 초대코드 가입은 해당 지점의 대표관리자(rental_primary_admin)로 즉시 ACTIVE이며 승인 요청을 만들지 않는다. 대표 이메일만 입력하면 해당 대표 지점의 일반관리자 가입 요청으로 승인 대기하며 승인 후 rental_manager가 된다. 상위 회사 권한은 부여하지 않는다.
- 차량 생성 시 외부 QR은 필수, 센서는 선택이다. 응답의 QR·센서 연결 상태를 구분한다.
- 관리자 고객 목록·상세·이력: `GET /nadreego/customers`, `GET /nadreego/customers/{customer_id}`, `GET /nadreego/customers/{customer_id}/history`. Bearer 인증, `spotMasterId` 조회 범위, 목록/이력 `page`·`pageSize` 페이지 방식이다. 일반 직원은 직접 소속 지점, 대표는 허용 하위 지점의 거래 고객만 조회한다. 연락처는 원천 데이터가 없어 null이며 여권·FCM·세션 정보는 노출하지 않는다.
- 지점 공통 알림: `GET /nadreego/notifications`, `GET /nadreego/notifications/unread-count`, `POST /nadreego/notifications/{notification_id}/read`. 목록/개수는 `shopId` 필수, 목록은 `page`·`pageSize`와 `isRead`·`eventType` 선택 필터다. 읽음은 직원 간 공통이며 반복 요청 시 최초 readAt을 유지한다. 예약·결제·환불·인계·반납 이벤트를 저장한다. 채팅은 활성화 후 app.chat_sync 작업으로 연결한다.
- `GET /nadreego/shop/profile` 전체 매장 조회, 기존 매장 수정에 대상 지점·주소/좌표·선택 정보 명시적 null 삭제를 추가했다. hierarchy에 회사·부모·작업 권한 정보를 추가했다. 지점 생성에 이메일·주소·좌표를 검증한다.
- 예약 시 위치를 저장하고 계약에 복사한다. 위치 없는 지점은 상품 조회를 유지하되 신규 예약만 제한한다. 기존 예약의 위치·금액은 매장 설정 변경으로 덮어쓰지 않는다.
- 지점 가격·배송 설정은 일반 직원의 직접 지점과 대표의 허용 하위 지점에 한정한다. 회사 공통 BASE 가격은 현재 테스트 값을 유지하며 회사별 운영 정책은 실데이터 이전 시 확정한다.
- 여권 업로드는 인계 필수 조건이 아니다. 기존 파일을 삭제하거나 신규 여권 기능을 추가하지 않았다.

추가 DB 변경은 [마이그레이션 안내](migrations/README.md)의 2026-10-12 항목을 따른다. 새 알림 테이블을 업무 트랜잭션에서 사용하므로 스키마 적용 없이 코드만 재시작하면 안 된다. 이전 전달 문서의 “추가 마이그레이션 없음”은 이번 변경에는 해당하지 않는다.

남은 작업(전체 완료로 판정하지 않음):

- 신규 채팅의 실제 Firebase 배포·연동, 공유 서버에서 직접 변경하는 소속/권한의 즉시 회수 연결은 남아 있다. 설정·운영 제한·검증은 [채팅 계약](chat/chat-contract.md)을 따른다.
- PG 상태 불명확 결제의 만료 전 확인, 뒤늦은 실제 결제·중복 청구의 자동 전액 환불, 실패 환불 자동 재시도·최종 실패 운영 재처리 보완. 기존 환불 처리를 이 요구사항 전체의 완료로 간주하지 않는다.
- 같은 장소의 위치 정정과 실제 이전을 구분하는 예약 위치 정정 계약·이력, 차량 QR 해시 조회 및 선택 센서 연결 계약(상단 최신 구현·정정 참조), 차량 이동/재배정 상세 시나리오 검증.
- 실제 공유 MySQL의 조직 생성 제약·중첩 지점 및 동시성 검증, 실제 Firebase·PayPal·탈퇴 후 문의/환불 연속성 인수. 기존 여권 파일 정리는 저장소·보존 범위를 확인한 별도 운영 절차가 필요하다.

수정된 API 스키마는 실제 라우터에서 OpenAPI로 생성한다. 2026-10-12 채팅 추가 후 로컬 테스트는 213개 통과, 9개 건너뜀(MySQL 6개, 별도 Firestore 에뮬레이터 3개)이다. Firestore 트랜잭션 3개는 별도 실행에서 통과했고 Rules 에뮬레이터 4개도 통과했다. 운영 전체 인수 완료를 뜻하지 않는다.

### 과거 진행 기록

- W00 실행·설정·DB 트랜잭션·인증·권한·테스트 기반 및 이번 범위의 마이그레이션 준비.
- W01·W02 기존 15개 경로와 관리자 가입 접수 1개 경로의 기본 기능 구현·로컬 검증을 완료했다. API 05 전화번호 암호문 저장을 위한 phone VARCHAR(200), API 23 소개·연락 이메일의 지점 컬럼 추가를 반영했으며 운영 DB에서는 승인된 컬럼·인덱스 적용 상태를 별도로 확인한다.
- W03~W08 차량·QR·가격·배송·예약·렌트·조회·PayPal 웹훅 라우터로 기존 관리자·조직 API 38개를 유지하고 관리자 가입 신청 1개를 추가했다. 나드리 고객 API 14개 경로(로그아웃·refresh GET 호환 포함 16개 메서드)는 별도 네임스페이스로 제공한다. 예약 요청·승인/거절·결제 기한·결제 확정의 FCM 발송과 활성 렌탈의 비식별 여권 이미지 업로드·보호 조회를 추가했으며 토큰은 계정별 현재 기기 값 1개를 기존 공유 DB에 저장한다. 예약·결제 응답에는 `shopId=spotMasterId`, `bookingId=reservationId` 매핑을 명시하고, 응답 유실 복구용 결제 상태 조회를 제공한다. 캘린더는 상태 필터가 없는 일반 요청에서 SQL로 차량 ID·페이지를 먼저 선별하고 상세 정보는 해당 페이지만 읽는다. 전체 로컬 테스트는 164개 통과, 6개는 별도 MySQL이 없어 건너뛴다.
- API 32·33의 신청 조회·승인·거절 구현과 `POST /nadreego/admin/signup` 가입 접수를 완료했다. 가입 API는 RiderLog 호환 `MSP_ADMIN` 계정을 만들고 대표 이메일·초대코드로 지점을 검증한 뒤 REQUESTED 신청만 저장한다. 승인 전에는 렌탈 role/scope를 부여하지 않는다. 하위지점 생성은 `MSP_SPOT_RENT.invite_code`를 발급하고 성공한 가입 신청에서 소비한다.
- 렌탈 사용자 영역은 MSP_DRIVER와 분리했다. MSP_RENTAL_USER는 uid_token을 기본키로 사용하고 name·gender·age·nationality를 보관하며, MSP_RESERVATION·MSP_RENTAL_CONTRACT도 uid_token으로 연결한다. 기존 legacy_user_code와 렌탈 영역의 driver_id는 003 마이그레이션에서 정리한다.
- 나드리 고객 앱의 UID 로그인·신규 사용자 생성, 1시간 access token 발급, 프로필 갱신, 렌탈 차량 가용성·가격 조회, 렌트 요청, PayPal 결제 주문·캡처, 진행·완료 렌트 목록 조회와 결제 전 예약 취소·고객 로그아웃 API를 구현했다. 관리자 앱에는 활성 렌탈의 비식별 여권 이미지 업로드·보호 조회를 추가했다. 고객 API 명세와 운영 전 확인 항목은 [사용자 API 설계](docs/nadri-user-api-design.md)에 별도로 정리했다. 관리자용 나드리고 API와 기존 RiderLog 운전자 API에는 영향을 주지 않는다.
- 정비 만료·승인 후 결제 기한 알림·PayPal 미결제 예약 만료·6개월 일별 재고를 `python -m app.jobs {maintenance|payments|inventory|all}`로 실행할 수 있다. PayPal Sandbox·FCM 서비스 계정·Redis·SMTP·MFA·앱 흐름·기존 서버 회귀는 운영 환경에서 별도로 확인해야 한다. 테스트 통과는 코드·로컬 검증 결과이며 외부 서비스 통합 완료를 뜻하지 않는다.

상세 진행표·제한사항·검증 결과: [W00~W02 구현 기록](docs/w00-w02-implementation.md). 전체 범위: [API 작업 구분](docs/api-work-groups.md).

## 실행

이 폴더를 작업 디렉터리로 사용한다. `.venv`는 기존 서버와 공유하지 않는다.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8008 --no-access-log
```

- Swagger UI: <http://127.0.0.1:8008/docs> (운영: <https://na-dree.com/docs>)
- ReDoc: <http://127.0.0.1:8008/redoc>
- 실행 확인: <http://127.0.0.1:8008/health/live>

FCM 토큰은 앱이 전달한 현재 기기의 최신 값 1개를 계정별로 저장한다. 예약·결제 확정 알림은 해당 지점에 직접 연결된 활성 관리자에게, 승인·거절·기한 알림은 고객에게 DB 트랜잭션 커밋 뒤 기존 FCM Firebase 프로젝트로 발송한다. 고객 인증·채팅도 같은 프로젝트를 사용하고 차량 위치 Firebase만 별도 프로젝트로 분리한다. 동일 토큰은 한 번만 발송한다. 발송 장애는 업무 API를 실패시키지 않으며, 일시 오류는 프로세스 내부에서 최대 5회·1시간 범위로 제한 재시도한다. 로그아웃에 현재 기기의 `X-FCM-Token`을 보내 저장값과 일치하면 토큰을 삭제하고, 헤더가 없으면 유지한다. 알림 큐 테이블이나 Firebase 데이터베이스는 사용하지 않는다.
- 의존 서비스·스키마 확인: <http://127.0.0.1:8008/health/ready>
- 실제 라우터에서 생성되는 OpenAPI JSON: <http://127.0.0.1:8008/openapi.json>

8008 포트를 다른 프로세스가 사용하면 빈 포트로 변경한다. 설정 없이도 개발 서버와 문서 화면은 열리지만 업무 API는 503으로 차단된다. 샘플 DB·로그인 계정을 운영 앱에 자동 생성하지 않는다.

`.env.example`의 항목을 환경 변수 또는 이 폴더의 비공개 `.env`로 설정한다. DB URL은 `mysql+pymysql://USER:PASSWORD@HOST:3306/DB?charset=utf8mb4` 형식이다. 실제 비밀값을 이 문서·엑셀·소스에 넣지 않는다.

| 설정 | 용도 |
| --- | --- |
| `NADREE_DATABASE_URL` | 기존 스키마와 승인된 렌탈 확장이 적용된 MySQL |
| `NADREE_REDIS_URL` | 서버 간 공통 요청 제한. 운영 환경에서는 인증·TLS 적용 |
| `NADREE_JWT_SECRET` | 새 서버 전용 무작위 서명 키, 최소 32바이트 |
| `NADREE_BUSINESS_TIMEZONE` | 기본 `Asia/Makassar` |
| `NADREE_FIELD_ENCRYPT_KEY` | 기존 전화번호 암호화와 호환되는 Fernet 키. 평문 대체 금지 |
| `NADREE_PAYPAL_*` | Sandbox/Live 환경, Client ID·Secret, Webhook ID, Merchant ID. 비공개 환경변수로 주입 |
| `NADREE_FCM_*` | FCM 발송·고객 인증·채팅용 기존 Firebase 서비스 계정. 차량 위치용 `NADREE_LOCATION_FIREBASE_*`와 분리 |
| `NADREE_FIRESTORE_PROJECT` / `NADREE_LOCATION_FIREBASE_*` | 차량 위치 조회용 Firestore 프로젝트·서비스 계정. 위치 어댑터는 `driving/{sensor_code}` 문서의 `g.geopoint`를 읽으며 FCM 발송 프로젝트와 분리하며, 서비스 계정이 없으면 ADC/workload identity를 사용 |
| `NADREE_SMTP_*` | 임시 비밀번호 메일 발송. 인증서 검증을 하는 STARTTLS 또는 SSL |
| `NADREE_ENV` | `development`, `test`, `production` |

JWT 키·issuer·audience는 기존 서버와 분리한다. 전화번호 키는 공유 데이터와의 호환성이 필요하므로 배포 환경에서 안전하게 주입한다. 기존 `.env` 전체를 복제하지 않는다.

## 테스트와 DB 변경

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m app.migrate
```

테스트는 임시 SQLite 데이터를 사용한다. MySQL 동시성 테스트는 별도 설정 없으면 건너뛴다. `app.migrate`는 기본 읽기 전용 계획 조회이며, 누락된 렌탈 조회 복합 인덱스도 계획에 표시한다. **공유 운영 DB 변경은 승인된 SQL·적용 주체·백업 절차를 확인한 뒤에만** 실행한다. [마이그레이션 안내](migrations/README.md)를 먼저 확인한다.

## 정본과 파일

| 경로 | 역할 |
| --- | --- |
| [통합 문서](../rental-project-master.md) | 프로젝트·API·추가 DB·업무 규칙 |
| [검토 문서](../rental-api-review-decisions.md) | 사용자 결정과 남은 정책 |
| [엑셀 API 명세](<../나드리고 api 마무리.xlsx>) | 관리자·가입·나드리 고객 API의 표·JSON 예시 및 통합 목록 |
| [ERD SQL](../erdcloud-current-plus-rental.sql) | 시각화용, 운영 실행 금지 |
| `app/` | 새 서비스 코드, 기존 조직 URL도 직접 구현 |
| `tests/` | 단위·권한·롤백·선택 MySQL 동시성 테스트 |
| `migrations/` | 승인 범위의 실행 SQL과 적용 안내 |
| `docs/` | 구현 진행·의존성·검증 기록 |

서비스 시작 시 `create_all`이나 마이그레이션을 자동 실행하지 않는다. 기존 웹 권한을 넓히거나 관리자를 자동 배정하지 않는다. 실제 운영에서는 HTTPS, 접근 로그 비밀값 제외, 신뢰하는 프록시 범위, DB 권한·백업·마이그레이션 실행 주체를 별도로 설정한다.
