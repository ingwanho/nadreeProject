# 일반관리자 개인정보 요청: 첫 접수에서 렌탈 탈퇴 완료

2026-11-09 사용자 요청에 따른 후속 변경. 기준 커밋 `91d6be9` 위의 서버 로컬 수정이며 기존 메일 선택 발송 정책과 로컬 작업 기록을 보존했다.

## 처리 계약

일반관리자의 첫 정상 `POST /nadreego/admin/account-deletion-requests`는 요청을 저장한 뒤 같은 지점 대표에게 본인 승인 업무를 인계하고 렌탈 역할·Nadree 로그인 세션·채팅 접근·FCM 연결을 회수한다. **응답 전에 렌탈 탈퇴가 완료되므로 두 번째 요청이나 DELETE가 필요하지 않다.**

```json
{
  "status": "success",
  "requestAccepted": true,
  "scope": "SELF",
  "requestState": "PROCESSING",
  "accessState": "REVOKED",
  "personalDataState": "IN_PROGRESS"
}
```

위는 기존 전체 응답 중 핵심 필드다. HTTP 상태는 기존 202이며 필수 헤더·확인 토큰·영수증·응답 필드는 그대로다. SQL 개인정보·채팅 익명화, 관리자 채팅용 Auth 삭제와 보관 검토는 같은 저장 요청을 배치가 이어간다. 개인정보 정리 전체까지 첫 응답에서 완료됐다고 표시하지 않는다.

대표 SUBTREE는 기존 배치와 본인·전체 하위 지점의 미완료 업무 검사를 유지한다. 일반 인계 대상 대표를 확인하지 못하거나 외부 채팅 회수가 실패하면 SQL 인계·탈퇴를 원자적으로 롤백하고 저장 요청은 복구 대상으로 보존한다. 예약·렌트·차량·QR·결제와 상태·배정·금액을 삭제/취소/강제 종료하지 않는다. 다른 서비스의 공유 권한과 데이터도 보존한다.

## 중복·실패 복구

- 같은 키·영수증·확인 본문의 재전송은 기존 영수증을 읽기만 한다. 이미 회수된 Bearer나 Bearer 없이도 원래 영수증의 제한된 상태만 조회하며 탈퇴를 다시 실행하지 않는다. 새 키로 탈퇴를 두 번 요청하지 않는다.
- 최초 요청에서 저장된 동의가 먼저 확정되고, 그 SQL 트랜잭션이 종료된 뒤 회수 트랜잭션을 실행한다. 중간 실패나 회수 후 체크포인트 장애는 `503 DELETION_OUTCOME_UNKNOWN`으로 알리고 같은 요청을 배치가 복구한다. 실패를 접수되지 않았다는 뜻으로 추정하지 않는다.
- HTTP와 배치가 같은 요청을 동시에 회수/익명화하지 않도록 요청별 MySQL named lock을 공유한다. 잠금은 HTTP의 접수~회수~최신 응답과 배치의 처리~완료 영수증 저장 전체를 감싼다. worker는 잠금 안에서 최신 행을 다시 읽고 사용 중인 요청은 건너뛴다.
- HTTP 잠금 대기 중 다른 첫 요청이 회수한 경우에도 인증 검사 전에 영수증을 다시 조회하여 정상 멱등 재전송이 401로 바뀌지 않게 한다. 잠금 실패 응답은 `503 DELETION_REQUEST_BUSY`, requestAccepted=false다.
- 잠금 획득/해제 장애 시 SQL 연결을 무효화하여 연결 풀에 잠금이 남지 않게 한다. 기존 배치 전체의 단일 실행 잠금도 유지한다.
- 메일 성공은 여전히 필수 조건이 아니며 기록된 시도 결과를 남기고 진행한다. 기존 CONTACT_OPERATOR·범위 재확인·개인정보 검토를 임의 재개/승인하지 않는다.

## 앱 담당자 처리

1. 키·영수증·원래 확인 본문을 안전하게 보관한 뒤 POST를 한 번 호출한다.
2. SELF 응답의 accessState=REVOKED이면 관리자 인증·채팅 세션을 정리하고 탈퇴로 안내한다. 일반 업무 API의 이후 401에 대해 로그인/refresh를 반복하지 않는다.
3. 개인정보는 personalDataState가 COMPLETED가 될 때까지 원래 영수증 상태 조회로 확인한다. 로그아웃하면서 영수증까지 지우지 않는다.
4. 응답 유실·503은 같은 키/영수증으로 조회·재전송하고 새 요청을 만들지 않는다. 실제 scope/nextAction이 재확인을 요구하면 변경 범위를 다시 확인한다.

## 검증·실제 반영

