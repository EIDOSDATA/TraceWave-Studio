/** @file @brief 연구 폼의 엄격한 숫자 변환과 읽기 전용 전력 표시를 구현한다. */
#include "project_study_model.h"
#include "frequency_display.h"
#include <cmath>
#include <iomanip>
#include <locale>
#include <sstream>
#include <stdexcept>

namespace
{
/** @brief locale과 무관하게 전체 문자열이 유한 숫자인지 확인한다. */
double Number(const std::string& text)
{
    std::istringstream input(text);
    input.imbue(std::locale::classic());
    double value = 0;
    input >> value;
    if (!input || !std::isfinite(value))
    {
        throw std::runtime_error("유한한 숫자를 입력하십시오.");
    }
    input >> std::ws;
    if (!input.eof())
    {
        throw std::runtime_error("숫자 뒤에 다른 문자를 넣을 수 없습니다.");
    }
    return value;
}

/** @brief 표본/시간 단계/각도 간격에 소수 정수를 강제로 반올림하지 않는다. */
int Integer(const std::string& text)
{
    const double value = Number(text);
    if (value != std::floor(value) || value < 0 || value > 1000000)
    {
        throw std::runtime_error("지원 범위의 정수를 입력하십시오.");
    }
    return static_cast<int>(value);
}

/** @brief 공학 단위 입력을 저장 계약의 Hz로 변환한다. 단위를 생략하면 Hz로 읽는다. */
double Frequency(const std::string& text)
{
    std::istringstream input(text);
    input.imbue(std::locale::classic());
    double value = 0;
    std::string unit;
    if (!(input >> value))
    {
        throw std::runtime_error("주파수를 숫자로 입력하세요. 예: 2.4 GHz");
    }
    if (input >> unit)
    {
        if (unit != "Hz" && unit != "kHz" && unit != "MHz" && unit != "GHz")
        {
            throw std::runtime_error("주파수 단위는 Hz, kHz, MHz, GHz를 사용하세요.");
        }
        value *= StudioFrequency::ForRange(0.0, 0.0, unit).divisor;
        input >> std::ws;
        if (!input.eof())
        {
            throw std::runtime_error("한 주파수에 단위 하나만 입력하세요.");
        }
    }
    if (!std::isfinite(value) || value <= 0)
    {
        throw std::runtime_error("0보다 큰 유한 주파수를 입력하세요.");
    }
    return value;
}

/** @brief 쉼표 목록의 빈 항목과 잘못된 수치를 거절한다. */
Json Numbers(const std::string& text, double (*parse)(const std::string&))
{
    Json values = Json::array();
    std::istringstream input(text);
    std::string part;
    if (text.empty() || text.back() == ',')
    {
        throw std::runtime_error("쉼표로 구분한 숫자 목록을 입력하십시오.");
    }
    while (std::getline(input, part, ','))
    {
        values.push_back(parse(part));
    }
    return values;
}

/** @brief 원시 유효 정밀도를 읽기 쉬운 문자열로 표현한다. */
std::string Format(const Json& value)
{
    if (!value.is_number() || !std::isfinite(value.get<double>()))
    {
        throw std::runtime_error("표시 값이 유한한 숫자가 아닙니다.");
    }
    std::ostringstream output;
    output.imbue(std::locale::classic());
    output << std::setprecision(9) << value.get<double>();
    return output.str();
}

/** @brief 설정의 이진 실수를 손실 없이 다시 읽을 수 있는 가장 짧은 JSON 숫자로 보존한다. */
std::string InputFormat(const Json& value)
{
    Format(value);
    return value.dump();
}

/** @brief 간결한 단위로 왕복할 수 없으면 원래 Hz 정밀도를 그대로 표시한다. */
std::string FrequencyInput(const Json& value)
{
    const auto original = InputFormat(value);
    const double hz = value.get<double>();
    const auto scale = StudioFrequency::ForRange(hz, hz);
    const auto compact = StudioFrequency::WithUnit(value);
    if (scale.unit != "Hz" && hz > 0 && Frequency(compact) == hz)
    {
        return compact;
    }
    return original + " Hz";
}

/** @brief 목록의 항목과 순서를 그대로 표시한다. */
std::string List(const Json& values, std::string (*format)(const Json&))
{
    std::string output;
    for (const auto& value : values)
    {
        if (!output.empty())
        {
            output += ", ";
        }
        output += format(value);
    }
    return output;
}
}

