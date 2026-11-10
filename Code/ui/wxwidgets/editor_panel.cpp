#include "editor_panel.h"
#include <wx/checklst.h>

#include <algorithm>
#include <cmath>
#include <stdexcept>

wxDEFINE_EVENT(wxEVT_RFAD_EDITOR_CHANGED, wxCommandEvent);

namespace
{
using Json = nlohmann::json;

/** @brief 필드 원문을 손실 없이 UTF-8 문자열로 수집한다. */
std::string Utf8(const wxString& value)
{
    const wxScopedCharBuffer buffer = value.utf8_str();
    return std::string(buffer.data(), buffer.length());
}

wxString Display(const std::string& value)
{
    return wxString::FromUTF8(value.data(), value.size());
}

std::string Text(const Json& value)
{
    return value.is_string() ? value.get<std::string>() : (value.is_null() ? "" : value.dump());
}
}

EditorPanel::EditorPanel(wxWindow* parent)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL)
{
    SetScrollRate(0, 12);
    m_layout = new wxBoxSizer(wxVERTICAL);
    SetSizer(m_layout);
}

/** @brief 필드 형식과 선택 목록을 그대로 사용하며 도메인 계산을 수행하지 않는다. */
void EditorPanel::SetFields(const Json& fields, const Json& selection, const Json& coordinateChoices)
{
    Freeze();
    m_fields.clear();
    m_selection = selection;
    m_coordinateChoices = coordinateChoices;
    m_diagnosticField.clear();
    m_layout->Clear(true);
    m_diagnostic = new wxStaticText(this, wxID_ANY, wxEmptyString);
    m_diagnostic->SetForegroundColour(wxColour(170, 35, 35));
    m_layout->Add(m_diagnostic, 0, wxEXPAND | wxALL, 8);
    m_diagnostic->Hide();
    m_inputNotice = new wxStaticText(this, wxID_ANY, wxEmptyString);
    m_layout->Add(m_inputNotice, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(6));
    m_inputNotice->Hide();
    m_details = new wxCheckBox(this, wxID_ANY, Display("상세 식별 정보 표시"));
    m_layout->Add(m_details, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(6));
    m_details->Hide();
    m_details->Bind(wxEVT_CHECKBOX, [this](wxCommandEvent&)
    {
        UpdateModes();
    });
    for (const auto& descriptor : fields)
    {
        const std::string key = descriptor.at("key").get<std::string>();
        const std::string editor = descriptor.at("editor").get<std::string>();
        const std::string valueKey = key == "unit" ? "value" :
            (key.size() > 5 && key.substr(key.size() - 5) == ".unit" ? key.substr(0, key.size() - 4) + "value" : "");
        const auto valueField = m_fields.find(valueKey);
        const bool paired = !valueKey.empty() && valueField != m_fields.end();
        auto* rowPanel = paired ? valueField->second.row : new wxPanel(this);
        auto* row = paired ? static_cast<wxBoxSizer*>(rowPanel->GetSizer()) : new wxBoxSizer(wxHORIZONTAL);
        auto* label = paired ? valueField->second.label :
            new wxStaticText(rowPanel, wxID_ANY, Display(descriptor.at("label").get<std::string>()));
        if (!paired)
        {
            label->Wrap(FromDIP(145));
            label->SetMinSize(wxSize(FromDIP(150), -1));
            row->Add(label, 0, wxTOP | wxRIGHT, FromDIP(4));
            rowPanel->SetSizer(row);
            m_layout->Add(rowPanel, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(6));
        }
        auto* input = new wxBoxSizer(wxVERTICAL);
        row->Add(input, paired ? 0 : 1, wxEXPAND | (paired ? wxLEFT : 0), paired ? FromDIP(6) : 0);
        wxWindow* control = nullptr;
        wxBoxSizer* bindingButtons = nullptr;
        std::vector<wxWindow*> auxiliaries;
        if (editor == "choice")
        {
            auto* choice = new wxChoice(rowPanel, wxID_ANY);
            for (const auto& item : descriptor.at("choices"))
            {
                choice->Append(Display(item.at("label").get<std::string>()));
            }
            control = choice;
            choice->Bind(wxEVT_CHOICE, [this](wxCommandEvent&)
            {
                UpdateModes();
                NotifyChanged();
            });
        }
        else if (editor == "multichoice")
        {
            auto* choice = new wxCheckListBox(rowPanel, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 100)));
            for (const auto& item : descriptor.at("choices"))
            {
                choice->Append(Display(item.at("label").get<std::string>()));
            }
            control = choice;
            choice->Bind(wxEVT_CHECKLISTBOX, [this](wxCommandEvent&)
            {
                NotifyChanged();
            });
        }
        else if (editor == "coordinate_table")
        {
            control = new wxButton(rowPanel, wxID_ANY, Display("좌표 편집"));
            control->Bind(wxEVT_BUTTON, [this, key](wxCommandEvent&)
            {
                EditCoordinates(key);
            });
        }
        else if (editor == "bool")
        {
            control = new wxCheckBox(rowPanel, wxID_ANY, Display("사용"));
            control->Bind(wxEVT_CHECKBOX, [this](wxCommandEvent&)
            {
                NotifyChanged();
            });
        }
        else if (editor == "bindings")
        {
            auto* grid = new wxGrid(rowPanel, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 140)));
            grid->CreateGrid(0, 2);
            grid->SetColLabelValue(0, Display("표현식 변수"));
            grid->SetColLabelValue(1, Display("참조 매개변수"));
            grid->SetColSize(0, FromDIP(125));
            grid->SetColSize(1, FromDIP(250));
            grid->SetRowLabelSize(FromDIP(30));
            control = grid;
            auto* buttons = new wxBoxSizer(wxHORIZONTAL);
            auto* add = new wxButton(rowPanel, wxID_ANY, Display("변수 결합 추가"));
            auto* remove = new wxButton(rowPanel, wxID_ANY, Display("선택한 결합 삭제"));
            buttons->Add(add, 0, wxRIGHT, 6);
            buttons->Add(remove, 0);
            bindingButtons = buttons;
            const Json choices = descriptor.at("choices");
            add->Bind(wxEVT_BUTTON, [this, grid, choices](wxCommandEvent&)
            {
                grid->AppendRows();
                wxArrayString labels;
                for (const auto& item : choices)
                {
                    labels.Add(Display(item.at("label").get<std::string>()));
                }
                grid->SetCellEditor(grid->GetNumberRows() - 1, 1, new wxGridCellChoiceEditor(labels, false));
                grid->SetGridCursor(grid->GetNumberRows() - 1, 0);
                grid->MakeCellVisible(grid->GetNumberRows() - 1, 0);
                NotifyChanged();
            });
            remove->Bind(wxEVT_BUTTON, [this, grid](wxCommandEvent&)
            {
                if (grid->GetGridCursorRow() >= 0 && grid->GetGridCursorRow() < grid->GetNumberRows())
                {
                    grid->DeleteRows(grid->GetGridCursorRow());
                    NotifyChanged();
                }
            });
            grid->Bind(wxEVT_GRID_CELL_CHANGED, [this](wxGridEvent& event)
            {
                NotifyChanged();
                event.Skip();
            });
            add->Enable(!descriptor.value("readonly", false));
            remove->Enable(!descriptor.value("readonly", false));
            auxiliaries = {add, remove};
        }
        else if (editor == "text")
        {
            const bool multiline = key == "expression" || key == "description" || key == "assumptions";
            control = new wxTextCtrl(rowPanel, wxID_ANY, wxEmptyString, wxDefaultPosition,
                multiline ? FromDIP(wxSize(-1, 54)) : wxDefaultSize, multiline ? wxTE_MULTILINE : 0);
            control->Bind(wxEVT_TEXT, [this](wxCommandEvent&)
            {
                NotifyChanged();
            });
        }
        else
        {
            throw std::runtime_error("Unsupported editor field type: " + editor);
        }
        Field field{descriptor, control, auxiliaries, rowPanel, input, label};
        WriteValue(field, descriptor.at("value"));
        control->SetName(Display(descriptor.at("label").get<std::string>()));
        if (descriptor.contains("help"))
        {
            control->SetToolTip(Display(descriptor.at("help").get<std::string>()));
        }
        control->Enable(!descriptor.value("readonly", false));
        input->Add(control, 0, wxEXPAND);
        if (bindingButtons != nullptr)
        {
            input->Add(bindingButtons, 0, wxTOP, FromDIP(4));
        }
        if (descriptor.value("advanced", false))
        {
            m_details->Show();
        }
        m_fields.emplace(key, std::move(field));
    }
    UpdateModes();
    UpdateInputNotice();
    Layout();
    FitInside();
    Scroll(0, 0);
    Thaw();
}

