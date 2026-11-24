# 2026-11-24 인계·예약 API 서버 적용

> **초기 인계 구현 지시서 보존본. 현재 적용에는 [후속 통합 서버 지시서](backend-branch-feedback-server-apply-2026-11-24.md)를 사용한다.** 이 문서의 공용 키·인계 알림·간편대여 자동 해제·Firebase 배포 불필요 지침은 후속 승인으로 대체됐다. 아래 938건 수치는 이전 구현의 검증 기록이다.

상태: 승인된 명세를 로컬 구현했다. 이 파일은 배포 지시서이며 서버 적용 결과가 아니다. 기준은 `f974fc2` 이후 이번 변경이다. 기획 원본은 상위 폴더의 `rental-api-change-spec-2026-11-24.md`다.

## 반영 내용

- availability는 `minCc`~`maxCc` 양 끝 포함 범위로 요청한다. `maxCc:null`은 상한 없음이고 구 `cc`는 422다. cc 등급은 앱 표시만 사용한다.
- 신규 현장 렌트는 고객 차량 선택/QR → 견적·신청 → 관리자 승인 → 고객 인계 → 담당자 렌트 시작 순서다. 관리자 UID 직접 신규 출고는 차단한다. 기존 예약의 구 인수 경로는 유지한다.
- 새 예약 승인에는 `finalPrice`가 필수다. **USD 고정이며 승인 요청에 currency를 보내지 않는다.** 승인과 동시에 인계 준비 행 1개를 만들고, 가격 1컬럼을 예약·계약에서 공유한다.
- 고객이 인계를 시작하면 같은 지점 관리자들에게 알림을 보낸다. 먼저 촬영/검토 시작을 요청한 담당자를 고정한다.
- 고객 폼 필수값은 여권번호·숙소·헬멧 수이며 0개도 허용한다. 면허번호·SNS는 선택이다. 폼 저장 시 입력한 번호/SNS를 회원정보에도 반영한다. 관리자 수정안은 고객 수락 후 반영한다.
- 고객은 폼 제출 → 실제 10초 이하 영상 검증 → 서명 완료 API 순서다. 서명 원문은 저장하지 않는다. 관리자는 제출된 폼부터 확인할 수 있고, 고객 영상/서명은 병행 가능하다.
- **관리자 추가 사진 1개 필수**, 여권/면허 사진은 선택이다. 추가 사진 READY 전에는 관리자 확인·렌트 시작이 불가하다. 준비 단계의 `extra_photo_key`는 NULL을 허용한다.
- 양측 완료 후 배정 담당자만 `/nadreego/rent/approve`로 계약을 1번 생성한다. 인계당 수정 제안은 최대 1회이며 고객 거부 시 구 인계만 취소하고 같은 예약에 새 인계를 준비한다. 예약·승인 금액·배정은 유지하며 환불은 실행하지 않는다. 응답의 restartHandoverId와 새 clientRequestId로 인계를 다시 시작한다. 수정 기능 UI 사용은 후속 앱 업데이트로 미뤄도 API는 준비돼 있다.
- QR 전역 사용 여부, 정상 이미지 Key/Url 응답, 폼 기반 예약/렌트 상세, 같은 모델/가격의 예약 차량 변경, 실제 사용 숙소 이력, 종료일이 있는 `UNTRACKED_RENT`를 추가했다.
- 일반관리자 탈퇴 시 승인 업무와 별개로 담당 중인 인계도 대표에게 넘긴다. 대표의 미완료 업무 차단 정책은 유지한다.

## DB와 외부 설정

신규 테이블은 **MSP_RENTAL_HANDOVER 1개**다. 기존 사용자에는 암호화 여권·면허번호와 SNS TEXT 3컬럼, 계약에는 nullable `handover_id` 1컬럼, 차량 상태에는 `untracked_rent_until` 1컬럼을 추가한다. 관련 활성 인계·고객 요청·계약 연결 유일성 및 CHECK/FK도 적용한다. 예약·계약별 가격/통화 복사 컬럼은 추가하지 않는다.

공유 부모 테이블의 UID/예약 ID 콜레이션을 검사해 인계 FK 컬럼에 맞춘다. 인계 ID와 계약 handover_id는 동일한 utf8mb4_bin으로 생성한다. 부모 콜레이션을 확인할 수 없으면 계획 단계에서 중단한다. 이미 다른 형태의 인계 테이블이 있는 환경은 임의로 변환하지 않고 호환 검사를 따른다.

