"""! @brief GUI용 선택 문맥의 개정, 표시 단위, 읽기 순수성과 원본 결합 보존을 확인한다."""

from copy import deepcopy
import json
import unittest
from uuid import uuid4

from rfad.application.rpc import handle_frame
from rfad.domain.errors import ProjectError
from test_design import quantity
import test_pcb_selection_service as service_fixture
from test_pcb_solver import fixture_document


class PcbSelectionContextTests(unittest.TestCase):
    """! @brief 실제 저장소의 현재 설계에서 작은 화면 DTO만 요청한다."""

    def setUp(self):
        """! @brief 기존 서비스 fixture를 재사용하며 테스트 메서드는 상속하지 않는다."""
        self.fixture = service_fixture.PcbSelectionServiceTests()
        self.fixture.setUp()

    def tearDown(self):
        """! @brief 시험이 소유한 파일과 writer 잠금을 회수한다."""
        self.fixture.tearDown()

    def context(self):
        """! @brief 실제 RPC dispatch를 통해 화면 문맥을 조회한다."""
        f = self.fixture
        response = handle_frame(json.dumps({"jsonrpc": "2.0", "id": "context", "method": "pcb.selection.context",
                                            "params": f.request({}, read=True)}).encode(), f.service)
        self.assertNotIn("error", response)
        return response["result"]

    def test_context_preserves_unknowns_and_never_loads_catalog_or_writes(self):
        """! @brief 카탈로그가 없어도 문맥/기존 직접 입력을 사용할 수 있다."""
        f = self.fixture
        spec = f.selection()
        spec["specification"]["layers"][1]["thickness_mm"] = None
        f.apply(spec)
        f.database.unlink()
        before = f.service.journal.read()
        result = self.context()
        self.assertEqual(f.service.journal.read(), before)
        self.assertEqual(result["revision_id"], f.document()["revision_id"])
        self.assertEqual(result["board"], {"kind": "circle"})
        self.assertIsNone(result["layers"][1]["thickness_mm"])
        self.assertIsNone(result["layers"][2]["z_min_mm"])
        self.assertAlmostEqual(result["layers"][0]["thickness_mm"], 0.035)
        self.assertNotIn("geometry", result)
        self.assertNotIn("evidence", result["selection"])

    def test_parameter_display_does_not_replace_binding_or_invalidate_preview(self):
        """! @brief 서비스가 매개변수를 평가해 mm로 표시하되 기존 결합은 그대로 남긴다."""
        f = self.fixture
        f.apply(f.selection())
        parameter = str(uuid4())
        f.command("parameter.set", {"id": parameter, "name": "Core height", "quantity": quantity(1000, "um")})
        layer = deepcopy(next(item for item in f.document()["stackup"] if item["role"] == "dielectric"))
        layer["thickness"] = {"parameter_id": parameter}
        f.command("layer.set", {"layer": layer})
        before = f.document()
        row = next(item for item in self.context()["layers"] if item["id"] == layer["id"])
        self.assertTrue(row["parameter_bound"])
        self.assertEqual(row["thickness_mm"], 1.0)
        preview = f.preview(f.selection({"source": None, "materials": []}))
        shown = next(item for item in preview["candidate_layers"] if item["id"] == layer["id"])
        self.assertEqual(row, shown)
        self.assertEqual(next(item for item in preview["candidate"]["stackup"] if item["id"] == layer["id"])["thickness"],
                         {"parameter_id": parameter})
        self.assertEqual(f.document(), before)

    def test_ports_are_displayed_in_mm_and_context_is_strictly_read_only(self):
        """! @brief 급전 좌표와 이름만 표시하고 요청으로 포트를 변경할 수 없게 한다."""
        f = self.fixture
        f.install_design(fixture_document(circle=True))
        result = self.context()
        self.assertEqual(result["ports"][0]["start_mm"], [-1.0, 0.0, 1.0])
        self.assertEqual(result["ports"][0]["stop_mm"], [1.0, 0.0, 1.0])
        self.assertFalse(result["ports"][0]["parameter_bound"])
        before = f.service.journal.read()
        with self.assertRaises(ProjectError):
            f.service.pcb_selection.context(f.request({"layers": []}, read=True))
        self.assertEqual(f.service.journal.read(), before)


if __name__ == "__main__":
    unittest.main()
