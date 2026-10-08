# 나드리 프론트엔드 수정사항 인수서

최종 수정일: 2026-10-08

이번 백엔드 변경 중 프론트엔드 동작에 영향을 주는 내용만 정리한 문서입니다. 기존 전체 API 계약은 [`nadree-frontend-handoff.md`](nadree-frontend-handoff.md)를 기준으로 합니다.

## 1. 운영 정보

| 항목 | 값 |
|---|---|
| 운영 주소 | `https://na-dree.com` |
| Swagger | `https://na-dree.com/docs` |
| OpenAPI JSON | `https://na-dree.com/openapi.json` |
| 고객 API prefix | `/api/v1/nadree` |
| 관리자 API prefix | `/nadreego` |

운영 Swagger에서 다음 여권 경로가 노출되는지 확인했습니다.

- `PUT /nadreego/rent/passport`
- `GET /nadreego/rent/passport/{booked_no}`

웹 프론트 호출용 CORS는 운영 `.env`의 `NADREE_CORS_ORIGINS`로 설정합니다. 현재 리뷰 기준 Origin은 다음 값입니다.

```env
NADREE_CORS_ORIGINS=https://www.riderlog-lte.com:50045
```

Origin에는 끝의 `/`, `/*`, 경로, 해시를 포함하지 않습니다. 프론트 배포 주소가 바뀌면 정확한 `scheme://host:port` 값을 백엔드에 전달해야 합니다. 네이티브 모바일 앱의 직접 API 호출에는 CORS가 필요하지 않습니다. 현재 설정은 쿠키를 사용하지 않는 `credentials: omit` 기준입니다.

## 2. 변경사항 요약

| 영역 | 변경 내용 | 프론트 처리 |
|---|---|---|
| 관리자 세션 | 계정당 활성 관리자 세션을 1개만 유지. 새 로그인 시 이전 세션 폐기 | 이전 기기의 토큰 만료를 정상 처리하고 재로그인 유도 |
| 관리자·고객 로그아웃 | `X-FCM-Token`이 저장값과 일치할 때만 현재 FCM 토큰 삭제 | 로그아웃 시 현재 기기의 FCM 토큰을 함께 전송 |
| 관리자 FCM | 예약·결제 알림은 대상 지점에 직접 연결된 관리자에게만 발송 | 하위 지점 전체 수신을 전제로 하지 않음 |
| 고객 프로필 | 최신 프로필 조회 API 추가 | 앱 시작·프로필 화면에서 GET 호출 가능 |
| 대여 기간 | 가용성 조회·예약 요청 최대 기간 42일에서 30일로 변경 | 시작일~반납일을 1~30일로 검증 |
| 결제 마감 | 관리자 승인 시각부터 72시간 이내에만 PayPal 주문·캡처 가능 | `paymentDeadline`, `canPay`, `cannotPayReason`으로 버튼 상태 제어 |
| 환불 정책 | 고객은 렌트일 전까지 취소 가능하며 결제금액의 90% 환불. 렌트 당일부터 고객 취소 불가. 인계 전 관리자 취소는 100% 환불 | `refundRequestedAmount`와 `refundStatus` 표시. 당일 고객 취소 버튼 비활성화 |
| 회원 탈퇴 | 예약·결제 상태와 관계없이 탈퇴 가능. 렌탈 이력은 보존하고 개인정보·세션 폐기 | `DELETE /api/v1/nadree/user/account` 호출 후 토큰 삭제 |
| 결제 응답 | `refundStatus`, `refundedAmount`, `refundRequestedAmount`를 응답 최상위에 제공 | `payment.*`보다 최상위 필드 우선 사용 |
| 관리자 여권 | 마스킹된 이미지 업로드·활성 렌탈 중 조회 API 추가 | 아래 여권 연동 규칙 적용 |

## 3. 고객 프로필 조회

```http
GET /api/v1/nadree/user/profile
Authorization: Bearer <nadree-access-token>
```

응답:

```json
{
  "status": "success",
  "user": {
    "uidToken": "firebase-user-uid",
    "name": "Nadree Test Customer",
    "age": 30,
    "gender": "M",
    "nationality": "KR"
  }
}
```

## 4. 대여 기간·결제 응답

가용성 조회와 예약 요청의 `returnDate`는 `startDate`보다 늦어야 하며 최대 30일 범위입니다. 프론트에서 30일을 초과하는 선택을 막고, 최종 금액은 서버 응답의 `price`를 사용합니다.

