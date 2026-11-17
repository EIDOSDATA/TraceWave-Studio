/** @file @brief 배열 원문을 유지하고 변경 셀과 명시 선택만 서비스 입력으로 반환한다. */
#include "pcb_feature_list_dialog.h"
#include "pcb_feature_model.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/grid.h>
#include <wx/listctrl.h>
#include <wx/checklst.h>
#include <wx/choice.h>
#include <wx/button.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/tokenzr.h>
#include <wx/msgdlg.h>
#include <algorithm>

namespace
{
Json ChoiceValue(const Json& choice)
{
    return choice.is_object() ? choice.value("value", choice.value("id", Json(nullptr))) : choice;
}

std::string ChoiceLabel(const Json& choice)
{
    return choice.is_object() ? choice.value("label", choice.value("name", "미정")) : PcbFeatureUi::Text(choice);
}

std::string FindLabel(const Json& choices, const Json& value)
{
    for (const auto& choice : choices)
    {
        if (ChoiceValue(choice) == value)
        {
            return ChoiceLabel(choice);
        }
    }
    return value.is_null() ? "미정" : "현재 목록에 없는 원문 참조";
}
}

PcbFeatureListDialog::PcbFeatureListDialog(wxWindow* parent, const Json& field, const Json& value, const Json& context)
    : wxDialog(parent, wxID_ANY, Display(field.value("label", "명시 목록")), wxDefaultPosition,
               parent->FromDIP(wxSize(820, 620)), wxDEFAULT_DIALOG_STYLE | wxRESIZE_BORDER),
      m_field(field), m_original(value), m_value(value), m_context(context), m_kind(field.value("kind", ""))
{
    StudioTheme::BindSurface(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* note = new wxStaticText(
        this, wxID_ANY,
        Display("목록 변경은 아직 원본에 적용되지 않습니다. 부모 화면에서 후보를 검토한 뒤 적용하세요."));
    note->Wrap(FromDIP(750));
    layout->Add(note, 0, wxEXPAND | wxALL, FromDIP(12));
    if (m_kind == "coordinates")
    {
        BuildCoordinates(layout);
    }
    else if (m_kind == "coordinate_loops")
    {
        BuildLoops(layout);
    }
    else if (m_kind == "pins")
    {
        BuildPins(layout);
    }
    else if (m_kind == "members")
    {
        m_memberChoices = field.value("choices", Json::array());
        m_members = new wxCheckListBox(this, wxID_ANY);
        for (const auto& choice : m_memberChoices)
        {
            m_members->Append(Display(ChoiceLabel(choice)));
            const auto record = ChoiceValue(choice);
            if (std::find(value.begin(), value.end(), record) != value.end())
            {
                m_members->Check(m_members->GetCount() - 1);
            }
        }
        layout->Add(m_members, 1, wxEXPAND | wxALL, FromDIP(12));
    }
    else
    {
        std::string text;
        for (const auto& item : value)
        {
            if (!text.empty())
            {
                text += "\n";
            }
            text += item.is_string() ? item.get<std::string>() : "";
        }
        layout->Add(new wxStaticText(this, wxID_ANY,
                                     Display("출처 식별자를 한 줄에 하나씩 입력합니다. 원문 순서를 유지합니다.")),
                    0, wxALL, FromDIP(12));
        m_refs = new wxTextCtrl(this, wxID_ANY, Display(text), wxDefaultPosition, wxDefaultSize, wxTE_MULTILINE);
        layout->Add(m_refs, 1, wxEXPAND | wxALL, FromDIP(12));
    }
    layout->Add(CreateSeparatedButtonSizer(wxOK | wxCANCEL), 0, wxEXPAND | wxALL, FromDIP(12));
    SetSizer(layout);
    SetMinSize(FromDIP(wxSize(620, 440)));
    CentreOnParent();
    Bind(
        wxEVT_BUTTON,
        [this](wxCommandEvent& event)
        {
            if (m_grid)
            {
                m_grid->SaveEditControlValue();
                m_grid->HideCellEditControl();
            }
            event.Skip();
        },
        wxID_OK);
}

void PcbFeatureListDialog::BuildCoordinates(wxSizer* layout)
{
    m_grid = new wxGrid(this, wxID_ANY);
    m_grid->CreateGrid(static_cast<int>(m_value.size()), 4);
    for (int col = 0; col < 4; ++col)
    {
        m_grid->SetColLabelValue(col, Display(col == 0 ? "X 값" : col == 1 ? "X 단위" : col == 2 ? "Y 값" : "Y 단위"));
        m_grid->SetColSize(col, FromDIP(col % 2 == 0 ? 200 : 90));
    }
    const auto rows = m_field.value("display_rows", Json::array());
    for (int row = 0; row < m_grid->GetNumberRows(); ++row)
    {
        for (int axis = 0; axis < 2; ++axis)
        {
            const auto value = static_cast<std::size_t>(row) < rows.size()
                                   ? rows.at(row).value(axis == 0 ? "x" : "y", Json::object())
                                   : Json::object();
            m_grid->SetCellValue(row, axis * 2, Display(value.value("text", "")));
            m_grid->SetCellValue(row, axis * 2 + 1, Display(value.value("unit", m_field.value("unit", "mm"))));
            m_grid->SetReadOnly(row, axis * 2 + 1);
        }
    }
    layout->Add(m_grid, 1, wxEXPAND | wxALL, FromDIP(12));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    auto* add = new wxButton(this, wxID_ANY, Display("꼭짓점 추가"));
    auto* remove = new wxButton(this, wxID_ANY, Display("선택 행 삭제"));
    actions->Add(add, 0, wxRIGHT, FromDIP(8));
    actions->Add(remove, 0);
    layout->Add(actions, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(12));
    add->Bind(wxEVT_BUTTON,
              [this](wxCommandEvent&)
              {
                  if (m_grid->GetNumberRows() >= 64)
                  {
                      return;
                  }
                  const int row = m_grid->GetNumberRows();
                  m_grid->AppendRows();
                  for (int col : {1, 3})
                  {
                      m_grid->SetCellValue(row, col, Display(m_field.value("unit", "mm")));
                      m_grid->SetReadOnly(row, col);
                  }
                  m_value.push_back(Json::array({nullptr, nullptr}));
                  m_grid->SetGridCursor(row, 0);
              });
    remove->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     const int row = m_grid->GetGridCursorRow();
                     if (row >= 0 && row < m_grid->GetNumberRows())
                     {
                         m_value.erase(m_value.begin() + row);
                         m_grid->DeleteRows(row);
                     }
                 });
    m_grid->Bind(wxEVT_GRID_CELL_CHANGING,
                 [this](wxGridEvent& event)
                 {
                     const auto& old = m_value.at(event.GetRow()).at(event.GetCol() / 2);
                     if (old.is_object() && old.contains("parameter_id"))
                     {
                         wxMessageDialog confirm(this,
                                                 Display("이 좌표의 매개변수 연결을 직접 입력으로 바꾸시겠습니까?"),
                                                 Display("좌표 입력 방식"), wxYES_NO | wxNO_DEFAULT | wxICON_QUESTION);
                         if (confirm.ShowModal() != wxID_YES)
                         {
                             event.Veto();
                             return;
                         }
                     }
                     event.Skip();
                 });
    m_grid->Bind(wxEVT_GRID_CELL_CHANGED,
                 [this](wxGridEvent& event)
                 {
                     const int row = event.GetRow(), axis = event.GetCol() / 2;
                     const auto old = m_value.at(row).at(axis);
                     m_value[row][axis] = {
                         {"text", Utf8(m_grid->GetCellValue(row, axis * 2))},
                         {"unit", Utf8(m_grid->GetCellValue(row, axis * 2 + 1))},
                         {"source_refs", old.is_object() ? old.value("source_refs", Json::array()) : Json::array()}};
                     event.Skip();
                 });
}

