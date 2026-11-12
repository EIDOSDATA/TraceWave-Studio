"""! @brief 승인 요구/AC와 검토한 구현 근거를 연결하며 수용 합격을 자동 생성하지 않는다."""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE / "src"))
from rfad.application.projects import ProjectService
from rfad.application.rpc import capabilities


def read(name):
    """! @brief 승인 원문을 수정 없이 읽는다."""
    return (CODE.parent / "01_Docs" / name).read_text(encoding="utf-8")


def require(condition, message):
    """! @brief 누락/중복 근거를 성공으로 숨기지 않는다."""
    if not condition:
        raise ValueError(message)


def reference(path):
    """! @brief Git의 개행 변환과 독립된 UTF-8 본문 hash를 기록한다."""
    data = path.read_text(encoding="utf-8").encode("utf-8")
    return {"path": path.relative_to(CODE.parent).as_posix(),
            "text_sha256": hashlib.sha256(data).hexdigest(), "utf8_bytes": len(data)}


def check_reference(value):
    """! @brief 저장소 내부 파일과 지정한 Python 시험 심볼의 존재를 검사한다."""
    parts = value.split("::")
    path = (CODE / parts[0]).resolve()
    require(path.is_relative_to(CODE) and path.is_file(), "근거 파일 없음: " + value)
    if len(parts) > 1:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        nodes = tree.body
        for symbol in ".".join(parts[1:]).split("."):
            match = next((node for node in nodes if getattr(node, "name", None) == symbol), None)
            require(match is not None, "시험 심볼 없음: " + value)
            nodes = getattr(match, "body", [])
    return path


def unique_ids(rows, expected, label):
    """! @brief 개수만 같은 중복/누락을 거부하고 승인 식별자 집합을 검사한다."""
    identities = [row["id"] for row in rows]
    require(len(identities) == len(set(identities)) and set(identities) == expected,
            label + " 식별자의 중복/누락 또는 미지원 ID가 있습니다.")


def validate_trace_links(requirements, acs, cases, verification_groups, apis, supplemental):
    """! @brief 요구/AC/단계/주 검수와 API 연결을 검사하되 수용 판정은 만들지 않는다.

    @details 숫자가 같더라도 잘못된 검수군, 다른 AC의 subcase 또는 바뀐 API
    식별자를 연결하면 감사 생성을 차단한다. 시험 실행과 검수 합격은 별도다.
    """
    requirement_ids = {identity.rsplit("-AC", 1)[0] for identity in acs}
    unique_ids(requirements, requirement_ids, "요구")
    group_ids = {f"VT-{index:03d}" for index in range(1, 31)}
    unique_ids(verification_groups, group_ids, "VT")
    unique_ids(apis, {f"API-{index:03d}" for index in range(1, 31)}, "API")
    unique_ids(supplemental, {f"{prefix}-{index:03d}" for prefix, count in
                              (("DES-URS", 5), ("PERF", 10), ("GUI-SPIKE", 7))
                              for index in range(1, count + 1)}, "보충 조건")
    requirement_map = {row["id"]: row for row in requirements}
    for row in requirements:
        groups = row["verification_groups"]
        require(groups and len(groups) == len(set(groups)) and set(groups) <= group_ids,
                "요구의 VT 연결이 유효하지 않습니다: " + row["id"])
        expected = {identity for identity in acs if identity.rsplit("-AC", 1)[0] == row["id"]}
        linked = row["acceptance_criteria"]
        require(len(linked) == len(set(linked)) and set(linked) == expected,
                "요구의 AC 연결이 다릅니다: " + row["id"])
    subcases = [row["subcase"] for row in cases]
    require(len(subcases) == len(set(subcases)) and {row["ac_id"] for row in cases} == set(acs),
            "AC subcase의 중복 또는 추적 누락이 있습니다.")
    for row in cases:
        ac_id = row["ac_id"]
        match = re.fullmatch(r"(VT-\d{3})/" + re.escape(ac_id) + r"\.(R[123])", row["subcase"])
        require(match is not None, "subcase의 AC 귀속 또는 단계 형식이 다릅니다: " + row["subcase"])
        group, stage = match.groups()
        owner = requirement_map[ac_id.rsplit("-AC", 1)[0]]
        require(group in group_ids and group in owner["verification_groups"],
                "subcase의 VT가 요구 연결에 없습니다: " + row["subcase"])
        original_stage, separator, selected_stage = row["stage"].partition(";")
        require(separator and original_stage.strip() == acs[ac_id]["stage"]
                and selected_stage.strip() == stage and stage in acs[ac_id]["stage"].split("/"),
                "subcase 단계가 원문 AC와 다릅니다: " + row["subcase"])
    grouped = [subcase for group in verification_groups for subcase in group["subcases"]]
    require(len(grouped) == len(subcases) and set(grouped) == set(subcases), "VT의 subcase 연결에 누락/중복이 있습니다.")
    for group in verification_groups:
        require(all(subcase.startswith(group["id"] + "/") for subcase in group["subcases"]),
                "다른 VT의 subcase가 연결되었습니다: " + group["id"])
    methods = [row["method"] for row in apis]
    require(len(methods) == len(set(methods)), "API 메서드가 중복됩니다.")
    for row in apis:
        descriptor = row["descriptor"]
        require(row["advertised"] is (descriptor is not None), "API 등록 상태와 descriptor가 다릅니다: " + row["id"])
        if descriptor is not None:
            require(descriptor.get("api_id") == row["id"], "API ID와 capability descriptor가 다릅니다: " + row["method"])


