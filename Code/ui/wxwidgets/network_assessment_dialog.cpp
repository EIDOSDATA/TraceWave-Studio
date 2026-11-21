/** @file @brief 목표 평가의 조건 선택, 후보 검토와 과거 표본 조회를 연결한다. */
#include "network_assessment_dialog.h"
#include "frequency_display.h"
#include "studio_notebook.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/wx.h>
#include <wx/listctrl.h>
#include <wx/scrolwin.h>
#include <array>
#include <stdexcept>

namespace
{
std::string TextValue(const Json& value)
{
    return value.is_null() ? "미정" : value.is_string() ? value.get<std::string>() : value.dump();
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

/** @brief 입력 라벨과 제어의 native 초점/접근성 정보를 유지한다. */
void AddField(wxWindow* parent, wxSizer* layout, const std::string& label, wxWindow* control)
{
    layout->Add(new wxStaticText(parent, wxID_ANY, Display(label)), 0, wxBOTTOM, parent->FromDIP(4));
    layout->Add(control, 0, wxEXPAND | wxBOTTOM, parent->FromDIP(12));
    control->SetToolTip(Display(label));
}
}

NetworkAssessmentDialog::NetworkAssessmentDialog(wxWindow* parent, const Json& context, const Json& selection,
                                                 DialogGateway gateway)
    : ProjectSetupDialog(parent, "목표 평가", context, std::move(gateway)), m_context(context), m_selection(selection)
{
    SetName("network.assessment.dialog");
    BuildInterface();
    m_loading = true;
    int selected = wxNOT_FOUND;
    for (const auto& row : context.at("datasets"))
    {
        const int index = m_datasets->Append(Display(row.at("name").get<std::string>()));
        if (!selection.is_null() && row.at("id") == selection.at("entry").at("id"))
        {
            selected = index;
        }
    }
    m_datasets->SetSelection(selected);
    for (const auto& row : context.at("targets"))
    {
        m_targets->Append(Display(row.at("name").get<std::string>()));
    }
    if (!m_targets->IsEmpty())
    {
        m_targets->SetSelection(0);
    }
    m_history->Append(Display("새 평가 후보"));
    for (const auto& row : context.at("assessments"))
    {
        m_history->Append(Display(row.at("name").get<std::string>() + " / " + Status(row.at("status"))));
    }
    m_history->SetSelection(0);
    ShowTargetPlane();
    m_loading = false;
    RenderSelection();
    SetStatus("목표 개정과 자료의 포트, 기준면, Z0를 확인하세요. 결과 저장은 새 평가 기록을 만듭니다.");
    UpdateActions();
}

void NetworkAssessmentDialog::BuildInterface()
{
    StudioTheme::ApplyTypography(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* title = new wxStaticText(this, wxID_ANY, Display("목표 평가"));
    StudioTheme::Title(*title);
    layout->Add(title, 0, wxALL, FromDIP(16));
    auto* notice = new wxStaticText(
        this, wxID_ANY,
        Display("정확한 요구 표본의 판정입니다. 표본 사이, 수렴과 실물 정확도는 별도 검증이 필요합니다."));
    StudioTheme::BindSecondary(*notice);
    layout->Add(notice, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(16));
    m_tabs = new StudioNotebook(this);
    auto* settings = new wxScrolledWindow(m_tabs, wxID_ANY);
    settings->SetScrollRate(FromDIP(16), FromDIP(16));
    auto* settingsLayout = new wxBoxSizer(wxHORIZONTAL);
    auto* inputs = new wxBoxSizer(wxVERTICAL);
    m_datasets = new wxChoice(settings, wxID_ANY);
    m_datasets->SetName("network.assessment.dataset");
    AddField(settings, inputs, "평가할 복소 자료", m_datasets);
    m_targets = new wxChoice(settings, wxID_ANY);
    m_targets->SetName("network.assessment.target");
    AddField(settings, inputs, "현재 개정의 목표", m_targets);
    m_ports = new wxChoice(settings, wxID_ANY);
    m_ports->SetName("network.assessment.port");
    AddField(settings, inputs, "목표 포트에 대응할 자료 포트", m_ports);
    m_plane = new wxTextCtrl(settings, wxID_ANY);
    m_plane->SetName("network.assessment.reference_plane");
    m_plane->SetHint(Display("빈칸은 미정 / 평가 기준면을 명시하세요"));
    AddField(settings, inputs, "평가 기준면", m_plane);
    m_name = new wxTextCtrl(settings, wxID_ANY, Display("목표 평가 01"));
    m_name->SetName("network.assessment.name");
    AddField(settings, inputs, "새 평가 기록 이름", m_name);
    settingsLayout->Add(inputs, 2, wxEXPAND | wxALL, FromDIP(16));
    auto* details = new wxBoxSizer(wxVERTICAL);
    auto* heading = new wxStaticText(settings, wxID_ANY, Display("결과 조건과 판정 범위"));
    StudioTheme::Heading(*heading);
    details->Add(heading, 0, wxBOTTOM, FromDIP(12));
    m_conditions = new wxTextCtrl(settings, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(390, 320)),
                                  wxTE_MULTILINE | wxTE_READONLY);
    details->Add(m_conditions, 1, wxEXPAND);
    settingsLayout->Add(details, 3, wxEXPAND | wxTOP | wxRIGHT | wxBOTTOM, FromDIP(16));
    settings->SetSizer(settingsLayout);
    m_tabs->AddPage(settings, Display("평가 조건"), true);
    auto* results = new wxPanel(m_tabs);
    auto* resultLayout = new wxBoxSizer(wxVERTICAL);
    m_history = new wxChoice(results, wxID_ANY);
    m_history->SetName("network.assessment.history");
    AddField(results, resultLayout, "저장된 평가 / 검토 중 후보", m_history);
    m_criteria =
        new wxListCtrl(results, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 175)), wxLC_REPORT | wxLC_SINGLE_SEL);
    m_criteria->SetName("network.assessment.criteria");
    const std::array<std::pair<const char*, int>, 5> columns{
        {{"목표 지표", 160}, {"원문 한계", 145}, {"표본 범위", 140}, {"판정", 190}, {"이유", 380}}};
    for (std::size_t index = 0; index < columns.size(); ++index)
    {
        m_criteria->InsertColumn(static_cast<int>(index), Display(columns[index].first), wxLIST_FORMAT_LEFT,
                                 FromDIP(columns[index].second));
    }
    StudioTheme::Table(*m_criteria);
    resultLayout->Add(m_criteria, 1, wxEXPAND | wxBOTTOM, FromDIP(8));
    m_summary = new wxTextCtrl(results, wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(-1, 75)),
                               wxTE_MULTILINE | wxTE_READONLY);
    resultLayout->Add(m_summary, 0, wxEXPAND | wxBOTTOM, FromDIP(8));
    m_points =
        new wxListCtrl(results, wxID_ANY, wxDefaultPosition, FromDIP(wxSize(-1, 170)), wxLC_REPORT | wxLC_SINGLE_SEL);
    const std::array<std::pair<const char*, int>, 4> pointColumns{
        {{"주파수 (Hz)", 170}, {"표본 값", 160}, {"상태", 150}, {"이유", 560}}};
    for (std::size_t index = 0; index < pointColumns.size(); ++index)
    {
        m_points->InsertColumn(static_cast<int>(index), Display(pointColumns[index].first), wxLIST_FORMAT_LEFT,
                               FromDIP(pointColumns[index].second));
    }
    StudioTheme::Table(*m_points);
    resultLayout->Add(m_points, 1, wxEXPAND);
    auto* paging = new wxBoxSizer(wxHORIZONTAL);
    m_pageLabel = new wxStaticText(results, wxID_ANY, Display("선택한 지표의 정확한 표본을 표시합니다."));
    paging->Add(m_pageLabel, 1, wxALIGN_CENTER_VERTICAL);
    m_previous = new wxButton(results, wxID_ANY, Display("이전 표본"));
    m_next = new wxButton(results, wxID_ANY, Display("다음 표본"));
    for (auto* button : {m_previous, m_next})
    {
        StudioTheme::Button(*button);
        paging->Add(button, 0, wxLEFT, FromDIP(8));
    }
    resultLayout->Add(paging, 0, wxEXPAND | wxTOP, FromDIP(8));
    auto* resultOuter = new wxBoxSizer(wxVERTICAL);
    resultOuter->Add(resultLayout, 1, wxEXPAND | wxALL, FromDIP(16));
    results->SetSizer(resultOuter);
    m_tabs->AddPage(results, Display("판정 결과와 이력"));
    layout->Add(m_tabs, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(12));
    m_status = new wxStaticText(this, wxID_ANY, wxEmptyString);
    layout->Add(m_status, 0, wxEXPAND | wxALL, FromDIP(16));
    auto* actions = new wxBoxSizer(wxHORIZONTAL);
    auto* close = new wxButton(this, wxID_CANCEL, Display("닫기"));
    m_preview = new wxButton(this, wxID_ANY, Display("평가 검토"));
    m_apply = new wxButton(this, wxID_APPLY, Display("검토한 평가 저장"));
    m_preview->SetName("network.assessment.preview");
    m_apply->SetName("network.assessment.apply");
    actions->AddStretchSpacer();
    for (auto* button : {close, m_preview, m_apply})
    {
        StudioTheme::Button(*button, button == m_apply);
        actions->Add(button, 0, wxLEFT, FromDIP(8));
    }
    layout->Add(actions, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(16));
    SetSizer(layout);
    m_datasets->Bind(wxEVT_CHOICE,
                     [this](wxCommandEvent&)
                     {
                         LoadDataset();
                     });
    m_targets->Bind(wxEVT_CHOICE,
                    [this](wxCommandEvent&)
                    {
                        Changed();
                        ShowTargetPlane();
                        RenderSelection();
                    });
    m_ports->Bind(wxEVT_CHOICE,
                  [this](wxCommandEvent&)
                  {
                      Changed();
                  });
    for (auto* control : {m_plane, m_name})
    {
        control->Bind(wxEVT_TEXT,
                      [this](wxCommandEvent&)
                      {
                          Changed();
                      });
    }
    m_history->Bind(wxEVT_CHOICE,
                    [this](wxCommandEvent&)
                    {
                        LoadHistory();
                    });
    m_criteria->Bind(wxEVT_LIST_ITEM_SELECTED,
                     [this](wxListEvent& event)
                     {
                         if (!m_loading)
                         {
                             SelectCriterion(static_cast<int>(event.GetIndex()));
                         }
                     });
    m_previous->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         LoadPoints(std::max(0, m_offset - 201));
                     });
    m_next->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     if (!m_nextOffset.is_null())
                     {
                         LoadPoints(m_nextOffset.get<int>());
                     }
                 });
    m_preview->Bind(wxEVT_BUTTON,
                    [this](wxCommandEvent&)
                    {
                        Preview();
                    });
    m_apply->Bind(wxEVT_BUTTON,
                  [this](wxCommandEvent&)
                  {
                      Apply();
                  });
}

