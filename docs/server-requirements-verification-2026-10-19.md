# 2026-10-19 서버 적용 상태·요구사항 검증 결과

최종 서버 확인: **2026-10-19 02:31:46 UTC**. 실제 인증/API 검사 기록 02:07:27 UTC, 공개/가격 검사 기록 02:08:28 UTC, 서비스/로그/작업 등록 기록 02:28:39 UTC. 기준 문서는 [최신 전체 인수서](nadree-full-change-handoff.md)의 2026-10-18 정책 및 **2026-10-19 앱 복귀 역할 분담**이다.

검증 대상 HEAD는 `ba23d26580d25bb23621fe021e2af885a6633932`다. 점검 시작 시 `f69474000e6ea21cf30363b52920c20f2ae7cd30`였고 중단 사이 최신 HEAD로 바뀌었다. 두 커밋의 차이는 인수 문서 1개뿐이며 Python 실행 코드·설정·테스트 변경은 없다. f694740의 커밋 시각은 01:18:47 UTC, API 시작 시각은 01:37:57 UTC다. 이 보고서는 프로세스 경로·시각·저장소 코드 대조 결과이며 별도 버전 응답 API에서 Git SHA를 받은 것은 아니다.

**기본 회귀 314 passed/10 skipped를 재현했다. 격리 MySQL 포함 회귀는 320 passed/4 skipped, 별도 Firestore 4개도 통과했다. 실제 HTTP/공개 스키마 검사 21개와 승인 계정 API 검사 33개가 통과했고, 추가 격리 배송·종료 조회 검사 20개도 통과했다. 최신 재검사에서 Sandbox OAuth와 웹훅 목록·상세 조회는 통과했다. 웹훅 이벤트 5개 누락은 승인 후 추가했고 상세 재조회에서 누락 0개를 확인했다. 복귀 URL은 설정 대기이며 실제 판매자 연결·결제·환불·App Check·탈퇴 종단 인수는 미검증이다. 테스트 개수를 전체 실연동 완료로 해석하지 않는다.**

## 1. 배포·설정·마이그레이션

| 검사 | 기대 | 실제 | 판정 |
| --- | --- | --- | --- |
| 실행 서비스 | 기존 서비스·독립 실행 경로 유지 | nadree-api.service, ec2-user, /srv/nadree-api, .venv/bin/uvicorn app.main:app, port 8008 | 통과 |
| 프로세스·코드 경로 | 배포 경로와 일치 | /proc/MainPID/cwd도 /srv/nadree-api. PID 2509709 유지 | 통과 |
| live/ready | 200 | 모두 200, 기존 MFA_FLOW_NOT_IMPLEMENTED 제한 유지 | 통과·제한 유지 |
| Swagger/OpenAPI | 최신 경로 공개 | /docs, /openapi.json 200. tierCreate·예약 직접 조회·판매자 start/verify·기존 merchant·탈퇴 경로 확인 | 통과(스키마 확인) |
| 마이그레이션 | pending 없음 | app.migrate를 읽기 전용으로 시작/종료 시 실행, 모두 No pending changes | 통과 |
| 서버 env 반영 | 파일과 실행 설정 일치 | Settings 전체 비교 일치. DB/Redis/JWT/암호화/QR/FCM·Auth/PayPal Client/Secret/Webhook/Partner 설정 존재 | 통과(유무 확인) |
| 복귀 URL | 프론트 확정 전 미설정 허용 | 설정 없음. 값 추가·대체 안 함 | 설정 대기 |
| DB 대상 | 의도한 테스트 DB | RIDERLOG_V2_DATA_TEST | 통과 |
| 판매자 컬럼 | 기존 지점/결제 컬럼 사용 | MSP_SPOT_RENT의 paypal_merchant_id/paypal_environment, MSP_RENTAL_PAYMENT의 paypal_merchant_id 존재 | 통과(구조 확인) |
| 제외 테이블 | 요청 결과·개인정보 작업·온보딩 신규 테이블 없음 | 실제 테이블 이름과 현재 metadata에서 해당 전용 테이블 미발견. 이번 작업에서 생성 안 함 | 통과 |
| 제외 타이머 | 온보딩/개인정보 전용 작업 없음 | 로컬 systemd에서 해당 타이머 미발견 | 통과(로컬 등록 범위) |
| 기존 결제·환불 복구 | 기존 운영 작업 유지 | 로컬 nadree-payments.service/timer는 LoadState=not-found. 검사한 systemd/cron에서 payments/all/refund_recovery 직접 등록 미발견 | **운영 동작 미검증** |
| 채팅 작업 | 기존 작업 유지 | nadree-chat-sync.service/timer 등록 유지, 중복 설치·재시작 안 함 | 통과(등록 확인) |
| 서비스 오류 로그 | 예상 오류 외 신규 장애 없음 | 재시작 이후 Traceback/DB 오류/Firebase 초기화 오류 0. HTTP 5xx 1건은 이번 start의 예상된 503과 일치 | 통과 |

