"""! @brief PCB 설정 화면에 현재 개정의 작은 명명 목록과 mm 표시값을 제공한다."""

from rfad.application.pcb_selection_contract import PROFILE, bounded
from rfad.domain.design import resolve_scalar
from rfad.domain.errors import ProjectError
from rfad.domain.pcb_selection import EXTENSION_KEY
from rfad.domain.units import QuantityError


def length_mm(document, value, field):
    """! @brief 서비스에서만 수량/매개변수를 해석하고 표시 단위로 환산한다."""
    quantity = resolve_scalar(document, value, "length", field)
    if quantity.value_si is None:
        return None
    try:
        return quantity.as_unit("mm")
    except QuantityError as error:
        raise ProjectError("E_SCHEMA", "기판 설정의 mm 표시 범위를 넘는 치수입니다. 기존 속성에서 값을 확인하십시오.",
                           details={"field_path": field}) from error


def layer_rows(document):
    """! @brief 원래 층 ID/역할/순서와 미정 또는 매개변수 결합 상태를 보존한다."""
    return [{"id": layer["id"], "name": layer["name"], "role": layer["role"], "order": layer["order"],
             "thickness_mm": length_mm(document, layer["thickness"], "stackup." + layer["id"] + ".thickness"),
             "z_min_mm": length_mm(document, layer["z_min"], "stackup." + layer["id"] + ".z_min"),
             "material_id": layer["material_id"],
             "parameter_bound": any("parameter_id" in layer[field] for field in ("thickness", "z_min"))}
            for layer in sorted(document["stackup"], key=lambda item: item["order"])]


def context_for(document):
    """! @brief 조회만으로 출처 원문이나 geometry 전체를 화면에 복사하지 않는다."""
    ports = []
    for port in document["ports"]:
        box = port.get("excitation_box")
        item = {"id": port["id"], "name": port["name"], "start_mm": None, "stop_mm": None, "parameter_bound": False}
        if box is not None:
            for endpoint in ("start", "stop"):
                item[endpoint + "_mm"] = [length_mm(document, value, "ports." + port["id"] + "." + endpoint)
                                         for value in box[endpoint]]
                item["parameter_bound"] |= any("parameter_id" in value for value in box[endpoint])
        ports.append(item)
    selected = document["extensions"].get(EXTENSION_KEY)
    summary = None if selected is None else {"id": selected["id"], "catalog": selected["catalog"],
                                            "history_count": len(selected.get("history", []))}
    return bounded({"profile": PROFILE, "project_id": document["project_id"], "revision_id": document["revision_id"],
                    "materials": [{"id": item["id"], "name": item["name"]} for item in document["materials"]],
                    "layers": layer_rows(document), "ports": ports, "selection": summary,
                    "board": None if document["board"] is None else {"kind": document["board"]["outline"]["kind"]}})
