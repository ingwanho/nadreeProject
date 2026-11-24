# 2026-11-24 예약·Walk-in·인계 후속 변경 서버 적용 결과

기준 실행서: [backend-branch-feedback-server-apply-2026-11-24.md](backend-branch-feedback-server-apply-2026-11-24.md). 이전 인계 배포 보류 보고 이후 **별도 인계 키 설정·DB/API/Firebase/배치 전환을 완료했다.** 격리 고유 **979개 통과**, 실제 업무 최종 시나리오 **108개 검사 기록의 기대 결과 충족**을 확인했다. 108은 HTTP와 SQL 확인을 포함하며 독립 테스트 케이스 수나 전체 외부 종단 완료를 뜻하지 않는다. 최종 런타임 확인은 **07:31:15 UTC**다.

## 적용 기준과 현재 서버

- 확인일: **2026-11-24 UTC**, 업무 시간대 `Asia/Makassar`(UTC+8).
- 시작 Git: `main`, 로컬 변경 없음, `134cc08a417189970d621fb747ac4e4e6620e01f`.
- `git pull --ff-only origin main`: 충돌 없이 **`72179977718c372eb101004ccbc52d67a0daa3af`**로 갱신.
- 서비스: `nadree-api.service`, 실행 사용자 `ec2-user`, 작업 경로 `/srv/nadree-api`, 가상환경 `.venv`.
- 실제 DB **`RIDERLOG_V2_DATA_TEST`**를 확인하고 적용했다. 자동 테스트에는 이 DB를 지정하지 않았다.
- 새 API 시작: **07:14:14 UTC**, PID **3407923**. 구 PID 4096997은 먼저 정지했다.
- 실제 로컬 포트는 **8008**이다. 실행서의 8000 예시 대신 실제 서비스 포트로 검증했다.
- 실행 중 프로세스의 DB·기존 FIELD 키·새 HANDOVER 키가 `.env`와 같은 것을 값 없이 비교했다.
- 부모 원본 명세 `/srv/rental-project-master.md`, `/srv/rental-api-review-decisions.md`는 이 서버에 없어 대조하지 못했다. 저장소 실행서·전달서·코드·실행 결과를 근거로 했다.

## 백업·마이그레이션·키

접근 제한 백업: `/home/ec2-user/.nadree-private/branch-feedback-20261124T070400465936Z/`.

- 디렉터리 700, 파일 600, ec2-user 소유. 전체 DB **77개 테이블 / 641,856,027바이트**, dump 완료 표식 확인.
- `database-full.sql` SHA256: `2ade5c84c67517d04f73a50d6ec423ab76993d89c7ca713c65dcd8ef08551eaa`.
- `.env` 변경 전 및 키 생성 후 사본을 같은 비공개 디렉터리에 보관했다. 초기화 도구도 별도 변경 전 사본을 `~/.nadree-private/env-before-handover-*`에 남겼다.
- 이 백업의 실제 전체 복구 시험은 하지 않았다. 복구 시 백업 이후 업무를 대조해야 하며, **생성한 인계 키는 보존**한다. 변경 전 env만 되돌려 인계 키를 유실시키면 안 된다.

ec2-user의 읽기 전용 계획을 검토한 뒤 **17개 작업 적용 → 재계획 0개**를 확인했다.

| 적용 대상 | 실제 결과 |
| --- | --- |
| `MSP_RENTAL_HANDOVER` | 35컬럼 신규 테이블·인덱스 생성 |
| `MSP_RESERVATION` | 상태 CHECK에 `NO_RESPONSE` 반영 |
| `MSP_RENTAL_CONTRACT` | nullable `handover_id`·고유 인덱스·FK 추가. 고객 UID NOT NULL 유지 확인 |
| `MSP_VEHICLE_STATUS` | `operation_id`, `state_version`, `untracked_rent_until` 및 상태·기간 제약 추가 |
| `MSP_RENTAL_USER` | 서류번호 암호문 2컬럼·SNS 컬럼 추가 |
| 구 `passport_img_key` | 잔존 참조 **0건** 재확인 후 실행서대로 컬럼 제거. 기존 이미지 파일 삭제 없음 |