/** @brief 입력 중인 grid cell을 확정하고 값 변경분만 반환한다. */
Json EditorPanel::Changes() const
{
    Json result = Json::object();
    for (const auto& item : m_fields)
    {
        if (item.second.descriptor.value("readonly", false) || !item.second.control->IsThisEnabled())
        {
            continue;
        }
        const Json value = ReadValue(item.second);
        if (value != item.second.descriptor.at("value"))
        {
            result[item.first] = value;
        }
    }
    return result;
}

bool EditorPanel::IsDirty() const
{
    try
    {
        return !Changes().empty();
    }
    catch (const std::exception&)
    {
        return true;
    }
}

Json EditorPanel::ReadValue(const Field& field) const
{
    if (field.descriptor.value("readonly", false))
    {
        return field.descriptor.at("value");
    }
    const std::string editor = field.descriptor.at("editor").get<std::string>();
    if (editor == "choice")
    {
        const int index = static_cast<wxChoice*>(field.control)->GetSelection();
        if (index == wxNOT_FOUND)
        {
            throw std::runtime_error("선택값이 없습니다: " + field.descriptor.at("label").get<std::string>());
        }
        return field.descriptor.at("choices").at(static_cast<std::size_t>(index)).at("value");
    }
    if (editor == "multichoice")
    {
        auto* choice = static_cast<wxCheckListBox*>(field.control);
        Json checked = Json::array();
        const auto& choices = field.descriptor.at("choices");
        for (std::size_t index = 0; index < choices.size(); ++index)
        {
            if (choice->IsChecked(static_cast<unsigned int>(index)))
            {
                checked.push_back(choices[index].at("value"));
            }
        }
        Json result = Json::array();
        for (const auto& original : field.descriptor.at("value"))
        {
            if (std::find(checked.begin(), checked.end(), original) != checked.end())
            {
                result.push_back(original);
            }
        }
        for (const auto& value : checked)
        {
            if (std::find(result.begin(), result.end(), value) == result.end())
            {
                result.push_back(value);
            }
        }
        return result;
    }
    if (editor == "coordinate_table")
    {
        return field.coordinateValue;
    }
    if (editor == "bool")
    {
        return static_cast<wxCheckBox*>(field.control)->GetValue();
    }
    if (editor == "bindings")
    {
        auto* grid = static_cast<wxGrid*>(field.control);
        grid->SaveEditControlValue();
        Json result = Json::object();
        for (int row = 0; row < grid->GetNumberRows(); ++row)
        {
            const std::string alias = Utf8(grid->GetCellValue(row, 0));
            const std::string label = Utf8(grid->GetCellValue(row, 1));
            if (alias.empty() && label.empty())
            {
                continue;
            }
            if (alias.empty() || label.empty() || result.contains(alias))
            {
                throw std::runtime_error("변수 결합의 이름과 대상이 필요하며 이름은 중복될 수 없습니다.");
            }
            bool matched = false;
            for (const auto& option : field.descriptor.at("choices"))
            {
                if (option.at("label") == label)
                {
                    result[alias] = option.at("value");
                    matched = true;
                    break;
                }
            }
            if (!matched)
            {
                throw std::runtime_error("변수 결합의 참조 매개변수를 목록에서 선택하십시오.");
            }
        }
        return result;
    }
    return Utf8(static_cast<wxTextCtrl*>(field.control)->GetValue());
}

