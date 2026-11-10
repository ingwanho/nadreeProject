# 개인정보 삭제 안내 메일: 시도 결과 기록 후 계속 진행

> 최신 상태: 사용자 추가 승인으로 **08:56 UTC** 기존 branch2 일반관리자의 미실행 실패 요청·owner 연결 2문서를 접근 제한 백업 후 제거했다. 아래 08:31의 CONTACT_OPERATOR 보존 기록은 당시 상태이며, 새 접수 준비 결과는 마지막 절을 따른다.

2026-11-09 사용자 확정 변경. 기준 코드는 `91d6be9`이며 이번 변경은 서버 로컬 수정이다. 이전 DELETE 중복 차단 해제는 원복한 상태를 유지한다.

## 변경 동작

접수·완료 안내 메일은 발송을 시도하되 성공 여부를 탈퇴·개인정보 정리의 필수 조건으로 보지 않는다.

| 메일 결과 | 기록 | 다음 처리 |
| --- | --- | --- |
| SMTP 발송 성공 | SENT / sentCount | 계속 진행 |
| SMTP 설정·연결·인증·발송 오류 | FAILED / failedCount / 안전한 오류 코드 | 계속 진행 |
| 등록 이메일 없음 | SKIPPED / skippedCount / DELETION_NOTIFICATION_CONTACT_REQUIRED | 계속 진행 |
| 결과 체크포인트 저장 실패 | 기존 삭제 작업의 저장 오류/재시도 처리 | 영속 진행 기록을 보장하도록 기존 처리 유지 |

메일 실패 자체로 일반 삭제 작업의 RETRYING 횟수를 늘리거나 CONTACT_OPERATOR로 전환하지 않는다. 접수와 완료는 별도 단계이며, 저장된 단계·대상별 시도 결과는 다음 배치에서 다시 발송하지 않는다. SMTP 발송 직후 체크포인트 저장이 실패하면 외부 발송과 저장을 하나의 트랜잭션으로 묶을 수 없어 같은 메일이 재발송될 가능성은 남는다.

일반관리자의 같은 지점 대표 업무 인계, 대표관리자의 본인·모든 하위 지점 미완료 업무 검사, 본인 인증·권한·중복 방지·범위 재확인·개인정보 보관 검토는 유지한다. 미완료 업무나 보관 검토 실패를 메일 실패처럼 무시하지 않는다. 임시 비밀번호 등 다른 메일 기능의 성공/실패 계약도 변경하지 않았다.

## 기록·개인정보

- 기존 요청의 notificationResults.received / notificationResults.completed에 sentCount·failedCount·skippedCount·lastAttemptAt·errorCodes를 남긴다. lastAttemptAt은 시도/건너뜀 처리 시각이며, 기존 성공 목록만 있는 과거 기록의 시각은 알 수 없어 null로 유지한다.
- 성공 목록 receivedNotified/completionNotified와 별도로 성공·실패·건너뜀을 포함한 시도 체크포인트를 남긴다. 기존에 발송 성공한 대상은 재발송하지 않는다.
- 로그에는 요청번호·단계·결과·허용된 오류 코드만 기록한다. 수신 이메일·비밀번호·토큰·SMTP 예외 원문은 기록하지 않는다.
- 완료 영수증에는 개인별 체크포인트를 제거하고 집계 결과만 남긴다. 완료 영수증의 기존 30일 만료는 유지한다.
- 운영 도구 account_deletion_ops의 inspect로 notificationResults를 확인할 수 있다. 공개 API 경로·본문·응답 필드는 변경하지 않았다. 프론트는 메일 수신 여부 대신 기존 영수증 상태 조회로 완료를 판단한다.

## 적용·검증

개인정보 타이머만 잠시 중지하고 실행 서비스가 종료된 상태에서 수정·격리 검사를 진행했다. 기존 결제·인수·채팅 작업의 설정은 변경하지 않았다. 최종 검사와 타이머 복구 결과는 아래에 기록한다.