결제 복구는 로컬 등록이 없다는 사실만 확인했다. 외부 스케줄러·별도 래퍼 등록은 확인하지 못했으므로 자동 복구가 실행 중이라고 표시하지 않는다. 기존 작업을 중지/삭제하거나 새 타이머를 설치하지 않았다. 운영자가 실행 주체·주기·최근 성공 기록을 확인해야 한다.

설정은 유무·일치 여부만 확인했으며 env 원문·키·토큰·비밀번호를 출력/기록하지 않았다. 부모 명세 `/srv/rental-project-master.md`, `/srv/rental-api-review-decisions.md`는 이 서버에 없어 직접 대조하지 못했다. 추가 구현·실제 DB 스키마 변경·서비스 재시작·Firebase 배포·보안 완화는 하지 않았다.

## 2. 격리 회귀·추가 시나리오

운영/공유 DB를 자동 테스트 대상으로 사용하지 않았다. 기본 실행은 /tmp 작업 경로, 깨끗한 환경, 저장소 PYTHONPATH, env 파일이 없는 상태로 실행했다. 확장 실행은 네트워크 비활성 임시 MySQL 8.4.6의 nadree_w02_test_* DB 및 SQLite fixture를 사용했다. Firebase는 demo-nadree-chat/로컬 Firestore, PG·FCM·계정 삭제는 대역이다.

| 실행 검사 | 실제 결과 | 해석 |
| --- | --- | --- |
| 기본 전체 pytest, 외부 MySQL/Firestore 설정 없음 | **314 passed, 10 skipped**, 70.93초, 기존 의존성 경고 2종 | 문서 기준 재현 |
| MySQL 포함 전체 29개 파일, 파일별 프로세스 | **320 passed, 4 skipped**, 실패 파일 없음 | MySQL 동시성 6개 추가 통과. 공유 DB 잠금 인수와 다름 |
| Firestore 통합 별도 실행 | **4 passed** | 기본/확장 회귀에서 건너뛴 동일 4개를 에뮬레이터에서 통과 |
| Firestore Rules | **4 passed**, 실패 0 | 고객/직접 직원 읽기, 쓰기 금지, 세션/쿼리 범위 제한 |
| callable 업무 핸들러 5개·만료 함수 | 통과 | 실제 Python 핸들러·합성 인증을 demo Firestore로 연결. HTTP App Check 종단과 다름 |
| 추가 배송·종료 조회 API 시나리오 | **20개 검사 통과** | 합성 주소·별도 SQLite. pytest 개수에 합산하지 않음 |

10개 건너뜀은 MySQL 6개와 Firestore 4개이며, 확장 회귀의 4개는 tests/test_chat_firestore.py다. 명시적 demo 프로젝트/에뮬레이터 설정이 없으면 실제 Firebase에 접근하지 않도록 skip한다. 이번 실행들을 합치면 해당 Python 테스트 324개가 실행돼 통과한 것이며, 반복 실행한 결과를 더해 테스트 수를 부풀리지 않는다. 기본 회귀·확장 회귀·에뮬레이터 모두 최종 정상 종료했다.

대표 실행 명령/기록:

```sh
# cwd=/tmp, env -i로 운영 env를 상속하지 않음
PYTHONPATH=/srv/nadree-api PYTHONDONTWRITEBYTECODE=1 \
  /srv/nadree-api/.venv/bin/python -m pytest /srv/nadree-api/tests \
  -q -p no:cacheprovider --tb=short -c /srv/nadree-api/pyproject.toml

# 실제 DB는 읽기 전용 계획만 조회
sudo -u ec2-user env PYTHONPATH=/srv/nadree-api \
  /srv/nadree-api/.venv/bin/python -m app.migrate
```

기본 로그는 build/test-runtime/baseline-2026-10-19.log, 확장 로그는 regression-2026-10-19-final.log, 에뮬레이터 로그는 emulator-2026-10-19.log다. 중단 전 regression-2026-10-19.log는 완료 결과로 사용하지 않았다.

## 3. 요구사항별 기대/실제 결과

아래의 ‘격리 통과’는 코드 읽기만 했다는 뜻이 아니라 실제 테스트 실행 결과다. 실제 서비스와 외부 실연동 여부를 별도로 표시한다.