void NetworkAssessmentDialog::Changed()
{
    if (m_loading)
    {
        return;
    }
    InvalidateRead();
    m_dirty = true;
    m_review = nullptr;
    m_reviewInput = nullptr;
    m_assessment = nullptr;
    m_recordId.clear();
    m_criterion = -1;
    m_offset = 0;
    m_criteria->DeleteAllItems();
    m_points->DeleteAllItems();
    m_nextOffset = nullptr;
    m_pageLabel->SetLabel(Display("새 평가 조건을 검토하세요."));
    m_history->SetSelection(0);
    m_summary->ChangeValue(Display("평가 입력이 바뀌었습니다. 다시 검토하세요."));
    UpdateActions();
}

void NetworkAssessmentDialog::LoadDataset()
{
    Changed();
    m_selection = nullptr;
    RenderSelection();
    const int index = m_datasets->GetSelection();
    if (index < 0)
    {
        return;
    }
    const Json identity = m_context.at("datasets").at(index).at("id");
    Request("network.get",
            {{"expected_revision", m_revision},
             {"dataset_id", identity},
             {"offset", 0},
             {"limit", 201},
             {"row", 0},
             {"column", 0}},
            false,
            [this, identity](const Json& result)
            {
                if (result.at("entry").at("id") != identity)
                {
                    throw std::runtime_error("평가할 자료 선택과 응답이 다릅니다.");
                }
                m_selection = result;
                RenderSelection();
            });
}

