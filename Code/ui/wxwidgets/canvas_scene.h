#pragma once

#include "canvas_geometry.h"
#include <nlohmann/json.hpp>
#include <map>
#include <set>
#include <string>
#include <vector>

/** @brief 창과 독립적으로 표시 DTO를 검증하고 선택/범위 계산에 사용하는 읽기 전용 장면이다. */
namespace CanvasScene
{
using Point = CanvasGeometry::Point;

/** @brief 서비스의 표시 형상을 mm 좌표로 보존하며 도메인 원본을 수정하지 않는다. */
struct Shape
{
    std::string id;
    std::string kind;
    std::string label;
    std::string layer;
    std::string role;
    Point start{0.0, 0.0};
    Point end{0.0, 0.0};
    Point center{0.0, 0.0};
    double radius = 0.0;
    double startAngle = 0.0;
    double sweepAngle = 0.0;
    double width = 0.0;
    std::vector<std::vector<Point>> rings;
    std::set<std::string> spanLayers;
    double holeRadius = 0.0;
    bool incomplete = false;
    bool movable = false;
};

/** @brief 화면 맞춤에 사용할 전체 mm 경계이다. */
struct Bounds
{
    double left;
    double bottom;
    double right;
    double top;
};

/** @brief 완전히 검증한 형상과 식별자 인덱스를 한 번에 교체한다. */
class Model
{
public:
    static Model Parse(const nlohmann::json& scene);
    const Shape* Find(const std::string& identity) const;
    Bounds VisibleBounds(const std::set<std::string>& hiddenLayers) const;
    std::vector<Shape> shapes;
    std::set<std::string> layers;
    bool hasBoard = false;
    double boardWidth = 0.0;
    double boardHeight = 0.0;
    bool circularBoard = false;
    Point boardCenter{0.0, 0.0};
    double boardRadius = 0.0;
    std::size_t omissionCount = 0;
    std::size_t rangeOmissionCount = 0;

private:
    std::map<std::string, std::size_t> m_indices;
};

bool Visible(const Shape& shape, const std::set<std::string>& hiddenLayers);
double DistanceTo(const Shape& shape, Point point);
}
