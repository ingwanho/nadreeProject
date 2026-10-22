# 2026-10-22 결제 8번 정산 지연 진단·자동 복구 cron 적용

## 현재 결과

사용자의 자동 복구 설치·cron 등록 요청에 따라 **PayPal 조회로 완료된 결제만 서버에 반영하는 작업을 매분 등록했다. 02:47 UTC 실제 cron 첫 실행에서 결제 8번이 PENDING → PAID로 반영됐고, 02:48 실제 고객 인증 API에서도 PAID / DONE / canCapture=false를 확인했다.** 추가 캡처·환불·예약 만료·푸시는 실행하지 않았다. 실제 서명 웹훅 전달 성공과 조회 복구 성공은 구분한다.

예약은 `8e217b09-9760-4ec1-aeb4-dc2fa933fb54`, 연결 결제 ID는 8번이다. 예약 테이블에 문자열 `8` 자체의 예약은 없으며 기존 승인된 테스트 고객의 신규 예약·연결 결제를 대조해 대상을 확인했다. 현재 예약 상태는 APPROVED이고 진행 목록에는 이 결제 완료 예약 1건이 있다. 앞선 7번 취소 후 진행 0건은 01:47 당시의 검증 결과이며, 이번 8번은 그 후 01:58에 새로 생성됐다.

## 원인과 확인 근거

| 검사 시각 UTC | 검사 | 실제 결과 |
| --- | --- | --- |
| 02:27 | DB 예약·결제 연결 | 예약 APPROVED/PROVISIONAL, 결제 PENDING·캡처 ID 있음·paid_at 없음 |
| 02:28 | PayPal 주문/캡처 직접 GET | 모두 HTTP 200/COMPLETED, USD 90.00, 캡처 1건·SQL 캡처 ID 및 판매자 일치 |
| 02:28 | 실제 서비스 로그 | 02:06:03 capture POST 200, 관련 상태 GET 27건 모두 200, 확인한 구간의 공급자 오류/Traceback 없음 |
| 02:28 | PG 이벤트·서버 반영 | PG 완료 이벤트 생성 02:06:33.982Z, SQL의 해당 이벤트/정산 기록 없음; 확인한 요청 로그에도 해당 웹훅 수신 기록 없음 |
| 02:28 | 기존 웹훅 설정 | 콜백 `https://na-dree.com/nadreego/paypal/webhook` 일치·15개 기존 구독 유지·필수 결제 이벤트 누락 없음 |
| 02:31 | 자동 실행 상태 | nadree-payments.timer/service 모두 not-found/inactive, 확인한 cron 파일에 복구 작업 없음·실행 중 작업 없음 |
| 적용 전 | cron 데몬 | cronie 미설치·crond.service 없음 |

현재 capture API는 성공 결과의 캡처 ID와 PENDING을 먼저 저장하고 최종 PAID는 검증된 웹훅/조회 복구에서 확정한다. 상태 GET은 캡처 ID가 이미 있으면 PG 재조회·정산 쓰기를 하지 않고, `_payment_next_action`이 WAIT를 반환한다. 따라서 **캡처 자체는 완료됐지만 웹훅이 반영되지 않고 자동 복구도 등록되지 않아 대기가 지속됐다.** 상태 GET을 반복하는 것만으로는 PAID가 되지 않는 조건이었다.

확인 코드: `app/customer_rentals.py`의 `_payment_next_action`, `nadree_payment_capture`, `nadree_payment_status`; `app/payment_recovery.py` 및 `app/jobs.py:payment_maintenance`. PayPal 이벤트 상세 응답에는 전달 상태/시도별 HTTP 결과가 없어 웹훅 미도착의 원인을 확정하지 못했다. 이번 cron 적용이 웹훅 전송 경로를 수정한 것은 아니다.

## 적용한 범위

- `app/payment_recovery.py`: 기존 `reconcile_payments`에 선택 가능한 settlement_only 모드와 명시적 CLI를 추가했다. 기존 전체 결제 작업의 기본 동작은 유지했다.
- 대상은 같은 환경의 PAYPAL·CREATED/PENDING·paid_at 없음·주문 ID 있음이며, 캡처 요청 시각 또는 캡처 ID가 있는 건이다. 아직 캡처를 시도하지 않은 주문·CANCELED/FAILED·다른 환경은 제외한다.
- PG 조회 결과 캡처 COMPLETED가 확인된 경우만 기존 판매자/금액/주문/캡처/예약 검증과 `save_event → process_event`로 반영한다. 미완료·캡처 없음은 변경 없이 건너뛴다. 근거는 `verification_status=API_QUERY`이며 실제 서명 웹훅으로 기록하지 않는다.
- 이 cron은 추가 주문/캡처·PG 환불·예약 만료·FCM을 호출하지 않는다. 기존 업무 정책에 따른 내부 결제 알림함은 저장한다. 늦은/중복 캡처 등 기존 정산 정책에서 환불 필요를 기록할 수 있으나 이 CLI에서 환불 실행은 하지 않는다.
- 별도의 전체 `app.jobs payments`는 환불 재시도·미결제 만료·푸시까지 포함하므로 이번 스케줄에 등록하지 않았다. 기존 시스템의 다른 기능·채팅·Firebase 보안·데이터 구조는 변경하지 않았다.

