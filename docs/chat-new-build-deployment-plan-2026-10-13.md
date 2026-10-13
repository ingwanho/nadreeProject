# 나드리 채팅 신규 구축과 함수 정리 실행안

기준일: 2026-10-13 UTC. 상태: 사용자 방향 확정, 삭제·배포 실행 승인 대기. 정본은 [채팅 계약](../chat/chat-contract.md)과 현재 Python 구현이다. 기존 데이터 이전·구버전 앱 호환·Node.js 호환 코드 없이 신규 구축한다. 이 문서 작성은 삭제·재배포·서버 재시작·동기화 실행이 아니다.

## 확인한 대상과 보존 범위

프로젝트는 bail-472405, 리전은 asia-southeast2, Firestore는 (default)다. 실제 조회에서 기존 Node.js 7개와 Python expireInactiveInquiries 1개가 ACTIVE였다. 현재 Rules는 저장소 chat/firestore.rules와 동일하다. 전체 인덱스 조회는 chatRoomAccess 복합 인덱스 4개와 빈 fieldOverrides를 반환했고 4개 모두 READY였다.

chatRooms, chatRoomAccess, bookingChatAccess, chatUsers, chatShops, chatInquiryKeys, chatPushEvents, chatNotificationJobs의 최상위 문서 수는 각각 0으로 조회됐다. 이는 전체 subcollection·토큰 문서의 부재까지 증명하지 않는다. 데이터 전체 삭제나 Authentication 사용자 정리를 수행하지 않는다.

보존 대상은 기존 FCM 프로젝트·업무 푸시 발송, 기존 Authentication 사용자·UID·앱 설정, 차량 위치용 별도 프로젝트와 기능, 채팅 외 함수·데이터·Rules·인덱스·스케줄, 공유 DB의 업무 데이터다. 앱 세션 발급 과정에서 필요한 관리자용 채팅 Firebase 사용자 생성은 계약의 정상 동작이지만 기존 Authentication 사용자 삭제/대량 변경은 하지 않는다.

현재 운영 Rules에는 채팅 허용 규칙과 기본 deny만 있다. 적용 직전 다시 내보내 채팅 외 규칙이 추가됐으면 보존·병합하고, 전체 allow로 채팅 보안을 약화하지 않는다. 인덱스도 전체 정의를 재조회해 삭제 없이 필요한 채팅 항목만 추가/확인한다. 차량 위치 프로젝트나 그 Rules에는 배포하지 않는다.

## 승인받을 Node.js 함수 7개

아래 정확한 함수에만 적용한다. 모두 bail-472405 / asia-southeast2 / default / nodejs22다.

| 함수 이름 | 정리 작업 | 후속 대상 |
| --- | --- | --- |
| notifyBookingChatMessage | 기존 Firestore 메시지 트리거 삭제 | 재생성하지 않음. 새 메시지 이벤트와 업무 서버가 알림 처리 |
| setChatStatus | 기존 callable 삭제 | 재생성하지 않음. 예약 종료는 SQL 동기화 기준이며 재개 API 없음 |
| ensureInquiryChat | 기존 callable 삭제 후 재생성 | 같은 이름, nadree-chat/python312 |
| ensureBookingChat | 기존 callable 삭제 후 재생성 | 같은 이름, nadree-chat/python312 |
| sendChatMessage | 기존 callable 삭제 후 재생성 | 같은 이름, nadree-chat/python312 |
| markChatRead | 기존 callable 삭제 후 재생성 | 같은 이름, nadree-chat/python312 |
| getChatUnreadSummary | 기존 callable 삭제 후 재생성 | 같은 이름, nadree-chat/python312 |

기존 Node.js 알림 트리거와 상태 변경 함수부터 정리하고 이어 다섯 callable을 제거한다. 동일 이름 재사용과 codebase 전환을 명확히 하기 위해 다섯 callable도 명시적 삭제·재생성 대상으로 승인받는다. 전환 동안 해당 callable은 일시적으로 제공되지 않는다. 이전 앱 호환은 제공하지 않는다.

