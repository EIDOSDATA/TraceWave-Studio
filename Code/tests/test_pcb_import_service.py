"""! @brief PCB 원문 전송의 바이트 보존, 영수증, 소유권과 별도 parser 경계를 검사한다."""
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application import pcb_import_service as imports
from rfad.application import exchange_artifacts
from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.exchange_runtime import ExchangeRuntime
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.domain.errors import ProjectError
from test_exchange_service import ExchangeFixture, AdmissionRuntime
from test_pcb_exchange_service import prepare, request


def begin(fixture, raw, name="원문.kicad_pcb", format_name="kicad_pcb"):
    """! @brief 원문 전체 hash를 먼저 선언하고 불변 전송 식별자를 받는다."""
    return fixture.service.mutate("pcb.import.begin", fixture.request({"format": format_name, "files": [
        {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}]}))["upload_id"]


def upload(fixture, upload_id, raw, name="원문.kicad_pcb"):
    """! @brief 전체 파일을 RPC 예외 한도 안의 명시 청크로 전송한다."""
    for offset in range(0, len(raw), imports.CHUNK_BYTES):
        fixture.service.mutate("pcb.import.chunk", fixture.request({"upload_id": upload_id, "path": name, "offset": offset,
            "content_base64": base64.b64encode(raw[offset:offset + imports.CHUNK_BYTES]).decode("ascii")}))


