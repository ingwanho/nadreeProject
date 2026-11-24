# 서버 적용 지시서 — 11월 24일 프론트 후속 요청

**이 파일만 읽고 현재 서버 상태를 확인한 후 적용·검증할 수 있도록 작성했다.** 로컬 구현 기준은 `134cc08 server` 이후 변경이다. 이 문서는 실행 결과가 아니다. 마지막 서버 보고 `docs/handover-server-verification-2026-11-24.md`에서는 새 인계 마이그레이션·API 재시작이 보류됐고 구 API가 실행 중이었다. 작업 시작 시 실제 상태를 다시 확인한다.

## 이번 최종 정책과 변경

- 발리 `Asia/Makassar` 기준 날짜 대여, 종료일 포함. 새 견적 일수는 날짜 차이+1. Walk-in 당일 반납 허용, 새 requestType은 `WALK_IN`, 옛 `ONSITE`는 읽기 호환한다.
- 종료일 다음 날 미승인 `NO_RESPONSE`, 승인/구 인수 대기 `EXPIRED`+실물 회수 보호, 실제 대여 `OVERDUE`. 조회와 쓰기는 배치 지연 중에도 날짜를 재검사한다.
- 예약일·반납일·첫 연체일 09:00 알림. 인계 시작·폼 제출·고객 완료 3종 알림은 제거한다. 만료·미승인 종료 알림 없음.
- 새 인계·프로필 서류번호는 **`NADREE_HANDOVER_ENCRYPT_KEY`**. 기존 전화번호용 **`NADREE_FIELD_ENCRYPT_KEY`와 기존 암호문을 변경하지 않는다.** 사용자에게 별도 키 분리·서버 비공개 최초 생성을 승인받았다.
- SNS는 폼 제출 당시 값을 인계에 암호화 보존한다. 서명은 완료 상태·시각·고객·인계 ID만 반환하며 이미지/필기는 받지 않는다.
- 간편대여는 **고객·예약·계약·렌탈 이력 행을 저장하지 않는다.** 현재 차량 상태·기간·작업 ID·상태 버전만 보관한다. 예정일 후에도 실제 QR 반납 전 점유하며 미래 예약은 예정일 다음 날부터 접수 가능하다. 정비만 자동 해제한다.
- 계층 직접 차량 수·유효 비활성 하위 지점·전역 QR 재확인·최근 렌탈 3건을 반영한다. 프론트 계약은 [전달 문서](backend-branch-feedback-handoff-2026-11-24.md)다.

## 1. 현재 상태·백업·중복 배치 확인

```bash
cd /srv/nadree-api
git status --short
git log -3 --oneline
sudo systemctl show nadree-api -p User -p WorkingDirectory -p MainPID -p ExecMainStartTimestamp
sudo systemctl list-timers --all --no-pager
sudo -u ec2-user crontab -l
```

서비스 사용자가 `ec2-user`, 작업 폴더가 `/srv/nadree-api`라는 기존 정보를 가정한 예시다. 다르면 실제 서비스 사용자·폴더로 변경한다. `.env`는 소유 사용자만 읽고 쓰는 600을 유지하며 내용을 출력하지 않는다. Git 로컬 수정은 백업·차이를 확인해 보존하고 강제 reset 하지 않는다.

테스트 DB `RIDERLOG_V2_DATA_TEST`가 실제 대상인지 비밀값 없이 확인하고, 변경 전 DB·스키마·`.env` 비공개 백업을 만든다. 기존 전화번호 암호문, 사용자, 예약·결제·계약 행 수와 업무 상태를 기록한다. 초기화 도구는 별도 인계 키만 다루며 전체 DB 백업을 대신하지 않는다.

점검 시간에 API 및 실행 중인 receipts/maintenance/lifecycle 타이머와 해당 oneshot 작업을 먼저 정지한다. 존재하는 unit만 정지하고 기존 활성 여부를 기록한다. Git 갱신 전부터 새 소스가 배치에 노출되는 점을 고려한다. 기존 결제 복구·계정 삭제·채팅 보존 배치를 삭제하거나 임의 재설정하지 않는다. 같은 `app.jobs all` 또는 cron이 있다면 해당 중복도 함께 확인한다.

