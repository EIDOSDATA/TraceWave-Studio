/** @file @brief 수렴 판정은 그대로 보존하고 화면용 문자열만 조립한다. */
#include "study_report_model.h"
#include <sstream>
#include <iomanip>
#include <cmath>
#include <stdexcept>

namespace
{
std::string Status(const std::string& value)
{
    if (value == "established" || value == "passed")
    {
        return "충족";
    }
    return value == "failed" ? "미충족" : "미확립";
}

std::string Axis(const std::string& value)
{
    if (value == "mesh")
    {
        return "격자";
    }
    if (value == "box")
    {
        return "기록 상자 거리";
    }
    if (value == "angle")
    {
        return "각도 간격";
    }
    return value == "boundary" ? "경계 거리" : "시간 종료";
}

/** @brief 원시 JSON 정밀도는 보존하고 화면 숫자는 유효 숫자 5개로 표시한다. */
std::string Number(const Json& value)
{
    if (!value.is_number() || !std::isfinite(value.get<double>()))
    {
        throw std::runtime_error("보고서 표시 숫자가 유한하지 않습니다.");
    }
    std::ostringstream text;
    text << std::setprecision(5) << value.get<double>();
    return text.str();
}

/** @brief 포트 수렴의 기존 표본/공진 판정 설명을 보존한다. */
std::string PortSummary(const Json& assessment)
{
    const auto& stability = assessment.at("numerical_stability");
    std::ostringstream text;
    text << "전체 수치 안정성: " << Status(stability.at("status")) << "\n\n";
    for (const auto* axis : {"mesh", "boundary", "termination"})
    {
        const auto& result = stability.at("axes").at(axis);
        text << Axis(axis) << ": " << Status(result.at("status")) << '\n';
        if (result.contains("final_pair") && result.at("final_pair").is_object())
        {
            const auto& pair = result.at("final_pair");
            text << "  마지막 복소 S11 최대 변화: " << Number(pair.at("metrics").at("max_s11_complex_delta"))
                 << " (기준 " << Number(pair.at("acceptance_profile").at("max_s11_complex_delta")) << ")\n";
            text << "  공진 위치 비교: " << Status(pair.at("resonance").at("status")) << '\n';
        }
        text << '\n';
    }
    text << "공진 미확립은 내부 공진 표본/대응 여부를 연구 결과에서 확인해야 합니다.\n"
            "전체 대역 정합과 제조/실측 정확도는 별도 검증 항목입니다.";
    return text.str();
}

/** @brief 방사 세 축의 마지막 쌍과 기준 계산의 전력 수지만 표시한다. */
std::string RadiationSummary(const Json& assessment)
{
    const auto& stability = assessment.at("numerical_stability");
    const auto& profile = assessment.at("acceptance_profile");
    std::ostringstream text;
    text << "방사 수치 안정성: " << Status(stability.at("status")) << '\n';
    text << "초기 기준: 패턴 " << Number(profile.at("max_pattern_delta")) << ", Prad 상대 변화 "
         << Number(profile.at("max_radiated_relative_delta")) << ", 지향성 " << Number(profile.at("max_directivity_delta_db"))
         << " dB, 이득 " << Number(profile.at("max_gain_delta_db")) << " dB\n\n";
    for (const auto* axis : {"mesh", "box", "angle"})
    {
        const auto& result = stability.at("axes").at(axis);
        const auto& pair = result.at("comparisons").back();
        text << Axis(axis) << ": " << Status(result.at("status")) << " / 마지막 인접 쌍\n";
        for (const auto& frequency : pair.at("frequencies"))
        {
            const auto& metrics = frequency.at("metrics");
            text << "  " << frequency.at("frequency_hz").get<double>() / 1e9 << " GHz: 패턴 "
                 << Number(metrics.at("pattern_max_delta")) << ", Prad " << Number(metrics.at("radiated_relative_delta"))
                 << ", D " << Number(metrics.at("directivity_delta_db")) << " dB, G " << Number(metrics.at("gain_delta_db"))
                 << " dB, 효율 변화 " << Number(metrics.at("efficiency_delta")) << '\n';
        }
        text << "  복소 S11 최대 변화: " << Number(pair.at("max_s11_complex_delta")) << " / 공통 각도 노드만 비교\n\n";
    }
    const auto& power = assessment.at("power_balance");
    text << "기준 계산 전력 예산: " << Status(power.at("status")) << '\n';
    for (const auto& entry : power.at("cases"))
    {
        if (entry.at("label") != power.at("reference_case"))
        {
            continue;
        }
        for (const auto& row : entry.at("frequencies"))
        {
            text << "  " << row.at("frequency_hz").get<double>() / 1e9 << " GHz: 구면 적분 오차 "
                 << Number(row.at("sphere_relative_error")) << ", 포트 수지 잔차 " << Number(row.at("port_wave_relative_residual"))
                 << ", 수동성 초과 " << Number(row.at("passivity_excess_fraction")) << '\n';
        }
    }
    text << "\n전력 단위: W*s^2 / 절대 출력 전력 미정\n"
            "전체 에너지 수지와 독립 체적/도체 흡수 손실 적분은 미평가입니다.\n"
            "실제 납품 물성, 제작 및 측정 조건은 미정이며 실물 안테나 성능 합격이 아닙니다.";
    return text.str();
}
}

Studio::StudyReportView Studio::PresentStudyReport(const Json& report)
{
    const bool radiation = report.at("schema") == "rfad.pcb-radiation-study-run/0.1";
    if ((!radiation && report.at("schema") != "rfad.ifa-convergence-run/0.1") || report.at("status") != "completed" ||
        !report.at("cases").is_array() || report.at("cases").empty() || report.at("cases").size() > 18)
    {
        throw std::runtime_error("완료된 수렴 연구 보고서가 필요합니다.");
    }
    StudyReportView result;
    result.columns = radiation ? std::vector<std::string>{"사례", "비교 축", "격자 mm", "기록 거리 mm", "theta/phi deg", "방사 주파수 GHz"}
                               : std::vector<std::string>{"사례", "비교 축", "격자 mm", "공기 여백 mm", "종료 기준", "주파수 GHz"};
    for (const auto& entry : report.at("cases"))
    {
        const auto& settings = entry.at("settings");
        std::vector<std::string> row{entry.at("label"), Axis(entry.at("axis")), settings.at("grid_mm").dump()};
        if (radiation)
        {
            const auto& fields = settings.at("radiation");
            row.push_back(fields.at("box_clearance_mm").dump());
            row.push_back(fields.at("theta_step_deg").dump() + " / " + fields.at("phi_step_deg").dump());
            std::ostringstream frequencies;
            for (const auto& frequency : fields.at("frequency_hz"))
            {
                frequencies << frequency.get<double>() / 1e9 << " ";
            }
            row.push_back(frequencies.str());
        }
        else
        {
            row.push_back(settings.at("air_padding_mm").dump());
            row.push_back(settings.at("end_criterion").dump());
            const auto& band = settings.at("frequency_hz");
            std::ostringstream frequency;
            frequency << band.at("start").get<double>() / 1e9 << " .. " << band.at("stop").get<double>() / 1e9 << " (" << band.at("count") << ")";
            row.push_back(frequency.str());
        }
        result.rows.push_back(std::move(row));
    }
    result.summary = radiation ? RadiationSummary(report.at("assessment")) : PortSummary(report.at("assessment"));
    return result;
}
