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
from rfad.domain.object_names import name_prefix
from rfad.domain.resource_limits import MAX_DOCUMENT_BYTES, MAX_SELECTION_RESULT_BYTES
from rfad.domain.units import Quantity
from test_cad_worker_process import CODE_ROOT, register_fixture
from test_cad_projection import cad_fixture


def large_project(*, legacy_names=False):
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
    if legacy_names:
        document["schema_version"] = "rfad.project/0.5"
        for row in document["geometry"]:
            row.pop("name", None)
        stored = document["geometry"][-1]
        stored["name"] = name_prefix(stored) + " 00103"
        document["geometry"][-2]["name"] = "사용자 도체"
        loss = Quantity.missing("dimensionless", "1").to_dict()
        loss["source_refs"] = ["시험: 사용자 제조 조건 미정"]
        document["materials"][0]["tan_delta"] = loss
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

    def test_legacy_design_keeps_assigned_and_temporary_labels_separate(self):
        """! @brief 같은 접두어의 명시 번호를 피하고 세 표시 경로에서 임시 상태를 일치시킨다."""
        with TemporaryDirectory(prefix="rfad legacy names ") as temporary, ProjectService(Path(temporary), auto_run=False) as service:
            document, _ = register_fixture(service, large_project(legacy_names=True))
            before = service.journal.read()
            query = {"expected_revision": document["revision_id"]}
            lookup = {row["id"]: row for row in document["geometry"]}
            views = []
            for method, key in (("editor.get", "items"), ("canvas.get", "shapes"), ("precision.get", "items")):
                with self.subTest(method=method):
                    fields = {"selection_ids": []} if method == "precision.get" else {"display_profile": PROFILE}
                    result = call(service, method, document, {**query, **fields})["result"]
                    views.append({row["id"]: (row["name"], row["name_state"], row["label"]) for row in result[key] if row["id"] in lookup})
            self.assertEqual(views[0], views[1])
            self.assertEqual(views[0], views[2])
            self.assertEqual(len(views[0]), len(lookup))
            for identity, obj in lookup.items():
                name, state, label = views[0][identity]
                if "name" in obj:
                    self.assertEqual((name, state, label), (obj["name"], "stored", obj["name"]))
                else:
                    self.assertEqual((name, state), (None, "temporary"))
                    self.assertNotIn(identity[:8], label)
            stored = document["geometry"][-1]
            prefix = name_prefix(stored)
            legacy_ids = sorted(row["id"] for row in lookup.values() if "name" not in row and name_prefix(row) == prefix)
            self.assertGreater(len(legacy_ids), 200)
            self.assertEqual([views[0][identity][2] for identity in legacy_ids],
                             [f"{prefix} {number:02d}" for number in range(104, 104 + len(legacy_ids))])
            self.assertEqual(service.journal.read(), before)

    @unittest.skipUnless(sys.platform == "win32" and os.environ.get("RFAD_GUI_EXE"), "Windows Studio 실행 파일이 필요합니다.")
    def test_windows_reopens_a_project_larger_than_legacy_views(self):
        """! @brief 표시 응답이 큰 명시 이름 설계를 실제 Windows에서 저장하고 다시 연다."""
        self._assert_windows_reopens(large_project(), "edit-view-transport.json")

    @unittest.skipUnless(sys.platform == "win32" and os.environ.get("RFAD_GUI_EXE"), "Windows Studio 실행 파일이 필요합니다.")
    def test_windows_reopens_legacy_design_with_temporary_labels(self):
        """! @brief 실제 Windows에서 구버전 무명 도체와 미정 재료를 저장하고 다시 연다."""
        self._assert_windows_reopens(large_project(legacy_names=True), "edit-view-legacy-names.json")

    def _assert_windows_reopens(self, fixture, output_name):
        """! @brief 두 서비스 세션의 저장 개정과 도체/미정 재료 원본을 대조한다."""
        with TemporaryDirectory(prefix="rfad Windows 큰 표시 ") as temporary:
            directory = Path(temporary)
            workspace = directory / "한글 작업 영역"
            with ProjectService(workspace, auto_run=False) as service:
                document, _ = register_fixture(service, fixture)
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
                (Path(output) / output_name).write_bytes(report.read_bytes())
