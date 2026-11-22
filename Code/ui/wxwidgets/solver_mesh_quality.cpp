/** @file @brief 축별 격자 품질 및 실제 좌표의 경고를 계산한다. */
#include "solver_mesh_quality.h"

#include <algorithm>
#include <cmath>
#include <iterator>
#include <limits>

namespace Studio::MeshQuality
{
namespace
{
using Json = nlohmann::json;
constexpr std::array<const char*, 3> Axes{"x", "y", "z"};
constexpr double CoordinateTolerance = 1e-9;
constexpr double MinimumCellWidth = 0.0001;

struct Cell
{
    double width;
    Zone zone;
};

/** @brief 모델 외곽 투영과 PML 시작선을 기준으로 실제 셀의 구간을 표시한다. */
Zone Location(double start, double stop, const std::array<double, 2>& model, const std::array<double, 2>& pml)
{
    if (stop <= pml[0] + CoordinateTolerance || start >= pml[1] - CoordinateTolerance)
    {
        return Zone::Pml;
    }
    return std::min(stop, model[1]) - std::max(start, model[0]) > CoordinateTolerance ? Zone::Model : Zone::Air;
}

/** @brief 셀 폭을 낮게 평가하는 지표와 높게 평가하는 지표의 최악값을 나눈다. */
bool LowerIsWorse(Metric metric)
{
    return metric == Metric::MinimumWidth || metric == Metric::Wavelength;
}

/** @brief 접하는 경고 구간에서 가장 나쁜 실제 셀 또는 쌍을 보존한다. */
void AddFinding(std::vector<Finding>& rows, Finding finding)
{
    if (!rows.empty())
    {
        auto& previous = rows.back();
        if (previous.zone == finding.zone && previous.setting == finding.setting && previous.limit == finding.limit &&
            finding.region.first <= previous.region.last)
        {
            previous.region.last = std::max(previous.region.last, finding.region.last);
            const bool worse = LowerIsWorse(finding.metric) ? finding.observed < previous.observed
                                                           : finding.observed > previous.observed;
            if (worse)
            {
                previous.observed = finding.observed;
                previous.worst = finding.worst;
                previous.cross = finding.cross;
            }
            return;
        }
    }
    rows.push_back(std::move(finding));
}

/** @brief 실제 적용된 국부 규칙이 닿은 셀만 해당 조건으로 연결한다. */
std::string LocalSetting(const Json& rules, const Span& span, const Report& report)
{
    const auto bounds = report.Bounds(span);
    for (std::size_t index = 0; index < rules.size(); ++index)
    {
        const auto& axes = rules.at(index).at("axes");
        if (!axes.contains(Axes[span.axis]))
        {
            continue;
        }
        for (const auto& segment : axes.at(Axes[span.axis]).at("segments"))
        {
            const auto limits = segment.at("bounds_mm").get<std::array<double, 2>>();
            if (segment.at("applied").get<bool>() &&
                std::min(limits[1], bounds[1]) - std::max(limits[0], bounds[0]) > CoordinateTolerance)
            {
                return "settings.local_mesh[" + std::to_string(index) + "]";
            }
        }
    }
    return {};
}
}

std::array<double, 2> Report::Bounds(const Span& span) const
{
    const auto& coordinates = lines.at(span.axis);
    return {coordinates.at(span.first), coordinates.at(span.last)};
}

Report Inspect(const Json& mesh, const Json& settings)
{
    Report report;
    const auto& reference = mesh.at("quality_reference");
    report.frequencyHz = reference.at("max_excitation_hz");
    report.modelWavelength = reference.at("model_wavelength_mm");
    report.vacuumWavelength = reference.at("vacuum_wavelength_mm");
    report.wavelengthLimit = reference.at("min_wavelength_cells");
    const auto model = reference.at("model_bounds_mm").get<std::array<std::array<double, 2>, 3>>();
    const auto policy = settings.value("mesh_policy", Json::object());
    report.growthLimit = policy.value("growth_ratio", report.growthLimit);
    const double modelWidth = settings.at("grid_mm");
    const double airWidth = policy.value("air_cell_mm", modelWidth);
    const bool splitFeatures = settings.value("feature_subdivisions", 1) > 1;
    const auto rules = mesh.value("local_mesh_report", Json::object()).value("rules", Json::array());

    std::array<std::vector<Cell>, 3> cells;
    std::array<std::optional<Span>, 3> widestModel;
    for (int axis = 0; axis < 3; ++axis)
    {
        auto& lines = report.lines[axis];
        lines = mesh.at("lines_mm").at(Axes[axis]).get<std::vector<double>>();
        const auto pml = mesh.at("axes").at(Axes[axis]).at("pml_inner_mm").get<std::array<double, 2>>();
        for (std::size_t index = 0; index + 1 < lines.size(); ++index)
        {
            const auto zone = Location(lines[index], lines[index + 1], model[axis], pml);
            cells[axis].push_back({lines[index + 1] - lines[index], zone});
            if (zone == Zone::Model &&
                (!widestModel[axis] || cells[axis].back().width > cells[axis][widestModel[axis]->first].width))
            {
                widestModel[axis] = Span{axis, index, index + 1};
            }
        }
    }

    for (int axis = 0; axis < 3; ++axis)
    {
        auto& summary = report.axes[axis];
        summary.minWidth = std::numeric_limits<double>::infinity();
        summary.minCellsPerWavelength = std::numeric_limits<double>::infinity();
        std::optional<Span> cross;
        double crossWidth = 0;
        for (int other = 0; other < 3; ++other)
        {
            if (axis != other && widestModel[other])
            {
                const auto candidate = *widestModel[other];
                const double width = cells[other][candidate.first].width;
                if (width > crossWidth)
                {
                    cross = candidate;
                    crossWidth = width;
                }
            }
        }
        std::array<std::vector<Finding>, 5> rows;
        for (std::size_t index = 0; index < cells[axis].size(); ++index)
        {
            const auto cell = cells[axis][index];
            const Span span{axis, index, index + 1};
            const bool inside = cell.zone == Zone::Model;
            const double wavelength = inside ? report.modelWavelength : report.vacuumWavelength;
            const double wavelengthCells = wavelength / cell.width;
            const double widthLimit = inside ? modelWidth : airWidth;
            const auto widthSetting = inside || policy.empty() ? "settings.grid_mm" : "settings.mesh_policy.air_cell_mm";
            summary.minWidth = std::min(summary.minWidth, cell.width);
            summary.maxWidth = std::max(summary.maxWidth, cell.width);
            summary.minCellsPerWavelength = std::min(summary.minCellsPerWavelength, wavelengthCells);

            const auto note = [&](Metric metric, Zone zone, const Span& range, double observed, double limit,
                                  std::string setting, std::optional<Span> witness = std::nullopt)
            {
                AddFinding(rows[static_cast<std::size_t>(metric)],
                           {metric, zone, range, range, witness, observed, limit, std::move(setting)});
            };
            if (cell.width < MinimumCellWidth - 1e-12)
            {
                auto setting = LocalSetting(rules, span, report);
                note(Metric::MinimumWidth, cell.zone, span, cell.width, MinimumCellWidth,
                     setting.empty() ? "settings.feature_subdivisions" : std::move(setting));
            }
            if (cell.width > widthLimit + CoordinateTolerance)
            {
                note(Metric::MaximumWidth, cell.zone, span, cell.width, widthLimit, widthSetting);
            }
            if (wavelengthCells < report.wavelengthLimit - CoordinateTolerance)
            {
                auto setting = LocalSetting(rules, span, report);
                note(Metric::Wavelength, cell.zone, span, wavelengthCells, report.wavelengthLimit,
                     setting.empty() ? widthSetting : std::move(setting));
            }
            if (inside && cross)
            {
                const double aspect = crossWidth / cell.width;
                summary.maxAspect = std::max(summary.maxAspect, aspect);
                if (aspect > report.aspectLimit + CoordinateTolerance)
                {
                    auto setting = LocalSetting(rules, *cross, report);
                    note(Metric::Aspect, cell.zone, span, aspect, report.aspectLimit,
                         setting.empty() ? "settings.grid_mm" : std::move(setting), cross);
                }
            }
            if (index + 1 < cells[axis].size())
            {
                const auto next = cells[axis][index + 1];
                const double ratio = std::max(cell.width, next.width) / std::min(cell.width, next.width);
                summary.maxGrowth = std::max(summary.maxGrowth, ratio);
                if (ratio > report.growthLimit + CoordinateTolerance)
                {
                    const auto zone = cell.zone == next.zone ? cell.zone : Zone::Interface;
                    const Span pair{axis, index, index + 2};
                    auto setting = LocalSetting(rules, pair, report);
                    if (setting.empty())
                    {
                        setting = !policy.empty() && zone != Zone::Model ? "settings.mesh_policy.growth_ratio"
                                  : splitFeatures ? "settings.feature_subdivisions" : "settings.grid_mm";
                    }
                    note(Metric::Growth, zone, pair, ratio, report.growthLimit, std::move(setting));
                }
            }
        }
        for (auto& metric : rows)
        {
            report.findings.insert(report.findings.end(), std::make_move_iterator(metric.begin()),
                                   std::make_move_iterator(metric.end()));
        }
    }
    return report;
}
}
