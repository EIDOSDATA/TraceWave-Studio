/** @file @brief 동일 source/pin의 유한 방사 페이지를 계산 없이 결합한다. */
#pragma once
#include "studio_types.h"
#include "result_presentation.h"
#include <cmath>
#include <stdexcept>
#include <string>
class ResultRadiationData
{
public:
    void Reset()
    {
        m_data = nullptr;
        m_complete = false;
    }
    const Json& Data() const
    {
        return m_data;
    }
    bool Complete() const
    {
        return m_complete;
    }
    int Next() const
    {
        return m_data.is_object() && !m_complete ? m_data.at("next_offset").get<int>() : 0;
    }
    /** @brief 연속 페이지, 출처, 표시 조건과 배열 경계를 검증한다. */
    void Append(const Json& page, const Json& description, const Json& options)
    {
        const auto fail = []()
        {
            throw std::runtime_error("방사 응답의 출처, 페이지 또는 배열 경계가 다릅니다.");
        };
        if (m_complete || !ResultUi::Matches(page, description) ||
            page.value("profile", "") != "rfad.result-radiation/0.1" || page.value("physics_validated", true) ||
            !page.at("absolute_power_w").is_null())
        {
            fail();
        }
        for (const std::string key :
             {"frequency_index", "observable", "display_scale", "floor_db", "polarization_basis"})
        {
            if (!options.contains(key) || page.at(key) != options.at(key))
            {
                fail();
            }
        }
        const int count = page.at("returned_count").get<int>(), total = page.at("theta_count").get<int>(),
                  offset = page.at("theta_offset").get<int>();
        const int columns = static_cast<int>(page.at("phi_deg").size());
        const int prior = m_data.is_object() ? static_cast<int>(m_data.at("theta_deg").size()) : 0;
        if (count < 1 || count > 5 || total < 1 || total > 37 || columns < 1 || columns > 72 || offset != prior ||
            offset + count > total || static_cast<int>(page.at("theta_deg").size()) != count)
        {
            fail();
        }
        if ((offset + count == total) != page.at("next_offset").is_null() ||
            (!page.at("next_offset").is_null() && page.at("next_offset") != offset + count))
        {
            fail();
        }
        const auto finite = [](const Json& value)
        {
            return value.is_number() && std::isfinite(value.get<double>());
        };
        const auto complex = [&finite](const Json& value)
        {
            return value.is_array() && value.size() == 2 && finite(value[0]) && finite(value[1]);
        };
        const auto frequencies = page.at("frequency_hz");
        const auto frequency = page.at("frequency_index").get<int>();
        const auto colours = page.at("color_range");
        if (!frequencies.is_array() || frequencies.empty() || frequencies.size() > 3 || frequency < 0 ||
            static_cast<std::size_t>(frequency) >= frequencies.size() || !colours.is_array() || colours.size() != 2 ||
            !finite(colours[0]) || !finite(colours[1]) || colours[0].get<double>() > colours[1].get<double>() ||
            page.value("coordinate_unit", "") != "dimensionless_display")
        {
            fail();
        }
        for (const auto& value : frequencies)
        {
            if (!finite(value) || value.get<double>() <= 0.0)
            {
                fail();
            }
        }
        for (const std::string key : {"theta_deg", "phi_deg"})
        {
            double previous = key == "theta_deg" && prior > 0 ? m_data.at(key).back().get<double>() : -1.0;
            for (const auto& angle : page.at(key))
            {
                if (!finite(angle) || angle.get<double>() <= previous ||
                    angle.get<double>() > (key == "theta_deg" ? 180.0 : 360.0))
                {
                    fail();
                }
                previous = angle.get<double>();
            }
        }
        for (const std::string key :
             {"e_theta", "e_phi", "normalized_power", "directivity", "polarization", "projection"})
        {
            if (!page.at(key).is_array() || static_cast<int>(page.at(key).size()) != count)
            {
                fail();
            }
            for (const auto& row : page.at(key))
            {
                if (!row.is_array() || static_cast<int>(row.size()) != columns)
                {
                    fail();
                }
            }
        }
        for (const auto& row : page.at("projection"))
        {
            for (const auto& point : row)
            {
                const auto xyz = point.at("xyz");
                if (!xyz.is_array() || xyz.size() != 3 || !finite(xyz[0]) || !finite(xyz[1]) || !finite(xyz[2]) ||
                    !finite(point.at("radius")) || point.at("radius").get<double>() < 0.0)
                {
                    fail();
                }
                if (!point.at("color").is_null() && !finite(point.at("color")))
                {
                    fail();
                }
            }
        }
        for (int row = 0; row < count; ++row)
        {
            for (int column = 0; column < columns; ++column)
            {
                if (!complex(page.at("e_theta")[row][column]) || !complex(page.at("e_phi")[row][column]) ||
                    !finite(page.at("normalized_power")[row][column]) || !finite(page.at("directivity")[row][column]))
                {
                    fail();
                }
                const auto& polarization = page.at("polarization")[row][column];
                if (!polarization.is_object() || !complex(polarization.at("rhcp_ri")) ||
                    !complex(polarization.at("lhcp_ri")))
                {
                    fail();
                }
                for (const std::string key : {"relative_phase_deg", "axial_ratio_db"})
                {
                    if (!polarization.at(key).is_null() && !finite(polarization.at(key)))
                    {
                        fail();
                    }
                }
            }
        }
        if (m_data.is_object())
        {
            for (const std::string key :
                 {"artifact_id", "snapshot", "frequency_hz", "frequency_index", "theta_count", "phi_deg", "observable",
                  "display_scale", "floor_db", "polarization_basis", "polarization_convention", "normalization_basis",
                  "normalization_peak_v_s_per_m", "coordinate_unit", "color_range", "color_unit", "metrics"})
            {
                if (page.value(key, Json(nullptr)) != m_data.value(key, Json(nullptr)))
                {
                    fail();
                }
            }
            for (const std::string key :
                 {"theta_deg", "e_theta", "e_phi", "normalized_power", "directivity", "polarization", "projection"})
            {
                for (const auto& row : page.at(key))
                {
                    m_data.at(key).push_back(row);
                }
            }
            m_data["next_offset"] = page.at("next_offset");
        }
        else
        {
            m_data = page;
        }
        m_complete = page.at("next_offset").is_null();
    }

private:
    Json m_data = nullptr;
    bool m_complete = false;
};
