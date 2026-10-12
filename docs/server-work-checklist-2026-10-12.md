# 나드리 서버 적용과 검증 작업 안내

기준일: 2026-10-12. 대상은 `/srv/nadree-api` 서버에서 작업하는 운영 담당자와 Codex다. 최신 백엔드 변경과 신규 Firebase 채팅을 적용하고 검증하기 위한 독립 실행 안내다. **명령을 처음부터 끝까지 한꺼번에 실행하지 말고 각 단계의 확인 조건을 충족한 뒤 진행한다.**

## 현재 상태와 작업 범위

- 로컬 코드와 문서는 작성되었지만 이 변경분의 운영 DB 마이그레이션·Firebase 배포·서버 배포는 완료로 확인되지 않았다.
- 로컬 Python 테스트 213개 통과, 9개 건너뜀. 건너뛴 Firestore 3개는 별도 에뮬레이터 실행에서 통과했고, Rules 테스트 4개도 통과했다. MySQL 테스트 6개는 미실행이다. 서버 재검증에서는 실제 결과를 새로 기록한다.
- 신규 채팅은 기존 FCM/Auth Firebase 프로젝트를 사용한다. 함수 리전은 **인도네시아 자카르타 `asia-southeast2`**다. 차량 위치 프로젝트는 사용하지 않는다.
- 신규 코드는 기본 `NADREE_FCM_CHAT_ENABLED=false`다. 배포와 설정 확인 전 활성화하지 않는다.
- 이 작업은 단순 문서 확인만 남은 상태가 아니다. 아래의 남은 개발 항목은 배포나 테스트 실행으로 자동 해결되지 않는다.

### 별도로 남은 개발과 확인

| 항목 | 해야 할 일 |
| --- | --- |
| 결제 상태 불명확 예약 만료 | PG 결과를 확인한 후 만료·재배정하도록 보완 |
| 뒤늦은 결제와 중복 청구 | 유효 원결제와 구분하여 추가 청구 자동 전액 환불 보완 |
| 실패 환불 | 자동 재시도·최종 실패 확인·운영 재처리 보완 |
| 예약 위치 정정 | 같은 장소의 오탈자/핀 보정과 실제 이전을 구분하는 계약·이력 보완 |
| 센서 QR와 차량 이동 | QR→sensorId 변환 계약, 재배정/이동 상세 시나리오 확인 |
| 공유 서버의 권한 변경 | 다른 서버나 직접 SQL로 소속을 변경하는 경로에도 즉시 채팅 권한 회수 연결 |
| 외부 서비스 인수 | 실제 MySQL 동시성, Firebase Auth/App Check/FCM, PayPal Sandbox 검증 |

현재 코드의 채팅 동기화는 예약·카탈로그 전량 재확인 방식이다. 처리시간이 실행 주기를 초과하면 증분 처리로 보완한다. 푸시는 best-effort이며 프로세스 종료 후 영속 재전송을 보장하지 않는다. 알림함은 중복 방지 키로 복구한다.

## 서버에서 작업하는 Codex의 안전 기준

1. 먼저 읽기 전용으로 코드 버전·실행 계정·DB 대상·Firebase 대상·현재 배포 상태를 확인하고 결과를 보고한다.
2. 운영 DB 변경, Firebase Rules/Functions 배포, 서비스 중단·재시작, 스케줄 등록, 실제 결제/환불은 대상과 영향 범위를 알리고 명시적으로 승인받은 뒤 수행한다. 이 문서 자체는 실행 승인이 아니다.
3. `.env` 전체, 서비스 계정 키, DB URL 원문, access/refresh/custom token을 출력하거나 결과 문서에 기록하지 않는다. `set -x`도 사용하지 않는다.
4. 사용자 변경 파일을 덮어쓰지 않는다. `git reset --hard`, 테이블 삭제, 운영 DB의 테스트 시드·create_all/drop_all 실행을 금지한다.
5. 테스트는 격리된 DB·Firebase demo 에뮬레이터·PayPal Sandbox를 사용한다. 라이브 예약 취소나 실제 고객 푸시를 검증 목적으로 실행하지 않는다.
6. 정책을 임의 변경하지 않는다. 미구현 항목은 미구현, 미실행 테스트는 미실행으로 보고한다.

