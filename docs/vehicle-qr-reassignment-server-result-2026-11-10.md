# 차량 QR 삭제·재연결 구현 및 서버 결과

작성일: 2026-11-10 UTC. 기준 커밋 91d6be9973ec52e7b0e718a94d68f9dd5543731a + 보존한 기존 서버 로컬 수정 + 이번 QR 변경이다. 사용자 요청으로 QR 연결 실제 삭제·해제 QR 재사용·기존 차량 단독 연결 API를 구현하고 지정 시험 차량의 비활성 연결을 정리한다.

## 구현

- 기존 POST /nadreego/sensor/delete의 division=QR은 현재 연결 행을 DELETE하고 DELETED 감사 이력을 남긴다. 센서 분기는 유지한다.
- 신규 POST /nadreego/vehicle/qr/link: vehicleNumber/qrToken으로 QR 없는 기존 차량에만 연결한다. 동일 활성 연결은 멱등이며 자동 이동·교체는 하지 않는다.
- 차량 생성의 과거 이력 중복 차단을 제거하고 현재 연결만 중복 차단한다. 현재 연결 UNIQUE/차량당 QR PK/HMAC·대소문자/지점·업무 가드를 유지한다.
- QR 없는 차량의 QR_LINK, 비활성·만료를 포함한 현재 연결의 QR_DELETE 액션을 제공한다.
- 고객 QR 해석·현장 신청에서 재연결 경합 시 차량을 재검증하고 삭제와 조회가 겹쳐도 QR_NOT_FOUND로 응답한다. 완료 인수 재전송은 유지한다.
- 추가 마이그레이션·env·Firebase 변경은 없다. 기존 개인정보 수정과 배치 설정을 보존한다.

부모 계약 문서 두 파일은 /srv에 없어 수정하지 못했다. 현행 [전체 인수서](nadree-full-change-handoff.md)와 [프론트 문서](frontend-vehicle-qr-reassignment-2026-11-10.md)에 변경 계약을 기록한다.

## 검증 및 실제 적용

2026-11-10 02:47~02:52 UTC 실제 확인을 완료했다. 검사는 이번 QR 변경과 연결된 부분만 실행했고 전체 회귀를 재실행하지 않았다.

| 구분 | 대상 | 실제 결과 |
|---|---|---|
| 격리 | QR 삭제·재연결·차량 이동·OpenAPI·현장 신청·인수 | **96 통과 / 3 건너뜀**, 최종 실패 0(중복 재검사 제외) |
| 서버 | API 재시작·헬스·Swagger·신규 경로 | **02:47:21 UTC 재시작**, ec2-user·/srv/nadree-api·PID 2444894, active/running |
| 서버 | 로컬 127.0.0.1:8008 / 공개 https://na-dree.com | /health/live·/health/ready·/docs·/openapi.json 모두 **200**, health 제외 **79개 경로** |
| 서버 | 신규 POST /nadreego/vehicle/qr/link | OpenAPI 경로·Bearer 보안·요청 예시 확인, 로컬/공개 무인증 **401 AUTH_REQUIRED** |
| 승인 시험 데이터 | testlisence의 지정 INACTIVE 연결 1행 | **02:50:04 UTC 백업 후 DELETE 1행·DELETED 이력 INSERT 1행** |
| 실제 DB 재조회 | 지정 차량 QR / 해제 원문의 현재 점유 | 각각 **0행**, 이력은 기존 2행 보존 + 삭제 이력 1행 = 3행 |
| 실제 DB 재조회 | 지정 차량 활성·렌탈 가능·상태 | is_active=1·rental_enabled=1·AVAILABLE 보존 |
| 보존 | .env·기존 개인정보/인수/채팅 타이머 | .env 수정 없음·600 유지, 네 타이머 active 보존. 결제 cron 설정 변경 없음 |
| 로그 | 재시작 후 API | startup complete, ERROR/Traceback·HTTP 5xx 로그 **0건** |
| 실제 앱 | 양 앱 화면·실기기 QR 스캔 | 미검증 |

### 격리 검사 근거

ec2-user, Python 3.12의 기존 venv, env -i·Settings(_env_file=None)·폐기용 SQLite·가짜 외부 연동으로 실행했다. 실제 서비스 DB·Firebase·PayPal·SMTP·푸시는 테스트에 사용하지 않았다.