/** @brief 저장한 기준면을 평가의 고정 입력으로 표시한다. */
void NetworkAssessmentDialog::ShowTargetPlane()
{
    const int selected = m_targets->GetSelection();
    const Json expected = selected < 0 ? Json(nullptr) : m_context.at("targets").at(selected).value("reference_plane", Json(nullptr));
    m_plane->ChangeValue(expected.is_null() ? wxString() : Display(expected.get<std::string>()));
    m_plane->SetEditable(expected.is_null());
}

void NetworkAssessmentDialog::RenderSelection()
{
    const bool loading = m_loading;
    m_loading = true;
    const int previous = m_ports->GetSelection();
    m_ports->Clear();
    std::string details = "주파수 정책: 정확한 표본만 사용\n보간/외삽/기준면 자동 이동 없음\n\n";
    if (!m_selection.is_null())
    {
        const auto& descriptor = m_selection.at("descriptor");
        for (std::size_t index = 0; index < descriptor.at("port_ids").size(); ++index)
        {
            const auto& name = descriptor.at("port_names").at(index);
            m_ports->Append(Display(name.is_null() ? "포트 " + std::to_string(index + 1) : name.get<std::string>()));
        }
        m_ports->SetSelection(previous >= 0 && previous < static_cast<int>(m_ports->GetCount()) ? previous : 0);
        details += "자료: " + m_selection.at("entry").at("name").get<std::string>() + "\n";
        details += "표본: " + TextValue(descriptor.at("sample_count")) + "개\n";
        details += "기준면: " + TextValue(descriptor.at("reference_planes")) + "\n";
        details += "Z0 (실수, 허수): " + TextValue(descriptor.at("z0_ohm")) + " ohm\n";
        details += "파 정의: " + descriptor.at("wave_definition").get<std::string>() + "\n\n";
    }
    else
    {
        details += "평가할 자료를 선택하세요.\n\n";
    }
    const int selected = m_targets->GetSelection();
    if (selected >= 0)
    {
        const auto& target = m_context.at("targets").at(selected);
        details += "목표: " + target.at("name").get<std::string>() + "\n";
        details += "목표에 저장한 기준면: " + TextValue(target.value("reference_plane", Json(nullptr))) + "\n";
        details += "목표 Z0: " + TextValue(target.at("reference_impedance").at("value_si")) + " ohm\n";
        details += "목표 포트: " + std::string(target.at("port_id").is_null() ? "미정" : "원본 목표 포트와 명시 대응") +
                   "\n\n";
    }
    details +=
        "표본 통과는 연속 대역이나 물리 정확도의 합격이 아닙니다.\n제작/측정 조건 미정은 원본에서 그대로 유지됩니다.";
    m_conditions->ChangeValue(Display(details));
    m_loading = loading;
    UpdateActions();
}

