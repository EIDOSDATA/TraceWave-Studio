"""! @brief 직접 입력 카드와 원문 근거가 있는 부분 기하 카드를 버전별로 제공한다."""

from copy import deepcopy

from rfad.application.canonical import canonical_hash
from rfad.domain.design import _fail, _fields, _text, _strings
from rfad.templates import g031


CARD_SCHEMA = "rfad.template-card/0.1"
GENERATOR_VERSION = "rfad.explicit-geometry/0.1"
ARC = "builtin.explicit_arc"
IFA = "builtin.explicit_planar_ifa"
VERSION = "0.1"
SUPPORT = {"geometry_generator": True, "seed_synthesizer": False, "simulated": False,
           "converged": False, "measured": False, "manufacturing_verified": False}
_ARC_FIELDS = (
    ("center_x", "원호 중심 X", "length", "mm"), ("center_y", "원호 중심 Y", "length", "mm"),
    ("radius", "중심선 반지름", "length", "mm"), ("start_angle", "시작각", "angle", "deg"),
    ("sweep_angle", "부호 있는 전개각", "angle", "deg"), ("width", "원호 선폭", "length", "mm"),
    ("feed_start_x", "급전 선 시작 X", "length", "mm"), ("feed_start_y", "급전 선 시작 Y", "length", "mm"),
    ("feed_width", "급전 선폭", "length", "mm"),
)
_IFA_FIELDS = tuple((key, label, "length", "mm") for key, label in (
    ("ground_left", "접지 왼쪽 X"), ("ground_bottom", "접지 아래쪽 Y"),
    ("ground_width", "접지 폭"), ("ground_height", "접지 높이"),
    ("radiator_start_x", "방사 가지 시작 X"), ("radiator_y", "방사 가지 Y"),
    ("radiator_length", "방사 가지 길이"), ("trace_width", "가지 선폭"),
    ("short_x", "단락 가지 X"), ("short_start_y", "단락 가지 시작 Y"),
    ("feed_x", "급전 가지 X"), ("feed_start_y", "급전 패드 중심 Y"),
    ("pad_width", "급전 패드 폭"), ("pad_height", "급전 패드 높이"),
))


def _card(identity: str) -> dict:
    """! @brief 구현 근거와 기하 생성 지원 범위를 가진 카드 원본을 만든다."""
    arc = identity == ARC
    return {
        "schema": CARD_SCHEMA, "template_id": identity, "version": VERSION,
        "name": "명시 치수 원호" if arc else "명시 치수 평면 IFA", "family": "FAM-01" if arc else "FAM-02",
        "description": "기존 보드와 적층에 사용자가 입력한 치수의 기하만 생성합니다.",
        "generator_version": GENERATOR_VERSION, "mode": "explicit_geometry",
        "board_kinds": ["rectangle", "circle"] if arc else ["rectangle"],
        "input_fields": [{"key": key, "label": label, "dimension": dimension, "display_unit": unit, "required": True}
                         for key, label, dimension, unit in (_ARC_FIELDS if arc else _IFA_FIELDS)],
        "support": deepcopy(SUPPORT),
        "source": {"source_id": "tracewave:" + identity + "/" + VERSION, "kind": "implementation_recipe",
                   "references": ["RFAD-D0-3.4/FN-006", "RFAD-D0-3.4/FN-007", "RFAD-D0-3.4/22"],
                   "scope": "사용자가 입력한 기하만 생성하며 업체 원문 재현 또는 RF 검증 카드가 아님"},
        "assumptions": ["주파수에서 치수나 물성을 자동 추정하지 않음", "제작, 측정, 정합 및 전력/손실 정확도는 미검증",
                        "명시 포트가 없으면 geometry-only 후보이며 50 ohm을 자동 입력하지 않음"],
        "limitations": ["RF 성능 합성/검증 및 전층 제조 DRC 미지원", "물성과 포트 미정값은 저장하고 후속 해석에서 검사"],
    }


def describe_card(identity: str, version: str = VERSION) -> dict:
    """! @brief 알려진 버전의 깊은 사본과 정규 내용 해시를 반환한다."""
    if type(identity) is not str or identity not in (ARC, IFA, g031.IDENTITY) or version != VERSION:
        _fail("E_UNSUPPORTED", "지원하지 않는 템플릿 또는 버전입니다.", "template")
    card = g031.card() if identity == g031.IDENTITY else _card(identity)
    return {**card, "content_hash": canonical_hash(card)}


