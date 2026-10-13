# 백엔드 API 검증 결과

## 최종 결과 — 사용자 승인 재시작 후

사용자가 수정한 `.env`를 반영하도록 API를 재시작했다. 실행 중 서비스와 dotenv의 모든 Settings 필드가 일치하고 FCM Certificate 파싱이 양쪽에서 성공했다. 이전 503은 재현되지 않았다. 제안했던 UnsetEnvironment drop-in은 설치하지 않았다.

**실제 서버 재검증 40개 및 별도 인증 오류 검사 8개, 총 48개 실행이 모두 통과했다.** 아래 이전 실패 기록은 재시작 전 이력이다. 격리 API 219개·Firestore 4개·Rules 4개·Python 함수 6개의 업무 핸들러 통과 결과도 유지한다.

| 실제 서버 항목 | 최종 결과 |
| --- | --- |
| 지정 UID의 Firebase custom token 인증 → ID token 폐기 확인 → 백엔드 로그인 | 200, access/refresh 발급 |
| UID 불일치 | 401 FIREBASE_UID_MISMATCH |
| 고객 프로필·진행/완료 예약 목록 | 200 |
| 고객 채팅 세션 | 200, 지정 firebaseUid 및 asia-southeast2 확인 |
| 고객 refresh 회전·이전 refresh 거절 | 200 / 401 INVALID_REFRESH_TOKEN |
| 대표·일반관리자 로그인과 역할 응답 | 200, 각 rental_primary_admin / rental_manager 확인 |
| 대표·일반관리자 채팅 세션 | 200, 직접 테스트 지점만 shops에 포함 |
| 대표 전용 관리자 가입 요청 조회 | 대표 200, 일반관리자 403 PRIMARY_ADMIN_REQUIRED |
| 두 관리자 지점 프로필·알림 목록·미읽음 수 | 200 |
| 두 관리자 타 지점 알림 조회 | 404 SPOT_NOT_FOUND, 범위 밖 지점 데이터 반환 없음 |
| 잘못된 입력·없는 예약 취소 | 422 INVALID_INPUT / 404 RESERVATION_NOT_FOUND |
| 인증 누락·잘못된/만료 access·잘못된 refresh·고객/관리자 토큰 교차 사용 | 모두 401 |
| 고객·대표·일반관리자 테스트 로그아웃 | 모두 200 |

초기 재시작 후 검사에서 타 지점 오류를 403으로 예상하여 두 항목이 테스트 실패로 표시됐다. `app/rental_common.py`의 resolve_spot은 실제 존재하는 범위 밖 지점도 404 SPOT_NOT_FOUND로 숨긴다. 확인된 정책에 맞춰 기대값을 수정하고 다시 실행했으며 최종 실패는 0개다. 서버 코드는 수정하지 않았다.

정상 로그인·채팅 세션 발급에 필요한 승인된 고객의 렌탈 사용자 행, 관리자 Firebase 채팅 사용자, 테스트 refresh/채팅 세션은 정상 API 경로로 생성됐다. 마지막에 세 계정을 로그아웃하여 테스트 업무·채팅 세션을 폐기했다. Auth 사용자나 렌탈 사용자 행을 삭제하지 않았다. FCM 토큰은 요청에 넣거나 변경하지 않았으며 실제 예약·결제·환불·푸시는 실행하지 않았다.

실제 예약 생성·취소 성공 및 알림 읽음 변경은 운영 환경에서 실행하지 않고 앞선 격리 DB 테스트 결과로 구분한다. 실제 배포 callable의 유효 App Check 종단 검증, 앱 화면·실기기 푸시, Google/Apple 등 앱 로그인 제공자 흐름은 여전히 별도 미검증 범위다.

## 이전 검증 기록

## 사용자 env 수정 후 재검증

2026-10-13 사용자 수정 후 실제 API를 다시 검사했다. Firebase 인증·폐기 검증과 인증 누락/입력 거절 5개는 통과했고, 고객 로그인·UID 불일치 검증·대표/일반관리자 로그인 4개는 이전과 동일한 503으로 실패했다. 정상 세션 이후 검증은 여전히 미검증이다.

`.env` 수정 시각은 02:22:54 UTC이며 실행 중 API는 01:28:55 UTC부터 같은 MainPID 1597120으로 동작 중이다. dotenv의 FCM Certificate 파싱은 성공하지만 실행 중 서비스 환경의 파싱은 여전히 ValueError다. 파일 변경만으로 이미 실행된 프로세스의 환경 변수가 갱신되지 않았다. 서비스 재시작 후 systemd가 수정된 값을 정상 파싱하는지는 아직 확인하지 않았다. 이번 재검증에서 env 수정·서비스 재시작·Firebase 재배포는 수행하지 않았다.

초기 검증일: 2026-10-13 UTC. 아래는 재시작 전 기록이며 최종 결과는 문서 상단을 따른다. 초기 실제 API 정상 로그인은 503으로 실패했다.

## 대상과 테스트 계정