void PcbFeatureListDialog::BuildPins(wxSizer* layout)
{
    m_pins = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 180)), wxLC_REPORT | wxLC_SINGLE_SEL);
    StudioTheme::Table(*m_pins);
    m_pins->AppendColumn(Display("핀 번호"), wxLIST_FORMAT_LEFT, FromDIP(100));
    m_pins->AppendColumn(Display("패드"), wxLIST_FORMAT_LEFT, FromDIP(370));
    m_pins->AppendColumn(Display("관통 홀"), wxLIST_FORMAT_LEFT, FromDIP(220));
    layout->Add(m_pins, 1, wxEXPAND | wxALL, FromDIP(12));
    auto* fields = new wxBoxSizer(wxHORIZONTAL);
    auto* number = new wxBoxSizer(wxVERTICAL);
    number->Add(new wxStaticText(this, wxID_ANY, Display("원문 핀 번호")), 0, wxBOTTOM, FromDIP(6));
    m_number = new wxTextCtrl(this, wxID_ANY);
    number->Add(m_number, 0, wxEXPAND);
    fields->Add(number, 1, wxRIGHT, FromDIP(8));
    m_padChoices = m_field.value("pad_choices", m_context.value("pads", Json::array()));
    m_pads = new wxCheckListBox(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(300, 130)));
    for (const auto& pad : m_padChoices)
    {
        m_pads->Append(Display(ChoiceLabel(pad)));
    }
    fields->Add(m_pads, 2, wxRIGHT | wxEXPAND, FromDIP(8));
    m_holeChoices = Json::array({{{"value", nullptr}, {"label", "관통 홀 없음"}}});
    for (const auto& hole : m_field.value("hole_choices", m_context.value("holes", Json::array())))
    {
        if (!ChoiceValue(hole).is_null())
        {
            m_holeChoices.push_back(hole);
        }
    }
    m_hole = new wxChoice(this, wxID_ANY);
    for (const auto& hole : m_holeChoices)
    {
        m_hole->Append(Display(ChoiceLabel(hole)));
    }
    m_hole->SetSelection(0);
    fields->Add(m_hole, 1);
    layout->Add(fields, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(12));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    auto* add = new wxButton(this, wxID_ANY, Display("새 핀 추가"));
    auto* update = new wxButton(this, wxID_ANY, Display("선택 핀 수정"));
    auto* remove = new wxButton(this, wxID_ANY, Display("선택 핀 삭제"));
    for (auto* button : {add, update, remove})
    {
        actions->Add(button, 0, wxRIGHT, FromDIP(8));
    }
    layout->Add(actions, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(12));
    const auto write = [this](bool append)
    {
        const long selected = m_pins->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
        if ((!append && selected < 0) || (append && m_value.size() >= 64))
        {
            return;
        }
        Json pads = Json::array();
        for (unsigned index = 0; index < m_pads->GetCount(); ++index)
        {
            if (m_pads->IsChecked(index))
            {
                pads.push_back(ChoiceValue(m_padChoices.at(index)));
            }
        }
        if (m_hole->GetSelection() < 0)
        {
            wxMessageBox(Display("관통 홀 원문을 확인하고 현재 목록에서 명시적으로 선택하세요."), Display("핀 연결"),
                         wxOK | wxICON_INFORMATION, this);
            return;
        }
        Json pin{{"number", Utf8(m_number->GetValue())},
                 {"pad_ids", pads},
                 {"hole_id", ChoiceValue(m_holeChoices.at(std::max(0, m_hole->GetSelection())))}};
        if (append)
        {
            m_value.push_back(pin);
        }
        else
        {
            m_value[selected] = pin;
        }
        RenderPins();
    };
    add->Bind(wxEVT_BUTTON,
              [write](wxCommandEvent&)
              {
                  write(true);
              });
    update->Bind(wxEVT_BUTTON,
                 [write](wxCommandEvent&)
                 {
                     write(false);
                 });
    remove->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     const long selected = m_pins->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
                     if (selected >= 0)
                     {
                         m_value.erase(m_value.begin() + selected);
                         RenderPins();
                     }
                 });
    m_pins->Bind(wxEVT_LIST_ITEM_SELECTED,
                 [this](wxListEvent&)
                 {
                     SelectPin();
                 });
    RenderPins();
}

