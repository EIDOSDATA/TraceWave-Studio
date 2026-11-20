"""! @brief 큰 프로젝트의 표시 조회, 호환 실패, Windows 편집 후 재열기를 확인한다."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID, uuid4

from rfad.application.canonical import canonical_bytes
from rfad.application.edit_view_contract import PROFILE
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.domain.design import DESIGN_COLLECTIONS, MAX_ENTITIES
from rfad.domain.resource_limits import MAX_DOCUMENT_BYTES, MAX_SELECTION_RESULT_BYTES
from rfad.domain.units import Quantity
from test_cad_worker_process import CODE_ROOT, register_fixture
from test_cad_projection import cad_fixture


def large_project():
    """! @brief 저장 한도 안에서 전체 이름과 도체 좌표가 60 KiB 조회 한도를 넘는 설계를 구성한다."""
    document = cad_fixture()
    amount = MAX_ENTITIES - sum(len(document[key]) for key in DESIGN_COLLECTIONS)
    shape = next(item for item in document["geometry"] if item["kind"] == "line_path")
    for index in range(amount):
        row = deepcopy(shape)
        row.update(id=str(UUID(int=index + 1000)), name=f"시험 도체 {index:03d} " + "한글이름" * 36)
        y = 1 + index / 10
        row["start"] = [Quantity.from_value(value, "mm").to_dict() for value in (15, y)]
        row["end"] = [Quantity.from_value(value, "mm").to_dict() for value in (28, y)]
        row["width"] = Quantity.from_value(0.05, "mm", source_refs=["fixture: geometry width"]).to_dict()
        document["geometry"].append(row)
    return document


def call(service, method, document, data):
    """! @brief 실제 NDJSON 조회 경계에서 같은 요청 ID와 표시 계약을 유지하는지 검사한다."""
    request = {"jsonrpc": "2.0", "id": "표시 시험", "method": method,
               "params": {"contract_version": "rfad.api/2.0", "context": {"project_id": document["project_id"]},
                          "input": data}}
    return handle_frame(canonical_bytes(request), service)


class EditViewTransportTests(unittest.TestCase):
    """! @brief 같은 원본을 작은 조회 계약과 별도 표시 한도로 대조한다."""

    def test_large_views_use_negotiated_limit_and_do_not_mutate(self):
        """! @brief 새 전송 계약이 기존 거부, 오류 ID, 모든 이름과 개정 소유권을 보존한다."""
        with TemporaryDirectory(prefix="rfad large edit ") as temporary, ProjectService(Path(temporary), auto_run=False) as service:
            document, _ = register_fixture(service, large_project())
            self.assertLess(len(canonical_bytes(document)), MAX_DOCUMENT_BYTES)
            bootstrap = {"jsonrpc": "2.0", "id": 1, "method": "capabilities.get",
                         "params": {"contract_version": "rfad.api/2.0", "context": {}, "input": {}}}
            capability = handle_frame(canonical_bytes(bootstrap), service)["result"]
            self.assertEqual(capability["edit_view_transport"], {"profile": PROFILE, "max_dto_bytes": MAX_SELECTION_RESULT_BYTES})
            before = service.journal.read()
            revision = document["revision_id"]
            for method, key in (("editor.get", "items"), ("canvas.get", "shapes")):
                with self.subTest(method=method):
                    old = call(service, method, document, {"expected_revision": revision})
                    self.assertEqual(old["id"], "표시 시험")
                    self.assertEqual(old["error"]["data"]["domain_code"], "E_RESOURCE")
                    query = {"expected_revision": revision, "display_profile": PROFILE}
                    view = call(service, method, document, query)["result"]
                    actual_bytes = len(json.dumps(view, ensure_ascii=False).encode("utf-8"))
                    self.assertGreater(actual_bytes, 60 * 1024)
                    self.assertLessEqual(actual_bytes, MAX_SELECTION_RESULT_BYTES)
                    self.assertEqual(view["revision_id"], revision)
                    labels = {row["id"]: row["label"] for row in view[key]}
                    for row in document["geometry"]:
                        self.assertIn(row["id"], labels)
                        if "name" in row:
                            self.assertEqual(labels[row["id"]], row["name"])
                    unsupported = call(service, method, document, {**query, "display_profile": None})
                    self.assertEqual(unsupported["error"]["data"]["domain_code"], "E_VERSION")
                    stale = call(service, method, document, {**query, "expected_revision": str(uuid4())})
                    self.assertEqual(stale["error"]["data"]["domain_code"], "E_CONFLICT")
            self.assertEqual(service.journal.read(), before)

    @unittest.skipUnless(sys.platform == "win32" and os.environ.get("RFAD_GUI_EXE"), "Windows Studio 실행 파일이 필요합니다.")
    def test_windows_reopens_a_project_larger_than_legacy_views(self):
        """! @brief 실제 새 GUI가 선택 DTO와 장면을 읽고 저장 후 원문 설계를 그대로 연다."""
        with TemporaryDirectory(prefix="rfad Windows 큰 표시 ") as temporary:
            directory = Path(temporary)
            workspace = directory / "한글 작업 영역"
            with ProjectService(workspace, auto_run=False) as service:
                document, _ = register_fixture(service, large_project())
                path = service.journal.read()["projects"][document["project_id"]]["path"]
            report = directory / "화면 실행 기록.json"
            gui = Path(os.environ["RFAD_GUI_EXE"]).resolve()
            result = subprocess.run(
                [str(gui), "--python", sys.executable, "--source", str(CODE_ROOT / "src"), "--workspace", str(workspace),
                 "--open-project", path, "--smoke-test", "--smoke-report", str(report)],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=100, check=False,
            )
            self.assertTrue(report.is_file(), (result.returncode, result.stderr))
            view = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(result.returncode, 0, view)
            self.assertTrue(view["passed"] and view["snapshot_id"])
            self.assertEqual(view["service_sessions"], 2)
            self.assertEqual(view["revision_id"], view["saved_revision"])
            with ProjectService(workspace, auto_run=False) as service:
                saved = service._load(service.journal.read()["projects"][document["project_id"]])
                self.assertEqual(saved["revision_id"], view["saved_revision"])
                for key in ("board", "geometry", "materials", "stackup", "ports"):
                    self.assertEqual(saved[key], document[key], key)
            if output := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                (Path(output) / "edit-view-transport.json").write_bytes(report.read_bytes())
