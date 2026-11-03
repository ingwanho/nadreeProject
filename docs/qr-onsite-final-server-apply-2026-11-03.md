# 서버 Codex 실행서 — QR 추가 계약·인수 상시화

이 파일만 읽고 적용 범위와 순서를 확인할 수 있도록 정리했다. **작성 당시에는 로컬 코드·마이그레이션 준비 단계였으며 이 실행서 자체는 실제 적용 증거가 아니다.** 당시 이전 적용 결과는 [서버 결과](qr-onsite-receipt-server-result-2026-11-03.md)의 `e31008c`·고객 인수 false 상태였다.

**후속 실행 완료: 2026-11-03 07:35 UTC.** 위 문단은 실행서 작성 당시 상태다. 이후 사용자 양 앱 준비 완료·배포 승인으로 `254507d`의 구 API 드레인·백업·신규 테이블·env 정리·API 전환을 완료했다. 인수는 상시 필수이고 시험 QR 차량 2대도 등록했다. 실제 적용·격리 검증·미검증을 구분한 정본은 [최종 배포 결과](qr-onsite-final-server-deployment-result-2026-11-03.md)다.

## 적용 대상과 전제

- 서비스: `/srv/nadree-api`, `nadree-api.service`, 실행 계정 `ec2-user`.
- 새 계약: [추가 요청 처리 계약](qr-onsite-followup-contract-2026-11-03.md). 고객 결과 응답의 requestStatus와 `/onsite/requests/{client_request_id}/close`를 포함한다.
- DB 변경은 **MSP_RENTAL_ONSITE_REQUEST 테이블 1개**다. 이전에 적용한 예약 3컬럼·인덱스·CHECK를 다시 만들거나 기존 예약을 변환하지 않는다.
- 고객 인수는 새 코드의 기본 필수 동작이다. **NADREE_CUSTOMER_RECEIPT_ENABLED는 제거됐고 false를 남겨도 비활성화되지 않는다.** 구버전 인계 요청은 CLIENT_UPDATE_REQUIRED로 차단하며 receiptRequired=true는 유지한다.
- 양 앱의 시험·전환 준비와 배포 시점이 확인된 뒤 이 코드를 서비스에 적용한다. 앱이 준비되지 않았다면 문서·격리 검증까지 진행하고 기존 서비스를 임의로 전환하지 않는다.

## 1. Git와 백업

AGENTS.md를 읽고 Git 상태·현재 서비스 커밋·실행 계정·DB 이름을 확인한다. 서버 문서의 기존 수정과 stash를 보존한다. 미커밋 코드를 임의로 reset하거나 강제 push하지 않는다. 문서 변경은 별도 보관 후 통합하되 충돌 표시를 커밋하지 않는다.

승인된 배포 창에서 기존 API 요청을 드레인하고 이전 프로세스를 종료한다. **구버전과 신규 요청 결과 코드가 동시에 쓰기를 처리하지 않게 한다.** 새 코드의 확정 거절 기록을 모르는 구버전이 나중에 예약을 생성하는 경로를 남기지 않는다.

기존 DB 전체/관련 테이블 백업과 접근 제한·압축 무결성을 확인한다. 자격증명·실제 고객 정보는 출력하거나 Git에 넣지 않는다. env 소유권과 0600, 백업 전용 디렉터리 0700을 유지한다. 실제 복원 시험은 별도 빈 DB에서 수행한다.

준비 후 정상 main을 가져온다.

```bash
cd /srv/nadree-api
git status
git pull --ff-only origin main
```

## 2. 신규 테이블 적용

서비스 계정으로 읽기 전용 계획을 확인한다.

```bash
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
```

예상 신규 작업은 `create MSP_RENTAL_ONSITE_REQUEST`다. 다른 pending이 있으면 기존 적용 상태와 대조한다. DB 이름을 실제 env·SELECT DATABASE()와 맞춰 확인하고, 승인된 DB에만 적용한다. 아래 DB명은 기존 테스트 환경 기준이다.

```bash
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST'
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
```

정상 결과는 No pending changes다. 생성 SQL은 [011_onsite_request.sql](../migrations/011_onsite_request.sql)에 있으며 app.migrate와 중복 실행하지 않는다. 부모 ERD SQL은 시각화용이므로 실행하지 않는다. 호환되지 않는 동명 테이블이 발견되면 임의 덮어쓰기를 하지 않는다.

결과 테이블은 고객+키 복합 PK, 본문 지문, PROCESSING/ACCEPTED/REJECTED, 예약 ID 또는 오류 코드/HTTP 상태와 UTC 생성·수정 시각을 저장한다. QR 원문·견적 토큰은 저장하지 않는다. UNKNOWN은 기록 부재나 처리 중단/조회 장애에서 계산하는 응답이며 확정 거절이 아니다. 키 기록에 TTL 삭제·자동 초기화 작업을 추가하지 않는다.

## 3. 설정과 서비스 전환

기존 `.env`의 NADREE_CUSTOMER_RECEIPT_ENABLED 줄을 정리한다. 새 코드의 설정 모델에는 이 항목이 없고 true/false 운영 전환으로 사용하지 않는다. 다른 env 값·권한·비밀키는 유지한다. 예전 false 설정이 새 코드의 즉시 대여 우회나 기능 차단을 만들지 않는 것이 의도된 변경이다.

새 요청 결과 테이블까지 준비된 상태에서 API를 시작한다. 명령의 서비스 이름과 경로는 실제 unit을 먼저 확인한다.

