/** @file @brief source 선택은 표시 상태이며 현재 설계나 과거 원본을 변경하지 않는다. */
#include "result_source_browser.h"
#include "result_presentation.h"
#include "studio_theme.h"
#include "studio_support.h"
#include <wx/choice.h>
#include <wx/listctrl.h>
#include <wx/stattext.h>
#include <wx/button.h>
#include <wx/sizer.h>
#include <wx/wrapsizer.h>
#include <algorithm>
#include <array>

ResultSourceBrowser::ResultSourceBrowser(wxWindow* parent)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL)
{
    SetScrollRate(0, FromDIP(16));
    SetName("result.sources");
    StudioTheme::BindSurface(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* title = new wxStaticText(this, wxID_ANY, Display("결과 원본 선택"));
    StudioTheme::Heading(*title);
    layout->Add(title, 0, wxALL, FromDIP(12));
    m_kind = new wxChoice(this, wxID_ANY);
    for (const auto* name : {"네트워크 자료", "해석 실행", "연구 후보"})
    {
        m_kind->Append(Display(name));
    }
    m_kind->SetSelection(0);
    m_kind->SetName("result.source-kind");
    layout->Add(m_kind, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    m_anchor = new wxChoice(this, wxID_ANY);
    m_anchor->SetName("result.source-revision");
    layout->Add(m_anchor, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    auto* anchors = new wxWrapSizer(wxHORIZONTAL);
    m_anchorPrevious = new wxButton(this, wxID_ANY, Display("이전 개정 목록"));
    m_anchorNext = new wxButton(this, wxID_ANY, Display("다음 개정 목록"));
    anchors->Add(m_anchorPrevious, 0, wxALL, FromDIP(2));
    anchors->Add(m_anchorNext, 0, wxALL, FromDIP(2));
    layout->Add(anchors, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(6));
    m_study = new wxChoice(this, wxID_ANY);
    m_study->SetName("result.source-study");
    layout->Add(m_study, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    m_items =
        new wxListCtrl(this, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL | wxLC_HRULES);
    m_items->SetName("result.source-items");
    m_items->SetMinSize(FromDIP(wxSize(-1, 160)));
    StudioTheme::Table(*m_items);
    m_items->AppendColumn(Display("자료 / 후보 이름"), wxLIST_FORMAT_LEFT, FromDIP(175));
    m_items->AppendColumn(Display("상태"), wxLIST_FORMAT_LEFT, FromDIP(95));
    layout->Add(m_items, 1, wxEXPAND | wxALL, FromDIP(8));
    m_page = new wxStaticText(this, wxID_ANY, Display("보존된 결과를 조회하세요."));
    layout->Add(m_page, 0, wxLEFT | wxRIGHT, FromDIP(8));
    auto* paging = new wxWrapSizer(wxHORIZONTAL);
    m_previous = new wxButton(this, wxID_ANY, Display("이전 25개"));
    m_next = new wxButton(this, wxID_ANY, Display("다음 25개"));
    paging->Add(m_previous, 0, wxALL, FromDIP(2));
    paging->Add(m_next, 0, wxALL, FromDIP(2));
    layout->Add(paging, 0, wxEXPAND | wxALL, FromDIP(6));
    m_refresh = new wxButton(this, wxID_ANY, Display("결과 목록 새로 읽기"));
    StudioTheme::Button(*m_refresh);
    layout->Add(m_refresh, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    StudioTheme::BindSecondary(*m_status);
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(8));
    SetSizer(layout);
    for (auto* choice : {m_kind, m_anchor, m_study})
    {
        choice->Bind(wxEVT_CHOICE,
                     [this](wxCommandEvent&)
                     {
                         if (!m_loading)
                         {
                             ClearCatalog("선택한 범위의 보존 결과를 읽습니다.");
                             UpdateLayout();
                             if (onContextChanged)
                             {
                                 onContextChanged();
                             }
                         }
                     });
    }
    m_items->Bind(wxEVT_LIST_ITEM_SELECTED,
                  [this](wxListEvent&)
                  {
                      if (!m_loading && onSelect && !SelectedSource().is_null())
                      {
                          onSelect(SelectedSource());
                      }
                  });
    m_items->Bind(wxEVT_LIST_ITEM_ACTIVATED,
                  [this](wxListEvent&)
                  {
                      if (!m_loading && onSelect && !SelectedSource().is_null())
                      {
                          onSelect(SelectedSource());
                      }
                  });
    m_refresh->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        if (onRefresh)
                        {
                            onRefresh();
                        }
                    });
    m_previous->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         if (onPage)
                         {
                             onPage(std::max(0, m_catalog.value("offset", 0) - 25));
                         }
                     });
    m_next->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     if (onPage && m_catalog.value("next_offset", Json(nullptr)).is_number_integer())
                     {
                         onPage(m_catalog.at("next_offset").get<int>());
                     }
                 });
    m_anchorPrevious->Bind(wxEVT_BUTTON,
                           [this](wxCommandEvent&)
                           {
                               if (onAnchorPage)
                               {
                                   onAnchorPage(std::max(0, m_anchorOffset - 25));
                               }
                           });
    m_anchorNext->Bind(wxEVT_BUTTON,
                       [this](wxCommandEvent&)
                       {
                           if (onAnchorPage && m_anchorNextOffset >= 0)
                           {
                               onAnchorPage(m_anchorNextOffset);
                           }
                       });
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             m_status->Wrap(std::max(120, GetClientSize().x - FromDIP(20)));
             event.Skip();
         });
    Reset();
}

