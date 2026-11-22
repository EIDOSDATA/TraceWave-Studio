"""! @brief 치수 간섭과 수동 고정, 원호 및 IFA 파일의 실제 값과 배치를 시험한다."""

from copy import deepcopy
import json
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from rfad.adapters.exchange.drawing import generate, verify
from rfad.adapters.exchange.drawing_readers import read_pdf
from rfad.application import exchange_contract
from rfad.application.exchange_runtime import ExchangeRuntime
from rfad.application.exchange_service import read
from rfad.application.projects import ProjectService
from rfad.domain import drawing_annotations, drawing_dimension_placement as placement
from rfad.domain.drawing_layout import layout
from rfad.domain.errors import ProjectError
from test_cad_worker_process import register_fixture, request, status
from test_drawing_annotations import export_data, fixture
from test_exchange_drawing import FONT, PACKAGES
from test_pcb_solver import snapshot_for


def drawing_input(snapshot, recipe, format_name):
    """! @brief 재열기 전에 저장한 실제 용지와 고정 개정에서 같은 입력을 조립한다."""
    data = export_data(snapshot, recipe, format_name)
    data["options"].update(recipe["placement"]["paper"])
    return data


def setup(kind):
    """! @brief 두 디자인의 크기와 축척을 달리해 우연히 같은 도면 좌표가 되는 경우를 피한다."""
    document, recipe = fixture(kind)
    paper = {"sheet": "A3", "orientation": "portrait", "scale": 1.5} if kind == "arc" else {
        "sheet": "A4", "orientation": "landscape", "scale": 1.25}
    recipe["placement"] = {"profile": "rfad.drawing-placement/0.1", "paper": paper, "pins": []}
    return document, recipe


def result(document, snapshot, recipe, format_name="svg"):
    """! @brief 실제 출력 입구와 같은 봉인 정보에서 용지 벡터를 얻는다."""
    data = drawing_input(snapshot, recipe, format_name)
    return exchange_contract.build_input(document, snapshot, data, str(uuid4()))


def dimension(page, key):
    """! @brief 화면 이름이나 정렬 순서가 바뀌어도 검증할 치수를 찾는다."""
    return next(row for row in page["dimension_placements"]["items"] if row["key"] == key)


def pin(recipe, item, point):
    """! @brief 표시 순서와 관계없이 원본과 뷰에 고정점을 연결한다."""
    return {"view_id": recipe["view"]["layer_id"], "source_id": item["source_id"], "key": item["key"], "point_mm": point}


