"""! @brief 기하 생성과 원문 치수 일치 여부를 RF 검증 상태와 분리해 표시한다."""


def generation_report(card: dict, inputs: dict) -> dict:
    """! @brief 치수 변경을 보수적으로 알리고 수행하지 않은 추정/해석/검증은 미완료로 유지한다."""
    references = card.get("reference_inputs", {})
    modified = [key for key, reference in references.items()
                if inputs[key]["value_si"] != reference["quantity"]["value_si"]]
    literature = bool(references)
    summary = ("부분 기하 생성 / " + ("원문 치수 사용" if not modified else "원문 치수 수정: " + ", ".join(modified))
               if literature else "명시 기하 생성")
    return {
        "applies_to": "creation_inputs",
        "geometry": {"status": "generated_partial" if literature else "generated_explicit",
                     "source_dimensions": "modified" if modified else ("reference" if literature else "not_applicable"),
                     "modified_fields": modified, "whole_board_reproduced": False},
        "initial_estimate": "not_performed", "analysis": "not_performed", "convergence": "not_established",
        "measurement": "not_verified", "manufacturing": "not_verified",
        "summary": summary + " / 초기 추정 미수행 / 해석 미수행 / 수렴 미확립 / 실측 미검증 / 제조 미검증",
    }
