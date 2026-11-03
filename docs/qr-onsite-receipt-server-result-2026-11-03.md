# QR 현장 신청·고객 인수 확인 서버 적용·검증 결과

검증일: **2026-11-03 UTC**. 최초 점검 02:26, 전체 격리 회귀 02:29:20~02:32:33, DB 적용 02:42:39~02:42:52, API 재시작 02:44:38, 타이머·데이터 최종 점검 02:54:19, 외부 API 추가 확인 03:12:06. 발리 시간은 UTC+8이다.

**서버 적용 완료, 고객 인수 기능은 비활성 유지.** 마이그레이션 잔여 0개, 기존 예약 29건 보존, API·전용 타이머 정상이다. 전체 격리 회귀는 **572 passed / 14 skipped / 0 failed / 0 errors**다. 실제 고객 신청·인계·인수·반납이나 실기기 푸시 성공을 의미하지 않는다.

기준 계약: [QR 현장 신청·고객 인수 전달서](qr-onsite-receipt-handoff-2026-11-03.md). 이번에는 업무 코드를 추가 수정하지 않고 요청된 커밋의 적용·검증을 수행했다.

## 1. Git·문서 통합

| 항목 | 확인 결과 |
| --- | --- |
| 브랜치 / 적용 커밋 | `main` / `e31008c251a8cb0369f2e7c84776914704f6ea2f` (`프론트 요청사항`) |
| 업데이트 판단 | 최초 HEAD가 이미 요청 커밋이었다. 로컬 문서 변경 3개가 있어 추가 pull을 하지 않음 |
| 기존 로컬 기록 | 채팅 트리거 결과·외부 결제 앱 전달서·외부 결제 서버 결과의 기존 수정 보존. 10월 29일 테스트 예약 준비 이력도 유지 |
| 통합한 stash 기록 | README와 전체 인수 문서의 07:50 env/재시작 및 08:17 OIDC 콜백 검증 기록, 총 4개 문단. 11월 3일 새 QR 변경 내용과 함께 보존 |
| 충돌 | Git 미해결 경로 0개, 관련 추적 파일 150개에서 충돌 표시 0개. `git diff --check` 통과 |
| stash | **삭제하지 않음**. `stash@{0}: On main: server-docs-before-pull-20261103`, OID `01e48b41d1c1b53d7d11b7f1c4fb487edbbba48d` 유지 |

강제 초기화·브랜치 전환·stash pop/drop/clear·자동 커밋은 하지 않았다. 통합 전 문서 원본과 통합 확인 결과는 `build/test-runtime/qr-receipts-2026-11-03/`에 보존했다. AGENTS.md·README·최신 전달서를 확인했으며, AGENTS.md가 참조하는 `/srv/rental-project-master.md`와 `/srv/rental-api-review-decisions.md`는 현재 서버에 없었다.

## 2. 실제 서버 적용

| 항목 | 실제 결과·판정 |
| --- | --- |
| 서비스 | `nadree-api.service`, `ec2-user`, `/srv/nadree-api/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8008` |
| 실행 경로 | 작업 디렉터리 `/srv/nadree-api`, Python 3.12 가상환경 |
| DB | 실제 연결의 `SELECT DATABASE()`와 설정 모두 **RIDERLOG_V2_DATA_TEST**, MySQL 8.0.45 |
| DB 백업 | **전체 76개 테이블**의 데이터·스키마와 routines/events/triggers를 single-transaction 방식으로 백업. dump 종료 0, gzip 전체 읽기·예약 CREATE TABLE·완료 푸터 확인 |
| 백업 접근 | ec2-user 전용 0700 경로, 압축 SQL 0600. 압축 18,010,107바이트, 원본 SQL 641,556,059바이트. 실제 복원 실행은 미검증 |
| 서비스 계정 계획 | `ec2-user`로 `python -m app.migrate` 읽기 전용 실행: 6개 pending |
| 마이그레이션 | `ec2-user`로 `python -m app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST` 실행: 6개 적용 |
| 재계획 | 적용 직후 CLI `No pending changes.`. 02:54 최종 읽기 전용 계획도 0개 |
| 기존 데이터 | 예약 29행의 모든 기존 컬럼을 적용 전후 비교해 동일 확인. 새 인수 필드의 non-NULL 값 0개. 기존 예약 상태·배정·가격·고객을 변환하지 않음 |
| env | 기존 내용 바이트를 보존하고 **NADREE_CUSTOMER_RECEIPT_ENABLED=false**만 명시. 기존 ec2-user 소유권·그룹·0600 유지 |
| 기존 결제 정책 | 실행 중 프로세스에서 `NADREE_RESERVATION_PAYMENT_METHOD=EXTERNAL`, `NADREE_PAYPAL_CHECKOUT_ENABLED=false` 유지 |
| 재시작 | **1회**, 02:44:38 UTC. PID 2660137 → **3479440**, active/running |
| Firebase | 배포·Rules·인덱스·키 변경 없음 |

