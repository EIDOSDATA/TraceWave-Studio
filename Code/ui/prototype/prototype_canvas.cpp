#include "prototype_canvas.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <imgui_internal.h>
#include <vector>

namespace
{
using CanvasScene::Point;

/** @brief 서비스의 mm 좌표를 기존 화면 배율과 옮김 위치로 변환한다. */
struct Projection
{
    ImVec2 origin;
    Point center;
    double scale;

    ImVec2 screen(Point value) const
    {
        return {origin.x + static_cast<float>((value.x - center.x) * scale),
                origin.y - static_cast<float>((value.y - center.y) * scale)};
    }

    Point world(ImVec2 value) const
    {
        return {center.x + (value.x - origin.x) / scale, center.y - (value.y - origin.y) / scale};
    }
};

void outline(ImDrawList& draw, const Projection& map, const std::vector<Point>& ring, ImU32 color)
{
    if (ring.size() < 2)
    {
        return;
    }
    std::vector<ImVec2> points;
    points.reserve(ring.size());
    for (const auto& point : ring)
    {
        points.push_back(map.screen(point));
    }
    draw.AddPolyline(points.data(), static_cast<int>(points.size()), color, ImDrawFlags_Closed, 1.5f);
}

void drawOutline(ImDrawList& draw, const Projection& map, const CanvasScene::Model& scene)
{
    constexpr auto color = IM_COL32(95, 199, 181, 255);
    if (!scene.hasBoard)
    {
        return;
    }
    if (scene.circularBoard)
    {
        draw.AddCircle(map.screen(scene.boardCenter), static_cast<float>(scene.boardRadius * map.scale), color, 0, 2.0f);
    }
    else if (!scene.boardOuter.empty())
    {
        outline(draw, map, scene.boardOuter, color);
    }
    else
    {
        draw.AddRect(map.screen({0, scene.boardHeight}), map.screen({scene.boardWidth, 0}), color, 0.0f, ImDrawFlags_None, 2.0f);
    }
}

void drawShape(ImDrawList& draw, const Projection& map, const CanvasScene::Shape& shape, bool selected)
{
    const auto color = selected ? IM_COL32(255, 238, 122, 255) : IM_COL32(244, 165, 80, 255);
    const float width = static_cast<float>(std::clamp(shape.width * map.scale, 1.5, 1000.0));
    if (shape.kind == "line_path")
    {
        draw.AddLine(map.screen(shape.start), map.screen(shape.end), color, width);
    }
    else if (shape.kind == "arc_path")
    {
        const int count = std::clamp(static_cast<int>(std::ceil(std::abs(shape.sweepAngle) / 4.0)), 4, 96);
        std::array<ImVec2, 97> points;
        for (int index = 0; index <= count; ++index)
        {
            points[index] = map.screen(CanvasGeometry::ArcPoint(shape.center, shape.radius,
                shape.startAngle + shape.sweepAngle * index / count));
        }
        draw.AddPolyline(points.data(), count + 1, color, ImDrawFlags_None, width);
    }
    else if (!shape.rings.empty())
    {
        for (const auto& ring : shape.rings)
        {
            outline(draw, map, ring, color);
        }
    }
    else if (shape.radius > 0)
    {
        draw.AddCircle(map.screen(shape.center), static_cast<float>(shape.radius * map.scale), color, 0, 1.5f);
    }
    if (shape.holeRadius > 0)
    {
        draw.AddCircle(map.screen(shape.center), static_cast<float>(shape.holeRadius * map.scale), color, 0, 1.0f);
    }
}
}

