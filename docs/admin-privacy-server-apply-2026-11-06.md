# 관리자 탈퇴·개인정보 처리: 서버 적용 및 검증

2026-11-06. **08:16 UTC 실제 서버 적용 완료**: `73564d4` + 검증된 서버 차단 보완으로 컬럼 1개 적용·API 재시작·5분 자동 처리 활성화를 마쳤다. 최초 요청/처리/실패는 0건이며 실제 계정 삭제·메일 시험은 하지 않았다. [서버 적용 결과·관련 검사·미검증](admin-privacy-server-result-2026-11-06.md)를 우선한다. 아래 명령은 적용 절차 참조이며 완료된 ALTER/설치를 중복 실행하지 않는다. 이전 90일 채팅 정리 기능과 이번 개인정보 요청 기능은 별도 변경이다. 프론트 계약은 [전달 문서](frontend-admin-privacy-handoff-2026-11-06.md)를 따른다.

## 변경 범위

- 기존 `DELETE /nadreego/admin/account`의 즉시 탈퇴 응답을 유지하고 비동기 요청·조회·재확인 API 4개를 추가했다. 새 요청 진행 중에는 기존 DELETE/직원 삭제/대표 양도 등으로 같은 대상을 우회 변경할 수 없다.
- 서버 보완: 기존 DELETE의 전체 대상 검사, 상위 대표가 선택한 실제 하위 지점의 쓰기/생성 차단, 접수·재확인·운영 등록·작업의 범위 중첩 거절을 추가했다. SQL 차단 표시가 커밋되지 않아도 저장된 Firestore 요청 범위를 확인하며, 서로 다른 SELF 요청은 허용한다.
- 새 SQL 테이블은 없다. 기존 `MSP_SPOT_RENT.deletion_request_id VARCHAR(80) NULL` **1컬럼**만 추가한다. 대표 요청의 신규 예약·가입 유입을 SQL 잠금 아래 차단하는 포인터다. 완료 후에도 닫힌 지점의 포인터를 남겨 재개·재가입을 막는다. 개인정보 요청 내용이나 연락처를 이 컬럼에 저장하지 않는다.
- 작업은 기존 FCM 프로젝트의 서버 전용 `accountDeletionRequests`에 보관한다. 요청 문서·요청자 해시별 중복 방지 문서·운영 보관 정책 문서가 있다. 기존 Rules의 기본 거부가 적용되며 앱에 직접 읽기/쓰기 권한을 열지 않는다. 새 Functions·Rules·복합 인덱스 배포는 필요 없다.
- 전용 배치를 5분마다 실행한다. MySQL named lock으로 여러 서버의 동일 배치를 직렬화하고 Firestore 트랜잭션으로 같은 키·같은 요청자의 중복 접수를 막는다. 미완료는 다음 실행에서 이어 처리한다.
- 여권 업로드/조회 두 라우트의 등록 데코레이터를 주석 처리했다. 구현·저장 파일·DB 값은 보존하고 OpenAPI에서 제외한다. 별도 오류나 빈 성공 API를 추가하지 않았다. 호출 시 일반 미등록 경로의 404다. 헬스 제외 경로는 **78개**다(기존 76 + 신규 4 - 여권 2).

## 배포 전 준비

현재 서버와 동일하게 `/srv/nadree-api`, 서비스 사용자 `ec2-user`, `.env`는 `ec2-user` 소유 0600을 사용한다. 새로운 env 변수는 없다. 기존 FCM 서비스 계정에 Firestore 읽기/쓰기 및 **관리자 채팅 전용 Firebase Auth UID 삭제** 권한이 필요하다. 위치 Firebase 설정은 사용하지 않는다.

기존 `NADREE_JWT_SECRET`은 최소 32바이트이며 확인 토큰 서명·진행 중 연락처 암호화·이메일 조회 HMAC에 용도별 파생키를 사용한다. 진행 중 임의 교체하면 연락처 복호화/조회 복구가 끊길 수 있으므로 키 이전 또는 요청 정리를 먼저 수행한다. 비밀 원문을 문서/로그에 넣지 않는다.

기존 SMTP 설정으로 접수·완료 안내를 보낸다. SMTP 장애나 대상의 등록 이메일 누락을 안내 성공/삭제 완료로 처리하지 않고 같은 작업을 재시도한다. 누락·실패가 반복되면 본인 확인된 운영 복구가 필요하다. 메일 전송 직후 체크포인트 장애가 나면 안내가 중복될 수 있다. 직원의 다른 서비스 연락처를 임의 변경하지 않는다.

