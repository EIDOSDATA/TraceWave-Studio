/** @file @brief 2D 끝점과 스냅 후보의 표시 연산이다. */
#pragma once

#include "canvas_scene.h"
#include <optional>

namespace CanvasPrecision
{
using CanvasGeometry::Point;
using CanvasScene::Shape;

enum class Endpoint
{
    Start = 1,
    End = 2
};

enum class SnapKind
{
    Endpoint,
    Midpoint,
    Horizontal,
    Vertical,
    Grid
};

struct Snap
{
    Point point;
    SnapKind kind;
    std::string target;
    Endpoint endpoint = Endpoint::Start;
};

struct Circle
{
    Point center;
    double radius;
};

inline bool HasEndpoints(const Shape& shape)
{
    return shape.kind == "line_path" || shape.kind == "arc_path";
}

inline Point At(const Shape& shape, Endpoint endpoint)
{
    const bool end = endpoint == Endpoint::End;
    if (shape.kind == "line_path")
    {
        return end ? shape.end : shape.start;
    }
    return CanvasGeometry::ArcPoint(shape.center, shape.radius, shape.startAngle + (end ? shape.sweepAngle : 0.0));
}

inline bool Editable(const Shape& shape, Endpoint endpoint)
{
    return (shape.endpointMask & static_cast<unsigned>(endpoint)) != 0;
}

inline double Distance(Point a, Point b)
{
    return std::hypot(a.x - b.x, a.y - b.y);
}

/** @brief 알려진 원주 위의 후보만 정확한 원호 스냅으로 표시한다. */
inline bool OnCircle(Point candidate, const Circle& circle)
{
    const double scale = std::max({circle.radius, std::abs(circle.center.x), std::abs(circle.center.y)});
    const double rounding = 8.0 * std::numeric_limits<double>::epsilon() * scale;
    return std::abs(Distance(candidate, circle.center) - circle.radius) <= rounding;
}

inline Point GridPoint(Point point, double step)
{
    return {std::round(point.x / step) * step, std::round(point.y / step) * step};
}

/** @brief 픽셀 이동과 구분하여 실제 끝점 좌표 또는 고정 반지름의 방향이 그대로인지 확인한다. */
inline bool EndpointUnchanged(const Shape& shape, Endpoint endpoint, Point cursor)
{
    if (!CanvasGeometry::Valid(cursor) || !HasEndpoints(shape))
    {
        return false;
    }
    if (shape.kind == "line_path")
    {
        const auto previous = At(shape, endpoint);
        return previous.x == cursor.x && previous.y == cursor.y;
    }
    if (Distance(cursor, shape.center) <= 1e-9)
    {
        return false;
    }
    const double previous = shape.startAngle + (endpoint == Endpoint::End ? shape.sweepAngle : 0.0);
    const double direction = std::atan2(cursor.y - shape.center.y, cursor.x - shape.center.x) * 180.0 / CanvasGeometry::Pi;
    return std::abs(std::remainder(direction - previous, 360.0)) <= 1e-10;
}

/** @brief 허용 반경 안의 가장 가까운 후보를 고르고 동률은 탐색 순서를 유지한다. */
class Nearest
{
public:
    Nearest(Point cursor, double tolerance, std::optional<Circle> circle)
        : m_cursor(cursor), m_limit(tolerance), m_circle(circle)
    {
    }

    void Consider(Point point, SnapKind kind, const std::string& target = {}, Endpoint endpoint = Endpoint::Start)
    {
        const double distance = Distance(m_cursor, point);
        if (!CanvasGeometry::Valid(point) || distance > m_limit || (m_result && distance == m_limit) ||
            (m_circle && !OnCircle(point, *m_circle)))
        {
            return;
        }
        m_limit = distance;
        m_result = Snap{point, kind, target, endpoint};
    }

    std::optional<Snap> Result() const
    {
        return m_result;
    }

private:
    Point m_cursor;
    double m_limit;
    std::optional<Circle> m_circle;
    std::optional<Snap> m_result;
};

/** @brief 서비스 입력 전 고정 반지름/회전 방향으로 끝점 드래그의 2D 미리보기를 계산한다. */
inline bool Preview(Shape& shape, Endpoint endpoint, Point cursor)
{
    if (!CanvasGeometry::Valid(cursor))
    {
        return false;
    }
    const auto fixed = At(shape, endpoint == Endpoint::Start ? Endpoint::End : Endpoint::Start);
    if (shape.kind == "line_path")
    {
        if (Distance(cursor, fixed) <= 1e-9)
        {
            return false;
        }
        (endpoint == Endpoint::Start ? shape.start : shape.end) = cursor;
        return true;
    }
    if (Distance(cursor, shape.center) <= 1e-9)
    {
        return false;
    }
    const auto first = endpoint == Endpoint::Start ? cursor : fixed;
    const auto last = endpoint == Endpoint::End ? cursor : fixed;
    const auto sweep = CanvasGeometry::SweepDegrees(shape.center, first, last, shape.sweepAngle < 0.0);
    if (sweep == 0.0)
    {
        return false;
    }
    if (endpoint == Endpoint::Start)
    {
        shape.startAngle = CanvasGeometry::NormalizeDegrees(
            std::atan2(first.y - shape.center.y, first.x - shape.center.x) * 180.0 / CanvasGeometry::Pi);
    }
    shape.sweepAngle = sweep;
    return true;
}
}
