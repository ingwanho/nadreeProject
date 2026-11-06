# 반납 완료 후 90일 채팅 자동 삭제 — 정책·서버 적용

2026-11-06 사용자 요청 반영. **명시적 승인 후 callable 4개 배포·API/chat_sync 전환·일일 자동삭제 타이머 활성화를 04:08 UTC 완료했다.** 최초 실제 --apply는 대상 0·삭제 0·실패 0으로 종료했다. 실제 만료 방 삭제·앱 종단은 별도 미검증이며 [서버 결과](chat-retention-server-result-2026-11-06.md)를 따른다. 아래 명령은 적용 절차 참조이며 이미 완료된 배포/설치를 반복할 필요가 없다. 2026-10-18의 채팅 본문 자동 정리 제외 결정 중 아래 반납 완료 90일 범위만 이번 요청으로 변경한다.

## 1. 삭제 기준과 범위

기준 데이터는 공유 SQL DB의 MSP_RENTAL_CONTRACT와 연결된 MSP_RESERVATION이다.

- 계약과 예약 모두 RETURNED이며 actual_end_time이 존재하는 렌트만 대상이다.
- **실제 반납 완료 시각 actual_end_time부터 90일이 경과**한 건을 정리한다. DB 시각은 UTC이고 실행 시각에서 정확히 90일을 뺀 값 이하를 선택한다. 예정 반납일 planned_end_date/end_datetime은 삭제 기한으로 사용하지 않는다.
- 예약 ID·고객·인수 지점의 연결이 계약과 일치해야 한다. SQL 후보를 200건씩 읽고 실제 삭제 직전에 SQL 행을 잠가 다시 판정한다.
- 진행 중/연체·실제 반납 시각 누락·취소/거절/만료·예약 미연결 계약·일반 문의방은 이번 대상에서 제외한다. 지점/관리자가 탈퇴했어도 정상적으로 연결된 과거 반납 기록은 대상이 될 수 있다.
- 삭제 대상은 연결된 **예약 채팅방, messages, reads, 해당 방의 chatPushEvents**다. 과거 문의에서 같은 예약방으로 전환된 메시지도 함께 삭제한다. 다른 예약방·이후 새 문의방·전역 사용자/지점/FCM 정보는 유지한다.
- SQL의 렌트·예약·계약·결제·차량/QR·이력·기존 공통 알림함 기록은 변경하지 않는다. 알림함에는 메시지 본문을 저장하지 않는다.

하루 한 번 **발리 04:15 / 한국 05:15 / UTC 전날 20:15**에 실행한다. 90일이 경과한 뒤 처음 돌아오는 일일 배치에서 정리하므로 정확한 90일째 시각에 즉시 실행하는 방식은 아니다.

## 2. 재생성·부분 실패 방지

기존 chat_sync는 SQL 예약을 계속 동기화하므로 방만 삭제하면 다시 생성될 수 있다. 기존 서버 전용 bookingChatAccess에 고객/지점/예약 연결과 내용 없는 retentionDeletedAt 표시를 남긴다. 새 SQL 테이블·컬럼·Firestore 컬렉션은 추가하지 않는다. 삭제 표시는 TTL로 지우지 않는다.

삭제 시작 시 링크에 retentionDeletingAt을 기록하고 해당 예약의 동기화·재생성·callable 접근을 차단한다. 먼저 방 문서를 삭제해 목록과 메시지 접근에서 제외하고, 하위 messages/reads와 연결 알림 이벤트를 **200개 이하의 쓰기 배치**로 지운다. 방 문서 삭제가 하위 문서까지 자동 삭제하는 것으로 간주하지 않는다. 모든 정리가 끝난 뒤 retentionDeletedAt을 확정한다.

일부 메시지 삭제 후 프로세스가 중단돼도 링크의 기존 roomId로 남은 하위 문서와 이벤트를 다음 실행에서 계속 삭제한다. 이미 완료한 건은 다시 만들거나 새 문의방을 소비하지 않는다. 채팅 매핑·방의 예약/고객/지점 정보가 SQL과 다르면 삭제하지 않고 실패로 집계한다. 방이 처음부터 없으면 재생성 방지 표시만 기록한다.