적용한 DB 변경은 다음 6개뿐이다.

1. `MSP_RESERVATION.client_request_id VARCHAR(64) DEFAULT NULL`.
2. `MSP_RESERVATION.handed_over_at DATETIME DEFAULT NULL`.
3. `MSP_RESERVATION.receipt_deadline_at DATETIME DEFAULT NULL`.
4. `uq_reservation_client_request (uid_token, client_request_id)` UNIQUE.
5. `idx_reservation_receipt_deadline (reservation_status, receipt_deadline_at)`.
6. `ck_reservation_status` CHECK 추가. 기존 DB에 상태 CHECK가 없어, 기존 상태와 `HANDOVER_PENDING`을 함께 허용하는 제약을 추가했다.

기존 QR·센서·가격·계약·결제·고객 행을 변환하거나 테스트 시드를 실행하지 않았다. 전용 신규 결과/개인정보/온보딩 테이블도 만들지 않았다.

백업 위치: `/srv/nadree-api/build/test-runtime/qr-receipts-server-2026-11-03/RIDERLOG_V2_DATA_TEST-before-receipts-20261103.sql.gz`. 백업용 DB 비밀번호는 일시적인 0600 옵션 파일로만 전달했고 완료 후 해당 파일을 제거했다. 비밀값을 명령 인자·출력·결과 문서에 남기지 않았다.

## 3. 실제 서버 HTTP·로그 검사

아래는 실제 서비스에 보낸 요청이다. 인증된 업무 쓰기나 새 테스트 예약 생성은 수행하지 않았다.

| 검사 | 기대 | 실제·판정 |
| --- | --- | --- |
| 로컬·공개 `/health/live` | 200 | 모두 200, 통과 |
| 로컬·공개 `/health/ready` | 200 | 모두 200·status=ok, 통과. 기존 제한 `MFA_FLOW_NOT_IMPLEMENTED`는 유지 |
| 로컬·공개 `/docs`, `/openapi.json` | 200 | 모두 200, 통과 |
| OpenAPI 신규 경로 6개 | 등록 및 요청/응답 필드 제공 | 모두 등록. receiptRequired·customerReceiptRequired·canReceive·vehicleRecoveryRequired 확인, 통과 |
| 로컬·공개 신규 고객 경로 5개 무인증 | 401 INVALID_NADRI_USER_TOKEN | 모두 일치, 통과 |
| 로컬·공개 관리자 회수 경로 무인증 | 401 AUTH_REQUIRED | 모두 일치, 통과 |
| 공개 기존 125cc availability | 200, EXTERNAL/온라인 중단 | 200·newReservationPaymentMethod=EXTERNAL·onlinePaymentEnabled=false·옵션 5개, 통과 |
| 재시작 이후 API 로그 | 시작 실패·ASGI 오류·Traceback 없음 | 02:54 점검에서 모두 0개, 통과. 개인정보가 포함될 수 있는 로그 본문은 출력하지 않음 |

신규 경로는 고객 `POST /api/v1/nadree/rental/qr/lookup`, `POST /onsite/quote`, `POST /onsite/requests`, `GET /onsite/requests/{client_request_id}`, `POST /reservations/{reservation_id}/receive`와 관리자 `POST /nadreego/booking/{booked_no}/receipt-recovery`다. 고객 경로의 생략된 접두사는 모두 `/api/v1/nadree/rental`이다.

명시적으로 기록한 실제 HTTP 검사는 재시작 검증 14개와 공개 경로/availability 추가 검증 7개다. 유효 고객 토큰으로 flag=false를 확인하는 업무 API 호출은 하지 않았다. 비활성 정책·인증 후 업무 동작은 아래 격리 API 결과와 구분한다.

## 4. 전용 만료 타이머