## 확정된 정책

| 구분 | 기준 |
| --- | --- |
| 관리자 취소 | 인계 전 APPROVED 예약, 시작일 전만 가능, 100% 환불. 시작일 당일부터 취소 불가 |
| 고객 취소 | 인계 전 REQUESTED/APPROVED 예약. 시작일 전 90%, 시작일 당일부터 0% 환불 |
| 당일 판단 | 기본 Asia/Makassar의 시작일 00:00. 자카르타 함수 리전과 업무 시간대는 별개 |
| 감사 정보 | 기존 결제 행에 취소 요청자 유형·ID·환불률 저장. 클라이언트가 비율을 지정하지 않음 |
| 결제 기한 | 최초 승인+72시간과 렌탈 시작 시각 중 빠른 시각 |
| 지점가입코드 | 해당 지점 대표관리자로 즉시 가입. 일회용이며 상위지점 권한 없음 |
| 대표 이메일 가입 | 해당 대표에게 일반관리자 가입 요청, 승인 전 대기 |
| 채팅 | 직접 소속 지점만 열람. 일반관리자는 열람·알림, 대표관리자는 추가로 답변 가능 |
| 여권 | 인계 필수 조건 아님. 이번 작업에서 기존 파일 임의 삭제 금지 |
| 회사 공통 가격 | 기존 테스트 값을 유지. 실데이터 이전 시 회사별 정책 확정 |

## 1 서버와 코드 버전 확인

지금까지 확인된 환경은 작업 디렉터리 `/srv/nadree-api`, 서비스 사용자 `ec2-user`, 접속 사용자 `ssm-user`다. 실제 서비스 설정과 다르면 아래 명령의 사용자를 실제 값으로 변경한다. 서비스 이름은 추정하지 않는다.

```sh
id
ls -ld /srv/nadree-api
ls -l /srv/nadree-api/.env
systemctl list-units --all --type=service '*nadree*'
cd /srv/nadree-api
git status --short
git log -1 --format='%h %s'
```

확인한 실제 서비스 이름을 같은 셸에 입력한다. 이후 서비스 명령은 이 변수를 사용한다.

```sh
read -r -p '실제 API 서비스명(.service 포함): ' NADREE_API_UNIT
systemctl show "$NADREE_API_UNIT" -p User -p Group -p WorkingDirectory -p FragmentPath
```

로컬에서 새로 생성한 `app/chat.py`, `app/chat_sync.py`, `chat/` 전체, 관련 테스트·문서까지 저장소에 커밋·전달되어 있어야 서버에서 받을 수 있다. **로컬 미추적 파일은 git pull만으로 전송되지 않는다.** Git 갱신은 기존 배포 절차로 승인된 커밋을 받으며, 서버의 미커밋 변경이 있으면 먼저 보존한다. 이 문서 작성 작업은 commit/push를 수행하지 않는다.

```sh
test -f app/chat.py
test -f app/chat_sync.py
test -f chat/functions/main.py
test -f chat/functions/chat_core.py
test -f chat/firestore.rules
test -f chat/firestore.indexes.json
test -f chat/package-lock.json
```

하나라도 실패하면 배포를 진행하지 않는다.

## 2 환경 파일과 대상 확인

`.env`가 ec2-user 소유·600이면 ssm-user가 직접 읽지 못하는 것이 정상이다. 전체 공개 권한으로 바꾸거나 소유자를 ssm-user로 옮기지 않는다. 서비스 계정으로 명령을 실행한다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && test -r .env && .venv/bin/python --version'
```

설정에서 비밀값이 아닌 DB 이름·프로젝트 ID·기능 활성 상태만 확인한다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -c '\''from app.config import Settings; from sqlalchemy.engine import make_url; s=Settings(); print("database=", make_url(s.database_url.get_secret_value()).database); print("fcm_project=", s.fcm_project_id); print("chat_enabled=", s.fcm_chat_enabled); print("paypal_environment=", s.paypal_environment)'\'''
```

