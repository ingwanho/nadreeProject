# 최신 변경 서버 적용·검증 결과

대상 커밋: `7b94277` (`프론트 추가사항`). 수행일: 2026-10-13 UTC. 기준: AGENTS.md, 최신 [전체 인수 문서](nadree-full-change-handoff.md), [마이그레이션 안내](../migrations/README.md), [QR 시드](../migrations/test_seed_vehicle_qr.sql), 고객 앱·웹 전달 문서. 부모 명세 파일 `/srv/rental-project-master.md`, `/srv/rental-api-review-decisions.md`는 이 서버에 없어 직접 대조하지 못했다.

**테스트 DB 마이그레이션 4개와 API 재시작은 완료했다. 자동 테스트는 파일별 격리 실행에서 272개 통과했고 별도 Firestore 4개·Rules 4개·함수 업무 핸들러도 통과했다. 실제 API 검사 54개, 웹 읽기 검사 3개가 기대 응답과 일치했다. 실제 QR 정상 조회와 결제 타이머는 아래 사유로 보류했으므로 전체 인수 완료로 표시하지 않는다.**

## 1. 적용 내용과 사전 상태

| 항목 | 작업 전 확인 | 이번 처리 |
| --- | --- | --- |
| 코드 | git pull 완료, 작업 시작 시 git 변경 없음 | 최신 코드로 재시작 |
| DB 변경 | 읽기 전용 app.migrate에서 4개 pending | 백업 후 4개 적용, 최종 No pending changes |
| 이전 마이그레이션 | 도구가 다른 pending·충돌을 보고하지 않음 | 재실행·데이터 초기화 없음 |
| 기존 테스트 지점/관리자/웹 모델 | 이전 검증 자료 및 실제 조회/가격 응답으로 확인 | 전체 기존 시드 실행 없음 |
| QR 전용/센서 차량 시드 | 대상 8개 업무 테이블의 차량/센서 행 모두 0개 | 키 조건 때문에 삽입 보류 |
| 의존성 | requirements.lock와 설치 버전 모두 일치, pip check 성공 | 설치/업그레이드 불필요 |
| 결제 작업 | payments/all cron·systemd 활성 등록 미발견 | 사용자 지시에 따라 실행·타이머 등록 보류 |
| 채팅 작업 | 기존 단일 nadree-chat-sync.timer/service 존재 | 중복 설치·수동 실행 없음 |
| Firebase | 함수 소스·Rules·인덱스·스케줄 일치 | 추가 배포·삭제·데이터 정리 없음 |

서비스는 `nadree-api.service`, 실행 사용자는 `ec2-user`, WorkingDirectory는 `/srv/nadree-api`, 가상환경은 `/srv/nadree-api/.venv`다. 실제 DB는 **RIDERLOG_V2_DATA_TEST / MySQL 8.0.45**, 관련 10개 테이블은 모두 InnoDB다. PayPal 환경은 SANDBOX이며 채팅은 활성 상태다. DB 이름이 TEST여도 초기화 가능한 DB로 취급하지 않았다.

## 2. 적용 완료 내역과 복구 수단

백업이 확인되지 않아 사용자에게 질문했고 **접근 제한 백업 생성 후 적용 승인**을 받았다. 변경 대상 및 QR 관련 10개 테이블을 single-transaction으로 백업했다. 디렉터리 700, 백업 파일 600, 자격정보 임시 파일은 실행 후 제거했다. 백업 원문은 출력하거나 문서에 넣지 않았다.

- 백업: `build/server-apply-2026-10-13/pre-apply-044642.private.sql`
- 874,660 bytes, 10개 CREATE TABLE 포함 검증.
- SHA-256: `d355ae9564e1cf0ded0b7deb7c9702ef34f988826603b523d0972d3c5af00965`.
- 보호된 동일 디렉터리의 backup-manifest.json에 대상 테이블·파일 체크섬을 보관했다.
- 백업 생성/구조/체크섬을 확인한 것이며 실제 복원 리허설은 수행하지 않았다. 전체 DB 백업도 아니다.

정확한 적용 범위는 아래 네 컬럼이다. 과거 값을 추정하여 채우거나 기존 행을 UPDATE/DELETE하지 않았다.

| 테이블 | 추가 컬럼 | 실제 타입 |
| --- | --- | --- |
| MSP_RENTAL_PAYMENT | order_requested_at | DATETIME NULL |
| MSP_RENTAL_PAYMENT | capture_requested_at | DATETIME NULL |
| MSP_RENTAL_PAYMENT | refund_attempt_state | JSON NULL |
| MSP_RESERVATION_HISTORY | details | JSON NULL |

