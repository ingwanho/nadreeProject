# 회원정보 정책 동의 이관·서버 적용 결과

**2026-11-25 최종 계약으로 적용 완료.** 인계의 실제 동의값을 고객별 최초 값으로 회원정보에 이관·검증한 뒤 인계 동의 컬럼을 제거했다. 관련 격리 **91개**, 실제 HTTP 검사 **41개**의 기대 결과를 충족했다. 실제 신규 NULL→최초 동의 저장은 별도 승인된 NULL 회원이 없어 미검증으로 구분한다.

기준: [회원 정책 동의 실행서](member-policy-consents-2026-11-25.md). 앞서 적용한 인계 단위 동의 계약과 보고는 이전 이력이다.

## 적용 기준·서비스

- 시작: `main`, 로컬 변경 없음, `7bb750382a8eda21813ab12370cc57409bd2f871`.
- `git pull --ff-only origin main` 성공: **`4a8ba54401c3ff59824c23b97e50941fe93bdf44`**. 충돌·강제 초기화 없음.
- 이관 순서를 보완한 서버 로컬 수정 포함: `app/migrate.py`·관련 회귀 테스트. 내용은 아래에 기록했다. Git commit/push는 하지 않았다.
- 실제 DB: **RIDERLOG_V2_DATA_TEST**, 서비스 사용자 ec2-user, `/srv/nadree-api`, `.venv`, 로컬 포트 8008.
- API 쓰기 중지: `systemctl stop nadree-api` 후 마지막 원본 스냅샷을 추가 저장하고 이관 실행.
- 재시작: **10:20:20 UTC, PID 460035**, active/running.
- 최종 런타임: **10:23:54 UTC**, 로컬·공개 health/live·health/ready·docs·OpenAPI **8회 200**.
- Swagger/OpenAPI **105경로/111메서드**, 회원 **15컬럼**, 인계 **35컬럼**.
- 기존 env·암호화 키·Firebase/Rules/인덱스·S3·타이머 설정은 변경하지 않았다. `.env`는 적용 전 비공개 사본과 바이트 단위 동일하다.

부모 원본 명세 파일은 이 서버에 없어 대조하지 못했다. 저장소의 최신 실행서·구현·실제 결과를 기준으로 했다.

## 비공개 백업과 중지 상태 원본

`/home/ec2-user/.nadree-private/member-consents-20261125T101426580013Z/`.

- ec2-user 소유, 디렉터리 700·파일 600.
- 전체 DB **78테이블 / 641,922,736바이트**. dump 완료 표식 확인.
- `database-full.sql` SHA256: `888b73ed6f43d30e40cff8392387ba85b6e099b348affafa071716c02ee7fbc9`.
- 회원·인계 전체 원본, 기존 동의값, 고객별 각 항목의 예상 최초 시각, 업무 행 수와 env 사본을 별도 비공개 저장했다.
- API 정지 후에도 `members-paused.private.json`, `handovers-paused.private.json`, `expected-member-consents-paused.private.json`을 추가 저장해 이관 직전 값과 대조했다.
- 실제 전체 DB 복구 시험은 실행하지 않았다. 전체 복구가 필요하면 백업 이후 업무와 기존 암호화 키를 함께 대조해야 한다. 삭제한 인계 컬럼을 참조하는 구 코드를 단순 재시작하지 않는다.

## 마이그레이션 순서·검증 결과

원본 코드 계획은 항목별 COPY→DROP 순서였다. 요청한 전체 단계에 맞춰 **두 COPY를 모두 완료한 다음 DROP 목록을 실행**하도록 `app/migrate.py`의 순서만 보완했다. 기존 각 DROP 직전의 누락/대상 회원/더 늦은 시각 검증은 그대로 유지했다.

추가 회귀 `test_second_copy_failure_preserves_both_source_columns_and_can_resume`는 두 번째 COPY 실패 시 두 원본 컬럼·값이 모두 남고 재개할 수 있음을 확인한다. 원본 순서는 이 검사를 통과하지 못한다.

읽기 전용 계획에는 다음 **6개만** 있었고, ec2-user의 **`python -m app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST`**로 적용했다.

1. 회원 `privacy_policy_agreed_at` nullable DATETIME 추가.
2. 회원 `terms_agreed_at` nullable DATETIME 추가.
3. 고객별 실제 개인정보처리방침 최초 시각 이관.
4. 고객별 실제 약관 최초 시각 이관.
5. 원본 대비 보존 검증 후 인계 `privacy_policy_agreed_at` 제거.
6. 원본 대비 보존 검증 후 인계 `terms_agreed_at` 제거.