| 항목 | 기대 | 실제 검증 | 판정·남은 범위 |
| --- | --- | --- | --- |
| 가용성·가격 | 승인 테스트 모델과 가격 옵션 제공 | 실제 availability 200. 테스트 지점/웹 모델 존재, priceOptionId/totalPrice 포함. BASIC DB 기대 일단가 25 일치, PREMIUM 응답이 DB 고정 단가와 일치 | 실제 읽기 통과 |
| BASIC 부분 우선·BASE 잔여·PREMIUM | 1~25 BASIC 우선, 나머지 BASE, PREMIUM 고정 | test_pricing_batch에서 부분 분할·경계 cc·고정 가격 실행 통과 | 격리 통과. 실제 DB에 새 BASE/부분 티어를 만들지는 않음 |
| 배열·동일 구간 수정 | UPDATED 저장, 중첩/중복 거절, 전체 원자성 | 실제 기존 테스트 BASIC 1행을 배열로 일시 +1 수정, GET으로 저장 확인 후 원값 복구·GET 확인. 중복 배열 422 TIER_BATCH_DUPLICATE_RANGE, 부분 중첩 409 TIER_RANGE_OVERLAP | 실제 수정/복구 통과. 신규/다중 항목·실패 원자성은 격리 통과 |
| 예약 생성·중복 | 요청 생성, 60초 이내 409 DUPLICATE_RENTAL_REQUEST | 기본 흐름 및 추가 배송 API에서 생성·행 저장·같은 요청 재전송 거절 통과 | 격리 통과. 실제 생성은 미검증(아래 영향 제한) |
| 다른 고객 예약 | 소유자 외 404 | 실제 승인 고객으로 다른 승인 시드 예약 직접 조회 404 RESERVATION_NOT_FOUND. 격리에서도 타 고객 접근 거절 | 실제/격리 통과 |
| 배송 | 주소 저장·선택 요금표 사용, 구역 추정 없음 | 합성 주소의 지역명과 무관하게 선택 ID 요금 적용. START_ONLY 회수비 0, 왕복 서로 다른 주소 보존, 다중 요금표 미선택 409 DELIVERY_REGION_REQUIRED. DB 저장값 확인 | 격리 API 통과. 실제 주소 판정/지리 검증은 범위 제외 |
| 이메일 직원 가입 | REQUESTED/PENDING_APPROVAL, 승인 전 관리권한 없음 | test_admin_signup 및 관련 권한 테스트 통과 | 격리 통과. 실제 새 계정 생성·권한 부여는 안 함 |
| 지점 코드 가입 | 대표 즉시 ACTIVE, 코드 1회 소진 | 격리 지점 생성→가입→코드 NULL→재사용 404 INVITE_CODE_NOT_FOUND, 직접 지점 권한 확인 | 격리 통과. 실제 기존 코드 소진 안 함 |
| 고객 취소 | 인계 전 시작일 전 90%, 당일부터 0%, 0%는 PG 환불 없음 | test_cancellation_policy의 날짜 경계·미결제·인계/권한 차단·환불 호출 검증 통과 | 격리 통과. 실제 PG 환불 미검증 |
| 지점 귀책 관리자 취소 | 당일 포함 인계 전 100%, BRANCH_FAULT만 | 당일/정확한 날짜 경계·인계 후 거절·반복/환불 정책 테스트 통과 | 격리 통과. 실제 기존 예약 취소 안 함 |
| 고객/관리자 조회 권한 | 서로 다른 인증 영역·지점 범위 | 실제 고객 Firebase 인증→로그인→profile/ongoing/completed 200, 대표·직원 로그인·main·알림 조회 200 | 실제 조회 통과 |
| 종료 내역 | 반납·취소·거절·만료 포함 | 추가 격리 API에서 4종 목록 포함, 각 본인 직접 조회 200·타 고객 404 확인 | 격리 통과. 실제 고객 종료 목록은 200이지만 빈 데이터여서 4종 실데이터 인수는 미검증 |

실제 쓰기는 사용자가 기존 시드 파일 기준으로 지정한 테스트 관리자·고객·지점만 사용했다. 가격은 기존 BASIC 값으로 복구됐고 신규 가격 행·공통 BASE는 추가하지 않았다. 승인 시도는 merchant 미연결로 409에서 차단됐으며 기존 예약은 승인/거절/취소로 바꾸지 않았다. 새 회원·지점·초대코드도 만들지 않았다.

예약/취소 실제 성공 요청은 기존 지점의 FCM 수신 토큰이 존재해 실제 푸시를 발생시킬 수 있으므로 수행하지 않았다. 실제 인증 검사를 풀거나 FCM 설정을 끄는 대신 격리 API로 검증했다. 마지막에 세 테스트 계정을 정상 로그아웃했다. 로그인/로그아웃의 기존 세션 및 채팅 세션 회수는 정상 인증 경로의 부수 효과이며, 계정 삭제·채팅 메시지 작성·방/업무 데이터 수정은 하지 않았다.

공개 HTTP/스키마 검사 **21개 통과**, 실제 승인 계정 검사 **33개 통과·설정 대기 1개·미검증 표시 1개**다. Swagger 경로 존재 확인은 업무 성공 검증의 대체 근거가 아니다. 실제 결과에는 HTTP 코드/오류 코드/통과 여부만 보관하고 응답 프로필·주소·토큰은 저장하지 않았다.

## 4. PayPal 판매자 연결