- DB 이름이 의도한 테스트/운영 대상과 같은지 확인한다. 서버가 현재 테스트 DB를 사용해도 무조건 삭제·재생성 가능한 DB라는 뜻은 아니다.
- Firebase 프로젝트는 `NADREE_FCM_PROJECT_ID`다. `NADREE_FIRESTORE_PROJECT`는 차량 위치용이므로 채팅 배포 대상으로 사용하지 않는다.
- 기존 FCM 계정에는 Firestore 접근과 Firebase Auth 사용자/토큰 발급 권한이 필요하다. 무조건 Owner 권한을 추가하지 말고 부족한 권한을 확인한다.
- 채팅 관련 신규 설정은 `NADREE_FCM_CHAT_ENABLED`뿐이며 처음에는 false를 유지한다. `NADREE_FCM_*` 기존 자격증명을 재사용한다.

파일 편집은 승인 후 `sudo -u ec2-user nano /srv/nadree-api/.env`처럼 소유자 계정으로 수행한다. 편집기 저장이 권한 문제로 실패하면 무작정 chmod하지 말고 경로·소유권을 확인한다. `sudoedit`는 상위 디렉터리가 다른 사용자에게 쓰기 가능하면 거절될 수 있다. 필요 시 운영 담당자가 root 편집기를 사용하되 변경 후 기존 ec2-user 소유·600을 유지한다. `.env`를 셸의 `source`로 실행하지 않는다.

## 3 백업과 DB 마이그레이션

적용 전에 현재 코드 커밋, DB 백업/복원 절차, `.env`의 접근 제한된 백업, 기존 Firebase Rules·인덱스·배포 함수 목록을 보존한다. 비밀 파일을 저장소나 공개 문서에 백업하지 않는다.

이번 변경에서 필요한 주요 DB 항목:

| 테이블 | 변경 |
| --- | --- |
| MSP_RENTAL_PAYMENT | cancellation_requested_by_type VARCHAR(20), cancellation_requested_by_id VARCHAR(36), refund_percentage INT, nullable |
| MSP_RENTAL_CONTRACT | pickup_location_snapshot, return_location_snapshot, nullable JSON |
| MSP_SPOT_RENT | address_detail VARCHAR(200), directions VARCHAR(500), nullable |
| MSP_RENTAL_NOTIFICATION | 지점 공통 알림·읽음, event_key UNIQUE, 조회 인덱스 |

기존 refund_requested_amount 등 이전 변경도 누락되어 있으면 계획에 함께 나타날 수 있다. Firebase 채팅 데이터 자체는 Firestore에 저장하며 별도 SQL 채팅 테이블은 없다.

먼저 읽기 전용 계획을 확인한다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
```

`PENDING ...`과 `Read-only plan; no database writes.`는 적용 완료가 아니다. 예상 밖 변경·기존 알림 테이블 구조 충돌이 나오면 중단한다. 구형 알림 테이블을 삭제하여 해결하지 않는다.

백업·공유 DB 담당자 승인·적용 시점을 확정한 후에만 아래를 실행한다. `CONFIRMED_DATABASE_NAME`을 위에서 확인한 DB 이름으로 바꾼다. 비밀번호는 명령에 넣지 않는다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate --apply --confirm-database CONFIRMED_DATABASE_NAME'
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.migrate'
```

완료 조건은 재조회 `No pending changes.`와 실제 스키마 일치다. MySQL DDL은 전체 롤백이 보장되지 않는다. 중간 실패 시 실제 적용 항목을 확인하고 남은 작업만 처리한다. 새 알림 테이블을 업무 트랜잭션에서 사용하므로 **스키마 적용 전에 새 API를 재시작하지 않는다.**