수동 DROP·공유 DB의 `create_all`·시각화 SQL로 우회하지 않았다. 서명·생성 시각을 동의 시각으로 추정하거나 새 현재 시각으로 채우지 않았다. 재계획은 **No pending changes**다.

| 실제 원본/대조 | 결과 |
| --- | --- |
| 원본 인계 행 | 11행 |
| 개인정보처리방침 실제 시각 | 2행 → 같은 고객의 최초 1개 값 |
| 약관 실제 시각 | 2행 → 같은 고객의 최초 1개 값 |
| 이관 회원 | 28명 중 1명, 항목별 원본 최솟값과 정확히 일치 |
| 나머지 회원 | 27명 두 값 NULL, 서명·생성 이력으로 보정 없음 |
| 회원/인계/예약/계약/결제 행 수 | 각각 **28/11/75/24/13**, 이관 전후 동일 |
| 인계 서명·다른 필드 | 두 삭제 컬럼을 제외한 모든 11행이 원본과 동일 |
| 회원 다른 업무 필드 | 원본과 동일 |
| 회원 `updated_at` | 이관 회원 1명의 값만 DB의 `ON UPDATE CURRENT_TIMESTAMP`로 자동 갱신 |
| env | 원본과 동일, 소유권·600 유지 |

회원의 `updated_at` 자동 갱신은 정보 스키마의 `DEFAULT_GENERATED on update CURRENT_TIMESTAMP`를 확인했다. 이를 숨기거나 과거 시각으로 다시 덮어쓰지 않았다. 다른 업무 필드와 생성 시각·인계 서명은 변경하지 않았다.

## 관련 격리 검증 — 91 passed

ec2-user, 최소 환경·격리 작업 폴더·별도 HOME에서 실제 서비스 env·Firebase/S3 인증정보 없이 수행했다. 현재 요청과 연결된 검사만 실행했고 전체 회귀는 반복하지 않았다.

| 파일 | 통과 |
| --- | ---: |
| `test_customer_consents.py` | 18 |
| `test_member_consent_migration.py` | 6 |
| `test_nadri_auth.py` | 14 |
| `test_handover_v2.py` | 11 |
| `test_handover_contract.py` | 1 |
| `test_foundation.py` | 7 |
| `test_schema.py` | 33 |
| 별도 MySQL 이관·로그인/프로필 경합 | 1 |
| 합계 | **91** |

관련 90개는 **10:14:01~10:14:57 UTC**, MySQL 1개는 **10:15:48~10:16:10 UTC**. 실패/건너뜀 0개, 각 실행 경고 2개는 기존 의존성 사용 중단 예고다.

별도 MySQL의 실제 SQL 실행으로 최초 값 보존·회원이 더 이른 값 보존·서명만 있는 회원 NULL·대상 회원 누락 중단·이관 누락 DROP 거부·두 번째 COPY 실패 시 원본 전체 보존/재개를 검증했다. 정상 HTTP 로그인/프로필 동시 저장과 20초 뒤 재요청의 회원 행 불변도 확인했다. 신규 격리 DB는 테이블 0개를 확인한 뒤 삭제했다. 실제 서비스 DB를 자동 테스트 대상으로 사용하지 않았다.

신규 NULL의 최초 저장·신규 회원·탈퇴/재가입·문서번호와 동의 변경의 원자성은 관련 격리 근거와 실제 수행 여부를 구분한다.

## 실제 API — 41개 HTTP 검사

**10:21:29~10:21:41 UTC**, 기존 승인 테스트 고객과 대표/일반관리자로 수행했다. 이 고객은 기존 인계의 두 동의값을 이미 이관받았으므로 **값을 지우거나 새 계정을 만들어 최초 저장을 시험하지 않았다.**

