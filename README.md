# Nadree API 구현 안내

최종 수정일: 2026-09-28

기존 DB를 공유하는 독립 Python 3.12·FastAPI 서버다. 기존 RiderLog 소스·환경 설정·배포는 변경하지 않는다. 모든 후속 구현 자료는 이 폴더에서 관리한다.

## 현재 상태

2026-10-13 백엔드 실제 검증: 사용자 env 수정과 승인된 API 재시작 후 이전 로그인 503은 해결됐다. 실제 인증·고객/관리자 로그인·채팅 세션·refresh·권한·오류 응답 검사 48개가 모두 통과했다. 격리 API 회귀 219개, Firestore 통합 4개·Rules 4개와 Python 6개 함수의 업무 핸들러도 통과했다. 실제 예약 생성/취소는 격리 검증으로 구분하며 App Check 종단·앱 화면·기기 푸시는 별도 미검증이다. [백엔드 검증 결과](docs/backend-api-verification-2026-10-13.md).

2026-10-13 신규 채팅 실제 적용: 승인된 Node.js 함수 7개를 정리하고 Python callable 5개를 재생성·만료 함수 1개를 갱신했다. bail-472405/asia-southeast2의 Python 6개 ACTIVE, Rules 일치·인덱스 4개 READY, 15분 만료 실행과 API 재시작·단일 동기화 타이머를 확인했다. 최초 동기화는 지점 24개·예약방 8개 생성 성공이다. 전체 Python 회귀 219개 및 별도 Firestore 3개·Rules 4개가 통과했다. 실제 계정·유효 App Check·실기기 푸시/앱 인수는 아직 미검증이다. [실제 적용 결과](docs/chat-new-build-deployment-result-2026-10-13.md)에 완료·잔여 항목을 구분했다.

2026-10-13 채팅 방향 확정: [채팅 계약](chat/chat-contract.md)과 현재 Python 구현을 정본으로 신규 구축한다. 기존 데이터 이전·구버전 호환 코드는 만들지 않는다. 기존 Node.js 채팅 함수 7개의 정리와 Python 함수 6개의 적용은 [신규 구축 실행안](docs/chat-new-build-deployment-plan-2026-10-13.md)의 정확한 목록으로 별도 승인을 받는다. 현재는 운영 적용·실제 앱 연동 인수 전이며 기존 FCM/Auth·차량 위치·채팅 외 데이터와 규칙을 보존한다.

2026-10-12 채팅 추가: 기존 소스가 없다는 사용자 확인에 따라 [채팅 연동 계약](chat/chat-contract.md), 자카르타 `asia-southeast2` Functions·Rules·인덱스, 관리자/고객 채팅 세션 API 및 업무 동기화 코드를 신규 작성했다. 아래 과거 “채팅 소스 미제공” 상태를 대체한다. 기본 비활성이며 실제 Firebase 배포·운영 실연동은 별도다.

### 2026-10-12 변경분 — 부분 구현, 전체 출시 인수 전

이 절의 최신 정책이 아래 과거 진행 기록보다 우선한다. 운영 배포·실제 DB 변경·Firebase/PayPal 실연동 테스트는 실행하지 않았다.

| 취소 실행자 | 시작일 전 | 시작일 당일부터 |
| --- | --- | --- |
| 관리자 | 인계 전 APPROVED 예약 취소, 100% 환불 | 취소 불가 |
| 고객 | 인계 전 REQUESTED/APPROVED 예약 취소, 90% 환불 | 인계 전 취소 가능, 0% 환불·PG 환불 요청 없음 |

날짜 경계는 업무 시간대(기본 Asia/Makassar)다. 기존 결제 행에 `cancellation_requested_by_type`, `cancellation_requested_by_id`, `refund_percentage`를 저장한다. 클라이언트가 요청자·환불률을 지정할 수 없으며 과거 데이터는 추정하여 채우지 않는다.

로컬 코드 반영 범위:

