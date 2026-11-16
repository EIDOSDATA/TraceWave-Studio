/** @file @brief 검증 계획과 보존 판정을 명시 선택하는 native 세 열 화면이다. */
#include "rf_validation_view.h"
#include "rf_validation_model.h"
#include "result_presentation.h"
#include "studio_theme.h"
#include "studio_support.h"
#include <wx/button.h>
#include <wx/choice.h>
#include <wx/listctrl.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/wrapsizer.h>
#include <algorithm>

namespace
{
wxListCtrl* Table(wxWindow* parent, wxSizer* layout, const std::vector<std::pair<std::string, int>>& columns,
                  int height)
{
    auto* table = new wxListCtrl(parent, wxID_ANY, wxDefaultPosition, parent->FromDIP(wxSize(-1, height)),
                                 wxLC_REPORT | wxLC_SINGLE_SEL);
    table->SetMinSize(parent->FromDIP(wxSize(160, height)));
    StudioTheme::Table(*table);
    for (const auto& column : columns)
    {
        table->AppendColumn(Display(column.first), wxLIST_FORMAT_LEFT, parent->FromDIP(column.second));
    }
    layout->Add(table, 0, wxEXPAND | wxALL, parent->FromDIP(8));
    return table;
}

wxButton* Button(wxWindow* parent, wxSizer* layout, const std::string& text)
{
    auto* button = new wxButton(parent, wxID_ANY, Display(text));
    StudioTheme::Button(*button);
    layout->Add(button, 0, wxALL, parent->FromDIP(4));
    return button;
}
}

