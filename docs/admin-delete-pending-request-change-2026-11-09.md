# 관리자 본인 DELETE 변경·원복 및 SMTP 설정 반영

> **최신 상태 — 2026-11-09 04:00:52 UTC / 발리 12:00:52:** 사용자 후속 지시로 아래 DELETE 중복 차단 해제와 연결 보완을 전부 원복했다. 현재 코드는 `91d6be9`의 중복·진행 중 요청·SQL gate 보호를 유지한다. SMTP 설정 수정·인증 확인과 원복 후 검사·재시작 결과는 문서 마지막 절을 따른다. 아래 03:42 배포 및 79개 검사 기록은 원복 이전 이력이다.

2026-11-09. 기준 커밋 `91d6be9` + 이번 로컬 코드 수정으로 사용자 최종 지시 **DELETE 경로만 변경**을 반영했다. 로컬 수정과 기존 서버 작업 기록은 보존했다. 사용자 후속 재시작 지시에 따라 **03:42:28 UTC / 발리 11:42:28 API 재시작·서버 반영 완료**, 최종 확인은 03:43 UTC다. 이번 변경을 별도 Git 커밋으로 생성하지 않았다.

## 변경 계약

`DELETE /nadreego/admin/account`의 Bearer 인증·본문 없음·200 성공 응답은 유지한다.

| 항목 | 이번 동작 |
| --- | --- |
| 일반관리자 | 본인이 승인한 진행 중 예약·렌트를 같은 지점 대표에게 인계한 후 본인만 렌탈 탈퇴 |
| 대표관리자 | 본인 지점과 모든 하위 지점의 미완료 예약·대여·반납·회수·환불·외부 정산을 검사. 남아 있으면 `409 DELETION_OBLIGATIONS_REMAIN` |
| 기존 개인정보 요청 | 본인·대상 직원의 접수/재시도/운영 확인 상태만으로 DELETE를 거절하지 않음 |
| SQL 삭제접수 표시 | 활성 지점의 `deletion_request_id`만으로 DELETE를 거절하지 않음. 기존 표시를 임의 초기화하지 않음 |
| 권한·범위 | 현재 세션·렌탈 역할·직접 manage·활성 지점·계약·동일 회사/계약/계층 경계를 계속 검증 |
| 동시성 | 기존 지점·계층·계정 SQL 잠금과 최종 세션 재검사를 유지 |
| 보존 | 예약·렌트·차량·QR·결제·반납 상태와 이력은 취소/삭제/강제 종료하지 않음. 업무 인계 이력만 기존 계약대로 추가 |

인계할 업무가 있는데 같은 지점 활성 대표를 확인할 수 없으면 기존 `PRIMARY_ADMIN_REQUIRED_FOR_HANDOVER`를 유지한다. 인계나 채팅 회수 실패 시 SQL 탈퇴와 인계 이력은 함께 롤백한다. 성공한 계정의 렌탈 역할·Nadree 로그인 세션·채팅 접근·FCM 연결을 회수한다. 다른 서비스의 공유 계정·권한은 보존한다.

DELETE는 개인정보 요청의 저장소를 조회하거나 요청 문서를 삭제하지 않는다. `POST /nadreego/admin/account-deletion-requests`와 영수증·중복 접수·재확인·메일·운영 확인·보관 정책은 그대로다. 따라서 **DELETE의 `deleted=true`는 렌탈 탈퇴이며 개인정보 완전 삭제 완료가 아니다.**

## 앱 담당자에게

1. 기존 관리자 Bearer로 본문 없이 DELETE를 요청한다. 사전에 개인정보 POST를 보낼 필요는 없다.
2. 일반관리자는 진행 업무가 대표에게 인계된 후 본인 탈퇴로 안내한다.
3. 대표에게 `DELETION_OBLIGATIONS_REMAIN`이 반환되면 기존 context의 미완료 항목을 처리한다. 계정·세션은 유지된다.
4. 200·`deleted=true`를 받으면 해당 앱의 관리자 인증·채팅 세션을 정리한다. 삭제 뒤 같은 토큰 재요청의 401만으로 성공을 추정하지 않는다.
5. 이미 개인정보 요청을 접수했다면 기존 영수증을 보관한다. DELETE 성공만으로 개인정보 요청을 COMPLETED로 표시하거나 새 요청 문서를 만들지 않는다. CONTACT_OPERATOR·범위 재확인·보관 검토는 기존 계약을 따른다.

## 기존 개인정보 배치와의 연결

