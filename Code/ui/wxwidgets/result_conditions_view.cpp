/** @file @brief 원본, 기준과 검증 상태를 시안의 접기 그룹으로 나누는 결과 속성 View다. */
#include "result_conditions_view.h"
#include "measurement_model.h"
#include "result_presentation.h"
#include "frequency_display.h"
#include "studio_support.h"
#include "studio_theme.h"
#include <wx/button.h>
#include <wx/clipbrd.h>
#include <wx/collpane.h>
#include <wx/dataobj.h>
#include <wx/scrolwin.h>
#include <wx/sizer.h>
#include <wx/stattext.h>
#include <wx/textctrl.h>
#include <algorithm>

namespace
{
/** @brief 확인된 조건 원문의 존재와 제작/측정 검증 완료를 구분한다. */
std::string RecordedCondition(const Json& conditions, const std::string& key)
{
    return !conditions.is_object() || !conditions.contains(key) || conditions.at(key).is_null()
               ? "미정"
               : "원문 기록 있음 (확정 여부는 출처 확인)";
}

/** @brief 조건 차이의 단위와 미정 사유를 삭제하지 않고 읽을 수 있는 문장으로 만든다. */
std::string DifferenceText(const Json& difference)
{
    std::string text = ResultUi::Text(difference.value("label", Json("조건"))) +
                       "\nA: " + ResultUi::Text(difference.value("left_display", Json(nullptr))) +
                       "\nB: " + ResultUi::Text(difference.value("right_display", Json(nullptr)));
    const auto unit = difference.value("unit", Json(nullptr));
    if (unit.is_string() && !unit.get<std::string>().empty())
    {
        text += "\n단위: " + unit.get<std::string>();
    }
    const auto reason = difference.value("reason", Json(nullptr));
    if (reason.is_string())
    {
        text += "\n" + reason.get<std::string>();
    }
    return text + "\n\n";
}
}