RfValidationView::RfValidationView(wxWindow* parent, wxWindow* navigation, wxWindow* conditions)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL)
{
    StudioTheme::BindSurface(*this);
    SetScrollRate(0, FromDIP(16));
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* title = new wxStaticText(this, wxID_ANY, Display("독립 RF 검증 기록"));
    StudioTheme::Title(*title);
    layout->Add(title, 0, wxALL, FromDIP(8));
    m_status = new wxStaticText(this, wxID_ANY, Display("프로젝트에 보존한 검증 기록을 선택하세요."));
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(8));
    auto* reportTools = new wxWrapSizer(wxHORIZONTAL);
    reportTools->Add(new wxStaticText(this, wxID_ANY, Display("표시 기록")), 0, wxALIGN_CENTER_VERTICAL | wxALL,
                     FromDIP(4));
    m_reportChoice = new wxChoice(this, wxID_ANY);
    m_reportChoice->SetMinSize(FromDIP(wxSize(240, -1)));
    reportTools->Add(m_reportChoice, 0, wxALL, FromDIP(4));
    m_reportsPrevious = Button(this, reportTools, "이전 판정 목록");
    m_reportsNext = Button(this, reportTools, "다음 판정 목록");
    layout->Add(reportTools, 0, wxEXPAND | wxLEFT, FromDIP(4));
    m_reportRange = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_reportRange, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_identity = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_identity, 0, wxEXPAND | wxALL, FromDIP(8));
    auto* actions = new wxWrapSizer(wxHORIZONTAL);
    m_openResult = Button(this, actions, "선택 사례의 관련 결과 열기");
    auto* oldReport = Button(this, actions, "기존 수렴 보고서 열기");
    layout->Add(actions, 0, wxEXPAND | wxLEFT, FromDIP(4));
    m_cases = Table(
        this, layout,
        {{"사례", 205}, {"비교 축", 95}, {"수준", 90}, {"실행 상태", 130}, {"결과", 135}, {"차단 / 미기록 사유", 310}},
        170);
    m_states = Table(this, layout, {{"검증 축", 145}, {"판정", 180}, {"범위와 사유", 550}}, 190);
    auto* metricsTitle = new wxStaticText(this, wxID_ANY, Display("고정한 기준과 기록 값"));
    StudioTheme::Heading(*metricsTitle);
    layout->Add(metricsTitle, 0, wxLEFT | wxRIGHT | wxTOP, FromDIP(8));
    m_metrics = Table(this, layout,
                      {{"사례", 180},
                       {"지표", 190},
                       {"주파수", 165},
                       {"참조 값", 135},
                       {"기록 값", 135},
                       {"오차", 130},
                       {"고정 한계", 130},
                       {"단위", 100},
                       {"판정", 165},
                       {"사유", 320}},
                      185);
    auto* warning =
        new wxStaticText(this, wxID_ANY,
                         Display("계산 종료, 격자/경계 안정성, 독립 모델 참조와 실측 검증은 각각 별도 판정입니다.\n"
                                 "현재 프로젝트의 물성이나 제작/측정 미정값을 이 보고서로 자동 확정하지 않습니다."));
    layout->Add(warning, 0, wxEXPAND | wxALL, FromDIP(8));
    SetSizer(layout);

    m_navigation = new wxPanel(navigation);
    StudioTheme::BindSurface(*m_navigation);
    auto* nav = new wxBoxSizer(wxVERTICAL);
    auto* navTitle = new wxStaticText(m_navigation, wxID_ANY, Display("검증 기록"));
    StudioTheme::Heading(*navTitle);
    nav->Add(navTitle, 0, wxALL, FromDIP(8));
    m_refresh = Button(m_navigation, nav, "목록 새로고침");
    m_records = new wxListCtrl(m_navigation, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL);
    StudioTheme::Table(*m_records);
    m_records->AppendColumn(Display("이름"), wxLIST_FORMAT_LEFT, FromDIP(175));
    m_records->AppendColumn(Display("실행"), wxLIST_FORMAT_LEFT, FromDIP(95));
    nav->Add(m_records, 1, wxEXPAND | wxALL, FromDIP(8));
    m_catalogRange = new wxStaticText(m_navigation, wxID_ANY, Display("기록 미조회"));
    nav->Add(m_catalogRange, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    auto* navPages = new wxWrapSizer(wxHORIZONTAL);
    m_previous = Button(m_navigation, navPages, "이전 25개");
    m_next = Button(m_navigation, navPages, "다음 25개");
    nav->Add(navPages, 0, wxEXPAND);
    m_navigation->SetSizer(nav);
    navigation->GetSizer()->Add(m_navigation, 1, wxEXPAND);

    m_conditions =
        new wxScrolledWindow(conditions, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL);
    StudioTheme::BindSurface(*m_conditions);
    m_conditions->SetScrollRate(0, FromDIP(16));
    m_conditions->SetSizer(new wxBoxSizer(wxVERTICAL));
    auto* evidenceTitle = new wxStaticText(m_conditions, wxID_ANY, Display("판정 근거 / 원본 보존"));
    StudioTheme::Heading(*evidenceTitle);
    m_conditions->GetSizer()->Add(evidenceTitle, 0, wxALL, FromDIP(8));
    m_original = AddGroup("원본과 실행 범위");
    m_basis = AddGroup("출처와 가정");
    m_limits = AddGroup("미확립과 제작 / 측정");
    m_metricDetail = AddGroup("선택 지표의 기준 / 사유");
    m_raw = AddGroup("고급 / 보존 원문", true);
    conditions->GetSizer()->Add(m_conditions, 1, wxEXPAND);
    m_navigation->Hide();
    m_conditions->Hide();

    m_refresh->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        if (onRefresh)
                        {
                            onRefresh();
                        }
                    });
    m_records->Bind(wxEVT_LIST_ITEM_SELECTED,
                    [this](wxListEvent& event)
                    {
                        if (!m_rebuilding && m_catalog.is_object() && event.GetIndex() >= 0 && onSelect)
                        {
                            const auto& item = m_catalog.at("items").at(static_cast<std::size_t>(event.GetIndex()));
                            onSelect(item.at("validation_id").get<std::string>(),
                                     item.value("latest_report_id", Json(nullptr)));
                        }
                    });
    m_previous->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         if (onCatalogPage && m_catalog.is_object())
                         {
                             onCatalogPage(std::max(0, m_catalog.value("offset", 0) - 25));
                         }
                     });
    m_next->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     if (onCatalogPage && m_catalog.is_object() &&
                         m_catalog.value("next_offset", Json(nullptr)).is_number_integer())
                     {
                         onCatalogPage(m_catalog.at("next_offset").get<int>());
                     }
                 });
    m_reportChoice->Bind(wxEVT_CHOICE,
                         [this](wxCommandEvent&)
                         {
                             const int selected = m_reportChoice->GetSelection();
                             if (!m_rebuilding && selected >= 0 &&
                                 static_cast<std::size_t>(selected) < m_reportIds.size() && onReport)
                             {
                                 onReport(m_reportIds.at(static_cast<std::size_t>(selected)));
                             }
                         });
    m_reportsPrevious->Bind(wxEVT_BUTTON,
                            [this](wxCommandEvent&)
                            {
                                if (onReportPage && m_reports.is_object())
                                {
                                    onReportPage(std::max(0, m_reports.value("offset", 0) - 25));
                                }
                            });
    m_reportsNext->Bind(wxEVT_BUTTON,
                        [this](wxCommandEvent&)
                        {
                            if (onReportPage && m_reports.is_object() &&
                                m_reports.value("next_offset", Json(nullptr)).is_number_integer())
                            {
                                onReportPage(m_reports.at("next_offset").get<int>());
                            }
                        });
    m_cases->Bind(wxEVT_LIST_ITEM_SELECTED,
                  [this](wxListEvent&)
                  {
                      ShowCase();
                  });
    m_metrics->Bind(wxEVT_LIST_ITEM_SELECTED,
                    [this](wxListEvent&)
                    {
                        ShowMetric();
                    });
    m_states->Bind(wxEVT_LIST_ITEM_SELECTED,
                   [this](wxListEvent& event)
                   {
                       const std::vector<std::string> keys{
                           "mesh", "boundary", "termination", "independent_reference", "manufacturing", "measurement"};
                       const long row = event.GetIndex();
                       if (!m_record.is_object() || row < 0 || static_cast<std::size_t>(row) >= keys.size())
                       {
                           return;
                       }
                       const auto& key = keys.at(static_cast<std::size_t>(row));
                       const auto state =
                           m_record.value("validation_states", Json::object()).value(key, Json::object());
                       m_metricDetail->ChangeValue(Display("검증 축: " + RfValidationUi::Axis(key) + "\n" +
                                                           RfValidationUi::State(state.value("state", Json(nullptr))) +
                                                           "\n\n범위와 사유\n" +
                                                           ResultUi::Text(state.value("reason", Json(nullptr)))));
                       m_metricDetail->ShowPosition(0);
                   });
    m_openResult->Bind(wxEVT_BUTTON,
                       [this](wxCommandEvent&)
                       {
                           const long selected = m_cases->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
                           if (selected >= 0 && m_record.is_object() && onOpenResult)
                           {
                               const auto& item = m_record.at("cases").at(static_cast<std::size_t>(selected));
                               if (RfValidationUi::HasSource(item))
                               {
                                   onOpenResult(item.at("source"), item.at("pin"));
                               }
                           }
                       });
    oldReport->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        if (onLegacyReport)
                        {
                            onLegacyReport();
                        }
                    });
    Bind(wxEVT_SIZE,
         [this, warning](wxSizeEvent& event)
         {
             const int width = std::max(FromDIP(220), GetClientSize().x - FromDIP(24));
             m_status->Wrap(width);
             m_identity->Wrap(width);
             m_reportRange->Wrap(width);
             warning->Wrap(width);
             Layout();
             FitInside();
             event.Skip();
         });
    Clear("프로젝트에 보존한 검증 기록을 선택하세요.");
}