void PcbFeatureListDialog::RenderPins()
{
    m_pins->DeleteAllItems();
    for (const auto& pin : m_value)
    {
        const long row =
            m_pins->InsertItem(m_pins->GetItemCount(), Display(PcbFeatureUi::Text(pin.value("number", Json(nullptr)))));
        std::string pads;
        for (const auto& pad : pin.value("pad_ids", Json::array()))
        {
            pads += (pads.empty() ? "" : ", ") + FindLabel(m_padChoices, pad);
        }
        m_pins->SetItem(row, 1, Display(pads));
        m_pins->SetItem(row, 2, Display(FindLabel(m_holeChoices, pin.value("hole_id", Json(nullptr)))));
    }
}

void PcbFeatureListDialog::SelectPin()
{
    const long selected = m_pins->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
    if (selected < 0)
    {
        return;
    }
    const auto& pin = m_value.at(selected);
    m_number->ChangeValue(Display(pin.value("number", "")));
    const auto pads = pin.value("pad_ids", Json::array());
    for (unsigned index = 0; index < m_pads->GetCount(); ++index)
    {
        const auto value = ChoiceValue(m_padChoices.at(index));
        m_pads->Check(index, std::find(pads.begin(), pads.end(), value) != pads.end());
    }
    m_hole->SetSelection(wxNOT_FOUND);
    for (std::size_t index = 0; index < m_holeChoices.size(); ++index)
    {
        if (ChoiceValue(m_holeChoices.at(index)) == pin.value("hole_id", Json(nullptr)))
        {
            m_hole->SetSelection(static_cast<int>(index));
        }
    }
}