중복 배치는 동일 SQL DB의 MySQL named lock으로 막는다. 한 렌트의 실패가 다른 렌트 정리를 중단하지 않으며 실패가 있으면 최종 종료 코드는 1이다. 데이터 내용·토큰·UID는 작업 로그에 출력하지 않는다.

## 3. 앱 영향

기존 callable 이름과 입력, REST API, Firestore 조회 경로, App Check 정책은 유지한다. 삭제 대상 예약의 ensureBookingChat은 기존 오류 **not-found / CHAT_NOT_FOUND**를 반환한다. 다른 고객이 조회하면 기존 권한 거절을 유지한다. 삭제된 예약 채팅을 BOOKING_CHAT_SYNC_PENDING처럼 반복 생성하지 않는다.

앱은 방 삭제 이벤트를 목록/화면에 반영하고, 과거 알림에서 진입했을 때 CHAT_NOT_FOUND이면 “보관 기간이 지난 채팅입니다” 등으로 안내한다. 기존 렌트 내역은 계속 표시한다. 이번 배치는 서버 보관 데이터 정리이며 기기 로컬 캐시는 앱의 삭제/동기화 처리에 따른다.

## 4. 실행 명령과 결과

기본 명령은 **SQL 대상 건수만 확인**하며 Firestore 읽기·삭제·삭제 표시 생성을 하지 않는다.

```bash
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.chat_retention'
```

실제 삭제 명령은 아래 배포 순서와 대상 확인 후 사용한다. 타이머도 같은 --apply 명령을 실행한다.

```bash
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.chat_retention --apply'
```

| 출력 | 의미 |
| --- | --- |
| mode=plan, cutoffUtc, eligibleRentals | SQL 기준 시각과 대상 렌트 수. 실제 채팅방 수/삭제 완료 수는 아님 |
| mode=apply, eligibleRentals | 이번 작업에서 처리 후보로 읽은 렌트 수 |
| deleted | 방과 연결 데이터 정리를 완료한 렌트 수 |
| alreadyDeleted | 이전 실행에서 정리를 완료한 건 |
| noRoom | 기존 방 없이 내용 없는 삭제 표시만 만든 건 |
| changed | 재검사 시 더 이상 삭제 대상이 아닌 건 |
| failed | 삭제 실패·연결 불일치. 다음 실행에서 재시도 |
| busy=true | 다른 배치가 같은 SQL DB의 작업 잠금을 보유하여 이번 실행 생략 |

기존 NADREE_FCM_* / NADREE_FCM_CHAT_ENABLED와 SQL DB 설정을 사용한다. 위치 조회용 Firebase 프로젝트는 사용하지 않는다. 새 env·패키지·스키마 마이그레이션·Rules·인덱스 변경은 없다.

## 5. 서버 Codex 적용 순서

이 순서가 끝나기 전에는 새 타이머를 활성화하거나 --apply를 실행하지 않는다. 코드 pull만으로 자동 배치가 등록되지는 않는다.

1. 서버 로컬 변경을 보존하고 commit/push된 코드를 git pull --ff-only origin main으로 반영한다. 새 타이머가 이미 설치돼 있다면 먼저 중지한다.
2. 격리 회귀와 demo-nadree-chat Firestore 검사를 실행한다. 서비스 DB나 실제 Firebase를 테스트 대상으로 사용하지 않는다.
3. **기존 FCM/Auth 프로젝트의 아래 네 callable을 새 chat_core.py가 포함된 소스로 업데이트**한다. 소스 codebase는 nadree-chat, 런타임 python312, 리전 asia-southeast2다. 실제 프로젝트 ID는 현재 NADREE_FCM_PROJECT_ID로 확인한다.

```bash
cd /srv/nadree-api/chat
npx firebase deploy --project 'FCM_PROJECT_ID' --only 'functions:nadree-chat:ensureBookingChat,functions:nadree-chat:sendChatMessage,functions:nadree-chat:markChatRead,functions:nadree-chat:getChatUnreadSummary'
```

