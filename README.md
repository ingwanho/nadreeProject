# Nadree API 구현 안내

최종 수정일: 2026-09-17

기존 DB를 공유하는 독립 Python 3.12·FastAPI 서버다. 기존 RiderLog 소스·환경 설정·배포는 변경하지 않는다. 모든 후속 구현 자료는 이 폴더에서 관리한다.

## 현재 상태

- W00 실행·설정·DB 트랜잭션·인증·권한·테스트 기반 및 이번 범위의 마이그레이션 준비.
- W01·W02 총 15개 경로의 기본 기능 구현·로컬 검증 완료. API 05 전화번호 암호문 저장을 위한 phone VARCHAR(200), API 23 소개·연락 이메일의 지점 컬럼 추가를 반영했다. 실제 DB 변경은 아직 적용하지 않았다.
- W03~W08 차량·QR·가격·배송·예약·렌트·조회·PayPal 웹훅 라우터로 기존 관리자 38개 명세를 유지한다. 나드리 고객 API 11개는 별도 네임스페이스로 추가했다. FCM 토큰 저장만 유지하고 알림 발송은 새 Firebase 프로젝트 연결 이후로 보류했다. 로컬 테스트는 140개 통과했으며 MySQL 동시성 6개는 별도 DB가 없어 건너뛴다.
- API 32·33의 신청 조회·승인·거절 구현 완료. 승인된 MSP_RENTAL_ADMIN_REQUEST 8컬럼과 마이그레이션을 추가했다. 기존 email/action 입력·status 응답은 유지한다. 신청을 처음 접수하는 가입 서버·계정 생성 경로 연결은 별도 남은 작업이다.
- 렌탈 사용자 영역은 MSP_DRIVER와 분리했다. MSP_RENTAL_USER는 uid_token을 기본키로 사용하고 name·gender·age·nationality를 보관하며, MSP_RESERVATION·MSP_RENTAL_CONTRACT도 uid_token으로 연결한다. 기존 legacy_user_code와 렌탈 영역의 driver_id는 003 마이그레이션에서 정리한다.
- 나드리 고객 앱의 UID 로그인·신규 사용자 생성, 1시간 access token 발급, 프로필 갱신, 렌탈 차량 가용성·가격 조회, 렌트 요청, PayPal 결제 주문·캡처, 진행·완료 렌트 목록 조회와 결제 전 예약 취소·고객 로그아웃 API를 구현했다. 고객 API 명세와 운영 전 확인 항목은 [사용자 API 설계](docs/nadri-user-api-design.md)에 별도로 정리했다. 관리자용 나드리고 API와 기존 RiderLog 운전자 API에는 영향을 주지 않는다.
- MySQL·Redis·SMTP 실연동, MFA 연동, 앱 연동 및 운영 DB 적용은 미완료다. 테스트 통과를 전체 W01·W02 완료로 보지 않는다.

상세 진행표·제한사항·검증 결과: [W00~W02 구현 기록](docs/w00-w02-implementation.md). 전체 범위: [API 작업 구분](docs/api-work-groups.md).

## 실행

이 폴더를 작업 디렉터리로 사용한다. `.venv`는 기존 서버와 공유하지 않는다.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8008 --no-access-log
```

- Swagger: <http://127.0.0.1:8008/docs>
- 실행 확인: <http://127.0.0.1:8008/health/live>

FCM 토큰은 앱이 전달한 값을 계정별로 저장하며 로그아웃 시 삭제하지 않는다. 알림 발송과 새 Firebase 서비스 계정 연결은 해당 프로젝트를 준비한 뒤 별도 작업으로 활성화한다.
- 의존 서비스·스키마 확인: <http://127.0.0.1:8008/health/ready>
- 실제 라우터에서 생성되는 OpenAPI: `/openapi.json`

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
| `NADREE_SMTP_*` | 임시 비밀번호 메일 발송. 인증서 검증을 하는 STARTTLS 또는 SSL |
| `NADREE_ENV` | `development`, `test`, `production` |

JWT 키·issuer·audience는 기존 서버와 분리한다. 전화번호 키는 공유 데이터와의 호환성이 필요하므로 배포 환경에서 안전하게 주입한다. 기존 `.env` 전체를 복제하지 않는다.

## 테스트와 DB 변경

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m app.migrate
```

테스트는 임시 SQLite 데이터를 사용한다. MySQL 동시성 테스트는 별도 설정 없으면 건너뛴다. `app.migrate`는 기본 읽기 전용 계획 조회이며, **실제 DB 변경은 별도 승인 후에만** 한다. [마이그레이션 안내](migrations/README.md)를 먼저 확인한다.

## 정본과 파일

| 경로 | 역할 |
| --- | --- |
| [통합 문서](../rental-project-master.md) | 프로젝트·API·추가 DB·업무 규칙 |
| [검토 문서](../rental-api-review-decisions.md) | 사용자 결정과 남은 정책 |
| [엑셀 API 명세](<../나드리고 api 마무리.xlsx>) | 38개 API의 표·JSON 예시 |
| [ERD SQL](../erdcloud-current-plus-rental.sql) | 시각화용, 운영 실행 금지 |
| `app/` | 새 서비스 코드, 기존 조직 URL도 직접 구현 |
| `tests/` | 단위·권한·롤백·선택 MySQL 동시성 테스트 |
| `migrations/` | 승인 범위의 실행 SQL과 적용 안내 |
| `docs/` | 구현 진행·의존성·검증 기록 |

서비스 시작 시 `create_all`이나 마이그레이션을 자동 실행하지 않는다. 기존 웹 권한을 넓히거나 관리자를 자동 배정하지 않는다. 실제 운영에서는 HTTPS, 접근 로그 비밀값 제외, 신뢰하는 프록시 범위, DB 권한·백업·마이그레이션 실행 주체를 별도로 설정한다.
