# QR 현장 신청 최종 변경 — 실제 서버 배포·검증 결과

검증일: **2026-11-03 UTC**. 사용자가 양 앱 준비 완료와 즉시 배포를 승인한 뒤 실행했다. 이전 [사전 점검 결과](qr-onsite-final-server-preflight-result-2026-11-03.md)의 배포 보류 상태를 대체하며, 당시 점검 기록은 보존한다.

**배포 완료.** 커밋 `254507d`의 요청 결과 저장·close·고객 인수 필수 흐름이 실행 중이다. 신규 테이블 적용 후 미적용 변경은 0개이며, 구 OFF env 항목을 제거했다. 실제 고객 업무 왕복·실기기 스캔/푸시는 아래 미검증으로 구분한다.

## 1. 적용 커밋·승인·Git 보존

- 기준 실행서: [최종 서버 적용 실행서](qr-onsite-final-server-apply-2026-11-03.md), [추가 요청 계약](qr-onsite-followup-contract-2026-11-03.md).
- `main`의 `git pull --ff-only origin main` 성공·Already up to date.
- 배포 커밋: **254507d802c08241d82f1f45e55481f694cb1891** (`프론트 요청사항`). origin/main과 일치.
- 배포 전에 이전 격리 회귀 소스의 파일 해시와 현재 소스를 대조해 동일함을 확인했다. 업무 코드는 추가 수정하지 않았다.
- 사용자 승인은 기존 드레인·백업·신규 테이블·env 정리·API 전환과 앞서 미등록으로 설명한 QR 시험 차량 2대 준비를 포함해 수행했다.
- 기존 문서·stash를 보존했다. stash OID **01e48b41d1c1b53d7d11b7f1c4fb487edbbba48d**, `stash@{0}: server-docs-before-pull-20261103`. reset·stash 삭제·자동 커밋 없음.

## 2. 실제 전환·DB·env

| 항목 | 기대 | 실제 결과·판정 |
| --- | --- | --- |
| 구 API 드레인 | 구/신 버전 동시 쓰기 방지 | **07:34:18 UTC** systemctl stop. Application shutdown complete·이전 PID 종료·8008 리스너 종료 확인, 통과 |
| 종료 방식 | 정상 graceful 종료 | systemd Result=success와 Uvicorn 정상 종료 로그 확인. SIGKILL/timeout 종료로 처리하지 않음 |
| 새 백업 | 구 API 종료 후 최신 전체 백업 | ec2-user로 기존 **76개 테이블**·routines/events/triggers를 single-transaction 백업, dump 종료 0·전체 gzip 무결성 통과 |
| DB 대상 | 승인된 테스트 DB만 적용 | 설정 및 SELECT DATABASE() 모두 **RIDERLOG_V2_DATA_TEST** |
| 읽기 전용 계획 | 신규 테이블 생성 1개 | ec2-user의 `PENDING create MSP_RENTAL_ONSITE_REQUEST`만 확인 |
| 마이그레이션 | 테이블 1개만 생성 | app.migrate --apply 성공. 기존 예약 3컬럼·인덱스·CHECK 재생성 없음 |
| 재계획 | 남은 변경 0개 | 적용 직후 및 **07:38:59** 최종 점검 모두 `No pending changes.` |
| 테이블 정의 | 결과 저장 구조·대소문자 구분 | 컬럼 9개·고객+키 복합 PK·결과 상태 CHECK·InnoDB·utf8mb4_bin 확인, 통과 |
| env 정리 | 구 인수 설정만 제거 | NADREE_CUSTOMER_RECEIPT_ENABLED 정의 **1줄만 제거**. 나머지 바이트/설정값·ec2-user 소유권·0600 보존 |
| 인수 정책 | OFF 없이 필수 | 새 설정 모델과 실행 프로세스에 구 env 키 없음. `receiptRequired=true` 계약 유지 |
| 새 API 시작 | 준비된 DB 후 새 프로세스만 시작 | **07:34:55 UTC** start, PID **3479440 → 3661271**, active/running |
| 전환 횟수 | 승인된 한 번의 전환 | stop 1회·start 1회. 약 40초 후 새 API 헬스 확인 |

