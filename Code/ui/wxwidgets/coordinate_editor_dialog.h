#pragma once

#include <wx/wx.h>
#include <wx/grid.h>
#include <nlohmann/json.hpp>
#include <array>
#include <functional>
#include <optional>
#include <string>
#include <vector>

/** @brief 좌표 표의 임시 입력과 모드별 위젯을 소유하며 확인한 값만 호출자에게 반환한다. */
class CoordinateEditorDialog final : public wxDialog
{
public:
    using Json = nlohmann::json;
    CoordinateEditorDialog(wxWindow* parent, const Json& descriptor, const Json& original, const Json& coordinateChoices);
    std::optional<Json> Edit(const std::function<void(wxGrid&, wxDialog&)>& opened = {});

private:
    void UpdateMode(int row, int base);
    Json m_original;
    wxGrid* m_grid = nullptr;
    std::array<wxString, 3> m_modeLabels;
    wxArrayString m_parameterLabels;
    std::vector<std::string> m_parameterIds;
};
