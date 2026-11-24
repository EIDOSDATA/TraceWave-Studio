/** @file @brief 시안 36/53의 연구 진행과 실제 종료 확인을 같은 선택에 결합한다. */
#include "sweep_panel.h"
#include "sweep_model.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/gauge.h>
#include <wx/listctrl.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/wrapsizer.h>
#include <algorithm>

SweepPanel::SweepPanel(wxWindow* parent, wxWindow* navigation, wxWindow* conditions)
    : wxScrolledWindow(parent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL)
{
    SetName("sweep.panel");
    SetScrollRate(0, FromDIP(16));
    StudioTheme::BindSurface(*this);
    auto* nav = new wxPanel(navigation);
    m_navigation = nav;
    StudioTheme::BindSurface(*nav);
    auto* navLayout = new wxBoxSizer(wxVERTICAL);
    auto* navTitle = new wxStaticText(nav, wxID_ANY, Display("저장 연구"));
    StudioTheme::Heading(*navTitle);
    navLayout->Add(navTitle, 0, wxALL, FromDIP(12));
    m_studies = new wxListCtrl(nav, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL);
    m_studies->SetName("sweep.studies");
    StudioTheme::Table(*m_studies);
    m_studies->AppendColumn(Display("연구 이름"), wxLIST_FORMAT_LEFT, FromDIP(170));
    m_studies->AppendColumn(Display("상태"), wxLIST_FORMAT_LEFT, FromDIP(90));
    navLayout->Add(m_studies, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(8));
    m_refresh = new wxButton(nav, wxID_ANY, Display("목록과 현재 상태 새로 읽기"));
    StudioTheme::Button(*m_refresh);
    m_refresh->SetName("sweep.refresh");
    navLayout->Add(m_refresh, 0, wxEXPAND | wxALL, FromDIP(8));
    nav->SetSizer(navLayout);
    auto* cond = new wxPanel(conditions);
    m_conditions = cond;
    StudioTheme::BindSurface(*cond);
    auto* condLayout = new wxBoxSizer(wxVERTICAL);
    auto* condTitle = new wxStaticText(cond, wxID_ANY, Display("고정 조건과 출처"));
    StudioTheme::Heading(*condTitle);
    condLayout->Add(condTitle, 0, wxALL, FromDIP(12));
    m_conditionText = new wxTextCtrl(cond, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize,
                                     wxTE_MULTILINE | wxTE_READONLY | wxTE_WORDWRAP);
    m_conditionText->SetName("sweep.conditions");
    condLayout->Add(m_conditionText, 1, wxEXPAND | wxALL, FromDIP(8));
    cond->SetSizer(condLayout);

    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_heading = new wxStaticText(this, wxID_ANY, Display("설계 스윕과 다축 연구"));
    StudioTheme::Title(*m_heading);
    layout->Add(m_heading, 0, wxALL, FromDIP(12));
    m_notice = new wxStaticText(this, wxID_ANY, Display(m_noticeText));
    StudioTheme::BindSecondary(*m_notice);
    layout->Add(m_notice, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    auto* actions = new wxWrapSizer(wxHORIZONTAL);
    m_create = new wxButton(this, wxID_ANY, Display("새 연구 설정"));
    m_create->SetName("sweep.create");
    StudioTheme::Button(*m_create);
    actions->Add(m_create, 0, wxALL, FromDIP(4));
    for (const auto& item : std::vector<std::pair<std::string, std::string>>{
             {"start", "선택 연구 실행"}, {"cancel", "취소 요청"}, {"resume", "명시적 재개"}, {"rank", "목표별 후보 순위"},
             {"replay", "보존 입력 다시 검토"}, {"recipe", "계산 명세 저장"}, {"export", "후보 CSV 저장"}})
    {
        auto* button = new wxButton(this, wxID_ANY, Display(item.second));
        button->SetName(Display("sweep." + item.first));
        StudioTheme::Button(*button);
        m_actions[item.first] = button;
        actions->Add(button, 0, wxALL, FromDIP(4));
        button->Bind(wxEVT_BUTTON,
                     [this, key = item.first](wxCommandEvent&)
                     {
                         if (onCommand)
                         {
                             onCommand(key);
                         }
                     });
    }
    layout->Add(actions, 0, wxEXPAND | wxALL, FromDIP(8));
    m_progressText = new wxStaticText(this, wxID_ANY, Display("저장 연구를 선택하세요."));
    layout->Add(m_progressText, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_progress = new wxGauge(this, wxID_ANY, 100, wxDefaultPosition, FromDIP(wxSize(-1, 10)));
    layout->Add(m_progress, 0, wxEXPAND | wxALL, FromDIP(12));
    m_candidates = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 210)),
                                  wxLC_REPORT | wxLC_SINGLE_SEL | wxLC_HRULES);
    m_candidates->SetName("sweep.candidates");
    m_candidates->SetMinSize(FromDIP(wxSize(-1, 210)));
    StudioTheme::Table(*m_candidates);
    for (const auto& column : std::vector<std::pair<std::string, int>>{
             {"후보", 60}, {"변수 값", 280}, {"단계와 상태", 140}, {"시도", 55}, {"완료 결과", 120}, {"이유", 350}})
    {
        m_candidates->AppendColumn(Display(column.first), wxLIST_FORMAT_LEFT, FromDIP(column.second));
    }
    layout->Add(m_candidates, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    auto* paging = new wxWrapSizer(wxHORIZONTAL);
    m_previous = new wxButton(this, wxID_ANY, Display("이전 25개"));
    m_next = new wxButton(this, wxID_ANY, Display("다음 25개"));
    m_pageLabel = new wxStaticText(this, wxID_ANY, Display("후보 없음"));
    m_result = new wxButton(this, wxID_ANY, Display("선택 후보 결과 보기"));
    m_result->SetName("sweep.result");
    m_adopt = new wxButton(this, wxID_ANY, Display("새 작업 사본으로 채택"));
    m_adopt->SetName("sweep.selection");
    m_adopt->SetToolTip(Display("현재 설계를 바꾸지 않고, 선택 후보와 새 저장 위치를 먼저 검토합니다."));
    for (auto* button : {m_previous, m_next, m_result, m_adopt})
    {
        StudioTheme::Button(*button);
    }
    paging->Add(m_previous, 0, wxALL, FromDIP(4));
    paging->Add(m_next, 0, wxALL, FromDIP(4));
    paging->Add(m_pageLabel, 0, wxALIGN_CENTER_VERTICAL | wxALL, FromDIP(4));
    paging->Add(m_result, 0, wxALL, FromDIP(4));
    paging->Add(m_adopt, 0, wxALL, FromDIP(4));
    layout->Add(paging, 0, wxEXPAND | wxALL, FromDIP(12));
    m_detail = new wxTextCtrl(this, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 100)),
                              wxTE_MULTILINE | wxTE_READONLY);
    m_detail->SetMinSize(FromDIP(wxSize(-1, 100)));
    layout->Add(m_detail, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(12));
    SetSizer(layout);
    m_adopt->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      const long row = m_candidates->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
                      if (onAdopt && row >= 0 && static_cast<std::size_t>(row) < m_rows.size())
                      {
                          onAdopt(m_rows.at(row).value("ordinal", m_offset + static_cast<int>(row)));
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
    m_create->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       if (onCreate)
                       {
                           onCreate();
                       }
                   });
    m_previous->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         if (onPage)
                         {
                             onPage(std::max(0, m_offset - 25));
                         }
                     });
    m_next->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     if (onPage && m_nextOffset >= 0)
                     {
                         onPage(m_nextOffset);
                     }
                 });
    m_studies->Bind(wxEVT_LIST_ITEM_SELECTED,
                    [this](wxListEvent& event)
                    {
                        if (!m_rebuilding && onSelect && event.GetIndex() >= 0 &&
                            static_cast<std::size_t>(event.GetIndex()) < m_ids.size())
                        {
                            onSelect(m_ids.at(event.GetIndex()));
                        }
                    });
    m_candidates->Bind(wxEVT_LIST_ITEM_SELECTED,
                       [this](wxListEvent&)
                       {
                           ShowCandidate();
                       });
    m_result->Bind(wxEVT_BUTTON,
                   [this](wxCommandEvent&)
                   {
                       const long row = m_candidates->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
                       if (onResult && row >= 0 && static_cast<std::size_t>(row) < m_rows.size())
                       {
                           onResult(m_rows.at(row).value("ordinal", m_offset + static_cast<int>(row)));
                       }
                   });
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             RefreshLayout();
             event.Skip();
         });
    Clear("새 연구 설정에서 변수와 예산을 검토하세요.");
}