Studio::StudyFields Studio::StudyDraft(const Json& specification)
{
    const auto& settings = specification.at("settings");
    const auto& frequency = settings.at("frequency_hz");
    StudyFields fields{{"name", specification.at("name")}, {"grids", List(specification.at("grid_levels_mm"), InputFormat)}};
    fields["adaptive_memory_limit_mib"] = specification.contains("adaptive_mesh")
        ? InputFormat(specification.at("adaptive_mesh").at("memory_limit_mib"))
        : "";
    fields["start"] = FrequencyInput(frequency.at("start"));
    fields["stop"] = FrequencyInput(frequency.at("stop"));
    fields["count"] = InputFormat(frequency.at("count"));
    for (const auto* key : {"air_padding_mm", "curve_tolerance_mm", "max_timesteps", "end_criterion"})
    {
        fields[key] = InputFormat(settings.at(key));
    }
    const auto policy = settings.value("mesh_policy", Json{{"air_cell_mm", 6}, {"growth_ratio", 1.5}});
    fields["air_cell_mm"] = InputFormat(policy.at("air_cell_mm"));
    fields["growth_ratio"] = InputFormat(policy.at("growth_ratio"));
    const auto radiation = settings.value(
        "radiation", Json{{"frequency_hz",
                           Json::array({frequency.at("start"),
                                        (frequency.at("start").get<double>() + frequency.at("stop").get<double>()) / 2,
                                        frequency.at("stop")})},
                          {"theta_step_deg", 15},
                          {"phi_step_deg", 15},
                          {"box_clearance_mm", 30}});
    fields["frequencies"] = List(radiation.at("frequency_hz"), FrequencyInput);
    for (const auto* key : {"theta_step_deg", "phi_step_deg", "box_clearance_mm"})
    {
        fields[key] = InputFormat(radiation.at(key));
    }
    fields["max_relative_residual"] =
        InputFormat(settings.value("power_balance", Json{{"max_relative_residual", 0.03}}).at("max_relative_residual"));
    fields["feature_subdivisions"] = InputFormat(settings.value("feature_subdivisions", Json(1)));
    const auto losses =
        specification.value("loss_profile", Json{{"max_relative_delta", 0.02}, {"absolute_fraction_floor", 1e-5}});
    fields["loss_max_relative_delta"] = InputFormat(losses.at("max_relative_delta"));
    fields["loss_absolute_fraction_floor"] = InputFormat(losses.at("absolute_fraction_floor"));
    for (const auto* key : {"max_s11_complex_delta", "max_resonance_relative_shift"})
    {
        fields[std::string("port_") + key] = InputFormat(specification.at("port_profile").at(key));
    }
    for (auto it = specification.at("radiation_profile").begin(); it != specification.at("radiation_profile").end();
         ++it)
    {
        if (it.key() != "id" && it.key() != "minimum_levels")
        {
            fields[it.key()] = InputFormat(it.value());
        }
    }
    return fields;
}

Json Studio::StudySpecification(const Json& basis, const StudyFields& fields, bool radiation, bool losses,
                                bool newStudy)
{
    const auto parse = [&fields](const std::string& key, auto convert)
    {
        try
        {
            return convert(fields.at(key));
        }
        catch (const std::runtime_error& error)
        {
            throw StudyFieldError(key, error.what());
        }
    };
    Json result = basis;
    result["name"] = fields.at("name");
    result["grid_levels_mm"] = parse("grids", [](const std::string& text) { return Numbers(text, Number); });
    if (result.at("grid_levels_mm").empty())
    {
        throw StudyFieldError("grids", "격자 수준을 지정하세요.");
    }
    result.erase("adaptive_mesh");
    const auto& adaptiveLimit = fields.at("adaptive_memory_limit_mib");
    if (!adaptiveLimit.empty())
    {
        result["adaptive_mesh"] = Json{{"memory_limit_mib", parse("adaptive_memory_limit_mib", Integer)}};
    }
    auto& settings = result["settings"];
    settings["grid_mm"] = result.at("grid_levels_mm").back();
    settings["frequency_hz"] = Json{{"start", parse("start", Frequency)},
                                    {"stop", parse("stop", Frequency)},
                                    {"count", parse("count", Integer)}};
    for (const auto* key : {"air_padding_mm", "curve_tolerance_mm", "end_criterion"})
    {
        settings[key] = parse(key, Number);
    }
    settings["max_timesteps"] = parse("max_timesteps", Integer);
    const int subdivisions = parse("feature_subdivisions", Integer);
    if (settings.contains("feature_subdivisions") || subdivisions != 1)
    {
        settings["feature_subdivisions"] = subdivisions;
    }
    settings["mesh_policy"] = Json{{"kind", "graded_air"},
                                   {"air_cell_mm", parse("air_cell_mm", Number)},
                                   {"growth_ratio", parse("growth_ratio", Number)}};
    settings.erase("radiation");
    settings.erase("power_balance");
    if (losses && !radiation)
    {
        throw std::runtime_error("독립 손실 적분에는 방사 기록이 필요합니다.");
    }
    if (radiation)
    {
        settings["radiation"] = Json{{"frequency_hz", parse("frequencies", [](const std::string& text) { return Numbers(text, Frequency); })},
                                     {"theta_step_deg", parse("theta_step_deg", Integer)},
                                     {"phi_step_deg", parse("phi_step_deg", Integer)},
                                     {"box_clearance_mm", parse("box_clearance_mm", Number)}};
    }
    if (losses)
    {
        settings["power_balance"] = Json{{"max_relative_residual", parse("max_relative_residual", Number)}};
    }
    const double relative = parse("loss_max_relative_delta", Number);
    const double floor = parse("loss_absolute_fraction_floor", Number);
    if (result.contains("loss_profile") || relative != 0.02 || floor != 1e-5 || (newStudy && losses))
    {
        result["loss_profile"] =
            result.value("loss_profile", Json{{"id", "independent-loss-initial/0.1"}, {"minimum_levels", 3}});
        result["loss_profile"]["max_relative_delta"] = relative;
        result["loss_profile"]["absolute_fraction_floor"] = floor;
    }
    for (const auto* key : {"max_s11_complex_delta", "max_resonance_relative_shift"})
    {
        result["port_profile"][key] = parse(std::string("port_") + key, Number);
    }
    for (auto it = result["radiation_profile"].begin(); it != result["radiation_profile"].end(); ++it)
    {
        if (it.key() != "id" && it.key() != "minimum_levels")
        {
            it.value() = parse(it.key(), Number);
        }
    }
    return result;
}

