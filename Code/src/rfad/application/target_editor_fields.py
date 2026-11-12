"""! @brief 목표 원본을 단위 변환과 출처를 보존한 작은 편집 필드로 투영한다."""

from copy import deepcopy

from rfad.application.editor import _display_quantity
from rfad.domain.targets import METRICS
from rfad.domain.units import Quantity


FREQUENCY_UNITS = ("Hz", "kHz", "MHz", "GHz")
METRIC_LABELS = {"s11_db": "S11", "radiation_efficiency": "방사 효율", "total_efficiency": "전체 효율", "fractional_bandwidth": "비대역폭"}
QUANTITIES = {"band.start": ("대역 시작", "frequency"), "band.end": ("대역 끝", "frequency"),
              "band.reference": ("기준 주파수", "frequency"), "reference_impedance": ("기준 임피던스", "impedance")}


def blank_target():
    """! @brief 이름과 물리값을 자동 채우지 않는 저장 전 표시 원본을 만든다."""
    return {"id": None, "revision_id": None, "name": "", "physical_mode": "radiating_rf",
            "band": {key: Quantity.missing("frequency", "GHz").to_dict() for key in ("start", "end", "reference")}
                    | {"sampling": {"kind": "linear", "count": None}},
            "port_id": None, "reference_impedance": Quantity.missing("impedance", "ohm").to_dict(),
            "criteria": [], "source_refs": []}


def field(key, label, value, *, editor="text", choices=(), readonly=False, help_text=""):
    """! @brief 기존 속성 패널과 같은 필드 형식을 사용하고 여러 줄은 배열로 전송한다."""
    result = {"key": key, "label": label, "value": value, "editor": editor,
              "choices": [{"value": value, "label": label} for value, label in choices], "readonly": readonly}
    if editor == "string_lines":
        result["multiline"] = True
    if readonly:
        result["advanced"] = True
    if help_text:
        result["help"] = help_text
    return result


def quantity_at(target, key):
    """! @brief 허용된 수량 경로를 읽으며 임의 경로 탐색을 허용하지 않는다."""
    return target["band"][key.split(".")[1]] if key.startswith("band.") else target[key]


def quantity_fields(target, key, label, dimension):
    """! @brief 숫자 표시와 입력 상태/출처를 분리하고 SI 변환은 서비스에서 끝낸다."""
    raw = quantity_at(target, key)
    number, unit, note = _display_quantity(Quantity(**raw))
    units = FREQUENCY_UNITS if dimension == "frequency" else ("ohm",)
    return [field(key + ".mode", label + " 입력", "missing" if raw["value_si"] is None else "value", editor="choice",
                  choices=(("value", "직접 입력"), ("missing", "미정"))),
            field(key + ".value", label, number),
            field(key + ".unit", label + " 단위", unit, editor="choice", choices=[(unit, unit) for unit in units],
                  help_text="단위만 바꾸면 물리값을 유지합니다. 숫자와 단위를 함께 바꾸면 새 입력값을 적용합니다."),
            field(key + ".status", label + " 입력 상태", raw["status"], readonly=True),
            field(key + ".source_refs", label + " 출처", deepcopy(raw["source_refs"]), editor="string_lines", readonly=True),
            field(key + ".display_note", label + " 표시 안내", note, readonly=True)]


def explicit_lines(sampling):
    """! @brief 명시 표본을 한 줄 한 수량으로 표시하며 단위 혼합도 그대로 유지한다."""
    if sampling["kind"] != "explicit":
        return []
    return [number + " " + unit for number, unit, _ in (_display_quantity(Quantity(**raw)) for raw in sampling["frequencies"])]


def _index_ranges(indices):
    """! @brief 같은 출처를 가진 연속 표본 번호를 손실 없는 범위로 표시한다."""
    groups = []
    first = last = indices[0]
    for index in indices[1:]:
        if index == last + 1:
            last = index
        else:
            groups.append(str(first) if first == last else f"{first}-{last}")
            first = last = index
    groups.append(str(first) if first == last else f"{first}-{last}")
    return ",".join(groups)


def fields_for(document, target):
    """! @brief 수정 가능한 목표 필드와 읽기 전용 provenance를 모두 반환한다."""
    fields = [field("name", "목표 이름", target["name"]),
              field("physical_mode", "물리 모드", target["physical_mode"], readonly=True)]
    for key, (label, dimension) in QUANTITIES.items():
        fields.extend(quantity_fields(target, key, label, dimension))
    ports = [("", "미정")] + [(row["id"], row["name"]) for row in document["ports"]]
    fields.append(field("port_id", "평가 포트", target["port_id"] or "", editor="choice", choices=ports))
    sampling = target["band"]["sampling"]
    count = sampling.get("count")
    fields.extend([
        field("sampling.kind", "주파수 표본 방식", sampling["kind"], editor="choice", choices=(("linear", "등간격"), ("explicit", "명시 표본"))),
        field("sampling.count", "등간격 표본 수", "" if count is None else str(count)),
        field("sampling.explicit", "명시 주파수 표본", explicit_lines(sampling), editor="string_lines",
              help_text="한 줄에 숫자와 단위를 입력하십시오. 예: 2400 MHz. 입력 순서는 오름차순이며 표본은 목표 대역 안에 있어야 합니다."),
    ])
    provenance = []
    if sampling["kind"] == "explicit":
        groups = {}
        for index, raw in enumerate(sampling["frequencies"], 1):
            key = (raw["status"], raw["display_unit"], tuple(raw["source_refs"]))
            groups.setdefault(key, []).append(index)
        for (status, unit, references), indices in groups.items():
            label = _index_ranges(indices)
            provenance.append(f"{label}: {status} / {unit}")
            provenance.extend(f"{label}: {source}" for source in references)
    fields.append(field("sampling.provenance", "명시 표본 입력 상태와 출처", provenance, editor="string_lines", readonly=True))
    criteria = {item["metric"]: item for item in target["criteria"]}
    for metric, rule in METRICS.items():
        original = criteria.get(metric)
        limit = None if original is None else original["limit"]
        mode = "absent" if limit is None else ("missing" if limit["value"] is None else "value")
        prefix, label = "criteria." + metric, METRIC_LABELS[metric]
        fields.extend([
            field(prefix + ".mode", label + " 목표", mode, editor="choice", choices=(("absent", "지정 안 함"), ("missing", "미정"), ("value", "직접 입력"))),
            field(prefix + ".value", label + " 한계 (" + rule["unit"] + ", " + ("이하" if rule["operator"] == "le" else "이상") + ")", "" if limit is None or limit["value"] is None else repr(limit["value"])),
            field(prefix + ".operator", label + " 비교", "이하" if rule["operator"] == "le" else "이상", readonly=True),
            field(prefix + ".unit", label + " 단위", rule["unit"], readonly=True),
            field(prefix + ".status", label + " 입력 상태", "not_set" if limit is None else limit["status"], readonly=True),
            field(prefix + ".source_refs", label + " 출처", [] if limit is None else deepcopy(limit["source_refs"]), editor="string_lines", readonly=True),
        ])
    fields.append(field("source_refs", "목표 출처와 변경 사유", deepcopy(target["source_refs"]), editor="string_lines", readonly=True))
    return fields


def summary(target):
    """! @brief 목록은 전체 원본을 복제하지 않고 명시한 두 끝점만 표시한다."""
    labels = []
    for key in ("start", "end"):
        value, unit, _ = _display_quantity(Quantity(**target["band"][key]))
        labels.append(value + " " + unit)
    return " ~ ".join(labels)
