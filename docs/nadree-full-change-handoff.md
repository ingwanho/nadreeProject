# Nadree 전체 변경사항 및 인수 문서

## 2026-11-10 지점 계층·Master ID·UNIT_NAME — 기존 데이터 정리 완료

사용자 확정 정책에 따라 신규 생성과 기존 데이터 정리를 실제 서버에 적용했다. 기준 커밋은 `e811aa124078eff832be3451e214a5c5505ffb9d` + 보존된 서버 로컬 변경이며 이번 작업에서 pull/reset/commit/stash 삭제는 하지 않았다. 부모 명세 `../rental-project-master.md`, `../rental-api-review-decisions.md`는 서버에 없어 읽지 못했다. 실제 공유 DB의 기존 정상 계층·컬럼·외래 키 및 사용자 확정 지시를 기준으로 확인했다.

확정 저장 규칙:

- 모든 계층의 지점 식별·부모 선택·관리자 소속·권한·업무 연결은 `MSP_SPOT_MASTER.spot_master_id`다. 정규 `MSP_ORG/REGION/LOCAL/SPOT`의 ID와 master ID가 달라도 동작한다. `MSP_SPOT_MASTER.spot_id`는 최하위 spot 연결 값이다.
- 생성할 계층은 잠근 부모의 `hierarchy_level`로 **org → region → local → spot** 순서로 결정한다. org 아래 요청에 기존 `unit_type=spot`을 보내도 region이 생성된다. 기존 필드와 enum은 유지하며 `unit_type=org`의 기존 403도 유지한다. spot/team/agency 부모의 신규 하위 생성은 422 `CHILD_HIERARCHY_NOT_SUPPORTED`다. 조회의 `canCreateChild`도 org/region/local에서만 true다.
- 신규 지점은 해당 정규 계층 행·`MSP_SPOT_MASTER` 행·`MSP_SPOT_RENT` 행을 한 트랜잭션으로 생성한다. 부모의 contract/org/region/local 연결을 상속하며 필수 조상 키가 없으면 422 `PARENT_HIERARCHY_INCOMPLETE`로 전체 생성이 취소된다. leaf의 주소/이메일/좌표 필수 검사와 계약·역할·삭제 중 신규 업무 차단은 유지한다.
- `unit_name`은 그 행 본인의 지점 이름이다. `org_name`, `region_name`, `local_name`, `spot_name`은 각각 연결된 계층의 이름이다. 비말단에서는 `spot_id`·`spot_name`을 NULL로 둔다. 예를 들어 PrmBali 아래 PUTU'S PLANET은 `org_name=PrmBali`, `region_name=unit_name=PUTU'S PLANET`인 region이다. 그 아래 local은 위 이름을 상속하고 본인 이름을 `local_name`·`unit_name`에 넣는다.
- 코드는 부모의 전체 `unit_code`에 `-RNN`, `-LNN`, `-SPNN`을 붙인다. 기존 정상 데이터의 `…-ORG01-R01-L01-SP01` 구조를 확인했다. 조회/권한/부모 연결은 동일 contract/org와 하이픈 구간 경계를 사용한다. 기존 공유 데이터의 RG/LO 등 유효한 과거 코드 형식은 바꾸지 않고 상위·하위 전체 접두사 관계를 보존했다.
- 지점명 변경은 `unit_name`, 해당 정규 계층 이름, 해당 계층의 하위 이름 캐시를 함께 갱신한다. 다른 지점의 본인 이름은 바꾸지 않는다. 조회·검색·동일 부모 이름 중복 판정·프로필·메인·고객 조회·탈퇴 범위·채팅 표시 이름은 `unit_name`을 읽는다.

프론트 계약:

| 기존 필드 | 의미와 처리 |
| --- | --- |
| 생성 요청 `parent_spot_id` | 선택한 부모의 **master ID**. leaf의 정규 spot ID가 아님 |
| 생성 요청 `spot_name` | 새 지점 본인 이름. DB에는 unit_name과 자기 계층의 정규 이름으로 저장 |
| 생성 응답 `spot_id` | 기존 이름을 유지하는 **새 master ID 별칭**. region/local에서도 반환 |
| 생성/계층 응답 `spot_name`, 프로필 `shopName` 등 | 기존 키를 유지하고 unit_name을 표시 |
| 관리자 로그인 `admin.spotMasterId` | 기존부터 primary_spot_master_id를 반환했으며 유지. 별도 정규 spot ID로 바꾸지 않음 |
| `hierarchy_level`, `unit_code`, `canCreateChild` | 실제 생성 계층·코드·가능 여부에 맞는 값 반환 |

앱은 새 필드로 바꿀 필요가 없다. 지점 선택 ID를 master ID로 보관하고, 기존에 캐시한 SP01 코드는 계층/프로필을 재조회해 갱신한다. 거래 당시 예약·계약 스냅샷의 코드/주소/이력은 현재 지점 코드로 일괄 치환하지 않는다.

실제 데이터 적용:

- 대상은 **RIDERLOG_V2_DATA_TEST**, 2026-11-10 **10:36:53 UTC** 비공개 백업 후 단일 DML 트랜잭션으로 적용했다. 스키마 마이그레이션은 없다. 읽기 전용 계획 **33개 작업/구조 오류 0개**, 실제 결과 **INSERT 5행·UPDATE 28행**, SQL 커밋 성공이다.
- org 바로 아래 생성됐던 spot 2개를 region으로 전환했다. `spot_master_id`, org/contract, 관리자 소속/권한, 차량·예약·계약 연결은 유지했다. 각 부모에 기존 R01이 없어 R01을 사용했고, 이후 같은 부모의 다음 region은 R02다.

| 기존 코드 | 적용 코드 | 적용 상태 |
| --- | --- | --- |
| `NR_TEST_20260921-ORG01-SP01` | `NR_TEST_20260921-ORG01-R01` | region, 기존 삭제된 지점의 is_active=0 유지 |
| `PRMBALI_20261109-ORG01-SP01` | `PRMBALI_20261109-ORG01-R01` | region, PUTU'S PLANET 활성 유지 |

- 위 두 지점의 `MSP_REGION` 2행을 추가하고, 이전 정규 `MSP_SPOT` 2행은 삭제하지 않았다. 이미 비활성이던 행은 유지하고 활성 과거 행 1개만 비활성으로 보존했다. 과거 참조/업무 이력을 지우지 않았다.
- 실제 정규 계층에는 있으나 master가 없던 기존 org/region/local 상위 3행을 추가했다. 새 master ID는 정규 ID와 구분되는 결정적 UUID이며 기존 leaf master ID는 유지했다. 이 보완에는 렌탈 설정·초대 코드·관리자·권한을 새로 만들지 않았다.
- 27개 기존 master의 계층 이름 캐시와 비말단 spot_name을 정리하고 기존 leaf의 누락 hierarchy_level을 보완했다. 최종 master **30개**, 재조회에서 빈 unit_name/비말단 spot_name/leaf 이름 불일치/누락 계층 각각 **0건**이다.
- 정확한 master ID와 이전 코드가 함께 일치하는 scope만 코드 정리 대상으로 삼았다. 실제 scope 변경은 0행이며 NULL 코드·과거 scope·권한은 보존했다.
- 관리자 소속/역할·렌탈 설정·차량/상태·센서·예약/배정·계약·결제/환불·QR·가격·배송 및 관련 이력/현장 요청 등 **17개 테이블의 검증 대상 컬럼 지문이 적용 전후 동일**했다. 예약 취소·환불·회원 삭제·시험 알림 발송은 하지 않았다.
- 실행 중 개인정보 요청은 0건이었다. 남은 SQL 삭제 포인터 1건은 COMPLETED인 비활성 지점의 과거 요청으로 보존했다. 공유 DB의 unit_code 외래 키는 0개이며 외래 키 검사를 끄지 않았다.

백업·복구:

- `build/test-runtime/spot-hierarchy-repair-2026-11-10/20261110T103653526138Z/`에 대상 6테이블 원본 `before.json`, 변경 전 행을 포함한 `operations.json`, 업무 참조 지문, 검증 결과를 저장했다. 디렉터리 **700**, 파일 **600**, ec2-user 소유다. 연락처 등이 포함될 수 있어 원문을 공개하지 않는다. env·비밀번호·토큰은 이 파일에 복사하지 않았다.
- 도구는 `migrations/repair_spot_hierarchy_2026_11_10.py`이며 인수 없이 실행하면 읽기 전용 계획이다. `--apply`는 승인된 위 테스트 DB에만 허용하고, 백업 실패·개인정보 진행 중 요청·중간 변경·구조 오류·업무 참조 변화 시 커밋하지 않는다.
- 격리 실제 SQL 실행으로 백업 실패 전 무변경과 후반 검증 실패 시 6테이블 전체 롤백을 검증했다. 커밋 후 수동 복구가 필요하면 API/개인정보 배치를 조율하고 새 참조 여부를 확인한 후 백업의 변경 목록을 역순으로 검토·복구한다. 신규 master/region에 새 업무가 붙었다면 바로 삭제하지 않는다. 이번에는 복구가 필요하지 않았다.

검증 — 격리 환경:

- ec2-user·`env -i`·기존 venv·실제 DB/Firebase 자격정보 없는 disposable SQLite/메모리 외부 연동을 사용했다. 업데이트와 직접 연결된 부분만 검사했으며 전체 API 회귀를 재실행하지 않았다.
- 고유 **153개 검사 통과**, 최종 미해결 실패/건너뜀 0개. 지점 master 조회·자동 단계·R01 뒤 R02·필수 조상·권한/형제 차단·정규/master ID 분리·이름 수정·프론트 필드·가입/초대 소진·관리자 탈퇴 범위·개인정보 신규 업무 차단·명세·현재 schema·로그인·다섯 표시 경로·데이터 정리/롤백을 포함한다.
- 최종 묶음은 150개 중 148 passed/2 failed였다. 실패 2건은 신규 격리 fixture가 실제 DB의 `delivery_service_type=NONE` 기본값을 누락한 원인이었고 서버 코드를 우회하지 않았다. fixture를 바로잡은 후 해당 이름 수정 파라미터 4개 모두 통과했다(2개는 재검사 중복). 별도 적용 안전성 3개도 통과했으므로 고유 검사 수는 **148+2+3=153**이다. 기존 TestClient 관련 사용 중단 예정 경고 2종은 남는다.
- 실행 파일: `test_spot_master_lookup.py`, `test_spot_hierarchy_repair.py`, `test_spot_unit_names.py`, `test_management.py`, `test_admin_signup.py`, `test_invite_codes.py`, `test_admin_account_deletion.py`, `test_privacy_admission_guards.py`, `test_spot_hierarchy_repair_apply.py` 및 foundation 경로·schema 현재 계약·accounts 로그인 지정 검사. 테스트 성공을 실제 앱 종단 성공으로 간주하지 않는다.

검증 — 실제 서버:

- 개인정보 타이머를 잠시 중지하고 실행 중 배치 없음 확인 후 API에 정상 종료를 요청했다. 구 API의 shutdown complete를 확인했고 DB 적용 후 **10:37:05 UTC / 발리 18:37:05** 새 API를 시작했다. PID **2807015**, active/running이다. 개인정보 타이머를 복구했고 기존 chat-sync/receipts/chat-retention 작업도 active다. 결제 작업 설정은 바꾸지 않았다.
- **10:38:42 UTC** 로컬/공개 health/live·health/ready·Swagger·OpenAPI **8개 모두 200**. health 제외 **79경로**, 기존 생성 필드 보존, master ID/자동 계층 설명, 공개 명세 한글 0개를 확인했다.
- 적용 후 다시 읽기 전용 계획을 실행해 **남은 작업 0개·구조 오류 0개**, master 30개와 17개 참조 테이블 검증 가능 상태를 확인했다. 별도 읽기 조회에서도 전환 코드·활성 상태·자기 region 이름과 unit_name 일치를 확인했다.
- 전환 이후 API·chat-sync·개인정보 서비스 로그의 ERROR/Traceback/HTTP 5xx **0건**이다. `.env` 내용/소유권/600 권한 보존, Firebase 함수/Rules/인덱스/인증 설정 배포 없음.

남은 확인:

- 실제 관리자 로그인·새 지점 생성·이름 변경·차량/예약 업무의 앱 왕복은 실행하지 않았다. 기존 앱 세션을 회수하거나 실제 업무를 추가하지 않기 위한 범위 구분이다. 위 쓰기 흐름의 동작은 격리 검증이다. 양 앱은 master ID/계층 재조회·이름 표시·말단 하위 생성 버튼을 확인한다.
- 실제 MySQL 동시 생성 경합과 RiderLog 실행 중 서버의 종단 호환은 별도 미검증이다. 서비스 소스가 서버에 없으므로 기존 정상 DB 구조와 실제 외래 키 검사를 근거로 삼았다.
- master가 존재하지 않는 공유 관리자 scope **2건**은 별도로 발견했다. 두 계정 모두 렌탈 역할이 없으며 하나는 비활성이다. 원래 귀속 지점의 정규 행도 현재 계층에 없어 임의 master 생성·권한 재배정·scope 삭제는 하지 않았다. 나드리 신규 생성/계층 정리의 미적용 건으로 섞지 않으며, 공유 계정 관리 담당자가 귀속을 확정해야 한다.

## 2026-11-10 회원가입 10회 제한·공개 영어 표기 — 서버 반영 완료

최종 사용자 요청에 따라 POST /nadreego/admin/signup의 횟수 제한을 유지한다. **가입 이메일별 첫 시도부터 1시간에 10회**, **접속 IP별 5분에 10회**이며 각 제한의 11번째부터 429 RATE_LIMITED다. 이메일 기준만 기존 5회에서 10회로 늘렸고 IP 기준은 기존 10회 그대로다. 가입 처리에 도달한 실패 요청도 누적된다. 기존 Redis 키/기간/누적 기록은 유지하며 전체 초기화하지 않았다. 로그인·갱신·비밀번호 재설정·채팅·개인정보 요청 등 다른 제한과 중복 계정/초대 코드/권한/계약 검사는 변경하지 않았다.

서버가 전달하는 고정 표시 문구를 영어로 정리했다. 기존 영어 알림·이메일은 유지하고, 남아 있던 PayPal 복귀 HTML의 lang/title/제목/본문, 공개 API summary/description, Swagger 태그/보안 헤더/응답 설명, 스키마 설명 및 고정 예시의 이름/주소/사유 등을 영어로 전환했다. 실제 DB의 이름·지점명·자유 입력·채팅 내용은 수정하지 않는다. 한국어 개발자 주석과 이 운영 문서는 사용자 화면용 문자열이 아니므로 유지한다. API 경로·필드·상태 코드·enum·79경로와 업무 처리 조건은 그대로다.

검증·적용:

- ec2-user·env -i·기존 venv·폐기용 SQLite/모의 외부 연동에서 최종 관련 **31 passed / 0 failed / 0 skipped**, 10.16초. IP/이메일 각각 10번째 업무 검증·11번째 차단, 중복 가입 보존, 대표/일반 가입·일회성 초대 소진, 기존 로그인 보호, 명세, 공개 복귀 페이지의 결제/DB 쓰기 없음과 알림 읽음을 확인했다. 기존 TestClient 사용 중단 예정 경고 2종은 남는다.
- 실행 대상: test_signup_attempt_policy.py, test_admin_signup.py, test_invite_codes.py, test_foundation.py, test_payment_return_url.py, test_accounts.py::test_login_response_and_hash_storage, test_admin_customer_inbox.py::test_notification_read_is_shared_idempotent_and_scoped. 전체 회귀는 재실행하지 않았다.
- 실제 자격정보 없는 별도 설정으로 생성한 OpenAPI의 한글 문자열 **0개**, app Python AST의 한글 문자열 상수 **0개**. 담당 변경의 비문구 AST 구조와 실제 diff를 검토해 기능 조건 보존을 확인했다.
- **09:54:09 UTC / 발리 17:54:09** API 재시작 완료(PID 2770400), active/running. **09:54:45 UTC** 로컬/공개 health/live·health/ready·Swagger·OpenAPI·정적 결제 복귀 10개 요청 모두 200이었다. 실제 공개/로컬 OpenAPI도 한글 0개·10회 정책 설명·79경로를 확인했고 복귀 HTML은 lang=en·영어 안내였다.
- 시작 완료·이후 ERROR/Traceback/HTTP 5xx 0건, 기존 채팅 동기화·개인정보·인수·채팅 보관 타이머 active 확인. .env 수정 없음·600 유지, DB/스키마·Firebase·결제/기타 배치 설정 변경 없음.
- 실제 신규 가입·의도적인 실서버 제한 소진·계정/예약 변경·결제/환불·메일/푸시 발송은 하지 않았다. 10회 경계는 격리 API에서 검증했고 실제 서버는 상태·명세·공개 정적 페이지를 확인했다. 앱 자체 번역/캐시와 실제 입력 데이터의 표시는 별도다.

## 2026-11-10 etc 50cc·125cc 모델 2개 추가 완료

사용자의 최종 요청대로 브랜드와 모델명을 모두 etc로 하여 **08:45:01 UTC** 공용 카탈로그에 두 행을 추가했다.

| modelId | brand | modelName | cc |
|---|---|---|---|
| ETC-50 | etc | etc | 50 |
| ETC-125 | etc | etc | 125 |

기존 카탈로그 백업·중복 확인 후 한 트랜잭션으로 2행만 추가했으며 기존 모델은 보존했다. 커밋 후 실제 DB 재조회로 etc 모델이 정확히 50cc/125cc 두 개·활성 상태, 전체 활성 모델 9개, 두 모델의 실차 참조 0건임을 확인했다. 차량·QR·가격·기존 Honda 모델·서버 설정은 변경하지 않았고 재시작도 필요 없다.

두 모델은 SCOOTER, 이미지 null, 배송 지원 기본값 0이다. 브랜드 API 새 조회부터 나타나며 이름이 같으므로 프론트는 modelId를 선택 키로 사용하고 cc를 함께 표시한다. 백업/계획/실제 결과는 build/test-runtime/etc-model-catalog-2026-11-10/20261110T084501433017Z 아래 700/600 권한으로 보관했다.

## 2026-11-10 Honda 모델 3개 데이터 추가 완료

사용자가 확정한 PCX 125cc, Scoopy 110cc, BeAT 110cc를 **08:37:24 UTC** RIDERLOG_V2_DATA_TEST의 공용 MSP_VEHICLE_MODEL에 추가했다. 브랜드는 기존 Honda를 사용한다.

| modelId | brand | modelName | cc |
|---|---|---|---|
| HONDA-PCX-125 | Honda | PCX | 125 |
| HONDA-SCOOPY-110 | Honda | Scoopy | 110 |
| HONDA-BEAT-110 | Honda | BeAT | 110 |

세 모델은 SCOOTER·is_active=1, 이미지 미설정(null)·배송 지원 기본값 0이다. 기존 모델 전체를 접근 제한 백업 후 한 트랜잭션으로 정확히 3행 추가했고 기존 4행 불변을 확인했다. 커밋 후 읽기 전용 재조회에서 활성 모델 7개·브랜드 Honda/SYM/Yamaha·신규 모델 차량 참조 0건을 확인했다. 차량·QR·가격·재고·예약은 생성/변경하지 않았다.

브랜드 API는 활성 모델을 매 요청 조회하므로 재시작 없이 새 조회부터 모델을 선택할 수 있다. 등록 시 brand/vehicleName은 위 표의 brand/modelName을 그대로 사용한다. 실제 인증된 HTTP 왕복이나 차량 등록 시험으로 새 차량을 만들지는 않았다. 백업/계획/결과는 build/test-runtime/honda-model-catalog-2026-11-10/20261110T083724743997Z 아래 700/600 권한으로 보관했다.

## 2026-11-10 브랜드 API — 공용 활성 모델 카탈로그

차량 등록 시 자신의 지점에 차량이 없어도 브랜드·모델을 고를 수 있도록 POST /nadreego/brand를 변경한다. 새 브랜드 테이블이나 데이터를 만들지 않고 기존 공용 MSP_VEHICLE_MODEL을 사용한다.

요청 경로/본문/응답 필드는 유지한다.

```json
{"page":1,"pageSize":20}
```

- brand: 전체 활성 모델의 브랜드를 중복 제거해 반환한다. 현재 지점 차량 수·요청 페이지와 무관하다. 빈 페이지에서도 전체 브랜드 목록은 유지한다.
- vehicle: 전체 활성 모델을 brand/modelId 순으로 정렬한 페이지다. 미보유 모델도 포함하며 비활성 모델은 제외한다.
- vehicleCount: 해당 모델의 **현재 직접 소속 지점 차량 수**다. 상위/하위/다른 지점 수를 합산하지 않는다. 미보유 모델은 0이다.
- price: 기존 BASIC 기준인 공통 BASE+현재 직접 지점 BASIC으로 계산한다. 상위 BASIC은 상속하지 않고 다른 지점 가격도 읽지 않는다. 미설정이면 null이다. PREMIUM 차량 고정 단가나 예약 확정 가격이 아니다.
- totalCount/hasNext: 전체 활성 모델 수와 현재 페이지 기준이다. tier/price/page/pageSize의 기존 형태도 유지한다.

프론트는 vehicleCount가 0이라는 이유로 등록용 모델을 숨기지 않는다. 전체 모델이 필요하면 hasNext에 따라 페이지를 추가 조회한다. 실제 보유 차량 목록은 /nadreego/vehicle/select, 고객 예약 가능 재고·견적은 기존 availability API를 사용한다. 카탈로그 표시만으로 차량 재고나 예약 가능 여부를 판단하지 않는다.

관리자 인증·역할·직접 지점·계약·탈퇴 처리 중 읽기 정책은 유지한다. DB 스키마/데이터·env·Firebase 변경은 없다. 이전의 차량 보유 기준 설명은 이 경로에 한해 이 절로 대체한다.

**서버 적용 완료:** 2026-11-10 **08:24:53 UTC / 발리 16:24:53** nadree-api.service 재시작(PID 2700911) 후 active/running을 확인했다. 08:25:42 UTC 로컬/공개 health/live·health/ready·Swagger·OpenAPI가 모두 200이고 카탈로그 설명·Bearer 요구·79경로 유지, 시작 완료·ERROR/Traceback/HTTP 5xx 0건을 확인했다. 로컬/공개 무인증 브랜드 요청은 각각 401 AUTH_REQUIRED였다.

관련 검사만 ec2-user·env -i·폐기용 SQLite/모의 외부 연동으로 실행하여 **21 passed / 0 failed / 0 skipped**다. 신규 test_brand_catalog.py 12개(4.86초)는 빈 지점/모든 페이지·미보유/비활성 모델·직접 수량/가격 격리·인증/권한·미설정 가격을 검증했다. 기존 OpenAPI, 선택한 QR 차량 등록 2종, 예약/결제 흐름 2종, 지점 이동 4종의 9개(5.84초)도 통과했다. 기존 TestClient 사용 중단 예정 경고 2종은 남는다. 전체 회귀는 재실행하지 않았다.

실행 대상:

```text
tests/test_brand_catalog.py
tests/test_foundation.py::test_openapi_has_exact_work_group_routes
tests/test_vehicle_qr.py::test_qr_identifies_vehicle_with_optional_sensor
tests/test_nadri_flow.py::test_nadri_reservation_payment_checkout_and_return
tests/test_vehicle_transfer.py
```

현재 실제 DB를 읽기 전용 대조한 공용 브랜드는 Honda/SYM/Yamaha, 활성 모델은 4개다. PUTU'S PLANET의 NRTEST-WEB-MODEL-125 직접 보유수는 조회 시점 2대, 나머지 모델은 0대이고 BASIC 기준 가격은 125cc 25/155cc 35 USD였다. 이번 API 수정 과정에서 차량·브랜드·모델·가격 데이터를 추가/수정하지 않았다.

성공 응답의 업무 계약은 격리 API에서 검증했다. 배포 서버는 헬스/명세/인증 차단 및 원본 카탈로그·직접 수량/가격을 읽기 전용으로 확인했으며, 기존 앱 세션을 보존하기 위해 새 관리자 로그인으로 인증된 실서버 응답 본문을 조회하지 않았다. 앱의 실제 선택 화면과 캐시 갱신은 미검증이다. 프론트가 vehicleCount>0으로 모델을 거르면 그 필터도 제거해야 한다.

## 2026-11-10 신규 초대 코드 8자리·지정 하위 지점 가입 — 서버 적용 완료

신규 지점의 inviteCode 생성은 8자리 대문자 영문/숫자([A-Z0-9]{8})의 암호학적 난수로 변경했다. 후보별 기존 named lock과 실제 DB 비교로 중복을 검사하며 최대 10회 재생성한다. 모두 충돌하면 503 INVITE_CODE_GENERATION_FAILED로 전체 지점 생성 트랜잭션을 롤백한다. 현재 invite_code UNIQUE 인덱스와 utf8mb4_unicode_ci 비교 설정은 유지한다.

변경: management.new_invite_code와 지점 생성 호출, 요청/응답의 영어 필드 설명, 공개 예시(A1B2C3D4), 관련 충돌/소진 회귀 3개. 가입 입력의 기존 1~64자리 계약은 유지하므로 다른 지점의 기존 코드는 계속 유효하다. 가입 성공 시 NULL로 소진하는 기존 원자적 처리와 대표 권한·직접 지점 manage 부여는 유지한다. DB 스키마/env/Firebase 변경이나 재발급 API 추가는 없다.

검증·적용:

- ec2-user·env -i·폐기용 SQLite/모의 외부 연동으로 관련 **19 passed / 0 failed / 0 skipped**, 8.46초. 생성 충돌 재시도, 10회 충돌의 전체 롤백, 8자리 코드의 대표 가입·소진·재사용 거절, 기존 가입/지점 계층·명세 검사를 통과했다. 실제 MySQL 동시 접속 경합은 별도 미검증이다.
- 실행: tests/test_invite_codes.py, tests/test_admin_signup.py, test_management의 nested_spot_creation_requires_profile_and_rejects_duplicate/create_child_persists_normalized_rows_and_rental_sidecar/invalid_child_creation_is_atomic, test_foundation의 openapi_has_exact_work_group_routes.
- RIDERLOG_V2_DATA_TEST의 사용자 지정 PUTU'S PLANET 미사용 코드 1개를 잠금·접근 제한 백업 후 **07:48:01 UTC** 8자리로 교체했다. 다른 지점 코드와 프로필은 변경하지 않았다.
- **07:48:14 UTC** API 재시작 완료(PID 2674508). **07:54:53 UTC** 로컬/공개 health/live·health/ready·OpenAPI 모두 200, 새 8자리 설명·79경로 유지, 시작 완료·ERROR/Traceback/HTTP 5xx 0건 확인.
- 후속 사용자 지시에 따라 지정 하위 지점은 초대 대기에서 실제 대표 가입 완료 상태로 변경했다. 첫 가입 API는 해당 이메일의 기존 누적 시도 7회로 429를 반환해 계정을 생성하거나 코드를 소진하지 않았다. 별도 사용자 승인 후 **해당 이메일의 Redis 가입 횟수 키 1개만** 백업/제거했다. 전역 제한 정책·IP 키·다른 계정 기록은 유지했다.
- **07:54:06 UTC** 정상 POST /nadreego/admin/signup 재시도가 **201 ACTIVE**로 성공했다. 해당 지점 관리자 1명·rental_primary_admin·직접 manage 1개·가입 승인 대기 0건·invite_code=NULL을 실제 재조회했다. 제공된 비밀번호와 저장 해시 일치도 확인했으며 비밀번호는 터미널 비공개 입력으로만 전달했다. 계정 식별 정보·비밀번호·초대 코드 원문은 공개 문서에 남기지 않는다.
- 실제 로그인, 시험 메일/푸시·Firebase 배포·결제/환불은 실행하지 않았다. 부모 PrmBali 계정과 기존 세션/역할은 변경하지 않았다. 보호 백업과 적용 기록은 build/test-runtime/putus-planet-child-2026-11-10 아래 디렉터리 700·파일 600에 보관한다.

프론트는 신규 코드를 8자리로 표시/입력하되 생성 응답의 원문을 전달한다. PUTU'S PLANET은 요청된 계정으로 바로 로그인하는 상태이며, 이전에 전달한 긴 코드와 임시 교체 코드는 가입 성공으로 모두 사용할 수 없다.

## 2026-11-10 알림·이메일 영어 통일 — 서버 반영 완료

사용자 요청으로 백엔드가 생성하는 앱 알림함·FCM의 고정 제목/본문을 영어로 통일했다. 기준은 e811aa124078eff832be3451e214a5c5505ffb9d + 아래 문구 수정이며, 발송 대상·조건·이벤트 코드·data·중복/재시도·읽음 계약은 유지한다. 사용자 채팅·이름·지점명은 번역하지 않는다.

| 전달 경로 | 내용 |
|---|---|
| 예약 요청 푸시 | New reservation request / You have a new rental reservation request. |
| 예약 승인·거절 | Reservation approved / Reservation declined. 현장·외부 결제, 온라인 중단, 기존 온라인 결제 안내의 기존 정책별 분기를 영어로 유지 |
| 차량 인수 확인 | Confirm vehicle receipt. 발리 현지 오늘 자정 전 차량 확인·앱 인수 확정 안내 |
| 결제 기한·만료 | Payment deadline reminder / Reservation canceled. 기존 3일·취소 10% 공제/당일부터 환불 없음 안내 유지 |
| 결제 완료 | Payment complete. 고객·관리자 대상별 본문 유지 |
| 채팅 푸시 | New chat message / You have received a new message. 메시지 내용·개인정보 미포함 유지 |
| 기본 알림함 | You have a new work notification. |
| 업무 인계 알림함 | Tasks have been transferred to the primary administrator after the assigned administrator's account was deleted. |
| 임시 비밀번호 이메일 | 기존 Nadree temporary password 제목·본문이 이미 영어여서 변경 없음 |
| 개인정보 삭제 이메일 | 기존 NadreeGo account deletion request 접수·완료 제목·본문이 이미 영어여서 변경 없음. 메일 성공/실패와 무관한 후속 처리 정책 유지 |

변경 코드는 app/fcm.py·app/chat_push.py·app/notifications.py다. 기존 두 테스트의 한국어 본문 기대치만 영어로 바꿨고 새 테스트 인프라는 추가하지 않았다.

알림함 SQL에는 문구를 저장하지 않고 event_type을 저장한다. 따라서 기존 알림도 목록/읽음 응답을 다시 받으면 영어가 된다. DB 데이터/스키마·env·Firebase 배포 변경은 없다. Firebase 함수는 이벤트 ID를 백엔드로 전달하고 실제 채팅 푸시 문구는 백엔드가 생성한다. 기존 30초 chat_sync·개인정보·인수·채팅 보관 작업과 결제 작업 설정은 유지했다.

### 확인한 결과

- ec2-user·기존 venv·env -i·임시 SQLite/가짜 Firebase·SMTP·PayPal에서 관련 기존 검사만 **58 passed / 0 failed / 0 skipped**(19.77초). 예약/결제 알림, 외부 결제 승인 8조합, 기한 알림, 인수 알림, 채팅 최초 발송/재시도/보안 문맥, 알림 읽음/중복, 관리자 업무 인계, 메일 TLS/오류·접수/완료 선택 발송을 확인했다. 기존 TestClient 사용 중단 예정 경고 2종은 남는다.
- 실행: test_nadri_flow의 직접 지점 수신자·예약/결제 왕복, test_external_reservations의 request_approval_qr_handover_return_without_paypal, test_jobs의 payment_deadline_reminders_and_expiry_notify_once, test_customer_receipt의 two_phase_handover_customer_receipt_and_return, test_chat_push_recovery 전체, test_admin_customer_inbox의 shared_idempotent_and_scoped/event_deduplicated, test_admin_rental_exit의 general_transfers_own_approved_bookings_and_live_rentals_without_canceling_any_data, test_mail 전체, test_deletion_notice_best_effort의 successful_notices_keep_legacy_success_lists_and_attempt_once/mail_failure_does_not_block_withdrawal_erasure_or_receipt.
- **03:24:19 UTC / 발리 11:24:19** nadree-api.service 재시작 완료. ec2-user·/srv/nadree-api·PID 2474625, active/running.
- **03:24:49 UTC** 로컬/공개 health/live·health/ready·Swagger·OpenAPI 8개 모두 200, health 제외 79경로 유지. 시작 완료·이후 ERROR/Traceback/HTTP 5xx 0건. 기존 네 타이머 active 확인.
- 실제 고객 데이터 쓰기, 시험 푸시/이메일·결제·환불 발송/실행은 하지 않았다. 실기기 수신·메일함 표시는 미검증이다.

앱은 기존 필드·eventType/data를 그대로 사용하고 서버가 내려주는 title/body/message를 표시한다. 앱이 자체 한국어 문구를 조합하거나 캐시한 문구를 쓰면 앱 측 영어 처리/새로고침이 필요하다. 이미 기기에 전달된 푸시나 발송 완료된 이메일은 소급 변경·재발송하지 않는다.

## 2026-11-10 차량 QR 실제 삭제·재연결

QR 삭제는 현재 연결을 실제 제거하고 해제된 원문은 다른 차량에도 다시 연결한다. 감사 이력은 보존하되 과거 해시로 재사용을 차단하지 않는다. 기존 차량 등록/조회/센서 삭제 경로는 유지하며 POST /nadreego/vehicle/qr/link(vehicleNumber, qrToken)를 추가한다. 대여·인수/회수 보호·지점 권한을 유지하고 고객 견적·신청 중 재연결 경합을 재검증한다. DB 스키마/env/Firebase 변경은 없다. [프론트 호출 계약](frontend-vehicle-qr-reassignment-2026-11-10.md), [검사·실제 서버 결과](vehicle-qr-reassignment-server-result-2026-11-10.md).

## 2026-11-09 대표 미완료 업무 차단·일반 승인 건 인계 — 발리 01:03 서버 적용 완료

대표 즉시 DELETE는 본인·모든 하위 지점에 미완료가 있으면 409 DELETION_OBLIGATIONS_REMAIN으로 거절한다. 기존 개인정보 요청은 접수 후 대기하며 실제 삭제는 하지 않는다. 일반의 승인 미완료 건은 대표에게 인계하고 예약·렌트·차량·결제는 취소/삭제하지 않는다. 이력·지점 인계 알림을 추가하며 별도 DB 변경은 없다. [확정 정책·API·서버 명령·검증](admin-withdrawal-handover-2026-11-09.md).

`05f5e12` + 완료 상태/실제 반납 시각을 함께 확인하는 로컬 보완으로 **2026-11-08 17:03:49 UTC / 발리 11월 9일 01:03:49** 적용했다. ec2-user 지정 6파일 110개 통과·MySQL 1개 건너뜀, 보완 인계 17개(기존 8개 중복) 통과다. API 재시작·8개 헬스/명세 응답 200·78경로, 개인정보 배치 새 코드 정상 실행 및 원래 일정 복구, 기존 결제/인수/채팅과 env/stash 보존을 확인했다. 지정 branch2는 미완료 렌트·예약·환불 0건이라 변경하지 않았다. 기존 삭제 요청은 안내 단계 재시도 후 CONTACT_OPERATOR 상태이며 삭제 시험 가능 상태로 초기화하지 않았다. 실제 계정 삭제/SMTP/Auth·앱·MySQL 경합은 별도다. [실제 적용·미검증·지점 결과](admin-withdrawal-server-result-2026-11-09.md).

## 2026-11-06 관리자 개인정보 요청 — 08:16 UTC 서버 적용 완료

비동기 4개 API, Firestore 작업 기록·중복 방지·영수증 조회·범위 재확인·업무 대기·재시도·완료 안내를 추가했다. 기존 DELETE는 유지한다. 완료 최소 기록은 30일이고 실패/대기 작업은 보존한다. 새 SQL 테이블 없이 기존 지점에 유입 차단 포인터 1컬럼을 추가한다. 여권 업로드/조회 등록만 주석 처리했다. [필드별 처리·DB/배치 적용·운영 절차](admin-privacy-server-apply-2026-11-06.md), [앱/웹 전달](frontend-admin-privacy-handoff-2026-11-06.md)를 먼저 확인한다. 아래 04:08 서버 완료 기록은 이전 90일 채팅 정리의 결과다.

사용자 전체 적용·자동 처리 승인 후 `73564d4` + 서버 로컬 보완으로 반영했다. 기존 DELETE 우회·상위 대표의 닫는 하위 지점 변경·SELF/SUBTREE 중첩을 차단하고 관련 회귀를 추가했다. 테스트 DB의 지점 테이블 백업·컬럼 1개 적용·잔여 계획 0개, **08:16:24 UTC API 재시작**, 공개/로컬 헬스·준비·Swagger 정상·78개 경로·여권 404를 확인했다. 5분 개인정보 배치를 활성화했고 최초 작업은 **처리/실패 0건**이다. 관련 검사만 선별했으며 최종 보완 **46 passed/1 skipped**, 별도 Firestore 3개 통과다. 기존 데이터·env·결제/채팅/인수 작업과 stash를 보존했다. 실제 삭제/메일·MySQL 동시성·앱 공동 검증·실제 보관 정책 확인은 미검증이다. [서버 결과](admin-privacy-server-result-2026-11-06.md).

## 2026-11-06 반납 완료 90일 채팅 삭제 — 04:08 UTC 서버 적용 완료

실제 반납 완료 actual_end_time에서 90일 경과한 RETURNED 계약/예약만 SQL에서 선택해 연결된 예약 채팅방·messages·reads·chatPushEvents를 매일 정리한다. 진행/연체·취소/거절/만료·일반 문의는 제외하고 SQL 업무 이력은 보존한다. 기존 bookingChatAccess에 내용 없는 삭제 표시를 남겨 chat_sync의 재생성과 새 문의 소비를 차단한다. 실패 시 남은 하위 문서를 다음 실행에 이어 정리한다. 기본 명령은 읽기 전용 계획이며 새 SQL/컬렉션/env/Rules/인덱스는 추가하지 않는다. [정책·검증·서버 실행서](chat-retention-90-days-2026-11-06.md). 아래 자동 정리 제외 결정 중 이 범위만 사용자 요청으로 변경한다.

사용자 승인 후 `167f25b` 기준 **bail-472405/asia-southeast2의 ensureBookingChat·sendChatMessage·markChatRead·getChatUnreadSummary 4개** 업데이트·원격 소스 12/12 해시 일치와 보존 함수 3개 설정 유지를 확인했다. **04:08:33 UTC API 재시작**·구 chat_sync 종료/새 일정 재개 후 발리 **04:15** 일일 retention 타이머를 활성화했다. 최초 --apply는 **대상 0·삭제 0·실패 0**, 다음 일정은 11월 7일 발리 04:15다. 로컬/공개 헬스·준비·Swagger/OpenAPI 200·76개 경로와 기존 작업/env 보존을 확인했다. 격리 전체 **622 passed/16 skipped**, 별도 Firestore **5 passed**; 남은 MySQL 11개·실제 만료 방 삭제·앱/App Check 종단은 미검증이다. [실제 적용·검증 결과](chat-retention-server-result-2026-11-06.md), [앱 담당자 전달](frontend-chat-retention-handoff-2026-11-06.md).

관리자 탈퇴 프론트 전달용: [신규 DELETE 연결·권한별 범위·성공/오류·앱/웹 시험](frontend-admin-account-deletion-handoff-2026-11-05.md).

## 2026-11-05 관리자 본인 요청 탈퇴·하위 지점 삭제 — 11:16 UTC 서버 반영 완료

신규 `DELETE /nadreego/admin/account`는 대상 ID 없는 본인 요청이다. 현재 일반관리자는 본인만, 대표관리자는 **대표 본인과 본인 지점·모든 하위 지점 관리자 전원**을 탈퇴시키고 해당 지점을 논리 삭제한다. 동일 계약·회사·계층 경계로 제한하고 상위/형제/다른 회사 지점은 유지한다. 렌탈 역할·본 서비스 세션·채팅·FCM을 회수하고 공유 관리자 식별 행·다른 서비스 권한·예약/차량/결제 이력을 보존한다. 기존 직원 지정 삭제 API는 유지한다. 추가 DB/env/Firebase 배포는 없다. 추가 테스트 16개·전체 회귀 **604 passed/15 skipped**이며 Swagger·API 엑셀도 반영했다. [요청·응답·실패/앱 처리·배포 안내](admin-account-deletion-handoff-2026-11-05.md)를 따른다. 아래 11월 3일 실제 배포 기록은 이 신규 API의 배포를 뜻하지 않는다.

`f8b73b1`로 ff-only 업데이트 후 관련 16개·전체 604개 격리 검사 통과를 확인하고 **2026-11-05 11:16:32 UTC** API를 1회 재시작했다. PID 1622907·active/running, 로컬/공개 live·ready·Swagger/OpenAPI 200, 실제 DELETE 경로와 health 제외 76개 경로를 확인했다. env 원문·소유권·0600 및 기존 결제/receipts/채팅 작업은 보존했다. 실제 계정·지점 삭제 요청은 실행하지 않았고 MySQL 잠금·Firebase 회수·앱 연동은 별도 미검증이다. [실제 적용·검증 결과](admin-account-deletion-server-result-2026-11-05.md).

## 2026-11-03 추가 인수서 반영 — 07:35 UTC 실제 서버 전환 완료

인수 ON/OFF와 즉시 대여 분기를 제거하고 receiptRequired=true를 유지한다. 사용자 양 앱 준비 완료·즉시 배포 승인 후 구 API 드레인/종료 → 테스트 DB 새 전체 백업 → MSP_RENTAL_ONSITE_REQUEST 테이블 1개 적용 → 구 OFF env 항목만 제거 → 새 API 시작을 완료했다. 커밋 `254507d`·PID 3661271이며, 실제 헬스/준비/Swagger 정상·75개 경로/close·잔여 마이그레이션 0개·기존 예약 29건과 결제/QR 보존을 확인했다. 접수·확정 거절·처리 중·불명 상태와 명시적 close, 관리자 ID/기한/액션, NDR 원문을 제공한다. 동일 소스 격리 회귀 588 passed/15 skipped·실패 0이며 QR_ONLY 시험 차량 2대의 실제 등록·조회도 완료했다. 실기기·실제 고객 업무 공동 시험은 별도다. [최신 계약](qr-onsite-followup-contract-2026-11-03.md), [서버 실행서](qr-onsite-final-server-apply-2026-11-03.md), [실제 배포·검증 결과](qr-onsite-final-server-deployment-result-2026-11-03.md)를 우선한다. 아래 false 유지 결과는 이전 코드의 실제 적용 기록이다.

프론트 전달용: [QR 현장 신청·고객 인수 연결과 테스트 순서](frontend-qr-onsite-receipt-handoff-2026-11-03.md). URL # 뒤의 동일 NDR 원문을 프론트가 추출해 qrCode로 전달한다. 현재 서버는 인수 상시 필수이며 추가 활성화 env 설정은 없다. 시험용 QR_ONLY 차량 2대는 실제 등록됐다.

## 2026-11-03 공용 QR 현장 신청·고객 인수 — 서버 적용 완료, 기능 비활성 유지

고객 QR 조회·당일 견적/멱등 신청·접수 결과 조회·인수 확정, 관리자 보호 차량 회수와 Swagger 예시를 추가했다. 기존 QR 원문·대소문자를 그대로 사용한다. 관리자 인계는 HANDOVER_PENDING, 고객 확정 후에만 HANDED_OVER/ON_RENT다. 기한 초과 시 EXPIRED여도 배정·DISABLED 보호를 유지하고 직원 실물 회수 후 해제한다. 현장 신청은 EXTERNAL이다.

2026-11-03 `e31008c` 기준으로 테스트 DB 76개 테이블 전체 백업 후 예약 nullable 3컬럼·인덱스 2개·상태 CHECK를 적용했다. ec2-user의 app.migrate 재계획은 잔여 0개이며 기존 예약 29건을 보존했다. **02:44:38 UTC API 재시작 완료**, 로컬/공개 live·ready·Swagger/OpenAPI 200·신규 경로 6개의 인증 차단을 확인했다. 전용 receipts 타이머를 설치했고 02:54 점검까지 자동 완료 9회·만료 0개였다. 기존 결제 cron·채팅 작업은 유지했다. 전체 격리 회귀 **572 passed/14 skipped**, 실패/오류 0개. `.env`와 실제 프로세스의 **NADREE_CUSTOMER_RECEIPT_ENABLED=false**를 유지한다. 앱 공동 검증·실기기 FCM/App Check·MySQL 동시성/Firestore 에뮬레이터는 별도다. 기존 진행 계약은 재확인하지 않는다. stash의 이전 서버 작업 기록과 새 QR 변경을 통합했고 stash는 삭제하지 않았다. [최신 API·적용/복구 안내](qr-onsite-receipt-handoff-2026-11-03.md)와 [실제 적용·미검증·남은 작업](qr-onsite-receipt-server-result-2026-11-03.md)을 우선한다.

## 2026-10-28 신규 예약의 현장·외부 결제 전환 — 07:50 UTC 최신 env 재검증 완료

이번 사용자의 정책 변경은 신규 예약을 `paymentMethod=EXTERNAL`로 저장하고 관리자 승인으로 확정하는 방식이다. 현장 수납·외부 환불은 지점에서 별도로 관리하며 가짜 PAID/capture/0원 결제 기록은 만들지 않는다. 기존 가격·배송·재고·권한·QR·인계·반납·채팅을 유지한다. 기존 JSON을 사용하므로 추가 DB 마이그레이션·데이터 이전은 없다.

기본 `NADREE_RESERVATION_PAYMENT_METHOD=EXTERNAL`, `NADREE_PAYPAL_CHECKOUT_ENABLED=false`이며 신규 현장 예약에는 판매자 연결·온라인 결제·결제 기한·미결제 만료·결제 유도 알림을 요구하지 않는다. 방식 정보 없는 과거 예약은 PAYPAL로 유지하고 기존 거래·웹훅·정산·필요한 환불은 보존한다. 온라인 중단 중에는 구버전 앱의 주문·capture·재시도·온보딩도 서버에서 차단하고 기존 결제 GET은 DB만 조회한다. 이후 재활성화해도 과거 현장 예약의 방식은 바꾸지 않는다.

고객 요청/목록/상세에 결제 방식·온라인 가능 여부를 추가하고 현장 예약의 `paymentStatus`/`payment`는 null을 허용한다. 관리자 목록·캘린더는 실제 인계 조건에 맞춰 `canHandOver`, `handoverBlockedReason`, `RENT_APPROVE`를 제공한다. 아래 과거 온라인 전용 결제 안내는 PAYPAL 예약과 온라인 기능 활성화 조건에서만 사용한다.

최종 격리 회귀 **550 passed/12 skipped** 후 07:03 UTC 최초 적용했고, 사용자가 `.env`에 정책 2개를 명시한 뒤 요청한 07:22 UTC 반영 후, 최신 env 업데이트 요청으로 **07:50 UTC 재시작을 완료**했다. PID 2660137·active/running, 명시 env의 새 프로세스 전달·로컬/공개 live·ready·Swagger·OpenAPI 200·실제 availability의 EXTERNAL/온라인 중단 응답을 확인했다. 기존 채팅 인증 설정은 실제 배포 함수와 일치하며 동일 중복 3줄을 정리했다. 정상 서비스 토큰의 수동 콜백 검증은 07:50에는 조회 계정 권한이 없어 보류했으나, 사용자 권한 추가 후 08:17에 토큰 발급과 실제 콜백 HTTP 200/processing=missing을 확인했다. 새 이벤트·데이터 쓰기·푸시는 0개이며 이번 수동 인증 확인과 기존 트리거 종단 검증은 구분한다. 기존 테스트 두 지점에 예약 가능 옵션도 확인했다. 실제 계정 로그인·예약 쓰기·PG 청구/환불·Firebase 배포·시험 푸시는 실행하지 않았으며 기존 설정·채팅·정산 cron은 보존했다. 기존 계정으로 신규 예약부터 테스트할 수 있다. 인계는 예약 기간에만 가능하다. [앱 담당자용 변경 계약과 요청 예시](external-payment-app-handoff-2026-10-28.md), [구현·실제 적용·미검증·복구 범위](external-payment-implementation-result-2026-10-28.md)를 우선한다.

## 2026-10-22 02:48 UTC 최신 적용 — 자동 정산 복구 cron·8번 PAID 확인

새 예약 `8e217b09-9760-4ec1-aeb4-dc2fa933fb54`·결제 8번은 PayPal USD 90 캡처 COMPLETED였으나 웹훅 미반영·자동 복구 미등록으로 PENDING/WAIT에 머물렀다. 사용자 요청으로 cronie를 설치하고 정산 복구 전용 cron을 매분 ec2-user로 등록했다. 02:47 첫 실제 cron 실행 checked=1/failed=0 및 SQL PAID·API_QUERY/PROCESSED를 확인했고, 02:48 고객 인증 API도 PAID/DONE/canCapture=false를 반환했다. 현재 진행 목록은 이 신규 8번 한 건이며 앞선 7번은 취소/환불 이력이다.

등록 파일은 `/etc/cron.d/nadree-payment-recovery`, 원본은 `deployment/nadree-payment-recovery.cron`이다. Sandbox·RIDERLOG_V2_DATA_TEST를 명시적으로 고정하고 flock·기존 MySQL 결제 잠금으로 중복을 차단했다. 완료 캡처만 조회 증거로 반영하며 추가 청구·PG 환불·예약 만료·푸시는 실행하지 않는다. 전체 payments 타이머는 함께 설치하지 않았다. API 재시작 없이 PID 326499를 유지했고 다른 결제/예약·기존 식별자/금액/요청 시각은 보존했다. 최신 격리 회귀는 398 passed/12 skipped다. 실제 서명 웹훅 전달 원인은 여전히 미확인이다. [원인·설치·실제 검증·운영/중단 방법](payment-recovery-cron-deployment-2026-10-22.md)을 우선한다.

## 2026-10-22 01:47 UTC 최신 상태 — 7번 관리자 취소·전액 환불·진행 0건

결제 흐름 검증 후 사용자의 정리 요청으로 테스트 결제 7번·예약 `35b12620-7ae0-4bfd-b23f-cd075229ea7b`를 정상 관리자 CANCEL API에서 취소했다. 취소 API HTTP 200·ADMIN_REFUND_100_PERCENT, 서버의 기존 환불 처리 1회 및 PayPal 환불 상세 GET 200/COMPLETED·USD 90.00을 확인했다. 현재 예약 CANCELED·재고 RELEASED, 결제 REFUNDED·refundStatus=COMPLETED다.

승인된 동일 고객으로 실제 공개 API를 호출해 결제 REFUNDED/DONE/canCapture=false·예약 상세 CANCELED/REFUNDED·`/ongoing`의 totalCount=0/items=[]·`/completed`의 취소/환불 이력 보존을 확인했다. 이는 01:47 당시 진행 중인 예약/렌탈이 없었다는 검증 결과다. 이후 신규 8번을 생성해 현재 상태는 위 최신 절을 따른다. 5·6·7번은 취소 이력이며 기존 승인 링크·캡처 테스트 대상으로 사용하지 않는다. 아래 01:40 PAID/DONE은 환불 전 검증 이력이다.

접근 제한 백업 후 수행했고 다른 결제 행·기존 주문/캡처/판매자·요청 시각·결제 시각·이력은 보존했다. 추가 캡처·주문·전체 환불 작업·서비스 재시작·설정/스키마·Firebase 변경은 없다. 실제 서명 웹훅 수신 검증의 기존 제한은 유지한다. [취소·환불·실제 API 확인 근거](reservation-payment-system-test-2026-10-22.md)의 최신 절을 우선한다.

## 2026-10-22 01:40 UTC 최신 적용 — 결제 7번 PAID/DONE 확인

사용자 승인으로 복귀 GET·캡처 JSON 보완을 서비스에 반영하고 `nadree-api.service`를 1회 재시작했다. PID 326499, active/running, local live/ready·public live·복귀/취소 복귀·OpenAPI가 모두 HTTP 200이다. 실제 Sandbox capture API도 HTTP 200이며 PayPal에서 USD 90·COMPLETED 캡처 1건을 확인했다. 기존 주문·`nadree-capture-7`·최초 요청 시각을 유지했다.

웹훅을 기다리던 SQL PENDING은 **7번만 기존 PG 조회 복구로 PAID/paid_at 반영**했다. 이 근거는 API_QUERY/PROCESSED이며 실제 서명 웹훅 수신과 구분한다. 01:40:55~01:40:59 UTC 승인된 테스트 고객으로 공개 API를 호출해 `/payment/7`의 `paymentStatus=PAID`, `nextAction=DONE`, `canCapture=false` 및 예약 상세 `item.payment.paymentStatus=PAID`·`item.paymentAvailability=PAID`를 확인했다. API만으로 최종 결과를 검증했으며 앱 화면은 필요하지 않았다.

이 검증 당시 대상은 7번·예약 `35b12620-7ae0-4bfd-b23f-cd075229ea7b`였고 결제 완료로 확인했다. 이후 01:46 사용자 요청으로 위 최신 절의 취소/환불까지 마쳤으므로 현재는 환불 이력으로 표시한다. 추가 capture나 새 order를 호출하지 않는다. 당시 PAID 상태의 `paypalOrderStatus=null`은 해당 상태 GET에서 PayPal을 재조회하지 않은 결과이며, 별도 PG 조회는 COMPLETED였다. 인계/렌탈 시작은 실행하지 않았다.

수정 후 격리 회귀 **386 passed / 12 skipped / 0 failed**, 관련 회귀 63개 통과다. 실제 서명 웹훅 전달·자동 정산·실기기 복귀/App Check/푸시 수신·실제 환불은 미검증이다. 기존 웹훅 URL·15개 구독은 일치하며 완료 이벤트 지정 재전송 1회는 202로 접수됐지만 수신 근거는 없다. 전체 결제 복구/환불 작업이나 타이머를 실행·설치하지 않았고 다른 결제 행·해당 예약 행은 보존했다. API_QUERY 복구에 따른 내부 알림함 1건 외 추가 주문·캡처·환불·푸시는 없다. 환경 설정·스키마·Firebase 변경도 없다. [시각별 실제 결과·근거·프론트 요구사항](reservation-payment-system-test-2026-10-22.md)을 우선한다.

## 2026-10-22 복귀 경로·캡처 요청 보완 — 코드 작성 당시 기록

사용자 요청으로 고정 GET `/api/v1/nadree/rental/payment/return`을 추가했다. 승인/취소 브라우저 복귀에 공개 HTTP 200 HTML 안내를 제공하며, 쿼리로 결제를 완료하거나 자동 캡처하지 않는다. 기존 앱의 URL 감지 → 고객 인증 상태 조회 → 명시적 capture 흐름은 유지한다. 캡처 요청은 빈 JSON 본문과 application/json 헤더를 전송하도록 보완했고 기존 주문·요청 키·판매자 인증·재시도 제한을 보존했다.

관련 격리 회귀 63개 통과. 코드 작성 단계에는 실행 중 API 재시작과 결제 7번의 실제 재시도를 하지 않았으며, 이후 사용자 승인에 따른 반영·실연동 완료 결과는 위 01:40 최신 절과 [검증 문서](reservation-payment-system-test-2026-10-22.md)를 따른다. 아래 실패/미수정 기록은 코드 수정 전 시점이다.

## 2026-10-22 01:09 결제 7번 실연동 실패 — 수정 전 진단 이력

PayPal 구매자 승인은 APPROVED로 확인됐고 구매자와 판매자는 다르다. 승인 후 브라우저가 `/payment/return`으로 복귀하면 해당 고정 GET이 없어 숫자 결제 ID 경로에서 422 INVALID_INPUT이 발생한다. 별도 승인 범위의 실제 capture 1회는 백엔드 500/PayPal 415 UNSUPPORTED_MEDIA_TYPE로 실패했고, 현재 capture POST의 JSON Content-Type 누락을 확인했다. 7번은 SQL PENDING·캡처 ID/paid_at 없음, PG APPROVED·캡처 0건이다. 코드는 아직 미수정이고 추가 캡처·새 주문·재시작은 하지 않았다. [최신 결과와 수정안](reservation-payment-system-test-2026-10-22.md)을 우선한다.

## 2026-10-22 신규 예약·결제 7번 검증 진행

사용자 승인으로 결제 5번 고객의 기존 예약을 모두 정상 취소했고 ongoing=0 확인 후 새 테스트 예약과 **결제 7번**을 만들었다. 프론트 테스트 대상은 예약 `35b12620-7ae0-4bfd-b23f-cd075229ea7b`·결제 7번(USD 90)이다. 초기 실제 API 응답 검사 30개와 격리 회귀 377개는 통과했고 별도 MySQL/Firestore 12개는 건너뛰었다. 생성 당시에는 PAYER_ACTION_REQUIRED/APPROVE·승인 URL 제공이었으며 이후 승인·캡처·최종 PAID는 위 최신 결과를 따른다.

capture API는 성공 시에도 PENDING·캡처 ID를 우선 저장할 수 있고, 최종 PAID/paid_at은 검증된 웹훅 또는 PG 조회 복구로 확정한다. 프론트는 APPROVE에서 구매자 승인, CAPTURE/canCapture=true에서 같은 결제 capture, PENDING/WAIT에서 상태 조회, PAID/DONE 확인 후 완료 표시한다. [실제 검사·대기 상태·프론트 요구사항](reservation-payment-system-test-2026-10-22.md)을 참고한다. 아래 5·6번은 취소 이력으로 유지하며 사용하지 않는다.

## 2026-10-22 테스트 결제 6번 취소 완료

사용자 요청으로 정상 관리자 API에서 테스트 결제 6번과 연결 예약을 취소했고 HTTP 200 및 실제 DB CANCELED를 확인했다. 배정 재고를 해제했으며 기존 기록은 보존했다. 환불·캡처·새 예약·새 주문은 실행하지 않았다. **5번과 6번 모두 취소 상태이므로 이전 승인 링크나 캡처 테스트 안내는 사용하지 않는다.** 이는 서버 예약·결제 취소이며 PayPal 원격 주문 VOID 성공을 의미하지 않는다. 상세는 [서버 검증 결과](server-requirements-verification-2026-10-19.md)의 2026-10-22 취소 완료 절을 참조한다.

## 2026-10-20 테스트 결제 대상 변경

사용자 승인으로 기존 테스트 예약과 결제 5번을 정상 취소했다. 기존 주문·요청·예약 이력은 보존했고 환불은 발생하지 않았다. 같은 고객·2026-10-31~2026-11-02·PREMIUM·픽업·USD 90 조건의 새 예약 요청과 관리자 승인, Sandbox 주문 생성은 실제 API에서 모두 200을 확인했다. 이후 프론트 테스트 대상은 **결제 6번**, 새 예약 `a70ec730-4b8d-4bdd-b075-f2ac4611bd72`다.

2026-10-20 15:01 UTC 기준 SQL CREATED, PayPal PAYER_ACTION_REQUIRED, nextAction=APPROVE이며 새 승인 링크가 제공된다. 구매자 승인·캡처·환불은 이번 작업에서 실행하지 않았다. 기존 5번 캡처를 재시도하지 않고 6번의 새 승인 링크를 사용한다. 구매자 승인 후에도 결제 확정으로 표시하지 말고, 본인 상태 API의 nextAction/canCapture에 따라 별도 capture 단계를 진행한다. [실제 적용·검증 결과](server-requirements-verification-2026-10-19.md)를 참고한다. 아래의 이전 5번 프론트 테스트 안내는 이 기록으로 대체한다.

## 2026-10-20 결제 단계 안내·캡처 재시도 보완 — 구현/격리 검증, 실제 캡처 미실행

**서버 반영 완료:** 사용자 승인으로 API를 재시작했고 PID 10470, active/running 및 `/health/live` HTTP 200을 확인했다. 아래 코드 변경이 실행 중 서비스에 반영됐다. 결제 5번의 실제 캡처는 서버에서 실행하지 않았으며 프론트 테스트로 남겼다. 프론트는 먼저 본인 결제 GET 상태를 조회해 `nextAction`/`canCapture`를 확인하고, CAPTURE/RETRY_CAPTURE일 때만 같은 paymentId로 명시적으로 호출한다. REVIEW/WAIT/NONE을 새 주문 생성이나 상태 초기화로 우회하지 않는다. 이 반영 결과가 아래의 이전 “재시작 미실행” 기록보다 우선한다.

결제 order/capture/status 응답에 기존 필드를 보존하면서 다음 필드를 추가한다.

- `paypalOrderStatus`: 이번 응답 처리에서 PayPal 조회/응답으로 확인한 주문 상태. 확인하지 못했으면 null이다. SQL의 `paymentStatus`와 구분한다.
- `nextAction`: 아래 표의 다음 동작. `approvalUrl`이 null이라는 이유만으로 캡처 가능을 추정하지 않는다.
- `canCapture`: `CAPTURE`/`RETRY_CAPTURE`일 때만 true. 후속 capture API는 소유권·판매자 권한·기한·상태를 다시 검사하므로 최종 성공을 보장하는 필드는 아니다.

| nextAction | 프론트 처리 |
| --- | --- |
| APPROVE | 응답의 approvalUrl로 구매자 승인 화면을 연다. |
| CAPTURE | 같은 paymentId로 POST `/api/v1/nadree/rental/payment/capture`를 호출한다. 새 주문을 만들지 않는다. |
| RETRY_CAPTURE | 승인 완료·캡처 미확인 상태이며 5시간 재시도 범위다. 같은 paymentId로 명시적 재시도한다. 서버는 같은 PayPal 요청 키를 사용한다. 무한 자동 재시도하지 않는다. |
| WAIT | GET `/api/v1/nadree/rental/payment/{paymentId}`로 상태를 확인한다. order API를 반복하거나 새 결제를 만들지 않는다. |
| DONE | 서버에서 PAID/PARTIALLY_REFUNDED/REFUNDED 상태가 확인됐다. 해당 결제/환불 상태에 맞춰 표시한다. |
| REVIEW | 재시도 기한 초과·판매자/리소스 불일치 등 운영 대조가 필요하다. PENDING 초기화·새 요청 키로 우회하지 않는다. |
| NONE | 종료/비활성 상태 또는 결제 기한 초과 등으로 현재 결제 동작을 제공하지 않는다. |

상태 조회는 본인 소유 확인 후, SQL이 CREATED/PENDING이고 주문 ID가 있지만 캡처 ID가 없는 건만 기존 주문을 PayPal에 **GET 조회**한다. 다른 결제 상태는 기존 SQL 기준 응답을 유지한다. 조회 중 주문 생성·캡처·환불·정산 DB 수정은 하지 않는다. 이 PayPal 조회가 필요한 경우 고객별 30회/분 제한이 적용되므로 폴링 간격은 최소 5초를 권장한다. 조회 실패는 WAIT/canCapture=false, 판매자·리소스 불일치는 REVIEW다. PayPal에 이미 캡처/완료가 있으면 추가 캡처 권한을 주지 않고 기존 웹훅/복구 반영을 기다린다. `paypalOrderStatus=COMPLETED`를 관측해도 SQL이 미정산이면 서버의 최종 PAID 확인 전 완료로 표시하지 않는다.

기존 `canPay`/`cannotPayReason` 의미는 바꾸지 않는다. PENDING에서는 기존 canPay=false/PAYMENT_IN_PROGRESS여도, PG에서 APPROVED·캡처 없음이 확인되고 재시도 조건이 맞으면 nextAction=RETRY_CAPTURE/canCapture=true가 나올 수 있다. 이는 기존 결제의 같은 키 재시도이며 새 결제 허용이 아니다.

최초 capture_requested_at/PENDING 기록 전에 PayPal 승인 상태 및 판매자 권한을 검사한다. 승인 전 요청·사전 조회/권한 실패는 새 PENDING 체크포인트를 남기지 않는다. 실제 캡처 직전에는 기존 체크포인트와 상태 재검증을 유지한다. 외부 요청이 시작된 후 결과 불명/타임아웃이면 같은 paymentId와 요청 키로만 5시간 안에 재시도한다. 기한은 최초 capture_requested_at 기준이며 성공 시각으로 새로 시작하거나 수동 초기화하지 않는다. 자동 캡처 작업은 추가하지 않았다.

PayPal 실패 로그에는 HTTP 상태·error_code·PayPal Debug ID만 기록한다. 요청 URL/헤더, Client ID·Secret·access token, 요청/응답 본문, 개인 식별자 및 예외 원문은 기록하지 않는다. 원격 HTTP 오류, 통신 오류, 잘못된 JSON 응답을 구분하고 후자의 두 경우는 고정 진단 코드를 사용한다. 사용자 API의 기존 오류 코드/응답 형식은 유지한다.

DB·env·기존 결제/주문·리턴 URL은 변경하지 않는다. 추가 리턴 URL은 필요 없다. 실제 결제 5번의 캡처/환불 재시도와 서비스 재시작은 이번 코드 수정에 포함하지 않았다. 적용 상태와 격리 테스트 결과는 [서버 검증 결과](server-requirements-verification-2026-10-19.md)의 최신 결제 단계 보완 절을 참조한다.

## 2026-10-20 APPROVED 주문 재사용 시 승인 URL 오류 보완

`POST /api/v1/nadree/rental/payment/order`에서 PayPal 주문 상태가 `APPROVED`이면 승인 URL을 필수 추출하지 않고 기존 결제 정보와 `approvalUrl: null`을 반환한다. 기존 주문 재사용과 신규/동일 요청 재처리 응답 경로에 모두 적용했다. 승인 전 `CREATED`/`SAVED`/`PAYER_ACTION_REQUIRED`의 승인 링크·호스트 검증은 유지한다. 서버 결제 상태를 PAID로 바꾸거나 자동 capture하지 않으며 실제 결제 확정은 기존 별도 capture API와 상태/웹훅 검증을 사용한다. 프론트는 승인 URL이 없는 승인 완료 응답에서 PayPal 승인 화면을 다시 열지 않는다. API 필드·DB 스키마 변경은 없다.

관련 격리 회귀 75개 통과. 이 변경은 코드 수정·격리 검증까지 완료했으며 서비스 재시작·실제 PayPal 주문/캡처 재시도는 수행하지 않았다. 상세는 [서버 검증 결과](server-requirements-verification-2026-10-19.md)의 APPROVED 주문 보완 절을 참조한다.

## 2026-10-20 고객 PayPal 결제 복귀 URL — 로컬 구현, 서버 적용 전

고객 결제의 복귀 기준 주소를 `https://na-dree.com/api/v1/nadree/rental/payment/return`으로 확정했다. 관리자 판매자 연결 복귀 주소와 별개다. 신규 PayPal 주문의 `payment_source.paypal.experience_context.return_url`에 이 값을, `cancel_url`에는 같은 주소에 `?cancelled=true`를 붙인 값을 전달한다. `application_context` 대신 현재 PayPal 권장 필드를 사용하며, `payer-action`/기존 `approve` 링크 모두 기존 응답의 approvalUrl로 제공한다.