기존 사용자 `passport_img_key`는 폐기한다. 비어 있을 때만 계획에 DROP이 나온다. 참조가 남아 있으면 마이그레이션이 중단되므로 백업·자료 보관 방침을 확인한다. 임의 NULL 처리나 파일 삭제로 검사만 우회하지 않는다. 비활성 여권 업로드 라우트는 계속 Swagger에 등록하지 않는다.

기존 `NADREE_FIELD_ENCRYPT_KEY`를 유지한다. 키를 새로 만들거나 바꾸면 기존 암호문을 읽지 못한다. 기존 S3 버킷/리전/URL TTL을 재사용하며 다음이 추가로 필요하다.

```dotenv
NADREE_MEDIA_FFPROBE=/usr/local/bin/ffprobe
```

실제 설치 경로로 지정한다. 서버에 ffprobe가 없다면 OS/아키텍처에 맞는 검증된 ffmpeg/ffprobe 배포본을 설치한 뒤 서비스 계정에서 실행을 확인한다. 미설치 시 파일 검증은 503 `MEDIA_VALIDATION_UNAVAILABLE`로 차단된다.

```bash
sudo -u ec2-user /usr/local/bin/ffprobe -version
```

EC2 역할에 [S3 추가 정책](../deployment/s3-handover-policy.json)의 버킷 자리표시자를 실제 이름으로 바꿔 추가한다. 기존 모델/차량 읽기 권한도 유지한다. 신규 경로는 임시 `handover-upload-tmp/`, 확정 `handover-media/`다. 버킷은 비공개로 유지한다. 직접 브라우저 업로드라면 버킷 CORS에 실제 허용 프론트 origin의 POST/GET/HEAD를 설정한다. API CORS와 버킷 CORS는 별개다.

