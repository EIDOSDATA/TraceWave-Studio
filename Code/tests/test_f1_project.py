"""! @brief 일반 편집 크기의 프로젝트와 실제 저장 경계를 검증한다."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rfad.application.projects import ProjectService
from rfad.domain.errors import ProjectError
from rfad.domain.parameter_graph import evaluate_parameters, expression_record
from rfad.domain.resource_limits import MAX_GEOMETRY, MAX_PARAMETERS, MAX_INLINE_DOCUMENT_BYTES
from rfad.storage.journal import MAX_ARTIFACT_BYTES
from test_cad_worker_process import register_fixture, request, status
from test_design import build_design, identity, quantity, unknown


def f1_project():
    """! @brief 네 층에 분포한 패턴 1만 개와 미정값을 포함한 매개변수 천 개를 만든다."""
    document = build_design(with_port=False)
    document["metadata"]["name"] = "F1 일반 편집 설계"
    document["board"]["outline"].update(width=quantity(102, "mm"), height=quantity(102, "mm"))
    document["materials"][0]["tan_delta"]["source_refs"] = ["시험 원문: 손실 미확정"]
    layer = document["stackup"][0]
    for index in range(1, 4):
        other = deepcopy(layer)
        other.update(id=identity(10 + index), name=f"시험 도체층 {index + 1}", order=index, z_min=quantity(index / 5, "mm"))
        document["stackup"].append(other)
    template = document["geometry"][0]
    geometry = []
    for number in range(MAX_GEOMETRY):
        layer_index, offset = divmod(number, 2_500)
        line_index, column = divmod(offset, 50)
        x = 1 + column + (layer_index % 2) * 50
        y = 1 + line_index + (layer_index // 2) * 50
        item = {**template, "id": identity(10_000 + number), "layer_id": document["stackup"][layer_index]["id"],
                "source_ref": "시험 원문: 도체 좌표", "width": quantity(0.15, "mm"),
                "start": [quantity(x, "mm"), quantity(y, "mm")],
                "end": [quantity(x + 0.7, "mm"), quantity(y + 0.2, "mm")]}
        if number % 50 == 0:
            item["kind"] = "arc_path"
            item["center"] = item.pop("start")
            del item["end"]
            item.update(radius=quantity(0.3, "mm"), start_angle=quantity(30, "deg"), sweep_angle=quantity(150, "deg"))
        if number % 123 == 0:
            item["name"] = f"사용자 패턴 {number:05d}"
        geometry.append(item)
    document["geometry"] = geometry
    for index in range(MAX_PARAMETERS):
        key = identity(40_000 + index)
        value = unknown("length", "mm") if index % 37 == 0 else quantity(index / 10, "mm")
        value["source_refs"] = ["시험 원문: 치수"]
        document["parameters"][key] = {"id": key, "name": f"치수 {index:04d}", "quantity": value}
    return document


class F1ProjectTests(unittest.TestCase):
    """! @brief 유한 문서 저장, 현재 개정 및 구형 인라인 형식을 확인한다."""

    def test_f1_capacity_preserves_snapshot_saved_and_reopened_bytes(self):
        """! @brief 개정과 스냅샷은 큰 원본을 보존하고 작업 영수증은 식별 정보만 저장한다."""
        def complete(service, method, data, project_id=None, *, expected="completed"):
            """! @brief 다른 클라이언트와 같은 작업 접수 및 상태 조회를 실행한다."""
            envelope = request(service, project_id, data)
            if project_id is None:
                envelope["context"] = {}
            task = service.mutate(method, envelope)
            self.assertTrue(service.run_next())
            result = status(service, task["job_id"])
            self.assertEqual(result["state"], expected, result["events"][-1])
            return result["events"][-1]

        with TemporaryDirectory(prefix="rfad f1 storage ") as temporary:
            workspace = Path(temporary)
            fixture = f1_project()
            with ProjectService(workspace, auto_run=False) as service:
                document, snapshot = register_fixture(service, fixture)
                project_id = document["project_id"]
                state = service.journal.read()
                row = state["projects"][project_id]
                current = row["current"]
                open_data = {"path": row["path"], "open_mode": "open"}
                self.assertGreater(current["bytes"], MAX_INLINE_DOCUMENT_BYTES)
                self.assertGreater(current["bytes"], MAX_ARTIFACT_BYTES)
                self.assertEqual(snapshot["artifact"]["sha256"], current["sha256"])
                self.assertEqual(service.journal.read_document(snapshot["artifact"]), service.journal.read_document(current))
                with self.assertRaises(ProjectError):
                    service.journal.read_artifact(current)
                complete(service, "project.open", open_data, expected="failed")
                result = complete(service, "project.open", {**open_data, "result_mode": "summary"})["operation_result"]
                self.assertNotIn("document", result)
                self.assertEqual(result["revision_hash"], current["sha256"])
                read_back = service.repository.load(row)
                read_back["metadata"]["name"] = "저장 원문과 다른 반환값"
                self.assertEqual(service.repository.load(row)["metadata"], fixture["metadata"])
                path = workspace / current["uri"]
                raw = path.read_bytes()
                try:
                    path.write_bytes(raw[:-1] + b" ")
                    with self.assertRaises(ProjectError) as damaged:
                        service.repository.load(row)
                    self.assertEqual(damaged.exception.code, "E_HASH")
                finally:
                    path.write_bytes(raw)
                noncanonical = service.journal.put_document("test/large-uncanonical.json", b" " + raw)
                with self.assertRaises(ProjectError) as invalid:
                    service.repository.read(noncanonical)
                self.assertEqual(invalid.exception.code, "E_HASH")
                edited = complete(service, "project.save", {"expected_revision": document["revision_id"]}, project_id)
                self.assertEqual(edited["operation_result"]["artifact"], current)
            with ProjectService(workspace, auto_run=False) as service:
                item = service.journal.read()["projects"][project_id]
                self.assertEqual(item["saved"], current)
                self.assertEqual(service.repository.load(item), fixture)

    def test_expression_graph_accepts_1000_chain_and_detects_deep_cycle(self):
        """! @brief 전체 크기의 참조 사슬을 반복 탐색하고 마지막 순환에서 거절한다."""
        parameters = {}
        for index in range(MAX_PARAMETERS):
            key = identity(index + 1)
            row = {"id": key, "name": f"p{index}", "quantity": quantity(2, "mm")}
            if index + 1 < MAX_PARAMETERS:
                row["quantity"] = quantity(0, "mm")
                row["expression"] = expression_record("next_value", {"next_value": identity(index + 2)})
            parameters[key] = row
        self.assertEqual(len(evaluate_parameters(parameters, update=True)), MAX_PARAMETERS - 1)
        self.assertEqual(evaluate_parameters(parameters), [])
        parameters[identity(MAX_PARAMETERS)]["expression"] = expression_record("next_value", {"next_value": identity(1)})
        with self.assertRaises(ProjectError) as failure:
            evaluate_parameters(parameters)
        self.assertEqual(failure.exception.code, "E_EXPR_CYCLE")
