# 나드리 신규 채팅 실제 적용 결과

후속 실제 계정 검증의 로그인 503은 사용자 env 수정과 승인된 API 재시작으로 해결됐다. 실제 인증·로그인·refresh·고객/관리자 채팅 세션·권한·오류 응답 48개가 통과했다. App Check 종단·앱 화면·기기 푸시는 별도 미검증이다. 최신 [백엔드 API 검증 결과](backend-api-verification-2026-10-13.md)를 따른다.

적용일: 2026-10-13 UTC. 수행: Codex, 사용자 승인에 따른 서버·Firebase 적용. 대상 코드 커밋 `e7ead60`. 이 결과와 새 deployment 자산·문서는 아직 커밋하지 않았다. 기준은 [채팅 계약](../chat/chat-contract.md)과 [승인된 실행안](chat-new-build-deployment-plan-2026-10-13.md)이다.

**서버·Firebase 적용과 격리 테스트는 완료했다. 승인된 실제 고객/관리자 테스트 계정·App Check 앱·기기 자료가 없어 정상 로그인부터 메시지·실기기 푸시까지의 인수는 미검증이다. 전체 출시 인수 완료로 판정하지 않는다.** 기존 데이터 이전·구버전 호환 코드는 추가하지 않았다.

## 삭제 전 확인과 교체 통제

Python 3.12.14의 Functions 전용 venv에서 requirements 설치와 pip check를 완료했다. firebase-functions 0.6.0, firebase-admin 6.9.0이며 의존성 충돌은 없었다. Firebase SDK 소스 분석에서 정확한 endpoint 6개, 자카르타 리전, timeout 60초/maxInstances 10, 15분 만료 schedule/UTC/retry 3을 확인했다.

실제 배포 계정 qwer886901@gmail.com의 검사 대상 배포 권한은 모두 허용됐고, 실제 build/runtime 서비스 계정에 actAs를 확인했다. 필수 API도 모두 ENABLED였다. FCM 런타임 서비스 계정에 배포 관리자 권한을 추가하지 않았다.

사전 검사에서 API는 채팅 활성 true였으며 chatUsers/chatRoomAccess/chatRooms/chatPushEvents는 모두 최상위 문서 0개였다. 실행 중 app.chat_sync, 로컬 cron/systemd 동기화 등록은 발견하지 못했고 전체 Cloud Scheduler 조회는 작업 0개였다. .env의 채팅 설정만 false로 바꾸고 nadree-api.service를 재시작해 새 세션·업무 동기화 진입을 막았다. 설정 false와 정상 health를 확인한 뒤 채팅 문서 0개·실행 중 sync 없음·읽기 전용 DB No pending changes를 다시 확인하고 삭제했다.

env=false가 Firebase 접근을 폐기한다고 판단하지 않았다. 당시 유효 세션 문서가 없고 현재 Rules와 기존 callable이 chatUsers 활성 상태를 요구하는 것을 함께 확인했다. 기존 Authentication 사용자·토큰의 대량 폐기나 사용자 삭제는 하지 않았다.

삭제 전 함수 소스 ZIP/메타데이터, Rules, 전체 인덱스, Scheduler와 .env의 접근 제한 백업을 git에서 제외되는 build/chat-cutover-2026-10-13에 보존했다. .env 백업 및 함수 설정 원문은 비공개이며 이 문서에 기록하지 않는다. 채팅 설정의 편집은 원래 파일 소유권·권한과 다른 설정을 보존했다.

## 실제 함수 적용

프로젝트 bail-472405 / asia-southeast2. 원래 default/nodejs22의 7개를 정확히 삭제했다. 아래 5개는 같은 이름의 nadree-chat/python312로 차례로 재생성했고 만료 함수는 삭제 없이 갱신했다.

| 함수 | 실제 작업 | 최종 상태 |
| --- | --- | --- |
| notifyBookingChatMessage | 기존 Node.js 트리거 삭제 | 제거됨, 재생성 안 함 |
| setChatStatus | 기존 Node.js callable 삭제 | 제거됨, 재생성 안 함 |
| ensureInquiryChat | Node.js 삭제 → Python 생성 | ACTIVE / nadree-chat / python312 |
| ensureBookingChat | Node.js 삭제 → Python 생성 | ACTIVE / nadree-chat / python312 |
| sendChatMessage | Node.js 삭제 → Python 생성 | ACTIVE / nadree-chat / python312 |
| markChatRead | Node.js 삭제 → Python 생성 | ACTIVE / nadree-chat / python312 |
| getChatUnreadSummary | Node.js 삭제 → Python 생성 | ACTIVE / nadree-chat / python312 |
| expireInactiveInquiries | 기존 Python 함수 갱신 | ACTIVE / nadree-chat / python312 |

