/** @file @brief 내부 식별자를 기본 안내에서 빼고 출력 상태의 의미를 표시한다. */
#include "output_model.h"
#include <filesystem>
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
    if (value.contains("reader") && value.at("reader").is_string())
    {
        return value.at("reader").get<std::string>();
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

std::string OutputUi::Purpose(const Json& record)
{
    const auto profile = record.value("profile", "");
    const auto format = record.value("format", "");
    if (profile == "rfad.exchange.kicad-board/0.1" || format == "kicad_pcb")
    {
        return "KiCad 보드 교환";
    }
    if (profile == "rfad.exchange.kicad-footprint/0.1" || format == "kicad_mod")
    {
        return "KiCad 풋프린트 교환";
    }
    if (profile == "rfad.exchange.cam/0.1" || format == "gerber_job")
    {
        return "Gerber / 드릴 / Job 패키지";
    }
    if (profile == "rfad.step.mechanical/0.1" || format == "step")
    {
        return "STEP 기계 형상";
    }
    const auto options = record.value("options", Json(nullptr));
    if (options.is_object() && options.value("mode", "") == "fabrication_geometry")
    {
        return "1:1 형상";
    }
    if (profile == "rfad.exchange.drawing/0.1" || format == "pdf" || format == "svg" || format == "dxf")
    {
        return format == "verification" ? "연관 도면 재검수 / 원래 용도 확인" : "기술 도면";
    }
    return "보존 원문의 출력 범위 확인";
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
                                                           {"uploading", "원문 전송 중"},
                                                           {"sealed", "원문 봉인"},
                                                           {"abandoned", "전송 중단 / 원문 보존"},
                                                           {"parsed_unapplied", "읽기 완료 / 미적용"},
                                                           {"not_started", "시작 전"},
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
            result += Text(
                issue.value("message_ko",
                            issue.value("message", issue.value("reason_label", issue.value("reason", Json(nullptr))))));
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
            if (std::string(key) == "format" && record.at(key) == "verification" &&
                combined.value("format", Json(nullptr)).is_string() &&
                !combined.at("format").get<std::string>().empty())
            {
                continue;
            }
            combined[key] = record.at(key);
        }
    }
    if (combined.value("format", "") == "verification")
    {
        static const std::map<std::string, std::string> formats{{"rfad.exchange.cam/0.1", "gerber_job"},
                                                                {"rfad.exchange.kicad-board/0.1", "kicad_pcb"},
                                                                {"rfad.exchange.kicad-footprint/0.1", "kicad_mod"},
                                                                {"rfad.step.mechanical/0.1", "step"}};
        const auto found = formats.find(combined.value("profile", ""));
        if (found != formats.end())
        {
            combined["format"] = found->second;
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

std::string OutputUi::ManifestPath(const Json& record)
{
    if (!record.is_object() || !record.value("result", Json(nullptr)).is_object())
    {
        return {};
    }
    for (const auto& artifact : record.at("result").value("artifacts", Json::array()))
    {
        if (artifact.value("role", "") == "manifest")
        {
            const auto uri = artifact.value("uri", "");
            const auto relative = std::filesystem::u8path(uri);
            if (uri.empty() || relative.is_absolute() || relative.has_root_name() || relative.filename() != "manifest.json")
            {
                return {};
            }
            for (const auto& part : relative)
            {
                if (part == ".." || part == ".")
                {
                    return {};
                }
            }
            return uri;
        }
    }
    return {};
}
