# 2026-11-24 인계·예약 서버 적용 및 검증 결과

## 현재 결론

**전체 자동 검증과 실제 S3/ffprobe 검증은 완료했지만, 신규 서비스 전환은 보류했다.** 공유 DB에 기존 암호문이 있는데 이를 읽을 정상 암호화 키를 확보하지 못했다. 사용자가 명시한 조건에 따라 새 키를 생성하거나 기존 키·암호문을 변경하지 않았다.

실제 서비스 DB 마이그레이션 14개·API 재시작·신규 만료 타이머 활성화·실제 예약/인계 쓰기 검증은 **미적용/미검증**이다. 현재 구 API가 정상 실행 중이라는 사실을 신규 인계 배포 성공으로 표시하지 않는다.

- 작업일: **2026-11-24 UTC**, 주요 검사 04:47~05:20. 각 보호 결과 파일에 실제 실행 시각을 기록했다.
- 작업 경로: `/srv/nadree-api`, 서비스 계정 `ec2-user`, 서비스 `nadree-api.service`.
- 적용 기준 문서: [서버 실행서](handover-server-apply-2026-11-24.md), [마이그레이션 안내](../migrations/README.md).
- 저장소: clean 상태를 확인하고 `git pull --ff-only origin main`으로 `f974fc2` → **`7cb44ecac1bc12387ae7743c437a4f14a49a006f`** fast-forward 완료. 충돌·stash·강제 초기화 없음.
- 실제 DB: **RIDERLOG_V2_DATA_TEST**. 자동 테스트에는 이 DB를 지정하지 않았다.
- 실행서의 상위 원본 명세 파일과 AGENTS가 참조한 상위 기획 파일은 이 서버에서 찾지 못했다. 이번 확인은 제공 실행서·최신 코드·테스트 기준이다.

## 적용 완료·준비 완료 항목

| 항목 | 실제 결과 |
| --- | --- |
| 최신 코드 수신 | 위 커밋으로 fast-forward 완료. 신규 소스 수신과 실행 프로세스 전환은 별개 |
| `.env` 접근 | ec2-user 읽기 가능, 소유권 유지, 권한 **600** 유지 |
| ffprobe/ffmpeg 설치 | OS 저장소에 해당 패키지가 없어 FFmpeg 공식 다운로드 페이지가 안내한 배포처의 Linux x86_64 정적 빌드를 SHA256 검증 후 별도 경로에 설치 |
| 실제 실행 경로 | `/usr/local/bin/ffprobe`, `/usr/local/bin/ffmpeg`; 실체 `/usr/local/libexec/nadree-ffmpeg-9.0/`. ec2-user `-version` 성공 |
| 실행 버전 | `n9.0.2-62-gac1c6e003f-20261123` |
| ffprobe 설정 | `NADREE_MEDIA_FFPROBE=/usr/local/bin/ffprobe` 한 항목만 반영. 암호화 키 및 나머지 설정 바이트·소유권·600 보존. 아직 API 재시작은 안 함 |
| Python 의존성 | 기존 가상환경 `pip check`: **No broken requirements found**. 잠금 파일에 새 Python 의존성 변경은 없어 임의 전체 재설치하지 않음 |
| S3 권한 | 사용자가 EC2 역할 `aws-elasticbeanstalk-ec2-role`에 `NadreeHandoverMediaAccess` 추가 후 실제 POST/HEAD/GET/조건부 COPY/서명 GET 성공 |
| S3 범위 | 기존 `nadree-vehicle-img`, `ap-northeast-2`, 임시 `handover-upload-tmp/*`, 확정 `handover-media/*`. 기존 모델/차량 이미지·버킷 공개 여부는 변경하지 않음 |
| DB 복구 자료 | 변경 대상 및 예약 참조 4테이블을 접근 제한 SQL 백업. 실제 서비스 DB에는 DDL을 실행하지 않음 |
| 마이그레이션 리허설 | 별도 빈 MySQL DB에 실제 서비스 스키마 72개만 복제, 업무 데이터 복사 0건. 마이그레이션 후 재계획 0개·인계 FK 확인 |
| 정비/직접렌트 만료 unit | 제공 `.service`·`.timer` 파일 설치·daemon-reload 완료. **미활성**이며 스키마/키 확인 후 활성화 필요 |
| 기존 작업 보존 | 개인정보·채팅·인수 타이머 및 `/etc/cron.d/nadree-payment-recovery` 보존. 이번 작업에서 재시작/중단하지 않음 |

