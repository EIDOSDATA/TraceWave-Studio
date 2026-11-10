# 프로젝트 명령, 저장과 스냅샷 0.2

이 구현은 RFAD-D0-3.4의 API-002~006, FN-001/002, SYS-036, PRJ-006/007, NFR-004 및 VT-018 일부를 구체화한다. 현재 이름/설명, 리터럴/표현식 매개변수, 기판/재료/적층/선/원호/net/단일 포트와 목적별 입력 검사를 지원한다. 필드는 [설계 데이터 0.2](design_data.md)를 따른다. 선택 속성 편집과 영속 undo/redo는 [편집 확장 profile](editor_contract.md)로 연결했다. 전체 CAD 형식, 범용 migration, 임의 이력 이동과 전체 VT-018 완료를 뜻하지 않는다.

## 실행과 지원 범위

Code에서 실행한다.

```powershell
$env:PYTHONPATH = 'src'
python -X utf8 -m rfad serve --workspace .local/projects-workspace
```

`--workspace`가 있으면 `rfad.projects/0.2` profile을 제공한다. 없으면 기존 읽기 전용 `rfad.bootstrap/0.1`을 유지한다. workspace는 프로젝트 상태와 접수 이력을 함께 관리하는 로컬 서비스 저장 영역이다. 같은 workspace의 두 번째 writer는 E_CONFLICT로 거부한다.

| API | 현재 지원 | 응답 |
| --- | --- | --- |
| capabilities.get | 지원 메서드/명령/schema/limits와 영속 epoch | 작은 직접 응답 |
| project.open | create/open/recover, workspace에 등록된 프로젝트 | queued TaskRef, 이후 terminal event.operation_result |
| project.apply_command | metadata, parameter/표현식, board, material/layer/net/geometry/port 명령 | new_revision, revision_hash, changed_ids, invalidation_set |
| editor.get / editor.apply | 선택 객체 DTO 조회와 표시 단위의 속성 입력. 개발용 확장 | 선택 필드 또는 기존 명령과 같은 변경 결과 |
| project.undo / project.redo | 개정과 영속 이력에 결합된 역명령/원명령 적용. 개발용 확장 | 새 revision과 history 상태 |
| project.save | 현재 프로젝트의 명시적 저장 기준점 지정 | queued TaskRef, 이후 saved_revision/checksum/artifact |
| snapshot.create | 접수 당시 revision의 별도 불변 사본 | queued TaskRef, 이후 SnapshotRef |
| design.validate | 접수 당시 draft revision의 geometry/step/em 입력 검사 | queued TaskRef, 이후 보고서. solver_ready=false |
| job.status | 상태, 마지막 cursor 이후 영속 event와 완료 결과 | 작은 직접 응답 |
| job.cancel | 이 profile의 queued/running 자료 처리 작업 취소 | 최초 확정 terminal 상태 보존 |

project.open의 copy, 외부 독립 프로젝트 import, 다른 target으로 저장, archive/migration/GC는 아직 지원하지 않는다. recover는 현재 journal의 정상 pointer와 hash를 검증해 다시 여는 모드다. 손상된 파일을 임의 수정하거나 과거 revision을 자동 선택하는 복구는 수행하지 않는다.

새 프로젝트에는 project/revision/world/board의 별도 UUID와 오른손 identity 좌표계, 빈 컬렉션을 만든다. 물성, 포트, 결과를 임의 생성하지 않는다. 지원 설계 객체는 명시적 명령으로 편집하고 미구현 핵심 컬렉션의 임의 쓰기는 거부한다. 새 문서는 rfad.project/0.2이며 0.1 원본은 그대로 읽고 다음 편집의 새 개정만 0.2로 전환한다. 미지 extensions의 JSON은 보존하되 실행하지 않는다.

## 명령과 재전송

변경/접수 params에는 `contract_version`, `context`, `input`, `request_key`, `request_key_epoch`를 넣는다. wire 버전은 `rfad.api/2.0`이다. epoch는 capabilities.get에서 얻은 실제 UUID를 사용한다.

project.apply_command의 context는 project_id, input은 expected_revision/command_id/type/payload다. parameter.set의 payload는 id/name/quantity다. quantity.value_si는 이미 SI 값이므로 표시 단위의 배율을 다시 곱하지 않는다. command_id와 parameter id는 정규 UUID 문자열이다.

