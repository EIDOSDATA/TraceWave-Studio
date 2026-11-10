"""! @brief 일반 입력 점검과 PCB sheet 계획이 같은 필수 물성을 사용하게 한다."""

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rfad.application.pcb_solver import build_pcb_plan
from rfad.application.projects import ProjectService
from rfad.domain.design import preflight_design
from rfad.domain.units import Quantity
from test_cad_worker_process import register_fixture, request, status
from test_pcb_solver import fixture_document, snapshot_for, runtime_identity, SETTINGS


class PcbInputValidationTests(unittest.TestCase):
    """! @brief 미사용 물성을 채우지 않고 입력 통과와 solver 합격을 구분한다."""

    def test_missing_unused_metal_properties_are_not_errors(self):
        """! @brief conducting sheet의 미사용 유전율/손실은 원본에 그대로 남긴다."""
        document = fixture_document(circle=True, arc=True)
        copper_id = next(layer["material_id"] for layer in document["stackup"] if layer["role"] == "conductor")
        copper = next(value for value in document["materials"] if value["id"] == copper_id)
        for key in ("epsilon_r", "tan_delta"):
            copper[key] = Quantity.missing("dimensionless", "1").to_dict()
        before = deepcopy(document)
        self.assertEqual(preflight_design(document, "em"), [])
        plan = build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)
        consumed = next(value for value in plan["case"]["materials"] if value["id"] == copper_id)
        self.assertEqual(consumed["consumed_properties"], ["conductivity"])
        self.assertEqual(document, before)

    def test_missing_dielectric_properties_remain_blocking(self):
        """! @brief 유전체에 필요한 유전율은 금속 예외와 혼동하지 않는다."""
        document = fixture_document()
        substrate_id = next(layer["material_id"] for layer in document["stackup"] if layer["role"] == "dielectric")
        substrate = next(value for value in document["materials"] if value["id"] == substrate_id)
        substrate["epsilon_r"] = Quantity.missing("dimensionless", "1").to_dict()
        diagnostics = preflight_design(document, "em")
        self.assertTrue(any(value["field_paths"] == [f"materials.{substrate_id}.epsilon_r"] for value in diagnostics))

    def test_missing_feed_coordinates_report_the_actual_field(self):
        """! @brief 저장 가능한 구형 포트의 누락 위치를 구체적으로 안내한다."""
        document = fixture_document()
        del document["ports"][0]["excitation_box"]
        diagnostics = preflight_design(document, "em")
        self.assertEqual(len(diagnostics), 1)
        self.assertEqual(diagnostics[0]["code"], "E_PORT")
        self.assertTrue(diagnostics[0]["field_paths"][0].endswith(".excitation_box"))

    def test_valid_input_report_does_not_claim_solver_readiness(self):
        """! @brief 실제 검사 보고서의 입력 통과와 solver/물리 검증을 분리한다."""
        with TemporaryDirectory(prefix="TraceWave PCB 입력 검사 ") as directory:
            with ProjectService(Path(directory), auto_run=False) as service:
                document, _ = register_fixture(service, fixture_document())
                task = service.mutate("design.validate", request(service, document["project_id"], {
                    "expected_revision": document["revision_id"], "profile": "rfad.design/0.1", "purpose": "em",
                }))
                service.run_next()
                report = status(service, task["job_id"])["events"][-1]["operation_result"]
                self.assertEqual(report["input_status"], "valid")
                self.assertFalse(report["solver_ready"])
                self.assertEqual(report["validation_scope"], "input_only")
                self.assertEqual(report["next_validation"], "solver.plan")


if __name__ == "__main__":
    unittest.main()
