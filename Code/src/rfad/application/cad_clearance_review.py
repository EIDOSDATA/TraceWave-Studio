"""! @brief 현재 해석 개정과 같은 CAD 패키지의 STEP 간극 증거점을 실제 Yee 셀에 대응한다."""

import json
import math

from rfad.application.cad_verification import verification_input
from rfad.application.canonical import canonical_hash
from rfad.application.pcb_clearance_review import _crossed_cells
from rfad.domain.errors import ProjectError
from rfad.domain.object_names import display_names
from rfad.domain.physical_setup import candidates


def _clip(points, lines):
    """! @brief 격자 경계에 선분을 자르고 전체 포함, 일부 포함 또는 외부를 구분한다."""
    first, last = 0.0, 1.0
    for axis, low, high in zip("xyz", points[0], points[1]):
        pos = lines[axis]
        delta = high - low
        if delta == 0:
            if not pos[0] <= low <= pos[-1]:
                return None
            continue
        a, b = sorted(((pos[0] - low) / delta, (pos[-1] - low) / delta))
        first, last = max(a, first), min(b, last)
        if first > last:
            return None
    clipped = [[min(max(x + (y - x) * t, lines[axis][0]), lines[axis][-1])
                for axis, x, y in zip("xyz", *points)] for t in (first, last)]
    if first == last:
        return "boundary_point", clipped
    return ("inside" if first == 0 and last == 1 else "partial"), clipped


def map_witness(record, lines, names):
    """! @brief CAD의 XYZ 원문과 거리, 접촉 상태를 보존하고 격자 안의 구간만 표시한다."""
    points, distance = record.get("witness_points_mm"), record.get("clearance_mm")
    row = {"object_ids": [record["id"], record["nearest_id"]], "distance_mm": distance,
           "object_names": [names.get(key, key or "상대 바디 없음") for key in (record["id"], record["nearest_id"])],
           "relation": record["relation"], "source": "cad_mechanical", "em_included": False}
    if points is None or distance is None:
        row["grid_state"] = "unavailable"
        return row
    if (type(points) is not list or len(points) != 2 or any(type(p) is not list or len(p) != 3 for p in points)
            or any(type(v) not in (int, float) or not math.isfinite(v) for p in points for v in p)
            or type(distance) not in (int, float) or not math.isfinite(distance) or distance < 0
            or abs(math.dist(*points) - distance) > max(1e-6, distance * 1e-8)):
        raise ProjectError("E_HASH", "CAD 간극 거리와 두 증거점이 일치하지 않습니다.")
    row["witness_points_mm"] = points
    clipped = _clip(points, lines)
    if clipped is None:
        row["grid_state"] = "outside"
        return row
    row["grid_state"], endpoints = clipped
    row["clipped_points_mm"] = endpoints
    row["cells_xyz"] = _crossed_cells(*endpoints, lines)
    return row


def review(service, state, document, lines):
    """! @brief 다른 프로젝트나 다른 개정의 완료 작업을 배제하고 봉인된 manifest에서 검토를 읽는다."""
    parts = {row["id"]: row["name"] for row in candidates(document)[1] if row["kind"] == "step"}
    if not parts:
        return None
    jobs = [job for job in state["jobs"].values() if job["state"] == "completed"
            and job["operation_method"] in {"export.build", "geometry.build"} and "cad" in job
            and job["context"].get("project_id") == document["project_id"]]
    current = [job for job in jobs if job["snapshot"]["revision_id"] == document["revision_id"]]
    if not current:
        return {"rows": [], "status": "stale" if jobs else "missing",
                "message": "현재 개정의 봉인된 CAD가 없습니다. 현재 설계에서 3D 모델 또는 STEP을 생성하세요."}
    current.sort(key=lambda job: (job["events"][-1]["timestamp"], job["job_id"]), reverse=True)
    checked = set()
    considered = set()
    output = []
    try:
        for job in current:
            purpose = job["operation_method"]
            if purpose in considered:
                continue
            considered.add(purpose)
            snapshot = job["snapshot"]
            if snapshot["content_hash"] != canonical_hash(document):
                raise ProjectError("E_HASH", "CAD 스냅샷과 현재 설계 원본이 다릅니다.")
            roles = {row["role"]: row for row in job["artifacts"]}
            info = {"job_id": job["job_id"], "manifest_sha256": roles["manifest"]["sha256"]}
            _, data = verification_input(service, state, {"project_id": document["project_id"]}, info)
            if not 0 < roles["validation"]["bytes"] <= 1024 * 1024:
                raise ProjectError("E_RESOURCE", "CAD 검증 파일이 허용 크기를 초과했습니다.")
            sidecar = json.loads(service.journal.read_artifact(data["files"]["sidecar.json"]))
            validation = json.loads(service.journal.read_artifact(roles["validation"]))
            if validation != sidecar["verification"] or validation.get("status") != "passed_same_kernel":
                raise ProjectError("E_HASH", "봉인된 CAD sidecar와 배치 검증 파일이 다릅니다.")
            bodies = {row["id"]: row for row in sidecar["body_map"]}
            names = {key: row["name"] for key, row in bodies.items()}
            names.update(display_names(document))
            names.update({row["id"]: row["name"] for row in document["stackup"]})
            names.update(parts)
            for record in validation.get("environment_placement", []):
                key = record["id"]
                if key in checked or key not in parts:
                    continue
                if (key not in bodies or "source_step" not in bodies[key] or
                        (record["nearest_id"] is not None and record["nearest_id"] not in bodies)):
                    raise ProjectError("E_HASH", "STEP 환경의 증거점에 대응하는 CAD 바디가 없습니다.")
                row = map_witness(record, lines, names)
                row.update(**info, snapshot_id=snapshot["snapshot_id"], revision_id=snapshot["revision_id"])
                output.append(row)
                checked.add(key)
            if checked == parts.keys():
                break
    except (ProjectError, ValueError, KeyError, TypeError) as error:
        return {"rows": [], "status": "invalid", "message": "CAD 봉인 검토 실패: " + str(error)}
    return {"rows": output, "status": "available" if checked == parts.keys() else "partial",
            "message": f"현재 개정 CAD 기계 간극 {len(output)}/{len(parts)}개. STEP 형상은 전자기 해석에 포함되지 않습니다."}
