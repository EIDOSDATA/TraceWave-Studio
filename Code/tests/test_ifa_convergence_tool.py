"""! @brief 수렴 실행 도구의 재접수/입력 혼합 차단과 표본 보존을 검증한다."""

from copy import deepcopy
import csv
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.projects import ProjectService
from verify_openems_worker import call, wait
from verify_ifa_convergence import execute_phase, load_cases, publish_assessment, save_report, validate_resume, validate_study, write_samples


def study_definition():
    """! @brief 계산 없이 연구의 독립 변화와 실패 경계를 확인하는 명시적 입력이다."""
    return {
        "schema": "rfad.ifa-convergence-study/0.1", "id": "test", "description": "도구 계약 시험",
        "fixture": "test.json",
        "acceptance_profile": {"id": "test_only", "minimum_levels": 3, "max_resonance_relative_shift": 0.01, "max_s11_complex_delta": 0.02},
        "base_settings": {"frequency_hz": {"start": 2e9, "stop": 3e9, "count": 201}, "grid_mm": 0.4,
                          "air_padding_mm": 12, "curve_tolerance_mm": 0.025, "max_timesteps": 100000, "end_criterion": 1e-5},
        "cases": [
            *[{"label": "mesh_" + str(index), "axis": "mesh", "overrides": {"grid_mm": grid}} for index, grid in enumerate((0.5, 0.45, 0.4))],
            *[{"label": "boundary_" + str(index), "axis": "boundary", "overrides": {"air_padding_mm": margin}} for index, margin in enumerate((8, 10, 12))],
            *[{"label": "time_" + str(index), "axis": "termination", "overrides": {"end_criterion": energy}} for index, energy in enumerate((1e-5, 1e-6))],
        ],
    }