| 확인 항목 | 결과 |
| --- | --- |
| 관련 최종 격리 검사 | ec2-user, 5파일 **75 passed / 1 skipped**, 실패 0, 45.19초. 건너뜀은 별도 폐기용 MySQL 경합 환경 부재 |
| 신규 검증 | 메일 설정/발송 오류·완료 메일만 실패·주소 누락에도 정상 정리, 일반 업무 인계·대표 미완료 차단, 기록된 결과 재발송 방지, 비밀값 미누출, 저장 장애 재시도, 기존 CONTACT_OPERATOR 유지 |
| 이전 성공 기록 | 발송 시각 없는 과거 성공 목록을 재발송하지 않고 lastAttemptAt=null로 유지. 최초 검사의 시각 기대 1건을 이 계약에 맞게 수정한 뒤 같은 관련 범위를 최종 재검증 |
| 격리 방식 | 실제 서비스 DB·Firebase 자격정보·SMTP를 제외한 임시 SQLite·메모리 저장소·가짜 채팅/메일 사용 |
| 타이머 복구 | **08:31:12 UTC / 발리 16:31:12**, enabled/active 복구. 첫 자동 배치 08:31:15 종료 코드 0 |
| 첫 배치 집계 | processed=1, deferred=0, completed=0, expiredReceipts=0, 신규 실패 로그 0. 기존 운영자 대기 요청을 건너뛴 것이므로 삭제 성공으로 계산하지 않음 |
| 기존 요청 보존 | SELF 1건, ACTION_REQUIRED/CONTACT_OPERATOR·attempts=5·updatedAt=03:55:43 UTC 그대로. access=PENDING/personalData=NOT_STARTED. 수동 재개·삭제 없음 |
| 기존 서비스 | API PID 1408497·active/running 유지. 인수·채팅 sync·채팅 retention 타이머와 crond active 유지 |
| 실제 HTTP | 로컬/공개 health/live·health/ready 4건 모두 200 |

```sh
sudo -n -u ec2-user env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/test_deletion_notice_best_effort.py tests/test_account_deletions.py \
  tests/test_admin_rental_exit.py tests/test_admin_account_deletion.py \
  tests/test_privacy_admission_guards.py -q -p no:cacheprovider
```

기존 branch2 일반관리자의 5회 실패 CONTACT_OPERATOR 요청은 이번 정책만으로 자동 재개하지 않는다. 요청을 삭제하거나 기한·업무·계정 상태를 임의 변경하지 않는다.

DB 스키마·env 수정·Firebase 배포는 없다. 변경 파일은 독립 실행 배치와 운영 CLI이므로 API 재시작은 필요하지 않으며, 개인정보 배치의 다음 실행부터 새 코드가 로드된다.

부모 정본 rental-project-master.md·rental-api-review-decisions.md는 이 서버에 없어 수정하지 못했다. 저장소의 개인정보 실행서와 프론트 전달서를 함께 갱신했다.

미검증: 실제 삭제 요청에서의 메일 실패 후 SQL/Firebase 개인정보 정리 종단, 실기기 앱 왕복, MySQL 동시성. 이번에는 실제 탈퇴·관리자 Auth 삭제·메일/푸시 발송을 시험하지 않았다. 기존 5회 실패 요청을 이 정책으로 실제 처리하려면 해당 요청에 대한 별도의 재개가 필요하다.

## 추가 승인: 기존 실패 요청만 제거하여 새 접수 준비

사용자가 최근 실패 확인 후 “이전 API 기록을 지워 새로 가능하게” 요청했다. **08:56:20~08:56:24 UTC / 발리 16:56**에 다음을 실행했다. 원래 요청의 접수·수정 시각, 요청번호 suffix, SELF 범위·계정·지점, CONTACT_OPERATOR/5회 실패 및 미실행 상태를 고정 검증했고 변경된 요청이면 중단하도록 했다.

- 변경: 해당 Firestore request 1개와 owner 연결 1개만 문서 버전 비교 후 원자 삭제. 삭제 후 두 문서 부재와 active_request=false, pending_scope_clear=true, 새 접수 가능 상태를 확인했다.
- 백업: protobuf 타입 보존·역직렬화 일치·SHA256 검증. 복구 자료는 `build/test-runtime/staff-self-request-reset-20261109T085620Z/`의 0700 디렉터리·0600 파일에 보관했다. 원본 연락처/비밀값은 문서나 출력에 남기지 않았다.
- SQL 변경 0, 계정 탈퇴 0, 역할/세션 변경 0, 메일/푸시 0. 계정·권한·세션·지점·예약·렌트·차량·QR·결제 및 관련 이력의 전후 지문 일치를 확인했다. SELF 업무 카운터의 정책상 0을 전체 지점 업무가 없는 증거로 사용하지 않았다.
- 기존 SQL 지점 gate는 원래 null이며 그대로 보존했다. `.env`와 기존 배치 설정·API PID 1610365도 변경하지 않았다. 개인정보 타이머만 중지/드레인·SQL 작업 잠금을 거친 뒤 원래 enabled/active로 복구했다.
- 로컬/공개 health/live·health/ready 모두 200. 실제 API 로그인·삭제 요청 재호출·계정 삭제 시험은 하지 않았다.

앱은 이전 요청 상태/영수증 대신 새 context 확인 토큰, 새 Idempotency-Key와 새 Deletion-Receipt-Token으로 접수한다. 삭제한 옛 영수증의 상태 조회는 404가 될 수 있다. 다음 요청 때 현재 인증·역할·삭제 범위·미완료 업무를 정상 검사한다. 요청 상태를 읽을 때 Firestore를 조회하므로 이 정리에 API 재시작은 필요하지 않다.