동기 DELETE가 먼저 역할을 회수한 경우 기존 개인정보 요청의 후속 배치가 `capture` 권한 검사에서 실패하지 않도록 이미 완료된 렌탈 탈퇴 상태만 인식하는 보완을 포함했다. SQL 잠금 아래 원본 계정·지점·계약·계층, 렌탈 역할 행의 실제 제거, Nadree 세션 전부 회수, FCM 연결 제거를 확인한다. SUBTREE는 원본 지점 전부가 비활성이어야 한다. 역할 만료나 역할 행만 사라진 상태를 탈퇴 완료로 추정하지 않는다.

이 인식 뒤에도 기존 업무 검사·멱등 인계·채팅/세션/FCM 회수와 개인정보 검토 정책을 적용한다. 일반이 먼저 탈퇴하여 대표 요청의 일부 범위만 달라진 경우 기존 범위 재확인을 유지한다. `CONTACT_OPERATOR`를 자동 재개하거나 메일·개인정보 검토 실패를 완료로 바꾸지 않는다. 기존 요청 문서·SQL 포인터를 삭제/초기화하지 않았다.

## 격리 검증

- 초기 관련 격리 검사: ec2-user, 4파일 **51 passed**, 실패 0. 기존 라이브러리 사용 중단 예정 경고 2개.
- 최종 관련 검사: 아래 5파일 **79 passed / 1 skipped**, 실패 0, 46.66초. 초기 51개를 포함한 최종 재실행으로 두 수치를 합산하지 않는다.
- 건너뜀 1개: 별도 폐기용 MySQL URL이 없는 예약 생성 대 대표 탈퇴 경합 검사. SQLite/메모리 결과를 실제 MySQL 경합 통과로 표시하지 않는다.
- 통과: 일반 RETRYING/ACTION_REQUIRED 요청 보존 중 본인 탈퇴, 대표 삭제접수 표시 중 일반/대표 탈퇴, 대표 미완료 업무 거절, 진행 중 예약·렌트 인계와 업무 상태 보존, 인계 이력 중복 없음, 인증 누락 차단, 지점 비활성·계약 만료 차단, 개인정보 요청 저장소 장애와 DELETE 분리, DELETE 후 기존 SELF/SUBTREE 배치 연결, 만료 역할/잔여 세션/FCM을 완료로 오인하지 않음.
- 실제 서비스 DB·Firebase 자격정보를 사용하지 않고 임시 SQLite와 메모리 어댑터로 검사했다.
- 검사 시 실제 계정 DELETE·개인정보 재개·SMTP/푸시·Firebase 배포·DB/env 변경은 실행하지 않았다.
- 부모 정본 `/srv/rental-project-master.md`, `/srv/rental-api-review-decisions.md`는 이 서버에 없어 수정하지 못했으며 저장소 내부의 관련 계약·앱 전달서를 갱신했다.

```sh
sudo -n -u ec2-user env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/test_admin_delete_pending_requests.py \
  tests/test_admin_account_deletion.py tests/test_admin_rental_exit.py \
  tests/test_privacy_admission_guards.py tests/test_account_deletions.py \
  -q -p no:cacheprovider
```

## 실제 서버 확인

| 검사 | 실제 결과 |
| --- | --- |
| 재시작 | `sudo -n systemctl restart nadree-api`, 종료 코드 0, 03:42:28 UTC |
| API 실행 | ec2-user, `/srv/nadree-api`, PID `1337651 → 1390664`, active/running, Result=success, NRestarts=0 |
| 로컬 HTTP | `http://127.0.0.1:8008`의 `/health/live`, `/health/ready`, `/docs`, `/openapi.json` 모두 200 |
| 공개 HTTP | `https://na-dree.com`의 동일 4경로 모두 200 |
| 변경 반영 | 양 OpenAPI에서 본인 DELETE·200 응답 및 기존 개인정보 요청으로 거절하지 않는 새 설명 확인 |
| 오류 로그 | 재시작 이후 03:43 UTC까지 시작 완료 확인, 오류 레코드 0. 원문 출력/문서 저장 없음 |
| 기존 작업 | account-deletions·receipts·chat-sync·chat-retention 타이머 active, crond active. 일정·작업 설정 변경 없음 |
| 환경 파일 | 실제 서버 ec2-user:ec2-user, 600 보존. 값 수정/출력 없음 |

미검증: 실제 폐기용 계정으로 DELETE→앱 로그아웃 왕복, 실제 MySQL 동시성·채팅 회수·Firebase Auth/메일/개인정보 완료. 실제 테스트 계정도 이번에는 삭제하지 않았다. 앱은 본문 없는 본인 DELETE로 바로 테스트할 수 있으나, 기존 비동기 요청의 완료 표시는 영수증 조회 결과를 따른다.

## 후속 읽기 전용 진단: 기존 요청 RETRYING (03:53 UTC)