- 기본 주소는 코드에 설정했다. 필요 시 `.env`의 `NADREE_PAYPAL_PAYMENT_RETURN_URL`에 같은 값을 명시할 수 있다. query/fragment/사용자정보 없는 HTTPS 주소를 사용한다. 미설정은 기본값을 사용하지만 명시적 빈 값·잘못된 설정은 신규 주문 생성 시 `503 PAYPAL_PAYMENT_RETURN_URL_REQUIRED`로 차단한다. 실제 `.env`는 이번 작업에서 수정하지 않았다.
- 프론트는 고객 WebView에서 같은 origin/path로의 이동을 감지한다. 취소 복귀는 `cancelled=true`로 구분하고 캡처하지 않는다. 결제 화면 취소가 예약 취소를 뜻하지 않으므로 `/request/cancel`을 자동 호출하지 않는다.
- 승인 복귀에서 PayPal query의 token을 시작 시 보관한 paypalOrderId와 대조하고, 보관한 paymentId로 기존 `POST /api/v1/nadree/rental/payment/capture`를 호출한다. 고객 인증이 필요하며 URL에 access/refresh 토큰을 넣지 않는다. URL만으로 결제 성공을 판단하지 않고 서버의 capture 응답과 결제 상태 조회로 확인한다.
- 이 주소는 앱이 감지하는 복귀 목적지다. 새로운 GET 완료/캡처 API나 홈페이지를 생성하지 않는다. 일반 브라우저에서 직접 열어 결제를 확정하는 주소가 아니므로 WebView의 이동 감지·취소/실패 처리를 확인한다.
- 이미 생성한 주문을 재사용하면 이전 주문의 복귀 설정이 남을 수 있다. 이번 설정은 신규 생성 주문부터 적용된다. 테스트를 위해 기존 주문을 임의 삭제하거나 중복 청구를 만들지 않고 지정된 새 테스트 예약/결제 시도로 확인한다.
- 서버 적용은 변경 코드 반영 후 기존 API 재시작이다. DB 마이그레이션·Firebase 배포는 추가하지 않는다. 관리자 판매자 연결용 `NADREE_PAYPAL_ONBOARDING_RETURN_URL` 설정은 별도로 유지한다.

