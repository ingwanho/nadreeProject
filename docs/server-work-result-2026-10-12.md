# 서버 체크리스트 수행 결과

확인일: 2026-10-12 UTC. 수행: Codex, 접속 사용자 ssm-user.

## 확인 결과

| 항목 | 실제 확인 |
| --- | --- |
| 코드 | `bae6de0` (`프론트 추가사항`). 필수 채팅 파일 7개 존재. 기존 미추적 `nohup.out` 보존 |
| API 서비스 | `nadree-api.service`, active/running, User=ec2-user, WorkingDirectory=/srv/nadree-api |
| 환경 파일 | 최초 샌드박스 조회 소유자 nobody:nobody, 권한 600. 서비스 계정으로 설정 조회 성공. 소유권·권한 변경 없음 |
| DB | `RIDERLOG_V2_DATA_TEST`. API 사용 DB이므로 폐기 가능한 테스트 DB로 취급하지 않음 |
| Firebase | 설정상 `bail-472405`. 실제 배포 함수·Rules·인덱스는 미조회 |
| 채팅 | `False`. 활성화·동기화 실행·타이머 등록 없음 |
| PayPal | `SANDBOX`. 실제 주문·캡처·환불 검증 없음 |
| 공개 health | https://na-dree.com/health/live 정상. ready 정상 응답이나 `MFA_FLOW_NOT_IMPLEMENTED` 제한 포함 |
| 공개 OpenAPI | 관리자/고객 채팅 세션 및 `/nadreego/notifications` 모두 없음 |
| 현재 소스 OpenAPI | 위 3개 경로 모두 있음. 실행 서비스에 현재 소스가 반영됐다고 판정할 수 없음 |
| 필수 상위 문서 | `/srv/rental-project-master.md`, `/srv/rental-api-review-decisions.md` 없음. 정책 구현 변경 보류 |
| 에뮬레이터 도구 | Node·Java·Firebase CLI 미확인/표준 경로에 없음, chat/node_modules 없음. Rules·트랜잭션 테스트 미실행 |

## 읽기 전용 마이그레이션 조회

서비스 계정으로 `python -m app.migrate` 실행, 종료 코드 0. 다음 9개 계획 항목이 남아 있다.

```text
PENDING create MSP_RENTAL_NOTIFICATION
PENDING index ix_notification_shop_read
PENDING add MSP_SPOT_RENT.address_detail
PENDING add MSP_SPOT_RENT.directions
PENDING add MSP_RENTAL_PAYMENT.cancellation_requested_by_type
PENDING add MSP_RENTAL_PAYMENT.cancellation_requested_by_id
PENDING add MSP_RENTAL_PAYMENT.refund_percentage
PENDING add MSP_RENTAL_CONTRACT.pickup_location_snapshot
PENDING add MSP_RENTAL_CONTRACT.return_location_snapshot
Read-only plan; no database writes.
```

백업·복구 절차 및 공유 DB 담당자 승인은 미확인. `--apply`는 실행하지 않았다. 스키마 적용 전 API 재시작 금지 조건을 유지한다.

## 격리 검증

운영 `.env`를 읽지 않도록 `/tmp`에서 환경변수를 비우고 `PYTHONPATH`로 현재 소스를 지정했다. MySQL URL·Firestore emulator 설정을 전달하지 않았으며 테스트는 임시 SQLite를 사용한다. 기존 서비스 가상환경의 의존성을 변경하지 않았다.

최초 샌드박스 실행은 TestClient의 스레드 대기에서 멈춰 중단했다. 샌드박스 밖에서 동일 격리 조건으로 재실행했다. 결과: **213 passed, 9 skipped, 2 warnings in 40.30s**, 종료 코드 0. 건너뜀은 MySQL 6개와 Firestore 3개다. 경고는 Starlette/httpx 및 anyio API deprecation이다. Rules 테스트 및 실제 외부 서비스 인수는 미실행이다.

## 후속 작업과 출시 판단

전체 출시 완료로 판정하지 않는다. DB 미적용, 공개 신규 API 경로 누락, 실제 Firebase 배포·Auth/App Check/FCM·PayPal 인수 미검증이 근거다. 코드에서 요구한 서울 리전은 `asia-northeast3`이며 실제 배포 여부는 확인되지 않았다.