Json PcbFeatureListDialog::Value() const
{
    if (m_members)
    {
        Json result = Json::array();
        for (const auto& original : m_value)
        {
            for (unsigned index = 0; index < m_members->GetCount(); ++index)
            {
                if (m_members->IsChecked(index) && ChoiceValue(m_memberChoices.at(index)) == original)
                {
                    result.push_back(original);
                }
            }
        }
        for (unsigned index = 0; index < m_members->GetCount(); ++index)
        {
            const auto selected = ChoiceValue(m_memberChoices.at(index));
            if (m_members->IsChecked(index) && std::find(result.begin(), result.end(), selected) == result.end())
            {
                result.push_back(selected);
            }
        }
        return result;
    }
    if (m_refs)
    {
        Json result = Json::array();
        wxStringTokenizer lines(m_refs->GetValue(), "\n", wxTOKEN_RET_EMPTY_ALL);
        while (lines.HasMoreTokens())
        {
            const auto line = lines.GetNextToken();
            if (!line.empty())
            {
                result.push_back(Utf8(line));
            }
        }
        return result;
    }
    return m_value;
}

Json PcbFeatureListDialog::DisplayRows() const
{
    Json rows = Json::array();
    if (m_grid)
    {
        for (int row = 0; row < m_grid->GetNumberRows(); ++row)
        {
            rows.push_back(
                {{"x", {{"text", Utf8(m_grid->GetCellValue(row, 0))}, {"unit", Utf8(m_grid->GetCellValue(row, 1))}}},
                 {"y", {{"text", Utf8(m_grid->GetCellValue(row, 2))}, {"unit", Utf8(m_grid->GetCellValue(row, 3))}}}});
        }
    }
    return rows;
}
