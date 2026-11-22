/** @file @brief 알려진 Cartesian 좌표에서 품질 계산과 경고 연결을 독립 대조한다. */
#include "solver_mesh_quality.h"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <stdexcept>

namespace
{
using Json = nlohmann::json;
using Studio::MeshQuality::Metric;
using Studio::MeshQuality::Zone;

void Check(bool condition, const char* message)
{
    if (!condition)
    {
        throw std::runtime_error(message);
    }
}

bool Near(double actual, double expected)
{
    return std::abs(actual - expected) < 1e-10;
}

/** @brief 재료 파장과 공기 파장, 가변 폭과 실제 직교 셀을 각각 시험한다. */
void CheckFiniteGrid()
{
    const Json mesh{
        {"quality_reference", {{"max_excitation_hz", 1e9}, {"min_wavelength_cells", 10},
         {"vacuum_wavelength_mm", 20}, {"model_wavelength_mm", 2},
         {"model_bounds_mm", {{0, 1}, {0, 1}, {0, .2}}}}},
        {"lines_mm", {{"x", {-3, -2, -1, 0, .02, .2, 1, 2, 3}},
                      {"y", {-3, -2, -1, 0, .5, 1, 2, 3}},
                      {"z", {-3, -2, -1, 0, .1, .2, 1, 2, 3}}}},
        {"axes", {{"x", {{"pml_inner_mm", {-2, 2}}}}, {"y", {{"pml_inner_mm", {-2, 2}}}},
                  {"z", {{"pml_inner_mm", {-2, 2}}}}}},
        {"local_mesh_report", {{"rules", Json::array({
            Json{{"axes", {{"x", {{"segments", Json::array({
                 Json{{"bounds_mm", {0, .2}}, {"applied", true}}})}}}}}}
        })}}}
    };
    const Json settings{{"grid_mm", .5}, {"mesh_policy", {{"air_cell_mm", 1}, {"growth_ratio", 1.45}}}};
    const auto report = Studio::MeshQuality::Inspect(mesh, settings);
    const auto& x = report.axes[0];
    Check(Near(x.minWidth, .02) && Near(x.maxWidth, 1) && Near(x.maxGrowth, 50), "셀 폭 또는 인접비");
    Check(Near(x.maxAspect, 25) && Near(x.minCellsPerWavelength, 2.5), "직교비 또는 파장당 셀 수");
    Check(Near(report.axes[2].minCellsPerWavelength, 20) && Near(report.growthLimit, 1.45),
          "공기/모델 기준과 저장 성장률");

    const auto find = [&](int axis, Metric metric, Zone zone) -> const Studio::MeshQuality::Finding&
    {
        const auto row = std::find_if(report.findings.begin(), report.findings.end(), [&](const auto& item)
        {
            return item.region.axis == axis && item.metric == metric && item.zone == zone;
        });
        Check(row != report.findings.end(), "기준 이탈 구간 누락");
        return *row;
    };
    const auto& aspect = find(0, Metric::Aspect, Zone::Model);
    Check(aspect.cross && aspect.cross->axis == 1 && Near(aspect.observed, 25) &&
              report.Bounds(*aspect.cross) == std::array<double, 2>{0, .5} &&
              report.Bounds(aspect.worst) == std::array<double, 2>{0, .02}, "종횡비의 실제 직교 구간");
    const auto& interface = find(0, Metric::Growth, Zone::Interface);
    Check(interface.setting == "settings.local_mesh[0]" && Near(interface.observed, 50) &&
              report.Bounds(interface.worst) == std::array<double, 2>{-1, .02}, "경계 인접 쌍과 국부 설정");
    const auto& paired = find(0, Metric::Growth, Zone::Model);
    Check(report.Bounds(paired.region) == std::array<double, 2>{0, 1} &&
              report.Bounds(paired.worst) == std::array<double, 2>{0, .2}, "연속 구간과 최악 쌍 구분");
    const auto& wavelength = find(0, Metric::Wavelength, Zone::Model);
    Check(wavelength.setting == "settings.grid_mm" && Near(wavelength.observed, 2.5) &&
              report.Bounds(wavelength.worst) == std::array<double, 2>{.2, 1}, "파장 기준 이탈과 수정 경로");
    const auto& width = find(0, Metric::MaximumWidth, Zone::Model);
    Check(Near(width.observed, .8) && Near(width.limit, .5), "실제 최대 폭의 기준");
}
}

int main()
{
    try
    {
        CheckFiniteGrid();
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << "\n";
        return 1;
    }
    return 0;
}
