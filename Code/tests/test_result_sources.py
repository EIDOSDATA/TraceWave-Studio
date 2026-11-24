"""! @brief 과거 복소 자료의 명시 개정/source/pin과 읽기 불변 경계를 검증한다."""

from copy import deepcopy
import base64
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application.result_service import read
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.domain.errors import ProjectError
from test_network_service import import_parameters


class ResultSourceTests(unittest.TestCase):
    """! @brief 실제 영속 자료를 공개 network 명령으로 만들고 공통 결과 읽기만 수행한다."""

    def setUp(self):
        """! @brief 공유 fixture는 시험 데이터 생성 보조로만 사용한다."""
        from test_network_service import NetworkServiceTests

        self.fixture = NetworkServiceTests("test_source_hdf5_missing_conditions_history_and_reopen")
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.identity = self.fixture.apply("import", import_parameters(declared=False))
        self.source = {"kind": "network", "dataset_id": self.identity, "revision_id": self.fixture.revision, "snapshot_id": None}

    def query(self, method, **data):
        """! @brief 조회는 실제 journal과 workspace 파일들을 변경하지 않는다."""
        before = self.fixture.service.journal.read()
        files = self.file_hashes()
        result = read(self.fixture.service, method, self.fixture.request(data))
        self.assertEqual(self.fixture.service.journal.read(), before)
        self.assertEqual(self.file_hashes(), files)
        return result

    def file_hashes(self):
        """! @brief 조회 전후 파일 게시/삭제 및 바이트 변경을 모두 감지한다."""
        return {str(path.relative_to(self.fixture.workspace)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.fixture.workspace.rglob("*") if path.is_file() and path.name != ".writer.lock"}

    def test_past_revision_survives_undo_current_absence_save_and_reopen(self):
        """! @brief 현재 자료 목록에서 없어져도 과거 명시 개정을 그대로 재조회한다."""
        before = self.query("result.describe", source=self.source)
        self.assertEqual(before["descriptor"]["phasor_convention"], "unknown")
        self.assertEqual(before["descriptor"]["reference_planes"], [None])
        self.assertFalse(before["available_views"]["radiation"])
        self.fixture.history("undo")
        self.assertEqual(self.fixture.read("network.library")["datasets"], [])
        self.fixture.save_reopen()
        after = self.query("result.describe", source=self.source)
        self.assertEqual(after["pin"], before["pin"])
        self.assertEqual(after["descriptor"], before["descriptor"])
        self.assertFalse(after["is_current_design"])
        page = self.query("result.page", source=self.source, pin=before["pin"], row=0, column=0, offset=0, limit=201)
        self.assertEqual([row["frequency_hz"] for row in page["page"]["samples"]], [1e9, 1.5e9, 2e9])
        self.assertEqual(page["page"]["samples"][0]["real"], .1)
        smith = self.query("result.smith", source=self.source, pin=before["pin"], port=0, chart="impedance", offset=0, limit=201)
        self.assertFalse(smith["points"][0]["smith_valid"])
        self.assertIn("phasor_convention_unknown", smith["points"][0]["reasons"])

    def test_null_tampered_pin_and_missing_revision_are_rejected(self):
        """! @brief 오래된 선택을 현재 자료로 묵시 재핀하거나 대체하지 않는다."""
        described = self.query("result.describe", source=self.source)
        for pin in (None, {**described["pin"], "identity_hash": "0" * 64}, {**described["pin"], "dataset_sha256": "0" * 64}):
            with self.subTest(pin=pin), self.assertRaises(ProjectError):
                self.query("result.page", source=self.source, pin=pin, row=0, column=0, offset=0, limit=201)
        missing = {**self.source, "revision_id": str(uuid4())}
        with self.assertRaises(ProjectError) as caught:
            self.query("result.describe", source=missing)
        self.assertEqual(caught.exception.code, "E_MISSING_ARTIFACT")

    def test_historical_export_preserves_original_bytes_unknowns_and_pin(self):
        """! @brief undo로 현재 목록에서 사라진 자료도 당시 조건과 정확한 원문으로 내보낸다."""
        from rfad.adapters.network_hdf5 import decode_network_hdf5

        description = self.query("result.describe", source=self.source)
        self.fixture.history("undo")
        self.fixture.save_reopen()
        results = {format_name: self.query("result.export", source=self.source, pin=description["pin"], format=format_name)
                   for format_name in ("source", "csv", "hdf5", "touchstone")}
        sidecar = results["source"]["sidecar"]
        revision = description["source_revision"]
        self.assertEqual(revision["label"], f"{revision['name']} ({revision['modified_at']})")
        original_revision = {**revision, "label": f"{revision['name']} / {revision['modified_at']}"}
        self.assertEqual(sidecar["source_revision"], original_revision)
        legacy_pin = {**description["pin"], "identity_hash": canonical_hash({
            "source": self.source, "project_id": self.fixture.project, "source_revision": original_revision,
            "source_record": {"entry": sidecar["dataset"], "revision_hash": original_revision["hash"]},
            "dataset_artifact": sidecar["dataset_artifact"],
        })}
        self.assertEqual(description["pin"], legacy_pin)
        self.query("result.page", source=self.source, pin=legacy_pin, row=0, column=0, offset=0, limit=3)
        source = base64.b64decode(results["source"]["content_base64"])
        self.assertEqual(source, base64.b64decode(import_parameters(declared=False)["source_base64"]))
        self.assertEqual(results["source"]["file_name"], "한글 시험.s1p")
        network = decode_network_hdf5(base64.b64decode(results["hdf5"]["content_base64"]))
        self.assertEqual(network["phasor_convention"], "unknown")
        self.assertEqual(network["reference_planes"], [None])
        for result in results.values():
            raw = base64.b64decode(result["content_base64"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), result["sha256"])
            self.assertEqual(result["pin"], description["pin"])
            self.assertEqual(result["sidecar"]["source_revision"]["id"], self.source["revision_id"])
            self.assertEqual(result["sidecar"]["descriptor"]["conditions"], {"manufacturing": None, "measurement": None})
            self.assertFalse(result["sidecar"]["descriptor"]["conditions"].get("physics_validated", False))

    def test_explicit_snapshot_anchor_and_human_revision_catalog(self):
        """! @brief 스냅샷과 개정 소유권을 대조하고 기본 목록은 표시 이름을 제공한다."""
        f = self.fixture
        task = f.service.mutate("snapshot.create", f.request({"expected_revision": f.revision, "description": "과거 복소 자료 비교 기준"}, mutation=True))
        f.service.run_next()
        snapshot = f.service.status({"contract_version": "rfad.api/2.0", "context": {}, "input": {"job_id": task["job_id"]}})["events"][-1]["operation_result"]
        source = {**self.source, "snapshot_id": snapshot["snapshot_id"]}
        described = self.query("result.describe", source=source)
        self.assertEqual(described["source"], source)
        result = self.query("result.revisions", offset=0, limit=25, catalog_hash=None)
        self.assertTrue(any(row["snapshot_id"] == snapshot["snapshot_id"] for row in result["items"]))
        self.assertTrue(all("보존 개정" in row["revision_label"] for row in result["items"]))
        bad = {**source, "revision_id": f.original["revision_id"]}
        with self.assertRaises(ProjectError):
            self.query("result.describe", source=bad)

    def test_catalog_anchor_and_hash_disallow_mixed_pages(self):
        """! @brief 현재 목록 alias는 응답에서 실제 개정으로 고정하고 후속 페이지는 hash를 요구한다."""
        arguments = {"kind": "network", "revision_id": None, "snapshot_id": None, "study_id": None,
                     "offset": 0, "limit": 1, "catalog_hash": None}
        first = self.query("result.sources", **arguments)
        self.assertEqual(first["items"][0]["source"], self.source)
        self.fixture.apply("import", {**import_parameters(), "name": "다른 입력"})
        with self.assertRaises(ProjectError) as caught:
            self.query("result.sources", **{**arguments, "catalog_hash": first["catalog_hash"]})
        self.assertEqual(caught.exception.code, "E_CONFLICT")
        anchored = self.query("result.sources", **{**arguments, "revision_id": self.source["revision_id"], "catalog_hash": first["catalog_hash"]})
        self.assertEqual(anchored["items"], first["items"])
        with self.assertRaises(ProjectError):
            self.query("result.sources", **{**arguments, "offset": 1})

    def test_current_result_list_combines_sources_without_mixing_design_revisions(self):
        """! @brief 기본 목록에서 새 계산과 자료를 함께 보여도 이전 해석은 보존한다."""
        project = self.fixture.project
        state = self.fixture.service.journal.read()
        current, old, other = (str(uuid4()) for _ in range(3))
        for artifact, owner, revision in ((current, project, self.source["revision_id"]),
                                           (old, project, self.fixture.original["revision_id"]),
                                           (other, str(uuid4()), self.source["revision_id"])):
            state["solver_results"][artifact] = {
                "project_id": owner, "snapshot": {"revision_id": revision, "sealed_at": 1},
                "metadata": {"profile": "rfad.openems.pcb-single-port/0.1"}, "normalized": {},
            }
        inputs = {"revision_id": None, "snapshot_id": None, "study_id": None, "offset": 0,
                  "limit": 25, "catalog_hash": None}
        with patch.object(self.fixture.service.journal, "read", return_value=state):
            mixed = self.query("result.sources", kind="all", **inputs)
            self.assertEqual([row["source"] for row in mixed["items"]],
                             [{"kind": "solver", "artifact_id": current}, self.source])
            self.assertEqual(mixed["current_totals"], {"network": 1, "solver": 1})
            solver = self.query("result.sources", kind="solver", **inputs)
            self.assertEqual({row["source"]["artifact_id"] for row in solver["items"]}, {current, old})

    def test_artifact_tampering_is_detected_and_read_does_not_repair_it(self):
        """! @brief 파일을 자동 재생성하지 않고 정확한 원문 hash 오류를 반환한다."""
        entry = self.fixture.read("network.library")["datasets"][0]
        path = self.fixture.workspace / entry["dataset"]["uri"]
        raw = path.read_bytes()
        path.write_bytes(raw + b" ")
        before = path.read_bytes()
        with self.assertRaises(ProjectError) as caught:
            self.query("result.describe", source=self.source)
        self.assertEqual(caught.exception.code, "E_HASH")
        self.assertEqual(path.read_bytes(), before)

    def test_wrong_owner_and_invalid_envelope_are_rejected(self):
        """! @brief 다른 프로젝트의 snapshot 또는 임의 source 구조를 읽을 수 없다."""
        state = self.fixture.service.journal.read()
        snapshot = deepcopy(self.fixture.snapshot)
        snapshot["project_id"] = str(uuid4())
        state["snapshots"][snapshot["snapshot_id"]] = snapshot
        with patch.object(self.fixture.service.journal, "read", return_value=state), self.assertRaises(ProjectError):
            read(self.fixture.service, "result.describe", self.fixture.request({"source": {
                **self.source, "revision_id": snapshot["revision_id"], "snapshot_id": snapshot["snapshot_id"]}}))
        for source in ({**self.source, "path": "anything"}, {"kind": "sweep", "study_id": str(uuid4()), "index": True}):
            with self.subTest(source=source), self.assertRaises(ProjectError):
                self.query("result.describe", source=source)
        with self.assertRaises(ProjectError):
            self.query("result.sources", kind="sweep", revision_id=None, snapshot_id=None, study_id=[], offset=0, limit=25, catalog_hash=None)

    def test_public_rpc_describe_pin_export_and_capabilities(self):
        """! @brief 등록된 실제 NDJSON 경로도 source/pin과 읽기 원본 보존을 강제한다."""
        from rfad.application.rpc import handle_frame, capabilities

        service = self.fixture.service
        before = service.journal.read()
        self.assertTrue({"result.describe", "result.smith", "result.export", "result.compare"} <= set(capabilities(service)["methods"]))
        request = {"jsonrpc": "2.0", "id": 1, "method": "result.describe", "params": self.fixture.request({"source": self.source})}
        described = handle_frame(canonical_bytes(request), service)
        self.assertNotIn("error", described, described)
        request["method"] = "result.export"
        request["params"]["input"].update(pin=described["result"]["pin"], format="source")
        exported = handle_frame(canonical_bytes(request), service)
        self.assertNotIn("error", exported, exported)
        self.assertEqual(exported["result"]["source"], self.source)
        request["params"]["input"]["pin"] = None
        rejected = handle_frame(canonical_bytes(request), service)
        self.assertEqual(rejected["error"]["data"]["domain_code"], "E_SCHEMA")
        self.assertEqual(service.journal.read(), before)


if __name__ == "__main__":
    unittest.main()
