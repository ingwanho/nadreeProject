# 관리자 본인 요청 탈퇴·하위 지점 삭제

2026-11-05 사용자 확정 사항을 반영한 로컬 구현이다. **실제 서버 적용·실제 계정/지점 삭제는 수행하지 않았다.** 기존 서버 배포 결과는 당시 적용 이력이며 이 API 배포 증거가 아니다.

**후속 서버 반영 완료: 2026-11-05 11:16 UTC.** 위 문단은 전달서 작성 당시 상태다. 이후 `f8b73b1`을 반영하고 격리 관련 16개·전체 604개 통과 후 API를 재시작했다. 실제 OpenAPI의 DELETE 경로·76개 경로와 헬스 정상 확인을 완료했다. 실제 계정/지점 삭제 요청은 실행하지 않았으며, 실제 적용·미검증은 [서버 결과](admin-account-deletion-server-result-2026-11-05.md)에서 구분한다.

## 요청과 삭제 범위

```http
DELETE /nadreego/admin/account
Authorization: Bearer <관리자 accessToken>
```

요청 본문과 대상 ID는 없다. 서버가 현재 DB의 관리자 역할·직접 소속 지점으로 범위를 결정한다. 요청의 adminId·spotMasterId·scope로 다른 대상을 선택할 수 없다. 기존 유효 세션·활성 지점·계약·직접 manage 권한 검사를 적용한다.

| 요청자 | 관리자 탈퇴 | 지점 삭제 |
| --- | --- | --- |
| 일반관리자 | 본인만 | 없음 |
| 대표관리자 | **대표 본인 + 본인 지점과 모든 하위 지점의 렌탈 관리자 전원** | **본인 지점 + 모든 하위 지점** |

계층은 동일 contract_id·org_id와 unit_code의 `-` 구간 경계로 판정한다. 상위·형제·다른 회사/계약 지점은 제외한다. ORG01 하위 판정에 ORG010은 포함하지 않는다. 하위 지점 대표관리자도 탈퇴 대상이다. 기존 렌탈 역할이 남은 비활성·역할 만료 관리자도 정리하며, 렌탈 역할이 없는 웹 전용 계정·가입 대기 기록은 보존한다.

## 저장 처리와 실패

- 대상 관리자의 rental_primary_admin/rental_manager 역할을 제거하고, 본 API 서비스의 access/refresh 세션과 채팅 접근을 회수하며 FCM 토큰을 제거한다.
- 지점은 **논리 삭제**한다. MSP_SPOT_MASTER와 해당 계층의 기존 MSP_ORG/MSP_REGION/MSP_LOCAL/MSP_SPOT 행에 is_active=0을 적용한다. 하위 지점 삭제 시 상위 계층의 정상 행은 유지한다.
- 공유 MSP_ADMIN 식별 행·다른 서비스 역할/세션·공유 소속 scope, 지점 정보·가입 코드 이력·예약·계약·차량·QR·결제 이력은 보존한다. 신규 가입·지점 생성·예약 등 활성 지점을 요구하는 경로에서는 삭제 지점을 차단한다.
- 진행 중 예약을 임의 취소하거나 결제·환불·차량 반납을 실행하지 않는다. 기존 고객의 본인 예약 이력 조회는 유지한다. 대표 탈퇴 후 해당 계정들로 지점 업무를 계속할 수 없다는 점을 앱에서 안내한다.

관리자·지점 DB 변경은 하나의 트랜잭션이다. 지점/계정 잠금으로 가입 승인·대표 양도·로그인·refresh·채팅 세션 발급과 직렬화하며, 하위 생성이 잠금 대기 중 끝났을 수 있어 잠근 계층을 다시 조회한다. 채팅 회수 실패 시 503 CHAT_SYNC_FAILED로 DB 변경을 롤백한다. 외부 채팅에서 이미 회수된 일부 세션은 DB 롤백으로 복원하지 않으며 재로그인/채팅 세션 재발급이 필요할 수 있다.