## 4 의존성과 격리 테스트

서비스 `.venv` 갱신은 실행 중 API에 영향을 줄 수 있으므로 승인된 배포 시간이나 별도 릴리스 가상환경에서 수행한다. 현재 Python 요구사항은 3.12 이상이며 Firebase Functions 런타임은 python312다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m pip install -r requirements.lock'
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m pytest -q'
```

pytest가 설치되지 않았다면 운영 가상환경에 임의로 개발 도구를 추가하기보다 별도 검증 가상환경을 준비한다. 테스트 선택 의존성은 pyproject.toml의 test 항목이다. `NADREE_TEST_MYSQL_URL`이 설정되어 있으면 먼저 가리키는 DB를 확인한다. MySQL 테스트는 **비어 있는 폐기 가능한 `nadree_w02_test_*` DB**만 사용하며 API가 사용하는 DB를 지정하지 않는다.

Firestore 보안·동시성 테스트는 운영 EC2가 아닌 별도 검증 장비에서 실행해도 된다. 저장소에서 고정한 테스트 도구는 Node 20·Java 17 환경으로 검증했다. npm 의존성은 chat 폴더의 개발/테스트용이며 API나 함수 런타임 배포에 포함하지 않는다.

```sh
cd /srv/nadree-api/chat
npm ci
npm test
npm run test:transactions
```

실행 계정이 chat 폴더와 백엔드 `.venv`를 사용할 수 있어야 한다. 마지막 테스트는 `../.venv/bin/python`을 사용한다. 프로젝트는 `demo-nadree-chat`로 고정되어 있다. 실제 Firebase 프로젝트 ID로 바꾸지 않는다. 포트 8080 충돌은 기존 서비스를 종료하지 말고 별도 검증 장비로 옮긴다.

## 5 Firebase 자카르타 리전 배포

기존 Firestore 위치에 맞춰 함수·API 응답·앱 호출 리전을 `asia-southeast2`로 통일한다. 업무 시간대 `Asia/Makassar`는 변경하지 않는다. 이전 서울 리전에 이미 배포한 이력이 있으면 이번 코드 변경만으로 기존 함수가 제거되는 것으로 간주하지 않는다. 기존 함수·만료 스케줄 목록을 확인하고 앱 전환 및 중복 스케줄 방지 계획을 세운 뒤 별도 승인으로 정리한다. 기존 함수 삭제 프롬프트를 자동 승인하지 않는다.

Firebase CLI를 사용할 승인된 배포 계정/장비에서 실행한다. EC2에 사람의 Firebase 로그인 자격증명을 저장할 필요는 없다. 프로젝트 선택은 항상 명시한다. 실제 프로젝트 ID를 확인하고 아래 변수에 입력한다.

```sh
read -r -p '확인한 FCM Firebase 프로젝트 ID: ' NADREE_FCM_DEPLOY_PROJECT
firebase projects:list
firebase functions:list --project "$NADREE_FCM_DEPLOY_PROJECT"
```

기존 FCM 프로젝트에 Firestore `(default)`와 함수 배포에 필요한 서비스·과금 설정이 준비되어 있어야 한다. 기존 Firestore 위치를 함수 리전 설정만으로 변경할 수는 없다. 신규 데이터베이스가 필요한 경우 생성 위치도 담당자에게 확인한다.

배포 전 필수 확인:

- 현재 운영 Rules·인덱스와 `chat/firestore.rules`, `chat/firestore.indexes.json`을 비교하여 병합한다. 기존 업무 규칙이나 인덱스를 누락하지 않는다.
- 전체 허용 catch-all 규칙이 있으면 채팅까지 허용하지 않도록 좁힌다. Firestore의 허용 규칙은 OR로 작동하므로 별도 deny로 기존 allow를 덮어쓸 수 없다.
- `chat/firebase.json`의 함수 codebase는 nadree-chat, 소스는 functions, 런타임은 python312다.
- 다섯 callable과 만료 함수의 리전은 소스에서 asia-southeast2로 고정되어 있다.
- App Check는 기본 강제다. 실제 앱을 등록하고 토큰 발급을 확인한다. 운영에서 테스트 편의를 위해 무조건 해제하지 않는다.

chat 폴더 안에서 Functions용 가상환경을 준비한다. 아래 명령은 Python 3.12가 설치된 배포 장비에서 수행한다.

```sh
cd /srv/nadree-api/chat
python3.12 -m venv functions/venv
functions/venv/bin/python -m pip install -r functions/requirements.txt
```

다른 장비이면 저장소 경로만 바꾼다. 실제 배포 승인을 받은 후 병합한 규칙으로 배포한다. 기존 함수 삭제나 인덱스 삭제를 요구하는 프롬프트가 나타나면 자동 승인하지 않고 중단한다.

```sh
firebase deploy --project "$NADREE_FCM_DEPLOY_PROJECT" --only functions:nadree-chat,firestore:rules,firestore:indexes
firebase functions:list --project "$NADREE_FCM_DEPLOY_PROJECT"
```

완료 조건: 아래 6개가 자카르타 리전에 배포되고 필요한 인덱스가 준비됨. 만료 스케줄은 15분 간격이며 관리자 callable이 아니다.

| 함수 | 용도 |
| --- | --- |
| ensureInquiryChat | 고객·지점의 열린 문의 재사용/생성 |
| ensureBookingChat | 예약에 연결된 방 조회 |
| sendChatMessage | 텍스트 저장, UUID 중복 처리 |
| markChatRead | 사용자별 읽음 위치 |
| getChatUnreadSummary | 지점별 미읽음 합계 |
| expireInactiveInquiries | 무대화 168시간 문의 만료 |

## 6 채팅 활성화와 API 재시작

DB·Firebase·IAM·App Check 확인 후 `.env`에 다음을 반영한다. 같은 키가 중복되지 않게 기존 값을 수정한다.

```dotenv
NADREE_FCM_CHAT_ENABLED=true
```

API와 아래 동기화 작업은 모두 같은 코드·같은 `.env`·같은 프로젝트를 사용해야 한다. 승인 후 API를 재시작한다. 셸이 바뀌었으면 1단계에서 서비스 이름 변수를 다시 지정한다.

```sh
sudo systemctl restart "$NADREE_API_UNIT"
systemctl is-active "$NADREE_API_UNIT"
sudo journalctl -u "$NADREE_API_UNIT" -n 100 --no-pager
```

로그에는 비밀값이 섞일 수 있으므로 원문을 외부 채팅/문서에 붙이지 않는다. `CHAT_SYNC_FAILED`는 성공이 아니며 IAM·프로젝트·Firestore 연결·Auth 계정을 확인한다.

## 7 동기화 작업 1회 실행과 스케줄 등록

이 명령은 읽기 전용이 아니다. SQL의 예약·상품 정보를 Firestore에 쓰고, 채팅 이벤트를 SQL 알림함에 저장하며 푸시를 발송할 수 있다. 테스트 대상과 수신자를 확인한 후 승인된 환경에서 실행한다.

```sh
sudo -u ec2-user -H bash -lc 'cd /srv/nadree-api && .venv/bin/python -m app.chat_sync'
```

종료 코드 0뿐 아니라 대상 지점의 chatShops/products와 예약의 bookingChatAccess 생성도 확인한다. 컬렉션은 최초 서버 쓰기로 생성되므로 콘솔에서 미리 만들 필요가 없다. 예약 동기화 실패는 최신 SQL 상태를 다시 읽어 복구하며 이미 닫힌 방은 재개하지 않는다.

정기 실행은 아래 systemd 예시를 사용하거나 동일 기능의 기존 운영 스케줄에 연결한다. **둘 다 등록하지 않는다.** 실제 서비스 사용자가 ec2-user인지 확인하고, 유닛 파일 생성은 승인 후 운영 담당자가 편집기로 수행한다. `.env`는 앱이 WorkingDirectory에서 읽으므로 systemd EnvironmentFile로 중복 해석하지 않는다.

`/etc/systemd/system/nadree-chat-sync.service`:

```ini
[Unit]
Description=Nadree chat reconciliation
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=ec2-user
WorkingDirectory=/srv/nadree-api
ExecStart=/srv/nadree-api/.venv/bin/python -m app.chat_sync
UMask=0077
```

`/etc/systemd/system/nadree-chat-sync.timer`:

```ini
[Unit]
Description=Run Nadree chat reconciliation