void NetworkAssessmentDialog::Preview()
{
    if (!Editable() || m_pending || m_selection.is_null() || m_targets->GetSelection() < 0 ||
        m_ports->GetSelection() < 0)
    {
        return;
    }
    const auto& target = m_context.at("targets").at(m_targets->GetSelection());
    const Json context{
        {"port_id", m_selection.at("descriptor").at("port_ids").at(m_ports->GetSelection())},
        {"target_port_id", target.at("port_id")},
        {"reference_plane", m_plane->GetValue().empty() ? Json(nullptr) : Json(Utf8(m_plane->GetValue()))},
        {"frequency_policy", "exact_only"}};
    const Json input{{"expected_revision", m_revision},
                     {"operation", "evaluate"},
                     {"parameters",
                      {{"name", Utf8(m_name->GetValue())},
                       {"dataset_id", m_selection.at("entry").at("id")},
                       {"target_id", target.at("id")},
                       {"context", context}}}};
    m_review = nullptr;
    m_reviewInput = nullptr;
    m_assessment = nullptr;
    m_criteria->DeleteAllItems();
    m_points->DeleteAllItems();
    m_summary->ChangeValue(Display("정확한 표본과 목표 조건을 검사하고 있습니다."));
    Request("network.preview", input, false,
            [this, input](const Json& result)
            {
                if (result.at("project_id") != m_projectId || result.at("revision_id") != m_revision ||
                    (result.value("can_apply", false) && result.at("operation") != "evaluate"))
                {
                    throw std::runtime_error("목표 평가 후보의 프로젝트, 개정 또는 작업이 다릅니다.");
                }
                m_review = result;
                m_reviewInput = input;
                m_recordId.clear();
                if (result.value("can_apply", false))
                {
                    m_history->SetSelection(0);
                    RenderAssessment(result.at("assessment"));
                    m_tabs->SetSelection(1);
                    SetStatus("평가 후보입니다. 저장하면 과거 결과와 목표를 덮어쓰지 않는 새 기록을 만듭니다.");
                }
                else
                {
                    std::string message = "평가 후보를 만들 수 없습니다.";
                    for (const auto& issue : result.at("issues"))
                    {
                        message += "\n" + issue.value("message", "입력 확인 필요");
                    }
                    SetStatus(message);
                }
            });
}