```text
sudo -n -u ec2-user env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/test_vehicle_qr.py tests/test_vehicle_qr_reassignment.py \
  tests/test_vehicle_transfer.py tests/test_foundation.py \
  tests/test_customer_receipt.py tests/test_onsite_request_outcomes.py -q -p no:cacheprovider
```

첫 실행은 88 통과·3 건너뜀·신규 테스트의 응답 객체 경로 오타 3건 실패였다(50.03초). 구현 결함이 아니라 테스트가 vehicle.vehicleId를 vehicleId로 읽은 오류로, 수정 후 해당 3건이 통과했다. 추가 재연결 경합 파일은 fixture import 누락을 보완하고 **5건 통과**(3.22초)했다. 총 관련 **96개 고유 검사 통과 / 3개 건너뜀**이며 미해결 실패는 없다. 기존 TestClient 의존성 사용 중단 예정 경고 2종은 남는다.

```text
... pytest tests/test_vehicle_qr_reassignment.py::test_delete_removes_only_current_qr_and_preserves_deleted_history_and_sensor tests/test_qr_reassignment_receipt.py -q -p no:cacheprovider
... pytest tests/test_qr_reassignment_receipt.py -q -p no:cacheprovider
```

건너뜀 3건은 전용 폐기용 MySQL 환경이 필요한 현장 신청/close/고객 인수 동시성 검사다. SQLite 경합 인터리빙 5건 통과를 실제 MySQL 동시 접속 검증으로 간주하지 않는다. 현재 QR UNIQUE·차량 PK와 기존 잠금은 유지했다.

### 지정 차량 실제 정리

사용자가 지목한 차량 c5b4ccca-3b14-46d7-81f2-d8201b87425a / 번호 testlisence / 최상위 시험 조직만 대상으로 했다. 현재 .env의 DB RIDERLOG_V2_DATA_TEST를 확인하고 기본 읽기 전용 계획을 먼저 실행했다. INACTIVE 현재 연결 1행·기존 이력 2행·진행 렌트 0·인수 대기 0·AVAILABLE을 확인했다.

적용 시에도 지점/차량/상태 잠금 및 동일 QR named lock 아래 대상·원문 일치·안전 조건을 다시 확인했다. 다른 차량의 QR이나 현재 테스트 QR 전체를 일괄 변경하지 않았다. 이전 감사 이력 2행은 유지했고 삭제 이력 1행만 추가했다. 차량·대여 확장·상태 행이 전후 동일함을 확인했다. 예약/렌트/결제/센서 쓰기·로그인·푸시·메일은 실행하지 않았다.

백업은 build/test-runtime/qr-reassignment-2026-11-10/20261110T025004363697Z/의 before.private.json 및 result.private.json이다. 디렉터리 700·파일 600·ec2-user 소유를 실제 확인했다. 원문 해시·DB 자격정보는 이 문서에 적지 않는다.

현재 차량에는 새 QR을 임의 발급하지 않았다. 앱에서 원하는 QR 원문으로 신규 link API를 호출하거나, 해제된 기존 원문을 같은 차량/다른 차량에 연결할 수 있다. 원문은 재연결 전 조회 404가 정상이다.

### 미검증·후속

- 신규 연결 API의 **인증된 실제 서버 쓰기 왕복**은 수행하지 않았다. 정상 연결·삭제·재연결·권한·보호 상태는 격리 API로 검증했고, 실제 서버는 승인 대상 연결의 백업/삭제와 명세·인증 차단을 확인했다.
- 실기기 QR 스캔·관리자 화면 버튼/목록 갱신·고객 앱 현장 견적/인수는 [프론트 체크리스트](frontend-vehicle-qr-reassignment-2026-11-10.md)대로 공동 확인한다.
- 실제 MySQL 동시 접속은 승인된 폐기용 DB를 준비한 뒤 별도 확인한다.

## 보존·복구

QR 이력을 일괄 삭제하지 않고 현재 점유 판정에서 분리한다. 지정 차량 외 QR·차량·센서·예약·결제는 변경하지 않는다. 대상 현재 연결과 이력을 접근 제한 백업 후 정리하며 복구 시 대상 차량에 QR이 없고 원문이 다른 차량에 재사용되지 않았는지 먼저 확인한다. 이미 재사용한 QR을 강제 복구하지 않는다.

코드 복구는 이번 QR 변경만 선택적으로 되돌리고 기존 개인정보 로컬 변경을 보존한다. 과거의 이력 기반 재사용 금지 정책으로 복귀하면 이미 재사용한 QR의 후속 동작에도 영향을 주므로 데이터·앱 상태를 먼저 검토한다.