ResultConditionsView::ResultConditionsView(wxWindow* parent) : wxPanel(parent)
{
    SetName("result.conditions");
    StudioTheme::ApplyTypography(*this);
    StudioTheme::BindSurface(*this);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* title = new wxBoxSizer(wxHORIZONTAL);
    m_heading =
        new wxStaticText(this, wxID_ANY, Display("결과 조건"), wxDefaultPosition, wxDefaultSize, wxST_ELLIPSIZE_END);
    m_heading->SetMinSize(FromDIP(wxSize(80, -1)));
    StudioTheme::Heading(*m_heading);
    title->Add(m_heading, 1, wxALIGN_CENTER_VERTICAL | wxRIGHT, FromDIP(8));
    m_copy = new wxButton(this, wxID_ANY, Display("조건 복사"));
    m_copy->SetName("result.conditions.copy");
    m_copy->SetToolTip(Display("현재 표시된 조건 문장을 복사합니다. 비교는 표시 중인 조건 페이지만 포함합니다."));
    StudioTheme::Button(*m_copy);
    title->Add(m_copy, 0, wxALIGN_CENTER_VERTICAL);
    layout->Add(title, 0, wxEXPAND | wxALL, FromDIP(8));
    m_validationButton = new wxButton(this, wxID_ANY, Display("프로젝트 검증 기록"));
    m_validationButton->SetToolTip(
        Display("프로젝트에 보존된 별도 검증 보고서를 조회합니다. 현재 결과의 판정으로 자동 연결하지 않습니다."));
    StudioTheme::Button(*m_validationButton);
    m_validationButton->Disable();
    layout->Add(m_validationButton, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    m_validationButton->Bind(wxEVT_BUTTON,
                             [this](wxCommandEvent&)
                             {
                                 if (onValidation)
                                 {
                                     onValidation();
                                 }
                             });
    m_solverEvidence = new wxButton(this, wxID_ANY, Display("해석 입력과 출처"));
    m_solverEvidence->SetName("result.conditions.solver.evidence");
    StudioTheme::Button(*m_solverEvidence);
    m_solverEvidence->Hide();
    layout->Add(m_solverEvidence, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    m_solverEvidence->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        if (onSolverEvidence && !m_solverArtifact.empty())
        {
            onSolverEvidence(m_solverArtifact);
        }
    });
    m_pager = new wxPanel(this);
    auto* pagerLayout = new wxBoxSizer(wxVERTICAL);
    m_pageLabel = new wxStaticText(m_pager, wxID_ANY, wxEmptyString);
    pagerLayout->Add(m_pageLabel, 0, wxEXPAND | wxBOTTOM, FromDIP(4));
    auto* buttons = new wxBoxSizer(wxHORIZONTAL);
    m_previous = new wxButton(m_pager, wxID_ANY, Display("이전 조건"));
    m_next = new wxButton(m_pager, wxID_ANY, Display("다음 조건"));
    StudioTheme::Button(*m_previous);
    StudioTheme::Button(*m_next);
    buttons->Add(m_previous, 1, wxRIGHT, FromDIP(4));
    buttons->Add(m_next, 1);
    pagerLayout->Add(buttons, 0, wxEXPAND);
    m_pager->SetSizer(pagerLayout);
    layout->Add(m_pager, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    m_previous->Bind(wxEVT_BUTTON,
                     [this](wxCommandEvent&)
                     {
                         if (!m_conditionsPending && m_conditionPage.is_object() && onConditionPage)
                         {
                             onConditionPage(std::max(0, m_conditionPage.value("offset", 0) - 32));
                         }
                     });
    m_next->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     if (!m_conditionsPending && m_conditionPage.is_object() &&
                         m_conditionPage.value("next_offset", Json(nullptr)).is_number_integer() && onConditionPage)
                     {
                         onConditionPage(m_conditionPage.at("next_offset").get<int>());
                     }
                 });
    m_scroll = new wxScrolledWindow(this, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxVSCROLL);
    m_scroll->SetName("result.conditions.groups");
    StudioTheme::BindSurface(*m_scroll);
    m_scroll->SetScrollRate(0, FromDIP(12));
    m_scroll->SetSizer(new wxBoxSizer(wxVERTICAL));
    layout->Add(m_scroll, 1, wxEXPAND);
    m_originalGroup = AddGroup("원본", "original", m_summary);
    m_basisGroup = AddGroup("기준", "basis", m_basis);
    m_validationGroup = AddGroup("검증 상태", "validation", m_validation);
    m_advanced = AddGroup("고급: 보존된 조건 원문", "raw", m_source, true);
    SetSizer(layout);
    m_copy->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     if (wxTheClipboard->Open())
                     {
                         wxTheClipboard->SetData(new wxTextDataObject(Display(m_copyText)));
                         wxTheClipboard->Close();
                     }
                 });
    Clear("실제 결과를 선택하면 원본 조건을 표시합니다.");
}

wxCollapsiblePane* ResultConditionsView::AddGroup(const std::string& label, const std::string& name, wxTextCtrl*& text,
                                                  bool collapsed)
{
    auto* group =
        new wxCollapsiblePane(m_scroll, wxID_ANY, Display(label), wxDefaultPosition, wxDefaultSize, wxCP_NO_TLW_RESIZE);
    group->SetName(Display("result.conditions.group." + name));
    StudioTheme::BindSurface(*group->GetPane());
    auto* body = new wxBoxSizer(wxVERTICAL);
    text = new wxTextCtrl(group->GetPane(), wxID_ANY, wxEmptyString, wxDefaultPosition, FromDIP(wxSize(100, 60)),
                          wxTE_MULTILINE | wxTE_READONLY | wxTE_WORDWRAP | wxBORDER_NONE);
    text->SetName(Display("result.conditions." + name));
    StudioTheme::BindSurface(*text);
    body->Add(text, 0, wxEXPAND | wxALL, FromDIP(8));
    group->GetPane()->SetSizer(body);
    group->Collapse(collapsed);
    group->Bind(wxEVT_COLLAPSIBLEPANE_CHANGED,
                [this](wxCollapsiblePaneEvent&)
                {
                    Relayout();
                });
    m_scroll->GetSizer()->Add(group, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(8));
    return group;
}