void NetworkAssessmentDialog::Apply()
{
    if (!Editable() || m_pending || m_review.is_null() || !m_review.value("can_apply", false))
    {
        return;
    }
    Json input = m_reviewInput;
    input["command_id"] = Uuid();
    input["review_hash"] = m_review.at("review_hash");
    Request("network.apply", input, true,
            [this](const Json& result)
            {
                if (result.at("operation") != "evaluate")
                {
                    throw std::runtime_error("목표 평가 적용 응답의 작업이 다릅니다.");
                }
                AcceptMutation(result);
                m_dirty = false;
                m_review = nullptr;
                m_reviewInput = nullptr;
                CloseDialog();
            });
}

void NetworkAssessmentDialog::LoadHistory()
{
    const int index = m_history->GetSelection();
    if (index <= 0)
    {
        m_recordId.clear();
        if (!m_review.is_null() && m_review.value("can_apply", false))
        {
            RenderAssessment(m_review.at("assessment"));
        }
        else
        {
            m_assessment = nullptr;
            m_criteria->DeleteAllItems();
            m_nextOffset = nullptr;
            RenderPoints(Json::array(), 0, 0);
            m_summary->ChangeValue(Display("새 평가 조건을 검토하면 후보를 표시합니다."));
        }
        UpdateActions();
        return;
    }
    const std::string id = m_context.at("assessments").at(index - 1).at("id");
    m_recordId.clear();
    m_assessment = nullptr;
    m_points->DeleteAllItems();
    m_criteria->DeleteAllItems();
    m_nextOffset = nullptr;
    Request("network.assessment", {{"expected_revision", m_revision}, {"assessment_id", id}}, false,
            [this, id](const Json& result)
            {
                if (result.at("entry").at("id") != id)
                {
                    throw std::runtime_error("선택한 평가 기록과 응답이 다릅니다.");
                }
                m_recordId = id;
                RenderAssessment(result.at("assessment"));
                SetStatus(
                    result.value("target_changed", false)
                        ? "저장된 평가입니다. 현재 목표가 변경되었거나 삭제되었습니다. 당시 목표의 판정을 유지합니다."
                        : "저장된 평가를 조회 중입니다. 이 기록은 당시 목표와 원본 자료의 조건을 보존합니다.");
            });
}

void NetworkAssessmentDialog::RenderAssessment(const Json& assessment)
{
    m_assessment = assessment;
    m_loading = true;
    m_criteria->DeleteAllItems();
    for (const auto& criterion : assessment.at("criteria"))
    {
        const long row = m_criteria->InsertItem(m_criteria->GetItemCount(), Display(Metric(criterion.at("metric"))));
        const auto& limit = criterion.at("limit");
        m_criteria->SetItem(row, 1,
                            Display((criterion.at("operator") == "le" ? "<= " : ">= ") + TextValue(limit.at("value")) +
                                    " " + limit.at("unit").get<std::string>()));
        m_criteria->SetItem(row, 2,
                            Display(TextValue(criterion.at("coverage").at("available")) + " / " +
                                    TextValue(criterion.at("coverage").at("required"))));
        m_criteria->SetItem(row, 3, Display(Status(criterion.at("status"))));
        m_criteria->SetItem(row, 4, Display(criterion.value("reason", "")));
    }
    m_summary->ChangeValue(
        Display("평가: " + Status(assessment.at("status")) +
                "\n연속 대역 검증: 미확립 / 실물 물리 검증: 미확립\n"
                "전체 표본을 확인하려면 저장된 평가의 지표를 선택하고 이전/다음 표본으로 조회하세요."));
    m_loading = false;
    m_criterion = assessment.at("criteria").empty() ? -1 : 0;
    if (m_criterion >= 0)
    {
        m_loading = true;
        m_criteria->SetItemState(0, wxLIST_STATE_SELECTED, wxLIST_STATE_SELECTED);
        m_loading = false;
        SelectCriterion(0);
    }
    else
    {
        RenderPoints(Json::array(), 0, 0);
    }
    UpdateActions();
}

