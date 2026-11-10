# 차량 QR 삭제·재연결 — 프론트 전달

작성일: 2026-11-10. 고객·관리자 앱 담당자가 사용하는 변경 계약이다.

서버 반영 완료: 공개 https://na-dree.com 의 Swagger/OpenAPI에서 신규 경로를 확인할 수 있다. 아래 JSON의 NDR-Ab12Cd34는 입력 형식 예시이며 실제 부착할 QR 원문으로 바꾼다.

## 변경 내용

- QR 삭제는 비활성화가 아니라 **현재 QR 연결 행 삭제**다. 차량 자체·센서·예약·렌트·결제는 삭제하지 않는다.
- 삭제된 QR 원문은 같은 차량이나 다른 차량에 다시 사용할 수 있다. 변경 이력은 보존하지만 과거 이력으로 재사용을 차단하지 않는다.
- 한 차량에는 현재 QR 하나, 한 QR에는 현재 차량 하나만 연결된다. 비활성·만료 QR도 현재 연결 행이 남아 있으면 먼저 삭제해야 한다.
- 다른 차량에 붙어 있는 QR의 자동 이동이나 대상 차량의 기존 QR 자동 교체는 하지 않는다. **원래 차량에서 삭제 → 대상 차량의 기존 QR 삭제(있을 때) → 대상 차량에 연결** 순서다.
- 신규 차량 등록 API와 기존 QR 조회 API의 경로·입력은 유지한다. 기존 차량에 QR만 연결하는 API를 추가한다.

## 인증·지점·차량 조건

관리자 API는 기존 관리자 access token을 Authorization Bearer로 보낸다. 대표/일반관리자의 기존 직접 소속 지점 관리 권한을 유지한다. 다른 지점 차량은 변경할 수 없다.

대여 중(ON_RENT/OVERDUE) 또는 고객 인수 대기·만료 후 실물 회수 보호 중인 차량은 QR 삭제·연결을 차단한다. availableActions는 화면 안내이며 서버가 실행 시 권한과 상태를 다시 확인한다.

## QR 삭제 — 기존 경로 유지

`POST /nadreego/sensor/delete`

```json
{"vehicleNumber":"testlisence","division":"QR"}
```

성공 HTTP 200:

```json
{"status":"success"}
```

성공 후 차량 목록을 갱신한다. 해당 차량의 qrStatus는 null, 변경 가능한 상태라면 availableActions에 QR_LINK가 나온다. 삭제한 QR을 재연결하기 전 조회하면 404 QR_NOT_FOUND다.

division=SENSOR는 기존 센서 분리 동작이며 QR을 삭제하지 않는다. QR 삭제를 위해 새 DELETE HTTP 메서드로 바꿀 필요는 없다. 이미 QR이 없으면 재삭제는 404 QR_NOT_FOUND다. 통신 결과가 불명확하면 차량 목록에서 현재 연결 유무를 확인한다.

## 기존 차량에 QR만 연결 — 신규 API

`POST /nadreego/vehicle/qr/link`

```json
{"vehicleNumber":"testlisence","qrToken":"NDR-Ab12Cd34"}
```

성공 HTTP 200:

```json
{
  "status":"success",
  "vehicleId":"<target-vehicle-id>",
  "qr":{"qrId":"<qr-id>","qrStatus":"ACTIVE"}
}
```

vehicleNumber는 대상 차량의 **차량번호**이며 vehicleId가 아니다. qrToken은 QR 원문이다. 같은 차량에 같은 활성 QR을 다시 보내면 같은 qrId를 반환하고 이력을 중복 생성하지 않는다. 삭제 후 새로 연결하면 새 qrId가 발급된다. 대여·인수 보호 중에는 같은 연결을 재요청해도 변경 API가 차단된다.

이 API는 차량을 새로 만들지 않는다. 기존 차량의 QR 교체에 /nadreego/vehicle/create를 다시 호출하지 않는다.

## 신규 차량 등록 — 기존 API 유지

`POST /nadreego/vehicle/create`의 qrToken 필드를 그대로 사용한다. 센서는 선택이며 해제된 QR도 재사용할 수 있다. 현재 다른 차량에 연결된 QR은 계속 차단한다. 차량번호·모델 등 기존 필수 입력과 중복 검사도 유지한다.

## 원문·조회·화면 처리

