"""! @brief 예산 확장에 따른 원시 재사용은 실제 입력 동일성을 증명한 경우만 허용한다."""

from copy import deepcopy
import unittest

from rfad.application.pcb_solver import build_pcb_plan
from test_pcb_power import power_plan
from verify_ro_loss_followup import equivalent_inputs


class LossInputEquivalenceTests(unittest.TestCase):
    """! @brief source/runtime를 바꿔 붙이거나 물리 입력 차이를 예산 차이로 숨기지 않는다."""

    def pair(self):
        """! @brief 물리적으로 동일하며 실행 한도만 늘린 명시적 두 계획이다."""
        old = power_plan()
        settings = deepcopy(old["case"]["settings"])
        settings["compute_profile"] = {"kind":"loss_refinement_deep/0.1","num_threads":2}
        new = build_pcb_plan(old["source_semantics"],old["snapshot"],old["runtime_identity"],settings)
        xml = {"bytes":123,"sha256":"a"*64}
        return old,new,xml

    def test_only_nonphysical_profile_can_change_with_identical_native_xml(self):
        """! @brief 동일 source/snapshot/격자/급전/설치와 XML의 실행 예산 변경만 인정한다."""
        old,new,xml = self.pair()
        self.assertEqual(new["resource_estimate"]["max_wall_time_seconds"],1800)
        proof = equivalent_inputs(old,new,xml,dict(xml))
        self.assertTrue(proof["native_xml_bytes_identical"])
        self.assertFalse(proof["fdtd_reexecuted"])

    def test_changed_physics_installation_or_actual_xml_is_rejected(self):
        """! @brief 재사용을 위해 기하/전도도/주파수/원본/정규화 차이를 무시하지 않는다."""
        for field in ("geometry","material","frequency","snapshot","normalization","install","xml"):
            old,new,xml = self.pair()
            other = dict(xml)
            if field == "geometry":
                new["case"]["board"]["dimensions_mm"][0] += 1
            elif field == "material":
                new["case"]["shapes"][0]["conductivity_s_per_m"] *= 1.01
            elif field == "frequency":
                new["case"]["frequency_hz"]["start"] += 1e6
            elif field == "snapshot":
                new["snapshot"]["content_hash"] = "b"*64
            elif field == "normalization":
                new["normalization"]["reference_impedance_ohm"] = 75
            elif field == "install":
                new["runtime_identity"]["manifest_sha256"] = "b"*64
            else:
                other["sha256"] = "b"*64
            with self.subTest(field=field),self.assertRaises(ValueError):
                equivalent_inputs(old,new,xml,other)


if __name__ == "__main__":
    unittest.main()
