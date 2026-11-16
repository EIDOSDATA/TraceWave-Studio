/** @file @brief 방사 페이지의 출처/각도/정규화 경계와 결과 표시의 원본 보존을 검사한다. */
#include "result_radiation_data.h"
#include "result_radiation_plane.h"
#include "result_presentation.h"
#include "rf_validation_model.h"
#include <iostream>
#include <limits>
#include <functional>
namespace
{
void Check(bool value, const std::string& message)
{
    if (!value)
    {
        throw std::runtime_error(message);
    }
}
void Rejected(const std::function<void()>& operation)
{
    bool rejected = false;
    try
    {
        operation();
    }
    catch (const std::exception&)
    {
        rejected = true;
    }
    Check(rejected, "잘못된 방사 페이지를 수용했습니다.");
}
Json Description()
{
    return {{"source", {{"kind", "solver"}, {"artifact_id", "sealed-original"}}},
            {"pin", {{"identity_hash", "identity"}, {"dataset_sha256", "dataset"}}}};
}
Json Options()
{
    return {{"frequency_index", 0},
            {"observable", "total"},
            {"display_scale", "linear_amplitude"},
            {"floor_db", -40},
            {"polarization_basis", "theta_phi"}};
}
Json Page(int offset, int count)
{
    Json page = Description();
    page.update(Options());
    page.update({{"profile", "rfad.result-radiation/0.1"},
                 {"physics_validated", false},
                 {"absolute_power_w", nullptr},
                 {"theta_count", 7},
                 {"theta_offset", offset},
                 {"returned_count", count},
                 {"next_offset", offset + count == 7 ? Json(nullptr) : Json(offset + count)},
                 {"phi_deg", {0.0, 180.0}},
                 {"frequency_hz", {1e9}},
                 {"color_range", {0.0, 1.0}},
                 {"color_unit", "1"},
                 {"normalization_peak_v_s_per_m", 1.0},
                 {"coordinate_unit", "dimensionless_display"}});
    for (const std::string key :
         {"theta_deg", "e_theta", "e_phi", "normalized_power", "directivity", "polarization", "projection"})
    {
        page[key] = Json::array();
    }
    for (int row = offset; row < offset + count; ++row)
    {
        page["theta_deg"].push_back(row * 30.0);
        for (const std::string key : {"e_theta", "e_phi"})
        {
            page[key].push_back({{1.0, 0.0}, {1.0, 0.0}});
        }
        page["normalized_power"].push_back({1.0, 1.0});
        page["directivity"].push_back({1.0, 1.0});
        const Json polar{{"rhcp_ri", {0.0, 1.0}},
                         {"lhcp_ri", {0.0, 1.0}},
                         {"relative_phase_deg", nullptr},
                         {"axial_ratio_db", nullptr},
                         {"axial_ratio_state", "infinite_linear"}};
        page["polarization"].push_back({polar, polar});
        const Json point{{"xyz", {0.0, 0.0, 1.0}}, {"radius", 1.0}, {"color", 1.0}};
        page["projection"].push_back({point, point});
    }
    return page;
}
}
int main()
{
    try
    {
        const Json validation{
            {"manufacturing", nullptr},
            {"measurement", nullptr},
            {"validation_states",
             {{"mesh", {{"state", "observed_not_established"}, {"reason", "세 격자의 변화 관측만"}}}}},
            {"cases",
             {{{"name", "급전 계약 미정"},
               {"source", nullptr},
               {"pin", nullptr},
               {"execution_state", "blocked_before_execution"},
               {"blocked_reason", "finite_feed_cross_section_and_terminal_contract_unresolved"}}}},
            {"rows",
             {{{"case_name", "다이폴"},
               {"label", "참조 오차"},
               {"frequency_hz", 2.4e9},
               {"expected", 1.6409},
               {"actual", nullptr},
               {"error", nullptr},
               {"tolerance", 0.1},
               {"state", "not_evaluated"},
               {"reason", "실제 계산 미수행"}}}}};
        const auto validationBefore = validation;
        const auto axes = RfValidationUi::States(validation);
        const auto values = RfValidationUi::Metrics(validation);
        Check(axes.size() == 6 && axes[4][0] == "제작" && axes[5][0] == "실측", "6개의 검증 축을 구분하지 못했습니다.");
        Check(axes[0][1].find("미확립") != std::string::npos, "격자 변화 관측을 합격으로 표시했습니다.");
        Check(values[0][2] == "2.4 GHz" && values[0][4] == "미정" && values[0][5] == "미정",
              "미실행 판정에 값을 채우거나 주파수 단위를 누락했습니다.");
        Check(!RfValidationUi::HasSource(validation["cases"][0]) &&
                  RfValidationUi::Cases(validation)[0][5].find("계약 미확정") != std::string::npos,
              "차단 사례에 관련 결과를 생성했습니다.");
        Check(RfValidationUi::Resources({{"wall_seconds", {{"value", 4500}, {"unit", "s"}, {"text", "75 min"}}}}) ==
                  "시간: 75 min\n",
              "서비스의 표시 단위에 원문 단위를 중복 부착했습니다.");
        Check(RfValidationUi::Resources({{"native_solves", {{"value", 9}, {"unit", "count"}, {"text", "9"}}}}) ==
                  "계산 횟수: 9\n",
              "예산 상한을 실제 계산 완료 횟수로 표시했습니다.");
        const Json notBlocked{{"cases", {{{"blocked_reason", nullptr}}}}};
        Check(RfValidationUi::Cases(notBlocked)[0][5] == "차단 없음" && RfValidationUi::Reason(nullptr) == "미정",
              "사례의 차단 없음과 일반 미정 사유를 혼동했습니다.");
        Json planRecord{{"report_id", nullptr},
                        {"cases",
                         {{{"blocked_reason", nullptr},
                           {"source", nullptr},
                           {"pin", nullptr},
                           {"execution_state", "postprocessed"}}}}};
        Check(RfValidationUi::Cases(planRecord)[0][4] == "판정 선택 필요",
              "계획 조회의 미선택 판정을 결과 미기록으로 표시했습니다.");
        planRecord["report_id"] = "stored-report";
        Check(RfValidationUi::Cases(planRecord)[0][4] == "결과 미기록",
              "보존 판정의 없는 결과를 판정 미선택으로 표시했습니다.");
        Check(RfValidationUi::Cases(validation)[0][4] == "결과 미기록", "실행 전 차단 사례의 결과 상태를 바꿨습니다.");
        const Json blockedMetric{
            {"rows", {{{"reason", "finite_feed_cross_section_and_terminal_contract_unresolved"}}}}};
        Check(RfValidationUi::Metrics(blockedMetric)[0][9] == "유한 급전 단면과 단자 계약 미확정",
              "기록 지표에 차단 코드 원문을 기본 표시했습니다.");
        Check(RfValidationUi::Time(nullptr) == "시각 미기록" && RfValidationUi::Time(0) == "1970-01-01 00:00:00 UTC",
              "없는 시각을 임의로 생성했습니다.");
        Check(RfValidationUi::Criteria({{"dipole", {{"maximum_pattern_error", 0.15}}}}).find("0.15 (비율)") !=
                  std::string::npos,
              "사전 기준의 저장값을 보존하지 못했습니다.");
        Check(validation == validationBefore, "읽기 전용 표시가 판정 원본을 변경했습니다.");
        const auto description = Description(), options = Options();
        const auto first = Page(0, 2), second = Page(2, 3), last = Page(5, 2);
        const auto original = Json::array({first, second, last});
        ResultRadiationData pattern;
        pattern.Append(first, description, options);
        Check(pattern.Next() == 2 && !pattern.Complete(), "첫 페이지 경계가 다릅니다.");
        pattern.Append(second, description, options);
        Check(pattern.Next() == 5, "고정 5행이 아닌 실제 반환 행을 사용해야 합니다.");
        pattern.Append(last, description, options);
        Check(pattern.Complete() && pattern.Data().at("theta_deg").size() == 7,
              "실제 각도 행을 모두 결합하지 못했습니다.");
        Check(original == Json::array({first, second, last}), "읽기 결합이 원문 페이지를 변경했습니다.");
        auto planeData = pattern.Data();
        for (auto& row : planeData["projection"])
        {
            row[1]["radius"] = 0.25;
        }
        const auto planeOriginal = planeData;
        const auto plane = RadiationPlaneCut::Build(planeData, 0);
        Check(plane.oppositePhi == 1 && plane.primary.size() == 7 && plane.opposite.size() == 7 &&
                  std::abs(plane.primary[3].x - 1.0) < 1e-12 && std::abs(plane.opposite[3].x + 0.25) < 1e-12 &&
                  plane.primary[3].phiIndex == 0 && plane.opposite[3].phiIndex == 1,
              "반대편 실제 표본 대신 선택 반경을 미러했습니다.");
        Check(planeData == planeOriginal, "평면 표시가 원문 방사 표본을 변경했습니다.");
        planeData["phi_deg"] = {0.0, 179.999999};
        const auto missing = RadiationPlaneCut::Build(planeData, 0);
        Check(missing.oppositePhi == -1 && missing.opposite.empty() && missing.primary.size() == 7,
              "정확한 반대 방위각이 없는데 가까운 표본 또는 미러를 생성했습니다.");
        planeData["phi_deg"] = {175.0, 355.0};
        const auto wrapped = RadiationPlaneCut::Build(planeData, 1);
        Check(wrapped.oppositePhi == 0 && std::abs(wrapped.primary[3].x - 0.25) < 1e-12 &&
                  std::abs(wrapped.opposite[3].x + 1.0) < 1e-12,
              "360도 경계를 넘는 실제 반대 방위각 선택이 다릅니다.");
        Rejected(
            [&]()
            {
                pattern.Append(last, description, options);
            });
        for (int fault = 0; fault < 8; ++fault)
        {
            ResultRadiationData invalid;
            invalid.Append(first, description, options);
            auto bad = second;
            if (fault == 0)
            {
                bad["pin"]["dataset_sha256"] = "other";
            }
            if (fault == 1)
            {
                bad["theta_offset"] = 3;
            }
            if (fault == 2)
            {
                bad["color_range"] = {-40.0, 0.0};
            }
            if (fault == 3)
            {
                bad["projection"][0][0]["xyz"][1] = std::numeric_limits<double>::infinity();
            }
            if (fault == 4)
            {
                bad["physics_validated"] = true;
            }
            if (fault == 5)
            {
                bad["e_phi"][0] = Json::array();
            }
            if (fault == 6)
            {
                bad["e_theta"][0][0][0] = nullptr;
            }
            if (fault == 7)
            {
                bad["polarization"][0][0]["rhcp_ri"] = {1.0};
            }
            Rejected(
                [&]()
                {
                    invalid.Append(bad, description, options);
                });
            Check(invalid.Next() == 2, "거절된 페이지가 이전 결합 범위를 변경했습니다.");
        }
        Check(ResultUi::SampleValue({{"magnitude_db", nullptr}, {"magnitude_db_state", "negative_infinity"}},
                                    "magnitude_db") == "-inf (크기 0)",
              "완전 정합 표본을 미정으로 표시했습니다.");
        Check(ResultUi::State("infinite_linear").find("선형") != std::string::npos, "무한 축비를 누락했습니다.");
        auto other = description;
        other["source"]["artifact_id"] = "other-original";
        Check(!ResultUi::Matches(other, description), "같은 해시의 다른 원본을 같은 선택으로 취급했습니다.");
        std::cout << "result view model checks passed\n";
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << "\n";
        return 1;
    }
}
