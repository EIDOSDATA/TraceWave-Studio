"""! @brief STEP 재검수의 원본 불변성, 접수 결합과 실제 새 reader 프로세스를 검증한다."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application.cad_jobs import CadCoordinator, CadRuntime
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from test_cad_worker_process import register_fixture, cad_request, request, status


CAD_PYTHON = os.environ.get("RFAD_CAD_PYTHON", "")


class StepVerificationContractTests(unittest.TestCase):
    """! @brief 검수 요청에 경로, 대체 커널 또는 임의 실행 설정을 주입할 수 없다."""

    def test_closed_keys_canonical_ids_and_manifest_hash(self):
        """! @brief 정규 참조 외 필드와 잘못된 SHA256을 실제 접수 전에 거부한다."""
        context = {"project_id": str(uuid4())}
        valid = {"job_id": str(uuid4()), "manifest_sha256": "a" * 64}
        CadCoordinator.validate_verify_input(context, valid)
        cases = [(context, {**valid, "path": "other.step"}), ({}, valid),
                 (context, {**valid, "job_id": "not-an-id"}), (context, {**valid, "manifest_sha256": "A" * 64}),
                 (context, {**valid, "manifest_sha256": None})]
        for current_context, data in cases:
            with self.subTest(data=data), self.assertRaises(ProjectError):
                CadCoordinator.validate_verify_input(current_context, data)


@unittest.skipUnless(sys.platform == "win32" and CAD_PYTHON, "RFAD_CAD_PYTHON으로 고정 Windows CAD 환경을 지정해야 합니다.")
class StepVerificationProcessTests(unittest.TestCase):
    """! @brief 원래 CAD 패키지와 독립된 새 검수 작업의 상태 및 저장 경계를 확인한다."""

    def setUp(self):
        """! @brief 실제 원호/선분 STEP와 미정 재료가 있는 완료 패키지를 만든다."""
        self.temporary = TemporaryDirectory(prefix="TraceWave STEP 재검수 ")
        self.workspace = Path(self.temporary.name)
        self.service = ProjectService(self.workspace, cad_runtime=CadRuntime(Path(CAD_PYTHON)), auto_run=False)
        self.document, self.snapshot = register_fixture(self.service)
        self.original_task = self.service.mutate("export.build", cad_request(self.service, self.document, self.snapshot))
        self.assertTrue(self.service.cad.run_next())
        self.original_status = status(self.service, self.original_task["job_id"])
        self.assertEqual(self.original_status["state"], "completed", self.original_status)
        self.original_artifacts = {item["role"]: item for item in self.original_status["artifacts"]}
        self.before = {item["uri"]: hashlib.sha256((self.workspace / item["uri"]).read_bytes()).hexdigest()
                       for item in self.original_status["artifacts"]}

    def tearDown(self):
        """! @brief 시험이 소유한 서비스 및 임시 저장소만 회수한다."""
        self.service.close()
        self.temporary.cleanup()

    def params(self, **overrides):
        """! @brief 공개 검수 API의 manifest 검토값을 고정한다."""
        data = {"job_id": self.original_task["job_id"], "manifest_sha256": self.original_artifacts["manifest"]["sha256"], **overrides}
        return request(self.service, self.document["project_id"], data)

    def admit(self, params=None):
        """! @brief 영속 receipt가 포함된 실제 공개 검수 명령을 접수한다."""
        return self.service.mutate("export.verify", self.params() if params is None else params)

    def assert_original(self):
        """! @brief 검수가 원래 완료 상태, 원본 자료와 모든 출력 바이트를 바꾸지 않는다."""
        self.assertEqual(status(self.service, self.original_task["job_id"]), self.original_status)
        for uri, expected in self.before.items():
            self.assertEqual(hashlib.sha256((self.workspace / uri).read_bytes()).hexdigest(), expected)
        self.assertEqual(self.service._load(self.service.journal.read()["projects"][self.document["project_id"]]), self.document)

    def test_fresh_reader_replay_reopen_and_original_unknowns(self):
        """! @brief 새 검수 프로세스, receipt 재생과 CAD 없는 재열기에서 원본 및 미정을 유지한다."""
        params = self.params()
        task = self.admit(params)
        self.assertEqual(self.admit(params), task)
        self.assertTrue(self.service.cad.run_next())
        completed = status(self.service, task["job_id"])
        self.assertEqual(completed["state"], "completed", completed)
        result = completed["events"][-1]["operation_result"]
        self.assertEqual(result["original_job_id"], self.original_task["job_id"])
        self.assertEqual(result["source_manifest_sha256"], self.original_artifacts["manifest"]["sha256"])
        self.assertEqual(result["status"], "generated_unverified")
        self.assertEqual(result["verification"]["status"], "passed_same_kernel")
        self.assertTrue(result["verification"]["fresh_reader_process"])
        self.assertTrue(result["verification"]["body_overlap_checked_after_read"])
        self.assertFalse(result["verification"]["body_overlap_checked_before_and_after"])
        for key in ("kernel_independent", "physics_verified", "manufacturing_verified"):
            self.assertFalse(result[key])
        self.assertEqual({item["role"] for item in completed["artifacts"]}, {"verification", "manifest"})
        report = json.loads(self.service.journal.read_artifact(next(item for item in completed["artifacts"] if item["role"] == "verification")))
        self.assertEqual(report["input"]["snapshot"], self.snapshot)
        self.assertTrue(report["verification"]["bodies"])
        self.assertIn("independent CAD kernel", report["verification"]["not_evaluated"])
        jobs = self.service.journal.read()["jobs"]
        self.assertNotEqual(jobs[task["job_id"]]["cad"]["process"]["pid"], jobs[self.original_task["job_id"]]["cad"]["process"]["pid"])
        self.assertFalse(jobs[task["job_id"]]["cad"]["resource_reserved"])
        self.assert_original()
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False)
        self.assertEqual(status(self.service, task["job_id"]), completed)
        self.assertEqual(self.admit(params), task)
        self.assert_original()
        with self.assertRaises(ProjectError) as caught:
            self.admit()
        self.assertEqual(caught.exception.code, "E_UNSUPPORTED")

    def test_wrong_manifest_and_other_project_do_not_commit_receipts(self):
        """! @brief 검토값 불일치와 다른 프로젝트의 STEP은 접수나 예약을 남기지 않는다."""
        before = self.service.journal.read()
        with self.assertRaises(ProjectError) as caught:
            self.admit(self.params(manifest_sha256="f" * 64))
        self.assertEqual(caught.exception.code, "E_CONFLICT")
        params = self.params()
        params["context"]["project_id"] = str(uuid4())
        with self.assertRaises(ProjectError):
            self.admit(params)
        self.assertEqual(self.service.journal.read(), before)
        self.assert_original()

    def test_tampered_original_step_after_admission_never_publishes(self):
        """! @brief 접수 후 바이트 변조를 새 프로세스 시작 전에 발견하고 검수 성공을 게시하지 않는다."""
        task = self.admit()
        reference = self.original_artifacts["step"]
        path = self.workspace / reference["uri"]
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        self.assertTrue(self.service.cad.run_next())
        failed = status(self.service, task["job_id"])
        self.assertEqual(failed["state"], "failed", failed)
        self.assertEqual(failed["events"][-1]["error"]["code"], "E_HASH")
        self.assertEqual(failed["artifacts"], [])
        self.assertNotIn("process", self.service.journal.read()["jobs"][task["job_id"]]["cad"])
        path.write_bytes(original)
        self.assert_original()

    def test_cancel_after_report_close_and_disk_failure_keep_original(self):
        """! @brief 보고서가 닫힌 뒤 취소와 디스크 실패 모두 새 검수 artifact를 노출하지 않는다."""
        for mode in ("cancel", "disk"):
            with self.subTest(mode=mode):
                task = self.admit()
                original_seal = self.service.cad._seal

                def seal_then_interrupt(*args):
                    """! @brief 봉인 완료 직후 취소하거나 봉인 직전에 디스크 실패를 주입한다."""
                    if mode == "disk":
                        raise ProjectError("E_DISK", "검수 보고서 저장 실패 시험")
                    result = original_seal(*args)
                    self.service.mutate("job.cancel", {**request(self.service, self.document["project_id"], {"job_id": task["job_id"]}), "context": {}})
                    return result

                with patch.object(self.service.cad, "_seal", side_effect=seal_then_interrupt):
                    self.assertTrue(self.service.cad.run_next())
                result = status(self.service, task["job_id"])
                self.assertEqual(result["state"], "cancelled" if mode == "cancel" else "failed", result)
                self.assertEqual(result["artifacts"], [])
                self.assertFalse(self.service.journal.read()["jobs"][task["job_id"]]["cad"]["resource_reserved"])
                self.assert_original()

    def test_hollow_pth_region_hole_surface_and_rotated_environment(self):
        """! @brief 새 검수 API가 중공 PTH, 별도 면 구멍, 표면 개구와 외부 고체 측정을 다시 확인한다."""
        from rfad.domain.physical_setup import KEY
        from test_cad_copper_features import copper_document
        from test_cad_native import identity
        from test_design import quantity, unknown
        from test_physical_setup import fixture as physical_fixture, parameters, load

        document = copper_document()
        via = next(item for item in document["geometry"] if item["kind"] == "via")
        via["tool_hole_diameter"] = unknown("length", "mm")
        pad = next(item for item in document["geometry"] if item["kind"] == "pad")
        region = {key: value for key, value in pad.items() if key not in {"pad_shape", "center", "size", "rotation"}}
        region.update(id=identity("verification-region-hole"), kind="planar_region",
            outer=[[quantity(value, "mm") for value in point] for point in [[1, 1], [1, 10], [10, 10], [10, 1]]],
            holes=[[[quantity(value, "mm") for value in point] for point in [[3, 3], [4, 3], [4, 4], [3, 4]]]])
        document["geometry"].append(region)
        document["geometry"].sort(key=lambda item: item["id"])
        document["extensions"][KEY] = deepcopy(physical_fixture()["extensions"][KEY])
        part = document["extensions"][KEY]["parts"][0]
        part.update(name="명시 회전 검수 상자; 실물 배터리 아님", visible=True, include_in_export=True)
        for name, value in (("x", 5), ("y", 4), ("z", 5), ("width", 2), ("height", 3), ("depth", 4)):
            part[name] = quantity(value, "mm")
        part["yaw"] = quantity(90, "deg")
        with TemporaryDirectory(prefix="TraceWave STEP 복합 검수 ") as directory:
            with ProjectService(Path(directory), cad_runtime=CadRuntime(Path(CAD_PYTHON)), auto_run=False) as service:
                document, _ = register_fixture(service, document)
                service.mutate("physical.setup.apply", parameters(service, document, "surface", {
                    "name": "명시 개구 피복; 납품 미확정", "offset": "0", "thickness": ".02",
                    "openings": "18 23 4 4", "include_in_export": True}))
                document = load(service, document)
                task = service.mutate("snapshot.create", request(service, document["project_id"], {"expected_revision": document["revision_id"]}))
                service.run_next()
                snapshot = status(service, task["job_id"])["events"][-1]["operation_result"]
                task = service.mutate("export.build", cad_request(service, document, snapshot))
                service.cad.run_next()
                built = status(service, task["job_id"])
                self.assertEqual(built["state"], "completed", built)
                refs = {item["role"]: item for item in built["artifacts"]}
                expected = json.loads(service.journal.read_artifact(refs["sidecar"]))
                verified = service.mutate("export.verify", request(service, document["project_id"], {
                    "job_id": task["job_id"], "manifest_sha256": refs["manifest"]["sha256"]}))
                service.cad.run_next()
                result = status(service, verified["job_id"])
                self.assertEqual(result["state"], "completed", result)
                report = json.loads(service.journal.read_artifact(next(item for item in result["artifacts"] if item["role"] == "verification")))
                checked = {item["name"]: item for item in report["verification"]["bodies"]}
                self.assertEqual(set(checked), {item["name"] for item in expected["body_map"]})
                for body in expected["body_map"]:
                    if body.get("feature_kind") == "via_barrel" or body["role"] == "surface" or body["id"] == region["id"]:
                        self.assertEqual(checked[body["name"]]["through_hole_count"], 1, body["name"])
                    if body["role"] == "environment":
                        self.assertAlmostEqual(body["metrics"]["volume_mm3"], 24.0)
                        self.assertLessEqual(checked[body["name"]]["volume_error_mm3"], checked[body["name"]]["volume_tolerance_mm3"])
                self.assertIsNone(next(item for item in expected["source_semantics"]["geometry"] if item["kind"] == "via")["tool_hole_diameter"]["value_si"])
                self.assertEqual(load(service, document), document)


if __name__ == "__main__":
    unittest.main()
