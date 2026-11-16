"""! @brief 목표 공간 크기/매개변수 범위를 평가하며 RF 성능 판정은 수행하지 않는다."""

from rfad.domain.check_geometry import scalar
from rfad.domain.errors import ProjectError
from rfad.domain.target_constraints import BOARD_LIMITS
from rfad.domain.units import Quantity, QuantityError


def _board_sizes(document):
    """! @brief 기존 외곽/적층에서만 크기를 읽고 누락된 두께를 만들지 않는다."""
    sizes = {key:None for key in BOARD_LIMITS}
    board = document["board"]
    if board is not None:
        outline = board["outline"]
        try:
            if outline["kind"] == "circle":
                diameter = 2 * scalar(document, outline["radius"])
                sizes.update(board_width_max=diameter, board_height_max=diameter, board_diameter_max=diameter)
            else:
                for key, field in (("board_width_max", "width"), ("board_height_max", "height")):
                    try:
                        sizes[key] = scalar(document, outline[field])
                    except ProjectError:
                        pass
        except ProjectError:
            pass
    try:
        from rfad.domain.physical_setup import setup, stack_review

        layers = [(scalar(document, row["z_min"]), scalar(document, row["thickness"])) for row in document["stackup"]]
        if layers:
            sizes["board_thickness_max"] = (stack_review(document)["full_extent_si"] if setup(document)["surfaces"]
                                            else max(z + t for z, t in layers) - min(z for z, _ in layers))
    except ProjectError:
        pass
    return sizes


def check_constraints(document, targets, report):
    """! @brief 선언한 목표의 강제 제약만 평가하고 원본 값/출처를 보존한다."""
    sizes = _board_sizes(document)
    profiles = set()
    for target in targets:
        constraints = target.get("constraints")
        if constraints is None:
            continue
        prefix = "targets." + target["id"] + ".constraints"
        for key, label in BOARD_LIMITS.items():
            report.bound(key, sizes[key], constraints[key], maximum=True, objects=[target["id"]],
                         paths=[prefix + "." + key], details={"label":label, "target_revision":target["revision_id"]})
        for row in constraints["parameter_bounds"]:
            parameter = document["parameters"][row["parameter_id"]]
            raw = parameter["quantity"]
            dimension = raw["dimension"]
            unit = "mm" if dimension == "length" else raw["display_unit"]
            try:
                actual = None if raw["value_si"] is None else Quantity(**raw).as_unit(unit)
            except QuantityError:
                actual = None
            for key, maximum in (("minimum",False),("maximum",True)):
                limit = row[key]
                if unit not in ("mm", "1"):
                    converted = dict(limit)
                    try:
                        converted["value_si"] = None if limit["value_si"] is None else Quantity(**limit).as_unit(unit)
                    except QuantityError:
                        converted["value_si"] = None
                    limit = converted
                report.bound("parameter_" + key, actual, limit, maximum=maximum, unit=unit,
                             objects=[target["id"], parameter["id"]], paths=[prefix + ".parameter_bounds", "parameters." + parameter["id"]])
            if row["integer"]:
                status = "not_evaluated" if actual is None else ("passed" if actual.is_integer() else "failed")
                report.add("parameter_integer", status, "무차원 정수 제약을 검사합니다.",
                           objects=[target["id"], parameter["id"]], paths=["parameters." + parameter["id"]],
                           measured=actual, unit="1", sources=row["source_refs"])
        if constraints["manufacturing_profile_id"] is not None:
            profiles.add(constraints["manufacturing_profile_id"])
    return profiles
