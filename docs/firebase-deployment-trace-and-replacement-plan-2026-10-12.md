# Firebase 배포 추적 및 채팅 전환 검토

확인일: 2026-10-12 UTC. 수행: Codex. 서버 커밋 `ad02598`. 읽기 전용 검토이며 함수 호출·배포·삭제·덮어쓰기·IAM 변경·DB 변경·재시작은 수행하지 않았다. 기존 구현은 실제 배포 ZIP의 TypeScript와 실행 lib JS까지 확보해 확인했다. 앱 사용 여부는 아직 확정하지 못했다.

## 1. 403 정확한 발생 경로

앞선 실패 명령은 다음이었다. Firebase CLI의 functions:list 실패가 아니다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && PYTHONPATH=/srv/nadree-api .venv/bin/python /tmp/nadree_firebase_readonly_audit.py'
```

스크립트는 Settings의 기존 FCM 자격증명으로 AuthorizedSession을 만들고 아래 HTTP GET을 수행했다.

```text
https://cloudfunctions.googleapis.com/v2/projects/bail-472405/locations/-/functions
https://cloudfunctions.googleapis.com/v1/projects/bail-472405/locations/-/functions
```

프로젝트 `bail-472405`, `-`는 전체 리전 조회다. 호출 주체는 `firebase-adminsdk-fbsvc@bail-472405.iam.gserviceaccount.com`이며 토큰/키를 출력하지 않았다. 이번 재현 명령은 같은 계정·인증 경로의 `/tmp/nadree_functions_permission_probe.py`다.

| 확인 | 실제 결과 |
| --- | --- |
| v1 목록 | HTTP 403 PERMISSION_DENIED, Permission 'cloudfunctions.functions.list' denied on resource 'projects/bail-472405/locations/-' (or resource may not exist). |
| v2 목록 | HTTP 403 PERMISSION_DENIED, Permission 'cloudfunctions.functions.list' denied on 'projects/bail-472405/locations/-/functions' |
| 프로젝트 testIamPermissions | HTTP 200. 요청: cloudfunctions.functions.list, cloudfunctions.functions.get, resourcemanager.projects.get. 반환: resourcemanager.projects.get만 |

직접 실패 원인은 **cloudfunctions.functions.list가 허용되지 않은 것**이다. 상세 조회용 get도 이번 프로젝트 권한 검사에서 허용되지 않았다. 프로젝트 자체는 존재하고 다른 인증의 목록/소스 조회가 성공했으므로 잘못된 프로젝트나 함수 자체 장애로 판단하지 않는다. IAM 정책/조건/deny의 구체적 원인까지는 조회하지 않았으므로 특정 역할 누락만으로 단정하지 않는다.

[공식 list API 문서](https://docs.cloud.google.com/functions/docs/reference/rest/v2/projects.locations.functions/list)는 parent에서 cloudfunctions.functions.list를 요구한다. 서비스 런타임 계정에 배포 관리자/Owner를 부여할 필요는 없다. 이번 검토는 기존 Firebase CLI의 별도 인증으로 완료했으므로 권한 추가 없이도 수행 가능했다. 권한을 추가한다면 별도 검토 계정의 필요한 읽기 권한을 대상으로 승인받는다.

## 2. 이번 배포에서 실제 변경된 함수

서버 `chat/firebase.json`은 functions 소스, nadree-chat codebase, python312 런타임을 선언한다. 현재 main.py는 다섯 callable과 15분 만료 함수를 모두 정의하지만 **소스 선언이 모두 배포됐다는 증거는 아니다**. ad02598 커밋은 main.py 리전을 서울에서 자카르타로 변경했다.

서버 저장소에서 firebase-debug.log, 배포 debug 로그, .firebaserc를 찾지 못했다. 쉘 히스토리·nohup 원문·비밀 환경파일은 출력하지 않았다. 대신 프로젝트 Cloud Audit Logs의 2026-10-12 UTC 하루 Cloud Functions Admin Activity를 읽었다. 결과 3건, nextPageToken 없음:

| 시각 UTC | 메서드 | 대상/결과 |
| --- | --- | --- |
| 06:23:37.111 | GenerateUploadUrl | asia-southeast2 소스 업로드 URL 발급 |
| 06:23:40.291 | CreateFunction, operation.first | expireInactiveInquiries 생성 시작; create 권한 granted |
| 06:24:57.432 | CreateFunction, operation.last | expireInactiveInquiries 생성 완료; status code 0 |

두 CreateFunction 로그는 같은 operation이다. 따라서 단순 갱신이 아니라 **expireInactiveInquiries 신규 생성**이 확인됐다. 이날 조회 범위에 나머지 7개 함수의 Create/Update/DeleteFunction은 없었다. 현재 메타데이터도 Node.js 7개의 updateTime을 2026-09-18로 표시한다.

| 실제 배포 | codebase/런타임 | 소스 및 상태 |
| --- | --- | --- |
| callable 5개 | default/nodejs22 | 9월 18일 배포, ACTIVE, 이번 배포에서 변경된 근거 없음 |
| setChatStatus | default/nodejs22 | 동일 |
| notifyBookingChatMessage | default/nodejs22 | 동일, chatRooms/{roomId}/messages/{messageId} created 트리거 |
| expireInactiveInquiries | nadree-chat/python312 | 10월 12일 신규 생성, ACTIVE, 현재 main.py/chat_core.py와 바이트 동일 |

Node.js 7개의 ZIP SHA256은 모두 `06f78148fb024896258a210763d5c0bf1460c657e6f07ec8255232ac69eb028e`; Python 만료 ZIP은 `4d45ac08754d7f36f91fc18380cd7a0e1e82afbf647ff8e916866e60328d2f33`. 각 함수 sourceProvenance generation을 지정해 읽었다. 배포 명령의 정확한 --only 선택, callable 누락 이유, CLI 경고/실패는 감사 로그만으로 복원할 수 없다. 필요한 자료는 비밀값을 제거한 당시 CLI 출력/CI 작업 기록과 실행 명령이다.

Firestore Rules release는 06:23:38 UTC 현재 계약 내용으로 변경돼 있다. 인덱스 4개 READY는 적용 상태를 증명하지만 각각의 적용 시각/이번 작업의 적용 주체까지 확인하지 않았다. 현재 기본 DB 위치는 asia-southeast2. SQL app.migrate는 No pending changes였지만 누가 언제 적용했는지는 이 결과만으로 알 수 없다.

## 3. 기존 함수의 앱 사용 여부

Cloud Run 요청 로그를 읽기 전용으로 조회했다. 범위는 bail-472405, timestamp >= 2026-09-12 UTC, 기존 callable 5개와 setChatStatus의 서비스 이름, run.googleapis.com/requests. 페이지 끝까지 조회해 총 7건 확인했다. 요청 본문·IP·토큰·사용자 정보는 조회 결과에 출력하지 않았다.

- 2026-09-17 ensureBookingChat 401 1건.
- 2026-09-18 ensureBookingChat/ensureInquiryChat/sendChatMessage/markChatRead/getChatUnreadSummary/setChatStatus 401 각 1건.
- 이 조회 결과에는 성공 요청이 없었다. 배포 확인용 미인증 호출일 가능성은 있으나 호출자의 정체는 확인하지 않아 추정이다.

**이는 현재 앱 사용 중이라는 증거도, 미사용이라는 확정 증거도 아니다.** 로그 제외·보존·샘플링/다른 경로, 아직 채팅 화면을 열지 않은 설치 앱, 오프라인 캐시를 확인하지 않았다. 서버 /srv에는 확인 가능한 모바일/웹 앱 소스가 없었다.

앱 담당자에게 필요한 비밀값 없는 자료:

| 자료 | 확인할 내용 |
| --- | --- |
| 실제 출시 앱/웹의 소스 또는 관련 파일 | Firebase 프로젝트·리전, httpsCallable 6개 이름, setChatStatus 사용 여부, Firestore 경로와 필드, 기존 직접 쓰기/읽음 방식 |
| 출시 버전·빌드/배포 커밋 | 스토어 출시본과 소스 일치, 최소 지원 버전, 원격 설정/feature flag, 활성 사용자 버전 분포 |
| 로그인/푸시 처리 코드 | custom token 교환, chatSessionId, 재연결/다른 기기/로그아웃, App Check 등록, token 갱신, 기존 푸시 type와 eventId 처리 |
| 앱 사용 기록의 집계 | 채팅 화면 진입·callable 호출 성공/실패·구독 경로, 사용자 본문/토큰 제외 |
| 출시본의 격리 테스트 결과 | 승인된 테스트 계정으로 문의/예약/메시지/읽음/종료 실제 호출 경로. 실제 고객 대상으로 실행하지 않음 |
| Firestore 데이터 현황 집계 | chatRooms/chatRoomAccess/bookingChatAccess/chatReads/토큰/알림 job의 문서 수·스키마·최근 쓰기 시각과 기존 매핑 존재 여부. 이번에는 고객 데이터 자체를 읽지 않음 |
| 기존 배포 운영 자료 | 당시 firebase.json·.firebaserc·원본 저장소 커밋, 이전 Rules/인덱스, 기존 cron/외부 Scheduler 위치 및 로그 |

## 4. Python 교체 시 영향과 승인 전 준비 계획

기존 구현 소스 확인은 가능했다. 다만 앱 사용 여부가 미확정이므로 아래는 교체를 실행하기 위한 확정 승인이 아닌 **검토용 계획**이다. 상세 불일치는 firebase-chat-compatibility-review-2026-10-12.md에 기록했다.

| 대상 | 영향 및 필요한 조치 |
| --- | --- |
| 앱 호출 | 동일 이름이어도 ensureInquiryChat의 productId, 오류 코드, 고객 unread, 메시지 UUID/원문, 읽음 position 의미가 달라짐. 현재 API 세션 발급→custom token 교환→자카르타 callable의 새 흐름과 App Check를 출시본에 반영해야 함. setChatStatus 재개 호출 제거 필요 |
| Firestore 방/메시지 | 기존 chatRooms/messages에서 chatRoomAccess/messages로 이동. roomType/chatStatus/sequence와 kind/status/lastSequence 매핑 필요. 기존 예약 hash roomId와 문의 결정 ID를 임의 UUID로 바꾸면 앱 링크가 깨지므로 매핑/호환 전략을 먼저 확정 |
| 예약·문의 | bookingChatAccess의 active/chatStatus/shopDisplayName과 새 roomId/closed/blocked 구조가 충돌. 첫 문의 전환과 복수 예약, 종료 불가역, 168시간 기준을 별도로 검증. 과거 문의를 임의 재개/현재 예약에 추정 연결하지 않음 |
| 읽음 | roleSequence와 전체 sequence가 달라 그대로 복사 불가. 기존 메시지의 순서와 발신자에 근거한 변환 규칙을 만들고 검증. 읽지 않은 메시지를 임의로 읽음 처리하지 않음 |
| Auth/세션 | role→kind, 새 sessionId/업무 세션/만료 필요. 기존 토큰을 새 세션으로 자동 승격하지 않고 재인증·채팅 세션 재발급. 일반 직원 canReply=false 검증 |
| 보안 규칙 | 현재 Rules는 새 경로만 허용하여 기존 앱의 chatRooms 읽기를 차단할 수 있음. 이전 Rules 확보 후 다른 업무 영향을 검토하고 앱 전환과 함께 적용. 글로벌 allow로 일시 복구하지 않음 |
| 알림 | 기존 notify 트리거·chatNotificationJobs·기기별 토큰과 새 chatPushEvents·SQL 알림함·단일 토큰 계약이 다름. FCM 발송 주체 하나를 선택하고 기존 대기 job 처리/중복 eventId/재시도 경계를 검증. 변환 백필이 실제 고객 푸시를 발생시키지 않도록 격리하거나 승인된 차단 절차 필요 |
| 함수 배포 | default/nodejs22 동명 함수를 nadree-chat/python312로 바꾸는 것은 기존 함수 소유 codebase와 런타임 전환이다. CLI가 삭제/재생성을 요구하면 별도 승인 대상. 이름별 작업·가용성 공백·앱 최소 버전을 명시하고 자동 삭제 승인 금지 |
| 만료 스케줄 | 실제 Scheduler를 전체 운영 경로에서 확인하고 한 실행 주체로 통일. 자카르타 jobs 조회는 빈 목록이었으므로 실제 15분 실행 확인 필요. 기존 Node.js 문의는 Python 만료 쿼리에 잡히지 않음 |
| 서버 동기화 | 전체 sync가 기존 동명 문서를 새 구조로 쓰므로 승인 전 실행하지 않음. dry-run 비교/읽기 전용 계획을 먼저 작성하고 유일성·단일 실행·종료 경합·공유 서버 회수 검증 |

전환 순서:

1. 앱 출시본/기존 데이터 사용 현황과 정본 계약 확인. 사용 중이면 지원 버전별 전환 기간·최소 앱 버전·가용성 창 확정.
2. 배포 소스 ZIP generation/hash, 기존 함수 메타데이터/IAM/환경 설정, Rules·인덱스·Scheduler·API 릴리스/비밀 환경설정의 접근 제한 백업과 Firestore/SQL 복구 지점 준비. 비밀 백업은 저장소에 넣지 않음.
3. demo Firebase와 폐기 가능한 nadree_w02_test_* DB에서 앱+API+callable+Rules+트리거를 함께 검증. PayPal Sandbox 테스트 계정만 사용하고 실제 푸시를 억제. migration dry-run 결과·기존 방/읽음/종료 매핑 검토.
4. 함수별 교체/삭제 여부, old trigger 처리, Rules 병합, 데이터 변환 항목, 스케줄, API 변경 및 복구 기준을 구체화한 뒤 명시적 승인 요청.
5. 승인된 작업창에서 쓰기/알림 전환을 통제하고 필요한 데이터만 이전. 이전/새 앱이 서로 다른 경로에 동시에 메시지를 쓰는 기간을 만들지 않음. 실제 고객을 인수 테스트 대상으로 쓰지 않음.
6. 테스트 계정으로 권한·세션 회수·문의/예약·중복 전송·알림·종료 경합·만료·복구 확인 후 단계적으로 해제. 실패 시 아래 복구 절차로 전환.

복구 계획:

- 단순 API env=false나 코드 rollback은 이미 발급된 Firebase 권한을 폐기하지 않는다. 장애 시 승인된 callable/Rules/세션 접근 차단과 알림·동기화·스케줄 정지를 함께 수행하는 절차를 준비한다.
- 이전 소스와 기존 runtime/codebase·IAM/환경 설정·Rules·인덱스·스케줄을 정확히 복원할 수 있어야 한다. 데이터 스키마가 새 구조이면 이전 함수만 복원해서는 안 된다.
- 전환 이후 새 메시지/읽음/예약 종료 변경을 별도 보존한 뒤 합의된 역변환/매핑으로 재적용한다. 사전 백업으로 무조건 덮어써 신규 메시지를 잃거나 종료된 방을 재개하지 않는다. 역변환 미검증 시 쓰기 차단 유지 후 수동 복구한다.
- 알림 중복 방지 기록과 미발송 job을 보존하고, 복구 시 양쪽 발송기를 동시에 켜지 않는다. 재전송 기준을 정해 고객에게 과거 메시지 푸시를 무더기로 발송하지 않는다.
- 복구 완료 후 승인된 테스트 계정으로 권한·현재 앱 읽기 경로·메시지 순서·종료/환불 상태를 다시 확인한다. DB 컬럼/테이블 삭제로 되돌리지 않는다.

전체 출시/교체 완료로 판정하지 않는다. 이번 작업으로 403 원인과 당일 함수 변경 이력은 확인했고, 기존 소스 분석도 가능했다. 앱 사용 여부와 실통합/데이터 이전·복구 검증은 남아 있다.

## Cloud Functions Viewer 추가 후 동일 계정 재확인

2026-10-12 사용자 역할 추가 안내 후 새 프로세스에서 기존 FCM 자격증명으로 재검사했다. 실제 principal은 `firebase-adminsdk-fbsvc@bail-472405.iam.gserviceaccount.com`, 대상은 `bail-472405`다. Firebase CLI의 별도 인증으로 대체하지 않았다.

- Functions v1/v2 전체 리전 list: 각각 HTTP 403 PERMISSION_DENIED.
- 자카르타의 위 8개 함수에 v2 get 직접 실행: 8개 모두 HTTP 403 PERMISSION_DENIED.
- 프로젝트 testIamPermissions: HTTP 200, cloudfunctions.functions.list/get 둘 다 반환되지 않음. resourcemanager.projects.get만 반환.

따라서 역할 추가가 이 principal/프로젝트에서 유효한 읽기 권한으로 반영됐다고 확인할 수 없다. 반영 지연, 다른 principal/대상에 부여, 조건/deny 중 원인은 미확정이다. 필요한 권한은 list(함수 목록)와 get(함수 설정/소스 provenance)이며, 추가 관리자/배포 권한을 요청하지 않는다. 먼저 bail-472405의 해당 서비스 계정에 부여한 Viewer 바인딩과 조건을 확인해야 한다.

이번 동일 계정 조회가 실패했으므로 최신 배포 설정/소스를 재확인했다고 보고하지 않는다. 앞선 별도 CLI 인증에서 확보한 소스 비교 결과는 그대로지만 재조회 성공 결과와 구분한다. get 실행 이후 로컬 소스 대조는 ec2-user가 ssm-user의 비공개 /tmp ZIP 폴더에 접근하지 못하는 PermissionError도 발생했다. 이는 Cloud Functions 403과 별개이며 파일 권한을 변경하지 않았다. 서비스 계정의 실제 list/get 결과에는 영향을 주지 않는다.

## 07:22 UTC 반영 대기 후 계정·IAM 원인 확정

2026-10-12 07:20 UTC 확인을 시작하고 30초 대기 후 새 프로세스로 재조회했다. 실제 요청 기록 시각은 07:22:14 UTC다. v1/v2 list와 8개 함수 v2 get 모두 403이었다. 응답 code=403, status=PERMISSION_DENIED, details=null. list 메시지는 `Permission 'cloudfunctions.functions.list' denied on 'projects/bail-472405/locations/-/functions'`; get은 `Permission 'cloudfunctions.functions.get' denied on 'projects/bail-472405/locations/asia-southeast2/functions/<함수명>'`이었다. testIamPermissions도 두 권한을 반환하지 않았다.

서비스 조회는 Settings로 명시적으로 만든 google.oauth2.service_account.Credentials를 AuthorizedSession에 넘긴다. Settings email, credential.service_account_email, signer_email 모두 `firebase-adminsdk-fbsvc@bail-472405.iam.gserviceaccount.com`으로 일치한다. Firebase 앱 프로젝트와 credential.project_id도 bail-472405로 일치하며 OAuth scope에 cloud-platform이 포함된다. 이 경로는 Firebase CLI 로그인/gcloud 로그인/ADC를 사용하지 않는다.

기존 Firebase CLI 인증으로 프로젝트 getIamPolicy(version 3 요청)를 읽었고 실제 결과는 version 1이었다. 핵심 바인딩:

```text
roles/cloudfunctions.viewer → user:qwer886901@gmail.com
roles/firebase.sdkAdminServiceAgent → serviceAccount:firebase-adminsdk-fbsvc@bail-472405.iam.gserviceaccount.com
roles/firebaseauth.admin → serviceAccount:firebase-adminsdk-fbsvc@bail-472405.iam.gserviceaccount.com
roles/iam.serviceAccountTokenCreator → 위 서비스 계정 등
```

Viewer 바인딩에는 condition이 없고 실패 요청 서비스 계정은 그 members에 없다. 따라서 **역할을 받은 사용자 계정과 실패 요청의 서비스 계정이 다른 것**을 확인했다. 단순 지연으로 판단하지 않는다. 확인된 직접 바인딩에 실패 서비스 계정의 Functions Viewer는 없다.

프로젝트 조회 결과 projectId=bail-472405, projectNumber=272033658852. getAncestry는 프로젝트만 반환했고 조직/폴더 부모는 없었다. 프로젝트 attachment의 IAM v2 deny policies 목록은 HTTP 200, 0개, nextPageToken 없음이었다. 이 조회 범위에서 IAM 조건/프로젝트 거부 정책이 원인이라는 증거는 없다.

인증 경로별 확인:

| 경로 | 실제 확인 |
| --- | --- |
| 실패 서비스 GET | 명시적 FCM 서비스 계정. signer까지 동일성 확인 |
| Firebase CLI | 설정 계정·requireAuth 반환 계정 모두 qwer886901@gmail.com, Firebase CLI configured account 경로 |
| gcloud | 서버에서 실행 파일 미설치. gcloud 로그인 상태를 실제 조회 경로로 사용하지 않음 |
| ADC, ssm-user | google-auth-library 기본 인증 탐색 실패. CLI configured account와 별개 |
| ADC, ec2-user | GOOGLE_APPLICATION_CREDENTIALS 미설정, 기본 application_default_credentials.json 없음, CLOUDSDK_CONFIG override 없음. 메타데이터/외부 인증 전체 부재를 증명하지 않지만 실패 요청은 ADC를 사용하지 않음 |

Policy Troubleshooter v3도 읽기 진단 목적으로 시도했으나 별개 HTTP 403, ErrorInfo.reason=SERVICE_DISABLED였다. 해당 요청의 API consumer는 projects/563584335869로, 함수 조회 대상 프로젝트 272033658852와 구분된다. CLI OAuth 호출 경로의 진단 API 비활성 오류이며 Functions list/get 누락 권한과 같은 오류가 아니다. API 활성화/소비 프로젝트 변경은 하지 않았다. 직접 IAM 바인딩·조건·deny 조회로 위 계정 불일치를 확인했다.

필요한 Functions 권한은 list(목록)와 get(상세 설정/provenance)이다. 더 높은 역할을 임의 부여할 필요가 없다. 사용자가 실패 서비스 계정으로 검토를 계속하려면 해당 계정/프로젝트 바인딩을 지정해야 하고, 배포 계정으로 검토하려면 현재 CLI 인증 경로를 사용하면 된다. 권한 확대·정책 변경·재배포는 수행하지 않았다.

## 최신 재조회 — 07:27 UTC 성공

사용자 재요청에 따라 30초 대기 후 2026-10-12 07:27:50 UTC에 새 프로세스로 확인했다. 실제 credential email/signer는 동일 FCM 서비스 계정, 대상 프로젝트는 bail-472405였다.

- v1/v2 list 모두 HTTP 200. v2 함수 8개 각각 get도 HTTP 200. v1 목록은 비어 있으며 null 이름 출력은 진단 스크립트의 빈 응답 처리 때문에 생긴 표시로 실제 함수가 아니다.
- testIamPermissions가 cloudfunctions.functions.get/list를 둘 다 반환했다.
- 현재 IAM Viewer 바인딩 members에 서비스 계정과 qwer886901@gmail.com이 모두 포함됐다. 이전 07:22 조회에서는 사용자 계정만 포함돼 있었다. 현재는 바인딩 변경과 유효 권한을 확인했으므로 이전 실패를 단순 지연으로 소급 단정하지 않는다.
- Viewer 바인딩 조건 없음, getAncestry는 프로젝트만, 프로젝트 deny policies는 0개다. 프로젝트 번호 272033658852 일치.
- 동일 서비스 계정으로 상세 설정 비교 완료: 기존 7개 default/nodejs22, 만료 함수 nadree-chat/python312, 전부 자카르타 ACTIVE. timeout 60초/max instances 10 공통, Node.js concurrency 80, Python 만료 concurrency 1. notify 트리거는 여전히 chatRooms 메시지 created이며 CHAT_ENFORCE_APP_CHECK override는 없음.
- 별도 CLI 인증·gcloud·ADC로 성공 요청을 대체하지 않았다. Policy Troubleshooter 별도 진단은 여전히 SERVICE_DISABLED지만, 직접 list/get 및 조건/deny 조회가 성공해 해당 API 활성화는 필요하지 않다.

현재 소스는 callable까지 nadree-chat/python312를 선언하므로 배포본과 계약 불일치는 그대로다. 추가 list/get 권한은 필요 없다. 비밀값 출력·권한 확대·재배포·함수 삭제/덮어쓰기는 수행하지 않았다.