ffmpeg 배포 아카이브 SHA256은 `d7c47f73cf9f4eab46dc387b9aaef263ec56c3728d9dc783b713406bf2292766`으로 검증했다. 실행파일 출처는 [FFmpeg 다운로드 안내](https://ffmpeg.org/download.html)의 Linux 정적 빌드 링크이며, OS 기본 실행파일을 덮어쓰지 않았다.

## 실제 암호화 설정 확인 — 서비스 전환 차단 사유

현재 `NADREE_FIELD_ENCRYPT_KEY`는 1회 정의돼 있고 앞뒤 공백·개행·CRLF·명백한 예시 문구 문제는 없었다. 실행 중 프로세스 값과 `.env` 값은 같고 systemd 직접 설정/drop-in에 의한 별도 덮어쓰기 징후도 없었다. 그러나 **Fernet 키 형식 검사에 실패**한다.

기존 RiderLog 설정명 `FIELD_ENCRYPT_KEY`를 찾기 위해 현재 설정, 기존 10월 배포 백업, `/srv`, `/home/ec2-user`, `/opt`, `/home/ssm-user`의 RiderLog 관련 경로, `/var/app/current`, `/var/app/ondeck`, `/var/app/staging`, `/opt/elasticbeanstalk/deployment/env`와 get-config 경로 등을 확인했다. RiderLog 실행 소스/설정과 정상 형식 후보 키를 확보하지 못했다. 따라서 기존 RiderLog 복호화 코드로 정상 복호화까지 검증한 키는 없다.

확인한 구체적인 설정/백업 경로에는 `/srv/nadree-api/.env`와 `/srv/nadree-api/build/test-runtime/chat-trigger-activation-2026-10-27/env-before.private`가 포함된다. `.env.example` 같은 템플릿은 정상 운영 키의 근거로 사용하지 않았다. 위 파일의 값은 출력하거나 이 문서에 복사하지 않았다.

사용자 후속 지시에 따라 공유 DB의 전화번호·여권/면허·식별 가능한 `_enc` 문자열 컬럼을 **READ ONLY**로 확인했다. 원문을 출력하지 않고 Base64·버전 바이트·암호문 블록 길이 등 Fernet 구조만 검사했다.

| 기존 암호문 대상 | 확인 건수 |
| --- | ---: |
| `MSP_ADMIN.phone` | **27** |
| `MSP_DRIVER.phone` | **1,798** |
| 합계 | **1,825** |

이는 **암호문 구조 확인**이며 기존 키로 복호화 성공했다는 뜻이 아니다. RiderLog 원본 소스가 없어 모든 암호화 대상의 완전한 목록까지 보장하지는 않는다. 다른 조사 대상 전화번호 컬럼의 비어 있지 않은 일반 문자열은 암호문으로 단정하지 않았다.

기존 암호문이 확인됐으므로 **최초 설정용 새 키 생성 조건이 충족되지 않는다.** 기존 값 가공·새 키 생성·키 교체·기존 암호문 재암호화/NULL 처리/삭제를 하지 않았다. 이 상태로 신규 폼을 서비스하면 `PII_ENCRYPTION_NOT_CONFIGURED`로 막히므로 구 API를 유지했다.

키·암호문·복호화 개인정보는 이 문서에 없고, 안전한 건수 요약은 비공개 작업 디렉터리의 `encryption-inventory.json`에 기록했다.

## DB 계획·백업·리허설

`ec2-user`로 `python -m app.migrate`를 기본 읽기 전용으로 실행했다. 실제 서비스 DB는 다음 **14개가 미적용**이다.

- 인계 테이블 1개 및 조회 인덱스 3개.
- 계약 `handover_id` 컬럼·UNIQUE·FK.
- 차량 상태 `untracked_rent_until` 컬럼 및 상태/기간 CHECK 2개.
- 고객 `passport_number_enc`, `driver_license_number_enc`, `sns_info` 3컬럼.
- 기존 `MSP_RENTAL_USER.passport_img_key` 폐기.

기존 `passport_img_key IS NOT NULL`은 **0건**이다. 값을 NULL로 바꾸거나 연결 파일을 삭제하지 않았으며, 실제 DROP도 아직 실행하지 않았다. 적용 직전에 구 프로세스/관련 writer를 조율하고 다시 확인해야 한다. MySQL DDL은 전체 트랜잭션 롤백을 보장하지 않는다.

백업: `build/test-runtime/handover-server-2026-11-24/db-backup-20261124T045808541846Z/affected-tables.sql`.

| 백업 테이블 | 당시 행수 |
| --- | ---: |
| MSP_RENTAL_USER | 28 |
| MSP_RENTAL_CONTRACT | 22 |
| MSP_VEHICLE_STATUS | 79 |
| MSP_RESERVATION | 66 |

디렉터리 700·파일 600, 160,617바이트·dump 완료 표시·SHA256을 확인했다. 접속 설정은 600 권한의 익명 메모리 파일로만 전달했고 자격정보 파일을 디스크에 저장하지 않았다. 처음 백업 도구의 설정 파일 권한/클라이언트 옵션 문제가 있었지만 이를 바로잡은 뒤 위 백업이 완료됐다. 개인정보가 포함될 수 있는 SQL 원본은 공개하거나 커밋하지 않는다.

리허설에서는 원본 DB의 DDL만 새 `nadree_w02_test_migration_*` DB로 복제했다. 빈 DB라 역할 2개 seed가 추가되는 차이를 제외하면 서비스의 14개 계획을 실행했고, **재계획 0개** 및 예약/고객 FK를 확인했다. 실패한 리허설 시도는 복제 도구가 DDL 주석의 특수문자를 파라미터로 해석한 문제였고, 서비스 DB에는 영향이 없었다. 도구 보완 후 리허설을 완료했다.

격리 테스트/리허설 DB **4개는 종료 후 허용 목록·업무 데이터 없음 검사를 거쳐 정리**했고, 임시 테스트 DSN 파일도 제거했다. 서비스 DB는 삭제·초기화·자동 스키마 생성하지 않았다.

## 전체 자동 테스트 — 격리 검증

모든 테스트는 `ec2-user`, 서비스 환경변수를 제거한 새 `/tmp` 작업 경로에서 실행했다. 기본 회귀는 SQLite/가짜 외부 서비스, MySQL은 별도 빈 `nadree_w02_test_*`, Firestore는 `demo-nadree-chat` 로컬 에뮬레이터만 사용했다. 실제 서비스 DB·실제 Firebase 프로젝트를 자동 테스트 대상으로 지정하지 않았다.

| 실행 | 결과 | 범위/근거 |
| --- | --- | --- |
| 기본 전체 `pytest tests/ -q` | **938 passed / 23 skipped / 14 warnings**, exit 0 | 04:48:11~04:55:56 UTC. 약 382초 pytest 실행 |
| 별도 S3 대역 SDK 통신 | **16 passed**, 실패/skip 0 | 안전 검사 13개는 기본과 중복, 별도 HTTP 통신 **추가 3개**. 파일 분석기는 대역 |
| Firestore 에뮬레이터 | **8 passed**, 실패/skip 0 | demo 프로젝트·localhost·익명 자격. 테스트 후 에뮬레이터 종료 |
| 별도 MySQL 최종 검사 | **12 passed**, 실패/skip 0 | 05:08:17~05:09:57 UTC. 시작/종료 테이블 0개 확인 |
| 고유 합계 | **961 passed / 0 failed / 0 remaining skipped** | 기본 938 + S3 통신 3 + Firestore 8 + MySQL 12. 중복 안전 검사는 합산하지 않음 |

기존 지원 중단 경고는 업무 실패와 구분했다. 최초 MySQL 결과는 6통과·4실패·2오류였으며 다음을 분리해 해결했다.

1. 격리 DB 기본 `utf8mb4_unicode_ci`와 렌탈 fixture의 `utf8mb4_0900_ai_ci` 불일치로 FK 3780/JOIN 1267 발생. **빈 격리 DB의 기본값만** 맞췄으며 서비스 DB의 콜레이션은 바꾸지 않았다.
2. 동시 현장 신청의 정상 `202 PROCESSING`을 기존 테스트가 즉시 200만 허용해 실패로 판단. `tests/test_customer_receipt.py`의 MySQL 테스트 1개를 보완했다. 200/202만 허용하고, 202의 Retry-After·동일 요청 키·처리 중 상태·최종 ACCEPTED 조회·동일 키 재전송·최종 예약 1건을 모두 확인한다. API 업무 코드는 변경하지 않았다.

기본 23개 skip은 MySQL 12·Firestore 8·S3 대역 3개로 전부 별도 수행됐다. 테스트 개수는 실제 앱/배포 서비스 완주를 뜻하지 않는다.

### 최신 정책별 판정

| 요구사항 | 격리 자동 검증 | 배포 서비스 실제 업무 API |
| --- | --- | --- |
| USD finalPrice 승인·currency 입력 거절·중복 승인 | 통과 | 미검증 |
| 여권번호/숙소/헬멧 필수·헬멧 0·면허/SNS 선택 | 통과 | 키 미확보로 미검증 |
| 고객 폼→영상 READY→서명 순서 | 통과 | 미검증 |
| 추가 사진 필수·선택 사진 생략 | 통과 | 미검증 |
| 양측 완료·담당자만 시작·중복 계약 방지 | 통과 | 미검증 |
| 수정 거부 시 인계만 취소·예약/금액/배정 유지·새 키 재시작 | 통과 | 미검증 |
| 신규 예약·현장 신청·중복 처리·타 고객/타 지점 차단 | 통과 | 미검증 |
| cc 범위·정상 ImageKey/ImageUrl·전역 QR 중복 | 통과 | 신규 프로세스에서 미검증 |
| 회원정보 동기화·차량 변경·숙소 이력 | 통과 | 미검증 |
| 기간 직접렌트·종료일/다음 날/조기 해제 | 통과 | 미검증 |
| 일반관리자 탈퇴 시 담당 인계 이전 | 통과 | 실제 계정 탈퇴는 실행하지 않음 |

## 실제 S3·파일 분석 검증

API가 사용하는 EC2 역할 자격으로 **합성 단색 사진/영상만** 검사했다. 서비스의 실제 인계 API를 호출한 검사와는 구분한다.

| 가상 파일 | S3 POST | 실제 ffprobe·HEAD/GET·조건부 COPY | 확정 파일 조회 |
| --- | --- | --- | --- |
| PNG 사진 | **204** | READY | 서명 GET **200**, SHA256 일치 |
| MP4 **10.0초** | **204** | READY, 실제 길이 10.0 | 서명 GET **200**, SHA256 일치 |
| MP4 **10.1초** | **204** | **422 VIDEO_DURATION_EXCEEDED**, 확정 복사 차단 | 확정본 미생성 |

정책 추가 전 4개 작업은 AccessDenied였고, 사용자 정책 추가 후 위 실제 작업은 성공했다. **IAM 정책 조회는 여전히 AccessDenied**이며 실제 S3 작업 성공 여부와 별개다. IAM 조회 권한을 추가하거나 역할·버킷 정책을 임의 변경하지 않았다.

미디어 POST는 실제 반환 주소로 HTTP 재전송/redirect 없이 성공했다. 서명 URL·POST fields·AWS 토큰은 출력/문서화하지 않았다. 신규 임시 3개·확정 2개의 테스트 객체만 생성했으며 기존 파일은 건드리지 않았다. 해당 가상 객체는 보존 중이고 자동 삭제 기간을 임의 설정하지 않았다.

**브라우저 CORS는 별도 설정 대기/확인 실패:** 현재 API에 설정된 웹 origin에 대해 S3 OPTIONS POST/GET/HEAD를 보냈을 때 모두 **403**이었다. 버킷 CORS 설정 조회도 AccessDenied다. 이는 서버 SDK/네이티브 통신의 성공과 구분하며 웹 브라우저 직접 업로드 성공으로 표시하지 않는다. 기존 CORS 규칙을 임의 교체하지 않았다.

## 현재 서비스와 배치

- 현재 API는 구 PID **4096997**, 2026-11-11 14:46:57 UTC 시작 프로세스를 유지한다. 이번 작업에서 API 중단·재시작·신규 코드 전환은 하지 않았다.
- 로컬·공개 각각 `/health/live`, `/health/ready`, `/docs`, `/openapi.json` **총 8회 HTTP 200**. 현재 OpenAPI는 health 제외 **79경로**이고 신규 `/handovers` 경로는 없다. 이는 **구 API의 상태 확인**이다.
- `nadree-maintenance` 전용 unit 파일은 설치됐으나 **timer enable/start는 미수행**이다. 기존 user/root crontab·시스템 cron에서 `app.jobs maintenance/all` 중복 일정은 발견하지 못했다.
- 기존 개인정보·채팅·receipts 타이머 및 매분 결제 복구 cron은 보존했다. 전체 결제/환불 작업을 새로 실행하지 않았다.
- 실제 DB의 상태 집계는 AVAILABLE 73·DISABLED 1·ON_RENT 5였다. 기존 상태를 강제로 종료/만료시키지 않았다.

## 실제 업무 검증 준비와 미검증 범위

사용자가 기존 승인 테스트 지점의 전체 관리자·고객을 시험 수신 대상으로 허용했다. 읽기 전용으로 대표/일반관리자의 기존 암호 일치와 차량 2대의 실제 소속·활성·가격·QR 조건을 확인했다. 암호를 초기화하거나 시드를 재실행하지 않았다. 실행자료는 ec2-user 소유 600 파일에만 저장했다.

실제 HTTP 검증 러너와 재개 설명은 `build/test-runtime/handover-http-runner-2026-11-24.py` 및 같은 이름의 README에 준비했다. 구 PID·정상 키 미확보·미적용 스키마·다른 커밋이면 실행을 차단한다. **현재 `--execute`는 실행하지 않았고 실제 로그인·프로필 변경·예약 생성·인계 알림·계약 시작/반납도 0건**이다.

사전예약은 오늘 신청할 때 미래 시작일만 허용하므로, 당일 전체 완주는 현장 신청으로 검증하고 미래 사전예약은 신청/승인/권한 및 시작일 전 차단을 분리해야 한다. DB 시간 변경이나 날짜 검사를 우회하지 않는다.

실제 App Check/앱 화면/기기 푸시 수신/실제 서명 UI·원본 서류 촬영은 미검증이다. 실제 계정 탈퇴·결제·환불·Firebase 배포/보안 완화는 하지 않았다.

## 사용자가 추가로 준비할 것과 재개 순서

1. **기존 정상 암호화 키 확보:** RiderLog를 실제 운영한 서버의 비공개 설정 또는 백업에서 기존 키를 확인한다. 기존 암호문 1,825건이 있어 새 키로 임의 초기화하면 안 된다. 원문은 채팅으로 보내지 않는다. 기존 키를 구할 수 없다면 별도 키 관리/데이터 처리 정책을 먼저 확정해야 하며, 이번 작업에서 그 정책을 임의 도입하지 않았다.
2. **웹 S3 CORS:** 브라우저 사용 시 실제 웹 origin별 POST/GET/HEAD 허용을 기존 규칙에 추가하고 재검증한다. API CORS와 버킷 CORS는 별개이며 API 실행 역할에 버킷 관리 권한을 넓히는 방식은 필요하지 않다.
3. 키를 기존 암호문으로 검증한 뒤 `.env` 해당 항목만 복원한다. 소유권/600 유지와 다른 값 보존을 재확인한다.
4. 점검 시간에 기존 API 요청·관련 스키마 참조 배치를 조율하고 새 백업/여권 참조 재확인 → 승인된 서비스 DB의 `app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST` → 재계획 0개 → API 재시작/헬스·신규 OpenAPI 확인 순서로 진행한다.
5. maintenance timer를 중복 없이 활성화하고 기존 작업을 복구·보존한다. 신규 인계는 구 코드가 우회할 수 있어 문제 발생 시 무조건 구 버전으로 되돌리지 않는다.
6. 승인된 테스트 자료로 실제 예약·현장 인계·거부/재시작·10초/초과 영상·필수 사진/폼·담당자·조회·반납 검증을 수행하고 이 문서에 실제 결과를 추가한다. 타 지점/타 고객의 실제 검사는 별도로 승인된 상대 테스트 계정 자료가 있어야 한다.

## 프론트 전달 사항

- **현재 서비스는 신규 계약으로 전환되지 않았다.** 저장소/OpenAPI 예시가 바뀌었다고 구 API에서 새 요청이 동작하는 것으로 판단하지 않는다.
- 전환 후 availability는 `minCc`/`maxCc`(양 끝 포함, maxCc null 허용), 승인 요청은 `finalPrice`만 추가하고 `currency`를 보내지 않는다.
- 필수 폼(여권번호/숙소/헬멧 0 포함) → 제출 → 10초 이하 영상 READY → 서명 완료 순서를 따른다. 면허번호/SNS는 선택이다.
- 관리자 추가 사진 1장은 필수이며 여권/면허 사진만 생략 가능하다. 양측 완료 후 배정 담당자만 렌트를 시작한다.
- 수정안 거부는 예약 취소가 아니다. 반환된 `restartHandoverId`와 새 `clientRequestId`를 사용하고 승인 금액/배정을 유지한다.
- 현장 동시 요청의 `202 PROCESSING`은 결과 조회·동일 키 재시도로 해소한다. 새 요청 키를 임의 생성해 중복 신청하지 않는다.
- 업로드 POST의 fields를 그대로 전송하고 API complete 후 READY를 확인한다. 조회는 별도 GET URL을 사용한다. 최신 코드는 ImageKey=저장 키, ImageUrl=조회 URL 정상 계약을 유지하며 과거 임시 교환 설정으로 바뀌지 않는다.

## 보관한 근거와 수정 범위

비공개 근거 루트: `build/test-runtime/handover-server-2026-11-24/`(700). 백업 SQL·원본 실행 결과·암호문 건수·테스트 요약은 600이다. 테스트 계정/고객 선택 자료는 별도 private 파일이며 문서에 원문이 없다.

저장소 코드 수정은 **MySQL 동시 현장 신청 테스트 1개**뿐이다. 그 외 실제 변경은 ffprobe/ffmpeg 도구 설치·ffprobe env 항목·미활성 maintenance unit 준비와 승인된 S3 가상 검증 객체다. 사용자 IAM 정책 추가는 실제 작업으로 검증했지만 이 에이전트가 IAM 정책을 수정하지 않았다. 커밋·push는 하지 않았다.
