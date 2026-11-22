"""! @brief 실제 회로 후보와 과거 계산 원문에 공통 결과 조회를 연결한다."""

from copy import deepcopy
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from rfad.application.canonical import canonical_hash
from rfad.application.solver_evidence import read as read_evidence
from rfad.application.projects import ProjectService
from rfad.application.result_service import read
from rfad.application.result_sources import resolve, read_solver_artifact
from rfad.domain.errors import ProjectError


class ResultSweepTests(unittest.TestCase):
    """! @brief 실제 회로 엔진 산출물의 과거 원본을 현재 후보 생성 없이 조회한다."""

    def setUp(self):
        """! @brief 공개 연구 명령으로 외부 회로 세 후보를 실제 계산한다."""
        from test_design_sweep_runner import DesignSweepRunnerTests

        self.runner = DesignSweepRunnerTests("runTest")
        self.runner.setUp()
        self.addCleanup(self.runner.tearDown)
        self.fixture = self.runner.fixture
        self.fixture.spec["target_ids"] = [item["id"] for item in self.fixture.original["targets"]]
        self.study = self.fixture.create()
        self.runner.command("start", self.study)
        self.runner.run_all(self.study)

    def query(self, method, **data):
        """! @brief 현재 source 생성기 재실행이 결과 조회에 들어가지 않도록 차단한다."""
        before = self.fixture.service.journal.read()
        with patch("rfad.domain.design_sweep.candidate_at", side_effect=AssertionError("현재 후보 재생성 금지")):
            result = read(self.fixture.service, method, self.fixture.request(data))
        self.assertEqual(self.fixture.service.journal.read(), before)
        return result

    def test_actual_circuit_and_duplicate_have_distinct_source_same_dataset(self):
        """! @brief 동일 계산 재사용도 선택 후보와 당시 목표 원문을 지우지 않는다."""
        first = {"kind": "sweep", "study_id": self.study, "index": 1}
        second = {**first, "index": 2}
        left, right = [self.query("result.describe", source=source) for source in (first, second)]
        self.assertEqual(left["pin"]["dataset_sha256"], right["pin"]["dataset_sha256"])
        self.assertNotEqual(left["pin"]["identity_hash"], right["pin"]["identity_hash"])
        self.assertEqual(left["calculated_ordinal"], 1)
        self.assertEqual(right["calculated_ordinal"], 1)
        self.assertFalse(left["available_views"]["radiation"])
        self.assertEqual(left["source_document_role"], "study_baseline")
        self.assertEqual(left["source_revision"]["id"], self.fixture.original["revision_id"])
        self.assertEqual(self.fixture.document(), self.fixture.original)
        self.assertNotEqual(left["selection_values"], right["selection_values"])
        self.assertTrue(left["historical_assessments"])
        self.assertTrue(all(item["physics_validated"] is False for item in left["historical_assessments"]))
        result = self.query("result.compare", left={"source": first, "pin": left["pin"]},
            right={"source": second, "pin": right["pin"]}, right_port_order=[0], row=0, column=0,
            frequency_policy="exact_only", offset=0, limit=201)
        self.assertEqual(result["points"][0]["difference_ri"], [0.0, 0.0])
        self.assertEqual(result["physical_comparability"]["status"], "not_established")
        from rfad.adapters.network_hdf5 import decode_network_hdf5

        exported = self.query("result.export", source=second, pin=right["pin"], format="hdf5")
        self.assertEqual(canonical_hash(decode_network_hdf5(base64.b64decode(exported["content_base64"]))), right["pin"]["dataset_sha256"])
        self.assertEqual(exported["sidecar"]["historical_assessments"], right["historical_assessments"])
        self.assertEqual(exported["sidecar"]["source"], second)
        with self.assertRaises(ProjectError) as raw_error:
            self.query("result.export", source=second, pin=right["pin"], format="source")
        self.assertEqual(raw_error.exception.code, "E_CONFLICT")
        with self.assertRaises(ProjectError):
            self.query("result.describe", source={**first, "index": 0})

    def test_candidate_dataset_reference_cannot_escape_the_study(self):
        """! @brief 유효한 다른 자료 hash여도 현재 연구 후보의 원본으로 수용하지 않는다."""
        from rfad.application.design_sweep_store import load_candidate

        service = self.fixture.service
        state = service.journal.read()
        study = state["sweeps"][self.study]
        candidate = load_candidate(service, study, 1)
        entry = self.fixture.document()["extensions"]["rfad.network-library"]["datasets"][0]
        candidate["results"]["dataset"] = deepcopy(entry["dataset"])
        with patch("rfad.application.design_sweep_store.load_candidate", return_value=candidate), self.assertRaises(ProjectError) as caught:
            self.query("result.describe", source={"kind": "sweep", "study_id": self.study, "index": 1})
        self.assertEqual(caught.exception.code, "E_HASH")

    def test_cached_candidate_cycle_is_rejected_without_recalculation(self):
        """! @brief 저장된 중복 참조가 순환하면 새 계산으로 덮지 않고 오류를 반환한다."""
        from rfad.application.design_sweep_store import load_candidate

        service = self.fixture.service
        study = service.journal.read()["sweeps"][self.study]
        candidate = load_candidate(service, study, 2)
        candidate["cached_from_ordinal"] = 2
        with patch("rfad.application.design_sweep_store.load_candidate", return_value=candidate), self.assertRaises(ProjectError) as caught:
            self.query("result.describe", source={"kind": "sweep", "study_id": self.study, "index": 2})
        self.assertEqual(caught.exception.code, "E_HASH")