사용자의 실패 로그 확인 요청에 따라 실제 요청 상태와 02:55 UTC 이후 개인정보 배치/API 로그를 대조했다. 요청 재개·삭제·설정 변경·API 추가 재시작은 하지 않았다.

- 남은 비동기 요청은 1건이며 기존 branch2 일반관리자의 SELF 요청이다. PrmBali 대표 요청이 아니다.
- 03:10:38 UTC 접수, 03:13:53·03:19:14·03:24:32·03:34:58 UTC에 `Problem`으로 총 4회 실패했다. 03:51 조회 당시 RETRYING, 다음 시도 예정은 03:50:47 UTC였지만 03:50 배치 실행 시각이 그보다 빨라 건너뛴 상태다. 배치의 success/processed=1이 삭제 성공을 의미하지 않는다.
- 미완료 업무 6종 모두 0, `steps={}`, phase 없음, 접수 메일 완료 체크포인트 0, access=PENDING/personalData=NOT_STARTED. 해당 계정의 일반 렌탈 역할이 남아 있어 실제 탈퇴는 아직 완료되지 않았다.
- 연락처 복호화 성공·이메일 존재·SMTP 필수 설정 존재를 확인했다. 이름/주소/암호문/계정 비밀번호는 출력하지 않았다.
- 현재 SMTP 전송 설정은 **465 + starttls**다. 동일 서버·포트에서 메일 발송/인증 없이 연결을 비교했을 때 현재 평문 접속 후 STARTTLS 방식은 `SMTPServerDisconnected`로 실패했고, implicit TLS 방식은 인증서 검증 및 EHLO **250**으로 성공했다. 코드상 이 연결 예외는 `MAIL_UNAVAILABLE`로 변환된다. 기존 로그에는 예외 클래스만 있어 과거 개별 시도의 SMTP 세부 응답은 남아 있지 않다.
- 배치는 접수 안내 메일을 필수 발송한 후 업무 인계/탈퇴를 시작하므로, 현재 연결 설정 오류가 첫 단계 진행을 막는다. 남아 있는 Firestore 문서 자체나 미완료 업무/DELETE 중복 차단이 원인은 아니다.

필요한 설정 수정은 `NADREE_SMTP_TLS=ssl`이며 현재 465 포트는 유지한다. 이번 진단에서는 수정하지 않았다. API 프로세스에는 재시작으로 반영하고, 개인정보 배치는 실행 시 새 설정을 읽는다. 5회째 실패로 CONTACT_OPERATOR가 되었다면 설정 수정만으로 자동 재개되지 않으므로 해당 기존 요청의 상태를 확인한 뒤 승인된 복구 절차를 적용해야 한다. 메일 계정 인증과 실제 발송 성공은 이번 연결 검사에서 검증하지 않았다.

## 최종 후속 적용: 중복 차단 원복·SMTP 인증 및 재시작

사용자는 SMTP 발신 계정 반영을 요청했고, 이어 연결 설정이 원인이면 중복 관련 코드를 복구하도록 지시했다. 이에 다음만 적용했다.

| 적용 항목 | 실제 결과 |
| --- | --- |
| DELETE 원복 | `app/management.py`, `app/security.py`, `app/account_deletion_jobs.py`를 `91d6be9` 내용으로 정확히 복구. 개인정보 요청 진행 중·범위 중첩·지점 gate 검사와 기존 배치 동작 복구 |
| 보존한 업무 정책 | 일반은 본인 승인 미완료 업무를 같은 지점 대표에게 인계, 대표는 본인·전체 하위 미완료 업무가 있으면 탈퇴 차단 |
| 테스트·전달서 | 기존 privacy admission 검사를 원복하고 철회한 DELETE 전용 검사를 제거. 이번에만 바꿨던 계약/프론트 문서 3개도 원복. 원래 로컬 README·서버 기록은 보존 |
| SMTP env | 전달받은 발신/로그인 계정과 비밀번호를 `NADREE_SMTP_FROM`, `NADREE_SMTP_USER`, `NADREE_SMTP_PASSWORD`에 반영. `NADREE_SMTP_TLS=ssl`, `NADREE_SMTP_PORT=465`. 기존 host 유지 |
| 비밀 취급 | 숨김 입력으로 인증·반영. 비밀번호를 코드/문서/명령 인자/결과 로그에 넣지 않음. 다른 env 값·ec2-user 소유권·600 권한 보존, 중복된 수정 대상 설정 정리 |
| 실제 SMTP 검사 | TLS 인증서 검증·EHLO 250·SMTP 인증 **235 성공**. 수신자 지정·메일 발송 없음 |
| 관련 격리 검사 | ec2-user, 기존 탈퇴·업무 인계·privacy admission·개인정보 요청 4파일 **63 passed / 1 skipped**, 실패 0, 40.33초. 건너뜀은 전용 MySQL 경합 환경 부재 |
| API 재시작 | `sudo -n systemctl restart nadree-api`, 04:00:52 UTC, PID `1390664 → 1405662`, ec2-user, active/running |
| 실제 HTTP | 로컬·공개 각각 health/live·health/ready·Swagger·OpenAPI 모두 **200**. 철회한 중복 해제 설명이 OpenAPI에서 제거됨 |
| 실행 설정 | API 프로세스의 SMTP 환경 덮어쓰기 충돌 없음, SSL/465·발신자/로그인 일치·비밀번호 설정·소유권/600 유지 확인. 값 원문은 출력하지 않음 |
| 오류·기존 작업 | 재시작 로그의 시작 완료·오류 레코드 0. 개인정보·인수·채팅 타이머와 crond active 유지 |

