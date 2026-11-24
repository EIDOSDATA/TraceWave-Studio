/** @file @brief 검사 결과의 수치/근거와 선택 위치를 서비스가 반환한 단위로 표시한다. */
#include "studio_internal.h"
#include "design_rules_dialog.h"
#include "result_presentation.h"
#include <array>

namespace
{
/** @brief 미정과 실제 영을 구분하여 표시한다. */
std::string Number(const Json& value)
{
    return ResultUi::Number(value);
}

std::string RuleLabel(const Json& issue)
{
    const auto rule = issue.at("rule").get<std::string>();
    const auto found = issue.at("details").find("label");
    if (found != issue.at("details").end() && found->is_string())
    {
        return found->get<std::string>();
    }
    if (rule == "manufacturing_profile" || rule == "manufacturing_coverage")
    {
        return "제조 규칙";
    }
    if (rule == "board_containment" || rule == "geometry_coverage")
    {
        return "기판 범위와 형상";
    }
    return "설계 규칙";
}
}

void DesignRulesDialog::Check()
{
    const auto& selection = m_context.at("selection");
    const auto& section = selection.at("section");
    const auto& target = selection.at("target_id");
    const Json targets = target.is_null() ? Json(nullptr) : Json::array({target});
    const Json profile = section == "manufacturing_profile" ? selection.at("record_id") : Json(nullptr);
    constexpr std::array<const char*, 3> scopes = {"all", "em", "export"};
    ClearReport();
    Request("design.rules.check", {{"expected_revision", m_revision}, {"inclusion", scopes.at(m_inclusion->GetSelection())},
            {"target_ids", targets}, {"manufacturing_profile_id", profile}}, false,
            [this](const Json& result)
            {
                if (result.at("project_id") != m_projectId || result.at("revision_id") != m_revision)
                {
                    throw std::runtime_error("현재 개정과 다른 검사 결과입니다.");
                }
                m_report = result;
                m_filter->Enable();
                m_connections->Append(Display("연결 묶음 선택"));
                const auto& components = result.at("connectivity").at("components");
                for (std::size_t index = 0; index < components.size(); ++index)
                {
                    m_connections->Append(Display("묶음 " + std::to_string(index + 1) + ", 도체 " +
                                                  std::to_string(components.at(index).size()) + "개"));
                }
                m_connections->SetSelection(0);
                m_connections->Enable(!components.empty());
                RenderFindings();
                const auto& counts = result.at("counts");
                SetStatus("만족 " + counts.at("passed").dump() + ", 위반 " + counts.at("failed").dump() +
                          ", 미평가 " + counts.at("not_evaluated").dump() + ", 적용 안 함 " +
                          counts.at("not_applicable").dump() + (result.at("issues_truncated") == true ? ". 일부 결과가 표시됩니다." : "") +
                          ", 연결 성분 " + std::to_string(result.at("connectivity").at("components").size()));
            });
}

void DesignRulesDialog::RenderFindings()
{
    if (!m_report.is_object())
    {
        return;
    }
    static constexpr std::array<const char*, 5> states{"", "failed", "not_evaluated", "passed", "not_applicable"};
    static constexpr std::array<const char*, 5> labels{"", "위반", "미평가", "충족", "적용 안 함"};
    const int filter = m_filter->GetSelection();
    m_issues->DeleteAllItems();
    m_findings = Json::array();
    m_editRule->Disable();
    m_connections->SetSelection(0);
    m_canvas->SetInspection({}, std::nullopt);
    for (const auto& issue : m_report.at(filter >= 3 ? "checks" : "issues"))
    {
        if (filter > 0 && issue.at("status") != states[filter])
        {
            continue;
        }
        m_findings.push_back(issue);
        const auto status = filter > 0 ? labels[filter] : issue.at("status") == "failed" ? "위반" : "미평가";
        const auto row = m_issues->InsertItem(m_issues->GetItemCount(), Display(status));
        m_issues->SetItem(row, 1, Display(RuleLabel(issue)));
        m_issues->SetItem(row, 2, Display(Number(issue.at("measured")) + ", 한계 " + Number(issue.at("limit")) +
                                         " " + issue.at("unit").get<std::string>()));
    }
    m_detail->ChangeValue(Display(m_findings.empty() ? "선택한 판정의 표시 항목이 없습니다." : ""));
    if (!m_findings.empty())
    {
        m_issues->SetItemState(0, wxLIST_STATE_SELECTED, wxLIST_STATE_SELECTED);
        ShowIssue(0);
    }
}

void DesignRulesDialog::ClearReport()
{
    m_report = nullptr;
    m_findings = Json::array();
    m_filter->Disable();
    m_connections->Clear();
    m_connections->Disable();
    m_editRule->Disable();
    m_issues->DeleteAllItems();
    m_detail->ChangeValue(wxEmptyString);
    m_canvas->SetInspection({}, std::nullopt);
}

void DesignRulesDialog::ShowIssue(long index)
{
    if (m_report.is_null() || index < 0 || static_cast<std::size_t>(index) >= m_findings.size())
    {
        return;
    }
    const auto& issue = m_findings.at(index);
    m_connections->SetSelection(0);
    const bool manufacturing = issue.at("rule") == "manufacturing_profile" || issue.at("rule") == "manufacturing_coverage";
    m_editRule->Enable(manufacturing && Editable() && !m_pending);
    const auto ids = issue.at("object_ids").get<std::vector<std::string>>();
    std::optional<wxPoint2DDouble> location;
    const auto& point = issue.at("location_mm");
    if (!point.is_null())
    {
        location.emplace(point.at(0).get<double>(), point.at(1).get<double>());
    }
    m_canvas->SetInspection(ids, location);
    std::string detail = RuleLabel(issue) + "\n" + issue.at("message").get<std::string>();
    if (location)
    {
        detail += "\n위치 " + point.dump() + " mm";
    }
    if (!ids.empty())
    {
        detail += "\n도면에서 관련 도체 " + std::to_string(ids.size()) + "개를 강조합니다.";
    }
    if (manufacturing)
    {
        detail += "\n제조 규칙 설정에서 적용할 규칙을 확인한 뒤 다시 검사하세요.";
    }
    for (const auto& source : issue.at("source_refs"))
    {
        detail += "\n출처 " + source.get<std::string>();
    }
    m_detail->ChangeValue(Display(detail));
}
