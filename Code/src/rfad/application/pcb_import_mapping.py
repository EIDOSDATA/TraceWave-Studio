"""! @brief 봉인 PCB/CAM parser 원문을 명시 층/넷 대응과 원자 typed patch로 연결한다."""
from copy import deepcopy
import math
import re
from uuid import UUID, uuid5

from rfad.application.canonical import canonical_bytes, canonical_hash
from rfad.application.project_contract import _fields
from rfad.application.pcb_exchange_projection import aperture_projection
from rfad.application.pcb_exchange_service import bounded, collection, new_record, _missing, place_footprint, record_summary, SECTIONS
from rfad.domain.design import _text
from rfad.domain.errors import ProjectError
from rfad.domain.pcb_features import PROJECT_SCHEMA, empty_pcb, fail, records, make_patch, apply_pcb_command
from rfad.domain.sweep_inputs import input_quantity
from rfad.domain.units import Quantity


class _ImportCandidate:
    """! @brief 이미 mm/world로 읽힌 원본을 명시 기존 대응으로만 편집 모델에 연결한다."""

    def __init__(self, document, parsed, record, mapping):
        self.before, self.document = document, deepcopy(document)
        self.document["schema_version"] = PROJECT_SCHEMA
        self.document.setdefault("pcb", empty_pcb())
        self.record, self.mapping = deepcopy(record), mapping
        self.record["bindings"] = []
        self.path, self.source, self.owners, self.containers = "", "", {}, set()
        _fields(mapping, {"board_id", "frame_id", "layers", "nets", "placement"})
        if document["board"] is None or mapping["board_id"] != document["board"]["id"] or mapping["frame_id"] != document["board"]["frame_id"]:
            fail("현재 기판과 기판 좌표계를 명시적으로 선택하십시오.", "mapping", "E_CONFLICT")
        self.layers = self._mapping("layers", {row["id"] for row in document["stackup"] if row["role"] == "conductor"} | {row["id"] for row in document.get("pcb", empty_pcb())["artwork_layers"]})
        self.nets = self._mapping("nets", {row["id"] for row in document["nets"]} | {None})
        if any(row["id"] == record["id"] for row in self.document["pcb"]["imports"]):
            fail("같은 수입 원문은 이미 이 프로젝트에 있습니다. 되돌리기 이력을 사용하십시오.", "import.id", "E_CONFLICT")
        self.document["pcb"]["imports"].append(self.record)
        self.parsed = parsed

    def _mapping(self, key, targets):
        """! @brief 이름 일치 추측이나 중복 대응을 허용하지 않는다."""
        rows, result = self.mapping[key], {}
        if type(rows) is not list or len(rows) > 128:
            fail("원본 대응은 최대 128개 목록이어야 합니다.", "mapping." + key)
        for row in rows:
            _fields(row, {"source", "target"})
            _text(row["source"], "mapping.source", empty=key == "nets", limit=512)
            if row["source"] in result or row["target"] not in targets:
                fail("원본 대응이 중복되거나 현재 대상이 없습니다.", "mapping." + key, "E_CONFLICT")
            result[row["source"]] = row["target"]
        return result

    def identity(self, suffix):
        """! @brief 파일 원래 ID가 없어도 고정 원문 순번에서 재현 가능한 새 ID를 만든다."""
        return str(uuid5(UUID(self.record["id"]), self.source + ":" + suffix))

    def quantity(self, value, unit="mm"):
        """! @brief 파일 값을 출처 기본값으로 보존하며 없는 제작 값은 미정으로 유지한다."""
        if value is None:
            result = _missing("angle" if unit == "deg" else "dimensionless" if unit == "1" else "length", unit)
            result["source_refs"] = [self.reference()]
            return result
        if type(value) not in (float, int):
            fail("읽은 좌표/치수는 유한 숫자여야 합니다.", self.source)
        return Quantity.from_value(value, unit, status="source_default", source_refs=(self.reference(),)).to_dict()

    def reference(self, source=None):
        """! @brief 원문 artifact를 보유한 수입 기록과 파일 객체를 함께 가리킨다."""
        return "pcb-import:" + self.record["id"] + "#" + (source or self.source)

    def point(self, value):
        """! @brief reader가 이미 적용한 배치와 좌표 반전을 반복하지 않는다."""
        if type(value) is not list or len(value) != 2:
            fail("원본 평면 좌표 두 개가 필요합니다.", self.source)
        return [self.quantity(item) for item in value]

    def layer(self, source):
        """! @brief 사용되는 모든 도체층에 명시 대응을 요구한다."""
        if source not in self.layers:
            fail("원본 도체층의 명시 대응이 필요합니다.", "mapping.layers", "E_CONFLICT")
        target = self.layers[source]
        if target not in {row["id"] for row in self.before["stackup"] if row["role"] == "conductor"}:
            fail("도체를 제조 이미지 층으로 대응할 수 없습니다.", "mapping.layers", "E_CONFLICT")
        return target

    def artwork_layer(self, source):
        """! @brief 원본 제조 이미지의 역할/면과 명시 기존 사용 층을 대조한다."""
        identity = self.layers.get(source)
        layer = next((row for row in self.document["pcb"]["artwork_layers"] if row["id"] == identity), None)
        if layer is None or layer["use_state"] != "used":
            fail("제조 개구에는 명시적으로 사용하는 기존 제조 이미지 층 대응이 필요합니다.", "mapping.layers", "E_CONFLICT")
        if source in ("F.Mask", "B.Mask", "F.Paste", "B.Paste"):
            role, side = ("solder_mask" if source.endswith("Mask") else "solder_paste"), ("top" if source.startswith("F.") else "bottom")
            if layer["role"] != role or layer["side"] != side:
                fail("제조 이미지 역할/면 대응이 원문과 다릅니다.", "mapping.layers", "E_CONFLICT")
        return layer

    def net(self, source):
        """! @brief 미연결도 null 대응을 명시하고 이름으로 추정하지 않는다."""
        if source not in self.nets:
            fail("원본 넷의 명시 대응이 필요합니다. 미연결은 null을 지정하십시오.", "mapping.nets", "E_CONFLICT")
        return self.nets[source]

    def append(self, section, row, suffix="", owner=None, *, native_source=None):
        """! @brief 수입 origin과 world 객체 소유권을 한 후보 안에서 함께 고정한다."""
        key = "geometry" if section == "geometry" else collection(section)
        rows = self.document["geometry"] if key == "geometry" else records(self.document, key)
        row["id"] = self.identity(section + suffix)
        base = row.get("name") or ("수입 도체" if section == "geometry" else "수입 " + SECTIONS[section])
        names = {value.get("name") for value in rows}
        name, number = base, 1
        while name in names:
            name = base + f" {number:02d}"
            number += 1
        row["name"] = name
        source = native_source or self.source
        if section != "geometry":
            row["origin"] = {"import_id": self.record["id"], "source_object_id": source}
            row["source_refs"] = [self.reference(source)]
        elif native_source is not None:
            row["source_ref"] = self.reference(source)
        rows.append(row)
        self.record["bindings"].append({"source_object_id": source, "collection": key, "id": row["id"]})
        if owner is not None:
            if owner in self.containers:
                self.record["bindings"].append({"source_object_id": self.path + ":" + owner, "collection": key, "id": row["id"]})
                return row
            if owner not in self.owners:
                fail("풋프린트 소유 원문을 찾을 수 없습니다.", self.source, "E_CONFLICT")
            self.owners[owner]["members"].append({"collection": key.removeprefix("pcb."), "id": row["id"]})
        return row

    def geometry(self, kind, layer, net):
        """! @brief 재료를 추정하지 않는 수입 도체의 공통 필드를 만든다."""
        return {"kind": kind, "role": "conductor", "frame_id": self.mapping["frame_id"], "layer_id": layer,
                "net_id": net, "material_ref": None, "source_ref": self.reference(), "include_in_em": True, "include_in_export": True}

    def hole(self, shape, plating, pads=(), net=None, owner=None, suffix="", *, native_source=None):
        """! @brief 완성 구멍과 실제 도금 상태만 보존하고 공구/도금 두께를 추정하지 않는다."""
        row = new_record(self.document, "hole")
        row.update(shape=shape, frame_id=self.mapping["frame_id"], tool_diameter=self.quantity(None))
        row["plating"].update(state=plating, thickness=self.quantity(None), pad_ids=list(pads), net_id=net if plating == "plated" else None)
        return self.append("hole", row, suffix, owner, native_source=native_source)

    def board(self, edges):
        """! @brief 기존 외곽을 대조하고 분리된 명시 내부 폐곡선만 새 절삭으로 보존한다."""
        import math
        from rfad.application.pcb_exchange_projection import scalar, point, shape_projection
        from rfad.domain.curve_boolean import _intersections, _point
        from rfad.domain.drawing_layout import mechanical_loops, _inside
        from rfad.domain.planar import validate_region
        if len(edges) > 1088:
            fail("기판 경계가 유한 수입 상한을 초과합니다.", "edges", "E_RESOURCE")
        shapes, lines = [], []
        for edge in edges:
            if edge["kind"] == "circle":
                shapes.append({"kind": "circle", "center_mm": edge["center_mm"], "diameter_mm": 2 * edge["radius_mm"]})
            elif edge["kind"] == "rect":
                shapes.append({"kind": "polygon", "outer_mm": edge["outer_mm"], "holes_mm": []})
            elif edge["kind"] == "line":
                lines.append((edge["start_mm"], edge["end_mm"]))
            else:
                fail("원/직선 폐곡선 이외의 기판 경계는 현재 수입하지 않습니다.", "edges", "E_UNSUPPORTED")
        while lines:
            start, end = lines.pop(0)
            vertices = [start]
            while end != start:
                vertices.append(end)
                matches = [(index, b if a == end else a) for index, (a, b) in enumerate(lines) if a == end or b == end]
                if len(matches) != 1 or len(vertices) > 64:
                    fail("열렸거나 분기하는 기판 경계를 자동 연결하지 않습니다.", "edges", "E_UNSUPPORTED")
                index, end = matches[0]
                lines.pop(index)
            shapes.append({"kind": "polygon", "outer_mm": vertices, "holes_mm": []})
        if not shapes or len(shapes) > 17:
            fail("기존 외곽 하나와 내부 절삭 최대 16개만 수입합니다.", "edges", "E_RESOURCE")
        for shape in shapes:
            if shape["kind"] == "polygon":
                validate_region(shape["outer_mm"], [], "edges")
            elif not math.isfinite(shape["diameter_mm"]) or shape["diameter_mm"] <= 0:
                fail("기판 원 경계의 지름이 유효하지 않습니다.", "edges")
        outline = self.before["board"]["outline"]
        if outline["kind"] == "circle":
            expected = {"kind": "circle", "center_mm": point(self.before, outline["center"]), "diameter_mm": 2 * scalar(self.before, outline["radius"])}
        else:
            if outline["kind"] == "rectangle":
                width, height = (scalar(self.before, outline[key]) for key in ("width", "height"))
                vertices = [[0, 0], [width, 0], [width, height], [0, height]]
            else:
                vertices = [point(self.before, value) for value in outline["outer"]]
            expected = {"kind": "polygon", "outer_mm": vertices, "holes_mm": []}
        def matches(shape):
            """! @brief 파일 좌표 정밀도 1 nm 안에서 방향/시작 꼭짓점만 무시한다."""
            if shape["kind"] != expected["kind"]:
                return False
            if shape["kind"] == "circle":
                return math.dist(shape["center_mm"], expected["center_mm"]) <= 1e-6 and abs(shape["diameter_mm"] - expected["diameter_mm"]) <= 2e-6
            actual, target = shape["outer_mm"], expected["outer_mm"]
            if len(actual) != len(target):
                return False
            return any(all(math.dist(actual[i], target[(offset + direction * i) % len(target)]) <= 1e-6 for i in range(len(actual))) for offset in range(len(target)) for direction in (-1, 1))
        indexes = [index for index, shape in enumerate(shapes) if matches(shape)]
        if len(indexes) != 1:
            fail("원본 Edge.Cuts와 현재 기판 외곽이 다릅니다. 기판을 묵시 교체하지 않습니다.", "mapping.board_id", "E_CONFLICT")
        shapes.pop(indexes[0])
        outer = mechanical_loops(expected)
        existing = [mechanical_loops(shape_projection(self.before, row["shape"])) for row in self.before["board"].get("cutouts", [])]
        for index, shape in enumerate(shapes):
            loop = mechanical_loops(shape)
            def touches(first, second):
                """! @brief 접점/겹침은 순수 해석형 교점 검사로 명시 차단한다."""
                return any(_intersections(a, b) for aa in first for a in aa for bb in second for b in bb)
            if touches(loop, outer) or not _inside(_point(loop[0][0], 0), outer):
                fail("내부 절삭은 기존 기판 안에 완전히 분리되어 있어야 합니다.", "edges", "E_UNSUPPORTED")
            for other in existing:
                if touches(loop, other) or _inside(_point(loop[0][0], 0), other) or _inside(_point(other[0][0], 0), loop):
                    fail("기존/새 절삭의 중복, 접점, 교차 또는 중첩은 묵시 병합하지 않습니다.", "edges", "E_CONFLICT")
            existing.append(loop)
            self.source = self.path + ":edge-cutout:" + str(index)
            row = new_record(self.document, "cutout", shape["kind"])
            row["shape"] = {"kind": "circle", "center": self.point(shape["center_mm"]), "diameter": self.quantity(shape["diameter_mm"])} if shape["kind"] == "circle" else {"kind": "polygon", "outer": [self.point(value) for value in shape["outer_mm"]], "holes": []}
            self.document["board"].setdefault("cutouts", [])
            self.append("cutout", row)
        self.record["bindings"].append({"source_object_id": self.path + ":profile", "collection": "board", "id": self.before["board"]["id"]})

    def kicad(self, data):
        """! @brief KiCad 원래 world 도체/풋프린트와 완성 구멍을 한 번만 변환한다."""
        import math
        if data["format"] == "kicad_pcb":
            self.board(data["edges"])
            if self.mapping["placement"] is not None:
                fail("기판 파일의 world 좌표를 다시 배치할 수 없습니다.", "mapping.placement", "E_UNSUPPORTED")
        elif data["edges"]:
            fail("풋프린트의 Edge.Cuts를 기판 절삭으로 추정하지 않습니다.", "edges", "E_UNSUPPORTED")
        self.owners, self.containers = {}, set()
        for index, item in enumerate(data["footprints"]):
            source_id = item["id"] or "footprint:" + str(index)
            self.source = self.path + ":" + source_id
            if source_id in self.owners or source_id in self.containers:
                fail("중복된 풋프린트 원본 ID입니다.", self.source, "E_CONFLICT")
            if item.get("technical_container") is True:
                self.containers.add(source_id)
                continue
            row = new_record(self.document, "footprint")
            row.update(name=item["properties"].get("Reference") or item["library_id"], reference=item["properties"].get("Reference"), value=item["properties"].get("Value"), library_id=item["library_id"], edit_state="original")
            place = item["placement"]
            row["placement"] = {"origin": self.point(place["origin_mm"]), "rotation": self.quantity(place["rotation_deg"], "deg"), "side": place["side"]}
            self.owners[source_id] = self.append("footprint", row)
        for index, item in enumerate(data["shapes"]):
            self.source = self.path + ":" + (item["id"] or "shape:" + str(index))
            kind, owner = item["kind"], item.get("footprint_id")
            net = self.net(str(item.get("net_code", 0)))
            if kind in ("line_path", "arc_path", "planar_region"):
                row = self.geometry(kind, self.layer(item["layer"]), net)
                if kind == "line_path":
                    row.update(start=self.point(item["start_mm"]), end=self.point(item["end_mm"]), width=self.quantity(item["width_mm"]))
                elif kind == "arc_path":
                    row.update(center=self.point(item["center_mm"]), radius=self.quantity(item["radius_mm"]), start_angle=self.quantity(item["start_angle_deg"], "deg"), sweep_angle=self.quantity(item["sweep_angle_deg"], "deg"), width=self.quantity(item["width_mm"]))
                else:
                    fill = item.get("fill_settings")
                    if fill is not None and (fill["connect_pads"] != "yes" or fill["clearance_mm"] not in (None, 0) or fill["thermal_gap_mm"] not in (None, 0)):
                        fail("열연결/간격 재계산이 필요한 zone은 원본 경계만 도체로 추정하지 않습니다.", self.source, "E_UNSUPPORTED")
                    row.update(outer=[self.point(value) for value in item["outer_mm"]], holes=[[self.point(value) for value in loop] for loop in item["holes_mm"]])
                self.append("geometry", row, owner=owner)
            elif kind in ("pad", "via"):
                is_via = kind == "via"
                drill = {"shape": "circle", "size_mm": [item["finished_hole_diameter_mm"]] * 2, "offset_mm": [0, 0], "plating": "plated"} if is_via else item["drill"]
                pad_type = "thru_hole" if is_via else item["pad_type"]
                layer_names = item["layers"]
                if "*.Cu" in layer_names:
                    layer_names = [row["name"] for row in data["layers"] if row["name"].endswith(".Cu")]
                    if not layer_names:
                        layer_names = [name for name in self.layers if name.endswith(".Cu")]
                layer_names = [name for name in layer_names if name.endswith(".Cu")]
                mapped = [] if pad_type == "np_thru_hole" else [self.layer(name) for name in layer_names]
                if len(set(mapped)) != len(mapped):
                    fail("서로 다른 원본 도체층을 같은 층으로 합칠 수 없습니다.", "mapping.layers", "E_CONFLICT")
                ordered = [row["id"] for row in sorted(self.before["stackup"], key=lambda value: value["order"]) if row["role"] == "conductor"]
                if is_via and len(mapped) == 2 and len(ordered) >= 2 and set(mapped) == {ordered[0], ordered[-1]}:
                    mapped = ordered
                pads = []
                if pad_type != "np_thru_hole":
                    pad_shape = "circle" if is_via else item["pad_shape"]
                    if pad_shape not in ("circle", "rect"):
                        fail("현재 패드 모델은 수입 타원/사용자 형상을 손실 없이 표현하지 못합니다.", self.source, "E_UNSUPPORTED")
                    for index2, layer in enumerate(mapped):
                        row = self.geometry("pad", layer, net)
                        size = [item["size_mm"]] * 2 if is_via else item["size_mm"]
                        row.update(pad_shape="circle" if pad_shape == "circle" else "rectangle", center=self.point(item["center_mm"]), size=self.point(size), rotation=self.quantity(0 if is_via else item["rotation_deg"], "deg"))
                        pads.append(self.append("geometry", row, str(index2), owner)["id"])
                    if not pads:
                        fail("실제 도체층이 없는 패드를 도체로 추정하지 않습니다.", self.source, "E_UNSUPPORTED")
                hole = None
                if drill is not None:
                    if any(value != 0 for value in drill["offset_mm"]):
                        fail("편심 drill의 좌표 의미는 현재 수입 profile에서 지원하지 않습니다.", self.source, "E_UNSUPPORTED")
                    if is_via or pad_type == "thru_hole":
                        if set(mapped) != set(ordered):
                            fail("현재 새 기계 홀은 전체 적층 관통만 지원합니다.", self.source, "E_UNSUPPORTED")
                    shape = {"kind": drill["shape"], "center": self.point(item["center_mm"])}
                    if drill["shape"] == "circle":
                        shape["diameter"] = self.quantity(drill["size_mm"][0])
                    else:
                        length, width = drill["size_mm"]
                        angle = item.get("rotation_deg", 0)
                        if width > length:
                            length, width, angle = width, length, angle + 90
                        shape.update(finished_length=self.quantity(length), finished_width=self.quantity(width), rotation=self.quantity(angle, "deg"))
                    hole = self.hole(shape, drill["plating"], pads, net, owner)
                if owner in self.owners and item.get("number"):
                    if not pads:
                        fail("패드가 없는 비도금 홀의 핀 번호를 전기 핀으로 추정하지 않습니다.", self.source, "E_UNSUPPORTED")
                    pin = next((row for row in self.owners[owner]["pins"] if row["number"] == item["number"]), None)
                    if pin is None:
                        self.owners[owner]["pins"].append({"number": item["number"], "pad_ids": pads, "hole_id": None if hole is None else hole["id"]})
                    elif hole is not None or pin["hole_id"] is not None:
                        fail("같은 핀의 여러 관통 홀 관계는 현재 수입 profile에서 지원하지 않습니다.", self.source, "E_UNSUPPORTED")
                    else:
                        pin["pad_ids"].extend(pads)
                if not is_via:
                    self.pad_artwork(item, pads, owner)
            else:
                fail("지원하지 않는 수입 도체 종류입니다.", self.source, "E_UNSUPPORTED")
        self.auxiliary(data)
        if self.mapping["placement"] is not None:
            if len(self.owners) != 1:
                fail("독립 풋프린트 하나만 명시 재배치할 수 있습니다.", "mapping.placement", "E_UNSUPPORTED")
            row = next(iter(self.owners.values()))
            place_footprint(self.document, {"id": row["id"], "placement": self.mapping["placement"]})

    def pad_artwork(self, item, pads, owner):
        """! @brief 명시 이미지 층의 패드 연관 개구를 만들되 없는 여유값/비율은 미정이다."""
        for layer_name in item["layers"]:
            if not layer_name.endswith((".Mask", ".Paste")):
                continue
            if layer_name.startswith("*."):
                fail("양면 제조 이미지의 암시 대응 대신 각 면을 명시하십시오.", self.source, "E_UNSUPPORTED")
            layer = self.artwork_layer(layer_name)
            copper = self.layer("F.Cu" if layer["side"] == "top" else "B.Cu")
            pad = next((identity for identity in pads if next(row for row in self.document["geometry"] if row["id"] == identity)["layer_id"] == copper), None)
            if pad is None:
                fail("제조 개구와 같은 면의 실제 패드가 없습니다.", self.source, "E_CONFLICT")
            row = new_record(self.document, "aperture")
            margin = item.get("solder_mask_margin" if layer["role"] == "solder_mask" else "solder_paste_margin")
            ratio = 0 if layer["role"] == "solder_mask" else item.get("solder_paste_margin_ratio")
            row.update(artwork_layer_id=layer["id"], definition={"mode": "pad_margin", "pad_id": pad, "margin": self.quantity(margin), "size_ratio": self.quantity(ratio, "1")})
            self.append("aperture", row, layer_name, owner)

    def auxiliary(self, data):
        """! @brief 명시 금지 영역과 채워진 제조 이미지만 기존 층에 손실 없이 대응한다."""
        for index, item in enumerate(data["keepouts"]):
            self.source = self.path + ":" + (item["id"] or "keepout:" + str(index))
            row = new_record(self.document, "keepout", "polygon")
            flags = item["prohibit"]
            if set(flags) - {"tracks", "vias", "pads", "copperpour", "copper_pours", "footprints"}:
                fail("지원하지 않는 금지 영역 규칙입니다.", self.source, "E_UNSUPPORTED")
            row.update(shape={"kind": "polygon", "outer": [self.point(value) for value in item["outer_mm"]], "holes": [[self.point(value) for value in loop] for loop in item["holes_mm"]]}, layer_ids=[self.layer(item["layer"])],
                       prohibit={key: flags.get("copperpour", flags.get(key, False)) if key == "copper_pours" else flags.get(key, False) for key in ("tracks", "vias", "pads", "copper_pours", "footprints")})
            self.append("keepout", row, owner=item.get("footprint_id"))
        for index, item in enumerate(data["artwork"]):
            self.source = self.path + ":" + (item["id"] or "artwork:" + str(index))
            if item["kind"] == "circle":
                shape = {"kind": "circle", "center": self.point(item["center_mm"]), "diameter": self.quantity(2 * item["radius_mm"])}
            elif item["kind"] in ("poly", "rect"):
                shape = {"kind": "polygon", "outer": [self.point(value) for value in item["outer_mm"]], "holes": []}
            else:
                fail("열린 선/원호 이미지를 닫힌 제조 개구로 추정하지 않습니다.", self.source, "E_UNSUPPORTED")
            owner = item.get("footprint_id")
            if item["layer"].endswith(".CrtYd"):
                if owner not in self.owners or self.owners[owner]["placement_envelope"] is not None:
                    fail("배치 외곽은 명시 풋프린트 하나의 단일 닫힌 외곽이어야 합니다.", self.source, "E_UNSUPPORTED")
                self.owners[owner]["placement_envelope"] = shape
                self.record["bindings"].append({"source_object_id": self.source, "collection": "pcb.footprints", "id": self.owners[owner]["id"]})
                continue
            if item["fill"] != "solid" or item["width_mm"] != 0:
                fail("stroke가 있는 제조 이미지의 실제 채움 영역은 현재 수입하지 않습니다.", self.source, "E_UNSUPPORTED")
            layer = self.artwork_layer(item["layer"])
            row = new_record(self.document, "aperture")
            row.update(artwork_layer_id=layer["id"], definition={"mode": "explicit_shape", "shape": shape})
            self.append("aperture", row, owner=owner)

    def cam_source(self, item):
        """! @brief 현행 순번과 새 프로젝트 ID를 유지하면서 안전한 원본 태그를 대응에 추가한다."""
        native = item.get("attributes", {}).get("TraceWaveId", [])
        if len(native) == 1 and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", native[0]):
            return self.source + ":TraceWaveId:" + native[0]
        return None

    def cam(self, data):
        """! @brief 단일 극성의 명시 해석 형상만 가져오며 곡선 polygon 근사는 만들지 않는다."""
        import math
        if self.mapping["placement"] is not None:
            fail("CAM world 좌표를 임의 재배치하지 않습니다.", "mapping.placement", "E_UNSUPPORTED")
        if data["schema"] == "rfad.gerber-job-read/0.1":
            return
        if data["schema"] == "rfad.xnc-read/0.1":
            for index, item in enumerate(data["holes"]):
                self.source = self.path + ":hole:" + str(index)
                if item["kind"] == "circle":
                    shape = {"kind": "circle", "center": self.point(item["center_mm"]), "diameter": self.quantity(item["finished_diameter_mm"])}
                else:
                    start, end, width = item["start_mm"], item["end_mm"], item["finished_width_mm"]
                    shape = {"kind": "capsule", "center": self.point([(start[i] + end[i]) / 2 for i in range(2)]), "finished_length": self.quantity(math.dist(start, end) + width), "finished_width": self.quantity(width), "rotation": self.quantity(math.degrees(math.atan2(end[1] - start[1], end[0] - start[0])), "deg")}
                self.hole(shape, data["plating"], native_source=self.cam_source(item))
            return
        if data["schema"] != "rfad.gerber-read/0.1":
            fail("지원하지 않는 parser 자료입니다.", "schema", "E_UNSUPPORTED")
        function = data["file_attributes"].get(".FileFunction", [])
        if not function:
            fail("Gerber의 파일 역할이 명시되어야 합니다.", self.path, "E_UNSUPPORTED")
        expected_polarity = "Negative" if function[0] == "Soldermask" else "Positive"
        if data["file_attributes"].get(".FilePolarity") != [expected_polarity]:
            fail("Gerber의 파일 역할에 대응하는 이미지 극성이 명시되어야 합니다.", self.path, "E_UNSUPPORTED")
        if function[0] == "Profile":
            edges, arcs = [], []
            for item in data["objects"]:
                if item["kind"] != "stroke" or item["polarity"] != "dark":
                    fail("기판 Profile은 닫힌 해석형 외곽만 대조합니다.", self.path, "E_UNSUPPORTED")
                edge = item["edge"]
                if edge["kind"] == "line":
                    if arcs:
                        fail("원/직선이 섞인 절삭은 현재 수입하지 않습니다.", self.path, "E_UNSUPPORTED")
                    edges.append({"kind": "line", "start_mm": edge["start"], "end_mm": edge["end"]})
                else:
                    if arcs and (math.dist(edge["center"], arcs[0]["center"]) > 1e-6 or abs(edge["radius"] - arcs[0]["radius"]) > 1e-6 or math.dist(arcs[-1]["end"], edge["start"]) > 1e-6 or edge["sweep_deg"] * arcs[0]["sweep_deg"] <= 0):
                        fail("유일한 동일 원을 이루지 않는 Profile 원호입니다.", self.path, "E_UNSUPPORTED")
                    arcs.append(edge)
                    sweep = sum(part["sweep_deg"] for part in arcs)
                    if abs(sweep) > 360 + 1e-8:
                        fail("중복 회전하는 원 경계는 수입하지 않습니다.", self.path, "E_UNSUPPORTED")
                    if abs(abs(sweep) - 360) <= 1e-8 and math.dist(arcs[-1]["end"], arcs[0]["start"]) <= 1e-6:
                        edges.append({"kind": "circle", "center_mm": arcs[0]["center"], "radius_mm": arcs[0]["radius"]})
                        arcs = []
            if arcs:
                fail("열린/복합 Profile 원호를 원형 절삭으로 추정하지 않습니다.", self.path, "E_UNSUPPORTED")
            self.board(edges)
            return
        artwork = function[0] in ("Soldermask", "Paste")
        if function[0] not in ("Copper", "Soldermask", "Paste"):
            fail("지원하지 않는 Gerber 파일 역할입니다.", self.path, "E_UNSUPPORTED")
        image_layer = self.artwork_layer(self.path) if artwork else None
        if artwork:
            role = "solder_mask" if function[0] == "Soldermask" else "solder_paste"
            side = "top" if "Top" in function else "bottom" if "Bot" in function or "Bottom" in function else None
            if image_layer["role"] != role or image_layer["side"] != side:
                fail("Gerber 제조 역할/면이 명시 대상과 다릅니다.", self.path, "E_CONFLICT")
        layer = None if artwork else self.layer(self.path)
        for index, item in enumerate(data["objects"]):
            self.source = self.path + ":object:" + str(index)
            if item["polarity"] != "dark":
                fail("clear 극성 합성은 현재 편집 모델로 조용히 생략할 수 없습니다.", self.source, "E_UNSUPPORTED")
            names = item["attributes"].get(".N") or [""]
            net = None if artwork else self.net(names[0])
            kind = item["kind"]
            if artwork:
                if kind == "flash":
                    aperture = item["aperture"]
                    shape = {"kind": "circle", "center": self.point(item["center_mm"]), "diameter": self.quantity(aperture["size_mm"][0])} if aperture["kind"] == "C" else {"kind": "rectangle", "center": self.point(item["center_mm"]), "size": self.point(aperture["size_mm"]), "rotation": self.quantity(0, "deg")}
                    if aperture["kind"] == "O":
                        a, b = aperture["size_mm"]
                        shape = {"kind": "capsule", "center": self.point(item["center_mm"]), "finished_length": self.quantity(max(a,b)), "finished_width": self.quantity(min(a,b)), "rotation": self.quantity(0 if a>b else 90, "deg")} if a != b else {"kind": "circle", "center": self.point(item["center_mm"]), "diameter": self.quantity(a)}
                elif kind == "region" and all(edge["kind"] == "line" for loop in item["loops"] for edge in loop):
                    loops = [[self.point(edge["start"]) for edge in loop] for loop in item["loops"]]
                    shape = {"kind": "polygon", "outer": loops[0], "holes": loops[1:]}
                elif kind == "region" and len(item["loops"]) == 1 and item["loops"][0] and all(edge["kind"] == "arc" for edge in item["loops"][0]):
                    arcs = item["loops"][0]
                    first = arcs[0]
                    if abs(abs(sum(edge["sweep_deg"] for edge in arcs)) - 360) > 1e-8 or any(math.dist(edge["center"], first["center"]) > 1e-6 or abs(edge["radius"] - first["radius"]) > 1e-6 or edge["sweep_deg"] * first["sweep_deg"] <= 0 or math.dist(edge["end"], arcs[(index + 1) % len(arcs)]["start"]) > 1e-6 for index, edge in enumerate(arcs)):
                        fail("제조 이미지 원호를 단일 원으로 확정할 수 없습니다.", self.source, "E_UNSUPPORTED")
                    shape = {"kind": "circle", "center": self.point(first["center"]), "diameter": self.quantity(2 * first["radius"])}
                else:
                    fail("제조 이미지는 명시 flash와 직선 닫힌 region만 수입합니다.", self.source, "E_UNSUPPORTED")
                row = new_record(self.document, "aperture")
                row.update(artwork_layer_id=image_layer["id"], definition={"mode": "explicit_shape", "shape": shape})
                self.append("aperture", row, native_source=self.cam_source(item))
                continue
            if kind == "region":
                if any(edge["kind"] != "line" for loop in item["loops"] for edge in loop):
                    fail("곡선 Gerber region을 다각형으로 근사하지 않습니다.", self.source, "E_UNSUPPORTED")
                row = self.geometry("planar_region", layer, net)
                loops = [[self.point(edge["start"]) for edge in loop] for loop in item["loops"]]
                row.update(outer=loops[0], holes=loops[1:])
            elif kind == "stroke":
                edge = item["edge"]
                row = self.geometry("line_path" if edge["kind"] == "line" else "arc_path", layer, net)
                row["width"] = self.quantity(item["width_mm"])
                if edge["kind"] == "line":
                    row.update(start=self.point(edge["start"]), end=self.point(edge["end"]))
                else:
                    row.update(center=self.point(edge["center"]), radius=self.quantity(edge["radius"]), start_angle=self.quantity(edge["start_deg"], "deg"), sweep_angle=self.quantity(edge["sweep_deg"], "deg"))
            elif kind == "flash":
                aperture = item["aperture"]
                if aperture["kind"] == "O":
                    length, width = aperture["size_mm"]
                    center = item["center_mm"]
                    vertical = width > length
                    distance = abs(length - width) / 2
                    if distance == 0:
                        aperture = {"kind": "C", "size_mm": [length]}
                    else:
                        row = self.geometry("line_path", layer, net)
                        delta = [0, distance] if vertical else [distance, 0]
                        row.update(start=self.point([center[i] - delta[i] for i in range(2)]), end=self.point([center[i] + delta[i] for i in range(2)]), width=self.quantity(min(length, width)))
                        self.append("geometry", row, native_source=self.cam_source(item))
                        continue
                row = self.geometry("pad", layer, net)
                size = aperture["size_mm"] * 2 if aperture["kind"] == "C" else aperture["size_mm"]
                row.update(pad_shape="circle" if aperture["kind"] == "C" else "rectangle", center=self.point(item["center_mm"]), size=self.point(size), rotation=self.quantity(0, "deg"))
            else:
                fail("지원하지 않는 Gerber 도형입니다.", self.source, "E_UNSUPPORTED")
            self.append("geometry", row, native_source=self.cam_source(item))

    def vendor(self, data):
        """! @brief 출처 동박을 사용자가 지정한 평면 배치와 기존 동박층에 연결한다."""
        from rfad.application.pcb_projection import project_board
        from rfad.domain.planar import point_in_loop, _intersect
        placement = self.mapping["placement"]
        _fields(placement, {"origin", "rotation"})
        if type(placement["origin"]) is not list or len(placement["origin"]) != 2:
            fail("제조사 패턴의 배치 X/Y가 필요합니다.", "mapping.placement.origin")
        offset = [input_quantity(item, "length", "mapping.placement.origin")["value_si"] for item in placement["origin"]]
        rotation = input_quantity(placement["rotation"], "angle", "mapping.placement.rotation")["value_si"]
        if None in offset or rotation is None:
            fail("제조사 패턴의 X/Y/회전을 명시하십시오.", "mapping.placement")
        board = project_board(self.before)
        cosine, sine = math.cos(rotation), math.sin(rotation)
        anchor_x, anchor_y = data.get("placement_anchor_mm", (0.0, 0.0))
        net = self.net("")
        targets = {item["layer"]: self.layer(item["layer"]) for item in data["regions"]}
        if len(set(targets.values())) != len(targets):
            fail("공급사 원문의 서로 다른 도체층은 별도 기존 층에 대응해야 합니다.", "mapping.layers")
        def placed(point):
            """! @brief 읽은 mm 좌표의 원점을 사용자 배치에 회전·이동한다."""
            x, y = point[0] - anchor_x, point[1] - anchor_y
            return [x * cosine - y * sine + offset[0] * 1000, x * sine + y * cosine + offset[1] * 1000]
        def vertex(point):
            """! @brief 정점의 공통 원문 참조는 도형과 수입 기록에 한 번만 보존한다."""
            return [Quantity.from_value(value, "mm", status="source_default").to_dict() for value in point]
        def within(loop):
            """! @brief 보드 형식에 따라 동박 경계 전체가 내부에 위치하는지 검사한다."""
            tolerance = 1e-8
            if board["kind"] == "circle":
                return all(math.dist(p, board["center_mm"]) <= board["radius_mm"] + tolerance for p in loop)
            if board["kind"] == "rectangle":
                width, height = board["dimensions_mm"]
                return all(-tolerance <= x <= width + tolerance and -tolerance <= y <= height + tolerance for x, y in loop)
            outline = board["outer_mm"]
            return (all(point_in_loop(p, outline, include_boundary=False) for p in loop) and
                    not any(_intersect(a, b, c, d, tolerance) for a, b in zip(loop, loop[1:] + loop[:1])
                            for c, d in zip(outline, outline[1:] + outline[:1])))
        for item in data["regions"]:
            self.source = item["source_id"]
            outer = [placed(point) for point in item["outer_mm"]]
            if not within(outer):
                fail("가져올 제조사 동박이 현재 기판 외곽을 벗어납니다.", "mapping.placement", "E_GEOMETRY")
            row = self.geometry("planar_region", targets[item["layer"]], net)
            row.update(name=data["card"]["label"].split(" / ", 1)[0] + " " + item.get("label", item["layer"]),
                       outer=[vertex(point) for point in outer],
                       holes=[[vertex(placed(point)) for point in loop] for loop in item["holes_mm"]],
                       include_in_em=False)
            self.append("geometry", row)

    def manufacturing_profile(self, data):
        """! @brief 제조 데이터 외곽을 현재 보드와 확인하고 내부 절삭만 적용한다."""
        profile = data["editable_profile"]
        if self.mapping["placement"] is not None or self.layers or self.nets:
            fail("이 프로파일은 기준 외곽과 절삭을 지원합니다. 배치·층·넷의 대응을 해제하십시오.",
                 "mapping", "E_UNSUPPORTED")
        self.board([{"kind": "rect", "outer_mm": loop} for loop in [profile["outer_mm"], *profile["cutouts_mm"]]])

    def build(self):
        """! @brief 모든 파일을 하나의 원자 후보에 모으고 UUID 순서/원문 제약을 검증한다."""
        from rfad.domain.project import validate_project
        for item in self.parsed["records"]:
            self.path = item["path"]
            data = item["data"]
            if data["schema"] == "rfad.kicad-read/0.1":
                self.kicad(data)
            elif data["schema"] == "rfad.vendor-pattern-read/0.1":
                self.vendor(data)
            elif data["schema"] in {"rfad.ipc2581-read/0.1", "rfad.odbpp-read/0.1"}:
                self.manufacturing_profile(data)
            else:
                self.cam(data)
        for key in self.document["pcb"]:
            if key != "schema":
                self.document["pcb"][key].sort(key=lambda row: row["id"])
        if "cutouts" in self.document["board"]:
            self.document["board"]["cutouts"].sort(key=lambda row: row["id"])
        self.document["geometry"].sort(key=lambda row: row["id"])
        if len(self.record["bindings"]) == 0:
            fail("편집 모델로 대응한 원본 객체가 없습니다.", "records", "E_UNSUPPORTED")
        validate_project(self.document)
        for row in self.document["pcb"]["apertures"]:
            aperture_projection(self.document, row)
        if len(canonical_bytes(self.document)) > 512 * 1024:
            fail("수입 후 프로젝트 원문이 512 KiB를 초과합니다.", "document", "E_RESOURCE")
        return self.document


