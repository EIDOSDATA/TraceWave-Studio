# 문서 전수 목록과 분류

기준일: 2026-11-16 KST. 저장소의 작성 설계 문서와 참고 원문/추출/검증 파일을 목적과 검토 수준으로 구분한다. 파일 목록에 포함된 것과 전문 기술 내용이 검증된 것은 다르다.

| 목록 | 내용 |
| --- | --- |
| [전체 문서 안내](../README.md) | 현재 분야별 폴더와 대표 문서 |
| [승인 설계 26개](approved_design.md) | 원래 번호/ID/내용을 유지한 분야별 연결 |
| [참고 자료 분류](reference_materials.md) | 원문/논문/제조 자료/추출/분석/수집 당시 감사의 역할 |
| [전수 파일 집계](inventory_summary.md) | 분류별 수량, 중복 바이트 그룹과 검토 범위 |
| [기계 판독 전수 목록](inventory.json) | 각 파일 경로/분류/검토 수준/크기/작업트리 SHA256/텍스트 읽기 상태 |
| [이전 경로와 현재 위치](path_map.json) | 개발 Markdown 48개와 이전 시안 자산 4개의 이동 대응 |
| [내용 검토와 정정](../review/README.md) | 시스템/기능/분석별 문서 검토, 구체 교정과 열린 의존성 |

`01_Docs`, `00_REF`, `Code/runtime_profiles`는 보존 위치다. 승인 및 원문 자료는 현재 폴더로 복사하지 않고 이 목록에서 연결한다. 개발 문서는 실제로 분야별 폴더로 이동했으며 completion_plan/development_status/implementation_audit의 옛 진입 파일 세 개만 짧은 위치 안내로 남겼다.

기계 목록의 `working_tree_sha256`은 이 작업트리에서 읽은 바이트다. 출처 manifest의 정본 해시, 승인 문서의 LF 정규화 해시 또는 Git blob 해시와 혼동하지 않는다. 서로 다른 역할의 파일이 같은 바이트여도 자동으로 삭제하지 않는다. 원문 무결성의 실제 비교와 알려진 불일치는 [분석 검토](../review/analysis_review.md)에 있다.

## 갱신과 검사

Code에서 다음 명령을 실행한다. 목록 생성은 과거 자료를 수정하지 않으며 최신 문서/자료 파일의 분류를 다시 계산한다.

```powershell
.venv/Scripts/python.exe -X utf8 tools/documentation/catalog_documents.py
.venv/Scripts/python.exe -X utf8 tools/documentation/check_documents.py --report .local/documentation-checks.json
```

Markdown 로컬 파일 링크/DrawIO 셀과 연결/SVG 동일 라벨/PNG 크기를 검사한다. 외부 웹 URL의 현재 내용, 모든 Markdown fragment의 렌더러별 동일성, native DrawIO 재열기, Studio 실제 GUI와 RF 시험은 이 명령의 범위가 아니다. 최종 문서 검토 보고서의 명령/범위를 함께 확인한다.
