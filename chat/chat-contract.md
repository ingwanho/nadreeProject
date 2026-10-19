# 나드리 신규 채팅 연동 계약

2026-10-18 정정: 개인정보 전용 테이블·자동 정리 타이머·채팅 본문 삭제 및 privacyStatus 추가는 사용자 결정으로 제외한다. 기존 탈퇴 시 계정 삭제·채팅 세션 회수를 검증하며 Functions/Rules 경로는 유지한다. scripts/verify_app_check.py 디버그 검증 도구는 유지하고 실제 검증은 미실행이다. [최신 인수 문서](../docs/nadree-full-change-handoff.md) 참조.



작성: 2026-10-12. 사용자 결정 반영: 2026-10-13. **채팅은 백지에서 신규 구축하며 이 계약과 현재 Python 구현을 정본으로 사용한다. 기존 데이터 이전·구버전 앱 호환·Node.js 호환 코드는 만들지 않는다.** 조회된 기존 Node.js 채팅 함수 7개는 별도 승인 후 정리한다. **소스 작성·격리 검증과 실제 배포·앱 인수 완료는 별개다.**

함수별 정리 대상·적용 순서·보존 범위는 [신규 구축 실행안](../docs/chat-new-build-deployment-plan-2026-10-13.md), 고객·관리자 앱 요구사항은 [앱 연동 안내](../docs/chat-app-integration-requirements-2026-10-13.md)를 따른다. 기존 FCM·Authentication 사용자·차량 위치 기능과 채팅 외 데이터·규칙은 보존한다. 신규 구축 결정은 기존 함수나 데이터의 무승인 삭제를 허용하지 않는다.

2026-10-13 적용 상태: 사용자 승인 후 Node.js 채팅 7개 정리, Python 6개·Rules/인덱스·만료 스케줄·API/동기화 적용을 완료했다. 실제 계정·유효 App Check·실기기 앱 인수는 미검증이며 [실제 적용 결과](../docs/chat-new-build-deployment-result-2026-10-13.md)를 따른다.

## 프로젝트·리전

- 기존 고객 Authentication·FCM 프로젝트를 사용한다. 실제 ID는 운영 `NADREE_FCM_PROJECT_ID`에서 확인하여 앱에 전달한다. 서비스 계정 비밀키는 앱/문서에 넣지 않는다.
- Functions 리전은 사용자 지정 **인도네시아 자카르타 `asia-southeast2`**. 앱 Functions 인스턴스에도 같은 값을 지정한다.
- 위치 추적 `NADREE_FIRESTORE_PROJECT` / `NADREE_LOCATION_FIREBASE_*`는 사용하지 않는다.
- Firestore `(default)` 데이터베이스를 사용한다. 함수 리전 설정은 이미 존재하는 Firestore의 위치를 변경하지 않는다.
- App Check는 기본 강제다. 출시 앱의 App Check 등록을 완료하고 개발은 에뮬레이터를 사용한다.

## 1. 채팅 로그인

관리자 앱 설정: `CHAT_SESSION_PATH=/nadreego/chat/session`.

```http
POST /nadreego/chat/session
Authorization: Bearer <관리자 access token>
```

본문 없음. 현재 업무 세션·역할·직접 manage 소속·활성 지점·유효 계약을 검증한다. Firebase 사용자와 membership 동기화 성공 후 custom token을 반환한다. 상위 조직의 매장 관리 권한을 하위지점 채팅에 상속하지 않는다.

```json
{
  "firebaseCustomToken": "<Firebase 로그인 교환용 토큰>",
  "firebaseUid": "nadree-admin-<관리자 ID SHA256>",
  "managerId": "<영구 관리자 ID>",
  "shops": [{"shopId": "<spotMasterId>", "spotCode": "<unit_code>"}],
  "region": "asia-southeast2"
}
```

Firebase SDK `signInWithCustomToken`으로 로그인한 후 callable/Firestore를 사용한다. UID·지점·역할을 요청 본문으로 보내지 않으며 토큰을 로그·분석 이벤트에 남기지 않는다.

고객 앱은 `POST /api/v1/nadree/user/chat/session`을 사용한다. 본문 없이 고객 access token과 `X-Refresh-Token`에 **현재 고객 refresh token**을 함께 보낸다. 응답 형식은 같고 firebaseUid는 기존 고객 UID, managerId=null, shops=[]다. 반환 custom token으로 로그인한다. 현재 refresh 검증으로 이전 기기의 access token이 새 채팅 세션을 발급받는 것을 방지한다.

