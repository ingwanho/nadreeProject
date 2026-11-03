# QR 현장 신청 최종 변경 — 서버 사전 점검·격리 검증 결과

**후속 배포 완료:** 이후 사용자가 양 앱 준비 완료와 즉시 배포를 승인해 **2026-11-03 07:35 UTC 서버 전환을 완료**했다. 아래 보류 기록은 당시 사전 점검 이력으로 보존한다. 현재 적용 상태·시험 QR·미검증 항목은 [최종 배포 결과](qr-onsite-final-server-deployment-result-2026-11-03.md)를 따른다.

검증일: **2026-11-03 UTC**. Git 확인 07:09 이후, 실제 서버 점검 07:13:42, 격리 전체 회귀 07:12:30~07:16:05, 서비스·설정 보존 최종 확인 07:19:19. 발리 시간은 UTC+8이다.

**사전 점검과 격리 검증 완료. 신규 서버 전환은 보류했다.** 사용자가 양 앱 준비 질문에 **“아직 미확인 — 사전 점검·격리 검증만 진행”**으로 답했다. 실행서와 이 답변에 따라 API 드레인/중지/재시작, 새 테이블 적용, env 제거, 실제 QR 차량 등록을 하지 않았다.

기준: [최종 서버 실행서](qr-onsite-final-server-apply-2026-11-03.md), [추가 계약](qr-onsite-followup-contract-2026-11-03.md). 이전 서버의 실제 적용 기록은 [기존 결과](qr-onsite-receipt-server-result-2026-11-03.md)이며, 아래 신규 코드 검증과 구분한다.

## 1. Git·기존 문서 보존

| 항목 | 실제 결과 |
| --- | --- |
| 시작 상태 | `main`, 추적/미추적 로컬 변경 없음. HEAD `254507d` |
| 업데이트 | `git pull --ff-only origin main` 성공, `Already up to date.` |
| 최신 커밋 | `254507d802c08241d82f1f45e55481f694cb1891` (`프론트 요청사항`), origin/main과 일치 |
| 이전 이력 | `d54f980` 서버 기록과 `e31008c`가 현재 커밋의 이전 이력으로 보존됨 |
| 충돌 | 미해결 경로·충돌 표시 없음, `git diff --check` 통과 |
| stash | **보존**. `stash@{0}: On main: server-docs-before-pull-20261103`, OID `01e48b41d1c1b53d7d11b7f1c4fb487edbbba48d` |

reset·강제 checkout·stash 삭제·자동 커밋은 하지 않았다. 업무 코드·기존 문서는 수정하지 않았고 이번 결과 파일을 추가했다. AGENTS.md·README·실행서·추가 계약을 확인했다. AGENTS.md가 참조하는 `/srv/rental-project-master.md`, `/srv/rental-api-review-decisions.md`는 서버에 없었다.

## 2. 실제 서버 확인 — 기존 서비스 유지

| 검사 | 기대/판정 | 실제 결과 |
| --- | --- | --- |
| 서비스 | 현재 서비스 유지, 통과 | `nadree-api.service`, ec2-user, 작업 경로 `/srv/nadree-api`, `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8008` |
| 실행 프로세스 | 재시작하지 않음, 통과 | PID **3479440**, 시작 **02:44:38 UTC**. 이전 `e31008c` 적용 기록의 PID와 일치, 최종 재확인에서도 동일 |
| 로컬/공개 health | 200, 통과 | `/health/live`, `/health/ready` 모두 200 |
| 로컬/공개 문서 | 200, 통과 | `/docs`, `/openapi.json` 모두 200 |
| 현재 준비 상태 | 기존 제한 구분, 통과 | status=ok, 기존 `MFA_FLOW_NOT_IMPLEMENTED` 유지 |
| 현재 API 계약 | 신규 배포와 구분 | health 제외 **74개** 경로, 새 `/onsite/requests/{client_request_id}/close` 없음. 보류 중인 기존 서비스의 예상 상태 |
| 실제 DB | 대상 확인, 통과 | 설정과 `SELECT DATABASE()` 모두 **RIDERLOG_V2_DATA_TEST** |
| 기존 예약 | 읽기 전용 확인 | 29건, HANDOVER_PENDING 0건. 고객·예약·결제·QR 데이터를 변경하지 않음 |
| 기존 인수 스키마 | 재적용 불필요, 통과 | 예약 3컬럼과 HANDOVER_PENDING 허용 CHECK 존재 |
| 신규 결과 테이블 | **미적용·보류** | `MSP_RENTAL_ONSITE_REQUEST` 없음 |
| 실제 env | 보존, 통과 | 기존 NADREE_CUSTOMER_RECEIPT_ENABLED=false 1개 유지. ec2-user 소유·0600·파일 전체 해시 불변 |

