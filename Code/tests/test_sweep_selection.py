"""! @brief 명시 합성 결과 fixture로 사본 채택의 저장/출처/원자 명령 경계를 검증한다. FDTD 시험이 아니다."""

from copy import deepcopy
import math
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application import design_sweep_service, sweep_selection
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.design_sweep_store import load_definition, publish_candidate
from rfad.application.network_solver_import import solver_dataset
from rfad.application.pcb_solver import build_pcb_plan
from rfad.application.projects import ProjectService
from rfad.application.result_sources import resolve
from rfad.domain.design_sweep import candidate_at
from rfad.domain.errors import ProjectError
from rfad.domain.sweep_selection import KEY
from test_design_sweep import axis, typed
import test_design_sweep_runner as sweep_fixtures


class SelectionFixture:
    """! @brief native 실행 없이 봉인 계약만 만드는 시험 전용 준비이며 계산 검증으로 사용하지 않는다."""

    def __init__(self):
        """! @brief 실제 공개 연구 접수와 저장소를 재사용한다."""
        self.runner = sweep_fixtures.NativeSweepRunnerTests("runTest")
        self.runner.setUp()
        self.service = self.runner.service
        self.workspace = self.service.workspace
        self.document = deepcopy(self.runner.document)
        self.project = self.document["project_id"]
        self.axis_id = self.runner.spec["variables"][0]["id"]
        first, second = typed("1"), typed("1000", "um")
        first["source_refs"], second["source_refs"] = ["test:최초 계산 행"], ["test:선택한 중복 행 원문"]
        self.runner.spec["variables"] = [axis(self.axis_id, [first, second])]
        self.study = None

    def close(self):
        """! @brief 시험이 소유한 서비스만 닫는다."""
        self.runner.fixture.service = self.service
        self.runner.tearDown()

    def request(self, data, mutation=False, project=None):
        """! @brief 실제 서비스 epoch와 공개 API 봉투를 사용한다."""
        result = {"contract_version": "rfad.api/2.0", "context": {"project_id": project or self.project}, "input": deepcopy(data)}
        if mutation:
            result.update(request_key=str(uuid4()), request_key_epoch=self.service.policy()["request_key_epoch"])
        return result

    def seal(self):
        """! @brief 계약용 복소수임을 명시하고 현재 생성기 결과를 시험 준비에만 사용한다."""
        self.document = self.service._load(self.service.journal.read()["projects"][self.project])
        self.runner.document = self.document
        request = self.request({"expected_revision": self.document["revision_id"], "specification": self.runner.spec})
        preview = design_sweep_service.read(self.service.host_calculation_context, "sweep.preview", request)
        created = self.service.mutate("sweep.create", self.request({**request["input"], "review_hash": preview["review_hash"]}, True))
        self.study = created["study_id"]
        study = self.service.journal.read()["sweeps"][self.study]
        definition = load_definition(self.service, study)
        candidates = [candidate_at(self.document, definition["specification"], index) for index in range(2)]
        def register(state):
            """! @brief 합성 fixture의 파일을 실제 artifact hash와 소유 경로로 봉인한다."""
            study = state["sweeps"][self.study]
            project = state["projects"][self.project]
            source = candidates[0]["document"]
            snapshot = self.service.operations.snapshot(state, project, source, canonical_bytes(source),
                {"description": "합성 계약 시험용 표본; 실제 native 계산/물리 검증 아님"})
            plan = build_pcb_plan(source, snapshot, self.runner.fixture.runtime.identity, definition["specification"]["settings"])
            prepared = str(uuid4())
            original = {"schema": "rfad.openems-pcb-result/0.1", "analysis_plan_id": plan["plan_id"], "normalization": plan["normalization"],
                "samples": [{"frequency_hz": 8e9 + 4e9 * index / 30, "s11": [0.3, 0.4], "impedance_ohm": [60, 50],
                    "vswr": 3.0, "s11_db": 20 * math.log10(0.5), "vswr_status": "defined"} for index in range(31)],
                "assessment": {"status": "computed_unvalidated", "physics_validated": False, "converged": True, "finite_samples": True},
                "termination": {"status": "end_criterion_reached"},
                "provenance": {"analysis_plan": plan, "prepared_plan": {"prepared_plan_id": prepared},
                               "test_scope": "synthetic storage contract only; no FDTD"}}
            identity = str(uuid4())
            root = project["path"] + "/sweeps/" + self.study
            normalized = self.service.journal.put_immutable(root + "/fixture/normalized.json", canonical_bytes(original))
            state["solver_results"][identity] = {"project_id": self.project, "snapshot": snapshot, "analysis_plan_id": plan["plan_id"],
                "prepared_plan_id": prepared, "normalized": normalized, "files": [], "raw_files": [], "metadata": {"test_only": True}}
            dataset, _ = solver_dataset(self.service, state, source, identity)
            dataset_ref = self.service.journal.put_immutable(root + "/results/fixture-network.json", canonical_bytes(dataset))
            for index, candidate in enumerate(candidates):
                row = {"ordinal": index, "indices": candidate["indices"], "values": candidate["values"],
                    "evaluation_key": candidate["evaluation_key"], "validation_status": "valid", "state": "completed",
                    "phase": "finished", "outcome": "evaluated", "diagnostics": [], "attempts": [],
                    "results": {"dataset": dataset_ref}, "convergence_state": "not_established", "physics_validated": False}
                if index == 0:
                    row.update(solver_result_id=identity, solver_normalized=normalized, snapshot=snapshot)
                else:
                    row["cached_from_ordinal"] = 0
                publish_candidate(self.service, state, study, row)
            study.update(state="completed", next_index=2, counts={"total": 2, "completed": 2, "failed": 0, "pending": 0, "running": 0, "skipped": 0})
        self.service.journal.transaction(register)
        return self.study

    def context(self, index=1):
        """! @brief 실제 공통 결과 pin을 포함한 후보 문맥을 읽는다."""
        return sweep_selection.read(self.service, "sweep.selection.context", self.request({"study_id": self.study, "index": index}))

    def data(self, index=1, path=None):
        """! @brief 사용자 사유와 새 경로를 갖는 실제 검토 입력을 만든다."""
        context = self.context(index)
        return {"expected_revision": context["revision_id"], "study_id": self.study, "index": index,
            "definition_hash": context["definition_hash"], "source_pin": context["source_pin"],
            "name": "선택 후보 작업 사본", "path": path or context["defaults"]["path"], "reason": "원문을 유지하고 편집만 검토; 실물 성능 미확립"}

    def preview(self, index=1, path=None):
        """! @brief 실제 검토 응답과 요청 원문을 함께 돌려준다."""
        data = self.data(index, path)
        return data, sweep_selection.read(self.service, "sweep.selection.preview", self.request(data))

    def apply(self, index=1, path=None):
        """! @brief 한 검토 hash와 단일 명령/영수증으로 새 프로젝트를 만든다."""
        data, preview = self.preview(index, path)
        if not preview["can_apply"]:
            raise AssertionError(preview)
        request = self.request({**data, "review_hash": preview["review_hash"], "command_id": str(uuid4())}, True)
        return self.service.mutate("sweep.selection.apply", request), request


