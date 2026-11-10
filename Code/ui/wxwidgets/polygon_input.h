#pragma once

#include <nlohmann/json.hpp>
#include <algorithm>
#include <cmath>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <string>

/** @brief mm 좌표의 외곽/구멍을 빈 줄로 분리하고 기하 검증은 서비스에 맡긴다. */
inline nlohmann::json ParsePolygonInput(const std::string& text)
{
    using Json = nlohmann::json;
    if (text.size() > 16384)
    {
        throw std::runtime_error("다각형 좌표 입력이 16 KiB를 초과했습니다.");
    }
    std::istringstream lines(text);
    Json rings = Json::array();
    Json ring = Json::array();
    std::string line;
    std::size_t vertices = 0;
    auto finish = [&]()
    {
        if (!ring.empty())
        {
            if (ring.size() < 3)
            {
                throw std::runtime_error("각 외곽/구멍에는 점 세 개 이상이 필요합니다.");
            }
            rings.push_back(ring);
            ring = Json::array();
        }
    };
    while (std::getline(lines, line))
    {
        if (line.find_first_not_of(" \t\r") == std::string::npos)
        {
            finish();
            continue;
        }
        std::replace(line.begin(), line.end(), ',', ' ');
        std::istringstream row(line);
        row.imbue(std::locale::classic());
        double x = 0, y = 0;
        std::string extra;
        if (!(row >> x >> y) || (row >> extra) || !std::isfinite(x) || !std::isfinite(y))
        {
            throw std::runtime_error("한 줄에 유한한 x, y 좌표 두 개를 입력하세요. 소수점은 . 입니다.");
        }
        if (++vertices > 64)
        {
            throw std::runtime_error("외곽과 구멍을 합해 최대 64점을 입력할 수 있습니다.");
        }
        ring.push_back(Json::array({x, y}));
    }
    finish();
    if (rings.empty() || rings.size() > 9)
    {
        throw std::runtime_error("외곽 한 개와 최대 여덟 개의 구멍을 입력하세요.");
    }
    Json result{{"outer", rings.front()}, {"holes", Json::array()}};
    for (std::size_t index = 1; index < rings.size(); ++index)
    {
        result["holes"].push_back(rings[index]);
    }
    return result;
}