새 채팅 세션 발급 시 이전 채팅 세션은 무효다. 앱의 여러 화면에서 중복 발급하지 말고 로그인/재연결 담당 한 곳에서 수행한다. FCM 토큰을 업무 API에 저장한 **다음** 채팅 세션을 발급한다. FCM 변경·대표 교체 후에도 세션을 다시 발급한다.

| HTTP | 의미 |
| --- | --- |
| 401 | 업무 세션 만료/폐기, 고객 refresh 불일치 |
| 403 | 업무 역할·소속 거절, CHAT_MEMBERSHIP_REQUIRED, CHAT_USER_DISABLED |
| 429 | 세션 발급 요청 제한 |
| 503 | CHAT_NOT_CONFIGURED 또는 CHAT_SYNC_FAILED, 성공으로 처리하지 말고 재시도 |

## 2. Callable

Firebase SDK의 인증된 callable 호출을 사용한다. 표의 반환값은 SDK 응답의 data다.

| 이름 | 입력 | 반환 |
| --- | --- | --- |
| ensureInquiryChat | shopId, 선택 productId | roomId, bookingId:null |
| ensureBookingChat | bookingId | roomId, bookingId |
| sendChatMessage | roomId, messageId, text | messageId, sequence |
| markChatRead | roomId, messageId | position |
| getChatUnreadSummary | shopId | unreadMessages, unreadRooms |

- 문의 생성은 고객이 수행한다. 직원은 직접 소속 지점의 문의 목록을 조회한다. 관리자가 임의의 고객 UID를 입력해 문의방을 만드는 API는 없다.
- bookingId는 reservationId 원문이다. BO 접두어가 붙은 bookedNo가 아니다. productId는 해당 지점에서 대여 가능한 모델의 modelId다.
- 고객+지점의 열린 문의 하나를 재사용한다. 다른 상품 문의는 같은 방의 최근 productId/displayName만 갱신한다.
- 첫 예약 요청 동기화 시 유효한 문의를 예약방으로 전환하고 roomId·메시지·읽음 위치를 유지한다. 복수 예약은 별도 방이다. 재시도로 다른 문의를 추가 소비하지 않는다.
- 메시지는 UTF-8 1~2000바이트의 텍스트만 허용하고 공백만 있는 본문은 거절한다. messageId는 소문자 표준 UUID 문자열이다. 앱에서 전송 전에 한 번 생성하고 재시도에서도 동일 ID·본문을 보낸다.
- 같은 ID·본문 재시도는 기존 sequence를 반환한다. 다른 본문/발신자로 재사용하면 MESSAGE_ID_CONFLICT다. 전송 성공 시 발신자의 읽음 위치도 새 sequence가 된다.
- 일반관리자는 목록·내용·알림을 볼 수 있지만 답변할 수 없다. 고객 본인과 직접 소속 대표만 전송할 수 있다.
- 읽음 위치는 사용자별 누적 sequence이며 뒤로 이동하지 않는다. 알림함의 지점 공통 읽음과 별개다.
- 문의는 마지막 새 메시지 저장 후 168시간 무대화 시 read_only다. 메시지가 없으면 생성 시각 기준이다. 진입·읽음·중복 전송은 기한을 갱신하지 않는다. 예약방에는 무대화 만료가 없다.
- 취소·거절·만료·반납은 read_only이며 재개 API는 없다. 종료 후 새 문의는 새 방을 만들고 다른 진행 예약방은 닫지 않는다.

주요 callable 오류: unauthenticated/CHAT_SESSION_REQUIRED, permission-denied/CHAT_ACCESS_DENIED 또는 CUSTOMER_REQUIRED, not-found/CHAT_SHOP_NOT_FOUND·CHAT_PRODUCT_NOT_FOUND·CHAT_NOT_FOUND·MESSAGE_NOT_FOUND, failed-precondition/BOOKING_CHAT_SYNC_PENDING·CHAT_READ_ONLY, already-exists/MESSAGE_ID_CONFLICT, invalid-argument/INVALID_MESSAGE·INVALID_IDENTIFIER·INVALID_INPUT.

BOOKING_CHAT_SYNC_PENDING이면 예약을 다시 만들지 말고 같은 bookingId로 잠시 후 재시도한다.