기존 branch2 일반관리자 요청은 03:55:43 UTC에 5회째 실패하여 `ACTION_REQUIRED/CONTACT_OPERATOR`, access=PENDING/personalData=NOT_STARTED가 되었다. **설정 수정만으로 이 요청은 자동 재개되지 않는다.** 요청 재개·삭제, 실제 계정 탈퇴·업무 변경·메일 발송·DB/Firebase 배포는 이번에 실행하지 않았다.

접수 안내 메일은 개인정보 요청을 받았다는 사실·요청번호를 등록 이메일로 보내는 서버 자동 안내이며 이메일 인증 링크 절차와 다르다. 기존 [11월 6일 실행서](admin-privacy-server-apply-2026-11-06.md)의 SMTP 접수·완료 안내 및 실패 시 같은 작업 재시도 계약에 명시돼 있다. 최초 제안자가 프론트인지 여부는 이 문서만으로 단정하지 않는다. 접수 메일 실패가 탈퇴 시작을 막는 기존 처리 순서는 변경하지 않았다.

미검증·남은 작업: 실제 메일 수신/발송, 기존 CONTACT_OPERATOR 요청의 승인된 재개와 최종 삭제 완료, 폐기용 계정의 실제 DELETE·MySQL 경합·앱 종단. 이전의 79개 통과 수치는 철회된 구현 검사이므로 현재 기준에는 합산하지 않는다.

## 최근 삭제 API 읽기 전용 확인: 08:10 UTC 이후

사용자의 최근 호출 처리 결과 확인 요청으로 실제 API 저널과 Firestore 상태·SQL 렌탈 권한을 대조했다. 이 검사에서 요청 재개/삭제·실제 탈퇴·메일 발송·서비스 재시작·설정 변경은 실행하지 않았다.

| 시각 UTC / 발리 | 실제 호출 | HTTP 결과 |
| --- | --- | --- |
| 08:06:20 / 16:06:20 | GET `/nadreego/admin/account-deletion-context` | 200 |
| 08:06:21 / 16:06:21 | POST `/nadreego/admin/account-deletion-requests` | 409, 신규 접수 거절 |
| 08:06:50 / 16:06:50 | GET `/nadreego/admin/account-deletion-requests/status` | 404 |
| 08:08:36 / 16:08:36 | GET `/nadreego/admin/account-deletion-requests/status` | 200 |

08:10:44 UTC Firestore 조회 결과 요청 레코드는 여전히 기존 branch2 일반 SELF 1건이다. 03:10:38 UTC 접수·03:55:43 UTC 5회째 실패 이후 `ACTION_REQUIRED/CONTACT_OPERATOR`, access=PENDING/personalData=NOT_STARTED, 단계 기록 없음, 완료 시각 없음이다. SQL에서도 일반 렌탈 역할과 계정 활성 상태가 유지된다. 저장된 미완료 업무 6종은 모두 0이다. 따라서 이 요청은 현재 탈퇴/개인정보 정리 완료 상태가 아니다.

SMTP 수정 뒤 확인한 48회 배치와 최신 08:08:47 UTC 결과는 processed=1/deferred=0/completed=0이다. CONTACT_OPERATOR 요청은 처리 함수 입구에서 건너뛰므로 배치 서비스의 success가 실제 삭제 완료를 뜻하지 않는다.

409 응답의 JSON errorCode는 현재 저널에 남아 있지 않아 본인 중복 접수·범위 중첩·동일 키 재사용 등 중 어떤 조건인지는 확정하지 못했다. 404도 영수증 오류/미존재 등을 구분할 수 없으므로 삭제 완료나 기존 요청 소실로 판단하지 않았다. 확인한 최근 HTTP 기록에는 직접 DELETE 호출이 없고 비동기 POST 거절·조회가 있다.