[Timer]
OnBootSec=1min
OnUnitInactiveSec=1min
Unit=nadree-chat-sync.service

[Install]
WantedBy=timers.target
```

이 예시는 직전 작업 종료 1분 후 재실행하므로 같은 유닛의 실행이 겹치지 않는다. 수동 실행이나 다른 cron까지 겹치면 보호되지 않으므로 단일 실행 주체를 유지한다. 작업 시간이 길어지면 알림 지연도 증가한다.

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now nadree-chat-sync.timer
systemctl list-timers --all nadree-chat-sync.timer
sudo journalctl -u nadree-chat-sync.service -n 100 --no-pager
```

## 8 서버와 앱 인수 검증

공개 주소가 기존과 같다면 다음을 실행한다. 503이나 JSON 파싱 실패는 정상으로 간주하지 않는다.

```sh
curl -fsS https://na-dree.com/health/live
curl -fsS https://na-dree.com/health/ready
curl -fsS https://na-dree.com/openapi.json | python3 -c 'import json,sys; p=json.load(sys.stdin)["paths"]; print({k: k in p for k in ["/nadreego/chat/session", "/api/v1/nadree/user/chat/session", "/nadreego/notifications"]})'
```

OpenAPI 경로 존재와 health 응답은 실제 채팅 성공을 증명하지 않는다. 다음은 테스트 계정/지점/예약으로 별도 확인한다. 토큰은 안전한 테스트 클라이언트에만 입력하고 셸 히스토리·로그에 남기지 않는다.