- 결제 기한은 최초 승인+72시간과 렌탈 시작 중 빠른 시각. 확정 예약의 저장된 견적을 사용하고 취소 정책에 맞춰 FCM 문구를 수정했다.
- 지점 생성 시 발급한 일회성 초대코드 가입은 해당 지점의 대표관리자(rental_primary_admin)로 즉시 ACTIVE이며 승인 요청을 만들지 않는다. 대표 이메일만 입력하면 해당 대표 지점의 일반관리자 가입 요청으로 승인 대기하며 승인 후 rental_manager가 된다. 상위 회사 권한은 부여하지 않는다.
- 차량 생성 시 외부 QR은 필수, 센서는 선택이다. 응답의 QR·센서 연결 상태를 구분한다.
- 관리자 고객 목록·상세·이력: `GET /nadreego/customers`, `GET /nadreego/customers/{customer_id}`, `GET /nadreego/customers/{customer_id}/history`. Bearer 인증, `spotMasterId` 조회 범위, 목록/이력 `page`·`pageSize` 페이지 방식이다. 일반 직원은 직접 소속 지점, 대표는 허용 하위 지점의 거래 고객만 조회한다. 연락처는 원천 데이터가 없어 null이며 여권·FCM·세션 정보는 노출하지 않는다.
- 지점 공통 알림: `GET /nadreego/notifications`, `GET /nadreego/notifications/unread-count`, `POST /nadreego/notifications/{notification_id}/read`. 목록/개수는 `shopId` 필수, 목록은 `page`·`pageSize`와 `isRead`·`eventType` 선택 필터다. 읽음은 직원 간 공통이며 반복 요청 시 최초 readAt을 유지한다. 예약·결제·환불·인계·반납 이벤트를 저장한다. 채팅은 활성화 후 app.chat_sync 작업으로 연결한다.
- `GET /nadreego/shop/profile` 전체 매장 조회, 기존 매장 수정에 대상 지점·주소/좌표·선택 정보 명시적 null 삭제를 추가했다. hierarchy에 회사·부모·작업 권한 정보를 추가했다. 지점 생성에 이메일·주소·좌표를 검증한다.
- 예약 시 위치를 저장하고 계약에 복사한다. 위치 없는 지점은 상품 조회를 유지하되 신규 예약만 제한한다. 기존 예약의 위치·금액은 매장 설정 변경으로 덮어쓰지 않는다.
- 지점 가격·배송 설정은 일반 직원의 직접 지점과 대표의 허용 하위 지점에 한정한다. 회사 공통 BASE 가격은 현재 테스트 값을 유지하며 회사별 운영 정책은 실데이터 이전 시 확정한다.
- 여권 업로드는 인계 필수 조건이 아니다. 기존 파일을 삭제하거나 신규 여권 기능을 추가하지 않았다.

추가 DB 변경은 [마이그레이션 안내](migrations/README.md)의 2026-10-12 항목을 따른다. 새 알림 테이블을 업무 트랜잭션에서 사용하므로 스키마 적용 없이 코드만 재시작하면 안 된다. 이전 전달 문서의 “추가 마이그레이션 없음”은 이번 변경에는 해당하지 않는다.

남은 작업(전체 완료로 판정하지 않음):

- 신규 채팅의 실제 Firebase 배포·연동, 공유 서버에서 직접 변경하는 소속/권한의 즉시 회수 연결은 남아 있다. 설정·운영 제한·검증은 [채팅 계약](chat/chat-contract.md)을 따른다.
- PG 상태 불명확 결제의 만료 전 확인, 뒤늦은 실제 결제·중복 청구의 자동 전액 환불, 실패 환불 자동 재시도·최종 실패 운영 재처리 보완. 기존 환불 처리를 이 요구사항 전체의 완료로 간주하지 않는다.
- 같은 장소의 위치 정정과 실제 이전을 구분하는 예약 위치 정정 계약·이력, 센서 QR→sensorId 변환 계약, 차량 이동/재배정 상세 시나리오 검증.
- 실제 공유 MySQL의 조직 생성 제약·중첩 지점 및 동시성 검증, 실제 Firebase·PayPal·탈퇴 후 문의/환불 연속성 인수. 기존 여권 파일 정리는 저장소·보존 범위를 확인한 별도 운영 절차가 필요하다.

수정된 API 스키마는 실제 라우터에서 OpenAPI로 생성한다. 2026-10-12 채팅 추가 후 로컬 테스트는 213개 통과, 9개 건너뜀(MySQL 6개, 별도 Firestore 에뮬레이터 3개)이다. Firestore 트랜잭션 3개는 별도 실행에서 통과했고 Rules 에뮬레이터 4개도 통과했다. 운영 전체 인수 완료를 뜻하지 않는다.

### 과거 진행 기록

