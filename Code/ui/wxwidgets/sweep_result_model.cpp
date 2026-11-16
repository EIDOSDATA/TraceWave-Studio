/** @file @brief 후보 결과의 조건/출처와 오류 상태를 사용자용 문장으로 투영한다. */
#include "sweep_model.h"
#include "frequency_display.h"
#include <map>
#include <set>

namespace
{
/** @brief 미정 값을 다른 정보로 채우거나 원문 객체를 기본 화면에 노출하지 않는다. */
std::string KnownText(const Json& value)
{
    if (value.is_null() || value == "" || value == "unknown")
    {
        return "미정";
    }
    if (value.is_number())
    {
        return StudioFrequency::Value(value, {"", 1.0}, 8);
    }
    return value.is_string() ? value.get<std::string>() : "원문 기록 있음 (고급 상세 확인)";
}

Json Item(const Json& object, const std::string& key, std::size_t index)
{
    const auto values = object.value(key, Json(nullptr));
    return values.is_array() && index < values.size() ? values.at(index) : Json(nullptr);
}

std::string Convention(const Json& value)
{
    static const std::map<std::string, std::string> labels{
        {"power", "전력파"},      {"pseudo", "의사파"},      {"traveling", "진행파"},      {"single_ended", "단일종단"},
        {"differential", "차동"}, {"into_dut", "대상 안쪽"}, {"out_of_dut", "대상 바깥쪽"}};
    const auto found = labels.find(value.is_string() ? value.get<std::string>() : "");
    return found == labels.end() ? KnownText(value) : found->second;
}

std::string Impedance(const Json& pair)
{
    if (!pair.is_array() || pair.size() != 2 || !pair.at(0).is_number() || !pair.at(1).is_number())
    {
        return "미정";
    }
    const double imaginary = pair.at(1).get<double>();
    return KnownText(pair.at(0)) + (imaginary == 0.0 ? "" : " + j(" + KnownText(pair.at(1)) + ")") + " ohm";
}

std::string Diagnostic(const Json& value)
{
    if (value.is_string())
    {
        return value.get<std::string>();
    }
    if (value.is_object())
    {
        for (const auto* key : {"message_ko", "message", "reason"})
        {
            const auto text = value.value(key, Json(nullptr));
            if (text.is_string() && !text.get<std::string>().empty())
            {
                return text.get<std::string>();
            }
        }
        return "진단 기록 있음 (고급 상세 확인)";
    }
    return "";
}

std::string Metric(const std::string& value)
{
    return value == "s11_db"                 ? "반사 (S11)"
           : value == "radiation_efficiency" ? "방사 효율"
           : value == "total_efficiency"     ? "총 효율"
           : value == "fractional_bandwidth" ? "비대역폭 (FBW)"
                                             : "성능 기준";
}
}