void ResultConditionsView::Relayout()
{
    for (auto* group : {m_originalGroup, m_basisGroup, m_validationGroup, m_advanced})
    {
        group->GetPane()->Layout();
        group->InvalidateBestSize();
    }
    Layout();
    m_scroll->Layout();
    m_scroll->FitInside();
}

void ResultConditionsView::SetText(wxTextCtrl* control, const std::string& value, int maximumHeight)
{
    control->ChangeValue(Display(value));
    // @brief 큰 조건도 버리지 않고 native 본문 스크롤과 전체 조건 복사로 접근한다.
    const auto lines = static_cast<int>(std::count(value.begin(), value.end(), '\n') + 2);
    const int height = std::clamp(lines * control->GetCharHeight() + FromDIP(12), FromDIP(52), FromDIP(maximumHeight));
    control->SetMinSize(wxSize(FromDIP(100), height));
    control->ShowPosition(0);
}

void ResultConditionsView::SetValidationAvailable(bool available)
{
    m_validationButton->Enable(available);
}
void ResultConditionsView::SetDescription(const Json& description)
{
    m_solverArtifact = description.value("solver_evidence_artifact_id", "");
    m_solverEvidence->Show(!m_solverArtifact.empty());
    ++m_conditionGeneration;
    m_conditionsPending = false;
    m_comparison = nullptr;
    m_conditionPage = nullptr;
    m_pager->Hide();
    m_heading->SetLabel(Display("결과 조건과 보존 원본"));
    m_heading->SetToolTip(m_heading->GetLabel());
    m_originalGroup->SetLabel(Display("원본"));
    m_basisGroup->SetLabel(Display("기준"));
    m_validationGroup->SetLabel(Display("검증 상태"));
    const auto descriptor = description.value("descriptor", Json::object());
    const auto revision = description.value("source_revision", Json::object());
    const auto states = description.value("states", Json::object());
    const auto references = description.value("source_refs", Json::array());
    SetText(m_summary,
            ResultUi::SourceKind(description.value("source", Json::object()).value("kind", Json(nullptr))) + "\n" +
                ResultUi::Text(description.value("label", Json(nullptr))) +
                (description.value("is_current_design", false) ? "\n\n현재 설계 개정\n" : "\n\n보존된 이전 개정\n") +
                ResultUi::Text(revision.value("label", revision.value("name", Json(nullptr)))) +
                "\n\n보존 출처 " + std::to_string(references.is_array() ? references.size() : 0) + "개",
            164);
    std::string basis = "주파수\n" +
                        StudioFrequency::Range(descriptor.value("frequency_min_hz", Json(nullptr)),
                                               descriptor.value("frequency_max_hz", Json(nullptr))) +
                        "\n\n파 정의: " + ResultUi::State(descriptor.value("wave_definition", Json(nullptr))) +
                        "\n시간 규약: " + ResultUi::Text(descriptor.value("phasor_convention", Json(nullptr)));
    const auto ports = descriptor.value("port_ids", Json::array());
    for (std::size_t index = 0; index < ports.size(); ++index)
    {
        const auto item = [&descriptor, index](const std::string& key)
        {
            const auto values = descriptor.value(key, Json(nullptr));
            return values.is_array() && index < values.size() ? values.at(index) : Json(nullptr);
        };
        basis += "\n\n" + ResultUi::PortName(descriptor, index) + ", Z0 " + ResultUi::Complex(item("z0_ohm")) +
                 " ohm\n기준면: " + ResultUi::Text(item("reference_planes")) + "\n" +
                 ResultUi::State(item("port_modes")) + ", " + ResultUi::State(item("current_orientation"));
    }
    if (descriptor.value("z0_frequency_dependent", false))
    {
        basis += "\nZ0는 주파수별입니다. 위 값은 첫 표본입니다.";
    }
    if (description.value("measurement_record", Json(nullptr)).is_object())
    {
        m_basisGroup->SetLabel(Display("시료, 교정 및 기준"));
        basis = MeasurementUi::Summary(description.at("measurement_record")) + "\n" + basis;
    }
    SetText(m_basis, basis, 206);
    const auto conditions = descriptor.value("conditions", Json(nullptr));
    std::string validation =
        "계산: " + ResultUi::State(states.value("computation", Json(nullptr))) +
        "\n독립 수치 수렴: " + ResultUi::State(states.value("numerical", Json("not_established"))) +
        "\n물리 검증: " + ResultUi::State(states.value("physics", Json("not_established"))) +
        "\n\n제작 조건: " + RecordedCondition(conditions, "manufacturing") +
        "\n측정 조건: " + RecordedCondition(conditions, "measurement");
    const auto numerical = description.value("numerical_details", Json(nullptr));
    const auto reference = description.value("reference_scope", Json(nullptr));
    if (reference.is_object() && reference.value("kind", "") == "explicit_synthetic_reference" &&
        reference.value("case", "") == "pec-dipole-nf2ff")
    {
        validation += "\n\n별도의 합성 참조 사례\n모델: " +
                      ResultUi::Text(reference.value("native_model", Json(nullptr))) +
                      "\n이상적인 얇은 반파장 해석식과 유한 반경 모델의 차이를 포함합니다."
                      "\n독립 판정은 프로젝트 검증 기록에서 명시 보고서를 선택해 확인하세요."
                      "\n제작과 실측 검증은 미확립 상태입니다.";
    }
    if (numerical.is_object())
    {
        validation += "\n\n계산 종료 기록\n" + ResultUi::State(numerical.value("status", Json("not_recorded")));
        if (numerical.value("reason", Json(nullptr)).is_string())
        {
            validation += "\n" + numerical.at("reason").get<std::string>();
        }
        validation += "\n독립 수렴: " + ResultUi::State(numerical.value("formal_convergence", Json("not_established")));
    }
    const auto assessments = description.value("historical_assessments", Json::array());
    if (assessments.is_array() && !assessments.empty())
    {
        validation += "\n\n당시 목표 평가 (현재 재평가 아님)";
        for (const auto& assessment : assessments)
        {
            Json name = assessment.value("name", Json(nullptr));
            const auto evidence = assessment.value("evidence", Json(nullptr));
            if (!name.is_string() && evidence.is_object())
            {
                const auto original =
                    evidence.value("target_original", evidence.value("target_original_summary", Json(nullptr)));
                if (original.is_object())
                {
                    name = original.value("name", Json(nullptr));
                }
            }
            validation += "\n" + (name.is_string() ? name.get<std::string>() : "보존 목표 평가") + ": " +
                          ResultUi::State(assessment.value("status", Json("not_evaluated")));
        }
    }
    SetText(m_validation, validation, 206);
    SetText(m_source, description.dump(2, ' ', false, Json::error_handler_t::replace), 220);
    m_copyText = "원본\n" + m_summary->GetValue().ToStdString(wxConvUTF8) + "\n\n기준\n" + basis + "\n\n검증 상태\n" +
                 validation;
    m_copy->Enable(true);
    Relayout();
}

