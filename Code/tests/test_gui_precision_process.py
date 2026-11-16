"""! @brief 실제 Windows 폼의 실패 복구, 정밀 편집과 저장 출처 보존을 검증한다."""

from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.adapters.planar_backend import runtime
from rfad.application.projects import ProjectService
from rfad.domain.precision_command import EXTENSION_KEY, validate_precision_origins
from rfad.domain.project import validate_project
from rfad.domain.units import Quantity
from test_cad_worker_process import register_fixture
from test_design_rules import scenario


ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")


@unittest.skipUnless(sys.platform == "win32" and GUI, "RFAD_GUI_EXE로 Windows GUI를 지정합니다.")
class GuiPrecisionTests(unittest.TestCase):
    """! @brief GUI 후보 적용을 재시작한 독립 서비스의 저장 원본과 비교한다."""

    def test_rename_precision_recovery_atomic_history_and_source_preservation(self):
        """! @brief 중복 이름/null 후보/검토 무효화/원자 이력과 미정 보존을 한 작업으로 확인한다."""
        with TemporaryDirectory(prefix="TraceWave 정밀 GUI ") as temporary:
            workspace = Path(temporary) / "작업 영역"
            original = scenario()
            identity = original["geometry"][0]["id"]
            original["geometry"][0]["name"] = "검증 대상 선"
            original["geometry"][1]["name"] = "중복 이름"
            parameter = str(uuid4())
            original["parameters"][parameter] = {"id": parameter, "name": "검증 선폭",
                "quantity": Quantity.from_value(2, "mm", source_refs=["명시한 선폭 매개변수"]).to_dict()}
            for material in original["materials"]:
                if material["name"] == "Explicit test substrate":
                    material["tan_delta"] = Quantity(None, "dimensionless", "1", "missing", ["제작 대역 Df 자료 미정"]).to_dict()
            original["extensions"]["test.reference"] = {
                "source_ref": "직접 입력의 원래 출처 사본", "manufacturing_condition": None,
                "measurement_condition": None,
            }
            validate_project(original)
            with ProjectService(workspace, auto_run=False) as service:
                _, snapshot = register_fixture(service, original)
            report_path = Path(temporary) / "정밀 편집 검증.json"
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.run([
                str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(ROOT / "src"),
                "--workspace", str(workspace), "--open-project", "projects/CAD 한글 교환 검증",
                "--precision-editor-smoke-test", "--smoke-report", str(report_path)],
                stdin=subprocess.DEVNULL, capture_output=True, startupinfo=startup, timeout=210, check=False)
            self.assertTrue(report_path.is_file(), (process.returncode, process.stderr))
            report = json.loads(report_path.read_bytes())
            if output := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                destination = Path(output) / "precision-editor.json"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(report_path.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            self.assertTrue(report["passed"], report)
            self.assertGreaterEqual(report["service_sessions"], 2, report)
            expected = {
                "rename_duplicate_rejection_keeps_draft", "rename_and_search_keep_stable_selection",
                "precision_null_scene_keeps_original_and_recovers", "precision_input_change_invalidates_review",
                "precision_dimension_atomic_apply", "precision_rotate_one_command_undo_redo_selection",
                "precision_parameter_binding_and_readonly_reopen",
                "precision_saved_service_restart_preserves_geometry",
            }
            self.assertEqual(set(report["setup_checks"]), expected, report)
            with ProjectService(workspace, auto_run=False) as service:
                journal = service.journal.read()
                stored = service._load(journal["projects"][original["project_id"]])
                self.assertEqual(stored["revision_id"], report["saved_revision"])
                for key in ("board", "materials", "stackup", "ports", "targets", "connections", "manufacturing_profiles", "parameters"):
                    self.assertEqual(stored[key], original[key], key)
                self.assertEqual({key: value for key, value in stored["extensions"].items() if key != EXTENSION_KEY}, original["extensions"])
                before = original["geometry"][0]
                after = next(row for row in stored["geometry"] if row["id"] == identity)
                untouched = next(row for row in stored["geometry"] if row["id"] != identity)
                self.assertEqual(untouched, original["geometry"][1])
                self.assertEqual(after["name"], "급전 선 검증")
                for key in before.keys() - {"name", "start", "end", "width"}:
                    self.assertEqual(after[key], before[key], key)
                self.assertEqual(after["width"], {"parameter_id": parameter})
                start = [Quantity(**value).as_unit("mm") for value in before["start"]]
                end = [Quantity(**value).as_unit("mm") for value in before["end"]]
                length = math.dist(start, end)
                extended = [start[index] + (end[index] - start[index]) * 8 / length for index in range(2)]
                for key, point in (("start", start), ("end", extended)):
                    expected_point = [16 - point[0], 12 - point[1]]
                    for index, value in enumerate(after[key]):
                        self.assertAlmostEqual(Quantity(**value).as_unit("mm"), expected_point[index])
                        self.assertEqual(value["source_refs"], before[key][index]["source_refs"])
                validate_precision_origins(stored)
                records = stored["extensions"][EXTENSION_KEY]["records"]
                self.assertEqual({row["operation"] for row in records}, {"dimension_set", "rotate", "bind_dimension"})
                self.assertEqual(len(records), 3)
                dimension = next(row for row in records if row["operation"] == "dimension_set")
                binding = next(row for row in records if row["operation"] == "bind_dimension")
                self.assertEqual(binding["parameters"][parameter], original["parameters"][parameter])
                renamed = deepcopy(before)
                renamed["name"] = "급전 선 검증"
                self.assertEqual(dimension["before"], [renamed])
                sealed = workspace / snapshot["artifact"]["uri"]
                self.assertEqual(hashlib.sha256(sealed.read_bytes()).hexdigest(), snapshot["artifact"]["sha256"])
                self.assertTrue(all("solver" not in row for row in journal["jobs"].values()))

    @unittest.skipUnless(runtime()[1]["available"], "고정 Shapely/GEOS 평면 엔진이 필요합니다.")
    def test_planar_multiselection_empty_recovery_mirror_and_restart(self):
        """! @brief 실제 체크 목록에서 집합/오프셋/미러를 검토하고 원본 사본을 독립 확인한다."""
        with TemporaryDirectory(prefix="TraceWave 평면 GUI ") as temporary:
            workspace = Path(temporary) / "작업 영역"
            original = scenario()
            original["ports"] = []
            original["targets"] = []
            original["connections"] = []
            net = original["geometry"][0]["net_id"]
            for index, shape in enumerate(original["geometry"]):
                for key in ("start", "end", "width"):
                    del shape[key]
                left = 1 + index * 3
                shape.update(kind="planar_region", name="연산 영역 " + ("A" if index == 0 else "B"),
                             role="radiator", net_id=net, holes=[],
                             outer=[[Quantity.from_value(value, "mm", source_refs=["직접 입력 영역 " + str(index)]).to_dict()
                                     for value in point] for point in [(left, 1), (left + 5, 1), (left + 5, 6), (left, 6)]])
            for material in original["materials"]:
                if material["name"] == "Explicit test substrate":
                    material["tan_delta"] = Quantity(None, "dimensionless", "1", "missing", ["제작 Df 미정"]).to_dict()
            validate_project(original)
            with ProjectService(workspace, auto_run=False) as service:
                _, snapshot = register_fixture(service, original)
            report_path = Path(temporary) / "평면 편집 검증.json"
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.run([
                str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(ROOT / "src"),
                "--workspace", str(workspace), "--open-project", "projects/CAD 한글 교환 검증",
                "--precision-planar-smoke-test", "--smoke-report", str(report_path)],
                stdin=subprocess.DEVNULL, capture_output=True, startupinfo=startup, timeout=210, check=False)
            self.assertTrue(report_path.is_file(), (process.returncode, process.stderr))
            report = json.loads(report_path.read_bytes())
            if output := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                destination = Path(output) / "precision-planar.json"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(report_path.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            self.assertTrue(report["passed"], report)
            self.assertGreaterEqual(report["service_sessions"], 2, report)
            self.assertEqual(set(report["setup_checks"]), {
                "planar_target_order_difference_intersection_union_preview",
                "planar_union_atomic_replacement_selection", "planar_empty_offset_blocks_without_deleting_source",
                "planar_offset_mirror_apply_undo_redo", "planar_saved_service_restart_preserves_geometry",
            }, report)
            with ProjectService(workspace, auto_run=False) as service:
                journal = service.journal.read()
                stored = service._load(journal["projects"][original["project_id"]])
                self.assertEqual(stored["revision_id"], report["saved_revision"])
                for key in ("board", "materials", "stackup", "ports", "targets", "connections", "manufacturing_profiles", "parameters"):
                    self.assertEqual(stored[key], original[key], key)
                self.assertEqual(len(stored["geometry"]), 1)
                shape = stored["geometry"][0]
                self.assertNotIn(shape["id"], {row["id"] for row in original["geometry"]})
                self.assertTrue(shape["name"])
                points = [[Quantity(**value).as_unit("mm") for value in point] for point in shape["outer"]]
                self.assertEqual([min(point[0] for point in points), min(point[1] for point in points),
                                  max(point[0] for point in points), max(point[1] for point in points)], [0, 5, 10, 12])
                area = abs(sum(first[0] * last[1] - last[0] * first[1]
                               for first, last in zip(points, points[1:] + points[:1]))) / 2
                self.assertAlmostEqual(area, 70)
                self.assertEqual(shape["holes"], [])
                validate_precision_origins(stored)
                records = stored["extensions"][EXTENSION_KEY]["records"]
                self.assertEqual({row["operation"] for row in records}, {"union", "offset", "mirror"})
                self.assertEqual(len(records), 3)
                union = next(row for row in records if row["operation"] == "union")
                self.assertEqual(union["before"], original["geometry"])
                self.assertEqual(union["engine"]["name"], "Shapely/GEOS")
                self.assertEqual({key: value for key, value in stored["extensions"].items() if key != EXTENSION_KEY}, original["extensions"])
                sealed = workspace / snapshot["artifact"]["uri"]
                self.assertEqual(hashlib.sha256(sealed.read_bytes()).hexdigest(), snapshot["artifact"]["sha256"])
