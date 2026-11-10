"""! @brief 실제 wxWidgets 창에서 CAD 출력과 3D 표시의 비동기 수명을 검증한다."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

from rfad.application.projects import ProjectService
from rfad.domain.design import apply_design_command
from test_cad_projection import cad_fixture
from test_cad_worker_process import register_fixture
from test_design import identity, quantity, unknown


GUI = os.environ.get("RFAD_GUI_EXE", "")
CAD = os.environ.get("RFAD_CAD_PYTHON", "")
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "win32" and GUI and CAD, "Windows GUI와 CAD 실행 환경을 명시해야 합니다.")
class GuiCadProcessTests(unittest.TestCase):
    """! @brief 보이는 컨트롤과 실제 분리 프로세스를 통한 생성/취소/복원을 검사한다."""

    def run_gui(self, directory: Path, *, invalid: bool = False):
        """! @brief 실제 RF 보드와 구분한 기하 fixture를 등록하고 GUI 버튼 흐름을 실행한다."""
        workspace = directory / "한글 CAD 작업 영역"
        document = cad_fixture()
        document["board"]["outline"].update(width=quantity(40, "mm"), height=quantity(60, "mm"))
        arc = deepcopy(document["geometry"][0])
        arc.pop("start")
        arc.pop("end")
        arc.update(id=identity(30), kind="arc_path", center=[quantity(20, "mm"), quantity(25, "mm")],
                   radius=quantity(10, "mm"), start_angle=quantity(20, "deg"), sweep_angle=quantity(-260, "deg"))
        apply_design_command(document, "geometry.set", {"geometry": arc})
        if invalid:
            document["stackup"][0]["thickness"] = unknown("length", "mm")
        with ProjectService(workspace, auto_run=False) as service:
            register_fixture(service, document)
        report = directory / "GUI CAD 검증.json"
        args = [str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(ROOT / "src"),
                "--workspace", str(workspace), "--cad-python", str(Path(CAD).resolve()),
                "--open-project", "projects/CAD 한글 교환 검증", "--cad-smoke-test", "--smoke-report", str(report)]
        if invalid:
            args.append("--cad-expect-failure")
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        # @brief 실제 GL paint/swap 검증에는 표시 가능한 창을 사용하고 시험 뒤 닫는다.
        startup.wShowWindow = 1
        process = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 timeout=210, startupinfo=startup, check=False)
        self.assertTrue(report.is_file(), (process.returncode, process.stderr))
        result = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(process.returncode, 0, result)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["cad_stage"], 7, result)
        return workspace, result

    def test_step_mesh_edit_save_cancel_and_restart(self):
        """! @brief 고정 입력 출력 중 저장하고 실제 GL 표시 및 취소 후 이전 결과 복원을 확인한다."""
        with TemporaryDirectory(prefix="TraceWave GUI CAD ") as temporary:
            workspace, report = self.run_gui(Path(temporary))
            self.assertEqual(set(report["cad_checks"]), {
                "draft_applied_before_snapshot", "editing_enabled_during_cad", "snapshot_fixed_and_stale_label",
                "save_during_cad", "verified_mesh_rendered", "step_package_accessible", "camera_controls",
                "cancel_preserves_previous_result", "restart_restores_published_mesh",
                "edit_error_does_not_drop_responses",
            })
            self.assertEqual(report["service_sessions"], 2)
            self.assertGreater(report["mesh_triangles"], 0)
            self.assertGreater(report["rendered_frames"], 0)
            self.assertTrue(report["renderer"])
            result = report["cad_result"]
            self.assertNotEqual(result["snapshot"]["revision_id"], report["revision_id"])
            self.assertFalse(result["physics_verified"])
            self.assertEqual({item["role"] for item in result["artifacts"]},
                             {"step", "brep", "sidecar", "validation", "display_mesh", "manifest"})
            for artifact in result["artifacts"]:
                raw = (workspace / artifact["uri"]).read_bytes()
                self.assertEqual(len(raw), artifact["bytes"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), artifact["sha256"])

    def test_missing_geometry_input_does_not_publish_or_display(self):
        """! @brief 미정 필수 두께는 GUI에 실패로 남고 파일/3D 성공으로 표시하지 않는다."""
        with TemporaryDirectory(prefix="TraceWave GUI CAD invalid ") as temporary:
            workspace, report = self.run_gui(Path(temporary), invalid=True)
            self.assertEqual(report["cad_checks"], ["invalid_input_not_published"])
            self.assertFalse(report["cad_result"])
            self.assertEqual(report["mesh_triangles"], 0)
            self.assertEqual(list(workspace.rglob("model.step")), [])


if __name__ == "__main__":
    unittest.main()