`deployment/initialize_handover_key.py`를 **읽기 전용 → --apply → 읽기 전용** 순서로 실행했다. 기존 인계·프로필 서류 암호문이 없어 최초 설정 조건을 통과했고 **`NADREE_HANDOVER_ENCRYPT_KEY`만 생성**했다. 재검사와 가상 값 암호화/복호화 왕복도 통과했다.

`NADREE_FIELD_ENCRYPT_KEY`와 다른 env 값은 변경하지 않았다. `.env` 소유권·600 권한을 유지했고 MSP_ADMIN/MSP_DRIVER의 기존 전화번호 컬럼 전체를 비공개 비교하여 동일함을 확인했다. **기존 전화번호 키 복구·복호화 성공을 확인했다는 의미는 아니다.** 그 문제는 별도로 남는다.

## 실제 보정·타이머

기존 receipts 타이머와 관련 작업 및 API를 정지한 뒤 적용했다. 중복 `app.jobs all/lifecycle/maintenance/receipts` cron은 없었고, 기존 결제 복구 cron은 보존했다.

`app.jobs lifecycle --backfill-no-response`: **전환 19건 / 알림 0건**.

| 상태 | 적용 전 | 보정 후 |
| --- | ---: | ---: |
| 예약 REQUESTED | 4 | 1 |
| 예약 APPROVED | 10 | 1 |
| 예약 EXPIRED | 5 | 12 |
| 예약 NO_RESPONSE | 0 | 5 |
| 실제 계약 ON_RENT / OVERDUE | 5 / 0 | 0 / 5 |
| 차량 AVAILABLE / DISABLED / ON_RENT | 73 / 1 / 5 | 66 / 8 / 5 |

기존 예약·계약·결제 행을 삭제하거나 강제 반납하지 않았다. 만료된 배정 차량은 회수 보호로 유지했고 실제 미반납 렌트는 OVERDUE로 전환했다. 위 수치는 이후 시험 예약 생성 전의 보정 결과다.

- `nadree-rental-lifecycle.timer`: 매분 활성화. 반복 실행에서 `transitions:0, reminders:0` 확인.
- `nadree-maintenance.timer`: 5분 간격 활성화. 첫 실행 `maintenanceReleased:0` 확인.
- 구 `nadree-receipts.timer`: disable/stop. 동일 역할의 중복 상시 실행 제거.
- 종료 과정의 SIGTERM으로 남았던 구 receipts 서비스의 failed 표시는 reset-failed로 정리했다. 서비스 재실행 없이 inactive, 타이머 disabled를 확인했다.
- 개인정보 삭제·채팅 동기화·90일 채팅 보존 타이머 및 결제 복구 cron은 유지했다.
- 간편대여는 maintenance 자동 해제 대상에서 제외한 코드이며, 실제/격리 검증을 아래에 구분한다.

## Firebase 실제 적용·채팅 동기화

프로젝트 **bail-472405**, 리전 **asia-southeast2**, codebase **nadree-chat**, **Python312**를 유지했다. 실제 CLI 조회 신원을 확인한 뒤 기존 7개만 업데이트했다.

`ensureBookingChat`, `ensureInquiryChat`, `sendChatMessage`, `markChatRead`, `getChatUnreadSummary`, `expireInactiveInquiries`, `dispatchChatPushEvent`.