namespace SweepUi
{
std::string SampleValue(const Json& sample, const std::string& key)
{
    const auto value = sample.value(key, Json(nullptr));
    if (value.is_number())
    {
        return StudioFrequency::Value(value, {"", 1.0}, 8);
    }
    const auto state = sample.value(key == "phase_deg" ? "phase_state" : key + "_state", "missing");
    if (state == "negative_infinity")
    {
        return "-inf (크기 0)";
    }
    if (state == "positive_infinity")
    {
        return "+inf";
    }
    if (state == "not_applicable")
    {
        return "해당 없음";
    }
    if (state.find("undefined") == 0)
    {
        return "정의 불가";
    }
    return state == "nonfinite" || sample.value("status", "") == "nonfinite" ? "유한값 없음" : "미정";
}

std::string ResultConditions(const Json& result)
{
    const auto& descriptor = result.at("descriptor");
    std::string text =
        "저장된 연구 후보 / 실제 계산 결과\n계산 완료, 목표 표본 판정, 수치 수렴, 실측 검증은 서로 구분합니다.\n\n";
    text += "전체 주파수: " +
            StudioFrequency::Range(descriptor.value("frequency_min_hz", Json(nullptr)),
                                   descriptor.value("frequency_max_hz", Json(nullptr))) +
            "\n자료 종류: " + KnownText(descriptor.value("parameter_kind", Json(nullptr))) + " / " +
            KnownText(descriptor.value("unit", Json(nullptr))) +
            "\n표본 수: " + KnownText(descriptor.value("sample_count", Json(nullptr))) +
            "\n파 정의: " + Convention(descriptor.value("wave_definition", Json(nullptr))) +
            "\n시간 규약: " + KnownText(descriptor.value("phasor_convention", Json(nullptr)));
    const auto ports = descriptor.value("port_ids", Json::array());
    for (std::size_t index = 0; index < ports.size(); ++index)
    {
        text += "\n\n자료 포트 " + std::to_string(index + 1) + ": " + KnownText(Item(descriptor, "port_names", index)) +
                "\n기준면: " + KnownText(Item(descriptor, "reference_planes", index)) +
                "\n기준 Z0: " + Impedance(Item(descriptor, "z0_ohm", index)) +
                "\n포트 모드: " + Convention(Item(descriptor, "port_modes", index)) +
                " / 전류 방향: " + Convention(Item(descriptor, "current_orientation", index));
    }
    if (descriptor.value("z0_frequency_dependent", false))
    {
        text += "\nZ0는 주파수별입니다. 위 값은 첫 표본이며 전체 조건은 원본에 보존합니다.";
    }
    const auto conditions = descriptor.value("conditions", Json(nullptr));
    const auto condition = [&conditions](const std::string& key)
    {
        if (conditions.is_null() ||
            (conditions.is_object() && (!conditions.contains(key) || conditions.at(key).is_null())))
        {
            return std::string("미정");
        }
        return std::string("원문 기록 있음. 확정 여부는 출처와 고급 상세 확인");
    };
    text += "\n\n제작 조건: " + condition("manufacturing") + "\n측정 조건: " + condition("measurement") +
            "\n유효하지 않은 복소 값: " + KnownText(descriptor.value("invalid_value_count", Json(nullptr))) +
            "\n\n출처\n";
    const auto sources = descriptor.value("source_refs", Json::array());
    if (sources.empty())
    {
        text += "출처 기록 미정\n";
    }
    for (const auto& source : sources)
    {
        if (source.is_string())
        {
            text += source.get<std::string>() + "\n";
        }
        else
        {
            std::string label;
            for (const auto* key : {"title", "name", "label", "description", "text", "url"})
            {
                const auto value = source.is_object() ? source.value(key, Json(nullptr)) : Json(nullptr);
                if (value.is_string() && !value.get<std::string>().empty())
                {
                    label = value.get<std::string>();
                    break;
                }
            }
            text += label.empty() ? "구조화된 출처 기록 있음 (고급 상세 확인)\n" : label + "\n";
        }
    }
    text += "\n목표 판정\n";
    const auto assessments = result.value("assessments", Json::array());
    if (assessments.empty())
    {
        text += "저장된 목표 평가 기록이 없습니다. 목표 충족을 판정하지 않습니다.\n";
    }
    for (const auto& assessment : assessments)
    {
        const auto evidence = assessment.value("evidence", Json::object());
        const auto target =
            evidence.value("target_original", evidence.value("target_original_summary", Json::object()));
        text += KnownText(target.value("name", Json("저장 당시 목표"))) + " / " +
                Status(assessment.value("status", "not_evaluated")) + "\n";
        for (const auto* key : {"reason", "diagnostic"})
        {
            const auto reason = Diagnostic(assessment.value(key, Json(nullptr)));
            if (!reason.empty())
            {
                text += "  " + reason + "\n";
            }
        }
        for (const auto& criterion : assessment.value("criteria", Json::array()))
        {
            text += "  " + Metric(criterion.value("metric", "")) + ": " +
                    Status(criterion.value("status", "not_evaluated")) + "\n";
            std::set<std::string> reasons;
            const auto reason = Diagnostic(criterion.value("reason", Json(nullptr)));
            if (!reason.empty())
            {
                reasons.insert(reason);
            }
            for (const auto& point : criterion.value("points_preview", Json::array()))
            {
                const auto detail = Diagnostic(point.value("reason", Json(nullptr)));
                if (!detail.empty())
                {
                    reasons.insert(detail);
                }
            }
            for (const auto& detail : reasons)
            {
                text += "    " + detail + "\n";
            }
            if (criterion.value("point_count", 0) >
                static_cast<int>(criterion.value("points_preview", Json::array()).size()))
            {
                text += "    사유는 앞 표본 요약입니다. 전체 판정 원문은 저장 기록에 보존합니다.\n";
            }
        }
    }
    text += "\n수치 수렴: 별도 검증 / 실측 검증: 미확립\n입력 스냅샷과 원본 조건은 저장 당시 그대로 보존합니다.";
    return text;
}
}
