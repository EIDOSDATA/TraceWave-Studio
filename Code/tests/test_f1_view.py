"""! @brief 대형 설계의 표시 페이지와 실제 Windows 재열기를 검증한다."""
import base64
from contextlib import closing
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.application import archive_export_service, project_archive
from rfad.application.canonical import canonical_bytes
from rfad.application.edit_view_pages import PROFILE, MAX_PAGE_BYTES, MAX_ROWS
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.catalog.models import CATALOG_IMPORT_VERSION, CATALOG_SCHEMA, canonical_json
from rfad.catalog.schema import create_indexes, create_schema
from test_cad_worker_process import CODE_ROOT, register_fixture, request
from test_design import build_design
from test_f1_project import f1_project


def f1_catalog(database):
    """! @brief 원문과 미정 Df를 가진 10만 건의 합성 SQLite 조회 자료를 만든다."""
    properties = canonical_json({"fixture": True})
    with closing(sqlite3.connect(database)) as connection, connection:
        create_schema(connection)
        metadata = {"schema": CATALOG_SCHEMA, "import_version": CATALOG_IMPORT_VERSION,
                    "catalog_id": "perf:f1-table-100000", "counts": {"observations": 100000}}
        connection.executemany("INSERT INTO meta VALUES (?,?)",
                               ((key, canonical_json(value)) for key, value in metadata.items()))
        source = '{"kind":"synthetic fixture"}'
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        connection.execute(
            "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?)",
            ("fixture-source", "F1", "합성 조회 자료", "https://example.test/fixture", None, 0, source, digest))
        connection.execute(
            "INSERT INTO products VALUES (?,?,?,?,?,?,?)",
            ("fixture-product", "F1", "합성 기판", "fixture", None, source, digest))

        def records():
            """! @brief 입력을 전량 쌓지 않고 안정 정렬 키와 원문 해시를 생성한다."""
            for index in range(1, 100001):
                record_id = f"fixture-{index:06d}"
                group = "A" if index % 2 == 0 else "B"
                product = f"조건 그룹 {group} / {index:06d}"
                text = canonical_json({"record_id": record_id, "product": product, "dk": 4.2, "df": None})
                # @brief 끝 페이지에 긴 표기를 넣어 프레임 바이트 제한으로 나뉘는 조회를 검증한다.
                display_product, form = (product + " 원문" * 160, "직조" * 256) if index > 99950 else (product, "core")
                yield (record_id, "fixture-product", "fixture-source", "F1", display_product, "fixture", form, 4.2,
                       None, text, hashlib.sha256(text.encode("utf-8")).hexdigest(), properties)

        connection.executemany(
            "INSERT INTO observations(record_id,product_id,source_id,publisher,product,dataset_role,material_form,"
            "dk,df,raw_json,raw_sha256,properties_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", records())
        create_indexes(connection)


def read(service, document, method, **input_data):
    """! @brief 클라이언트와 같은 JSON-RPC 경계에서 페이지를 요청한다."""
    envelope = {"jsonrpc": "2.0", "id": "F1", "method": method,
                "params": {"contract_version": "rfad.api/2.0", "context": {"project_id": document["project_id"]},
                           "input": {"expected_revision": document["revision_id"], **input_data}}}
    return handle_frame(canonical_bytes(envelope), service)