| 시나리오 | 기대 결과 |
| --- | --- |
| 관리자 POST /nadreego/chat/session | 관리자 Bearer만, 본문 없음. 직접 소속 shops·custom token·region 반환 |
| 고객 POST /api/v1/nadree/user/chat/session | 고객 Bearer와 현재 X-Refresh-Token 필요. managerId=null |
| Firebase 로그인 | custom token을 signInWithCustomToken으로 교환 후 자카르타 리전 callable 성공 |
| 권한 | 고객 본인과 직접 지점 직원만 조회, 일반관리자 답변 거절, 대표 답변 성공, 상위 대표의 미소속 하위지점 거절 |
| 문의 | 같은 고객·지점 열린 방 재사용, 다른 상품은 같은 방의 최근 상품만 변경 |
| 예약 전환 | 첫 예약에서 유효 문의의 roomId/메시지/읽음 유지. 두 번째 예약은 별도 방 |
| 중복 전송 | 같은 UUID·본문 재시도는 같은 sequence, 메시지/알림함 중복 없음 |
| 입력 제한 | 텍스트 UTF-8 1~2000바이트, 공백·초과 길이·직접 Firestore 쓰기 거절 |
| 종료와 만료 | 취소·거절·만료·반납 시 양쪽 전송 차단. 문의 168시간 무대화 만료. 종료된 방 재개 불가 |
| 세션 회수 | 로그아웃·다른 기기 로그인·대표 교체·직원 제거 후 이전 Firebase 토큰으로 조회/전송 거절 |
| 알림함 | CHAT_MESSAGE / CHAT / roomId 저장, 직원 한 명의 읽음이 지점 전체에 반영 |
| FCM | 현재 기기에 일반 안내만 전달. 본문/개인정보 없음. 토큰 변경 후 새 채팅 세션 발급 |
| 장애 복구 | 동기화 실패 후 최신 SQL 상태 재반영. 닫힌 방이 오래된 이벤트로 열리지 않음 |
| 기존 업무 | 취소 환불률·감사 컬럼, 가입코드 대표 즉시 가입, 이메일 가입 승인 대기, 일반 직원 인계/반납 회귀 |

