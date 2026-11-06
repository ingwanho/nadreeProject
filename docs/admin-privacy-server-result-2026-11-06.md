# 관리자 개인정보 요청·여권 중단 — 실제 서버 적용·검증 결과

검증일: **2026-11-06 UTC**. Git: **73564d4b6d215190f847c18014377d3a0ff9abea** + 아래 서버 로컬 보완. **사용자의 “전체 적용·자동 처리 활성화 승인” 후 신규 컬럼 1개 적용, API 1회 재시작, 5분 자동 처리 활성화를 08:16 UTC 완료했다.** 최초 배치는 대상/처리/완료/재시도/영수증 만료 삭제 모두 0건으로 정상 종료했다. 실제 시험 탈퇴·메일·Auth 삭제는 실행하지 않았다.

기준: [서버 실행서](admin-privacy-server-apply-2026-11-06.md), [앱 계약](frontend-admin-privacy-handoff-2026-11-06.md). 사용자의 최신 검사 범위 지시에 따라 변경 관련 검사만 실행했으며 전체 회귀는 실행하지 않았다.

## 받은 변경과 Git 보존

- 시작 상태 main·로컬 변경 없음. `git pull --ff-only origin main`: **fd67cd1 → 73564d4**, 충돌·강제 초기화 없음.
- 신규 개인정보 요청 API 4개, Firestore 작업·복구·운영 도구, 기존 탈퇴/가입/예약/인계의 차단 연결, 5분 전용 배치를 받았다.
- 여권 PUT/GET은 라우트 등록만 중단한다. 구현·기존 파일·DB 키를 삭제하지 않는다. 새 API 적용 후 health 제외 경로는 **78개**다.
- SQL 변경은 `MSP_SPOT_RENT.deletion_request_id VARCHAR(80) NULL` **1컬럼**이다. 신규 SQL 테이블·env·의존성·Firebase Functions/Rules/인덱스 배포는 없다.
- stash OID `01e48b41d1c1b53d7d11b7f1c4fb487edbbba48d`를 보존했다. 서버 보완은 로컬 변경으로 남기며 자동 커밋/푸시하지 않았다.
- AGENTS.md와 README·실행서를 확인했다. 부모 명세 `/srv/rental-project-master.md`, `/srv/rental-api-review-decisions.md`는 서버에 없어 갱신하지 못했다.

## 적용 전에 발견·보완한 연결 문제

| 문제 | 수정 전 근거 / 영향 | 로컬 보완 |
| --- | --- | --- |
| 기존 DELETE 우회 | 일반관리자의 개인정보 요청이 진행 중이어도 대표의 기존 SUBTREE DELETE가 HTTP 200. 대상의 역할·세션 회수로 원래 복구 작업이 실패할 수 있음 | 전체 대상 관리자·지점과 저장된 요청 범위를 잠금 아래 확인하고 외부 회수 전 거절 |
| 상위 대표의 하위 지점 변경 | 하위 지점 삭제 접수 후 상위 대표의 프로필 수정·하위 생성이 각각 HTTP 200 | 실제 변경 대상과 생성 부모의 차단 표시 확인. GET·상위 지점 정상 변경은 유지 |
| 신규 요청의 범위 중첩 | 요청자별 중복 검사만 있어 일반 SELF와 대표 SUBTREE, 상하위 SUBTREE가 같은 대상을 처리할 수 있음 | SQL 지점 잠금 아래 저장된 Firestore 요청 범위의 관리자/지점 교집합 확인. 접수·재확인·운영 등록·작업 회수·기존 DELETE에 적용 |

수정 전 첫 두 문제는 격리 재현 **3건 실패(기대 409, 실제 200)**로 확인했다. 같은 실행의 새 CORS 헤더 검사는 통과했다. 실패 증거를 보존하고 원인을 가리는 예외 처리를 추가하지 않았다.