expireInactiveInquiries는 이미 nadree-chat/python312이므로 삭제 대상이 아니다. 같은 이름·리전으로 소스를 확인/갱신하고 연결된 채팅 만료 스케줄만 확인/보완한다. 목록에 없는 함수·스케줄의 삭제를 CLI가 요구하면 중단한다.

승인 후 사용할 함수 삭제 명령의 범위는 다음과 같다. 지금은 실행하지 않았다.

```sh
firebase functions:delete notifyBookingChatMessage setChatStatus ensureInquiryChat ensureBookingChat sendChatMessage markChatRead getChatUnreadSummary --project bail-472405 --region asia-southeast2
```

## Python 함수 6개의 배포 순서

조건: 정본 코드·필수 의존성·비밀값 없는 백업 목록을 확정하고, 기존 일곱 함수 정리와 Rules/인덱스 확인을 승인받은 뒤 실행한다. 함수는 모두 nadree-chat / python312 / asia-southeast2다.

| 순서 | 함수 | 작업과 확인 |
| --- | --- | --- |
| 1 | ensureInquiryChat | 신규 생성. shopId/선택 productId, 고객 권한·세션·App Check |
| 2 | ensureBookingChat | 신규 생성. reservationId 매핑·본인/직접 지점 접근 |
| 3 | sendChatMessage | 신규 생성. 대표 답변 제한·UUID 중복·종료 차단·이벤트 원자 저장 |
| 4 | markChatRead | 신규 생성. 사용자별 누적 sequence |
| 5 | getChatUnreadSummary | 신규 생성. 고객 본인/직접 지점 직원 범위 |
| 6 | expireInactiveInquiries | 기존 Python 함수 확인/갱신. 15분 주기·UTC·retry 3 및 단일 Scheduler 연결 |

함수별 --only 대상으로 차례로 적용한다. 전체 codebase 배포의 병렬 순서를 위 순서로 보장한다고 주장하지 않는다. 예시는 다음과 같으며 뒤의 함수 이름을 표 순서대로 바꾼다.

```sh
firebase deploy --project bail-472405 --only functions:nadree-chat:ensureInquiryChat
```

배포 후 목록의 이름뿐 아니라 runtime/codebase/entryPoint/source hash·리전과 실제 테스트를 확인한다. App Check는 강제 상태를 유지한다. 테스트 편의를 위한 운영 비활성화는 하지 않는다. 기존 함수에 CHAT_ENFORCE_APP_CHECK=false가 잔존하지 않는지 선별 조회한다.

## Rules 인덱스 스케줄과 서버 적용

1. 적용 직전 전체 Rules/인덱스·함수·채팅 Scheduler와 서비스 환경의 비밀값 없는 상태를 읽는다. 백업은 접근 제한 경로에 보관한다. 공유 DB는 읽기 전용 migrate 계획을 확인한다. 새 DB pending이나 규칙 충돌이 발견되면 승인 범위를 다시 구체화한다.
2. 기존 함수 7개를 표대로 정리한다. 현재 계약과 동일한 Rules는 유지/필요 시 승인된 동일 정의를 적용한다. 인덱스 4개 READY를 확인하며 채팅 외 정의는 보존한다.
3. Python 6개를 순서대로 적용한다. 만료 스케줄의 실제 지역·target·15분 cron·단일 실행을 확인하고 해당 채팅 job만 생성/수정한다. 기존 expire 함수를 삭제해 스케줄을 해결하지 않는다.
4. API의 NADREE_FCM_CHAT_ENABLED 및 실제 실행 버전을 확인한다. 이전 조회에서는 true였으므로 활성화를 미실행 상태의 false로 가정하지 않는다. 승인 후 필요한 설정만 조정하고 nadree-api.service를 재시작한다. .env 원문·키·토큰은 출력하지 않는다.
5. app.chat_sync 1회 실행으로 SQL 최신 상품/예약을 새 계약 Firestore에 반영한다. 이는 이전 채팅 데이터 이전이 아니라 현재 업무 데이터 동기화다. SQL 알림함 쓰기와 FCM 발생 가능성이 있으므로 적용 직전 대기 이벤트·수신자 범위를 확인한다. 실제 고객 대상으로 테스트 푸시를 보내지 않는다.
6. 동기화의 단일 실행 주체를 확인하고 없을 때만 승인된 nadree-chat-sync.service/timer를 등록한다. 기존 cron과 중복 등록하지 않는다. 재시작/타이머/최초 동기화까지 승인 범위에 명시한다.