마이그레이션은 **ec2-user**로 실행했다.

```text
# 읽기 전용 계획
PENDING create MSP_RENTAL_ONSITE_REQUEST
Read-only plan; no database writes.

# --apply --confirm-database RIDERLOG_V2_DATA_TEST
APPLY create MSP_RENTAL_ONSITE_REQUEST
Applied.

# 적용 후 읽기 전용 계획
No pending changes.
```

테이블 PK는 `(uid_token, client_request_id)`이며 PROCESSING/ACCEPTED/REJECTED의 필수·금지 필드 CHECK를 확인했다. 기존 데이터를 결과 테이블로 일괄 이관하지 않았고, 실제 서버 무인증 검증으로 결과 행도 만들지 않았다. 최종 점검 시 결과 행은 0개였다.

백업 파일은 `/srv/nadree-api/build/test-runtime/qr-onsite-final-deployment-2026-11-03/RIDERLOG_V2_DATA_TEST-before-onsite-results-20261103.sql.gz`다. ec2-user 소유 전용 디렉터리 0700·파일 0600, 압축 **18,010,271바이트**, 원본 SQL **641,557,062바이트**다. 백업 자격증명은 일시적인 0600 옵션 파일로만 전달한 뒤 제거했다. **실제 빈 DB 복원 시험은 하지 않았다.**

## 3. 기존 데이터·작업 보존

마이그레이션 전후 비교에 이어 QR 시험 차량 생성 후에도 신규 차량 ID를 제외한 기존 행을 다시 비교했다. 아래 테이블의 기존 행 수·전체 내용 지문은 모두 동일했다.

- MSP_RESERVATION: **29건 유지**.
- MSP_RESERVATION_HISTORY, MSP_RENTAL_CONTRACT, MSP_RENTAL_PAYMENT.
- MSP_VEHICLE_QR, MSP_VEHICLE_QR_HISTORY, MSP_VEHICLE_STATUS.

기존 예약·결제·QR·센서를 변환하거나 시드를 재실행하지 않았다. PayPal 청구·환불·시험 푸시를 실행하지 않았다. Firebase Functions·Rules·인덱스·서비스 키도 재배포/변경하지 않았다.

기존 `/etc/cron.d/nadree-payment-recovery`, receipts service/timer, 채팅 service/timer 파일은 배포 전후 해시가 동일하다. receipts·채팅 타이머와 crond 모두 active다. **새로 중복 스케줄을 설치하지 않았다.**

배포 후 receipts 자동 완료 기록은 다음과 같으며 수동 작업 실행은 하지 않았다.

| 완료 시각 UTC | receiptsExpired |
| --- | --- |
| 07:35:53 | 0 |
| 07:36:56 | 0 |
| 07:38:02 | 0 |

## 4. 실제 서비스 HTTP·로그 검증

| 검사 | 기대 | 실제 결과·판정 |
| --- | --- | --- |
| 로컬/공개 health live·ready | 200 | 모두 200, 통과 |
| 로컬/공개 Swagger·OpenAPI | 200 | 모두 200, 통과 |
| 신규 OpenAPI | health 제외 75개·close POST | 로컬·공개 모두 **75개와 close 경로 확인**, 통과 |
| 고객 QR/견적/신청/결과/close/receive 무인증 | 401 INVALID_NADRI_USER_TOKEN | 로컬·공개 모두 일치, 통과 |
| 관리자 receipt-recovery 무인증 | 401 AUTH_REQUIRED | 로컬·공개 모두 일치, 통과 |
| 최종 헬스 재확인 | 프로세스/준비 상태 유지 | 07:38:59 점검에서 PID 3661271 유지, 로컬/공개 live·ready 200 |
| 새 프로세스 오류 로그 | Traceback·ASGI 오류·시작 실패 0 | 모두 **0개**, 통과 |