```bash
sudo systemctl stop nadree-api
git pull --ff-only origin main
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m pip install -r requirements.lock'
```

분기/로컬 수정으로 pull이 거절되면 보존 후 충돌을 해결한다. 키·백업·테스트 비공개 파일을 Git에 추가하지 않는다.

## 2. DB 계획과 적용

이번까지의 실제 추가 대상은 다음과 같다. 이미 적용된 항목은 `app.migrate`가 건너뛴다.

| 위치 | 내용 |
| --- | --- |
| `MSP_RENTAL_HANDOVER` | 인계 1테이블. 이전 인계 구현 33컬럼에 nullable `sns_snapshot_enc`, `signature_completed_at` 추가: 총 35컬럼 |
| `MSP_RENTAL_USER` | nullable `passport_number_enc`, `driver_license_number_enc`, `sns_info` |
| `MSP_RENTAL_CONTRACT` | nullable `handover_id`, 고유 연결·FK. **uid_token NOT NULL 유지** |
| `MSP_VEHICLE_STATUS` | nullable `untracked_rent_until`, `operation_id`; `state_version INT NOT NULL DEFAULT 0`; 관련 상태·기간 CHECK |
| `MSP_RESERVATION` | CHECK에 `NO_RESPONSE` 및 미적용 `HANDOVER_PENDING`, 기존 인계·현장 요청 컬럼/인덱스가 미적용이면 함께 계획 |
| 구 사용자 이미지 키 | `passport_img_key`가 전부 비었을 때만 제거. 잔존 참조가 있으면 보존하고 중단 사유 보고 |

공유 부모 UID/예약 ID 콜레이션을 검사한다. 마이그레이션은 부모 콜레이션을 확인할 수 없거나 기존 인계 테이블 구조가 호환되지 않으면 멈춘다. 전체 자동 create_all이나 시각화 SQL을 공유 DB에 실행하지 않는다.

```bash
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate --apply --confirm-database RIDERLOG_V2_DATA_TEST'
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
```

첫 계획·백업을 검토한 뒤 실제 apply를 실행한다. 재계획에 미적용 변경이 없어야 한다. `migrations/013_handover.sql` 등 비교용 SQL과 중복 실행하지 않는다. MySQL DDL은 전체 롤백이 보장되지 않아 실패 시 적용된 항목부터 재확인한다.

## 3. 별도 인계 키 최초 설정

기존 전화번호의 유효 키는 앞선 서버 점검에서 발견되지 않았다. **이유만으로 공용 FIELD 키를 새로 만들지 않는다.** 이번 분리는 새 인계·여권/면허 프로필 기능이 그 문제에 종속되지 않도록 한다. 기존 전화번호 복호화·변경 기능의 복구는 별도 작업이다.

점검 시간에 인계 쓰기가 정지된 상태에서 다음을 실행한다. `.env` 소유자인 ec2-user로 실행하며 키 값을 출력하지 않는다.

```bash
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python deployment/initialize_handover_key.py --confirm-database RIDERLOG_V2_DATA_TEST'
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python deployment/initialize_handover_key.py --confirm-database RIDERLOG_V2_DATA_TEST --apply'
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python deployment/initialize_handover_key.py --confirm-database RIDERLOG_V2_DATA_TEST'
```

처음은 읽기 전용이다. 이미 유효한 별도 키가 있으면 그대로 유지하고 복호화 가능한 기존 필드를 검사한다. 별도 키가 없고 새 프로필/인계 암호문도 없을 때만 `--apply`가 새 키를 `.env`에 저장한다. 해당 필드·암호화 수정안이 이미 있거나 설정된 키가 잘못됐으면 **키를 생성·교체하지 않고 중단**한다. 서버에 정상 원본 키를 복구한 뒤 재검사한다.

