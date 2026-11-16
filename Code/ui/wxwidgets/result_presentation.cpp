/** @file @brief 결과 조건의 표시 문자열만 구성하고 RF 환산은 서비스에 맡긴다. */
#include "result_presentation.h"
#include "frequency_display.h"
#include <map>

namespace ResultUi
{
std::string Number(const Json& value, int precision)
{
    return StudioFrequency::Value(value, {"", 1.0}, precision);
}

std::string Text(const Json& value)
{
    if (value.is_null() || value == "unknown" || value == "")
    {
        return "미정";
    }
    if (value.is_number())
    {
        return Number(value);
    }
    return value.is_string() ? value.get<std::string>() : "원문 기록 있음 (고급 상세 확인)";
}

std::string State(const Json& value)
{
    static const std::map<std::string, std::string> names{{"valid", "유효"},
                                                          {"finite", "유한"},
                                                          {"missing", "미정"},
                                                          {"unknown", "미정"},
                                                          {"completed", "계산 완료"},
                                                          {"computed_unvalidated", "계산값 / 물리 미확립"},
                                                          {"sample_dependent", "전제 확인 / 표본별 판정"},
                                                          {"defined", "정의됨"},
                                                          {"zero_magnitude_phase_undefined", "크기 0 / 위상 미정"},
                                                          {"undefined_zero_component", "영 성분으로 위상 미정의"},
                                                          {"undefined_zero_field", "영전계로 편파 미정의"},
                                                          {"infinite_linear", "무한 축비 / 선형 편파"},
                                                          {"circular", "원형 편파"},
                                                          {"elliptical", "타원 편파"},
                                                          {"overflow", "표현 범위 초과"},
                                                          {"not_recorded", "미기록"},
                                                          {"not_assessed", "미평가"},
                                                          {"end_criterion_reached", "기록된 종료 기준 도달"},
                                                          {"failed", "실패"},
                                                          {"cancelled", "취소됨"},
                                                          {"blocked", "차단됨"},
                                                          {"requires_review", "검토 필요"},
                                                          {"different_conditions", "물리 조건 다름"},
                                                          {"nonconverged", "미수렴"},
                                                          {"not_established", "미확립"},
                                                          {"not_evaluated", "미평가"},
                                                          {"conditional", "표본 통과 / 조건부"},
                                                          {"pass", "표본 통과"},
                                                          {"fail", "기준 미달"},
                                                          {"singular", "특이"},
                                                          {"ill_conditioned", "수치 불안정"},
                                                          {"nonfinite", "비유한"},
                                                          {"unsupported", "미지원"},
                                                          {"unavailable", "자료 없음"},
                                                          {"outside_validity", "적용 범위 밖"},
                                                          {"infinite", "무한대"},
                                                          {"nonfinite_projection", "표시 투영 범위 초과"},
                                                          {"active_region", "단위원 바깥 / 능동 영역"},
                                                          {"inside_unit_circle", "단위원 안쪽"},
                                                          {"on_unit_circle", "단위원 경계"},
                                                          {"computed", "계산"},
                                                          {"measured", "측정"},
                                                          {"imported", "가져온 자료"},
                                                          {"derived", "파생"},
                                                          {"interpolated", "보간"},
                                                          {"comparable", "수학 비교 가능"},
                                                          {"not_comparable", "수학 비교 불가"},
                                                          {"power", "전력파"},
                                                          {"pseudo", "의사파"},
                                                          {"traveling", "진행파"},
                                                          {"single_ended", "단일종단"},
                                                          {"differential", "차동"},
                                                          {"into_dut", "대상 안쪽"},
                                                          {"out_of_dut", "대상 바깥쪽"},
                                                          {"frequency_missing", "같은 주파수의 표본 없음"}};
    const auto key = value.is_string() ? value.get<std::string>() : "unknown";
    const auto found = names.find(key);
    return found == names.end() ? Text(value) : found->second;
}

std::string SourceKind(const Json& value)
{
    const auto key = value.is_string() ? value.get<std::string>() : "";
    return key == "network"  ? "네트워크 자료"
           : key == "solver" ? "해석 실행"
           : key == "sweep"  ? "연구 후보"
                             : "결과 자료";
}

std::string PortName(const Json& descriptor, std::size_t index)
{
    const auto names = descriptor.value("port_names", Json::array());
    const auto name = index < names.size() ? names.at(index) : Json(nullptr);
    return name.is_string() && !name.get<std::string>().empty()
               ? name.get<std::string>()
               : "자료 포트 " + std::to_string(index + 1) + " (이름 미정)";
}

std::string Complex(const Json& value, const std::string& state)
{
    if (value.is_number())
    {
        return Number(value);
    }
    if (!value.is_array() || value.size() != 2)
    {
        return state == "finite" ? "미정" : State(state);
    }
    if (!value.at(0).is_number() || !value.at(1).is_number())
    {
        return "미정";
    }
    return Number(value.at(0)) + (value.at(1) == 0.0 ? "" : " + j(" + Number(value.at(1)) + ")");
}

std::string SampleValue(const Json& point, const std::string& key)
{
    const auto state = point.value(key == "phase_deg" ? "phase_state" : key + "_state", std::string());
    if (state == "negative_infinity")
    {
        return "-inf (크기 0)";
    }
    if (state == "positive_infinity")
    {
        return "+inf";
    }
    if (state == "undefined_zero_magnitude")
    {
        return "정의 안 됨 (크기 0)";
    }
    if (state == "undefined_active")
    {
        return "정의 안 됨 (능동)";
    }
    if (state == "not_applicable")
    {
        return "해당 없음";
    }
    if (state == "nonfinite")
    {
        return "유한값 없음";
    }
    return Number(point.value(key, Json(nullptr)));
}

std::string ConditionSummary(const Json& description)
{
    if (!description.is_object())
    {
        return "결과를 선택하면 기록 당시의 조건을 표시합니다.";
    }
    const auto descriptor = description.value("descriptor", Json::object());
    const auto revision = description.value("source_revision", Json::object());
    const auto states = description.value("states", Json::object());
    std::string text =
        "원본\n" + Text(description.value("label", Json(nullptr))) + "\n" +
        SourceKind(description.value("source", Json::object()).value("kind", Json(nullptr))) +
        "\n입력: " + Text(revision.value("label", revision.value("name", Json(nullptr)))) +
        (description.value("is_current_design", false) ? "\n현재 설계 개정" : "\n저장 당시 개정 / 현재 편집과 구분") +
        "\n\n주파수\n" +
        StudioFrequency::Range(descriptor.value("frequency_min_hz", Json(nullptr)),
                               descriptor.value("frequency_max_hz", Json(nullptr))) +
        "\n\n기준\n파 정의: " + State(descriptor.value("wave_definition", Json(nullptr))) +
        "\n시간 규약: " + Text(descriptor.value("phasor_convention", Json(nullptr)));
    const auto ports = descriptor.value("port_ids", Json::array());
    for (std::size_t index = 0; index < ports.size(); ++index)
    {
        const auto item = [&descriptor, index](const std::string& key)
        {
            const auto values = descriptor.value(key, Json(nullptr));
            return values.is_array() && index < values.size() ? values.at(index) : Json(nullptr);
        };
        text += "\n\n" + PortName(descriptor, index) + "\n기준면: " + Text(item("reference_planes")) +
                "\nZ0: " + Complex(item("z0_ohm")) + " ohm\n" + State(item("port_modes")) + " / " +
                State(item("current_orientation"));
    }
    if (descriptor.value("z0_frequency_dependent", false))
    {
        text += "\nZ0는 주파수별입니다. 위 값은 첫 표본입니다.";
    }
    const auto conditions = descriptor.value("conditions", Json(nullptr));
    const auto condition = [&conditions](const std::string& key)
    {
        return conditions.is_null() ||
                       (conditions.is_object() && (!conditions.contains(key) || conditions.at(key).is_null()))
                   ? "미정"
                   : "원문 기록 있음 / 확정 여부는 출처 확인";
    };
    text += "\n\n검증 상태\n계산: " + State(states.value("computation", Json(nullptr))) +
            "\n수치 수렴: " + State(states.value("numerical", Json("not_established"))) +
            "\n물리 검증: " + State(states.value("physics", Json("not_established"))) +
            "\n제작 조건: " + condition("manufacturing") + "\n측정 조건: " + condition("measurement");
    const auto numerical = description.value("numerical_details", Json(nullptr));
    if (numerical.is_object())
    {
        text += "\n\n계산 종료 기록\n" + State(numerical.value("status", Json("not_recorded")));
        if (numerical.value("reason", Json(nullptr)).is_string())
        {
            text += "\n" + numerical.at("reason").get<std::string>();
        }
        text += "\n독립 수렴: " + State(numerical.value("formal_convergence", Json("not_established")));
    }
    const auto references = description.value("source_refs", Json::array());
    text += "\n\n보존 출처: " + std::to_string(references.is_array() ? references.size() : 0) + "개 / 원문은 고급 상세";
    const auto assessments = description.value("historical_assessments", Json::array());
    if (assessments.is_array() && !assessments.empty())
    {
        text += "\n\n당시 목표 평가 (현재 목표의 재평가 아님)";
        std::size_t shown = 0;
        for (const auto& assessment : assessments)
        {
            if (shown++ >= 8)
            {
                break;
            }
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
            text += "\n" + (name.is_string() ? name.get<std::string>() : "보존 목표 평가") + ": " +
                    State(assessment.value("status", Json("not_evaluated")));
        }
        if (assessments.size() > 8)
        {
            text += "\n나머지 평가는 보존 원문에 유지됩니다.";
        }
    }
    return text;
}

bool Matches(const Json& response, const Json& description)
{
    return response.is_object() && description.is_object() && description.contains("source") &&
           description.contains("pin") && response.value("source", Json(nullptr)) == description.at("source") &&
           response.value("pin", Json(nullptr)) == description.at("pin");
}
}
