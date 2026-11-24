/** @file @brief 시안 40의 저장된 목표 평가, 조건 차이와 실제 표본을 표시한다. */
#include "network_assessment_panel.h"
#include "frequency_display.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/listctrl.h>
#include <wx/scrolwin.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <wx/wrapsizer.h>
#include <algorithm>
#include <array>

namespace
{
/** @brief 없는 조건은 이름이나 다른 결과 값으로 채우지 않는다. */
std::string Text(const Json& value)
{
    if (value.is_null() || value == "unknown" || value == "")
    {
        return "미정";
    }
    return value.is_string() ? value.get<std::string>() : value.dump();
}

std::string Metric(const std::string& value)
{
    return value == "s11_db"                 ? "반사 (S11)"
           : value == "radiation_efficiency" ? "방사 효율"
           : value == "total_efficiency"     ? "총 효율"
           : value == "fractional_bandwidth" ? "비대역폭 (FBW)"
                                             : value;
}

std::string Status(const std::string& value)
{
    return value == "conditional" ? "표본 통과 / 조건부"
           : value == "pass"      ? "표본 통과"
           : value == "fail"      ? "실패"
                                  : "미평가";
}

/** @brief 판정 때의 목표 원문 또는 큰 원문의 요약을 같은 표시 이름으로 찾는다. */
Json OriginalTarget(const Json& assessment)
{
    const auto& evidence = assessment.at("evidence");
    return evidence.contains("target_original") ? evidence.at("target_original")
                                                : evidence.value("target_original_summary", Json::object());
}

/** @brief 상태는 색에 의존하지 않고 한국어 텍스트로 함께 표시한다. */
void ApplyNoticeColours(wxPanel& panel, wxStaticText& label)
{
    const auto colours = StudioTheme::Colours();
    panel.SetBackgroundColour(colours.selection);
    label.SetForegroundColour(colours.text);
    panel.Refresh();
}
}

