"""! @brief 검사 단위/범위/미평가와 위반 위치를 결과 상태와 분리하여 보고한다."""

from collections import Counter
import math

from rfad.application.canonical import canonical_hash


class Report:
    """! @brief 모든 판정의 개수를 유지하며 화면 목록만 유한하게 제한한다."""

    def __init__(self, document, scope):
        """! @brief 검사의 불변 개정과 요청 범위를 고정한다."""
        self.document, self.scope = document, scope
        self.counts, self.checks, self.issues = Counter(), [], []

    def add(self, rule, status, message, *, objects=(), paths=(), measured=None, limit=None,
            unit="mm", sources=(), location=None, details=None):
        """! @brief 단일 판정을 기록하며 미평가를 합격으로 집계하지 않는다."""
        row = {"rule":rule, "status":status, "message":message, "object_ids":list(objects),
               "field_paths":list(paths), "measured":measured, "limit":limit, "unit":unit,
               "source_refs":list(sources), "location_mm":location, "details":details or {}}
        row["id"] = canonical_hash({"revision":self.document["revision_id"], "scope":self.scope, **row})
        row["severity"] = "blocking" if status == "failed" else ("warning" if status == "not_evaluated" else "info")
        self.counts[status] += 1
        if len(self.checks) < 256:
            self.checks.append(row)
        if status in ("failed", "not_evaluated") and len(self.issues) < 128:
            self.issues.append(row)
        elif status == "failed":
            for index, previous in enumerate(self.issues):
                if previous["status"] != "failed":
                    self.issues[index] = row
                    break
        return status

    def bound(self, rule, measured, raw, *, maximum=False, guard=0.0, **context):
        """! @brief 해당 없음/미정/경계 보호 구간과 실제 한계 위반을 구분한다."""
        unit = context.pop("unit", "mm")
        value = raw["value_si"]
        limit = None if value is None else value * (1000 if unit == "mm" else 1)
        if raw["status"] == "not_applicable":
            status, message = "not_applicable", "명시적으로 적용하지 않는 제약입니다."
        elif limit is None or measured is None or not math.isfinite(limit) or not math.isfinite(measured):
            status, message = "not_evaluated", "필요한 한계 또는 측정 치수가 미정/미지원입니다."
            limit = limit if limit is None or math.isfinite(limit) else None
            measured = measured if measured is None or math.isfinite(measured) else None
        elif 0 < abs(measured - limit) <= guard:
            status, message = "not_evaluated", "float64 경계 보호 구간이므로 합격을 확정하지 않습니다."
        else:
            status = "passed" if (measured <= limit if maximum else measured >= limit) else "failed"
            message = "선언한 한계를 만족합니다." if status == "passed" else "선언한 강제 한계를 위반합니다."
        return self.add(rule, status, message, measured=measured, limit=limit, unit=unit,
                        sources=raw["source_refs"], **context)

    def result(self, connectivity, stats):
        """! @brief 검사 성공과 전체 평가/물리 검증 완료를 다른 필드로 반환한다."""
        count = sum(self.counts.values())
        issues = self.counts["failed"] + self.counts["not_evaluated"]
        return {"profile":"rfad.design-checks/0.1", "project_id":self.document["project_id"],
                "revision_id":self.document["revision_id"], "scope":self.scope,
                "status":"failed" if self.counts["failed"] else ("not_evaluated" if self.counts["not_evaluated"] else "passed"),
                "counts":{name:self.counts[name] for name in ("passed","failed","not_evaluated","not_applicable")},
                "checks":self.checks, "issues":self.issues, "check_count":count, "issue_count":issues,
                "checks_truncated":count > len(self.checks), "issues_truncated":issues > len(self.issues),
                "connectivity":connectivity, "statistics":stats, "geometry_method":"analytic_segments_circular_arcs_float64",
                "numeric_guard_is_metrology_uncertainty":False, "automatic_repair":False,
                "solver_ready":False, "physics_verified":False, "manufacturing_verified":False}


def blocking_diagnostics(report):
    """! @brief 기존 입력 검사에는 확인된 위반만 추가하며 미정 상태를 합격으로 승격하지 않는다."""
    return [{"code":"E_DESIGN_CONSTRAINT", "severity":"blocking", "message_ko":row["message"],
             "entity_ids":row["object_ids"], "field_paths":row["field_paths"],
             "details":row, "suggested_actions":["제약/연결/DRC에서 현재 개정을 다시 검사하십시오."], "recoverable":True}
            for row in report["issues"] if row["status"] == "failed"]