class F1ViewTests(unittest.TestCase):
    """! @brief 누락 없는 전송과 실제 Windows 열기, 저장, 재열기 경계를 시험한다."""

    def collect(self, service, document, method, rows, **selection):
        """! @brief 합산 행 수와 실제 전송 크기를 확인하고 개정별 순서로 연결한다."""
        output = {key: [] for key in rows}
        offset = 0
        while offset is not None:
            reply = read(service, document, method, offset=offset, **selection)
            self.assertEqual(reply["id"], "F1")
            self.assertIn("result", reply, reply)
            result = reply["result"]
            count = 0
            for key in rows:
                output[key].extend(result[key])
                count += len(result[key])
            self.assertLessEqual(count, MAX_ROWS)
            self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")), MAX_PAGE_BYTES)
            self.assertEqual(result["revision_id"], document["revision_id"])
            page = result["page"]
            self.assertEqual(page["profile"], PROFILE)
            self.assertEqual(page["offset"], offset)
            if page["next"] is None:
                self.assertEqual(page["total"], offset + count)
            else:
                self.assertGreater(page["next"], offset)
                self.assertEqual(page["next"], offset + count)
            offset = page["next"]
        return output

    def test_pages_return_all_geometry_parameters_and_port_choices(self):
        """! @brief 큰 선택 목록도 한 응답 크기로 제한하지 않고 원래 순서로 보낸다."""
        with TemporaryDirectory(prefix="rfad F1 pages ") as temporary, ProjectService(Path(temporary), auto_run=False) as service:
            fixture = f1_project()
            port = build_design()["ports"][0]
            port["positive_geometry_id"] = fixture["geometry"][0]["id"]
            port["reference_geometry_id"] = fixture["geometry"][1]["id"]
            fixture["ports"] = [port]
            document, _ = register_fixture(service, fixture)
            before = service.journal.read()
            editor = self.collect(service, document, "editor.page", ("items", "view_choices"))
            self.assertEqual(sum(row["kind"] == "parameter" for row in editor["items"]), 1000)
            shapes = self.collect(service, document, "canvas.page", ("shapes", "omissions"))
            identities = [row["id"] for row in fixture["geometry"]]
            self.assertEqual([row["id"] for row in shapes["shapes"]], identities)
            self.assertEqual(shapes["omissions"], [])
            self.assertEqual([row["id"] for row in editor["items"] if row["kind"] == "geometry"], identities)
            port_only = self.collect(service, document, "editor.page", ("items", "view_choices"), include_items=False,
                                     selection={"kind": "port", "id": port["id"]})
            self.assertEqual(port_only["items"], [])
            identity_set = set(identities)
            chosen = {}
            for index, item in port_only["view_choices"]:
                if item["value"] in identity_set:
                    chosen.setdefault(index, []).append(item["value"])
            self.assertEqual(list(chosen.values()), [identities, identities])
            stale = read(service, document, "canvas.page", offset=0, expected_revision=fixture["frames"]["board"]["id"])
            self.assertEqual(stale["error"]["data"]["domain_code"], "E_CONFLICT")
            end = read(service, document, "canvas.page", offset=10000)
            self.assertEqual(end["error"]["data"]["domain_code"], "E_SCHEMA")
            self.assertEqual(service.journal.read(), before)

    @unittest.skipUnless(sys.platform == "win32" and os.environ.get("RFAD_GUI_EXE"), "실제 Windows Studio가 필요합니다.")
    def test_windows_saves_and_reopens_all_rows(self):
        """! @brief 실제 Studio의 두 서비스 세션에서 큰 설계와 출처를 대조한다."""
        with TemporaryDirectory(prefix="TraceWave F1 Windows ") as temporary:
            directory = Path(temporary)
            workspace = directory / "한글 대형 설계"
            with ProjectService(workspace, auto_run=False) as service:
                document, _ = register_fixture(service, f1_project())
                path = service.journal.read()["projects"][document["project_id"]]["path"]
            artifact = directory / "studio.json"
            catalog = directory / "자료 검색.sqlite"
            f1_catalog(catalog)
            before_catalog = hashlib.sha256(catalog.read_bytes()).hexdigest()
            executable = Path(os.environ["RFAD_GUI_EXE"]).resolve()
            display_probe = os.environ.get("RFAD_TEST_CATALOG_SCROLL_DISPLAY") == "1"
            process = subprocess.run([str(executable), "--python", sys.executable, "--source", str(CODE_ROOT / "src"),
                "--workspace", str(workspace), "--open-project", path, "--catalog", str(catalog),
                "--catalog-table-smoke-test", "--smoke-report", str(artifact)],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=200 if display_probe else 125, check=False)
            self.assertTrue(artifact.is_file(), (process.returncode, process.stderr))
            report = json.loads(artifact.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            self.assertTrue(report["passed"] and report["snapshot_id"])
            self.assertEqual(report["service_sessions"], 2)
            self.assertEqual(report["revision_id"], report["saved_revision"])
            self.assertEqual(report["canvas_shapes"], 10_000)
            self.assertEqual(report["canvas_omissions"], 0)
            self.assertEqual(report["editor_parameters"], 1_000)
            self.assertEqual(report["pcb_catalog_metrics"]["rows"], 100_000)
            self.assertEqual(report["pcb_catalog_metrics"]["filtered_rows"], 50_000)
            self.assertIn("virtual_catalog_scroll_filter_and_last_row", report["pcb_checks"])
            if display_probe:
                trace = report["pcb_catalog_metrics"]["display_trace"]
                self.assertEqual(trace["catalog_rows"], 100_000)
                self.assertGreaterEqual(trace["end_qpc"] - trace["start_qpc"], 35 * trace["qpc_frequency"])
                visible = {row[2] for row in trace["desktop_updates"] if row[2] is not None and row[2] > 0}
                self.assertGreaterEqual(len(visible), 1001, "표 합성 간격 1000개를 확보하지 못했습니다.")
            self.assertEqual(hashlib.sha256(catalog.read_bytes()).hexdigest(), before_catalog)
            with ProjectService(workspace, auto_run=False) as service:
                state = service.journal.read()
                item = state["projects"][document["project_id"]]
                saved = service.repository.load(item)
                self.assertEqual(saved["revision_id"], report["saved_revision"])
                for key in ("board", "geometry", "parameters", "materials", "stackup", "ports", "extensions"):
                    self.assertEqual(document[key], saved[key], key)
                self.assertEqual(state["snapshots"][report["snapshot_id"]]["artifact"]["sha256"], item["current"]["sha256"])
            if output := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                (Path(output) / "f1-save-reopen.json").write_bytes(artifact.read_bytes())


    @unittest.skipUnless(sys.platform == "win32" and os.environ.get("RFAD_GUI_EXE"), "실제 Windows Studio가 필요합니다.")
    def test_windows_reopens_a_restored_large_archive(self):
        """! @brief 8 MiB를 넘는 복원 ZIP의 게시와 수신을 실제 Windows 재열기로 연결한다."""
        with TemporaryDirectory(prefix="TraceWave 대형 복원 ") as temporary:
            directory = Path(temporary)
            source = directory / "송신"
            destination = directory / "수신"
            document = f1_project()
            identity = document["project_id"]
            scope = {"project_id": identity}

            def call(service, method, data):
                """! @brief 로컬의 실제 수신/검토/복원 API와 같은 프레임을 보낸다."""
                params = {"contract_version": "rfad.api/2.0", "context": {}, "input": data}
                if method in ("reserve", "apply"):
                    params.update(request_key=str(uuid4()), request_key_epoch=service.policy()["request_key_epoch"])
                frame = {"jsonrpc": "2.0", "id": "archive", "method": "archive.receive." + method, "params": params}
                response = handle_frame(canonical_bytes(frame), service)
                self.assertIn("result", response, response)
                return response["result"]

            with ProjectService(source, auto_run=False) as service:
                document, snapshot = register_fixture(service, document)
                path = service.journal.read()["projects"][identity]["path"]
                data = {"expected_revision": document["revision_id"], "include_sources": True}
                preview = archive_export_service.read(service, "archive.export.preview", {
                    "contract_version": "rfad.api/2.0", "context": scope, "input": data})
                item = service.mutate("archive.export.build", request(service, identity, {
                    **data, "review_hash": preview["review_hash"]}))
                reference = item["artifact"]
                self.assertGreater(reference["bytes"], 8 * 1024 * 1024)
                self.assertEqual(reference["bytes"], preview["estimated_bytes"])
                self.assertLessEqual(reference["bytes"], project_archive.MAX_ARCHIVE_BYTES)
                raw = (source / reference["uri"]).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), reference["sha256"])
                for offset in (0, (len(raw) - 1) // item["chunk_bytes"] * item["chunk_bytes"]):
                    chunk = archive_export_service.read(service, "archive.export.read", {
                        "contract_version": "rfad.api/2.0", "context": scope,
                        "input": {"package_id": item["package_id"], "offset": offset, "sha256": reference["sha256"]}})
                    self.assertEqual(base64.b64decode(chunk["content_base64"]), raw[offset:offset + item["chunk_bytes"]])
            with ProjectService(destination, auto_run=False) as service:
                accepted = call(service, "begin", {"bytes": len(raw), "archive_sha256": reference["sha256"]})
                transfer = {"upload_id": accepted["upload_id"]}
                for offset in range(0, len(raw), accepted["chunk_bytes"]):
                    chunk = raw[offset:offset + accepted["chunk_bytes"]]
                    observed = call(service, "chunk", {
                        **transfer, "offset": offset, "content_base64": base64.b64encode(chunk).decode("ascii")})
                    self.assertEqual(observed["received"], offset + len(chunk))
                preview = call(service, "review", transfer)
                review = {**transfer, "archive_sha256": reference["sha256"], "review_hash": preview["review_hash"]}
                self.assertEqual(call(service, "reserve", review)["status"], "reserved")
                self.assertEqual(call(service, "apply", review)["status"], "restored")
                state = service.journal.read()
                self.assertEqual(state["snapshots"][snapshot["snapshot_id"]], snapshot)
                self.assertEqual(service.repository.load(state["projects"][identity]), document)

            report_path = directory / "복원 GUI.json"
            executable = Path(os.environ["RFAD_GUI_EXE"]).resolve()
            process = subprocess.run([str(executable), "--python", sys.executable, "--source", str(CODE_ROOT / "src"),
                "--workspace", str(destination), "--open-project", path, "--smoke-test", "--smoke-report", str(report_path)],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=125, check=False)
            self.assertTrue(report_path.is_file(), (process.returncode, process.stderr))
            report = json.loads(report_path.read_bytes())
            self.assertEqual(process.returncode, 0, report)
            self.assertTrue(report["passed"])
            self.assertEqual(report["canvas_shapes"], 10_000)
            self.assertEqual(report["canvas_omissions"], 0)
            self.assertEqual(report["editor_parameters"], 1_000)
            self.assertEqual(report["service_sessions"], 2)
            with ProjectService(destination, auto_run=False) as service:
                actual = service.repository.load(service.journal.read()["projects"][identity])
                for field in ("geometry", "parameters", "materials", "extensions"):
                    self.assertEqual(actual[field], document[field], field)
            if output := os.environ.get("RFAD_GUI_TEST_ARTIFACT_DIR"):
                evidence = {"studio": report, "archive_bytes": len(raw), "archive_sha256": reference["sha256"]}
                (Path(output) / "f1-large-restored.json").write_bytes(canonical_bytes(evidence))