std::string ResultSourceBrowser::Kind() const
{
    const std::array<const char*, 3> kinds{{"network", "solver", "sweep"}};
    return kinds.at(std::clamp(m_kind->GetSelection(), 0, 2));
}

Json ResultSourceBrowser::Anchor() const
{
    const int index = m_anchor->GetSelection() - 1;
    return index >= 0 && static_cast<std::size_t>(index) < m_anchors.size() ? m_anchors.at(index) : Json(nullptr);
}

std::string ResultSourceBrowser::StudyId() const
{
    const int index = m_study->GetSelection();
    return index >= 0 && static_cast<std::size_t>(index) < m_studies.size()
               ? m_studies.at(index).at("study_id").get<std::string>()
               : "";
}

Json ResultSourceBrowser::SelectedSource() const
{
    const long index = m_items->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
    const auto items = m_catalog.value("items", Json::array());
    return index >= 0 && static_cast<std::size_t>(index) < items.size() ? items.at(index).at("source") : Json(nullptr);
}

void ResultSourceBrowser::SetAnchors(const Json& response)
{
    const auto prior = Anchor();
    m_loading = true;
    m_anchors = response.value("items", Json::array());
    if (prior.is_object())
    {
        const auto selected = std::find_if(m_anchors.begin(), m_anchors.end(),
                                           [&prior](const Json& item)
                                           {
                                               return item.at("revision_id") == prior.at("revision_id") &&
                                                      item.value("snapshot_id", Json(nullptr)) ==
                                                          prior.value("snapshot_id", Json(nullptr));
                                           });
        if (selected == m_anchors.end())
        {
            // @brief 목록 페이지가 달라져도 사용자가 고른 과거 개정을 현재 개정으로 바꾸지 않는다.
            m_anchors.insert(m_anchors.begin(), prior);
        }
    }
    m_anchorOffset = response.value("offset", 0);
    m_anchorNextOffset =
        response.value("next_offset", Json(nullptr)).is_number_integer() ? response.at("next_offset").get<int>() : -1;
    m_anchor->Clear();
    m_anchor->Append(Display("현재 설계의 보존 자료"));
    m_anchor->SetSelection(0);
    for (const auto& item : m_anchors)
    {
        const int index =
            m_anchor->Append(Display(ResultUi::Text(item.value("revision_label", item.value("name", Json(nullptr))))));
        if (!prior.is_null() && item.at("revision_id") == prior.at("revision_id") &&
            item.value("snapshot_id", Json(nullptr)) == prior.value("snapshot_id", Json(nullptr)))
        {
            m_anchor->SetSelection(index);
        }
    }
    m_loading = false;
    UpdateLayout();
}