`app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST` 후 읽기 전용 계획을 두 번 재확인하여 No pending changes를 확인했다. 적용 전/후 결제 행 4개, 예약 이력 11개로 유지됐다. 이는 해당 두 테이블의 행 수 보존 확인이며 모든 업무 데이터의 바이트 동일성 검사는 아니다.

04:47:40 UTC API 재시작, MainPID 1625807, active/running을 확인했다. 실제 `/health/live`, `/health/ready` 모두 200이다. readiness의 기존 `MFA_FLOW_NOT_IMPLEMENTED` 제한은 남아 있다. 재시작 이후 조회한 오류 종류 필터에서 새 Traceback/SQL 컬럼/Firebase 초기화 오류는 발견하지 못했다. 첫 검증 스크립트는 DB 접속 중 ConnectionResetError(104)/MySQL 2006으로 시작하지 못했으나 재실행에서는 접속 및 전체 API 검사에 성공했다.

MySQL DDL 전체 롤백은 보장되지 않는다. 장애 시 외부 결제/복구 작업을 중지하고 실제 스키마와 PG 결과를 대조한다. 추가 nullable 컬럼을 무조건 삭제하거나 구버전 결제 코드로 즉시 되돌리지 않는다. 백업 복원은 기존 공유 데이터에 영향을 주므로 별도 승인과 대상 테이블 확인 후 수행하며, 이 백업 전체를 공유 DB에 무조건 덮어쓰지 않는다.

## 3. 자동 테스트 — 실제 API와 구분

| 실행 범위 | 결과 | 근거/한계 |
| --- | --- | --- |
| 최신 Python 테스트 전체 24개 파일 | 272 passed, 4 skipped | 파일별 pytest 프로세스, 임시 SQLite fixture·네트워크 차단 MySQL 8.4.6. 실패 파일 없음 |
| MySQL 동시성 | 6개 포함 통과 | 공유 DB가 아닌 격리 MySQL |
| 차량 QR | 14개 포함 통과 | QR_ONLY·QR_WITH_SENSOR 생성/조회, 일반관리자 조회·타 지점/무인증 차단, 가격 변경, 센서 분리 후 QR 유지, 센서 코드 대체 조회 거절, 중복/비활성/만료 |
| 결제 안전성 | 21개 포함 통과 | 주문/캡처 응답 유실·재전송 제한·중복/늦은 청구·웹훅 순서·환불 재시도. PayPal 대역만 사용 |
| 위치 정정·권한 회수·차량 이동 | 관련 파일 통과 | 격리 fixture. 실제 위치 Firebase/권한 변경은 실행 안 함 |
| Firestore 통합 | 별도 4 passed | demo-nadree-chat 에뮬레이터, 전량 실행에서 skipped된 4개를 별도 실행 |
| Firestore Rules | 별도 4 passed | 클라이언트 쓰기 금지, 직접 소속/소유자 읽기·세션/쿼리 제한 |
| Python callable 5개 및 만료 함수 | 업무 핸들러 통과 | 실제 소스의 핸들러를 demo Firestore로 연결, 합성 인증/session. 배포 HTTP/App Check 종단 검증과 다름 |

전량 단일 프로세스 실행은 180초와 600초 제한에서 AnyIO/TestClient 스레드 대기로 중단됐다. Assertion 실패로 확정하지 않았고 통과로도 표시하지 않았다. 동일 테스트를 생략/변경하지 않고 파일별 새 프로세스로 실행하여 24개 파일 모두 종료 코드 0을 얻었다. 단일 프로세스 대기 원인은 별도 미확정 항목이다. FastAPI/Starlette TestClient 의존성 경고 2종도 남아 있다.

재현 로그: `build/test-runtime/latest-per-file-tests.log`. 임시 MySQL과 Firestore 에뮬레이터는 최종 종료 확인했다.

## 4. 실제 서버 API·웹 검증

승인된 Firebase UID `Ux1J9v9q8FQPUuAtrwRob0SYxzx1`, 기존 테스트 대표 `nadree.test.admin` 및 일반관리자 `nadree.test.manager`를 사용했다. 임의 운영 계정은 사용하지 않았다. 기존 비밀번호는 실행 중 메모리에서만 읽고 FCM 토큰은 요청에서 생략했다. 테스트 종료 시 세 계정을 로그아웃했고 계정 삭제·역할 변경은 하지 않았다.

실제 인증·API 검사 **46개**와 별도 인증 거절 검사 **8개**는 기대 응답과 일치했다. 46개 중 QR 2개는 503 설정 차단 확인이며 정상 QR 조회 성공 수로 계산하지 않는다. 웹 공개 읽기 검사 **3개**도 통과했다.