변경 전 `.env`는 실행 사용자의 `~/.nadree-private/env-before-handover-*`에 600으로 보관하며 디렉터리는 700이어야 한다. 정상 인계 키를 별도 비공개 백업에도 보존한다. `NADREE_FIELD_ENCRYPT_KEY`, 기존 전화번호 암호문, 다른 env 값은 도구가 변경하지 않는다. systemd Environment/EnvironmentFile에서 별도 인계 키를 다르게 덮어쓰고 있으면 먼저 정리한다.

## 4. S3와 앱 업로드

기존 `nadree-vehicle-img` 비공개 버킷, 기존 S3 env와 `/usr/local/bin/ffprobe`를 재사용한다. 실제 설정은 이름/리전만 확인하고 자격증명·서명 URL을 문서나 로그에 남기지 않는다. 기존 서버 보고에서는 실제 PNG·10초 영상·객체 복사·GET 검증이 통과했다. 이번 최종 코드의 앱 전체 시나리오와 구분한다.

- 임시 `handover-upload-tmp/*`: PutObject, GetObject, GetObjectVersion.
- 확정 `handover-media/*`: PutObject, GetObject.
- 기존 모델/차량 이미지 읽기 권한 유지, 버킷 공개 전환 없음.
- `NADREE_MEDIA_FFPROBE=/usr/local/bin/ffprobe`가 실제 실행 가능해야 한다.

네이티브 앱은 API에서 받은 POST URL+fields+파일로 S3 업로드 후 complete를 호출한다. 브라우저 OPTIONS 403은 이 네이티브 업로드의 차단 사유가 아니다. 웹/JavaScript WebView 업로드를 실제 사용할 때만 프론트 origin을 받아 S3 CORS를 별도 설정한다. API에서 앱 사진을 다시 받아 프록시 업로드하는 새 경로는 만들지 않았다.

## 5. API·Firebase·배치 적용

```bash
sudo systemctl start nadree-api
sudo systemctl status nadree-api --no-pager
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
curl -fsS http://127.0.0.1:8000/openapi.json -o /tmp/nadree-openapi-current.json
```

새 명세는 **105경로 / 111메서드(health 포함)**다. `/nadreego/vehicle/{vehicle_id}/rental-history`, `NO_RESPONSE`, `WALK_IN`, 새 정비/간편대여 QR·버전 입력, 서명 시각/행위자 필드를 확인한다. 로컬·공개 health/ready/docs가 현재 PID와 코드인지 확인한다.

Firebase `chat/functions/chat_core.py`의 종료 상태에 `NO_RESPONSE`를 추가했다. 기존 채팅 codebase `nadree-chat`, Python312, 자카르타 `asia-southeast2`를 유지하고 **현재 승인된 배포 계정으로 Functions를 재배포**한다. Rules·인덱스 변경은 없다. 다른 codebase를 삭제하거나 IAM을 늘리지 않는다.

```bash
cd /srv/nadree-api/chat
npx firebase deploy --only functions:nadree-chat --project bail-472405
cd /srv/nadree-api
```

기존 chat-sync 타이머의 다음 실행/승인된 일회 실행으로 SQL의 종료 상태를 동기화한다. 실제 Firebase 앱/토큰의 App Check 설정은 기존 정책을 유지한다.

알림 없는 과거 미승인 만료 보정을 먼저 1회 실행한다. 이 명령은 DB 상태를 변경하므로 위 테스트 DB 확인·백업 후 수행한다.

```bash
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.jobs lifecycle --backfill-no-response'
sudo install -m 0644 deployment/nadree-rental-lifecycle.service /etc/systemd/system/
sudo install -m 0644 deployment/nadree-rental-lifecycle.timer /etc/systemd/system/
sudo install -m 0644 deployment/nadree-maintenance.service /etc/systemd/system/
sudo install -m 0644 deployment/nadree-maintenance.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nadree-rental-lifecycle.timer nadree-maintenance.timer
sudo systemctl list-timers nadree-rental-lifecycle.timer nadree-maintenance.timer --no-pager
```

