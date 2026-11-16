/** @file @brief 기록된 두 방위각의 반경만 전체 평면의 표시 좌표로 배치한다. */
#pragma once
#include "studio_types.h"
#include <cmath>
#include <stdexcept>
#include <vector>

struct RadiationPlanePoint
{
    std::size_t thetaIndex;
    std::size_t phiIndex;
    double x;
    double y;
};

/** @brief 반대 방위각은 정확히 기록된 경우만 사용하며 RF 보간이나 미러를 만들지 않는다. */
struct RadiationPlaneCut
{
    int oppositePhi = -1;
    std::vector<RadiationPlanePoint> primary;
    std::vector<RadiationPlanePoint> opposite;

    static RadiationPlaneCut Build(const Json& data, int phiIndex)
    {
        const auto& phis = data.at("phi_deg");
        if (phiIndex < 0 || static_cast<std::size_t>(phiIndex) >= phis.size())
        {
            throw std::runtime_error("선택한 방위각이 기록 범위를 벗어났습니다.");
        }
        RadiationPlaneCut result;
        double other = phis.at(static_cast<std::size_t>(phiIndex)).get<double>() + 180.0;
        if (other >= 360.0)
        {
            other -= 360.0;
        }
        for (std::size_t index = 0; index < phis.size(); ++index)
        {
            if (phis.at(index).get<double>() == other)
            {
                result.oppositePhi = static_cast<int>(index);
                break;
            }
        }
        const auto append = [&data](std::vector<RadiationPlanePoint>& points, int column, double direction)
        {
            for (std::size_t row = 0; row < data.at("theta_deg").size(); ++row)
            {
                const double angle = data.at("theta_deg")[row].get<double>() * 3.14159265358979323846 / 180.0;
                const auto phi = static_cast<std::size_t>(column);
                const double radius = data.at("projection")[row][phi].at("radius").get<double>();
                if (!std::isfinite(radius) || radius < 0.0)
                {
                    throw std::runtime_error("방사 표시 반경이 유한하지 않습니다.");
                }
                points.push_back({row, phi, direction * radius * std::sin(angle), radius * std::cos(angle)});
            }
        };
        append(result.primary, phiIndex, 1.0);
        if (result.oppositePhi >= 0)
        {
            append(result.opposite, result.oppositePhi, -1.0);
        }
        return result;
    }
};