void ResultConditionsView::SetComparison(const Json& response, const std::string& leftName,
                                         const std::string& rightName)
{
    m_solverEvidence->Hide();
    ++m_conditionGeneration;
    m_comparison = response;
    m_leftName = leftName;
    m_rightName = rightName;
    m_conditionPage = {{"left", response.at("left")},
                       {"right", response.at("right")},
                       {"items", response.at("condition_differences")},
                       {"offset", 0},
                       {"total", response.at("condition_count")},
                       {"next_offset", response.at("condition_next_offset")}};
    m_conditionsPending = false;
    PresentComparison();
}

void ResultConditionsView::SetConditionPage(const Json& response)
{
    if (!m_comparison.is_object() || response.at("left") != m_comparison.at("left") ||
        response.at("right") != m_comparison.at("right"))
    {
        throw std::runtime_error("조건 페이지의 두 원본이 현재 비교와 다릅니다.");
    }
    ++m_conditionGeneration;
    m_conditionPage = response;
    m_conditionsPending = false;
    PresentComparison();
}

void ResultConditionsView::ConditionsPending(bool pending)
{
    m_conditionsPending = pending;
    PageActions();
}

void ResultConditionsView::PageActions()
{
    const bool present = m_conditionPage.is_object();
    m_pager->Show(present);
    m_previous->Enable(present && !m_conditionsPending && m_conditionPage.value("offset", 0) > 0);
    m_next->Enable(present && !m_conditionsPending && !m_conditionPage.value("next_offset", Json(nullptr)).is_null());
    if (present)
    {
        const int offset = m_conditionPage.value("offset", 0);
        const auto count = m_conditionPage.at("items").size();
        m_pageLabel->SetLabel(Display("조건 " + std::to_string(offset + (count ? 1 : 0)) + "~" +
                                      std::to_string(offset + count) + " (전체 " + std::to_string(ConditionTotal()) + "건)" +
                                      (m_conditionsPending ? " (조회 중)" : "")));
    }
}

