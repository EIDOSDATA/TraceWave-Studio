/** @file @brief 측정 기록의 미정과 출처를 읽기 가능한 한국어 요약으로 표시한다. */
#include "measurement_model.h"
#include <sstream>
#include <iomanip>
#include <array>

namespace MeasurementUi
{
const std::vector<FieldDefinition>& Fields()
{
    static const std::vector<FieldDefinition> fields{
        {"specimen.identifier", "시료 식별", "text", {}},
        {"specimen.serial", "일련 번호", "text", {}},
        {"specimen.lot", "제작 로트", "text", {}},
        {"specimen.fabrication_revision", "제작 개정", "text", {}},
        {"specimen.assembly_revision", "조립 개정", "text", {}},
        {"specimen.mounting_cycle", "장착 회차", "quantity", {"1"}},
        {"specimen.trim_notes", "조정 / 변경 기록", "text", {}},
        {"acquisition.instrument", "측정 장비", "text", {}},
        {"acquisition.serial", "장비 일련 번호", "text", {}},
        {"acquisition.firmware", "장비 펌웨어", "text", {}},
        {"acquisition.measured_at", "측정 일시 (ISO 8601)", "text", {}},
        {"acquisition.timezone", "측정 시간대", "text", {}},
        {"acquisition.if_bandwidth_hz", "IF 대역폭", "quantity", {"Hz", "kHz", "MHz"}},
        {"acquisition.averages", "평균 횟수", "quantity", {"1"}},
        {"acquisition.stimulus_power", "입력 전력", "quantity", {"dBm", "W", "mW"}},
        {"calibration.method", "교정 방식", "text", {}},
        {"calibration.performed_at", "교정 일시 (ISO 8601)", "text", {}},
        {"calibration.timezone", "교정 시간대", "text", {}},
        {"calibration.kit_id", "교정 키트", "text", {}},
        {"calibration.standard_ids", "교정 표준 (한 줄에 하나)", "texts", {}},
        {"calibration.verification_notes", "교정 확인 기록", "text", {}},
        {"fixture.connector", "커넥터", "text", {}},
        {"fixture.cable", "케이블", "text", {}},
        {"fixture.fixture_id", "지그 식별", "text", {}},
        {"fixture.path_notes", "연결 순서 / 급전", "text", {}},
        {"fixture.mounting_notes", "장착 조건", "text", {}},
        {"fixture.included_effects", "포함 효과 (한 줄에 하나)", "texts", {}},
        {"fixture.corrected_effects", "외부 보정 효과 (한 줄에 하나)", "texts", {}},
        {"environment.temperature", "온도", "quantity", {"degC", "K"}},
        {"environment.humidity", "상대 습도", "quantity", {"%", "1"}},
        {"environment.enclosure", "외장 조건", "text", {}},
        {"environment.battery", "배터리 조건", "text", {}},
        {"environment.pose", "자세 / 방향", "text", {}},
        {"environment.nearby_objects", "주변 물체 (한 줄에 하나)", "texts", {}}};
    return fields;
}

Json Leaf(const Json& record, const std::string& path)
{
    Json value = record;
    std::istringstream input(path);
    std::string key;
    while (std::getline(input, key, '.'))
    {
        if (!value.is_object() || !value.contains(key))
        {
            return nullptr;
        }
        value = value.at(key);
    }
    return value;
}

std::string Text(const Json& value)
{
    if (value.is_null())
    {
        return "미정";
    }
    if (value.is_string())
    {
        return value.get<std::string>().empty() ? "미정" : value.get<std::string>();
    }
    if (value.is_number())
    {
        std::ostringstream text;
        text << std::setprecision(10) << value.get<double>();
        return text.str();
    }
    if (value.is_boolean())
    {
        return value.get<bool>() ? "예" : "아니요";
    }
    if (value.is_object() && value.contains("number"))
    {
        return Text(value.at("number")) + " " + value.value("unit", std::string());
    }
    return value.is_array() ? std::to_string(value.size()) + "개 기록" : "보존 기록";
}

std::string Lines(const Json& values)
{
    std::string result;
    if (values.is_array())
    {
        for (const auto& value : values)
        {
            if (value.is_string())
            {
                result += (result.empty() ? "" : "\n") + value.get<std::string>();
            }
        }
    }
    return result;
}

Json Lines(const std::string& text)
{
    Json result = Json::array();
    std::istringstream input(text);
    std::string line;
    while (std::getline(input, line))
    {
        if (!line.empty() && line.back() == '\r')
        {
            line.pop_back();
        }
        if (!line.empty())
        {
            result.push_back(line);
        }
    }
    return result;
}

std::string Evidence(int index)
{
    static const std::array<const char*, 4> keys{"unknown", "planned", "declared", "reported"};
    return index >= 0 && index < static_cast<int>(keys.size()) ? keys.at(static_cast<std::size_t>(index)) : "unknown";
}

int Evidence(const Json& leaf)
{
    for (int index = 0; index < 4; ++index)
    {
        if (leaf.is_object() && leaf.value("evidence", "") == Evidence(index))
        {
            return index;
        }
    }
    return 0;
}

std::string Summary(const Json& record)
{
    if (!record.is_object())
    {
        return "시료 / 교정 기록 없음. 측정 조건을 확인하지 않았습니다.";
    }
    const std::string kind = record.value("data_class", "unknown");
    std::string text = "기록: " + record.value("name", std::string("이름 미기록")) + "\n자료 분류: " +
                       (kind == "measurement"         ? "사용자 제출 측정 자료"
                        : kind == "synthetic_fixture" ? "합성 시험 자료"
                                                      : "미정") +
                       "\n";
    for (const auto& field : Fields())
    {
        if (field.path == "specimen.identifier" || field.path == "specimen.fabrication_revision" ||
            field.path == "specimen.assembly_revision" || field.path == "calibration.method" ||
            field.path == "acquisition.measured_at" || field.path == "fixture.path_notes" ||
            field.path == "environment.pose")
        {
            const auto leaf = Leaf(record, field.path);
            text +=
                field.label + ": " + Text(leaf.is_object() ? leaf.value("value", Json(nullptr)) : Json(nullptr)) + "\n";
        }
    }
    text += "불확도: " + std::to_string(record.value("uncertainty", Json::array()).size()) +
            "개 기록 / 자동 전파와 실측 일치 판정은 수행하지 않습니다.\n";
    return text;
}

std::string Issues(const Json& response)
{
    std::string text;
    for (const auto& issue : response.value("issues", Json::array()))
    {
        text += issue.is_string()
                    ? issue.get<std::string>()
                    : issue.value("message_ko",
                                  issue.value("message", issue.value("reason", std::string("입력 조건 확인"))));
        text += "\n";
    }
    return text;
}

bool SameRecord(const Json& left, const Json& right)
{
    return left.value("source", Json(nullptr)) == right.value("source", Json(nullptr)) &&
           left.value("pin", Json(nullptr)) == right.value("pin", Json(nullptr)) &&
           left.value("measurement_ref", Json(nullptr)) == right.value("measurement_ref", Json(nullptr));
}
}
