"""! @brief 고정 PCB 사례를 독립적인 Netgen/NGSolve 유한요소법으로 계산한다."""

import argparse
from itertools import product
import json
import math
import sys
from pathlib import Path

from netgen.meshing import Mesh, MeshPoint, Pnt, Element3D, Element2D, FaceDescriptor
import ngsolve as ng
import numpy as np


def spans(knots, max_step):
    """! @brief 재료 경계를 고정한 채 각 구간만 등분한다."""
    return np.concatenate([np.linspace(a, b, math.ceil((b - a) / max_step), endpoint=False)
                           for a, b in zip(knots, knots[1:])] + [[knots[-1]]])


def mesh_case(case, frequency, step, skin_cells):
    """! @brief 양쪽 동박 표피를 분리하고 서로 대응하는 X/Y 면 점을 연결한다."""
    k0 = 2 * np.pi * frequency / 299792458000
    conductivity = case["materials"]["copper"]["conductivity_s_per_m"]
    skin = 1000 * math.sqrt(2 / (2 * np.pi * frequency * (4e-7 * np.pi) * conductivity))
    width, height = case["period_mm"]
    points = case["layers"][0]["regions"][0]["outer"]
    xs = sorted({p[0] for p in points})
    ys = sorted({p[1] for p in points})
    foil = case["layers"][0]["thickness_mm"]
    total = foil + case["layers"][1]["thickness_mm"]
    padding = 8
    skin_edges = skin * np.linspace(0, 4, skin_cells + 1)
    z = np.unique(np.round(np.concatenate((spans([-padding, 0], step), skin_edges,
                                           foil - skin_edges, spans([foil, total, total + padding], step))), 12))
    x, y = spans([0, *xs, width], step), spans([0, *ys, height], step)
    if any(xa != xb and ya != yb for (xa, ya), (xb, yb) in zip(points, points[1:] + points[:1])):
        raise ValueError("검증 도구는 X/Y에 평행한 동박 윤곽을 사용합니다.")
    nx, ny, nz = len(x) - 1, len(y) - 1, len(z) - 1
    mesh = Mesh(dim=3)
    nodes = {key: mesh.Add(MeshPoint(Pnt(k0*x[key[0]], k0*y[key[1]], k0*z[key[2]])))
             for key in product(range(nx + 1), range(ny + 1), range(nz + 1))}
    for j, k in product(range(ny + 1), range(nz + 1)):
        mesh.AddPointIdentification(nodes[0, j, k], nodes[nx, j, k], 1)
    for i, k in product(range(nx + 1), range(nz + 1)):
        mesh.AddPointIdentification(nodes[i, 0, k], nodes[i, ny, k], 2)
    for material, name in enumerate(("air", "substrate", "copper"), 1):
        mesh.SetMaterial(material, name)
    corners = ((0,0,0), (1,0,0), (1,1,0), (0,1,0), (0,0,1), (1,0,1), (1,1,1), (0,1,1))
    for i, j, k in product(range(nx), range(ny), range(nz)):
        cx, cy, cz = (x[i] + x[i+1])/2, (y[j] + y[j+1])/2, (z[k] + z[k+1])/2
        crosses = [(ya > cy) != (yb > cy) and cx < xa
                   for (xa, ya), (_, yb) in zip(points, points[1:] + points[:1])]
        copper = sum(crosses) % 2 == 1
        material = 3 if 0 < cz < foil and copper else 2 if foil < cz < total else 1
        mesh.Add(Element3D(material, [nodes[i+a,j+b,k+c] for a,b,c in corners]))
    for idx, name in enumerate(("front", "back"), 1):
        mesh.Add(FaceDescriptor(surfnr=idx, domin=1, bc=idx))
        mesh.SetBCName(idx - 1, name)
    for k, index, quad in ((0, 1, ((0,0),(0,1),(1,1),(1,0))), (nz, 2, ((0,0),(1,0),(1,1),(0,1)))):
        for i, j in product(range(nx), range(ny)):
            mesh.Add(Element2D(index, [nodes[i+a,j+b,k] for a,b in quad]))
    mesh.Compress()
    return ng.Mesh(mesh), k0, padding, total


def real_imag(value):
    """! @brief 복소 접선 전계를 JSON 숫자 쌍으로 변환한다."""
    return [float(value.real), float(value.imag)]