class SweepSelectionTests(unittest.TestCase):
    """! @brief 새 사본과 원본의 저장/역명령/재전송을 실제 journal에서 검사한다."""

    def setUp(self):
        """! @brief 매 시험의 독립 봉인 workspace를 준비한다."""
        self.fixture = SelectionFixture()
        self.addCleanup(self.fixture.close)
        self.fixture.seal()

    def test_duplicate_ordinal_source_undo_redo_and_saved_reopen(self):
        """! @brief 계산 재사용 행의 단위/출처를 잃지 않고 새 사본에서만 한 번에 되돌린다."""
        f = self.fixture
        before = f.service.journal.read()
        with patch("rfad.domain.design_sweep.candidate_at", side_effect=AssertionError("과거 후보 재생성 금지")):
            response, request = f.apply()
        self.assertEqual(f.service.mutate("sweep.selection.apply", request), response)
        state = f.service.journal.read()
        identity = response["new_project_id"]
        copied = f.service._load(state["projects"][identity])
        self.assertEqual(state["projects"][f.project], before["projects"][f.project])
        self.assertEqual(state["sweeps"], before["sweeps"])
        self.assertEqual(state["solver_results"], before["solver_results"])
        self.assertEqual(copied["parameters"][f.axis_id]["quantity"]["display_unit"], "um")
        self.assertEqual(copied["parameters"][f.axis_id]["quantity"]["source_refs"], ["test:선택한 중복 행 원문"])
        record = copied["extensions"][KEY]["records"][0]
        self.assertEqual((record["index"], record["calculated_ordinal"]), (1, 0))
        self.assertEqual(record["scope"], "editing_copy_only")
        for operation in ("undo", "redo"):
            current = f.service._load(f.service.journal.read()["projects"][identity])
            f.service.mutate("project." + operation, f.request({"expected_revision": current["revision_id"], "command_id": str(uuid4())}, True, identity))
            changed = f.service._load(f.service.journal.read()["projects"][identity])
            expected = f.document if operation == "undo" else copied
            self.assertEqual(changed["parameters"], expected["parameters"])
            self.assertEqual(changed["extensions"], expected["extensions"])
        saved = f.service.repository.read(f.service.journal.read()["projects"][identity]["saved"])[1]
        self.assertEqual(saved, copied)
        current_before = f.service.journal.read()["projects"]
        f.service.close()
        f.service = ProjectService(f.workspace, auto_run=False, clock=lambda: 2000000000.0)
        self.assertEqual(f.service.journal.read()["projects"], current_before)
        self.assertEqual(f.service.repository.read(f.service.journal.read()["projects"][identity]["saved"])[1], copied)

    def test_preview_and_rejected_review_leave_no_files_or_project_changes(self):
        """! @brief 검토 및 바뀐 사유/경로의 거절은 파일과 권위 상태를 바꾸지 않는다."""
        f = self.fixture
        before = f.service.journal.read()
        files = {str(path): path.read_bytes() for path in Path(f.workspace).rglob("*") if path.is_file() and path.name != ".writer.lock"}
        data, preview = f.preview()
        self.assertTrue(preview["can_apply"], preview)
        request = f.request({**data, "reason": "검토 이후 다른 사유", "review_hash": preview["review_hash"], "command_id": str(uuid4())}, True)
        with self.assertRaises(ProjectError) as caught:
            f.service.mutate("sweep.selection.apply", request)
        self.assertEqual(caught.exception.code, "E_CONFLICT")
        self.assertEqual(f.service.journal.read(), before)
        self.assertEqual({str(path): path.read_bytes() for path in Path(f.workspace).rglob("*") if path.is_file() and path.name != ".writer.lock"}, files)

    def test_receipt_owner_unresolved_expired_and_replay_after_source_edit(self):
        """! @brief 조회 실패/만료를 미생성으로 바꾸지 않고 동일 요청은 원래 결과를 반환한다."""
        f = self.fixture
        response, request = f.apply()
        receipt_input = {key: request[key] for key in ("request_key", "request_key_epoch")}
        result = sweep_selection.read(f.service, "sweep.selection.receipt", f.request(receipt_input))
        self.assertEqual(result["response"], response)
        self.assertEqual(result["status"], "found")
        missing = sweep_selection.read(f.service, "sweep.selection.receipt", f.request({**receipt_input, "request_key": "missing"}))
        self.assertEqual(missing["status"], "unresolved")
        with self.assertRaises(ProjectError):
            sweep_selection.read(f.service, "sweep.selection.receipt", f.request(receipt_input, project=response["new_project_id"]))
        f.service.mutate("project.apply_command", f.request({"expected_revision": f.document["revision_id"], "command_id": str(uuid4()),
            "type": "metadata.rename", "payload": {"name": "원본의 이후 편집"}}, True))
        self.assertEqual(f.service.mutate("sweep.selection.apply", request), response)
        with patch.object(f.service, "_now", return_value=1e20):
            expired = sweep_selection.read(f.service, "sweep.selection.receipt", f.request(receipt_input))
        self.assertEqual(expired["status"], "expired")
        self.assertIsNone(expired["response"])

    def test_pin_and_definition_changes_block_new_copy(self):
        """! @brief 정확한 source pin과 연구 정의 없이 같은 값의 후보로 대체하지 않는다."""
        f = self.fixture
        data, _ = f.preview()
        for field in ("definition_hash", "source_pin"):
            bad = deepcopy(data)
            bad[field] = "0" * 64 if field == "definition_hash" else {**bad[field], "identity_hash": "0" * 64}
            result = sweep_selection.read(f.service, "sweep.selection.preview", f.request(bad))
            self.assertFalse(result["can_apply"])
            self.assertEqual(result["issues"][0]["code"], "E_HASH")

    def test_current_edit_is_not_copied_and_literal_command_is_private(self):
        """! @brief 현재 후속 편집과 연구 baseline을 구분하고 공개 내부명령 우회를 막는다."""
        f = self.fixture
        f.service.mutate("project.apply_command", f.request({"expected_revision": f.document["revision_id"], "command_id": str(uuid4()),
            "type": "metadata.describe", "payload": {"description": "연구 뒤 현재 원본만 바꾼 메모"}}, True))
        data, preview = f.preview()
        self.assertTrue(preview["can_apply"], preview)
        self.assertFalse(preview["copy_summary"]["source_revision_matches_current"])
        response, _ = f.apply()
        copied = f.service._load(f.service.journal.read()["projects"][response["new_project_id"]])
        self.assertEqual(copied["metadata"]["description"], f.document["metadata"]["description"])
        with self.assertRaises(ProjectError) as caught:
            f.service.mutate("project.apply_command", f.request({"expected_revision": data["expected_revision"], "command_id": str(uuid4()),
                "type": "sweep.selection.apply", "payload": {}}, True))
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED")

    def test_physical_projection_ignores_only_validated_selection_origin(self):
        """! @brief 채택 출처 추가가 EM 형상을 바꾸지 않으며 같은 물리 키와 미정 물성을 유지한다."""
        from rfad.domain.design_sweep import _evaluation_key
        from test_pcb_solver import snapshot_for
        f = self.fixture
        response, _ = f.apply()
        copied = f.service._load(f.service.journal.read()["projects"][response["new_project_id"]])
        original = resolve(f.service, {"project_id": f.project}, {"kind": "sweep", "study_id": f.study, "index": 1})["source_document"]
        spec = load_definition(f.service, f.service.journal.read()["sweeps"][f.study])["specification"]
        self.assertEqual(_evaluation_key(copied, spec["settings"], None, spec), _evaluation_key(original, spec["settings"], None, spec))
        before = build_pcb_plan(original, snapshot_for(original), f.runner.fixture.runtime.identity, spec["settings"])
        after = build_pcb_plan(copied, snapshot_for(copied), f.runner.fixture.runtime.identity, spec["settings"])
        self.assertEqual(before["case"], after["case"])
        self.assertEqual(copied["materials"], original["materials"])
        self.assertTrue(any(item["epsilon_r"]["value_si"] is None for item in copied["materials"]))

    def test_public_rpc_advertises_exact_private_copy_flow(self):
        """! @brief 실제 NDJSON 공개 등록에서도 검토와 영수증을 구분한다."""
        from rfad.application.rpc import capabilities, handle_frame
        f = self.fixture
        methods = capabilities(f.service)["methods"]
        self.assertTrue(sweep_selection.READS | sweep_selection.MUTATIONS <= set(methods))
        result = handle_frame(canonical_bytes({"jsonrpc": "2.0", "id": 1, "method": "sweep.selection.context",
            "params": f.request({"study_id": f.study, "index": 1})}), f.service)
        self.assertNotIn("error", result, result)
        self.assertTrue(result["result"]["eligibility"]["can_select"])
        self.assertEqual(result["result"]["calculated_ordinal"], 0)