| 검사 | 기대/실제 | 판정 |
| --- | --- | --- |
| 지점 ID 없음 | 실제 APPROVE가 409 SHOP_PAYPAL_MERCHANT_REQUIRED. 격리에서는 상태 REQUESTED 유지·REJECT 200 확인 | 실제 승인 차단·격리 거절 통과 |
| 임의 ID 입력 | 실제 대표 PUT가 409 PAYPAL_ONBOARDING_REQUIRED, 직원은 403 PRIMARY_ADMIN_REQUIRED | 실제 통과, 연결값 변경 없음 |
| 직접 지점 대표만 연결 | 실제 직원 start 403. 다른 지점 대표/상위 대표 제한은 격리 실행 통과 | 실제 직원 차단·격리 통과 |
| 기존 컬럼·동일 ID 여러 지점 | 기존 컬럼 존재, 격리 start/verify에서 root/child 동일 판매자 저장·재전송·연결 해제 확인 | 구조 확인·격리 통과. 실제 연결 성공은 미검증 |
| Sandbox/Live 분리·원거래 판매자 | 격리에서 환경 불일치 차단·기존 결제 ID 보존·해제 후 원거래 환불 대상 유지 확인 | 격리 통과 |
| state 경계 | 실제 HTTP로 변조/다른 세션·지점·환경 400 PAYPAL_ONBOARDING_STATE_INVALID, 만료 410 PAYPAL_ONBOARDING_STATE_EXPIRED | 실제 부정적 경계 통과 |
| 복귀 URL | 실제 대표 start가 503 PAYPAL_ONBOARDING_RETURN_URL_REQUIRED | **설정 대기, 예상 결과** |
| 실제 Sandbox 인증 | 설정 반영·재시작 후 OAuth HTTP 200, 02:51:44 UTC 재확인도 200 | **통과(이전 401 해소)** |
| 실제 판매자 연결·결제·환불·서명 웹훅 정산 | 이번에 start 발급/복귀/판매자 저장·자금 처리를 하지 않음 | **미검증** |

실제 state 오류 테스트는 검증용 합성·변조 state를 현재 승인 관리자 인증으로 보낸 것이다. URL 미설정으로 정상 start state를 발급받아 실제 PayPal을 왕복한 결과와 구분한다. 실제 연결값·환경값·키·복귀 URL은 수정하지 않았다.

OAuth 401의 관측 원인은 PayPal의 invalid_client다. Sandbox 앱의 Client ID/Secret 조합 또는 환경 일치 여부 확인이 필요하지만 정확히 어느 값이 잘못됐는지는 이번 결과만으로 확정하지 않는다. LIVE endpoint로 바꿔 시험하거나 인증/판매자 검증을 우회하지 않았다. 웹훅 등록/판매자 이벤트 구독 재조회는 **미실행**이며 웹훅 자체의 실패로 판단하지 않는다. 이전 날짜의 인증 성공 결과를 현재 성공으로 사용하지 않는다.

### OAuth 요청·설정 재확인 — 2026-10-19 02:39:28 UTC

- 실행 중 `nadree-api.service`의 PID는 2509709이고 작업 경로는 `/srv/nadree-api`다. 서비스의 EnvironmentFile은 `/srv/nadree-api/.env`다. 실행 프로세스의 Client ID/Secret과 현재 파일에서 로드한 설정이 모두 일치했다.
- 두 설정은 각각 파일 및 프로세스 환경에서 한 번씩 존재했다. 누락·앞뒤 공백·CR/LF 줄바꿈은 없고 dotenv 구문 오류도 없었다. 다른 값으로 덮어쓰인 징후는 확인되지 않았다.
- 현재 `PayPalClient`의 HTTP 클라이언트로 OAuth 요청을 재현하고 전송 시점 요청을 검사했다. 실제 목적지는 `https://api-m.sandbox.paypal.com/v1/oauth2/token`, 메서드는 POST였다. HTTP Basic의 두 값은 실행 중 설정의 Client ID/Secret과 일치했고, 폼은 `grant_type=client_credentials`였다. 헤더·인증 값·응답 토큰은 출력하거나 저장하지 않았다.
- 원격 응답: **HTTP 401 / 오류 코드 `invalid_client` / PayPal Debug ID `f923072aff6ce`**.
- 웹훅 조회는 실행하지 않았다. 키 수정과 서비스 재시작도 하지 않았다. 파일과 실행 설정이 일치하므로 이번 결과를 미반영 설정 문제로 판단하지 않는다.
- 후속 작업: PayPal Developer의 **Sandbox REST 앱**에서 Client ID와 Secret이 동일 앱의 유효한 한 쌍인지 비공개로 확인한다. 401만으로 어느 값이 잘못됐거나 폐기됐는지, Live 키인지까지 확정할 수 없다. 사용자 승인에 따라 키를 수정한 경우 재시작 후 같은 OAuth 검사를 반복할 수 있다. 인증 검사는 우회하지 않는다.