로그·백업·캐시·검색 인덱스·회사 export의 실제 위치와 삭제/접근 제한/복원 절차를 확인해야 한다. 이 코드가 외부 백업·로그 정책을 자동 변경하거나 검증한 것은 아니다. 정책 확인 문서가 없거나 기간이 만료되면 요청은 `ACTION_REQUIRED`에서 멈추며 거짓 완료를 반환하지 않는다.

## 서버 적용 명령

작업트리가 깨끗한 상태에서 pull한다. 로컬 변경이 있으면 먼저 보존하고 충돌을 해결한다. 실제 DB 백업과 공유 서비스 영향 확인 후 적용한다. ERD 시각화 SQL은 실행하지 않는다.

```sh
cd /srv/nadree-api
git pull --ff-only origin main
sudo -u ec2-user -H bash
cd /srv/nadree-api
.venv/bin/python -m app.migrate
```

기존 적용이 완료됐다면 이번 신규 계획은 `add MSP_SPOT_RENT.deletion_request_id`다. 그 외 계획이 있으면 누락된 이전 변경부터 확인한다. 아래 DB 이름은 실제 `.env`가 가리키는 이름과 일치시킨다. 기본 계획 명령은 읽기 전용이다.

```sh
.venv/bin/python -m app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST
.venv/bin/python -m app.migrate
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q
.venv/bin/python -m app.account_deletion_jobs
exit
sudo systemctl restart nadree-api
curl -fsS http://127.0.0.1:8008/health/ready
```

`012_account_deletion_gate.sql`은 같은 ALTER의 수동 검토용이며 마이그레이션 도구와 중복 실행하지 않는다. DDL은 MySQL에서 암묵 커밋될 수 있다. API 재시작 전에 컬럼을 적용해야 readiness 검사를 통과한다.

배치를 켜면 저장된 요청의 실제 권한 회수·익명화·메일 발송이 시작된다. 폐기 가능한 시험 계층으로 먼저 확인한 뒤 활성화한다. 기존 receipts/payments/chat-sync/chat-retention 일정은 그대로 둔다.

```sh
sudo install -m 0644 deployment/nadree-account-deletions.service /etc/systemd/system/
sudo install -m 0644 deployment/nadree-account-deletions.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nadree-account-deletions.timer
sudo systemctl list-timers nadree-account-deletions.timer
sudo journalctl -u nadree-account-deletions.service -n 50 --no-pager
```

## 단계·기한·경합

1. 현재 세션·역할·소속·동일 계약/회사 하위 범위를 잠금 아래 확인한다. 입력으로 대상 ID를 받지 않는다. 확인 토큰은 10분 유효하다.
2. Firestore에 요청과 요청자 중복 방지 문서를 원자적으로 저장한 뒤 SQL 지점 유입 차단을 기록한다. **Firestore와 SQL 전체를 하나의 트랜잭션으로 묶지 않는다.** SQL 커밋/체크포인트 실패 시 저장된 동일 요청을 배치가 복구한다. 그 간격의 신규 업무도 최종 검사에 포함한다. 커밋 불명은 `DELETION_OUTCOME_UNKNOWN`으로 조회하게 한다.
3. 대표는 REQUESTED/APPROVED 예약, 실제 진행/연체, 인계 후 미인수 회수, 환불 REQUESTED/PENDING/FAILED/잔액, 현장 결제 정산을 검사한다. 계약에 직접 연결된 환불과 예약 없는 기존 현장 대여도 포함한다. 예정일 경과만으로 완료로 보지 않는다.
4. 미완료면 `WAITING_OBLIGATIONS`: 신규 예약/현장 신청/직원 가입·승인/하위 생성·일반 변경은 차단한다. 조회, 예약 CANCEL/REJECT, 기존 반납 및 미인수 차량 회수는 기존 권한·업무 조건 아래 허용한다. 폐업 절차의 기존 의무 처리는 계약 기간 만료만으로 막지 않는다. 결제·환불 자체를 자동 실행하지 않는다.
5. 최종 범위가 달라지면 `WAITING_RECONFIRMATION`으로 멈추고 같은 요청에 새 범위를 확인한다. 자동 확대하지 않는다. 요청자 역할 자체가 사라져 본인 확인이 불가능하면 운영자가 원인을 확인해야 한다.
6. 조건 충족 시 채팅 접근 → SQL 역할·세션·FCM 회수/지점 논리 삭제 → SQL 개인정보 정리 → 채팅 본문/연결 정리 → 관리자 채팅 전용 Auth 계정 삭제 → 공용 자료·보관 정책 확인 → 완료 안내 → 완료 상태 순서다. 이미 커밋한 권한 회수는 재부팅 후 이어 처리한다.
7. 일반은 인증 접수 시점, 대표는 인증 및 업무 정리 완료 시점부터 **7일**. 재시도·재확인·수동 재개로 기존 기한을 연장하지 않는다. 5회 실패 또는 기한 초과는 운영자 확인 상태와 오류 로그를 남긴다. 실제 운영 경보 수집은 이 서비스 로그를 모니터링에 연결해야 한다.

