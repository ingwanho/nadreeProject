# Firebase 채팅 배포 호환성 읽기 전용 검토

확인: 2026-10-12 UTC, Codex. 소스 커밋 `ad02598`. 기준: `chat/chat-contract.md`, `docs/server-work-checklist-2026-10-12.md`, 현재 API/Functions 소스. 이 보고는 이전 서버 점검 이후의 상태를 기록한다. 실제 고객 데이터·메시지·토큰을 조회하거나 기능 호출로 검증하지 않았다.

## 결론

**현재 서버와 배포된 Node.js callable은 호환되지 않는다.** 이름·리전·ACTIVE 상태만 일치한다. 운영 Rules와 인덱스는 현재 Python 계약에 맞지만 배포 callable은 다른 계약을 구현한다. 활성화·재시작·덮어쓰기·삭제·DB 변경·동기화·스케줄 등록은 이번 검토에서 실행하지 않았다.

현재 서비스 계정 설정에서 `NADREE_FCM_CHAT_ENABLED=True`, API 서비스 active, 활성 시작 시각 2026-10-12 06:27:56 UTC를 확인했다. 이는 이번 검토가 수행한 변경이 아니다. 공개 OpenAPI에는 관리자/고객 채팅 세션과 알림함 경로가 있다. ready는 정상 응답하면서 `MFA_FLOW_NOT_IMPLEMENTED` 제한을 표시한다. 경로 존재는 실제 채팅 성공을 증명하지 않는다.

## 배포 메타데이터와 소스 근거

서비스 계정의 Functions v1/v2 조회는 403 PERMISSION_DENIED였으나 Firebase CLI 기존 인증으로 목록 및 v2 메타데이터, Cloud Storage의 **각 함수 sourceProvenance에 지정된 generation** 소스 ZIP을 모두 읽었다. 토큰·키·전체 환경변수를 기록하지 않았다.

| 함수 | 실제 codebase | 런타임 | 리전 | 배포 소스 |
| --- | --- | --- | --- | --- |
| ensureInquiryChat | default | nodejs22 | asia-southeast2 | 기존 TypeScript 및 lib JS |
| ensureBookingChat | default | nodejs22 | asia-southeast2 | 동일 |
| sendChatMessage | default | nodejs22 | asia-southeast2 | 동일 |
| markChatRead | default | nodejs22 | asia-southeast2 | 동일 |
| getChatUnreadSummary | default | nodejs22 | asia-southeast2 | 동일 |
| setChatStatus | default | nodejs22 | asia-southeast2 | 동일 |
| notifyBookingChatMessage | default | nodejs22 | asia-southeast2 | 동일, Firestore created 트리거 |
| expireInactiveInquiries | nadree-chat | python312 | asia-southeast2 | 현재 main.py/chat_core.py와 바이트 동일 |

8개 모두 ACTIVE. Node.js 7개는 2026-09-18 배포, 함수 hash `75ed68a233190332b3f9ad37e23630caf724ec01`. ZIP도 전부 같은 SHA256 `06f78148fb024896258a210763d5c0bf1460c657e6f07ec8255232ac69eb028e`다. package.json의 실행 진입점은 `lib/index.js`; TypeScript뿐 아니라 실제 lib/index.js·lib/chat.js도 확인했다.

Python 만료 함수는 2026-10-12 06:24:57 UTC 갱신, 함수 hash `441cc478d006b487e9652982ecca439a0ddb9b08`. ZIP SHA256 `4d45ac08754d7f36f91fc18380cd7a0e1e82afbf647ff8e916866e60328d2f33`. 동일 main.py SHA256 `11e016a3b388ed4638f458155229db35aaa6e6083f8be8444968c9e041bfdc3d`, chat_core.py `8cc3936f078b70941a6395fb684139a2a36a8bed71a8dbb0d085bb1fce06b9c8`.

소스와 선별 메타데이터는 비공개 `/tmp/nadree-deployed-chat-audit/`에 보관했다. 임시 경로이므로 장기 보존은 보장하지 않는다. ZIP 내 로그·환경 파일은 출력/실행하지 않았다. Git 저장소·원본 배포 커밋은 ZIP만으로 확정할 수 없다.

## 계약 비교