실제 HTTP 확인은 위 8개 읽기 요청이다. 새 코드의 요청·close·인수 성공을 실제 서버에서 확인한 결과가 아니다. 실행 중 소스 기준은 이전 배포 기록과 동일 PID 및 현재 OpenAPI 계약으로 대조했으며, 디스크 HEAD가 곧 실행 중 버전이라는 전제로 판단하지 않았다.

**디스크의 새 코드는 OFF 설정이 없다.** 새 Settings 모델에도 해당 필드가 없으며, 기존 false를 남겨도 신규 프로세스의 인수를 비활성화하지 않는다. 현재 false가 있는 기존 프로세스를 유지한 것과 신규 코드를 false로 운영하는 것은 다르다. 준비 확인 전 API를 재시작하지 않았다.

## 3. 마이그레이션 계획·백업·작업 일정

서비스 계정으로 다음 **읽기 전용** 명령을 실행했다.

```bash
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
```

실제 결과:

```text
PENDING create MSP_RENTAL_ONSITE_REQUEST
Read-only plan; no database writes.
```

최종 재조회도 동일했다. 다른 pending은 없으며 예약 컬럼·인덱스·상태를 재생성하는 계획도 없다. 생성 예정 정의는 고객+키 복합 PK, 본문 지문, PROCESSING/ACCEPTED/REJECTED, 예약 ID 또는 오류 코드/HTTP 상태, UTC 생성/갱신 시각과 상태 CHECK다. 실제 적용은 하지 않았다.

이번 신규 배포용 백업은 **아직 생성하지 않았다**. API 드레인·정지 후 승인된 배포 시점에 현재 DB를 새로 백업해야 한다. 이전 02:35:30 UTC의 전체 백업 파일과 당시 무결성 검사 결과는 존재함을 확인했지만, 이를 이번 전환의 최신 백업으로 간주하지 않는다. 복원 실행도 하지 않았다.

| 기존 작업 | 실제 확인 |
| --- | --- |
| nadree-receipts.timer | enabled / active / waiting 유지 |
| nadree-receipts.service | 최근 실행 종료 0, Result=success. oneshot의 완료 후 inactive/dead는 정상 |
| nadree-chat-sync.timer | enabled / active 유지 |
| 결제 복구 | `/etc/cron.d/nadree-payment-recovery` 유지, crond.service active |
| 보존 검사 | 결제 cron·receipts service/timer·채팅 service/timer의 최종 파일 해시가 사전 점검과 동일 |

작업을 수동 실행하거나 일정을 재설치/중단하지 않았다. 서비스 설정은 SIGTERM, 종료 대기 90초, Restart=always임을 읽기 전용으로 확인했다. 실제 드레인과 구버전 종료 확인은 배포 승인 시 수행할 작업이다.

## 4. 격리 전체 회귀 — 신규 코드

커밋 `254507d`의 서비스 소스 134개 파일을 별도 경로에 복사했다. 실제 `.env`·가상환경·외부 인증 환경변수·서비스 DB URL을 제외하고 `/tmp`를 작업 경로로 사용했다. 일회용 SQLite와 FastAPI TestClient를 사용했으며 PG·FCM은 테스트 대역이다.

실행 형태:

```text
.venv/bin/python -m pytest <격리 소스>/tests -q -p no:cacheprovider --tb=short --junitxml=<결과 파일>
```

