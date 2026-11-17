/** @file @brief 기계 제거, 제조 개구와 규칙 영역의 표시 좌표만 해석한다. */
#include "canvas_scene.h"
#include <cmath>
#include <set>
#include <stdexcept>

namespace CanvasScene
{
namespace
{
Point PointValue(const nlohmann::json& value)
{
    if (!value.is_array() || value.size() != 2 || !value[0].is_number() || !value[1].is_number())
    {
        throw std::runtime_error("PCB 표시 좌표는 두 유한 숫자여야 합니다.");
    }
    Point point{value[0].get<double>(), value[1].get<double>()};
    if (!CanvasGeometry::Valid(point))
    {
        throw std::runtime_error("PCB 표시 좌표가 지원 범위를 벗어났습니다.");
    }
    return point;
}

double PositiveValue(const nlohmann::json& value)
{
    if (!value.is_number())
    {
        throw std::runtime_error("PCB 표시 치수에 숫자가 필요합니다.");
    }
    const auto number = value.get<double>();
    if (!std::isfinite(number) || number <= 0 || number > CanvasGeometry::MaxCoordinate)
    {
        throw std::runtime_error("PCB 표시 치수가 지원 범위를 벗어났습니다.");
    }
    return number;
}
}

std::vector<Shape> ParsePcbFeatures(const nlohmann::json& values)
{
    if (!values.is_array() || values.size() > 256)
    {
        throw std::runtime_error("PCB 표시 객체 수가 유한 상한을 벗어났습니다.");
    }
    std::vector<Shape> result;
    std::set<std::string> ids;
    for (const auto& item : values)
    {
        if (item.value("missing", false) || item.value("shape_mm", nlohmann::json(nullptr)).is_null())
        {
            continue;
        }
        const auto& shape = item.at("shape_mm");
        Shape view;
        view.id = item.at("id").get<std::string>();
        if (view.id.empty() || !ids.insert(view.id).second)
        {
            throw std::runtime_error("PCB 표시 객체의 식별자가 중복되거나 비어 있습니다.");
        }
        view.selectionKind = item.at("kind").get<std::string>();
        const std::set<std::string> kinds{"cutout", "hole", "footprint", "artwork_layer", "aperture", "keepout"};
        if (!kinds.count(view.selectionKind))
        {
            throw std::runtime_error("지원하지 않는 PCB 표시 객체 종류입니다.");
        }
        view.label = item.value("source_label", item.value("label", "PCB 객체"));
        const auto owner = item.value("owner_footprint_id", nlohmann::json(nullptr));
        view.ownerFootprint = owner.is_string() ? owner.get<std::string>() : "";
        view.role = view.selectionKind;
        view.incomplete = item.value("missing", false);
        view.movable = false;
        const auto kind = shape.at("kind").get<std::string>();
        if (kind == "circle")
        {
            view.kind = "pad";
            view.center = PointValue(shape.at("center_mm"));
            view.radius = PositiveValue(shape.at("diameter_mm")) / 2;
        }
        else if (kind == "rectangle")
        {
            view.kind = "planar_region";
            view.center = PointValue(shape.at("center_mm"));
            const auto& size = shape.at("size_mm");
            const double rotation = shape.at("rotation_deg").get<double>();
            if (!std::isfinite(rotation))
            {
                throw std::runtime_error("PCB 표시 회전각이 유한하지 않습니다.");
            }
            view.rings.push_back(CanvasGeometry::RectanglePoints(view.center, PositiveValue(size.at(0)),
                                                                 PositiveValue(size.at(1)), rotation));
        }
        else if (kind == "capsule")
        {
            view.kind = "line_path";
            view.center = PointValue(shape.at("center_mm"));
            const double length = PositiveValue(shape.at("finished_length_mm"));
            view.width = PositiveValue(shape.at("finished_width_mm"));
            const double rotation = shape.at("rotation_deg").get<double>();
            if (!std::isfinite(rotation) || length <= view.width)
            {
                throw std::runtime_error("PCB 슬롯 표시의 완성 길이와 폭을 확인할 수 없습니다.");
            }
            const double half = (length - view.width) / 2;
            const double radians = rotation * CanvasGeometry::Pi / 180;
            const Point delta{half * std::cos(radians), half * std::sin(radians)};
            view.start = {view.center.x - delta.x, view.center.y - delta.y};
            view.end = {view.center.x + delta.x, view.center.y + delta.y};
        }
        else if (kind == "polygon")
        {
            view.kind = "planar_region";
            auto rings = nlohmann::json::array({shape.at("outer_mm")});
            for (const auto& hole : shape.value("holes_mm", nlohmann::json::array()))
            {
                rings.push_back(hole);
            }
            std::size_t count = 0;
            if (rings.size() > 9)
            {
                throw std::runtime_error("PCB 표시 다각형의 구멍 수를 초과했습니다.");
            }
            for (const auto& ring : rings)
            {
                if (!ring.is_array() || ring.size() < 3 || (count += ring.size()) > 64)
                {
                    throw std::runtime_error("PCB 표시 다각형의 꼭짓점 범위를 초과했습니다.");
                }
                std::vector<Point> points;
                for (const auto& point : ring)
                {
                    points.push_back(PointValue(point));
                }
                view.rings.push_back(std::move(points));
            }
        }
        else
        {
            throw std::runtime_error("지원하지 않는 PCB 표시 형상입니다.");
        }
        if (!CanvasGeometry::Valid(view.center) || !CanvasGeometry::Valid(view.start) ||
            !CanvasGeometry::Valid(view.end))
        {
            throw std::runtime_error("PCB 표시 외곽이 지원 좌표 범위를 벗어났습니다.");
        }
        for (const auto& ring : view.rings)
        {
            for (const auto& point : ring)
            {
                if (!CanvasGeometry::Valid(point))
                {
                    throw std::runtime_error("PCB 표시 외곽이 지원 좌표 범위를 벗어났습니다.");
                }
            }
        }
        result.push_back(std::move(view));
    }
    return result;
}
}
