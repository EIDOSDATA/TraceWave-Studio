/** @file @brief 검사 결과의 수치/근거와 선택 위치를 서비스가 반환한 단위로 표시한다. */
#include "studio_internal.h"
#include "design_rules_dialog.h"
#include <array>

namespace
{
/** @brief 미정과 실제 영을 구분하여 표시한다. */
std::string Number(const Json& value)
{
    return value.is_null() ? "미정" : value.dump();
}

std::string RuleLabel(const Json& issue)
{
    return issue.at("details").value("label", issue.at("rule").get<std::string>());
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
                for (const auto& issue : result.at("issues"))
                {
                    const auto row = m_issues->InsertItem(m_issues->GetItemCount(),
                                                        Display(issue.at("status") == "failed" ? "위반" : "미평가"));
                    m_issues->SetItem(row, 1, Display(RuleLabel(issue)));
                    m_issues->SetItem(row, 2, Display(Number(issue.at("measured")) + " / " + Number(issue.at("limit")) +
                                                     " " + issue.at("unit").get<std::string>()));
                }
                const auto& counts = result.at("counts");
                SetStatus("만족 " + counts.at("passed").dump() + " / 위반 " + counts.at("failed").dump() +
                          " / 미평가 " + counts.at("not_evaluated").dump() + " / 적용 안 함 " +
                          counts.at("not_applicable").dump() + (result.at("issues_truncated") == true ? " / 일부 결과 표시" : "") +
                          " / 연결 성분 " + std::to_string(result.at("connectivity").at("components").size()));
                if (m_issues->GetItemCount() > 0)
                {
                    m_issues->SetItemState(0, wxLIST_STATE_SELECTED, wxLIST_STATE_SELECTED);
                    ShowIssue(0);
                }
            });
}

void DesignRulesDialog::ClearReport()
{
    m_report = nullptr;
    m_issues->DeleteAllItems();
    m_detail->ChangeValue(wxEmptyString);
    m_canvas->SetInspection({}, std::nullopt);
}

void DesignRulesDialog::ShowIssue(long index)
{
    if (m_report.is_null() || index < 0 || static_cast<std::size_t>(index) >= m_report.at("issues").size())
    {
        return;
    }
    const auto& issue = m_report.at("issues").at(index);
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
    for (const auto& id : ids)
    {
        detail += "\n객체 " + id;
    }
    for (const auto& source : issue.at("source_refs"))
    {
        detail += "\n출처 " + source.get<std::string>();
    }
    m_detail->ChangeValue(Display(detail));
}
