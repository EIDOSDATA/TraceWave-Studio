/** @file @brief 연구 표시 모델은 원문 표현식과 미정값을 추측하지 않는다. */
#include "sweep_model.h"
#include "frequency_display.h"
#include <map>

namespace SweepUi
{
std::string Text(const Json& value)
{
    return value.is_null() ? "미정" : (value.is_string() ? value.get<std::string>() : value.dump());
}

std::string Status(const std::string& value)
{
    static const std::map<std::string, std::string> labels{{"ready", "실행 전"},
                                                           {"pending", "대기"},
                                                           {"running", "실행 중"},
                                                           {"preparing", "준비 중"},
                                                           {"prepare", "준비"},
                                                           {"solve", "해석"},
                                                           {"evaluated", "목표 평가됨"},
                                                           {"completed", "완료"},
                                                           {"failed", "실패"},
                                                           {"solver_failed", "해석 실패"},
                                                           {"blocked", "차단"},
                                                           {"invalid", "입력 불가"},
                                                           {"invalid_geometry", "형상 불가"},
                                                           {"invalid_input", "입력 오류"},
                                                           {"unsupported", "미지원"},
                                                           {"duplicate", "중복 후보"},
                                                           {"nonconverged", "미수렴"},
                                                           {"not_established", "미확립"},
                                                           {"cancel_requested", "취소 확인 중"},
                                                           {"cancelled", "취소됨"},
                                                           {"interrupted", "중단됨"},
                                                           {"resuming", "재개 중"},
                                                           {"budget_exhausted", "예산 소진"},
                                                           {"paused", "일시 정지"},
                                                           {"connected", "연결"},
                                                           {"open", "개방"},
                                                           {"short", "단락"},
                                                           {"dnp", "미실장"},
                                                           {"pass", "표본 통과"},
                                                           {"fail", "기준 미달"},
                                                           {"conditional", "조건부"},
                                                           {"unknown", "미정"},
                                                           {"unevaluated", "미평가"},
                                                           {"planned", "계획됨"},
                                                           {"valid", "유효"},
                                                           {"skipped", "제외됨"},
                                                           {"not_evaluated", "미평가"},
                                                           {"missing", "미정"},
                                                           {"singular", "특이"},
                                                           {"ill_conditioned", "수치 불안정"},
                                                           {"outside_validity", "적용 범위 밖"},
                                                           {"nonfinite", "비유한"},
                                                           {"computed", "계산"},
                                                           {"measured", "측정"},
                                                           {"imported", "가져온 자료"},
                                                           {"derived", "파생"},
                                                           {"interpolated", "보간"}};
    const auto found = labels.find(value);
    return found == labels.end() ? value : found->second;
}

std::string Type(const std::string& value)
{
    return value == "grid_sweep"        ? "설계 변수 스윕"
           : value == "numerical_study" ? "수치 설정 다축 연구"
           : value == "circuit_sweep"   ? "회로 소자 스윕"
                                        : value;
}

std::string Quantity(const Json& value)
{
    if (!value.is_object())
    {
        return value.is_string() ? Status(value.get<std::string>()) : Text(value);
    }
    if (value.contains("text"))
    {
        return Text(value.at("text")) + " " + value.value("unit", "");
    }
    if (value.value("dimension", "") == "frequency")
    {
        return StudioFrequency::WithUnit(value.value("value_si", Json(nullptr)));
    }
    if (value.contains("value_si"))
    {
        static const std::map<std::string, std::string> si{
            {"length", "m"},     {"angle", "rad"},     {"time", "s"},        {"impedance", "ohm"},
            {"inductance", "H"}, {"capacitance", "F"}, {"dimensionless", ""}};
        const auto unit = si.find(value.value("dimension", ""));
        return Text(value.at("value_si")) + (unit == si.end() || unit->second.empty() ? "" : " " + unit->second);
    }
    return value.value("label", "입력 원문 있음");
}

std::string Diagnostics(const Json& values)
{
    if (!values.is_array())
    {
        return values.is_null() ? "" : Text(values);
    }
    std::string result;
    for (const auto& row : values)
    {
        if (!result.empty())
        {
            result += "\n";
        }
        result +=
            row.is_object() ? row.value("message_ko", row.value("message", row.value("code", "진단"))) : Text(row);
    }
    return result;
}

std::string CandidateValues(const Json& candidate)
{
    const auto values = candidate.value("values", Json::array());
    std::string text;
    for (const auto& value : values)
    {
        if (!text.empty())
        {
            text += ", ";
        }
        text += value.is_object() && (value.contains("quantity") || value.contains("value"))
                    ? value.value("name", "") + " " +
                          (value.contains("text")
                               ? Text(value.at("text")) + " " + value.value("unit", "")
                               : Quantity(value.contains("value") ? value.at("value") : value.at("quantity")))
                    : Quantity(value);
    }
    return text.empty() ? "값은 후보 상세에서 확인" : text;
}

Json Variables(const Json& context, const std::string& type, const std::string& circuitId)
{
    Json result = Json::array();
    if (type != "circuit_sweep")
    {
        for (const auto& source :
             context.value(type == "grid_sweep" ? "parameters" : "numerical_fields", Json::array()))
        {
            Json row = source;
            row["kind"] = type == "grid_sweep" ? "parameter" : "solver_setting";
            row["name"] = source.value("name", source.value("label", "이름 없음"));
            result.push_back(std::move(row));
        }
        return result;
    }
    for (const auto& circuit : context.value("circuits", Json::array()))
    {
        if (circuit.value("id", "") != circuitId)
        {
            continue;
        }
        for (const auto& element :
             circuit.value("display", circuit.value("definition", Json::object())).value("elements", Json::array()))
        {
            Json row{{"kind", "circuit_value"},
                     {"id", element.at("id")},
                     {"name", element.value("name", "소자") + " 값"},
                     {"quantity", element.at("value")},
                     {"dimension", element.at("value").value("dimension", "")},
                     {"units", element.value("allowed_units", Json::array({element.value("value_unit", "ohm")}))},
                     {"eligible", true},
                     {"read_only", false}};
            result.push_back(row);
            row["kind"] = "circuit_state";
            row["dimension"] = "state";
            row["name"] = element.value("name", "소자") + " 연결 상태";
            row["quantity"] = element.value("state", "connected");
            row["units"] = Json::array();
            result.push_back(std::move(row));
        }
    }
    return result;
}

std::string VariableSummary(const Json& variable)
{
    if (variable.contains("range"))
    {
        const auto& range = variable.at("range");
        return Quantity(range.at("start")) + " ~ " + Quantity(range.at("stop")) + ", " + Text(range.at("count")) +
               "개";
    }
    std::string text;
    for (const auto& value : variable.value("values", Json::array()))
    {
        if (!text.empty())
        {
            text += ", ";
        }
        text += Quantity(value);
    }
    return text;
}
}
