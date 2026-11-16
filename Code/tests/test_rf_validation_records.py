"""! @brief 합성 전송과 실제 영속 서비스로 RF 검증 캠페인의 수명 및 과거 판정을 검사한다.

@details 모든 수치는 계약 시험용 합성이며 native RF 정확도 또는 실제 수렴의 증거가 아니다.
"""

from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application.canonical import canonical_hash
from rfad.application.projects import ProjectService
from rfad.application.result_service import read as result_read
from rfad.application.rf_validation_records import read
from rfad.domain.errors import ProjectError
from test_rf_reference_jobs import ReferenceTransport
import test_solver_jobs


class RFValidationRecordTests(unittest.TestCase):
    """! @brief 검토/접수/예산/취소/별도 판정을 원래 프로젝트와 분리한다."""

    def setUp(self):
        """! @brief 독립 journal과 명시적 가짜 전송을 생성한다."""
        self.host = test_solver_jobs.SolverJobTests("runTest")
        self.host.setUp()
        self.addCleanup(self.host.tearDown)
        self.host.transport.__class__ = ReferenceTransport
        self.original = self.document()

    @property
    def service(self):
        """! @brief 재시작 후의 서비스 소유자를 반환한다."""
        return self.host.service

    def document(self):
        """! @brief 현재 프로젝트의 실제 봉인 원문을 읽는다."""
        state = self.service.journal.read()
        return json.loads(self.service.journal.read_artifact(state["projects"][self.host.project]["current"]))

    def query(self, method, **data):
        """! @brief 공개 조회가 영속 저장소를 바꾸지 않는지 확인한다."""
        before = self.service.journal.read()
        result = read(self.service, method, {"contract_version": "rfad.api/2.0",
            "context": {"project_id": self.host.project}, "input": data})
        self.assertEqual(self.service.journal.read(), before)
        return result

    def command(self, method, **data):
        """! @brief 공통 request ledger를 통과하는 공개 명령을 사용한다."""
        return self.service.mutate(method, self.host.request(data))

    def create(self):
        """! @brief 실제 검토 hash로 이름/원본/고정 조건을 봉인한다."""
        preview = self.query("rf.validation.preview", expected_revision=self.host.revision, name="합성 캠페인 계약 시험")
        result = self.command("rf.validation.create", expected_revision=self.host.revision,
            name="합성 캠페인 계약 시험", review_hash=preview["review_hash"])
        return result["validation_id"]

    def record(self, identity):
        """! @brief 시험에서 영속 예약 및 불변 참조를 확인한다."""
        return self.service.journal.read()["rf_validations"][identity]

    def advance(self, identity, case, phase, *, execute=True):
        """! @brief 기존 조정기의 한 작업만 명시적으로 실행한다."""
        result = self.command("rf.validation.advance", validation_id=identity, case_id=case, phase=phase)
        if execute:
            self.service.solver.run_next()
            self.assertEqual(self.host.status(result)["state"], "completed", self.host.status(result))
        return result

    def test_review_idempotency_and_blocked_cases_keep_project_and_sources(self):
        """! @brief 검토는 무기록이고 같은 영수증은 캠페인과 예산을 중복 생성하지 않는다."""
        before = self.service.journal.read()
        preview = self.query("rf.validation.preview", expected_revision=self.host.revision, name="고정 검토")
        self.assertEqual(self.service.journal.read(), before)
        self.assertEqual(len(preview["definition"]["cases"]), 9)
        self.assertEqual(sum(c["blocked_reason"] is not None for c in preview["definition"]["cases"]), 6)
        self.assertIsNone(preview["definition"]["finite_feed_cross_section"])
        for changed in ({"name": "검토하지 않은 이름"}, {"review_hash": "0" * 64}):
            data = {"expected_revision": self.host.revision, "name": "고정 검토", "review_hash": preview["review_hash"], **changed}
            with self.subTest(changed=changed), self.assertRaises(ProjectError) as error:
                self.command("rf.validation.create", **data)
            self.assertEqual(error.exception.code, "E_CONFLICT")
        request = self.host.request({"expected_revision": self.host.revision, "name": "고정 검토", "review_hash": preview["review_hash"]})
        first = self.service.mutate("rf.validation.create", request)
        record = deepcopy(self.record(first["validation_id"]))
        self.assertEqual(self.service.mutate("rf.validation.create", request), first)
        self.assertEqual(self.record(first["validation_id"]), record)
        view = self.query("rf.validation.get", validation_id=first["validation_id"], report_id=None)
        self.assertIsNone(view["manufacturing"])
        self.assertIsNone(view["measurement"])
        self.assertEqual(view["source_refs"], preview["definition"]["source_refs"])
        for case in ("sheet-1", "finite_feed-1"):
            with self.subTest(case=case), self.assertRaises(ProjectError) as error:
                self.advance(first["validation_id"], case, "plan")
            self.assertEqual(error.exception.code, "E_UNSUPPORTED")
        self.assertEqual(self.record(first["validation_id"])["usage"], record["usage"])
        self.assertEqual(self.document(), self.original)

    def test_all_prepare_gate_reports_and_runtime_free_historical_reopen(self):
        """! @brief 세 수준 준비 전 계산을 차단하고 이전 판정과 실제 결과 참조를 따로 보존한다."""
        identity = self.create()
        first = self.command("rf.validation.assess", validation_id=identity)
        old_bytes = self.service.journal.read_artifact(first["artifact"])
        old_view = self.query("rf.validation.get", validation_id=identity, report_id=first["report_id"])
        self.assertTrue(all(case["source"] is None for case in old_view["cases"]))
        self.advance(identity, "dipole-1", "plan")
        self.assertEqual(self.query("rf.validation.get", validation_id=identity, report_id=None)["cases"][0]["execution_state"], "planned")
        self.advance(identity, "dipole-1", "prepare")
        self.assertEqual(self.query("rf.validation.get", validation_id=identity, report_id=None)["cases"][0]["execution_state"], "prepared")
        usage = deepcopy(self.record(identity)["usage"])
        with self.assertRaises(ProjectError) as error:
            self.advance(identity, "dipole-1", "solve")
        self.assertEqual(error.exception.code, "E_CONFLICT")
        self.assertEqual(self.record(identity)["usage"], usage)
        self.assertEqual(len(self.host.transport.calls), 1)
        for level in (2, 3):
            self.advance(identity, "dipole-" + str(level), "plan")
            self.advance(identity, "dipole-" + str(level), "prepare")
        for level in (1, 2, 3):
            case = "dipole-" + str(level)
            self.advance(identity, case, "solve")
            self.assertEqual(self.query("rf.validation.get", validation_id=identity, report_id=None)["cases"][level - 1]["execution_state"], "solved")
            self.advance(identity, case, "postprocess")
            viewed = self.query("rf.validation.get", validation_id=identity, report_id=None)["cases"][level - 1]
            self.assertEqual(viewed["execution_state"], "postprocessed")
            self.assertEqual(viewed["phase_states"]["postprocess"]["state"], "completed")
        second = self.command("rf.validation.assess", validation_id=identity)
        self.assertNotEqual(first["report_id"], second["report_id"])
        report = self.query("rf.validation.get", validation_id=identity, report_id=second["report_id"])
        self.assertEqual(report["status"], "partial_evidence")
        self.assertFalse(report["physics_validated"])
        self.assertEqual(report["validation_states"]["mesh"]["state"], "observed_not_established")
        self.assertEqual(report["validation_states"]["boundary"]["state"], "not_established")
        self.assertTrue(any(row["state"] == "requires_review" for row in report["rows"]))
        dipoles = [case for case in report["cases"] if case["group"] == "dipole"]
        self.assertEqual(len({case["source"]["artifact_id"] for case in dipoles}), 3)
        self.assertTrue(all(case["pin"] and case["postprocess_evidence"] for case in dipoles))
        self.assertEqual(self.record(identity)["usage"]["native_solves"], 3)
        self.assertEqual(self.record(identity)["usage"]["worker_calls"], 9)
        self.assertEqual(self.record(identity)["usage"]["analysis_seconds"], 900)
        self.assertEqual(len(self.host.transport.calls), 9)
        reports = self.query("rf.validation.reports", validation_id=identity, offset=0, limit=25)
        self.assertEqual([r["report_id"] for r in reports["items"]], [second["report_id"], first["report_id"]])
        self.assertEqual(self.service.journal.read_artifact(first["artifact"]), old_bytes)
        self.assertEqual(self.document(), self.original)
        self.service.close()
        self.host.service = ProjectService(self.host.workspace, auto_run=False)
        self.assertEqual(self.query("rf.validation.get", validation_id=identity, report_id=first["report_id"]), old_view)
        self.assertEqual(self.query("rf.validation.get", validation_id=identity, report_id=second["report_id"]), report)
        for case in dipoles:
            selected = result_read(self.service, "result.describe", {"contract_version": "rfad.api/2.0",
                "context": {"project_id": self.host.project}, "input": {"source": case["source"]}})
            self.assertEqual(selected["pin"], case["pin"])
            self.assertIsNone(selected["reference_scope"]["manufacturing"])
        self.assertEqual(canonical_hash(self.document()), canonical_hash(self.original))
        self.assertEqual(self.service.journal.read_artifact(first["artifact"]), old_bytes)

    def test_phase_receipt_replay_and_fresh_duplicate_do_not_increase_usage(self):
        """! @brief 접수 응답을 잃어도 같은 phase를 두 번 실행하거나 예산을 재설정하지 않는다."""
        identity = self.create()
        request = self.host.request({"validation_id": identity, "case_id": "dipole-1", "phase": "plan"})
        first = self.service.mutate("rf.validation.advance", request)
        before = self.record(identity)
        self.assertEqual(self.service.mutate("rf.validation.advance", request), first)
        self.assertEqual(self.record(identity), before)
        self.service.solver.run_next()
        with self.assertRaises(ProjectError) as error:
            self.advance(identity, "dipole-1", "plan")
        self.assertEqual(error.exception.code, "E_CONFLICT")
        self.assertEqual(self.record(identity)["usage"], before["usage"])

    def test_cancel_and_unknown_termination_preserve_reserved_budget(self):
        """! @brief 종료 미확인 작업을 취소 표시만으로 반납하거나 새 판정에 사용하지 않는다."""
        identity = self.create()
        self.advance(identity, "dipole-1", "plan")
        self.host.transport.mode = "unknown"
        submitted = self.advance(identity, "dipole-1", "prepare", execute=False)
        reserved = deepcopy(self.record(identity)["usage"])
        self.service.solver.run_next()
        self.assertTrue(self.host.job(submitted)["solver"]["resource_reserved"])
        with self.assertRaises(ProjectError) as error:
            self.command("rf.validation.assess", validation_id=identity)
        self.assertEqual(error.exception.code, "E_CONFLICT")
        self.command("rf.validation.cancel", validation_id=identity)
        self.assertTrue(self.host.job(submitted)["solver"]["resource_reserved"])
        self.assertEqual(self.query("rf.validation.get", validation_id=identity, report_id=None)["status"], "cancel_requested")
        self.assertEqual(self.query("rf.validation.list", offset=0, limit=25)["items"][0]["state"], "cancel_requested")
        self.assertEqual(self.record(identity)["usage"], reserved)
        with self.assertRaises(ProjectError):
            self.advance(identity, "dipole-2", "plan")
        self.assertEqual(self.document(), self.original)
        self.host.transport.reconcile_confirmed = False
        self.service.close()
        self.host.service = ProjectService(self.host.workspace, auto_run=False)
        self.assertEqual(self.query("rf.validation.get", validation_id=identity, report_id=None)["status"], "cancel_requested")
        self.assertEqual(self.query("rf.validation.list", offset=0, limit=25)["items"][0]["state"], "cancel_requested")
        self.assertTrue(self.host.job(submitted)["solver"]["resource_reserved"])
        self.assertEqual(self.record(identity)["usage"], reserved)

    def test_wall_time_and_count_budget_reject_before_job_admission(self):
        """! @brief 중단 시간이 누적 상한에 포함되고 거절 시 추가 예약을 남기지 않는다."""
        identity = self.create()
        self.advance(identity, "dipole-1", "plan")
        before = self.record(identity)
        job_count = len(self.service.journal.read()["jobs"])
        with patch.object(self.service, "_now", return_value=before["started_at"] + 10801), self.assertRaises(ProjectError) as error:
            self.advance(identity, "dipole-1", "prepare")
        self.assertEqual(error.exception.code, "E_RESOURCE")
        self.assertEqual(len(self.service.journal.read()["jobs"]), job_count)
        self.assertEqual(self.record(identity)["usage"], before["usage"])
        self.service.journal.transaction(lambda state: state["rf_validations"][identity]["usage"].update(worker_calls=27))
        with self.assertRaises(ProjectError) as error:
            self.advance(identity, "dipole-1", "prepare")
        self.assertEqual(error.exception.code, "E_RESOURCE")
        self.assertEqual(len(self.service.journal.read()["jobs"]), job_count)
        self.assertEqual(self.record(identity)["usage"]["worker_calls"], 27)

    def test_foreign_project_and_tampered_report_are_rejected(self):
        """! @brief UUID 선택만으로 다른 프로젝트나 변경된 판정 원문을 읽지 않는다."""
        identity = self.create()
        report = self.command("rf.validation.assess", validation_id=identity)
        task = self.service.mutate("project.open", self.host.request({"path": "projects/다른 참조", "open_mode": "create", "name": "다른 프로젝트"}, {}))
        self.service.run_next()
        foreign = self.host.status(task)["events"][-1]["operation_result"]["project_id"]
        for method, data in (("rf.validation.get", {"validation_id": identity, "report_id": None}),
                             ("rf.validation.get", {"validation_id": identity, "report_id": report["report_id"]})):
            with self.subTest(data=data), self.assertRaises(ProjectError) as error:
                read(self.service, method, {"contract_version": "rfad.api/2.0", "context": {"project_id": foreign}, "input": data})
            self.assertEqual(error.exception.code, "E_CONFLICT")
        with self.assertRaises(ProjectError):
            self.query("rf.validation.get", validation_id=identity, report_id=str(uuid4()))
        self.service.journal.transaction(lambda state: state["rf_validations"][identity]["reports"][0].update(assessment_hash="0" * 64))
        with self.assertRaises(ProjectError) as error:
            self.query("rf.validation.get", validation_id=identity, report_id=report["report_id"])
        self.assertEqual(error.exception.code, "E_HASH")
