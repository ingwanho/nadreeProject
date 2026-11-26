# 관리자 채팅 lastMessageAt 인덱스 — 병합·검증·서버 배포

**2026-11-26 정식 설정 병합·에뮬레이터 검증 완료, 운영 생성은 권한 부족으로 미적용이다.** 기존 서비스 계정으로 운영 인덱스 조회에는 성공했으나, 새 인덱스 생성은 **403 PERMISSION_DENIED**였다. 실제 생성 0개이며 요청 4개는 모두 MISSING이다. 실패 후 확인 시각은 **2026-11-26 02:55:26 UTC / 한국 11:55:26 / 발리 10:55:26**다.

대상은 Firebase 프로젝트 **bail-472405**, Firestore **(default)**, 컬렉션 그룹 **chatRoomAccess**, 범위 **COLLECTION**이다. [요청 원본](../../backend-chat-last-message-index-request.md)과 [제안 JSON](../../manager-chat-indexes.json)을 기준으로 작업했다.

## 정식 설정과 네 조회 형태

배포할 파일은 **[chat/firestore.indexes.json](../chat/firestore.indexes.json)** 하나다. 제안 JSON을 단독 배포 파일로 사용하지 않는다.

| 관리자 조회 조건 | 추가 인덱스 필드 | 운영 상태 |
| --- | --- | --- |
| 지점의 전체 대화 | shopId ASC → lastMessageAt DESC → __name__ DESC | MISSING |
| 대화 유형 필터 | shopId ASC → kind ASC → lastMessageAt DESC → __name__ DESC | MISSING |
| 상태 필터 | shopId ASC → status ASC → lastMessageAt DESC → __name__ DESC | MISSING |
| 유형·상태 필터 | shopId ASC → kind ASC → status ASC → lastMessageAt DESC → __name__ DESC | MISSING |

