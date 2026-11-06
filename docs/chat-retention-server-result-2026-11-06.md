# 반납 완료 90일 채팅 정리 — 실제 서버 적용·검증 결과

검증일: **2026-11-06 UTC**. 적용 커밋: **167f25bec2a713b287f43d9af718510500ec6c65**.

**사용자 승인 범위의 callable 4개 업데이트, API·chat_sync 전환, 일일 자동삭제 타이머 활성화를 완료했다.** 최초 실제 `--apply`는 대상 **0건 / 삭제 0건 / 실패 0건**으로 종료했다. 실제 보관 만료 채팅 삭제와 실기기 동작까지 검증했다는 의미는 아니다.

기준: [90일 정책·실행서](chat-retention-90-days-2026-11-06.md), [채팅 계약](../chat/chat-contract.md). 앱 담당자 전달용은 [별도 문서](frontend-chat-retention-handoff-2026-11-06.md)를 사용한다.

## 1. 승인·Git·적용 범위

- 초기 main·로컬 변경 없음. `git pull --ff-only origin main`으로 `0b8e380` → **167f25b** 업데이트. 충돌·강제 초기화 없음.
- 사전 검증 후 사용자가 **“승인 — 명시된 범위 배포·자동삭제 활성화”**로 아래 실제 작업을 승인했다. Persistent 누락 실행과 향후 대상 채팅 자동삭제도 승인 범위다.
- **bail-472405 / asia-southeast2 / nadree-chat / python312**의 기존 callable 4개만 업데이트했다. 함수 삭제·신규 생성 없음.
- API 재시작 1회, 기존 chat_sync 정지·새 코드 재개, 신규 retention service/timer 설치·활성화 및 최초 실행을 완료했다.
- 새 스키마·env·패키지·Rules·인덱스 변경 없음. 기존 시드 재실행·실제 계정 로그인/삭제·시험 푸시·결제·환불 없음.
- stash `server-docs-before-pull-20261103`, OID `01e48b41d1c1b53d7d11b7f1c4fb487edbbba48d`를 보존했다.
- AGENTS.md·README·전달서를 확인했다. 참조된 `/srv/rental-project-master.md`, `/srv/rental-api-review-decisions.md`는 서버에 없어 수정하지 못했다.

## 2. 정책·소스 확인

| 항목 | 확인한 동작 |
| --- | --- |
| 대상 | 계약과 예약 모두 RETURNED, actual_end_time 존재·실행 UTC에서 90일 이전 또는 같은 시각 |
| 연결·재판정 | 예약 ID·고객·인수 지점 일치. 실제 삭제 직전 SQL 행 잠금 후 재판정 |
| 삭제 | 연결된 예약 채팅방·messages·reads·그 방의 chatPushEvents. 과거 문의에서 같은 방으로 전환된 메시지도 포함 |
| 제외 | 진행/연체·미반납·취소/거절/만료·예약 미연결 계약·일반 문의·다른 예약·전역 사용자/지점/FCM 정보 |
| SQL 보존 | 예약·계약·렌트·결제·차량/QR·이력·공통 알림함 데이터 변경 없음 |
| 재생성 차단 | 기존 bookingChatAccess의 내용 없는 retentionDeletingAt/retentionDeletedAt 유지. TTL 제거 없음 |
| 부분 실패 | 방을 먼저 숨기고 하위 문서·이벤트를 최대 200개 쓰기 배치로 삭제. 기존 roomId로 다음 실행에서 재개 |
| 중복 실행 | MySQL named lock. 개별 실패는 나머지 대상을 중단하지 않으며 failed가 있으면 종료 코드 1 |

## 3. 격리 자동 테스트 — 통과

서비스 .env·서비스 DB 주소·Google/Firebase/PayPal 인증 환경을 제거한 별도 소스로 실행했다. SQL 단위 검사는 일회용 SQLite·외부 대역을 사용했다. 실제 Firebase/서비스 DB로 삭제 시험을 하지 않았다.

| 검사·실행 시각 UTC | 기대 | 실제 |
| --- | --- | --- |
| 관련 검사, 03:31:08~03:31:13 | 신규 정책·예외 처리 통과 | **18 passed**, 실패/건너뜀 0 |
| 전체 회귀, 03:31:13~03:35:11 | 기존 기능과 신규 정책 회귀 없음 | **622 passed / 16 skipped / 0 failed / 0 errors**, 총 638개, 경고 14개 |
| 실제 SDK·Firestore 에뮬레이터, 03:33:41~03:34:04 | 실제 SDK 삭제/재생성 방지와 기존 동시성·권한·읽음 통과 | **5 passed / 0 skipped / 0 failed / 0 errors**, 경고 2개 |

관련 18개는 전체 622개에 포함된다. 전체 회귀의 Firestore 건너뜀 5개는 별도 에뮬레이터로 모두 통과해, 서로 다른 검사 기준 **627개 통과**다. 남은 건너뜀 **11개는 전용 MySQL 환경이 필요한 검사**이며 실제 서비스 DB를 시험 DB로 사용하지 않았다.