검사 기록: `build/test-runtime/paypal-oauth-diagnostic-2026-10-19.json` (설정 진단 불리언·개수 및 허용된 응답 메타데이터만 저장).

**최신 재검사 — 2026-10-19 02:50:03 UTC: OAuth 통과.** 사용자 설정 수정 후 파일의 Sandbox Client ID/Secret 존재·공백·줄바꿈 조건을 확인했다. 실행 중 Client ID가 파일과 달라 기존 승인 범위에서 `nadree-api.service`를 재시작했다. 새 PID 2521781, active/running, 공개 `/health/live` HTTP 200을 확인했다. 재시작 후 두 자격증명이 파일과 실행 프로세스에서 일치했고 중복·누락·공백·줄바꿈은 없었다. Sandbox URL·HTTP Basic·grant_type 검사도 통과했다. **HTTP 200 / 오류 코드 없음 / PayPal Debug ID `f870441c0ae8b`**. 이전 OAuth 실패는 이 최신 결과로 해소됐다. 웹훅 조회·실제 판매자 연결·결제·환불은 이번 재검사에서 실행하지 않았으므로 해당 항목의 성공을 의미하지 않는다. 키·Authorization·access token은 출력하거나 저장하지 않았다.

재검사(2026-10-19 02:48:30 UTC): **HTTP 401 / 오류 코드 `invalid_client` / PayPal Debug ID `f851264c255ce`**。 이번에는 현재 파일에서 로드한 Client ID/Secret과 실행 프로세스 설정이 모두 불일치했다. `.env`에서 정확한 변수명 `NADREE_PAYPAL_CLIENT_SECRET`의 할당이 0개로 확인됐다(이전 검사에서는 1개). 실행 중 프로세스에는 기존 값이 존재한다. 파일 설정이 변경된 상태이므로 이전의 설정 일치 판정은 이번 시점에 적용되지 않는다. 키 값이나 변수명을 임의 수정하지 않았고, 불완전한 설정으로 서비스 재시작도 하지 않았다. 웹훅 조회는 미실행이다. 비공개로 해당 변수명과 값의 저장을 완료한 후 설정 반영·재검사가 필요하다.

재검사(2026-10-19 02:44:14 UTC): **HTTP 401 / 오류 코드 `invalid_client` / PayPal Debug ID `f923639ef3d45`**. 파일과 실행 중 설정 일치, 누락·공백·줄바꿈·중복 없음, Sandbox URL·Basic 인증·grant_type 정상임을 다시 확인했다. 웹훅 조회·설정 변경·서비스 재시작은 수행하지 않았다.

재검사(2026-10-19 02:42:32 UTC): 사용자의 설정 적용·재시작 완료 안내 후 다시 확인했다. 현재 파일과 실행 프로세스의 Client ID/Secret은 여전히 일치하며 누락·공백·줄바꿈·중복이 없었다. Sandbox URL·Basic 인증·grant_type 검사도 통과했다. 원격 응답은 **HTTP 401 / 오류 코드 `invalid_client` / PayPal Debug ID `f2876551da837`**였다. 웹훅 조회는 미실행이다. 관측 PID는 앞선 검사와 같은 2509709로, 두 검사 사이 재시작 여부를 이 결과로 입증하지는 않는다. 설정 변경이나 추가 재시작은 수행하지 않았다.

기존 결제 중 판매자 ID가 없는 행은 읽기 전용 집계에서 4개다. 마이그레이션은 이를 임의 추정/보충하지 않는다. 격리 테스트는 seller가 없는 기존 결제를 PAYMENT_MERCHANT_RECONCILIATION_REQUIRED로 차단함을 확인했다. 이 4개 실제 거래의 판매자/복구 상태는 별도 대조가 필요하며 수정·환불·재시도하지 않았다.

## 5. 탈퇴·채팅·App Check

| 항목 | 실제 실행 근거 | 판정 |
| --- | --- | --- |
| 탈퇴 프로필/FCM·세션 | test_nadri_auth에서 DELETE 성공 응답, 프로필/FCM 비움, access/refresh 차단, 이전 auth_time 재사용 거절 확인 | 격리 통과 |
| Firebase 삭제·채팅 회수 | 외부 호출 대역의 순서/대상, 서비스 실패 시 503·SQL 폐기/성공 오표시 방지 확인 | 격리 통과. 실제 삭제 종단 미검증 |
| 전용 개인정보 작업 테이블 없음 | 실제 이름 점검·현재 metadata와 기존 처리 확인 | 통과(구조). 신규 테이블 생성 없음 |
| 대표 답변·일반관리자 읽기 | MemoryStore/Firestore 에뮬레이터/실제 함수 업무 핸들러에서 대표 전송 성공·직원 전송 거절/열람 허용·다른 지점 차단 | 격리/에뮬레이터 통과. 실제 메시지 종단 미검증 |
| App Check | 문서 지정 고객/관리자 비공개 JSON 미제공·해당 경로 파일 없음 | 미검증. 비활성화/위조 등록/보안 완화 안 함 |

