"""! @brief 원호와 IFA 도면의 참조 주석, 원본 보존 및 파일 재열기를 검사한다."""

from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.adapters.exchange.drawing import generate, verify
from rfad.application import exchange_contract
from rfad.application.exchange_runtime import ExchangeRuntime
from rfad.application.exchange_service import read
from rfad.application.pcb_solver import build_pcb_plan
from rfad.application.projects import ProjectService
from rfad.domain import drawing_annotations as model
from rfad.domain.drawing_layout import layout
from rfad.domain.errors import ProjectError
from test_cad_worker_process import register_fixture, request, status
from test_exchange_drawing import FONT, PACKAGES
from test_pcb_ifa import IFA_SETTINGS
from test_pcb_solver import SETTINGS, runtime_identity, snapshot_for
from test_sketch_constraints import sketch_fixture


def fixture(kind):
    """! @brief 기존 구동 급전 치수와 실제 홀이 있는 검증용 두 프로젝트를 준비한다."""
    document, _ = sketch_fixture(kind)
    layer = next(row["layer_id"] for row in document["geometry"]
                 if row["id"] == document["ports"][0]["positive_geometry_id"])
    view = {"kind": "layer", "layer_id": layer}
    catalog = model.catalog(document)
    datum = next(row for row in catalog["datums"] if row["name"] == "기준 홀 왼쪽")
    keys = {"arc.radius", "smart.distance", "line.length"}
    references = [{key: row[key] for key in ("source_id", "key")} for row in catalog["model_dimensions"]
                  if layer in row["views"] and row["key"] in keys]
    recipe = {"view": view, "datum": {"kind": "hole", "id": datum["id"]},
              "style": "baseline" if kind == "arc" else "ordinate", "categories": list(model.CATEGORIES),
              "model_dimensions": references, "hole_table": True}
    return document, recipe


def export_data(snapshot, recipe, format_name="svg"):
    """! @brief 선택 뷰와 형식이 봉인된 도면 요청을 구성한다."""
    return {"snapshot": {key: snapshot[key] for key in ("snapshot_id", "content_hash")},
            "profile": exchange_contract.PROFILE, "format": format_name,
            "options": {"mode": "drawing", "sheet": "A4", "orientation": "landscape", "scale": 1,
                        "views": [recipe["view"]], "dimensions": True, "notes": True, "annotations": recipe}}


