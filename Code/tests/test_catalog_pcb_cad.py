"""! @brief 카탈로그 2층 PCB의 실제 CAD 교환과 미정 RF 물성의 분리를 검증한다."""

from copy import deepcopy
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4

from rfad.application.cad import build_cad_input
from rfad.application.cad_runtime import CadRuntime
from rfad.application.projects import ProjectService
from rfad.domain.design import preflight_design
from rfad.domain.errors import ProjectError
from rfad.domain.pcb_selection import EXTENSION_KEY
from test_cad_projection import snapshot_for
from test_design import quantity, unknown
import test_pcb_selection_service as selection_fixture


CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / "tools"))

from catalog_pcb_verification.cad import restore_cad, verify_cad


CAD_PYTHON = os.environ.get("RFAD_CAD_PYTHON", "")


class CatalogPcbCadTests(unittest.TestCase):
    """! @brief 별도 임시 카탈로그와 공개 선택 API의 원본을 native CAD까지 전달한다."""

    def setUp(self):
        """! @brief 기존 작은 가상 카탈로그와 명시적 시험 적층을 재사용한다."""
        self.fixture = selection_fixture.PcbSelectionServiceTests()
        self.fixture.setUp()
        specification = selection_fixture.manual_specification()
        specification["catalog_id"] = self.fixture.catalog_id
        specification["materials"] = [selection_fixture.manual_material(catalog=True)]
        self.fixture.apply(self.fixture.selection(specification))
        self.add_patterns()

    def tearDown(self):
        """! @brief 테스트가 소유한 잠금과 임시 파일만 회수한다."""
        self.fixture.tearDown()

    def add_patterns(self):
        """! @brief 위아래 동박층에 서로 다른 명시적 시험 도체를 배치한다."""
        fixture = self.fixture
        document = fixture.document()
        for index, layer in enumerate(item for item in document["stackup"] if item["role"] == "conductor"):
            net_id = str(uuid4())
            fixture.command("net.set", {"net": {"id": net_id, "name": "시험 net " + str(index)}})
            fixture.command("geometry.set", {"geometry": {
                "id": str(uuid4()), "kind": "line_path", "role": "radiator" if index else "ground",
                "frame_id": document["frames"]["board"]["id"], "layer_id": layer["id"], "net_id": net_id,
                "material_ref": None, "source_ref": None, "include_in_em": True, "include_in_export": True,
                "start": [quantity(-5, "mm"), quantity(index * 2, "mm")],
                "end": [quantity(5, "mm"), quantity(index * 2, "mm")], "width": quantity(1, "mm"),
            }})

    def test_missing_rf_properties_do_not_block_cad_or_gain_defaults(self):
        """! @brief 출처로 채택한 Dk와 미정 Df를 그대로 두고 CAD 기하만 허용한다."""
        document = self.fixture.document()
        original = deepcopy(document)
        projection = build_cad_input(document, snapshot_for(document))
        material = document["materials"][0]
        self.assertEqual(material["epsilon_r"]["value_si"], 4.2)
        self.assertIsNone(material["tan_delta"]["value_si"])
        self.assertEqual(material["tan_delta"]["status"], "missing")
        self.assertTrue(document["extensions"][EXTENSION_KEY]["evidence"])
        self.assertEqual(projection["source_semantics"], original)
        self.assertEqual(len(projection["layers"]), 3)
        self.assertEqual(len(projection["shapes"]), 2)
        self.assertEqual(document, original)
        self.assertTrue(any(item["code"] == "E_MATERIAL_UNKNOWN" for item in preflight_design(document, "em")))

    def test_missing_layer_thickness_blocks_cad_without_erasing_evidence(self):
        """! @brief 형상 필수 두께는 RF 물성과 달리 미정 상태에서 생성하지 않는다."""
        fixture = self.fixture
        layer = deepcopy(fixture.document()["stackup"][1])
        layer["thickness"] = unknown("length", "mm")
        fixture.command("layer.set", {"layer": layer})
        document = fixture.document()
        original = deepcopy(document)
        with self.assertRaises(ProjectError) as raised:
            build_cad_input(document, snapshot_for(document))
        self.assertEqual(raised.exception.code, "E_GEOMETRY")
        self.assertEqual(raised.exception.details["field_path"], "stackup." + layer["id"] + ".thickness")
        self.assertEqual(document, original)
        self.assertTrue(document["extensions"][EXTENSION_KEY]["evidence"])

    @unittest.skipUnless(sys.platform == "win32" and CAD_PYTHON, "RFAD_CAD_PYTHON으로 고정 Windows CAD 환경을 지정해야 합니다.")
    def test_native_geometry_step_mesh_and_catalog_free_restart(self):
        """! @brief 두 native 작업과 STEP 재입력 후 카탈로그/CAD 없는 재열기를 확인한다."""
        fixture = self.fixture
        document = fixture.document()
        fixture.complete("project.save", fixture.request({"expected_revision": document["revision_id"]}))
        snapshot = fixture.complete("snapshot.create", fixture.request({"expected_revision": document["revision_id"]}))
        context = {"project_id": document["project_id"]}
        fixture.service.close()
        fixture.service = ProjectService(fixture.workspace, cad_runtime=CadRuntime(Path(CAD_PYTHON)))
        report = verify_cad(fixture.service, context, snapshot, document)
        self.assertEqual(report["status"], "passed")
        self.assertEqual([item["method"] for item in report["operations"]], ["geometry.build", "export.build"])
        for operation in report["operations"]:
            self.assertEqual(operation["result"]["body_count"], 3)
            self.assertEqual(operation["native_reopen"]["status"], "passed_same_kernel")
            self.assertTrue(operation["catalog_evidence_preserved"])
            self.assertFalse(operation["result"]["physics_verified"])
        fixture.service.close()
        fixture.database.unlink()
        fixture.service = ProjectService(fixture.workspace, auto_run=False, catalog_database=fixture.database)
        restore_cad(fixture.service, context, snapshot, report)
        self.assertIsNone(fixture.service.cad.runtime)
        self.assertEqual(fixture.document(), document)
        self.assertIsNone(fixture.document()["materials"][0]["tan_delta"]["value_si"])


if __name__ == "__main__":
    unittest.main()