- W00 실행·설정·DB 트랜잭션·인증·권한·테스트 기반 및 이번 범위의 마이그레이션 준비.
- W01·W02 기존 15개 경로와 관리자 가입 접수 1개 경로의 기본 기능 구현·로컬 검증을 완료했다. API 05 전화번호 암호문 저장을 위한 phone VARCHAR(200), API 23 소개·연락 이메일의 지점 컬럼 추가를 반영했으며 운영 DB에서는 승인된 컬럼·인덱스 적용 상태를 별도로 확인한다.
- W03~W08 차량·QR·가격·배송·예약·렌트·조회·PayPal 웹훅 라우터로 기존 관리자·조직 API 38개를 유지하고 관리자 가입 신청 1개를 추가했다. 나드리 고객 API 14개 경로(로그아웃·refresh GET 호환 포함 16개 메서드)는 별도 네임스페이스로 제공한다. 예약 요청·승인/거절·결제 기한·결제 확정의 FCM 발송과 활성 렌탈의 비식별 여권 이미지 업로드·보호 조회를 추가했으며 토큰은 계정별 현재 기기 값 1개를 기존 공유 DB에 저장한다. 예약·결제 응답에는 `shopId=spotMasterId`, `bookingId=reservationId` 매핑을 명시하고, 응답 유실 복구용 결제 상태 조회를 제공한다. 캘린더는 상태 필터가 없는 일반 요청에서 SQL로 차량 ID·페이지를 먼저 선별하고 상세 정보는 해당 페이지만 읽는다. 전체 로컬 테스트는 164개 통과, 6개는 별도 MySQL이 없어 건너뛴다.
- API 32·33의 신청 조회·승인·거절 구현과 `POST /nadreego/admin/signup` 가입 접수를 완료했다. 가입 API는 RiderLog 호환 `MSP_ADMIN` 계정을 만들고 대표 이메일·초대코드로 지점을 검증한 뒤 REQUESTED 신청만 저장한다. 승인 전에는 렌탈 role/scope를 부여하지 않는다. 하위지점 생성은 `MSP_SPOT_RENT.invite_code`를 발급하고 성공한 가입 신청에서 소비한다.
- 렌탈 사용자 영역은 MSP_DRIVER와 분리했다. MSP_RENTAL_USER는 uid_token을 기본키로 사용하고 name·gender·age·nationality를 보관하며, MSP_RESERVATION·MSP_RENTAL_CONTRACT도 uid_token으로 연결한다. 기존 legacy_user_code와 렌탈 영역의 driver_id는 003 마이그레이션에서 정리한다.
- 나드리 고객 앱의 UID 로그인·신규 사용자 생성, 1시간 access token 발급, 프로필 갱신, 렌탈 차량 가용성·가격 조회, 렌트 요청, PayPal 결제 주문·캡처, 진행·완료 렌트 목록 조회와 결제 전 예약 취소·고객 로그아웃 API를 구현했다. 관리자 앱에는 활성 렌탈의 비식별 여권 이미지 업로드·보호 조회를 추가했다. 고객 API 명세와 운영 전 확인 항목은 [사용자 API 설계](docs/nadri-user-api-design.md)에 별도로 정리했다. 관리자용 나드리고 API와 기존 RiderLog 운전자 API에는 영향을 주지 않는다.
- 정비 만료·승인 후 결제 기한 알림·PayPal 미결제 예약 만료·6개월 일별 재고를 `python -m app.jobs {maintenance|payments|inventory|all}`로 실행할 수 있다. PayPal Sandbox·FCM 서비스 계정·Redis·SMTP·MFA·앱 흐름·기존 서버 회귀는 운영 환경에서 별도로 확인해야 한다. 테스트 통과는 코드·로컬 검증 결과이며 외부 서비스 통합 완료를 뜻하지 않는다.

상세 진행표·제한사항·검증 결과: [W00~W02 구현 기록](docs/w00-w02-implementation.md). 전체 범위: [API 작업 구분](docs/api-work-groups.md).

## 실행

이 폴더를 작업 디렉터리로 사용한다. `.venv`는 기존 서버와 공유하지 않는다.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8008 --no-access-log
```

- Swagger UI: <http://127.0.0.1:8008/docs> (운영: <https://na-dree.com/docs>)
- ReDoc: <http://127.0.0.1:8008/redoc>
- 실행 확인: <http://127.0.0.1:8008/health/live>

FCM 토큰은 앱이 전달한 현재 기기의 최신 값 1개를 계정별로 저장한다. 예약·결제 확정 알림은 해당 지점에 직접 연결된 활성 관리자에게, 승인·거절·기한 알림은 고객에게 DB 트랜잭션 커밋 뒤 기존 FCM Firebase 프로젝트로 발송한다. 고객 인증·채팅도 같은 프로젝트를 사용하고 차량 위치 Firebase만 별도 프로젝트로 분리한다. 동일 토큰은 한 번만 발송한다. 발송 장애는 업무 API를 실패시키지 않으며, 일시 오류는 프로세스 내부에서 최대 5회·1시간 범위로 제한 재시도한다. 로그아웃에 현재 기기의 `X-FCM-Token`을 보내 저장값과 일치하면 토큰을 삭제하고, 헤더가 없으면 유지한다. 알림 큐 테이블이나 Firebase 데이터베이스는 사용하지 않는다.
- 의존 서비스·스키마 확인: <http://127.0.0.1:8008/health/ready>
- 실제 라우터에서 생성되는 OpenAPI JSON: <http://127.0.0.1:8008/openapi.json>

8008 포트를 다른 프로세스가 사용하면 빈 포트로 변경한다. 설정 없이도 개발 서버와 문서 화면은 열리지만 업무 API는 503으로 차단된다. 샘플 DB·로그인 계정을 운영 앱에 자동 생성하지 않는다.

`.env.example`의 항목을 환경 변수 또는 이 폴더의 비공개 `.env`로 설정한다. DB URL은 `mysql+pymysql://USER:PASSWORD@HOST:3306/DB?charset=utf8mb4` 형식이다. 실제 비밀값을 이 문서·엑셀·소스에 넣지 않는다.