**총 603개: 588 passed / 15 skipped / 0 failed / 0 errors.** 기존 경고 14개는 별도다. 신규 인수/회수 모듈은 20개 통과·MySQL 2개 건너뜀, 요청 결과 모듈은 11개 통과·MySQL 1개 건너뜀이다.

| 요구사항 | 격리 기대 결과 | 실제 판정 |
| --- | --- | --- |
| 확정 거절 영속성 | 실패는 REJECTED로 남고 같은 키의 지연/새 견적 제출도 예약 생성 불가 | 통과 |
| UNKNOWN | 404가 키를 닫지 않고 새 신청 가능으로 오인하지 않음 | 통과 |
| close | 미접수 키를 종료해 지연 신청 차단, ACCEPTED의 close는 예약 취소 없이 기존 결과 반환 | 통과 |
| PROCESSING/중단 | 경합 202와 중단/오류를 확정 거절로 표시하지 않음 | 대역 기반 계약 통과. 실제 MySQL 경합은 아래 미검증 |
| 원자성 | 예약/이력/알림 중간 장애 롤백, 의도 유지 후 같은 요청은 예약 1개 | 격리 SQL/API 통과 |
| 고객 범위 | 다른 고객의 키 조회·종료·예약 인수 차단 | 통과 |
| 상시 인수 | 과거 false 설정으로 즉시 대여 우회 불가. 구버전 관리자 요청은 CLIENT_UPDATE_REQUIRED | 통과 |
| 인계/인수 | 관리자 처리 후 HANDOVER_PENDING·계약 없음, 고객 성공 후에만 HANDED_OVER/ON_RENT·계약 1개 | 통과 |
| 발리 기한 | 자정부터 인수 차단, 만료 전후 같은 기한 오류 | 통과 |
| 보호/회수 | EXPIRED 뒤에도 배정·DISABLED 보호 유지, 직원 실물 확인 후 해제 | 통과 |
| 기존 ON_RENT | 재인수 강제 없음, 기존 반납 경로 유지 | 통과 |
| 관리자 표시 | 목록·홈·캘린더·currentBooking 식별자/기한/액션 일치, 과거 기간의 회수 대기 누락 없음 | 통과 |
| NDR QR | 원문·대소문자 보존, URL 원문 임의 변환 없음 | 문자열/서버 검사 통과. 실기기 추출/스캔은 미검증 |
| 기존 기능 | 가격·예약·재고·권한·반납·기존 금융 경로 회귀 | 전체 격리 회귀 통과, 실제 PG 호출 없음 |

추가로 **격리 앱의 OpenAPI만 생성**해 아래를 직접 확인했다. 실제 서비스의 74개 경로와 구분한다.

- health 제외 **75개** 경로, 신규 close POST 존재.
- 결과 GET 200 accepted/rejected, 202 processing, 404 notFoundIsNotFinal, 503 interruptedAttempt named examples.
- 관리자 예약 목록·GET 홈·캘린더·QR 검증의 상태별 named examples.
- 고객 receive의 RECEIPT_DEADLINE_EXPIRED 차단 예시.

전체 회귀와 추가 명세 검사는 모두 통과했으며, 결과를 맞추려고 업무 코드를 수정하지 않았다.

## 5. 공동 QR 예시 — 읽기 전용 확인

`deployment/onsite-qr-test-requests.json`의 QR_ONLY 예시 2개를 현재 DB와 대조했다.

| 예시 번호판 | 모델 존재 | 같은 QR 해시 등록 | 번호판 충돌 | 실제 등록 |
| --- | --- | --- | --- | --- |
| DK-NDR-ONLY-001 | 예 | 없음 | 없음 | **하지 않음** |
| DK-NDR-ONLY-002 | 예 | 없음 | 없음 | **하지 않음** |