| 실행 | 실제 결과 |
| --- | --- |
| Firebase 인증 → 기존 고객 로그인, 동의 생략/각각/함께 전달 | 200, 응답 두 시각이 이관 전 비공개 예상 최초값과 일치 |
| 프로필에서 각각/함께 true 전달·재요청 | 200, 최초 시각 유지 |
| GET 회원 프로필 | 200, 로그인/PATCH의 두 값과 동일 |
| 위 요청 전후 시험 회원 | 이관 직후 행 전체와 동일. updated_at·FCM·기존 개인정보도 변경 없음 |
| 잘못된 false/null/문자열·숫자/시각·UID 등 입력 | 422 INVALID_INPUT 13건, 빈 프로필은 422 EMPTY_PROFILE_UPDATE 1건 |
| 로그인 Firebase UID 불일치 | 401 FIREBASE_UID_MISMATCH 1건 |
| 관리자·무인증 등 고객 토큰 검사 | 401 INVALID_NADRI_USER_TOKEN 6건, FIREBASE_ID_TOKEN_REQUIRED 1건 |
| 기존 인계 consents POST | 유효한 기존 본인 대상에서도 **404 Not Found** |
| 고객/대표/일반 인계 상세·고객 예약 handover·관리자 인계 목록 | 두 동의 응답 필드 없음 |
| 본인 기존 인계 8건 | 행 전체와 서명 동일 |

HTTP 분포는 **200×18 / 422×14 / 401×8 / 404×1**이며 모두 기대 결과다. HTTP 기록 수를 독립 테스트 케이스 수로 표현하지 않는다.

새 회원·예약·인계·계약·결제를 만들지 않았고 행 증가 0이다. `fcmToken`·문서번호·폼·미디어를 보내지 않았다. 실제 계정 삭제·결제·환불·S3 업로드·Firebase 설정 변경도 실행하지 않았다. 정상 로그인에 따른 refresh 토큰·관리자 세션/채팅 인증 갱신은 기존 승인 범위다.

최종 로컬·공개 구 POST도 각각 404, OpenAPI에서 구 경로가 제거됐다. `CustomerUser`에는 회원 동의가 있고 `HandoverItem/HandoverListItem`에는 없다. 재시작 이후 최종 집계 **traceback 0 / ERROR 0 / HTTP 5xx 0**. 기존 서명·영상·렌트 시작 조건은 관련 회귀와 실제 기존 인계 불변으로 확인했다.

## 미검증·남은 작업·프론트 전달

수행한 검사에 미해결 실패는 없다. 다음은 실제 서버에서 실행하지 않았다.

- **승인된 NULL 회원의 최초 저장·신규 가입.** 기존 승인 UID는 같은 고객이었고 이미 두 값을 이관받았다. 실제 최초 저장을 추가 검증하려면 별도 승인된 NULL 동의 테스트 고객이 필요하다. 기존 이관값을 초기화하지 않는다.
- 실제 회원 탈퇴/재가입, 문서번호와 동의의 실제 동시 수정. 격리 검사는 통과했다.
- 별도 고객으로 로그인하는 권한 시험, 관리자 예약 상세·고객 렌트 상세 실응답, 새로운 회원 동의 후 렌트 전체 흐름 재완주.
- 앱 화면·App Check·실기기 푸시 수신·전체 DB 복구 시험.

프론트는 **회원 가입/로그인 POST `/api/v1/nadree/user/login` 또는 PATCH `/api/v1/nadree/user/profile`**에 실제 체크한 항목만 JSON true로 보낸다. 두 항목은 선택 입력이며 생략은 동의로 간주하지 않는다. GET 프로필/로그인/PATCH의 `user.privacyPolicyAgreedAt`, `user.termsAgreedAt`를 조회한다. 인계 ID 없이 처리하고, 구 consents POST 및 인계 응답 필드 사용은 제거한다. 기존 서명 완료 API와 렌트 조건은 유지한다. 추가 env·키·Firebase 설정은 없다.

적용 코드는 Git `4a8ba54`에 이관 순서 보완을 더한 상태다. 보완 소스와 회귀·결과 문서는 로컬 수정으로 남아 있어 향후 Git 반영 시 보존해야 한다.

## 비공개 근거

- 전체 DB·원본/중지 상태·예상 최초값·전후 대조·최종 런타임: 위 `~/.nadree-private/member-consents-*` 디렉터리.
- 관련 90개: `/tmp/nadree-member-consents-tests-20261125-64k5njvk/result.json`.
- MySQL 1개: `/tmp/nadree-member-consents-mysql-20261125-3e4fmhsn/result.json`.
- 실제 API: `build/test-runtime/member-consents-http-ready-2026-11-25/sanitized-result-2026-11-25.json`.

비공개 파일은 600/디렉터리 700으로 보관했다. 이 문서에는 키·토큰·비밀번호·개인정보·서명 URL을 넣지 않았다.