- `deployment/nadree-receipts.service`, `.timer`를 `/etc/systemd/system/`에 0644로 설치하고 원본과 바이트 일치를 확인했다.
- daemon-reload 후 `systemctl enable --now nadree-receipts.timer` 실행. **enabled / active / waiting** 확인.
- 실행 명령은 `ec2-user`, `/srv/nadree-api`, `.venv/bin/python -m app.jobs receipts`만 사용한다. 기존 MySQL receipts 작업 잠금을 재사용한다.
- 설정은 `OnBootSec=1min`, `OnUnitInactiveSec=1min`이다. 완료 후 1분 기준 systemd 일정이므로 정확한 매시각 00초 실행을 의미하지 않는다.
- 02:44:46~02:53:32 UTC 자동 완료 **9회**에서 모두 `receiptsExpired=0`, 마지막 서비스 `Result=success / ExecMainStatus=0` 확인. one-shot 서비스의 완료 후 inactive/dead는 정상이며 타이머는 계속 active다.
- 설치 전 HANDOVER_PENDING·ONSITE·고객 인수 필요 예약 모두 0건임을 확인했다. 자동 실행 후에도 기존 예약 29건의 원래 데이터가 동일했다.
- `/etc/cron.d/nadree-payment-recovery`와 기존 채팅 service/timer는 파일 해시 불변. `crond.service`와 `nadree-chat-sync.timer` active 유지. 기존 결제 작업이나 jobs all에 receipts를 추가하지 않았다.

타이머가 돌았다는 결과와 실제 인수 만료 데이터를 처리한 결과를 혼동하지 않는다. 실제 데이터 만료 처리는 0건이며, 보호·만료·회수의 변경 동작은 격리 테스트에서 검증했다.

## 5. 격리 전체 회귀와 신규 업무 흐름

현재 소스를 별도 디렉터리에 복사하고 실제 `.env`·외부 인증 환경변수·서비스 DB 주소를 제외했다. 일회용 SQLite와 FastAPI TestClient를 사용했으며, 기능 활성은 격리 앱 설정에서만 수행했다. 외부 PayPal은 호출 시 테스트 실패하는 대역, FCM은 수집/실패 대역을 사용했다. 실제 고객·PG·Firebase·FCM에 쓰지 않았다.

실행은 `.venv/bin/python -m pytest <격리 소스>/tests -q --tb=short --junitxml=...`이며 결과는 **총 586개: 572 통과, 14 건너뜀, 실패/오류 0개**다. 신규 `test_customer_receipt.py`는 **18개 통과 + MySQL 동시성 2개 건너뜀**이다.

| 요구사항 | 격리 기대 결과 | 실제·판정 |
| --- | --- | --- |
| 공용 QR 원문·대소문자 | 기존 HMAC 원문 사용, 임의 대문자 변경 실패 | 조회·요청 대소문자 보존 및 다른 QR 차단, 통과 |
| 현장 견적·신청 | 당일 시작·EXTERNAL·차량 고정·결제 행 없음 | REQUESTED/가격/배정 조건 및 PG 비호출, 통과 |
| 중복·접수 결과 | 같은 키·내용은 같은 예약, 다른 내용 재사용 차단 | 예약 1건·GET 복구·가격/견적/소유권/만료 차단, 통과 |
| 관리자 인계 | HANDOVER_PENDING/LOCKED, 계약 없음 | 재호출해도 기한 유지·안내 큐 중복 없음·회수 액션 제공, 통과 |
| 고객 본인 인수 | 본인 예약·배정 QR 확인 후 HANDED_OVER/ON_RENT | 다른 고객/차량/인계 전 차단·성공 후 계약 1개·재시도 동일 계약, 통과 |
| 발리 자정 | 배치 전에도 마감 시각부터 인수 차단 | RECEIPT_DEADLINE_EXPIRED 경계 검사, 통과 |
| 미인수 만료 | EXPIRED여도 배정/차량 DISABLED 보호 유지 | 자동 해제 없음·반납/이동/재배정 차단·반복 만료 0건, 통과 |
| 직원 실물 회수 | vehicleReturned=true와 사유·권한·QR 확인 후 해제 | 누락 422, 정상 회수 CANCELED/RELEASED·가용 상태 복원, 통과 |
| feature=false | 신규 진입 차단, 이미 필요한 건의 인수/회수 유지 | 신규 앱의 receiptRequired 오인계 방지·기존 필요 건 완료, 통과 |
| FCM 실패 | 발송 실패가 인계를 되돌리지 않음 | HANDOVER_PENDING 유지·계약 생성 없음, 통과. 실제 발송은 하지 않음 |
| 기존 예약·가격·권한·반납 | 기존 회귀 유지 | 전체 회귀 통과. 기존 ON_RENT의 재인수 강제 없음 |

