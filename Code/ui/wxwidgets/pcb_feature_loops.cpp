/** @file @brief 다각형 내부 루프를 좌표 표로 편집하고 원문 순서를 보존한다. */
#include "pcb_feature_list_dialog.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/listctrl.h>
#include <wx/sizer.h>
#include <wx/msgdlg.h>

void PcbFeatureListDialog::BuildLoops(wxSizer* layout)
{
    m_displayLoops = m_field.value("display_loops", Json::array());
    m_loops = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL);
    StudioTheme::Table(*m_loops);
    m_loops->AppendColumn(Display("내부 구멍"), wxLIST_FORMAT_LEFT, FromDIP(220));
    m_loops->AppendColumn(Display("꼭짓점"), wxLIST_FORMAT_LEFT, FromDIP(160));
    layout->Add(m_loops, 1, wxEXPAND | wxALL, FromDIP(12));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    auto* add = new wxButton(this, wxID_ANY, Display("내부 구멍 추가"));
    auto* edit = new wxButton(this, wxID_ANY, Display("선택 좌표 편집"));
    auto* remove = new wxButton(this, wxID_ANY, Display("선택 구멍 삭제"));
    for (auto* button : {add, edit, remove})
    {
        actions->Add(button, 0, wxRIGHT, FromDIP(8));
    }
    layout->Add(actions, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(12));
    add->Bind(wxEVT_BUTTON,
              [this](wxCommandEvent&)
              {
                  EditLoop(true);
              });
    edit->Bind(wxEVT_BUTTON,
               [this](wxCommandEvent&)
               {
                   EditLoop(false);
               });
    m_loops->Bind(wxEVT_LIST_ITEM_ACTIVATED,
                  [this](wxListEvent&)
                  {
                      EditLoop(false);
                  });
    remove->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     const long row = m_loops->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
                     if (row >= 0)
                     {
                         m_value.erase(m_value.begin() + row);
                         if (static_cast<std::size_t>(row) < m_displayLoops.size())
                         {
                             m_displayLoops.erase(m_displayLoops.begin() + row);
                         }
                         RenderLoops();
                     }
                 });
    RenderLoops();
}

void PcbFeatureListDialog::RenderLoops()
{
    m_loops->DeleteAllItems();
    for (std::size_t index = 0; index < m_value.size(); ++index)
    {
        const long row =
            m_loops->InsertItem(m_loops->GetItemCount(), Display("내부 구멍 ") + wxString::Format("%zu", index + 1));
        m_loops->SetItem(row, 1, wxString::Format("%zu", m_value.at(index).size()));
    }
}

void PcbFeatureListDialog::EditLoop(bool append)
{
    const long row = m_loops->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
    if ((!append && row < 0) || (append && m_value.size() >= 8))
    {
        return;
    }
    const Json missing{{"value_si", nullptr},
                       {"dimension", "length"},
                       {"display_unit", "mm"},
                       {"status", "missing"},
                       {"source_refs", Json::array()}};
    const Json value = append ? Json::array({Json::array({missing, missing}), Json::array({missing, missing}),
                                             Json::array({missing, missing})})
                              : m_value.at(row);
    Json descriptor{{"label", "내부 구멍 좌표"},
                    {"kind", "coordinates"},
                    {"unit", "mm"},
                    {"display_rows", !append && static_cast<std::size_t>(row) < m_displayLoops.size()
                                         ? m_displayLoops.at(row)
                                         : Json::array()}};
    PcbFeatureListDialog dialog(this, descriptor, value, m_context);
    if (dialog.ShowModal() != wxID_OK)
    {
        return;
    }
    auto loops = m_value;
    if (append)
    {
        loops.push_back(dialog.Value());
    }
    else
    {
        loops[row] = dialog.Value();
    }
    std::size_t count = 0;
    for (const auto& loop : loops)
    {
        count += loop.size();
    }
    if (count > 64)
    {
        wxMessageBox(
            Display("내부 구멍 전체 꼭짓점은 64개 이내여야 합니다. 외곽을 포함한 최종 상한도 서비스에서 검토합니다."),
            Display("꼭짓점 범위"), wxOK | wxICON_INFORMATION, this);
        return;
    }
    m_value = std::move(loops);
    if (append)
    {
        m_displayLoops.push_back(dialog.DisplayRows());
    }
    else
    {
        m_displayLoops[row] = dialog.DisplayRows();
    }
    RenderLoops();
}

Json PcbFeatureListDialog::DisplayLoops() const
{
    return m_displayLoops;
}
