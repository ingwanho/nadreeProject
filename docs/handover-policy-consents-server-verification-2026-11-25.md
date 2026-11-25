# 인계별 개인정보처리방침·이용약관 동의 서버 적용 결과

> 이후 최종 정정으로 동의값을 회원정보로 안전하게 이관하고 인계2컬럼·구 API를 제거했다. 현재 계약/실제 상태는 [회원 동의 최종 서버 보고](member-policy-consents-server-verification-2026-11-25.md)를 따른다. 아래 내용은 06:30까지 인계 단위 배포 당시의 이력이다.

검증일 **2026-11-25 UTC**. 기준은 [동의 API 적용서](handover-policy-consents-2026-11-25.md)다. **동의 컬럼 2개·API 배포를 완료했고, 관련 격리 68개 및 실제 HTTP 검사 50개의 기대 결과를 충족했다.** 이전 11월 24일 전체 회귀·업무 검사 수를 이번 검증으로 합산하지 않았다.

## 적용 정보

| 항목 | 실제 확인 |
| --- | --- |
| Git | 시작 `main`, 로컬 변경 없음. `git pull --ff-only origin main` 성공, 충돌/강제 초기화 없음 |
| 적용 커밋 | `2ccd9c0e26d69e7fa4d686ba4b4182de968e456f` (`c5c1bbb`에서 갱신) |
| 서비스 | `nadree-api.service`, ec2-user, `/srv/nadree-api`, `.venv`, 포트 8008 |
| 실제 DB | **RIDERLOG_V2_DATA_TEST** |
| API 전환 | 기존 PID 3407923 정지 → **06:26:55 UTC / 새 PID 287088** 시작 |
| 최종 런타임 확인 | **06:30:15 UTC**, 로컬·공개 live/ready/docs/OpenAPI 총 8회 200 |
| 명세 | **106경로 / 112메서드**, 새 consents POST 및 요청/응답 필드 확인 |

부모 명세 `/srv/rental-project-master.md`, `/srv/rental-api-review-decisions.md`는 이 서버에 없었다. 저장소 실행서·구현·실행 결과로 검증했다.

## 백업·마이그레이션·기존 기록 보존

비공개 백업: `/home/ec2-user/.nadree-private/handover-consents-20261125T062523232742Z/`.

- ec2-user 소유 디렉터리 700·파일 600. 전체 DB **78테이블 / 641,905,708바이트**, dump 완료 표식 확인.
- `database-full.sql` SHA256: `0d0f01a759bb5cf548cc381706e38de50bb97d31f8aa0c2b521c06de7f610686`.
- 기존 인계 7건의 비공개 원본과 `.env` 사본을 함께 보관했다. 원문 데이터는 출력하지 않았다.
- 실제 전체 DB 복구 시험은 하지 않았다. 복구가 필요하면 이후 업무 변경과 기존 암호화 키를 보존하면서 백업을 대조해야 한다.

ec2-user로 읽기 전용 계획을 확인했고 **다음 2개만** 적용했다.

```sql
ALTER TABLE MSP_RENTAL_HANDOVER ADD COLUMN privacy_policy_agreed_at DATETIME DEFAULT NULL;
ALTER TABLE MSP_RENTAL_HANDOVER ADD COLUMN terms_agreed_at DATETIME DEFAULT NULL;
```

적용 후 재계획 **0개**, 인계 테이블 **37컬럼**을 확인했다. 두 컬럼은 nullable DATETIME·기본값 NULL이다. 공유 DB에 `create_all`이나 시각화 SQL을 실행하지 않았다.

**기존 인계 7건 모두 두 동의 시각 NULL, 서명 시각을 포함한 다른 필드 전체 동일**을 적용 직후와 실제 API 시험 후 비교했다. 서명/생성 시각으로 추정한 UPDATE나 일괄 보정은 수행하지 않았다.

`.env`는 적용 전 사본과 **바이트 단위 동일**, 소유권·600 권한 유지. env·전화번호/인계 암호화 키·Firebase/Rules/인덱스·S3·타이머 설정은 변경하지 않았다. 이번 서버 작업의 업무 코드 추가 수정도 없다.

## 격리 검증 — 68개 통과