void EditorPanel::WriteValue(Field& field, const Json& value)
{
    const std::string editor = field.descriptor.at("editor").get<std::string>();
    if (editor == "choice")
    {
        auto* choice = static_cast<wxChoice*>(field.control);
        choice->SetSelection(wxNOT_FOUND);
        std::size_t index = 0;
        for (const auto& option : field.descriptor.at("choices"))
        {
            if (option.at("value") == value)
            {
                choice->SetSelection(static_cast<int>(index));
            }
            ++index;
        }
    }
    else if (editor == "multichoice")
    {
        if (!value.is_array())
        {
            throw std::runtime_error("다중 참조 선택값은 목록이어야 합니다.");
        }
        auto* choice = static_cast<wxCheckListBox*>(field.control);
        Json selected = Json::array();
        const auto& choices = field.descriptor.at("choices");
        for (std::size_t index = 0; index < choices.size(); ++index)
        {
            const auto& id = choices[index].at("value");
            const bool checked = std::find(value.begin(), value.end(), id) != value.end();
            choice->Check(static_cast<unsigned int>(index), checked);
            if (checked)
            {
                selected.push_back(id);
            }
        }
        if (selected.size() != value.size())
        {
            throw std::runtime_error("다중 참조에 중복되거나 선택 목록에 없는 식별자가 있습니다.");
        }
    }
    else if (editor == "coordinate_table")
    {
        if (!value.is_array() || value.size() < 3 || value.size() > 64)
        {
            throw std::runtime_error("좌표 표의 점 수가 지원 범위를 벗어났습니다.");
        }
        for (const auto& point : value)
        {
            if (!point.is_array() || point.size() != 2)
            {
                throw std::runtime_error("좌표 표에는 점마다 두 좌표가 필요합니다.");
            }
            for (const auto& coordinate : point)
            {
                const std::string mode = coordinate.at("mode");
                if ((mode != "value" && mode != "missing" && mode != "parameter") || !coordinate.at("value").is_string() ||
                    !coordinate.at("parameter_id").is_string() || !coordinate.at("unit").is_string())
                {
                    throw std::runtime_error("좌표 표의 입력 방식이나 값 형식이 유효하지 않습니다.");
                }
            }
        }
        field.coordinateValue = value;
        static_cast<wxButton*>(field.control)->SetLabel(Display("좌표 " + std::to_string(value.size()) + "점 편집"));
    }
    else if (editor == "bool")
    {
        static_cast<wxCheckBox*>(field.control)->SetValue(value.get<bool>());
    }
    else if (editor == "bindings")
    {
        auto* grid = static_cast<wxGrid*>(field.control);
        if (grid->GetNumberRows() > 0)
        {
            grid->DeleteRows(0, grid->GetNumberRows());
        }
        wxArrayString labels;
        for (const auto& option : field.descriptor.at("choices"))
        {
            labels.Add(Display(option.at("label").get<std::string>()));
        }
        for (const auto& binding : value.items())
        {
            grid->AppendRows();
            const int row = grid->GetNumberRows() - 1;
            grid->SetCellValue(row, 0, Display(binding.key()));
            for (const auto& option : field.descriptor.at("choices"))
            {
                if (option.at("value") == binding.value())
                {
                    grid->SetCellValue(row, 1, Display(option.at("label").get<std::string>()));
                }
            }
            grid->SetCellEditor(row, 1, new wxGridCellChoiceEditor(labels, false));
        }
    }
    else
    {
        const Json displayValue = field.descriptor.value("readonly", false) ?
            field.descriptor.value("display_value", value) : value;
        static_cast<wxTextCtrl*>(field.control)->ChangeValue(Display(Text(displayValue)));
    }
}

