# 관리자 앱 전달: 탈퇴·개인정보 삭제 요청

2026-11-06. **08:16 UTC 서버 반영·5분 자동 처리 활성화 완료**, 실제 OpenAPI 78개 경로·여권 PUT/GET 404를 확인했다. **실제 탈퇴·메일/Auth 삭제·앱 공동 인수는 별도 미검증**이다. 이전 관리자 DELETE 전달서 이후 추가된 계약과 여권 API 등록 중단을 포함한다. [서버 실제 결과](admin-privacy-server-result-2026-11-06.md), [필드별 처리](admin-privacy-server-apply-2026-11-06.md)를 함께 참고한다.

## 대상과 화면

한 번 확인하여 요청하면 렌탈 탈퇴와 NadreeGo 개인정보 정리까지 같은 요청번호로 추적한다. 접수·접근 회수·개인정보 처리 완료를 구분한다. 접수 후 별도의 개인정보 삭제 이메일을 필수로 요구하지 않는다.

일반은 본인만, 대표는 **본인 및 직접 지점과 모든 깊이 하위 지점의 대표·일반 관리자 전체**가 대상이다. 상위·형제·다른 회사/계약·고객 계정·직원의 별도 서비스 계정은 포함하지 않는다. 앱에서 대상 ID·scope를 선택하지 않는다.

대표에게 미완료 업무가 있어도 접수할 수 있다. `WAITING_OBLIGATIONS`에서는 제한 상태와 남은 업무를 표시하고 기존 반납/회수/예약 취소·거절을 처리하게 둔다. 새 예약 승인·인계·직원 가입·하위 생성 등은 차단된다. 현장 결제를 자동 환불하지 않는다. 업무 정리 후 새 요청 없이 자동 재평가한다.

## 호출 계약

| 순서 | 메서드·경로 | 인증·입력 |
| --- | --- | --- |
| 범위 확인 | `GET /nadreego/admin/account-deletion-context` | 기존 관리자 Bearer, 본문 없음 |
| 접수 | `POST /nadreego/admin/account-deletion-requests` | Bearer, `Idempotency-Key`, `Deletion-Receipt-Token`, 확인 본문 |
| 진행 조회 | `GET /nadreego/admin/account-deletion-requests/status` | `Authorization: DeletionReceipt <비밀값>` + 원래 `Idempotency-Key` |
| 범위 변경 시 재확인 | `POST /nadreego/admin/account-deletion-requests/{deletion_id}/reconfirm` | 현재 Bearer, 같은 영수증 헤더, 새 확인 본문 |

범위 확인의 `confirmationToken`은 10분 유효하며 사용자·역할·소속·하위 범위에 묶인다. `directShopName/scope/affectedAdminCount/affectedShopCount/outstandingWork`를 표시한다. `canExecuteWithdrawal=false`여도 `canSubmitRequest=true`면 접수 가능하다. 업무 카운터는 겹칠 수 있어 합계를 고유 예약 건수로 표시하지 않는다. `pendingExternalSettlements`는 현장 결제 등 담당자 정산 확인이 필요한 건수다.

앱은 **전송 전** 다음을 안전한 저장소에 보관한다.

- Idempotency-Key: UUID 등 `[A-Za-z0-9_-]` 16~64자.
- 영수증: 암호학적 난수 최소 32바이트를 base64url 등으로 표현한 `[A-Za-z0-9_-]` 43~128자. FCM 토큰/UID/이메일을 재사용하지 않는다.
- 최초 전송 본문: 응답 유실 시 같은 키에 확인 토큰을 새로 바꿔 보내지 않도록 유지한다.

```http
POST /nadreego/admin/account-deletion-requests
Authorization: Bearer <admin-access-token>
Idempotency-Key: <전송 전 보관한 UUID>
Deletion-Receipt-Token: <전송 전 보관한 비밀값>
Content-Type: application/json

{"confirmationToken":"<범위 조회에서 받은 토큰>","confirmed":true}
```

접수 성공은 **202**, `requestAccepted=true`다. 응답은 `requestId`, `requestState`, `scope`, `receivedAt`, `identityVerifiedAt`, `eligibleAt`, `processingDueAt`, `completedAt`, `accessState`, `personalDataState`, 업무 카운터·대상 건수·`nextAction`, 보관 고지를 포함한다. `deleted=true`는 반환하지 않는다. Swagger에 상태별 실제 형식의 예시를 반영했다.

일반 접수 예시는 `PROCESSING/PENDING/NOT_STARTED`다. 배치가 회수하므로 접수 응답만 보고 서버 권한이 이미 회수됐다고 표시하지 않는다. 이후 `accessState=REVOKED`, `personalDataState=IN_PROGRESS`를 거쳐 실제 정리·검토·완료 안내 후에만 `COMPLETED`가 된다.

대표 업무 대기는 `WAITING_OBLIGATIONS/LIMITED_TO_SETTLEMENT/NOT_STARTED`, `eligibleAt/processingDueAt=null`, `nextAction=SETTLE_OUTSTANDING_WORK`다. 남은 업무가 있을 때 일반 인증까지 먼저 지워 업무 처리를 막지 않는다.

## 상태와 기한

