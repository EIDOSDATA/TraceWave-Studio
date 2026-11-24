#include "editor_panel.h"
#include "coordinate_editor_dialog.h"
#include "studio_theme.h"
#include <wx/checklst.h>

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <sstream>
#include <set>

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

/** @brief 서비스 필드는 바꾸지 않고 화면의 기본/연결/출처 영역만 분류한다. */
int FieldGroup(const std::string& key, const Json& descriptor, const std::string& kind)
{
    const auto separator = key.rfind('.');
    const std::string leaf = separator == std::string::npos ? key : key.substr(separator + 1);
    if (key.find("source") != std::string::npos || key.find("origin") != std::string::npos ||
        key.find("assumption") != std::string::npos || key.find("provenance") != std::string::npos)
    {
        return 2;
    }
    if (kind == "target" && key.rfind("criteria.", 0) == 0)
    {
        return 1;
    }
    if (descriptor.value("advanced", false) || leaf == "status" || leaf == "parameter_id" ||
        (leaf == "mode" && separator != std::string::npos && !descriptor.value("primary_quantity", false)) ||
        (kind == "geometry" &&
         (key == "name" || key == "net_id" || key == "role" || key.find("flags.") == 0 || key.find("center.") == 0 ||
          key == "include_in_analysis" || key == "include_in_em" || key == "include_in_export")) ||
        (descriptor.value("readonly", false) && (leaf == "kind" || leaf == "model" || leaf == "fill")))
    {
        return 3;
    }
    if (kind == "port" || kind == "new_port")
    {
        return key == "name" || key == "reference_plane" || key.rfind("resistance.", 0) == 0 ||
            key.rfind("validity_hz.", 0) == 0 ? 0 : 1;
    }
    if (key == "name" || key == "layer_id" || key == "material_id" || key == "material_ref" || key == "net_id" ||
        key == "role" || key.find("flags.") == 0 || key == "include_in_analysis" || key == "include_in_em" ||
        key == "include_in_export")
    {
        return 1;
    }
    return 0;
}

/** @brief 값/단위 열의 중복 접미어를 없애고 원래 라벨은 입력 접근성 이름에 유지한다. */
wxString ShortLabel(const std::string& source)
{
    wxString label = Display(source);
    for (const auto* suffix : {" / 단위", " 단위", " 값"})
    {
        const wxString ending = Display(suffix);
        if (label.EndsWith(ending))
        {
            label.RemoveLast(ending.size());
        }
    }
    label.Replace(Display(" / "), " ");
    return label;
}
}