class SweepSelectionCopyTests(unittest.TestCase):
    """! @brief 사본의 활성 자료 파일 폐쇄와 역사 원문을 실제 봉인 바이트로 확인한다."""

    def setUp(self):
        """! @brief 연구를 봉인하기 전에 추가 자료를 연결할 수 있는 준비를 만든다."""
        self.fixture = SelectionFixture()
        self.addCleanup(self.fixture.close)

    def network(self, operation, parameters):
        """! @brief 임의 library 삽입 대신 실제 검토/원자 적용으로 자료를 생성한다."""
        from rfad.application import network_service
        f = self.fixture
        current = f.service._load(f.service.journal.read()["projects"][f.project])
        data = {"expected_revision": current["revision_id"], "operation": operation, "parameters": parameters}
        review = network_service.read(f.service.host_calculation_context, "network.preview", f.request(data))
        self.assertTrue(review["can_apply"], review)
        return f.service.mutate("network.apply", f.request({**data, "review_hash": review["review_hash"], "command_id": str(uuid4())}, True))["record_id"]

    def test_imported_and_derived_artifacts_copy_without_rewriting_provenance(self):
        """! @brief 가져온 원문/회로/파생 자료의 파일만 새 소유 경로로 복사하고 내부 출처는 그대로 둔다."""
        from test_network_service import import_parameters, circuit_definition
        from rfad.application.network_records import read_dataset
        from rfad.domain.network_library import KEY as LIBRARY_KEY
        f = self.fixture
        dataset = self.network("import", import_parameters(f.document["ports"][0]["id"]))
        circuit = self.network("circuit_save", {"name": "원래 회로", "definition": circuit_definition()})
        derived = self.network("circuit_apply", {"name": "원래 외부망", "dataset_id": dataset, "circuit_id": circuit})
        f.seal()
        before = f.service.journal.read()
        original_library = deepcopy(f.document["extensions"][LIBRARY_KEY])
        result, _ = f.apply()
        project = f.service.journal.read()["projects"][result["new_project_id"]]
        copied = f.service._load(project)
        library = copied["extensions"][LIBRARY_KEY]
        self.assertEqual(library["circuits"], original_library["circuits"])
        for row in library["datasets"]:
            old = next(item for item in original_library["datasets"] if item["id"] == row["id"])
            for field in ("dataset", "normalized_hdf5", "raw", "diagnostics"):
                if row[field] is not None:
                    self.assertTrue(row[field]["uri"].startswith(result["path"] + "/"))
                    self.assertNotEqual(row[field]["uri"], old[field]["uri"])
                    self.assertEqual(f.service.journal.read_artifact(row[field]), f.service.journal.read_artifact(old[field]))
            data, _ = read_dataset(f.service, project, library, row["id"])
            original_data, _ = read_dataset(f.service, before["projects"][f.project], original_library, row["id"])
            self.assertEqual(data, original_data)
        self.assertEqual(next(row for row in library["datasets"] if row["id"] == derived)["inputs"], [dataset])
        self.assertEqual(f.service.journal.read()["projects"][f.project], before["projects"][f.project])

    def test_unknown_extension_and_compound_library_are_not_silently_deleted(self):
        """! @brief 지원하지 않는 외부 소유권은 복사 전 차단하고 출처를 지우지 않는다."""
        from rfad.application.sweep_copy import prepare_artifacts
        from rfad.domain.network_library import empty_library
        f = self.fixture
        original = deepcopy(f.document)
        original["extensions"]["vendor.unresolved"] = {"manufacturing": None, "source_refs": ["사용자 보존 원문"]}
        before = deepcopy(original)
        with self.assertRaises(ProjectError) as caught:
            prepare_artifacts(f.service, f.service.journal.read()["projects"][f.project], original, "projects/새사본")
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED")
        self.assertEqual(original, before)
        original = deepcopy(f.document)
        original["extensions"][KEY] = None
        before = deepcopy(original)
        with self.assertRaises(ProjectError) as caught:
            prepare_artifacts(f.service, f.service.journal.read()["projects"][f.project], original, "projects/새사본")
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED")
        self.assertEqual(original, before)


if __name__ == "__main__":
    unittest.main()