| 요구사항 | 실제 결과 | 격리/미검증 구분 |
| --- | --- | --- |
| Firebase 고객 인증 → backend 로그인 | ID token 교환·check_revoked, UID 일치 검증, 200 access/refresh | 실제 앱의 Google/Apple 화면은 미검증 |
| 고객 refresh·profile·ongoing/completed | 200, refresh 회전·이전 토큰 401 | 승인 UID에 예약이 없어 실제 예약 상세의 모든 저장 스냅샷은 미검증 |
| 고객·관리자 채팅 session | 200, 지역 asia-southeast2·직접 테스트 지점 확인 | App Check/메시지 HTTP 종단은 별도 |
| 대표/일반관리자 분리 | 역할 응답 일치, 대표 전용 가입 요청 조회 200/403 | 실제 roleChange/adminDelete는 실행 안 함 |
| 타 지점 접근 | 두 관리자 모두 404 SPOT_NOT_FOUND | 존재하지만 범위 밖 지점을 숨기는 코드 정책과 일치 |
| 관리자 main·지점 profile·알림 목록/미읽음 | 모두 200 | 실제 읽음 변경은 실행 안 함 |
| 예약 잘못된 입력·존재하지 않는 예약 취소 | 422 / 404 RESERVATION_NOT_FOUND | 예약 생성·취소 성공은 격리 테스트 |
| 위치 정정 이력의 권한/없는 예약 | 대표 404 RESERVATION_NOT_FOUND, 일반관리자 403 PRIMARY_ADMIN_REQUIRED | 실제 위치 변경·기존 예약 변경 안 함 |
| 인증 누락·잘못된/만료 access·잘못된 refresh·토큰 교차 사용 | 모두 401 | 실제 인증 검사를 해제하지 않음 |
| 웹 가용성·가격 | 200, NRTEST-WEB-MODEL-125 및 currency/rentalDays/dailyFrom/dailyTo/totalFrom/totalTo/pricingTiers 확인 | 모든 배송 지역 조합은 격리 테스트 결과와 구분 |
| 잘못된 웹 대여 날짜 | 422 INVALID_INPUT | 실제 요청 |
| 문서 웹 Origin CORS | OPTIONS 200, 요청한 Origin 허용 확인 | 실제 브라우저 화면은 미검증 |
| 최신 OpenAPI | QR validate·위치 정정/이력 경로 존재, 잘못된 sensor/qr/resolve 경로 없음 | 스키마 노출 확인이며 API 업무 성공의 대체 근거가 아님 |

비밀값 없는 실제 결과는 `build/test-runtime/backend-live-verification-2026-10-13.json`, `backend-live-negative-verification-2026-10-13.json`, `latest-web-readonly-results.json`에 보관했다. 이전 날짜의 동일 파일은 이번 최신 결과로 갱신되므로 이전 문서의 수치와 구분한다.

## 5. QR 시드와 실제 QR 정상 조회 — 보류

현재 서버 QR 키가 최소 32바이트 조건을 충족하지 않는다. 사용자에게 확인했고 임시값을 유지하고 넘어가라는 답변에 따라 키 변경·검사 우회·짧은 키의 QR 해시 삽입은 하지 않았다. 실제 API는 대표·일반관리자 모두 `503 QR_VALIDATION_UNAVAILABLE`을 반환했다. 이는 예상 설정 차단이며 **QR_ONLY/QR_WITH_SENSOR의 실제 성공 검증은 미검증**이다.

읽기 전용 조회에서 QR 차량 2개와 관련 QR/상태/지점/센서 이력이 없음을 확인했다. 또한 SQL 시드의 `MSP_SENSOR.spot_id`가 실제 테이블에 없고 `spot_master_id`가 존재함을 확인했다. 원인과 수정 범위를 사용자에게 먼저 설명한 뒤 SQL의 센서 INSERT만 `spot_master_id` 및 직접 테스트 지점 값으로 정정했다. 업무 API 코드·DB 센서 컬럼은 변경하지 않았다. 이 SQL은 실제로 실행하지 않았고 정정한 SQL의 배치 실행 검증도 미실행이다.

향후 정상 키 설정이 확인되면 원문 `testQr123123`/`testQr456456`의 HMAC을 해당 서버 키로 계산하고, 중복 식별자·QR 해시 충돌·선행 지점/관리자/모델·실제 구조를 다시 확인한 뒤 없는 행만 추가한다. 기존 시드 전체 재실행·기존 QR 덮어쓰기·키 임의 교체는 금지한다. SQL 오류는 전체 트랜잭션 롤백으로 처리하며 --force를 사용하지 않는다.

