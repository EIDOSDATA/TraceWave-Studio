#include "canvas_scene.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace CanvasScene
{
namespace
{
using Json = nlohmann::json;
/** @brief 원본이 잘못된 경우와 현재 화면의 표시 범위를 초과한 경우를 구분한다. */
class DisplayRangeError final : public std::runtime_error
{
public:
    explicit DisplayRangeError(const char* message) : std::runtime_error(message)
    {
    }
};

Point ReadPoint(const Json& value)
{
    if (!value.is_array() || value.size() != 2 || !value[0].is_number() || !value[1].is_number())
    {
        throw std::runtime_error("표시 좌표는 두 숫자의 배열이어야 합니다.");
    }
    const Point point{value[0].get<double>(), value[1].get<double>()};
    if (!std::isfinite(point.x) || !std::isfinite(point.y))
    {
        throw std::runtime_error("표시 좌표는 유한해야 합니다.");
    }
    if (!CanvasGeometry::Valid(point))
    {
        throw DisplayRangeError("현재 캔버스의 좌표 표시 범위를 초과했습니다.");
    }
    return point;
}

double Positive(const Json& value)
{
    if (!value.is_number())
    {
        throw std::runtime_error("표시 치수는 숫자여야 합니다.");
    }
    const double number = value.get<double>();
    if (!std::isfinite(number) || number <= 0.0)
    {
        throw std::runtime_error("표시 치수가 유한한 양수 범위를 벗어났습니다.");
    }
    if (number > CanvasGeometry::MaxCoordinate)
    {
        throw DisplayRangeError("현재 캔버스의 치수 표시 범위를 초과했습니다.");
    }
    return number;
}

}

Model Model::Parse(const nlohmann::json& scene)
{
    std::vector<Shape> shapes;
    std::set<std::string> layers;
    std::set<std::string> identities;
    const Json& board = scene.at("board");
    if (!board.is_null() && board.value("kind", "rectangle") != "rectangle" && board.value("kind", "rectangle") != "circle")
    {
        throw std::runtime_error("지원하지 않는 기판 외곽 표시 형식입니다.");
    }
    const bool circular = !board.is_null() && board.value("kind", "rectangle") == "circle";
    bool hasBoard = !board.is_null() && (circular ?
        (!board.at("radius").is_null() && board.at("center").is_array() && board.at("center").size() == 2 &&
            !board.at("center").at(0).is_null() && !board.at("center").at(1).is_null()) :
        (!board.at("width").is_null() && !board.at("height").is_null()));
    double boardWidth = 0.0;
    double boardHeight = 0.0;
    double boardRadius = 0.0;
    Point boardCenter{0.0, 0.0};
    std::size_t rangeOmissions = 0;
    if (hasBoard)
    {
        try
        {
            if (circular)
            {
                boardCenter = ReadPoint(board.at("center"));
                boardRadius = Positive(board.at("radius"));
            }
            else
            {
                boardWidth = Positive(board.at("width"));
                boardHeight = Positive(board.at("height"));
            }
        }
        catch (const DisplayRangeError&)
        {
            hasBoard = false;
            ++rangeOmissions;
        }
    }
    for (const auto& layer : scene.at("layers"))
    {
        layers.insert(layer.at("id").get<std::string>());
    }
    if (!scene.at("shapes").is_array() || scene.at("shapes").size() > 4096)
    {
        throw std::runtime_error("초기 캔버스 표시 객체 수를 초과했습니다.");
    }
    for (const auto& item : scene.at("shapes"))
    {
        try
        {
            Shape shape;
            shape.id = item.at("id").get<std::string>();
            shape.kind = item.at("kind").get<std::string>();
            shape.label = item.value("label", shape.id);
            shape.layer = item.at("layer_id").get<std::string>();
            shape.role = item.value("role", std::string("conductor"));
            shape.width = (shape.kind == "line_path" || shape.kind == "arc_path") ? Positive(item.at("width")) : 0.0;
            shape.movable = item.value("movable", false);
            if (shape.id.empty() || !identities.insert(shape.id).second || !layers.count(shape.layer))
            {
                throw std::runtime_error("표시 객체의 식별자 또는 층 참조가 유효하지 않습니다.");
            }
            if (shape.kind == "line_path")
            {
                shape.start = ReadPoint(item.at("start"));
                shape.end = ReadPoint(item.at("end"));
                if (std::hypot(shape.start.x - shape.end.x, shape.start.y - shape.end.y) == 0.0)
                {
                    throw std::runtime_error("0 길이 선을 표시할 수 없습니다.");
                }
            }
            else if (shape.kind == "arc_path")
            {
                shape.center = ReadPoint(item.at("center"));
                shape.radius = Positive(item.at("radius"));
                shape.startAngle = item.at("start_angle").get<double>();
                shape.sweepAngle = item.at("sweep_angle").get<double>();
                if (!std::isfinite(shape.startAngle) || !std::isfinite(shape.sweepAngle) ||
                    shape.sweepAngle == 0.0 || std::abs(shape.sweepAngle) > 360.0 + 1e-10)
                {
                    throw std::runtime_error("표시 원호의 각도 구간이 유효하지 않습니다.");
                }
                shape.startAngle = CanvasGeometry::NormalizeDegrees(shape.startAngle);
            }
            else if (shape.kind == "planar_region")
            {
                Json rings = Json::array({item.at("outer")});
                if (!item.at("holes").is_array() || item.at("holes").size() > 8)
                {
                    throw std::runtime_error("표시 다각형의 구멍 목록이 유효하지 않습니다.");
                }
                for (const auto& hole : item.at("holes"))
                {
                    rings.push_back(hole);
                }
                std::size_t vertices = 0;
                for (const auto& ring : rings)
                {
                    if (!ring.is_array() || ring.size() < 3 || (vertices += ring.size()) > 64)
                    {
                        throw std::runtime_error("표시 다각형은 폐곡선마다 3점 이상, 전체 64점 이하여야 합니다.");
                    }
                    std::vector<Point> points;
                    for (const auto& point : ring)
                    {
                        points.push_back(ReadPoint(point));
                    }
                    shape.rings.push_back(std::move(points));
                }
            }
            else if (shape.kind == "pad")
            {
                shape.center = ReadPoint(item.at("center"));
                if (!item.at("size").is_array() || item.at("size").size() != 2)
                {
                    throw std::runtime_error("패드 크기는 폭과 높이 두 값이어야 합니다.");
                }
                const double width = Positive(item.at("size").at(0)), height = Positive(item.at("size").at(1));
                const double rotation = item.at("rotation").get<double>();
                if (!std::isfinite(rotation))
                {
                    throw std::runtime_error("패드 회전은 유한한 각도여야 합니다.");
                }
                if (item.at("pad_shape") == "circle")
                {
                    if (width != height)
                    {
                        throw std::runtime_error("원형 패드의 두 지름이 일치하지 않습니다.");
                    }
                    shape.radius = width / 2.0;
                }
                else if (item.at("pad_shape") == "rectangle")
                {
                    std::vector<Point> corners;
                    for (const auto& point : CanvasGeometry::RectanglePoints(shape.center, width, height, rotation))
                    {
                        if (!CanvasGeometry::Valid(point))
                        {
                            throw DisplayRangeError("회전 패드 외곽이 표시 좌표 범위를 초과했습니다.");
                        }
                        corners.push_back({point.x, point.y});
                    }
                    shape.rings.push_back(std::move(corners));
                }
                else
                {
                    throw std::runtime_error("지원하지 않는 패드 외곽입니다.");
                }
            }
            else if (shape.kind == "via")
            {
                shape.center = ReadPoint(item.at("center"));
                for (const auto& layer : item.at("span_layer_ids"))
                {
                    const std::string identity = layer.get<std::string>();
                    if (!layers.count(identity))
                    {
                        throw std::runtime_error("비아 범위가 존재하지 않는 층을 참조합니다.");
                    }
                    shape.spanLayers.insert(identity);
                }
                const auto& hole = item.at("finished_hole_diameter");
                const auto& plating = item.at("plating_thickness");
                const auto& toolHole = item.at("tool_hole_diameter");
                shape.incomplete = hole.is_null() || plating.is_null() || toolHole.is_null();
                shape.holeRadius = hole.is_null() ? 0.0 : Positive(hole) / 2.0;
                shape.radius = shape.holeRadius;
                if (!plating.is_null())
                {
                    const double thickness = Positive(plating);
                    if (!hole.is_null())
                    {
                        shape.radius += thickness;
                    }
                }
                if (!toolHole.is_null())
                {
                    Positive(toolHole);
                }
            }
            else
            {
                throw std::runtime_error("지원하지 않는 2D 표시 형상입니다.");
            }
            if ((shape.kind == "via" || shape.kind == "pad") && shape.rings.empty() && shape.radius > 0.0 &&
                (std::abs(shape.center.x) + shape.radius > CanvasGeometry::MaxCoordinate ||
                    std::abs(shape.center.y) + shape.radius > CanvasGeometry::MaxCoordinate ||
                    shape.center.x - shape.radius >= shape.center.x + shape.radius ||
                    shape.center.y - shape.radius >= shape.center.y + shape.radius))
            {
                throw DisplayRangeError("패드/비아 외곽이 표시 범위 또는 좌표 정밀도를 벗어났습니다.");
            }
            shapes.push_back(std::move(shape));
        }
        catch (const DisplayRangeError&)
        {
            ++rangeOmissions;
        }
    }
    std::stable_sort(shapes.begin(), shapes.end(), [](const Shape& left, const Shape& right)
    {
        auto order = [](const Shape& shape)
        {
            return shape.kind == "planar_region" ? 0 : (shape.kind == "pad" ? 2 : (shape.kind == "via" ? 3 : 1));
        };
        return order(left) < order(right);
    });
    Model result;
    result.shapes = std::move(shapes);
    result.layers = std::move(layers);
    result.hasBoard = hasBoard;
    result.boardWidth = boardWidth;
    result.boardHeight = boardHeight;
    result.circularBoard = circular;
    result.boardCenter = boardCenter;
    result.boardRadius = boardRadius;
    result.omissionCount = scene.contains("omissions") && scene.at("omissions").is_array() ? scene.at("omissions").size() : 0;
    result.rangeOmissionCount = rangeOmissions;
    for (std::size_t index = 0; index < result.shapes.size(); ++index)
    {
        result.m_indices.emplace(result.shapes[index].id, index);
    }
    return result;
}

/** @brief 표시 순서를 유지하면서 식별자 검색은 인덱스로 수행한다. */
const Shape* Model::Find(const std::string& identity) const
{
    const auto found = m_indices.find(identity);
    return found == m_indices.end() ? nullptr : &shapes[found->second];
}

/** @brief 여러 층을 관통하는 비아는 보이는 층이 하나라도 있으면 표시한다. */
bool Visible(const Shape& shape, const std::set<std::string>& hiddenLayers)
{
    if (shape.kind == "via" && !shape.spanLayers.empty())
    {
        return std::any_of(shape.spanLayers.begin(), shape.spanLayers.end(), [&](const std::string& layer)
        {
            return hiddenLayers.count(layer) == 0;
        });
    }
    return hiddenLayers.count(shape.layer) == 0;
}

/** @brief 한 번 해석한 다각형 좌표를 재사용하며 선택마다 좌표 배열을 복제하지 않는다. */
double DistanceTo(const Shape& shape, Point point)
{
    if (shape.kind == "line_path")
    {
        return CanvasGeometry::SegmentDistance(point, shape.start, shape.end);
    }
    if (shape.kind == "arc_path")
    {
        return CanvasGeometry::ArcDistance(point, shape.center, shape.radius, shape.startAngle, shape.sweepAngle);
    }
    if (!shape.rings.empty())
    {
        return CanvasGeometry::RegionDistance(point, shape.rings);
    }
    return std::max(0.0, std::hypot(point.x - shape.center.x, point.y - shape.center.y) - shape.radius);
}

/** @brief 실제 원호 구간과 폭/구멍 외곽을 포함한 표시 경계를 계산한다. */
Bounds Model::VisibleBounds(const std::set<std::string>& hiddenLayers) const
{
    double left = std::numeric_limits<double>::infinity();
    double bottom = left;
    double right = -left;
    double top = -left;
    auto include = [&](double x, double y, double padding)
    {
        if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(padding))
        {
            return;
        }
        left = std::min(left, x - padding);
        right = std::max(right, x + padding);
        bottom = std::min(bottom, y - padding);
        top = std::max(top, y + padding);
    };
    if (hasBoard)
    {
        if (circularBoard)
        {
            include(boardCenter.x, boardCenter.y, boardRadius);
        }
        else
        {
            include(0.0, 0.0, 0.0);
            include(boardWidth, boardHeight, 0.0);
        }
    }
    for (const Shape& shape : shapes)
    {
        if (!Visible(shape, hiddenLayers))
        {
            continue;
        }
        if (shape.kind == "line_path")
        {
            include(shape.start.x, shape.start.y, shape.width / 2.0);
            include(shape.end.x, shape.end.y, shape.width / 2.0);
        }
        else if (shape.kind == "arc_path")
        {
            const auto first = CanvasGeometry::ArcPoint(shape.center, shape.radius, shape.startAngle);
            const auto last = CanvasGeometry::ArcPoint(shape.center, shape.radius, shape.startAngle + shape.sweepAngle);
            include(first.x, first.y, shape.width / 2.0);
            include(last.x, last.y, shape.width / 2.0);
            for (double angle : {0.0, 90.0, 180.0, 270.0})
            {
                if (CanvasGeometry::InSweep(angle, shape.startAngle, shape.sweepAngle))
                {
                    const auto point = CanvasGeometry::ArcPoint(shape.center, shape.radius, angle);
                    include(point.x, point.y, shape.width / 2.0);
                }
            }
        }
        else if (!shape.rings.empty())
        {
            for (const auto& ring : shape.rings)
            {
                for (const auto& point : ring)
                {
                    include(point.x, point.y, 0.0);
                }
            }
        }
        else
        {
            include(shape.center.x, shape.center.y, shape.radius);
        }
    }
    if (!std::isfinite(left))
    {
        left = -20.0;
        right = 20.0;
        bottom = -20.0;
        top = 20.0;
    }
    return {left, bottom, right, top};
}
}
