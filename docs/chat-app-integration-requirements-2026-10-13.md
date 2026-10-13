# 신규 나드리 채팅 고객 관리자 앱 연동 요구사항

기준: 2026-10-13 사용자 결정 및 [채팅 계약](../chat/chat-contract.md). 새 앱 연동용이며 구버전 호환·기존 채팅 데이터 이전은 제공하지 않는다. 앱 소스·실기기 인수 자료는 아직 제공되지 않았다. 이 요구사항은 앱 구현 완료를 뜻하지 않는다.

## 공통 Firebase 설정과 세션

FCM/Auth 프로젝트 bail-472405, Functions 리전 asia-southeast2, Firestore (default), API https://na-dree.com을 사용한다. 차량 위치 Firebase는 채팅 설정으로 사용하지 않는다. App Check 등록과 토큰 발급을 준비하고 운영 callable에는 유효한 App Check를 전달한다. 에뮬레이터는 demo-nadree-chat만 사용한다.

기존 업무 로그인 후 현재 FCM 토큰을 API에 등록하고 채팅 세션을 발급한다. 반환 firebaseCustomToken으로 signInWithCustomToken을 수행한다. 여러 화면에서 중복 세션을 발급하지 않으며 새 세션 발급은 이전 채팅 세션을 무효화한다. custom/ID/access/refresh/App Check 토큰은 로그·분석·문서에 남기지 않는다.

## 고객 앱

본문 없이 POST /api/v1/nadree/user/chat/session에 고객 Authorization Bearer와 현재 X-Refresh-Token을 전달한다. 응답은 firebaseCustomToken, firebaseUid, managerId=null, shops=[], region이다.

고객 UID는 서버 응답을 사용한다. 본인 방만 조회하고 shopId와 선택 productId로 문의한다. productId는 해당 지점 modelId다. bookingId는 BO 접두어가 없는 reservationId다. 첫 예약은 유효 문의와 같은 방으로 전환되며 두 번째 예약은 별도 방이다. BOOKING_CHAT_SYNC_PENDING이면 같은 bookingId로 재시도하고 예약을 다시 만들지 않는다.

## 관리자 앱

본문 없이 POST /nadreego/chat/session에 관리자 Bearer를 전달한다. 응답은 firebaseCustomToken, firebaseUid, managerId, shops[{shopId,spotCode}], region이다. 직접 소속 지점만 목록에 나타난다. 일반관리자는 열람·알림·개인 읽음, 대표관리자는 추가로 답변 가능하다. 서버 권한 검사가 최종 기준이며 상위 회사의 하위 지점 관리 권한을 채팅에 상속하지 않는다.

대표 교체·직원 제거·업무 로그아웃·다른 기기 로그인 후 이전 세션의 접근을 거절 처리한다. UI에서 전송을 숨기는 것만으로 보안을 대체하지 않는다. 관리자에게 고객을 임의 지정해 문의방 생성 또는 종료 방 재개 기능을 제공하지 않는다.

## Callable 요청과 응답

| 함수 | 요청 | 응답 data |
| --- | --- | --- |
| ensureInquiryChat | shopId, 선택 productId | roomId, bookingId:null |
| ensureBookingChat | bookingId | roomId, bookingId |
| sendChatMessage | roomId, messageId, text | messageId, sequence |
| markChatRead | roomId, messageId | position |
| getChatUnreadSummary | shopId | unreadMessages, unreadRooms |

messageId는 소문자 표준 UUID를 한 번 생성해 동일 본문 재시도에서 재사용한다. 텍스트는 원문 UTF-8 1~2000바이트이며 공백만 있는 본문은 보내지 않는다. 전송 성공은 발신자의 개인 읽음도 갱신한다. 읽음 위치는 누적 전체 sequence이고 감소하지 않는다.

setChatStatus/notifyBookingChatMessage를 앱 callable로 사용하지 않는다. expireInactiveInquiries는 서버 스케줄이며 앱이 직접 호출하지 않는다.

## Firestore 조회와 화면 상태

방은 chatRoomAccess/{roomId}, 메시지는 그 아래 messages/{messageId}, 본인 읽음은 reads/{firebaseUid}를 조회한다. 관리자 목록은 shopId=선택한 직접 지점, 고객 목록은 customerUid=본인 UID로 제한한다. updatedAt 내림차순, limit 50, startAfter로 페이지 처리한다. 메시지는 sequence 오름차순으로 페이지 처리한다. 클라이언트 직접 쓰기는 전부 금지하며 읽음도 callable만 사용한다.

status=read_only이면 양쪽 전송 UI를 비활성화한다. 문의는 마지막 새 메시지 또는 생성 후 168시간 무대화 만료이며 진입/읽음/중복 전송으로 기한이 늘지 않는다. 취소·거절·만료·반납 종료 후 재개 기능은 없다. 종료 후 새 문의는 새 roomId다.

채팅 개인 읽음과 /nadreego/notifications의 지점 공통 읽음은 별개다. 푸시는 CHAT_MESSAGE 안내와 eventId/shopId/roomId를 처리하고 같은 eventId 중복 표시를 방지한다. 메시지 본문·개인정보는 푸시에 기대하지 않는다. 알림함을 기준으로 누락된 푸시를 복구한다.

## 오류와 인수 자료

CHAT_SESSION_REQUIRED/HTTP 401은 업무 세션 상태에 맞춰 재인증한다. CHAT_ACCESS_DENIED/CUSTOMER_REQUIRED는 권한 오류로 처리한다. CHAT_READ_ONLY는 종료 상태를 표시하고 재개/반복 전송하지 않는다. MESSAGE_ID_CONFLICT는 같은 ID의 다른 본문/발신자 재사용 오류다. CHAT_SYNC_FAILED/503은 성공으로 표시하지 않고 업무 상태를 다시 조회한다. 세부 오류는 정본 계약을 따른다.

실제 인수에는 앱 소스/출시 커밋, Firebase 앱 등록과 App Check 준비 상태, 승인된 고객/대표/일반관리자·지점·예약·상품 식별자, 테스트 기기와 푸시 수신 확인이 필요하다. 토큰·키는 비공개 테스트 클라이언트/런타임에서 사용하고 채팅으로 전달하지 않는다. 앱 소스가 없으면 서버 API/callable 결과와 실기기 미검증 상태를 구분해서 보고한다.