1. 현재 revision과 expected_revision을 비교한다. 불일치하면 E_CONFLICT다.
2. 원본 사본에 허용한 명령만 적용하고 전체 문서와 단위를 검사한다.
3. 새 revision UUID, 부모 revision, 변경 영향과 역명령을 기록한다.
4. 불변 project.json과 checksum을 준비한다.
5. current revision 참조, 명령 이력, receipt를 같은 journal commit으로 게시한 뒤 ACK한다.

같은 epoch/key/payload는 같은 결과 또는 TaskRef를 반환한다. 같은 키의 다른 method/context/input은 E_CONFLICT다. 동일 command_id를 새로운 request_key로 다시 적용하는 것도 거부한다. 무변경 재전송은 새 디스크 commit을 만들지 않는다.

metadata.set은 이름과 설명을 한 명령으로 적용한다. 일반 명령과 편집 확장의 변경 모두 프로젝트별 최근 128개 원명령 이력을 갱신한다. undo/redo는 과거 revision 포인터를 덮어쓰지 않고 새 revision을 게시하며 저장 기준점과 스냅샷을 유지한다. 이력 head와 현재 revision이 다르면 차단한다. 세부 호환성과 제한은 [편집 계약](editor_contract.md)을 따른다.

epoch의 신규 접수 기간과 receipt 보존 기간은 각각 7일이다. 기존 receipt를 먼저 검사하므로 epoch가 끝나도 해당 receipt 자체의 expires_at 전까지 재조회할 수 있다. receipt가 없고 epoch가 만료/미인식이면 E_IDEMPOTENCY_EXPIRED다. 만료 뒤에는 원 작업/프로젝트를 조회하고 명시적으로 새 요청 여부를 정한다.

## 비동기 자료 처리

open/save/snapshot/design.validate는 실제 background thread에서 순차 실행하며 짧아도 접수 응답을 최종 결과로 바꾸지 않는다. TaskRef에는 job_id/state/events_cursor를 넣는다. queued -> running -> completed 또는 failed를 영속 event로 기록한다. event는 단조 증가 seq, run_id, timestamp, phase와 불확정 진행 상태를 가진다. 현재는 job.status polling으로 읽으며 API-028 push transport는 아직 없다.

save/snapshot/design.validate는 접수 때 검증한 revision의 artifact를 붙잡는다. snapshot과 design.validate는 이후 편집이 발생해도 그 입력으로 생성한다. save는 완료 시 현재 revision이 바뀌었다면 E_CONFLICT로 실패하여 저장 기준점을 되돌리지 않는다.

취소와 완료는 journal의 같은 writer 경계에서 경쟁한다. 실제 파일 transaction이 진행되는 동안에는 중간 상태를 다른 writer가 변경하지 않는다. 파일 작업이 시작되기 전에 취소되면 실행하지 않고 cancelled로 확정한다. 먼저 completed/failed가 게시되면 늦은 취소는 그 terminal을 반환한다. native/WSL 프로세스 취소 구현으로 확대 해석하지 않는다.

장시간 solver는 이 파일 작업 transaction 안에서 호출하지 않는다. 별도 SolverCoordinator가 [해석 worker 계약](solver_contract.md)의 불변 접수/WSL 실행/결과 게시를 처리한다. guest 종료 확인 전에는 취소 완료나 자원 반환을 확정하지 않는다.

재시작 시 queued는 다시 처리할 수 있다. running은 완료를 입증하지 못하므로 interrupted로 남기며 자동 성공/재실행하지 않는다. 정상 동작 중 epoch 갱신은 실행 중인 작업 상태를 바꾸지 않는다. 종료는 현재 파일 transaction을 마친 뒤 worker와 writer lock을 해제한다.

## 저장 배치와 원자적 경계

```text
workspace/
  .writer.lock
  current.json
  commits/<commit_uuid>/
    state.json
    manifest.json
  projects/<name>/
    revisions/<revision_uuid>/project.json
    snapshots/<revision_uuid>/<snapshot_uuid>/project.json
```

초기 저장 profile은 08번의 current-revision pointer 방식이다. current.json이 지정한 검증 manifest/state가 현재 설계, 명시적 저장 기준점, 스냅샷, 명령/작업/receipt를 한 번에 확정한다. 각 revision의 project.json은 실제 설계 원본의 불변 바이트다. 별도의 가변 project.json과 receipt 파일을 각각 교체해 원자성을 주장하지 않는다.