**09:41 UTC / 발리 17:41 서버 반영 완료.** 새로운 DB 스키마·env·Firebase 배포는 없다. 개인정보 타이머를 잠시 중지하고 실행 중 작업이 없는 상태에서 수정·격리 검사 후 API를 재시작하고 원래 일정으로 복구했다. 실제 계정 삭제·고객 업무 변경·메일/푸시 발송을 시험하지 않았다.

| 검사 | 실제 결과 |
| --- | --- |
| 신규 흐름 우선 검사 | 11 passed. 이후 최종 검사에 포함되므로 합산하지 않음 |
| 최종 관련 격리 검사 | ec2-user, 아래 7파일 **99 passed / 1 skipped**, 실패 0, 54.94초. 기존 라이브러리 사용 중단 예정 경고 2개 |
| 범위 | 최초 POST 권한 회수·업무 인계, 순수 멱등 재조회, 실패·SQL 커밋 후 체크포인트 복구, 요청별 busy/최신 행 사용, 잠금 해제/연결 무효화, 기존 메일·권한·대표 업무·중복/범위 보호·OpenAPI |
| 격리 방식 | 임시 SQLite·메모리 Firestore/채팅·가짜 메일·가짜 MySQL 연결. 실제 서비스 DB·Firebase 자격정보·SMTP 제외 |
| 건너뜀 | 별도 폐기용 MySQL이 없어 예약 생성 대 대표 삭제의 실제 경합 검사 1개 미실행. 실제 HTTP/배치 동시 경합은 모의 검사와 구분 |
| API 재시작 | `sudo -n systemctl restart nadree-api`, **09:41:10 UTC**, PID 1610365 → 1663792, active/running |
| 개인정보 일정 | 09:41:12 UTC enabled/active 복구. 첫 자동 배치 종료 코드 0, processed=1/deferred=0/completed=0/expiredReceipts=0 |
| HTTP | 로컬·공개 각각 health/live·health/ready·Swagger·OpenAPI 모두 200 |
| 실제 OpenAPI | 일반 SELF의 첫 접수 REVOKED 설명·REVOKED/IN_PROGRESS 예시, 대표 LIMITED_TO_SETTLEMENT/NOT_STARTED 예시 확인. health 제외 78개 경로 유지 |
| 오류·보존 작업 | 재시작 이후 API 시작 완료·API/배치 오류 레코드 0. 인수·채팅 sync·채팅 retention 타이머와 crond active 유지 |

```sh
sudo -n -u ec2-user env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/test_immediate_general_withdrawal.py tests/test_deletion_notice_best_effort.py \
  tests/test_account_deletions.py tests/test_admin_rental_exit.py \
  tests/test_admin_account_deletion.py tests/test_privacy_admission_guards.py \
  tests/test_foundation.py -q -p no:cacheprovider
```

09:42 UTC 읽기 전용 확인에서 남은 요청 1건은 **배포 전 09:00:41 UTC에 접수된 기존 SELF 요청**이다. access=REVOKED, withdrawal/sql 체크포인트 완료, personalData=IN_PROGRESS, ACTION_REQUIRED/REVIEW_DATA_AND_RETENTION이다. 즉 렌탈 탈퇴는 끝났고 개인정보 보관 정책 검토가 남아 있다. 이 기존 요청 상태를 새 동기 POST의 실제 실행 시험으로 표시하지 않았다. 검토를 임의 승인하거나 요청을 재접수/삭제하지 않았다.

미검증: 새 코드에서 실제 폐기용 일반관리자의 첫 POST 왕복, 실제 HTTP와 배치의 MySQL 경합, 실제 외부 채팅/Firebase 장애 후 복구, 앱 화면·기기 로그아웃. 새로운 정책은 격리 검사와 실행 중 API/OpenAPI 반영까지 확인했으며 실제 계정을 탈퇴시켜 시험하지 않았다.

부모 정본 rental-project-master.md·rental-api-review-decisions.md가 서버에 없어 수정하지 못했으며 저장소의 업무 인계 계약과 관리자 앱 전달서를 갱신했다. 수정은 로컬 상태로 보존했고 별도 Git 커밋·push는 하지 않았다.

## 후속 승인: 이전 일반관리자 로그인으로 재시험 준비

사용자가 이전 일반관리자로 시험할 수 없으면 가능하도록 설정할 것을 승인했다. 읽기 전용 확인에서 직전 branch2 일반관리자 원본은 이미 비활성·익명화됐고 렌탈 역할·소속도 제거돼 있었다. 진행 중인 옛 개인정보 요청과 충돌하지 않도록 그 관리자 ID나 개인정보를 복원하지 않았다.

