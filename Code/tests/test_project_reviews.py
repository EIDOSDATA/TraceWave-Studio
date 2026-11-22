"""! @brief 화면의 출처와 해석 사전 검토가 보존 개정과 실행 이력을 바꾸지 않는지 확인한다."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application import project_evidence, solver_preview
from rfad.application.canonical import canonical_hash
from rfad.application.pcb_solver import build_pcb_plan, mesh_lines, shape_polygons
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.domain.errors import ProjectError
from test_cad_worker_process import register_fixture, request
from test_pcb_solver import fixture_document, quantity, runtime_identity, SETTINGS
from test_targets import target_input


def read_params(document, **values):
    """! @brief 조회에는 mutation key를 발급하지 않는다."""
    return {"contract_version": "rfad.api/2.0", "context": {"project_id": document["project_id"]},
            "input": {"expected_revision": document["revision_id"], **values}}


class ProjectReviewTests(unittest.TestCase):
    def test_selected_target_history_and_saved_revision_are_read_only(self):
        """! @brief 목표 ID를 따라가며 저장본과 적용 개정, 미정값을 분리해 표시한다."""
        with TemporaryDirectory() as root, ProjectService(Path(root), auto_run=False) as service:
            document, _ = register_fixture(service, fixture_document())
            saved = document["revision_id"]
            target = target_input()
            other = target_input(start=5.0, end=5.2)
            for value in (target, other):
                service.mutate("project.apply_command", request(service, document["project_id"], {
                    "expected_revision": document["revision_id"], "command_id": str(uuid4()),
                    "type": "target.set", "payload": {"target": value},
                }))
                service.run_next()
                document = service._load(service.journal.read()["projects"][document["project_id"]])
            state = service.journal.read()
            result = project_evidence.read(service, read_params(document, target_id=target["id"]))
            self.assertEqual(result["saved_revision"], saved)
            self.assertEqual(result["history_total"], 1)
            self.assertEqual(result["history"][0][3], target["id"])
            self.assertIn("미정", result["records"][0]["values"][1][3])
            self.assertIn("사용자 정합 목표", result["records"][0]["source"])
            self.assertEqual(service.journal.read(), state)
            with self.assertRaises(ProjectError):
                project_evidence.read(service, read_params({**document, "revision_id": saved}))

    def test_saved_revision_reports_description_and_same_count_geometry_changes(self):
        """! @brief 개체 수가 같아도 설명과 연관 치수의 실제 전후값을 표시한다."""
        with TemporaryDirectory() as root, ProjectService(Path(root), auto_run=False) as service:
            saved, _ = register_fixture(service, fixture_document())
            document = saved
            shape = {**document["geometry"][0], "width": quantity(1.2, "mm")}
            for method, payload in (("metadata.describe", {"description": "수정한 한글 설명"}),
                                    ("geometry.set", {"geometry": shape})):
                service.mutate("project.apply_command", request(service, saved["project_id"], {
                    "expected_revision": document["revision_id"], "command_id": str(uuid4()),
                    "type": method, "payload": payload,
                }))
                service.run_next()
                document = service._load(service.journal.read()["projects"][saved["project_id"]])
            state = service.journal.read()
            result = project_evidence.read(service, read_params(document))
            self.assertEqual(len(document["geometry"]), len(saved["geometry"]))
            rows = result["recovery_details"]["rows"]
            self.assertIn(["프로젝트", saved["metadata"]["name"], "설명",
                           saved["metadata"]["description"], "수정한 한글 설명"], rows)
            width = next(row for row in rows if row[0] == "형상" and row[2] == "폭 / 값")
            self.assertTrue(width[3].startswith("1 mm"), width)
            self.assertTrue(width[4].startswith("1.2 mm"), width)
            self.assertFalse(result["recovery_details"]["has_more"])
            self.assertEqual(service.journal.read(), state)

    def test_saved_revision_does_not_pair_removed_and_added_geometry_by_list_index(self):
        """! @brief 같은 개수의 추가와 삭제를 다른 안정 ID의 변경으로 보존한다."""
        saved = fixture_document()
        current = {**saved, "geometry": [{**saved["geometry"][0], "id": str(uuid4())}, saved["geometry"][1]]}
        rows = list(project_evidence._recovery_rows(saved, current))
        self.assertEqual([row[2] for row in rows], ["삭제", "추가"])
        self.assertEqual(rows[0][4], "항목 없음")
        self.assertEqual(rows[1][3], "항목 없음")

    def test_solver_preview_uses_real_plan_without_publishing_snapshot(self):
        """! @brief 실제 계획의 자원값을 사용하고 조회 뒤 파일과 journal을 그대로 보존한다."""
        with TemporaryDirectory() as root, ProjectService(Path(root), auto_run=False) as service:
            document, snapshot = register_fixture(service, fixture_document())
            state = service.journal.read()
            files = sorted(path.relative_to(root) for path in Path(root).rglob("*"))
            with patch.object(service.solver, "runtime", SimpleNamespace(identity=runtime_identity())):
                result = solver_preview.read(service, read_params(document, settings=SETTINGS))
            self.assertGreater(result["estimated"]["estimated_grid_points"], 0)
            self.assertEqual(result["settings"]["grid_mm"], SETTINGS["grid_mm"])
            plan = build_pcb_plan(document, snapshot, runtime_identity(), SETTINGS)
            expected = mesh_lines(plan["case"])
            self.assertEqual(result["mesh"]["lines_mm"], expected)
            self.assertEqual(result["mesh"]["lines_sha256"], canonical_hash(expected))
            self.assertEqual(result["mesh"]["case_sha256"], canonical_hash(plan["case"]))
            self.assertEqual(result["mesh"]["axes"]["z"]["pml_inner_mm"], [expected["z"][8], expected["z"][-9]])
            conductors = {row["id"]: row for row in result["model"]["included"] if row["role"] == "conductor"}
            for shape in plan["case"]["shapes"]:
                row = conductors[shape["id"]]
                self.assertEqual([part["points_mm"] for part in row["primitives"]],
                                 shape_polygons(shape, SETTINGS["curve_tolerance_mm"]))
            self.assertEqual(service.journal.read(), state)
            self.assertEqual(sorted(path.relative_to(root) for path in Path(root).rglob("*")), files)

    def test_solver_preview_rpc_reports_mesh_limit_and_exact_input_field(self):
        """! @brief 실제 GUI가 받는 차단 진단은 상한과 수정할 입력 경로를 유지한다."""
        with TemporaryDirectory() as root, ProjectService(Path(root), auto_run=False) as service:
            document, _ = register_fixture(service, fixture_document())

            def checked_error(settings):
                """! @brief 화면과 동일한 JSON-RPC 응답에서 구조화한 오류를 꺼낸다."""
                payload = {"jsonrpc": "2.0", "id": "preview", "method": "solver.preview",
                           "params": read_params(document, settings=settings)}
                error = handle_frame(json.dumps(payload).encode("utf-8"), service)["error"]
                return error["data"]["domain_code"], error["data"]["diagnostics"][0]["details"]

            before = service.journal.read()
            with patch.object(service.solver, "runtime", SimpleNamespace(identity=runtime_identity())):
                code, details = checked_error({**SETTINGS, "air_padding_mm": 200})
                self.assertEqual(code, "E_RESOURCE")
                self.assertEqual(details["field_path"], "mesh")
                self.assertGreater(details["grid_points_lower_bound"], details["grid_point_limit"])
                code, details = checked_error({**SETTINGS, "air_padding_mm": 1})
                self.assertEqual((code, details["field_path"]), ("E_GEOMETRY", "settings.air_padding_mm"))
            self.assertEqual(service.journal.read(), before)