```bash
sudo systemctl start nadree-api.service
sudo systemctl is-active nadree-api.service
sudo systemctl is-enabled nadree-receipts.timer
sudo systemctl is-active nadree-receipts.timer
```

기존 receipts 만료 타이머를 유지한다. 설치되지 않았다면 기존 deployment/nadree-receipts.service·timer를 설치하고 daemon-reload 후 enable --now 한다. 기존 채팅·결제 복구 일정은 변경하지 않는다. 이번 변경은 Firebase Functions·Rules·인덱스·새 키·새 외부 의존성 배포를 요구하지 않는다.

로컬 실제 서비스 포트는 unit에서 확인한다. 기존 서버 결과는 8008이며 공개 주소는 `https://na-dree.com`이다. `/health/live`, `/health/ready`, `/docs`, `/openapi.json`을 검사한다. readiness는 이제 예약 인수 컬럼과 결과 테이블을 항상 검사하므로 누락을 false 설정으로 우회할 수 없다.

## 4. 검증

실제 env·운영/서비스 DB 주소를 제외한 격리 소스에서 전체 pytest를 실행한다. MySQL 동시성은 빈 `nadree_w02_test_*` 전용 DB가 있을 때만 실행하고 서비스 DB로 대체하지 않는다. Firestore도 격리 에뮬레이터를 사용한다.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider --tb=short
```

필수 확인:

1. **결과 영속성:** 요청 실패가 REJECTED로 저장되고 같은 키의 지연 제출·새 견적 제출도 생성되지 않음. 404는 UNKNOWN이고 조회만으로 종료되지 않음.
2. **종료 API:** UNKNOWN 뒤 close가 REJECTED이면 늦은 제출 차단. 이미 접수된 키의 close는 기존 ACCEPTED를 반환하고 실제 예약을 취소하지 않음. PROCESSING 202·5xx를 확정 종료로 오인하지 않음.
3. **원자성:** 처리 중 장애 시 예약/이력/알림 변경이 롤백되고 의도 기록은 남음. 같은 본문 재시도는 예약 1건만 생성. 고객 간 키 조회·종료가 격리됨.
4. **상시 인수:** env의 구 false로 인수 절차를 우회하지 않음. 관리자 누락 필드 409, 절차 완료 HANDOVER_PENDING, 본인 고객 receive 후에만 계약 1개·ON_RENT.
5. **기한·회수:** 발리 자정 차단, 만료 전후 같은 기한 오류, EXPIRED여도 보호 유지, 실물 회수 후 해제. 기존 ON_RENT 재인수 강제 없음.
6. **관리자 화면:** 목록·홈·캘린더·currentBooking에 ID·기한·액션이 일치함. 홈에서 원래 예약 기간이 지난 회수 대기가 빠지지 않음.
7. **공개 명세:** 경로 75개(health 제외), 새 close 경로, 요청 결과 200/202/404/503·거절 예시와 고객 차단·관리자 named examples 확인.

실제 업무 왕복·기기 푸시는 별도 승인된 테스트 계정·차량으로만 실행한다. 명세/무인증 차단 확인을 실제 신청·인수 성공으로 기록하지 않는다. PayPal 청구·환불·운영 고객 데이터 변경을 격리 테스트 대신 실행하지 않는다.

## 5. 새 QR 공동 시험 준비

[onsite-qr-test-requests.json](../deployment/onsite-qr-test-requests.json)은 신규 NDR 규격의 QR_ONLY 차량 2대 등록용 요청 예시다. 현재 모델·지점·역할·원문/번호판 중복과 테스트 쓰기 승인을 확인하고 기존 API로 등록한다. 이전 QR/차량·센서를 변경하거나 SQL 시드를 전체 재실행하지 않는다. 반환 vehicleId와 실제 등록/미등록 결과를 별도로 기록한다.

URL 예시의 도메인은 실제 발급 주소로 바꾼다. 실제 QR은 HTTP(S) URL의 # 뒤에 전체 NDR 원문을 인코딩 없이 넣는다. 두 앱의 스캔과 수동 입력 → 서버 qrCode 동일성을 기기에서 확인한다. 등록 파일 제공·서버 문자열 테스트 성공은 실제 인쇄 QR 인식 성공을 뜻하지 않는다.

## 6. 실패·복구와 결과 문서

신규 코드에 기능 OFF 복구는 없다. 장애 시 신규 신청·인계 쓰기를 잠시 막고 원인을 수정한다. 결과 테이블과 확정 거절 키를 보존한다. 인수 대기·회수 보호 차량은 현재 계약으로 마무리하며 AVAILABLE 강제 SQL이나 구버전 즉시 출고 코드로 복구하지 않는다. 테이블을 삭제하거나 전체 백업을 현재 DB에 자동 덮어쓰지 않는다.

구버전은 결과 키 종료를 모르므로 새 REJECTED 키가 존재하는 상태에서 쓰기 처리용으로 단순 복귀할 수 없다. 이전 코드를 진단 목적으로 띄워야 하면 신규 신청·인계 경로를 차단한 상태에서 별도로 판단한다. 앱은 불명 요청을 성공으로 표시하지 않고 조회·동일 키 재시도/close로 해결한다.

결과 MD에는 커밋·실제 적용 시각·DB 계획/적용·기존 데이터 보존·env 정리·재시작·타이머·실제 HTTP·격리 테스트·건너뜀·미검증·남은 앱 작업을 구분한다. 서버의 기존 작업 기록과 stash는 통합 확인 전까지 보존한다. 이 실행서의 작성은 실제 적용·운영 승인·앱 인수를 대신하지 않는다.
