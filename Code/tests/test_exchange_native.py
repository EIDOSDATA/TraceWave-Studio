"""! @brief 명시한 별도 Python에서 실제 도면 생성/재입력/봉인/재열기를 검사한다."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from rfad.application import exchange_jobs
from rfad.application import exchange_contract
from rfad.application.canonical import canonical_bytes
from rfad.application.exchange_runtime import ExchangeRuntime
from rfad.application.projects import ProjectService
from test_exchange_service import ExchangeFixture

PYTHON = os.environ.get("RFAD_EXCHANGE_PYTHON")


@unittest.skipUnless(PYTHON, "RFAD_EXCHANGE_PYTHON으로 고정한 실제 출력 실행 환경을 지정합니다.")
class ExchangeNativeTests(unittest.TestCase):
    """! @brief 실제 파일 검수를 제조/실측 합격과 구분한다."""
    def setUp(self):
        self.fixture = ExchangeFixture(ExchangeRuntime(Path(PYTHON)))

    def tearDown(self):
        self.fixture.close()

    def build(self, format_name):
        """! @brief 실제 review hash로 별도 실행을 접수하고 완료 결과를 읽는다."""
        f = self.fixture
        data = f.data(format_name)
        preview = f.complete("export.preview", data)
        self.assertTrue(preview["can_build"], preview)
        task = f.service.mutate("export.build", f.request({**data, "review_hash": preview["review_hash"]}))
        self.assertTrue(f.service.exchange.run_next())
        job = f.service.journal.read()["jobs"][task["job_id"]]
        self.assertEqual(job["state"], "completed", job["events"][-1])
        result = f.read("export.get", {"job_id": task["job_id"]})
        self.assertFalse(result["result"]["manufacturing_verified"])
        self.assertFalse(result["result"]["physics_verified"])
        self.assertEqual(result["report"]["status"], "passed_profile")
        return task, job, result

    def test_pdf_svg_dxf_actual_workers_full_source_and_runtime_free_reopen(self):
        """! @brief 세 형식의 실제 파일과 원문 sidecar를 읽고 설치 없이 과거 결과를 다시 연다."""
        f = self.fixture
        before = deepcopy(f.service.journal.read()["projects"][f.project])
        records = []
        for format_name in ("pdf", "svg", "dxf"):
            with self.subTest(format=format_name):
                task, job, result = self.build(format_name)
                self.assertGreater(job["exchange"]["process"]["pid"], 0)
                self.assertEqual(job["exchange"]["runtime"]["source_bundle"]["profile"], "rfad.source.exchange/0.1")
                refs = result["result"]["artifacts"]
                sidecar = next(row for row in refs if row["uri"].endswith("/sidecar.json"))
                source = json.loads(f.service.journal.read_artifact(sidecar))
                self.assertEqual(source["source_semantics"], f.document)
                self.assertTrue(source["source_bindings"]["dimensions"])
                for row in refs:
                    self.assertEqual(hashlib.sha256((f.workspace / row["uri"]).read_bytes()).hexdigest(), row["sha256"])
                records.append((task, result))
        self.assertEqual(f.service.journal.read()["projects"][f.project], before)
        f.service.close()
        f.service = ProjectService(f.workspace, auto_run=False)
        for task, result in records:
            self.assertEqual(f.read("export.get", {"job_id": task["job_id"]}), result)
        self.assertEqual(f.service._load(f.service.journal.read()["projects"][f.project]), f.document)

    def test_fresh_verification_preserves_original_package_and_is_idempotent(self):
        """! @brief 원래 보고서를 덮지 않고 다른 소유 프로세스의 새 검수 보고서를 만든다."""
        f = self.fixture
        task, original_job, result = self.build("svg")
        before = {row["uri"]: (f.workspace / row["uri"]).read_bytes() for row in result["result"]["artifacts"]}
        request = f.request({"job_id": task["job_id"], "manifest_sha256": result["manifest_sha256"]})
        verification = f.service.mutate("export.verify", request)
        self.assertEqual(f.service.mutate("export.verify", request), verification)
        f.service.exchange.run_next()
        current = f.read("export.get", {"job_id": verification["job_id"]})
        self.assertEqual(current["state"], "completed", current)
        self.assertEqual(current["result"]["original_job_id"], task["job_id"])
        self.assertEqual(current["result"]["source_manifest_sha256"], result["manifest_sha256"])
        new_job = f.service.journal.read()["jobs"][verification["job_id"]]
        self.assertNotEqual(new_job["exchange"]["process"]["pid"], original_job["exchange"]["process"]["pid"])
        self.assertEqual(f.read("export.get", {"job_id": task["job_id"]}), result)
        for uri, raw in before.items():
            self.assertEqual((f.workspace / uri).read_bytes(), raw)

    def test_tampered_worker_file_never_replaces_previous_completed_output(self):
        """! @brief 실행 뒤 변조한 파일을 부분 게시하지 않고 과거 정상 결과를 유지한다."""
        f = self.fixture
        original_task, _, result = self.build("svg")
        before = {row["uri"]: (f.workspace / row["uri"]).read_bytes() for row in result["result"]["artifacts"]}
        data = f.data("svg")
        preview = f.complete("export.preview", data)
        task = f.service.mutate("export.build", f.request({**data, "review_hash": preview["review_hash"]}))
        original_seal = exchange_jobs.seal
        def changed(journal, job, package, output):
            path = next(output.glob("*.svg"))
            path.write_bytes(path.read_bytes() + b"<!-- deliberate test tamper -->")
            return original_seal(journal, job, package, output)
        with patch.object(exchange_jobs, "seal", side_effect=changed):
            f.service.exchange.run_next()
        current = f.read("export.get", {"job_id": task["job_id"]})
        self.assertEqual(current["state"], "failed")
        self.assertIsNone(current["result"])
        self.assertEqual(f.read("export.get", {"job_id": original_task["job_id"]}), result)
        for uri, raw in before.items():
            self.assertEqual((f.workspace / uri).read_bytes(), raw)

    def test_new_reader_identity_verifies_old_writer_without_replacing_history(self):
        """! @brief 같은 profile의 새 reader 소스가 이전 writer의 보존 패키지를 새 기록으로 검수한다."""
        f = self.fixture
        task, original_job, original = self.build("svg")
        old_identity = deepcopy(original_job["exchange"]["runtime"])
        entry = f.workspace.parent / "different-reader-entry.py"
        source = Path(__file__).resolve().parents[1] / "tools" / "exchange_worker.py"
        entry.write_bytes(source.read_bytes() + b"\n# Explicit reader identity variation for preservation testing.\n")
        f.service.close()
        runtime = ExchangeRuntime(Path(PYTHON), entry=entry)
        self.assertNotEqual(runtime.identity, old_identity)
        f.service = ProjectService(f.workspace, auto_run=False, exchange_runtime=runtime)
        verify = f.service.mutate("export.verify", f.request({"job_id": task["job_id"],
            "manifest_sha256": original["manifest_sha256"]}))
        self.assertTrue(f.service.exchange.run_next())
        viewed = f.read("export.get", {"job_id": verify["job_id"]})
        self.assertEqual(viewed["state"], "completed", viewed)
        self.assertEqual(viewed["manifest"]["original_writer_runtime"], old_identity)
        self.assertEqual(viewed["manifest"]["current_reader_runtime"], runtime.identity)
        self.assertEqual(f.read("export.get", {"job_id": task["job_id"]}), original)

    def test_omission_labels_use_sealed_names_without_changing_projection_or_history(self):
        """! @brief 미정 외부 물체와 제외 도형의 당시 이름을 조회하되 현재 이름/보존 바이트를 섞지 않는다."""
        f = self.fixture
        omitted_shape = deepcopy(f.document["geometry"][0])
        omitted_shape.update(id=str(uuid4()), name="출력에서 제외한 원호 검토선", include_in_export=False, include_in_em=False)
        f.command("geometry.set", {"geometry": omitted_shape})

        def physical(section, changes, identity=None):
            """! @brief 실물 치수는 입력하지 않고 공개 물리 설정 명령으로 출처만 보존한다."""
            response = f.service.mutate("physical.setup.apply", f.request({
                "expected_revision": f.revision, "command_id": str(uuid4()), "section": section,
                "operation": "set", "record_id": identity, "reason": "미정 시료의 출력 제외 검토",
                "changes": changes, "step_token": None}))
            f.revision = response["new_revision"]
            return response["record_id"]

        scenario = physical("scenario", {"name": "설치 치수 미정 환경"})
        part = physical("part", {"name": "치수 미정 배터리", "scenario_id": scenario,
                                "visible": False, "include_in_export": False})
        physical("activation", {"active_scenario_id": scenario})
        f.document = f.service._load(f.service.journal.read()["projects"][f.project])
        f.snapshot = f.complete("snapshot.create", {"expected_revision": f.revision, "description": "제외 항목의 당시 이름"})
        data = f.data("svg")
        projection = exchange_contract.build_input(f.document, f.snapshot, data, str(uuid4()))
        preview = f.complete("export.preview", data)
        self.assertEqual(preview["review_hash"], exchange_contract.review_hash(projection, f.service.exchange.runtime.identity))
        labels = {row["id"]: row for row in preview["omissions"]}
        self.assertEqual(labels[part]["label"], "치수 미정 배터리")
        self.assertEqual(labels[omitted_shape["id"]]["label"], omitted_shape["name"])
        self.assertTrue(all(row["name_state"] == "stored" for row in labels.values()))
        self.assertEqual([{key: row[key] for key in ("id", "reason")} for row in preview["omissions"]],
                         projection["projection"]["omissions"])
        task, job, viewed = self.build("svg")
        raw_input = f.service.journal.read_artifact(job["exchange"]["input"])
        self.assertEqual(json.loads(raw_input)["projection"]["omissions"], projection["projection"]["omissions"])
        self.assertEqual(viewed["omissions"], preview["omissions"])
        omitted_shape["name"] = "후속 개정의 다른 도형 이름"
        f.command("geometry.set", {"geometry": omitted_shape})
        physical("part", {"name": "후속 개정의 다른 배터리 이름"}, part)
        state = f.service.journal.read()
        files = {path.relative_to(f.workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in f.workspace.rglob("*") if path.is_file() and path.name != ".writer.lock"}
        self.assertEqual(f.read("export.get", {"job_id": task["job_id"]}), viewed)
        self.assertEqual(f.service.journal.read(), state)
        f.service.close()
        f.service = ProjectService(f.workspace, auto_run=False)
        self.assertEqual(f.read("export.get", {"job_id": task["job_id"]}), viewed)
        self.assertEqual(f.service.journal.read_artifact(job["exchange"]["input"]), raw_input)
        self.assertEqual(f.service.journal.read_artifact(f.snapshot["artifact"]), canonical_bytes(f.document))
        self.assertEqual({path.relative_to(f.workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in f.workspace.rglob("*") if path.is_file() and path.name != ".writer.lock"}, files)


if __name__ == "__main__":
    unittest.main()
