# 채팅 메시지별 즉시 호출 — 실제 적용·검증 결과

검증일: 2026-10-27 UTC. 기준 Git HEAD는 `3129beb5d0577c70e2ede52c2f033e83ad87d532`이며 이번 변경은 작업 트리의 미커밋 수정으로 적용했다. 배포 소스를 내려받아 현재 파일과 직접 대조했다. 사용자에게 승인받은 신규 함수 1개·서버 인증 설정 3개·API 재시작 1회·무발송 진단 이벤트 1개 범위로 수행했다.

## 적용 완료

| 항목 | 실제 결과 |
| --- | --- |
| Firebase | `bail-472405` / `asia-southeast2` / Firestore `(default)` |
| 신규 함수 | `dispatchChatPushEvent`, `nadree-chat`, Python 3.12, `ACTIVE` |
| 트리거 | `google.cloud.firestore.document.v1.created`, `chatPushEvents/{eventId}` 생성만 감지 |
| 실행 설정 | CPU 1, 동시 실행 4, 최대 인스턴스 2, 제한 시간 30초 |
| Functions 재시도 | 배포 후 신규 함수의 `eventTrigger.retryPolicy=RETRY_POLICY_RETRY`를 조회해 확인 |
| 내부 API | `POST /internal/chat/push-events`. Google OIDC 서명·발급자·만료·audience·서비스 계정 이메일/고유 subject 검증. 공개 Swagger에는 표시하지 않음 |
| 서버 설정 | `NADREE_CHAT_PUSH_AUDIENCE`, `NADREE_CHAT_PUSH_INVOKER_EMAIL`, `NADREE_CHAT_PUSH_INVOKER_SUBJECT`만 추가. 비밀값·토큰은 기록하지 않음 |
| API 서비스 | `nadree-api.service` 1회 재시작. 기존 NADREE 설정값과 결제 복구 설정 보존 |
| 중복 방지 | HTTP와 주기 작업이 같은 이벤트별 MySQL named lock을 사용하고 잠금 후 원본을 재조회 |
| 복구 | 기존 매분 00초·30초 타이머 유지. 일부 성공은 제외하고 같은 수신 세션·토큰에 한해 최초 발송 포함 최대 5회, 생성 후 1시간 이내 전송 시도 |

새 메시지마다 즉시 발송을 시도한다. 일반관리자는 기존대로 조회·수신만 가능하며 대표만 답변한다. 로그아웃·만료·토큰 소유권·계약·역할·지점 권한이 바뀌면 전송을 중단한다. 읽음·방 상태·전송 상태 수정은 트리거를 다시 발생시키지 않는다. 앱의 callable·Firebase Auth·App Check와 푸시 data 필드 계약은 유지했다.

기존 `ensureBookingChat`, `ensureInquiryChat`, `sendChatMessage`, `markChatRead`, `getChatUnreadSummary`, `expireInactiveInquiries` 6개의 배포 소스 정보·설정·updateTime이 전후 동일하다. 기존 함수 삭제·덮어쓰기, Rules·인덱스·만료 스케줄 배포, SQL 스키마 변경, 계정 생성/삭제, 실제 결제·환불·고객 메시지·테스트 FCM 발송은 수행하지 않았다.

## 통과한 검사