class DrawingAnnotationTests(unittest.TestCase):
    def test_reference_dimensions_reports_and_three_styles(self):
        """! @brief 세 방식의 실제 값, 중복 병합과 미정/누락을 기하와 구분한다."""
        for kind in ("arc", "ifa"):
            with self.subTest(kind=kind):
                doc, recipe = fixture(kind)
                snapshot = snapshot_for(doc)
                data = export_data(snapshot, recipe)
                value = exchange_contract.build_input(doc, snapshot, data, str(uuid4()))
                first, table = layout(value)
                summary = first["annotation_review"]
                rows = first["viewports"][0]["dimensions"]
                self.assertEqual(summary["hole_count"], 2)
                self.assertEqual(summary["missing"], [])
                self.assertEqual(len(summary["duplicates"]), 2 if kind == "arc" else 1)
                radius = [row["value"] for row in rows if row["dimension_key"] == "arc.radius"]
                self.assertEqual(radius, [2] if kind == "arc" else [])
                gap = next(row for row in rows if row["dimension_key"] == "feed.gap")
                self.assertAlmostEqual(gap["value"], 2)
                self.assertEqual(gap["origins"][1]["mode"], "driving")
                self.assertEqual([row["value"] for row in rows if row["dimension_key"] == "hole.center"],
                                 [[0, 0], [6, 0]])
                labels = [item["text"] for item in table["primitives"] if item["kind"] == "text"]
                self.assertTrue({"홀 표", "H1", "H2", "1.2", "비도금", "미정"} <= set(labels))
                self.assertEqual([item["title"] for item in summary["not_applicable"]], [] if kind == "arc" else ["원호 반경"])
                unannotated = deepcopy(value)
                del unannotated["options"]["annotations"]
                self.assertEqual([r for r in first["primitives"] if r["role"] == "geometry"],
                                 [r for r in layout(unannotated)[0]["primitives"] if r["role"] == "geometry"])

                alternate = value["options"]["annotations"]
                alternate["datum"] = {"kind": "board_origin", "id": None}
                alternate["style"] = "chain"
                chain = layout(value)[0]["viewports"][0]["dimensions"]
                self.assertEqual([row["value"] for row in chain if row["dimension_key"] == "hole.center"][1], [6, 0])
                alternate["style"] = "baseline"
                baseline = layout(value)[0]["viewports"][0]["dimensions"]
                self.assertNotEqual([row["value"] for row in baseline if row["dimension_key"] == "hole.center"][1], [6, 0])

                alternate["datum"] = {"kind": "hole", "id": str(uuid4())}
                alternate["model_dimensions"].append({"source_id": str(uuid4()), "key": "line.length"})
                value["projection"]["source_semantics"]["ports"][0].pop("excitation_box")
                incomplete = layout(value)[0]["annotation_review"]
                self.assertGreaterEqual(len(incomplete["missing"]), 3)

    def test_settings_save_reopen_snapshot_undo_and_solver(self):
        """! @brief 저장은 설정 개정만 바꾸며 모든 도체·급전과 동일 해석 형상을 보존한다."""
        for kind, settings in (("arc", SETTINGS), ("ifa", IFA_SETTINGS)):
            with self.subTest(kind=kind), TemporaryDirectory() as path:
                source, recipe = fixture(kind)
                with ProjectService(Path(path), auto_run=False) as service:
                    source, snapshot = register_fixture(service, source)
                    project = source["project_id"]

                    def current():
                        """! @brief 영속 개정에서 모델과 치수 설정을 읽는다."""
                        return service._load(service.journal.read()["projects"][project])

                    response = service.mutate("project.apply_command", request(service, project, {
                        "expected_revision": source["revision_id"], "command_id": str(uuid4()),
                        "type": model.COMMAND, "payload": {"recipe": recipe}}))
                    self.assertEqual(response["invalidation_set"], ["revision", "exports"])
                    for operation, expected in (("project.undo", None), ("project.redo", recipe)):
                        service.mutate(operation, request(service, project, {
                            "command_id": str(uuid4()), "expected_revision": current()["revision_id"]}))
                        self.assertEqual(model.recipe(current()), expected)
                    save = service.mutate("project.save", request(service, project, {"expected_revision": current()["revision_id"]}))
                    self.assertTrue(service.run_next())
                    self.assertEqual(status(service, save["job_id"])["state"], "completed")
                    self.assertEqual(json.loads(service.journal.read_artifact(snapshot["artifact"])), source)
                with ProjectService(Path(path), auto_run=False) as service:
                    reopened = service._load(service.journal.read()["projects"][project])
                    self.assertEqual(model.recipe(reopened), recipe)
                    for key in ("geometry", "board", "pcb", "stackup", "ports", "connections"):
                        self.assertEqual(reopened[key], source[key])
                    self.assertEqual({key: value for key, value in reopened["extensions"].items() if key != model.KEY},
                                     source["extensions"])
                    expected = build_pcb_plan(source, snapshot_for(source), runtime_identity(), settings)
                    actual = build_pcb_plan(reopened, snapshot_for(reopened), runtime_identity(), settings)
                    self.assertEqual(actual["case"], expected["case"])
                    data = export_data(snapshot, recipe)
                    catalog = read(service, "export.context", {"contract_version": "rfad.api/2.0",
                                   "context": {"project_id": project}, "input": {"snapshot": data["snapshot"]}})
                    self.assertEqual(catalog["drawing_annotations"]["saved"], recipe)
                    self.assertEqual(catalog["source_revision_id"], source["revision_id"])
                    preview = service.mutate("export.preview", request(service, project, data))
                    self.assertTrue(service.run_next())
                    result = status(service, preview["job_id"])["events"][-1]["operation_result"]
                    self.assertEqual(result["annotation_review"]["missing"], [])
                    self.assertEqual(result["annotation_review"]["hole_count"], 2)

    def test_reject_annotation_on_fabrication_wrong_view_and_repeated_key(self):
        """! @brief 제조 형상과 다른 뷰 요청은 입구에서 거절한다."""
        source, original = fixture("arc")
        snapshot = snapshot_for(source)
        for change in ("fabrication", "wrong_view", "duplicate"):
            with self.subTest(change=change):
                recipe = deepcopy(original)
                options = export_data(snapshot, recipe)["options"]
                if change == "fabrication":
                    options.update(mode="fabrication_geometry", dimensions=False, notes=False)
                elif change == "wrong_view":
                    options["views"] = [{"kind": "outline"}]
                else:
                    recipe["model_dimensions"].append(recipe["model_dimensions"][0])
                with self.assertRaises(ProjectError):
                    exchange_contract.options(options, "svg", source)

    @unittest.skipUnless(PACKAGES and FONT.is_file(), "PDF/SVG/DXF 재입력 패키지와 고정 글꼴이 필요합니다.")
    def test_actual_pdf_svg_dxf_annotation_and_hole_table(self):
        """! @brief 화면과 같은 주석·홀 표가 세 파일의 별도 reader에서 유지된다."""
        for kind in ("arc", "ifa"):
            doc, recipe = fixture(kind)
            snapshot = snapshot_for(doc)
            for format_name in ("pdf", "svg", "dxf"):
                with self.subTest(kind=kind, format=format_name), TemporaryDirectory() as folder:
                    data = exchange_contract.build_input(doc, snapshot, export_data(snapshot, recipe, format_name), str(uuid4()))
                    expected = layout(data)[0]["annotation_review"]
                    output = Path(folder)
                    result = generate(data, output, font_path=FONT)
                    self.assertEqual(verify(data, output, result)["annotation_review"], expected)
                    source = json.loads((output / "sidecar.json").read_bytes())
                    self.assertEqual(source["source_semantics"], doc)
                    self.assertEqual(source["options"]["annotations"], recipe)

    @unittest.skipUnless(os.environ.get("RFAD_EXCHANGE_PYTHON"), "별도 실제 출력 실행 환경이 필요합니다.")
    def test_sealed_windows_worker_reads_annotation_and_builds(self):
        """! @brief 봉인 worker가 새 의존 소스와 설정을 읽어 실제 도면을 발행한다."""
        with TemporaryDirectory() as folder:
            runtime = ExchangeRuntime(Path(os.environ["RFAD_EXCHANGE_PYTHON"]))
            with ProjectService(Path(folder), auto_run=False, exchange_runtime=runtime) as service:
                doc, recipe = fixture("arc")
                doc, snapshot = register_fixture(service, doc)
                project = doc["project_id"]
                data = export_data(snapshot, recipe, "pdf")
                task = service.mutate("export.preview", request(service, project, data))
                self.assertTrue(service.run_next())
                review = status(service, task["job_id"])["events"][-1]["operation_result"]
                build = service.mutate("export.build", request(service, project, {**data, "review_hash": review["review_hash"]}))
                self.assertTrue(service.exchange.run_next())
                result = read(service, "export.get", {"contract_version": "rfad.api/2.0",
                              "context": {"project_id": project}, "input": {"job_id": build["job_id"]}})
                self.assertEqual(result["state"], "completed", result.get("issues"))
                self.assertEqual(result["report"]["annotation_review"], review["annotation_review"])
