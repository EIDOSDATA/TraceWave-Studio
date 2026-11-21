"""! @brief 두 축대칭 수치법으로 합성 PTH의 유한 패드·접합·급전 저항을 대조한다."""

import argparse
from collections import defaultdict
import json
import math

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import spsolve


CONDUCTIVITY = 58e6
INNER, BARREL, PAD = 0.0003, 0.0004, 0.0009
HEIGHT, PAD_THICKNESS, JOINT_THICKNESS = 0.001, 0.0001, 0.00005


def domain(level, contact_ratio):
    """! @brief 두 유한 원형 패드와 중공 배럴, 양쪽 접합을 별도 체적 재료로 배정한다."""
    r = np.linspace(INNER, PAD, 12 * level + 1)
    z = np.linspace(0, HEIGHT, 20 * level + 1)
    cells = {}
    for i in range(len(r) - 1):
        for j in range(len(z) - 1):
            depth = min(j, len(z) - 2 - j)
            if depth < 2 * level:
                cells[i, j] = ("pad", CONDUCTIVITY)
            elif i < 2 * level:
                cells[i, j] = (("joint", CONDUCTIVITY * contact_ratio) if depth < 3 * level
                               else ("barrel", CONDUCTIVITY))
    return r, z, cells


def potentials(size, triplets, boundary):
    """! @brief 고정 전위의 단자를 적용하고 내부 전위와 단자 전류를 되돌린다."""
    rows, columns, data = zip(*triplets, strict=True)
    matrix = coo_matrix((data, (rows, columns)), shape=(size, size)).tocsr()
    fixed = np.array(list(boundary))
    free = np.setdiff1d(np.arange(size), fixed)
    values = np.zeros(size)
    values[fixed] = list(boundary.values())
    values[free] = spsolve(matrix[free, :][:, free], -matrix[free, :][:, fixed] @ values[fixed])
    current = dict(zip(fixed, (matrix @ values)[fixed], strict=True))
    return values, current


def summarize(current, boundary, powers):
    """! @brief 1 V 급전의 전체 저항, 재료별 소산 및 양단 보존 오차를 보고한다."""
    positive = math.fsum(value for node, value in current.items() if boundary[node] == 1)
    power = math.fsum(powers.values())
    return {"resistance_ohm": 1 / positive, "source_current_a": positive, "power_w": dict(powers),
            "current_relative_residual": abs(math.fsum(current.values()) / positive),
            "power_relative_residual": abs(power / positive - 1)}


def finite_volume(r, z, cells):
    """! @brief 셀 중심을 조화 전도 계수의 플럭스로 연결하고 외곽 급전면에 반 셀을 둔다."""
    nodes = {cell: index for index, cell in enumerate(cells)}
    boundary = {len(nodes): 0, len(nodes) + 1: 1}
    edges, triplets = [], []
    dr, dz = r[1] - r[0], z[1] - z[0]

    def connect(a, b, area, lengths):
        """! @brief 이웃 양쪽의 직렬 반 셀 저항을 계산해 전력도 양쪽에 배정한다."""
        terms = [(region, width / (area * conductivity)) for width, (region, conductivity) in lengths]
        conductance = 1 / sum(resistance for _, resistance in terms)
        edges.append((a, b, conductance, terms))
        triplets.extend(((a, a, conductance), (b, b, conductance), (a, b, -conductance), (b, a, -conductance)))

    for (i, j), item in cells.items():
        node = nodes[i, j]
        for neighbor, area, width in (
            ((i + 1, j), math.tau * r[i + 1] * dz, dr),
            ((i, j + 1), math.pi * (r[i + 1]**2 - r[i]**2), dz),
        ):
            if neighbor in cells:
                connect(node, nodes[neighbor], area, ((width / 2, item), (width / 2, cells[neighbor])))
        if i == len(r) - 2:
            terminal = len(nodes) + int(j >= (len(z) - 1) / 2)
            connect(node, terminal, math.tau * r[-1] * dz, ((dr / 2, item),))
    values, current = potentials(len(cells) + 2, triplets, boundary)
    powers = defaultdict(float)
    for a, b, conductance, terms in edges:
        squared = (conductance * (values[a] - values[b]))**2
        for region, resistance in terms:
            powers[region] += squared * resistance
    return summarize(current, boundary, powers)