class IfaConvergenceToolTests(unittest.TestCase):
    """! @brief 저장된 연구의 실행과 별도 판정이 원본 계산을 혼합하지 않는지 검사한다."""

    def test_invalid_or_coupled_study_is_rejected_before_execution(self):
        """! @brief 부족한 수준, 역전 격자, 두 변수 변경과 잘못된 한계를 거부한다."""
        original = study_definition()
        for kind in ("levels", "order", "coupled", "duplicate", "nan", "bool"):
            value = deepcopy(original)
            if kind == "levels":
                value["cases"].pop()
            elif kind == "order":
                value["cases"][1]["overrides"]["grid_mm"] = 0.6
            elif kind == "coupled":
                value["cases"][0]["overrides"]["end_criterion"] = 1e-6
            elif kind == "duplicate":
                value["cases"][1]["label"] = value["cases"][0]["label"]
            elif kind == "nan":
                value["acceptance_profile"]["max_s11_complex_delta"] = float("nan")
            else:
                value["acceptance_profile"]["minimum_levels"] = True
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                validate_study(value)
        self.assertEqual(original, study_definition())

    def test_shared_anchor_reuses_exact_settings_hash_without_mutating_definition(self):
        """! @brief 세 연구의 공통 anchor를 동일한 실제 계산으로 연결할 수 있다."""
        definition = study_definition()
        before = deepcopy(definition)
        cases = validate_study(definition)
        anchors = [cases[index]["settings_hash"] for index in (2, 5, 6)]
        self.assertEqual(len(set(anchors)), 1)
        self.assertEqual(len({case["settings_hash"] for case in cases}), 6)
        self.assertEqual(definition, before)

    def test_resume_rejects_changed_fixture_workspace_profile_and_runtime(self):
        """! @brief 같은 보고서 경로라도 원본/판정/worker가 다르면 계산을 섞지 않는다."""
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            study, fixture, identity = study_definition(), {"data": "original"}, {"code": "original"}
            report = {"schema": "rfad.ifa-convergence-run/0.1", "workspace": str(workspace.resolve()), "study": study,
                      "study_hash": canonical_hash(study), "fixture_hash": canonical_hash(fixture), "runtime_identity": identity,
                      "subject": {"snapshot": "immutable"}}
            validate_resume(report, workspace, study, fixture, identity)
            for kind in ("fixture", "workspace", "profile", "runtime", "initializing"):
                current, path, config, source, runtime = deepcopy(report), workspace, deepcopy(study), deepcopy(fixture), deepcopy(identity)
                if kind == "fixture":
                    source["data"] = "changed"
                elif kind == "workspace":
                    path = workspace / "different"
                elif kind == "profile":
                    config["acceptance_profile"]["max_s11_complex_delta"] = 0.5
                elif kind == "runtime":
                    runtime["code"] = "changed"
                else:
                    current.pop("subject")
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    validate_resume(current, path, config, source, runtime)

    def test_lost_phase_response_replays_one_persistent_service_job(self):
        """! @brief 응답 저장 전 중단을 흉내 내도 저장 요청 키로 기존 작업만 복원한다."""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            report, entry = {"runs": {"one": {}}}, {}
            report["runs"]["one"] = entry
            report_path = root / "report.json"
            with ProjectService(root / "workspace") as service:
                opened, _ = wait(service, call(service, "project.open", {"path": "projects/phase", "open_mode": "create", "name": "단계 복원"}, mutation=True))
                context = {"project_id": opened["project_id"]}
                data = {"expected_revision": opened["revision_id"]}
                first = execute_phase(service, report, report_path, entry, "save", "project.save", data, context)
                count = len(service.journal.read()["jobs"])
                phase = entry["phases"]["save"]
                phase.pop("task")
                phase.pop("state")
                phase.pop("states")
                save_report(report_path, report)
                repeated = execute_phase(service, report, report_path, entry, "save", "project.save", data, context)
                self.assertEqual(first, repeated)
                self.assertEqual(len(service.journal.read()["jobs"]), count)
                self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), report)
                with self.assertRaises(ValueError):
                    execute_phase(service, report, report_path, entry, "save", "project.save", {"expected_revision": "different"}, context)

    def test_csv_retains_complex_values_and_undefined_values_without_interpolation(self):
        """! @brief 정의되지 않은 dB/VSWR는 빈 칸이고 직접 복소 표본은 바뀌지 않는다."""
        cases = [{"label": "case", "axis": "mesh", "normalized_result": {"samples": [
            {"frequency_hz": 2.45e9, "s11": [0.0, 0.0], "s11_db": None, "impedance_ohm": [50.0, -2.0], "vswr": None}]}}]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "samples.csv"
            write_samples(path, cases)
            with path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["s11_db"], "")
            self.assertEqual(rows[0]["vswr"], "")
            self.assertEqual(float(rows[0]["z_imag_ohm"]), -2.0)
            self.assertEqual(float(rows[0]["frequency_hz"]), 2.45e9)

    def test_reassessment_retains_previous_immutable_decision_and_evaluator(self):
        """! @brief 새 판정을 저장해도 이전 판정 파일/해시와 판단기 출처가 남는다."""
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            report = {"study_hash": "a" * 64, "fixture_hash": "b" * 64}
            publish_assessment(path, report, [], {"status": "not_established"})
            first = deepcopy(report["assessment_artifact"])
            original = (path.parent / first["path"]).read_bytes()
            publish_assessment(path, report, [], {"status": "failed"})
            self.assertEqual(len(report["assessment_history"]), 2)
            self.assertNotEqual(first["path"], report["assessment_artifact"]["path"])
            self.assertEqual((path.parent / first["path"]).read_bytes(), original)
            self.assertEqual(json.loads(original)["assessment"]["status"], "not_established")
            self.assertEqual(len(json.loads(original)["evaluator"]), 2)

    def test_reassessment_rejects_normalized_reference_and_snapshot_substitution(self):
        """! @brief 진행표가 다른 유효 결과를 가리켜도 원래 artifact와 스냅샷의 판정으로 수용하지 않는다."""
        from test_convergence import fixture_result

        original = fixture_result()
        original_snapshot = deepcopy(original["provenance"]["analysis_plan"]["snapshot"])
        for mismatch in (None, "descriptor", "snapshot"):
            result = deepcopy(original)
            if mismatch == "snapshot":
                plan = result["provenance"]["analysis_plan"]
                plan["source_semantics"]["material"]["epsilon_r"] = 9.9
                plan["snapshot"] = {"snapshot_id": "other-snapshot", "content_hash": canonical_hash(plan["source_semantics"])}
                plan["plan_id"] = "other-physical-plan"
                result["analysis_plan_id"] = plan["plan_id"]
            data = canonical_bytes(result)
            registered = {"uri": "solver-artifacts/registered/normalized.json", "sha256": canonical_hash(result), "bytes": len(data)}
            descriptor = deepcopy(registered)
            if mismatch == "descriptor":
                descriptor["uri"] = "solver-artifacts/unrelated/normalized.json"
            plan = result["provenance"]["analysis_plan"]
            settings = deepcopy(plan["case"]["settings"])
            key = canonical_hash(settings)
            entry = {"status": "completed", "settings": settings, "artifact_id": "registered-result",
                     "normalized_result": descriptor, "analysis_plan": {"plan_id": plan["plan_id"], "content_hash": canonical_hash(plan)}}
            report = {"runs": {key: entry}, "runtime_identity": deepcopy(plan["runtime_identity"]),
                      "subject": {"context": {"project_id": "test-project"}, "snapshot": original_snapshot}}
            definitions = [{"label": "case", "axis": "mesh", "settings": settings, "settings_hash": key}]
            service = SimpleNamespace(journal=SimpleNamespace(read_artifact=Mock(return_value=data)))
            opened = {"artifact_id": entry["artifact_id"], "files": [{"role": "normalized_result", "media_type": "application/json", **registered}]}
            with self.subTest(mismatch=mismatch), patch("verify_ifa_convergence.call", return_value=opened):
                if mismatch is None:
                    loaded = load_cases(service, report, definitions)
                    self.assertEqual(loaded[0]["normalized_result"], original)
                else:
                    with self.assertRaises(ValueError):
                        load_cases(service, report, definitions)


if __name__ == "__main__":
    unittest.main()
