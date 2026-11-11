#include "canvas_viewport.h"
#include <algorithm>
#include <cmath>

namespace
{
constexpr double MaximumNativeCoordinate = 1.0e6;
constexpr double MaximumClipCoordinate = 1.0e12;
}

/** @brief Y-up 장면을 Y-down 픽셀로 변환하며 clipping 전의 정밀도를 보존한다. */
CanvasViewport::Point CanvasViewport::Project(Point point, Point offset) const
{
    return {width / 2.0 + (point.x + offset.x - center.x) * pixelsPerMm,
        height / 2.0 - (point.y + offset.y - center.y) * pixelsPerMm};
}

/** @brief 입력 좌표는 지원하는 유한 world 범위로 제한한다. */
CanvasViewport::Point CanvasViewport::Unproject(Point pixel) const
{
    return {std::clamp(center.x + (pixel.x - width / 2.0) / pixelsPerMm,
        -CanvasGeometry::MaxCoordinate, CanvasGeometry::MaxCoordinate),
        std::clamp(center.y - (pixel.y - height / 2.0) / pixelsPerMm,
        -CanvasGeometry::MaxCoordinate, CanvasGeometry::MaxCoordinate)};
}

/** @brief 그리기와 선택에서 같은 native 좌표/폭 제한을 적용한다. */
bool CanvasViewport::Renderable(const CanvasScene::Shape& shape, Point offset) const
{
    const double width = shape.width * pixelsPerMm;
    if (!std::isfinite(width) || width > MaximumNativeCoordinate)
    {
        return false;
    }
    if (shape.kind == "line_path")
    {
        const Point start = Project(shape.start, offset);
        const Point end = Project(shape.end, offset);
        return std::isfinite(start.x) && std::isfinite(start.y) && std::isfinite(end.x) && std::isfinite(end.y) &&
            std::max({std::abs(start.x), std::abs(start.y), std::abs(end.x), std::abs(end.y)}) <= MaximumClipCoordinate;
    }
    if (!shape.rings.empty())
    {
        for (const auto& ring : shape.rings)
        {
            for (const auto& point : ring)
            {
                const Point pixel = Project(point, offset);
                if (!std::isfinite(pixel.x) || !std::isfinite(pixel.y) ||
                    std::max(std::abs(pixel.x), std::abs(pixel.y)) > MaximumNativeCoordinate)
                {
                    return false;
                }
            }
        }
        return true;
    }
    const Point center = Project(shape.center, offset);
    const double extent = shape.radius * pixelsPerMm + width / 2.0;
    return std::isfinite(extent) && std::isfinite(center.x) && std::isfinite(center.y) &&
        std::max(std::abs(center.x), std::abs(center.y)) + extent <= MaximumNativeCoordinate;
}
