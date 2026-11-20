/** @file @brief 3D 표시 JSON의 큰 숫자 배열을 작은 연속 자료로 읽는다. */
#pragma once
#include <nlohmann/json.hpp>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace DisplayMesh
{
using Json = nlohmann::json;
constexpr std::size_t MaxLargeTriangles = 1000000;
constexpr std::size_t MaxLargeVertices = MaxLargeTriangles * 3;

struct Point
{
    double x = 0.0;
    double y = 0.0;
    double z = 0.0;
};

using Triangle = std::array<std::uint32_t, 3>;

/** @brief 바디의 정점과 인덱스만 JSON 노드 수에 비례하지 않는 모양으로 소유한다. */
struct Coordinates
{
    std::vector<Point> vertices;
    std::vector<Triangle> triangles;
};

inline void Require(bool condition, const char* message)
{
    if (!condition)
    {
        throw std::runtime_error(message);
    }
}

inline void CheckCancelled(const std::atomic<bool>* cancelled)
{
    if (cancelled != nullptr && cancelled->load())
    {
        throw std::runtime_error("3D 파일 읽기를 취소했습니다.");
    }
}

/** @brief 원본 double 좌표와 표시 범위를 검증한다. */
inline Point ReadPoint(const Json& value)
{
    Require(value.is_array() && value.size() == 3, "3D 정점 좌표가 올바르지 않습니다.");
    std::array<double, 3> numbers{};
    for (std::size_t index = 0; index < 3; ++index)
    {
        Require(value[index].is_number(), "3D 정점에는 숫자가 필요합니다.");
        numbers[index] = value[index].get<double>();
        Require(std::isfinite(numbers[index]) && std::abs(numbers[index]) <= 1000001.0,
                "3D 정점이 표시 범위를 벗어났습니다.");
    }
    return {numbers[0], numbers[1], numbers[2]};
}

/** @brief 표시 상한 안의 정확한 정수 인덱스 세 개를 읽는다. */
inline Triangle ReadTriangle(const Json& value)
{
    Require(value.is_array() && value.size() == 3, "3D 삼각형 인덱스가 올바르지 않습니다.");
    Triangle result{};
    for (std::size_t index = 0; index < result.size(); ++index)
    {
        Require(value[index].is_number_integer() && value[index].get<std::int64_t>() >= 0,
                "3D 삼각형 인덱스는 음수가 아닌 정수여야 합니다.");
        const auto point = value[index].get<std::uint64_t>();
        Require(point < MaxLargeVertices, "3D 삼각형이 없는 정점을 참조합니다.");
        result[index] = static_cast<std::uint32_t>(point);
    }
    return result;
}

/** @brief 파일의 본문에서 표준 구조와 좌표 순서를 유지하며 최대 한 숫자 행씩 남긴다. */
inline Json ReadPackedMesh(const std::string& bytes, std::vector<Coordinates>& arrays,
                           const std::atomic<bool>* cancelled)
{
    enum class Kind { Other, Vertices, Triangles };
    using Event = Json::parse_event_t;
    bool bodiesKey = false;
    bool inBodies = false;
    bool inBody = false;
    bool hadBodies = false;
    bool hadVertices = false;
    bool hadTriangles = false;
    bool collecting = false;
    Kind kind = Kind::Other;
    std::size_t vertices = 0;
    std::size_t triangles = 0;
    std::size_t rowValues = 0;
    return Json::parse(bytes, [&](int depth, Event event, Json& value)
    {
        CheckCancelled(cancelled);
        Require(depth <= 32, "3D 파일 중첩 깊이가 너무 큽니다.");
        if (depth == 1 && event == Event::key)
        {
            bodiesKey = value == "bodies";
            if (bodiesKey)
            {
                Require(!hadBodies, "3D body 목록이 중복되었습니다.");
                hadBodies = true;
            }
        }
        else if (depth == 1 && event == Event::array_start && bodiesKey)
        {
            inBodies = true;
        }
        else if (depth == 1 && event == Event::array_end && inBodies)
        {
            inBodies = false;
        }
        else if (depth == 2 && event == Event::object_start && inBodies)
        {
            Require(arrays.size() < 256, "3D body 수가 지원 범위를 벗어났습니다.");
            arrays.emplace_back();
            inBody = true;
            hadVertices = false;
            hadTriangles = false;
            kind = Kind::Other;
        }
        else if (depth == 2 && event == Event::object_end && inBody)
        {
            inBody = false;
        }
        else if (depth == 3 && event == Event::key && inBody)
        {
            kind = Kind::Other;
            if (value == "vertices")
            {
                Require(!hadVertices, "3D body의 정점 목록이 중복되었습니다.");
                hadVertices = true;
                kind = Kind::Vertices;
            }
            else if (value == "triangles")
            {
                Require(!hadTriangles, "3D body의 삼각형 목록이 중복되었습니다.");
                hadTriangles = true;
                kind = Kind::Triangles;
            }
        }
        else if (depth == 3 && event == Event::array_start && inBody && kind != Kind::Other)
        {
            collecting = true;
        }
        else if (depth == 3 && event == Event::array_end && collecting)
        {
            collecting = false;
        }
        else if (depth == 4 && collecting)
        {
            Require(event == Event::array_start || event == Event::array_end,
                    "3D 정점과 삼각형의 각 행은 배열이어야 합니다.");
            if (event == Event::array_start)
            {
                rowValues = 0;
            }
            if (event == Event::array_end)
            {
                if (kind == Kind::Vertices)
                {
                    Require(vertices < MaxLargeVertices, "3D 정점 수가 표시 상한을 넘었습니다.");
                    arrays.back().vertices.push_back(ReadPoint(value));
                    ++vertices;
                }
                else
                {
                    Require(triangles < MaxLargeTriangles, "3D 삼각형 수가 표시 상한을 넘었습니다.");
                    arrays.back().triangles.push_back(ReadTriangle(value));
                    ++triangles;
                }
                return false;
            }
        }
        else if (depth == 5 && collecting)
        {
            Require(event == Event::value && value.is_number() && rowValues < 3,
                    "3D 정점 또는 삼각형의 한 행에는 숫자 세 개가 필요합니다.");
            ++rowValues;
        }
        return true;
    });
}
}