class PcbImportTransferTests(unittest.TestCase):
    """! @brief parser를 가장하지 않고 전송/봉인/실패 후의 권위 상태를 확인한다."""
    def setUp(self):
        self.f = ExchangeFixture(AdmissionRuntime())

    def tearDown(self):
        self.f.close()

    def test_chunk_receipt_duplicate_and_reopen_preserve_exact_bytes(self):
        f = self.f
        raw = bytes(range(256)) * 40
        identity = begin(f, raw)
        data = {"upload_id": identity, "path": "원문.kicad_pcb", "offset": 0,
                "content_base64": base64.b64encode(raw).decode("ascii")}
        parameters = f.request(data)
        frame = {"jsonrpc": "2.0", "id": "large-source", "method": "pcb.import.chunk", "params": parameters}
        first = handle_frame(canonical_bytes(frame), f.service)
        self.assertNotIn("error", first, first)
        self.assertEqual(handle_frame(canonical_bytes(frame), f.service), first)
        receipt = f.read("pcb.import.receipt", {key: parameters[key] for key in ("request_key", "request_key_epoch")})
        self.assertEqual(receipt["response"]["received"], len(raw))
        task = f.service.mutate("pcb.import.parse", f.request({"upload_id": identity}))
        state = f.service.journal.read()
        source = state["pcb_imports"][identity]["source_files"][0]["artifact"]
        self.assertEqual(f.service.journal.read_artifact(source), raw)
        f.service.mutate("job.cancel", f.request({"job_id": task["job_id"], "reason": "접수만 검증"}, {}))
        f.service.close()
        f.service = ProjectService(f.workspace, auto_run=False)
        context = f.read("pcb.import.context", {})
        self.assertEqual(context["uploads"][0]["upload_id"], identity)
        self.assertEqual(f.read("pcb.import.get", {"upload_id": identity})["parse_state"], "cancelled")
        self.assertEqual(f.service.journal.read_artifact(source), raw)
        self.assertEqual(f.service._load(f.service.journal.read()["projects"][f.project]), f.document)

    def test_wrong_offset_hash_and_incomplete_parse_leave_source_unmodified(self):
        f = self.f
        identity = begin(f, b"expected")
        before = deepcopy(f.service.journal.read())
        with self.assertRaises(ProjectError):
            f.service.mutate("pcb.import.parse", f.request({"upload_id": identity}))
        self.assertEqual(f.service.journal.read(), before)
        with self.assertRaises(ProjectError):
            f.service.mutate("pcb.import.chunk", f.request({"upload_id": identity, "path": "원문.kicad_pcb", "offset": 1, "content_base64": "eA=="}))
        upload(f, identity, b"tampered")
        before = deepcopy(f.service.journal.read())
        with self.assertRaises(ProjectError) as caught:
            f.service.mutate("pcb.import.parse", f.request({"upload_id": identity}))
        self.assertEqual(caught.exception.code, "E_HASH")
        self.assertEqual(f.service.journal.read(), before)
        self.assertEqual(f.service._load(before["projects"][f.project]), f.document)

    def test_paths_sizes_duplicates_and_wrong_owner_are_rejected(self):
        f = self.f
        for path in ("../원문.gbr", "C:원문.gbr", "CON.txt", "끝.", "폴더/원문.gbr"):
            with self.subTest(path=path), self.assertRaises(ProjectError):
                begin(f, b"x", path)
        row = {"path": "A.gbr", "bytes": 1, "sha256": "a" * 64}
        with self.assertRaises(ProjectError):
            f.service.mutate("pcb.import.begin", f.request({"format": "gerber_job", "files": [row, {**row, "path": "a.GBR"}]}))
        identity = begin(f, b"x")
        other = f.complete("project.open", {"path": "projects/다른 소유자", "open_mode": "create", "name": "다른 소유자"}, {})
        with self.assertRaises(ProjectError):
            imports.read(f.service, "pcb.import.get", {"contract_version": "rfad.api/2.0", "context": {"project_id": other["project_id"]}, "input": {"upload_id": identity}})

    def test_abandoned_source_cannot_be_resumed_or_applied(self):
        f = self.f
        identity = begin(f, b"abc")
        upload(f, identity, b"abc")
        f.service.mutate("pcb.import.abandon", f.request({"upload_id": identity}))
        self.assertEqual(f.read("pcb.import.get", {"upload_id": identity})["status"], "abandoned")
        with self.assertRaises(ProjectError):
            f.service.mutate("pcb.import.parse", f.request({"upload_id": identity}))
        self.assertEqual(f.service._load(f.service.journal.read()["projects"][f.project]), f.document)

    def _parser_publication(self):
        """! @brief 실제 parser 합격과 구분한 합성 저장 경계 입력을 소유 작업에 연결한다."""
        f = self.f
        raw = b"synthetic storage boundary only; no parser or manufacturing validation"
        identity = begin(f, raw)
        upload(f, identity, raw)
        task = f.service.mutate("pcb.import.parse", f.request({"upload_id": identity}))
        f.service.journal.transaction(lambda state: f.service._event(state["jobs"][task["job_id"]], "running"))
        state = f.service.journal.read()
        job = state["jobs"][task["job_id"]]
        source = state["pcb_imports"][identity]["source_files"][0]["artifact"]
        output = f.workspace / "synthetic-parser-output"
        output.mkdir()
        body = canonical_bytes({"schema": "rfad.pcb-parse/0.1", "format": "kicad_pcb", "raw_preservation_required": True,
            "manufacturing_verified": False, "physics_verified": False,
            "records": [{"path": "원문.kicad_pcb", "data": {}}], "losses": []})
        (output / "parse.json").write_bytes(body)
        returned = {"parsed": {"path": "parse.json", "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}}
        return job, returned, output, source, raw

    def _assert_publication_rejected(self, job, returned, output, source, raw, code):
        """! @brief 거절 시 권위 상태/원시 바이트/파일 목록이 모두 유지되는지 검사한다."""
        f = self.f
        before = f.service.journal.read()
        paths = {path.relative_to(f.workspace) for path in f.workspace.rglob("*") if path.is_file()}
        with self.assertRaises(ProjectError) as raised:
            imports.seal_parsed(f.service.journal, job, returned, output)
        self.assertEqual(raised.exception.code, code)
        self.assertEqual(f.service.journal.read(), before)
        self.assertEqual(f.service.journal.read_artifact(source), raw)
        self.assertEqual({path.relative_to(f.workspace) for path in f.workspace.rglob("*") if path.is_file()}, paths)
        self.assertFalse(any(f.workspace.rglob("parsed")))

    def test_parser_publication_capacity_rejects_before_report_sealing(self):
        """! @brief 실행 중 줄어든 journal 여유를 확인하고 미참조 보고서를 남기지 않는다."""
        args = self._parser_publication()
        limit = len(canonical_bytes(self.f.service.journal.read())) + 512
        with patch.object(exchange_artifacts, "MAX_STATE_BYTES", limit):
            self._assert_publication_rejected(*args, "E_RESOURCE")

    def test_cancelled_parser_cannot_publish_a_report(self):
        """! @brief 완료 파일이 있어도 취소 요청 상태이면 봉인/예약 해제를 하지 않는다."""
        args = self._parser_publication()
        job = args[0]
        self.f.service.journal.transaction(lambda state: self.f.service._event(state["jobs"][job["job_id"]], "cancel_requested"))
        self._assert_publication_rejected(*args, "E_CONFLICT")

    def test_stale_parser_nonce_cannot_publish_a_report(self):
        """! @brief 같은 작업 ID라도 다른 실행 소유 nonce의 완료 파일은 게시하지 않는다."""
        args = self._parser_publication()
        args[0]["exchange"]["nonce"] = str(uuid4())
        self._assert_publication_rejected(*args, "E_CONFLICT")


@unittest.skipUnless(os.environ.get("RFAD_EXCHANGE_PYTHON"), "별도 PCB parser 환경을 명시합니다.")
class PcbImportNativeTests(unittest.TestCase):
    """! @brief 실제 writer 출력의 원시 바이트를 별도 parser로 읽고 환경 없이 다시 연다."""
    def test_real_board_parse_preserves_raw_source_and_runtime_free_reopen(self):
        f = ExchangeFixture(ExchangeRuntime(Path(os.environ["RFAD_EXCHANGE_PYTHON"])))
        try:
            prepare(f)
            data = request(f)
            review = f.complete("export.preview", data)
            task = f.service.mutate("export.build", f.request({**data, "review_hash": review["review_hash"]}))
            f.service.exchange.run_next()
            output = f.read("export.get", {"job_id": task["job_id"]})
            self.assertEqual(output["state"], "completed", output)
            artifact = next(row for row in output["result"]["artifacts"] if row["uri"].endswith("/board.kicad_pcb"))
            raw = f.service.journal.read_artifact(artifact)
            identity = begin(f, raw)
            upload(f, identity, raw)
            parsed = f.service.mutate("pcb.import.parse", f.request({"upload_id": identity}))
            f.service.exchange.run_next()
            record = f.read("pcb.import.get", {"upload_id": identity})
            self.assertEqual(record["parse_state"], "completed", record)
            self.assertEqual(record["parsed"]["schema"], "rfad.pcb-parse/0.1")
            self.assertFalse(record["parsed"]["manufacturing_verified"])
            reference = record["result"]["source_files"][0]["artifact"]
            self.assertEqual(f.service.journal.read_artifact(reference), raw)
            source = record["parsed"]["records"][0]["data"]
            copper = sorted((row for row in f.document["stackup"] if row["role"] == "conductor"), key=lambda row: row["order"])
            mapping = {"board_id": f.document["board"]["id"], "frame_id": f.document["board"]["frame_id"],
                "layers": [{"source": "F.Cu", "target": copper[-1]["id"]}, {"source": "B.Cu", "target": copper[0]["id"]}],
                "nets": [{"source": "0", "target": None}] + [{"source": str(row["code"]), "target": next(net["id"] for net in f.document["nets"] if net["name"] == row["name"])} for row in source["nets"] if row["code"] != 0],
                "placement": None}
            inputs = {"upload_id": identity, "expected_revision": f.revision, "mapping": mapping,
                "acknowledged_losses": [canonical_hash(row) for row in record["parsed"]["losses"]], "reason": "실제 파일 원본을 명시 대응하는 통합 시험"}
            preview = f.read("pcb.import.preview", inputs)
            self.assertTrue(preview["can_apply"], preview)
            apply_request = f.request({**inputs, "command_id": str(uuid4()), "review_hash": preview["review_hash"]})
            applied = f.service.mutate("pcb.import.apply", apply_request)
            self.assertEqual(f.service.mutate("pcb.import.apply", apply_request), applied)
            updated = f.service._load(f.service.journal.read()["projects"][f.project])
            self.assertEqual(updated["materials"], f.document["materials"])
            self.assertTrue(updated["pcb"]["imports"])
            undone = f.service.mutate("project.undo", f.request({"expected_revision": applied["new_revision"], "command_id": str(uuid4())}))
            original = f.service._load(f.service.journal.read()["projects"][f.project])
            for key in ("geometry", "pcb", "materials", "stackup"):
                self.assertEqual(original[key], f.document[key])
            redone = f.service.mutate("project.redo", f.request({"expected_revision": undone["new_revision"], "command_id": str(uuid4())}))
            f.revision = redone["new_revision"]
            f.complete("project.save", {"expected_revision": f.revision})
            updated = f.service._load(f.service.journal.read()["projects"][f.project])
            record = f.read("pcb.import.get", {"upload_id": identity})
            f.service.close()
            f.service = ProjectService(f.workspace, auto_run=False)
            self.assertEqual(f.read("pcb.import.get", {"upload_id": identity}), record)
            self.assertEqual(f.service._load(f.service.journal.read()["projects"][f.project]), updated)
            self.assertEqual(f.service.journal.read_artifact(reference), raw)
        finally:
            f.close()