def _loss_message(row, prefix):
    """! @brief 업체 원문의 생략·근사 근거를 고정 보고서에 정의한 문구로 표시한다."""
    if row.get("code", "").startswith(("vendor_", "cam_", "xnc_", "ipc2581_", "odbpp_")) and row.get("message"):
        return row["message"]
    return prefix + str(row.get("code", "unknown"))


def import_candidate(document, parsed, import_record, mapping, acknowledged_losses, reason):
    """! @brief 봉인 parser 결과의 명시 대응/손실 확인을 검토 hash와 한 역명령에 연결한다."""
    from rfad.application.canvas import build_canvas_dto
    base = {"project_id": document["project_id"], "revision_id": document["revision_id"], "source_revision_id": document["revision_id"],
            "profile": "rfad.pcb-import-candidate/0.1", "operation": "import.apply", "manufacturing_verified": False, "physics_verified": False}
    losses = [{"id": canonical_hash(row), "message": _loss_message(row, "원문에 보존되지만 편집 모델에서 지원하지 않는 항목: "), "original": deepcopy(row)} for row in parsed.get("losses", [])]
    try:
        if parsed.get("format") in {"ipc2581_revc", "odbpp_zip"} and not _has_manufacturing_profile(parsed):
            fail("지원하는 단일 보드의 직선 프로파일이 필요합니다.", "parsed", "E_UNSUPPORTED")
        _text(reason, "reason", limit=512)
        if parsed.get("schema") != "rfad.pcb-parse/0.1" or parsed.get("raw_preservation_required") is not True or len(canonical_bytes(parsed)) > 768 * 1024:
            fail("지원하지 않거나 상한을 넘은 고정 parser 결과입니다.", "parsed", "E_UNSUPPORTED")
        if type(acknowledged_losses) is not list or len(set(acknowledged_losses)) != len(acknowledged_losses) or set(acknowledged_losses) != {row["id"] for row in losses}:
            fail("모든 원문 보존 손실 항목을 각각 확인하십시오.", "acknowledged_losses", "E_CONFLICT")
        candidate = _ImportCandidate(document, parsed, import_record, mapping).build()
        patch = make_patch(document, candidate, "import.apply", reason)
        probe = deepcopy(document)
        probe["schema_version"] = PROJECT_SCHEMA
        apply_pcb_command(probe, patch)
        digest = canonical_hash({"source": canonical_hash(document), "parsed": canonical_hash(parsed), "import": import_record, "mapping": mapping, "acknowledged_losses": acknowledged_losses, "reason": reason, "patch": patch})
        changes = [{"collection": row["collection"], "id": row["id"], "label": (row["replacement"]["value"] or row["expected"]["value"]).get("name", "수입 원문"), "before": row["expected"]["value"], "after": row["replacement"]["value"], "before_display": record_summary(document, row["expected"]["value"]), "after_display": record_summary(candidate, row["replacement"]["value"]), "unit": ""} for row in patch["changes"]]
        return bounded({**base, "can_apply": True, "review_hash": digest, "before_scene": build_canvas_dto(document), "scene": build_canvas_dto(candidate), "selection": {"kind": "project", "id": document["project_id"]}, "changes": changes, "losses": losses, "issues": [], "document_bytes": len(canonical_bytes(candidate)), "conditions": {"stackup": "현재 적층 유지; 파일의 물성 기본값을 채택하지 않음", "tool_and_plating": "기록되지 않은 공구와 도금 두께는 미정", "zone": "명시 solid 경계만 보존; 외부 CAD refill 합격 아님"}}), patch
    except ProjectError as error:
        return bounded({**base, "can_apply": False, "review_hash": None, "scene": None, "changes": [], "losses": losses, "issues": [{"severity": "blocker", "code": error.code, "message_ko": error.message, "details": error.details}]}), None
    except (KeyError, TypeError, ValueError, IndexError, OverflowError) as error:
        return bounded({**base, "can_apply": False, "review_hash": None, "scene": None, "changes": [], "losses": losses, "issues": [{"severity": "blocker", "code": "E_SCHEMA", "message_ko": "원본 대응 또는 parser 필수 필드가 유효하지 않습니다.", "details": {"error_type": type(error).__name__}}]}), None