실제 회원 삭제는 별도 승인 대상이므로 기존 고객 UID를 삭제하지 않았다. 승인된 실제 폐기용 계정과 App Check 비공개 자료 없이 해당 종단을 실행하지 않는다. Firebase 삭제 후 SQL 실패 같은 분산 처리의 부분 성공은 기존 인수 문서의 운영 확인 항목이며 새 작업 테이블·자동 정리 타이머로 대체하지 않았다. 실제 채팅 본문/거래 주소의 후속 삭제도 이번 범위가 아니다.

## 6. 실패·설정 대기·미검증과 후속 작업

1. **해소 — Sandbox OAuth 401 invalid_client:** 설정 반영·승인된 재시작 후 HTTP 200 확인. 추가 키 수정은 필요하다고 판단하지 않는다. 웹훅 이벤트 누락도 02:58 UTC 사용자 승인 후 보완·재조회 완료했다.
2. **설정 대기 — 앱 복귀 URL:** 프론트가 HTTPS App Link/Universal Link 등 실제 복귀 주소를 확정하여 서버 담당자에게 전달한다. 임의 URL을 넣지 않았다. 주소 확정·설정·현재 관리자 세션 유지 후 실제 start→복귀→verify 성공을 다시 확인한다.
3. **운영 동작 미검증 — 결제 복구 작업:** 로컬 systemd unit 없음·검사한 cron 직접 등록 없음. 외부 스케줄러가 있다면 주체/주기/최근 성공 결과를 제공해야 한다. 없으면 설치 대상·처리할 승인 테스트 거래·실제 PG/알림 영향을 검토한 뒤 별도 승인한다. 기존 작업 삭제/중지는 하지 않았다.
4. **미검증 — 실제 PG·탈퇴·App Check·기기:** Partner 권한·검증된 판매자·구매자 승인·테스트 거래, 승인된 폐기용 계정 및 보호된 App Check 자료로 별도 인수한다. 이번 모의·에뮬레이터 통과를 실제 외부 성공으로 표시하지 않는다.
5. **미검증 — 실제 가입코드 소진/새 계정·예약 생성/취소/배송 저장:** 운영 데이터·권한·알림을 변경하지 않도록 격리에서 수행했다. 별도 지정한 소모 가능한 지점/계정/차량 및 푸시 영향 승인이 있으면 실제 서비스에서도 이어서 확인할 수 있다.

프론트 확인 사항:

- 앱 복귀 화면·링크·종료 처리는 프론트 담당. PayPal 완료/복귀 자체를 성공으로 표시하지 않고 state와 **같은 관리자 세션**으로 verify 성공 후 종료한다. 실패·취소를 구분하고 예약 승인은 별도 재요청한다.
- HTTPS 복귀 주소는 query/fragment 없이 확정해 전달한다. custom scheme은 현재 HTTPS 제한과 먼저 협의한다. state를 로그·분석도구에 남기지 않고 URL에서 제거한다. 만료/다른 세션이면 start부터 다시 진행한다.
- priceOptionId/배송 포함 totalPrice는 응답 값을 사용하고 임의 합성·배송비 중복 가산을 하지 않는다. effectiveTiers는 편집용 원구간이 아니며 tiers를 저장/삭제에 사용한다.
- 응답 유실은 새 요청을 무조건 보내지 말고 진행/종료 목록·본인 예약 직접 조회로 확인한다. 중복 검사는 60초이며 장기 멱등/요청 결과 저장 테이블은 없다.
- 주소는 지리 검증 결과가 아니다. 배송 요금표 선택을 구역 판정처럼 표시하지 않는다. 관리자 취소는 지점 귀책 100%이며 고객 취소 90%/0%와 분리한다.
- 탈퇴/로그아웃 시 클라이언트 캐시를 비우고 App Check·Android/iOS 복귀·실기기 푸시는 별도로 확인한다.

## 7. 결과 파일

### OAuth 해소 후 추가 검증 — 2026-10-19

현재 코드 `ba23d26580d25bb23621fe021e2af885a6633932` 기준, 02:51:44 UTC에 Sandbox 읽기 전용 검사를 수행했다.

| 검사 | 기대 | 실제 | 판정 |
| --- | --- | --- | --- |
| OAuth | HTTP 200 | HTTP 200, 오류 없음, Debug ID `ca4cc7b93398f` | 통과 |
| 웹훅 목록 | HTTP 200 및 현재 설정 ID 존재 | HTTP 200, 설정 ID 존재, Debug ID `ca4cc7b979b4d` | 통과 |
| 웹훅 상세 | HTTP 200, 현재 API 콜백 일치 | HTTP 200, `https://na-dree.com/nadreego/paypal/webhook` 일치, Debug ID `ca4cc7b9bfcad` | 통과 |
| 이벤트 구독 | 서버 처리 이벤트 구독 | 아래 5개 누락, 와일드카드 구독 없음 | 실패(설정 불일치) |
| 앱 복귀 URL | 프론트 확정값 설정 | 미설정 | 설정 대기 |
| Partner 설정 | 유무·형식 확인 | Merchant ID 존재·13자리 형식 충족, Attribution ID 존재 | 형식 확인만. 실제 Partner 권한 미검증 |

