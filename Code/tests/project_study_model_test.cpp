/** @file @brief 연구 화면의 숫자 왕복, 명시적 실행 정책과 음수 잔차 표시를 검사한다. */
#include "project_study_model.h"
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace
{
/** @brief 잘못된 표시/정책은 시험 실패로 기록한다. */
void Check(bool condition, const std::string& message)
{
    if (!condition)
    {
        throw std::runtime_error(message);
    }
}
}

int main(int argc, char** argv)
{
    try
    {
        Check(argc == 3, "two fixture paths required");
        std::ifstream powerFile(argv[1]), radiationFile(argv[2]);
        const Json power = Json::parse(powerFile), radiation = Json::parse(radiationFile);
        Json specification{{"name", "원본 보존 연구"},
                           {"grid_levels_mm", power.at("grid_levels_mm")},
                           {"settings", power.at("settings")},
                           {"radiation_profile", radiation.at("acceptance_profile")},
                           {"port_profile", Json{{"id", "test"},
                                                 {"minimum_levels", 3},
                                                 {"max_s11_complex_delta", 0.02},
                                                 {"max_resonance_relative_shift", 0.01}}}};
        specification["settings"]["curve_tolerance_mm"] = 0.012345678901234;
        auto fields = Studio::StudyDraft(specification);
        Check(Studio::StudySpecification(specification, fields, true, true) == specification,
              "draft lost source numeric precision");
        const Json copied = Studio::StudySpecification(specification, fields, true, true, true);
        Check(copied.contains("loss_profile") && copied.at("loss_profile").at("max_relative_delta") == 0.02,
              "new study copy missed explicit loss criterion");
        Check(!specification.contains("loss_profile"), "historical study modified by new criterion");
        Json extended = specification;
        extended["settings"]["feature_subdivisions"] = 3;
        extended["loss_profile"] = Json{{"id", "loss-test"},
                                        {"minimum_levels", 3},
                                        {"max_relative_delta", 0.02},
                                        {"absolute_fraction_floor", 1e-5}};
        Check(Studio::StudySpecification(extended, Studio::StudyDraft(extended), true, true) == extended,
              "loss precision conditions changed");
        for (const auto* invalid : {"NaN", "1 trailing", "", "inf"})
        {
            auto wrong = fields;
            wrong["start"] = invalid;
            bool rejected = false;
            try
            {
                Studio::StudySpecification(specification, wrong, true, true);
            }
            catch (const std::exception&)
            {
                rejected = true;
            }
            Check(rejected, "invalid numeric field accepted");
        }
        auto wrong = fields;
        wrong["count"] = "3.5";
        bool rejected = false;
        try
        {
            Studio::StudySpecification(specification, wrong, true, true);
        }
        catch (const std::exception&)
        {
            rejected = true;
        }
        Check(rejected, "fractional integer accepted");
        Json view{{"state", "ready"}, {"runtime_matches", true}};
        Check(Studio::StudyActionAllowed(view, "start", false), "ready start disabled");
        Check(!Studio::StudyActionAllowed(view, "resume", false), "ready resume enabled");
        view["state"] = "interrupted";
        Check(Studio::StudyActionAllowed(view, "resume", false), "explicit resume disabled");
        Check(!Studio::StudyActionAllowed(view, "resume", true), "duplicate mutation enabled");
        view["runtime_matches"] = false;
        Check(!Studio::StudyActionAllowed(view, "resume", false), "changed runtime resumed");
        Json row{{"frequency_hz", 2.4e9}, {"status", "requires_review"}, {"relative_residual", -0.01}};
        for (const auto* key : {"incident_power_w_s2", "reflected_power_w_s2", "accepted_power_w_s2",
                                "radiated_power_w_s2", "dielectric_loss_w_s2", "conductor_loss_w_s2"})
        {
            row[key] = 1e-24;
        }
        row["residual_w_s2"] = -1e-26;
        row["sheet_loss_w_s2"] = 9e-25;
        row["via_loss_w_s2"] = 1e-25;
        view.update(Json{{"name", "검증"},
                         {"source_revision_matches_current", false},
                         {"assessment", nullptr},
                         {"cases", Json::array({Json{{"grid_mm", 0.4},
                                                     {"phase", "done"},
                                                     {"power_balance", Json{{"frequencies", Json::array({row})}}}}})}});
        const auto text = Studio::StudySummary(view);
        Check(text.find("W*s^2") != std::string::npos && text.find("-1e-26") != std::string::npos,
              "power unit or signed residual lost");
        Check(text.find("이전 개정") != std::string::npos && text.find("실제 납품 물성") != std::string::npos,
              "source/unknown status missing");
        Check(text.find("PTH 비아") != std::string::npos && text.find("1e-25") != std::string::npos,
              "independent barrel power missing");
        std::cout << "Project study presentation checks passed\n";
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