class DimensionPlacementTests(unittest.TestCase):
    def test_crossing_labels_arrows_and_dimension_lines_are_rearranged(self):
        """! @brief 같은 위치에서 겹친 선·문자·화살표를 해소하고 수동 고정이 우선함을 확인한다."""
        group = {"kind": "linear", "anchors": [[50, 40], [52, 40]], "preferred": [51, 48],
                 "label": "2 mm", "title": "두 기준점의 간격", "projected": True}
        a = {**group, "source_id": str(uuid4()), "key": "first"}
        b = {**group, "source_id": str(uuid4()), "key": "second"}
        raw = placement._candidate(group, group["preferred"])
        self.assertTrue(placement._collision(raw, raw))
        bounds = [10, 10, 130, 100]
        items, report = placement.arrange([a, b], bounds, [])
        self.assertEqual(report["moved"], 1)
        self.assertEqual(report["collisions"], [])
        self.assertFalse(placement._collision(*items))
        short = next(row[1:] for row in items[0]["segments"] if row[0] == "arrow")
        self.assertLess(short[1][0], short[0][0])
        fixed = [{key: row[key] for key in ("source_id", "key")} | {"point_mm": group["preferred"]} for row in (a, b)]
        items, report = placement.arrange([a, b], bounds, fixed)
        self.assertEqual(report["pinned"], 2)
        self.assertEqual(len(report["collisions"]), 2)
        self.assertEqual([row["point_mm"] for row in items], [group["preferred"]] * 2)
        fixed[0]["point_mm"] = [2, 2]
        _, report = placement.arrange([a, b], bounds, fixed)
        self.assertEqual((report["pinned"], len(report["unavailable"])), (1, 1))

    def test_arc_ifa_automatic_and_saved_positions_keep_original_anchors(self):
        """! @brief 원호와 IFA에서 치수 배치만 저장해 재열어 같은 종이 위치와 물리값을 얻는다."""
        for kind in ("arc", "ifa"):
            with self.subTest(kind=kind), TemporaryDirectory() as folder:
                source, recipe = setup(kind)
                with ProjectService(Path(folder), auto_run=False) as service:
                    source, snapshot = register_fixture(service, source)
                    project = source["project_id"]
                    original = layout(result(source, snapshot, recipe))[0]
                    report = original["annotation_review"]["placement"]
                    self.assertGreater(report["moved"], 0)
                    self.assertEqual(report["collisions"], [])
                    x = dimension(original, "board.x")
                    wanted = [x["point_mm"][0] + 12.25, x["point_mm"][1] + 8.5]
                    recipe["placement"]["pins"].append(pin(recipe, x, wanted))
                    next_revision = service.mutate("project.apply_command", request(service, project, {
                        "command_id": str(uuid4()), "expected_revision": source["revision_id"],
                        "type": drawing_annotations.COMMAND, "payload": {"recipe": recipe}}))["new_revision"]
                    save = service.mutate("project.save", request(service, project, {"expected_revision": next_revision}))
                    self.assertTrue(service.run_next())
                    self.assertEqual(status(service, save["job_id"])["state"], "completed")
                with ProjectService(Path(folder), auto_run=False) as service:
                    loaded = service._load(service.journal.read()["projects"][project])
                    self.assertEqual(drawing_annotations.recipe(loaded), recipe)
                    context = read(service, "export.context", {"contract_version": "rfad.api/2.0",
                                   "context": {"project_id": project}, "input": {}})
                    self.assertEqual(context["drawing_annotations"]["saved"], recipe)
                    for key in ("geometry", "board", "pcb", "ports", "connections"):
                        self.assertEqual(loaded[key], source[key])
                    current = layout(result(loaded, snapshot_for(loaded), recipe))[0]
                    self.assertEqual(dimension(current, "board.x")["point_mm"], wanted)
                    self.assertTrue(dimension(current, "board.x")["pinned"])
                    self.assertEqual(current["viewports"], original["viewports"])
                    self.assertEqual([p for p in current["primitives"] if p["role"] == "geometry"],
                                     [p for p in original["primitives"] if p["role"] == "geometry"])
                    other_view = deepcopy(recipe)
                    other_view["placement"]["pins"][0]["view_id"] = "outline"
                    unpinned = layout(result(loaded, snapshot_for(loaded), other_view))[0]
                    self.assertFalse(dimension(unpinned, "board.x")["pinned"])
                    duplicate = deepcopy(recipe)
                    duplicate["placement"]["pins"] *= 2
                    with self.assertRaises(ProjectError):
                        result(loaded, snapshot_for(loaded), duplicate)

    @unittest.skipUnless(PACKAGES and FONT.is_file(), "PDF/DXF 읽기 패키지와 고정 글꼴이 필요합니다.")
    def test_pdf_dxf_receive_numeric_labels_paper_position_and_scale(self):
        """! @brief 두 형식의 실제 문자와 선, 단위·축척을 원호와 IFA의 저장 위치에 대조한다."""
        import ezdxf
        from pypdf import PdfReader, PdfWriter
        from pypdf.generic import FloatObject

        for kind, width in (("arc", 20), ("ifa", 40)):
            document, recipe = setup(kind)
            snapshot = snapshot_for(document)
            auto = layout(result(document, snapshot, recipe))[0]
            target = dimension(auto, "board.x")
            requested = [target["point_mm"][0] + 12.25, target["point_mm"][1] + 8.5]
            recipe["placement"]["pins"].append(pin(recipe, target, requested))
            expected = str(width) + " mm"
            scale = recipe["placement"]["paper"]["scale"]
            for format_name in ("pdf", "dxf"):
                with self.subTest(kind=kind, format=format_name), TemporaryDirectory() as folder:
                    data = result(document, snapshot, recipe, format_name)
                    pages = layout(data)
                    page = pages[0]
                    index = next(i for i, item in enumerate(page["primitives"])
                                 if item.get("dimension_key") == "board.x" and item.get("placement_part") == "label")
                    self.assertEqual(page["primitives"][index]["text"], expected)
                    self.assertEqual(page["primitives"][index]["position"], requested)
                    self.assertEqual(page["viewports"][0]["transform"]["scale"], scale)
                    self.assertIn("축척 " + format(scale, ".9g") + ":1", page["title_rows"][1]["value"])
                    bar_index = next(i for i, item in enumerate(page["primitives"]) if item.get("start") == [16, 48])
                    bar = page["primitives"][bar_index]
                    self.assertAlmostEqual(math.dist(bar["start"], bar["end"]), 50 * scale)
                    output = Path(folder)
                    manifest = generate(data, output, font_path=FONT)
                    self.assertEqual(verify(data, output, manifest)["annotation_review"]["placement"]["pinned"], 1)
                    if format_name == "dxf":
                        drawing = ezdxf.readfile(output / "drawing-01.dxf")
                        texts = {entity.get_xdata("TRACEWAVE")[0].value: entity for entity in drawing.modelspace().query("TEXT")}
                        self.assertEqual(texts[index].dxf.text, expected)
                        self.assertEqual(list(texts[index].dxf.align_point)[:2], requested)
                        lines = {entity.get_xdata("TRACEWAVE")[0].value: entity for entity in drawing.modelspace().query("LINE")}
                        self.assertAlmostEqual(lines[bar_index].dxf.start.distance(lines[bar_index].dxf.end), 50 * scale)
                        continue
                    with (output / "drawing.pdf").open("rb") as stream:
                        writer = PdfWriter(clone_from=PdfReader(stream, strict=True))
                        sheet = writer.pages[0]
                        content = sheet.get_contents()
                        active = None
                        for operands, operator in content.operations:
                            if operator == b"BDC":
                                active = int(operands[1]["/Id"])
                            if operator == b"Tm" and active == index:
                                operands[4] = FloatObject(float(operands[4]) + 1)
                            if operator == b"EMC":
                                active = None
                        sheet.replace_contents(content)
                        with (output / "moved-x.pdf").open("wb") as changed:
                            writer.write(changed)
                    with self.assertRaisesRegex(ProjectError, "X 위치"):
                        read_pdf(output / "moved-x.pdf", pages)

    @unittest.skipUnless(os.environ.get("RFAD_EXCHANGE_PYTHON"), "Windows 출력 worker 실행 환경을 지정합니다.")
    def test_windows_worker_seals_placed_dimensions(self):
        """! @brief 두 고정 스냅샷의 실제 PDF와 DXF를 Windows 출력 worker에서 발행한다."""
        with TemporaryDirectory() as folder:
            runtime = ExchangeRuntime(Path(os.environ["RFAD_EXCHANGE_PYTHON"]))
            for kind, format_name in (("arc", "pdf"), ("ifa", "dxf")):
                with self.subTest(kind=kind):
                    source, recipe = setup(kind)
                    workspace = Path(folder) / kind
                    with ProjectService(workspace, auto_run=False, exchange_runtime=runtime) as owned:
                        source, snapshot = register_fixture(owned, source)
                        project = source["project_id"]
                        page = layout(result(source, snapshot, recipe))[0]
                        target = dimension(page, "board.x")
                        moved = [target["point_mm"][0] + 12.25, target["point_mm"][1] + 8.5]
                        recipe["placement"]["pins"].append(pin(recipe, target, moved))
                        data = drawing_input(snapshot, recipe, format_name)
                        task = owned.mutate("export.preview", request(owned, project, data))
                        self.assertTrue(owned.run_next())
                        preview = status(owned, task["job_id"])["events"][-1]["operation_result"]
                        build = owned.mutate("export.build", request(owned, project, {**data, "review_hash": preview["review_hash"]}))
                        self.assertTrue(owned.exchange.run_next())
                        output = read(owned, "export.get", {"contract_version": "rfad.api/2.0",
                                      "context": {"project_id": project}, "input": {"job_id": build["job_id"]}})
                        self.assertEqual(output["state"], "completed", output.get("issues"))
                        self.assertEqual(output["report"]["annotation_review"], preview["annotation_review"])
                        reference = next(row for row in output["result"]["artifacts"] if row["uri"].endswith("/sidecar.json"))
                        sidecar = json.loads(owned.journal.read_artifact(reference))
                        self.assertEqual(sidecar["options"]["annotations"]["placement"]["pins"][0]["point_mm"], moved)
