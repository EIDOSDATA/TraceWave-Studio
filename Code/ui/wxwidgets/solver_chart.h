/** @file @brief 해석 결과 표본을 화면 좌표에만 변환하는 그래프다. */
#pragma once

#include <cstddef>
#include <wx/panel.h>
#include <nlohmann/json.hpp>

/** @brief 제한된 서비스 DTO를 보관하며 물리 값과 원본 주파수를 변경하지 않는다. */
class SolverChart final : public wxPanel
{
public:
    using Json = nlohmann::json;

    explicit SolverChart(wxWindow* parent);
    void SetResult(const Json& value);
    void Clear();
    void SetMetric(int metric);
    std::size_t SampleCount() const;
    std::size_t RenderedFrames() const;

private:
    void Paint(wxPaintEvent& event);

    Json m_result = Json::object();
    int m_metric = 0;
    std::size_t m_frames = 0;
};