| 항목 | 현재 계약/서버 | 실제 배포 Node.js | 판정 |
| --- | --- | --- | --- |
| Auth | ID token chatSessionId와 chatUsers.sessionId 일치, active, expiresAt 검사 | request.auth 및 chatUsers.active만 검사 | 이전 기기·세션 만료 회수 불일치. 새 세션 발급으로 active가 다시 true가 되면 이전 ID token도 callable 검사 통과 가능 |
| App Check | 기본 true | 환경값이 정확히 'true'일 때만 강제. 실제 설정 키 없음 | 배포 코드상 강제 false |
| 직원 답변 | active 및 canReply=true인 직접 지점 대표 | active membership이면 shop 역할, canReply 미검사 | 일반관리자 답변 허용 가능 |
| 문의 입력 | shopId, 선택 productId | shopId만 허용, 추가 필드 거절 | productId 요청 실패 |
| 문의 사용자/매장 | chatUsers.kind=customer, shop.active, 상품 검증 | chatUsers.role=customer, shop.inquiriesEnabled 필요 | 서버 발급 문서에 필요한 필드가 없어 문의 거절 |
| 예약 매핑 | bookingChatAccess/SHA256(bookingId)의 roomId, closed, blocked | active/shopDisplayName/chatStatus 필요; roomId는 bookingId hash | 서버 생성 예약 문서 validAccess 실패 |
| 방/메시지 | chatRoomAccess 자체가 방, 그 아래 messages | chatRooms가 방/메시지, chatRoomAccess는 별도 active 접근 투영 | 현재 Rules가 Node.js 메시지 읽기 경로를 허용하지 않음 |
| 방 필드 | kind/status/lastSequence/expiresAt | roomType/chatStatus/sequence/상대별 count | Python 만료 함수는 기존 Node.js 문의를 만료시키지 못함 |
| 문의→예약 | 첫 예약에 같은 roomId/메시지/읽음 유지 | 별도 hash 예약방 및 linkInquiry로 링크 | 전환 계약 불일치 |
| 문의 재생성 | 만료/종료 후 새 UUID 방 | 고객·지점으로 결정된 같은 inquiry hash 방 재사용 | 종료 후 새 문의·168시간 만료 계약 미구현 |
| 메시지 | 소문자 표준 UUID, 원문 UTF-8 1~2000바이트; 발신자 읽음도 증가 | UUID v4(대문자도 허용), trim/개행 정규화 후 길이 검사; 발신자 읽음 미갱신 | 이름/반환 형태 일부만 동일, 상세 의미 불일치 |
| 읽음 | 방 아래 reads/uid의 전체 sequence | chatReads/uid/rooms/roomId의 상대별 roleSequence; 본인 메시지 읽음 거절 | position 의미·저장 경로 불일치 |
| unread | 직원 및 본인 고객, 본인 전체 sequence 기반 | 직원만, chatShopInboxes와 customerCount 기반 | 고객 거절·조회 구조 불일치 |
| 종료 | SQL 선행 blocked/closed 확인, read_only 불가역 | chatStatus만 확인; setChatStatus가 직원에게 open 변경 허용 | 예약 취소/반납 차단 및 재개 금지 불일치 |
| 오류 | CHAT_SESSION_REQUIRED, BOOKING_CHAT_SYNC_PENDING 등 | Sign in again, BOOKING_CHAT_NOT_READY 등 | 클라이언트 복구 분기 불일치 |

일부 성공 응답 키(roomId/bookingId, messageId/sequence, position, unreadMessages/unreadRooms)는 같지만 의미와 전제 조건이 달라 호환으로 판정할 수 없다. Rules는 Admin SDK callable 쓰기를 막지 못하므로 현재 Rules를 배포했다고 위 callable 권한 문제가 해소되는 것은 아니다.

## 알림·중복 검토

기존 notifyBookingChatMessage는 `chatRooms/{roomId}/messages/{messageId}` created를 감시하고 FCM을 직접 발송한다. `chatNotificationJobs`의 roomId/messageId/recipientUid hash와 기기별 done으로 자체 재시도를 관리한다. 토큰 경로는 `chatPushTokens/{uid}/tokens/{hash(token)}`이며 현재 서버의 단일 문서 token/sessionId 및 chatPushTokenOwners와 다르다. 기존 트리거는 active만 확인하고 현재 채팅 세션·만료·토큰 소유권 계약을 적용하지 않는다.

현재 Python send는 `chatRoomAccess/.../messages`와 `chatPushEvents/SHA256(roomId+':'+messageId)`를 같은 트랜잭션에서 생성한다. app.chat_sync는 inboxSynced=false를 읽고 SQL event_key=`chat:<event hash>`로 중복 알림함 삽입을 방지하며 서버가 FCM을 발송한다.

**현 소스 그대로는 두 발송기의 메시지 경로가 달라 같은 메시지에 대한 자동 중복 발송을 입증하지 못했다. 대신 기존 Node.js 메시지는 chatPushEvents를 만들지 않아 신규 SQL 알림함 동기화가 누락되고, Python 메시지는 기존 트리거 대상이 아니다.** 추후 브리지·복제·동시 쓰기를 추가하면 서로 다른 dedup 키여서 양쪽 FCM을 동시에 발송할 수 있다. 한 발송 주체 및 같은 eventId 계약을 먼저 확정해야 한다.

