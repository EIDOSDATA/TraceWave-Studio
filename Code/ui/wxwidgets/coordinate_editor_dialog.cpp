#include "coordinate_editor_dialog.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace
{
/** @brief 화면 입력을 UTF-8 원문으로 돌려준다. */
std::string Utf8(const wxString& value)
{
    const wxScopedCharBuffer buffer = value.utf8_str();
    return std::string(buffer.data(), buffer.length());
}

wxString Display(const std::string& value)
{
    return wxString::FromUTF8(value.data(), value.size());
}
}

CoordinateEditorDialog::CoordinateEditorDialog(wxWindow* parent, const Json& descriptor,
    const Json& original, const Json& coordinateChoices)
    : wxDialog(parent, wxID_ANY, Display(descriptor.at("label").get<std::string>() + " 좌표"),
        wxDefaultPosition, parent->FromDIP(wxSize(940, 480)), wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER),
      m_original(original)
{
    auto* layout = new wxBoxSizer(wxVERTICAL);
    layout->Add(new wxStaticText(this, wxID_ANY, Display("각 좌표의 입력 방식을 고르세요. 숫자는 옆에 표시한 단위를 사용합니다.\n단위는 읽기 전용이며 미정값을 계산값으로 채우지 않습니다. 참조는 목록에서 선택합니다.\n꼭짓점 수는 유지하고 변경 적용 전까지 초안으로 보존합니다.")), 0, wxEXPAND | wxALL, 10);
    m_grid = new wxGrid(this, wxID_ANY);
    auto* grid = m_grid;
    grid->CreateGrid(static_cast<int>(m_original.size()), 8);
    const char* labels[] = {"X 입력", "X 값", "단위", "X 참조", "Y 입력", "Y 값", "단위", "Y 참조"};
    m_modeLabels = {Display("직접 입력"), Display("미정"), Display("매개변수 참조")};
    wxArrayString modeChoices;
    for (const auto& mode : m_modeLabels)
    {
        modeChoices.Add(mode);
    }
    m_parameterLabels.Add(Display("선택 없음"));
    m_parameterIds = {std::string()};
    for (const auto& choice : coordinateChoices)
    {
        const std::string id = choice.at("value");
        if (!id.empty())
        {
            m_parameterIds.push_back(id);
            m_parameterLabels.Add(Display(choice.at("label").get<std::string>() + " / " + id));
        }
    }
    for (int column = 0; column < 8; ++column)
    {
        grid->SetColLabelValue(column, Display(labels[column]));
        grid->SetColSize(column, FromDIP(column % 4 == 3 ? 215 : (column % 4 == 2 ? 45 : 115)));
    }
    grid->SetRowLabelSize(FromDIP(38));
    for (int row = 0; row < grid->GetNumberRows(); ++row)
    {
        for (int axis = 0; axis < 2; ++axis)
        {
            const int base = axis * 4;
            const auto& coordinate = m_original.at(row).at(axis);
            const std::string mode = coordinate.at("mode");
            grid->SetCellEditor(row, base, new wxGridCellChoiceEditor(modeChoices, false));
            grid->SetCellValue(row, base, m_modeLabels[mode == "value" ? 0 : (mode == "missing" ? 1 : 2)]);
            grid->SetCellValue(row, base + 1, Display(coordinate.at("value")));
            grid->SetCellValue(row, base + 2, Display(coordinate.at("unit")));
            grid->SetCellEditor(row, base + 3, new wxGridCellChoiceEditor(m_parameterLabels, false));
            const std::string reference = coordinate.at("parameter_id");
            const auto found = std::find(m_parameterIds.begin(), m_parameterIds.end(), reference);
            if (found == m_parameterIds.end())
            {
                throw std::runtime_error("좌표 참조가 현재 매개변수 목록에 없습니다.");
            }
            grid->SetCellValue(row, base + 3, m_parameterLabels[static_cast<std::size_t>(std::distance(m_parameterIds.begin(), found))]);
            UpdateMode(row, base);
        }
    }
    grid->Bind(wxEVT_GRID_CELL_CHANGED, [this](wxGridEvent& event)
    {
        if (event.GetCol() % 4 == 0)
        {
            UpdateMode(event.GetRow(), event.GetCol());
        }
        event.Skip();
    });
    layout->Add(grid, 1, wxEXPAND | wxLEFT | wxRIGHT, 10);
    layout->Add(CreateSeparatedButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, 10);
    SetSizer(layout);
}

/** @brief 직접값/미정/매개변수에 맞는 편집 열만 열고 단위는 항상 잠근다. */
void CoordinateEditorDialog::UpdateMode(int row, int base)
{
    const wxString mode = m_grid->GetCellValue(row, base);
    m_grid->SetReadOnly(row, base + 1, mode != m_modeLabels[0]);
    m_grid->SetReadOnly(row, base + 2, true);
    m_grid->SetReadOnly(row, base + 3, mode != m_modeLabels[2]);
    m_grid->SetCellBackgroundColour(row, base + 1, mode == m_modeLabels[0] ? *wxWHITE : wxColour(238, 240, 243));
    m_grid->SetCellBackgroundColour(row, base + 2, wxColour(238, 240, 243));
    m_grid->SetCellBackgroundColour(row, base + 3, mode == m_modeLabels[2] ? *wxWHITE : wxColour(238, 240, 243));
}

/** @brief 취소는 원래 값을 그대로 두며 유효한 확인만 새 좌표 값을 반환한다. */
std::optional<CoordinateEditorDialog::Json> CoordinateEditorDialog::Edit(const std::function<void(wxGrid&, wxDialog&)>& opened)
{
    const std::string modes[] = {"value", "missing", "parameter"};
    if (opened)
    {
        opened(*m_grid, *this);
    }
    while (ShowModal() == wxID_OK)
    {
        m_grid->SaveEditControlValue();
        Json value = m_original;
        bool valid = true;
        for (int row = 0; row < m_grid->GetNumberRows() && valid; ++row)
        {
            for (int axis = 0; axis < 2; ++axis)
            {
                const int base = axis * 4;
                const wxString modeLabel = m_grid->GetCellValue(row, base);
                const int modeIndex = modeLabel == m_modeLabels[0] ? 0 : (modeLabel == m_modeLabels[1] ? 1 : 2);
                auto& coordinate = value.at(row).at(axis);
                coordinate["mode"] = modes[modeIndex];
                if (modeIndex == 0)
                {
                    double number = 0;
                    const wxString text = m_grid->GetCellValue(row, base + 1);
                    valid = text.ToDouble(&number) && std::isfinite(number);
                    coordinate["value"] = Utf8(text);
                    coordinate["parameter_id"] = "";
                }
                else if (modeIndex == 1)
                {
                    coordinate["value"] = "";
                    coordinate["parameter_id"] = "";
                }
                else
                {
                    const int selected = m_parameterLabels.Index(m_grid->GetCellValue(row, base + 3));
                    valid = selected > 0;
                    if (valid)
                    {
                        coordinate["parameter_id"] = m_parameterIds.at(static_cast<std::size_t>(selected));
                    }
                }
                if (!valid)
                {
                    m_grid->SetGridCursor(row, base + (modeIndex == 0 ? 1 : 3));
                    m_grid->MakeCellVisible(row, base);
                    break;
                }
            }
        }
        if (!valid)
        {
            wxMessageBox(Display("직접 입력에는 유한한 숫자를, 참조에는 목록의 매개변수를 지정하세요."), Display("좌표 입력"), wxOK | wxICON_WARNING, this);
            m_grid->SetFocus();
            continue;
        }
        return value;
    }
    return std::nullopt;
}
