/** @file @brief 페이지 단위 방사 DTO를 검증하고 표시 데이터로 결합한다. */
#pragma once

#include "studio_types.h"
#include <cmath>
#include <stdexcept>

namespace Studio
{
/** @brief 계산이나 보간 없이 동일 산출물의 연속된 theta 행만 결합한다. */
class RadiationPattern
{
public:
    void Reset()
    {
        m_data = Json::object();
        m_complete = false;
    }

    /** @brief 요청한 산출물과 페이지 경계 및 유한 패턴을 모두 확인한다. */
    void Append(const Json& page, const std::string& artifact, int frequency)
    {
        if (m_complete || page.at("profile") != "rfad.radiation-chart/0.1" || page.at("artifact_id") != artifact ||
            page.at("frequency_index") != frequency || page.at("physics_validated") != false ||
            !page.at("absolute_power_w").is_null())
        {
            throw std::runtime_error("방사 표시 데이터의 산출물 또는 검증 상태가 다릅니다.");
        }
        const auto count = page.at("returned_count").get<std::size_t>();
        const auto total = page.at("theta_count").get<std::size_t>();
        const auto offset = page.at("theta_offset").get<std::size_t>();
        const auto columns = page.at("phi_deg").size();
        const auto prior = m_data.empty() ? 0 : m_data.at("theta_deg").size();
        if (count < 1 || count > 5 || total < 7 || total > 37 || columns < 12 || columns > 72 || offset != prior ||
            offset + count > total || page.at("theta_deg").size() != count)
        {
            throw std::runtime_error("방사 페이지의 순서나 크기가 유효하지 않습니다.");
        }
        for (const auto* key : {"theta_deg", "phi_deg"})
        {
            const auto& axis = page.at(key);
            const bool theta = std::string(key) == "theta_deg";
            double previous = theta && prior > 0 ? m_data.at("theta_deg").back().get<double>() : -1.0;
            if (!axis.is_array())
            {
                throw std::runtime_error("방사 각도 축은 배열이어야 합니다.");
            }
            for (const auto& angle : axis)
            {
                if (!angle.is_number() || !std::isfinite(angle.get<double>()) || angle.get<double>() <= previous ||
                    angle.get<double>() < 0 || angle.get<double>() > (theta ? 180.0 : 359.999))
                {
                    throw std::runtime_error("방사 각도 축의 순서나 범위가 다릅니다.");
                }
                previous = angle.get<double>();
            }
        }
        for (const auto* key : {"directivity_dbi", "gain_dbi", "realized_gain_dbi", "radiation_efficiency"})
        {
            const auto& number = page.at("metrics").at(key);
            if (!number.is_number() || !std::isfinite(number.get<double>()) || std::abs(number.get<double>()) > 1e100)
            {
                throw std::runtime_error("방사 지표가 유효한 표시 범위를 벗어났습니다.");
            }
        }
        for (const auto* key : {"normalized_power", "directivity"})
        {
            const auto& matrix = page.at(key);
            if (!matrix.is_array() || matrix.size() != count)
            {
                throw std::runtime_error("방사 페이지 행 수가 다릅니다.");
            }
            for (const auto& row : matrix)
            {
                if (!row.is_array() || row.size() != columns)
                {
                    throw std::runtime_error("방사 페이지 열 수가 다릅니다.");
                }
                for (const auto& cell : row)
                {
                    if (!cell.is_number() || !std::isfinite(cell.get<double>()) || cell.get<double>() < 0 ||
                        (std::string(key) == "normalized_power" && cell.get<double>() > 1.0 + 1e-12))
                    {
                        throw std::runtime_error("방사 패턴은 유한한 비음수여야 합니다.");
                    }
                }
            }
        }
        if (!m_data.empty())
        {
            for (const auto* key : {"snapshot", "frequency_hz", "frequency_index", "theta_count", "phi_deg", "metrics", "center_m", "radius_m"})
            {
                if (m_data.at(key) != page.at(key))
                {
                    throw std::runtime_error("방사 페이지의 출처나 각도 격자가 바뀌었습니다.");
                }
            }
        }
        const bool complete = offset + count == total;
        if ((complete && !page.at("next_offset").is_null()) ||
            (!complete && page.at("next_offset") != offset + count))
        {
            throw std::runtime_error("방사 페이지의 다음 위치가 잘못되었습니다.");
        }
        if (m_data.empty())
        {
            m_data = page;
        }
        else
        {
            for (const auto* key : {"theta_deg", "normalized_power", "directivity"})
            {
                for (const auto& row : page.at(key))
                {
                    m_data[key].push_back(row);
                }
            }
        }
        m_complete = complete;
    }

    bool Complete() const
    {
        return m_complete;
    }

    const Json& Data() const
    {
        return m_data;
    }

private:
    Json m_data = Json::object();
    bool m_complete = false;
};
}