누락 이벤트는 `CHECKOUT.PAYMENT-APPROVAL.REVERSED`, `PAYMENT.CAPTURE.DECLINED`, `PAYMENT.CAPTURE.REVERSED`, `PAYMENT.REFUND.FAILED`, `PAYMENT.REFUND.PENDING`이다. 해당 이벤트가 현재 구독을 통해 전달되지 않아 승인 철회·캡처 거절/취소·환불 보류/실패의 이벤트 기반 반영이 누락될 수 있다. 별도 조회·복구 작업이 모두 대체한다고 판단하지 않는다. **수정안은 현재 Sandbox 앱에서 조회된 기존 웹훅 한 개에 이 5개 구독만 추가하고 콜백·기존 구독을 보존하는 것이다. 신규 웹훅 생성·삭제나 Live 변경은 필요하지 않다. 이번 작업에서는 설정 변경을 실행하지 않았으며 승인 후 적용한다.**

추가 격리 회귀: `test_paypal_onboarding.py`, `test_payment_safety.py`, `test_payment_deadline_policy.py`, `test_refunds.py`, `test_webhook_replay.py`를 `/tmp`에서 `env -i`로 서버 환경변수를 제거하고 실행했다. **50 passed, 0 failed, 0 skipped (9.54초)**. 테스트 DB·모의 PG를 사용했으며 실제 서비스 DB를 대상으로 실행하지 않았다. 판매자 연결/state/권한, 결제 중복·응답 불명·지연/역순 처리, 결제 기한, 취소·환불 정책, 웹훅 서명 시간·재전송/멱등 처리를 검증했다. 샌드박스 내 첫 실행들은 진행 지연으로 중단했고, 권한 승인 후 같은 격리 조건에서 재실행한 최종 결과다. 의존성 deprecation 경고 2건은 실패가 아니다.

실제 판매자 연결은 확정 복귀 URL과 Sandbox 판매자 동의가 필요하다. 실제 주문 승인·캡처·환불 및 서명된 웹훅 수신/정산은 이번에 실행하지 않았고 미검증이다. 현재 변경된 앱의 승인된 거래·판매자 연결 대상이 확정되지 않았으므로 과거 앱의 주문을 재사용하지 않았다. 진행하려면 테스트 판매자·구매자, 소액 거래 대상 및 Sandbox 캡처·환불 영향에 대한 승인이 필요하다. 실제 고객·Live·푸시·회원 삭제는 실행하지 않았다.

원격 조회 기록: `build/test-runtime/paypal-post-oauth-2026-10-19.json`. 비밀값·인증 헤더·access token은 기록하지 않았다.

git에서 제외되는 build/test-runtime 아래에 비밀값 없는 재현 자료를 보관했다.

- baseline-2026-10-19.log / regression-2026-10-19-final.log / emulator-2026-10-19.log
- public-verification-2026-10-19.json: 실제 HTTP/스키마 21개
- live-verification-2026-10-19.json: 통과 33·설정 대기 1·미검증 1
- delivery-api-2026-10-19.json / delivery-terminal-api-2026-10-19.log: 추가 격리 20개
- system-verification-2026-10-19.json: 서비스·등록·오류 건수
- paypal-readonly-2026-10-19.json: 현재 Sandbox OAuth 실패

검증 도구의 경로/표기/컬럼명 조정은 보조 스크립트에만 했고 애플리케이션·마이그레이션·Firebase·서비스 설정은 수정하지 않았다. 실제 테스트 지점 가격 수정/원복과 승인 테스트 계정 인증 외 업무 데이터 쓰기는 하지 않았다. 토큰·비밀번호·실제 프로필·실제 배송 주소·개인정보 응답 원문은 결과 파일이나 이 문서에 넣지 않았다.


## 8. 승인된 Sandbox 웹훅 구독 보완 완료 — 2026-10-19 02:58 UTC