배포 HTTP 상태 검사 22개와 최종 헬스 4개를 기록했다. readiness의 기존 제한 **MFA_FLOW_NOT_IMPLEMENTED**는 유지되며 이번 신규 배포 오류로 해석하지 않는다.

유효 고객 인증으로 close를 호출하면 영속 거절 행이 생기므로 이 배포 점검에서는 **무인증 차단과 명세만 확인**했다. 실제 고객의 신청·인수·회수 성공으로 기록하지 않는다.

## 5. 공동 시험용 NDR QR 차량 — 실제 등록·조회 완료

승인된 기존 최상위 테스트 지점 **00000000-0000-4000-8000-000000000101**에 기존 차량 생성 API로 다음 2대를 추가했다. 대상 대표·직접 manage 권한·계약·모델 ID/브랜드/이름·125cc·현재 QR와 **QR 이력**·번호판 중복을 사전 확인했다.

| 항목 | 차량 1 | 차량 2 |
| --- | --- | --- |
| 번호판 | DK-NDR-ONLY-001 | DK-NDR-ONLY-002 |
| vehicleId | a2e47c5a-d968-4bb7-8736-c215ab65e154 | 7bb04647-c051-45c5-b31c-4b4dc5ba37f5 |
| QR 원문 | **NDR-Ab12Cd34** | **NDR-Ef56Gh78** |
| 모델 | NRTEST-WEB-MODEL-125 | NRTEST-WEB-MODEL-125 |
| 상태 | QR_ONLY / AVAILABLE / QR ACTIVE | QR_ONLY / AVAILABLE / QR ACTIVE |
| 센서 | 없음 | 없음 |

등록 시각은 **07:36:58~07:37:02 UTC**다. 정상 테스트 대표 로그인→차량 생성 2회→관리자 QR 조회 2회→대문자 변경 QR의 404 차단 2회→로그아웃을 모두 확인했다. 차량별 기존 등록 계약의 6개 행(차량·렌탈 차량·상태·소속·QR·QR 이력)과 센서 0개를 DB에서 확인했다. 고객 예약이나 결제 행은 만들지 않았다.

테스트 비밀번호는 기존 승인 자료와 현재 DB 해시를 메모리에서 대조해 사용했고 출력·복사 저장하지 않았다. 로그인·로그아웃은 정상 정책에 따라 해당 **테스트 대표의 업무/채팅 세션을 회수**하므로, 앱 담당자는 그 테스트 계정으로 다시 로그인해야 한다. FCM 토큰을 교체하거나 시험 푸시를 보내지는 않았다.

QR 이미지 발급 URL은 아직 예시 도메인이므로 실제 프론트 발급 도메인으로 정해야 한다. URL `#` 뒤 전체 NDR 원문을 두 앱이 추출해 위 `qrCode`로 보내며 대소문자를 유지한다. 서버 등록 성공은 실제 인쇄 QR·카메라 인식·양 앱 화면 검증을 뜻하지 않는다.

## 6. 격리 회귀·명세 검증

동일 커밋의 **07:12:30~07:16:05 UTC** 격리 전체 회귀 결과를 배포 직전 파일 해시 일치 확인 후 사용했다. 소스가 바뀌지 않았으므로 동일 전체 회귀를 반복하지 않았다. 서비스 .env·외부 인증 환경·DB 주소를 제외한 일회용 SQLite와 FastAPI TestClient, PG/FCM 대역을 사용한 결과다.

**총 603개: 588 passed / 15 skipped / 0 failed / 0 errors.** 요청 결과/close 11개와 인수/회수 20개가 통과했다. 실제 MySQL 검사는 별도다.

검증된 내용:

