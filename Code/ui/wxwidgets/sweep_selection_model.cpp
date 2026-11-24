/** @file @brief 후보 표시와 새 사본 응답의 식별 검사를 수행한다. */
#include "sweep_selection_model.h"
#include "result_presentation.h"
#include <map>
#include <set>

namespace SweepSelectionUi
{
std::string Issues(const Json& issues)
{
    std::string text;
    if (!issues.is_array())
    {
        return "안내 기록 없음";
    }
    for (const auto& issue : issues)
    {
        if (issue.is_string())
        {
            text += issue.get<std::string>() + "\n";
        }
        else if (issue.is_object())
        {
            text += ResultUi::Text(
                        issue.value("message_ko", issue.value("message", issue.value("reason", Json(nullptr))))) +
                    "\n";
        }
    }
    return text.empty() ? "추가 안내 없음" : text;
}

std::string Conditions(const Json& review)
{
    std::string text = "선택한 후보\n" + ResultUi::Text(review.value("label", Json(nullptr))) + "\n";
    if (review.value("index", Json(nullptr)).is_number_integer())
    {
        text += "연구 후보 " + std::to_string(review.at("index").get<int>() + 1) + "\n";
    }
    if (review.value("calculated_ordinal", Json(nullptr)).is_number_integer())
    {
        text += "실제 계산 후보 " + std::to_string(review.at("calculated_ordinal").get<int>() + 1) + "\n";
    }
    text += "\n계산 원본\n";
    const auto source = review.value("source", Json(nullptr));
    text += source.is_null() ? "연결된 계산 결과 없음\n" : "검토한 계산 원본과 봉인 식별을 보존합니다.\n";
    text += "선택한 후보 순서와 계산을 재사용한 후보 순서는 같지 않을 수 있습니다.\n\n선택 원본의 당시 검증 상태\n";
    text += "새 작업 사본의 재계산, 수렴, 제작, 실측 상태는 따로 검증해야 합니다.\n";
    const std::map<std::string, std::string> labels{{"geometry", "명시 형상"},      {"computation", "계산"},
                                                    {"target", "목표 평가"},        {"numerical", "수치 수렴"},
                                                    {"convergence", "수렴"},        {"physics", "물리 정확도"},
                                                    {"manufacturing", "제작 조건"}, {"measurement", "측정 조건"}};
    const Json states = review.value("states", Json::object());
    for (const auto& item : labels)
    {
        if (states.is_object() && states.contains(item.first))
        {
            const Json value = states.at(item.first);
            text +=
                item.second + ": " + ResultUi::State(value.is_object() ? value.value("state", Json(nullptr)) : value);
            if (value.is_object() && value.value("reason", Json(nullptr)).is_string())
            {
                text += ". " + value.at("reason").get<std::string>();
            }
            text += "\n";
        }
    }
    const auto numerical = review.value("numerical_details", Json::object());
    if (numerical.is_object() && numerical.contains("status"))
    {
        text += "기록된 계산 종료: " + ResultUi::State(numerical.at("status")) + "\n";
        if (numerical.value("reason", Json(nullptr)).is_string())
        {
            text += numerical.at("reason").get<std::string>() + "\n";
        }
    }
    text +=
        "\n제작과 측정\n원문의 미정값을 보존합니다. 새 사본의 제작 조건과 실측 검증은 따로 확인하세요.\n";
    text += "\n당시 목표 평가\n";
    const auto assessments = review.value("historical_assessments", Json::array());
    if (!assessments.is_array() || assessments.empty())
    {
        text += "보존된 목표 평가가 없습니다. 목표 달성 여부는 미확인입니다.\n";
    }
    else
    {
        for (const auto& item : assessments)
        {
            const Json evidence = item.value("evidence", Json::object());
            const Json target =
                evidence.value("target_original", evidence.value("target_original_summary", Json::object()));
            text += ResultUi::Text(item.value("name", target.value("name", Json("보존 목표 평가")))) + ": " +
                    ResultUi::State(item.value("status", Json(nullptr))) + "\n";
            if (item.value("reason", Json(nullptr)).is_string())
            {
                text += item.at("reason").get<std::string>() + "\n";
            }
        }
    }
    return text;
}

std::string CopySummary(const Json& review)
{
    std::string text =
        "원본 프로젝트의 개정, 저장 위치와 실행 취소 이력은 바뀌지 않습니다.\n"
        "별도 프로젝트를 만든 뒤 '새 사본 열기'를 눌러 이동합니다.\n"
        "사본의 실행 취소는 사본 안의 기준 형상으로 돌아갑니다. 원본 연구와 계산 결과는 수정하지 않습니다.\n";
    const auto summary = review.value("copy_summary", Json(nullptr));
    if (summary.is_string())
    {
        text += "\n" + summary.get<std::string>();
    }
    else if (summary.is_object())
    {
        if (summary.value("source_revision_matches_current", Json(nullptr)) == false)
        {
            text += "\n주의: 연구의 당시 기준 개정에서 사본을 만듭니다. 현재 원본에 추가한 후속 편집은 사본에 포함하지 "
                    "않습니다.\n";
        }
        if (summary.value("artifact_count", Json(nullptr)).is_number_integer())
        {
            text += "\n함께 보존할 자료 참조: " + std::to_string(summary.at("artifact_count").get<int>()) + "개\n";
        }
        for (const auto* key : {"message", "description", "limitations"})
        {
            if (summary.value(key, Json(nullptr)).is_string())
            {
                text += "\n" + summary.at(key).get<std::string>();
            }
            else if (summary.value(key, Json(nullptr)).is_array())
            {
                text += "\n" + Issues(summary.at(key));
            }
        }
    }
    return text;
}

bool MatchesCopy(const Json& result, const Json& context)
{
    return context.is_object() && context.value("project_id", Json(nullptr)).is_string() &&
           context.value("revision_id", Json(nullptr)).is_string() &&
           context.value("study_id", Json(nullptr)).is_string() &&
           context.value("index", Json(nullptr)).is_number_integer() &&
           context.value("source_pin", Json(nullptr)).is_object() && result.is_object() &&
           result.value("source_project_id", Json(nullptr)) == context.value("project_id", Json(nullptr)) &&
           result.value("source_revision_id", Json(nullptr)) == context.value("revision_id", Json(nullptr)) &&
           result.value("study_id", Json(nullptr)) == context.value("study_id", Json(nullptr)) &&
           result.value("index", Json(nullptr)) == context.value("index", Json(nullptr)) &&
           result.value("source_pin", Json(nullptr)) == context.value("source_pin", Json(nullptr)) &&
           result.value("new_project_id", Json(nullptr)).is_string() &&
           !result.at("new_project_id").get<std::string>().empty() &&
           result.at("new_project_id") != context.value("project_id", Json(nullptr)) &&
           result.value("revision_id", Json(nullptr)).is_string() &&
           !result.at("revision_id").get<std::string>().empty() && result.value("path", Json(nullptr)).is_string() &&
           !result.at("path").get<std::string>().empty();
}

bool Rejected(const Json& error)
{
    const Json data = error.value("data", Json::object());
    const Json code = data.is_object() ? data.value("domain_code", error.value("code", Json(nullptr)))
                                       : error.value("code", Json(nullptr));
    static const std::set<std::string> definitive{"E_SCHEMA",      "E_CONFLICT",  "E_UNIT",    "E_RESOURCE",
                                                  "E_UNSUPPORTED", "E_NOT_FOUND", "E_VERSION", "E_LIMIT"};
    return code.is_string() && definitive.count(code.get<std::string>()) != 0;
}
}