대상은 실행 중 서비스가 설정한 현재 Sandbox 앱의 **기존 웹훅 한 개**다. 사용자 승인에 따라 최신 상세를 읽고 기존 구독과 아래 5개 이벤트의 합집합으로 `/event_types`만 PATCH했다. 변경 직전 상세를 다시 읽어 첫 조회 이후 콜백·구독이 바뀌지 않았는지 확인했다. 적용 방식은 [PayPal 공식 웹훅 API 명세](https://github.com/paypal/paypal-rest-api-specifications/blob/main/openapi/notifications_webhooks_v1.json)의 기존 웹훅 PATCH를 따랐다.

추가한 이벤트:

- `CHECKOUT.PAYMENT-APPROVAL.REVERSED`
- `PAYMENT.CAPTURE.DECLINED`
- `PAYMENT.CAPTURE.REVERSED`
- `PAYMENT.REFUND.FAILED`
- `PAYMENT.REFUND.PENDING`

| 검사 | 실제 결과 | 판정 |
| --- | --- | --- |
| Sandbox OAuth | HTTP 200, 오류 없음, Debug ID `f6530810788fb` | 통과 |
| 기존 웹훅 구독 수정 | HTTP 200, 오류 없음, Debug ID `f164470299fc2` | 통과 |
| 적용 후 상세 재조회 | HTTP 200, 오류 없음, Debug ID `f7075851311b6` | 통과 |
| 웹훅 동일성 | 설정한 기존 웹훅 ID와 동일 | 통과 |
| 콜백 보존 | `https://na-dree.com/nadreego/paypal/webhook` 유지 | 통과 |
| 기존 이벤트 보존 | 기존 10개 모두 보존, 승인된 5개만 추가, 총 15개 | 통과 |
| 승인 이벤트 및 서버 처리 이벤트 | 누락 모두 0개 | 통과 |

새 웹훅 생성·삭제·Live 요청·키 변경·API 재시작·DB 변경은 하지 않았다. 비밀값·Authorization·access token은 출력하거나 저장하지 않았다. 변경 전후 이벤트 목록과 허용된 응답 메타데이터는 `build/test-runtime/paypal-webhook-update-2026-10-19.json`에 기록했다. 복구가 필요할 경우 이 기록의 변경 전 이벤트 10개로 해당 웹훅의 `/event_types`만 되돌릴 수 있으나, 복구 변경은 별도 승인 후 수행한다.

위의 과거 이벤트 누락 실패·승인 대기 기록은 이 최신 완료 결과로 대체된다. 실제 결제·환불·서명된 이벤트 전달과 DB 정산 종단 검증, 실제 판매자 연결 및 앱 복귀 URL 설정 대기는 여전히 별도 미검증/설정 대기다. 구독 설정 성공을 실제 이벤트 처리 성공으로 표시하지 않는다.

## 9. 실제 서버 테스트 데이터 진행 확인 — 2026-10-19 03:00:05 UTC

사용자의 실제 테스트 요청에 따라 DB가 `RIDERLOG_V2_DATA_TEST`인지 재확인하고 기존 승인 테스트 지점·대표·예약만 사용했다. 실제 HTTPS API를 호출했으며 모의 응답이 아니다. 현재 승인 지점의 판매자 ID는 없고 앱 복귀 URL도 미설정이다.

| 실행 검사 | 기대/실제 | 판정 |
| --- | --- | --- |
| 테스트 대표 로그인 | HTTP 200 | 통과 |
| 테스트 지점 판매자 상태 조회 | HTTP 200, 미연결 | 조회 통과·연결 선행 필요 |
| 실제 판매자 연결 시작 | HTTP 503 `PAYPAL_ONBOARDING_RETURN_URL_REQUIRED` | 예상 차단 확인·설정 대기 |
| 기존 테스트 예약 승인 시도 | HTTP 409 `SHOP_PAYPAL_MERCHANT_REQUIRED` | 예상 차단 확인·판매자 연결 대기 |
| 승인 시도 후 예약 보존 | 기존 REQUESTED 유지 | 통과 |
| 실제 웹훅에 서명 없는 요청 | HTTP 400 | 보안 차단 통과·정상 서명 이벤트 수신은 미검증 |
| 테스트 대표 로그아웃 | HTTP 200 | 통과 |

7개 검사에서 기대 응답/상태를 확인했지만, 설정 대기 응답을 정상 판매자 연결·결제 성공으로 계산하지 않는다. 로그인·로그아웃은 해당 테스트 대표의 인증/채팅 세션에 영향을 주는 기존 동작이며 별도 고객이나 일반 운영 계정은 사용하지 않았다. 주문 생성·캡처·환불·푸시 발송은 모두 0건이다. 판매자 ID 수동 주입·임의 복귀 URL·검사 우회는 하지 않았다.

다음 선행 작업은 프론트가 확정한 HTTPS 앱 복귀 URL 설정과 해당 테스트 지점 대표의 Sandbox 판매자 연결 동의다. 이 작업 후 소액 Sandbox 주문 생성→구매자 승인→캡처→환불 및 실제 서명 웹훅/정산 확인을 이어갈 수 있다. 과거 앱의 테스트 주문은 재사용하지 않았다.

기록: `build/test-runtime/paypal-real-preflight-2026-10-19.json`, `build/test-runtime/paypal-real-api-progress-2026-10-19.json`. 비밀번호·토큰·개인정보·Secret은 기록하지 않았다.
