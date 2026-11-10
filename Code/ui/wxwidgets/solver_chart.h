#pragma once

#include <wx/wx.h>
#include <wx/dcbuffer.h>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

/** @brief 제한된 서비스 결과 DTO를 그리며 정규화나 물리 계산을 반복하지 않는다. */
class SolverChart final : public wxPanel
{
public:
    using Json = nlohmann::json;

    explicit SolverChart(wxWindow* parent) : wxPanel(parent)
    {
        SetBackgroundStyle(wxBG_STYLE_PAINT);
        Bind(wxEVT_PAINT, &SolverChart::Paint, this);
        Bind(wxEVT_SIZE, [this](wxSizeEvent& event)
        {
            Refresh(false);
            event.Skip();
        });
    }

    /** @brief 실제 결과 주파수 축과 유한 표시 값을 확인한 뒤 교체한다. */
    void SetResult(const Json& value)
    {
        if (value.value("profile", "") != "rfad.solver-chart/0.1" || !value.at("samples").is_array() ||
            value.at("samples").empty() || value.at("samples").size() > 201)
        {
            throw std::runtime_error("지원하지 않는 해석 표시 데이터입니다.");
        }
        double previous = 0.0;
        for (const auto& row : value.at("samples"))
        {
            const double frequency = row.at("frequency_hz").get<double>();
            if (!std::isfinite(frequency) || frequency <= previous)
            {
                throw std::runtime_error("해석 결과 주파수 축이 유효하지 않습니다.");
            }
            previous = frequency;
            for (const auto* key : {"s11_db", "vswr", "impedance_real_ohm", "impedance_imag_ohm"})
            {
                if (!row.at(key).is_null() && (!row.at(key).is_number() || !std::isfinite(row.at(key).get<double>()) || std::abs(row.at(key).get<double>()) > 1e100))
                {
                    throw std::runtime_error("해석 그래프 값은 유한수 또는 미표시 값이어야 합니다.");
                }
            }
        }
        m_result = value;
        Refresh(false);
    }

    void Clear()
    {
        m_result = Json::object();
        Refresh(false);
    }

    void SetMetric(int metric)
    {
        m_metric = metric;
        Refresh(false);
    }

    std::size_t SampleCount() const
    {
        return m_result.empty() ? 0 : m_result.at("samples").size();
    }

    std::size_t RenderedFrames() const
    {
        return m_frames;
    }

private:
    /** @brief null 표본은 선을 끊어 미정/발산 값을 유한한 값으로 위장하지 않는다. */
    void Paint(wxPaintEvent&)
    {
        wxAutoBufferedPaintDC dc(this);
        dc.SetBackground(wxBrush(wxColour(250, 251, 253)));
        dc.Clear();
        const wxSize size = GetClientSize();
        const int left = FromDIP(82), top = FromDIP(30);
        const int width = size.x - left - FromDIP(35), height = size.y - top - FromDIP(65);
        if (m_result.empty() || width < 60 || height < 40)
        {
            dc.DrawText(wxString::FromUTF8("해석 완료 후 S11, VSWR, 임피던스를 표시합니다."), FromDIP(20), FromDIP(20));
            return;
        }
        const std::vector<std::string> keys = m_metric == 0 ? std::vector<std::string>{"s11_db"} :
            (m_metric == 1 ? std::vector<std::string>{"vswr"} : std::vector<std::string>{"impedance_real_ohm", "impedance_imag_ohm"});
        const auto& rows = m_result.at("samples");
        const double first = rows.front().at("frequency_hz"), last = rows.back().at("frequency_hz");
        double low = std::numeric_limits<double>::infinity(), high = -low;
        std::size_t missing = 0;
        for (const auto& row : rows)
        {
            for (const auto& key : keys)
            {
                if (row.at(key).is_null())
                {
                    ++missing;
                }
                else
                {
                    const double value = row.at(key);
                    low = std::min(low, value);
                    high = std::max(high, value);
                }
            }
        }
        if (!std::isfinite(low) || !std::isfinite(high))
        {
            dc.DrawText(wxString::FromUTF8("이 채널에는 표시 가능한 유한 표본이 없습니다."), left, top);
            return;
        }
        const double padding = std::max(0.05 * (high - low), std::max(1.0, std::abs(low)) * 0.01);
        low -= padding;
        high += padding;
        dc.SetTextForeground(wxColour(60, 72, 88));
        for (int i = 0; i <= 4; ++i)
        {
            const int y = top + height * i / 4;
            dc.SetPen(wxPen(wxColour(220, 225, 232)));
            dc.DrawLine(left, y, left + width, y);
            dc.DrawText(wxString::Format("%.4g", high - (high - low) * i / 4), FromDIP(8), y - FromDIP(7));
            const int x = left + width * i / 4;
            dc.DrawLine(x, top, x, top + height);
            dc.DrawText(wxString::Format("%.4g", (first + (last - first) * i / 4) / 1e9), x - FromDIP(18), top + height + FromDIP(8));
        }
        dc.DrawText("GHz", left + width / 2, top + height + FromDIP(32));
        dc.DrawText(m_metric == 0 ? "S11 (dB)" : (m_metric == 1 ? "VSWR" : "Z (ohm): Re / Im"), left, FromDIP(5));
        const wxColour colours[] = {wxColour(31, 115, 195), wxColour(205, 111, 34)};
        dc.SetClippingRegion(left, top, width + 1, height + 1);
        for (std::size_t channel = 0; channel < keys.size(); ++channel)
        {
            dc.SetPen(wxPen(colours[channel], FromDIP(2)));
            bool havePrevious = false;
            wxPoint previous;
            for (const auto& row : rows)
            {
                if (row.at(keys[channel]).is_null())
                {
                    havePrevious = false;
                    continue;
                }
                const double x = (row.at("frequency_hz").get<double>() - first) / std::max(1.0, last - first);
                const double y = (row.at(keys[channel]).get<double>() - low) / (high - low);
                const wxPoint point(left + static_cast<int>(x * width), top + height - static_cast<int>(y * height));
                if (havePrevious)
                {
                    dc.DrawLine(previous, point);
                }
                previous = point;
                havePrevious = true;
            }
        }
        dc.DestroyClippingRegion();
        if (missing)
        {
            dc.DrawText(wxString::FromUTF8("미표시 표본: ") + wxString::Format("%zu", missing), left + FromDIP(150), FromDIP(5));
        }
        ++m_frames;
    }

    Json m_result = Json::object();
    int m_metric = 0;
    std::size_t m_frames = 0;
};