NetworkAssessmentPanel::NetworkAssessmentPanel(wxWindow* centerParent, wxWindow* navigationParent,
                                               wxWindow* conditionsParent)
    : wxScrolledWindow(centerParent, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL | wxTAB_TRAVERSAL)
{
    SetName("network.assessment.panel");
    SetScrollRate(0, FromDIP(16));
    StudioTheme::ApplyTypography(*this);
    StudioTheme::BindSurface(*this);
    BuildNavigation(navigationParent);
    BuildConditions(conditionsParent);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* heading = new wxStaticText(this, wxID_ANY, Display("목표 평가"));
    StudioTheme::Title(*heading);
    layout->Add(heading, 0, wxLEFT | wxRIGHT | wxTOP, FromDIP(12));
    m_contextLabel = new wxStaticText(this, wxID_ANY, Display("저장된 평가를 선택하거나 새 평가를 만드세요."));
    StudioTheme::BindSecondary(*m_contextLabel);
    layout->Add(m_contextLabel, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    layout->AddSpacer(FromDIP(8));
    auto* noticePanel = new wxPanel(this);
    auto* noticeLayout = new wxBoxSizer(wxHORIZONTAL);
    m_notice = new wxStaticText(noticePanel, wxID_ANY, Display("목표 개정과 결과 입력이 일치하는지 먼저 확인합니다."));
    noticeLayout->Add(m_notice, 1, wxEXPAND | wxALL, FromDIP(8));
    noticePanel->SetSizer(noticeLayout);
    ApplyNoticeColours(*noticePanel, *m_notice);
    noticePanel->Bind(wxEVT_SYS_COLOUR_CHANGED,
                      [noticePanel, label = m_notice](wxSysColourChangedEvent& event)
                      {
                          ApplyNoticeColours(*noticePanel, *label);
                          event.Skip();
                      });
    layout->Add(noticePanel, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    layout->AddSpacer(FromDIP(8));
    m_criteria = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 136)),
                                wxLC_REPORT | wxLC_SINGLE_SEL | wxLC_HRULES);
    m_criteria->SetName("network.assessment.panel.criteria");
    m_criteria->SetMinSize(FromDIP(wxSize(-1, 136)));
    const std::array<std::pair<const char*, int>, 5> columns{
        {{"목표 / 지표", 175}, {"기준", 125}, {"평가 표본", 125}, {"상태", 180}, {"이유", 360}}};
    for (const auto& column : columns)
    {
        m_criteria->AppendColumn(Display(column.first), wxLIST_FORMAT_LEFT, FromDIP(column.second));
    }
    StudioTheme::Table(*m_criteria);
    layout->Add(m_criteria, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_validation = new wxStaticText(
        this, wxID_ANY, Display("표본 판정: 미평가 | 연속 대역: 미확립 | 수치 수렴 / 실측 검증: 별도 확인"));
    layout->AddSpacer(FromDIP(8));
    layout->Add(m_validation, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_reason = new wxStaticText(this, wxID_ANY, wxEmptyString);
    StudioTheme::BindSecondary(*m_reason);
    layout->Add(m_reason, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    layout->AddSpacer(FromDIP(8));
    m_pointHeading = new wxStaticText(this, wxID_ANY, Display("선택한 기준의 실제 표본"));
    StudioTheme::Heading(*m_pointHeading);
    layout->Add(m_pointHeading, 0, wxLEFT | wxRIGHT, FromDIP(12));
    layout->AddSpacer(FromDIP(4));
    m_points = new wxListCtrl(this, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 128)),
                              wxLC_REPORT | wxLC_SINGLE_SEL | wxLC_HRULES);
    m_points->SetName("network.assessment.panel.points");
    m_points->SetMinSize(FromDIP(wxSize(-1, 128)));
    const std::array<std::pair<const char*, int>, 4> pointColumns{
        {{"주파수 (Hz)", 170}, {"평가 값", 170}, {"판정", 145}, {"이유", 480}}};
    for (const auto& column : pointColumns)
    {
        m_points->AppendColumn(Display(column.first), wxLIST_FORMAT_LEFT, FromDIP(column.second));
    }
    StudioTheme::Table(*m_points);
    layout->Add(m_points, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    auto* paging = new wxWrapSizer(wxHORIZONTAL);
    m_pageLabel = new wxStaticText(this, wxID_ANY, Display("표본 없음 / 미평가"));
    paging->Add(m_pageLabel, 0, wxALIGN_CENTER_VERTICAL | wxALL, FromDIP(4));
    m_allPoints = new wxButton(this, wxID_ANY, Display("전체 표본 보기"));
    m_previous = new wxButton(this, wxID_ANY, Display("이전 표본"));
    m_next = new wxButton(this, wxID_ANY, Display("다음 표본"));
    for (auto* button : {m_allPoints, m_previous, m_next})
    {
        StudioTheme::Button(*button);
        paging->Add(button, 0, wxALL, FromDIP(4));
    }
    layout->Add(paging, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    auto* actions = new wxWrapSizer(wxHORIZONTAL);
    m_original = new wxButton(this, wxID_ANY, Display("목표 원문 / 출처 보기"));
    m_evaluate = new wxButton(this, wxID_ANY, Display("새 평가 / 재평가"));
    m_evaluate->SetName("network.assessment.panel.evaluate");
    StudioTheme::Button(*m_original);
    StudioTheme::Button(*m_evaluate, true);
    actions->Add(m_original, 0, wxALL, FromDIP(4));
    actions->Add(m_evaluate, 0, wxALL, FromDIP(4));
    layout->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_status = new wxStaticText(this, wxID_ANY,
                                Display("재평가는 새 판정 기록을 만들며 과거 목표와 결과를 덮어쓰지 않습니다."));
    StudioTheme::BindSecondary(*m_status);
    layout->Add(m_status, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    SetSizer(layout);
    m_evaluate->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         if (m_evaluate->IsEnabled() && onEvaluate)
                         {
                             onEvaluate();
                         }
                     });
    m_original->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         m_conditionTabs->SetSelection(1);
                         m_source->SetFocus();
                     });
    m_criteria->Bind(wxEVT_LIST_ITEM_SELECTED,
                     [this](wxListEvent& event)
                     {
                         if (!m_rebuilding)
                         {
                             SelectCriterion(static_cast<int>(event.GetIndex()), true);
                         }
                     });
    m_allPoints->Bind(wxEVT_BUTTON,
                      [this](wxCommandEvent&)
                      {
                          RequestPoints(0);
                      });
    m_previous->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         RequestPoints(std::max(0, m_offset - 201));
                     });
    m_next->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     RequestPoints(m_nextOffset);
                 });
    Bind(wxEVT_SIZE,
         [this](wxSizeEvent& event)
         {
             const int width = std::max(FromDIP(280), GetClientSize().x - FromDIP(32));
             for (auto* label : {m_contextLabel, m_notice, m_validation, m_reason, m_status})
             {
                 label->Wrap(width);
             }
             UpdateLayout();
             event.Skip();
         });
    UpdateActions();
    UpdateLayout();
}