- 7개 모두 ACTIVE, 배포 소스 4파일×7개 **28/28 일치**.
- Auth/App Check 설정·호출자 IAM·콜백 env·문의 만료 `every 15 minutes / UTC` 스케줄과 재시도·대상 보존 확인.
- Functions 생성/삭제, 다른 codebase, Rules·인덱스, IAM 정책, 빌드 이미지 삭제 없음.
- CLI 배포가 `dispatchChatPushEvent` 재시도를 DO_NOT_RETRY로 바꾼 것을 발견하여 기존 도구로 **해당 retryPolicy만 RETRY_POLICY_RETRY로 복원**했다. 최종 트리거 설정 재확인 완료. 다음 codebase 배포 때도 이 항목을 확인해야 한다.
- 실제 읽기 전용 대조: SQL NO_RESPONSE **5건**, Firestore 예약 접근 링크 closed **5건**, 채팅방 read_only **5건**, 열린 방/링크·누락 **0건**.
- 기존 chat-sync는 정상 반복 중이다. 07:00~07:18 UTC 21회 정상 완료, 타임아웃·권한 오류·예외 0건. 전체 1회 약 51~56초여서 30초 타이머의 oneshot 실행 중 표시와 정지를 혼동하지 않았다.
- 실제 배포 callable의 App Check 종단·기기 푸시 수신은 별도 미검증이다.

## 격리 자동 검증

ec2-user, 최소 환경·별도 HOME·실제 서비스 인증정보 없는 환경으로 실행했다.

| 실행 | 결과 |
| --- | --- |
| 최신 전체 기본 회귀 | **956 passed / 23 skipped / 14 warnings** |
| Firestore demo 에뮬레이터 | **8 passed** |
| localhost S3 SDK 통신 대역 | **16 passed**, 기본 회귀 중복 13개 제외 시 추가 **3개** |
| 별도 MySQL DB 경합 | 초회 **11 passed / 1 failed**, 해당 입력 수정 후 새 DB에서 **1 passed** |
| 고유 합계 | **979 passed**, 남은 조건부 건너뜀 0개 |

MySQL 실패는 `test_mysql_reservation_racing_with_primary_deletion_is_blocked_or_included`의 오래된 견적 입력이었다. 종료일 포함 **4일×10=40**인데 30을 보내 가격 검증에서 막혔다. `tests/test_account_deletions.py`의 금액 1줄만 30→40으로 수정하고 보안/경합 판정은 그대로 유지하여 재검사했다. 업무 코드 수정은 없다. 새 MySQL DB 2개는 테이블 0개를 확인한 뒤 정리했다.

14개 경고는 기존 의존성·자원 경고다. 테스트 수만으로 외부 연동 완료로 판단하지 않는다.

| 실행서 6절 요구 | 격리 결과 | 실제 서버 |
| --- | --- | --- |
| 종료일 포함·당일 1일 Walk-in·USD finalPrice | 통과 | 실제 견적·승인·렌트·반납 통과 |
| 다음 날 NO_RESPONSE·EXPIRED 회수 보호·OVERDUE | 통과 | 무알림 보정 19건·차량 보호 확인 |
| 09:00 수신자·중복·발송 직전 상태·늦은 Walk-in 제외 | 통과 | 정상 배치의 현재 대상 0 확인. 실제 09:00/기기 수신 미검증 |
| 인계 3단계 무알림·SNS 당시 값·서명 행위자/시각 | 통과 | 실제 저장/불변·업무 알림 증가 0 확인 |
| 간편대여 무이력·기한 후 점유·실제 QR 반납·오래된 요청 차단 | 통과 | 실제 시작/QR 반납 2회·업무 5테이블 증가 0·오래된 ID 차단. 기한 경계는 격리 |
| 직접 차량 수·비활성 하위·QR 타 지점 비공개·최근 3건 | 통과 | 본인 지점 QR·최근 3건 정렬은 실제 통과. 계층/타 지점은 격리만 |
| 실제 MySQL 중복 경합·탈퇴 담당 업무 인계 | 별도 DB 통과 | 실제 계정 탈퇴 실행 없음 |
| cc 범위·이미지 Key/Url·차량 변경·숙소 이력 | 통과 | cc 범위 조회·숙소 이력 실제 통과. 모델 이미지 명시적 확인/차량 재배정은 격리만 |

## 실제 API·S3 업무 검증

승인된 기존 테스트 지점의 대표/일반관리자와 고객, 기존 시험 QR 차량만 사용한다. 만료 보호된 시험 차량을 임의 해제하지 않고, 다른 기존 AVAILABLE 시험 차량을 확인했다. 새 차량을 만들지 않았다.