`demo-nadree-chat`·AnonymousCredentials·localhost 에뮬레이터를 사용했고 직접 띄운 Java 프로세스는 종료했다. 실제 Firebase 연결·새 다운로드·시험 푸시 없음. 90일 경계·실제 반납 기준·읽기 전용 계획·다른 채팅/SQL 이력 보존·삭제 표시·연결 불일치 거절·200건 분할·중간 실패/재개/후속 재시도를 검증했다.

## 4. 실제 Cloud Functions — 업데이트·원격 소스 확인 완료

실제 배포/조회 계정은 **qwer886901@gmail.com**으로 확인했다. list 및 함수 7개 get HTTP 200, 필요한 배포·빌드·actAs 권한 조회를 통과했다. IAM 추가/확대는 하지 않았다.

배포 **03:51:29~03:53:07 UTC**, CLI 종료 코드 **0**. 아래 네 함수 모두 GEN_2다.

| 업데이트 함수 | 배포 후 상태 | codebase / runtime / entryPoint | 원격 소스 |
| --- | --- | --- | --- |
| ensureBookingChat | ACTIVE | nadree-chat / python312 / ensureBookingChat | 3개 파일 일치 |
| sendChatMessage | ACTIVE | nadree-chat / python312 / sendChatMessage | 3개 파일 일치 |
| markChatRead | ACTIVE | nadree-chat / python312 / markChatRead | 3개 파일 일치 |
| getChatUnreadSummary | ACTIVE | nadree-chat / python312 / getChatUnreadSummary | 3개 파일 일치 |

각 함수의 배포된 GCS 소스에서 **chat_core.py·main.py·requirements.txt를 내려받아 로컬 해시와 12/12 일치**를 확인했다. 목록·런타임만으로 성공을 판단하지 않았다. 기존 App Check 관련 소스·설정도 유지됐으며 실제 App Check 호출 성공 검사는 별도다.

**ensureInquiryChat·expireInactiveInquiries·dispatchChatPushEvent**는 설정·updateTime이 전후 동일하고, dispatch의 기존 재시도 정책도 유지된다. 보존 함수의 Cloud Run 리비전 **3/3 Ready**를 확인했다. 최초 dispatch 원본 메타데이터 해시 차이는 eventFilters 배열 순서만 달라 발생했음을 재현·확인했고 최종 설정 차이는 없었다.

