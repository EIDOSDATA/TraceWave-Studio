"""! @brief 근거가 있는 초기 길이의 조건과 산술을 기하 생성 및 RF 판정에서 분리한다."""

from copy import deepcopy

from rfad.domain.design import _fail, _fields, _text
from rfad.domain.template_inputs import normalize_inputs, normalize_quantity_input
from rfad.domain.units import Quantity, QuantityError
from rfad.templates.printed_references import MONOPOLE


C0_M_PER_S = 299792458.0


def normalize_candidate(card, requested, mode="explicit_geometry", seed=None):
    """! @brief 명시 치수는 그대로 유지하고 별도 초기식 요청만 추정 길이로 변환한다."""
    if mode not in card.get("modes", ["explicit_geometry"]):
        _fail("E_UNSUPPORTED", "이 카드는 요청한 초기 후보 방식을 지원하지 않습니다.", "mode")
    if mode == "explicit_geometry":
        if seed is not None:
            _fail("E_SCHEMA", "명시 기하 요청에는 초기식 입력을 함께 보낼 수 없습니다.", "seed")
        return normalize_inputs(card, requested), None
    if card["template_id"] != MONOPOLE:
        _fail("E_UNSUPPORTED", "이 topology의 초기 RF 합성은 지원하지 않습니다.", "mode")
    _fields(seed, {"recipe_id", "frequency", "assumption"}, "seed")
    _text(seed["assumption"], "seed.assumption")
    if len(seed["assumption"]) > 512:
        _fail("E_RESOURCE", "초기식의 사용자 가정은 512자 이하여야 합니다.", "seed.assumption")
    recipe = next((item for item in card["seed_recipes"] if item["id"] == seed["recipe_id"]), None)
    if recipe is None:
        _fail("E_UNSUPPORTED", "카드에 없는 초기식입니다.", "seed.recipe_id")
    frequency = normalize_quantity_input(seed["frequency"], "frequency", "seed.frequency")
    hz = frequency["value_si"]
    if hz <= 0:
        _fail("E_UNIT", "초기식 주파수는 양수여야 합니다.", "seed.frequency")
    if recipe["id"] != "ideal_quarter_wave" and hz != 2450000000.0:
        _fail("E_UNSUPPORTED", "nWP008의 0.75 보정은 원문 2.45 GHz 조건에서만 제공합니다.", "seed.frequency")
    if type(requested) is not dict or requested.get("length") != {"source": "initial_estimate"}:
        _fail("E_SCHEMA", "계산 길이를 사용하려면 length에 initial_estimate 선택을 명시하십시오.", "explicit_inputs.length")
    refs = ["RFAD-D0-3.4/EQ-003", "RFAD-D0-3.4/EQ-004", "NORDIC_NWP008/p.1-3/initial-estimate"]
    try:
        base = (C0_M_PER_S / hz) * recipe["kappa"] / 4.0
        value = base * (1.0 + recipe["extension"])
        length = Quantity(value, "length", "mm", "estimated", refs).to_dict()
    except (OverflowError, QuantityError):
        _fail("E_UNIT", "초기 길이가 유한 수량 범위를 벗어납니다.", "seed.frequency")
    if value <= 0:
        _fail("E_UNIT", "초기 길이가 유효한 양수 범위를 벗어납니다.", "seed.frequency")
    inputs = normalize_inputs(card, requested, calculated={"length": length})
    if recipe["id"] != "ideal_quarter_wave" and inputs["width"]["value_si"] != card["reference_inputs"]["width"]["quantity"]["value_si"]:
        _fail("E_UNSUPPORTED", "nWP008 보정의 선폭 조건은 원문 1.5 mm입니다.", "explicit_inputs.width")
    return inputs, {
        "schema": "rfad.initial-estimate/0.1", "request": deepcopy(seed), "recipe": deepcopy(recipe),
        "frequency": frequency, "length": length, "c0_m_per_s": C0_M_PER_S,
        "source_rounded_length_mm": 23.0, "base_length_m": base,
        "conditions_verified": False, "evidence_state": "estimated_seed",
        "summary": f"초기 추정 {value * 1000:.9g} mm / 조건 가정 / 공진/정합 해 아님 / 해석/수렴/실측 미검증",
    }
