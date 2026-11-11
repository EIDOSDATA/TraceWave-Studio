/** @file @brief 방사 결과 페이지가 혼합되거나 부분 결과로 표시되지 않는지 검사한다. */
#include "radiation_pattern.h"
#include <cstdlib>
#include <iostream>
#include <limits>

namespace
{
void Check(bool condition)
{
    if (!condition)
    {
        std::cerr << "radiation page contract failed\n";
        std::exit(1);
    }
}

template <class Action> void Reject(Action action)
{
    try
    {
        action();
    }
    catch (const std::exception&)
    {
        return;
    }
    Check(false);
}

Json Page(int offset, int count)
{
    Json theta = Json::array(), phi = Json::array(), matrix = Json::array();
    for (int index = 0; index < 12; ++index)
    {
        phi.push_back(30 * index);
    }
    for (int index = offset; index < offset + count; ++index)
    {
        theta.push_back(30 * index);
        matrix.push_back(Json::array({1.0, 0.5, 0.25, 0.1, 0.0, 0.1, 0.25, 0.5, 1.0, 0.5, 0.25, 0.1}));
    }
    return {{"profile", "rfad.radiation-chart/0.1"}, {"artifact_id", "fixture"}, {"frequency_index", 0},
            {"frequency_hz", Json::array({2.4e9})}, {"theta_offset", offset}, {"returned_count", count},
            {"theta_count", 7}, {"next_offset", offset + count == 7 ? Json(nullptr) : Json(offset + count)},
            {"theta_deg", theta}, {"phi_deg", phi}, {"normalized_power", matrix}, {"directivity", matrix},
            {"physics_validated", false}, {"absolute_power_w", nullptr}, {"radius_m", 1.0},
            {"center_m", Json::array({0, 0, 0})}, {"snapshot", {{"revision_id", "source"}}},
            {"metrics", {{"directivity_dbi", 1.5}, {"gain_dbi", 1.2}, {"realized_gain_dbi", -1.0}, {"radiation_efficiency", 0.9}}}};
}
}

int main()
{
    Studio::RadiationPattern pattern;
    const Json first = Page(0, 5), last = Page(5, 2);
    pattern.Append(first, "fixture", 0);
    Check(!pattern.Complete());
    Reject([&]()
    {
        pattern.Append(first, "fixture", 0);
    });
    auto changed = last;
    changed["snapshot"]["revision_id"] = "changed";
    Reject([&]()
    {
        pattern.Append(changed, "fixture", 0);
    });
    pattern.Append(last, "fixture", 0);
    Check(pattern.Complete() && pattern.Data().at("theta_deg").size() == 7);
    Reject([&]()
    {
        pattern.Append(last, "fixture", 0);
    });
    for (int mode = 0; mode < 8; ++mode)
    {
        pattern.Reset();
        changed = first;
        if (mode == 0)
        {
            changed["artifact_id"] = "foreign";
        }
        else if (mode == 1)
        {
            changed["frequency_index"] = 1;
        }
        else if (mode == 2)
        {
            changed["normalized_power"][0][0] = -1;
        }
        else if (mode == 3)
        {
            changed["theta_deg"][1] = 1e300;
        }
        else if (mode == 4)
        {
            changed["metrics"]["gain_dbi"] = std::numeric_limits<double>::quiet_NaN();
        }
        else if (mode == 5)
        {
            changed["physics_validated"] = true;
        }
        else if (mode == 6)
        {
            changed["next_offset"] = 6;
        }
        else
        {
            changed["normalized_power"][0].push_back(1);
        }
        Reject([&]()
        {
            pattern.Append(changed, "fixture", 0);
        });
        Check(pattern.Data().empty());
    }
    return 0;
}
