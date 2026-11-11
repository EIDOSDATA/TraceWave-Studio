/** @file @brief 연구 폼의 엄격한 숫자 변환과 읽기 전용 전력 표시를 구현한다. */
#include "project_study_model.h"
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

/** @brief 쉼표 목록의 빈 항목과 잘못된 수치를 거절한다. */
Json Numbers(const std::string& text)
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
        values.push_back(Number(part));
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

/** @brief 직접 주파수 목록을 보간/추가 없이 문자열로 보존한다. */
std::string List(const Json& values)
{
    std::string output;
    for (const auto& value : values)
    {
        if (!output.empty())
        {
            output += ", ";
        }
        output += InputFormat(value);
    }
    return output;
}
}

Studio::StudyFields Studio::StudyDraft(const Json& specification)
{
    const auto& settings = specification.at("settings");
    const auto& frequency = settings.at("frequency_hz");
    StudyFields fields{{"name", specification.at("name")}, {"grids", List(specification.at("grid_levels_mm"))}};
    for (const auto* key : {"start", "stop", "count"})
    {
        fields[key] = InputFormat(frequency.at(key));
    }
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
    fields["frequencies"] = List(radiation.at("frequency_hz"));
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
    Json result = basis;
    result["name"] = fields.at("name");
    result["grid_levels_mm"] = Numbers(fields.at("grids"));
    if (result.at("grid_levels_mm").empty())
    {
        throw std::runtime_error("격자 수준을 지정하십시오.");
    }
    auto& settings = result["settings"];
    settings["grid_mm"] = result.at("grid_levels_mm").back();
    settings["frequency_hz"] = Json{{"start", Number(fields.at("start"))},
                                    {"stop", Number(fields.at("stop"))},
                                    {"count", Integer(fields.at("count"))}};
    for (const auto* key : {"air_padding_mm", "curve_tolerance_mm", "end_criterion"})
    {
        settings[key] = Number(fields.at(key));
    }
    settings["max_timesteps"] = Integer(fields.at("max_timesteps"));
    const int subdivisions = Integer(fields.at("feature_subdivisions"));
    if (settings.contains("feature_subdivisions") || subdivisions != 1)
    {
        settings["feature_subdivisions"] = subdivisions;
    }
    settings["mesh_policy"] = Json{{"kind", "graded_air"},
                                   {"air_cell_mm", Number(fields.at("air_cell_mm"))},
                                   {"growth_ratio", Number(fields.at("growth_ratio"))}};
    settings.erase("radiation");
    settings.erase("power_balance");
    if (losses && !radiation)
    {
        throw std::runtime_error("독립 손실 적분에는 방사 기록이 필요합니다.");
    }
    if (radiation)
    {
        settings["radiation"] = Json{{"frequency_hz", Numbers(fields.at("frequencies"))},
                                     {"theta_step_deg", Integer(fields.at("theta_step_deg"))},
                                     {"phi_step_deg", Integer(fields.at("phi_step_deg"))},
                                     {"box_clearance_mm", Number(fields.at("box_clearance_mm"))}};
    }
    if (losses)
    {
        settings["power_balance"] = Json{{"max_relative_residual", Number(fields.at("max_relative_residual"))}};
    }
    const double relative = Number(fields.at("loss_max_relative_delta"));
    const double floor = Number(fields.at("loss_absolute_fraction_floor"));
    if (result.contains("loss_profile") || relative != 0.02 || floor != 1e-5 || (newStudy && losses))
    {
        result["loss_profile"] =
            result.value("loss_profile", Json{{"id", "independent-loss-initial/0.1"}, {"minimum_levels", 3}});
        result["loss_profile"]["max_relative_delta"] = relative;
        result["loss_profile"]["absolute_fraction_floor"] = floor;
    }
    for (const auto* key : {"max_s11_complex_delta", "max_resonance_relative_shift"})
    {
        result["port_profile"][key] = Number(fields.at(std::string("port_") + key));
    }
    for (auto it = result["radiation_profile"].begin(); it != result["radiation_profile"].end(); ++it)
    {
        if (it.key() != "id" && it.key() != "minimum_levels")
        {
            it.value() = Number(fields.at(it.key()));
        }
    }
    return result;
}

std::string Studio::StudyStatus(const std::string& state)
{
    const std::map<std::string, std::string> labels{{"ready", "실행 전"},
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
    for (const auto& row : view.at("cases"))
    {
        output << "\n격자 " << Format(row.at("grid_mm")) << " mm / " << StudyStatus(row.at("phase")) << '\n';
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
        output << "\n포트 격자 안정성: " << StudyStatus(value.at("port_stability"))
               << "\n방사 격자 안정성: " << StudyStatus(value.at("radiation_mesh_stability"))
               << "\n기준 전력 수지: " << StudyStatus(value.at("reference_energy_closure")) << '\n';
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
