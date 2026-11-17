/** @file @brief 내부 식별자를 기본 안내에서 빼고 출력 상태의 의미를 표시한다. */
#include "output_model.h"
#include <cmath>
#include <iomanip>
#include <map>
#include <sstream>

std::string OutputUi::Reader(const Json& value)
{
    if (value.is_string())
    {
        return value.get<std::string>();
    }
    if (!value.is_object())
    {
        return "미기록";
    }
    std::string result;
    for (const auto& item : value.value("formats", Json::array()))
    {
        const auto reader = Text(item.value("reader", Json(nullptr)), "미기록");
        if (result.find(reader) != std::string::npos)
        {
            continue;
        }
        if (!result.empty())
        {
            result += "\n";
        }
        result += reader;
    }
    return result.empty() ? "미기록" : result;
}

std::string OutputUi::Text(const Json& value, const std::string& missing)
{
    if (value.is_null())
    {
        return missing;
    }
    if (value.is_string())
    {
        return value.get<std::string>();
    }
    if (value.is_number())
    {
        const double number = value.get<double>();
        if (!std::isfinite(number))
        {
            return "유한값 없음";
        }
        std::ostringstream stream;
        stream << std::setprecision(8) << number;
        return stream.str();
    }
    if (value.is_boolean())
    {
        return value.get<bool>() ? "예" : "아니요";
    }
    return "상세 원문 확인";
}

std::string OutputUi::State(const std::string& state)
{
    static const std::map<std::string, std::string> labels{{"preview_only", "검토만 완료"},
                                                           {"generated_unverified", "생성 완료 / 검수 범위 확인"},
                                                           {"verified_profile", "명시 교환 범위 검수 통과"},
                                                           {"passed", "통과"},
                                                           {"passed_profile", "명시 교환 범위 검수 통과"},
                                                           {"failed", "실패"},
                                                           {"passed_same_kernel", "동일 커널 재입력 통과"},
                                                           {"not_assessed", "미평가"},
                                                           {"not_established", "미확립"},
                                                           {"unsupported", "미지원"},
                                                           {"unavailable", "사용 불가"},
                                                           {"queued", "대기"},
                                                           {"running", "실행 중"},
                                                           {"completed", "완료"},
                                                           {"cancelled", "취소"},
                                                           {"interrupted", "중단"},
                                                           {"partial", "부분 결과"},
                                                           {"missing", "미기록"},
                                                           {"included", "포함"},
                                                           {"omitted", "제외"},
                                                           {"blocked", "차단"},
                                                           {"warning", "주의"}};
    const auto found = labels.find(state);
    return found == labels.end() ? (state.empty() ? "미정" : "상태 상세: " + state) : found->second;
}

std::string OutputUi::Issues(const Json& issues)
{
    if (!issues.is_array())
    {
        return Text(issues, "");
    }
    std::string result;
    for (const auto& issue : issues)
    {
        if (!result.empty())
        {
            result += "\n";
        }
        if (issue.is_object())
        {
            result += Text(issue.value("message_ko", issue.value("message", issue.value("reason", Json(nullptr)))));
        }
        else
        {
            result += Text(issue);
        }
    }
    return result;
}

Json OutputUi::RecordForDisplay(const Json& record)
{
    if (!record.is_object() || !record.value("result", Json(nullptr)).is_object())
    {
        return record;
    }
    auto combined = record.at("result");
    for (const auto* key : {"format", "manifest", "report", "omissions"})
    {
        if (record.contains(key))
        {
            combined[key] = record.at(key);
        }
    }
    return combined;
}

bool OutputUi::MatchesPreview(const Json& result, const Json& input)
{
    if (!result.is_object() || !input.is_object() || !result.value("can_build", false) ||
        !result.value("review_hash", Json(nullptr)).is_string() || result.at("review_hash").get<std::string>().empty())
    {
        return false;
    }
    const auto source = result.value("snapshot", Json(nullptr));
    const auto expected = input.value("snapshot", Json(nullptr));
    return source.is_object() && expected.is_object() &&
           source.value("snapshot_id", Json(nullptr)) == expected.value("snapshot_id", Json(nullptr)) &&
           source.value("content_hash", Json(nullptr)) == expected.value("content_hash", Json(nullptr)) &&
           source.value("snapshot_id", Json(nullptr)).is_string() &&
           source.value("content_hash", Json(nullptr)).is_string() &&
           result.value("profile", Json(nullptr)).is_string() &&
           result.value("profile", Json(nullptr)) == input.value("profile", Json(nullptr)) &&
           result.value("format", Json(nullptr)) == input.value("format", Json(nullptr)) &&
           result.value("options", Json(nullptr)) == input.value("options", Json(nullptr));
}

std::string OutputUi::Conditions(const Json& record)
{
    if (!record.is_object())
    {
        return "출력할 고정 입력을 먼저 선택하세요.\n화면 표시 층과 출력 포함 층은 별개입니다.";
    }
    std::string result =
        "제작 조건: " +
        (record.contains("manufacturing") ? Text(record.at("manufacturing"))
                                          : "이 출력에서 확인하지 않음 / 출처 확인") +
        "\n측정 조건: " +
        (record.contains("measurement") ? Text(record.at("measurement")) : "이 출력에서 확인하지 않음 / 출처 확인") +
        "\n제조 승인 / RF·실측 검증: 이 출력으로 확정하지 않음";
    const auto assumptions = Issues(record.value("assumptions", Json::array()));
    if (!assumptions.empty())
    {
        result += "\n\n가정\n" + assumptions;
    }
    const auto omissionItems = record.value("omissions", Json::array());
    std::string omissions;
    if (omissionItems.is_array())
    {
        for (const auto& item : omissionItems)
        {
            if (!omissions.empty())
            {
                omissions += "\n";
            }
            const auto label = item.is_object() ? Text(item.value("label", item.value("name", Json(nullptr))), "") : "";
            if (!label.empty())
            {
                omissions += label + ": ";
            }
            omissions += Issues(Json::array({item}));
        }
    }
    else
    {
        omissions = Issues(omissionItems);
    }
    if (!omissions.empty())
    {
        result += "\n\n제외 / 의미 손실\n" + omissions;
    }
    return result;
}