NetworkAssessmentPanel::~NetworkAssessmentPanel()
{
    onSelect = {};
    onPoints = {};
    onEvaluate = {};
    onRefresh = {};
}

void NetworkAssessmentPanel::BuildNavigation(wxWindow* parent)
{
    auto* panel = new wxPanel(parent);
    m_navigation = panel;
    StudioTheme::ApplyTypography(*panel);
    StudioTheme::BindSurface(*panel);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* heading = new wxStaticText(panel, wxID_ANY, Display("저장된 목표 평가"));
    StudioTheme::Heading(*heading);
    layout->Add(heading, 0, wxALL, FromDIP(12));
    m_records =
        new wxListCtrl(panel, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL | wxLC_HRULES);
    m_records->SetName("network.assessment.panel.records");
    m_records->AppendColumn(Display("평가 이름"), wxLIST_FORMAT_LEFT, FromDIP(160));
    m_records->AppendColumn(Display("판정"), wxLIST_FORMAT_LEFT, FromDIP(160));
    StudioTheme::Table(*m_records);
    layout->Add(m_records, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(4));
    m_refresh = new wxButton(panel, wxID_ANY, Display("평가 다시 읽기"));
    StudioTheme::Button(*m_refresh);
    layout->Add(m_refresh, 0, wxEXPAND | wxALL, FromDIP(8));
    panel->SetSizer(layout);
    wxWeakRef<NetworkAssessmentPanel> owner(this);
    m_records->Bind(wxEVT_LIST_ITEM_SELECTED,
                    [owner](wxListEvent& event)
                    {
                        if (owner && !owner->m_rebuilding && event.GetIndex() >= 0 &&
                            static_cast<std::size_t>(event.GetIndex()) < owner->m_ids.size())
                        {
                            owner->m_identity = owner->m_ids[static_cast<std::size_t>(event.GetIndex())];
                            owner->RequestSelected();
                        }
                    });
    m_refresh->Bind(wxEVT_BUTTON,
                    [owner](wxCommandEvent&)
                    {
                        if (owner && owner->m_available && !owner->m_busy && owner->onRefresh)
                        {
                            owner->onRefresh();
                        }
                    });
}

void NetworkAssessmentPanel::BuildConditions(wxWindow* parent)
{
    auto* panel = new wxPanel(parent);
    m_conditions = panel;
    StudioTheme::ApplyTypography(*panel);
    StudioTheme::BindSurface(*panel);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* heading = new wxStaticText(panel, wxID_ANY, Display("평가 조건과 출처"));
    StudioTheme::Title(*heading);
    layout->Add(heading, 0, wxALL, FromDIP(12));
    m_conditionTabs = new StudioNotebook(panel);
    auto* summary = new wxScrolledWindow(m_conditionTabs, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL);
    summary->SetScrollRate(0, FromDIP(12));
    auto* summaryLayout = new wxBoxSizer(wxVERTICAL);
    m_conditionSummary = new wxStaticText(summary, wxID_ANY, Display("저장된 평가를 선택하세요."));
    summaryLayout->Add(m_conditionSummary, 0, wxEXPAND | wxALL, FromDIP(12));
    summary->SetSizer(summaryLayout);
    m_conditionTabs->AddPage(summary, Display("판정 조건"));
    m_source = new wxTextCtrl(m_conditionTabs, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize,
                              wxTE_MULTILINE | wxTE_READONLY);
    m_source->SetName("network.assessment.panel.source");
    m_conditionTabs->AddPage(m_source, Display("목표 원문 / 출처"));
    layout->Add(m_conditionTabs, 1, wxEXPAND);
    auto* notice = new wxStaticText(
        panel, wxID_ANY,
        Display("표본 통과와 연속 대역, 수렴, 실측 검증은 별도입니다. 제작/측정 미정값을 확정하지 않습니다."));
    notice->Wrap(FromDIP(278));
    StudioTheme::BindSecondary(*notice);
    layout->Add(notice, 0, wxEXPAND | wxALL, FromDIP(12));
    panel->SetSizer(layout);
}