결제 상태 조회·결제 캡처 응답에서 환불 관련 필드는 다음처럼 최상위에서 읽습니다.

```json
{
  "status": "success",
  "paymentId": 2,
  "paymentStatus": "PAID",
  "refundStatus": "NONE",
  "refundedAmount": 0,
  "refundRequestedAmount": null,
  "paymentDeadline": "2026-10-04T10:00:00+08:00",
  "canPay": false,
  "cannotPayReason": "PAYMENT_ALREADY_COMPLETED",
  "totalPrice": 200,
  "serverTotalPrice": 200,
  "currency": "USD"
}
```

환불 화면은 `refundStatus`를 기준으로 상태를 전환하고, 예정 환불액은 `refundRequestedAmount`, 실제 반영액은 `refundedAmount`를 표시합니다. 고객 취소는 총액의 90%, 관리자 취소는 100%가 목표 환불액입니다. 업무 시간대(기본 Asia/Makassar) 기준 렌트 시작일 00:00부터 고객 취소는 `CUSTOMER_CANCELLATION_DEADLINE_PASSED`로 차단됩니다. 서버가 반환한 `paymentStatus`·`refundStatus` 외의 상태를 프론트에서 임의로 만들지 않습니다.

결제 마감은 승인 이력의 `APPROVED` 시각부터 정확히 72시간입니다. 마감 후 주문·캡처 요청은 `409 PAYMENT_DEADLINE_EXPIRED`로 거절됩니다.

## 5. 회원 탈퇴

```http
DELETE /api/v1/nadree/user/account
Authorization: Bearer <nadree-access-token>
```

진행 중 예약·결제 여부와 관계없이 성공합니다. 서버는 렌탈 이력 보존을 위해 사용자 식별 행과 예약·결제 이력은 유지하고, 프로필·FCM 토큰·고객 access/refresh 세션을 폐기합니다. 운영 Firebase 설정이 있으면 같은 `NADREE_FCM_*` 프로젝트의 Firebase Authentication 계정도 삭제합니다. 성공 후 앱은 저장한 access/refresh token을 즉시 삭제합니다.

## 6. 관리자 로그인·로그아웃

### 5.1 단일 활성 세션

관리자 계정은 한 번에 하나의 활성 세션만 사용할 수 있습니다. 같은 계정으로 새 로그인하면 이전 access token과 refresh token이 폐기됩니다.

이전 기기에서 `401 INVALID_REFRESH_TOKEN` 또는 이에 준하는 인증 실패가 발생하면 저장된 토큰을 삭제하고 재로그인 화면으로 이동합니다.

### 5.2 로그아웃 FCM 헤더

```http
GET /nadreego/admin/logout
Authorization: Bearer <admin-access-token>
X-Refresh-Token: <admin-refresh-token>
X-FCM-Token: <current-device-fcm-token>
```

고객 로그아웃도 같은 방식으로 `X-FCM-Token`을 선택적으로 보냅니다.

- 현재 기기 FCM 토큰과 저장값이 일치하면 FCM 토큰을 삭제합니다.
- 헤더를 생략하거나 다른 토큰을 보내면 세션만 로그아웃하고 저장된 최신 FCM 토큰은 유지합니다.
- 로그아웃 후 access token과 refresh token은 프론트 저장소에서 삭제합니다.

## 7. 관리자 여권 이미지 API

여권 API는 관리자 앱용 `/nadreego` 경로입니다. 고객 앱에서 호출하지 않습니다.

### 6.1 업로드

```http
PUT /nadreego/rent/passport
Authorization: Bearer <admin-access-token>
Content-Type: application/json
```

```json
{
  "bookedNo": "BONRTEST-RES-HAND-001",
  "contentType": "image/jpeg",
  "imageBase64": "<base64-of-already-masked-jpeg>",
  "masked": true
}
```

요청 규칙:

- `bookedNo`는 예약번호 `BO...` 또는 렌탈계약번호 `RT...`입니다.
- 진행 중 렌탈인 `ON_RENT`, `OVERDUE` 상태에서만 업로드할 수 있습니다.
- `imageBase64`에는 `data:image/jpeg;base64,` 같은 data URL 접두사를 넣지 않습니다.
- `contentType`은 `image/jpeg` 또는 `image/png`만 허용합니다.
- 여권번호와 개인정보가 보이지 않도록 프론트에서 먼저 마스킹하고 `masked: true`로 보냅니다.
- 원본 여권 이미지는 전송하지 않습니다.

