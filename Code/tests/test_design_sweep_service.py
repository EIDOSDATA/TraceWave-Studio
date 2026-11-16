"""! @brief 연구 저장/원본 보존/영수증/페이지와 중단 후 명시 재개의 공개 서비스 경계를 검증한다."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application import design_sweep_service as sweep, network_service
from rfad.application.canonical import canonical_bytes
from rfad.application.design_sweep_store import baseline, load_definition
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.domain.errors import ProjectError
from test_cad_worker_process import register_fixture
from test_design_rules import scenario
from test_network_service import circuit_definition, import_parameters


class DesignSweepServiceTests(unittest.TestCase):
    """! @brief 별도 native 계산 없이도 영구 정의와 실제 프로젝트 파일의 불변을 검사한다."""

    def setUp(self):
        """! @brief 미정 물성/출처가 있는 실제 서비스 자료와 회로를 등록한다."""
        self.temporary = TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.now = 2000000000.0
        self.service = ProjectService(self.workspace, auto_run=False, clock=lambda: self.now)
        original = scenario()
        original["extensions"]["test.preserved"] = {"source_refs": ["사용자 원문"], "manufacturing": None, "measurement": None}
        original, self.snapshot = register_fixture(self.service, original)
        self.project = original["project_id"]
        self.dataset_id = self.network_apply("import", import_parameters(original["ports"][0]["id"]))
        self.circuit_id = self.network_apply("circuit_save", {"name": "명시 저항망", "definition": circuit_definition()})
        self.original = self.document()
        self.spec = self.read("sweep.context")["initial_specification"]
        circuit = next(row for row in self.original["extensions"]["rfad.network-library"]["circuits"] if row["id"] == self.circuit_id)
        self.spec.update(type="circuit_sweep", name="외부 R 값 후보", settings=None,
            network={"dataset_id": self.dataset_id, "circuit_id": self.circuit_id},
            variables=[{"kind": "circuit_value", "id": circuit["definition"]["elements"][0]["id"], "dimension": "impedance",
                        "values": [{"text": value, "unit": unit, "source_refs": ["명시 시험 값; 실측 아님"]}
                                   for value, unit in (("0", "ohm"), ("50", "ohm"), ("0.05", "kohm"))]}])

    def tearDown(self):
        """! @brief 시험 소유 서비스와 임시 자료만 닫는다."""
        self.service.close()
        self.temporary.cleanup()

    def document(self):
        """! @brief 현재 권위 파일을 읽는다."""
        return self.service._load(self.service.journal.read()["projects"][self.project])

    def request(self, data, mutation=False):
        """! @brief 모든 변경은 실제 영수증 epoch와 고유 키를 갖는다."""
        request = {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project}, "input": data}
        if mutation:
            request.update(request_key=str(uuid4()), request_key_epoch=self.service.policy()["request_key_epoch"])
        return request

    def read(self, method, **data):
        """! @brief 현재 API와 동일한 조회 경계를 사용한다."""
        return sweep.read(self.service, method, self.request(data))

    def network_apply(self, operation, parameters):
        """! @brief 시험 준비도 제품 원자 명령으로 자료 출처를 저장한다."""
        data = {"expected_revision": self.document()["revision_id"], "operation": operation, "parameters": parameters}
        preview = network_service.read(self.service, "network.preview", self.request(data))
        self.assertTrue(preview["can_apply"], preview)
        result = self.service.mutate("network.apply", self.request({**data, "review_hash": preview["review_hash"],
            "command_id": str(uuid4())}, mutation=True))
        return result["record_id"]

    def create(self):
        """! @brief 동일 검토/생성 요청의 영수증 재전송은 두 연구를 만들지 않는다."""
        data = {"expected_revision": self.document()["revision_id"], "specification": self.spec}
        preview = self.read("sweep.preview", **data)
        request = self.request({**data, "review_hash": preview["review_hash"]}, mutation=True)
        result = self.service.mutate("sweep.create", request)
        self.assertEqual(result, self.service.mutate("sweep.create", request))
        return result["study_id"]

    def test_preview_dedup_and_atomic_definition_preserve_all_originals(self):
        """! @brief 단위 동치 중복 행과 원문은 유지하고 검토 중 파일/이력은 쓰지 않는다."""
        before = self.service.journal.read()
        files = sorted(str(path.relative_to(self.workspace)) for path in self.workspace.rglob("*") if path.is_file())
        preview = self.read("sweep.preview", expected_revision=self.original["revision_id"], specification=self.spec)
        self.assertEqual(preview["counts"]["duplicates"], 1)
        self.assertEqual(preview["candidate_count"], 3)
        self.assertEqual(preview["candidates"][2]["duplicate_of"], 1)
        self.assertEqual(preview["budget_estimate"]["native_solves"], 0)
        self.assertEqual(before, self.service.journal.read())
        self.assertEqual(files, sorted(str(path.relative_to(self.workspace)) for path in self.workspace.rglob("*") if path.is_file()))
        identity = self.create()
        after = self.service.journal.read()
        self.assertEqual(len(after["sweeps"]), 1)
        study = after["sweeps"][identity]
        self.assertEqual(study["records"], {})
        self.assertEqual(study["state"], "ready")
        display = self.read("sweep.get", study_id=identity)
        self.assertIn(display["budget_display"]["disk_bytes"]["unit"], {"KiB", "MiB", "GiB"})
        self.assertEqual(display["budget_usage"], study["usage"])
        self.assertEqual(self.document(), self.original)
        self.assertEqual(after["commands"], before["commands"])
        definition, source = baseline(self.service, study)
        self.assertEqual(source, self.original)
        self.assertEqual(definition["original_specification"], self.spec)
        self.assertIsNone(definition["network"]["descriptor"]["conditions"]["manufacturing"])
        first = self.read("sweep.page", study_id=identity, offset=0, limit=2)
        last = self.read("sweep.page", study_id=identity, offset=2, limit=1)
        self.assertEqual(first["next_offset"], 2)
        self.assertEqual(last["candidates"][0]["ordinal"], 2)
        self.assertEqual(self.service.journal.read(), after)
        with self.assertRaises(ProjectError):
            self.read("sweep.result", study_id=identity, index=0, offset=0, limit=201, row=0, column=0)

    def test_review_stale_input_and_cross_project_are_rejected(self):
        """! @brief 검토 뒤 변경/다른 소유자/과대 페이지는 원본을 변경하지 않고 거부한다."""
        data = {"expected_revision": self.original["revision_id"], "specification": deepcopy(self.spec)}
        preview = self.read("sweep.preview", **data)
        data["specification"]["name"] = "검토 뒤 이름 변경"
        with self.assertRaises(ProjectError):
            self.service.mutate("sweep.create", self.request({**data, "review_hash": preview["review_hash"]}, mutation=True))
        self.assertEqual(self.service.journal.read()["sweeps"], {})
        identity = self.create()
        request = self.request({"study_id": identity})
        request["context"]["project_id"] = str(uuid4())
        with self.assertRaises(ProjectError):
            sweep.read(self.service, "sweep.get", request)
        with self.assertRaises(ProjectError):
            self.read("sweep.page", study_id=identity, offset=0, limit=26)
        self.assertEqual(self.document(), self.original)

    def test_rejected_creation_budget_leaves_no_snapshot_or_definition_files(self):
        """! @brief 확정된 예산 거절을 반복해도 숨은 불변 파일이나 참조를 게시하지 않는다."""
        self.spec["budget"]["disk_bytes"] = 1
        before = self.service.journal.read()
        files = {str(path.relative_to(self.workspace)): None if path.name == ".writer.lock" else path.read_bytes()
                 for path in self.workspace.rglob("*") if path.is_file()}
        for _ in range(2):
            with self.assertRaises(ProjectError) as error:
                self.create()
            self.assertEqual(error.exception.code, "E_RESOURCE")
            self.assertEqual(self.service.journal.read(), before)
            self.assertEqual({str(path.relative_to(self.workspace)): None if path.name == ".writer.lock" else path.read_bytes()
                              for path in self.workspace.rglob("*") if path.is_file()}, files)

    def test_restart_consumes_elapsed_budget_and_requires_explicit_resume(self):
        """! @brief 재시작은 자동 재실행하지 않고 중단 기간도 누적 예산에서 보존한다."""
        identity = self.create()
        self.service.mutate("sweep.start", self.request({"study_id": identity}, mutation=True))
        self.service.close()
        self.now += 20
        self.service = ProjectService(self.workspace, auto_run=False, clock=lambda: self.now)
        current = self.read("sweep.get", study_id=identity)
        self.assertEqual(current["state"], "interrupted")
        self.assertEqual(current["budget_usage"]["wall_seconds"], 20)
        self.assertTrue(current["allowed_actions"]["resume"])
        self.assertEqual(self.document(), self.original)
        self.service.mutate("sweep.resume", self.request({"study_id": identity}, mutation=True))
        self.assertEqual(self.read("sweep.get", study_id=identity)["budget_usage"]["wall_seconds"], 20)
        self.service.mutate("sweep.cancel", self.request({"study_id": identity}, mutation=True))
        self.assertEqual(self.read("sweep.get", study_id=identity)["state"], "cancel_requested")

    def test_definition_tamper_and_engine_change_block_resume_not_reading(self):
        """! @brief 없는 런타임/달라진 엔진으로 저장 연구의 출처를 바꿔 재개하지 않는다."""
        identity = self.create()
        with patch.object(sweep, "installation_metadata", return_value={"available": False, "installed": {}}):
            view = self.read("sweep.get", study_id=identity)
            self.assertFalse(view["allowed_actions"]["start"])
            with self.assertRaises(ProjectError):
                self.service.mutate("sweep.start", self.request({"study_id": identity}, mutation=True))
        study = self.service.journal.read()["sweeps"][identity]
        path = self.workspace / study["definition"]["uri"]
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(ProjectError) as error:
            load_definition(self.service, study)
        self.assertEqual(error.exception.code, "E_HASH")

    def test_host_source_change_blocks_resume_without_rewriting_old_evidence(self):
        """! @brief 패키지 버전이 같아도 앱 계산 코드가 달라지면 재개만 차단하고 조회는 유지한다."""
        identity = self.create()
        self.service.mutate("sweep.cancel", self.request({"study_id": identity}, mutation=True))
        before = self.service.journal.read()
        study = before["sweeps"][identity]
        definition = load_definition(self.service, study)
        encoded = self.service.journal.read_artifact(study["definition"])
        original = definition["engine_identity"]
        changed = deepcopy(original["application_source"])
        changed["bundle_sha256"] = "f" * 64
        with patch.object(sweep, "application_source_manifest", return_value=changed):
            view = self.read("sweep.get", study_id=identity)
            self.assertEqual(view["state"], "cancelled")
            self.assertFalse(view["allowed_actions"]["resume"])
            self.assertEqual(len(self.read("sweep.page", study_id=identity, offset=0, limit=25)["candidates"]), 3)
            with self.assertRaises(ProjectError) as error:
                self.service.mutate("sweep.resume", self.request({"study_id": identity}, mutation=True))
            self.assertEqual(error.exception.code, "E_CONFLICT")
        with patch.object(sweep, "application_source_manifest", side_effect=ProjectError("E_VERSION", "source unavailable")):
            self.assertFalse(self.read("sweep.get", study_id=identity)["allowed_actions"]["resume"])
        self.assertEqual(self.service.journal.read(), before)
        self.assertEqual(self.service.journal.read_artifact(study["definition"]), encoded)
        self.assertEqual(self.document(), self.original)

    def test_bounded_host_source_manifest_tracks_calculation_dependencies(self):
        """! @brief 회로/후보/평가 구현을 빠뜨리지 않으며 소스 교체와 유한 파일 예산을 검증한다."""
        manifest = sweep.application_source_manifest()
        paths = {row["path"] for row in manifest["code_files"]}
        self.assertTrue({"src/rfad/domain/network_circuit.py", "src/rfad/domain/network_assessment.py",
                         "src/rfad/domain/design_sweep.py", "src/rfad/domain/parameter_graph.py",
                         "src/rfad/application/design_sweep_runner.py", "src/rfad/adapters/network_backend.py"} <= paths)
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "calculation.py"
            source.write_bytes(b"value = 1\r\n")
            first = sweep.application_source_manifest(root)
            source.write_bytes(b"value = 1\n")
            self.assertEqual(first, sweep.application_source_manifest(root))
            source.write_bytes(b"value = 2\n")
            self.assertNotEqual(first["bundle_sha256"], sweep.application_source_manifest(root)["bundle_sha256"])
            source.write_bytes(b"x" * (4 * 1024**2 + 1))
            with self.assertRaises(ProjectError) as error:
                sweep.application_source_manifest(root)
            self.assertEqual(error.exception.code, "E_RESOURCE")
            source.write_bytes(b"value = 1\n")
            with patch.object(sweep, "MAX_WORKER_SOURCE_FILES", 1):
                (root / "other.py").write_bytes(b"value = 2\n")
                with self.assertRaises(ProjectError):
                    sweep.application_source_manifest(root)

    def test_public_rpc_units_and_unknown_metadata_do_not_mutate(self):
        """! @brief GHz와 MiB 입력 및 API 응답을 실제 RPC 직렬화 경계로 검사한다."""
        request = {"jsonrpc": "2.0", "id": 1, "method": "sweep.context", "params": self.request({})}
        response = handle_frame(json.dumps(request).encode(), self.service)
        self.assertNotIn("error", response)
        frequency = response["result"]["numerical_fields"][0]
        self.assertEqual(frequency["display_unit"], "GHz")
        self.assertEqual(frequency["text"], "2.4")
        changed = self.read("sweep.quantity", expected_revision=self.original["revision_id"],
                            quantity=frequency["quantity"], display_unit="MHz")
        self.assertEqual(changed["quantity"]["value_si"], frequency["quantity"]["value_si"])
        self.assertEqual(changed["text"], "2400")
        self.assertEqual(self.document(), self.original)


if __name__ == "__main__":
    unittest.main()