void ResultConditionsView::PresentComparison()
{
    const auto& response = m_comparison;
    m_heading->SetLabel(Display("비교 조건"));
    m_heading->SetToolTip(m_heading->GetLabel());
    m_originalGroup->SetLabel(Display("비교 원본"));
    m_basisGroup->SetLabel(Display("수학 비교 기준"));
    m_validationGroup->SetLabel(Display("물리 조건과 검증 상태"));
    std::string original = "기준 A: " + (m_leftName.empty() ? "기준 원본" : m_leftName) +
                           "\n비교 B: " + (m_rightName.empty() ? "비교 원본" : m_rightName) +
                           "\n차이 = B - A\n같은 실제 주파수만 비교합니다.\n\n";
    std::string basis =
        "수학 비교\n" +
        ResultUi::State(response.value("math_comparability", Json::object()).value("status", Json("not_comparable"))) +
        "\n\n";
    std::string validation =
        "물리 비교\n" +
        ResultUi::State(
            response.value("physical_comparability", Json::object()).value("status", Json("not_established"))) +
        "\n과거 목표 판정과 실측 검증은 별도입니다. 두 미정 조건을 같은 조건으로 판정하지 않습니다.\n\n";
    for (const auto& difference : m_conditionPage.at("items"))
    {
        const auto field = difference.value("field", std::string());
        auto& text = difference.value("affects_math", false) ? basis
                     : field == "source_revision" || field == "selection_values" || field.rfind("design.", 0) == 0
                         ? original
                         : validation;
        text += DifferenceText(difference);
    }
    SetText(m_summary, original, 164);
    SetText(m_basis, basis, 206);
    SetText(m_validation, validation, 206);
    const Json details{{"comparison", response}, {"displayed_condition_page", m_conditionPage}};
    SetText(m_source, details.dump(2, ' ', false, Json::error_handler_t::replace), 220);
    m_copyText = "비교 원본\n" + original + "\n수학 비교 기준\n" + basis + "\n물리 조건과 검증 상태\n" + validation;
    m_copy->Enable(true);
    PageActions();
    m_copyText = m_pageLabel->GetLabel().ToStdString(wxConvUTF8) + "\n\n" + m_copyText;
    Relayout();
}

void ResultConditionsView::Clear(const std::string& message)
{
    m_solverArtifact.clear();
    m_solverEvidence->Hide();
    ++m_conditionGeneration;
    m_conditionsPending = false;
    m_comparison = nullptr;
    m_conditionPage = nullptr;
    m_pager->Hide();
    m_heading->SetLabel(Display("결과 조건"));
    m_heading->SetToolTip(m_heading->GetLabel());
    m_originalGroup->SetLabel(Display("원본"));
    m_basisGroup->SetLabel(Display("기준"));
    m_validationGroup->SetLabel(Display("검증 상태"));
    SetText(m_summary, message, 164);
    SetText(m_basis, "원본 선택 후 기록된 기준을 표시합니다.", 206);
    SetText(m_validation, "제작과 측정 조건이 미정입니다.\n검증 완료를 뜻하지 않습니다.", 206);
    SetText(m_source, "", 220);
    m_copyText.clear();
    m_copy->Enable(false);
    Relayout();
}
