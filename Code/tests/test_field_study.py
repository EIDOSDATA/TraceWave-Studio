"""! @brief 고정 실좌표, 실제 직전 장 선택, 반복/자원 종료와 공통 표본의 거짓 합격을 차단한다."""

from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application import field_study, field_study_geometry as geometry
from rfad.application.canonical import canonical_hash
from rfad.domain.errors import ProjectError
from test_convergence import fixture_result, PROFILE


class FieldStudyTests(unittest.TestCase):
    """! @brief 물리 정답과 구분한 조밀/비등간 합성 격자에서 연구 계약을 검사한다."""

    def setUp(self):
        self.initial = {"monitor_id": "probe_electric", "component": "x", "frequency_index": 0,
                        "plane": {"normal_axis": "z", "index": 1}, "roi": {"u_start": 0, "u_count": 3, "v_start": 1, "v_count": 2}}
        self.limits = {"threshold_fraction": .05, "max_rules": 2, "memory_limit_mib": 128, "max_rounds": 2, "max_s11_complex_delta": .02}
        self.model = {"frequency_hz": [1e9], "shape": [4, 4, 4], "primary_coordinates_mm": {k: [0, 1, 2, 3] for k in "xyz"},
                      "next_nodes_mm": {k: 4 for k in "xyz"}}

    def test_same_mm_region_uses_different_yee_indices_after_refinement(self):
        with patch.object(geometry, "_model", return_value=self.model):
            region = geometry.anchor({}, self.initial)
        self.assertEqual(region["bounds_mm"], {"x": [.5, 2.5], "y": [1, 2]})
        fine = deepcopy(self.model)
        fine["shape"] = [6, 5, 5]
        fine["primary_coordinates_mm"] = {"x": [0, .5, 1, 1.5, 2, 3], "y": [0, .5, 1, 2, 3], "z": [0, .5, 1, 2, 3]}
        with patch.object(geometry, "_model", return_value=fine):
            selection, used = geometry.selection_for({}, region)
            self.assertEqual(selection["plane"]["index"], 2)
            self.assertEqual(selection["roi"], {"u_start": 1, "u_count": 4, "v_start": 2, "v_count": 2})
            self.assertEqual(used["bounds_mm"]["x"], [.75, 2.5])
            with self.assertRaises(ProjectError):
                geometry.selection_for({}, {**region, "frequency_hz": 2e9})

    def test_recording_index_may_change_but_port_or_physical_settings_may_not(self):
        left, right = fixture_result(), fixture_result(phase=.1)
        lhs, rhs = (row["provenance"]["analysis_plan"]["case"] for row in (left, right))
        lhs["settings"]["field_probe"] = rhs["settings"]["field_probe"] = {"z_mm": 1.0}
        lhs["port"], rhs["port"] = {"resistance_ohm": 50}, {"resistance_ohm": 50}
        lhs["field_recording"] = {"start_indices": [1, 2, 3]}
        rhs["field_recording"] = {"start_indices": [1, 3, 4]}
        rhs["settings"]["local_mesh"] = [{"test": 1}]
        before = deepcopy(right)
        report = geometry.compare(left, right, PROFILE)
        self.assertFalse(report["complex_s11_passed"])
        self.assertEqual(len(report["frequency_rows"]), 5)
        self.assertEqual(right, before)
        rhs["settings"]["air_padding_mm"] += 1
        with self.assertRaises(ProjectError):
            geometry.compare(left, right, PROFILE)
        rhs["settings"]["air_padding_mm"] -= 1
        rhs["port"]["resistance_ohm"] = 75
        with self.assertRaises(ValueError):
            geometry.compare(left, right, PROFILE)

    def test_rejects_ambiguous_or_unbounded_inputs(self):
        data = {"expected_revision": str(uuid4()), "name": "원호", "source": {"kind": "solver", "artifact_id": str(uuid4())},
                "pin": {"identity_hash": "a"*64, "dataset_sha256": "b"*64}, "selection": self.initial, "limits": self.limits}
        field_study.validate(data)
        for key, value in [("memory_limit_mib", 127), ("max_rules", 17), ("max_rounds", False), ("max_s11_complex_delta", float("nan"))]:
            with self.subTest(key=key), self.assertRaises(ProjectError):
                field_study.validate({**data, "limits": {**self.limits, key: value}})

    def exercise(self, reason=None, *, second=False, phase=0, cancel=False, converged=True):
        """! @brief 실제 서비스와 같은 결정 단계에서 봉인/공개 근거를 읽되 native 완료 결과만 대역한다."""
        first, second_result = fixture_result(), fixture_result(phase=phase)
        first["assessment"]["converged"] = converged
        snapshot = first["provenance"]["analysis_plan"]["snapshot"]
        snapshot["revision_id"] = "original"
        second_result["provenance"]["analysis_plan"]["snapshot"] = deepcopy(snapshot)
        identity = "test"
        study = {"study_id": identity, "project_id": "example", "snapshot": snapshot, "definition": "def", "runtime_identity": {},
                 "specification": {"field_adaptive": {"limits": {**self.limits, "max_rounds": 1}, "physical_region": {}}, "port_profile": PROFILE},
                 "state": "running", "cases": [{"phase": "done", "result_id": "old", "settings": {"grid_mm": .25}}]}
        if second:
            study["cases"].append({"phase": "done", "result_id": "new", "settings": {"grid_mm": .25}, "refinement": {
                "next_mesh_sha256": canonical_hash(second_result["mesh_statistics"]["lines_mm"])}})
        files = {}
        def store(path, raw):
            files[path] = raw
            return path
        def transact(callback):
            if cancel:
                study["state"] = "cancel_requested"
            callback({"studies": {identity: study}})
        journal = SimpleNamespace(put_immutable=store, read_artifact=files.__getitem__, transaction=transact)
        service = SimpleNamespace(journal=journal)
        def read(_, __, case):
            return (first if case["result_id"] == "old" else second_result), None, None
        with patch("rfad.application.project_study_results.read_case", side_effect=read), patch.object(field_study, "resolve", return_value={"pin": {}}), \
             patch.object(geometry, "selection_for", return_value=(self.initial, {})), \
             patch.object(field_study, "propose", return_value={"status": reason}) as propose:
            self.assertTrue(field_study.advance(service, study))
        return service, study, propose

    def test_budget_or_no_change_terminates_without_another_execution(self):
        for reason in ("memory_limit", "no_eligible_change", "rule_limit", "unchanged_mesh"):
            service, study, propose = self.exercise(reason)
            self.assertEqual(len(study["cases"]), 1)
            self.assertEqual(json.loads(service.journal.read_artifact(study["assessment"]))["adaptive_mesh_decision"]["reason"], reason)
            self.assertEqual(propose.call_count, 1)
            self.assertEqual(study["state"], "completed")

    def test_last_real_pair_stops_on_observations_or_round_limit(self):
        for phase, reason in [(0, "stability_reached"), (.12, "round_limit")]:
            service, study, propose = self.exercise(second=True, phase=phase)
            report = json.loads(service.journal.read_artifact(study["assessment"]))
            self.assertEqual(report["adaptive_mesh_decision"]["reason"], reason)
            self.assertFalse(report["physics_validated"])
            self.assertFalse(propose.called)
            self.assertEqual(len(field_study.load_pair(service, study, 1)["rows"]), 5)

    def test_nonterminated_baseline_does_not_choose_a_mesh(self):
        with self.assertRaisesRegex(ValueError, "시간 종료"):
            self.exercise("no_eligible_change", converged=False)

    def test_cancelled_race_does_not_publish_completion(self):
        _, study, _ = self.exercise("memory_limit", cancel=True)
        self.assertEqual(study["state"], "cancel_requested")
        self.assertNotIn("assessment", study)
