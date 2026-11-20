"""! @brief 편집 복원, 임시 발행 실패와 원래 이력의 리플레이를 확인한다."""

import base64
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application import project_archive, rpc
from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from test_cad_worker_process import register_fixture, request
from test_design_rules import scenario
from test_network_service import import_parameters


class ProjectArchiveTests(unittest.TestCase):
    """! @brief 등록된 사용자 자료만 보존하며 기존 workspace는 덮어쓰지 않는다."""

    def setUp(self):
        """! @brief 출처와 미정 확장, 이전 저장 기준 및 별도 변경이 있는 설계를 만든다."""
        self.temp = TemporaryDirectory(prefix="TraceWave 편집 복원 ")
        self.original = Path(self.temp.name) / "소스"
        self.target = Path(self.temp.name) / "수령"
        self.source = ProjectService(self.original, auto_run=False)
        doc = scenario()
        doc["extensions"]["test.unknown"] = {"source_refs": ["최초 원문"], "measurement": None}
        self.document, self.snapshot = register_fixture(self.source, doc)
        self.identity = doc["project_id"]
        data = {"expected_revision": doc["revision_id"], "command_id": str(uuid4()),
                "type": "metadata.set", "payload": {"name": "복원 후 이름", "description": "검증 원본"}}
        self.changed = self.source.mutate("project.apply_command", request(self.source, self.identity, data))["new_revision"]

    def tearDown(self):
        """! @brief 독립 workspace writer를 닫고 시험 폴더 수명을 종료한다."""
        self.source.close()
        self.temp.cleanup()

    def build(self, include_sources=True):
        """! @brief 원본 workspace에 작업을 만들지 않고 정확히 같은 검토를 발행한다."""
        before = self.source.journal.read()
        preview = project_archive.prepare(self.source, self.identity, self.changed, include_sources)
        payload = project_archive.build(self.source, self.identity, self.changed, include_sources, preview["review_hash"])
        self.assertEqual(len(payload), preview["zip_bytes"])
        self.assertEqual(before, self.source.journal.read())
        return payload

    def test_recovers_edit_history_snapshot_and_original_source_on_new_workspace(self):
        """! @brief 기존 설계와 저장 포인터, 출처/미정값을 복원한 뒤 실제 undo와 redo를 검사한다."""
        raw = self.build()
        with ProjectService(self.target, auto_run=False) as dest:
            reviewed = project_archive.preview_restore(dest, raw)
            self.assertEqual(reviewed["revision_id"], self.changed)
            self.assertEqual(reviewed["saved_revision"], self.document["revision_id"])
            result = project_archive.restore(dest, raw, reviewed["review_hash"])
            self.assertEqual(result, project_archive.restore(dest, raw, reviewed["review_hash"]))
            state = dest.journal.read()
            self.assertEqual(state["jobs"], {})
            self.assertEqual(state["snapshots"][self.snapshot["snapshot_id"]], self.snapshot)
            old = self.source.journal.read()["projects"][self.identity]
            self.assertEqual(dest.repository.load(state["projects"][self.identity]), self.source.repository.load(old))
        with ProjectService(self.target, auto_run=False) as dest:
            result = dest.mutate("project.undo", request(dest, self.identity, {
                "expected_revision": self.changed, "command_id": str(uuid4())}))
            project = dest.journal.read()["projects"][self.identity]
            restored = dest.repository.load(project)
            for field in ("name", "description"):
                self.assertEqual(restored["metadata"][field], self.document["metadata"][field])
            self.assertEqual(restored["extensions"], self.document["extensions"])
            dest.mutate("project.redo", request(dest, self.identity, {
                "expected_revision": result["new_revision"], "command_id": str(uuid4())}))
            project = dest.journal.read()["projects"][self.identity]
            self.assertEqual(dest.repository.load(project)["metadata"]["name"], "복원 후 이름")
            self.assertEqual(dest.repository.saved_revision(project), self.document["revision_id"])

    def test_omitted_sources_keep_registered_references_and_never_fabricate_inputs(self):
        """! @brief 선택하지 않은 복소 원문은 누락이라고 표시하고 설계 내 원래 참조는 보존한다."""
        data = {"expected_revision": self.changed, "operation": "import", "parameters": import_parameters(declared=False)}
        context = self.source.host_calculation_context
        preview = context.read("network.preview", {"contract_version": "rfad.api/2.0",
                                                  "context": {"project_id": self.identity}, "input": data})
        saved = self.source.mutate("network.apply", request(self.source, self.identity, {
            **data, "review_hash": preview["review_hash"], "command_id": str(uuid4())}))
        self.changed = saved["new_revision"]
        raw = self.build(False)
        with ProjectService(self.target, auto_run=False) as dest:
            reviewed = project_archive.preview_restore(dest, raw)
            self.assertGreaterEqual(reviewed["missing_count"], 3)
            self.assertEqual({item["reason"] for item in reviewed["omitted"]}, {"source_omitted"})
            project_archive.restore(dest, raw, reviewed["review_hash"])
            state = dest.journal.read()
            source = self.source.journal.read()["projects"][self.identity]
            self.assertEqual(dest.repository.load(state["projects"][self.identity]), self.source.repository.load(source))
            self.assertTrue(all(not (self.target / item["reference"]["uri"]).exists() for item in reviewed["omitted"]))

    def test_mid_copy_failure_keeps_project_unpublished_and_retry_safe(self):
        """! @brief 일부 파일을 봉인한 상태에서도 같은 묶음만 이어 쓰고 타 경로는 보존한다."""
        raw = self.build()
        with ProjectService(self.target, auto_run=False) as dest:
            candidate = project_archive.preview_restore(dest, raw)
            original = dest.journal.seal_file
            calls = []

            def fault(*args, **kwargs):
                """! @brief 첫 파일만 실제로 발행한 뒤 다음 파일의 디스크 오류를 모사한다."""
                calls.append(args[0])
                if len(calls) == 2:
                    raise ProjectError("E_DISK", "모의 저장 장치 오류")
                return original(*args, **kwargs)

            with patch.object(dest.journal, "seal_file", side_effect=fault), self.assertRaises(ProjectError) as blocked:
                project_archive.restore(dest, raw, candidate["review_hash"])
            self.assertEqual(blocked.exception.code, "E_DISK")
            self.assertNotIn(self.identity, dest.journal.read()["projects"])
            self.assertTrue((self.target / calls[0]).is_file())
        with ProjectService(self.target, auto_run=False) as dest:
            recovered = project_archive.restore(dest, raw, candidate["review_hash"])
            self.assertEqual(recovered["status"], "restored")

    def test_rpc_exports_restorable_bundle_without_mixing_report_history(self):
        """! @brief 같은 작업 영역에서 읽기 전용과 편집용 발행 목록과 영수증을 분리한다."""
        context = {"project_id": self.identity}
        def call(method, input, mutation=False, error=None):
            """! @brief 동일 로컬 RPC 소유자를 명시하고 확정 변경만 request_key를 보낸다."""
            params = {"contract_version": "rfad.api/2.0", "context": context, "input": input}
            if mutation:
                params.update(request_key=str(uuid4()), request_key_epoch=self.source.policy()["request_key_epoch"])
            response = rpc.handle_frame(canonical_bytes({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}),
                                        self.source)
            if error is not None:
                self.assertEqual(response.get("error", {}).get("data", {}).get("domain_code"), error, response)
                return None
            self.assertIn("result", response, response)
            return response["result"], params

        input = {"expected_revision": self.changed, "include_sources": False}
        preview, _ = call("archive.export.preview", input)
        package, params = call("archive.export.build", {**input, "review_hash": preview["review_hash"]}, True)
        self.assertEqual(preview["estimated_bytes"], package["artifact"]["bytes"])
        receipt = {key: params[key] for key in ("request_key", "request_key_epoch")}
        found, _ = call("archive.export.receipt", receipt)
        self.assertEqual(found["response"], package)
        call("package.receipt", receipt, error="E_CONFLICT")
        self.assertEqual(call("package.list", {})[0]["items"], [])
        self.assertEqual(call("archive.export.list", {})[0]["items"], [package])
        decoded = bytearray()
        query = {"package_id": package["package_id"], "sha256": package["artifact"]["sha256"], "offset": 0}
        call("package.read", query, error="E_CONFLICT")
        while query["offset"] is not None:
            chunk, _ = call("archive.export.read", query)
            decoded.extend(base64.b64decode(chunk["content_base64"]))
            query["offset"] = chunk["next_offset"]
        with project_archive.read_verified(bytes(decoded)) as (_, manifest, _):
            self.assertEqual(manifest["revision_id"], self.changed)

    def test_rpc_receives_chunks_reserves_and_recovers_project_after_reopen(self):
        """! @brief 실제 RPC의 원문 전송, 검토, 영수증과 프로세스 재열기를 연결한다."""
        data = {"expected_revision": self.changed, "operation": "import", "parameters": import_parameters(declared=False)}
        params = {"contract_version": "rfad.api/2.0", "context": {"project_id": self.identity}, "input": data}
        preview = self.source.host_calculation_context.read("network.preview", params)
        applied = self.source.mutate("network.apply", request(self.source, self.identity, {
            **data, "review_hash": preview["review_hash"], "command_id": str(uuid4())}))
        self.changed = applied["new_revision"]
        raw = self.build()
        actual = sha256(raw).hexdigest()

        def call(service, method, data, *, key=None, error=None):
            """! @brief 유한 청크까지 실제 stdio parser의 공통 RPC 진입점으로 보낸다."""
            params = {"contract_version": "rfad.api/2.0", "context": {}, "input": data}
            if key is not None:
                params.update(request_key=key, request_key_epoch=service.policy()["request_key_epoch"])
            message = {"jsonrpc": "2.0", "id": 1, "method": "archive.receive." + method, "params": params}
            response = rpc.handle_frame(canonical_bytes(message), service)
            if error is not None:
                self.assertEqual(response.get("error", {}).get("data", {}).get("domain_code"), error, response)
                return None
            self.assertIn("result", response, response)
            return response["result"]

        with ProjectService(self.target, auto_run=False) as dest:
            start = call(dest, "begin", {"archive_sha256": actual, "bytes": len(raw)})
            transfer = {"upload_id": start["upload_id"]}
            call(dest, "review", transfer, error="E_CONFLICT")
            self.assertGreater(len(raw), start["chunk_bytes"])
            for offset in range(0, len(raw), start["chunk_bytes"]):
                chunk = raw[offset:offset + start["chunk_bytes"]]
                payload = {**transfer, "offset": offset, "content_base64": base64.b64encode(chunk).decode("ascii")}
                received = call(dest, "chunk", payload)
                self.assertEqual(received["received"], offset + len(chunk))
                if offset == 0:
                    self.assertEqual(call(dest, "chunk", payload), received)
            review = call(dest, "review", transfer)
            restored_input = {**transfer, "archive_sha256": actual, "review_hash": review["review_hash"]}
            call(dest, "apply", restored_input, key=str(uuid4()), error="E_CONFLICT")
            first = call(dest, "reserve", restored_input, key=str(uuid4()))
            self.assertEqual(first["status"], "reserved")
            self.assertNotIn(self.identity, dest.journal.read()["projects"])
            key = str(uuid4())
            restored = call(dest, "apply", restored_input, key=key)
            self.assertEqual(restored["status"], "restored")
            call(dest, "drop", transfer)
            self.assertEqual(call(dest, "apply", restored_input, key=key), restored)
        with ProjectService(self.target, auto_run=False) as dest:
            status = call(dest, "status", {"archive_sha256": actual})
            self.assertEqual(status["result"], restored)
            self.assertEqual(dest.journal.read()["jobs"], {})

    def test_existing_destination_and_review_for_other_workspace_are_rejected(self):
        """! @brief 기존 파일과 검토하지 않은 다른 복원 위치를 변경하지 않는다."""
        raw = self.build()
        with ProjectService(self.target, auto_run=False) as dest:
            candidate = project_archive.preview_restore(dest, raw)
        with ProjectService(Path(self.temp.name) / "다른 수령", auto_run=False) as dest:
            with self.assertRaises(ProjectError) as conflict:
                project_archive.restore(dest, raw, candidate["review_hash"])
            self.assertEqual(conflict.exception.code, "E_CONFLICT")
            self.assertFalse(dest.journal.read()["projects"])
        folder = self.target / candidate["path"]
        folder.mkdir(parents=True)
        sentinel = folder / "original.txt"
        sentinel.write_bytes(b"existing")
        with ProjectService(self.target, auto_run=False) as dest:
            with self.assertRaises(ProjectError):
                project_archive.preview_restore(dest, raw)
            self.assertEqual(sentinel.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