def solve(case, frequency, step, skin_cells, port_order, order):
    """! @brief Bloch 포락선으로 curl-curl 약형과 외부 복사 조건을 푼다."""
    mesh, k0, padding, total = mesh_case(case, frequency, step, skin_cells)
    fes = ng.Periodic(ng.HCurl(mesh, order=order, complex=True))
    u, v = fes.TnT()
    theta, phi = np.radians([case["theta_deg"], case["phi_deg"]])
    kt = np.sin(theta)*np.array([np.cos(phi), np.sin(phi)])
    def cross(w):
        """! @brief 주기 포락선의 curl에 입사 접선 파수를 더한다."""
        return ng.CF((kt[1] * w[2], -kt[0] * w[2], kt[0] * w[1] - kt[1] * w[0]))

    def dot(a, b):
        """! @brief 켤레의 위치를 약형에서 직접 적용할 선형 내적을 계산한다."""
        return sum(a[i] * b[i] for i in range(3))

    materials = {name: m["epsilon_r"]*(1+1j*m["tan_delta"])
                 +1j*m["conductivity_s_per_m"]/(2*np.pi*frequency*8.8541878128e-12)
                 for name,m in case["materials"].items()}
    eps = mesh.MaterialCF(materials)
    a = ng.BilinearForm(fes)
    a += (dot(ng.curl(u)+1j*cross(u), ng.curl(v)-1j*cross(v))-eps*dot(u,v))*ng.dx
    a += -1j*dot(u.Trace(), v.Trace())*ng.ds
    a.Assemble()
    print(f"FEM dofs={fes.ndof} step={step} skin_cells={skin_cells}", file=sys.stderr, flush=True)

    period = k0 * np.array(case["period_mm"])
    area = np.prod(period)
    entries, port, waves = [], [], []
    incident_pol = 0 if case["polarization"] == "TE" else 1
    for nx,ny in product(range(-port_order, port_order+1), repeat=2):
        gx,gy = 2*np.pi*np.array([nx,ny])/period
        kx,ky = kt + [gx,gy]
        q = np.sqrt(complex(1-kx*kx-ky*ky))
        radius = np.hypot(kx, ky)
        p = np.array([kx, ky]) / radius if radius else np.array([np.cos(phi), np.sin(phi)])
        harmonic = ng.exp(1j*(gx*ng.x + gy*ng.y))
        for pol, (px,py,y) in enumerate(((-p[1],p[0],q),(p[0],p[1],1/q))):
            for side in ("front", "back"):
                integrand = harmonic * (px*v.Trace()[0]+py*v.Trace()[1])
                lf = ng.LinearForm(fes)
                lf += integrand * ng.ds(side, bonus_intorder=8)
                lf.Assemble()
                entries.append(lf.vec.FV().NumPy().copy())
                waves.append(((nx,ny), pol, side, q, y))
                port.append(-1j*(y-1)/area)
    entries = np.stack(entries, axis=1)
    port = np.asarray(port)
    source = next(i for i, item in enumerate(waves) if item[:3] == ((0,0),incident_pol,"front"))
    q0, y0 = waves[source][-2:]
    rhs = entries[:,source] * (-2j*y0*np.exp(-1j*q0*k0*padding))

    # @brief 국소 Robin 행렬을 인수분해하고 외부 Fourier 어드미턴스는 저계수 보정으로 적용한다.
    free = np.asarray(list(fes.FreeDofs()), dtype=bool)
    from scipy.sparse import coo_matrix
    from scipy.sparse.linalg import splu
    rows, cols, values = a.mat.COO()
    matrix = coo_matrix((values,(rows,cols)),shape=(fes.ndof,fes.ndof)).tocsc()[free,:][:,free]
    inverse = splu(matrix)
    reduced = entries[free]
    scattered = inverse.solve(rhs[free])
    response = inverse.solve(reduced)
    overlap = reduced.conj().T @ response
    coefficients = np.linalg.solve(np.eye(len(port)) + overlap * port, reduced.conj().T @ scattered)
    solution = scattered - response @ (port * coefficients)
    field = ng.GridFunction(fes)
    field.vec.FV().NumPy()[free] = solution

    powers = {"reflected": 0.0, "transmitted": 0.0}
    report = {}
    for i, ((nx,ny),pol,side,q,y) in enumerate(waves):
        if q.imag != 0:
            continue
        amplitude = coefficients[i]/area
        if side == "front":
            if i == source:
                amplitude -= np.exp(-1j*q0*k0*padding)
            amplitude *= np.exp(-1j*q*k0*padding)
            channel = "reflected"
        else:
            amplitude *= np.exp(-1j*q*k0*padding)
            channel = "transmitted"
        power = abs(amplitude)**2 * (y/y0).real
        powers[channel] += power
        report[f"{nx},{ny},{pol},{side}"] = {"amplitude_ri": real_imag(amplitude), "power": float(power)}
    absorption = {name: ng.Integrate(dot(field,ng.Conj(field))*materials[name].imag, mesh,
                                     definedon=mesh.Materials(name)).real/(area*y0.real)
                  for name in ("substrate","copper")}
    powers["absorbed"] = sum(absorption.values())
    phase = np.exp(1j * kt * period)
    return {"frequency_hz": frequency, "dofs": fes.ndof,
            "boundary_factor_ri": [real_imag(v) for v in phase], "power": powers, "absorption": absorption,
            "residual": abs(1 - sum(powers.values())), "orders": report}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case", type=Path)
    parser.add_argument("--frequency", type=float, required=True)
    parser.add_argument("--step", type=float, default=4)
    parser.add_argument("--skin-cells", type=int, default=4)
    parser.add_argument("--port-order", type=int, default=2)
    parser.add_argument("--order", type=int, default=1)
    args = parser.parse_args()
    ng.SetNumThreads(3)
    case = json.loads(args.case.read_text(encoding="utf-8"))
    if (len(case["layers"]) != 2 or len(case["layers"][0]["regions"]) != 1 or case["layers"][1]["regions"]
            or case["epsilon_left"] != 1 or case["epsilon_right"] != 1
            or case["layers"][0]["background"] != "air" or case["layers"][1]["background"] != "substrate"
            or case["layers"][0]["regions"][0]["material"] != "copper" or case["layers"][0]["regions"][0]["holes"]):
        parser.error("첫 층에 동박 윤곽 하나, 둘째 층에 균질 기판, 외부에 공기가 필요합니다.")
    if not (args.frequency > 0 and args.step > 0 and args.skin_cells >= 1 and args.port_order >= 1 and args.order in (0, 1)):
        parser.error("유한 양의 계산 조건과 유한요소 차수 0 또는 1이 필요합니다.")
    result = solve(case, args.frequency, args.step, args.skin_cells, args.port_order, args.order)
    print(json.dumps(result, indent=2))