wxWindow* RfValidationView::NavigationView() const
{
    return m_navigation;
}
wxWindow* RfValidationView::ConditionsView() const
{
    return m_conditions;
}

wxTextCtrl* RfValidationView::AddGroup(const std::string& label, bool collapsed)
{
    auto* group = new wxCollapsiblePane(m_conditions, wxID_ANY, Display(label), wxDefaultPosition, wxDefaultSize,
                                        wxCP_NO_TLW_RESIZE);
    auto* body = new wxBoxSizer(wxVERTICAL);
    auto* text = new wxTextCtrl(group->GetPane(), wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(100, 150)),
                                wxTE_MULTILINE | wxTE_READONLY | wxTE_WORDWRAP | wxBORDER_NONE);
    text->SetMinSize(FromDIP(wxSize(100, 150)));
    StudioTheme::BindSurface(*text);
    body->Add(text, 0, wxEXPAND | wxALL, FromDIP(8));
    group->GetPane()->SetSizer(body);
    group->Collapse(collapsed);
    group->Bind(wxEVT_COLLAPSIBLEPANE_CHANGED,
                [this](wxCollapsiblePaneEvent&)
                {
                    Relayout();
                });
    m_conditions->GetSizer()->Add(group, 0, wxEXPAND | wxALL, FromDIP(8));
    if (collapsed)
    {
        m_advanced = group;
    }
    return text;
}

void RfValidationView::Populate(wxListCtrl* table, const std::vector<std::vector<std::string>>& rows)
{
    table->DeleteAllItems();
    for (const auto& values : rows)
    {
        if (values.empty())
        {
            continue;
        }
        const auto row = table->InsertItem(table->GetItemCount(), Display(values.front()));
        for (std::size_t index = 1; index < values.size(); ++index)
        {
            table->SetItem(row, static_cast<int>(index), Display(values[index]));
        }
    }
}

void RfValidationView::Relayout()
{
    const int width = std::max(FromDIP(220), GetClientSize().x - FromDIP(24));
    m_status->Wrap(width);
    m_identity->Wrap(width);
    m_reportRange->Wrap(width);
    Layout();
    FitInside();
    m_conditions->Layout();
    m_conditions->FitInside();
}
