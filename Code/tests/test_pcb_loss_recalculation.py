"""! @brief 원시 생산자의 기록 이름 이전은 기하/물성의 재해석이나 원본 수정을 허용하지 않는다."""

from copy import deepcopy
import json
from pathlib import Path
import unittest
import tempfile

from loss_recalculation import validate_producer_plan, load_producer, OLD_METHOD
from rfad.application.canonical import canonical_hash
from rfad.application.pcb_solver import build_pcb_plan
from test_pcb_solver import snapshot_for, runtime_identity


class LossRecalculationContractTests(unittest.TestCase):
    """! @brief 새 손실 판정기는 원래 FDTD와 별도 출처를 가져야 한다."""

    def plan(self):
        """! @brief 명시적 합성 PTH의 실제 결정적 투영을 사용한다."""
        root = Path(__file__).resolve().parents[1] / "fixtures"
        document = json.loads((root / "pth_worker_smoke.json").read_text(encoding="utf-8"))["document"]
        settings = json.loads((root / "pth_loss_study.json").read_text(encoding="utf-8"))["cases"][0]["settings"]
        return build_pcb_plan(document, snapshot_for(document), runtime_identity(), settings)

    def test_only_known_recording_label_can_differ_without_mutating_producer(self):
        """! @brief 폐기된 개발 이름을 원본에 덮어쓰지 않고 비교용 사본에서만 대조한다."""
        plan = self.plan()
        plan["case"]["loss_recording"]["method"] = OLD_METHOD
        original = deepcopy(plan)
        self.assertTrue(validate_producer_plan(plan)["only_legacy_recording_method_label_differs"])
        self.assertEqual(plan, original)

    def test_material_geometry_or_unknown_label_is_never_migrated(self):
        """! @brief 재계산이라는 이름으로 물리 입력이나 임의 기록 모델을 바꾸지 않는다."""
        for field in ("conductivity", "radius", "method"):
            plan = self.plan()
            if field == "method":
                plan["case"]["loss_recording"]["method"] = "unrecognized"
            else:
                plan["case"]["loss_recording"]["method"] = OLD_METHOD
                plan["case"]["vias"][0]["conductivity_s_per_m" if field == "conductivity" else "outer_radius_mm"] *= 1.1
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_producer_plan(plan)

    def test_derived_report_cannot_relabel_actual_settings(self):
        """! @brief 편집 가능한 진행 보고서가 실제 계획과 다른 수치 축을 만들지 못하게 한다."""
        root = Path(__file__).resolve().parents[1] / "fixtures"
        study = json.loads((root / "pth_loss_study.json").read_text(encoding="utf-8"))
        report = {"schema": "rfad.pcb-loss-study-run/0.1", "study": study,
                  "runs": {canonical_hash(case["settings"]): {"settings": deepcopy(case["settings"])} for case in study["cases"]}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text(json.dumps(report), encoding="utf-8")
            load_producer(path)
            next(iter(report["runs"].values()))["settings"]["grid_mm"] += 0.01
            path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_producer(path)


if __name__ == "__main__":
    unittest.main()