`pending_scope_allowed`는 Firestore에 접수됐지만 SQL 차단 표시가 커밋되지 않은 구간도 검사한다. 서로 다른 일반관리자의 SELF 요청은 허용한다. 새 컬렉션/인덱스/테이블을 추가하지 않았다. 추가 테스트는 [연결 회귀](../tests/test_privacy_admission_guards.py)에 있다.

## 관련 격리 테스트

실제 .env·서비스 DB 주소·Firebase/Google/PayPal 자격정보를 제외한 추적 소스 스냅샷, 폐기용 SQLite, 가짜 채팅/메일/삭제 저장소, 임시 파일을 사용했다. 계정 삭제는 격리 데이터에만 수행했다.

| 실행 UTC | 범위 | 실제 결과 |
| --- | --- | --- |
| 07:54:59~07:55:39 | 신규 요청·기존 관리자 탈퇴·역할 양도/직원 제거·가입·인수/반납/회수·여권 중단·마이그레이션 계획·OpenAPI/CORS | **56 passed / 1 skipped / 실패·오류 0** |
| 07:51:17~07:51:28 | 기존 SDK를 사용하는 개인정보 Firestore 검사 3개 | **3 passed / 건너뜀·실패·오류 0** |
| 08:03:33~08:04:14 | 최초 우회 보완 후 위 관련 검사 + 신규 4개 | **60 passed / 1 skipped / 실패·오류 0** |
| 08:08:40~08:09:11 | 최종 중첩 보완 후 요청/운영/복구·기존 탈퇴·신규 11개 연결 회귀 | **46 passed / 1 skipped / 실패·오류 0**, 신규 11개 모두 통과 |

서로 겹치는 재검사 횟수를 더해 통과 건수를 부풀리지 않는다. 건너뜀은 비어 있는 전용 `nadree_w02_test_*` MySQL이 필요한 대표 삭제 접수·예약 동시성 검사다. SQLite 순차 검사를 실제 MySQL 경합 통과로 표시하지 않는다. 기존 의존성 deprecation 경고 2개는 실패와 구분한다.

Firestore는 **demo-nadree-chat / AnonymousCredentials / localhost 에뮬레이터**만 사용했다. 동일키/요청자 동시 접수, 회전 영수증 보존·완료 영수증 만료, 상대방 내용·메시지 순번 보존 익명화를 검증했다. 자체 에뮬레이터 프로세스 종료 확인, 새 다운로드·실제 Firebase·SMTP·FCM 사용 없음. 이후 서버 로컬 보완은 SDK 저장소/메시지 익명화 구현을 바꾸지 않아 해당 검사를 반복하지 않았다.

## 적용 전 실제 서버 읽기 전용 점검

2026-11-06 **07:53:41~07:53:44 UTC**, ec2-user로 확인했다.

| 항목 | 실제 결과 |
| --- | --- |
| 실제 DB | **RIDERLOG_V2_DATA_TEST**, 대상 테이블 2행 |
| app.migrate 기본 계획 | **PENDING add MSP_SPOT_RENT.deletion_request_id** 1개, 그 외 변경 없음 |
| 현재 컬럼 | 없음. `--apply` 실행 안 함 |
| Firestore 프로젝트 | **bail-472405**, 위치 Firebase 미사용 |
| 실제 계정 | **firebase-adminsdk-fbsvc@bail-472405.iam.gserviceaccount.com** |
| 권한 | testIamPermissions HTTP 200. datastore.databases.get·entities.get/list/create/update/delete, firebaseauth.users.get/delete **8개 모두 부여**, 추가 IAM 변경 없음 |
| SMTP | host·from·user·password 설정 존재. 실제 로그인/메일 발송 성공은 미검증 |
| 확인 토큰/연락처 보호 | 기존 JWT 키 최소 32바이트 조건 충족. 키 변경 안 함 |
| 기존 개인정보 요청 | **0건** |
| 보관 정책 확인 문서 | **없음**. 확인하지 않은 운영 정책을 임의 등록하지 않음 |
| 현재 API | 로컬 live·ready·OpenAPI HTTP 200, **76개 경로**, 기존 여권 경로는 아직 노출 |
| env | ec2-user 소유 **0600**, 값 변경/출력 없음 |