std::string Studio::StudyStatus(const std::string& state)
{
    static const std::map<std::string, std::string> labels{{"round_limit", "지정 반복 횟수 소진"},
                                                    {"rule_limit", "국부 규칙 상한 도달"},
                                                    {"solver_resource_limit", "기록 또는 격자 상한 도달"},
                                                    {"no_eligible_change", "선택 영역에 세분화 대상 없음"},
                                                    {"unchanged_mesh", "국부 격자 증가 없음"},
                                                    {"ready", "실행 전"},
                                                    {"running", "실행 중"},
                                                    {"resuming", "재개 확인 중"},
                                                    {"cancel_requested", "종료 확인 중"},
                                                    {"cancelled", "취소됨"},
                                                    {"interrupted", "중단됨"},
                                                    {"blocked", "진행 차단"},
                                                    {"completed", "계산 완료"},
                                                    {"failed", "실패"},
                                                    {"prepare", "준비"},
                                                    {"solve", "해석"},
                                                    {"done", "완료"},
                                                    {"skipped", "미실행"},
                                                    {"stability_reached", "격자 안정성 기준 충족"},
                                                    {"memory_limit", "예상 메모리 상한"},
                                                    {"levels_exhausted", "격자 수준 소진"},
                                                    {"passed", "초기 기준 충족"},
                                                    {"established", "초기 기준 충족"},
                                                    {"not_established", "미확립"},
                                                    {"not_evaluated", "미평가"},
                                                    {"within_initial_numerical_budget", "초기 수지 기준 충족"},
                                                    {"requires_review", "검토 필요"}};
    const auto found = labels.find(state);
    return found == labels.end() ? state : found->second;
}

bool Studio::StudyActionAllowed(const Json& view, const std::string& action, bool pending)
{
    if (pending || view.empty())
    {
        return false;
    }
    const std::string state = view.at("state");
    if (action == "cancel")
    {
        return state == "running" || state == "resuming";
    }
    if (!view.value("runtime_matches", false))
    {
        return false;
    }
    if (action == "start")
    {
        return state == "ready";
    }
    return action == "resume" &&
           (state == "cancelled" || state == "interrupted" || state == "failed" || state == "blocked");
}

