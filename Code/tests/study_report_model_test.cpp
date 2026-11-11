/** @file @brief 두 종류의 수렴 보고서 표와 미평가 항목 표시를 확인한다. */
#include "study_report_model.h"
#include <cstdlib>
#include <iostream>

namespace
{
void Check(bool value)
{
    if (!value)
    {
        std::cerr << "study report presentation failed\n";
        std::exit(1);
    }
}
}

int main()
{
    const Json settings{{"grid_mm", 0.4}, {"air_padding_mm", 90}, {"end_criterion", 1e-5},
                        {"frequency_hz", {{"start", 2.4e9}, {"stop", 2.4835e9}, {"count", 201}}},
                        {"radiation", {{"box_clearance_mm", 30}, {"theta_step_deg", 5}, {"phi_step_deg", 5}, {"frequency_hz", Json::array({2.4e9, 2.4835e9})}}}};
    Json axes = Json::object();
    for (const auto* axis : {"mesh", "boundary", "termination"})
    {
        axes[axis] = {{"status", "not_established"}};
    }
    Json report{{"schema", "rfad.ifa-convergence-run/0.1"}, {"status", "completed"},
                {"cases", Json::array({{{"label", "case"}, {"axis", "mesh"}, {"settings", settings}}})},
                {"assessment", {{"numerical_stability", {{"status", "not_established"}, {"axes", axes}}}}}};
    const auto old = Studio::PresentStudyReport(report);
    Check(old.rows.size() == 1 && old.rows.front().size() == 6);
    Check(old.summary.find("공진") != std::string::npos);
    const Json frequency{{"frequency_hz", 2.4e9}, {"metrics", {{"pattern_max_delta", 0.01}, {"radiated_relative_delta", 0.01},
                         {"directivity_delta_db", 0.02}, {"gain_delta_db", 0.03}, {"efficiency_delta", 0.001}}}};
    const Json comparison{{"max_s11_complex_delta", 0.001}, {"frequencies", Json::array({frequency})}};
    axes = Json::object();
    for (const auto* axis : {"mesh", "box", "angle"})
    {
        axes[axis] = {{"status", "not_established"}, {"comparisons", Json::array({comparison})}};
    }
    report["schema"] = "rfad.pcb-radiation-study-run/0.1";
    report["assessment"]["numerical_stability"]["axes"] = axes;
    report["assessment"]["acceptance_profile"] = {{"max_pattern_delta", 0.02}, {"max_radiated_relative_delta", 0.02},
                                                  {"max_directivity_delta_db", 0.1}, {"max_gain_delta_db", 0.1}};
    report["assessment"]["power_balance"] = {{"status", "failed"}, {"reference_case", "case"},
        {"cases", Json::array({{{"label", "case"}, {"frequencies", Json::array({{{"frequency_hz", 2.4e9},
             {"sphere_relative_error", 0.04}, {"port_wave_relative_residual", 1e-15}, {"passivity_excess_fraction", 0.0}}})}}})}};
    const auto radiation = Studio::PresentStudyReport(report);
    Check(radiation.columns.at(3).find("기록") != std::string::npos);
    Check(radiation.summary.find("전체 에너지 수지") != std::string::npos);
    Check(radiation.summary.find("미평가") != std::string::npos);
    Check(radiation.summary.find("미충족") != std::string::npos);
    report["status"] = "running";
    try
    {
        Studio::PresentStudyReport(report);
    }
    catch (const std::exception&)
    {
        return 0;
    }
    Check(false);
    return 1;
}
