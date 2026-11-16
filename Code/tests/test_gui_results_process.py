"""! @brief 실제 Windows 결과 화면의 과거 원본/Smith/비교/교환과 서비스 재시작을 검증한다."""

import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.application import network_service, result_service
from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.domain.network_library import KEY
from test_cad_worker_process import register_fixture, request, status
from test_design_rules import scenario
from test_network_service import import_parameters


ROOT = Path(__file__).resolve().parents[1]
GUI = os.environ.get("RFAD_GUI_EXE", "")


def fixture(workspace):
    """! @brief 원문이 알려진 분석식 표본이며 실측/해석 검증 자료라고 주장하지 않는다."""
    with ProjectService(workspace, auto_run=False) as service:
        document = scenario()
        document["extensions"]["test.results-original"] = {"source_refs": ["화면/분석식 시험 전용"], "fabrication": None, "measurement": None}
        document, original_snapshot = register_fixture(service, document)
        original = deepcopy(document)
        selections, descriptions = {}, {}
        for key, name, frequencies, values, declared in (
                ("first", "분석식 A - 개방 단락 능동 표본", [1e9, 1.25e9, 1.5e9, 2e9], [0, 1, -1, 2], True),
                ("second", "분석식 B - 다른 주파수 표본", [1e9, 1.25e9, 1.75e9, 2e9], [.2, .5, -.4, .8], True),
                ("unknown", "미정 원문 - 규약 채택 없음", [1e9, 1.25e9, 1.5e9, 2e9], [.1, .2, .3, .4], False)):
            parameters = import_parameters(declared=declared)
            parameters["name"] = name
            parameters["file_name"] = key + ".s1p"
            raw = ("! 화면 경계 표본; 실측 아님\n# Hz S RI R 50\n" + "".join(f"{frequency:.17g} {value:.17g} 0\n" for frequency, value in zip(frequencies, values))).encode("utf-8")
            parameters["source_base64"] = base64.b64encode(raw).decode("ascii")
            if key == "second":
                parameters["declarations"]["conditions"] = {
                    "manufacturing": {"note": "다른 탐색 가정"}, "measurement": None,
                    **{f"검토조건{index:02d}": None if index % 2 == 0 else f"보존 조건 {index}"
                       for index in range(40)}}
            data = {"expected_revision": document["revision_id"], "operation": "import", "parameters": parameters}
            preview = network_service.read(service, "network.preview", {"contract_version": "rfad.api/2.0", "context": {"project_id": document["project_id"]}, "input": data})
            if not preview["can_apply"]:
                raise AssertionError(preview)
            applied = service.mutate("network.apply", request(service, document["project_id"], {**data,
                "command_id": str(uuid4()), "review_hash": preview["review_hash"]}))
            document = service._load(service.journal.read()["projects"][document["project_id"]])
            selections[key] = {"kind": "network", "dataset_id": applied["record_id"], "revision_id": document["revision_id"], "snapshot_id": None}
        service.mutate("project.apply_command", request(service, document["project_id"], {
            "expected_revision": document["revision_id"], "command_id": str(uuid4()), "type": "metadata.describe",
            "payload": {"description": "선택한 결과보다 뒤의 현재 편집 개정; 원본은 유지"}}))
        document = service._load(service.journal.read()["projects"][document["project_id"]])
        for key, source in selections.items():
            descriptions[key] = result_service.read(service, "result.describe", {"contract_version": "rfad.api/2.0",
                "context": {"project_id": document["project_id"]}, "input": {"source": source}})
        saved = service.mutate("project.save", request(service, document["project_id"], {"expected_revision": document["revision_id"]}))
        service.run_next()
        if status(service, saved["job_id"])["state"] != "completed":
            raise AssertionError(status(service, saved["job_id"]))
        files = {reference["uri"]: service.journal.read_artifact(reference) for item in document["extensions"][KEY]["datasets"]
                 for reference in (item["dataset"], item["raw"], item["normalized_hdf5"])}
        data = {"sources": selections, "descriptions": descriptions, "revision_id": document["revision_id"], "project_id": document["project_id"]}
        (workspace / "results-smoke-fixture.json").write_bytes(canonical_bytes(data))
        return original, original_snapshot, document, files, data


