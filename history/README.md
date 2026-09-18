# 작업 도구 이력

[W00~W02 일회성 작업 도구 보관본](w00-w02-tools-2026-09-14.zip)

기존 `/private/tmp`에 있던 이번 구현의 편집·반영·검증 도구와 당시 파일 해시 기록을 옮겨 보관한다. 현재 API 코드나 명세의 원본은 이 압축 파일이 아니다.

| 압축 내부 파일 | 용도 |
| --- | --- |
| `sync_nadree_w02_docs.py.txt` | 당시 MD·엑셀 일괄 편집 스크립트 |
| `publish_nadree_w02.py.txt` | 당시 지정 폴더 반영·가상환경 설치 스크립트 |
| `validate_nadree_w02.py.txt` | 임시 경로와 당시 해시를 사용하던 검증 스크립트 원본 |
| `publication-manifest.json` | 당시 반영 대상·보존 파일의 해시 기록 |
| `organize_project_files.py.txt` | 이번 파일 정리·이동 작업 기록 |

일회성 Python 파일은 실수로 재실행하지 않도록 `.py.txt`로 보관한다. 과거 경로·당시 버전에 종속되므로 현재 파일에 다시 적용하지 않는다. 비밀값·가상환경·테스트 DB·중복 소스 사본은 압축하지 않았다.

현재 사용하는 검증 도구는 [scripts/validate_w02_spec.py](../scripts/validate_w02_spec.py)다. 프로젝트 위치에서 상대 경로로 파일을 찾으며 과거 발행 해시 기록은 요구하지 않는다.

전체 현재 파일은 [프로젝트 파일 안내](../../README.md)에서 확인한다.