| 검사 | 실제 결과 |
| --- | --- |
| 전체 격리 자동 회귀 | **508 passed, 12 skipped**, 실패/오류 0. 실제 서비스 DB·외부 자격증명을 제거하고 SQLite·가짜 Firestore/FCM으로 수행 |
| 신규 보안·경합 | 허용되지 않은 Google 호출자·누락 토큰·토큰 검증 실패·설정 누락 차단, API/복구 작업 동시 실행·재전송·상태 저장 실패·역할/계약 변경을 격리 검증 |
| 함수 소스 분석 | 기존 6개와 신규 1개를 정상 분석. CLI 배포 선택기가 신규 함수 1개만 선택함을 확인 |
| 실제 배포 소스 | 내려받은 `main.py`, `chat_core.py`, `chat_push_dispatch.py`가 서버 파일과 모두 일치 |
| 실제 인증 거절 | 신규 함수 무인증 호출 403, 백엔드 내부 API 무인증 호출 401 |
| 실제 연결 | 진단 이벤트 생성 `06:36:28.381128 UTC` → 인증된 백엔드 HTTP 200 `06:36:30.577301 UTC` → 함수 완료 로그 `06:36:30.624188 UTC`. 이벤트→완료 로그 약 **2.24초** |
| 무발송 확인 | 생성한 서버 전용 진단 이벤트 1개, 테스트 메시지 0·SQL 알림 0·FCM 0·계정 변경 0. 진단 이벤트의 내용도 그대로 유지 |
| 적용 후 API | 로컬 live/ready·공개 live·Swagger HTTP 200. 기존 고객 프로필·관리자 채팅 세션의 무인증 요청은 401 유지 |
| 적용 후 복구 | 최근 시작 간격 약 29.99~30.01초, 작업 오류·지연 처리 오류·traceback 0 |

진단 이벤트는 처음부터 `inboxSynced=true`, `pushPending=false`, `diagnostic=true`로 생성했으므로 실제 사용자 메시지·푸시 건수에 합산하지 않는다. 기존 메시지나 전송 상태를 초기화하지 않았다. 약 2.24초는 이 진단 한 건의 서버 연결 시간이며 FCM 전달·실기기 표시 시간 보장이 아니다.

## 해결된 적용 중 문제

- 첫 배포 사전검사에서 동시 실행 4개에 필요한 CPU 설정이 없어 중단됐다. 신규 함수에만 CPU 1을 명시하고 재분석·배포했다. 첫 시도는 소스 업로드·함수 생성 전 단계였으며 기존 6개 함수에는 영향이 없었다.
- 진단 결과 조회 중 Cloud 로그 API가 429를 반환했다. 같은 이벤트만 조회 간격을 늘려 재확인했고 최종 HTTP 200과 진단 완료 로그를 확인했다. 추가 진단 이벤트는 생성하지 않았다.

## 미검증·후속 확인

- 격리 MySQL 환경이 없는 8개와 Firestore 에뮬레이터 동시성 검사 4개는 미실행이다. 실제 서버 연결 검증으로 이 12개를 통과 처리하지 않았다.
- 실제 앱 화면·App Check 실기기·실기기 푸시 수신/표시, 실제 사용자 메시지에 대한 FCM 전달과 네트워크 장애 주입은 이번 무발송 검증에 포함하지 않았다. 인증·App Check 검사를 해제하지 않았다.
- 앱은 기존 경로로 메시지를 보내며 별도 내부 API를 호출하지 않는다. 같은 eventId 중복 표시 방지와 Firestore sequence 정렬·복귀 시 재조회는 [앱 전달 문서](chat-session-fcm-app-handoff-2026-10-22.md)를 따른다.

## 운영·복구

Python Functions SDK 0.6은 Firestore retry 옵션을 제공하지 않는다. 이후 신규 함수를 재배포할 때도 [재시도 설정 도구](../deployment/configure_chat_push_trigger.py)를 승인된 기존 Firebase CLI 계정으로 실행해 정책을 확인한다. 도구는 기본 읽기 전용이며 `--apply`를 지정해야 해당 함수의 재시도 정책만 변경한다.

즉시 호출 중지가 필요하면 신규 함수의 `CHAT_PUSH_FORWARD_ENABLED=false`를 설정하고 기존 30초 복구 작업을 유지한다. 기존 함수·데이터를 삭제하거나 전송 상태를 초기화하지 않는다. 접근 제한된 코드·설정 백업과 실제 검사 JSON은 서버 `build/test-runtime` 하위에 보관했다. 함수/정책 변경은 승인된 운영 절차로 수행한다.