## 실제 데이터 처리 목록

| 저장 위치 | 자동 처리 / 보존 기준 |
| --- | --- |
| `MSP_ADMIN_ROLE` | 대상의 렌탈 대표/일반 역할 제거. 다른 서비스 역할 보존 |
| `MSP_REFRESH_TOKEN` | Nadree 서비스 표시 세션 폐기 후 삭제. 다른 활성 서비스 세션 보존 |
| `MSP_ADMIN` | FCM 해제. 다른 활성 역할/다른 서비스의 유효 세션이 없으면 이름·이메일·전화·MFA·소속·최근 로그인 제거, 로그인/비밀번호 불가역 대체·비활성화. 참조 무결성을 위해 식별 행 자체는 남김 |
| `MSP_ADMIN_SPOT_SCOPE` | 다른 서비스 관계가 없으면 대상 scope 제거. 대상이 부여한 `granted_by` 연결은 NULL |
| `MSP_RENTAL_ADMIN_REQUEST` | 대상 가입 신청 삭제. 남아야 할 다른 신청의 reviewer는 개인과 무관한 공용 비활성 익명 행으로 치환하여 상태 CHECK 유지 |
| `MSP_VEHICLE_STATUS`, `MSP_VEHICLE_QR_HISTORY`, `MSP_RESERVATION_HISTORY`, `MSP_RENTAL_CONTRACT_HISTORY` | 대상 `changed_by` NULL. 차량/예약/계약 상태·시각·이력 보존 |
| `MSP_RENTAL_PAYMENT` | `refund_requested_by_admin_id`, ADMIN 유형의 `cancellation_requested_by_id` NULL. 고객 취소자·금액·환불률·거래/판매자 ID·결제 이력 보존 |
| 예약 `required_criteria_json`, 예약 이력 `details` | 알려진 관리자 ID 키 및 ADMIN 취소자 연결 제거. 고객 UID·업무 사실은 보존 |
| 대표 대상 `MSP_SPOT_RENT` | 연락 이메일·소개·상세주소·길안내·초대코드·현재 PayPal 연결값 제거. 과거 결제 판매자 스냅샷 보존 |
| `MSP_SPOT_MASTER`, `MSP_ORG/REGION/LOCAL/SPOT` | 대상 지점 비활성화. 공용 사업장 주소/전화·고객 계약 스냅샷·공유 생성자 참조는 소유 서비스와 실제 필요성 검토 대상으로 추적 |
| Firestore `chatRoomAccess/*/messages` | 본인이 보낸 메시지 내용/식별정보 제거, sender를 비식별 공용 값으로 치환. 메시지 ID·순번·시각을 유지해 읽음/중복 계약 보존 |
| 채팅 reads/members/푸시 이벤트/토큰/`chatUsers` | 본인 연결 제거. 본인 발송 이벤트의 발신자 제거·재전송 중단. 타인 이벤트의 본인 수신자 연결 제거 |
| Firebase Auth | `nadree-admin-<관리자 ID 해시>` 전용 채팅 UID만 삭제. 고객 UID와 다른 서비스의 공통 로그인 계정을 삭제하지 않음. 실제 존재·삭제 확인 시에만 공급자 잔여 사본 안내 |
| 공용 자유문·타인 채팅의 이름/이메일/전화 언급 | 발견 시 `ACTION_REQUIRED`. 다른 사람의 글을 일괄 삭제하거나 접근 차단만으로 삭제 완료라 하지 않음. 담당자가 정리/정당한 보관 범위 확인 |
| 고객 계정·차량/QR/센서·예약/계약/거래 | 본 요청으로 일괄 삭제하지 않음 |
| 개인 기기 여권 사진 | 이번 원격 삭제 대상 아님. 서버 여권 API도 등록 중단 |