관리자 세션 응답 필드: firebaseCustomToken, firebaseUid, managerId, shops[{shopId,spotCode}], region. 고객은 기존 Firebase UID를 사용한다. Callable 입력은 ensureInquiryChat(shopId, 선택 productId), ensureBookingChat(bookingId), sendChatMessage(roomId,messageId,text), markChatRead(roomId,messageId), getChatUnreadSummary(shopId)다. bookingId는 BO 접두어 없는 reservationId, productId는 해당 지점 modelId다.

직접 Firestore 조회는 chatRoomAccess에서 관리자 `shopId == 직접 지점`, 고객 `customerUid == 본인 UID`로 제한하고 updatedAt 내림차순·limit·startAfter로 페이지 처리한다. 메시지는 chatRoomAccess/{roomId}/messages에서 sequence 오름차순이다. 읽음 변경은 callable만 사용한다. 채팅 세션 발급은 FCM 등록 후 한 번 수행하며 화면별 중복 발급을 피한다.

## 9 장애 시 중단과 복구

- DB 마이그레이션 실패: 현재 스키마·적용 항목을 확인하고 중단한다. 테이블/컬럼을 삭제해서 되돌리지 않는다.
- API 재시작 실패: 실제 유닛·WorkingDirectory·서비스 계정·600 환경 파일 접근·의존성·스키마를 확인한다. 이전 릴리스 복구는 새 스키마와의 호환성을 먼저 확인한다.
- Firebase 배포 실패: 기존 함수/Rules를 보존하고 실패한 범위를 기록한다. 다른 프로젝트에 재시도하지 않는다.
- 채팅 동기화 실패: 이 구현은 안전을 위해 일부 로그인/권한 변경/예약 종료를 CHAT_SYNC_FAILED로 차단할 수 있다. API와 Firebase 장애를 함께 점검한다.
- 채팅 중단: `NADREE_FCM_CHAT_ENABLED=false`만으로 이미 발급한 Firebase 접근을 폐기할 수 없다. 먼저 채팅 Rules/callable 접근 차단과 활성 chatUsers 무효화를 승인된 절차로 수행한다. 그 후 타이머를 중지하고 환경설정/API를 변경한다. Rules만 막아도 Admin SDK를 쓰는 callable은 따로 차단해야 한다.
- 앱에 이미 저장된 오프라인 채팅 캐시는 원격 삭제를 보장하지 않는다. 앱 로그아웃 시 캐시 정리도 확인한다.

## 최종 보고 양식

다른 작업자가 이어받을 수 있도록 다음 내용을 비밀값 없이 기록한다. 결과는 서버 배포 커밋과 함께 보관한다.

```text
적용 일시와 담당자:
코드 커밋:
API 서비스명 및 사용자:
DB 이름 및 백업 확인:
마이그레이션 재조회 결과:
Firebase 프로젝트 ID / Functions 리전:
Rules 병합 및 인덱스 준비 상태:
배포된 함수 6개 확인:
채팅 활성화 상태:
동기화 최초 실행 / 타이머 / 단일 실행 확인:
Python 테스트 통과 / 실패 / 건너뜀:
MySQL 격리 테스트:
Firestore Rules / 동시성 테스트:
실제 Auth / App Check / FCM / PayPal Sandbox 결과:
권한 회수와 종료 경합 결과:
남은 구현과 미검증 항목:
프론트 전달 프로젝트 ID / 자카르타 리전 / API 주소:
전체 출시 가능 여부와 근거:
```

기능이 실제로 미구현이거나 외부 통합 검증이 남아 있으면 “전체 완료”로 보고하지 않는다. 이 문서는 작업 범위를 정리한 인수 안내이며 이후 코드 변경이 있으면 해당 커밋의 정책·테스트 결과로 갱신한다.
