/** @file @brief 실제 Cartesian 격자선에서 읽기 전용 품질 검토를 계산한다. */
#pragma once

#include <array>
#include <optional>
#include <string>
#include <vector>
#include <nlohmann/json.hpp>

namespace Studio::MeshQuality
{
enum class Metric { MinimumWidth, MaximumWidth, Growth, Aspect, Wavelength };
enum class Zone { Model, Air, Pml, Interface };

struct Span
{
    int axis = 0;
    std::size_t first = 0;
    std::size_t last = 0;
};

struct Finding
{
    Metric metric;
    Zone zone;
    Span region;
    Span worst;
    std::optional<Span> cross;
    double observed;
    double limit;
    std::string setting;
};

struct AxisSummary
{
    double minWidth = 0;
    double maxWidth = 0;
    double maxGrowth = 1;
    double maxAspect = 1;
    double minCellsPerWavelength = 0;
};

struct Report
{
    std::array<std::vector<double>, 3> lines;
    std::array<AxisSummary, 3> axes;
    std::vector<Finding> findings;
    double frequencyHz = 0;
    double modelWavelength = 0;
    double vacuumWavelength = 0;
    double growthLimit = 1.5;
    double aspectLimit = 10;
    double wavelengthLimit = 10;

    /** @brief 구간의 실제 시작과 끝 좌표를 같은 격자에서 읽는다. */
    std::array<double, 2> Bounds(const Span& span) const;
};

/** @brief 격자선마다 셀을 읽어 보존된 기준과 비교하고 연속 경고 구간을 묶는다. */
Report Inspect(const nlohmann::json& mesh, const nlohmann::json& settings);
}