EditorPanel::EditorPanel(wxWindow* parent)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxHSCROLL)
{
    StudioTheme::BindSurface(*this);
    SetScrollRate(FromDIP(12), FromDIP(12));
    m_layout = new wxBoxSizer(wxVERTICAL);
    SetSizer(m_layout);
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             ReflowRows();
             event.Skip();
         });
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
    m_valueState = new wxStaticText(this, wxID_ANY, wxEmptyString);
    m_valueState->SetForegroundColour(StudioTheme::Colours().secondary);
    m_layout->Add(m_valueState, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    const std::string kind = selection.value("kind", "");
    const bool port = kind == "port" || kind == "new_port";
    const std::array<std::string, 4> names{
        {kind == "material"
             ? "재료 물성"
             : kind == "layer" ? "적층 치수"
             : kind == "target" ? "대역과 기준면"
             : port ? "급전 기준면과 유효 대역"
             : kind == "design_rules" ? "규칙 입력"
             : kind == "parameter" || kind == "new_parameter" ? "매개변수" : "형상과 치수",
         kind == "target" ? "성능 기준" : port ? "단자와 급전 영역" : "기판 및 재료", "출처와 가정", "고급 설정"}};
    for (std::size_t index = 0; index < m_groups.size(); ++index)
    {
        auto& group = m_groups[index];
        group.header =
            new wxToggleButton(this, wxID_ANY, Display(names[index]), wxDefaultPosition, wxDefaultSize, wxBU_LEFT);
        group.header->SetValue(index < 2);
        group.header->SetFont(GetFont().Bold());
        group.header->SetBackgroundColour(StudioTheme::Colours().panel);
        group.header->SetMinSize(FromDIP(wxSize(-1, 34)));
        group.header->SetToolTip(Display("그룹을 펼치거나 접습니다. 입력 초안은 유지됩니다."));
        m_layout->Add(group.header, 0, wxEXPAND | wxLEFT | wxRIGHT | wxTOP | wxBOTTOM, FromDIP(8));
        group.rows = new wxBoxSizer(wxVERTICAL);
        m_layout->Add(group.rows, 0, wxEXPAND | wxBOTTOM, FromDIP(8));
        group.header->Bind(wxEVT_TOGGLEBUTTON,
                           [this](wxCommandEvent&)
                           {
                               UpdateModes();
                           });
    }
    m_details = m_groups[3].header;
    if (kind == "geometry" || kind == "board" || kind == "layer" || kind == "material")
    {
        auto* conditionNotice = new wxStaticText(
            this, wxID_ANY, Display("제작과 측정 조건은 별도로 확인하세요.\n미정값은 자동 확정하지 않습니다."));
        conditionNotice->SetForegroundColour(StudioTheme::Colours().secondary);
        conditionNotice->Wrap(FromDIP(286));
        m_layout->Add(conditionNotice, 0, wxEXPAND | wxALL, FromDIP(8));
    }
    std::vector<Json> ordered(fields.begin(), fields.end());
    if (kind == "geometry")
    {
        std::string shapeKind;
        for (const auto& descriptor : fields)
        {
            if (descriptor.at("key") == "kind")
            {
                shapeKind = descriptor.value("value", "");
            }
        }
        const std::vector<std::string> order =
            shapeKind == "arc_path"
                ? std::vector<std::string>{"radius.", "width.", "start_angle.", "sweep_angle.", "center."}
                : std::vector<std::string>{"start.", "end.", "center.", "width.", "height.", "rotation."};
        const auto rank = [&order](const Json& descriptor)
        {
            const std::string key = descriptor.at("key");
            for (std::size_t index = 0; index < order.size(); ++index)
            {
                if (key.rfind(order[index], 0) == 0)
                {
                    return static_cast<int>(index);
                }
            }
            return static_cast<int>(order.size());
        };
        std::stable_sort(ordered.begin(), ordered.end(),
                         [&](const Json& left, const Json& right)
                         {
                             return rank(left) < rank(right);
                         });
    }
    if (port)
    {
        const auto plane = std::find_if(ordered.begin(), ordered.end(), [](const Json& field)
        {
            return field.at("key") == "reference_plane";
        });
        if (plane != ordered.end())
        {
            std::rotate(ordered.begin(), plane, std::next(plane));
        }
    }
    for (auto& descriptor : ordered)
    {
        const std::string key = descriptor.at("key").get<std::string>();
        if (port && key == "reference_plane")
        {
            descriptor["multiline"] = true;
        }
        const std::string editor = descriptor.at("editor").get<std::string>();
        const auto separator = key.rfind('.');
        const auto leaf = separator == std::string::npos ? key : key.substr(separator + 1);
        const bool primary = (kind == "target" || kind == "design_rules") && separator != std::string::npos &&
            (leaf == "mode" || leaf == "value");
        if (primary)
        {
            descriptor["primary_quantity"] = true;
        }
        const auto prefix = separator == std::string::npos ? "" : key.substr(0, separator + 1);
        const std::string valueKey = leaf == "unit" ? prefix + "value" :
            primary && leaf == "value" ? prefix + "mode" : "";
        const auto valueField = m_fields.find(valueKey);
        const bool paired = !valueKey.empty() && valueField != m_fields.end();
        auto* rowPanel = paired ? valueField->second.row : new wxPanel(this);
        auto* row = paired ? static_cast<wxBoxSizer*>(rowPanel->GetSizer()) : new wxBoxSizer(wxVERTICAL);
        auto* inputs = paired ? valueField->second.inputs : new wxBoxSizer(wxHORIZONTAL);
        auto* label = paired ? valueField->second.label
                             : new wxStaticText(rowPanel, wxID_ANY, Display(descriptor.at("label").get<std::string>()));
        if (!paired)
        {
            StudioTheme::BindSurface(*rowPanel);
            label->SetLabel(key == "sweep_angle.value" ? Display("포함각")
                                                       : ShortLabel(descriptor.at("label").get<std::string>()));
            label->Wrap(FromDIP(100));
            row->Add(label, 0, wxBOTTOM | wxEXPAND, FromDIP(4));
            row->Add(inputs, 0, wxEXPAND);
            rowPanel->SetSizer(row);
            m_groups[static_cast<std::size_t>(FieldGroup(key, descriptor, kind))].rows->Add(
                rowPanel, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::InputGap));
        }
        auto* input = new wxBoxSizer(wxVERTICAL);
        inputs->Add(input, !paired || leaf == "value" ? 1 : 0, wxEXPAND | (paired ? wxLEFT : 0), paired ? FromDIP(6) : 0);
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
            choice->Bind(wxEVT_CHOICE,
                         [this](wxCommandEvent&)
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
            choice->Bind(wxEVT_CHECKLISTBOX,
                         [this](wxCommandEvent&)
                         {
                             NotifyChanged();
                         });
        }
        else if (editor == "coordinate_table")
        {
            control = new wxButton(rowPanel, wxID_ANY, Display("좌표 편집"));
            control->Bind(wxEVT_BUTTON,
                          [this, key](wxCommandEvent&)
                          {
                              EditCoordinates(key);
                          });
        }
        else if (editor == "bool")
        {
            control = new wxCheckBox(rowPanel, wxID_ANY, Display("사용"));
            control->Bind(wxEVT_CHECKBOX,
                          [this](wxCommandEvent&)
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
            add->Bind(wxEVT_BUTTON,
                      [this, grid, choices](wxCommandEvent&)
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
            remove->Bind(wxEVT_BUTTON,
                         [this, grid](wxCommandEvent&)
                         {
                             if (grid->GetGridCursorRow() >= 0 && grid->GetGridCursorRow() < grid->GetNumberRows())
                             {
                                 grid->DeleteRows(grid->GetGridCursorRow());
                                 NotifyChanged();
                             }
                         });
            grid->Bind(wxEVT_GRID_CELL_CHANGED,
                       [this](wxGridEvent& event)
                       {
                           NotifyChanged();
                           event.Skip();
                       });
            add->Enable(!descriptor.value("readonly", false));
            remove->Enable(!descriptor.value("readonly", false));
            auxiliaries = {add, remove};
        }
        else if (editor == "text" || editor == "string_lines")
        {
            const bool multiline = descriptor.value("multiline", false) || editor == "string_lines" ||
                                   key == "expression" || key == "description" || key == "assumptions";
            control =
                new wxTextCtrl(rowPanel, wxID_ANY, wxEmptyString, wxDefaultPosition,
                               multiline ? FromDIP(wxSize(-1, 84)) : wxDefaultSize, multiline ? wxTE_MULTILINE : 0);
            control->Bind(wxEVT_TEXT,
                          [this](wxCommandEvent&)
                          {
                              NotifyChanged();
                          });
        }
        else
        {
            throw std::runtime_error("Unsupported editor field type: " + editor);
        }
        Field field{descriptor, control, auxiliaries, rowPanel, input, label, inputs};
        field.group = paired ? valueField->second.group : FieldGroup(key, descriptor, kind);
        const bool multiline = descriptor.value("multiline", false) || editor == "bindings" ||
                               editor == "string_lines" || key == "expression" || key == "description" ||
                               key == "assumptions";
        if (!multiline && editor != "multichoice")
        {
            control->SetMinSize(FromDIP(wxSize(primary && leaf == "mode" ? 106 : paired ? 68 : 0, 32)));
        }
        WriteValue(field, descriptor.at("value"));
        if (kind == "geometry" && editor == "text" && leaf == "value" &&
            (key.rfind("start.", 0) == 0 || key.rfind("end.", 0) == 0))
        {
            auto* entry = static_cast<wxTextCtrl*>(control);
            const auto original = entry->GetValue();
            double coordinate = 0;
            if (original.length() > 10 && original.ToCDouble(&coordinate) && std::isfinite(coordinate))
            {
                field.compactCoordinate = wxString::Format("%.8g", coordinate);
                field.showingCompactCoordinate = true;
                entry->ChangeValue(field.compactCoordinate);
                entry->SetToolTip(Display("입력 칸에 초점을 두면 원래 좌표를 읽거나 복사할 수 있습니다.") + "\n" + original);
                entry->Bind(wxEVT_SET_FOCUS, [this, key, entry, original](wxFocusEvent& event)
                {
                    const auto pointer = m_fields.find(key);
                    if (pointer != m_fields.end() && pointer->second.control == entry &&
                        pointer->second.showingCompactCoordinate)
                    {
                        pointer->second.showingCompactCoordinate = false;
                        entry->ChangeValue(original);
                    }
                    event.Skip();
                });
                entry->Bind(wxEVT_KILL_FOCUS, [this, key, entry, original](wxFocusEvent& event)
                {
                    const auto pointer = m_fields.find(key);
                    if (pointer != m_fields.end() && pointer->second.control == entry && entry->GetValue() == original)
                    {
                        pointer->second.showingCompactCoordinate = true;
                        entry->ChangeValue(pointer->second.compactCoordinate);
                    }
                    event.Skip();
                });
            }
        }
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
        m_fields.emplace(key, std::move(field));
    }
    UpdateModes();
    ReflowRows(true);
    UpdateInputNotice();
    Layout();
    FitInside();
    Scroll(0, 0);
    Thaw();
}

void EditorPanel::ReflowRows(bool force)
{
    const bool compact = ToDIP(GetClientSize()).x < 292;
    if (m_reflowing || (!force && compact == m_compactRows))
    {
        return;
    }
    m_reflowing = true;
    m_compactRows = compact;
    std::set<wxPanel*> visited;
    for (auto& entry : m_fields)
    {
        auto& field = entry.second;
        if (!visited.insert(field.row).second)
        {
            continue;
        }
        auto* row = static_cast<wxBoxSizer*>(field.row->GetSizer());
        const std::string editor = field.descriptor.at("editor");
        const bool stacked = compact || editor == "bindings" || editor == "string_lines" ||
                             editor == "coordinate_table" || field.descriptor.value("multiline", false) ||
                             entry.first == "expression" || entry.first == "description" ||
                             entry.first == "assumptions";
        row->SetOrientation(stacked ? wxVERTICAL : wxHORIZONTAL);
        field.label->SetMinSize(wxSize(stacked ? 0 : FromDIP(100), -1));
        row->GetItem(field.label)->SetFlag(stacked ? wxBOTTOM | wxEXPAND : wxALIGN_CENTER_VERTICAL | wxRIGHT);
        row->GetItem(field.inputs)->SetProportion(stacked ? 0 : 1);
        field.row->Layout();
    }
    Layout();
    FitInside();
    m_reflowing = false;
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
    if (field.descriptor.value("readonly", false) || field.showingCompactCoordinate)
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
    if (editor == "string_lines")
    {
        Json lines = Json::array();
        std::istringstream stream(Utf8(static_cast<wxTextCtrl*>(field.control)->GetValue()));
        std::string line;
        while (std::getline(stream, line))
        {
            if (!line.empty() && line.back() == '\r')
            {
                line.pop_back();
            }
            lines.push_back(line);
        }
        return lines;
    }
    const auto value = static_cast<wxTextCtrl*>(field.control)->GetValue();
    if (field.descriptor.at("key") == "reference_plane" && field.descriptor.value("multiline", false))
    {
        auto original = Display(Text(field.descriptor.at("value")));
        original.Replace("\r\n", "\n");
        original.Replace("\r", "\n");
        if (original == value)
        {
            return field.descriptor.at("value");
        }
    }
    return Utf8(value);
}

void EditorPanel::WriteValue(Field& field, const Json& value)
{
    field.showingCompactCoordinate = false;
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
                if ((mode != "value" && mode != "missing" && mode != "parameter") ||
                    !coordinate.at("value").is_string() || !coordinate.at("parameter_id").is_string() ||
                    !coordinate.at("unit").is_string())
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
    else if (editor == "string_lines")
    {
        std::string text;
        bool first = true;
        for (const auto& line : value)
        {
            if (!first)
            {
                text += '\n';
            }
            first = false;
            text += line.get<std::string>();
        }
        static_cast<wxTextCtrl*>(field.control)->ChangeValue(Display(text));
    }
    else
    {
        const Json displayValue =
            field.descriptor.value("readonly", false) ? field.descriptor.value("display_value", value) : value;
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
    CoordinateEditorDialog dialog(this, field.descriptor, field.coordinateValue, m_coordinateChoices);
    const auto value = dialog.Edit(opened);
    if (value)
    {
        WriteValue(field, *value);
        NotifyChanged();
    }
}

/** @brief 실제 좌표 대화상자의 grid와 확인 버튼 이벤트를 smoke에서 검사한다. */
void EditorPanel::EditCoordinateCellForSmoke(const std::string& key, int point, int axis, const std::string& value)
{
    EditCoordinates(key,
                    [point, axis, value](wxGrid& grid, wxDialog& dialog)
                    {
                        if (point < 0 || point >= grid.GetNumberRows() || axis < 0 || axis > 1)
                        {
                            throw std::runtime_error("좌표 표 smoke 셀 범위를 벗어났습니다.");
                        }
                        dialog.CallAfter(
                            [&grid, &dialog, point, axis, value]()
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

/** @brief 가용 상태 계산 중 동일 컨트롤을 반복 읽지 않는 일회성 입력 스냅샷이다. */
EditorPresentation::Fields EditorPanel::PresentationFields() const
{
    EditorPresentation::Fields result;
    for (const auto& item : m_fields)
    {
        result.emplace(item.first, EditorPresentation::Field{&item.second.descriptor,
                                                             EditorPresentation::RequiresCurrentValue(item.first)
                                                                 ? ReadValue(item.second)
                                                                 : Json(),
                                                             item.second.control->IsThisEnabled()});
    }
    return result;
}

/** @brief 선택 객체와 일치하는 진단 경로만 화면 필드에 연결한다. */
std::string EditorPanel::ResolveDiagnosticField(const std::string& path) const
{
    return EditorPresentation::ResolveDiagnosticField(path, m_selection, PresentationFields());
}

/** @brief 오류 설명은 사용자 용어로 표시하고 원래 경로는 상세 tooltip에 보존한다. */
std::string EditorPanel::ShowDiagnostic(const std::string& field, const std::string& message)
{
    m_diagnosticField = ResolveDiagnosticField(field);
    const auto found = m_fields.find(m_diagnosticField);
    const std::string label =
        found == m_fields.end() ? "설계 입력" : found->second.descriptor.at("label").get<std::string>();
    const std::string displayMessage = message.empty() ? "" : label + ": " + message;
    m_diagnostic->SetLabel(Display(displayMessage));
    m_diagnostic->SetToolTip(Display(field));
    m_diagnostic->Show(!message.empty());
    m_diagnostic->Wrap(std::max(200, GetClientSize().GetWidth() - 24));
    Layout();
    FitInside();
    if (found != m_fields.end())
    {
        if (!m_groups[static_cast<std::size_t>(found->second.group)].header->GetValue())
        {
            m_groups[static_cast<std::size_t>(found->second.group)].header->SetValue(true);
            UpdateModes();
        }
        if (found->second.control->IsThisEnabled())
        {
            found->second.control->SetFocus();
        }
        const wxPoint position =
            CalcUnscrolledPosition(ScreenToClient(found->second.control->ClientToScreen(wxPoint(0, 0))));
        int horizontal = 0;
        int vertical = 0;
        GetScrollPixelsPerUnit(&horizontal, &vertical);
        Scroll(std::max(0, position.x / std::max(1, horizontal)), std::max(0, position.y / std::max(1, vertical)));
    }
    return displayMessage;
}

/** @brief 숨긴 고급 정보와 사용하지 않는 입력은 보이지 않으며 평가값은 읽기 전용으로 남긴다. */
void EditorPanel::UpdateModes()
{
    const auto fields = PresentationFields();
    std::map<wxPanel*, bool> visibleRows;
    std::array<bool, 4> hasFields{};
    std::vector<wxString> missing;
    bool missingInDetails = false;
    for (auto& item : m_fields)
    {
        const auto group = static_cast<std::size_t>(item.second.group);
        const auto state = EditorPresentation::Evaluate(
            item.first, fields, group == 2 ? m_groups[2].header->GetValue() : m_details->GetValue());
        item.second.control->Enable(state.enabled);
        item.second.section->ShowItems(state.visible);
        hasFields[group] = true;
        visibleRows[item.second.row] =
            visibleRows[item.second.row] || (state.visible && m_groups[group].header->GetValue());
        if ((item.first == "mode" || (item.first.size() > 5 && item.first.substr(item.first.size() - 5) == ".mode")) &&
            fields.at(item.first).value == "missing")
        {
            wxString label = Display(item.second.descriptor.at("label").get<std::string>());
            const wxString ending = Display(" 입력 방식");
            if (label.EndsWith(ending))
            {
                label.RemoveLast(ending.size());
            }
            missing.push_back(label);
            missingInDetails = missingInDetails || group == 3;
        }
        for (wxWindow* auxiliary : item.second.auxiliaries)
        {
            auxiliary->Enable(state.enabled);
        }
        const std::string label = EditorPresentation::ValueLabel(item.first, fields);
        if (!label.empty())
        {
            wxString displayLabel = ShortLabel(label);
            if (item.first == "sweep_angle.value")
            {
                displayLabel.Replace(Display("회전 각도"), Display("포함각"));
            }
            item.second.label->SetLabel(displayLabel);
            item.second.label->Wrap(FromDIP(100));
        }
    }
    for (const auto& row : visibleRows)
    {
        row.first->Show(row.second);
        row.first->Layout();
    }
    for (std::size_t index = 0; index < m_groups.size(); ++index)
    {
        m_groups[index].header->Show(hasFields[index]);
    }
    wxString stateText;
    if (!missing.empty())
    {
        stateText = Display("미정 입력: ") + missing.front();
        if (missing.size() > 1)
        {
            stateText += Display(" 외 ") + wxString::Format("%zu", missing.size() - 1) + Display("개");
        }
        stateText += Display(missingInDetails ? ". 고급 설정의 입력 방식에서 확인하세요."
                                              : ". 해당 행에서 직접 입력 또는 미정을 선택하세요.");
    }
    m_valueState->SetLabel(stateText);
    m_valueState->Wrap(std::max(FromDIP(200), GetClientSize().x - FromDIP(24)));
    m_valueState->Show(!stateText.empty());
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
    m_inputNoticeText = EditorPresentation::InputNotice(PresentationFields());
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
