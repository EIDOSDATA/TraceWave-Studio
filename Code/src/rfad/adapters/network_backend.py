"""! @brief 고정 scikit-rf 변환을 조건수/잔차 검사 뒤 지연 호출한다."""

from functools import lru_cache
from importlib import metadata
import math

from rfad.domain.network_data import fail


VERSIONS = {"scikit-rf": "2.2.0", "numpy": "2.5.4", "scipy": "1.18.1"}
CONDITION_LIMIT = 1e9
RESIDUAL_LIMIT = 1e-8


def installation_metadata():
    """! @brief 일반 지원 조회에서 NumPy와 native 라이브러리를 import하지 않는다."""
    installed = {}
    for name in VERSIONS:
        try:
            installed[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            installed[name] = None
    return {"name": "scikit-rf", "required": VERSIONS.copy(), "installed": installed,
            "runtime_checked": False, "available": None if installed == VERSIONS else False}


@lru_cache(maxsize=1)
def runtime():
    """! @brief 계산 요청에서만 고정 라이브러리를 읽고 미설치를 명시적으로 거부한다."""
    description = installation_metadata()
    if description["installed"] != VERSIONS:
        fail("고정 네트워크 계산 환경이 필요합니다.", "engine", "E_UNSUPPORTED")
    try:
        import numpy as np
        import scipy
        import skrf
    except (ImportError, OSError) as error:
        fail("네트워크 엔진을 읽을 수 없습니다: " + type(error).__name__, "engine", "E_UNSUPPORTED")
    return np, scipy, skrf, {**description, "runtime_checked": True, "available": True,
                            "condition_limit": CONDITION_LIMIT, "residual_limit": RESIDUAL_LIMIT}


def _condition(np, matrix):
    """! @brief 특이값과 엔진의 미소 고유값 보정 범위를 먼저 검사하여 수치 보정을 차단한다."""
    singular_values = np.linalg.svd(matrix, compute_uv=False)
    largest, smallest = float(singular_values[0]), float(singular_values[-1])
    if smallest == 0:
        return "singular", None
    condition = largest / smallest
    if not math.isfinite(condition) or condition >= CONDITION_LIMIT or smallest <= max(1e-12, largest / CONDITION_LIMIT):
        return "ill_conditioned", condition if math.isfinite(condition) else None
    return "valid", condition


def _convert(matrix, source_kind, target_kind, z0):
    """! @brief 한 주파수의 S/Z/Y 변환과 독립 잔차를 반환하며 실패 표본을 큰 숫자로 바꾸지 않는다."""
    np, _, skrf, engine = runtime()
    value = np.asarray(matrix, dtype=np.complex128)
    count = value.shape[0]
    identity = np.eye(count, dtype=np.complex128)
    reference = np.asarray(z0, dtype=float)
    root = np.diag(np.sqrt(reference))
    inverse_root = np.diag(1 / np.sqrt(reference))
    if source_kind == target_kind:
        return value.tolist(), {"status": "valid", "condition_number": 1.0, "relative_residual": 0.0}, engine
    if source_kind == "S":
        denominator = identity - value if target_kind == "Z" else identity + value
    elif target_kind == "S":
        denominator = value + np.diag(reference if source_kind == "Z" else 1 / reference)
    else:
        denominator = value
    status, condition = _condition(np, denominator)
    diagnostic = {"status": status, "condition_number": condition, "relative_residual": None}
    if status != "valid":
        return None, diagnostic, engine
    functions = {("S", "Z"): skrf.network.s2z, ("S", "Y"): skrf.network.s2y,
                 ("Z", "S"): skrf.network.z2s, ("Y", "S"): skrf.network.y2s,
                 ("Z", "Y"): skrf.network.z2y, ("Y", "Z"): skrf.network.y2z}
    try:
        with np.errstate(all="raise"):
            if source_kind == "S" or target_kind == "S":
                result = functions[source_kind, target_kind](value[None, :, :], z0=reference[None, :], s_def="power")[0]
            else:
                result = functions[source_kind, target_kind](value[None, :, :])[0]
            if source_kind == "S" or target_kind == "S":
                scattering = value if source_kind == "S" else result
                impedance = result if source_kind == "S" else value
                electrical_kind = target_kind if source_kind == "S" else source_kind
                if electrical_kind == "Z":
                    normalized = inverse_root @ impedance @ inverse_root
                    left, right = (identity - scattering) @ normalized, identity + scattering
                else:
                    normalized = root @ impedance @ root
                    left, right = (identity + scattering) @ normalized, identity - scattering
            else:
                left, right = value @ result, identity
            residual = float(np.linalg.norm(left - right) / max(float(np.linalg.norm(right)), 1e-300))
            if not np.all(np.isfinite(result)) or not math.isfinite(residual):
                diagnostic["status"] = "nonfinite"
                return None, diagnostic, engine
    except (np.linalg.LinAlgError, FloatingPointError, ValueError, ZeroDivisionError):
        diagnostic["status"] = "singular"
        return None, diagnostic, engine
    diagnostic["relative_residual"] = residual
    if residual > RESIDUAL_LIMIT:
        diagnostic["status"] = "ill_conditioned"
        return None, diagnostic, engine
    return result.tolist(), diagnostic, engine


def convert(matrix, source_kind, target_kind, z0):
    """! @brief 전처리/SVD의 overflow까지 표본 상태로 돌려주고 원본 값을 수정하지 않는다."""
    np, _, _, engine = runtime()
    try:
        with np.errstate(all="raise"):
            return _convert(matrix, source_kind, target_kind, z0)
    except (np.linalg.LinAlgError, FloatingPointError, OverflowError, ValueError, ZeroDivisionError):
        return None, {"status": "nonfinite", "condition_number": None, "relative_residual": None}, engine