이 표는 적용 전 상태다. 신규 컬럼을 먼저 적용한 뒤 아래 순서로 API를 재시작했으며, 최종 상태는 78개 경로·여권 미등록이다.

## 백업·복구 준비

- **08:01:48 UTC** ec2-user가 변경 대상 `MSP_SPOT_RENT` 전체 구조·2행을 읽기 전용 mysqldump로 백업했다.
- 경로: `build/test-runtime/admin-privacy-2026-11-06/MSP_SPOT_RENT-before-deletion-gate.sql.gz`.
- 디렉터리 **0700**, 파일 **0600**, ec2-user 소유. dump 종료 코드 0·gzip/대상 CREATE/완료 footer·체크섬 확인.
- 백업 명령용 비공개 접속 옵션 파일은 작업 후 제거했다. 복구 시험·DB 쓰기·기존 데이터 초기화는 하지 않았다.
- 이번 백업은 컬럼 추가 전 해당 테이블 복구 수단이다. 실제 개인정보 정리 후 전체 데이터를 되살리는 백업 정책 승인이나 실제 복원 검증을 의미하지 않는다.
- 적용 후 문제가 생기면 새 배치를 중지하고 진행 중 작업을 확인한다. 추가 컬럼은 구 코드와 공존시키며 자동 DROP·계정 재활성화·삭제 데이터 복원은 하지 않는다.

## 승인받은 실제 적용 범위

기존 사용자의 DB 스키마·실제 계정 삭제 등 외부 영향 작업 사전 승인 지침에 따라, 이전 **90일 채팅 보관 종료 승인과 다른 개인정보 처리 범위**를 구체적으로 제시했다. 사용자가 **“전체 적용·자동 처리 활성화 승인”**으로 회신했고 아래 작업을 모두 완료했다.

1. 백업한 **RIDERLOG_V2_DATA_TEST**에 위 nullable 컬럼 **1개만** app.migrate로 적용하고 읽기 전용 재계획 0개 확인.
2. 원격 커밋 **73564d4 + 검증된 서버 로컬 차단 보완**으로 nadree-api 1회 재시작. 로컬/공개 헬스·준비·Swagger/OpenAPI·신규 4경로 인증 차단과 여권 2경로 404 확인. 실제 탈퇴 요청은 시험하지 않음.
3. `nadree-account-deletions.service/.timer` 설치·**5분 배치 --apply 활성화**, 활성화 직후 실행 가능성 포함. 향후 저장된 요청에 따라 실제 렌탈 역할·세션/FCM 회수, SQL 개인정보·채팅 익명화, **관리자 채팅 전용 Auth UID 삭제**, 접수/완료 메일이 수행됨.
4. 기존 결제/환불·receipts·chat-sync·90일 chat-retention과 FCM/Auth 고객·차량/QR/위치 데이터를 보존. Firebase 배포·보안 완화·임의 테스트 요청/푸시·키 변경은 하지 않음.

실제 보관/복원 통제가 확인되지 않았으므로 policy 확인을 등록하지 않는다. 이 상태에서도 배치가 권한 회수·익명화까지 진행할 수 있으며 최종 정책 확인 단계에서 **ACTION_REQUIRED**로 멈춘다. 임의 정책 문구로 완료시키지 않는다.

## 실제 적용·HTTP 결과 — 통과

실제 적용 **08:16:13~08:16:36 UTC**. 서비스 계정 ec2-user로 app.migrate.main의 승인 범위 제한 래퍼를 실행했다. 도구 자체의 마이그레이션 잠금 아래 계획이 정확히 승인된 ALTER 1개인지 확인한 후 적용했으며, 다른 계획이 있으면 실행 전 중단하도록 제한했다.