공식 JSON의 마지막 `lastMessageAt DESC` 뒤에는 Firestore가 기본 `__name__ DESC`를 추가하므로 제안 JSON처럼 생략했다. [기본 문서 이름 정렬 규칙](https://firebase.google.com/docs/firestore/query-data/index-overview#default_ordering_and_the_name_field)을 따른다.

기존 정식 파일 4개는 그대로 보존했다. 운영 조회에서 발견한 기존 11개 중 저장소에 없던 7개도 병합했다. 이 7개는 관리자 updatedAt 필터 3개와 고객 lastMessageAt 필터 4개이며 이미 운영 READY 상태였다. 따라서 정식 파일은 **운영 기존 11개 + 요청 신규 4개 = 15개**다. 기존 고객·관리자 조회를 지원하는 항목을 삭제하거나 대체하지 않는다. 기존 fieldOverrides도 변경하지 않았다.

이번 작업에 채팅 함수·Firestore Rules·updatedAt 갱신 로직·메시지 데이터·SQL 스키마·REST API·env 변경은 없다. 과거 데이터 변경과 lastMessageAt 필드 보완도 제외했다.

## 관리자 앱 조회 계약

```javascript
import {
  collection, query, where, orderBy, documentId, limit, startAfter
} from 'firebase/firestore';

const filters = [where('shopId', '==', selectedShopId)];
if (selectedKind) filters.push(where('kind', '==', selectedKind));
if (selectedStatus) filters.push(where('status', '==', selectedStatus));

const constraints = [
  ...filters,
  orderBy('lastMessageAt', 'desc'),
  orderBy(documentId(), 'desc'),
  limit(50)
];
if (lastDocument) {
  constraints.push(startAfter(lastDocument.get('lastMessageAt'), lastDocument.id));
}
const roomsQuery = query(collection(db, 'chatRoomAccess'), ...constraints);
```

유형 값은 `booking`/`inquiry`, 상태 값은 `open`/`read_only`다. UI의 Bookings/Inquiries 및 Open/Closed를 이 값에 대응한다. 전체 선택은 해당 where 조건을 생략한다. 한 번에 직접 소속 지점 하나만 조회하며 대표·일반관리자 모두 기존 읽기 권한을 사용한다. 답변 권한은 기존 대표관리자 제한을 유지한다.

문서 ID 없이 시각 하나만 커서로 쓰면 같은 시각의 방을 건너뛸 수 있으므로 두 값을 함께 사용한다. null도 원래 값 그대로 전달하며 updatedAt·createdAt으로 대체하지 않는다. 명시적 null은 포함되고, lastMessageAt 필드가 없는 문서는 제외된다. 이번 요청에 누락 필드 일괄 보완은 없다. [Firestore 페이지 커서 안내](https://firebase.google.com/docs/firestore/query-data/query-cursors)를 참고한다.

## 확인한 검증 범위

- Firebase CLI의 인덱스 스키마 검증 통과. 기존 4개 보존·요청 4개 일치와 중복 없음, 운영 기존 11개가 정식 파일에 모두 포함됨을 대조했다.
- `CI=1 npm test`를 demo-nadree-chat Firestore 에뮬레이터에서 실행했다. **TAP 24 passed / 0 failed / 0 skipped**이며 상위 6개 검사와 하위 18개 조합을 포함하는 수다.
- 대표·일반관리자 각각 전체/Bookings/Inquiries × 전체/Open/Closed의 9개 조합, 총 18개 조합에서 50건 페이지 처리를 확인했다.
- 조합마다 110개씩 총 440개 가상 방을 사용했다. 같은 시각 55개와 null 55개가 페이지 경계를 넘도록 구성해 문서 ID 순서·전체 결과·중복/누락 없음을 확인했다. 시각 필드 없는 기존 가상 문서가 정렬에서 제외되는 것도 확인했다.
- 다른 지점의 9개 필터 조합과 지점 없는 전역 목록, 무인증·다른 사용자·이전 채팅 세션 접근을 거절하는지 확인했다. 기존 클라이언트 직접 쓰기 금지도 통과했다.
- 운영 조회에서는 기존 11개 READY, 신규 4개 MISSING을 확인했다. 생성 요청 403 이후에도 기존 11개의 ID·정의가 보존됐으며 새 생성은 0개다.

에뮬레이터는 복합 인덱스 유무를 강제하지 않으므로 위 검사를 운영 인덱스 준비 완료로 해석하지 않는다. [에뮬레이터의 인덱스 한계](https://firebase.google.com/docs/emulator-suite/connect_firestore#indexes)를 따른다. 운영 인덱스 생성·READY 전환과 실제 앱 토큰을 사용한 필터 조회는 아직 미검증이다.

키·토큰·채팅 본문·회원번호는 결과에 기록하지 않았다. 운영 Firestore 문서·Rules·Functions·IAM은 변경하지 않았다. 조회/실패/최종 상태 근거는 작업 환경의 접근 제한된 `/private/tmp/nadree-chat-indexes-before-2026-11-26.json`, `/private/tmp/nadree-chat-indexes-applied-2026-11-26.json`에 보관했다. 운영 데이터 스냅샷이 아니라 인덱스 정의·생성 상태 메타데이터다.

## 인증된 서버에서 적용

새 코드를 Git에 반영하고, 인덱스 생성 권한이 있는 승인된 Firebase 배포 계정으로 진행한다. 현재 로컬 CLI는 미로그인이고 기존 앱 서비스 계정은 생성 권한이 없으므로 같은 계정으로 반복 실행해도 해결되지 않는다. 기존 키를 교체하거나 새 키를 만들지 않는다.

```bash
cd /srv/nadree-api
git status --short
git pull --ff-only origin main
cd chat
npx firebase firestore:indexes --project bail-472405 --database '(default)' --pretty
npx firebase deploy --only firestore:indexes --project bail-472405 --non-interactive
```

서버 로컬 수정은 보존한다. 배포 전에 운영 인덱스와 fieldOverrides를 백업·대조한다. 이 파일에 없는 다른 컬렉션의 인덱스나 별도 fieldOverrides가 발견되면 그 항목도 정식 설정에 보존하고 검토한 뒤 배포한다. API 재시작·Functions/Rules 배포·DB 마이그레이션은 필요 없다.

**`--force`를 추가하지 않는다.** 확인한 firebase-tools 13.35.1은 원격에만 있는 인덱스/fieldOverrides가 있으면 비대화형 배포를 삭제 확인 단계에서 중단한다. 이때 강제로 삭제하지 않고 원격 항목을 정식 파일에 병합한 뒤 다시 실행한다. 대화형 배포에서 삭제 질문이 나오면 No를 선택한다. 다른 CLI 버전이면 동일한 보존 동작을 먼저 확인한다.

배포 명령 성공만으로 READY를 확정하지 않는다. 아래 조회나 콘솔 Firestore → Indexes에서 위 네 정의가 모두 **READY / 사용 설정됨**으로 바뀔 때까지 확인한다.

```bash
npx firebase firestore:indexes --project bail-472405 --database '(default)' --pretty
```

## 배포 후 공동 확인·회신

승인된 대표·일반관리자 테스트 계정의 실제 채팅 토큰으로 9개 필터 조합을 조회한다. 운영 문서 변경이나 시험 메시지 발송 없이 현재 허용된 데이터로 확인하고, 다른 지점과 전역 목록의 접근 거절도 확인한다. Admin SDK로 읽은 결과만으로 앱 Rules 검증을 통과했다고 기록하지 않는다. 같은 시각·null 데이터가 운영에 없으면 해당 경계는 에뮬레이터 근거로 남기고, 운영 데이터에 임의로 값을 채우지 않는다.

결과 문서에는 프로젝트·DB·적용/READY 확인 시각, 네 인덱스 ID·상태, 기존 11개 보존, 역할별 9개 조합의 결과 건수/오류, 페이지 중복·누락, 다른 지점 차단, 미검증을 구분해 기록한다. 실제 room ID·UID·토큰·대화 본문은 공유 문서에 넣지 않는다. 실패 시 기존 인덱스와 조회 계약을 보존하고, 신규 인덱스를 급히 삭제해 복구하려 하지 않는다. 앱 전환 시점은 네 인덱스 READY 및 공동 확인 이후로 한다.