Firebase CLI 13.35.1의 표준 정리 단계가 보존 함수를 포함한 7개 함수의 Artifact Registry 빌드 패키지 DELETE 요청을 기록했다. **함수 리소스 삭제 요청은 없었다.** 해당 패키지 정리 요청의 HTTP 성공 여부는 수집되지 않았고, 후속 현재 이미지 조회는 404였다. 실행 함수 설정·리비전 Ready 확인과 빌드 아티팩트 보존 여부를 구분한다. Cloud Run은 배포 시 이미지를 가져와 보관하므로 레지스트리 이미지 삭제만으로 실행 리비전 삭제를 의미하지 않는다. [Google Cloud 공식 배포 문서](https://docs.cloud.google.com/run/docs/deploying). 추가 삭제·복구·재배포는 하지 않았다.

## 5. 실제 API·동기화·DB 확인 — 통과

| 검사 | 기대 | 실제 |
| --- | --- | --- |
| ec2-user app.migrate 읽기 전용 계획 | 미적용 변경 없음 | **No pending changes.**; 마이그레이션 적용 없음 |
| 적용 전 SQL-only 계획 | 삭제 대상 수 확인 | 03:34:58 UTC **eligibleRentals=0**, Firestore 접근 없는 계획 |
| 새 API | 새 코드·정상 실행, 구 프로세스 종료 | **04:08:33 UTC** 재시작, PID **2360838**, ec2-user, `/srv/nadree-api`, active/running. 구 PID 1622907 종료 |
| 로컬 live·ready·Swagger·OpenAPI | HTTP 200 | **4/4 200** |
| 공개 live·ready·Swagger·OpenAPI | HTTP 200 | **4/4 200**, `https://na-dree.com` |
| OpenAPI | 기존 API 경로 보존 | health 제외 **76개 경로** |
| 새 chat_sync | 구 프로세스 종료 후 기존 일정 재개 | 구 PID 2359956 종료·타이머 재개. 04:10:40 점검까지 새 실행 정상 완료 **3회**, 해당 구간 Traceback/서비스 실패 0 |
| API 오류 로그 | 시작·ASGI 예외 없음 | 04:08:33 이후 점검 구간 Traceback·ASGI·시작 오류 **0** |
| env | 비밀값·소유권·권한 보존 | 적용 전후 파일 해시 동일, ec2-user 소유·**0600**, 변경 없음 |
| 기존 작업 | 변경/중단 없이 유지 | chat-sync·receipts 타이머·crond 정상, 기존 결제 cron·chat-sync/receipts unit 파일 해시 동일 |

전환 중 chat_sync에 보낸 정상 종료 신호가 systemd에서 failed/signal 15로 표시돼 자동 검사가 한 번 멈췄다. 실제 프로세스 종료·MainPID=0을 확인하고 해당 상태만 정리한 후 체크포인트부터 재개했다. API 재시작·함수 배포·retention 적용을 중복 실행하지 않았으며 최종 미해결 서비스 실패는 없다.

백엔드 실제 Firebase 서비스 계정의 `datastore.entities.get/list/create/update/delete` 5개 권한을 testIamPermissions HTTP 200으로 확인했다. 데이터를 쓰거나 삭제해 권한을 시험하지 않았고 IAM 변경도 없다. FCM 프로젝트는 **bail-472405**이며 위치 조회 프로젝트는 사용하지 않았다.

## 6. 실제 자동삭제 일정·최초 실행 — 통과, 실제 삭제 0건

- 설치: `nadree-chat-retention.service` / `.timer`, 배포 템플릿과 일치.
- 실행 계정: **ec2-user**. 명령: `.venv/bin/python -m app.chat_retention --apply`.
- 타이머: **enabled / active / waiting**, **Persistent=yes**.
- 일정: 매일 **UTC 20:15 / 다음 날 발리 04:15 / 한국 05:15**.
- 최초 다음 자동 일정: **2026-11-06 20:15 UTC = 2026-11-07 04:15 발리 = 05:15 한국**.
- 활성화: **04:08:41 UTC**. 활성화 직후 자동 실행 이력이 없어 승인된 최초 실행을 별도로 1회 수행했다.
- 실제 최초 실행: **04:08:41~04:08:43 UTC**, Result=success, 종료 코드 **0**. oneshot 완료 후 inactive/dead는 정상이다.

```text
mode=apply
cutoffUtc=2026-08-08T04:08:43.085465
eligibleRentals=0
deleted=0
alreadyDeleted=0
noRoom=0
changed=0
failed=0
```

완료 후 04:08:45 UTC SQL-only 재계획도 **0건**이었다. **자동삭제 활성화와 최초 작업의 정상 종료는 확인했지만, 실제 서비스의 90일 경과 채팅방 삭제는 대상이 없어 미검증**이다. 실제 과거 고객 데이터를 만들어 시험하거나 강제로 반납 시각을 변경하지 않았다. 이후 조건에 맞는 대상은 일일 작업에서 실제 삭제된다.

## 7. 미검증·후속 작업·복구

| 구분 | 항목·이유 / 후속 작업 |
| --- | --- |
| 통과 | 승인된 4개 함수 배포·원격 소스, API/동기화 전환, 타이머 활성화·최초 작업, 헬스, 격리 회귀/에뮬레이터 |
| 실패 | **미해결 실패 없음**. 자동 검사 중단 2건은 메타데이터 순서 차이·정상 종료 신호를 각각 확인하고 해소 |
| 설정 대기 | **이번 배포에 필요한 추가 env·스키마·Rules·인덱스 설정 없음** |
| 미검증 | 전용 MySQL 검사 11개, 실제 후보가 있는 SQL-Firestore 삭제·잠금 경합/재개, 첫 정시 자동 실행 |
| 미검증 | 실제 신규 callable의 Auth/App Check 종단·고객/대표 로그인 왕복·일반 문의/진행 예약의 실사용 |
| 미검증 | 앱 목록·열린 방·과거 알림·오프라인 캐시 정리·실기기 푸시. 시험 푸시를 보내지 않음 |
| 확인 한계 | CLI 빌드 패키지 정리 요청의 실제 HTTP 결과 미수집. 보호 함수 실행 리비전은 Ready 확인 |

앱 담당자는 [전달 문서](frontend-chat-retention-handoff-2026-11-06.md)에 따라 목록 삭제·캐시·CHAT_NOT_FOUND 안내와 기존 권한 오류 구분을 확인한다. 공동 시험은 승인된 폐기용 데이터로 별도 진행하며 실제 고객 메시지는 시험에 사용하지 않는다.

중지가 필요하면 retention 타이머를 멈추고 기존 삭제 표시를 보존한다. 이미 삭제된 메시지는 타이머 중지나 코드 되돌리기로 복구되지 않는다. 삭제 표시를 모르는 구버전으로 단순 복귀하거나 채팅방을 재생성하지 않는다. 이번 실행에서는 삭제 대상이 없어 실제 삭제·복구 대상은 없었다.

접근 제한된 `build/test-runtime/chat-retention-2026-11-06/`에 소스 지문·테스트 XML/요약·Cloud 배포/원격 소스 결과·서버 전환 체크포인트·최종 점검 JSON을 보관했다. `.env` 원문·키·토큰·비밀번호·실제 UID·메시지 본문은 결과 문서에 기록하지 않았다.