## 3. Firestore 읽기 계약

| 경로 | 용도/접근 |
| --- | --- |
| chatUsers/{firebaseUid} | 활성/업무 세션 연결, 본인 get |
| chatShops/{shopId}/members/{firebaseUid} | active/canReply, 본인 get |
| chatShops/{shopId}/products/{modelId} | active/displayName, 활성 상품 조회 |
| chatRoomAccess/{roomId} | 방 목록/상태 |
| chatRoomAccess/{roomId}/messages/{messageId} | senderUid/text/sequence/createdAt |
| chatRoomAccess/{roomId}/reads/{firebaseUid} | 본인 position |
| bookingChatAccess/{SHA256(bookingId)} | 서버 전용 예약 매핑 |
| chatInquiryKeys/{SHA256(uid+개행+shopId)} | 서버 전용 문의 중복 방지 |
| chatPushTokens, chatPushTokenOwners, chatPushEvents | 서버 전용 토큰/최근 채팅 세션 토큰 소유권/알림 중복 방지 이벤트 |

방 필드: customerUid, shopId, bookingId(null 가능), kind(inquiry/booking), status(open/read_only), blocked, createdAt, updatedAt, lastMessageAt(null 가능), expiresAt(예약방 null), lastSequence, productId/productDisplayName(null 가능). 시각은 Firestore Timestamp다.

관리자 목록은 `where(shopId == 선택한 직접 지점)`, 고객 목록은 `where(customerUid == 본인 UID)`로 제한한다. `orderBy(updatedAt, descending)`·`limit(50)`·`startAfter(lastSnapshot)`으로 페이지 처리한다. 지점 하나씩 조회한다. 전역 목록은 거절된다. 메시지는 해당 방의 messages를 sequence 오름차순·limit/startAfter로 조회한다.