def build():
    """! @brief 141개 요구/404개 AC/407개 검수 subcase를 함수 감사와 연결한다."""
    directory = CODE / "docs/audit"
    functions = []
    for name in ("design_functions.json", "analysis_functions.json"):
        functions.extend(json.loads((directory / name).read_text(encoding="utf-8")))
    function_map = {row["id"]: row for row in functions}
    require(len(functions) == len(function_map) == 46, "46개 FN의 고유 감사가 필요합니다.")
    require(set(function_map) == {f"FN-{i:03d}" for i in range(1, 47)}, "FN 집합 불일치")
    files = set()
    for row in functions:
        require(row["implementation_status"] in {"partial", "not_implemented", "implemented_scope", "deferred"}, row["id"])
        require(row["gaps"] and (row["next_steps"] or row["implementation_status"] == "deferred"), "남은 범위/담당 단계가 필요합니다: " + row["id"])
        require(all(type(i) is int and 2 <= i <= 13 for i in row["next_steps"]), row["id"])
        for category in ("code", "tests", "evidence"):
            for value in row[category]:
                files.add(check_reference(value))
    urs = read("03_RFAD_사용자_요구사항.md")
    trace = read("17_RFAD_요구사항_추적표.md")
    acs = {}
    for match in re.finditer(r"^- \*\*([A-Z]+(?:-[A-Z]+)?-\d{3}-AC\d+)\*\*\s*,\s*(.*?)\s*,\s*출처 (.*?): (.+)$", urs, re.M):
        ac_id, stage, source, text = match.groups()
        require(ac_id not in acs, "중복 AC: " + ac_id)
        acs[ac_id] = {"id": ac_id, "stage": stage, "source": source, "text": text}
    require(len(acs) == 404, f"AC 수 불일치: {len(acs)}")
    requirements = []
    for line in trace.splitlines():
        if not line.startswith('| <a id="trace-'):
            continue
        columns = [s.strip() for s in line.split("|")[1:-1]]
        req_id = re.search(r"\[([A-Z]+(?:-[A-Z]+)?-\d{3})\]", columns[0])[1]
        fn_ids = sorted(set(re.findall(r"\[(FN-\d{3})\]", columns[3])))
        require(fn_ids and set(fn_ids) <= function_map.keys(), req_id)
        requirement_acs = [key for key in acs if key.startswith(req_id + "-AC")]
        require(requirement_acs, "AC가 없는 요구: " + req_id)
        requirements.append({"id": req_id, "stage": columns[0].split("<br>")[-1],
                             "functions": fn_ids, "verification_groups": sorted(set(re.findall(r"\[(VT-\d{3})\]", columns[4]))),
                             "acceptance_criteria": requirement_acs, "acceptance_status": "open",
                             "evidence_scope": "linked_function_review_not_clause_pass",
                             "next_steps": sorted({step for fn in fn_ids for step in function_map[fn]["next_steps"]})})
    require(len(requirements) == len({r["id"] for r in requirements}) == 141, "요구 수 불일치")
    cases = []
    for line in trace.splitlines():
        if not re.match(r"^\| \[[A-Z]+(?:-[A-Z]+)?-\d{3}-AC\d+\]", line):
            continue
        columns = [s.strip() for s in line.split("|")[1:-1]]
        ac_id = re.search(r"\[([^]]+)\]", columns[0])[1]
        require(ac_id in acs, "원문에 없는 AC: " + ac_id)
        cases.append({"ac_id": ac_id, "stage": columns[1], "subcase": columns[2].strip("`"),
                      "assertion_summary": columns[3], "required_evidence": columns[4].split(","),
                      "acceptance_status": "open"})
    require(len(cases) == len({c["subcase"] for c in cases}) == 407, "subcase 수/고유성 불일치")
    require({c["ac_id"] for c in cases} == acs.keys(), "AC 추적 누락")
    vt_source = read("14_RFAD_검증과_수용_기준.md")
    verification_groups = []
    for part in re.split(r"(?=^### VT-)", vt_source, flags=re.M)[1:]:
        match = re.match(r"### (VT-\d{3}) - (.+)", part)
        stage = next(line for line in part.splitlines() if line.startswith("**단계:"))
        verification_groups.append({"id": match[1], "title": match[2], "stage_contract": stage,
                                    "acceptance_status": "open", "subcases": [c["subcase"] for c in cases if c["subcase"].startswith(match[1] + "/")]})
    require(len(verification_groups) == 30, "VT 수 불일치")
    api_source = read("11_RFAD_해석기_어댑터_계약.md")
    with tempfile.TemporaryDirectory(prefix="rfad-audit-") as temporary:
        with ProjectService(Path(temporary), auto_run=False) as service:
            actual = capabilities(service)
    apis = []
    for api_id, method in re.findall(r"^\| (API-\d{3}) `([^`]+)`", api_source, re.M):
        record = actual["methods"].get(method)
        apis.append({"id": api_id, "method": method, "advertised": record is not None,
                     "descriptor": record, "full_contract_accepted": False})
    require(len(apis) == 30, "API 수 불일치")
    gui_source = read("24_RFAD_GUI_선정과_성능_설계.md")
    supplemental = []
    for line in (urs + "\n" + gui_source).splitlines():
        match = re.match(r"^\| ((?:DES-URS|PERF|GUI-SPIKE)-\d{3}) \|", line)
        if match:
            supplemental.append({"id": match[1], "specified_row": line, "acceptance_status": "open"})
    require(len(supplemental) == 22, "추가 설계/성능/GUI 조건 수 불일치")
    validate_trace_links(requirements, acs, cases, verification_groups, apis, supplemental)
    source_names = ["03_RFAD_사용자_요구사항.md", "06_RFAD_기능_설계.md", "11_RFAD_해석기_어댑터_계약.md", "14_RFAD_검증과_수용_기준.md", "17_RFAD_요구사항_추적표.md", "24_RFAD_GUI_선정과_성능_설계.md"]
    profile = {"schema": "rfad.implementation-audit/0.1", "design_baseline": "RFAD-D0-3.4",
               "review_date_kst": "2026-11-12", "reviewed_commit": "1ed9686b8eea5cec3b17931d8655565fbafc72e2",
               "working_tree_review": True,
               "scope": "implementation_gap_review_not_release_acceptance",
               "generator": reference(Path(__file__).resolve()),
               "review_inputs": [reference(directory / name) for name in ("design_functions.json", "analysis_functions.json")],
               "design_sources": [reference(CODE.parent / "01_Docs" / name) for name in source_names],
               "functions": sorted(functions, key=lambda r: r["id"]), "requirements": requirements,
               "acceptance_criteria": list(acs.values()), "acceptance_subcases": cases,
               "verification_groups": verification_groups, "public_api": apis,
               "supplemental_design_conditions": supplemental,
               "source_and_test_files": [reference(path) for path in sorted(files)],
               "capability_scope": "temporary_workspace_no_native_runtime_no_catalog_no_solver_execution",
               "capability_profiles": {key: value for key, value in actual.items()
                                       if key.endswith("_profile") or key in {"profile", "tested_envelopes", "transport"}},
               "extension_methods": {k:v for k,v in actual["methods"].items() if k not in {a["method"] for a in apis}},
               "physics_validated": False, "fabrication_validated": False, "measurement_validated": False}
    return profile