void NetworkAssessmentDialog::SelectCriterion(int index)
{
    if (m_assessment.is_null() || index < 0 || index >= static_cast<int>(m_assessment.at("criteria").size()))
    {
        return;
    }
    m_criterion = index;
    const auto& row = m_assessment.at("criteria").at(index);
    m_summary->ChangeValue(Display(Metric(row.at("metric")) + ": " + Status(row.at("status")) + "\n" +
                                   row.value("reason", "") + "\n연속 대역과 실물 정확도: 미확립"));
    m_nextOffset = nullptr;
    RenderPoints(row.value("points_preview", Json::array()), 0, row.value("point_count", 0));
    if (!m_recordId.empty() && row.value("point_count", 0) > 0)
    {
        LoadPoints(0);
    }
    if (row.contains("sampled_estimate") && !row.at("sampled_estimate").is_null())
    {
        m_summary->ChangeValue(Display("FBW 통과 표본 폭 추정: " + TextValue(row.at("sampled_estimate").at("value")) +
                                       "\n임계 교차점과 표본 사이를 검증하지 않아 최종 판정은 미평가입니다."));
    }
}

void NetworkAssessmentDialog::LoadPoints(int offset)
{
    if (m_recordId.empty() || m_criterion < 0 || m_assessment.is_null() || !Editable() || m_pending)
    {
        return;
    }
    const std::string record = m_recordId;
    const int criterion = m_criterion;
    Request("network.assessment.points",
            {{"expected_revision", m_revision},
             {"assessment_id", record},
             {"criterion", criterion},
             {"offset", offset},
             {"limit", 201}},
            false,
            [this, record, criterion](const Json& result)
            {
                if (m_recordId != record || m_criterion != criterion)
                {
                    return;
                }
                m_nextOffset = result.at("next_offset");
                RenderPoints(result.at("points"), result.at("offset"), result.at("total"));
            });
}

void NetworkAssessmentDialog::RenderPoints(const Json& points, int offset, int total)
{
    m_offset = offset;
    m_points->DeleteAllItems();
    const bool matchingDataset = StudioFrequency::AssessmentMatchesDataset(m_assessment, m_selection);
    const auto frequencyScale =
        StudioFrequency::ForAssessment(m_assessment, matchingDataset ? m_selection.at("descriptor") : Json(nullptr));
    wxListItem column;
    column.SetText(Display("주파수 (" + frequencyScale.unit + ")"));
    m_points->SetColumn(0, column);
    for (const auto& point : points)
    {
        const long row = m_points->InsertItem(
            m_points->GetItemCount(), Display(StudioFrequency::Value(point.at("frequency_hz"), frequencyScale)));
        m_points->SetItem(row, 1,
                          Display(point.value("value_state", "") == "negative_infinity"
                                      ? "-inf (완전 정합)"
                                      : TextValue(point.at("value"))));
        m_points->SetItem(row, 2, Display(Status(point.at("status"))));
        m_points->SetItem(row, 3, Display(point.at("reason").is_null() ? "" : point.at("reason").get<std::string>()));
    }
    m_pageLabel->SetLabel(Display((m_recordId.empty() ? "후보 미리보기 " : "저장된 평가 ") + std::to_string(offset) +
                                  "부터 " + std::to_string(points.size()) + " / " + std::to_string(total) + "개 표본"));
    UpdateActions();
}

bool NetworkAssessmentDialog::HasDraft() const
{
    return m_dirty || (!m_review.is_null() && m_review.value("can_apply", false));
}

void NetworkAssessmentDialog::UpdateActions()
{
    if (!m_apply)
    {
        return;
    }
    const bool enabled = Editable() && !m_pending;
    for (auto* control : std::vector<wxWindow*>{m_datasets, m_targets, m_ports, m_plane, m_name, m_history, m_criteria})
    {
        control->Enable(enabled);
    }
    m_preview->Enable(enabled && !m_selection.is_null() && m_targets->GetSelection() >= 0 &&
                      m_ports->GetSelection() >= 0);
    m_apply->Enable(enabled && !m_review.is_null() && m_review.value("can_apply", false) &&
                    m_history->GetSelection() == 0);
    m_previous->Enable(enabled && !m_recordId.empty() && m_offset > 0);
    m_next->Enable(enabled && !m_recordId.empty() && !m_nextOffset.is_null());
}

void NetworkAssessmentDialog::ShowRequestFailure(const Json& error)
{
    m_review = nullptr;
    m_reviewInput = nullptr;
    ProjectSetupDialog::ShowRequestFailure(error);
}