/** @brief 많은 꼭짓점을 작은 DTO로 유지하고 값/미정/변수 참조를 셀마다 구분한다. */
void EditorPanel::EditCoordinates(const std::string& key, const std::function<void(wxGrid&, wxDialog&)>& opened)
{
    Field& field = m_fields.at(key);
    if (field.descriptor.value("readonly", false))
    {
        return;
    }
    wxDialog dialog(this, wxID_ANY, Display(field.descriptor.at("label").get<std::string>() + " 좌표"),
        wxDefaultPosition, FromDIP(wxSize(940, 480)), wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    layout->Add(new wxStaticText(&dialog, wxID_ANY, Display("각 좌표의 입력 방식을 고르세요. 숫자는 옆에 표시한 단위를 사용합니다.\n단위는 읽기 전용이며 미정값을 계산값으로 채우지 않습니다. 참조는 목록에서 선택합니다.\n꼭짓점 수는 유지하고 변경 적용 전까지 초안으로 보존합니다.")), 0, wxEXPAND | wxALL, 10);
    auto* grid = new wxGrid(&dialog, wxID_ANY);
    grid->CreateGrid(static_cast<int>(field.coordinateValue.size()), 8);
    const char* labels[] = {"X 입력", "X 값", "단위", "X 참조", "Y 입력", "Y 값", "단위", "Y 참조"};
    const wxString modeLabels[] = {Display("직접 입력"), Display("미정"), Display("매개변수 참조")};
    const std::string modes[] = {"value", "missing", "parameter"};
    wxArrayString modeChoices;
    for (const auto& mode : modeLabels)
    {
        modeChoices.Add(mode);
    }
    wxArrayString parameterLabels;
    parameterLabels.Add(Display("선택 없음"));
    std::vector<std::string> parameterIds{std::string()};
    for (const auto& choice : m_coordinateChoices)
    {
        const std::string id = choice.at("value");
        if (!id.empty())
        {
            parameterIds.push_back(id);
            parameterLabels.Add(Display(choice.at("label").get<std::string>() + " / " + id));
        }
    }
    for (int column = 0; column < 8; ++column)
    {
        grid->SetColLabelValue(column, Display(labels[column]));
        grid->SetColSize(column, FromDIP(column % 4 == 3 ? 215 : (column % 4 == 2 ? 45 : 115)));
    }
    grid->SetRowLabelSize(FromDIP(38));
    auto updateMode = [grid, modeLabels](int row, int base)
    {
        const wxString mode = grid->GetCellValue(row, base);
        grid->SetReadOnly(row, base + 1, mode != modeLabels[0]);
        grid->SetReadOnly(row, base + 2, true);
        grid->SetReadOnly(row, base + 3, mode != modeLabels[2]);
        grid->SetCellBackgroundColour(row, base + 1, mode == modeLabels[0] ? *wxWHITE : wxColour(238, 240, 243));
        grid->SetCellBackgroundColour(row, base + 2, wxColour(238, 240, 243));
        grid->SetCellBackgroundColour(row, base + 3, mode == modeLabels[2] ? *wxWHITE : wxColour(238, 240, 243));
    };
    for (int row = 0; row < grid->GetNumberRows(); ++row)
    {
        for (int axis = 0; axis < 2; ++axis)
        {
            const int base = axis * 4;
            const auto& coordinate = field.coordinateValue.at(row).at(axis);
            const std::string mode = coordinate.at("mode");
            grid->SetCellEditor(row, base, new wxGridCellChoiceEditor(modeChoices, false));
            grid->SetCellValue(row, base, modeLabels[mode == "value" ? 0 : (mode == "missing" ? 1 : 2)]);
            grid->SetCellValue(row, base + 1, Display(coordinate.at("value")));
            grid->SetCellValue(row, base + 2, Display(coordinate.at("unit")));
            grid->SetCellEditor(row, base + 3, new wxGridCellChoiceEditor(parameterLabels, false));
            const std::string reference = coordinate.at("parameter_id");
            const auto found = std::find(parameterIds.begin(), parameterIds.end(), reference);
            if (found == parameterIds.end())
            {
                throw std::runtime_error("좌표 참조가 현재 매개변수 목록에 없습니다.");
            }
            grid->SetCellValue(row, base + 3, parameterLabels[static_cast<std::size_t>(std::distance(parameterIds.begin(), found))]);
            updateMode(row, base);
        }
    }
    grid->Bind(wxEVT_GRID_CELL_CHANGED, [updateMode](wxGridEvent& event)
    {
        if (event.GetCol() % 4 == 0)
        {
            updateMode(event.GetRow(), event.GetCol());
        }
        event.Skip();
    });
    layout->Add(grid, 1, wxEXPAND | wxLEFT | wxRIGHT, 10);
    layout->Add(dialog.CreateSeparatedButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, 10);
    dialog.SetSizer(layout);
    if (opened)
    {
        opened(*grid, dialog);
    }
    while (dialog.ShowModal() == wxID_OK)
    {
        grid->SaveEditControlValue();
        Json value = field.coordinateValue;
        bool valid = true;
        for (int row = 0; row < grid->GetNumberRows() && valid; ++row)
        {
            for (int axis = 0; axis < 2; ++axis)
            {
                const int base = axis * 4;
                const wxString modeLabel = grid->GetCellValue(row, base);
                const int modeIndex = modeLabel == modeLabels[0] ? 0 : (modeLabel == modeLabels[1] ? 1 : 2);
                auto& coordinate = value.at(row).at(axis);
                coordinate["mode"] = modes[modeIndex];
                if (modeIndex == 0)
                {
                    double number = 0;
                    const wxString text = grid->GetCellValue(row, base + 1);
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
                    const int selected = parameterLabels.Index(grid->GetCellValue(row, base + 3));
                    valid = selected > 0;
                    if (valid)
                    {
                        coordinate["parameter_id"] = parameterIds.at(static_cast<std::size_t>(selected));
                    }
                }
                if (!valid)
                {
                    grid->SetGridCursor(row, base + (modeIndex == 0 ? 1 : 3));
                    grid->MakeCellVisible(row, base);
                    break;
                }
            }
        }
        if (!valid)
        {
            wxMessageBox(Display("직접 입력에는 유한한 숫자를, 참조에는 목록의 매개변수를 지정하세요."), Display("좌표 입력"), wxOK | wxICON_WARNING, &dialog);
            grid->SetFocus();
            continue;
        }
        WriteValue(field, value);
        NotifyChanged();
        return;
    }
}

/** @brief 실제 좌표 대화상자의 grid와 확인 버튼 이벤트를 smoke에서 검사한다. */
void EditorPanel::EditCoordinateCellForSmoke(const std::string& key, int point, int axis, const std::string& value)
{
    EditCoordinates(key, [point, axis, value](wxGrid& grid, wxDialog& dialog)
    {
        if (point < 0 || point >= grid.GetNumberRows() || axis < 0 || axis > 1)
        {
            throw std::runtime_error("좌표 표 smoke 셀 범위를 벗어났습니다.");
        }
        dialog.CallAfter([&grid, &dialog, point, axis, value]()
        {
            const int base = axis * 4;
            grid.SetCellValue(point, base, Display("직접 입력"));
            grid.SetCellValue(point, base + 1, Display(value));
            wxGridEvent changed(grid.GetId(), wxEVT_GRID_CELL_CHANGED, &grid, point, base);
            grid.GetEventHandler()->ProcessEvent(changed);
            wxWindow* accept = dialog.FindWindow(wxID_OK);
            wxCommandEvent clicked(wxEVT_BUTTON, wxID_OK);
            clicked.SetEventObject(accept);
            accept->GetEventHandler()->ProcessEvent(clicked);
        });
    });
}

/** @brief 실제 폼 컨트롤을 사용하여 개발 smoke 입력을 설정한다. */
void EditorPanel::SetFieldValue(const std::string& key, const Json& value)
{
    WriteValue(m_fields.at(key), value);
    UpdateModes();
    NotifyChanged();
}

Json EditorPanel::FieldValue(const std::string& key) const
{
    return ReadValue(m_fields.at(key));
}

/** @brief 선택 객체와 일치하는 진단 경로만 화면 필드에 연결한다. */
std::string EditorPanel::ResolveDiagnosticField(const std::string& path) const
{
    std::string key;
    for (const char character : path)
    {
        if (character == '[')
        {
            key += '.';
        }
        else if (character != ']')
        {
            key += character;
        }
    }
    if (key.compare(0, 7, "values.") == 0)
    {
        key.erase(0, 7);
    }
    const std::string kind = m_selection.value("kind", "");
    const std::string identity = m_selection.value("id", "");
    const std::map<std::string, std::string> collections = {
        {"parameter", "parameters"}, {"new_parameter", "parameters"}, {"material", "materials"},
        {"layer", "stackup"}, {"geometry", "geometry"}, {"port", "ports"}, {"net", "nets"}
    };
    auto collection = collections.find(kind);
    std::vector<std::string> prefixes;
    if (collection != collections.end() && !identity.empty())
    {
        prefixes.push_back(collection->second + "." + identity + ".");
        if (kind == "parameter" || kind == "new_parameter")
        {
            prefixes.push_back("parameters.input.");
        }
    }
    if (kind == "board")
    {
        prefixes.push_back("board.");
    }
    for (const auto& prefix : prefixes)
    {
        if (key.compare(0, prefix.size(), prefix) == 0)
        {
            key.erase(0, prefix.size());
            break;
        }
    }
    if (key == "quantity.value_si")
    {
        key = "value";
    }
    else if (key == "quantity.display_unit")
    {
        key = "unit";
    }
    if (m_fields.count(key) != 0)
    {
        return key;
    }
    for (const auto& item : m_fields)
    {
        if (item.second.descriptor.at("editor") == "coordinate_table" &&
            key.compare(0, item.first.size() + 1, item.first + ".") == 0)
        {
            return item.first;
        }
    }
    for (const auto& suffix : {".value", ".parameter_id", ".mode"})
    {
        const auto found = m_fields.find(key + suffix);
        if (found != m_fields.end() && found->second.control->IsThisEnabled())
        {
            return found->first;
        }
    }
    return "";
}

/** @brief 오류 설명은 사용자 용어로 표시하고 원래 경로는 상세 tooltip에 보존한다. */
std::string EditorPanel::ShowDiagnostic(const std::string& field, const std::string& message)
{
    m_diagnosticField = ResolveDiagnosticField(field);
    const auto found = m_fields.find(m_diagnosticField);
    const std::string label = found == m_fields.end() ? "설계 입력" : found->second.descriptor.at("label").get<std::string>();
    const std::string displayMessage = message.empty() ? "" : label + ": " + message;
    m_diagnostic->SetLabel(Display(displayMessage));
    m_diagnostic->SetToolTip(Display(field));
    m_diagnostic->Show(!message.empty());
    m_diagnostic->Wrap(std::max(200, GetClientSize().GetWidth() - 24));
    Layout();
    FitInside();
    if (found != m_fields.end())
    {
        if (found->second.descriptor.value("advanced", false))
        {
            m_details->SetValue(true);
            UpdateModes();
        }
        if (found->second.control->IsThisEnabled())
        {
            found->second.control->SetFocus();
        }
        const wxPoint position = CalcUnscrolledPosition(ScreenToClient(found->second.control->ClientToScreen(wxPoint(0, 0))));
        Scroll(0, std::max(0, position.y / 12));
    }
    return displayMessage;
}

/** @brief 숨긴 고급 정보와 사용하지 않는 입력은 보이지 않으며 평가값은 읽기 전용으로 남긴다. */
void EditorPanel::UpdateModes()
{
    std::map<wxPanel*, bool> visibleRows;
    for (auto& item : m_fields)
    {
        bool enabled = !item.second.descriptor.value("readonly", false);
        bool visible = !item.second.descriptor.value("advanced", false) || m_details->GetValue();
        if (item.first.size() >= 12 && item.first.substr(item.first.size() - 12) == "display_note" &&
            item.second.descriptor.at("value") == "")
        {
            visible = false;
        }
        const auto parameterMode = m_fields.find("mode");
        if (parameterMode != m_fields.end())
        {
            const std::string mode = ReadValue(parameterMode->second).get<std::string>();
            if (item.first == "value")
            {
                enabled = enabled && mode == "value";
                visible = visible && mode != "missing";
            }
            else if (item.first == "expression" || item.first == "bindings")
            {
                enabled = enabled && mode == "expression";
                visible = visible && mode == "expression";
            }
        }
        const std::size_t separator = item.first.rfind('.');
        if (separator != std::string::npos)
        {
            const std::string prefix = item.first.substr(0, separator);
            const std::string suffix = item.first.substr(separator + 1);
            const auto modeField = m_fields.find(prefix + ".mode");
            if (modeField != m_fields.end())
            {
                const std::string mode = ReadValue(modeField->second).get<std::string>();
                if (suffix == "value")
                {
                    enabled = enabled && mode == "value";
                    visible = visible && mode != "missing";
                }
                else if (suffix == "unit")
                {
                    enabled = enabled && mode != "parameter";
                }
                else if (suffix == "parameter_id")
                {
                    enabled = enabled && mode == "parameter";
                    visible = visible && mode == "parameter";
                }
            }
        }
        item.second.control->Enable(enabled);
        item.second.section->ShowItems(visible);
        visibleRows[item.second.row] = visibleRows[item.second.row] || visible;
        for (wxWindow* auxiliary : item.second.auxiliaries)
        {
            auxiliary->Enable(enabled);
        }
    }
    for (const auto& item : m_fields)
    {
        const std::string& key = item.first;
        const bool rootValue = key == "value";
        if (!rootValue && (key.size() <= 6 || key.substr(key.size() - 6) != ".value"))
        {
            continue;
        }
        const std::string prefix = rootValue ? "" : key.substr(0, key.size() - 5);
        const auto unit = m_fields.find(prefix + "unit");
        const auto mode = m_fields.find(prefix + "mode");
        if (unit != m_fields.end() && mode != m_fields.end())
        {
            const std::string inputMode = ReadValue(mode->second).get<std::string>();
            const std::string label = inputMode == "missing" ? unit->second.descriptor.at("label").get<std::string>() :
                ((rootValue && inputMode == "expression" ? std::string("마지막 적용값") :
                    item.second.descriptor.at("label").get<std::string>() + (inputMode == "parameter" ? " (마지막 적용값)" : "")) + " / 단위");
            item.second.label->SetLabel(Display(label));
            item.second.label->Wrap(FromDIP(145));
        }
    }
    for (const auto& row : visibleRows)
    {
        row.first->Show(row.second);
        row.first->Layout();
    }
    Layout();
    FitInside();
}

/** @brief grid 편집 확정 중의 중첩 이벤트를 막고 변경 상태를 부모에 알린다. */
void EditorPanel::NotifyChanged()
{
    if (m_notifying)
    {
        return;
    }
    m_notifying = true;
    UpdateInputNotice();
    wxCommandEvent event(wxEVT_RFAD_EDITOR_CHANGED, GetId());
    event.SetEventObject(this);
    GetEventHandler()->ProcessEvent(event);
    m_notifying = false;
}

bool EditorPanel::IsFieldVisible(const std::string& key) const
{
    const Field& field = m_fields.at(key);
    return field.row->IsShown() && field.control->IsShown();
}

const std::string& EditorPanel::DiagnosticField() const
{
    return m_diagnosticField;
}

/** @brief 단위만 변경할 때 원래 숫자를 새 단위의 물리값으로 오해하지 않도록 안내한다. */
void EditorPanel::UpdateInputNotice()
{
    std::vector<std::string> notices;
    for (const auto& item : m_fields)
    {
        const std::string& key = item.first;
        const bool rootUnit = key == "unit";
        if (!rootUnit && (key.size() <= 5 || key.substr(key.size() - 5) != ".unit"))
        {
            continue;
        }
        const std::string prefix = rootUnit ? "" : key.substr(0, key.size() - 4);
        const auto number = m_fields.find(prefix + "value");
        const auto mode = m_fields.find(prefix + "mode");
        if (number == m_fields.end() || mode == m_fields.end() ||
            ReadValue(item.second) == item.second.descriptor.at("value"))
        {
            continue;
        }
        const std::string inputMode = ReadValue(mode->second).get<std::string>();
        const std::string original = Text(number->second.descriptor.at("value"));
        if (original.empty() || inputMode == "missing" || inputMode == "parameter" ||
            (inputMode == "value" && ReadValue(number->second) != number->second.descriptor.at("value")))
        {
            continue;
        }
        notices.push_back(number->second.descriptor.at("label").get<std::string>() +
            ": 단위만 변경한 숫자는 적용 후 환산됩니다. 마지막 적용값: " + original + " " +
            Text(item.second.descriptor.at("value")) + ". 값도 함께 수정하면 새 값과 단위를 사용합니다.");
    }
    m_inputNoticeText = notices.empty() ? "" : notices.front();
    if (notices.size() > 1)
    {
        m_inputNoticeText += " 같은 상태의 다른 항목 " + std::to_string(notices.size() - 1) + "개.";
    }
    m_inputNotice->SetLabel(Display(m_inputNoticeText));
    m_inputNotice->Wrap(std::max(200, GetClientSize().GetWidth() - FromDIP(20)));
    m_inputNotice->Show(!m_inputNoticeText.empty());
    Layout();
    FitInside();
}

const std::string& EditorPanel::InputNotice() const
{
    return m_inputNoticeText;
}