예약 전환/09:00 알림은 lifecycle 매분, 정비는 maintenance 5분 주기다. 예전 receipts 타이머는 같은 날짜 전환을 하므로 lifecycle로 대체하고 중복 상시 실행하지 않는다. cron/all 등 다른 소유자가 이미 같은 작업을 관리하면 한 방식만 선택한다. 중지해 둔 기존 관련 작업은 해당 역할·중복 여부를 확인해 복구한다.

## 6. 검증·실패 시 대응

현재 로컬 전체 회귀 **956 passed / 23 skipped**, 기존 의존성·자원 경고 14건. 23건은 실제 MySQL·Firestore 등 별도 환경과 S3 대역 통신 실행 조건이며 이번 최종 코드의 외부 종단 통과를 의미하지 않는다. 직전 서버 보고의 S3/Firestore/MySQL 격리 961건 결과도 이전 코드 기준의 별도 증거다.

서버에서는 승인된 테스트 고객과 같은 지점 대표·일반 관리자, QR 차량으로 다음을 확인하고 비밀값 없이 결과를 기록한다.

1. 사전예약/Walk-in 당일 1일 → finalPrice 승인 → 고객 시작 → 폼 → 영상 → 동의 → 관리자 필수 사진/확인 → 담당자 시작 → QR 반납. 앱 밖 수납이며 PayPal 호출 없음.
2. 종료일 당일 정상, 다음 날 미승인 NO_RESPONSE·미픽업 EXPIRED 회수 보호·실제 렌트 OVERDUE. 반복 배치·늦은 요청 차단·QR 회수·다른 정비/대여 보호 보존.
3. 09:00 수신자·중복·취소/반납 직후 발송 차단, 늦은 Walk-in 소급 알림 없음, 인계 3단계 무알림. 실제 기기 전달과 격리 검증 구분.
4. SNS 당시 값·동의 시각/본인/대상, 프로필 수정 후 과거 값 유지. 기존 전화번호 값/공용 키 보존.
5. 정비·간편대여 최종 QR/버전·중복·응답 유실·오래된 반납 요청 차단. 간편대여 기한 후 자동 해제 없음·이력 0행·미래 예약 가능·실제 미반납 인계 차단.
6. 계층 직접 차량 수·비활성 하위·QR 타 지점 정보 비공개·최근 3건 정렬/이전 배정, 실제 MySQL 중복 요청 경합.

실제 행의 종료일을 임의로 바꾸지 말고 승인된 격리 DB/테스트 자료를 사용한다. 기존 예약·결제·차량을 테스트 종료에 일괄 초기화하지 않는다. 업무 요청 성공 응답이 유실되면 기존 ID/키로 결과부터 조회한다.

실패 시 신규 쓰기를 중단하고 실패 단계의 상태·부분 DDL·자료를 보존한다. NO_RESPONSE·새 인계 키·35컬럼·새 인계 필수 조건을 모르는 구 코드로 단순 되돌리면 동작이 달라질 수 있다. 새 키는 유지하고 현재 스키마에 맞는 수정 배포를 우선한다. 전체 DB 복구가 필요하면 백업 이후 업무와 자료를 함께 대조하고 새 키·S3 파일을 임의 삭제하지 않는다.

서버 Codex 전달문:

```text
docs/backend-branch-feedback-server-apply-2026-11-24.md를 읽고 실제 git diff/서버 상태부터 확인해줘.
승인된 RIDERLOG_V2_DATA_TEST에 백업·DB 계획·미적용 변경을 적용하고 별도 인계 키를 비공개 초기화/검증해줘.
기존 FIELD 키와 전화번호 암호문은 변경하지 마. 고객 없는 대여는 이력 저장하지 마.
API 재시작, Firebase nadree-chat 종료 상태 배포, 무알림 NO_RESPONSE 일회 보정, lifecycle/maintenance 단일 배치를 적용해줘.
네이티브 앱 S3 업로드는 브라우저 CORS와 구분하고 원문 키·토큰·서명 URL은 출력하지 마.
문서 6절 검증을 수행하고 실제/격리/미검증·행 수 변화·남은 작업을 결과 MD에 구분해줘.
```
