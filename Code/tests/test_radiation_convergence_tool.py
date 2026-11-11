"""! @brief 방사 연구의 재개/불변 판정과 봉인 파일 참조 대입 차단을 검사한다."""

from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.pcb_radiation import raw_names
from rfad.application.radiation_assessment import assess_study
from rfad.application.radiation_study import validate_study
from test_radiation_convergence import definition, cases_for
from verify_pcb_radiation_convergence import validate_resume, run
from radiation_convergence.evidence import load_cases, publish_assessment, write_metrics
from plot_pcb_radiation_convergence import read_assessment
from verify_pcb_radiation_faces import coordinates_match


def stored_case():
    """! @brief 실제 native 증거와 구분한 해시 검증용 메모리 파일 저장소를 만든다."""
    case = cases_for()[0]
    normalized = deepcopy(case["normalized_result"])
    plan = normalized["provenance"]["analysis_plan"]
    blobs, files = {}, []
    def put(role, data):
        """! @brief 시험 파일도 실제 바이트/길이/해시로 식별한다."""
        uri = "test/" + role
        blobs[uri] = data
        item = {"role": role, "uri": uri, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        files.append(item)
        return {key: item[key] for key in ("uri", "bytes", "sha256")}
    manifest = {"files": []}
    for name in raw_names(plan):
        ref = put("raw/" + name, b"explicit seal-only fixture, no native computation")
        manifest["files"].append({"role": "raw/" + name, "bytes": ref["bytes"], "sha256": ref["sha256"]})
    normalized["raw_manifest"] = manifest
    put("raw_manifest", canonical_bytes(manifest))
    put("provenance", canonical_bytes(normalized["provenance"]))
    put("radiation_native", b"not real HDF5; metadata test only")
    norm_ref = put("normalized_result", canonical_bytes(normalized))
    field_ref = put("radiation_result", canonical_bytes(case["radiation_result"]))
    plan_ref = put("analysis_plan", canonical_bytes(plan))
    files.pop()
    def read(ref):
        """! @brief 사본 변경과 파일 참조 변경을 실제 journal처럼 거부한다."""
        data = blobs[ref["uri"]]
        if len(data) != ref["bytes"] or hashlib.sha256(data).hexdigest() != ref["sha256"]:
            raise ValueError("test artifact hash mismatch")
        return data
    entry = {"status": "completed", "settings": case["settings"], "artifact_id": "original",
             "normalized_result": norm_ref, "radiation_result": field_ref,
             "analysis_plan": {"plan_id": plan["plan_id"], "content_hash": canonical_hash(plan), "artifact": plan_ref}}
    report = {"runs": {case["settings_hash"]: entry}, "runtime_identity": plan["runtime_identity"],
              "subject": {"snapshot": plan["snapshot"], "context": {"project_id": plan["snapshot"]["project_id"]}}}
    return case, report, {"artifact_id": "original", "files": files}, SimpleNamespace(journal=SimpleNamespace(read_artifact=read)), blobs


class RadiationConvergenceToolTests(unittest.TestCase):
    """! @brief 재판정은 원시 계산과 독립되고 다른 결과를 원본으로 수용하지 않는다."""

    def test_source_and_raw_face_substitution_are_blocked(self):
        """! @brief 유효 참조라도 원래 결과/계획/면과 다르면 연구 입력으로 거절한다."""
        for mode in (None, "field_reference", "snapshot", "surface", "missing_face"):
            case, report, opened, service, blobs = stored_case()
            if mode == "field_reference":
                report["runs"][case["settings_hash"]]["radiation_result"]["uri"] = "test/foreign.json"
            elif mode == "snapshot":
                report["subject"]["snapshot"]["revision_id"] = "foreign"
            elif mode == "surface":
                blobs["test/raw/pcb_nf2ff_H_2.h5"] += b"tamper"
            elif mode == "missing_face":
                opened["files"] = [item for item in opened["files"] if item["role"] != "raw/pcb_nf2ff_E_0.h5"]
            with self.subTest(mode=mode), patch("radiation_convergence.evidence.call", return_value=opened):
                if mode is None:
                    loaded = load_cases(service, report, [case])
                    self.assertEqual(loaded[0]["radiation_result"], case["radiation_result"])
                else:
                    with self.assertRaises(ValueError):
                        load_cases(service, report, [case])

    def test_resume_rejects_new_workspace_input_and_worker(self):
        """! @brief 다른 소스나 초기화 미완료 상태로 기존 연구를 이어 붙이지 않는다."""
        study, fixture, identity = definition(), {"explicit": "fixture"}, {"runtime": "original"}
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            original = {"schema": "rfad.pcb-radiation-study-run/0.1", "workspace": str(workspace.resolve()),
                        "study": study, "study_hash": canonical_hash(study), "fixture_hash": canonical_hash(fixture),
                        "runtime_identity": identity, "subject": {"snapshot": "original"}}
            validate_resume(original, workspace, study, fixture, identity)
            for mode in ("workspace", "input", "worker", "initializing"):
                report = deepcopy(original)
                path, source, runtime = workspace, fixture, identity
                if mode == "workspace":
                    path = workspace / "other"
                elif mode == "input":
                    source = {"explicit": "changed"}
                elif mode == "worker":
                    runtime = {"runtime": "changed"}
                else:
                    report.pop("subject")
                with self.subTest(mode=mode), self.assertRaises(ValueError):
                    validate_resume(report, path, study, source, runtime)

    def test_immutable_decisions_include_evaluator_source_and_csv_keeps_unknown(self):
        """! @brief 이전 판정은 남고 미평가 흡수 전력은 빈 칸으로 보존한다."""
        cases = cases_for()
        assessment = assess_study(cases, definition()["acceptance_profile"])
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            report = {"study_hash": "a" * 64, "fixture_hash": "b" * 64}
            publish_assessment(path, report, cases, assessment)
            first = deepcopy(report["assessment_artifact"])
            raw = (path.parent / first["path"]).read_bytes()
            publish_assessment(path, report, cases, assessment)
            self.assertEqual(len(report["assessment_history"]), 2)
            self.assertEqual((path.parent / first["path"]).read_bytes(), raw)
            for source in json.loads(raw)["evaluator"]:
                self.assertEqual(hashlib.sha256(source["source_utf8"].encode("utf-8")).hexdigest(), source["sha256"])
            report.update(schema="rfad.pcb-radiation-study-run/0.1", status="completed", assessment=assessment)
            path.write_bytes(canonical_bytes(report))
            self.assertEqual(read_assessment(path), assessment)
            changed = deepcopy(report)
            changed["assessment"]["numerical_stability"]["status"] = "forged"
            path.write_bytes(canonical_bytes(changed))
            with self.assertRaisesRegex(ValueError, "근거"):
                read_assessment(path)
            csv_path = path.with_suffix(".csv")
            write_metrics(csv_path, assessment)
            with csv_path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 9)
            self.assertTrue(all(row["independent_absorption_power_w_s2"] == "" for row in rows))

    def test_actual_face_coordinates_require_matching_count_units_and_finite_values(self):
        """! @brief HDF5의 m 좌표를 mm 계획과 비교하며 잘못된 단위나 NaN을 차단한다."""
        self.assertTrue(coordinates_match([-30, 0, 30], [-0.03, 0, 0.03]))
        self.assertTrue(coordinates_match([-30], [-0.03 + 1e-13]))
        for values in ([-30, 0, 30], [-0.03, 0], [-0.03, float("nan"), 0.03], [-0.03, 0.001, 0.03]):
            self.assertFalse(coordinates_match([-30, 0, 30], values))

    def test_power_frequency_requires_a_direct_port_sample(self):
        """! @brief 주파수 보간으로 포트 전력 수지 검사를 채우지 않는다."""
        study = definition()
        study["base_settings"]["radiation"]["frequency_hz"] = [10e9 + 1]
        with self.assertRaisesRegex(ValueError, "직접 포트 표본"):
            validate_study(study)


if __name__ == "__main__":
    unittest.main()
