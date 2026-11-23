"""! @brief 실제 출력 API의 고정 원본, 영수증과 게시 전 자원 거절을 검사한다."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application import exchange_service, exchange_contract
from rfad.application.canonical import canonical_bytes
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.domain.errors import ProjectError
from test_cad_projection import cad_fixture


class AdmissionRuntime:
    """! @brief native 계산 없이 접수 및 취소 계약만 확인하는 명시적인 시험 설정이다."""
    identity = {"test_only_admission": True}
    manifest_bytes, source_bytes = b'{}', b'{}'
    timeout_seconds = 10
    font_bytes = None

    def verify(self, expected):
        """! @brief 실제 계산/검수 성공을 만들지 않고 접수 identity만 비교한다."""
        if expected != self.identity:
            raise ProjectError("E_VERSION", "시험 실행 설정 변경")


class ExchangeFixture:
    """! @brief 실제 영속 명령으로 유한 보드와 스냅샷을 준비한다."""
    def __init__(self, runtime=None):
        """! @brief 출처와 미정 RF 물성을 가진 기하만 저장한다."""
        self.temporary = TemporaryDirectory(prefix="TraceWave 출력 계약 ")
        self.workspace = Path(self.temporary.name) / "작업 영역"
        self.service = ProjectService(self.workspace, auto_run=False, exchange_runtime=runtime)
        opened = self.complete("project.open", {"path": "projects/원본 도면", "open_mode": "create", "name": "도면 계약 원본"}, {})
        self.project, self.revision = opened["project_id"], opened["revision_id"]
        original = cad_fixture()
        frame = opened["document"]["frames"]["board"]["id"]
        original["board"]["frame_id"] = frame
        self.command("board.set", {"board": original["board"]})
        for collection, kind in (("materials", "material"), ("stackup", "layer"), ("nets", "net"), ("geometry", "geometry"), ("ports", "port")):
            for item in original[collection]:
                if "frame_id" in item:
                    item["frame_id"] = frame
                self.command(kind + ".set", {kind: item})
        self.snapshot = self.complete("snapshot.create", {"expected_revision": self.revision, "description": "출처와 미정 보존 도면"})
        self.document = self.service._load(self.service.journal.read()["projects"][self.project])

    def close(self):
        """! @brief 소유 스레드와 임시 시험 저장소만 해제한다."""
        self.service.close()
        self.temporary.cleanup()

    def request(self, data, context=None):
        """! @brief 기존 ledger의 epoch와 새 key를 사용한다."""
        return {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project} if context is None else context,
                "input": data, "request_key": str(uuid4()), "request_key_epoch": self.service.policy()["request_key_epoch"]}

    def complete(self, method, data, context=None):
        """! @brief 작은 비동기 작업을 실제 저장 worker로 완료한다."""
        task = self.service.mutate(method, self.request(data, context))
        if not self.service.run_next():
            raise AssertionError("queued 자료 작업 없음")
        job = self.service.journal.read()["jobs"][task["job_id"]]
        if job["state"] != "completed":
            raise AssertionError(job)
        return job["events"][-1]["operation_result"]

    def command(self, kind, payload):
        """! @brief 현재 원본만 기존 공개 명령으로 변경한다."""
        response = self.service.mutate("project.apply_command", self.request({"expected_revision": self.revision,
            "command_id": str(uuid4()), "type": kind, "payload": payload}))
        self.revision = response["new_revision"]

    def read(self, method, data):
        """! @brief 실제 RPC dispatch로 읽기 계약을 시험한다."""
        frame = {"jsonrpc": "2.0", "id": "exchange-test", "method": method,
                 "params": {"contract_version": "rfad.api/2.0", "context": {"project_id": self.project}, "input": data}}
        result = handle_frame(canonical_bytes(frame), self.service)
        if "error" in result:
            raise AssertionError(result)
        return result["result"]

    def data(self, format_name="svg"):
        """! @brief 현재 원본을 묵시 선택하지 않고 실제 snapshot을 명시한다."""
        context = self.read("export.context", {"snapshot": {key: self.snapshot[key] for key in ("snapshot_id", "content_hash")}})
        return {"snapshot": {key: self.snapshot[key] for key in ("snapshot_id", "content_hash")},
                "profile": exchange_contract.PROFILE, "format": format_name, "options": context["default_options"]}


class ExchangeServiceTests(unittest.TestCase):
    """! @brief 형식 라이브러리 없이도 검토/보존/오류 상태가 정확한지 확인한다."""
    def setUp(self):
        self.fixture = ExchangeFixture(AdmissionRuntime())

    def tearDown(self):
        self.fixture.close()

    def test_optimized_process_still_publishes_all_inputs_before_receipt(self):
        """! @brief -O에서도 원본 파일 게시를 생략하지 않고 참조 바이트를 대조한다."""
        program = '''from test_exchange_service import ExchangeFixture, AdmissionRuntime
f = ExchangeFixture(AdmissionRuntime())
try:
    data = f.data()
    preview = f.complete("export.preview", data)
    task = f.service.mutate("export.build", f.request({**data, "review_hash": preview["review_hash"]}))
    job = f.service.journal.read()["jobs"][task["job_id"]]
    for key in ("input", "runtime_manifest", "source"):
        raw = f.service.journal.read_artifact(job["exchange"][key])
        if not raw:
            raise RuntimeError("빈 원본 게시")
    print("published-before-receipt")
finally:
    f.close()
'''
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(root / "src"), str(root / "tests"))))
        output = subprocess.run([sys.executable, "-O", "-c", program], cwd=root, env=env,
                                capture_output=True, timeout=60, check=False)
        self.assertEqual(output.returncode, 0, output.stderr.decode("utf-8", errors="replace"))
        self.assertIn(b"published-before-receipt", output.stdout)

    def test_preview_uses_fixed_snapshot_and_preserves_full_source_unknowns(self):
        """! @brief 후속 현재 편집과 과거 출력의 층/치수/출처를 혼합하지 않는다."""
        f = self.fixture
        data = f.data()
        first = f.complete("export.preview", data)
        changed = deepcopy(f.document["stackup"][-1])
        changed["name"] = "나중에 바뀐 현재 층 이름"
        f.command("layer.set", {"layer": changed})
        context = f.read("export.context", {"snapshot": data["snapshot"]})
        self.assertNotEqual(context["revision_id"], context["source_revision_id"])
        self.assertEqual(context["layers"][-1]["name"], f.document["stackup"][-1]["name"])
        second = f.complete("export.preview", data)
        self.assertEqual(first, second)
        projection = exchange_contract.build_input(f.document, f.snapshot, data, str(uuid4()))
        self.assertEqual(projection["projection"]["source_semantics"], f.document)
        self.assertTrue(any(item["epsilon_r"]["value_si"] is None for item in f.document["materials"]))
        self.assertTrue(first["pages"])

    def test_format_specific_history_preserves_other_outputs(self):
        """! @brief 형식 조회를 바꿔도 다른 형식과 원래 개정의 작업을 유지한다."""
        f = self.fixture
        requests = {kind: f.data(kind) for kind in ("pdf", "svg")}
        for data in requests.values():
            data["review_hash"] = f.complete("export.preview", data)["review_hash"]
        ids = {}
        for kind, data in requests.items():
            job = f.service.mutate("export.build", f.request(data))["job_id"]
            ids[kind] = job
            f.service.mutate("job.cancel", f.request({"job_id": job, "reason": "목록 검증 접수 종료"}, {}))
        before = f.service.journal.read()
        for kind, job in ids.items():
            view = f.read("export.list", {"offset": 0, "format": kind})
            self.assertEqual(view["total"], 1)
            self.assertEqual(view["items"][0]["job_id"], job)
            self.assertEqual(view["items"][0]["snapshot"]["revision_id"], f.revision)
        self.assertEqual({row["job_id"] for row in f.read("export.list", {})["items"]}, set(ids.values()))
        self.assertEqual(f.service.journal.read(), before)

    def test_changed_option_hash_rejects_without_artifacts_or_job(self):
        """! @brief 검토 뒤 축척 변경이 이전 hash를 재사용하지 못한다."""
        f = self.fixture
        data = f.data()
        preview = f.complete("export.preview", data)
        before = f.service.journal.read()
        data["options"]["scale"] = 2
        with self.assertRaises(ProjectError) as raised:
            f.service.mutate("export.build", f.request({**data, "review_hash": preview["review_hash"]}))
        self.assertEqual(raised.exception.code, "E_CONFLICT")
        self.assertEqual(f.service.journal.read(), before)
        self.assertFalse(any(f.workspace.rglob("exchange-inputs")))

    def test_idempotency_receipt_cancel_and_original_are_preserved(self):
        """! @brief 반복 접수는 같은 TaskRef이고 계산 전 취소는 원본을 건드리지 않는다."""
        f = self.fixture
        data = f.data()
        preview = f.complete("export.preview", data)
        request = f.request({**data, "review_hash": preview["review_hash"]})
        task = f.service.mutate("export.build", request)
        self.assertEqual(f.service.mutate("export.build", request), task)
        receipt = f.read("export.receipt", {key: request[key] for key in ("request_key", "request_key_epoch")})
        self.assertEqual(receipt["response"], task)
        self.assertEqual(len(f.read("export.list", {})["items"]), 1)
        f.service.mutate("job.cancel", f.request({"job_id": task["job_id"], "reason": "시험 접수 취소"}, {}))
        self.assertEqual(f.read("export.get", {"job_id": task["job_id"]})["state"], "cancelled")
        self.assertEqual(f.service._load(f.service.journal.read()["projects"][f.project]), f.document)

    def test_near_full_journal_rejects_before_publishing_source_files(self):
        """! @brief 예측 가능한 용량 거절 뒤 새 입력 폴더도 남기지 않는다."""
        f = self.fixture
        data = f.data()
        preview = f.complete("export.preview", data)
        before = f.service.journal.read()
        with patch.object(exchange_service, "MAX_STATE_BYTES", len(canonical_bytes(before)) + 1):
            with self.assertRaises(ProjectError) as raised:
                f.service.mutate("export.build", f.request({**data, "review_hash": preview["review_hash"]}))
        self.assertEqual(raised.exception.code, "E_RESOURCE")
        self.assertEqual(f.service.journal.read(), before)
        self.assertFalse(any(f.workspace.rglob("exchange-inputs")))

    def test_missing_runtime_is_readable_and_does_not_mark_ready(self):
        """! @brief 별도 환경 없이 과거 입력을 검토하되 출력 가능으로 표시하지 않는다."""
        f = self.fixture
        f.service.exchange.runtime = None
        preview = f.complete("export.preview", f.data())
        self.assertFalse(preview["can_build"])
        self.assertFalse(f.read("export.context", {})["runtime_configured"])
        self.assertNotIn("reportlab", sys.modules)
        self.assertNotIn("ezdxf", sys.modules)

    def test_unknown_fields_and_fabrication_annotation_are_rejected(self):
        """! @brief 원문 없는 옵션과 제작 기하에 섞인 축척/주석을 명시 차단한다."""
        f = self.fixture
        for change in ({"unknown": 1}, {"mode": "fabrication_geometry"}, {"scale": float("inf")}, {"views": []}):
            data = f.data()
            data["options"].update(change)
            with self.subTest(change=change), self.assertRaises((ProjectError, ValueError)):
                f.service.mutate("export.preview", f.request(data))

    def test_paper_overflow_is_an_explicit_failed_review(self):
        """! @brief 지정 축척을 자동 변경하거나 형상을 잘라 성공하지 않는다."""
        f = self.fixture
        data = f.data()
        data["options"]["scale"] = 100
        preview = f.complete("export.preview", data)
        self.assertFalse(preview["can_build"])
        self.assertIsNone(preview["review_hash"])
        self.assertTrue(preview["issues"])

    def test_snapshot_and_receipt_owner_mismatch_is_rejected(self):
        """! @brief 다른 원본이나 영수증을 현재 출력으로 가장하지 못한다."""
        f = self.fixture
        data = f.data()
        data["snapshot"]["content_hash"] = "0" * 64
        with self.assertRaises(ProjectError):
            f.service.mutate("export.preview", f.request(data))
        missing = f.read("export.receipt", {"request_key": "unknown-operation", "request_key_epoch": f.service.policy()["request_key_epoch"]})
        self.assertEqual(missing["status"], "unresolved")
        self.assertIsNone(missing["response"])


if __name__ == "__main__":
    unittest.main()