void ResultSourceBrowser::SetStudies(const Json& response)
{
    const auto prior = StudyId();
    m_loading = true;
    m_studies = response.value("studies", Json::array());
    m_study->Clear();
    for (const auto& item : m_studies)
    {
        const int index = m_study->Append(Display(item.at("name")));
        if (item.at("study_id") == prior || m_study->GetSelection() < 0)
        {
            m_study->SetSelection(index);
        }
    }
    m_loading = false;
    UpdateLayout();
}

void ResultSourceBrowser::SetCatalog(const Json& response, const Json& selected)
{
    m_loading = true;
    m_catalog = response;
    m_items->DeleteAllItems();
    for (const auto& item : response.value("items", Json::array()))
    {
        const long row = m_items->InsertItem(m_items->GetItemCount(), Display(item.at("label")));
        m_items->SetItem(row, 1, Display(ResultUi::State(item.value("result_state", Json(nullptr)))));
        if (!selected.is_null() && item.at("source") == selected)
        {
            m_items->SetItemState(row, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                                  wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
            m_items->EnsureVisible(row);
        }
    }
    const int offset = response.value("offset", 0);
    m_page->SetLabel(Display(std::to_string(offset + (m_items->GetItemCount() ? 1 : 0)) + "~" +
                             std::to_string(offset + m_items->GetItemCount()) + " / " +
                             std::to_string(response.value("total", 0))));
    m_loading = false;
    SetStatus(m_items->GetItemCount() ? "이름을 선택하면 해당 개정의 결과만 읽습니다."
                                      : "이 범위에 보존된 결과가 없습니다. 다른 종류/개정/연구를 선택하세요.");
    UpdateLayout();
}

void ResultSourceBrowser::ClearCatalog(const std::string& message)
{
    m_loading = true;
    m_catalog = Json::object();
    m_items->DeleteAllItems();
    m_page->SetLabel(Display("후보 목록 없음"));
    m_loading = false;
    SetStatus(message);
    UpdateLayout();
}

void ResultSourceBrowser::Reset()
{
    m_kind->SetSelection(0);
    SetAnchors(Json::object());
    SetStudies(Json::object());
    ClearCatalog("현재 프로젝트의 결과를 선택하세요.");
}

void ResultSourceBrowser::SetStatus(const std::string& message)
{
    m_status->SetLabel(Display(message));
    m_status->Wrap(std::max(120, GetClientSize().x - FromDIP(20)));
    Layout();
}

void ResultSourceBrowser::SetAvailable(bool available)
{
    m_available = available;
    UpdateLayout();
}

void ResultSourceBrowser::UpdateLayout()
{
    const bool network = Kind() == "network";
    m_anchor->Show(network);
    m_anchorPrevious->Show(network);
    m_anchorNext->Show(network);
    m_study->Show(Kind() == "sweep");
    for (auto* choice : {m_kind, m_anchor, m_study})
    {
        choice->Enable(m_available);
    }
    m_items->Enable(m_available);
    m_refresh->Enable(m_available);
    m_previous->Enable(m_available && m_catalog.value("offset", 0) > 0);
    m_next->Enable(m_available && m_catalog.value("next_offset", Json(nullptr)).is_number_integer());
    m_anchorPrevious->Enable(m_available && m_anchorOffset > 0);
    m_anchorNext->Enable(m_available && m_anchorNextOffset >= 0);
    Layout();
    FitInside();
}
