# 관리자 채팅 lastMessageAt 인덱스 서버 적용 결과

**2026-11-26 적용·검증 완료. 신규4개 모두 READY, 기존11개 보존, 운영 전체15개 READY다.** 실제 Firebase 사용자 ID 토큰으로 대표·일반관리자 각각9개 조합을 조회했고, 50건 페이지·null 문서 ID 커서·타 지점 차단을 확인했다. Admin SDK 결과와 실제 Rules 적용 결과를 분리했다.

기준: [인덱스 실행서](chat-last-message-indexes-2026-11-26.md), 정식 파일 [firestore.indexes.json](../chat/firestore.indexes.json), [채팅 계약](../chat/chat-contract.md).

## 대상·Git·배포 계정

| 항목 | 확인 결과 |
| --- | --- |
| 프로젝트 | **bail-472405** |
| Firestore DB | **(default)** |
| 컬렉션/인덱스 범위 | **chatRoomAccess / COLLECTION** |
| Git 시작 | main / 7303a1ce03b64340ba270d4108f9c27f3bd76830 / 로컬 변경 없음 |
| 갱신 | git pull --ff-only origin main 성공, 충돌·강제 초기화 없음 |
| 적용 커밋 | **27a78a70e50c04b93f8ccf9e7c99a59d9240994b** |
| 실제 배포 계정 | **qwer886901@gmail.com**, 기존 Firebase CLI 로그인 계정·실제 요청 토큰 신원 확인 |
| CLI | firebase-tools **13.35.1** |
| 배포 명령 실행 | **03:45:33~03:45:41 UTC**, exit0 |
| 신규4개 최초 READY 관측 | **03:51:07.467601 UTC** / 발리11:51:07 |

실제 배포 계정의 `datastore.indexes.create/get/list`, `datastore.databases.get`, `serviceusage.services.use` 권한을 확인했다. 로컬 FCM 서비스 계정을 생성 주체로 사용하지 않았고 키 교체·새 키 발급·IAM 권한 변경은 하지 않았다. 기존 CLI 로그인 캐시도 보존했다.

## 운영 백업·정식 설정 대조

비공개 근거: `build/test-runtime/chat-last-message-indexes-2026-11-26/`(디렉터리700/파일600).

- `before.private.json`: 운영 (default) 전체 복합 인덱스와 사용자 지정 fieldOverrides 원본 메타데이터.
- `formal-before.private.json`: 배포 전 정식 설정 사본.
- 기존 운영 **11개/모두 READY**, fieldOverrides **0개**였다.
- 정식 설정 **15개 = 기존11개 + 요청 신규4개**. 모든 기존 항목이 포함돼 있고 중복·원격 전용 항목은0개였다.
- 원격 전용 병합이 필요하지 않아 정식 JSON을 추가 수정하지 않았다. `__name__`의 암묵적 방향을 정규화해 정의를 비교했다.
- 완료 후 기존11개의 **ID와 정의**가 모두 동일하고, fieldOverrides **0→0**인 것을 다시 대조했다. 다른 컬렉션 항목을 삭제하지 않았다.

백업은 인덱스 정의·상태 메타데이터이며 운영 채팅 문서/본문을 백업한 것이 아니다. 초기 조회에서 pageSize 인자를 넣은 요청은400(0만 지원)이어서, 인자를 생략하고 다음 페이지 토큰을 처리하는 방식으로 수정했다. 권한 오류로 해석하거나 IAM을 변경하지 않았다.

## 실제 배포·신규 READY 상태

`chat` 폴더에서 지정 명령 그대로 실행했다.

```bash
npx firebase deploy --only firestore:indexes --project bail-472405 --non-interactive
```

`--force`를 사용하지 않았다. 감사 기록에서 **새 인덱스 생성 POST4개/각HTTP200**, DELETE·필드 PATCH·IAM·Functions/Rules 배포·문서 쓰기 요청0개를 확인했다. CLI가 수행한 Rules 구문 검사는 비영속 검사이며 Rulesets/Releases 배포는 없었다.

CLI 성공 직후4개는 CREATING이었다. 반복 생성하지 않고20초 간격의 읽기 전용 확인으로 READY 전환을 확인했다. 아래 시각은 내부 빌드 완료 시각이 아닌 **최초 READY 관측 시각**이다.

| 관리자 조건 | 신규 인덱스 ID | 실제 정렬 필드 | 상태 / 관측 UTC |
| --- | --- | --- | --- |
| 전체 | CICAgNjaxJEK | shopId ASC → lastMessageAt DESC → __name__ DESC | **READY / 03:51:07** |
| kind | CICAgNjaxJEJ | shopId ASC → kind ASC → lastMessageAt DESC → __name__ DESC | **READY / 03:51:07** |
| status | CICAgOi36pgK | shopId ASC → status ASC → lastMessageAt DESC → __name__ DESC | **READY / 03:51:07** |
| kind + status | CICAgOi36pgJ | shopId ASC → kind ASC → status ASC → lastMessageAt DESC → __name__ DESC | **READY / 03:51:07** |