각 함수 source provenance의 generation을 지정해 배포 ZIP을 다시 내려받고 main.py·chat_core.py·requirements.txt가 저장소 파일과 바이트 동일함을 확인했다. 6개 소스 hash는 모두 `441cc478d006b487e9652982ecca439a0ddb9b08`이며 실제 entryPoint도 함수 이름과 일치한다. CHAT_ENFORCE_APP_CHECK override는 없고 소스의 기본 강제 true를 사용한다.

삭제·배포 CLI가 빌드 이미지 정리 경고를 출력했으나 각 함수 작업과 Deploy complete는 종료 코드 0이었다. 잔존 빌드 이미지 정리 및 비용 확인은 별도 운영 항목이다. 범위 밖 컨테이너/이미지 삭제를 추가로 실행하지 않았다.

## Rules 인덱스와 만료 스케줄

Rules 컴파일·release 적용을 완료했다. 기존과 내용이 같아 소스 업로드는 건너뛰었고 최종 ruleset은 `6a1de722-8439-466f-b5b9-772b5b38234b`다. 채팅 외 규칙은 이번 적용 전후 바꾸지 않았다. 글로벌 allow를 추가하지 않았다.

전체 인덱스 백업과 실제 조회는 chatRoomAccess 4개/fieldOverrides 0개였으며 적용 후 모두 READY다. 복합 필드는 shopId+updatedAt DESC, customerUid+updatedAt DESC, shopId+customerUid, kind+status+expiresAt이다. 인덱스 삭제나 비채팅 정의 변경은 하지 않았다.

Cloud Scheduler 작업은 자카르타의 `firebase-schedule-expireInactiveInquiries-asia-southeast2` 한 개다. 상태 ENABLED, schedule every 15 minutes, timeZone UTC. 해당 채팅 작업에 1회 run을 요청해 HTTP 200을 받았고, 2026-10-13 01:32:13 UTC 이후 실제 Cloud Run 요청 로그 HTTP 200 및 job status code 0을 확인했다. 실행 시 문의방은 없었고 예약방·결제·푸시를 대상으로 처리하지 않았다. 채팅 외 스케줄은 변경하지 않았다.

## API와 서버 동기화

Firebase 실제 상태·배포 소스 검증 후 채팅 설정을 true로 복원하고 nadree-api.service를 재시작했다. 서비스 사용자 ec2-user, WorkingDirectory /srv/nadree-api, active다. 다른 .env 설정은 보존했다.

| 확인 항목 | 실제 결과 |
| --- | --- |
| 공개 health/live | status ok, nadree-api |
| 공개 health/ready | status ok, 기존 MFA_FLOW_NOT_IMPLEMENTED 제한 표시 |
| 공개 OpenAPI | 관리자/고객 chat/session, /nadreego/notifications 경로 확인 |
| 공유 DB | RIDERLOG_V2_DATA_TEST. 읽기 전용 migrate No pending changes. 마이그레이션 미실행 |
| 초기 sync | nadree-chat-sync.service 1회 실행 Result=success / ExecMainStatus=0 |
| SQL 기준 동기화 대상 | 지점 24개, 예약 8개 |
| 실제 Firestore 결과 | chatShops 24개, bookingChatAccess 8개, chatRoomAccess 8개. 예약방 필수 필드·kind=booking·expiresAt=null 검증 |
| 로그인/푸시 데이터 | 확인 시 chatUsers 0개, chatPushEvents 0개, SQL 알림 0개. 실제 고객 푸시 테스트 없음 |

단일 동기화 [service](../deployment/nadree-chat-sync.service)와 [timer](../deployment/nadree-chat-sync.timer)를 문법 검증 후 /etc/systemd/system에 설치했다. timer는 enabled/active이며 초기 동기화 성공 후 활성화했다. OnBootSec=1min, OnUnitInactiveSec=1min으로 같은 유닛의 직전 실행 종료 후 1분 뒤 다시 실행한다. 첫 자동 실행도 Result=success / ExecMainStatus=0을 확인했다. 별도 cron은 등록하지 않았다.

