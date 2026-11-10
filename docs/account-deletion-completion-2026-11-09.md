# 개인정보 처리 완료와 로그·백업 보관 검토 분리

2026-11-09 사용자 후속 지시: 삭제와 개인정보 처리를 성공 상태까지 마무리하며, 보관 정책 확인을 먼저 완료해야 하는 종속 관계를 제거한다. 기준 커밋 `91d6be9` 위의 기존 로컬 수정과 첫 요청 일반 탈퇴·선택 메일 정책을 보존했다.

## 완료 조건

실제 업무 인계·렌탈 권한/세션/FCM/채팅 회수·SQL 개인정보 정리·채팅 익명화·관리자 채팅용 Auth 정리가 성공한 요청은 `requestState=COMPLETED`, `personalDataState=COMPLETED`, `nextAction=NONE`으로 완료한다. 다른 활성 서비스 관계 등 기존 확인 근거로 보존하는 정보가 있으면 기존 `COMPLETED_WITH_RETENTION`을 유지한다. 완료 범위는 `COMPANY_ACTIVE_SYSTEMS`다.

보관 정책 문서가 없거나, 만료됐거나, 조회/형식 확인에 실패해도 위 실제 처리가 성공했다면 완료를 막지 않는다. 별도 `retentionReview.state`와 공개 응답의 `residualCopies[].reviewState`에 PENDING/VERIFIED를 기록한다.

- VERIFIED: 확인된 기존 보관 기간으로 deleteBy를 고지한다.
- PENDING: 사용자 요청 기준 requestedMaxDays=30을 고지하며 확인되지 않은 deleteBy·정책 증거를 생성하지 않는다.
- 실제 공유 자료의 미정리 개인정보 발견, 권한·업무 조건 불충족, SQL/Firestore/Firebase 처리 오류는 기존 검사·추가 검토·재시도 대상으로 유지한다. 실행되지 않은 삭제를 성공으로 바꾸는 수정은 아니다.
- 완료 영수증에서 대상 관리자·연락처 암호문·단계별 개인 ID를 제거하고 기존 최소 영수증 30일 만료를 유지한다. 운영 inspect에서 개인 식별값 없는 보관 검토 요약을 확인할 수 있다.

## 이번에 보류한 인프라

앞서 사용자와 정한 로그 최대 30일·백업 최대 30일·추가 개인정보 보존 없음은 요청 기준이다. 이후 사용자가 나드리 로그만 분리하고 과거 공용 로그는 별도 확인, 정기 DB 백업 작업은 이번에 제외하도록 지정했으며, 다시 삭제 성공 처리 구현을 우선하도록 지시했다.

따라서 이번 작업에서 journal namespace·공용 journal·cron·로그/백업 정리 설정을 설치/변경하거나 백업 파일을 삭제하지 않았다. 정책 확인을 VERIFIED로 등록하지 않았다. 사전 조사는 읽기 전용이며, 감사 메타데이터는 접근 제한된 build/test-runtime/retention-audit-2026-11-09에 보관한다. 실제 보관 설정을 적용했다고 주장하지 않는다.

## 검증·반영 결과

**11:45 UTC 코드 반영·12:11 UTC 전체 시험 요청 마무리 완료.** 신규 탈퇴 요청이나 정책 강제 승인으로 상태를 꾸미지 않고 기존 배치의 정상 완료 경로를 사용했다.

| 검사 | 실제 결과 |
| --- | --- |
| 관련 격리 검사 | ec2-user, 개인정보 완료·첫 접수 탈퇴·메일·인계·권한·중복·OpenAPI 관련 8파일 **117 passed / 1 skipped**, 실패 0, 65.23초 |
| 건너뜀 | 별도 폐기용 MySQL 환경이 없는 실제 예약/대표 탈퇴 경합 1개. 가짜 연결 잠금 검사와 실제 경합을 구분 |
| 회귀 범위 | 정책 없음/만료/미검증/형식 오류/조회 오류에도 실제 개인정보 정리 완료, 확인된 기한 유지, 실제 공유 개인정보·Firebase 오류는 미완료/재시도 유지, 비밀값 미노출 |
| API 반영 | **11:45:50 UTC**, nadree-api 재시작, PID 1759894, active/running |
| 개인정보 배치 | 타이머 enabled/active 복구, 첫 배치 processed=3/deferred=0/completed=2/expiredReceipts=0 |
| 실제 HTTP | 로컬/공개 health/live·health/ready·Swagger·OpenAPI 모두 200. 완료+별도 보관 검토 예시 확인 |
| 오류·기존 작업 | API 시작 완료·API/배치 오류 레코드 0, 인수·채팅·결제 cron 상태 유지 |

```sh
sudo -n -u ec2-user env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  tests/test_retention_review_nonblocking.py tests/test_immediate_general_withdrawal.py \
  tests/test_deletion_notice_best_effort.py tests/test_account_deletions.py \
  tests/test_admin_rental_exit.py tests/test_admin_account_deletion.py \
  tests/test_privacy_admission_guards.py tests/test_foundation.py -q -p no:cacheprovider
```

### 실제 요청 결과

기존 SELF 2건은 **11:45:53 UTC**에 requestState=COMPLETED, personalDataState=COMPLETED, accessState=REVOKED, nextAction=NONE으로 정상 종결됐다. 완료 안내 메일도 각각 SMTP 성공 1건으로 기록됐다. 완료 영수증의 원본 관리자·연락처 암호문·스냅샷 제거와 공개 응답 모델 유효성을 확인했다.

확인 중 **10:26:24 UTC 접수된 별도 SUBTREE 1건**도 발견했다. 보관 정책이 아닌 SHARED_ASSET_AUDIT_REFERENCES/SHARED_SHOP_LOCATION_AND_CONTRACT_SNAPSHOTS 검토가 남아 있었다. 승인된 branch2 시험 지점 1개·관리자 2명 범위로 고정하고 다음 사실을 실제 조회해 검토 근거를 기록했다.

- 대상 관리자 모두 비활성·이름/이메일/전화/소속/FCM 익명화, 남은 역할 0, 채팅 정리 체크포인트 2개 완료.
- 공유 차량 생성 이력 6개는 익명화된 관리자 식별 행을 참조하며, 검사한 공유 사업장/자산 행에서 원래 관리자 이름·이메일·전화 문자열이 발견되지 않음.
- 기존 시험 지점의 사업장 정보와 생성 이력은 업무 기록으로 보존하며, SQL 변경·차량/예약/렌트/결제 수정은 0.
- 실제 조회와 분류 근거는 `build/test-runtime/branch2-shared-data-review-20261109T121028Z/`의 0700 디렉터리·0600 파일에 보관. 개인정보 원문은 보고서/출력에 남기지 않음.

검토 기록 후 기존 서비스로 정상 후속 처리하여 SUBTREE도 **12:11:29 UTC**에 COMPLETED/personalDataState=COMPLETED/REVOKED/NONE으로 종결됐다. 배치 12:11:40 종료 코드 0, API와 타이머 정상이다. **최종 요청 3건 중 완료 3건·대기 0건**을 실제 조회로 확인했다. 모든 완료 영수증은 민감 워크플로 필드가 제거됐고 공개 응답 모델 검증도 통과했다.

로그·백업 보관 검토는 세 건 모두 별도 PENDING이며 확정 deleteBy를 만들지 않았다. 보관 설정 설치·기존 로그/백업 삭제·정책 VERIFIED 등록은 하지 않았다. 이는 활성 시스템 개인정보 완료와 분리한 결과이며 실제 보관 통제가 완료됐다는 의미가 아니다.