기본 업로드 제한은 MP4 영상 50MiB·실제 0초 초과~10초 이하, JPEG/PNG/WebP 사진 10MiB다. 서버가 발급한 POST의 모든 fields와 실제 파일을 S3로 전송하고, API complete 성공 후 READY로 표시한다. 임시 업로드 주소는 조회 주소로 쓰지 않는다. 완료 시 HEAD→다운로드 검사→ETag/VersionId 고정 복사하며, 사진·영상 조회 API에서 임시 GET URL을 발급한다. [POST 정책](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/generate_presigned_post.html), [다운로드 조건](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/get_object.html), [복사 조건](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/copy_object.html), [ffprobe](https://ffmpeg.org/ffprobe.html) 계약을 따른다.

확정 자료의 자동 보관·삭제 기간은 정하지 않았고 채팅 90일 정책을 적용하지 않는다. 임시 prefix만 별도 lifecycle로 정리할 수 있으며 기간은 운영에서 정한다. 버전 관리 버킷이면 임시 비현재 버전 정리도 함께 검토한다. S3 정책·CORS·lifecycle·ffprobe 설치는 이번 로컬 작업에서 실행하지 않았다.

## 서버 적용 순서

환경은 `/srv/nadree-api`, 서비스 사용자 `ec2-user`, 서비스명 `nadree-api` 기준이다. 기존 실행 계정/서비스명이 다르면 맞춘다. 먼저 Git 작업 내용과 DB 백업을 확인하고, 앱도 신규 요청 계약에 맞춰 전환한다. 스키마 추가 전 신규 API를 실행하지 않는다.

```bash
cd /srv/nadree-api
git status --short
git pull --ff-only origin main
```

기존에 미커밋 변경이 있으면 먼저 내용을 보존하고 충돌을 해결한다. 강제 reset은 사용하지 않는다. 의존성은 기존 가상환경을 유지하며 필요 시 잠금 파일로 설치한다.

```bash
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m pip install -r requirements.lock'
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
```

읽기 전용 계획에 이번 변경 및 기존 미적용 변경이 나올 수 있다. 실제 대상 DB·기존 자료·제약·백업을 확인한 뒤 점검 시간에 적용한다. 다음 DB 이름은 현재 테스트 환경 기준이며 다른 환경에 그대로 사용하지 않는다.

```bash
sudo systemctl stop nadree-api
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST'
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
sudo systemctl start nadree-api
sudo systemctl status nadree-api --no-pager
```

재계획에 미적용 변경이 없는지 확인한다. [013 SQL](../migrations/013_handover.sql)은 비교용이며 app.migrate와 중복 실행하지 않는다. MySQL DDL은 전체 롤백이 보장되지 않으므로 도중 실패 시 적용된 항목부터 확인한다.

직접렌트/정비 만료는 기존 `app.jobs maintenance`를 사용한다. 기존 cron/timer가 실행 중이면 하나만 유지한다. 아직 주기 실행이 없다면 다음을 설치한다. 실제 상태는 최대 5분 내 갱신되고 가용성 계산은 종료 다음 날 00:00부터 즉시 풀린 것으로 판단한다.

```bash
sudo install -m 0644 deployment/nadree-maintenance.service /etc/systemd/system/
sudo install -m 0644 deployment/nadree-maintenance.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nadree-maintenance.timer
sudo systemctl list-timers nadree-maintenance.timer --no-pager
```

Firebase Functions/Rules/인덱스의 새 배포는 필요 없다. 기존 FCM 설정과 커밋 후 발송 경로를 사용한다. 새 미디어/서류 필드 값을 로그·푸시 본문에 남기지 않는다.

## 검증과 복구

최종 로컬 전체 회귀는 **938 passed / 23 skipped**(122.48초)다. 실제 MySQL 등 환경 검증이 필요한 기존 20건과 별도 실행 조건인 S3 대역 통신 3건이 기본 실행에서 제외됐다. 기존 의존성 경고 14건은 유지됐다. 최신 거부/재시작·USD 입력·추가 사진 필수·MySQL 콜레이션 검사와 시작 전 본인 프로필 미리보기/시작 후 저장 번호 보존까지 포함한다. API 엑셀의 110메서드와 master C절 110개 앵커를 대조하고 요청/응답 JSON 예시 **195개**를 OpenAPI 타입·형식과 검증했다. 오류 정리는 현재 고정 정의 314종이며 모든 오류의 운영 재현 결과는 아니다.

S3 대역은 [simulation](../postman/simulations/handover-media.sim.yaml)과 [문맥/한계](../postman/simulations/handover-media.context.yaml)를 사용했다. 별도 **16 passed**(안전 검사 13 + 실제 SDK 통신 시나리오 3)다. 실제 boto3 HEAD/조건부 GET/조건부 COPY 성공, 미업로드 404, 저장소 장애 503을 확인했다. [비밀값 없는 요청 요약](handover-s3-simulation-2026-11-24.json)에 5개 HTTP 요청을 기록했다. 파일 분석기는 이 HTTP 검증에서 대역을 사용했으며 로컬 ffprobe는 설치돼 있지 않다.

서버에서는 테스트 고객·같은 지점의 대표/일반관리자·QR 차량을 이용해 예약과 현장 요청 각각 승인→인계→반납을 수행한다. 여권·숙소·헬멧 누락, 0개 헬멧, 추가 사진 누락/생략, 선택 사진 생략, 영상 10초/초과, 제출 전 관리자 열람, 타 지점/타 고객, 중복 승인/시작, 인계 중 차량 교체, 탈퇴 업무 인계, 직접렌트 종료일/다음 날/조기 해제를 확인한다. 실제 S3 파일·IAM·기기 FCM·실제 ffprobe 디코딩·MySQL 동시성은 로컬 통과와 구분해 기록한다.

실패 시 신규 쓰기를 중단하고 마지막 정상 코드와 이번 코드의 스키마 호환성을 먼저 확인한다. 신규 인계 예약은 구 코드가 인수 우회를 허용할 수 있어 단순 구 버전 재시작으로 복구하지 않는다. 구 앱 신규 입력을 차단하고 이번 코드 수정/재배포를 우선한다. DB 복구가 필요하면 점검 시간에 백업과 이후 생성된 예약/자료를 함께 대조한다. 이미 접수한 업무 데이터나 S3 파일을 일괄 삭제하지 않는다.

서버 Codex에 전달할 요청:

```text
docs/handover-server-apply-2026-11-24.md와 실제 git diff를 읽고 적용 상태를 확인해줘.
현재 환경과 DB를 확인하고 스키마 계획·비공개 백업·ffprobe·EC2 S3 prefix 권한을 점검해줘.
여권 이미지 참조가 남아 있으면 삭제하지 말고 중단 사유를 알려줘.
승인된 테스트 DB에 필요한 마이그레이션만 적용하고 재계획·API 재시작·기존 만료 배치 중복 여부를 확인해줘.
기존 예약 호환과 신규 예약/현장 요청 인계 전체를 검증해줘.
필수 추가 사진·필수 폼·10초 영상·서명·담당자·USD finalPrice·중복 시작·QR 전역 중복을 포함해줘.
실제 검증과 대역/미검증을 구분하고 비밀값 없이 결과 MD를 작성해줘.
```