wxWindow* NetworkAssessmentPanel::NavigationView() const
{
    return m_navigation.get();
}
wxWindow* NetworkAssessmentPanel::ConditionsView() const
{
    return m_conditions.get();
}
const Json& NetworkAssessmentPanel::Library() const
{
    return m_library;
}
const Json& NetworkAssessmentPanel::Selection() const
{
    return m_selection;
}
const std::string& NetworkAssessmentPanel::AssessmentId() const
{
    return m_identity;
}
int NetworkAssessmentPanel::CriterionIndex() const
{
    return m_criterion;
}

std::string NetworkAssessmentPanel::RecordName(const std::string& collection, const Json& identity) const
{
    for (const auto& row : m_library.value(collection, Json::array()))
    {
        if (row.at("id") == identity)
        {
            return row.at("name").get<std::string>();
        }
    }
    return "목록에서 확인할 수 없음";
}

void NetworkAssessmentPanel::SetLibrary(const Json& context, const std::string& preferredId)
{
    const std::string desired = preferredId.empty() ? m_identity : preferredId;
    m_library = context;
    m_rebuilding = true;
    m_records->DeleteAllItems();
    m_ids.clear();
    long selected = -1;
    for (const auto& record : context.at("assessments"))
    {
        const long row =
            m_records->InsertItem(m_records->GetItemCount(), Display(record.at("name").get<std::string>()));
        m_records->SetItem(row, 1, Display(Status(record.at("status"))));
        m_ids.push_back(record.at("id"));
        if (m_ids.back() == desired)
        {
            selected = row;
        }
    }
    if (selected < 0 && !m_ids.empty())
    {
        selected = 0;
    }
    m_identity = selected < 0 ? "" : m_ids[static_cast<std::size_t>(selected)];
    if (selected >= 0)
    {
        m_records->SetItemState(selected, wxLIST_STATE_SELECTED, wxLIST_STATE_SELECTED);
        m_records->EnsureVisible(selected);
    }
    m_rebuilding = false;
    ClearSelection(m_ids.empty() ? "저장된 평가가 없습니다. 목표와 복소 자료를 선택하여 새 평가를 만드세요."
                                 : "선택한 평가를 읽어야 합니다.");
}

void NetworkAssessmentPanel::ClearSelection(const std::string& message)
{
    m_selection = nullptr;
    m_dataset = nullptr;
    m_criterion = -1;
    m_displayedPoints = Json::array();
    m_offset = 0;
    m_total = 0;
    m_nextOffset = -1;
    m_pointsPreview = true;
    m_criteria->DeleteAllItems();
    m_points->DeleteAllItems();
    m_contextLabel->SetLabel(Display("목표와 자료가 연결된 저장 기록을 선택하세요."));
    m_notice->SetLabel(Display("목표 개정과 결과 입력이 일치하는지 먼저 확인합니다."));
    m_validation->SetLabel(Display("표본 판정: 미평가 | 연속 대역: 미확립 | 수치 수렴 / 실측 검증: 별도 확인"));
    m_reason->SetLabel(wxEmptyString);
    m_pointHeading->SetLabel(Display("선택한 기준의 실제 표본"));
    m_pageLabel->SetLabel(Display("표본 없음 / 미평가"));
    m_conditionSummary->SetLabel(Display("저장된 평가의 조건을 조회해야 합니다."));
    m_source->Clear();
    SetStatus(message);
    UpdateActions();
}

void NetworkAssessmentPanel::Clear(const std::string& message)
{
    m_library = Json::object();
    m_identity.clear();
    m_ids.clear();
    m_records->DeleteAllItems();
    ClearSelection(message);
}

void NetworkAssessmentPanel::RequestSelected()
{
    if (!m_available || m_busy || m_identity.empty() || !onSelect)
    {
        return;
    }
    onSelect(m_identity);
}