bool drawProjectCanvas(PrototypeProject::View& view, float& zoom, ImVec2& pan, PrototypeEndpoint* endpoint)
{
    const auto origin = ImGui::GetCursorScreenPos();
    const auto size = ImGui::GetContentRegionAvail();
    if (size.x < 24 || size.y < 24)
    {
        return false;
    }
    const bool clicked = ImGui::InvisibleButton("###project-canvas", size, ImGuiButtonFlags_MouseButtonLeft);
    const auto& io = ImGui::GetIO();
    if (ImGui::IsItemHovered() && io.MouseWheel != 0.0f)
    {
        zoom = std::clamp(zoom * std::pow(1.15f, io.MouseWheel), 0.35f, 6.0f);
    }
    if (ImGui::IsItemActive() && ImGui::IsMouseDragging(ImGuiMouseButton_Left))
    {
        pan.x += io.MouseDelta.x;
        pan.y += io.MouseDelta.y;
    }
    const auto bounds = view.canvas.VisibleBounds({});
    const Projection map{{origin.x + size.x / 2 + pan.x, origin.y + size.y / 2 + pan.y},
        {(bounds.left + bounds.right) / 2, (bounds.bottom + bounds.top) / 2},
        zoom * 0.82 * std::min(size.x / std::max(0.01, bounds.right - bounds.left),
            size.y / std::max(0.01, bounds.top - bounds.bottom))};
    if (clicked && !ImGui::IsMouseDragPastThreshold(ImGuiMouseButton_Left))
    {
        const auto world = map.world(io.MousePos);
        if (endpoint && endpoint->picking)
        {
            endpoint->point = world;
            endpoint->picking = false;
            endpoint->snapLabel.clear();
            const auto* selected = view.canvas.Find(view.selection);
            if (endpoint->snap && selected)
            {
                using namespace CanvasPrecision;
                std::optional<Circle> circle;
                if (selected->kind == "arc_path")
                {
                    circle = Circle{selected->center, selected->radius};
                }
                Nearest nearest(world, 8.0 / map.scale, circle);
                for (auto other = view.canvas.shapes.rbegin(); other != view.canvas.shapes.rend(); ++other)
                {
                    if (other->id != selected->id && selected->layer == other->layer && HasEndpoints(*other))
                    {
                        nearest.Consider(At(*other, Endpoint::End), SnapKind::Endpoint, other->id);
                        nearest.Consider(At(*other, Endpoint::Start), SnapKind::Endpoint, other->id);
                    }
                }
                if (!nearest.Result())
                {
                    nearest.Consider(GridPoint(world, 1.0), SnapKind::Grid);
                }
                if (const auto candidate = nearest.Result())
                {
                    endpoint->point = candidate->point;
                    const auto* target = view.canvas.Find(candidate->target);
                    endpoint->snapLabel = target ? "스냅 " + target->label : "1 mm 격자 스냅";
                }
            }
        }
        else
        {
            double closest = 6.0 / map.scale;
            view.selection.clear();
            for (auto shape = view.canvas.shapes.rbegin(); shape != view.canvas.shapes.rend(); ++shape)
            {
                const double distance = CanvasScene::DistanceTo(*shape, world);
                if (distance < closest)
                {
                    closest = distance;
                    view.selection = shape->id;
                }
            }
        }
    }
    auto& draw = *ImGui::GetWindowDrawList();
    const ImVec2 end(origin.x + size.x, origin.y + size.y);
    draw.PushClipRect(origin, end, true);
    draw.AddRectFilled(origin, end, IM_COL32(17, 26, 35, 255));
    drawOutline(draw, map, view.canvas);
    for (const auto& shape : view.canvas.shapes)
    {
        drawShape(draw, map, shape, shape.id == view.selection);
    }
    if (endpoint && endpoint->id == view.selection && endpoint->revision == view.revision)
    {
        if (const auto* selected = view.canvas.Find(view.selection))
        {
            auto preview = *selected;
            if (CanvasPrecision::Preview(preview, endpoint->side, endpoint->point))
            {
                const auto target = CanvasPrecision::At(preview, endpoint->side);
                draw.AddLine(map.screen(CanvasPrecision::At(*selected, endpoint->side)), map.screen(target),
                    IM_COL32(115, 226, 233, 255), 2.0f);
                draw.AddCircle(map.screen(target), 4.0f, IM_COL32(115, 226, 233, 255), 12, 2.0f);
            }
        }
    }
    for (const auto& port : view.canvas.portMarkers)
    {
        draw.AddCircleFilled(map.screen(port.point), 3.5f, IM_COL32(125, 212, 249, 255));
    }
    draw.PopClipRect();
    return true;
}

/** @brief 서비스가 생성한 후보 장면만 표시하며 편집 입력을 받지 않는다. */
void drawCandidateCanvas(const CanvasScene::Model& scene, const std::vector<std::string>& highlighted, float height)
{
    const auto origin = ImGui::GetCursorScreenPos();
    const ImVec2 size{ImGui::GetContentRegionAvail().x, height};
    if (size.x < 24.0f || size.y < 24.0f)
    {
        return;
    }
    ImGui::Dummy(size);
    const auto bounds = scene.VisibleBounds({});
    const Projection map{{origin.x + size.x * 0.5f, origin.y + size.y * 0.5f},
        {(bounds.left + bounds.right) / 2, (bounds.bottom + bounds.top) / 2},
        0.82 * std::min(size.x / std::max(0.01, bounds.right - bounds.left),
            size.y / std::max(0.01, bounds.top - bounds.bottom))};
    auto& draw = *ImGui::GetWindowDrawList();
    const ImVec2 end(origin.x + size.x, origin.y + size.y);
    draw.PushClipRect(origin, end, true);
    draw.AddRectFilled(origin, end, IM_COL32(17, 26, 35, 255));
    drawOutline(draw, map, scene);
    for (const auto& shape : scene.shapes)
    {
        drawShape(draw, map, shape, std::ranges::find(highlighted, shape.id) != highlighted.end());
    }
    draw.PopClipRect();
}