공용 식별 정보 보존은 실제 다른 활성 역할/세션 확인에만 적용하며 `COMPLETED_WITH_RETENTION`에 항목·목적·사유·보관 기준을 고지한다. 서비스명/법적 근거는 운영 검토가 필요하고 코드의 기술 분류가 법적 근거 확정은 아니다. 추가 보관은 담당자가 항목·목적·근거·기한·사유를 모두 기록해야 한다.

## Firestore 기록의 수명

진행/실패 중에는 연락처 암호문·대상 스냅샷·체크포인트를 복구에 필요한 동안 보존한다. 완료 후에는 원본 이름·이메일·전화·연락처 암호문·대상 관리자/지점 목록·요청자 ID를 없앤다. 영수증/요청 본문 해시·이메일 HMAC·건수·상태/시각·보관 고지·검증 증거 해시만 **완료 후 30일** 보관한 뒤 배치로 삭제한다. 지점의 차단 포인터는 식별값 없는 요청번호만 남는다.

미완료 문서에는 TTL을 설정하지 않는다. 완료 영수증을 지워서 실패 작업을 잃지 않는다. 원본 영수증 비밀값은 저장하지 않는다. 원본 이메일은 HMAC에서 복구할 수 없다. 비밀값 회전은 기한을 연장하지 않는다.

완료 후 복원용 개인 대상 목록을 별도 보관하는 기능은 추가하지 않았다. 따라서 **과거 백업의 개인별 자동 재삭제 및 실제 복원 시 재노출 방지 검증은 완료하지 않았다.** 복원 전 공개 접근을 닫고, 현재 데이터의 삭제 상태와 삭제 대상 개인정보를 포함하지 않는 복원 범위/재정리 절차를 담당자가 검증한 뒤 재개한다. 이를 보장할 운영 절차가 없으면 아래 정책 확인을 실행하지 않는다.

## 운영자 처리 명령

공개 삭제 우회 API는 없다. 본인 확인된 이메일 대체 접수/분실 복구/외부 정산/자료 검토를 서버 운영자가 같은 요청에 연결한다. `--operator`와 **실제 확인 증거 파일**이 필수다. 이메일·영수증·검토 보고서는 0600 파일로 전달하며 셸 인자/URL/로그에 원문을 넣지 않는다. `inspect`는 연락처를 출력하지 않고 검토 분류·체크포인트만 보여준다. 작업 후 입력 파일도 안전하게 정리한다.

아래는 사용 형태이며 경로·값을 확인한 후 `ec2-user` 셸에서 실행한다. 확인하지 않은 사실을 문구만 작성해 승인하지 않는다.

```sh
.venv/bin/python -m app.account_deletion_ops inspect --request-id REQUEST_ID --operator OPERATOR --evidence-file /private/path/evidence.txt
.venv/bin/python -m app.account_deletion_ops lookup --verified-email-file /private/path/email.txt --operator OPERATOR --evidence-file /private/path/evidence.txt
.venv/bin/python -m app.account_deletion_ops register --admin-id VERIFIED_ADMIN_ID --idempotency-key SAVED_RANDOM_KEY --verified-email-file /private/path/email.txt --receipt-file /private/path/receipt.txt --operator OPERATOR --evidence-file /private/path/evidence.txt
.venv/bin/python -m app.account_deletion_ops rotate-receipt --request-id REQUEST_ID --verified-email-file /private/path/email.txt --receipt-file /private/path/new-receipt.txt --operator OPERATOR --evidence-file /private/path/evidence.txt
.venv/bin/python -m app.account_deletion_ops settlement --request-id REQUEST_ID --operator OPERATOR --evidence-file /private/path/settlement-proof.txt
.venv/bin/python -m app.account_deletion_ops review --request-id REQUEST_ID --report-file /private/path/review.json --operator OPERATOR --evidence-file /private/path/evidence.txt
.venv/bin/python -m app.account_deletion_ops resume --request-id REQUEST_ID --operator OPERATOR --evidence-file /private/path/recovery-proof.txt
```

`register`는 운영자가 등록 이메일의 본인 확인과 최신 삭제 범위를 안내·확인한 경우에만 실행한다. 이미 진행 중이면 그 요청을 반환한다. `lookup`이 반환한 requestId와 원래 앱의 Idempotency-Key 연결이 필요한 경우 요청 문서 ID는 `adr_ + SHA256(원래 키)`다. 원래 키도 분실했다면 운영 도구로 조회해 안내하며 새 접수·새 계정 생성을 강제하지 않는다. 회전된 영수증으로 앱 조회하려면 원래 키도 필요하므로 키를 잃은 경우 운영자 조회 경로를 사용한다.