**최종 실행: 07:23:27~07:24:01 UTC, 108개 검사 기록의 기대 결과 충족.** HTTP 응답과 SQL 불변 확인 2개가 포함돼 있다. 예상 오류 응답을 포함한 수치이며 성공 응답만 108개라는 뜻은 아니다.

| 실제 실행 | 기대/실제 결과 |
| --- | --- |
| 고객 Firebase 인증→API 로그인, 대표·일반 로그인 | 성공. 승인된 계정만 사용; 세션 회수 가능 범위 사전 승인됨 |
| 사전예약 가능 차량·cc 범위·가격·신청·finalPrice 승인 | 성공. 시험 사전예약은 정상 취소 |
| 당일 1일 Walk-in 견적·신청·승인 | 성공, WALK_IN 계약으로 진행 |
| 수정안 거부·새 인계 재시작 | 승인/배정/금액 유지, 새 요청 ID로 재시작 성공 |
| 필수 폼·헬멧 0·SNS 스냅샷·숙소 이력 | 저장 성공. 프로필 SNS 변경 후 과거 인계 값 유지 |
| S3 직접 POST·실제 파일 검증·확정 복사·조회 | 4개 업로드 POST 204, 서명 GET 200 및 SHA256 4개 일치 |
| 10초/10.1초 영상 | 10초 READY, 10.1초 422 VIDEO_DURATION_EXCEEDED |
| 고객 동의·재요청 | 두 번 200. 저장 시각·고객·인계 ID 불변 확인 |
| 관리자 필수 사진·확인·담당자만 렌트 시작 | 성공. 담당자 아닌 대표는 403 HANDOVER_ASSIGNEE_REQUIRED |
| 렌트 시작 중복 차단·QR 실제 반납 | 성공, 최종 계약 RETURNED |
| 간편대여 2회 START/QR 반납·재요청/오래된 요청 차단 | 성공. 고객·예약·계약·관련 이력 5테이블 증가 0행, 최근 렌탈 목록 불변 |
| 인계 시작/폼 제출/고객 완료 3종 업무 알림 | 증가 0건 |

첫 실행은 07:17:51~07:18:19 UTC, 80개 기록 후 **러너의 시각 문자열 비교**에서 중단됐다. 첫 서명 완료 응답은 소수초를 포함하고 DB는 DATETIME(0)이라 재조회 형식이 달랐다. 앱/스키마는 바꾸지 않고 러너를 보완해 DB 시각의 실제 불변과 두 UTC 시각의 차이 1초 미만을 확인했다. **정밀도 표현 차이는 남아 있으므로 프론트는 문자열 전체 동일 여부로 중복 처리를 판단하지 않는다.** 첫 실행 자체 예약 2건만 정상 취소했다.

최종 실행의 HTTP/검사 상태 분포: 200 75개·204 4개·409 16개·422 6개·401 2개·503 4개·403 1개. **503 4개는 파일을 업로드하기 전 complete를 호출한 의도적 오류 조건 검사**의 `MEDIA_STORAGE_UNAVAILABLE`이다. 현재 객체 단위 권한에서는 없는 S3 객체의 HEAD가 403으로 숨겨질 수 있어 서버가 존재하지 않음과 권한 부족을 구분할 수 없다. 정확한 404→409 오류 변환 검증으로 표시하지 않는다. 실제 업로드 후 complete/조회는 통과했고 IAM을 확대하거나 검사/인증을 우회하지 않았다.

두 실행을 합친 시험 행 순증가: **예약 +4(취소 3·반납 1), 인계 +6, 계약 +1(RETURNED), 계약 이력 +2, 예약 이력 +13, 고객 +0**. 결제는 **13행 그대로**이며 PayPal 결제/환불 호출이 없다. 인계 취소 이력도 삭제하지 않았다.

시험 차량 최종 AVAILABLE, state_version 6, 정비/간편대여 종료일 NULL. 이번 시험의 미완료 건 **0건**. 기존 다른 회수 보호/미반납 렌트는 해제하지 않았다. 테스트 고객의 가상 서류번호·SNS 프로필은 유지했고 최초 값은 비공개 사본에 보존했다. 실제 고객 계정 삭제·데이터 일괄 초기화는 실행하지 않았다.