서비스 사용자인 ec2-user로 최소 환경·별도 HOME·실제 `.env`를 읽지 않는 작업 경로에서 수행했다. 실제 Firebase/S3 자격정보와 실제 서비스 DB를 자동 테스트 대상으로 사용하지 않았다.

| 검사 | 결과 |
| --- | --- |
| `test_handover_consents.py` | 15 passed |
| `test_handover_v2.py` | 11 passed |
| `test_handover_contract.py` | 1 passed |
| `test_foundation.py` | 7 passed |
| `test_schema.py` | 33 passed |
| 별도 신규 MySQL DB 동의 동시 요청 | 1 passed |
| 합계 | **68 passed / 실패 0 / 건너뜀 0** |

첫 67개는 06:24:11~06:24:51 UTC, 추가 MySQL 검사는 06:25:23~06:25:40 UTC에 실행했다. 각 실행의 경고 2개는 기존 Starlette/httpx·anyio 사용 중단 예고다.

별도 MySQL DB에서 최초 개인정보/약관 요청을 동시에 보내 두 값을 저장한 뒤, 19초 후 재요청해도 행 전체와 최초 시각이 유지됨을 확인했다. 서명 NOT_STARTED·고객 DRAFT도 유지됐다. 이 신규 격리 DB는 테이블 0개를 확인하고 삭제했다.

기존 NULL 이력 보존·각각/동시 저장·고객 소유권·엄격한 true 입력·닫힌 상태·기존 서명/렌트 시작 조건 회귀를 포함한다. 요청 범위에 맞춰 **전체 회귀는 다시 실행하지 않았다.** 실행서의 로컬 전체 971 passed/23 skipped는 별도 근거다.

## 실제 API 검증 — 50개 HTTP 검사

**06:28:12~06:28:36 UTC**, 승인된 기존 테스트 고객과 대표/일반관리자·테스트 지점의 기존 QR 차량으로 새 Walk-in/인계 2건을 만들었다. 다른 계정의 비밀번호 변경·새 계정 생성·타 고객 로그인은 하지 않았다.

| 검증 | 기대 결과와 실제 결과 |
| --- | --- |
| 미시작 인계에 동의 | 409 HANDOVER_CLOSED, 저장 없음 |
| 개인정보처리방침만 동의 | 200, 개인정보 시각만 서버 UTC 초 단위 저장·약관 NULL |
| 이후 약관만 동의 | 200, 개인정보 최초 시각 유지·약관 최초 시각 기록 |
| 이미 기록한 두 항목 재요청 | 200, 최초 시각 및 행 전체 불변 |
| 두 동의를 함께 최초 저장 | 200, 두 시각 동일 |
| 같은 인계에 실제 동시 POST 2건 | 두 응답 200, 같은 최초 시각·중복 덮어쓰기 없음 |
| 고객 인계 상세·고객 예약 상세 | 두 동의 시각 일치 |
| 대표/일반관리자 인계 상세·관리자 인계 목록 | 두 동의 시각 일치 |
| 관리자 토큰·무인증으로 저장 | 401 INVALID_NADRI_USER_TOKEN |
| 빈 값/false/null/문자열·숫자/고객 지정 시각 등 8개 | 422 INVALID_INPUT, 기록 변경 없음 |
| 정상 취소한 새 인계에 재요청 | 409 HANDOVER_CLOSED |
| 기존 본인 STARTED 인계에 요청 | 409 HANDOVER_CLOSED, 기존 행 동일 |
| 승인 테스트 고객 → 타 고객 소유의 기존 닫힌 인계 | 404 HANDOVER_REQUIRED, 타 고객 행 전체 동일 |
| 동의 저장 후 서명·고객·렌트 가능 상태 | 서명 NOT_STARTED/시각 NULL·고객 DRAFT 유지, canStartRental을 완료로 올리지 않음 |

상태 분포: **200 33건 / 409 5건 / 401 3건 / 422 8건 / 404 1건**. 모두 검사에서 의도한 응답이며 검사 기록 수를 독립 테스트 케이스 수로 해석하지 않는다.