현재 계약의 app.chat_sync는 카탈로그·예약을 전량 재확인한다. Firebase 장애 시 일부 업무 종료·로그아웃/권한 변경이 CHAT_SYNC_FAILED로 실패할 수 있다. 배포 중 이 연결을 통제할 필요가 있으면 코드/설정·서비스 영향 범위를 보고하고 승인된 작업창에서 처리한다. 환경변수 false만으로 이미 발급된 접근을 폐기할 수는 없다.

## 격리 테스트와 실제 테스트 계정 인수

기존 격리 결과는 Python 213개 통과 후 건너뛴 MySQL 6개·Firestore 트랜잭션 3개가 별도 실행에서 통과, Rules 4개 통과다. 새 배포 전후에는 필요한 회귀와 Functions callable 입구의 Auth/App Check·응답/오류 처리도 확인한다. 위 결과는 실제 배포 callable/앱 인수 성공을 대신하지 않는다.

실제 연동에는 승인된 테스트 고객 UID, 대표/일반관리자 ID, 직접 지점·예약/모델 ID, 테스트 기기 토큰, App Check 등록 앱이 필요하다. 비밀 토큰은 비공개 런타임에서만 사용한다. 실제 고객 예약 취소·결제/환불·푸시는 테스트에 사용하지 않는다. 기능 확인에 필요한 테스트 예약 변경은 대상과 부작용을 확인한 뒤 테스트 계정에 한정한다.

확인할 시나리오는 API 세션 발급→custom token 로그인→자카르타 callable, 잘못된 Auth/App Check 거절, 고객 문의·상품 변경·첫 예약 전환·두 번째 예약 분리, 동일 UUID 재시도, 일반관리자 조회/알림 가능·전송 거절, 대표 답변, 개인 읽음/지점 공통 읽음, 예약 종료/만료·재개 거절, 로그아웃/다른 기기/권한 제거 시 접근 회수, SQL 알림함과 테스트 기기 푸시, 동기화 장애 복구다.

테스트 계정 자료와 앱 소스가 없으면 서버에서 확인 가능한 단계까지 수행하고 실기기/App Check/푸시는 미검증으로 남긴다. 고객·관리자 앱 담당 요구사항은 [별도 안내](chat-app-integration-requirements-2026-10-13.md)에 정리한다.

## 실패 시 처리와 승인 경계

삭제 전 소스 ZIP·함수 메타데이터·현재 Rules·인덱스·채팅 스케줄과 API 복구 자료를 보존한다. 새 배포 실패 시 먼저 채팅 접근·동기화·푸시를 승인된 범위에서 통제하고 실패한 신규 범위만 재적용한다. FCM/Auth 사용자·차량 위치·비채팅 규칙을 복구 대상으로 변경하지 않는다.

기존 Node.js의 확인된 보안 문제를 그대로 복원하는 자동 rollback은 하지 않는다. 필요 시 접근 차단을 유지한 채 운영 담당자와 안전한 복구 범위를 결정한다. 기존 채팅 데이터 이전이나 구버전 호환을 복구 수단으로 추가하지 않는다. 새로운 채팅 테스트 자료 삭제도 대상 목록을 기록하고 테스트 자료에 한정한다.

현재 승인 요청 범위는 **정확한 Node.js 7개 삭제, Python callable 5개 재생성, Python 만료 함수 확인/갱신과 15분 스케줄, 비채팅 보존을 전제로 한 Rules/인덱스 적용, API 필요 설정/재시작, 최초 동기화·단일 스케줄 적용**이다. 기존 데이터 전체 삭제, Auth 사용자 삭제, 공유 DB 마이그레이션, 채팅 외 함수/규칙/인덱스/스케줄 변경은 포함하지 않는다. 승인 전 이 운영 작업은 실행하지 않는다.
