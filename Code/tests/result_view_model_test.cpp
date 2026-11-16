/** @file @brief 방사 페이지의 출처/각도/정규화 경계와 결과 표시의 원본 보존을 검사한다. */
#include "result_radiation_data.h"
#include "result_radiation_plane.h"
#include "result_presentation.h"
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