- 등록/연결에는 qrToken, 관리자 조회 `POST /nadreego/vehicle/qr/validate` 및 고객 QR 조회에는 qrCode로 **동일 원문**을 보낸다.
- 대소문자·공백을 바꾸지 않는다. 허용 길이는 1~4096자다. 앱에서 해시를 계산하지 않는다.
- QR 이미지가 URL이라면 기존 계약대로 프론트가 fragment 원문을 추출한다. URL 전체나 센서 코드를 보내지 않는다. 서버 해시·비밀키는 앱이 보관할 필요가 없다.
- QR_DELETE: 현재 QR이 있으므로 삭제 화면 제공(기존 INACTIVE/EXPIRED 포함).
- QR_LINK: 현재 QR이 없으므로 QR 스캔·연결 화면 제공.
- 대여/인수 보호로 액션이 없으면 QR 변경 버튼을 표시하지 않는다. 삭제·연결 후 차량 목록/상세를 갱신한다.
- 해제된 QR은 다음 연결 전까지 404이고, 다른 차량에 재연결한 뒤에는 새 차량을 반환한다. 이전 차량 캐시를 재사용하지 않는다.
- 현장 견적 후 QR이 다른 차량으로 이동하면 기존 견적으로 신청하지 않는다. 새 QR 조회와 견적을 받는다.
- 이미 완료된 고객 인수의 재전송은 기존 본인 예약의 결과를 반환한다. QR 재사용으로 새 예약·계약을 만들지 않는다.

## 주요 오류

기존 실패 형식은 `{"status":"fail","errorCode":"..."}`다.

| HTTP | errorCode | 프론트 처리 |
|---|---|---|
| 401 | 기존 인증 오류 코드 | 토큰 갱신/재로그인 |
| 404 | VEHICLE_NOT_FOUND | 차량번호·현재 지점 확인 |
| 404 | QR_NOT_FOUND | QR 없음 또는 삭제/변경됨. 목록 갱신 |
| 409 | QR_ALREADY_ISSUED | QR이 현재 연결 중. 원래 차량에서 삭제 후 연결 |
| 409 | VEHICLE_QR_ALREADY_LINKED | 대상 차량의 기존 QR을 먼저 삭제 |
| 409 | VEHICLE_ALREADY_ON_RENT | 반납 전 QR 변경 불가 |
| 409 | VEHICLE_RECEIPT_HOLD | 고객 인수 또는 직원 실물 회수 완료 전 변경 불가 |
| 409 | ONSITE_QUOTE_MISMATCH | QR이 다른 차량으로 변경됨. 새 조회·견적 필요 |
| 409 | SHOP_CLOSING | 지점 탈퇴/폐점 처리 중 변경 불가 |
| 409 | REQUEST_KEY_REUSED | 같은 접수 키의 본문을 바꾸지 말 것 |
| 422 | INVALID_INPUT | 필수 필드·길이·차량번호·불필요 필드 확인 |

현재 연결이 남은 INACTIVE/EXPIRED QR의 조회 오류 QR_INACTIVE/QR_EXPIRED는 기존대로다. 연결을 삭제하면 이후 조회는 QR_NOT_FOUND다. 권한·계약·설정 오류도 기존 공통 계약을 따른다.

## 앱 확인 항목

1. 차량 A QR 삭제 → 목록 qrStatus=null/QR_LINK → 삭제 QR 조회 404.
2. 차량 B에 같은 QR 연결 → QR 조회 시 B 반환, A는 QR 없는 상태 유지.
3. B QR 삭제 → 다른 QR 연결 → 새 원문으로 B 조회.
4. 현재 점유 QR 중복과 기존 QR 자동 교체는 409이며 기존 연결 유지.
5. 같은 활성 연결 재요청은 같은 qrId 반환.
6. 일반관리자 직접 지점은 허용, 타 지점·무인증·대여 중·인수/회수 보호는 차단.
7. 교체 후 고객 QR 조회·견적·관리자 인계·본인 고객 인수 흐름 확인.

백엔드 격리 검사와 실제 서버 적용·지정 차량 정리는 별도 [서버 결과](vehicle-qr-reassignment-server-result-2026-11-10.md)에 기록한다. 실기기 스캔·양 앱 화면은 공동 확인 대상이다.

현재 승인된 시험 차량 testlisence는 이전 INACTIVE QR 연결을 실제 삭제했고 차량은 AVAILABLE로 유지했다. 이전 원문 NDR-bMMvEtKn도 현재 점유가 없어 재사용 가능하다. 새 QR은 임의 연결하지 않았으므로 원하는 원문을 link API로 연결한 뒤 스캔한다.