**09:52:41~09:53:00 UTC / 발리 17:53**에 승인된 동일 테스트 이메일 `nadree.test.branch2.staff@example.com`과 사용자가 앞서 지정한 테스트 비밀번호로 새 관리자 UUID를 생성했다. 같은 활성 branch2 지점에 MSP_ADMIN·일반 렌탈 ROLE·직접 manage SCOPE 각 1행, 총 3행만 하나의 SQL 트랜잭션으로 추가했다. 비밀번호는 숨김 입력 후 bcrypt로 저장했고 문서/소스/출력/결과 파일에 원문을 남기지 않았다.

- 비활성 계정을 포함한 이메일/login ID 중복 없음, 원래 지점·계약 활성·삭제 gate 없음·직접 활성 대표 1명을 확인했다.
- 기존 탈퇴 계정과 대표 계정의 전후 지문 일치, 옛 삭제 요청의 소유자·회수/SQL 정리 상태 보존을 확인했다. 예약·렌트·차량·결제·이력을 수정하지 않았다.
- 새 계정의 정상 로그인 1회 HTTP 200, 일반관리자 역할·지점 일치를 확인했다. 로컬/공개 account-deletion-context 각각 HTTP 200, SELF/canSubmitRequest=true/activeRequestId=null이다. 액세스·리프레시·확인 토큰은 출력/저장하지 않았다.
- 실제 POST 삭제 요청과 DELETE는 실행하지 않아 계정은 테스트 가능한 상태로 유지된다. 메일/푸시 발송·기존 요청 재개·서비스 재시작은 없다.
- 접근 제한된 생성 계획/결과는 `build/test-runtime/branch2-general-retest-20261109T095241Z/`에 보관한다. 생성 실패 시 커밋 전 전체 롤백하며 새 ID의 범위만 복구 대상으로 삼는다.

앱은 기존 캐시의 관리자/채팅 인증을 정리하고 같은 테스트 이메일로 다시 로그인하여 **새 관리자 ID**를 사용한다. 새 context와 요청 키·영수증으로 첫 POST를 시험한다. 옛 탈퇴 요청의 개인정보 검토와 이번 새 테스트 계정의 삭제 요청은 별개다.

## 실제 클라이언트 시험 후 읽기 전용 확인: 09:59 요청

사용자가 수행한 최근 삭제 요청을 10:05 UTC 이후 로그·Firestore·SQL·Firebase Auth로 확인했다. 이번 확인에서 새 삭제 요청·계정 변경·정책 승인·메일 발송은 실행하지 않았다.

| 실제 근거 | 확인 결과 |
| --- | --- |
| 최초 요청 | **09:59:11 UTC / 발리 17:59:11**, POST account-deletion-requests HTTP **202**. 직전 context 조회 200 |
| 진행 조회 | 09:59~10:02 UTC 동일 상태 경로 조회 HTTP 200. 확인한 구간에 추가 POST/DELETE 없음 |
| 탈퇴 | 최신 SELF 요청 accessState=REVOKED, withdrawal 체크포인트 true. 실제 SQL 계정 비활성·렌탈 역할 없음·미회수 Nadree 세션 0·FCM 없음 |
| SQL 개인정보 | sql 체크포인트 true. 실제 SQL 이메일·지점 연결 없음 |
| 채팅 | chatErased 체크포인트 1, 해당 관리자 채팅용 Auth 사용자 없음(read-only get_user 확인). providerDeletionInitiated=false이므로 실제 Auth 삭제를 새로 일으켰다고 해석하지 않음 |
| 접수 메일 | 10:01:56 UTC SMTP 전송 성공(SENT) 1건. 수신함 도착 여부는 미검증 |
| 실패·재시도 | 최근 로그에 즉시 회수/배치 실패 없음, 최신 요청 attempts=0. 10:02 배치 deferred=0 |
| 최종 개인정보 상태 | **ACTION_REQUIRED / REVIEW_DATA_AND_RETENTION**, personalData=IN_PROGRESS, completedAt=null, reviewRequired=[] |
| 대기 원인 | 기존 Firestore policy_retention 문서 없음. 회사 활성 저장소·로그·백업의 실제 보관 정책 확인 기록이 없어 최종 완료를 보류함 |

이 사례는 새 코드의 실제 첫 POST와 후속 처리를 관찰한 결과이며, 격리 검사만의 결과와 구분한다. 렌탈 탈퇴·SQL 정리는 정상 진행됐지만 개인정보 전체 완료로 표시하지 않았다. 메일 오류나 요청 재전송 부족으로 멈춘 것이 아니다. 실제 보관 정책 검토·근거를 임의로 승인하지 않았고 기존 요청을 지우거나 다시 접수하지 않았다.