SweepPanel::~SweepPanel()
{
    if (m_navigation)
    {
        m_navigation->Destroy();
    }
    if (m_conditions)
    {
        m_conditions->Destroy();
    }
}
wxWindow* SweepPanel::NavigationView() const
{
    return m_navigation.get();
}
wxWindow* SweepPanel::ConditionsView() const
{
    return m_conditions.get();
}
const std::string& SweepPanel::StudyId() const
{
    return m_id;
}
const Json& SweepPanel::Selection() const
{
    return m_study;
}
int SweepPanel::Offset() const
{
    return m_offset;
}

void SweepPanel::SetStudies(const Json& listing, const std::string& preferred)
{
    m_rebuilding = true;
    const std::string old = preferred.empty() ? m_id : preferred;
    m_studies->DeleteAllItems();
    m_ids.clear();
    m_id.clear();
    long selected = -1;
    for (const auto& study : listing.value("studies", Json::array()))
    {
        const auto id = study.at("study_id").get<std::string>();
        m_ids.push_back(id);
        const long row = m_studies->InsertItem(m_studies->GetItemCount(), Display(study.at("name")));
        m_studies->SetItem(row, 1, Display(SweepUi::Status(study.value("state", "unknown"))));
        if (id == old)
        {
            selected = row;
        }
    }
    if (selected < 0 && !m_ids.empty())
    {
        selected = 0;
    }
    if (selected >= 0)
    {
        m_id = m_ids.at(selected);
        m_studies->SetItemState(selected, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                                wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
        m_studies->EnsureVisible(selected);
    }
    m_rebuilding = false;
    UpdateActions();
}

void SweepPanel::BeginRead(const std::string& id)
{
    if (m_study.is_object() && m_study.value("study_id", "") == id)
    {
        return;
    }
    m_id = id;
    m_offset = 0;
    m_nextOffset = -1;
    m_heading->SetLabel(Display("선택 연구 조회 중"));
    m_noticeText = "선택한 연구의 입력 조건과 후보를 읽고 있습니다.";
    m_pageLabel->SetLabel(Display("후보 조회 중"));
    ClearSelection("이전 연구의 후보를 분리했습니다. 선택한 연구의 응답을 기다립니다.");
}

void SweepPanel::SetStudy(const Json& study)
{
    m_study = study;
    m_id = study.at("study_id");
    m_rebuilding = true;
    for (long row = 0; row < m_studies->GetItemCount(); ++row)
    {
        const bool selected = m_ids.at(row) == m_id;
        m_studies->SetItemState(row, selected ? wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED : 0,
                                wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
        if (selected)
        {
            m_studies->SetItem(row, 1, Display(SweepUi::Status(study.value("state", "unknown"))));
            m_studies->EnsureVisible(row);
        }
    }
    m_rebuilding = false;
    m_heading->SetLabel(Display(study.value("name", "연구")));
    const auto spec = study.value("specification", Json::object());
    m_noticeText = SweepUi::Type(spec.value("type", study.value("type", ""))) + ", " +
                   (study.value("source_revision_matches_current", false) ? "현재 원본 개정"
                                                                          : "저장 당시 원본 개정 (현재 편집과 별개)") +
                   "\n계산 완료와 목표 충족, 수치 수렴, 실측 검증을 구분합니다.";
    const auto counts = study.value("counts", Json::object());
    const int total = counts.value("total", study.value("candidate_count", 0));
    const int completed = counts.value("completed", 0);
    const int failed = counts.value("failed", 0);
    const int skipped = counts.value("skipped", 0);
    m_progressText->SetLabel(Display(SweepUi::Status(study.value("state", "unknown")) + ", 완료 " +
                                     std::to_string(completed) + ", 실패 " + std::to_string(failed) + ", 제외 " +
                                     std::to_string(skipped) + ", 전체 " + std::to_string(total)));
    m_progress->SetRange(std::max(1, total));
    m_progress->SetValue(std::min(std::max(0, completed + failed + skipped), std::max(1, total)));
    std::string conditions =
        "입력 개정\n" + SweepUi::Text(study.value("snapshot", Json::object()).value("revision_id", Json(nullptr))) +
        "\n\n연구 유형\n" + SweepUi::Type(spec.value("type", "")) + "\n\n변수\n";
    const auto original = study.value("original_specification", spec);
    for (const auto& variable : original.value("variables", Json::array()))
    {
        const auto labels = study.value("variable_labels", Json::object());
        const auto key = variable.at("kind").get<std::string>() + ":" + variable.at("id").get<std::string>();
        conditions += labels.value(key, "변수") + ": " + SweepUi::VariableSummary(variable) + "\n";
    }
    conditions += "\n고정 예산\n후보 수: " + SweepUi::Text(spec.at("budget").at("max_candidates")) +
                  "개\nEM 해석 상한: " + SweepUi::Text(spec.at("budget").at("max_native_solves")) +
                  "회\n동시 실행: 1개\n";
    const std::map<std::string, std::string> budgetNames{
        {"wall_seconds", "시간"}, {"ram_bytes", "RAM"}, {"disk_bytes", "디스크"}, {"native_solves", "실제 EM 해석"}};
    for (const auto* key : {"budget_display", "usage_display"})
    {
        if (key == std::string("usage_display"))
        {
            conditions += "\n누적 사용량 (RAM은 별도 추정)\n";
        }
        const Json data = study.value(key, Json::object());
        for (auto item = data.begin(); item != data.end(); ++item)
        {
            const auto label = budgetNames.find(item.key());
            conditions += (label == budgetNames.end() ? item.key() : label->second) + ": " +
                          item.value().value("text", "미정") + " " + item.value().value("unit", "") + "\n";
        }
    }
    conditions += "\n입력 출처와 가정\n";
    for (const auto& source : original.value("source_refs", Json::array()))
    {
        conditions += SweepUi::Text(source) + "\n";
    }
    conditions += "\n제작 및 측정 조건\n원본의 미정 상태를 유지합니다. 수렴과 실측은 별도 검증이 필요합니다.\n\n재개\n완료 "
                  "후보와 이전 시도를 보존합니다. 해석 내부 시간 단계 재개 기능은 아닙니다.";
    m_conditionText->ChangeValue(Display(conditions));
    SetStatus(study.value("message", "") + (study.value("stop_reason", Json(nullptr)).is_null()
                                                ? ""
                                                : "\n" + SweepUi::Text(study.at("stop_reason"))));
    UpdateActions();
    RefreshLayout();
}

void SweepPanel::SetPage(const Json& page)
{
    m_offset = page.value("offset", 0);
    m_nextOffset =
        page.value("next_offset", Json(nullptr)).is_number_integer() ? page.at("next_offset").get<int>() : -1;
    m_rows = page.value("candidates", Json::array());
    const long selected = m_candidates->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
    m_candidates->DeleteAllItems();
    for (const auto& candidate : m_rows)
    {
        const long row = m_candidates->InsertItem(
            m_candidates->GetItemCount(),
            Display(std::to_string(
                candidate.value("ordinal", m_offset + static_cast<int>(m_candidates->GetItemCount())) + 1)));
        m_candidates->SetItem(row, 1, Display(SweepUi::CandidateValues(candidate)));
        m_candidates->SetItem(
            row, 2,
            Display(SweepUi::Status(candidate.value("state", "pending")) + ", " +
                    SweepUi::Status(candidate.value("outcome", candidate.value("validation_status", "")))));
        m_candidates->SetItem(row, 3, Display(std::to_string(candidate.value("attempts", Json::array()).size())));
        m_candidates->SetItem(
            row, 4, Display(candidate.value("results", Json::object()).contains("dataset") ? "결과 있음" : "없음"));
        std::string reason = candidate.value("message", "") +
                             SweepUi::Diagnostics(candidate.value("diagnostics", Json::array()));
        if (candidate.contains("cached_from_ordinal"))
        {
            reason = "후보 " + std::to_string(candidate.at("cached_from_ordinal").get<int>() + 1) + "의 계산 재사용, " + reason;
        }
        m_candidates->SetItem(row, 5, Display(reason));
    }
    if (!m_rows.empty())
    {
        const long row = std::clamp(selected, 0L, static_cast<long>(m_rows.size()) - 1);
        m_candidates->SetItemState(row, wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED,
                                   wxLIST_STATE_SELECTED | wxLIST_STATE_FOCUSED);
    }
    m_pageLabel->SetLabel(Display(std::to_string(m_offset + (m_rows.empty() ? 0 : 1)) + "~" +
                                  std::to_string(m_offset + m_rows.size()) + " (전체 " +
                                  std::to_string(page.value("total", 0)) + "개)"));
    ShowCandidate();
    UpdateActions();
    RefreshLayout();
}

void SweepPanel::ShowCandidate()
{
    const long row = m_candidates->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
    if (row < 0 || static_cast<std::size_t>(row) >= m_rows.size())
    {
        m_detail->Clear();
        UpdateActions();
        return;
    }
    const auto& candidate = m_rows.at(row);
    m_detail->ChangeValue(Display(
        "후보 " + std::to_string(candidate.value("ordinal", m_offset + static_cast<int>(row)) + 1) + ", " +
        SweepUi::Status(candidate.value("state", "pending")) + "\n" + SweepUi::CandidateValues(candidate) + "\n" +
        candidate.value("message", "") + "\n" + SweepUi::Diagnostics(candidate.value("diagnostics", Json::array()))));
    UpdateActions();
}

void SweepPanel::SetEnabledState(bool available, bool busy, bool uncertain)
{
    m_available = available;
    m_busy = busy;
    m_uncertain = uncertain;
    UpdateActions();
}
void SweepPanel::SetSelectionSupported(bool supported)
{
    m_selectionSupported = supported;
    UpdateActions();
}
void SweepPanel::SetStatus(const std::string& text)
{
    m_statusText = text;
    RefreshLayout();
}
void SweepPanel::ClearSelection(const std::string& text)
{
    m_study = nullptr;
    m_rows = Json::array();
    m_candidates->DeleteAllItems();
    m_detail->Clear();
    m_conditionText->Clear();
    m_progress->SetValue(0);
    m_progressText->SetLabel(Display("연구 상태를 읽어야 합니다."));
    SetStatus(text);
    UpdateActions();
}
void SweepPanel::Clear(const std::string& text)
{
    m_rebuilding = true;
    m_id.clear();
    m_ids.clear();
    m_studies->DeleteAllItems();
    m_rebuilding = false;
    ClearSelection(text);
}
void SweepPanel::UpdateActions()
{
    const bool enabled = m_available && !m_busy;
    m_refresh->Enable(enabled);
    m_studies->Enable(enabled);
    m_create->Enable(enabled && !m_uncertain);
    const Json allowed = m_study.is_object() ? m_study.value("allowed_actions", Json::array()) : Json::array();
    for (const auto& action : m_actions)
    {
        const bool permitted = allowed.is_array()
                                   ? std::find(allowed.begin(), allowed.end(), Json(action.first)) != allowed.end()
                                   : allowed.value(action.first, false);
        action.second->Enable(enabled && !m_uncertain && permitted);
    }
    m_previous->Enable(enabled && m_offset > 0 && !m_study.is_null());
    m_next->Enable(enabled && m_nextOffset >= 0 && !m_study.is_null());
    const long row = m_candidates->GetNextItem(-1, wxLIST_NEXT_ALL, wxLIST_STATE_SELECTED);
    m_result->Enable(enabled && row >= 0 && static_cast<std::size_t>(row) < m_rows.size() &&
                     m_rows.at(row).value("results", Json::object()).contains("dataset"));
    m_adopt->Enable(enabled && !m_uncertain && m_selectionSupported && row >= 0 &&
                    static_cast<std::size_t>(row) < m_rows.size());
}
void SweepPanel::RefreshLayout()
{
    const int width = std::max(180, GetClientSize().x - FromDIP(28));
    m_notice->SetLabel(Display(m_noticeText));
    m_notice->Wrap(width);
    m_status->SetLabel(Display(m_statusText));
    m_status->Wrap(width);
    Layout();
    FitInside();
}