실제 API는 `https://na-dree.com`, 서비스는 `nadree-api.service`, Firebase Auth/FCM 프로젝트는 `bail-472405`다. 공유 DB는 `RIDERLOG_V2_DATA_TEST`지만 삭제 가능한 격리 DB로 취급하지 않았다.

고객 Firebase UID는 사용자가 승인한 `Ux1J9v9q8FQPUuAtrwRob0SYxzx1`이다. 존재하고 비활성화되지 않은 사용자임을 확인한 뒤 Firebase custom token을 실제 Auth 서비스에서 ID token으로 교환했다. Admin SDK의 `check_revoked=True` 검증도 통과했다. Google/Apple 등 실제 앱 로그인 제공자의 화면·재인증 흐름을 검증한 것은 아니다.

기존 시드 SQL과 실제 계정·유효 역할·지점 연결을 읽기 전용으로 비교했다. 관리자 비밀번호는 기존 전달 문서에서 실행 중 메모리로만 읽고 출력하지 않았다. 시드 재실행·비밀번호 초기화는 하지 않았다.

| 계정 | ID | 실제 유효 역할 | 지점 |
| --- | --- | --- | --- |
| nadree.test.admin | 00000000-0000-4000-8000-000000000201 | rental_primary_admin | 00000000-0000-4000-8000-000000000101 |
| nadree.test.manager | 00000000-0000-4000-8000-000000000202 | rental_manager | 동일 지점 |

두 계정과 지점은 활성 상태, MFA는 none, 역할 만료일은 없고 지점 scope는 manage다. 기존 FCM 값은 로그인 요청에서 생략하여 변경하지 않았다.

## 실제 서버 결과

최종 실행 기준 13개 통과, 4개 실패다. 토큰·개인키·비밀번호는 결과 파일에 기록하지 않았다. 로그인 실패로 이후 정상 세션 기반 업무 요청은 실행하지 못했다.

| 항목 | 결과 | 실제 근거 |
| --- | --- | --- |
| 지정 UID Firebase 인증 및 폐기 확인 | 통과 | 실제 custom token → ID token 교환 200, check_revoked 검증 성공 |
| 고객 Firebase 토큰 누락 | 통과 | 401 FIREBASE_ID_TOKEN_REQUIRED |
| 고객 로그인 잘못된 입력 | 통과 | 422 INVALID_INPUT |
| 고객 UID 불일치 거절 | 실패 | 기대 401 대신 503 CUSTOMER_FIREBASE_AUTH_NOT_CONFIGURED |
| 고객 백엔드 로그인·access/refresh 발급 | 실패 | 503 CUSTOMER_FIREBASE_AUTH_NOT_CONFIGURED |
| 대표관리자 로그인 | 실패 | 503 CHAT_SYNC_FAILED |
| 일반관리자 로그인 | 실패 | 503 CHAT_SYNC_FAILED |
| 고객 프로필·관리자 채팅 인증 누락 | 통과 | 각각 401 INVALID_NADRI_USER_TOKEN / AUTH_REQUIRED |
| 고객·관리자 잘못된 access token | 통과 | 각각 401 INVALID_NADRI_USER_TOKEN / AUTH_REQUIRED |
| 고객 잘못된 refresh token | 통과 | 401 INVALID_REFRESH_TOKEN |
| 예약·취소·알림함 인증 누락 | 통과 | 유효한 형식의 요청에서 모두 401 |
| 고객·관리자 만료 access token | 통과 | 실제 서명 키로 만든 만료 토큰을 각각 401로 거절 |

예약 요청에 인증 누락과 잘못된 본문을 동시에 주면 422 INVALID_INPUT이 먼저 반환됐다. 유효한 본문으로 분리해 다시 검사하면 401을 반환했다. 두 오류의 검증 순서를 인증 우회로 판단하지 않는다.

비밀값 없는 실행 결과는 `build/test-runtime/backend-live-verification-2026-10-13.json` 및 `backend-live-negative-verification-2026-10-13.json`에 보관했다. build는 git에서 제외된다.

## 503 원인과 승인 대기 수정안

서비스의 EnvironmentFile과 Python Settings의 dotenv 파서가 역슬래시를 다르게 처리한다. `/proc/<MainPID>/environ`의 값은 출력하지 않고 Settings 필드별 동일 여부와 키 파싱 결과만 비교했다.

- dotenv 단독: FCM 개인키의 literal `\\n` 28개를 소스의 정규화 코드가 실제 줄바꿈으로 바꾸며 Certificate 파싱 성공.
- systemd 실행 환경: literal `\\n`과 실제 줄바꿈 모두 0개이며 Certificate 파싱 ValueError.
- 로그: Customer Firebase initialization failed: ValueError. 관리자 로그인은 기존 채팅 세션 revoke의 초기화 실패를 CHAT_SYNC_FAILED로 반환.
- 모든 Settings 비교에서 다른 필드는 `fcm_private_key`, `location_firebase_private_key` 두 개뿐이었다. 차량 위치 설정도 파서 차이가 있으나 이번 승인 범위 밖이며 수정하지 않았다. 차량 위치 기능 자체를 이번 검증에서 호출하지 않았다.

