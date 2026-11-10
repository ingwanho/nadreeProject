# 관리자 탈퇴: 미완료 업무 차단·대표 인계

2026-11-09 사용자 최종 확정 정책. **2026-11-08 17:03 UTC / 발리 11월 9일 01:03 서버 적용 완료**다. `9a77b7e → 05f5e12` ff-only pull 후 완료 판정 1줄 보완·관련 격리 검사·API 재시작과 기존 개인정보 일정 복구를 마쳤다. DB/env/Firebase 변경·실제 계정 탈퇴는 없다. [최신 서버 결과·검사·테스트 지점 현황](admin-withdrawal-server-result-2026-11-09.md)을 우선한다. 아래 명령은 적용 절차 참조이며 이번 적용은 완료됐다.

## 확정 정책

| 대상 | 삭제 조건·미완료 업무 처리 |
| --- | --- |
| 대표관리자 | 본인 지점과 모든 깊이 하위 지점의 미완료 예약·대여·반납·차량 회수·환불·외부 정산이 없어야 실제 탈퇴/지점 논리 삭제 가능 |
| 일반관리자 | 본인이 승인한 미완료 예약·렌트를 같은 지점 대표에게 인계한 뒤 본인만 탈퇴 |
| 일반관리자의 업무 데이터 | 예약·계약·차량·고객·결제 행과 상태/배정/금액/시각은 보존. 자동 취소·강제 종료·환불 없음 |

앞서 검토했던 강제 취소/강제 종료 처리는 제거했다. 이번 변경으로 실제 예약을 취소하거나 `actual_end_time`을 기록하지 않는다. 일반관리자 본인의 역할/세션/채팅·FCM 회수와, 개인정보 요청 경로에서의 본인 정보 정리는 기존 계약대로 별도로 진행한다. 다른 직원·고객의 업무 데이터 삭제와 구분한다.

## API·상태

- `DELETE /nadreego/admin/account`: 일반은 인계 후 기존 200·deleted=true. 대표는 전체 하위 범위를 SQL 잠금 아래 확인하며 미완료가 있으면 **409 `DELETION_OBLIGATIONS_REMAIN`**, `nextAction=SETTLE_OUTSTANDING_WORK`로 거절한다. 계정·세션·지점과 업무 상태를 그대로 둔다. 미완료 건수는 기존 context API로 확인한다.
- `POST /nadreego/admin/account-deletion-requests`: 202 계약을 유지한다. 대표 미완료 시 `WAITING_OBLIGATIONS/LIMITED_TO_SETTLEMENT`로 접수만 보존하고 실제 삭제는 하지 않는다. 업무 정리 후 같은 요청을 배치가 최종 재검사한다. **11월 9일 후속 변경: 일반은 첫 정상 접수에서 업무 인계와 본인 접근 회수까지 완료하고 REVOKED를 반환한다. 개인정보 정리는 재요청 없이 기존 배치가 이어간다.** 동일 키·영수증·본문의 재전송은 조회만 수행한다. [후속 구현·검사·실제 반영](general-deletion-first-request-2026-11-09.md).
- `POST /nadreego/shop/adminDelete`: 대표가 일반관리자를 지정 제거하는 기존 경로에도 동일한 업무 인계를 적용한다.
- 인계 대상이 있는데 같은 지점의 활성 대표/manage 권한을 정확히 하나로 확인하지 못하면 **409 `PRIMARY_ADMIN_REQUIRED_FOR_HANDOVER`**로 즉시 탈퇴를 막는다. 비동기 요청은 기존 단계별 재시도·운영 확인 경로로 남아 업무를 잃지 않는다. 대표를 지정하고 복구한 후 진행한다.

예정 반납일 경과나 상태 문자열만으로 반납 완료라고 보지 않는다. 기존 실제 종료 시각·미인수 차량 보호·환불 목표/상태·정산 확인 조건을 유지한다. 실제 업무 검사와 역할 회수는 같은 지점 잠금/SQL 트랜잭션에서 수행한다. 기존 Firestore 중복·범위 중첩·재확인·7일 기한·완료 영수증 30일 보관 정책은 유지한다.

## 인계 기록과 대표 화면

현재 별도 담당자 컬럼이 없으므로 해당 지점의 기존 예약 승인 이력 `MSP_RESERVATION_HISTORY`의 APPROVED 처리자를 기준으로 본인 승인 건을 식별한다. 이후 MANAGER_TRANSFERRED 이력이 있으면 그 수신자가 현재 담당자다. 차량을 인계한 직원이 달라도 최초/최종 승인 담당을 임의로 바꾸지 않는다. 미승인 공통 신청·다른 직원 승인 건·이미 반납 완료된 건은 건드리지 않는다. 과거 데이터에 승인자가 없으면 추정해서 배정하지 않는다.