성공 응답:

```json
{
  "status": "success",
  "bookedNo": "BONRTEST-RES-HAND-001",
  "available": true,
  "contentType": "image/jpeg",
  "sizeBytes": 184320,
  "uploadedAt": "2026-10-07T09:00:00+08:00",
  "downloadPath": "/nadreego/rent/passport/BONRTEST-RES-HAND-001"
}
```

응답에 저장소 내부 키나 이미지 원문은 포함되지 않습니다.

### 6.2 조회

```http
GET /nadreego/rent/passport/{booked_no}
Authorization: Bearer <admin-access-token>
```

응답은 JSON이 아니라 이미지 바이너리입니다.

- JPEG: `Content-Type: image/jpeg`
- PNG: `Content-Type: image/png`
- 프론트 HTTP 클라이언트에서는 `responseType: "blob"`으로 요청합니다.
- 응답은 `Cache-Control: no-store`입니다.
- 반납된 렌탈은 조회할 수 없으며 `404`를 처리해야 합니다.

### 6.3 여권 오류 처리

| 오류 코드 | 의미 | 프론트 처리 |
|---|---|---|
| `PASSPORT_MASK_REQUIRED` | `masked`가 true가 아님 | 마스킹 후 재업로드 |
| `PASSPORT_IMAGE_INVALID` | base64 또는 이미지 형식이 잘못됨 | 이미지 인코딩 확인 |
| `PASSPORT_IMAGE_SIZE_INVALID` | 이미지 크기 초과 | 이미지 압축 후 재업로드 |
| `PASSPORT_RENTAL_NOT_ACTIVE` | 활성 렌탈이 아님 | 렌탈 상태를 다시 조회 |
| `PASSPORT_NOT_FOUND` | 해당 렌탈에 이미지 없음 | 업로드 화면 표시 |
| `PASSPORT_STORAGE_NOT_CONFIGURED` | 서버 저장소 설정 문제 | 사용자에게 일반 오류 표시, 백엔드 확인 |

## 8. 프론트 체크리스트

- [ ] 운영 Swagger에서 여권 PUT/GET 경로 확인
- [ ] 관리자 인증 토큰을 `Authorization`에 전송
- [ ] 관리자 로그아웃 시 현재 기기의 `X-FCM-Token` 전송
- [ ] 새 관리자 로그인 후 기존 세션 만료를 처리
- [ ] 고객 앱에서 프로필 화면 진입 시 `GET /api/v1/nadree/user/profile` 호출
- [ ] 대여 기간을 최대 30일로 제한
- [ ] `paymentDeadline`, `canPay`, `cannotPayReason`으로 결제 버튼 상태 제어
- [ ] 환불 화면에서 최상위 `refundStatus`, `refundRequestedAmount`, `refundedAmount` 사용
- [ ] 회원 탈퇴 시 `DELETE /api/v1/nadree/user/account` 호출 후 저장 토큰 삭제
- [ ] 여권 이미지 마스킹 후 base64 JSON 업로드
- [ ] 여권 조회 응답을 `blob`으로 표시하고 로컬 캐시 금지
- [ ] 반납 후 여권 조회 `404` 처리

## 9. 현재 제한사항

- 서버는 `masked: true` 요청을 받지만 이미지에 실제 개인정보가 보이지 않는지 OCR/비전 검증까지는 하지 않습니다. 프론트 마스킹이 필수입니다.
- 현재 저장소는 운영 서버의 비공개 파일 시스템입니다. 향후 S3 또는 암호화 오브젝트 저장소로 교체할 수 있습니다.
- 반납 후 API 조회는 차단되지만, 자동 파일 삭제 정책은 별도 운영 작업이 필요합니다.

## 10. 권장 확인 순서

1. 테스트 관리자 계정으로 로그인합니다.
2. 활성 렌탈의 `bookedNo`를 확인합니다.
3. 개인정보를 포함하지 않은 테스트 이미지로 PUT 업로드합니다.
4. 응답의 `downloadPath`로 GET 요청을 보내 `blob` 표시를 확인합니다.
5. 렌탈 반납 후 같은 GET 요청이 `404`인지 확인합니다.

실제 여권 원본이나 운영 고객의 개인정보 이미지는 테스트에 사용하지 않습니다.
