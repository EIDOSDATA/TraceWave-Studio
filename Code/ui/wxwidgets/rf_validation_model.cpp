/** @file @brief 실행, 수치 안정성, 독립 참조와 실측을 별개 상태로 표시한다. */
#include "rf_validation_model.h"
#include "result_presentation.h"
#include "frequency_display.h"
#include <map>
#include <algorithm>
#include <cmath>
#include <ctime>
#include <limits>

namespace RfValidationUi
{
std::string State(const Json& value)
{
    static const std::map<std::string, std::string> names{{"plan", "계획 저장됨"},
                                                          {"observed", "관측값 / 합격 한계 없음"},
                                                          {"identical", "원시 결과 재처리 일치"},
                                                          {"requires_review", "기준 초과 / 검토 필요"},
                                                          {"failed", "실패"},
                                                          {"cancelled", "취소됨"},
                                                          {"partial_evidence", "부분 근거 / 전체 검증 미확립"},
                                                          {"recorded", "기록 있음"},
                                                          {"not_started", "미실행"},
                                                          {"cancel_requested", "취소 요청됨"},
                                                          {"observed_not_established", "변화 관측 / 미확립"},
                                                          {"within_preliminary_reference", "초기 참조 범위 이내"},
                                                          {"planned", "계획 저장됨"},
                                                          {"created", "계획 저장됨"},
                                                          {"ready", "준비됨"},
                                                          {"pending", "대기"},
                                                          {"queued", "대기"},
                                                          {"preparing", "준비 중"},
                                                          {"running", "실행 중"},
                                                          {"prepared", "준비 완료"},
                                                          {"solved", "계산 완료"},
                                                          {"postprocessing", "후처리 중"},
                                                          {"postprocessed", "후처리 완료"},
                                                          {"completed", "단계 완료"},
                                                          {"partial", "일부 완료"},
                                                          {"interrupted", "중단됨"},
                                                          {"blocked_before_execution", "실행 전 차단"},
                                                          {"passed", "해당 기준 충족"},
                                                          {"established", "해당 범위 확립"},
                                                          {"within_initial_bounds", "초기 비교 범위 이내"},
                                                          {"not_verified", "미검증"},
                                                          {"not_performed", "미수행"},
                                                          {"not_applicable", "적용 대상 아님"}};
    const auto found = value.is_string() ? names.find(value.get<std::string>()) : names.end();
    return found == names.end() ? ResultUi::State(value) : found->second;
}

std::string Axis(const Json& value)
{
    static const std::map<std::string, std::string> names{{"manufacturing", "제작"},
                                                          {"interior_grid_mm", "내부 격자"},
                                                          {"planned_grid_mm", "계획 격자"},
                                                          {"planned_refinement", "계획 국부 분할"},
                                                          {"mesh", "격자"},
                                                          {"boundary", "경계"},
                                                          {"termination", "시간 종료"},
                                                          {"independent_reference", "독립 참조"},
                                                          {"measurement", "실측"},
                                                          {"model", "모델 비교"},
                                                          {"body", "형상군"},
                                                          {"normalization", "정규화"}};
    const auto found = value.is_string() ? names.find(value.get<std::string>()) : names.end();
    return found == names.end() ? ResultUi::Text(value) : found->second;
}

std::string Reason(const Json& value)
{
    if (value == "native_excitation_and_boundary_contract_unresolved")
    {
        return "native 여기와 경계 계약 미확정";
    }
    if (value == "finite_feed_cross_section_and_terminal_contract_unresolved")
    {
        return "유한 급전 단면과 단자 계약 미확정";
    }
    return ResultUi::Text(value);
}

/** @brief 보존된 epoch만 UTC 표시로 바꾸며 없는 시각을 현재 시각으로 채우지 않는다. */
std::string Time(const Json& value)
{
    if (value.is_string())
    {
        return value.get<std::string>();
    }
    if (!value.is_number())
    {
        return "시각 미기록";
    }
    const double seconds = value.get<double>();
    if (!std::isfinite(seconds) || seconds < 0 ||
        seconds >= static_cast<double>(std::numeric_limits<std::time_t>::max()))
    {
        return "시각 표시 범위 밖";
    }
    const auto instant = static_cast<std::time_t>(seconds);
    const auto* time = std::gmtime(&instant);
    char buffer[40]{};
    return time != nullptr && std::strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S UTC", time)
               ? std::string(buffer)
               : "시각 표시 범위 밖";
}

std::string Notes(const Json& value)
{
    if (value.is_null() || (value.is_array() && value.empty()))
    {
        return "미정 / 기록 없음";
    }
    if (!value.is_array())
    {
        if (value.is_object())
        {
            for (const auto* key : {"label", "name", "description", "reason", "note", "url"})
            {
                if (value.contains(key) && value.at(key).is_string())
                {
                    return value.at(key).get<std::string>();
                }
            }
        }
        return ResultUi::Text(value);
    }
    std::string text;
    for (const auto& item : value)
    {
        text += (text.empty() ? "" : "\n\n") + Notes(item);
    }
    return text;
}

std::string Resources(const Json& value)
{
    if (!value.is_object())
    {
        return "미기록";
    }
    static const std::map<std::string, std::string> names{{"wall_seconds", "시간"},
                                                          {"ram_bytes", "메모리"},
                                                          {"disk_bytes", "디스크 예약"},
                                                          {"native_solves", "계산 횟수"},
                                                          {"max_native_solves", "최대 계산 횟수"},
                                                          {"worker_calls", "워커 호출"},
                                                          {"max_worker_calls", "최대 워커 호출"},
                                                          {"concurrency", "동시 실행"},
                                                          {"analysis_seconds", "계산 예약 시간"},
                                                          {"worker_reserved_seconds", "워커 예약 시간"},
                                                          {"case_output_bytes", "사례 출력 상한"},
                                                          {"artifact_bytes", "단일 산출물 상한"},
                                                          {"memory_estimate_bytes", "메모리 추정 상한"}};
    std::string text;
    for (auto item = value.begin(); item != value.end(); ++item)
    {
        const auto found = names.find(item.key());
        if (found == names.end())
        {
            continue;
        }
        const auto& quantity = item.value();
        text += found->second + ": ";
        text += quantity.is_object() ? ResultUi::Text(quantity.value("text", quantity.value("value", Json(nullptr))))
                                     : ResultUi::Text(quantity);
        text += "\n";
    }
    return text.empty() ? "기록 있음 / 고급 상세 확인" : text;
}

/** @brief 사전에 저장된 기준만 표시하고 새 합격 한계나 백분율을 계산하지 않는다. */
std::string Criteria(const Json& value)
{
    if (!value.is_object())
    {
        return "기준 미기록";
    }
    const auto dipole = value.value("dipole", Json::object());
    std::string text;
    for (const auto& item :
         std::vector<std::pair<std::string, std::string>>{{"maximum_pattern_error", "정규화 패턴 최대 오차"},
                                                          {"relative_directivity_error", "지향성 상대 오차"},
                                                          {"efficiency_error", "효율 절대 차이"}})
    {
        text += item.second + ": " +
                ResultUi::Number(dipole.is_object() ? dipole.value(item.first, Json(nullptr)) : Json(nullptr)) +
                " (비율)\n";
    }
    for (const auto& item : std::vector<std::pair<std::string, std::string>>{
             {"reference_directivity", "이상 반파장 참조 지향성 (선형)"},
             {"mesh_relative_change_acceptance", "격자 상대 변화 합격 한계"},
             {"ro4350b_local_loss_relative_limit", "RO4350B 국부 손실 상대 기준"},
             {"loss_absolute_floor", "손실 비교 절대 바닥값"},
             {"total_power_balance_limit", "총 전력 수지 상대 기준"}})
    {
        text += item.second + ": " + ResultUi::Number(value.value(item.first, Json(nullptr))) + "\n";
    }
    return text + "\n" + ResultUi::Text(value.value("dipole_scope", Json(nullptr))) + "\n" +
           ResultUi::Text(value.value("mesh_policy", Json(nullptr)));
}

bool HasSource(const Json& item)
{
    return item.is_object() && item.value("source", Json(nullptr)).is_object() &&
           item.value("pin", Json(nullptr)).is_object() &&
           item.at("pin").value("identity_hash", Json(nullptr)).is_string();
}

std::vector<std::vector<std::string>> Cases(const Json& record)
{
    std::vector<std::vector<std::string>> rows;
    for (const auto& item : record.value("cases", Json::array()))
    {
        rows.push_back(
            {ResultUi::Text(item.value("name", Json(nullptr))), Axis(item.value("axis", Json(nullptr))),
             ResultUi::Text(item.value("level", Json(nullptr))), State(item.value("execution_state", Json(nullptr))),
             HasSource(item) ? "봉인 결과 있음"
             : record.value("report_id", Json(nullptr)).is_null() &&
                     item.value("blocked_reason", Json(nullptr)).is_null()
                 ? "판정 선택 필요"
                 : "결과 미기록",
             item.value("blocked_reason", Json(nullptr)).is_null() ? "차단 없음" : Reason(item.at("blocked_reason"))});
    }
    return rows;
}

std::vector<std::vector<std::string>> States(const Json& record)
{
    std::vector<std::vector<std::string>> rows;
    const auto states = record.value("validation_states", Json::object());
    for (const auto* key : {"mesh", "boundary", "termination", "independent_reference", "manufacturing", "measurement"})
    {
        const auto item = states.is_object() ? states.value(key, Json::object()) : Json::object();
        rows.push_back({Axis(key), State(item.is_object() ? item.value("state", Json("not_established")) : item),
                        ResultUi::Text(item.is_object() ? item.value("reason", Json(nullptr)) : Json(nullptr))});
    }
    return rows;
}

std::vector<std::vector<std::string>> Metrics(const Json& record)
{
    std::vector<std::vector<std::string>> rows;
    const auto values = record.value("rows", Json::array());
    const auto scale = StudioFrequency::ForSamples(values);
    for (const auto& item : values)
    {
        const auto frequency = item.value("frequency_hz", Json(nullptr));
        rows.push_back(
            {ResultUi::Text(item.value("case_name", Json(nullptr))), ResultUi::Text(item.value("label", Json(nullptr))),
             frequency.is_number() ? StudioFrequency::Value(frequency, scale) + " " + scale.unit : "미정",
             ResultUi::Number(item.value("expected", Json(nullptr))),
             ResultUi::Number(item.value("actual", Json(nullptr))),
             ResultUi::Number(item.value("error", Json(nullptr))),
             ResultUi::Number(item.value("tolerance", Json(nullptr))),
             item.value("unit", Json(nullptr)) == "ratio"     ? "1 (비율)"
             : item.value("unit", Json(nullptr)) == "boolean" ? "0 / 1"
                                                              : ResultUi::Text(item.value("unit", Json(nullptr))),
             State(item.value("state", Json(nullptr))), Reason(item.value("reason", Json(nullptr)))});
    }
    return rows;
}
}