| 설정 | 용도 |
| --- | --- |
| `NADREE_DATABASE_URL` | 기존 스키마와 승인된 렌탈 확장이 적용된 MySQL |
| `NADREE_REDIS_URL` | 서버 간 공통 요청 제한. 운영 환경에서는 인증·TLS 적용 |
| `NADREE_JWT_SECRET` | 새 서버 전용 무작위 서명 키, 최소 32바이트 |
| `NADREE_BUSINESS_TIMEZONE` | 기본 `Asia/Makassar` |
| `NADREE_FIELD_ENCRYPT_KEY` | 기존 전화번호 암호화와 호환되는 Fernet 키. 평문 대체 금지 |
| `NADREE_PAYPAL_*` | Sandbox/Live 환경, Client ID·Secret, Webhook ID, Merchant ID. 비공개 환경변수로 주입 |
| `NADREE_FCM_*` | FCM 발송·고객 인증·채팅용 기존 Firebase 서비스 계정. 차량 위치용 `NADREE_LOCATION_FIREBASE_*`와 분리 |
| `NADREE_FIRESTORE_PROJECT` / `NADREE_LOCATION_FIREBASE_*` | 차량 위치 조회용 Firestore 프로젝트·서비스 계정. 위치 어댑터는 `driving/{sensor_code}` 문서의 `g.geopoint`를 읽으며 FCM 발송 프로젝트와 분리하며, 서비스 계정이 없으면 ADC/workload identity를 사용 |
| `NADREE_SMTP_*` | 임시 비밀번호 메일 발송. 인증서 검증을 하는 STARTTLS 또는 SSL |
| `NADREE_ENV` | `development`, `test`, `production` |

JWT 키·issuer·audience는 기존 서버와 분리한다. 전화번호 키는 공유 데이터와의 호환성이 필요하므로 배포 환경에서 안전하게 주입한다. 기존 `.env` 전체를 복제하지 않는다.

## 테스트와 DB 변경

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m app.migrate
```

테스트는 임시 SQLite 데이터를 사용한다. MySQL 동시성 테스트는 별도 설정 없으면 건너뛴다. `app.migrate`는 기본 읽기 전용 계획 조회이며, 누락된 렌탈 조회 복합 인덱스도 계획에 표시한다. **공유 운영 DB 변경은 승인된 SQL·적용 주체·백업 절차를 확인한 뒤에만** 실행한다. [마이그레이션 안내](migrations/README.md)를 먼저 확인한다.

## 정본과 파일

| 경로 | 역할 |
| --- | --- |
| [통합 문서](../rental-project-master.md) | 프로젝트·API·추가 DB·업무 규칙 |
| [검토 문서](../rental-api-review-decisions.md) | 사용자 결정과 남은 정책 |
| [엑셀 API 명세](<../나드리고 api 마무리.xlsx>) | 관리자·가입·나드리 고객 API의 표·JSON 예시 및 통합 목록 |
| [ERD SQL](../erdcloud-current-plus-rental.sql) | 시각화용, 운영 실행 금지 |
| `app/` | 새 서비스 코드, 기존 조직 URL도 직접 구현 |
| `tests/` | 단위·권한·롤백·선택 MySQL 동시성 테스트 |
| `migrations/` | 승인 범위의 실행 SQL과 적용 안내 |
| `docs/` | 구현 진행·의존성·검증 기록 |

서비스 시작 시 `create_all`이나 마이그레이션을 자동 실행하지 않는다. 기존 웹 권한을 넓히거나 관리자를 자동 배정하지 않는다. 실제 운영에서는 HTTPS, 접근 로그 비밀값 제외, 신뢰하는 프록시 범위, DB 권한·백업·마이그레이션 실행 주체를 별도로 설정한다.