def finite_elements(r, z, cells):
    """! @brief 독립 선형 삼각형의 약형으로 축대칭 전도 문제를 조립한다."""
    nodes, elements, triplets, boundary = {}, [], [], {}
    for (i, j), (region, conductivity) in cells.items():
        corners = ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))
        for corner in corners:
            nodes.setdefault(corner, len(nodes))
        if i == len(r) - 2:
            for corner in corners[1:3]:
                boundary[nodes[corner]] = int(j >= (len(z) - 1) / 2)
        for indices in ((0, 1, 2), (0, 2, 3)):
            triangle = [corners[index] for index in indices]
            vertices = np.array([[r[a], z[b]] for a, b in triangle])
            a, b = vertices[1] - vertices[0], vertices[2] - vertices[0]
            twice_area = a[0] * b[1] - a[1] * b[0]
            opposites = np.roll(vertices, -1, axis=0) - np.roll(vertices, 1, axis=0)
            gradients = np.column_stack((opposites[:, 1], -opposites[:, 0])) / twice_area
            stiffness = (conductivity * math.pi * twice_area * np.mean(vertices[:, 0])) * (gradients @ gradients.T)
            ids = [nodes[corner] for corner in triangle]
            triplets.extend((a, b, stiffness[row, col]) for row, a in enumerate(ids) for col, b in enumerate(ids))
            elements.append((ids, region, stiffness))
    values, current = potentials(len(nodes), triplets, boundary)
    powers = defaultdict(float)
    for ids, region, stiffness in elements:
        voltage = values[ids]
        powers[region] += float(voltage @ stiffness @ voltage)
    return summarize(current, boundary, powers)


def lower_bound(contact_ratio):
    """! @brief 같은 전류가 지나는 배럴과 두 분리된 축·반경 구간의 Joule 하한을 구한다."""
    area = math.pi * (BARREL**2 - INNER**2)
    barrel_length = HEIGHT - 2 * (PAD_THICKNESS + JOINT_THICKNESS)
    radial = math.log(PAD / BARREL) / (math.tau * CONDUCTIVITY * PAD_THICKNESS)
    return barrel_length / (CONDUCTIVITY * area) + 2 * (
        radial + JOINT_THICKNESS / (CONDUCTIVITY * contact_ratio * area))


def run():
    """! @brief 고정 세 격자에서 완전 접합과 유한 저항 접합을 각각 대조한다."""
    result = []
    for ratio in (1.0, 0.1):
        observations = []
        for level in (2, 4, 8):
            r, z, cells = domain(level, ratio)
            volume, elements = finite_volume(r, z, cells), finite_elements(r, z, cells)
            observations.append({"level": level, "cells": len(cells), "finite_volume": volume, "finite_elements": elements})
        minimum = lower_bound(ratio)
        finest = observations[-1]
        volume, elements = finest["finite_volume"], finest["finite_elements"]
        if any(min(model["resistance_ohm"] - minimum, *model["power_w"].values()) <= 0 or
               max(model["current_relative_residual"], model["power_relative_residual"]) > 1e-9
               for row in observations for model in (row["finite_volume"], row["finite_elements"])):
            raise ValueError("합성 접합의 Joule 하한, 양단 전류 또는 전력 수지가 다릅니다.")
        if abs(volume["resistance_ohm"] / elements["resistance_ohm"] - 1) > 0.005:
            raise ValueError("합성 접합의 두 독립 격자 풀이의 저항 차이가 0.5%를 넘었습니다.")
        result.append({"joint_conductivity_ratio": ratio, "analytic_resistance_lower_bound_ohm": minimum,
                       "levels": observations})
    if result[1]["levels"][-1]["finite_elements"]["resistance_ohm"] <= result[0]["levels"][-1]["finite_elements"]["resistance_ohm"]:
        raise ValueError("접합 전도도 감소가 단자 저항에 반영되지 않았습니다.")
    return {"schema": "rfad.axisymmetric-pth-junction-reference/0.1", "scope": "synthetic_axisymmetric_dc",
            "native_or_measurement_validated": False, "terminal_voltage_v": [0, 1],
            "geometry_m": {"inner": INNER, "barrel_outer": BARREL, "pad_outer": PAD, "height": HEIGHT,
                           "pad_thickness": PAD_THICKNESS, "joint_thickness": JOINT_THICKNESS},
            "conductivity_s_per_m": CONDUCTIVITY, "cases": result}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(json.dumps(run(), allow_nan=False))