std::string Studio::StudySummary(const Json& view)
{
    std::ostringstream output;
    output << "연구: " << view.at("name").get<std::string>() << " / " << StudyStatus(view.at("state")) << '\n'
           << (view.value("source_revision_matches_current", false) ? "현재 설계와 동일한 개정"
                                                                    : "이전 개정의 고정 결과")
           << '\n'
           << view.value("message", std::string()) << "\n\n전력 단위: W*s^2 / 절대 W 값 미정\n";
    if (!view.value("runtime_matches", false))
    {
        output
            << "현재 해석 환경이 미연결이거나 원래 worker와 다릅니다. 결과 조회만 가능하며 실행/재개는 차단합니다.\n";
    }
    if (view.contains("specification") && view.at("specification").contains("field_adaptive"))
    {
        const auto& config = view.at("specification").at("field_adaptive");
        const auto& region = config.at("physical_region");
        output << "기록 전계 E" << region.at("component").get<std::string>() << " / " << Format(region.at("frequency_hz"))
               << " Hz / " << region.at("normal_axis").get<std::string>() << " = " << Format(region.at("plane_mm"))
               << " mm / 복소 S11 허용차 " << Format(config.at("limits").at("max_s11_complex_delta")) << '\n';
    }
    for (const auto& row : view.at("cases"))
    {
        output << "\n격자 " << Format(row.at("grid_mm")) << " mm / " << StudyStatus(row.at("phase")) << '\n';
        if (row.contains("refinement"))
        {
            output << "직전 기록 전계에서 추가한 국부 규칙 " << row.at("refinement").at("rules_added") << "개\n";
        }
        if (row.contains("sample_evidence"))
        {
            const auto& pair = row.at("sample_evidence");
            output << "공통 주파수 " << pair.at("sample_count") << "개 / 최대 복소 S11 변화 " << Format(pair.at("max_s11_complex_delta"))
                   << " (" << Format(pair.at("worst_frequency_hz")) << " Hz)\n";
        }
        if (row.contains("estimated_memory_bytes"))
        {
            output << "예상 메모리 " << Format(row.at("estimated_memory_bytes").get<double>() / (1024 * 1024))
                   << " MiB\n";
        }
        if (row.at("power_balance").is_null())
        {
            output << "독립 손실 수지: 미평가 또는 계산 전\n";
            continue;
        }
        for (const auto& power : row.at("power_balance").at("frequencies"))
        {
            output << Format(power.at("frequency_hz")) << " Hz: " << StudyStatus(power.at("status")) << '\n';
            for (const auto& entry :
                 std::vector<std::pair<std::string, std::string>>{{"입사", "incident_power_w_s2"},
                                                                  {"반사", "reflected_power_w_s2"},
                                                                  {"수용", "accepted_power_w_s2"},
                                                                  {"방사", "radiated_power_w_s2"},
                                                                  {"유전체", "dielectric_loss_w_s2"},
                                                                  {"도체", "conductor_loss_w_s2"},
                                                                  {"부호 있는 잔차", "residual_w_s2"}})
            {
                output << "  " << entry.first << ": " << Format(power.at(entry.second)) << '\n';
            }
            output << "  상대 잔차: " << Format(power.at("relative_residual")) << '\n';
            if (power.contains("via_loss_w_s2"))
            {
                output << "  평면 도체: " << Format(power.at("sheet_loss_w_s2"))
                       << " / PTH 비아: " << Format(power.at("via_loss_w_s2")) << '\n';
            }
        }
    }
    if (!view.at("assessment").is_null())
    {
        const auto& value = view.at("assessment");
        const bool fieldStudy = value.value("schema", std::string()) == "rfad.field-study-assessment/0.1";
        output << (fieldStudy ? "\n선택 급전의 공통 주파수 복소 S11 변화: " : "\n포트 격자 안정성: ")
               << StudyStatus(value.at("port_stability"))
               << "\n방사 격자 안정성: " << StudyStatus(value.at("radiation_mesh_stability"))
               << "\n기준 전력 수지: " << StudyStatus(value.at("reference_energy_closure")) << '\n';
        if (value.contains("adaptive_mesh_decision"))
        {
            const auto& decision = value.at("adaptive_mesh_decision");
            output << "적응 격자 종료 사유 " << StudyStatus(decision.at("reason"))
                   << " / 실행 수준 " << decision.at("completed_levels") << '\n';
        }
        if (value.contains("individual_loss_stability") && !value.at("individual_loss_stability").is_null())
        {
            output << "개별 유전체 / 도체 / 비아 손실 안정성: "
                   << StudyStatus(value.at("individual_loss_stability").at("status")) << '\n';
        }
        if (!value.at("reference_radiation_budget").is_null())
        {
            output << "기준 방사 전력 예산: " << StudyStatus(value.at("reference_radiation_budget").at("status"))
                   << '\n';
        }
    }
    output << "\n격자 한 축의 설정 안정성입니다. 전체 세 축 수렴, skin depth 및 연속체 정확도는 별도입니다.\n"
              "실제 납품 물성, 제작/측정 조건은 미정이며 실물 성능 합격이 아닙니다.";
    return output.str();
}