## 6. 실패·건너뜀·미검증

최종 서버 적용·회귀의 미해결 실패는 없다. 준비 중 결과 저장 디렉터리의 서비스 계정 쓰기 권한, Git 소유권 검사, 로그 시각 형식 때문에 보조 검사가 중단된 적은 있다. 새 전용 ec2-user 경로, 해당 Git 조회 명령에만 지정한 `safe.directory`, journalctl 지원 UTC 형식으로 해결했다. 이 과정에서 기존 경로 소유권·전역 Git 설정·업무 코드를 바꾸거나 마이그레이션을 중복 적용하지 않았다. 별도 검증 복사본은 추적된 가상환경/CA 번들을 제외하고 서비스 소스만 준비했다.

| 구분 | 항목·이유 | 필요한 후속 작업 |
| --- | --- | --- |
| 건너뜀 10개 | 일회용 MySQL URL 미지정. 현장 신청 중복 제출·동시 고객 인수 2개와 기존 MySQL 동시성/FK 8개 | 빈 `nadree_w02_test_*` 전용 DB를 확보해 실행. 서비스 DB를 대입하지 않음 |
| 건너뜀 4개 | demo-nadree-chat Firestore 에뮬레이터 미기동 | 격리 에뮬레이터에서 채팅 동시성·권한·읽음 검사 |
| 경고 14개 | 기존 라이브러리 deprecation 2개 및 Google Auth 전송 테스트 대역 close 경고 12개 | 별도 의존성/테스트 대역 정리 대상. 기능 성공으로 대체하거나 새 서버 장애로 계산하지 않음 |
| 미검증 | 실제 고객/관리자 앱의 로그인·스캔·화면·HTTP 인증 후 업무 왕복 | 양 앱 계약 연결 후 승인된 테스트 계정·차량으로 공동 인수 |
| 미검증 | 실기기 FCM·App Check | 비공개 테스트 자료와 테스트 기기로 별도 검증. 인증 검사 완화 없음 |
| 미검증 | 백업의 실제 DB 복원 | 별도 빈 복구 DB에서 복원 리허설. 현재는 dump 성공·압축 무결성만 확인 |

실제 회원/고객 변경·예약 생성/취소·실제 인계/회수·결제·환불·시험 푸시·Firebase 배포는 이번 작업에서 실행하지 않았다.

## 7. 앱 전달·남은 작업·복구

1. 고객 앱은 공용 QR 원문을 그대로 보내고, 현장 견적→clientRequestId 보존→신청/결과 조회→명시적 receive를 연결한다. QR 조회나 알림 선택만으로 인수 처리하지 않는다.
2. 관리자 앱은 receiptRequired=true, HANDOVER_PENDING·인수 기한·보호/회수 상태와 RECOVER_VEHICLE 액션을 지원한다. 관리자 인계만으로 ON_RENT로 표시하지 않는다.
3. **현재 서버 설정은 false이므로 양 앱 통합 전 신규 인수 기능을 사용할 수 없다.** 앱 준비 후 격리/승인된 테스트 환경에서 공동 검증하고, 별도 활성화 요청으로 true 및 재시작을 진행한다. 임의로 이번 서버를 활성화하지 않았다.
4. MySQL/Firestore 건너뜀과 실기기 검증을 별도 완료한다. 참고 계약은 [전달서](qr-onsite-receipt-handoff-2026-11-03.md)다.
5. 복구 시 false를 유지하고 이미 인수/회수 필요한 건은 현재 코드로 마무리한다. 보호 차량이 남으면 구버전 바이너리나 AVAILABLE 강제 SQL을 적용하지 않는다. 신규 nullable 컬럼·CHECK·기록은 보존하며 전체 백업을 현재 DB에 자동 덮어쓰지 않는다.
6. 통합 확인용 stash는 계속 보존했다. 사용자가 최종 확인한 뒤 별도로 정리할 수 있다.

증거 파일은 접근 제한된 `build/test-runtime/qr-receipts-2026-11-03/`와 ec2-user 소유 `build/test-runtime/qr-receipts-server-2026-11-03/`에 분리 보관했다. 이 문서에는 자격증명·토큰·고객 UID·개인정보를 기록하지 않았다.