대표를 포함한 모든 클라이언트의 직접 쓰기는 금지한다. 읽음도 callable로만 변경한다. 서버 Admin SDK에는 Rules가 적용되지 않으므로 callable 내부에서도 접근 권한을 검증한다. [Firebase 보안 쿼리 안내](https://firebase.google.com/docs/firestore/security/rules-query)

## 4. 업무 동기화·알림

- 예약 API는 SQL 커밋 후 즉시 동기화를 시도한다. 실패해도 예약 성공은 유지하며 `python -m app.chat_sync`가 SQL 최신 상태를 다시 읽어 복구한다.
- 종료는 SQL 커밋 전에 Firestore 쓰기 차단 표식을 저장한다. Firebase 장애로 차단 실패 시 503이며 해당 업무 변경은 커밋하지 않는다. SQL 롤백 후 일시 차단은 재동기화로 해제되지만 이미 확정된 read_only 방은 다시 열지 않는다.
- 이 서버의 로그아웃·다른 기기 로그인·탈퇴·대표 교체·직원 제거는 먼저 채팅 세션을 무효화한다. Firebase ID Token이 아직 만료되지 않아도 Rules/callable에서 차단한다.
- **공유 DB를 다른 서버나 SQL로 직접 수정하면 즉시 회수를 보장하지 않는다.** 해당 변경 주체에도 채팅 무효화를 연결해야 한다. 현재 재동기화 작업은 발견 후 차단하므로 주기만큼 지연될 수 있다.
- 기존 알림함에 eventType=CHAT_MESSAGE, targetType=CHAT, targetId=roomId로 저장한다. 목록·지점 공통 읽음은 기존 API를 사용한다.
- 푸시는 업무 서버 한 곳에서만 발송하며 Functions는 중복 방지 이벤트만 저장한다. 개인정보·메시지 본문·여권을 푸시에 넣지 않는다. 앱은 eventId로 중복 표시를 방지한다.
- 기존 best-effort FCM 발송기를 사용한다. 알림함 이벤트는 재시도 시 중복 저장하지 않지만 **프로세스 종료 시 푸시 영속 재전송/전달 보장은 없다**. 앱은 알림함을 기준으로 복구한다.
- 기존 데이터·구버전 앱의 이전/호환 없이 신규로 시작한다. 적용 직전 동명 컬렉션의 충돌을 읽기 전용 확인한다. 충돌 문서가 발견되면 이전 코드를 추가하지 않고 대상과 처리 범위를 보고한다. 함수 정리 승인만으로 기존 문서를 일괄 삭제하지 않는다.

## 5. 배포 담당자 작업

아래는 승인된 배포 시 수행하는 절차다. 코드 작성 중 운영 Firebase/DB에는 실행하지 않았다.

1. 기존 FCM 프로젝트 ID·Firestore 기본 DB·서비스 활성화·배포 권한·과금 설정 확인. 위치 프로젝트를 선택하지 않는다.
2. 기존 Firestore Rules를 내보내 비교하고 제공된 채팅 전용 Rules와 병합한다. **기존 전체 허용 catch-all이 채팅에도 적용되면 deny 규칙으로 막을 수 없으므로 기존 허용 범위를 좁혀야 한다.**
3. chat/functions에 Python 3.12 `venv`를 만들고 requirements.txt를 설치한다. CLI와 같은 환경에서 소스 분석을 확인한다.
4. chat 폴더에서 프로젝트를 명시하여 배포한다.

```sh
firebase deploy --project YOUR_FCM_PROJECT_ID --only functions:nadree-chat,firestore:rules,firestore:indexes
```

5. 자카르타 리전에 다섯 callable과 expireInactiveInquiries가 배포되었는지 확인한다. 만료 스케줄은 15분 간격이다. 앱 App Check를 등록한다.
6. 백엔드 의존성/이전 DB 마이그레이션 적용 후 `NADREE_FCM_CHAT_ENABLED=true`로 설정하고 API 재시작. 기존 NADREE_FCM_* 계정에 Firestore 읽기/쓰기·Firebase Auth 사용자/토큰 발급 권한이 필요하다. 별도 위치 계정이나 새 프로젝트 자격증명은 필요 없다.
7. 백엔드 폴더에서 아래 동기화를 실행한다. 업무 데이터의 Firestore 복제 및 알림함 쓰기가 발생한다.

```sh
.venv/bin/python -m app.chat_sync
```

8. 매분 단일 cron/systemd 실행 주체로 등록하고 실패 로그·실행시간을 감시한다. 현재는 예약/카탈로그 전량 재확인 방식이다. 한 주기보다 오래 걸리는 규모에서는 중복 실행하지 말고 증분 처리로 보완한다.
9. 프론트에 실제 프로젝트 ID, 자카르타 리전, 이 문서, 배포된 OpenAPI를 전달한다. 컬렉션/문서는 콘솔에서 미리 만들 필요 없이 최초 서버 쓰기에서 생성된다.

채팅을 중단할 때는 환경변수만 false로 바꾸지 않는다. 먼저 채팅 접근 Rules/Functions를 차단하고 활성 chatUsers를 무효화한 뒤 동기화·API 연결을 끈다. 이미 발급된 Firebase 세션이 환경변수 변경만으로 자동 폐기되지는 않는다.

## 6. 검증

2026-10-12 확인: 전체 Python 213개 통과/9개 건너뜀, Rules 에뮬레이터 4개 통과, Firestore 트랜잭션 에뮬레이터 3개 통과. 운영 Firebase/DB에는 쓰지 않았다. Python 테스트의 건너뜀 중 Firestore 3개는 위 별도 실행 결과로 확인했고 MySQL 6개는 아직 미실행이다. 마지막 채팅 세션 만료 보완 후 해당 테스트 11개도 다시 통과했다.

로컬 Python 단위 테스트와 demo Firestore Rules 테스트를 제공한다. chat 폴더에서 `npm ci`, `npm test`로 Rules를 검증하며 `npm run test:transactions`는 동시 문의 생성·메시지 재시도·예약 전환·종료를 실제 Firestore 에뮬레이터 트랜잭션으로 검증한다. demo-nadree-chat 외의 프로젝트에는 이 테스트를 실행하지 않는다. 테스트 도구 의존성은 앱/함수 운영 배포 대상이 아니다.

운영 인수는 별도: 실제 MySQL 잠금과 Firebase 간 경합, custom token 교환, App Check, 실제 FCM, IAM, 재동기화 실패 복구, 공유 서버 소속 변경 즉시 회수 연동. 기기에 이미 내려받은 오프라인 내용은 원격 삭제를 보장하지 않으므로 앱 로그아웃 시 로컬 채팅 캐시를 정리한다.

공식 참고: [Callable](https://firebase.google.com/docs/functions/callable), [스케줄 함수](https://firebase.google.com/docs/functions/schedule-functions), [리전](https://firebase.google.com/docs/functions/locations).