| requestState | 앱 안내 |
| --- | --- |
| `WAITING_OBLIGATIONS` | 접수됨. 대표 범위 전체의 업무 정리 필요 |
| `WAITING_RECONFIRMATION` | 자동 확대 중단. 최신 범위 조회 후 같은 요청번호에 재확인 |
| `PROCESSING` | 접수됨·처리 중. 별도 DELETE 금지 |
| `RETRYING` | 서버 재시도 중. 새 요청번호로 다시 접수하지 않음 |
| `ACTION_REQUIRED` | 같은 요청을 담당자가 확인 중. `nextAction`에 맞는 안내 |
| `COMPLETED` | 회사 활성 시스템의 대상 정보 정리 완료 |
| `COMPLETED_WITH_RETENTION` | 정리 완료. 남는 항목·목적·근거·기간 함께 표시 |
| `WAITING_VERIFICATION` | 예약된 상태. 현재 유효 Bearer 접수는 추가 이메일 없이 본인 확인 완료로 접수 |

일시는 UTC 절대 시각이다. 일반은 인증 접수 후 7일, 대표는 인증과 업무 정리 완료 후 7일이다. 7일 뒤 처리를 시작한다는 뜻이 아니다. 재시도/재확인/수동 재개로 기존 기한을 연장하지 않는다.

완료 범위는 `completionScope=COMPANY_ACTIVE_SYSTEMS`다. `retainedData`의 항목·필드·목적·보관 기준·기간·사유를 고지한다. `residualCopies`의 회사 로그/제한 백업 일정과 실제 관리자 채팅 Auth 삭제가 있었을 때의 공급자 안내를 구분한다. 공급자의 모든 잔여 사본까지 즉시 소거됐다고 표시하지 않는다. 개인 기기의 여권 사진 원격 삭제 완료도 표시하지 않는다.

## 응답 유실·로그아웃·복구

영수증은 해당 요청의 최소 진행 조회만 허용한다. 일반 로그인·업무 API·삭제 범위 변경 권한은 없다. URL/query/알림/분석 이벤트/콘솔/HTTP 디버그 로그에 넣지 않는다. 로그아웃할 때 access/refresh·채팅 인증은 정리하되 영수증과 요청 키는 별도 보존한다.

POST 응답을 잃으면 같은 키/영수증으로 조회한다. 원래 본문·키·영수증 그대로 재전송하면 기존 요청을 반환하며, 접근 토큰이 회수된 뒤에도 유효한 동일 요청 재생은 읽기만 수행한다. 다른 본문에 같은 키면 `409 IDEMPOTENCY_KEY_REUSED`, 다른 키의 진행 요청이 있으면 `409 DELETION_REQUEST_ALREADY_ACTIVE`다. context의 `activeRequestId` 또는 본인 확인된 운영 조회로 연결한다.

조회 404는 미존재·권한/영수증 오류·만료를 구분하지 않으며 **미접수 확정 근거가 아니다**. 401/503/통신 오류로 완료 표시하거나 구형 DELETE로 우회하지 않는다. 429는 `Retry-After: 60`을 따른다. 범위 불일치 409는 `requestAccepted=false/nextAction=RELOAD_AND_RECONFIRM`, 저장 결과 불명 503은 `DELETION_OUTCOME_UNKNOWN`이며 같은 영수증으로 확인한다.

`409 DELETION_SCOPE_IN_PROGRESS`는 포함 대상이 다른 진행 요청과 겹친다는 뜻이다. 일반 SELF와 대표 SUBTREE, 상하위 대표 요청 모두 적용되며 기존 DELETE로 우회하지 않는다. 다른 요청자의 영수증/상태에 접근하지 말고 본인 요청 조회 또는 운영자 안내를 사용한다. 서로 무관한 SELF 요청은 계속 허용한다.

영수증과 최소 기록은 **완료 후 30일** 유지한다. 진행/실패 요청은 기간 때문에 버리지 않는다. 완료 작업 기록에서 원본 이름·이메일·대상 목록·연락처 암호문을 제거한다.

앱 삭제/기기 분실 시 등록 이메일의 안전한 본인 확인 후 운영자가 같은 요청을 조회하고 영수증을 회전할 수 있다. 새 가입/개인정보 삭제 재접수를 강제하지 않는다. 원래 요청 키까지 잃으면 운영자 조회로 안내한다. 이메일 최초 접수도 동일 작업에 등록하며 공개 이메일 삭제 API는 없다.

범위 재확인은 context를 다시 받아 변경 건수를 보여준 다음 새 토큰을 같은 요청의 `/reconfirm`에 전송한다. 원래 접수 시각/기한은 유지한다. 영수증만으로 새 범위에 동의할 수 없다. 재확인 응답을 잃은 경우 동일 본문/영수증 재생은 조회만 수행한다.

## 호환성·여권·시험

기존 `DELETE /nadreego/admin/account`는 200·`deleted=true`의 렌탈 탈퇴만 의미한다. 개인정보 요청으로 몰래 확대하지 않는다. 새 흐름 진행 중에는 기존 삭제/직원 제거/대표 양도 경로로 우회하지 못한다. 고객 본인 탈퇴 API는 별개다.

여권 `PUT /nadreego/rent/passport`, `GET /nadreego/rent/passport/{booked_no}`는 등록 부분을 주석 처리하여 **호출·Swagger에서 제외**했다. 업로드 성공 예시는 사용하지 않는다. 기존 파일/필드는 이번에 삭제하지 않았다.

서버 적용 후 폐기 가능한 계층에서 일반 접수→로그아웃 조회→완료, 대표 하위 경계 보존, 업무 대기/반납·회수·거절, 범위 재확인, 중복/응답 유실/영수증 분실, 외부 장애 재시도를 공동 확인한다. 운영 공용 대표/업무 데이터를 삭제하지 않는다. 실제 MySQL 경합·SMTP/Auth·앱·백업 복원은 추가 실연동 검증 항목이다.