- 확정 REJECTED 후 같은 키의 지연 제출/새 견적도 생성 차단, UNKNOWN 404는 확정 종료로 처리하지 않음.
- close는 미접수 키를 영속 종료하고, 이미 ACCEPTED인 키는 예약 취소 없이 기존 결과 반환.
- PROCESSING 202와 중단 결과를 성공/확정 거절로 오인하지 않음.
- 예약·이력·알림 쓰기 실패 롤백, 처리 의도 보존, 같은 본문 재시도의 단일 예약과 고객 간 키 격리.
- 구 false 설정으로 인수 우회 불가, 구버전 관리자 누락 필드 CLIENT_UPDATE_REQUIRED.
- HANDOVER_PENDING 후 본인 receive에만 HANDED_OVER/ON_RENT·단일 계약, 발리 자정·만료 전후 기한 차단.
- EXPIRED 뒤 차량 보호/배정 유지와 직원 실물 회수, 기존 ON_RENT 재인수 강제 없음.
- 관리자 목록·홈·캘린더·currentBooking의 ID·기한·액션과 기간 지난 회수 대기 표시, 기존 가격·권한·반납 회귀.
- 별도 격리 OpenAPI에서 75개 경로, close, 200/202/404/503 결과 예시·고객 차단·관리자 named examples 확인.

## 7. 실패·미검증·남은 앱 작업

최종 배포·실제 서버 검사·QR 등록 검증의 미해결 실패는 **없다**. 인수 기능을 켜기 위해 추가할 env 값도 없다. 기존 OFF 항목은 제거 완료다.

| 구분 | 항목·이유 | 후속 작업 |
| --- | --- | --- |
| 건너뜀 11개 | 빈 전용 MySQL URL 미지정. 신규 제출/인수/close 경합 3개와 기존 MySQL/FK 8개 | 별도 `nadree_w02_test_*` DB에서 검사. 실제 서비스 DB로 대체하지 않음 |
| 건너뜀 4개 | demo-nadree-chat Firestore 에뮬레이터 미기동 | 격리 에뮬레이터 검사 |
| 경고 14개 | 기존 라이브러리·테스트 대역 경고 | 회귀 실패와 구분, 업무 코드 수정하지 않음 |
| 미검증 | 새 서버의 실제 고객 신청→관리자 인계→고객 인수→반납, 실제 인증 close 경합 | 양 앱이 준비됐다는 사용자 확인 후 배포했으나 이 실제 업무 왕복은 별도 공동 시험 필요 |
| 미검증 | 실제 QR 출력/스캔·직접 입력, 실기기 FCM/App Check | 위 테스트 차량과 승인된 계정으로 앱 담당자 확인. 실제 고객·푸시 대상은 임의 사용하지 않음 |
| 미검증 | 압축 SQL의 빈 DB 실제 복원 | 현재는 dump 성공·gzip 전체 무결성 확인. 별도 복구 리허설 필요 |

앱 담당자는 테스트 대표에 재로그인하고 위 QR 원문을 사용한다. 요청의 원래 clientRequestId·본문을 보존하고, ACCEPTED/REJECTED/PROCESSING/UNKNOWN과 명시적 close를 구분한다. 관리자 인계 응답만으로 ON_RENT를 표시하지 않고 본인 고객 receive 후 최신 예약 상세를 확인한다.

## 8. 복구 기준과 증거

새 코드에 OFF 복구는 없다. 장애 시 신규 신청·인계 쓰기를 통제하고 현재 결과 테이블·거절 키·보호 차량을 보존해 수정한다. REJECTED가 생긴 뒤 구버전 쓰기 서버로 단순 복귀하거나 테이블 초기화/삭제·전체 백업 덮어쓰기·AVAILABLE 강제 변경을 하지 않는다.

배포·백업·마이그레이션·env 보존·QR 실제 검증·최종 로그/데이터 비교 증거는 접근 제한된 `build/test-runtime/qr-onsite-final-deployment-2026-11-03/`, 격리 회귀와 소스 지문은 `build/test-runtime/qr-onsite-final-2026-11-03/`에 보존했다. 결과 문서에는 비밀번호·토큰·비밀키·실제 고객 UID를 기록하지 않았다. 기존 기록과 stash도 보존했다.