def _has_manufacturing_profile(parsed):
    """! @brief 구형 읽기 자료를 유지하며 새 parser가 제공한 단일 프로파일만 받는다."""
    records = parsed.get("records", [])
    return len(records) == 1 and bool(records[0]["data"].get("editable_profile"))


def import_sources(parsed):
    """! @brief native가 원문 형식/넷/hash를 해석하지 않도록 명시 대응 목록을 제공한다."""
    layers, nets = {}, {}
    def add_layer(source, role="conductor", side=None):
        """! @brief 같은 파일층의 서로 다른 역할을 임의로 합치지 않는다."""
        item = {"source": source, "label": source, "role": role, "side": side}
        if source in layers and layers[source] != item:
            fail("파일층 대응 의미가 여러 원문에서 다릅니다.", "mapping.layers", "E_CONFLICT")
        layers[source] = item
    def add_net(source, name):
        """! @brief 파일 코드와 이름을 함께 보이고 무명/미연결을 분리한다."""
        label = name if name else "이름 / 연결 미정"
        item = {"source": source, "label": label + (" (코드 " + source + ")" if source.isdigit() else ""), "source_name": name}
        if source in nets and nets[source] != item:
            fail("같은 원본 넷 키의 이름이 파일마다 다릅니다.", "mapping.nets", "E_CONFLICT")
        nets[source] = item
    for record in parsed["records"]:
        data = record["data"]
        if data["schema"] == "rfad.kicad-read/0.1":
            conductor = [row["name"] for row in data["layers"] if row["name"].endswith(".Cu")]
            for item in data["shapes"]:
                if item.get("pad_type") == "np_thru_hole":
                    add_net(str(item.get("net_code", 0)), item.get("net_name"))
                    continue
                names = item.get("layers", [item.get("layer")])
                if "*.Cu" in names:
                    names = [*names, *(conductor or ["F.Cu", "B.Cu"])]
                for name in names:
                    if name is None or name.startswith("*."):
                        continue
                    if name.endswith(".Cu"):
                        add_layer(name)
                    elif name.endswith((".Mask", ".Paste")):
                        add_layer(name, "solder_mask" if name.endswith(".Mask") else "solder_paste", "top" if name.startswith("F.") else "bottom")
                add_net(str(item.get("net_code", 0)), item.get("net_name"))
            for item in data["keepouts"]:
                add_layer(item["layer"])
            for item in data["artwork"]:
                name = item["layer"]
                if name.endswith((".Mask", ".Paste")):
                    add_layer(name, "solder_mask" if name.endswith(".Mask") else "solder_paste", "top" if name.startswith("F.") else "bottom")
        elif data["schema"] == "rfad.vendor-pattern-read/0.1":
            for region in data["regions"]:
                add_layer(region["layer"], side=region["side"])
            add_net("", None)
        elif data["schema"] == "rfad.gerber-read/0.1":
            function = data["file_attributes"].get(".FileFunction", [])
            if function and function[0] == "Copper":
                add_layer(record["path"])
                for item in data["objects"]:
                    names = item["attributes"].get(".N") or [""]
                    add_net(names[0], names[0] or None)
            elif function and function[0] in ("Soldermask", "Paste"):
                add_layer(record["path"], "solder_mask" if function[0] == "Soldermask" else "solder_paste", "top" if "Top" in function else "bottom" if "Bot" in function or "Bottom" in function else None)
    profile_available = _has_manufacturing_profile(parsed)
    return {"layers": list(layers.values()), "nets": list(nets.values()),
            "manufacturing_profile_available": profile_available,
            "ipc_profile_available": parsed.get("format") == "ipc2581_revc" and profile_available,
            "losses": [{"id": canonical_hash(row), "message": _loss_message(row, "원문에 보존되는 미지원 항목: "), "original": deepcopy(row)} for row in parsed["losses"]]}