## 6. 스케줄·Firebase

결제 복구 타이머는 등록돼 있지 않았다. 등록하면 현재 SANDBOX 결제 4건(PENDING 1·PAID 2·FAILED 1)을 조회하고 환불·예약 만료·푸시가 발생할 수 있음을 설명했다. 사용자가 **외부 영향 작업 보류, 격리 검증 진행**을 선택하여 `app.jobs payments`, refund_recovery --apply, 결제 타이머 설치/enable을 실행하지 않았다. 따라서 자동 결제 복구 운영 적용은 미완료다. 소스의 payments 작업은 MySQL GET_LOCK을 사용하지만 실제 타이머 적용 인수와 구분한다. 기존 채팅 타이머는 유지했다.

Firebase 프로젝트 **bail-472405**, 자카르타 **asia-southeast2**, codebase **nadree-chat**, Python **python312**다. list/get과 배포 ZIP 다운로드를 다시 수행했다.

- ensureInquiryChat, ensureBookingChat, sendChatMessage, markChatRead, getChatUnreadSummary, expireInactiveInquiries: 모두 ACTIVE.
- 6개 ZIP의 main.py·chat_core.py·requirements.txt가 최신 저장소 파일과 바이트 동일.
- Rules 소스 일치, ruleset `6a1de722-8439-466f-b5b9-772b5b38234b`.
- chatRoomAccess 복합 인덱스 4개 READY.
- expireInactiveInquiries 스케줄 하나, ENABLED, every 15 minutes, UTC.
- 실제 callable 5개 무인증 요청은 401 UNAUTHENTICATED. 유효 App Check 종단 검증은 하지 않음.

**이번 변경에 추가 Firebase 배포는 필요하지 않다.** 함수·Rules·인덱스·스케줄·위치 프로젝트·Authentication 사용자를 삭제/재배포하지 않았다.

## 7. 사용자 작업·프론트 전달

현재 추가 사용자 작업은 QR 정상 테스트를 원할 때 기존 정상 QR 키 설정을 확인하는 것, 외부 결제 검증을 원할 때 허용할 테스트 거래·환불·FCM 수신 대상과 타이머 가동 범위를 별도로 승인하는 것이다. 앱/웹 소스·실기기를 제공하지 않았으므로 화면 동작·실기기 푸시·유효 App Check 인수는 프론트/사용자 측 별도다. MFA 제한과 단일 프로세스 테스트 대기 원인도 남아 있다.

| 프론트 변경사항 | 전달 내용 |
| --- | --- |
| 차량 QR | POST /nadreego/vehicle/qr/validate에 QR 원문 qrCode 전송. 센서 코드·ID·클라이언트 해시 대체 금지. 현재 실제 서버는 임시 키 때문에 503 |
| QR 응답 | status/errorCode/data 유지, equipmentType·sensorId·sensorStatus·vehicle·availableActions 추가. QR_ONLY도 지원하며 availableActions는 권한 토큰이 아님 |
| 차량 생성 | qrToken 필수, sensorId는 선택/null. QR 정상 키 확보 후 시드/생성 검증 |
| 결제 복구 | PAYMENT_ALREADY_PAID / PAYMENT_IN_PROGRESS는 기존 상태 조회, PAYMENT_RECONCILIATION_REQUIRED는 운영 확인. 새 청구 반복 금지 |
| 위치 정정 | 대표만 CORRECTION·이전/정정 위치·reason 전송. LOCATION_SNAPSHOT_CHANGED면 최신 예약 다시 조회. 실매장 이전·배송지 변경과 혼동 금지 |
| 채팅 | 실제 고객/관리자 session 발급 검증 완료. 직원 열람·대표 답변 정책, 실제 callable/App Check는 별도 인수 |
| 테스트 정보 | 테스트 지점 00000000-0000-4000-8000-000000000101, 고객 UID 및 두 관리자 로그인 ID는 위 검증 절 참조. 비밀번호·토큰은 별도 보호 경로로 전달하며 이 문서에 넣지 않음 |

과거 인수 문서의 “채팅은 프론트만 처리”, “알림 테이블 없음”, 과거 취소 정책 및 센서 코드 QR 안내는 최신 채팅 계약·2026-10-12/13 정책보다 우선하지 않는다. 이 결과는 서버 적용 기록이며 앱 구현·RiderLog 전체 회귀·외부 PG·위치 기능 인수 완료를 의미하지 않는다.