def list_cards() -> list[dict]:
    """! @brief 작은 내장 카드 목록을 외부 파일 실행 없이 반환한다."""
    return [describe_card(identity) for identity in (ARC, IFA, g031.IDENTITY)]


def resolve_card(reference: dict) -> dict:
    """! @brief 미리보기와 적용에 지정한 정확한 카드 버전/해시를 확인한다."""
    _fields(reference, {"template_id", "version", "content_hash"}, "template")
    card = describe_card(reference["template_id"], reference["version"])
    if reference["content_hash"] != card["content_hash"]:
        _fail("E_CONFLICT", "선택한 템플릿 내용이 변경되었습니다. 다시 조회하십시오.", "template.content_hash")
    return card


def validate_card_snapshot(card: object) -> None:
    """! @brief 과거 카드 사본은 현재 라이브러리 재조회 없이 내용과 제한된 증거 상태를 검사한다."""
    keys = {"schema", "template_id", "version", "name", "description", "family", "generator_version", "mode", "board_kinds",
            "input_fields", "support", "source", "assumptions", "limitations", "content_hash"}
    literature = type(card) is dict and card.get("schema") == g031.SCHEMA
    if literature:
        keys |= {"evidence", "reference_inputs"}
    _fields(card, keys, "template_origin.card")
    if (card["schema"] != (g031.SCHEMA if literature else CARD_SCHEMA) or card["mode"] != "explicit_geometry"
            or card["generator_version"] != (g031.GENERATOR if literature else GENERATOR_VERSION) or card["support"] != SUPPORT
            or type(card["support"]) is not dict or any(type(value) is not bool for value in card["support"].values())):
        _fail("E_VERSION", "템플릿 사본의 지원 profile 또는 검증 주장이 다릅니다.", "template_origin.card")
    _text(card["template_id"], "template_origin.card.template_id")
    _text(card["version"], "template_origin.card.version")
    if card["template_id"] not in ((g031.IDENTITY,) if literature else (ARC, IFA)) or card["version"] != VERSION:
        _fail("E_VERSION", "지원하지 않는 과거 템플릿 카드 형식입니다.", "template_origin.card.template_id")
    for key in ("name", "description", "family"):
        _text(card[key], "template_origin.card." + key)
    kinds = ["rectangle", "circle"] if card["template_id"] in (ARC, g031.IDENTITY) else ["rectangle"]
    if card["board_kinds"] != kinds or type(card["board_kinds"]) is not list:
        _fail("E_SCHEMA", "템플릿의 보드 지원 범위가 다릅니다.", "template_origin.card.board_kinds")
    _fields(card["source"], {"source_id", "kind", "references", "scope"}, "template_origin.card.source")
    for key in ("source_id", "kind", "scope"):
        _text(card["source"][key], "template_origin.card.source." + key)
    if card["source"]["kind"] != ("cad_reference" if literature else "implementation_recipe"):
        _fail("E_SCHEMA", "내장 기하 생성기 출처를 원문 검증 카드로 바꿀 수 없습니다.", "template_origin.card.source.kind")
    for name, value in (("source.references", card["source"]["references"]), ("assumptions", card["assumptions"]), ("limitations", card["limitations"])):
        _strings(value, "template_origin.card." + name)
        if not value or len(value) > 16:
            _fail("E_RESOURCE", "템플릿 출처/가정 설명은 1~16개여야 합니다.", "template_origin.card." + name)
    definitions = g031.FIELDS if literature else (_ARC_FIELDS if card["template_id"] == ARC else _IFA_FIELDS)
    descriptors = card["input_fields"]
    if type(descriptors) is not list or len(descriptors) != len(definitions):
        _fail("E_SCHEMA", "템플릿 입력 descriptor 수가 다릅니다.", "template_origin.card.input_fields")
    for descriptor, definition in zip(descriptors, definitions):
        _fields(descriptor, {"key", "label", "dimension", "display_unit", "required"}, "template_origin.card.input_fields")
        key, _, dimension, unit = definition
        if (descriptor["key"] != key or descriptor["dimension"] != dimension or descriptor["display_unit"] != unit
                or descriptor["required"] is not True):
            _fail("E_SCHEMA", "템플릿 입력 descriptor의 역할/차원/단위가 다릅니다.", "template_origin.card.input_fields")
        _text(descriptor["label"], "template_origin.card.input_fields.label")
    if literature:
        g031.validate_snapshot(card)
    if card["content_hash"] != canonical_hash({key: value for key, value in card.items() if key != "content_hash"}):
        _fail("E_HASH", "프로젝트의 템플릿 카드 사본 해시가 다릅니다.", "template_origin.card.content_hash")
