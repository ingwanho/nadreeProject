# 나드리 Firebase·채팅 정책

최종 수정일: 2026-10-08

## Firebase 프로젝트 분리

- 고객 Firebase Authentication, FCM 발송, 채팅 Firestore/Callable Functions는 현재 FCM용 Firebase 프로젝트 하나를 함께 사용합니다.
- 백엔드 환경변수는 기존 `NADREE_FCM_*` 서비스 계정 블록을 사용합니다. 채팅 전용 프로젝트나 `NADREE_CHAT_*` 블록은 추가하지 않습니다.
- 차량 위치 탐색만 기존 위치 Firebase 설정(`NADREE_FIRESTORE_PROJECT`, `NADREE_LOCATION_FIREBASE_*`)을 사용합니다.
- 채팅과 차량 위치 데이터·권한은 서로 섞지 않습니다.

## 관리자 채팅 권한

| 역할 | 채팅 목록·본문 조회 | 새 채팅 알림 | 답변 전송 |
|---|---:|---:|---:|
| 대표관리자(`rental_primary_admin`) | 가능 | 가능 | 가능 |
| 일반관리자(`rental_manager`) | 가능 | 가능 | 불가 |

권한 범위는 현재 관리자와 동일하게 지점 직접 scope를 기준으로 합니다. 하위 지점 전체를 자동으로 열람하지 않으며, 해당 지점에 직접 연결된 활성 관리자만 알림 수신 대상입니다.

## 프론트가 사용할 Firebase Callable 계약

관리자 앱에서 사용할 이름은 기존 인수 요청과 동일하게 유지합니다.

| Callable | 용도 | 권한 |
|---|---|---|
| `ensureBookingChat` | 예약별 채팅방 생성·조회 | 해당 지점 대표/일반관리자, 고객 |
| `ensureInquiryChat` | 문의별 채팅방 생성·조회 | 해당 지점 대표/일반관리자, 고객 |
| `sendChatMessage` | 메시지 등록 및 상대방 알림 | 고객, 대표관리자만 |
| `markChatRead` | 읽음 시각 기록 | 해당 채팅방 참여자 |
| `getChatUnreadSummary` | 미읽음 합계·채팅 알림 뱃지 | 해당 지점 대표/일반관리자, 고객 |

`sendChatMessage`는 일반관리자 호출을 Firebase Rules와 Callable 내부에서 모두 거절해야 합니다. 일반관리자는 채팅방을 열어 내용을 확인하고 알림을 받을 수 있지만 답변을 등록할 수 없습니다.

## 현재 백엔드 저장소의 범위

이 저장소에는 Firebase Functions 소스와 Firestore Rules가 없으므로 Callable/Rules를 이 FastAPI 코드만으로 배포할 수 없습니다. 이번 백엔드에는 공유 FCM 프로젝트 기준과 관리자 FCM 수신자 정책을 반영했고, 실제 채팅 기능을 완료하려면 Firebase Functions 프로젝트에 위 Callable과 Rules를 추가한 뒤 동일한 `NADREE_FCM_PROJECT_ID`에 배포해야 합니다.

추가로 확정할 값은 Firebase Functions 리전입니다. 기존 Firebase 프로젝트의 현재 리전을 그대로 사용할지, 별도로 지정할지 Firebase 배포 담당자가 정하면 됩니다. 리전을 바꾸면 Callable 호출 URL과 배포 설정이 달라질 수 있습니다.