최소 수정안은 [서비스 drop-in 초안](../deployment/nadree-api-firebase-env.conf)의 `UnsetEnvironment=NADREE_FCM_PRIVATE_KEY` 한 줄이다. 서비스가 상속받은 손상된 FCM 개인키 변수만 제거하면 기존 Settings가 보호된 `.env`에서 해당 값만 정상적으로 읽는다. `.env` 원문·키·FCM 계정·프로젝트·Auth 검사·App Check·차량 위치 설정·Firebase 함수·DB는 변경하지 않는다.

**아직 설치하거나 API를 재시작하지 않았다.** 승인 후 `/etc/systemd/system/nadree-api.service.d/firebase-env.conf`에 설치, daemon-reload, nadree-api.service 재시작, health 및 같은 테스트 계정의 로그인→refresh→채팅 세션·권한·안전한 읽기 요청을 다시 검증한다. 실패 시 이 신규 drop-in만 제거하고 daemon-reload·재시작하여 기존 환경 로딩 방식으로 복구한다. API 재시작에 짧은 요청 중단 가능성이 있다. 기존 checklist의 서비스 재시작 승인 기준과 사용자의 재시작 사전 승인 요구에 따라 추가 수리 적용은 대기한다.

## 격리 DB·에뮬레이터 결과

| 범위 | 결과 | 확인한 내용과 한계 |
| --- | --- | --- |
| 전체 Python API 회귀 | 219개 통과 | 임시 SQLite fixture와 네트워크 비활성 임시 MySQL 8.4.6. MySQL 동시성 6개 포함. Firestore 3개만 별도 실행 대상으로 건너뜀 |
| Firestore 통합 | 4개 통과 | demo-nadree-chat. 문의 생성·메시지 재시도 동시성, 최초 예약 승격, 종료/만료 후 재개 차단, 대표 답변·직원 열람만 허용·타 사용자 차단·읽음·이벤트 중복 방지·세션 만료 |
| Firestore Rules | 4개 통과 | 소속·소유자 조회, 클라이언트 쓰기 차단, 쿼리 범위 제한, 세션 불일치·인증 누락 차단 |
| 실제 Python 함수 업무 핸들러 | 통과 | ensureInquiryChat, ensureBookingChat, sendChatMessage, markChatRead, getChatUnreadSummary 및 expireInactiveInquiries를 demo Firestore에 연결하여 실행 |

함수 업무 핸들러 테스트는 합성 auth/session과 AnonymousCredentials로 에뮬레이터 DB에만 연결했다. SDK의 HTTP 래퍼를 unwrap하여 **업무 로직만** 검증했다. 실제 배포 callable의 ID token/App Check HTTP 검증을 통과했다는 의미가 아니다. 운영 App Check·인증 검사는 해제하지 않았다.

API 회귀는 대표·일반관리자·타 지점 접근 거절, access/refresh 발급·회전·폐기·audience 분리, Firebase UID/폐기 검증, 예약 생성·가용성 오류·취소 상태/권한/날짜 경계, 알림함 목록·읽음 공유·중복 방지 등을 포함한다. 외부 Firebase 검증 일부는 테스트 대역이며 실제 정상 API 인증과 구분한다. 결제·환불 시나리오의 PayPal 및 FCM은 메모리 대역으로만 실행했다. 실제 PayPal Sandbox 호출도 이번 범위에서는 하지 않았다.

추가한 재현 테스트는 [Firestore 권한·읽음 테스트](../tests/test_chat_firestore.py)와 [함수 업무 에뮬레이터 테스트](../chat/tests/callable_business_emulator.py)다. 초기 추가 테스트의 컬렉션 이름과 SDK 중첩 래퍼 호출 오류는 테스트 코드에서 수정했고, 최종 에뮬레이터 실행은 모두 통과했다. 운영 소스는 수정하지 않았다.

## 미검증·범위 밖

- 실제 API의 고객 access/refresh 발급·회전, 고객/관리자 채팅 세션 정상 응답: 로그인 503 때문에 미검증.
- 실제 서버 세션으로 대표·일반관리자 권한 및 타 지점 차단, 예약 목록·알림함 정상 응답: 미검증. 격리 API 테스트에서는 통과.
- 실제 예약 생성·취소·알림 읽음 변경: 실제 고객/푸시/환불을 건드리지 않기 위해 수행하지 않음. 격리 DB에서 검증.
- 배포 callable의 유효 App Check 포함 종단 검증, 실제 앱 화면·실기기 푸시 수신: 사용자 지정 별도 범위.
- 별도 결제 개발 미구현 항목은 이번 테스트로 완료되지 않는다. 결제 상태 불명확 예약 만료, 뒤늦은/중복 결제 자동 환불 및 실패 환불 재시도 등은 기존 [서버 체크리스트](server-work-checklist-2026-10-12.md)를 유지한다.

실제 고객 예약·결제·환불·푸시, 운영 DB 마이그레이션·시드·비밀번호 초기화·Firebase 함수/Rules/인덱스 변경·서비스 재시작은 이번 검증에서 실행하지 않았다. 임시 MySQL과 Firestore 에뮬레이터는 최종 실행 후 종료했다.
