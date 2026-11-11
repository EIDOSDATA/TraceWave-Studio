"""! @brief 총 유전 손실 모델의 명시 선택, 미사용 물성 보존과 이전 계획 호환성을 검증한다."""

from copy import deepcopy
import json
import math
from pathlib import Path
import unittest

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.pcb_projection import EPSILON0, MaterialProjection, project_pcb
from rfad.application.pcb_solver import build_pcb_plan, validate_pcb_plan
from rfad.domain.design import preflight_design
from rfad.domain.errors import ProjectError
from rfad.domain.material_models import TOTAL_TAN_DELTA_MODEL
from rfad.domain.project import validate_project
from rfad.domain.units import Quantity
from test_pcb_solver import SETTINGS, fixture_document, quantity, runtime_identity, snapshot_for


class MaterialLossModelTests(unittest.TestCase):
    """! @brief 시험 가정과 실제 재료를 구분하며 미정 전도도를 0으로 바꾸지 않는다."""

    def document(self):
        """! @brief 기존 시험 기하에서 유전체의 총 손실 모델만 명시적으로 선택한다."""
        document = fixture_document(circle=True, arc=True)
        identity = next(layer["material_id"] for layer in document["stackup"] if layer["role"] == "dielectric")
        material = next(item for item in document["materials"] if item["id"] == identity)
        material["model"] = TOTAL_TAN_DELTA_MODEL
        material["conductivity"] = Quantity.missing("conductivity", "S/m").to_dict()
        material["assumptions"].append("시험에서 총 전기 손실을 tan_delta 하나로 선택하며 독립 전도도는 소비하지 않음")
        return document, material

    def plan(self, document):
        """! @brief 불변 원본과 실제 계약 검증을 사용하는 순수 계획을 구성한다."""
        return build_pcb_plan(document, snapshot_for(document), runtime_identity(), SETTINGS)

    def test_total_loss_preserves_missing_conductivity_and_reports_consumption(self):
        """! @brief 미정 전도도 원본과 총 Df에서 변환한 native 손실을 구분한다."""
        document, material = self.document()
        before = canonical_bytes(document)
        self.assertEqual(preflight_design(document, "em"), [])
        plan = self.plan(document)
        validate_pcb_plan(plan)
        consumed = next(item for item in plan["case"]["materials"] if item["id"] == material["id"])
        layer = next(item for item in plan["case"]["layers"] if item["role"] == "dielectric")
        self.assertEqual(consumed["model"], TOTAL_TAN_DELTA_MODEL)
        self.assertEqual(consumed["consumed_properties"], ["epsilon_r", "tan_delta"])
        self.assertEqual(consumed["unconsumed_properties"], ["conductivity"])
        self.assertNotIn("conductivity_s_per_m", consumed)
        self.assertEqual(layer["loss_partition"], consumed["loss_partition"])
        self.assertEqual(layer["loss_reference_frequency_hz"], 10e9)
        self.assertIn("not_broadband_constant_tan_delta", layer["loss_approximation"])
        self.assertAlmostEqual(layer["kappa_s_per_m"], 2 * math.pi * 10e9 * EPSILON0 * 2.2 * 0.002, places=15)
        source = next(item for item in plan["source_semantics"]["materials"] if item["id"] == material["id"])
        self.assertIsNone(source["conductivity"]["value_si"])
        self.assertEqual(source["conductivity"]["status"], "missing")
        self.assertEqual(canonical_bytes(document), before)

    def test_known_independent_conductivity_is_not_added_twice(self):
        """! @brief 총 손실 모델의 미사용 전도도가 알려져도 Df 손실에 중복 합산하지 않는다."""
        document, material = self.document()
        initial = self.plan(document)
        material["conductivity"] = quantity(123.0, "S/m")
        before = deepcopy(document)
        changed = self.plan(document)
        self.assertEqual(initial["case"]["layers"], changed["case"]["layers"])
        consumed = next(item for item in changed["case"]["materials"] if item["id"] == material["id"])
        self.assertNotIn("conductivity_s_per_m", consumed)
        self.assertEqual(document, before)

    def test_legacy_model_still_requires_separate_conductivity(self):
        """! @brief 이전 모델의 누락 입력을 새 모델로 묵시 전환해 허용하지 않는다."""
        document = fixture_document()
        identity = document["stackup"][0]["material_id"]
        material = next(item for item in document["materials"] if item["id"] == identity)
        material["conductivity"] = Quantity.missing("conductivity", "S/m").to_dict()
        diagnostics = preflight_design(document, "em")
        self.assertTrue(any(item["field_paths"] == ["materials." + identity + ".conductivity"] for item in diagnostics))
        with self.assertRaises(ProjectError) as raised:
            self.plan(document)
        self.assertEqual(raised.exception.code, "E_MATERIAL_UNKNOWN")

    def test_missing_permittivity_loss_or_model_band_remains_blocking(self):
        """! @brief 총 손실 선택은 필수 Dk/Df와 유효 대역의 누락을 해소하지 않는다."""
        for field in ("epsilon_r", "tan_delta", "validity_hz.min", "validity_hz.max"):
            with self.subTest(field=field):
                document, material = self.document()
                if field.startswith("validity_hz"):
                    material["validity_hz"][field.rsplit(".", 1)[1]] = Quantity.missing("frequency", "Hz").to_dict()
                else:
                    material[field] = Quantity.missing("dimensionless", "1").to_dict()
                diagnostics = preflight_design(document, "em")
                self.assertTrue(any(item["field_paths"] == ["materials." + material["id"] + "." + field] for item in diagnostics))
                with self.assertRaises(ProjectError):
                    self.plan(document)

    def test_total_loss_model_cannot_be_used_as_a_conducting_sheet(self):
        """! @brief 유전체 전용 손실 선택을 금속 sheet의 전도도 생략에 악용할 수 없다."""
        document, _ = self.document()
        identity = document["stackup"][-1]["material_id"]
        metal = next(item for item in document["materials"] if item["id"] == identity)
        metal["model"] = TOTAL_TAN_DELTA_MODEL
        diagnostics = preflight_design(document, "em")
        self.assertTrue(any(item["code"] == "E_UNSUPPORTED" and item["field_paths"] == ["materials." + identity + ".model"]
                            for item in diagnostics))
        with self.assertRaises(ProjectError) as raised:
            self.plan(document)
        self.assertEqual(raised.exception.code, "E_UNSUPPORTED")

    def test_total_loss_model_cannot_be_used_as_volume_conductor(self):
        """! @brief 비아 같은 유한 전도 체적에도 총 Df 모델을 적용하지 않는다."""
        document, material = self.document()
        projection = MaterialProjection(document, SETTINGS["frequency_hz"])
        for volume in (False, True):
            with self.subTest(volume=volume), self.assertRaises(ProjectError) as raised:
                projection.consume(material["id"], "test.material_ref", conductor=True, volume=volume)
            self.assertEqual(raised.exception.code, "E_UNSUPPORTED")
            self.assertEqual(raised.exception.details["field_path"], "materials." + material["id"] + ".model")
        self.assertEqual(projection.consumed, {})

    def test_model_band_cannot_be_silently_extended(self):
        """! @brief Df 자료가 있어도 저장한 모델 대역 밖 계산은 거절한다."""
        document, material = self.document()
        material["validity_hz"]["max"] = quantity(9, "GHz")
        with self.assertRaises(ProjectError) as raised:
            self.plan(document)
        self.assertEqual(raised.exception.code, "E_MATERIAL_RANGE")

    def test_unsupported_model_is_not_treated_as_total_loss(self):
        """! @brief 오타나 비문자열 모델을 지원 모델로 대체하지 않는다."""
        for model in ("tan_delta", None, [], {}):
            with self.subTest(model=model):
                document, material = self.document()
                material["model"] = model
                with self.assertRaises(ProjectError) as raised:
                    validate_project(document)
                self.assertEqual(raised.exception.code, "E_UNSUPPORTED")

    def test_legacy_native_projection_bytes_remain_compatible(self):
        """! @brief 새 모델 추가 전 두 고정 fixture의 투영 해시와 비교해 이전 계획 의미를 보존한다."""
        expected = {
            "pcb_worker_smoke.json": "6201ccb7aad54c6a49c80afaed2954b4f574c3a99154aaf00ccb16992be2f858",
            "ifa_feed_smoke.json": "18940171c4ff38c69d74bb9d1a08fb664b1be8b3bce77009fb312618839b5558",
        }
        for name, digest in expected.items():
            with self.subTest(fixture=name):
                fixture = json.loads((Path(__file__).resolve().parents[1] / "fixtures" / name).read_bytes())
                projection = project_pcb(fixture["document"], fixture["settings"])
                self.assertEqual(canonical_hash(projection), digest)


if __name__ == "__main__":
    unittest.main()