def main():
    """! @brief 명시한 산출물 생성 또는 저장된 산출물의 재현성을 확인한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    profile = build()
    target = CODE / "docs/audit/implementation_matrix.json"
    encoded = json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        require(target.read_text(encoding="utf-8") == encoded, "감사 산출물이 현재 근거와 다릅니다.")
    else:
        target.write_text(encoded, encoding="utf-8")
    lines = ["# 기능별 구현 대조", "", "자동 생성: tools/build_implementation_audit.py. 근거 경로는 Code 기준이다. 시험 연결은 전체 AC 합격을 뜻하지 않는다.", ""]
    for row in profile["functions"]:
        lines.extend(["## " + row["id"], "", "상태: " + row["implementation_status"] + ". 담당 단계: " + ("/".join(map(str, row["next_steps"])) or "R1 이후"), "", row["implemented"], "", "남은 범위:", ""])
        lines.extend("- " + item for item in row["gaps"])
        for category, label in (("code", "코드"), ("tests", "시험"), ("evidence", "기존 실행/설명 근거")):
            lines.extend(["", label + ":", ""])
            lines.extend("- [" + value + "](../../" + value.split("::")[0] + ")" for value in row[category])
            if not row[category]:
                lines.append("- 해당 제품 기능의 근거 없음.")
        lines.extend(["", "계약 확인:", ""])
        lines.extend("- " + item for item in row["contract_notes"])
        lines.append("")
    markdown = "\n".join(lines)
    path = CODE / "docs/audit/function_matrix.md"
    if args.check:
        require(path.read_text(encoding="utf-8") == markdown, "기능 대조 문서가 다릅니다.")
    else:
        path.write_text(markdown, encoding="utf-8")
    print(json.dumps({"requirements": len(profile["requirements"]), "acs": len(profile["acceptance_criteria"]),
                      "subcases": len(profile["acceptance_subcases"]), "functions": len(profile["functions"]),
                      "verification_groups": len(profile["verification_groups"]), "apis": len(profile["public_api"]),
                      "acceptance_passes_claimed": 0, "mode": "checked" if args.check else "generated"}))


if __name__ == "__main__":
    main()
