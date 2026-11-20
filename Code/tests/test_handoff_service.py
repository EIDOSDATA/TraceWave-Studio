"""! @brief 선택 시점의 실제 스냅샷, 보고서 및 원문 인계를 저장소와 RPC에서 확인한다."""

import base64
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4
from zipfile import ZipFile

from rfad.application import handoff_archive, rpc
from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from test_cad_worker_process import register_fixture
from test_design_rules import scenario
from test_network_service import import_parameters


class HandoffTests(unittest.TestCase):
    """! @brief 공개 진입점부터 독립 ZIP 재읽기까지 같은 봉인 바이트를 대조한다."""

    def setUp(self):
        """! @brief 원본 자료가 있는 별도 프로젝트를 생성한다."""
        self.folder = TemporaryDirectory(prefix="TraceWave 인계 ")
        self.workspace = Path(self.folder.name) / "작업 영역"
        self.service = ProjectService(self.workspace, auto_run=False)
        document = scenario()
        document["metadata"]["name"] = "원래 설계 | 검증 <기록>"
        document["extensions"]["test.unknown"] = {"measurement": None, "source_refs": ["원래 작성 근거"]}
        self.document, self.snapshot = register_fixture(self.service, document)
        self.project = self.document["project_id"]
        self.revision = self.document["revision_id"]

    def tearDown(self):
        """! @brief writer를 닫고 시험 폴더 수명을 끝낸다."""
        self.service.close()
        self.folder.cleanup()

    def request(self, data, mutation=False, project=None):
        """! @brief 공개 범위와 원래 변경 epoch를 함께 전달한다."""
        result = {"contract_version": "rfad.api/2.0", "context": {"project_id": project or self.project}, "input": data}
        if mutation:
            result.update(request_key=str(uuid4()), request_key_epoch=self.service.policy()["request_key_epoch"])
        return result

    def rpc(self, method, data, *, mutation=False, error=None):
        """! @brief 실제 공개 RPC가 반환한 결과 또는 선언 오류를 검사한다."""
        request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": self.request(data, mutation)}
        response = rpc.handle_frame(canonical_bytes(request), self.service)
        if error is not None:
            self.assertIn("error", response, response)
            self.assertEqual(response["error"]["data"]["domain_code"], error, response)
            return response["error"]
        self.assertIn("result", response, response)
        return response["result"]

    def pin(self):
        """! @brief 현재 UI alias 대신 보존한 스냅샷 ID와 내용 해시를 사용한다."""
        return {key: self.snapshot[key] for key in ("snapshot_id", "content_hash")}

    def download(self, package):
        """! @brief 실제 청크를 조립하여 같은 보존 바이트를 얻는다."""
        contents, offset = [], 0
        while offset is not None:
            output = self.rpc("package.read", {"package_id": package["package_id"], "sha256": package["artifact"]["sha256"], "offset": offset})
            contents.append(base64.b64decode(output["content_base64"], validate=True))
            offset = output["next_offset"]
        return b"".join(contents)

    def test_report_fixed_snapshot_replay_and_reopen(self):
        """! @brief 후속 편집 이후에도 인계 설계/근거, 영수증과 ZIP 원문은 같은 바이트다."""
        edit = {"expected_revision": self.revision, "command_id": str(uuid4()), "type": "metadata.rename", "payload": {"name": "나중에 편집"}}
        self.service.mutate("project.apply_command", self.request(edit, True))
        query = {"snapshot": self.pin(), "kinds": ["snapshot"], "records": [], "offset": 0, "limit": 1}
        evidence = self.rpc("evidence.query", query)
        self.assertEqual(evidence["items"][0]["name"], self.document["metadata"]["name"])
        self.assertEqual(evidence["items"][0]["artifact_state"], "verified")
        self.assertEqual(evidence["scope"]["measurement_acceptance"], "not_established")
        contract = {"snapshot": self.pin(), "records": [], "inclusion": "design_and_report", "rights_confirmed": False}
        journal = self.service.journal.read()
        preview = self.rpc("package.preview", contract)
        self.assertEqual(self.service.journal.read(), journal)
        params = self.request({**contract, "review_hash": preview["review_hash"]}, True)
        package = self.service.mutate("package.build", params)
        self.assertEqual(package, self.service.mutate("package.build", params))
        receipt = self.rpc("package.receipt", {key: params[key] for key in ("request_key", "request_key_epoch")})
        self.assertEqual(receipt["response"], package)
        self.service.close()
        self.service = ProjectService(self.workspace, auto_run=False)
        raw = self.download(package)
        self.assertEqual(len(raw), preview["estimated_bytes"])
        with handoff_archive.read_archive(BytesIO(raw)) as (archive, manifest):
            self.assertEqual(manifest["content_hash"], self.snapshot["content_hash"])
            self.assertEqual(archive.read("workspace/" + self.snapshot["artifact"]["uri"]), canonical_bytes(self.document))
            self.assertIn("원래 설계 \\| 검증 &lt;기록&gt;", archive.read("report.md").decode("utf-8"))
            report = json.loads(archive.read("report.json"))
            self.assertEqual(report["project_name"], self.document["metadata"]["name"])
            self.assertEqual(report["scope"]["manufacturing_acceptance"], "not_established")

    def test_include_only_selected_network_original_preserves_raw(self):
        """! @brief 명시한 네트워크의 원문과 정규 사본을 복제하며 누락 조건은 그대로 둔다."""
        network = import_parameters(declared=False)
        original = base64.b64decode(network["source_base64"]) + (b"! source comment retained by the handoff\n" * 3400)
        network["source_base64"] = base64.b64encode(original).decode("ascii")
        request = {"expected_revision": self.revision, "operation": "import", "parameters": network}
        reviewed = self.rpc("network.preview", request)
        written = self.rpc("network.apply", {**request, "review_hash": reviewed["review_hash"], "command_id": str(uuid4())}, mutation=True)
        task = self.rpc("snapshot.create", {"expected_revision": written["new_revision"], "description": "합성 원문"}, mutation=True)
        self.service.run_next()
        self.snapshot = self.service.journal.read()["jobs"][task["job_id"]]["events"][-1]["operation_result"]
        selection = {"kind": "network", "id": written["record_id"]}
        data = {"snapshot": self.pin(), "records": [selection], "inclusion": "include_selected_files", "rights_confirmed": True}
        self.rpc("package.preview", {**data, "rights_confirmed": False}, error="E_CONFLICT")
        preview = self.rpc("package.preview", data)
        self.rpc("package.build", {**data, "inclusion": "design_and_report", "review_hash": preview["review_hash"]}, mutation=True, error="E_CONFLICT")
        self.assertEqual(self.rpc("package.list", {})["items"], [])
        package = self.rpc("package.build", {**data, "review_hash": preview["review_hash"]}, mutation=True)
        self.assertGreater(package["artifact"]["bytes"], package["chunk_bytes"])
        with handoff_archive.read_archive(BytesIO(self.download(package))) as (archive, manifest):
            report = json.loads(archive.read("report.json"))
            selected = [row for row in report["items"] if row["selected_for_copy"]]
            self.assertEqual(len(selected), 1)
            self.assertTrue(any(row["kind"] == "material" for row in report["items"]))
            row = selected[0]
            self.assertEqual(row["copy_state"], "included")
            self.assertEqual(archive.read("workspace/" + row["detail"]["original"]["uri"]), base64.b64decode(network["source_base64"]))
            dataset = json.loads(archive.read("workspace/" + row["artifact"]["uri"]))
            self.assertEqual(dataset["reference_planes"], [None])
            self.assertEqual(dataset["conditions"], {"manufacturing": None, "measurement": None})
            self.assertEqual(len(manifest["files"]), 7)

    def test_archive_rejects_unlisted_case_collision_and_changed_bytes(self):
        """! @brief ZIP 이름/목록/바이트를 하나라도 바꾸면 어떤 자료도 반환하지 않는다."""
        data = {"snapshot": self.pin(), "records": [], "inclusion": "design_and_report", "rights_confirmed": False}
        preview = self.rpc("package.preview", data)
        package = self.rpc("package.build", {**data, "review_hash": preview["review_hash"]}, mutation=True)
        with ZipFile(BytesIO(self.download(package))) as source:
            members = {item.filename: source.read(item) for item in source.infolist()}
        foreign_report = json.loads(members["report.json"])
        foreign_report["revision_id"] = str(uuid4())
        replacement = canonical_bytes(foreign_report)
        forged_manifest = json.loads(members["manifest.json"])
        for row in forged_manifest["files"]:
            if row["uri"] == "report.json":
                row.update(bytes=len(replacement), sha256=sha256(replacement).hexdigest())
        for change in ({"report.md": b"x" * len(members["report.md"])}, {"Report.md": b"duplicate"},
                       {"unlisted.txt": b"outside list"},
                       {"manifest.json": canonical_bytes(forged_manifest), "report.json": replacement}):
            with self.subTest(change=list(change)):
                raw = BytesIO()
                with ZipFile(raw, "w") as archive:
                    for name, content in {**members, **change}.items():
                        archive.writestr(name, content)
                with self.assertRaises(ProjectError):
                    with handoff_archive.read_archive(raw):
                        self.fail("검증하지 못한 인계 원문을 노출했습니다.")


if __name__ == "__main__":
    unittest.main()