`review.json`에는 `reviewedCategories`에 inspect의 모든 검토 분류를 넣고, 실제로 남겨야 하는 정보가 있다면 `retainedData` 배열에 `category/fields/purpose/retentionBasis/retentionUntil/reason`을 명시한다. 검토 명령 자체가 공용 자료를 자동 삭제하는 것은 아니다. 실제 정리 또는 필요 보관 분류를 완료한 뒤 기록한다.

외부 정산 증거는 실제 현장 수납/환불·회수 완료 확인용이며 다른 의무가 남으면 거절된다. 수동 재개는 기한을 초기화하지 않는다. 로그/제한 백업 각각 최대 30일과 활성 시스템의 캐시·검색·export·공유 참조 및 복원 방지 절차를 **실제로 검증한 후에만** 아래를 실행한다. 확인 유효기간은 30일이며 만료 시 다시 검토한다.

```sh
.venv/bin/python -m app.account_deletion_ops policy --operator OPERATOR --evidence-file /private/path/verified-retention-controls.txt --log-days 30 --backup-days 30
```

## 검증·장애 복구

2026-11-06 로컬 결과:

- 최종 전체 격리 회귀 **642 passed / 20 skipped**, 실패 0. 등록 이메일 누락을 알림 성공으로 세지 않는 검사와 대표 접수/예약 동시성 MySQL 전용 검사를 포함한다. 별도 관련 검사도 **50 passed**다.
- 별도 실제 Firestore SDK 에뮬레이터 **8 passed**: 동시 접수/요청자 중복 방지, 완료 시 영수증 회전 유지, 만료 정리, 메시지 익명화 및 기존 채팅 계약.
- 전체 실행에서 생략된 20개는 에뮬레이터 8개와 전용 MySQL 12개다. 에뮬레이터 8개는 위 별도 실행으로 통과했다. MySQL 12개는 로컬 연결이 없어 실행하지 않았다. 새 동시성 검사는 `tests/test_account_deletions.py::test_mysql_reservation_racing_with_primary_deletion_is_blocked_or_included`이며 비어 있는 폐기용 `nadree_w02_test_*` DB만 사용하도록 기존 보호 장치를 따른다.
- 일반/대표·정산 대기·재확인·중복·응답 유실·체크포인트 장애 복구·영수증 회전·타 서비스 보존·정책 미확인 시 미완료·30일 만료·여권 미등록을 격리 데이터로 확인했다. 기존 테스트 환경 경고 14개(라이브러리 폐기 예정 2개 및 Google Auth 테스트 전송 객체 정리 12개)는 남아 있다.
- 파이썬 구문, 새 문서 링크, OpenAPI 상태별 예시·인증, API 엑셀 4시트/통합표, DB 엑셀·시각화 SQL의 1컬럼을 확인했다. 시각화 SQL이나 실제 마이그레이션은 실행하지 않았다.

로컬 전체 결과는 최종 검증란에 기록한다. Firestore는 `demo-nadree-chat` 에뮬레이터와 익명 자격증명으로만 시험했고 실제 메일/FCM/Auth 삭제나 운영 DB 변경은 실행하지 않았다. 실제 MySQL 경합·실제 권한/SMTP/앱 왕복·외부 자료/백업 복원 시험은 서버에서 승인된 폐기 계층으로 확인해야 한다.

문제가 있으면 `sudo systemctl stop nadree-account-deletions.timer`로 신규 배치를 멈추고 같은 Firestore 요청의 상태·SQL 마커·외부 처리를 대조한다. 실행 중인 작업은 별도로 확인한다. 요청 문서/마커를 지우거나 이전 계정을 재활성화하지 않는다. 이미 익명화한 개인정보는 코드 롤백으로 복구되지 않는다. 새 코드의 복구 후 `resume`으로 이어 처리한다. 컬럼은 구버전 코드와 공존 가능하므로 다운 마이그레이션으로 제거하지 않는다. 진행 중에는 새 API를 모르는 구버전으로 되돌려 닫는 지점의 유입 차단을 우회하지 않는다.

프론트 공동 인수는 일반 1회 접수→회수→완료, 대표 하위 경계 보존, 대기 중 신규 차단/기존 업무 처리, 범위 재확인, 같은 키/다른 기기 중복, 접수 응답 유실 후 영수증 조회, SQL/Firestore/SMTP 실패, 다른 서비스 보존, 영수증 분실 운영 복구를 포함한다. 요청안 9절의 고객 정보 90일 정리 등 별도 정책 제안은 이번에 임의 적용하지 않았다.