타 고객 차단의 실제 검증 방향은 **승인 고객이 타 고객의 닫힌 인계에 접근**하는 방식이었다. 다른 고객으로 로그인해 새 시험 인계에 접근하는 방향은 실행하지 않았다. 대상은 닫혀 있어 권한 검사에 문제가 있더라도 `_open`에서 저장되지 않으며, 기존 행 불변도 확인했다.

## 시험 후 데이터·서비스 상태

- 새 예약 **2행**, 새 인계 **2행** 추가. 두 시험 예약은 모두 정상 취소했고 시험 미완료 **0건**이다. 시험 이력을 삭제하거나 기존 예약을 초기화하지 않았다.
- 고객·계약·결제 증가 **0행**. 시험 차량은 AVAILABLE이다. 기존 다른 진행/미반납·회수 보호는 변경하지 않았다.
- 새 인계 2건은 실제 동의 시각을 보존하고, 기존 7건은 두 값이 모두 NULL이다.
- 이번 시험에서는 폼·프로필·서류·미디어·S3 업로드·PayPal 결제/환불·실제 계정 삭제를 실행하지 않았다.
- 최종 health/live·health/ready·Swagger·OpenAPI는 로컬/공개 모두 200. OpenAPI의 `HandoverConsents`, `HandoverItem`, `HandoverListItem`에 새 계약을 확인했다.
- 06:26:55 UTC 재시작 이후 최종 로그 집계: **traceback 0 / ERROR 0 / HTTP 5xx 0**.
- 실제 고객/관리자 테스트 로그인은 기존 세션을 회수할 수 있으므로 해당 시험 앱에서는 재로그인이 필요할 수 있다.

## 실패·미검증·남은 작업

**수행한 검증에서 미해결 실패는 없다.** 다음은 이번 실서버 시험의 범위 밖이며 코드 확인/격리 통과를 실제 성공으로 대체하지 않는다.

- 두 번째 고객의 실제 로그인 → 새 인계 접근 방향. 소유권 차단은 위 반대 방향과 격리 테스트로 확인했다.
- 관리자 예약 상세·고객 렌트 상세의 새 필드 실응답. 이번에는 실제 렌트를 새로 시작하지 않았고 고객 예약 상세/인계 상세/관리자 목록을 확인했다.
- 실제 앱 UI·App Check·기기 푸시 수신 및 **동의 API만의 실제 FCM 전송 수**. 동의 함수가 새 알림을 큐에 넣지 않는 코드와 격리 근거는 있으나 실제 발송 수를 계측하지 않았다.
- 새로운 동의를 포함해 서류·S3·서명·렌트 시작까지 전체 실제 흐름 재완주. 이번에는 기존 시작 조건의 관련 회귀와 실제 상태 불변을 확인했다.
- 전체 DB 복구 시험. 이번 변경의 백업·완료 표식·파일 체크섬은 확인했다.

프론트는 고객이 실제 체크한 항목만 JSON `true`로 `/api/v1/nadree/rental/handovers/{handover_id}/consents`에 보낸다. 하나 또는 둘을 함께 저장할 수 있고 별도 요청 ID가 필요 없다. 생략한 항목은 유지하며 false로 철회할 수 없다. 새 인계는 NULL부터 시작한다. 상세의 `privacyPolicyAgreedAt`·`termsAgreedAt`를 사용하고 **기존 서명 완료 API나 렌트 시작 조건을 대체하지 않는다.** 추가 env·키·Firebase 배포는 필요 없다.

## 근거 파일

- DB 전체/기존 행/마이그레이션·env 보존 비교: 위 ec2-user 비공개 백업 디렉터리. 최종 런타임은 `final-runtime-evidence.json`.
- 격리 67개: `/tmp/nadree-consents-tests-20261125-86f03tk_/result.json`.
- MySQL 경합 1개: `/tmp/nadree-consents-mysql-20261125-mvdm32ab/result.json`.
- 실제 API: `build/test-runtime/consents-http-ready-2026-11-25/sanitized-result-2026-11-25.json`.

근거는 비공개 700/600에 보관했다. 이 문서에 키·토큰·비밀번호·개인정보·S3 서명 URL을 넣지 않았다. Git 커밋·push는 실행하지 않았다.
