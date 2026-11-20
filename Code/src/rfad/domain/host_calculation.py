"""! @brief 경로/서비스/callback 없이 JSON 원문만 받는 닫힌 복소 계산 진입점을 정의한다."""
from copy import deepcopy

from rfad.application.canonical import canonical_hash
from rfad.domain.design import resolve_scalar
from rfad.domain.errors import ProjectError
from rfad.domain.network_assessment import evaluate_target
from rfad.domain.network_circuit import apply_circuit
from rfad.domain.network_transform import transform_dataset
from rfad.application.network_forms import input_quantity, transform_input

FIELDS = {
    "network.transform": {"dataset", "options"},
    "network.circuit": {"dataset", "circuit"},
    "network.evaluate": {"document", "target", "dataset", "context", "metrics"},
    "sweep.assess": {"document", "specification", "dataset", "metrics"},
    "measurement.align": {"dataset", "specification"},
    "result.compare": {"left", "right", "parameters"},
}


def resolved_target(document, target):
    """! @brief 원문을 바꾸지 않고 평가 시점의 매개변수 참조만 해석한다."""
    output = deepcopy(target)
    for key in ("start", "end", "reference"):
        if key in output["band"]:
            output["band"][key] = resolve_scalar(document, output["band"][key], "frequency", "target.band." + key).to_dict()
    output["reference_impedance"] = resolve_scalar(document, output["reference_impedance"], "impedance", "target.reference_impedance").to_dict()
    return output


def assess(inputs):
    """! @brief 재사용/중단 후 보존 자료도 동일한 목표 계산 경계에서 평가한다."""
    spec, document, dataset = inputs["specification"], inputs["document"], inputs["dataset"]
    contexts = {item["target_id"]: item["context"] for item in spec["target_contexts"]}
    results = []
    for identity in spec["target_ids"]:
        target = next(item for item in document["targets"] if item["id"] == identity)
        context = contexts.get(identity)
        if context is None or context["target_port_id"] != target["port_id"]:
            result = {"target_id": identity, "target_revision_id": target["revision_id"],
                      "status": "not_evaluated", "criteria": [], "continuous_band_verified": False,
                      "physics_validated": False, "reason": "목표와 자료의 명시 포트/기준면 대응이 없습니다."}
        else:
            try:
                result = evaluate_target(resolved_target(document, target), dataset, context, metrics=inputs["metrics"])
            except ProjectError as error:
                result = {"target_id": identity, "target_revision_id": target["revision_id"],
                          "status": "not_evaluated", "criteria": [], "continuous_band_verified": False,
                          "physics_validated": False, "diagnostic": error.diagnostic()}
        result["evidence"] = {"target_original": deepcopy(target), "project_revision": document["revision_id"],
                              "context": deepcopy(context), "dataset_hash": canonical_hash(dataset)}
        results.append(result)
    return {"schema": "rfad.sweep-assessments/0.1", "assessments": results,
            "continuous_band_verified": False, "physics_validated": False}


def execute(operation, inputs, engine_identity=None):
    """! @brief 고정 작업과 exact 입력 키만 수용하고 임의 모듈/함수 실행을 허용하지 않는다."""
    if type(operation) is not str or operation not in FIELDS:
        raise ProjectError("E_UNSUPPORTED", "지원하지 않는 host 계산 작업입니다.")
    if type(inputs) is not dict or set(inputs) != FIELDS[operation]:
        raise ProjectError("E_SCHEMA", "host 계산 입력 필드가 닫힌 계약과 다릅니다.")
    if operation == "measurement.align":
        from rfad.domain.measurement_alignment import align_dataset
        return align_dataset(inputs["dataset"], inputs["specification"], engine_identity)
    if operation == "result.compare":
        from rfad.application.result_complex import compare_data
        from rfad.domain.network_data import validate_dataset
        validate_dataset(inputs["left"])
        validate_dataset(inputs["right"])
        return compare_data(inputs["left"], inputs["right"], inputs["parameters"])
    if operation == "network.transform":
        options = inputs["options"]
        derived = transform_dataset(inputs["dataset"], transform_input(inputs["dataset"], options))
        if "reference" in options:
            source = derived["dataset"]["provenance"]["network_operations"][-1]
            source["original_options"] = deepcopy(options)
            source["reference_quantity"] = input_quantity(options["reference"], "impedance", "reference")
        return derived
    if operation == "network.circuit":
        return apply_circuit(inputs["dataset"], inputs["circuit"])
    if operation == "network.evaluate":
        return evaluate_target(resolved_target(inputs["document"], inputs["target"]), inputs["dataset"], inputs["context"], metrics=inputs["metrics"])
    return assess(inputs)