따라서 이 초기 profile에서 프로젝트 하위 폴더만 복사하면 독립적으로 열 수 없다. workspace 전체와 current/commits의 참조가 필요하다. 독립 프로젝트 폴더/인계 archive는 추후 export/migration profile로 제공한다. 원본 역할과 저장된 값은 유지하며 이 배치 차이를 승인 문서의 완료 상태로 소급하지 않는다.

명령 적용 때마다 새 revision을 영속화하므로 서비스 중단 뒤 승인된 변경을 복원할 수 있다. project.save는 사용자가 명시한 saved revision을 별도로 확정한다. autosave draft/사용자 저장 기준점/실행용 snapshot을 같은 것으로 취급하지 않는다. autosave draft 자체는 아직 미구현이다.

게시 순서:

1. 새 immutable payload를 기록하고 flush/fsync 및 read-back 검증한다.
2. 새 state와 manifest에 byte 길이와 SHA256을 기록하고 검증한다.
3. 같은 volume의 임시 pointer를 기록한다.
4. current.json 하나를 마지막에 교체한다.

게시 전 실패는 이전 pointer와 정상 상태를 유지한다. 미게시 파일은 남을 수 있으나 결과로 노출하지 않는다. 게시 뒤 ACK 전에 실패했다면 오류에 `details.committed=true`를 남기며 동일 request_key로 확정 결과를 재조회한다. 읽을 때마다 pointer/manifest/payload와 프로젝트 artifact hash를 확인한다. 손상된 파일을 조용히 재생성하거나 덮어쓰지 않는다.

Windows에서 파일 fsync, 같은 volume 교체, 실제 프로세스 강제 종료와 OS lock 해제를 시험했다. WSL Linux의 ext4 임시 저장소에서도 저장/잠금/복구 시험을 통과했다. 정전/하드웨어 쓰기 cache 장애의 완전한 내구성은 아직 검증하지 않았다. [Python 파일 교체/동기화](https://docs.python.org/3.12/library/os.html), [Windows 파일 잠금](https://docs.python.org/3.12/library/msvcrt.html#msvcrt.locking)을 사용한다.

## 제한과 데이터 보존

- 프로젝트 경로는 workspace 안의 `projects/이름`이다. absolute/상위 이동/Windows 예약 이름과 기존 symlink/reparse 경로를 거부한다.
- create는 이미 존재하는 경로를 덮어쓰지 않는다. 미게시 orphan이 남은 경로도 자동 삭제하지 않는다.
- 프로젝트 32 KiB/32개, 매개변수 128개, 설계 객체 256개(32 KiB 제한도 적용), jobs 512개/대기 32개, receipts와 명령 이력 각각 2048개, snapshots 1024개, epoch 128개가 초기 상한이다.
- journal state와 단일 artifact의 최대 크기는 각각 8 MiB다. 초기 disk admission은 최소 16 MiB 또는 새 상태의 이중 기록에 필요한 여유 중 큰 값을 확인한다. 실제 기록 실패도 별도로 처리한다.
- 오래된 commit과 artifact의 자동 GC는 아직 없으므로 상한/공간 부족은 E_RESOURCE로 접수를 거부한다. 보존 이력을 몰래 삭제하지 않는다.
- mutation batch와 mutation notification은 실행하지 않는다. 조회 batch만 지원하며 변경에는 응답 ID와 영속 request key를 사용한다.
- stdout의 최대 프레임은 기존 64 KiB다. 큰 프로젝트/배열의 chunk/artifact 전송을 지원하는 완료 profile이 아니다.

## AI/MCP와 EDA 연결 경계

GUI와 자동화는 같은 프로젝트 서비스 명령을 사용하도록 구성했다. 후속 MCP adapter도 이 서비스를 호출하고 revision/request key/job ID/snapshot을 보존하는 구조로 연결할 수 있다. 현재 내부 JSON-RPC가 MCP 서버 자체인 것은 아니며 MCP discovery/tool/resource와 호환성 시험은 미구현이다. [MCP 공식 구조](https://modelcontextprotocol.io/docs/learn/architecture)

다른 EDA 도구와의 연계는 AI host가 여러 MCP 서버를 조합하거나 별도 EDA 파일/데이터 adapter를 사용하는 방식이다. 각 도구의 단위/좌표/layer/net/재료/port 의미를 변환해야 하며 MCP 연결만으로 데이터 호환성을 보장하지 않는다. 이번 변경에서 MCP나 EDA 실행 기능을 추가하지 않았다.