이는 기초 중복 검사이며 신규 차량·QR 생성이나 인쇄 QR/두 앱 스캔 검증을 의미하지 않는다. 발급 URL의 도메인은 아직 예시다. 추후 승인된 지점·관리자 쓰기 권한과 당시 모델·차량 상태를 재확인하고 기존 등록 API로 생성해야 한다. 이전 QR·센서를 교체하거나 시드 전체를 실행하지 않았다.

## 6. 실패·건너뜀·미검증·남은 작업

최종 사전 점검과 격리 검증의 실패/오류는 **0개**다. 배포 보류와 신규 테이블 pending은 앱 준비 확인을 기다리는 계획 상태이며 적용 실패가 아니다.

| 구분 | 항목 | 이유/후속 작업 |
| --- | --- | --- |
| 배포 보류 | 드레인·프로세스 종료·신규 백업·테이블 적용·env 제거·신규 API 시작 | 양 앱 준비와 승인된 배포 시점 미확인. 사용자도 사전 점검만 선택 |
| 건너뜀 11개 | 일회용 MySQL 검사 | `NADREE_TEST_MYSQL_URL` 미지정. 신규 제출/인수/close 경합 3개와 기존 MySQL 동시성/FK 8개. 빈 `nadree_w02_test_*` DB에서 별도 수행 |
| 건너뜀 4개 | Firestore 통합 | demo-nadree-chat 에뮬레이터 미기동. 운영 Firebase로 대체하지 않음 |
| 경고 14개 | 기존 라이브러리/테스트 대역 | 기능 실패와 구분. 이번 업무 코드 변경 범위에 포함하지 않음 |
| 미검증 | 실제 신규 서버의 요청 결과·close·인수·회수 왕복 | 현재 실제 서버는 이전 코드. 준비 완료 후 승인된 테스트 계정/차량으로 수행 |
| 미검증 | 양 앱의 QR 추출·직접 입력·상태 UI·실기기 FCM/App Check | 앱 공동 시험 필요. 인증 검사 완화/시험 푸시 없음 |
| 미검증 | 신규 배포 백업·실제 복원 | 배포 창에서 새 백업 및 압축 검증. 복원은 별도 빈 DB |

배포 재개 순서는 다음과 같다.

1. **양 앱 준비 완료와 배포 시각을 명시적으로 확인**한다. requestStatus/close, receiptRequired=true, 인수/회수·오류 상태·새 QR 원문 계약이 대상이다.
2. 신규 요청을 통제하고 진행 중 API 요청을 드레인한 뒤 구버전을 종료한다. 기존 PID·리스너 종료를 확인하고 구/신 버전이 동시에 쓰지 않게 한다.
3. 당시 실제 대상 DB를 다시 확인하고 접근 제한된 최신 백업·무결성을 확보한다. ec2-user 읽기 전용 계획에서 예상 테이블 생성 1개인지 재확인한다.
4. app.migrate로 MSP_RENTAL_ONSITE_REQUEST만 적용하고 잔여 계획 0개를 확인한다. 예약·결제·QR을 일괄 변경하지 않는다.
5. 기존 NADREE_CUSTOMER_RECEIPT_ENABLED 항목만 정리하고 나머지 env·비밀값·소유권·0600을 보존한다.
6. 새 API를 시작해 health/ready·75개 경로·close·예시를 확인한다. 기존 receipts·채팅·결제 작업을 유지하고 승인된 데이터로 공동 인수한다.

새 코드에는 OFF 복구가 없다. 전환 후 장애가 나면 신규 쓰기를 통제하고 결과 키·보호 차량·기록을 유지해 수정한다. 확정 REJECTED가 생긴 뒤 구버전 쓰기 서버로 단순 복귀하거나 결과 테이블 삭제/초기화·차량 AVAILABLE 강제 변경·백업 일괄 덮어쓰기를 하지 않는다.

이번 작업에서 실제 고객 데이터 변경·실제 결제·환불·시험 푸시·Firebase 배포는 모두 하지 않았다. 증거 파일은 접근 제한된 `build/test-runtime/qr-onsite-final-2026-11-03/`에 보존하며, 결과 문서에 비밀번호·토큰·비밀키·고객 UID를 기록하지 않았다.