다음 운영 작업은 체크리스트의 명시적 승인 조건에 따라 미실행이다: DB 마이그레이션, Firebase Rules/Functions/인덱스 배포, 채팅 활성화, API 재시작, 최초 동기화 및 스케줄 등록. 먼저 DB 백업·적용 주체와 Firebase 기존 Rules/인덱스 보존을 확인해야 한다.

별도 개발 잔여 항목도 그대로 남아 있다: PG 상태 불명확 만료 처리, 늦은/중복 결제 자동 전액 환불, 실패 환불 재시도·재처리, 예약 위치 정정 계약·이력, 센서 QR 변환·차량 이동, 공유 서버 권한 변경 시 즉시 채팅 회수. 필수 상위 정책 문서 확보 후 구현 범위와 계약을 확인해야 한다.

프론트 전달 후보 설정: 프로젝트 `bail-472405`, 리전 `asia-northeast3`, API `https://na-dree.com`. 채팅 실사용 가능한 배포 상태로 전달하면 안 된다.

## 후속 검증: 건너뛴 테스트 실행 완료

2026-10-12 08:03 UTC 추가 기록. 위 내용은 최초 점검 시점의 상태이며, 최신 Firebase/DB 배포 상태는 `firebase-deployment-trace-and-replacement-plan-2026-10-12.md`를 따른다. 현재 계약의 함수 리전은 자카르타 `asia-southeast2`다.

| 테스트 | 실제 결과 | 격리 환경 |
| --- | --- | --- |
| MySQL 동시성 6개 | 6 passed, 0 skipped, 2 deprecation warnings, 5.85초 | 공식 MySQL Community 8.4.6, 네트워크 비활성, 임시 디렉터리 전용 Unix socket, 새 `nadree_w02_test_*` DB |
| Firestore 트랜잭션 3개 | 3 passed, 0 skipped, 2 deprecation warnings, 8.76초 | demo-nadree-chat, Firestore emulator 1.19.8, 127.0.0.1:18080 |
| Firestore Rules 4개 | 4 passed, 0 failed/skipped | 같은 demo 에뮬레이터, 현재 저장소 Rules |

기존 Python 213 passed/9 skipped에서 건너뛴 9개는 이번에 모두 별도 실행했다. 전체 222개를 한 번에 실행했다고 보고하지는 않는다. Rules 4개는 Python 테스트와 별도다. Rules 출력의 PERMISSION_DENIED는 금지된 클라이언트 쓰기의 거절을 확인하는 기대 결과다.

MySQL 최초 실행은 4 passed/2 failed였다. 지점 생성 테스트는 최신 필수 이메일·주소·좌표가 없어 422였으며 테스트 요청을 수정했다. 이메일 경쟁 테스트는 account/refresh row lock 뒤의 barrier 때문에 두 요청이 만나지 못해 BrokenBarrierError였다. barrier를 principal 확인 직후, DB 잠금 이전으로 이동하고 최종 동일 이메일 소유자가 1명인지 검증을 추가했다. 수정 범위는 `tests/test_mysql_concurrency.py`이며 서비스 코드·정책은 변경하지 않았다. 재실행에서 6개 모두 통과했다.

Java는 공식 Amazon Corretto 17.0.20.12.1, Node는 기존 22.23.2, Firebase CLI는 기존 13.35.1이다. 시스템 패키지를 설치하거나 기존 API 가상환경을 갱신하지 않고 `build/test-runtime/`에 검증 런타임을 풀었다. Firebase 설정은 별도 파일과 demo 프로젝트를 사용하고 실제 자격증명/NADREE 환경변수는 테스트에 전달하지 않았다. CLI의 Rules 경로 제한을 해결하기 위해 현재 Rules/인덱스와 바이트 동일한 파일을 검증 설정 디렉터리에 복사했고 최종 실행은 경로 경고 없이 성공했다.

테스트용 MySQL 두 인스턴스와 Firestore 에뮬레이터는 종료했다. 런타임·임시 DB 파일은 git에서 제외되는 `build/test-runtime/`에 남아 있다. 공유 DB 변경·운영 Firebase 배포·채팅 활성화·API 재시작·실제 결제/환불/고객 푸시는 수행하지 않았다.

검증 범위는 현재 Python 구현/SQL API 동시성과 저장소 Rules다. 기존 배포 Node.js callable과 현재 계약의 불일치, 출시 앱과 실제 Auth/App Check/FCM·PayPal Sandbox 인수는 이 테스트 통과로 해결되거나 완료되지 않는다.