운영 응답에서 네 정의의 `__name__ DESC`를 직접 확인했다. 정식 JSON의 마지막 lastMessageAt DESC에 따른 기본 문서 이름 정렬과 일치한다. [Firestore 기본 이름 정렬 기준](https://firebase.google.com/docs/firestore/query-data/index-overview#default_ordering_and_the_name_field).

## 실제 인증·Admin SDK·Rules 조회 구분

승인된 테스트 대표/일반관리자2명으로 정상 백엔드 로그인→채팅 세션→Firebase custom token 교환을 수행했다. 각 단계200, 실제 Firebase ID 토큰의 프로젝트·UID·세션 일치와 본인 chatUsers의 Rules 적용 조회200을 확인했다.

- **Admin SDK**: 서비스 계정의 읽기 권한으로 메타데이터만9개 조합 조회. 기준 결과와 데이터 상태 대조에 사용했다. Rules 권한 검증으로 해석하지 않는다.
- **실제 Firebase 사용자 ID 토큰 REST**: 정상 앱 인증 흐름으로 발급한 토큰을 사용해 Firestore Rules가 적용되는 조회를 대표/일반 각각9개, **18개 조합/양성 페이지 요청38개 모두200**으로 확인했다. 토큰은 기기에서 전달받은 것이 아니라 승인 계정의 정상 서버 발급 흐름으로 만들었다. [Firestore REST 인증 구분](https://firebase.google.com/docs/firestore/use-rest-api#authentication_and_authorization).
- 조회 대상은 `shopId/kind/status/lastMessageAt` 메타데이터뿐이다. 방 ID는 커서/중복 비교 시 메모리에서만 사용했으며 결과 문서에 넣지 않았다. messages/본문을 읽지 않았다.

정상 인증 준비는03:44:38 UTC에 완료했고, 신규 READY 확인 후 실제 양성 조회는 **03:51:58~03:52:08 UTC**에 수행했다.

| 종류 | 상태 | 대표 사용자 토큰 | 일반관리자 사용자 토큰 | 별도 Admin SDK |
| --- | --- | --- | --- | --- |
| 전체 | 전체 | 56건 / 50+6+0 | 56건 / 50+6+0 | 56건·동일 순서 |
| 전체 | Open | 4건 / 4+0 | 4건 / 4+0 | 4건·동일 순서 |
| 전체 | Closed | 52건 / 50+2+0 | 52건 / 50+2+0 | 52건·동일 순서 |
| Bookings | 전체 | 56건 / 50+6+0 | 56건 / 50+6+0 | 56건·동일 순서 |
| Bookings | Open | 4건 / 4+0 | 4건 / 4+0 | 4건·동일 순서 |
| Bookings | Closed | 52건 / 50+2+0 | 52건 / 50+2+0 | 52건·동일 순서 |
| Inquiries | 전체 | 0건 / 0 | 0건 / 0 | 0건 |
| Inquiries | Open | 0건 / 0 | 0건 / 0 | 0건 |
| Inquiries | Closed | 0건 / 0 | 0건 / 0 | 0건 |

UI의 Bookings/Inquiries는 `booking/inquiry`, Open/Closed는 `open/read_only` 조건이다. 전체 선택은 해당 조건을 생략했다. 페이지 표현의 마지막0은 커서 뒤 결과가 비는 종료 확인이며 사용자에게 빈 페이지를 추가로 보여주라는 의미가 아니다.

운영 대상56개 모두 lastMessageAt 필드가 있었다. **누락0 / 명시적 null48 / 실제 시각8**이었다. null 그룹은 전체 목록의9~56번째에 있어 실제50건 경계를 넘었다. 반환된 원래 timestamp/null과 문서 참조를 함께 startAfter로 보내 문서 ID DESC 순서를 확인했다. **중복·누락0, 18개 조합 전부 Admin SDK의 전체 순서와 일치**했다. 시각을 updatedAt/createdAt으로 바꾸거나 정밀도를 줄이지 않았다.

## 실제 접근 차단

**03:53:54~03:53:57 UTC 최종 오류 코드 확인**:

- 대표/일반관리자 각각 타 지점9개 조합, **18개 모두403 PERMISSION_DENIED**.
- 지점 조건 없는 전역 목록, **2개 모두403 PERMISSION_DENIED**.
- 무인증 조회 **403 PERMISSION_DENIED**.
- 실제 오류는 App Check/인덱스 미준비 오류가 아닌 권한 거절로 확인했다.

runQuery의 오류 본문이 JSON 배열인 형식을 테스트 도구에서 처리하도록 보완하고 오류 조건만 재확인했다. 양성 조회를 불필요하게 반복하거나 서버 업무 코드·Rules·인증 조건을 바꾸지 않았다. 대표의 답변 가능/일반관리자 답변 불가 멤버십도 현재 값으로 확인했으며 시험 메시지는 보내지 않았다.

## 격리 검증 — TAP24 통과

**03:41:40~03:42:12 UTC**, ec2-user·최소 환경·격리 HOME, `demo-nadree-chat` Firestore 에뮬레이터에서 **CI=1 npm test**를 실행했다. **TAP24 passed / 실패·건너뜀0**이다. 상위 검사6개와 역할별9조합 하위18개를 포함한 수이며 중복 합산하지 않는다.

가상 방440개(booking/inquiry × open/read_only, 각110개)에 같은 시각55개·null55개를 구성했다. 두 역할의9개 조합마다50건 페이지·같은 시각/명시적null·문서 ID DESC·중복/누락 없음과 시각 필드 없는 문서 제외를 확인했다. 타 지점/전역/무인증/다른 사용자/이전 세션 차단과 클라이언트 직접 쓰기 금지도 통과했다. 설치된 CLI의 정식15개 스키마·중복 없음도 검증했다.

에뮬레이터는 복합 인덱스를 강제하지 않으므로 이 결과를 운영 READY 증거로 사용하지 않았다. 운영 증거는 위 실제15 READY 메타데이터와 사용자 토큰 조회다. [에뮬레이터 인덱스 한계](https://firebase.google.com/docs/emulator-suite/connect_firestore#indexes). 종료 후 에뮬레이터·포트 정리 완료, 격리 실행이 운영 데이터를 읽거나 쓰지 않았다.

## 보존·미검증·남은 작업

검증 범위에서 미해결 실패는 없다. 실제 인덱스15개와 접근 검증은 완료했으며 다음을 구분한다.

- **운영 Inquiries는0건**이다. 필터 쿼리/Rules/빈 결과는 실제 확인했지만 문의 데이터가 있는 정렬·50건 경계는 격리 근거다.
- 운영의 **비null 동일 시각 그룹이50건 경계를 넘는 조건**, lastMessageAt 필드 없는 문서 제외는 격리에서 확인했다. 실제 운영의 null 그룹50건 경계는 통과했다. 문서를 만들어 조건을 맞추지 않았다.
- 실제 iOS/Android 앱 화면·기기에서 제공한 토큰·기기 App Check·푸시 수신은 미검증이다. 실제 사용한 정상 발급 Firebase 사용자 ID 토큰·현재 Rules 조회와 구분한다. App Check를 비활성화하거나 우회하지 않았다.
- 과거 lastMessageAt 데이터 보완·시험 메시지·읽음/예약 상태 변경·채팅방 직접 쓰기를 실행하지 않았다. 정상 승인 관리자 로그인/채팅 세션 발급에 따른 세션·멤버십·푸시 토큰 문서 갱신은 있었다. 시험 계정 앱은 필요 시 재로그인/푸시 등록을 갱신한다.
- **API 재시작·SQL 마이그레이션·Functions/Rules 배포·env/키/IAM/S3/기존 배치 변경0**. 최종03:53:28 UTC API는 기존 PID1132783/시작00:54:12 그대로 active/running이었다. env/Rules/Functions/배치 파일의 전후 해시·env600도 동일했다.
- 프론트는 선택한 직접 지점1개 조건, lastMessageAt DESC+문서 ID DESC, limit50, 마지막 원래 시각/null+문서 ID의 커서를 사용한다. 기존 updatedAt·고객 인덱스는 보존돼 있다. 이번 검증 지점은 READY 및 두 역할 조회 조건을 충족했다.

## 근거 파일

- 운영 원본·정식 파일·권한/명령 감사·READY 이력·최종 대조: `build/test-runtime/chat-last-message-indexes-2026-11-26/final-result.json` 및 같은 디렉터리의 `before.private.json`, `verification-result.json`, `readiness-history.json`.
- 실제 인증/조회/차단: `build/test-runtime/chat-index-query-check-2026-11-26/authentication-summary.json`, `query-result.json`.
- 이 실행에 만든 임시 비밀번호/ID 토큰 파일2개는 검증 후 정리했고, 비밀값 없는 인증·조회 근거만 보존했다. 원격 세션을 추가 회수하거나 기존 자격정보를 삭제하지 않았다.
- 격리: `/tmp/nadree-chat-index-rules-20261126-xb6h_vqi/result.json`.
- 런타임 보존: `/home/ec2-user/.nadree-private/chat-last-message-indexes-20261126T034036590283Z/final-integrity.private.json`.

근거 디렉터리700/파일600. 이 문서에는 키·토큰·실제 UID/방 ID·채팅 본문·비밀번호·서명 URL을 기록하지 않았다. Git commit/push는 실행하지 않았다.