07:27 재검사: 마이그레이션 잔여 0, 인계 35컬럼, 저장된 인계 암호문 전부 기존 생성 키로 검사 통과, 전화번호/기존 키 불변. 예약 70·계약 23·인계 6·결제 13행. 07:31 최종 로컬/공개 health/live·ready·docs·OpenAPI **8회 200**, 새 PID 유지. API/배치 traceback·ERROR 로그 0건이며 관측 503 8건은 두 실행의 위 의도적 업로드 전 검사와 일치한다. lifecycle 반복 16회 0전환/0알림, maintenance 4회 0해제 결과를 확인했다.

## 남은 작업과 프론트 확인

- **실행한 업무 검증에서 미해결 실패는 없다.** 초회 MySQL 테스트의 구 요금 입력과 실서버 러너의 시간 정밀도 비교를 수정해 재검증했다. 서버 업무 코드 추가 수정은 없다.
- 실제 날짜/시계를 바꾸지 않았으므로 자정·09:00 경계는 격리 근거와 실제 보정 결과로 구분한다.
- 타 고객/다른 지점의 실제 로그인 검증은 별도 승인된 계정 자료가 필요하다. 격리 권한 차단 검사는 통과했다.
- 실제 정비 API·차량 재배정·계층 직접 차량 수/비활성 조회·모델 이미지 Key/Url과 이미지 GET 명시적 검증은 이번 실서버 러너에서 수행하지 않았다. 관련 격리 회귀는 통과했다. 인계 미디어 S3 GET 성공을 모델 이미지 검증으로 대신하지 않는다.
- 앱 화면·실제 서명 UI·기기 FCM·배포 callable App Check 종단은 미검증이다. 인증/App Check를 완화하지 않았다.
- 브라우저/WebView JavaScript 업로드는 웹 origin에 맞는 S3 CORS 확인이 별도 필요하다. 네이티브 HTTP 직접 업로드와 구분하며 버킷을 공개하지 않았다.
- 기존 전화번호 암호화 키 복구는 이번 분리 키 초기화로 해결한 항목이 아니다. 기존 값은 보존했다.
- 프론트 계약은 [backend-branch-feedback-handoff-2026-11-24.md](backend-branch-feedback-handoff-2026-11-24.md)를 따른다. WALK_IN·종료일 포함·finalPrice·고객 폼→영상→동의·담당자 시작·실제 QR 반납·요청 ID/상태 버전 복구를 확인한다.
- 미디어는 S3 업로드 성공 후 complete한다. 업로드 전 503을 받은 경우 상태와 업로드 결과를 먼저 확인한다. 서명 완료 시각은 DATETIME(0) 표현 차이를 고려하고 같은 인계/행위자/완료 상태로 처리한다.

## 비공개 근거

- DB·env 백업/전후 건수·암호문 보존 비교: 위 `~/.nadree-private/branch-feedback-*` 디렉터리.
- 전체/외부 격리 요약: `/tmp/nadree-branch-test-summary-20261124-j5xziqwg/result.json`.
- Firebase 소스·설정: `build/test-runtime/branch-feedback-firebase-2026-11-24/deploy-result.json`, `chat-sync-readonly-audit.json`.
- 실제 API 러너: `build/test-runtime/branch-feedback-http-runner-2026-11-24.py`, 실행 자료는 별도 700/600 비공개 디렉터리.
- 실제 API 요약/잔여 상태: `build/test-runtime/branch-feedback-http-ready-2026-11-24/sanitized-result-2026-11-24.json`, `final-readonly-state-2026-11-24.json`.
- 최종 런타임: 백업 디렉터리의 `final-runtime-evidence.json`(600).

이 문서에는 키·암호문·해시 원문·토큰·비밀번호·개인정보·S3 서명 URL을 넣지 않는다. Git 커밋·push는 수행하지 않았다.