void NetworkAssessmentPanel::SetAssessment(const Json& result)
{
    if (result.at("entry").at("id") != m_identity)
    {
        ClearSelection("선택과 다른 평가 응답을 표시하지 않았습니다. 다시 읽으세요.");
        return;
    }
    m_selection = result;
    m_dataset = nullptr;
    const auto& assessment = result.at("assessment");
    const Json target = OriginalTarget(assessment);
    const std::string targetName = target.value("name", "목표 원문 확인 필요");
    m_contextLabel->SetLabel(Display("평가: " + result.at("entry").at("name").get<std::string>() +
                                     " | 자료: " + RecordName("datasets", result.at("entry").at("dataset_id")) +
                                     " | 당시 목표: " + targetName));
    m_notice->SetLabel(
        Display(result.value("target_changed", true)
                    ? "현재 목표가 변경되었거나 삭제되었습니다. 아래 표는 평가 당시 목표의 판정을 유지합니다."
                    : "현재 목표 개정과 평가 당시 목표 개정이 같습니다. 표본 판정과 물리 검증은 구분합니다."));
    m_rebuilding = true;
    m_criteria->DeleteAllItems();
    for (const auto& criterion : assessment.at("criteria"))
    {
        const long row = m_criteria->InsertItem(m_criteria->GetItemCount(), Display(Metric(criterion.at("metric"))));
        const auto& limit = criterion.at("limit");
        const std::string bound = limit.at("value").is_null()
                                      ? "미정"
                                      : (criterion.at("operator") == "le" ? "<= " : ">= ") + Text(limit.at("value")) +
                                            " " + Text(limit.at("unit"));
        m_criteria->SetItem(row, 1, Display(bound));
        m_criteria->SetItem(row, 2,
                            Display(Text(criterion.at("coverage").at("available")) + " / " +
                                    Text(criterion.at("coverage").at("required"))));
        m_criteria->SetItem(row, 3, Display(Status(criterion.at("status"))));
        m_criteria->SetItem(row, 4, Display(criterion.value("reason", "")));
    }
    m_rebuilding = false;
    m_validation->SetLabel(Display("표본 판정: " + Status(assessment.at("status")) +
                                   " | 연속 대역: 미확립 | 수치 수렴 / 실측 검증: 별도 확인"));
    m_criterion = assessment.at("criteria").empty() ? -1 : 0;
    if (m_criterion >= 0)
    {
        m_rebuilding = true;
        m_criteria->SetItemState(0, wxLIST_STATE_SELECTED, wxLIST_STATE_SELECTED);
        m_rebuilding = false;
        SelectCriterion(0, false);
    }
    else
    {
        ShowPoints(Json::array(), 0, 0, true);
        m_reason->SetLabel(Display("평가 당시 목표에 성능 기준이 없어 미평가입니다."));
    }
    ShowConditions();
    SetStatus("재평가는 새 판정 기록을 만듭니다. 과거 목표/결과와 제작·측정 미정 조건은 유지됩니다.");
    UpdateActions();
}

void NetworkAssessmentPanel::SetDataset(const Json& result)
{
    if (m_selection.is_null() || result.at("entry").at("id") != m_selection.at("entry").at("dataset_id"))
    {
        return;
    }
    m_dataset = result;
    ShowPoints(m_displayedPoints, m_offset, m_total, m_pointsPreview);
    ShowConditions();
}