SQL→Firestore의 현재 카탈로그·예약 동기화는 기존 채팅 데이터 이전과 구분된다. 기존 chatRooms 메시지·읽음·토큰의 이전/호환 처리나 일괄 삭제는 하지 않았다. 공유 DB의 예약·권한 데이터와 기존 SQL 알림을 테스트 시드로 재생성하지 않았다.

## 테스트 결과와 미검증 항목

| 범위 | 실제 결과 | 해석 |
| --- | --- | --- |
| 전체 Python 회귀 | 219 passed, 3 skipped, 2 deprecation warnings, 46.63초 | 새 네트워크 비활성 MySQL 8.4.6의 nadree_w02_test_* 및 임시 SQLite 사용. 운영 .env/외부 자격증명 전달 없음 |
| 건너뛴 Firestore 트랜잭션 | 별도 3 passed, 10.96초 | demo-nadree-chat Firestore emulator 1.19.8 |
| Rules | 별도 4 passed | demo 에뮬레이터에서 현재 Rules. 로그의 PERMISSION_DENIED는 금지 요청의 기대 거절 |
| 배포 callable 입구 | 5개 모두 실제 HTTP 401 / UNAUTHENTICATED | Auth/App Check 없는 data={} 요청. 정상 인증·App Check 성공 흐름을 대신하지 않음 |
| 만료 함수 실행 | 실제 Scheduler 요청 및 Cloud Run HTTP 200 | OIDC/실행 경로 확인. 실제 문의 168시간 경계는 격리 테스트로 검증 |
| 서버 실제 연동 | 현재 SQL 대상이 새 Firestore 구조로 생성됨 | 초기 sync 및 자동 실행 성공 |

따라서 Python 테스트 222개는 전체 회귀 219개와 별도 Firestore 3개로 모두 실행했고 Rules 4개는 별도다. 222개를 한 번의 실행에서 통과했다고 보고하지 않는다. 임시 MySQL과 Firestore 에뮬레이터는 종료했다.

**미검증:** 승인된 실제 고객/대표/일반관리자 테스트 계정으로 API 세션 발급→custom token 교환→유효 App Check callable, 실제 기기 메시지·읽음·권한/세션 회수·푸시·SQL 알림함, 앱 로그아웃 캐시 정리, Firebase 장애와 공유 서버 권한 변경 경합. 테스트 식별자·App Check 앱·기기 자료를 요청했지만 이번 작업 중 제공되지 않았다. 실제 고객을 대신 사용하지 않았다.

**남은 구현/연동:** 공유 서버·직접 SQL 소속 변경 시 즉시 채팅 회수 연결. 현재 주기 재확인은 즉시 회수의 대체가 아니다. 동기화는 전량 조회이고 푸시는 best-effort로 프로세스 종료 후 영속 전달을 보장하지 않는다. 결제·환불 등 별도 잔여 개발은 이번 채팅 배포로 완료되지 않는다.

고객·관리자 앱 담당자는 [연동 요구사항](chat-app-integration-requirements-2026-10-13.md)을 따른다. 프로젝트 bail-472405, 리전 asia-southeast2, API https://na-dree.com이며 setChatStatus/notifyBookingChatMessage는 사용하지 않는다. 정상 App Check 등록·실기기 인수 완료 전 전체 출시 가능으로 보고하지 않는다.

## 보존과 복구 자료

승인된 채팅 함수와 채팅 전용 Rules/인덱스/스케줄, API 채팅 키와 승인된 재시작·동기화만 적용했다. 기존 FCM·Authentication 사용자·차량 위치 기능, 채팅 외 데이터·설정의 변경·삭제는 수행하지 않았다. 새 Auth 사용자도 테스트 목적으로 만들거나 삭제하지 않았다.

비공개 백업과 실제 상태 확인 JSON/소스 ZIP은 build/chat-cutover-2026-10-13에 있다. 장애 시 단순 env=false만으로 기존 Firebase 세션을 폐기하지 않고 승인된 접근 통제와 sync/timer를 함께 처리한다. 보안 문제가 확인된 이전 Node.js 함수를 자동 복원하지 않는다. 데이터 이전·구버전 호환·공유 DB 테이블 삭제를 복구 수단으로 추가하지 않는다.
