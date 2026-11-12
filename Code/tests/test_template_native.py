"""! @brief 공개 템플릿/목표 명령에서 실제 CAD 출력과 해석기 없는 재열기까지 검사한다."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.application.cad_jobs import CadRuntime
from rfad.application.projects import ProjectService
from rfad.application.rpc import handle_frame
from rfad.templates.cards import ARC, IFA, describe_card
from rfad.templates.g031 import IDENTITY as G031
from test_literature_templates import literature_input
from test_cad_worker_process import cad_request, register_fixture, request, status
from test_pcb_ifa import ifa_document
from test_pcb_solver import fixture_document, quantity


CAD_PYTHON = os.environ.get("RFAD_CAD_PYTHON", "")


def explicit_case(identity):
    """! @brief 제조값이 아닌 명시 기하 시험을 준비하고 모든 RF 물성은 미정으로 둔다."""
    document = fixture_document(circle=True) if identity in (ARC, G031) else ifa_document()
    if identity == G031:
        document["board"]["outline"]["radius"] = quantity(10, "mm")
    document["geometry"], document["ports"], document["nets"] = [], [], []
    for material in document["materials"]:
        for key in ("epsilon_r", "tan_delta", "conductivity"):
            material[key].update(value_si=None, status="missing")
    if identity == G031:
        return document, literature_input(document, x="0", y="0")["explicit_inputs"]
    values = ({"center_x": 0, "center_y": 0, "radius": 6, "start_angle": 0, "sweep_angle": 90,
               "width": 0.8, "feed_start_x": 2, "feed_start_y": 0, "feed_width": 0.6}
              if identity == ARC else
              {"ground_left": 0, "ground_bottom": 0, "ground_width": 40, "ground_height": 50,
               "radiator_start_x": 5, "radiator_y": 57, "radiator_length": 26, "trace_width": 1,
               "short_x": 5, "short_start_y": 49.5, "feed_x": 9, "feed_start_y": 53,
               "pad_width": 2, "pad_height": 2})
    fields = describe_card(identity)["input_fields"]
    return document, {field["key"]: quantity(values[field["key"]], field["display_unit"]) for field in fields}


@unittest.skipUnless(sys.platform == "win32" and CAD_PYTHON, "RFAD_CAD_PYTHON으로 실제 Windows CAD 환경을 지정해야 합니다.")
class TemplateNativeTests(unittest.TestCase):
    """! @brief 두 기하 카드의 실제 worker 경로에서도 출처/미정 상태가 유지되는지 검사한다."""

    def rpc(self, service, method, params):
        """! @brief 실제 공개 프레임 검사와 라우팅을 통과시킨다."""
        reply = handle_frame(json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, ensure_ascii=False).encode(), service)
        self.assertNotIn("error", reply, reply)
        return reply["result"]

    def complete(self, service, method, params):
        """! @brief 일반 자료 처리 작업이 완료한 권위 결과를 읽는다."""
        job = self.rpc(service, method, params)
        self.assertTrue(service.run_next())
        result = status(service, job["job_id"])
        self.assertEqual(result["state"], "completed", result)
        return result["events"][-1]["operation_result"]

    def test_arc_and_ifa_sources_survive_real_step_and_runtime_free_reopen(self):
        """! @brief 기하 성공이 물성/급전/실물 성능을 채우지 않으며 같은 봉인 원본을 출력한다."""
        self.run_cases((ARC, IFA))

    def test_g031_sources_survive_real_step_and_runtime_free_reopen(self):
        """! @brief 문헌의 부분 원호/stub도 같은 실제 CAD/봉인/재열기 경로를 사용한다."""
        self.run_cases((G031,))

    def run_cases(self, identities):
        """! @brief 카드별로 독립 작업 영역에서 공개 API와 실제 worker를 실행한다."""
        evidence = []
        for identity in identities:
            with self.subTest(template=identity), TemporaryDirectory(prefix="rfad template CAD ") as directory:
                workspace = Path(directory)
                with ProjectService(workspace, cad_runtime=CadRuntime(Path(CAD_PYTHON)), auto_run=False) as service:
                    original, inputs = explicit_case(identity)
                    document, original_snapshot = register_fixture(service, original)
                    project_id = document["project_id"]
                    target = self.rpc(service, "target.editor.apply", request(service, project_id, {
                        "expected_revision": document["revision_id"], "command_id": str(uuid4()),
                        "operation": "set", "target_id": None, "reason": "native 기하 통합 시험의 목표 입력; RF 합격 아님",
                        "values": {"name": "명시 시험 대역", "band.start.mode": "value", "band.start.value": "2.4",
                                   "band.end.mode": "value", "band.end.value": "2.5", "sampling.count": "11"},
                    }))
                    current = service._load(service.journal.read()["projects"][project_id])
                    card = describe_card(identity)
                    layer = next(row for row in current["stackup"] if row["role"] == "conductor")
                    data = {"expected_revision": target["new_revision"], "mode": "explicit_geometry",
                            "template": {key: card[key] for key in ("template_id", "version", "content_hash")},
                            "instance_id": str(uuid4()),
                            "target_refs": [{key: current["targets"][0][key] for key in ("id", "revision_id")}],
                            "binding": {"board_id": current["board"]["id"], "frame_id": current["board"]["frame_id"],
                                        "layer_id": layer["id"], "material_id": layer["material_id"]},
                            "explicit_inputs": inputs, "port": None}
                    preview = self.rpc(service, "template.synthesize", {
                        "contract_version": "rfad.api/2.0", "context": {"project_id": project_id}, "input": data})
                    self.assertTrue(preview["can_apply"], preview)
                    applied = self.rpc(service, "template.apply", request(service, project_id, {
                        **data, "command_id": str(uuid4()), "preview_hash": preview["preview_hash"]}))
                    document = service._load(service.journal.read()["projects"][project_id])
                    self.assertEqual(document["materials"], original["materials"])
                    self.assertEqual(document["stackup"], original["stackup"])
                    self.assertEqual(document["targets"], current["targets"])
                    self.assertEqual(document["ports"], [])
                    self.assertTrue(document["extensions"])
                    snapshot = self.complete(service, "snapshot.create", request(service, project_id, {
                        "expected_revision": applied["new_revision"]}))
                    self.complete(service, "project.save", request(service, project_id, {"expected_revision": applied["new_revision"]}))
                    task = self.rpc(service, "export.build", cad_request(service, document, snapshot))
                    self.assertTrue(service.cad.run_next())
                    completed = status(service, task["job_id"])
                    self.assertEqual(completed["state"], "completed", completed)
                    result = completed["events"][-1]["operation_result"]
                    self.assertEqual(result["status"], "generated_unverified")
                    self.assertFalse(result["physics_verified"])
                    self.assertFalse(result["manufacturing_verified"])
                    artifacts = {row["role"]: row for row in completed["artifacts"]}
                    sidecar = json.loads(service.journal.read_artifact(artifacts["sidecar"]))
                    self.assertEqual(sidecar["source_semantics"], document)
                    self.assertEqual(sidecar["snapshot"], snapshot)
                    self.assertGreater(artifacts["step"]["bytes"], 0)
                    self.assertGreater(result["solid_count"], 0)
                    sealed = {row["uri"]: row["sha256"] for row in completed["artifacts"]}
                    sealed[original_snapshot["artifact"]["uri"]] = original_snapshot["artifact"]["sha256"]
                    saved = deepcopy(document)
                with ProjectService(workspace, auto_run=False) as reopened:
                    self.assertIsNone(reopened.cad.runtime)
                    opened = self.complete(reopened, "project.open", {
                        "contract_version": "rfad.api/2.0", "context": {},
                        "input": {"open_mode": "open", "path": "projects/CAD 한글 교환 검증"},
                        "request_key": str(uuid4()), "request_key_epoch": reopened.policy()["request_key_epoch"]})
                    self.assertEqual(opened["document"], saved)
                    self.assertEqual(opened["target_input_statuses"][0]["evaluation_status"], "not_evaluated")
                    latest = self.rpc(reopened, "cad.latest", {
                        "contract_version": "rfad.api/2.0", "context": {"project_id": project_id}, "input": {}})
                    self.assertEqual(latest["result"], result)
                    self.assertFalse(reopened.cad.run_next())
                    for uri, digest in sealed.items():
                        self.assertEqual(hashlib.sha256((workspace / uri).read_bytes()).hexdigest(), digest)
                    evidence.append({
                        "template_id": identity, "card_hash": card["content_hash"],
                        "snapshot": snapshot, "result": result,
                        "artifacts": list(artifacts.values()),
                        "materials_and_stackup_preserved": True, "targets_preserved": True,
                        "runtime_free_reopen": True, "original_snapshot_preserved": True,
                        "artifacts_retained_after_test": False,
                    })
        report = os.environ.get("RFAD_TEMPLATE_NATIVE_REPORT")
        if report:
            Path(report).write_text(json.dumps({"cases": evidence}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