void NetworkAssessmentPanel::ShowConditions()
{
    if (m_selection.is_null())
    {
        return;
    }
    const auto& assessment = m_selection.at("assessment");
    const Json target = OriginalTarget(assessment);
    std::string summary = "평가 당시 목표: " + target.value("name", "원문 확인 필요") +
                          "\n평가 자료: " + RecordName("datasets", m_selection.at("entry").at("dataset_id"));
    summary += "\n\n현재 목표: " + std::string(m_selection.at("current_target_revision").is_null() ? "삭제되었거나 없음"
                                               : m_selection.value("target_changed", true) ? "평가 당시와 개정 다름"
                                                                                           : "평가 당시와 같은 개정");
    summary += "\n평가 기준면: " + Text(assessment.at("context").at("reference_plane"));
    summary += "\n표본 정책: 정확히 같은 주파수만\n보간 / 기준면 자동 보정: 없음";
    if (target.contains("reference_impedance"))
    {
        summary += "\n목표 Z0: " + Text(target.at("reference_impedance").at("value_si")) + " ohm";
    }
    else
    {
        summary += "\n큰 목표 원문: 봉인 파일에 전체 보존";
    }
    if (m_dataset.is_null())
    {
        summary += "\n\n원본 자료 조건: 조회 대기 / 확인 전";
    }
    else
    {
        const auto& descriptor = m_dataset.at("descriptor");
        summary += "\n\n파 정의: " + Text(descriptor.at("wave_definition"));
        summary += "\n시간 규약: " + Text(descriptor.at("phasor_convention"));
        for (std::size_t index = 0; index < descriptor.at("port_ids").size(); ++index)
        {
            if (descriptor.at("port_ids").at(index) == assessment.at("context").at("port_id"))
            {
                const auto& name = descriptor.at("port_names").at(index);
                summary += "\n평가 자료 포트: " + (name.is_null() ? "포트 " + std::to_string(index + 1) : Text(name));
                summary += "\n자료 기준면: " + Text(descriptor.at("reference_planes").at(index));
                summary += "\n첫 표본 Z0 (실수, 허수): " +
                           Text(descriptor.at("z0_ohm").is_null() ? Json(nullptr) : descriptor.at("z0_ohm").at(index)) +
                           " ohm";
            }
        }
        if (descriptor.value("z0_frequency_dependent", false))
        {
            summary += "\nZ0는 주파수별입니다. 전체 조건은 원문에 보존됩니다.";
        }
        const auto& conditions = descriptor.at("conditions");
        for (const auto& entry : std::array<std::pair<const char*, const char*>, 2>{
                 {{"manufacturing", "제작 조건"}, {"measurement", "측정 조건"}}})
        {
            summary +=
                "\n" + std::string(entry.second) + ": " +
                (conditions.is_null() || !conditions.contains(entry.first) || conditions.at(entry.first).is_null()
                     ? "미정"
                     : "원문 있음 / 확정 여부는 출처 확인");
        }
    }
    const auto& evidence = assessment.at("evidence");
    if (evidence.contains("matching"))
    {
        const auto& matching = evidence.at("matching");
        summary += "\n\n정합 전 부하 기준면: " + Text(matching.at("load_reference_plane")) +
                   "\n정합 후 입력 기준면: " + Text(matching.at("input_reference_plane")) +
                   "\n이상 RLC 손실: 입사전력 대비. 표본별 회로 진단을 참조하세요.";
    }
    summary += "\n\n연속 대역 / 수치 수렴 / 실측 검증: 이 표본 평가로 확립하지 않음";
    m_conditionSummary->SetLabel(Display(summary));
    m_conditionSummary->Wrap(FromDIP(278));
    auto* scrolled = static_cast<wxScrolledWindow*>(m_conditionSummary->GetParent());
    scrolled->Layout();
    scrolled->FitInside();
    Json source{{"평가 당시 목표와 자료 근거", assessment.at("evidence")},
                {"목표 출처", assessment.at("source_refs")},
                {"지표 출처", assessment.at("metric_source_refs")},
                {"현재 목표 개정", m_selection.at("current_target_revision")},
                {"과거 평가 원본", m_selection.at("entry")}};
    if (!m_dataset.is_null())
    {
        source["자료 조건과 출처"] = m_dataset.at("descriptor");
    }
    m_source->ChangeValue(Display(source.dump(2, ' ', false, Json::error_handler_t::replace)));
}

void NetworkAssessmentPanel::SelectCriterion(int index, bool request)
{
    if (m_selection.is_null() || index < 0 ||
        index >= static_cast<int>(m_selection.at("assessment").at("criteria").size()))
    {
        return;
    }
    m_criterion = index;
    const auto& criterion = m_selection.at("assessment").at("criteria").at(index);
    m_pointHeading->SetLabel(Display(Metric(criterion.at("metric")) + " / 실제 표본"));
    std::string reason = criterion.value("reason", "");
    if (criterion.contains("sampled_estimate") && !criterion.at("sampled_estimate").is_null())
    {
        reason += "\n통과 표본 폭 추정: " + Text(criterion.at("sampled_estimate").at("value")) +
                  " (비율). 임계 교차점 미검증으로 FBW 최종 판정은 미평가입니다.";
    }
    m_reason->SetLabel(Display(reason));
    m_reason->Wrap(std::max(FromDIP(280), GetClientSize().x - FromDIP(32)));
    ShowPoints(criterion.at("points_preview"), 0, criterion.at("point_count"), true);
    if (request && m_total > 0)
    {
        RequestPoints(0);
    }
    UpdateLayout();
}