인계 시 기존 테이블에만 다음을 추가한다.

| 위치 | 내용 |
| --- | --- |
| `MSP_RESERVATION_HISTORY` | `event_type=MANAGER_TRANSFERRED`, 변경 전후 상태·차량·배정 동일, changed_by는 인계받은 대표 |
| `MSP_RENTAL_CONTRACT_HISTORY` | 연결된 미완료 계약의 `MANAGER_TRANSFERRED`, 변경 전후 계약 상태 동일, 대표 참조 |
| `MSP_RENTAL_NOTIFICATION` | `eventType=RESERVATION_MANAGER_TRANSFERRED`, targetType=RESERVATION, targetId=예약 ID |

대표는 기존 `GET /nadreego/notifications?shopId=...`로 인계 알림을 확인하고 targetId로 기존 예약/렌트 상세를 열어 계속 처리한다. 메시지는 “담당 관리자의 탈퇴로 대표관리자에게 업무가 인계되었습니다.”다. 기존 지점 공용 알림 권한을 유지하므로 대표 전용 비공개 알림함이나 새 FCM 푸시 계약을 추가하지 않는다.

인계 후 최신 이력의 담당자가 대표가 되어 재시도해도 같은 일반관리자의 건을 다시 인계하지 않는다. SQL 또는 채팅 회수 단계가 실패하면 기존 트랜잭션/재시도 계약을 따른다. 인계 이력 추가만 먼저 확정하고 탈퇴를 실패시키는 별도 커밋은 없다.

## DB·서버 적용

새 테이블·컬럼·인덱스·env·Firebase 배포·타이머 변경이 없다. 11월 6일 적용한 포인터 컬럼을 재사용한다. 기존 데이터의 일괄 담당자 변경·취소나 마이그레이션도 실행하지 않는다.

변경을 Git에 반영한 뒤 서버에서 아래 순서로 적용한다. 미완료 실제 운영 계정을 삭제하는 시험은 하지 않는다.

```sh
cd /srv/nadree-api
git pull --ff-only origin main
sudo -u ec2-user -H bash
cd /srv/nadree-api
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_admin_rental_exit.py tests/test_admin_account_deletion.py tests/test_account_deletions.py tests/test_privacy_admission_guards.py tests/test_management.py -q
exit
sudo systemctl restart nadree-api
curl -fsS http://127.0.0.1:8008/health/ready
```

개인정보 배치가 실행 중이면 완료를 확인하고 새 코드로 재실행되도록 반영한다. 기존 5분 일정과 결제/인수/채팅 작업을 보존한다. 이 변경 때문에 보관 정책을 임의 승인하거나 기존 요청 문서/지점 차단 표시를 지우지 않는다. 문제 시 새 개인정보 배치를 중지하고 인계 이력과 탈퇴 상태를 대조한 뒤 복구한다.

## 검증 범위

문서 작성 당시 로컬 통합 관련 검사 **109 passed / 1 skipped**, 이후 특화 검사 **8 passed**다. 서버에서는 ec2-user의 사용자 지정 6파일 **110 passed / 1 skipped**, 실제 반납 시각 보완 후 인계 파일 **17 passed**를 확인했다(기존 8개 중복). 일반 탈퇴 3경로 × RETURNED+종료시각 없음 / ON_RENT+종료시각 있음 / RETURNED+종료시각 있음의 9개 회귀를 추가했다. 반환 상태와 실제 종료 시각을 모두 확인해야 완료로 분류한다. 건너뜀은 전용 MySQL 동시성이며 실서비스 경합 통과를 뜻하지 않는다. 기존 경고 2개는 남아 있다. 사용자 지시에 따라 관련 범위만 실행했으며 [서버 결과](admin-withdrawal-server-result-2026-11-09.md)에 두 실행을 구분했다.

로컬 관련 검사에서는 일반의 기존 승인 예약·진행 계약·실결제·차량·지점 상태 보존, 대표에게 인계된 이력/지점 알림, 다른 직원/미승인 건 보존, 대표 미확인 시 원상 유지, 하위 지점 진행·연체·가짜 반납 완료에 대한 대표 삭제 차단을 확인한다. 실제 MySQL 경합·실제 SMTP/Auth·앱 공동 인수는 서버에서 별도 검증해야 한다. 실제 운영 계정·예약·결제·Firebase에는 쓰기하지 않았다.
