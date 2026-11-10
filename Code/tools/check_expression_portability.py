"""! @file
@brief 런타임 간 표현식, UUID 그래프와 미정 물성의 정확한 직렬화 일치를 검사한다.

@details baseline은 해당 런타임에서 실제 계산하여 생성한다. 비교는 허용차를
사용하지 않으며 기존 프로젝트나 baseline을 수정하지 않는다. 제한된 corpus의
일치가 모든 입력과 모든 수학 라이브러리의 bitwise 호환성을 보장하지는 않는다.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
from uuid import UUID


CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / "src"))

from rfad.application.canonical import CANONICAL_VERSION, canonical_bytes, canonical_hash
from rfad.domain.errors import ProjectError
from rfad.domain.expressions import ENGINE_VERSION, evaluate_expression
from rfad.domain.parameter_graph import evaluate_parameters, expression_record
from rfad.domain.project import validate_project
from rfad.domain.units import Quantity


SCHEMA = "rfad.expression-portability/0.1"
CORPUS_VERSION = "rfad.expression-corpus/0.1"
MAX_BASELINE_BYTES = 512 * 1024


def runtime_identity() -> dict:
    """! @brief 사용자 경로 없이 계산을 수행한 런타임을 기록한다."""
    return {
        "implementation": platform.python_implementation(), "python": platform.python_version(),
        "system": platform.system(), "release": platform.release(), "machine": platform.machine(),
        "libc": list(platform.libc_ver()), "compiler": platform.python_compiler(),
    }


def source_identity() -> dict:
    """! @brief OS 줄바꿈을 제외하고 실제 관련 소스의 동일성을 확인한다."""
    paths = ["application/canonical.py", "domain/expressions.py", "domain/parameter_graph.py", "domain/units.py", "domain/project.py", "domain/design.py"]
    return {name: hashlib.sha256((CODE_ROOT / "src/rfad" / name).read_text(encoding="utf-8").encode("utf-8")).hexdigest() for name in paths}


def _quantity(value: float, unit: str, *, estimated: bool = False) -> dict:
    """! @brief 명시적 단위와 출처를 포함한 검사 입력을 만든다."""
    return Quantity.from_value(value, unit, status="estimated" if estimated else "user_entered", source_refs=("portability-corpus",)).to_dict()


def build_inputs() -> dict:
    """! @brief 상수 기대값 대신 계산할 원문과 입력을 결정적으로 구성한다."""
    cases = []
    def add(name, expression, dimension="dimensionless", unit="1", variables=None):
        """! @brief 독립된 표현식 사례를 입력 corpus에 넣는다."""
        cases.append({"id": name, "expression": expression, "dimension": dimension, "display_unit": unit, "variables": variables or {}})
    add("unit_arithmetic", "폭 / 2 + 1 mm", "length", "mm", {"폭": _quantity(40, "mm")})
    add("wavelength", "c0 / (4 * f)", "length", "mm", {"f": _quantity(2.45, "GHz")})
    add("hypotenuse", "sqrt((3 mm)**2 + (4 mm)**2)", "length", "mm")
    add("sqrt_irrational", "sqrt(2)")
    add("fractional_power", "((2 m)**3)**(1/3)", "length", "m")
    add("power_precedence", "-2**2 + 2**3**2")
    add("clamp", "clamp(max(abs(-5 mm), 2 mm), 1 mm, 4 mm)", "length", "mm")
    add("minimum", "min(2, 3, -1)")
    add("conductivity", "1 / (2 ohm * 0.5 m)", "conductivity", "S/m")
    add("time_frequency", "1 / (2 ns)", "frequency", "MHz")
    add("power_unit", "10 mW + 1 W", "power", "mW")
    add("estimated_sources", "a+b", "length", "mm", {"a": _quantity(1, "mm"), "b": _quantity(2, "mm", estimated=True)})
    for angle in (-170, -135, -83, -40, -15, 0, 15, 33, 67, 90, 115, 179):
        for function in ("sin", "cos"):
            add(f"{function}_{angle}", f"{function}({angle} deg)")
    for angle in (-73, -17, 0, 31, 68):
        add(f"tan_{angle}", f"tan({angle} deg)")
    for x, y in ((3, 2), (-3, 2), (-3, -2), (3, -2)):
        add(f"atan2_{x}_{y}", f"atan2({y} mm, {x} mm)", "angle", "deg")
    add("missing_input", "width", "length", "mm", {"width": Quantity.missing("length", "mm").to_dict()})
    add("domain_error", "sqrt(-1)")
    add("unit_error", "1 mm + 1 s")
    add("code_rejected", "__import__('os')")
    ids = [str(UUID(int=number)) for number in range(1, 5)]
    parameters = {ids[0]: {"id": ids[0], "name": "폭", "quantity": _quantity(40, "mm", estimated=True)}}
    for identity, name, expression, bindings in (
        (ids[1], "절반", "w / 2", {"w": ids[0]}),
        (ids[2], "원호 길이 입력", "half * cos(33 deg)", {"half": ids[1]}),
        (ids[3], "합산", "arc + width", {"arc": ids[2], "width": ids[0]}),
    ):
        parameters[identity] = {"id": identity, "name": name, "quantity": Quantity.missing("length", "mm").to_dict(), "expression": expression_record(expression, bindings)}
    fixture = json.loads((CODE_ROOT / "fixtures/design/initial_ifa.json").read_text(encoding="utf-8"))
    return {"cases": cases, "parameters": parameters, "fixture": fixture}


def evaluate_inputs(inputs: dict) -> dict:
    """! @brief 복제한 입력만 계산하고 구조화 오류와 직렬화 근거를 모은다."""
    results = {}
    for case in inputs["cases"]:
        try:
            variables = {name: Quantity(**quantity) for name, quantity in case["variables"].items()}
            quantity = evaluate_expression(case["expression"], variables, expected_dimension=case["dimension"], display_unit=case["display_unit"])
            results[case["id"]] = {"quantity": quantity.to_dict(), "float_hex": quantity.value_si.hex()}
        except ProjectError as error:
            results[case["id"]] = {"error_code": error.code}
    parameters = deepcopy(inputs["parameters"])
    evaluate_parameters(parameters, update=True)
    evaluate_parameters(parameters)
    fixture = deepcopy(inputs["fixture"])
    try:
        validate_project(fixture)
        validation = {"status": "valid"}
    except ProjectError as error:
        validation = {"status": "rejected", "error_code": error.code, "details": error.details}
    return {"cases": results, "parameters": parameters, "fixture": {"validation": validation, "canonical_hash": canonical_hash(fixture), "materials": fixture["materials"]}}


def generate_baseline() -> dict:
    """! @brief 현재 런타임의 실제 계산 결과와 원문을 기준 자료로 생성한다."""
    inputs = build_inputs()
    expected = evaluate_inputs(inputs)
    if expected["fixture"]["validation"]["status"] != "valid":
        raise ValueError("The existing IFA fixture failed validation; its cache must not be rewritten.")
    body = {"inputs": inputs, "expected": expected}
    return {"schema": SCHEMA, "corpus_version": CORPUS_VERSION, "engine_version": ENGINE_VERSION, "canonical_version": CANONICAL_VERSION, "created_at_utc": datetime.now(timezone.utc).isoformat(), "origin_runtime": runtime_identity(), "sources": source_identity(), "body_hash": canonical_hash(body), **body}


def _differences(expected: object, actual: object, path: str = "result") -> list[str]:
    """! @brief 최대 64개의 불일치 위치를 찾아 결과 보고서에 포함한다."""
    if canonical_bytes(expected) == canonical_bytes(actual):
        return []
    if type(expected) is dict and type(actual) is dict and expected.keys() == actual.keys():
        result = []
        for key in sorted(expected):
            result.extend(_differences(expected[key], actual[key], path + "." + key))
            if len(result) >= 64:
                return result[:64]
        return result
    return [path]


def compare_baseline(baseline: dict) -> dict:
    """! @brief 같은 소스의 다른 런타임 결과를 허용차 없이 비교한다."""
    for field, expected in (("schema", SCHEMA), ("corpus_version", CORPUS_VERSION), ("engine_version", ENGINE_VERSION), ("canonical_version", CANONICAL_VERSION)):
        if baseline.get(field) != expected:
            raise ValueError(f"Unsupported {field}.")
    if baseline.get("sources") != source_identity():
        raise ValueError("Source identity differs; this is not a runtime-only comparison.")
    if not isinstance(baseline.get("origin_runtime"), dict) or not baseline["origin_runtime"].get("python"):
        raise ValueError("The baseline must record its origin runtime.")
    body = {key: baseline[key] for key in ("inputs", "expected")}
    if canonical_hash(body) != baseline.get("body_hash"):
        raise ValueError("Baseline content hash mismatch.")
    if canonical_bytes(baseline["inputs"]) != canonical_bytes(build_inputs()):
        raise ValueError("Corpus input differs; existing project caches are not modified.")
    actual = evaluate_inputs(baseline["inputs"])
    differences = _differences(baseline["expected"], actual)
    return {"schema": "rfad.expression-portability-report/0.1", "status": "passed" if not differences else "failed", "comparison": "exact_canonical_bytes_and_float_hex", "origin_runtime": baseline["origin_runtime"], "current_runtime": runtime_identity(), "checked_at_utc": datetime.now(timezone.utc).isoformat(), "case_count": len(actual["cases"]), "expected_hash": canonical_hash(baseline["expected"]), "actual_hash": canonical_hash(actual), "mismatch_paths": differences, "actual": actual, "scope": "fixed corpus only; not a universal floating-point portability guarantee", "project_or_baseline_modified": False}


def main(argv: list[str] | None = None) -> int:
    """! @brief 기준 생성 또는 읽기 전용 비교를 실행하고 실패를 종료 코드로 알린다."""
    parser = argparse.ArgumentParser(description="Check exact expression cache portability without modifying projects.")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--generate", type=Path, help="Write a new baseline; an existing file is never replaced.")
    modes.add_argument("--compare", type=Path, help="Compare an existing baseline with the current runtime.")
    parser.add_argument("--output", type=Path, help="Write a comparison report; cannot be the baseline or fixture.")
    args = parser.parse_args(argv)
    report = None
    try:
        if args.generate:
            if args.output:
                raise ValueError("--output is only valid with --compare.")
            baseline = generate_baseline()
            args.generate.parent.mkdir(parents=True, exist_ok=True)
            with args.generate.open("xb") as stream:
                stream.write(canonical_bytes(baseline) + b"\n")
            print(json.dumps({"status": "generated", "case_count": len(baseline["inputs"]["cases"]), "origin_runtime": baseline["origin_runtime"]}, ensure_ascii=False))
            return 0
        if args.compare.stat().st_size > MAX_BASELINE_BYTES:
            raise ValueError("Baseline exceeds the 512 KiB limit.")
        if args.output and args.output.resolve() in (args.compare.resolve(), (CODE_ROOT / "fixtures/design/initial_ifa.json").resolve()):
            raise ValueError("Report output must not overwrite the baseline or project fixture.")
        report = compare_baseline(json.loads(args.compare.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, KeyError, ProjectError) as error:
        report = {"status": "failed", "error": str(error), "current_runtime": runtime_identity(), "project_or_baseline_modified": False}
        print(json.dumps(report, ensure_ascii=False))
        return 2
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_bytes(report) + b"\n")
    print(json.dumps({key: value for key, value in report.items() if key != "actual"}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
