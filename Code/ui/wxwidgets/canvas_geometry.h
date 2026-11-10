#pragma once

#include <algorithm>
#include <cmath>

/** @brief 물리 계산과 독립적인 2D 표시 좌표의 거리와 각도 연산이다. */
namespace CanvasGeometry
{
constexpr double Pi = 3.14159265358979323846;
constexpr double MaxCoordinate = 1.0e9;

struct Point
{
    double x;
    double y;
};

/** @brief 화면 변환에서 표현할 유한 좌표 범위를 확인한다. */
inline bool Valid(Point point)
{
    return std::isfinite(point.x) && std::isfinite(point.y) &&
        std::abs(point.x) <= MaxCoordinate && std::abs(point.y) <= MaxCoordinate;
}

inline double NormalizeDegrees(double angle)
{
    const double reduced = std::fmod(angle, 360.0);
    return reduced < 0.0 ? reduced + 360.0 : reduced;
}

/** @brief Y가 위로 증가하는 좌표에서 부호 있는 원호 구간에 포함되는지 확인한다. */
inline bool InSweep(double angle, double start, double sweep)
{
    if (std::abs(sweep) >= 360.0 - 1e-10)
    {
        return true;
    }
    const double traveled = sweep >= 0.0 ? NormalizeDegrees(angle - start) : NormalizeDegrees(start - angle);
    return traveled <= std::abs(sweep) + 1e-10;
}

inline Point ArcPoint(Point center, double radius, double degrees)
{
    const double angle = NormalizeDegrees(degrees) * Pi / 180.0;
    return {center.x + radius * std::cos(angle), center.y + radius * std::sin(angle)};
}

/** @brief 선분 양 끝을 포함한 최소 거리를 구하며 0 길이 입력도 유한하게 처리한다. */
inline double SegmentDistance(Point point, Point start, Point end)
{
    const double dx = end.x - start.x;
    const double dy = end.y - start.y;
    const double lengthSquared = dx * dx + dy * dy;
    if (lengthSquared <= 1e-24)
    {
        return std::hypot(point.x - start.x, point.y - start.y);
    }
    const double fraction = std::clamp(((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSquared, 0.0, 1.0);
    return std::hypot(point.x - (start.x + fraction * dx), point.y - (start.y + fraction * dy));
}

/** @brief 원호의 실제 각도 구간과 양 끝을 포함하여 선택 거리를 구한다. */
inline double ArcDistance(Point point, Point center, double radius, double start, double sweep)
{
    const double angle = std::atan2(point.y - center.y, point.x - center.x) * 180.0 / Pi;
    if (InSweep(angle, start, sweep))
    {
        return std::abs(std::hypot(point.x - center.x, point.y - center.y) - radius);
    }
    const Point first = ArcPoint(center, radius, start);
    const Point last = ArcPoint(center, radius, start + sweep);
    return std::min(std::hypot(point.x - first.x, point.y - first.y), std::hypot(point.x - last.x, point.y - last.y));
}

/** @brief 중심/시작/끝 방향에서 기본 CCW 또는 명시한 CW 회전량을 구한다. */
inline double SweepDegrees(Point center, Point start, Point end, bool clockwise)
{
    const double a = std::atan2(start.y - center.y, start.x - center.x) * 180.0 / Pi;
    const double b = std::atan2(end.y - center.y, end.x - center.x) * 180.0 / Pi;
    const double ccw = NormalizeDegrees(b - a);
    if (ccw <= 1e-10 || ccw >= 360.0 - 1e-10)
    {
        return 0.0;
    }
    return clockwise ? ccw - 360.0 : ccw;
}

/** @brief 큰 화면 좌표를 native float로 좁히기 전에 double 선분을 표시 사각형으로 자른다. */
inline bool ClipSegment(Point& start, Point& end, double left, double top, double right, double bottom)
{
    const double dx = end.x - start.x;
    const double dy = end.y - start.y;
    double first = 0.0;
    double last = 1.0;
    auto boundary = [&](double direction, double distance)
    {
        if (direction == 0.0)
        {
            return distance >= 0.0;
        }
        const double parameter = distance / direction;
        if (direction < 0.0)
        {
            first = std::max(first, parameter);
        }
        else
        {
            last = std::min(last, parameter);
        }
        return first <= last;
    };
    if (!boundary(-dx, start.x - left) || !boundary(dx, right - start.x) ||
        !boundary(-dy, start.y - top) || !boundary(dy, bottom - start.y))
    {
        return false;
    }
    const Point original = start;
    start = {std::clamp(original.x + first * dx, left, right), std::clamp(original.y + first * dy, top, bottom)};
    end = {std::clamp(original.x + last * dx, left, right), std::clamp(original.y + last * dy, top, bottom)};
    return true;
}
}