공식 명세: [PayPal Create order](https://developer.paypal.com/api/orders/v2/orders-create). 공개 API 검색에서 해당 주문 생성 계약도 대조했다. Postman CLI 미로그인으로 공급자 소유 모의 서버 검색은 완료하지 못했으며, 이 명세의 OAuth/주문 생성 부분을 로컬 모의 서버로 구성했다.

검증: 관련 격리 테스트 66개 통과, 최신 전체 회귀 **352 passed, 12 skipped**(별도 MySQL·Firestore), 기존 의존성 경고 2개. 실제 PayPalClient가 로컬 HTTP 모의 서버로 OAuth 200·주문 생성 201 요청을 보냈고 두 복귀 주소 및 payer-action 처리를 확인했다. 실행 로그의 요청 2건을 확인한 뒤 모의 서버를 종료했다. 실제 PayPal Sandbox 왕복·기기 복귀·구매자 승인/캡처 성공은 아직 검증하지 않았다. 전체 실행은 `env -u NADREE_TEST_MYSQL_URL -u FIRESTORE_EMULATOR_HOST PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests -q -p no:cacheprovider --tb=short`이며 git diff --check도 통과했다.

재현용 파일: `postman/simulations/paypal-payment-return.sim.yaml`, `postman/mocks/paypal-payment-return.js`. `postman simulation run postman/simulations/paypal-payment-return.sim.yaml --port 4927 --no-history --output ndjson`으로 가짜 OAuth/주문 API만 실행한다. 로컬 테스트 클라이언트의 base_url을 `http://127.0.0.1:4927/paypal/`로 바꿔 호출한다. 운영 endpoint/실제 키로 이 모의 서버를 호출하지 않는다.

## 2026-10-18 최신 변경 — 프론트 전달 및 서버 적용

이 절이 아래 과거 정책·2026-10-16 수동 판매자 설정 문서보다 우선한다. **로컬 구현이며 서버 DB·실제 PayPal·Firebase에는 미적용**이다. 회사별 BASE 관리, 주소의 실제 배송구역 자동 판정, 가입코드 추가 발급/재발급은 이번 범위에서 제외한다.

### 프론트에 전달할 확정 정책

- BASE는 서비스 공통 기본 cc 가격이다. 약 4개 큰 구간을 운영 정책으로 정할 예정이며 이번 코드가 임의 가격이나 구간을 새로 생성하지 않는다.
- BASIC은 해당 지점의 cc 구간만 BASE보다 우선한다. 예: BASE 1~50cc/10 USD와 BASIC 1~25cc/12 USD가 있으면 1~25cc는 12 USD, 26~50cc는 BASE 10 USD다. BASE 전체를 BASIC으로 채울 필요는 없다. 중간 상위 지점 BASIC을 상속하지 않는다.
- PREMIUM은 차량별 고정 일단가다. PREMIUM 아닌 차량은 cc로 BASE/BASIC을 선택한다. 가격 설정은 정수 USD, 결제·환불은 USD 센트 단위다. 기존 확정 예약 금액에 가격 변경을 소급하지 않는다.
- representativeEmail 가입은 일반관리자 승인 요청(PENDING_APPROVAL/REQUESTED)이며 대표 승인 후 활성화된다. inviteCode 가입은 그 지점 대표관리자로 즉시 ACTIVE, requestId/requestStatus=null이다. 코드는 하위지점 생성 시만 자동 생성하고 가입 성공 트랜잭션에서 NULL로 소진한다. 추가 발급·재발급 API/UI는 제공하지 않는다.
- 관리자 CANCEL은 지점 귀책 전용: 당일 포함 인계 전 APPROVED에 대해 실제 결제 총액 100% 환불. 고객 사유 대리 취소는 지원하지 않으며 cancellationReasonType은 BRANCH_FAULT만 허용한다(생략해도 동일 정책). 고객 취소는 인계 전 시작일 전 90%, 당일부터 0%로 유지한다. 인계 후 취소 불가, 미결제/0% PG 환불 호출 없음.
- 실제 주소·좌표·placeId로 배송구역 안/밖을 판정하는 기능은 지역 정책 미확정으로 제외했다. 지역명 문자열 추정도 제거했다. 주소는 보관하되 배송 가능 구역으로 검증했다는 문구를 표시하지 않는다. 같은 장소인지의 지리적 자동 판정도 제공하지 않으며 기존 대표의 위치 정정 권한·이전값 충돌 검사·감사 이력은 유지한다.

### 가격 API

POST `/nadreego/shop/tierCreate`는 기존 단건 또는 동일 지점의 1~100개 배열을 받는다.

```json
[
  {"spotCode":"지점코드", "minCc":1, "maxCc":25, "price":12, "type":"BASIC"},
  {"spotCode":"지점코드", "minCc":26, "maxCc":50, "price":15, "type":"BASIC"}
]
```

배열 응답은 `{"status":"success","tiers":[...]}`이고 각 항목에 `action=CREATED|UPDATED`가 있다. 동일 지점·시작/끝 cc가 같으면 수정, 없으면 추가한다. 배열 전체가 한 트랜잭션이며 생략된 기존 티어를 삭제하지 않는다. 요청 내부 동일 구간 중복은 422 TIER_BATCH_DUPLICATE_RANGE, 지점 혼합은 422 TIER_BATCH_SPOT_MISMATCH, 부분 겹침은 409 TIER_RANGE_OVERLAP, 하나의 BASE 안에 속하지 않으면 409 TIER_BASE_NOT_UNIQUE다. 기존 넓은 BASIC을 세분화할 때는 기존 BASIC을 삭제한 뒤 새 구간 배열을 등록한다. 삭제 후에는 BASE로 복귀한다.

GET 같은 경로의 `tiers`는 편집용 원설정(BASE+BASIC), `effectiveTiers`는 겹침 없이 실제 적용되는 구간이다. **effectiveTiers의 BASE 잔여 구간을 저장/삭제용 원구간으로 사용하지 않는다.** spotCode 생략은 공통 BASE만, 지정하면 해당 지점을 조회한다. POST에서 spotCode 생략은 로그인 관리자의 직접 지점이다. 직접 지점 일반관리자와 허용 하위 지점 대표의 기존 가격 권한을 유지한다.

고객 availability의 `price.pricingTiers[]`에 `priceOptionId`와 배송비 포함 `totalPrice`를 추가했다. 예: BASIC:10, PREMIUM:10은 금액이 같아도 다른 선택이다. 프론트는 문자열을 직접 합성하지 말고 받은 값을 request의 priceOptionId로 보낸다. 식별자의 범위는 요청한 지점·모델·기간의 최신 견적이다. 구버전에서 옵션을 생략하면 총액에 맞는 옵션이 정확히 하나일 때만 허용한다. 모호하면 409 PRICE_OPTION_REQUIRED, 선택이 무효면 PRICE_OPTION_INVALID, 금액 변경은 PRICE_QUOTE_MISMATCH다. 예약 생성 때 옵션·재고·금액을 재검증하고 선택 스냅샷을 저장한다. 관리자 reservation.selectedPriceOption/pricingTiers는 현재 차량 정보가 아니라 예약 당시 선택이다.

### 배송·조회 계약

고객 availability/request의 pickupLocation·returnLocation은 최대 500자 주소 문자열(공백만 불가)이다. deliveryRegionId는 선택할 지점 요금표 지역 ID이며 지리 검증 결과가 아니다. 활성 요금표가 하나면 생략 가능, 여러 개면 선택 필요(예약 시 409 DELIVERY_REGION_REQUIRED). 지점이 지원하지 않는 ID는 DELIVERY_REGION_NOT_SUPPORTED다. 공개 검색은 해당 배송 조건을 지원하지 않는 상품을 제외한다.

deliveryRequestType=START_ONLY면 전달 주소 필수·반환 주소 null/생략, 회수비 0이다. START_AND_RETURN이면 양쪽 주소 필수이며 서로 다른 주소 문자열도 저장한다(지리 판정 없음). 명시적 type 생략 시 반환 주소가 있으면 왕복, 없으면 편도로 해석한다. 배송 자체가 false면 type은 보내지 않는다. 지점 START_ONLY는 왕복을 거절한다. totalPrice에는 배송비가 이미 포함되므로 프론트에서 다시 더하지 않는다. 관리자 delivery.pickupLocation/returnLocation으로 실제 목적지를 제공하고 기존 마스킹 startAddress/returnAddress는 호환용으로 유지한다.

고객 GET `/api/v1/nadree/rental/completed`에 반납 외 취소·거절·만료가 포함된다. 기존 page/pageSize(최대 100)를 사용한다. GET `/api/v1/nadree/rental/reservations/{reservationId}`는 상태와 무관하게 본인 예약을 직접 조회한다. 관리자 POST `/nadreego/booking/select`에 bookedNo 정확 일치 필터를 추가했다. 예약 ID와 bookingId는 동일하며 bookedNo=BO+예약 ID다. 관리자 JWT를 고객 조회에 사용하지 않는다.

### 예약 중복 검증 — 별도 테이블 없음

사용자 결정으로 요청 결과 테이블·Idempotency-Key 저장·30일 결과 재현 및 GET `/api/v1/nadree/rental/requests/{requestId}`는 제외한다. 기존 MSP_RESERVATION에서 동일 고객·지점·모델·기간의 60초 이내 REQUESTED/APPROVED 예약을 확인하여 409 DUPLICATE_RENTAL_REQUEST를 반환한다. 고객 및 모델 잠금과 재고 검증은 유지한다.

이는 장기 멱등성 보장이 아니다. 응답 유실 시 무조건 재전송하지 말고 본인 진행/종료 예약 목록을 조회하여 확인한다. reservationId를 알면 예약 직접 조회를 사용한다. 60초 이후에는 같은 요청도 새 예약이 될 수 있으므로 프론트에서 재전송을 제한해야 한다. 다중 서버 MySQL 동시성은 서버에서 별도 검증한다.

### PayPal 판매자 연결 — 별도 테이블 없음

#### 2026-10-19 앱 복귀 역할 분담 — 프론트 전달

- 대상은 관리자 앱이다. PASS처럼 PayPal 로그인·판매자 연결 동의 후 기존 앱 화면으로 돌아오는 UX를 프론트에서 구현한다. 백엔드는 별도 홈페이지나 임의 복귀 URL을 만들지 않으며 이번 작업에서 실제 env 값을 추가·변경하지 않는다.
- 앱 복귀 링크와 연결 화면 종료 처리는 프론트 담당이다. 현재 지원하는 HTTPS App Link/Universal Link 등 복귀 방식을 정하고, 사용할 HTTPS URL을 서버 담당자에게 전달한다. 커스텀 스킴을 선택하면 현재 HTTPS 제한과 호환되는지 사전 협의가 필요하다.
- PayPal 완료/앱 복귀만으로 저장 성공으로 판단하지 않는다. 프론트가 state와 기존 관리자 인증으로 verify를 호출하고, 서버의 판매자 검증·DB 저장 성공 응답을 받은 뒤 연결 화면을 종료하고 기존 화면에 완료 상태를 표시한다. 실패·취소는 완료로 표시하지 않는다. 예약 승인은 별도 재요청이다.
- 백엔드는 현재 start/verify 계약을 유지한다. `NADREE_PAYPAL_ONBOARDING_RETURN_URL`을 제거하는 결정이 아니라 프론트 확정 전 설정을 보류하는 결정이다. URL을 전달받으면 실제 연동 전에 서버 설정에 반영해야 한다. 미설정 상태의 start는 `503 PAYPAL_ONBOARDING_RETURN_URL_REQUIRED`이며, URL 없이 자동 복귀되는 것으로 안내하지 않는다.
- 인수 확인: 실제 Android/iOS에서 복귀, state 전달, 같은 관리자 로그인 세션 유지, verify 성공 후 화면 종료, 실패·사용자 취소 처리를 확인한다. 현재 프론트 구현·기기 검증은 완료로 간주하지 않는다.

사용자 결정으로 온보딩 테이블·상태 복구 CLI·전용 타이머는 제외한다. 기존 MSP_SPOT_RENT.paypal_merchant_id에 검증된 판매자를 저장하며 같은 ID를 여러 지점에 허용한다. Sandbox/Live 혼동 방지용 paypal_environment와 원거래 환불 대상을 보존하는 MSP_RENTAL_PAYMENT.paypal_merchant_id는 기존 설계대로 유지한다. 추가 세션 컬럼은 없다.

프론트 흐름:

1. 예약 APPROVE 시 ID가 없으면 409 SHOP_PAYPAL_MERCHANT_REQUIRED. 예약 상태는 REQUESTED로 유지하고 거절은 가능하다. 프론트는 ‘PayPal 판매자 연결이 필요합니다’와 연결 버튼을 표시한다. 일반관리자는 직접 지점 대표에게 연결을 요청한다.
2. 직접 지점 대표가 POST `/nadreego/shop/paypal-onboarding/start`, `{ "spotMasterId":"..." }`를 호출한다. 응답의 actionUrl을 연다. URL 발급을 승인 오류 처리 안에서 자동 실행하거나 백엔드가 UI를 띄우지는 않는다.
3. start 응답은 state/actionUrl/expiresAt/paymentEnvironment다. state는 서버가 서명한 30분 유효값이며 관리자 로그인 세션·지점·환경·PayPal tracking ID에 연결된다. DB에 저장하지 않는다. 반복 start는 새 연결 URL을 발급한다. 이미 ID가 있으면 SHOP_PAYPAL_ALREADY_CONNECTED다.
4. PayPal 로그인·동의 후 프론트가 정하여 env에 반영한 HTTPS 앱 복귀 주소로 이동한다. 별도 홈페이지 화면을 보여줄 필요는 없다. 프론트는 복귀 query의 state와 관리자 인증으로 POST `/nadreego/shop/paypal-onboarding/verify`, `{ "spotMasterId":"...", "state":"..." }`를 호출한다. 서버는 서명·만료·현재 대표 권한을 확인하고 PayPal tracking 조회로 판매자 ID 및 수취/이메일/플랫폼 권한을 검증한 뒤 지점 컬럼에 저장한다. 브라우저 merchantId/merchantIdInPayPal 값을 직접 저장하지 않는다.
5. verify 성공 응답은 spotMasterId/merchantId/paymentEnvironment다. 프론트에서 기존 승인 요청을 다시 실행한다. 연결 완료만으로 예약을 자동 승인하지 않는다.

저장값 조회는 기존 GET `/nadreego/shop/paypal-merchant?spotMasterId=...`, 연결 해제는 PUT 같은 경로에 `{ "spotMasterId":"...", "merchantId":null }`이다. 임의 판매자 ID 입력은 거절한다. 새 /status·/refresh API는 제외한다. Sandbox ID가 남은 채 Live로 전환하면 환경 불일치로 승인/결제를 차단하며 대표가 기존 연결을 해제하고 Live로 다시 연결해야 한다.

state 만료는 410 PAYPAL_ONBOARDING_STATE_EXPIRED, 변조/다른 지점·환경·로그인 세션은 400 PAYPAL_ONBOARDING_STATE_INVALID다. 대표가 재로그인했거나 state를 잃으면 start부터 다시 진행한다. 동일 판매자 verify 재전송은 허용하지만 다른 저장 판매자를 덮어쓰지는 않는다. 별도 저장 상태가 없으므로 미완료 연결 자동 복구·state 개별 취소는 제공하지 않는다. 연결 해제 후에도 유효 state를 가진 같은 대표 세션의 명시적 verify는 재연결할 수 있으므로 프론트는 해제 시 state를 폐기하고 자동 재전송하지 않는다. 복귀 페이지는 state를 로그·분석도구에 보내지 않고 처리 후 URL에서 제거한다.

승인·실제 결제 전 PayPal 판매자 권한 검증은 안전상 유지한다. 연결값이 있어도 권한 미완료/철회는 PAYPAL_MERCHANT_NOT_READY, 외부 장애는 오류로 차단된다. 서명 검증된 판매자 웹훅은 현재 PayPal 상태를 재확인하여 권한이 실제로 없어진 동일 환경의 연결 지점 ID/환경을 비운다. 늦은 철회 이벤트라도 현재 권한이 유효하면 유지하며 미연결 지점을 자동 연결하지 않는다. 기존 결제 당시 판매자 ID와 결제·환불 웹훅/복구 작업은 보존한다.

공식 기준: [PayPal 플랫폼 온보딩](https://developer.paypal.com/platforms/checkout/save-payment-methods/onboarding/platform/). 실제 Sandbox 파트너 권한·복귀 페이지·웹훅·결제 검증은 별도다.

### 탈퇴·환불·채팅 — 기존 처리 검증

사용자 결정으로 개인정보 작업 테이블·백그라운드 정리·자동 재시도 타이머 및 cleanupStatus/privacyStatus 응답 추가는 제외한다. 기존 탈퇴 API는 진행 중 거래와 무관하게 Firebase 계정 삭제·채팅 세션 회수를 호출한 후 SQL 프로필/FCM을 비우고 서비스 access/refresh를 폐기한다. 성공 응답은 `{ "status":"success", "deleted":true }`다. 기존 인증 시각을 가진 토큰으로 재가입할 수 없다.

외부 서비스 실패 시 성공으로 표시하지 않고 오류를 반환한다. SQL과 Firebase는 하나의 원자적 트랜잭션이 아니므로 외부 삭제 이후 SQL 실패 등 부분 성공은 운영 확인이 필요하며 자동 복구를 보장하지 않는다. 거래 참조·주소 스냅샷·기존 채팅 본문의 후속 삭제는 이번에 추가하지 않는다. 이름 null만으로 탈퇴를 추정하지 않는다. 기존 여권 기능·정리는 보류한다.

검증 범위는 프로필/FCM 삭제, access/refresh 차단, Firebase 삭제·채팅 회수 호출, 외부 실패 시 성공 오표시 방지 및 기존 거래 보존이다. 실제 Firebase 계정/채팅 연동 검증은 별도다.

관리자 결제 조회의 refundRequestedAmount(목표액), refundedAmount(실제 누적액), refundStatus 구분과 가능한 경우 결제 오류의 paymentId 제공은 유지한다. 채팅 경로·일반관리자 읽기/대표 답변 정책도 유지하며 프론트는 로그아웃/탈퇴 때 로컬 캐시를 비운다.

### 서버 적용 순서 — 아래 명령은 아직 실행하지 않음

1. 사용자 변경을 보존하여 코드 배포. DB 백업과 대상 DB 이름을 먼저 확인한다.
2. ec2-user가 읽을 수 있는 `/srv/nadree-api/.env`의 기존 Platform Client ID/Secret/Webhook/Partner Merchant ID를 확인한다. 복귀 URL은 지금 임의로 추가하지 않는다. 프론트에서 HTTPS 앱 복귀 주소를 전달받은 뒤 실제 연결 테스트 전에 `NADREE_PAYPAL_ONBOARDING_RETURN_URL`에 설정한다. URL에는 query/fragment를 넣지 않는다. 미설정 동안 온보딩 start는 사용할 수 없다. `NADREE_CORS_ORIGINS`에는 필요한 기존 origin을 유지하면서 `https://www.riderlog-lte.com:50045`를 쉼표로 구분해 포함한다.
3. 마이그레이션 계획을 확인한다. 이번 요청 결과·개인정보·온보딩 관련 신규 테이블은 모두 제외했다. 판매자 연결은 기존 지점/결제 컬럼만 사용한다. 이전 미적용 판매자 컬럼 등도 계획에 포함될 수 있다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
```

출력과 DB 백업 확인 후 **실제 env의 DB 이름과 일치할 때만** 아래 테스트 DB 적용 명령을 실행한다. Live DB에는 이 명령을 그대로 사용하지 않는다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST'
sudo systemctl restart nadree-api.service
```

4. PayPal 앱에 판매자 완료·동의 철회 이벤트 구독을 추가하고 기존 결제 이벤트 구독을 유지한다. Sandbox 온보딩→승인→주문→구매자 승인→캡처→고객/관리자 환불→서명 웹훅을 검증한다.
5. 이번 온보딩/개인정보 전용 타이머는 설치하지 않는다. 기존 결제·환불 복구 타이머는 그대로 유지한다. 이전 문서대로 이미 새 타이머를 설치했다면 실제 설치 여부를 확인하여 해당 전용 타이머만 중지하고 운영자에게 변경 이력을 전달한다.
6. 별도 테이블을 이미 다른 서버에 생성했다면 자동 DROP하지 않는다. 기존 데이터 유무와 적용 이력을 확인한다. 이번 코드는 해당 테이블에 의존하지 않는다.

### App Check 디버그 검증 준비

scripts/verify_app_check.py는 등록된 디버그 비밀값을 실제 App Check 토큰으로 교환하고 읽기 전용 getChatUnreadSummary에 정상·누락·위조 토큰을 보내 200/401/401을 확인한다. 검증을 끄는 방식이 아니다. [공식 교환 API](https://firebase.google.com/docs/reference/appcheck/rest/v1/projects.apps/exchangeDebugToken)를 사용한다.

서버의 저장소 밖 0600 비공개 JSON에 projectNumber, appId, apiKey, debugToken, firebaseIdToken, data를 보관한다. firebaseIdToken은 **현재 채팅 세션의 custom token을 Firebase ID token으로 교환한 값**이며 일반 Nadree JWT나 FCM 토큰이 아니다. 고객 data는 `{}`, 관리자 data는 `{ "shopId":"직접지점ID" }`다. 고객/관리자 앱별로 등록된 디버그 토큰을 사용한다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python scripts/verify_app_check.py /srv/nadree-api-private/app-check-customer.json'
```

실제 비밀 파일은 제공되지 않아 외부 검증은 아직 실행하지 않았다. 이 검사는 앱 기기 무결성·FCM 수신·모든 Firestore 쿼리의 인수를 대체하지 않는다. 결과 파일에는 비밀값/응답 원문 없이 HTTP 코드와 통과 여부만 남기고 테스트 종료 후 디버그 토큰을 폐기한다.

### 인수 상태

온보딩 테이블까지 제외한 변경 후 전체 로컬 회귀는 **314 passed, 10 skipped**(별도 MySQL 6·Firestore 4), 기존 의존성 경고 2개다. 판매자 연결은 기존 컬럼만 사용하며 권한 검증·state 변조/만료/다른 세션·지점·환경 차단·연결 해제·웹훅 현재 권한 재확인·중복 판매자 허용을 확인했다. 실행 명령은 `env -u NADREE_TEST_MYSQL_URL -u FIRESTORE_EMULATOR_HOST PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests -q -p no:cacheprovider --tb=short`다. `git diff --check`도 통과했다.

실제 MySQL 잠금·PayPal Sandbox 온보딩/결제·Firebase 계정/채팅 회수·App Check 및 기기 푸시는 서버 인수에서 별도 확인해야 한다. 서버 DB 변경·배포는 실행하지 않았다.

---

2026-10-16 추가 변경: 지점별 PayPal 판매자 설정 API, 미설정 승인 차단, 결제 당시 판매자 보존 및 Platform 요청 분리를 구현했다. 기존 단일 판매자 env 정책을 대체하며 **서버 미적용**이다. [최신 Platform 변경 전달서](spot-paypal-platform-handoff-2026-10-16.md)를 먼저 확인한다.

2026-10-13 실제 서버 후속 기록: 테스트 DB의 미적용 컬럼 4개를 백업 후 적용하고 API를 재시작했다. QR 시드와 결제 타이머/외부 영향 작업은 보류했다. 아래 “서버 미적용”은 로컬 작업 당시 기록이며 최신 실측 상태는 [서버 적용·검증 결과](server-apply-verification-2026-10-13.md)를 따른다.

## 2026-10-13 추가 보완 — 배포 전 확인

이 절은 이번 로컬 변경분이다. 아래 9월 문서의 과거 정책보다 현재 확정 정책과 이 절이 우선한다. 서버 DB·실제 PayPal·Firebase에는 이번 변경을 적용하지 않았다.

### 차량 QR 조회 — 센서 코드와 분리하는 최종 정정

QR은 차량 식별용이고 센서는 선택 장치다. 차량은 QR만 있는 차량과 QR+센서 차량 두 가지다. 이전 센서 코드 기반 QR 조회 안내는 잘못된 가정이므로 폐기하며 `/nadreego/sensor/qr/resolve`도 제거했다. 프론트는 QR 원문을 전달하고 서버는 기존 `NADREE_QR_HASH_KEY`로 HMAC-SHA256을 계산해 `MSP_VEHICLE_QR.qr_code_hash`를 조회한다. 원문을 해시 컬럼에 그대로 저장하거나 프론트에서 해시를 만들어 보내지 않는다. 센서 코드·ID로 대체 조회하지 않는다.

```http
POST /nadreego/vehicle/qr/validate
Authorization: Bearer <관리자 access token>
Content-Type: application/json

{"qrCode":"testQr123123"}
```

성공 예시:

```json
{"status":true,"errorCode":null,"data":{"vehicleId":"example-vehicle-id","qrId":"example-qr-id","qrStatus":"ACTIVE","equipmentType":"QR_ONLY","sensorId":null,"sensorStatus":"NOT_LINKED","vehicle":{"vehicleId":"example-vehicle-id","vehicleNo":"DK-TEST-301","vehicleStatus":"AVAILABLE"},"availableActions":["PRICE_CHANGE","SPOT_CHANGE","REPAIR","QR_DELETE"]}}
```

위 성공 예시는 주요 필드만 표시했다. 센서가 있으면 `equipmentType=QR_WITH_SENSOR`, `sensorStatus=LINKED`, `sensorId`에 연결 센서 ID가 반환된다. 차량 정보에는 모델·번호·상태 등이 포함되며 QR 원문/해시·센서 코드는 노출하지 않는다. 기존 status/errorCode/data와 vehicleId/qrId/qrStatus를 유지하고 필드를 추가했다. 센서 존재 여부로 QR 조회를 거절하지 않는다.

차량 생성은 기존 `POST /nadreego/vehicle/create`에 QR 원문 `qrToken`을 필수로 보낸다. 센서가 없으면 sensorId 생략/null, 있으면 별도로 확보한 센서 ID를 전달한다. 서버는 QR 해시와 차량을 연결하고 센서 지정 시 소속·이미 연결됨·대여 중 여부를 다시 검증한다. 센서를 분리해도 QR 연결은 유지된다. 조회 후 가격·정비·지점·QR/센서 분리 등의 변경은 기존 API를 사용하며 각 API에서 권한과 최신 상태를 검증한다. availableActions는 화면 표시용이고 변경 권한을 부여하는 토큰이 아니다.

미등록/다른 지점 QR은 `404 QR_NOT_FOUND`, 비활성은 `409 QR_INACTIVE`, 만료는 `410 QR_EXPIRED`다. 한 차량에 활성 센서가 여러 개면 `409 SENSOR_STATE_INCONSISTENT`로 잘못된 연결을 숨기지 않는다. 원문 길이 제한은 기존 API와 동일하게 최대 4096자다. URL/JSON 파싱은 하지 않는다.

새 매핑 테이블·DB 컬럼·env·Firebase 변경은 없다. 테스트하려면 동일 서버 키로 생성된 차량 QR 해시와 차량 지점 이력이 필요하다. 기존 차량 생성 API를 통해 테스트 차량을 등록하면 해시가 저장된다. 이번 작업에서 서버 데이터나 기존 QR 해시·키는 변경하지 않았다. 기존 결제/위치 변경분에 필요한 컬럼 4개 적용은 여전히 별도다.

정정 후 전체 로컬 회귀: **266 passed, 10 skipped**(별도 MySQL 6개·Firestore 4개), 기존 의존성 경고 2개. QR 단독/센서 연결 차량 생성·조회·가격 변경, 센서 분리 후 QR 유지, 센서 코드 조회 거절, 다른 지점 접근·중복 QR·비활성/만료 QR 차단을 검증했다. 아래 252개 결과는 QR 보완 전 기록이다. 서버 적용과 실제 MySQL 동시성 검증은 아직 수행하지 않았다.

### 앱·웹 공통 결제 변경

- 주문/캡처 API 경로·요청 필드는 유지한다. 최신 결제 행만 보는 대신 해당 예약·설정된 SANDBOX/LIVE 환경의 모든 결제를 확인한다. 진행 중 주문은 재사용하며 이전 완료 결제·결과 불명 캡처가 있으면 새 청구를 차단한다.
- PG 호출 전 DB에 요청 의도를 저장한다. 주문/캡처 응답 유실은 FAILED로 단정하지 않고 동일 식별자로 복구한다. 최초 요청 후 5시간이 지난 결과 불명 주문/캡처는 자동 POST 재전송하지 않는다. PG 멱등 보존 기간에 안전 여유를 둔 처리다. [PayPal Orders 설명](https://developer.paypal.com/api/rest/integration/orders-api/api-use-cases/advanced/).
- `PAYMENT_ALREADY_PAID`: 기존 결제를 조회한다. `PAYMENT_IN_PROGRESS`: 새 주문을 만들지 말고 기존 결제 상태를 조회한다. `PAYMENT_RECONCILIATION_REQUIRED`: 운영 확인 후 복구한다. `PAYMENT_SCHEMA_UPDATE_REQUIRED`: 서버 마이그레이션을 먼저 확인한다.
- 늦은 실제 청구와 중복 추가 청구는 각각 `refund_reason=LATE_CAPTURE/DUPLICATE_CAPTURE`, `refund_percentage=100`으로 남긴다. 기존 취소 요청자 필드는 보존하며 시스템 처리를 고객/관리자 요청으로 꾸미지 않는다. 유효 원결제는 유지한다. 웹훅 순서가 뒤바뀌면 선행 시도를 확인하기 전 환불 판정을 보류한다.
- PG capture의 create_time을 마감/취소 이력과 비교한다. 단순 웹훅 지연·중복은 늦은 신규 청구로 보지 않는다. 기존 취소 정책은 관리자 시작일 전 100%·당일 취소 불가, 고객 시작일 전 90%·당일 인계 전 취소 0%다.
- `python -m app.jobs payments`가 PG 조회 복구 → 환불 재시도 → 미결제 확인 후 만료를 실행한다. PG 장애/불명 상태는 차량을 임의 해제하지 않는다. 직접 조회 기록은 웹훅 서명 검증 결과와 혼동하지 않도록 `verification_status=API_QUERY`로 구분한다.
- 환불은 동일 요청의 금액·식별자를 고정한다. PENDING은 기존 refund ID를 조회하며 새 환불을 추가하지 않는다. 실패는 조회로 확정한 뒤 새 시도를 만든다. 최대 5회 자동 호출 이후 운영 확인 표시/알림을 남긴다. 요청 결과가 불명인 경우 새 키로 재시도하지 않는다. 환불 재전송은 보존 기간보다 짧은 44일까지 제한한다. [PayPal 멱등 요청](https://developer.paypal.com/api/make-api-requests/), [환불 API](https://developer.paypal.com/api/payments/v2/captures-refund).
- 이 방식은 불필요한 중복 청구를 줄이는 것이며 PG 수수료가 절대 발생하지 않음을 보장하지 않는다.

### 관리자 권한·위치 정정

- 퇴사는 `POST /nadreego/shop/adminDelete`로 렌탈 직원 권한을 제거하는 경우다. 장기 미로그인을 자동 퇴사로 판단하지 않는다. 대표는 먼저 `POST /nadreego/admin/roleChange`로 일반관리자에게 대표권한을 양도한다.
- 두 경로는 기존 채팅 세션을 먼저 회수한다. 회수 실패 시 역할 DB 변경은 롤백한다. 일부 Firebase 회수 후 DB가 롤백되면 사용자는 다시 채팅 세션을 발급받아 현재 DB 권한으로 복구한다. 퇴사자는 재발급 불가, 양도한 대표는 일반관리자 읽기 권한, 새 대표는 답변 권한이다. 직접 MySQL 수정 감시용 별도 서비스는 추가하지 않았다.
- 추가 POST `/nadreego/booking/location-correction`: 대표만 자기/하위 지점의 인계 전 REQUESTED/APPROVED 예약을 수정한다. `bookedNo`, 선택 `spotMasterId`, `changeType=CORRECTION`, `target=PICKUP|RETURN`, `previousLocation`, `correctedLocation`, `reason`을 사용한다.
- 위치 형식은 `{address, zipCode, latitude, longitude}`. 이전 위치가 없으면 `previousLocation=null`이다. 화면의 이전 값이 서버와 다르면 `409 LOCATION_SNAPSHOT_CHANGED`로 거절하므로 최신 예약을 조회한다. 인계 후/종료 예약의 기록은 이 API로 바꾸지 않는다.
- 추가 GET `/nadreego/booking/{booked_no}/location-corrections?spotMasterId=...`: 대표 권한으로 정정 전후 값·작업자·사유·시각을 조회한다. `CORRECTION`은 같은 장소의 주소/핀 보정에만 사용한다. 서버가 실제 장소 동일 여부를 자동 증명하는 기능은 아니다.
- 실제 매장 이전은 기존 `/nadreego/shop/update`를 사용하며 기존 예약에 전파하지 않는다. 위치 정정도 배송 목적지·요금·확정 견적을 변경하지 않는다. Swagger 설명과 테스트용 요청 예시를 반영했다.

### 서버에서 실행할 순서

먼저 현재 서버의 `NADREE_DATABASE_URL`이 의도한 테스트 DB인지, PayPal 환경이 SANDBOX인지 비밀값을 출력하지 않고 확인한다. 별도 스케줄러가 이미 payments/all을 실행한다면 새 타이머를 중복 설치하지 않는다.

1. 코드 pull 후 마이그레이션 계획 조회:

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
```

2. 백업·승인 후 적용. `DATABASE_NAME`은 확인한 실제 대상 DB 이름으로 바꾼다. 이 명령은 DB를 변경한다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate --apply --confirm-database DATABASE_NAME'
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
sudo systemctl restart nadree-api.service
```

3. 승인된 테스트 결제만 있는 환경에서 복구 작업 1회 실행. 이 명령은 실제 PG 환불/DB 상태 변경을 할 수 있다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.jobs payments'
```

4. 기존 결제 스케줄러가 없는 경우에만, 검증 후 타이머 설치:

```sh
sudo install -m 644 /srv/nadree-api/deployment/nadree-payments.service /etc/systemd/system/nadree-payments.service
sudo install -m 644 /srv/nadree-api/deployment/nadree-payments.timer /etc/systemd/system/nadree-payments.timer
sudo systemctl daemon-reload
sudo systemctl enable --now nadree-payments.timer
sudo systemctl status nadree-payments.timer --no-pager
sudo journalctl -u nadree-payments.service -n 60 --no-pager
```

신규 env 값·Firebase Functions/Rules 변경은 이번 보완에 없다. 기존 PayPal/채팅 설정과 권한이 정상이어야 한다.

### 운영 환불 재처리

`PAYMENT_ID`를 해당 테스트/운영 결제의 숫자 ID로 바꾼다. 아래 첫 명령은 DB 읽기만 수행한다. 두 번째는 명시적인 운영 승인 후에만 실행하며 외부 환불이 발생할 수 있다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.refund_recovery PAYMENT_ID'
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.refund_recovery PAYMENT_ID --apply'
```

`--apply`도 임의 금액·기한이 지난 불명 요청의 새 키 생성을 허용하지 않는다. 과거 FAILED/PENDING 환불에 기록이 없거나 요청 식별자 보존 기간이 지났으면 자동 복구 대상이 아니다. PayPal 거래/환불 내역을 먼저 대조하고 수동 처리 범위를 확정한다. DB의 FAILED 표시만 보고 새 환불을 만들지 않는다.

### 서버 검증과 남은 확인

- 이번 변경의 로컬 회귀 결과: **252 passed, 10 skipped**. 건너뛴 항목은 별도 MySQL 6개·Firestore 4개이며 기존 의존성 deprecation 경고 2개가 있다. `git diff --check`도 통과했다. 실제 MySQL 행 잠금 동시성, PayPal Sandbox 승인·캡처·응답 유실·웹훅 역순·환불 실패 복구, Firebase 권한 회수 종단은 서버에서 별도 검증한다.
- 차량 QR 해시 기반 조회로 정정했다. 실제 서버의 등록 QR·차량 지점 이력과 MySQL 동시 연결 방지 검증은 별도이며 예시 데이터가 자동 배포되지는 않는다.
- 차량 이동의 기본 성공·타 지점 차단·예약/활성 렌트 차량 이동 차단을 격리 테스트한다. 실제 센서 동반 이동·동시 재배정 및 실제 DB 계층 제약은 별도 인수 항목이다.
- 앱 화면·App Check·실기기 푸시는 별도 범위다. 위의 배포 명령을 아직 실행하지 않았으며 전체 출시 완료로 판정하지 않는다.

작성 기준: 2026-09-29

이 문서는 Nadree 관광객 앱, NadreeGo 관리자 앱, 공통 백엔드, 기존 RiderLog 연동 범위를 한 문서로 정리한 인수용 문서입니다. 관광객 앱 전용 상세 문서는 `docs/nadree-frontend-handoff.md`에 별도로 유지합니다.

## 1. 시스템 범위

- 관광객 앱 API: `/api/v1/nadree`
- 관리자 앱 API: `/nadreego`
- PayPal 웹훅: `/nadreego/paypal/webhook`
- 상태 확인: `/health/live`, `/health/ready`
- 운영 도메인: `https://na-dree.com`
- Swagger: `https://na-dree.com/docs`
- 기존 RiderLog API와 DB를 공유하지만, 이번 변경은 Nadree 기능을 추가하는 방식입니다.

## 2. 관광객 앱 API

관광객 앱의 기준 명세는 `docs/nadri-user-api-design.md`이며 현재 구현된 주요 메서드는 다음과 같습니다.

| 기능 | 메서드 | 경로 |
|---|---|---|
| Firebase UID 로그인/회원 생성 | POST | `/api/v1/nadree/user/login` |
| 사용자 정보 수정 | PATCH | `/api/v1/nadree/user/profile` |
| 로그아웃 | POST | `/api/v1/nadree/user/logout` |
| 토큰 갱신 | POST | `/api/v1/nadree/user/refresh` |
| 차량·지점·가격 조회 | POST | `/api/v1/nadree/rental/availability` |
| 예약 요청 | POST | `/api/v1/nadree/rental/request` |
| 예약 요청 취소 | POST | `/api/v1/nadree/rental/request/cancel` |
| 진행 중 렌트·예약 목록 | GET | `/api/v1/nadree/rental/ongoing` |
| 완료 렌트 목록 | GET | `/api/v1/nadree/rental/completed` |
| PayPal 결제 주문 생성 | POST | `/api/v1/nadree/rental/payment/order` |
| PayPal 결제 캡처 | POST | `/api/v1/nadree/rental/payment/capture` |
| PayPal 결제 상태 조회 | GET | `/api/v1/nadree/rental/payment/{paymentId}` |

예약·결제와 관련된 응답은 프론트가 임의로 상태를 만들지 말고 응답의 `status`, `paymentStatus`, `refundStatus`를 기준으로 화면을 전환해야 합니다.

진행 중·완료 목록의 각 항목도 차량 조회와 같은 가격 구조를 사용합니다. `price`에는 `currency`, `rentalDays`, `dailyFrom`, `dailyTo`, `rentalFrom`, `rentalTo`, `pricingTiers`, `deliveryStart`, `deliveryReturn`, `deliveryTotal`, `totalOptions`, `totalFrom`, `totalTo`, `requestedTotal`, `calculatedTotalFrom`, `calculatedTotalTo`, `finalTotal`을 포함합니다. `delivery`에는 `deliveryRegionId`, 픽업·반납 주소, 시작·반납·합계 배송비를 포함합니다. 값이 존재하지 않는 현장 렌트 항목은 해당 필드를 `null` 또는 빈 배열로 반환합니다.

## 3. 인증과 토큰

### 관광객

1. 앱은 Firebase Authentication으로 로그인하고 Firebase ID Token을 받습니다.
2. Nadree 로그인 요청 body에는 `UID`를 보내고, Firebase ID Token은 `Authorization: Bearer <firebase-id-token>` 헤더로 보냅니다.
3. 서버는 Firebase Admin SDK로 ID Token을 검증하고 토큰의 `uid`가 요청의 `UID`와 같은지 확인합니다.
4. 검증 성공 시 Nadree 전용 access token과 user refresh token을 발급합니다.
5. 신규 UID면 `MSP_RENTAL_USER`를 만들고, 기존 UID면 정보를 반환합니다.

Firebase ID Token이 없거나 만료됐으면 `CUSTOMER_FIREBASE_AUTH_NOT_CONFIGURED`, `FIREBASE_ID_TOKEN_REQUIRED`, `FIREBASE_ID_TOKEN_INVALID`, `FIREBASE_UID_MISMATCH` 계열 오류를 처리해야 합니다. 운영 환경에서 Firebase 인증 설정이 빠지면 관광객 로그인은 차단됩니다.

### 관리자

- 관리자 인증은 기존 NadreeGo access/refresh token 흐름을 사용합니다.
- 관리자 역할은 `rental_primary_admin`, `rental_manager`입니다.
- 관리자 refresh token은 `MSP_REFRESH_TOKEN`에서 관리하며 관리자 계정과 기기별 세션 제한 정책을 적용합니다.
- 관광객 토큰과 관리자 토큰은 검증 대상과 권한이 다르므로 서로 교차 사용하면 안 됩니다.

## 4. 식별자와 데이터 매핑

- `UID`: Firebase UID이자 `MSP_RENTAL_USER.uid_token`의 외부 식별자입니다.
- `shopId`: `MSP_SPOT_MASTER.spot_master_id`입니다.
- `bookingId`: `MSP_RESERVATION.reservation_id`입니다.
- `bookedNo`: 화면 표시용 예약 번호이며 관계 키로 사용하지 않습니다.
- `spotCode`, `unitCode`: 지점 검색·표시용 코드입니다.
- `spot_master`: 최상위 계약부터 하위 지점까지의 연결 관계를 표현합니다.
- 이번 Nadree API의 지점 관계는 `spot_master_id`를 기준으로 조회하며 별도 `spot_id`를 필수 관계 키로 사용하지 않습니다.
- `MSP_DRIVER`와 기존 RiderLog의 드라이버 흐름은 이번 변경 범위가 아닙니다.

## 5. 관광객 예약 흐름

1. 로그인 후 차량 조회 API에 대여 시작일, 반납일, 배기량/모델 조건, 배송 여부와 픽업·반납 위치를 전달합니다.
2. 서버는 지점·차량 모델 단위로 재고와 예약·렌트 기간을 확인하고 가격, 티어, 배송비, 샵 정보를 반환합니다.
3. 예약 요청 시 조회에 사용한 조건 JSON을 예약에 스냅샷으로 저장합니다.
4. 같은 모델·지점·기간에 동시에 요청이 들어오면 DB 잠금과 가용성 확인을 다시 수행하고 먼저 확정된 요청만 허용합니다.
5. 예약은 `REQUESTED`로 생성되며 관리자 승인 전에는 결제 주문을 만들 수 없습니다.
6. 관리자 승인 시 `APPROVED`가 되고 승인 시각 기준 결제 기한을 계산합니다.
7. 승인 후 PayPal 주문을 생성하고 결제를 완료합니다.
8. 결제 완료 웹훅 확인 후 관리자가 QR로 인계 처리합니다. 인계가 렌트 시작이며 관광객 앱에서 QR을 처리하지 않습니다.
9. 반납 처리 후 `RETURNED` 상태가 됩니다.

### 예약 및 결제 상태

- 예약: `REQUESTED`, `APPROVED`, `REJECTED`, `CANCELED`, `EXPIRED`
- 결제: `CREATED`, `PENDING`, `PAID`, `FAILED`, `CANCELED`
- 환불: `NONE`, `NOT_REQUIRED`, `REQUESTED`, `PENDING`, `COMPLETED`, `FAILED`

결제가 완료되기 전 `REQUESTED` 또는 `APPROVED` 예약은 관광객이 취소할 수 있습니다. 승인 후 결제하지 않으면 결제 기한 만료 시 예약이 자동 취소되어 렌트를 생성할 수 없습니다. 관리자가 승인한 뒤 결제하지 않은 예약을 렌트 생성 API가 통과시키면 안 됩니다. 결제 완료 후 취소는 관리자 취소와 PayPal 환불 흐름으로 처리합니다.

승인 후 결제 기한 안내는 남은 기간 2일, 1일에 각각 FCM으로 보내고, 기한이 지나면 만료 알림을 보냅니다.

## 6. PayPal 연동

- 표시 금액과 결제 금액은 MVP에서 USD 기준입니다.
- 결제 주문은 관리자 승인 이후에만 생성할 수 있습니다.
- 결제 전 예약 취소는 PayPal 결제 전에 처리됩니다.
- 결제 완료는 PayPal API 결과와 웹훅을 함께 확인합니다.
- 웹훅 URL: `https://na-dree.com/nadreego/paypal/webhook`
- 동일 웹훅 재전송은 이벤트 ID 저장, 서명 검증, 결제 상태 전이 검증으로 중복 반영을 막습니다.
- 결제 생성·캡처·환불 요청은 해당 결제와 예약의 소유자 및 상태를 다시 확인합니다.
- 샌드박스 테스트에서는 PayPal Sandbox Client ID/Secret, Webhook ID, 판매자 계정을 서버 환경 변수에 넣습니다.

## 7. 관리자 앱 기능

### 계정과 지점

- 대표 관리자는 상위 계약/지점 생성 시 발급된 초대 코드를 관리합니다.
- 일반 관리자는 대표 관리자 이메일 또는 가입 코드를 입력해 해당 지점 가입 요청을 보냅니다.
- 대표 관리자가 가입 요청을 승인해야 일반 관리자 역할이 활성화됩니다.
- 지점 계층은 `MSP_CONTRACT` → `MSP_ORG` → `MSP_REGION` → `MSP_LOCAL` → `MSP_SPOT` 및 `MSP_SPOT_MASTER` 관계로 관리됩니다.

### 차량과 예약

- 차량 모델, 지점별 재고, 가격 티어, 배송 지역을 관리합니다.
- 관리자 예약 승인·거절 결과는 관광객에게 FCM으로 전달합니다.
- 관리자 앱에서 QR 인계와 반납 처리를 수행합니다. 관광객 앱에는 QR 처리 기능이 없습니다.
- 캘린더는 해당 지점이 보유한 모델/차량의 기간별 예약·렌트·정비 가능 여부를 조회합니다.
- 활성 렌탈 중에는 `PUT /nadreego/rent/passport`로 앱에서 식별정보를 마스킹한 JPEG/PNG를 업로드하고, `GET /nadreego/rent/passport/{bookedNo}`로 같은 지점의 활성 관리자만 조회합니다. 반납 후에는 API 접근을 차단합니다. 원본 이미지나 저장소 키를 응답하지 않습니다.

## 8. FCM 정책

FCM 토큰은 앱이 전달한 값을 계정의 최신 토큰으로 저장합니다. 이번 정책은 계정당 기기 하나이며, 로그아웃 요청에 현재 기기의 `X-FCM-Token`을 보내 저장된 값과 일치하면 토큰을 삭제합니다. 헤더를 보내지 않으면 토큰을 유지합니다.

| 이벤트 | 수신자 |
|---|---|
| 예약 요청 | 해당 지점에 직접 연결된 활성 관리자 |
| 예약 승인 | 관광객 |
| 예약 거절 | 관광객 |
| 결제 기한 2일/1일 전 | 관광객 |
| 결제 기한 만료 | 관광객 |
| 결제 완료 | 관광객 및 해당 지점 관리자 전체 |

관리자 수신자는 대상 지점에 직접 연결된 활성 `rental_primary_admin`/`rental_manager`를 조회합니다. 같은 토큰이 여러 계정에 있으면 한 번만 발송합니다. FCM 발송 실패가 예약·결제 트랜잭션 자체를 실패시키지 않도록 비즈니스 처리와 알림 결과를 분리합니다.

FCM과 Firebase ID Token 검증은 같은 Firebase 프로젝트의 서비스 계정 설정을 사용합니다. 위치 정보 Firebase는 별도 프로젝트/환경 변수로 구분합니다.

## 9. DB와 마이그레이션

주요 Nadree 테이블은 다음과 같습니다.

- `MSP_RENTAL_USER`, `MSP_RENTAL_USER_REFRESH_TOKEN`
- `MSP_RESERVATION`, `MSP_RENTAL_CONTRACT`, `MSP_RENTAL_PAYMENT`
- `MSP_RENTAL_VEHICLE`, `MSP_RENTAL_TIER`, `MSP_MODEL_DAILY_INVENTORY`
- `MSP_SPOT_MASTER`, `MSP_SPOT_RENT`, `MSP_SPOT_DELIVERY_REGION`, `MSP_DELIVERY_REGION`
- PayPal 웹훅 이벤트 저장 테이블

테스트 DB용 렌탈 시나리오 데이터는 `migrations/test_seed_rental_scenarios.sql`에 있습니다. 기존 테스트 지점을 새로 만들지 않고 차량 모델·차량·가격·재고·관광객·예약 상태·렌트 계약·결제 상태·배송 지역만 `NRTEST_*` 식별자로 추가합니다. API 응답의 `shopId`와 `spotMasterId`는 기존 테스트 지점의 `spot_master_id`를 그대로 반환하고, 모델·예약·계약·결제 필드는 시드된 ID와 상태를 동적으로 반환합니다.

주요 시드 상태는 다음과 같습니다.

- `NRTEST-MODEL-125` / `NRTEST-MODEL-155`: 125cc·155cc 모델, USD 일일 요금 25·35
- `NRTEST-VEHICLE-301`: 대여 가능, `302`: 정비, `303`: 진행 중 렌트, `304`: 미래 승인 예약
- `NRTEST-RES-REQ-001`: 승인 대기, `APP-001`: 승인 후 결제 필요, `PENDING-001`: 결제 진행 중
- `NRTEST-RES-HAND-001`: 인계 완료, `RETURN-001`: 반납 완료·환불 완료
- 목록 응답의 `price`와 `delivery`는 위 예약의 저장된 견적·배송 스냅샷을 사용합니다.

알림 전용 테이블과 채팅 테이블은 추가하지 않습니다. FCM 토큰은 기존 사용자·관리자 저장 컬럼을 사용합니다.

운영 DB 적용 전 읽기 전용 계획을 확인합니다.

~~~bash
cd /srv/nadree-api
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
~~~

계획이 맞을 때만 다음처럼 명시적으로 적용합니다.

~~~bash
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST'
~~~

현재 캘린더 최적화용 주요 인덱스는 `MSP_VEHICLE_SPOT_HISTORY.idx_vehicle_spot_current`, `MSP_RESERVATION.idx_reservation_calendar`, `MSP_RENTAL_CONTRACT.idx_rental_contract_calendar`입니다. 인덱스 추가는 RiderLog 기존 테이블 구조나 드라이버 데이터 흐름을 삭제·변경하지 않는 additive 변경입니다.

## 10. RiderLog 영향 범위

- `MSP_DRIVER`는 Nadree에서 새로 수정하거나 대체하지 않습니다.
- 기존 RiderLog API와 RiderLog의 `RiderLog` 기록 흐름은 그대로 유지합니다.
- 공유 DB의 `MSP_ROLE`에서 Nadree 역할을 임의로 삭제하지 않습니다.
- Nadree 예약·결제·사용자 테이블을 추가해도 기존 드라이버, 운행, 사고, 배치 기능의 관계 키를 변경하지 않습니다.
- 배포 전 기존 RiderLog 회귀 테스트와 Nadree 테스트를 함께 실행해야 합니다.

## 11. 프론트엔드 구현 체크리스트

### 관광객 앱

- Firebase 로그인 성공 후 ID Token을 Nadree 로그인 API에 전달합니다.
- `shopId`는 `spotMasterId`, `bookingId`는 `reservationId`로 저장합니다.
- 예약 요청 후에는 관리자 승인 전 결제 버튼을 노출하지 않습니다.
- PayPal 주문 생성 응답의 승인 URL로 이동하고, 앱 복귀 후 결제 상태 API와 웹훅 반영 상태를 확인합니다.
- 결제 완료 전 `REQUESTED`·`APPROVED` 예약 취소를 허용하고, 결제 진행 중·완료 후에는 상태 API 또는 관리자 환불 절차를 안내합니다.
- 결제 완료·승인·거절·만료 FCM을 받으면 예약 목록을 다시 조회합니다.
- 로그아웃 요청에 일치하는 `X-FCM-Token`을 보내면 현재 FCM 토큰을 삭제하고, 헤더를 보내지 않으면 토큰을 유지합니다.
- 오류 응답의 `errorCode`를 기준으로 사용자 메시지를 표시하고 원문 DB 오류를 노출하지 않습니다.

### 관리자 앱

- 대표 관리자와 일반 관리자 역할에 따라 메뉴와 API 권한을 분리합니다.
- 가입 요청 승인 전 일반 관리자의 관리 API 접근을 허용하지 않습니다.
- 예약 승인 후 결제 기한을 표시합니다.
- 결제 완료 전 QR 인계 메뉴를 실행하지 않습니다.
- QR 인계는 관리자 앱에서만 수행하고 인계 완료를 렌트 시작으로 표시합니다.
- 대상 지점의 모든 관리자에게 예약·결제 FCM이 도착하는지 확인합니다.

## 12. 운영 환경 변수

`.env`는 `/srv/nadree-api/.env`에 두고 `ec2-user`가 읽을 수 있도록 소유자와 권한을 설정합니다.

~~~bash
sudo chown ec2-user:ec2-user /srv/nadree-api/.env
sudo chmod 600 /srv/nadree-api/.env
~~~

필수 그룹:

- `NADREE_ENV`, `NADREE_DATABASE_URL`, `NADREE_REDIS_URL`
- `NADREE_JWT_SECRET`, `NADREE_FIELD_ENCRYPT_KEY`
- `NADREE_FCM_*` 및 Firebase Admin 서비스 계정 값
- `NADREE_LOCATION_FIREBASE_*` 위치 Firebase 값
- `NADREE_PAYPAL_*` 및 Webhook 설정
- `NADREE_SMTP_*` 이메일 설정
- `NADREE_PASSPORT_STORAGE_ROOT` (현재 개발용 로컬 저장소 설정; 운영 S3 어댑터·보관/삭제 정책 별도)

서비스는 systemd의 `User=ec2-user`, `WorkingDirectory=/srv/nadree-api`로 실행해야 합니다. `.env`를 읽을 수 없는 `ssm-user`로 마이그레이션이나 수동 실행을 하면 `PermissionError`가 발생하므로 다음처럼 실행합니다.

~~~bash
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
~~~

## 13. 배포 및 점검

~~~bash
cd /srv/nadree-api
sudo systemctl stop nadree-api
git pull --ff-only origin main
sudo chown ec2-user:ec2-user .env
sudo chmod 600 .env
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/pip install -r requirements.lock'
sudo systemctl daemon-reload
sudo systemctl reset-failed nadree-api
sudo systemctl start nadree-api
sudo systemctl status nadree-api --no-pager -l
curl -sS https://na-dree.com/health/live
curl -sS https://na-dree.com/health/ready
~~~

`/health/ready`가 `status: ok`이면 DB, 필수 스키마, 역할 설정이 준비된 상태입니다. `MFA_FLOW_NOT_IMPLEMENTED`는 현재 남아 있는 제한사항이며 Nadree 예약·결제 흐름을 막는 오류가 아닙니다.

## 14. 테스트 현황과 남은 운영 확인

- 전체 자동 테스트: 160 passed, 6 skipped, 2 warnings 기준으로 통과했습니다.
- 스킵 항목은 외부 Firebase, PayPal, 실제 DB/Redis 같은 운영 의존성이 필요한 통합 테스트입니다.
- 실제 운영 전 Firebase ID Token 검증, FCM 발송, PayPal Sandbox 주문·캡처·웹훅·환불, Redis 연결을 각각 확인해야 합니다.
- PayPal 웹훅은 Sandbox 콘솔의 Webhook URL과 이벤트 구독이 실제 도메인으로 저장되어 있어야 합니다.
- 대상 그룹 health check와 `/health/ready`가 모두 정상인지 확인합니다.
- 예약 동시성, 승인 후 결제 기한 만료, 중복 웹훅, 결제 후 관리자 취소·환불을 시나리오로 테스트합니다.

## 15. 알려진 제한사항

- MFA 전체 흐름은 아직 구현되지 않아 readiness에 `MFA_FLOW_NOT_IMPLEMENTED`가 표시됩니다.
- FCM 토큰은 계정당 최신 1개 정책입니다. 한 계정의 여러 기기 동시 수신이 필요해지면 별도 기기 토큰 테이블과 토큰별 폐기 정책을 추가해야 합니다.
- MVP는 발리 기준 고정 시간과 USD 결제를 전제로 합니다. 여러 국가를 지원할 때는 지점 타임존, 영업시간, 환율 스냅샷을 별도로 도입해야 합니다.
- 채팅은 백엔드 범위가 아니며 프론트에서 처리합니다.
- 여권 업로드는 현재 파일시스템 어댑터와 클라이언트의 마스킹 확인 플래그를 사용합니다. 운영 S3/암호화 저장소, 시각적 마스킹 검증, 반납 후 실제 자동 삭제 배치의 승인은 아직 필요합니다.
## 2026-10-19 서버 보완: 고객 예약 이력과 관리자 FK 호환

실제 테스트 DB의 `MSP_RESERVATION_HISTORY.changed_by`는 관리자 FK이므로 고객 신청·취소의 UID를 이 컬럼에 넣지 않는다. 해당 고객 이력은 `changed_by=NULL`, 기존 `details` JSON에 `actorType=CUSTOMER`, `actorId=고객 UID`를 기록한다. 관리자 실행 이력은 기존 관리자 ID 기록을 유지한다. DB 스키마·기존 FK·기존 데이터와 API 요청/응답 필드는 변경하지 않는다. 고객 신청에 판매자 ID는 필요하지 않으며 관리자 승인·결제의 판매자 검증은 그대로 유지한다. 프론트 수정은 필요하지 않다.

격리 회귀와 실제 재검증 결과는 [서버 검증 결과](server-requirements-verification-2026-10-19.md)의 11절에 기록했다.

## 2026-10-20 온보딩 리턴 URL 반영 후 서버 보완

PayPal Sandbox가 referral self 링크를 api.sandbox.paypal.com으로 반환하는 실제 응답을 기존 api-m.sandbox.paypal.com 단일 호스트 검사에서 거절하던 문제를 수정했다. 환경별 PayPal API 호스트만 허용하며 HTTPS·경로·사용자정보/포트 및 Sandbox/Live 분리 검사를 유지한다. 후속 호출은 경로만 사용하고 기존 고정 base로 보낸다. CORS나 프론트 API 계약 변경은 없다. 격리 회귀 56개 및 재시작 후 실제 start HTTP 200을 확인했다. state·Sandbox actionUrl·expiresAt·paymentEnvironment 응답 존재를 확인했고 값은 기록하지 않았다. 판매자 동의·실기기 앱 복귀·같은 세션 verify·저장·결제는 별도 미검증이다. 상세는 [서버 검증 결과](server-requirements-verification-2026-10-19.md)의 2026-10-20 최신 절을 참조한다.

## 2026-10-20 대기 예약 승인 시 RESERVATION_CHANGED 보완

`compute_assignment`는 REQUESTED/SOFT_HOLD 신청도 용량을 점유하도록 가상 차량 배정에 포함한다. 기존 `apply_assignments`는 이 결과를 APPROVED 전용 UPDATE로 저장하려다 다른 대기 신청에서 수정 건수 0을 감지해 RESERVATION_CHANGED를 발생시켰다. 대기 신청의 계산 결과만 저장에서 제외하도록 수정했다. 대기 신청의 용량 점유·승인 대상의 별도 PROVISIONAL 배정·기존 승인 예약 재배정·실제 상태 변경 충돌 검사는 유지한다. API·DB 스키마 변경은 없다.

실제 승인 테스트 지점/모델의 대기 예약 4건을 읽기 전용 확인했고, 수정 전 격리 승인 409를 재현한 뒤 신규 8개 포함 관련 격리 회귀 39개가 통과했다. 이 절의 변경은 작업 트리 구현·격리 검증 완료 상태다. 실제 예약 승인·서비스 재시작은 이번 작업에서 하지 않았으므로 실행 중 API 반영/실제 승인 성공과 구분한다. 상세는 [서버 검증 결과](server-requirements-verification-2026-10-19.md)의 RESERVATION_CHANGED 보완 절을 참조한다.

## 2026-10-20 플랫폼 판매자 조회 인증 보완

결제 주문/캡처 경로에서 판매자 지정 PayPalClient로 플랫폼 merchant-integrations를 조회할 때 판매자 assertion이 추가돼 401 AUTHORIZATION_ERROR가 발생하던 조건을 수정했다. 상세·tracking 조회는 플랫폼 Bearer 인증만 사용하고 기존 판매자 수취·이메일·OAuth 동의 검사는 유지한다. 주문·캡처·환불에는 기존 판매자 assertion이 유지된다. 기존 결제/DB/env와 프론트 API 계약 변경은 없다. 관련 격리 회귀 81개 통과 후 2026-10-20 05:49 UTC API 재시작, active/running 및 헬스체크 200을 확인했다. 사용자 지시에 따라 실제 주문·결제·PayPal 업무 요청은 재시도하지 않았으므로 외부 주문 성공은 미검증이다. 상세는 [서버 검증 결과](server-requirements-verification-2026-10-19.md)의 최신 인증 보완 절에 기록했다.