## 응답과 앱 처리

일반관리자 성공:

```json
{
  "status": "success",
  "deleted": true,
  "scope": "SELF",
  "spotMasterId": "<본인-지점-ID>",
  "deletedAdminCount": 1,
  "deletedSpotCount": 0
}
```

대표 성공 예시 — 본인 지점·하위 지점 1개와 소속 관리자 총 4명:

```json
{
  "status": "success",
  "deleted": true,
  "scope": "SUBTREE",
  "spotMasterId": "<본인-지점-ID>",
  "deletedAdminCount": 4,
  "deletedSpotCount": 2
}
```

deletedAdminCount는 렌탈 탈퇴 대상 수, deletedSpotCount는 논리 삭제 대상 계층의 지점 수다. 이미 비활성인 하위 지점도 대상 수에 포함될 수 있다. HTTP 200 이후 앱은 저장한 access/refresh 및 채팅 인증 정보를 폐기하고 로그인 화면으로 이동한다. 대표 요청 화면에는 본인과 하위 지점의 관리자 전원·지점이 함께 삭제된다고 명시한다. 성공 후 동일 토큰 재호출은 401이다. 응답 유실 시 401만으로 삭제 결과를 확정하거나 자동 재로그인/재삭제하지 않는다.

401 AUTH_REQUIRED는 만료/폐기 세션, 403은 역할·직접 소속·지점/계약 제한, 503 CHAT_SYNC_FAILED는 채팅 회수 실패다. Swagger에 SELF/SUBTREE 성공과 주요 오류 예시를 반영했다.

기존 `POST /nadreego/shop/adminDelete`는 대표가 같은 지점 일반관리자 한 명을 지정해 제거하는 API로 유지한다. 그 API의 대표 삭제 제한은 그대로이며 이번 API의 대표 본인 요청은 권한 양도 없이 계층 전체를 삭제한다.

## 서버 적용과 검증

추가 테이블·컬럼·마이그레이션·env·Firebase 배포는 없다. 변경 코드를 commit/push한 뒤 서버의 로컬 변경을 보존하며 `git pull --ff-only origin main`하고 기존 nadree-api.service를 재시작한다. Swagger/OpenAPI에 `DELETE /nadreego/admin/account`, health 제외 **76개 경로**가 있는지 확인한다. 문서 추가만으로 서버에 적용되지는 않는다.

실제 관리자나 지점을 헬스 확인 목적으로 삭제하지 않는다. 삭제 시험은 격리 DB 또는 명시적으로 승인된 폐기 가능한 테스트 계층에서 수행한다. 운영 계층 복구는 이번 API에 포함하지 않으며 역할·세션·지점 활성 상태를 함께 확인하는 별도 작업이다.

로컬 추가 테스트 **16개 통과**. 일반 본인 한정, 대표 본인 포함·다단계 하위 삭제, 상위/형제/계약/회사 경계, 구 spot_id 유무의 공유 계층 호환, 권한 양도 후 현재 역할, 세션/로그인/채팅 차단, 신규 가입/예약 차단·기존 이력 보존, 채팅 장애·중간 DB 오류의 롤백, Swagger 예시를 검증했다.

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider --tb=short
604 passed, 15 skipped, 14 warnings
```

SQLite와 FastAPI TestClient 기반의 격리 전체 회귀이며 실제 공유 DB나 Firebase로 삭제 요청을 보내지 않았다. 건너뜀 15개는 전용 MySQL 11개와 Firestore 에뮬레이터 4개다. 기존 라이브러리·테스트 대역 경고 14개는 실패와 구분한다. 새 API의 실제 MySQL 잠금 경합·Firebase 연동·서버 배포와 앱 화면은 별도 검증 대상이다. OpenAPI 76개 경로·새 API의 성공/오류 예시 5개·API 엑셀 신규/통합 시트도 확인했다.
