# 문서 전수 목록과 경로 대응

현재 개발 문서는 모두 [01_개발문서 안내](../README.md)에서 찾는다. 기존 00~25 현행 편집본도 분야별 폴더에 배치했고 승인 당시 사본은 12_보관이력/01_승인기준선에 둔다.

| 목록 | 내용 |
| --- | --- |
| [기존 설계 번호별 분류](04_기존설계분류.md) | 현행 편집본과 승인 당시 원문을 각각 연결 |
| [참고 자료 분류](05_참고자료분류.md) | 원문/논문/제조 자료/추출/수집 감사의 역할 |
| [전수 파일 집계](03_문서집계.md) | 분류별 수량과 동일 바이트 그룹 |
| [기계 목록](02_문서목록.json) | 경로/분류/검토 수준/크기/작업트리 SHA256 |
| [이전 경로 대응](01_이전경로대응.json) | 과거 Code/docs 및 기존 01_개발문서 루트 경로의 현재 위치 |
| [통합 검토 기록](../11_검토기록/01_문서통합_검토.md) | 실제 삭제/수정/보강, 검증 및 남은 의존성 |

Code/docs는 제거했다. 개발 문서의 복제본이나 전달용 README는 유지하지 않는다. 제품/GUI README는 빌드/사용 진입 안내만 두고 정식 문서로 연결한다. 참고자료 내부는 사용자가 복구하며 이번 개발 문서 변경 대상에서 제외한다. Code/runtime_profiles의 과거 실행 파일도 그대로 보존한다. 당시 기록 속 경로는 path_map과 해당 Git 커밋으로 찾는다.

기계 목록의 working_tree_sha256은 현재 파일 바이트이며 승인 manifest의 LF 정규화 hash나 Git blob hash와 다르다. 같은 바이트라도 출처/이력 역할이 다르면 자동 삭제하지 않는다. PDF 파일 목록을 만들었다는 사실은 전 페이지 기술 내용 검토가 아니다. 알려진 출처 문제는 [분석 검토](../11_검토기록/05_해석과_참고자료_검토.md)에 유지한다.

## 갱신과 검사

Code 디렉터리에서 실행한다. 문서 도구는 01_개발문서를 읽고 갱신한다.

```powershell
.venv/Scripts/python.exe -X utf8 tools/documentation/catalog_documents.py
.venv/Scripts/python.exe -X utf8 tools/documentation/check_documents.py --report ../01_개발문서/11_검토기록/06_문서검증_기록.json
.venv/Scripts/python.exe -X utf8 tools/build_implementation_audit.py --check
```

문서 검사는 현재 Markdown 로컬 링크, DrawIO/SVG 라벨과 연결, PNG 크기 및 승인 사본 27개의 정규화 hash를 확인한다. 보관 원문의 당시 상대 경로는 수정하지 않고 현재 링크 검사에서 제외한다. 외부 URL 최신 상태/모든 렌더러의 heading fragment/native DrawIO 왕복/제품 GUI/RF 수용은 이 검사의 범위가 아니다. 구현 감사 --check는 해당 코드/문서 개정의 입력 hash와 일치해야 하며 미커밋 제품 변경이 있으면 게시 기준 생성물과 달라질 수 있다.