LEGACY = os.environ.get("RFAD_RESULT_LEGACY_WORKSPACE", "")


@unittest.skipUnless(LEGACY, "RFAD_RESULT_LEGACY_WORKSPACE로 보존 실제 PCB 계산을 지정해야 합니다.")
class ResultLegacySolverTests(unittest.TestCase):
    """! @brief 원본 폴더를 서비스로 열지 않고 복사본에서 과거 전역 산출물을 조회한다."""

    def test_real_legacy_global_artifact_snapshot_and_runtime_free_reopen(self):
        """! @brief old solver-artifacts 경로, 실제 입력 개정과 고정 pin이 재열기를 통과한다."""
        original = Path(LEGACY).resolve()
        pointer = json.loads((original / "current.json").read_bytes())
        commit = original / "commits" / pointer["commit_id"]
        state = json.loads((commit / "state.json").read_bytes())
        artifact_id = "a73812c0-9c38-4b82-bd9b-99f7066752dc"
        record = state["solver_results"][artifact_id]
        source = {"kind": "solver", "artifact_id": artifact_id}
        context = {"project_id": record["project_id"]}
        plan = state["analysis_plans"][record["analysis_plan_id"]]["reference"]
        refs = [record["normalized"], record["snapshot"]["artifact"], plan["artifact"],
                *[row["artifact"] for row in record["files"]]]
        before = {item["uri"]: hashlib.sha256((original / item["uri"]).read_bytes()).hexdigest() for item in refs}
        with TemporaryDirectory(prefix="보존 solver 결과 조회 ") as directory:
            workspace = Path(directory)
            shutil.copy2(original / "current.json", workspace / "current.json")
            shutil.copytree(commit, workspace / "commits" / pointer["commit_id"])
            shutil.copytree(original / "projects", workspace / "projects")
            for reference in refs:
                target = workspace / reference["uri"]
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original / reference["uri"], target)
            with ProjectService(workspace, auto_run=False) as service:
                resolved = resolve(service, context, source)
                self.assertEqual(resolved["source_snapshot"], record["snapshot"])
                describe = read(service, "result.describe", {"contract_version": "rfad.api/2.0",
                    "context": context, "input": {"source": source}})
                self.assertEqual(describe["solver_evidence_artifact_id"], artifact_id)
                evidence = read_evidence(service, {"contract_version": "rfad.api/2.0", "context": context,
                    "input": {"artifact_id": artifact_id}})
                self.assertEqual(evidence["snapshot"], record["snapshot"])
                self.assertEqual(evidence["plan"], plan)
                self.assertEqual(evidence["settings"], resolved["normalized"]["provenance"]["analysis_plan"]["case"]["settings"])
                self.assertEqual(resolved["source_revision"]["id"], record["snapshot"]["revision_id"])
                self.assertEqual(resolved["normalized"]["provenance"]["analysis_plan"]["source_semantics"], resolved["source_document"])
                self.assertEqual(resolved["pin"]["dataset_sha256"], canonical_hash(resolved["dataset"]))
                self.assertIsNone(resolved["dataset"]["conditions"]["absolute_power_w"])
                self.assertIsNone(resolved["dataset"]["conditions"]["manufacturing"])
                self.assertTrue(resolved["normalized"]["radiation_summary"])
                self.assertEqual(resolved["numerical_details"]["solver_assessment"], resolved["normalized"]["assessment"])
                self.assertEqual(resolved["numerical_details"]["termination"], resolved["normalized"]["termination"])
                self.assertEqual(resolved["numerical_details"]["formal_convergence"], "not_established")
                self.assertEqual(read_solver_artifact(service, resolved["project"], record, record["normalized"]),
                    (original / record["normalized"]["uri"]).read_bytes())
                pin = resolved["pin"]
                response = read(service, "result.smith", {"contract_version": "rfad.api/2.0", "context": context,
                    "input": {"source": source, "pin": pin, "port": 0, "chart": "impedance", "offset": 0, "limit": 201}})
                self.assertTrue(response["points"][0]["smith_valid"])
                exported = read(service, "result.export", {"contract_version": "rfad.api/2.0", "context": context,
                    "input": {"source": source, "pin": pin, "format": "source"}})
                self.assertEqual(base64.b64decode(exported["content_base64"]), (original / record["normalized"]["uri"]).read_bytes())
                self.assertEqual(exported["sidecar"]["source_snapshot"], record["snapshot"])
                wrong_state = service.journal.read()
                wrong_state["solver_results"][artifact_id]["snapshot"]["description"] = "다른 입력이라고 주장하는 색인"
                with patch.object(service.journal, "read", return_value=wrong_state), self.assertRaises(ProjectError) as caught:
                    resolve(service, context, source)
                self.assertEqual(caught.exception.code, "E_HASH")
            with ProjectService(workspace, auto_run=False) as reopened:
                self.assertEqual(resolve(reopened, context, source, pin)["pin"], pin)
        after = {item["uri"]: hashlib.sha256((original / item["uri"]).read_bytes()).hexdigest() for item in refs}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