## 서버 설치·운영 설정

| 항목 | 적용 결과 |
| --- | --- |
| 패키지 | Amazon Linux 저장소의 cronie·의존 cronie-anacron 1.5.7-1.amzn2023.0.2 설치 |
| cron 데몬 | crond.service enabled·active/running |
| 배포 원본 | `deployment/nadree-payment-recovery.cron` |
| 실제 등록 | `/etc/cron.d/nadree-payment-recovery`, root:root·0644 |
| 주기·사용자 | 매분·ec2-user·작업 디렉터리 `/srv/nadree-api` |
| 설정 | 기존 .env 읽기; 프로세스와 DB URL·환경·Client ID/Secret 일치 여부만 검사·모두 일치 |
| 실행 제한 | SANDBOX 및 RIDERLOG_V2_DATA_TEST를 명시적으로 검사; 설정 대상이 바뀌면 중단 |
| 중복 방지 | 로컬 flock + 기존 전체 결제 작업과 같은 MySQL named lock `nadree:job:payments` |
| 실행 시간 | timeout 180초; 다음 분 작업이 겹치면 flock으로 새 실행 차단 |
| 로그 | journald 식별자 `nadree-payment-recovery`, 실행 결과/환경/집계·고정 오류 코드만 기록 |
| API | 재시작 없음·기존 PID 326499 유지·공개 헬스 200 |
| 소스 기준 | 저장소 HEAD bd0df68fac30458108569efb6112a42e6e3b6eb9 위의 미커밋 변경; cron은 실행 시 최신 작업 트리 로드 |

실행 명령은 다음과 같다. 비밀값을 인수나 cron 파일에 넣지 않는다.

```sh
/srv/nadree-api/.venv/bin/python -m app.payment_recovery --settlement-only --expected-environment SANDBOX --expected-database RIDERLOG_V2_DATA_TEST
```

systemd의 전체 결제 타이머를 함께 등록하지 않고 cron 하나만 사용한다. crond의 기존/패키지 기본 설정은 보존했다. 새 잠금 디렉터리는 ec2-user 0700·파일 0600이며 상위 runtime 디렉터리는 접근 가능하도록 설정했다. 초기 설치 전 검사에서 상위 경로 접근 문제를 발견해 cron 등록 전에 보정했고, 실패 이력은 보존했다. App Check·API 인증 검사나 기존 보안 설정은 변경하지 않았다.

## 실제 검증 결과

| 검사 | 기대 | 실제 | 판정 |
| --- | --- | --- | --- |
| 대상·백업 | 승인된 테스트 데이터만 최초 처리 | 최초 후보 8번 한 건, Test DB/Sandbox·대상 지점/예약 일치, 0700/0600 백업 생성 | 통과 |
| 실행 계정 설정 읽기 | ec2-user가 기존 설정 사용 | Sandbox·테스트 DB·자격 설정 존재 모두 true | 통과 |
| cron 문법 | 유효한 설정 | root의 crontab -T 검사 통과 | 통과 |
| DB 중복 잠금 | 다른 작업이 보유하면 중단 | 실제 잠금 보유 상태의 CLI status=busy, DB 변경 없음 | 통과 |
| 로컬 중복 잠금 | 동시 프로세스 차단 | 잠금 보유 중 두 번째 flock exit 1 | 통과 |
| 02:46:42~02:46:44 등록 | 단일 cron·데몬 활성화 | 원본 일치·root 0644·enabled/active/running | 통과 |
| 02:47:03 첫 cron 자동 실행 | 미반영 결제 완료 반영 | checked=1·failed=0·skipped=0·status=completed | 통과 |
| 02:48~02:51 후속 자동 실행 4회 | 이미 완료된 결제 중복 처리 없음 | 모두 checked=0·failed=0·skipped=0·status=completed, 완료 알림 총 1건 유지 | 통과 |
| SQL·근거 | PAID 및 출처 보존 | 8번 PAID·paid_at 있음·API_QUERY/PROCESSED·내부 완료 알림 1건 | 통과 |
| 기존 데이터 | 다른 결제/예약·원래 식별자 보존 | 다른 결제 행·해당 예약 행·주문/캡처/판매자/금액·최초 요청 시각 불변 | 통과 |
| 외부 영향 | 새 청구·환불 없음 | refundStatus=NONE·환불 요청 없음, 새 주문/캡처/환불 호출 없음 | 통과 |
| 02:48:23~02:48:28 실제 고객 API | 결제 완료로 조회 | Firebase 인증·백엔드 로그인·상태·상세·진행 목록·로그아웃 모두 HTTP 200, PAID/DONE/canCapture=false | 통과 |
| 진행 목록 | 신규 8번 정상 유지 | totalCount=1, 대상 예약 결제 PAID | 통과 |