| 항목 | 기대 / 실제 |
| --- | --- |
| DB 마이그레이션 | 승인된 nullable 컬럼 1개만 적용, 재계획 **No pending changes.** |
| 기존 테이블 데이터 | 기존 **2행**의 새 컬럼 제외 전체 값 해시 전후 동일. 새 컬럼은 모두 NULL |
| API | **08:16:24 UTC** 1회 재시작, PID **2553900**, ec2-user, `/srv/nadree-api`, active/running. 구 PID 2360838 종료 |
| 로컬/공개 live·ready·Swagger·OpenAPI | **8/8 HTTP 200** |
| API 명세 | 로컬/공개 **78개 경로**, 신규 요청 4경로 존재·여권 경로 없음 |
| 무인증 차단 | 로컬/공개 context GET·접수 POST·재확인 POST **6/6 HTTP 401**. POST는 합성 확인 문자열/조회 키만 사용했고 삭제 요청은 생성되지 않음 |
| 여권 중단 | 로컬/공개 PUT 및 GET **4/4 HTTP 404**. 이미지 업로드/삭제 안 함 |
| API 로그 | 적용 구간 시작 오류·ASGI 오류·Traceback **0** |
| 신규 타이머 | nadree-account-deletions.timer **enabled / active / waiting** |
| 최초 자동 실행 | **08:16:31~08:16:33 UTC**, Result=success, 종료 코드 **0**. 완료 후 oneshot inactive/dead는 정상 |
| 최초 작업 집계 | **processed=0 / deferred=0 / completed=0 / expiredReceipts=0** |
| 다음 일정 | 완료 5분 후인 **08:21:33 UTC / 발리 16:21:33 / 한국 17:21:33**, 이후 매회 완료 후 5분 |
| 요청 재계획 | 활성화 전/후 모두 **pendingRequests=0** |
| 보존 | env 값·소유권·0600과 기존 결제 cron·receipts·chat-sync·90일 retention unit 파일 해시 동일. 기존 타이머/crond active |

임의 탈퇴 요청·시험 푸시·실제 메일·실제 계정 삭제·결제/환불·Firebase 배포·권한 확대는 없었다. 현재 요청이 없어 실제 개인정보 처리 성공까지 입증한 것은 아니다. 신규 기능은 이후 접수되는 정상 요청을 자동 처리한다.

**08:19:31 UTC 최종 점검**에서도 API·신규 타이머·기존 작업 정상, 검증한 구현 소스 지문 일치·env/기존 작업 파일/stash 보존을 확인했다. 갱신 문서의 비밀값·충돌 표시·깨진 링크 없음과 git diff --check 통과를 확인했다.

## 남은 검증·운영자/앱 할 일

- 서버 적용·설정·최초 배치·관련 격리 검증은 완료했으며 **미해결 검사 실패는 없다**. 전체 회귀는 사용자 지시대로 실행하지 않음.
- 실제 SMTP 발송·전용 관리자 Auth 삭제·앱의 접수/로그아웃 후 영수증 조회·분실 복구는 폐기 계층과 승인된 수신자 준비 후 별도 공동 시험.
- 전용 MySQL 동시성, 닫는 지점의 계약 기간 만료 후 실제 반납/회수, QR/가입 유입 차단의 실제 서버 왕복은 미검증. 일반 격리 관련 검사와 구분.
- 운영자는 로그·제한 백업·캐시/검색/export·공유 자료와 복원 시 재노출 방지 절차를 실제 검토하고 증거가 있을 때만 보관 정책/자료 검토를 등록.
- 앱은 [최신 계약](frontend-admin-privacy-handoff-2026-11-06.md)에 따라 새 영수증·상태 흐름과 중첩 요청 `409 DELETION_SCOPE_IN_PROGRESS`를 처리하고, 여권 API 호출을 제거.

비공개 근거: `build/test-runtime/admin-privacy-2026-11-06/`, `build/test-runtime/admin-privacy-73564d4-2026-11-06/`. 실제 개인정보·토큰·키·비밀번호는 이 문서에 기록하지 않았다.