class ResultConditionsPagingTests(unittest.TestCase):
    """! @brief 많은 원문 조건의 모든 페이지를 실제 읽기 계약과 불변 원본으로 대조한다."""

    def test_explicit_condition_pages_keep_tail_unknowns_and_originals(self):
        """! @brief 첫32개와 마지막 페이지를 합쳐 빠진 조건이 없는지 확인하고 원본 bytes를 보존한다."""
        with TemporaryDirectory(prefix="TraceWave 조건 페이지 ") as directory:
            workspace = Path(directory)
            _, _, document, files, inputs = fixture(workspace)
            with ProjectService(workspace, auto_run=False) as service:
                pair = {key: {"source": inputs["descriptions"][source]["source"],
                              "pin": inputs["descriptions"][source]["pin"]}
                        for key, source in (("left", "first"), ("right", "second"))}
                def read(method, values):
                    return result_service.read(service, method, {"contract_version": "rfad.api/2.0",
                        "context": {"project_id": document["project_id"]}, "input": values})
                compared = read("result.compare", {**pair, "right_port_order": [0], "row": 0,
                    "column": 0, "frequency_policy": "exact_only", "offset": 0, "limit": 201})
                self.assertEqual(len(compared["condition_differences"]), 32)
                self.assertGreater(compared["condition_count"], 32)
                rows, offset = [], 0
                while offset is not None:
                    page = read("result.conditions", {**pair, "offset": offset, "limit": 32})
                    self.assertEqual(page["left"], pair["left"])
                    self.assertEqual(page["right"], pair["right"])
                    self.assertEqual(page["offset"], offset)
                    self.assertLessEqual(len(page["items"]), 32)
                    rows.extend(page["items"])
                    offset = page["next_offset"]
                self.assertEqual(len(rows), compared["condition_count"])
                self.assertEqual(len({row["field"] for row in rows}), len(rows))
                self.assertEqual(rows[:32], compared["condition_differences"])
                last = next(row for row in rows if row["field"] == "conditions.검토조건39")
                self.assertEqual(last["right_display"], "보존 조건 39")
                unknown = next(row for row in rows if row["field"] == "conditions.검토조건38")
                self.assertEqual(unknown["difference"], "both_unknown")
                self.assertEqual(service._load(service.journal.read()["projects"][document["project_id"]]), document)
                for uri, content in files.items():
                    self.assertEqual((workspace / uri).read_bytes(), content)


@unittest.skipUnless(sys.platform == "win32" and GUI, "RFAD_GUI_EXE로 Windows GUI를 지정합니다.")
class GuiResultsTests(unittest.TestCase):
    """! @brief 실제 wx 입력 이벤트와 서비스 응답으로 고정된 과거 원본을 검증한다."""

    def test_native_past_sources_smith_compare_export_and_reopen(self):
        """! @brief 표시 선택/단위/마커와 재시작이 프로젝트 원본 및 과거 결과를 바꾸지 않는다."""
        with TemporaryDirectory(prefix="TraceWave 결과 표시 ") as directory:
            workspace = Path(directory) / "작업 영역"
            original, snapshot, saved, files, inputs = fixture(workspace)
            report_path = Path(directory) / "결과 화면 검증.json"
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.run([str(Path(GUI).resolve()), "--python", sys.executable, "--source", str(ROOT / "src"),
                "--workspace", str(workspace), "--open-project", "projects/CAD 한글 교환 검증", "--results-smoke-test",
                "--smoke-report", str(report_path)], stdin=subprocess.DEVNULL, capture_output=True,
                startupinfo=startup, timeout=180, check=False)
            self.assertTrue(report_path.is_file(), (process.returncode, process.stderr))
            report = json.loads(report_path.read_bytes())
            if output := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                destination = Path(output) / "results.json"
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(report_path.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            self.assertTrue(report["passed"], report)
            self.assertGreaterEqual(report["service_sessions"], 2)
            self.assertEqual(set(report["setup_checks"]), {
                "results_past_revision_named_catalog", "results_unknown_source_preserved",
                "results_late_selection_reset_destroy_safe", "results_smith_poles_active_and_units",
                "results_explicit_port_comparison_and_conditions", "results_exact_shared_frequency_marker",
                "results_comparison_selection_restores_source_conditions",
                "results_grouped_conditions_preserve_unknowns",
                "results_conditions_pages_and_stale_selection",
                "results_pinned_historical_export", "results_saved_restart_preserves_source",
                "results_return_design_preserves_selection"})
            with ProjectService(workspace, auto_run=False) as service:
                current = service._load(service.journal.read()["projects"][saved["project_id"]])
                self.assertEqual(current, saved)
                self.assertEqual(service.journal.read_artifact(snapshot["artifact"]), canonical_bytes(original))
                for uri, expected in files.items():
                    self.assertEqual((workspace / uri).read_bytes(), expected)
                for key, source in inputs["sources"].items():
                    described = result_service.read(service, "result.describe", {"contract_version": "rfad.api/2.0",
                        "context": {"project_id": saved["project_id"]}, "input": {"source": source}})
                    self.assertEqual(described["pin"], inputs["descriptions"][key]["pin"])
            exported = Path(directory) / "GUI 과거 결과.csv"
            self.assertTrue(exported.is_file(), {"expected": str(exported),
                "files": [entry.name for entry in Path(directory).iterdir()]})
            sidecar = json.loads(exported.with_name(exported.name + ".conditions.json").read_bytes())
            self.assertEqual(sidecar["source"], inputs["sources"]["first"])
            self.assertEqual(sidecar["pin"], inputs["descriptions"]["first"]["pin"])
            self.assertIsNone(sidecar["descriptor"]["conditions"]["measurement"])


if __name__ == "__main__":
    unittest.main()