위 FCM_PROJECT_ID 문자열은 확인한 실제 프로젝트 ID로 교체한다. ensureInquiryChat·expireInactiveInquiries·dispatchChatPushEvent·기존 Rules/인덱스·App Check 설정·다른 프로젝트는 변경하지 않는다. 함수 코드/배포 성공을 확인한 뒤 다음 단계로 간다.

4. 기존 API와 chat_sync가 모두 새 코드를 사용하도록 전환한다. 이전 버전 프로세스가 삭제 표시를 무시하고 방을 다시 만들지 않도록 기존 chat_sync 실행을 종료한 뒤 새 일정으로 다시 시작한다.

```bash
sudo systemctl stop nadree-chat-sync.timer
sudo systemctl stop nadree-chat-sync.service
sudo systemctl restart nadree-api
sudo systemctl start nadree-chat-sync.timer
```

5. 로컬/공개 health·Swagger와 기존 채팅 작업을 확인하고 **읽기 전용 기본 명령으로 실제 DB 대상 건수**를 확인한다. 대표/고객 로그인·일반 문의·진행 예약이 영향을 받지 않는지 승인된 계정으로 확인한다. 스키마 변경을 적용하거나 기존 시드를 재실행할 필요는 없다.
6. 확인된 대상에 90일 삭제 정책을 적용할 때 아래 전용 일일 타이머를 등록한다. 기존 30초 채팅 동기화/푸시 복구·15분 문의 만료·결제/인수 일정은 유지한다.

```bash
cd /srv/nadree-api
sudo install -m 644 deployment/nadree-chat-retention.service /etc/systemd/system/nadree-chat-retention.service
sudo install -m 644 deployment/nadree-chat-retention.timer /etc/systemd/system/nadree-chat-retention.timer
sudo systemctl daemon-reload
sudo systemctl enable --now nadree-chat-retention.timer
sudo systemctl list-timers nadree-chat-retention.timer
```

타이머는 Persistent=true이므로 누락된 실행이 있으면 활성화/부팅 후 실행될 수 있다. 최초 실행 결과는 `journalctl -u nadree-chat-retention.service`로 확인하고 삭제 건수·실패 건수·다음 일정·기존 작업 보존을 결과 MD에 기록한다. 실제 채팅 삭제와 에뮬레이터 검증을 구분한다.

운영 중 정리가 실패하면 실패 건은 다음 일일 실행에서 이어 처리한다. 정리 정책 적용을 멈추려면 타이머를 중지하고 삭제 표시를 보존한다. 이미 삭제된 메시지를 다시 만들거나 삭제 표시를 모르는 구버전으로 단순 복귀하지 않는다.

## 6. 검증 범위

추가 격리 검사 **18개 통과**. SQL 90일 경계·실제 반납/상태 조건·읽기 전용 계획·기존 SQL 이력 보존·다른 예약/문의 보존·재생성 차단·잘못된 고객 연결 거절·200건 쓰기 분할·중간 실패 후 재개·다음 실행 재시도를 검증했다. 삭제 도중 중단돼도 방은 목록/접근에서 빠지고 남은 하위 문서를 재시도로 삭제하는 것도 확인했다.

```text
# 일반 격리 전체 회귀
622 passed, 16 skipped, 14 warnings

# 별도 demo-nadree-chat Firestore 에뮬레이터
5 passed, 2 warnings
```

전체 회귀의 건너뜀 16개 중 Firestore 5개는 localhost의 별도 에뮬레이터에서 따로 실행해 모두 통과했다. 신규 실제 SDK 삭제·재생성 방지 검사 1개와 기존 동시성/권한/읽음 검사 4개다. AnonymousCredentials·demo 프로젝트 제한을 사용했고 종료 후 직접 띄운 에뮬레이터도 중지했다. 기존 경고는 테스트 실패와 구분한다.

전용 MySQL 환경 검사 11개는 미실행이다. Functions 4개 배포·원격 소스 확인·systemd 일정 적용과 최초 대상 0건 실행은 완료했다. 실제 후보가 있는 공유 MySQL 잠금/SQL-Firestore 삭제·부분 실패/재개·첫 정시 자동 실행·실기기 처리는 별도 미검증이다. 로컬 에뮬레이터 성공을 실제 서비스 데이터 삭제 성공으로 표시하지 않는다.
