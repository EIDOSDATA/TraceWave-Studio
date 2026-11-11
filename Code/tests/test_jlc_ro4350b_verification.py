"""! @brief 제조사 원본 미정값과 허용한 탐색용 모델을 섞지 않는지 검증한다."""

from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from catalog_pcb_verification.common import VerificationError
from manufacturing_verification.jlc_ro4350b import CODE_ROOT, MODEL_BAND, prepare, run, specification
from rfad.catalog.material_selection import build_material
from rfad.domain.material_models import TOTAL_TAN_DELTA_MODEL


class JlcRo4350bVerificationTests(unittest.TestCase):
    """! @brief 명목 기하, 관측값과 명시적 모델 적용의 서로 다른 수명을 검사한다."""

    def setUp(self):
        """! @brief 승인 fixture와 후속 제조 후보를 읽기 전용으로 준비한다."""
        self.fixture = json.loads((CODE_ROOT / "fixtures/ifa_feed_smoke.json").read_bytes())
        self.candidate = json.loads((CODE_ROOT / "fixtures/manufacturing/jlc_ro4350b_candidate.json").read_bytes())

    def test_preparation_preserves_unknown_physical_materials_and_fixture(self):
        """! @brief 모델링 전부터 시험 물성을 제거하며 납품 물성의 미정 사본을 보존한다."""
        before, candidate_before = deepcopy(self.fixture), deepcopy(self.candidate)
        prepared, identities = prepare(self.fixture, self.candidate)
        self.assertEqual(self.fixture, before)
        self.assertEqual(self.candidate, candidate_before)
        document = prepared["document"]
        self.assertEqual(document["geometry"], before["document"]["geometry"])
        self.assertEqual(len(identities), 2)
        self.assertEqual(len(document["materials"]), 4)
        for material in document["materials"]:
            for field in ("epsilon_r", "tan_delta", "conductivity"):
                self.assertIsNone(material[field]["value_si"])
            self.assertTrue(all(value["value_si"] is None for value in material["validity_hz"].values()))
        active = {layer["material_id"] for layer in document["stackup"]}
        self.assertFalse(active & set(identities))
        self.assertAlmostEqual(sum(layer["thickness"]["value_si"] for layer in document["stackup"]), 0.000832)
        self.assertNotAlmostEqual(sum(layer["thickness"]["value_si"] for layer in document["stackup"]), 0.0009)
        for port in document["ports"]:
            self.assertEqual({key: value["value_si"] for key, value in port["validity_hz"].items()}, MODEL_BAND)
            for endpoint in ("start", "stop"):
                self.assertAlmostEqual(port["excitation_box"][endpoint][2]["value_si"], 0.000797)

    def test_model_uses_separate_observations_and_reference_copper(self):
        """! @brief 서로 다른 관측의 근사 이유와 IACS 구리의 표준 출처를 분리한다."""
        prepared, _ = prepare(self.fixture, self.candidate)
        before = deepcopy(prepared)
        spec = specification(prepared["document"], self.candidate, "catalog:fixture")
        self.assertEqual(prepared, before)
        core, copper = spec["materials"]
        self.assertEqual(core["model"], TOTAL_TAN_DELTA_MODEL)
        self.assertNotEqual(core["properties"]["epsilon_r"]["record_id"], core["properties"]["tan_delta"]["record_id"])
        self.assertEqual(core["properties"]["conductivity"]["mode"], "missing")
        self.assertNotIn("value", core["properties"]["conductivity"])
        self.assertEqual(copper["properties"]["conductivity"]["value"], 58e6)
        self.assertIn("JLC 제공값 아님", copper["properties"]["conductivity"]["reason"])
        selected = build_material({**copper, "id": spec["material_ids"]["copper"]}, None)
        self.assertEqual(selected["material"]["conductivity"]["status"], "user_entered")
        self.assertTrue(any("ENIG" in item for item in spec["notes"]))

    def test_approximations_are_not_implicitly_accepted(self):
        """! @brief 명시적 허용 없이 실행하면 저장소나 임의 물성 입력을 만들지 않는다."""
        with TemporaryDirectory() as directory:
            workspace, report = Path(directory) / "workspace", Path(directory) / "report.json"
            with self.assertRaises(VerificationError):
                run(workspace, report, Path(directory) / "absent.sqlite")
            self.assertFalse(workspace.exists())
            self.assertFalse(report.exists())


if __name__ == "__main__":
    unittest.main()