void NetworkAssessmentPanel::ShowPoints(const Json& points, int offset, int total, bool preview)
{
    m_displayedPoints = points;
    m_offset = offset;
    m_total = total;
    m_pointsPreview = preview;
    if (preview)
    {
        m_nextOffset = -1;
    }
    m_points->DeleteAllItems();
    std::string unit;
    if (!m_selection.is_null() && m_criterion >= 0)
    {
        unit = Text(m_selection.at("assessment").at("criteria").at(m_criterion).at("limit").at("unit"));
    }
    wxListItem column;
    column.SetText(Display("평가 값" + (unit.empty() ? "" : " (" + unit + ")")));
    m_points->SetColumn(1, column);
    const auto frequencyScale =
        StudioFrequency::ForAssessment(m_selection.is_object() ? m_selection.at("assessment") : Json(nullptr),
                                       m_dataset.is_object() ? m_dataset.at("descriptor") : Json(nullptr));
    column.SetText(Display("주파수 (" + frequencyScale.unit + ")"));
    m_points->SetColumn(0, column);
    for (const auto& point : points)
    {
        const long row = m_points->InsertItem(
            m_points->GetItemCount(), Display(StudioFrequency::Value(point.at("frequency_hz"), frequencyScale)));
        const std::string state = point.value("value_state", "missing");
        const std::string value = state == "negative_infinity"   ? "-inf (반사 0)"
                                  : state == "positive_infinity" ? "+inf"
                                                                 : Text(point.at("value"));
        m_points->SetItem(row, 1, Display(value));
        m_points->SetItem(row, 2, Display(Status(point.at("status"))));
        m_points->SetItem(row, 3, Display(point.at("reason").is_null() ? "" : Text(point.at("reason"))));
    }
    m_pageLabel->SetLabel(Display(std::string(preview ? "요약 미리보기 " : "저장된 실제 표본 ") +
                                  std::to_string(points.empty() ? 0 : offset + 1) + "-" +
                                  std::to_string(offset + points.size()) + " / " + std::to_string(total) + "개"));
    UpdateActions();
}

void NetworkAssessmentPanel::RequestPoints(int offset)
{
    if (!m_available || m_busy || m_selection.is_null() || m_criterion < 0 || offset < 0 || m_total == 0 || !onPoints)
    {
        return;
    }
    onPoints(m_criterion, offset);
}

void NetworkAssessmentPanel::SetPoints(const Json& result)
{
    if (m_selection.is_null() || m_criterion < 0)
    {
        return;
    }
    m_nextOffset = result.at("next_offset").is_null() ? -1 : result.at("next_offset").get<int>();
    ShowPoints(result.at("points"), result.at("offset"), result.at("total"), false);
}

void NetworkAssessmentPanel::SetEnabledState(bool available, bool busy)
{
    m_available = available;
    m_busy = busy;
    UpdateActions();
}

void NetworkAssessmentPanel::SetStatus(const std::string& message)
{
    m_status->SetLabel(Display(message));
    const int width = std::max(FromDIP(280), GetClientSize().x - FromDIP(32));
    for (auto* label : {m_contextLabel, m_notice, m_validation, m_reason, m_status})
    {
        label->Wrap(width);
    }
    UpdateLayout();
}

void NetworkAssessmentPanel::UpdateLayout()
{
    Layout();
    FitInside();
}

void NetworkAssessmentPanel::UpdateActions()
{
    if (!m_evaluate)
    {
        return;
    }
    const bool ready = m_available && !m_busy;
    const bool hasAssessment = m_selection.is_object();
    const bool hasPoints = hasAssessment && m_criterion >= 0;
    const bool selected = ready && hasAssessment;
    const std::array<wxWindow*, 4> summary{m_contextLabel, m_notice->GetParent(), m_validation, m_reason};
    const std::array<wxWindow*, 6> samples{m_pointHeading, m_points, m_pageLabel, m_allPoints, m_previous, m_next};
    bool reflow = m_criteria->Show(hasAssessment && m_criteria->GetItemCount() > 0);
    for (auto* control : summary)
    {
        reflow = control->Show(hasAssessment) || reflow;
    }
    for (auto* control : samples)
    {
        reflow = control->Show(hasPoints) || reflow;
    }
    if (reflow)
    {
        UpdateLayout();
    }
    m_records->Enable(ready);
    m_refresh->Enable(ready);
    m_criteria->Enable(selected);
    m_original->Enable(selected);
    m_allPoints->Enable(selected && m_criterion >= 0 && m_total > 0);
    m_previous->Enable(selected && !m_pointsPreview && m_offset > 0);
    m_next->Enable(selected && !m_pointsPreview && m_nextOffset >= 0);
    m_evaluate->Enable(ready && !m_library.value("targets", Json::array()).empty() &&
                       !m_library.value("datasets", Json::array()).empty());
}