실제 결제 상태 응답 핵심 값:

```json
{
  "paymentId": 8,
  "paymentStatus": "PAID",
  "paypalOrderStatus": null,
  "nextAction": "DONE",
  "canCapture": false,
  "approvalUrl": null,
  "refundStatus": "NONE",
  "currency": "USD",
  "totalPrice": 90
}
```

PAID 조회의 paypalOrderStatus=null은 해당 상태 GET에서 PG 재조회를 하지 않은 결과다. 실제 PG 직접 조회에서는 COMPLETED를 확인했다. 프론트는 DONE/PAID에 따라 결제 완료로 표시하고 추가 capture나 새 order를 호출하지 않는다. 예약 승인·인계·렌탈 시작과 결제 완료는 별도 상태다.

## 격리 자동 회귀·남은 검증

관련 회귀 59개 통과 후 환경 고정 검사까지 추가한 최신 전체 회귀는 **398 passed·12 skipped·0 failed·0 errors, 95.54초**다. 이번에 정산 완료·재실행·미완료 보존·대상/환경 제외·명시적 CLI·안전한 로그·공유 잠금 등 12개를 추가했다. SQLite·모의 외부 서비스만 사용했고 공유 DB/PayPal은 pytest 대상으로 사용하지 않았다. 건너뜀은 별도 Firestore 4개·폐기 가능한 MySQL 8개다. 기존 의존성 경고 2개가 있다. 제한 환경의 최초 실행은 설정 접근/실행 환경 문제로 중단했고, 서버 설정을 제거한 /tmp에서 재실행한 위 결과를 최종으로 사용한다.

실제 서명 웹훅 수신·전달 누락 원인은 미검증이다. Live 결제·실기기 App Check·앱 화면·푸시·이번 cron의 자동 환불/예약 만료는 검증하지 않았으며 활성화하지 않았다. 미완료/실패/취소 결제 전체 복구와 환불 재시도 운영은 별도 범위다. 부모 지침이 참조하는 `/srv/rental-project-master.md`, `/srv/rental-api-review-decisions.md`는 서버에 없어 갱신하지 못했다.

## 운영 확인·중단 방법

```sh
sudo systemctl status crond.service --no-pager
sudo journalctl -t nadree-payment-recovery --since '2026-10-22 02:46:42 UTC' --no-pager
```

예상 로그는 job=payment-settlement-recovery·status=completed와 checked/failed/skipped 집계다. 환경/DB 검사 실패나 failed 증가 시 해당 설정/PG 진단을 확인한다. 정상일 때 완료된 결제는 다음 주기의 후보에서 제외된다. cron 중단이 필요하면 **이 작업의 `/etc/cron.d/nadree-payment-recovery` 파일만 cron 디렉터리 밖으로 보관**한다. 전체 crond나 다른 작업은 중단하지 않는다. 이미 PayPal 증거로 확정한 PAID를 이전 PENDING으로 수동 되돌리지 않는다. 현재 사용자에게 필요한 수동 설정 작업은 없으며, 프론트에서 8번의 상태를 다시 조회하면 된다.

근거 파일: `build/test-runtime/reservation-8-links-readonly-2026-10-22.json`, `payment-8-readonly-audit-2026-10-22.json`, `payment-recovery-scheduling-readonly-2026-10-22.json`, `payment-recovery-focused-2026-10-22.log/.xml`, `payment-recovery-full-2026-10-22.log/.xml`; 배포/백업/실제 검증은 `build/test-runtime/payment-recovery-deployment-2026-10-22/`의 prepare-result.json·before.private.json·install-result.json·verification-result.json·customer-api-verification-result.json에 있다. 비밀번호·토큰·비밀키·고객 UID는 결과 문서에 남기지 않았다.