app.chat_sync도 단일 실행을 전제로 한다. 두 프로세스의 SQL exists 선조회가 모두 false이면 알림 행은 UNIQUE로 하나만 남더라도 양쪽이 푸시를 큐에 넣을 가능성이 있다. SQL 커밋 후 Firestore inboxSynced 업데이트/FCM 발송 경계에서 프로세스가 종료되면 푸시 누락 가능성이 있어 영속 전달 보장은 없다. 실제 중복 푸시 재현은 하지 않았다.

## 적용 상태

- DB: 서비스 설정 `RIDERLOG_V2_DATA_TEST`, 읽기 전용 app.migrate 결과 `No pending changes.`. 계획 검사 범위의 스키마 일치이며 전체 공유 DB 호환성·동시성 인수는 아니다. 백업·실제 적용 주체는 미확인.
- Firestore 기본 DB: FIRESTORE_NATIVE, asia-southeast2.
- 운영 Rules: releases/cloud.firestore가 가리키는 ruleset `6a1de722-8439-466f-b5b9-772b5b38234b`, updateTime 2026-10-12 06:23:38 UTC. 내용은 현재 chat/firestore.rules와 동일. 다른 업무 허용 규칙은 이 배포본에 없음. 기존 규칙 보존/다른 앱 영향은 이전 Rules가 없어 미검증.
- chatRoomAccess 복합 인덱스: shopId+updatedAt DESC, customerUid+updatedAt DESC, shopId+customerUid, kind+status+expiresAt의 4개 모두 COLLECTION/READY. 현재 계약의 인덱스와 일치한다.
- Scheduler: 자카르타 지역 jobs 목록 조회는 200이지만 빈 목록. 만료 함수의 소스는 15분 schedule이나 실제 동작 스케줄을 확인하지 못했다. 다른 지역 스케줄 여부도 미조회.
- systemd: nadree 타이머 목록 0개. 다른 cron/외부 실행 주체까지 부재를 증명하지 않는다. 동기화는 실행하지 않았다.

## 검증 상태 및 필요한 후속 결정

**완료:** 배포 8개 메타데이터/ZIP 소스 확보, 계약 비교, 알림 경로·중복 경계 검토, 읽기 전용 DB 계획/Rules/인덱스 확인, 현 커밋 전체 Python 격리 회귀. 결과 **213 passed, 9 skipped, 2 warnings in 40.17s**. 환경변수 없는 /tmp 작업 경로, 임시 SQLite만 사용했다. 실제 고객 결제·환불·푸시는 수행하지 않았다.

**배포본에 미구현/불일치:** 현재 세션 회수·만료 검사, App Check 기본 강제, 대표 전송 제한, 현재 예약/문의/읽음/알림/만료 구조, 종료 불가역 계약. 서버의 별도 잔여 개발(PG 불명확 만료·늦은/중복 결제 환불·실패 환불 재시도·위치 정정·센서/차량 이동·공유 서버 즉시 권한 회수)도 이 검토에서 구현하지 않았다.

**미검증:** 격리 MySQL 6개, Firestore 에뮬레이터 3개 및 Rules 재검증(Java 미설치), 실제 Auth custom token/App Check/FCM/IAM 경합, 실제 PayPal Sandbox, 전체 API↔배포 callable 통합, 실제 만료 스케줄과 동기화 실행. 로컬 단위 테스트는 현재 Python 구현만 검증하며 배포 Node.js를 통합 검증하지 않는다.

필수 상위 정책 문서 `/srv/rental-project-master.md`, `/srv/rental-api-review-decisions.md`는 이전 점검에서 없었다. 구현 계약 변경 전 자료 확보가 필요하다. 배포 소스는 확보했으므로 사용자에게 소스를 다시 요청할 필요는 없지만 원본 저장소/커밋, 이전 Rules, 실제 스케줄 위치/내역, 폐기 가능한 nadree_w02_test_* MySQL DB와 Sandbox 테스트 계정/대상은 추가 자료다. 비밀키·토큰은 문서/채팅으로 받지 않는다.

현재 Python 계약을 정본으로 유지할지 먼저 결정하고, 기존 default codebase 함수 교체/이전 및 setChatStatus·알림 트리거 처리 계획을 검토해야 한다. 동명 함수의 codebase/런타임 변경은 단순 신규 배포로 취급하지 않는다. 기존 삭제·덮어쓰기·DB 변경·Rules 변경·활성화/재시작은 구체적 범위에 대한 사용자 승인 후 수행한다. **전체 완료 또는 출시 가능으로 판정하지 않는다.**
