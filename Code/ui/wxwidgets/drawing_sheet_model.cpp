/** @file @brief 종이 미리보기의 자원/유한값 경계와 화면 맞춤만 처리한다. */
#include "drawing_sheet_model.h"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace
{
void Require(bool condition, const char* reason)
{
    if (!condition)
    {
        throw std::runtime_error(reason);
    }
}

double Number(const Json& value)
{
    Require(value.is_number(), "도면 표시 좌표가 숫자가 아닙니다.");
    const double number = value.get<double>();
    Require(std::isfinite(number) && std::abs(number) <= 1e6, "도면 표시 좌표가 유한 범위를 벗어났습니다.");
    return number;
}

void Point(const Json& value)
{
    Require(value.is_array() && value.size() == 2, "도면 표시 점은 두 좌표여야 합니다.");
    Number(value.at(0));
    Number(value.at(1));
}

void Colour(const Json& value)
{
    if (value.is_null())
    {
        return;
    }
    Require(value.is_array() && value.size() == 3, "도면 표시 색 형식이 다릅니다.");
    for (const auto& part : value)
    {
        Require(part.is_number_integer() && part.get<int>() >= 0 && part.get<int>() <= 255,
                "도면 표시 색이 0부터 255 범위를 벗어났습니다.");
    }
}

/** @brief 마우스/키보드 편집에 사용하기 전에 종이 치수의 선택 영역을 검증한다. */
void DimensionPositions(const Json& layout)
{
    const auto validBox = [](const Json& box)
    {
        Require(box.is_array() && box.size() == 4, "도면 치수 배치 범위가 유효하지 않습니다.");
        Require(Number(box.at(0)) < Number(box.at(2)) && Number(box.at(1)) < Number(box.at(3)),
                "도면 치수 배치 범위는 양수여야 합니다.");
    };
    validBox(layout.at("bounds_mm"));
    const auto& items = layout.at("items");
    Require(items.is_array() && items.size() <= 2048, "도면 배치 치수 수가 표시 상한을 초과했습니다.");
    for (const auto& item : items)
    {
        Point(item.at("point_mm"));
        validBox(item.at("label_box"));
        validBox(item.at("pin_bounds_mm"));
        Require(item.at("source_id").is_string() && item.at("key").is_string() && item.at("title").is_string() &&
                    item.at("label").is_string() && item.at("pinned").is_boolean(),
                "도면 치수 배치의 원본 식별자 또는 표시값이 유효하지 않습니다.");
    }
}

void Primitive(const Json& primitive)
{
    Require(primitive.is_object(), "도면 표시 요소가 객체가 아닙니다.");
    const std::string kind = primitive.at("kind").get<std::string>();
    if (primitive.contains("clip_rect_mm"))
    {
        const auto& clip = primitive.at("clip_rect_mm");
        Require(clip.is_array() && clip.size() == 4, "도면 상세 뷰의 잘라내기 범위가 유효하지 않습니다.");
        Number(clip.at(0));
        Number(clip.at(1));
        Require(Number(clip.at(2)) > 0 && Number(clip.at(3)) > 0, "도면 상세 뷰의 표시 범위는 양수여야 합니다.");
    }
    Colour(primitive.value("stroke", Json(nullptr)));
    Colour(primitive.value("fill", Json(nullptr)));
    if (primitive.contains("stroke_width_mm"))
    {
        Require(Number(primitive.at("stroke_width_mm")) >= 0.0, "도면 표시 선폭은 음수일 수 없습니다.");
    }
    if (kind == "line")
    {
        Point(primitive.at("start"));
        Point(primitive.at("end"));
    }
    else if (kind == "circle" || kind == "arc")
    {
        Point(primitive.at("center"));
        Require(Number(primitive.at("radius")) > 0.0, "도면 표시 반지름은 양수여야 합니다.");
        if (kind == "arc")
        {
            Number(primitive.at("start_deg"));
            Require(std::abs(Number(primitive.at("sweep_deg"))) <= 360.0, "도면 표시 원호는 한 바퀴 이하여야 합니다.");
        }
    }
    else if (kind == "path")
    {
        if (primitive.contains("loops"))
        {
            Require(!primitive.contains("rings"), "도면 표시 경계의 두 표현이 동시에 들어왔습니다.");
            const auto& loops = primitive.at("loops");
            Require(loops.is_array() && loops.size() <= 128, "도면 표시 경계 수가 상한을 초과했습니다.");
            std::size_t count = 0;
            for (const auto& loop : loops)
            {
                Require(loop.is_array() && !loop.empty(), "도면 표시 경계의 요소가 없습니다.");
                count += loop.size();
                Require(count <= 32768, "도면 표시 경계 요소 수가 상한을 초과했습니다.");
                for (const auto& segment : loop)
                {
                    const auto segmentKind = segment.value("kind", "");
                    Require(segmentKind == "line" || segmentKind == "arc", "지원하지 않는 도면 경계 요소입니다.");
                    Primitive(segment);
                }
            }
            return;
        }
        const auto& rings = primitive.at("rings");
        Require(rings.is_array() && rings.size() <= 128, "도면 표시 경계 수가 상한을 초과했습니다.");
        std::size_t count = 0;
        for (const auto& ring : rings)
        {
            Require(ring.is_array() && ring.size() >= 2, "도면 표시 경계의 점이 부족합니다.");
            count += ring.size();
            Require(count <= 32768, "도면 표시 경계의 점 수가 상한을 초과했습니다.");
            for (const auto& point : ring)
            {
                Point(point);
            }
        }
    }
    else if (kind == "text")
    {
        Point(primitive.at("position"));
        const auto text = primitive.at("text").get<std::string>();
        Require(text.size() <= 4096, "도면 표시 문구가 상한을 초과했습니다.");
        const double size = Number(primitive.at("height_mm"));
        Require(size > 0 && size <= 1000, "도면 표시 글자 크기가 범위를 벗어났습니다.");
        Number(primitive.value("rotation_deg", Json(0)));
        const auto align = primitive.value("align", "left");
        Require(align == "left" || align == "center" || align == "right", "도면 글자 정렬을 지원하지 않습니다.");
    }
    else
    {
        throw std::runtime_error("지원하지 않는 도면 표시 요소입니다. 조용히 생략하지 않습니다.");
    }
}
}

void DrawingSheet::ValidatePages(const Json& pages)
{
    Require(pages.is_array() && !pages.empty() && pages.size() <= 32, "도면 페이지 수는 1부터 32까지입니다.");
    std::size_t total = 0;
    for (const auto& page : pages)
    {
        const double width = Number(page.at("width_mm"));
        const double height = Number(page.at("height_mm"));
        Require(width > 0 && height > 0, "도면 종이 크기는 명시된 표시 범위 안에 있어야 합니다.");
        if (page.contains("view_box_mm"))
        {
            const auto& box = page.at("view_box_mm");
            Require(box.is_array() && box.size() == 4, "도면 표시 원점/크기가 유효하지 않습니다.");
            Number(box.at(0));
            Number(box.at(1));
            Require(Number(box.at(2)) == width && Number(box.at(3)) == height,
                    "도면 종이 크기와 표시 좌표 크기가 다릅니다.");
        }
        if (page.contains("dimension_placements"))
        {
            DimensionPositions(page.at("dimension_placements"));
        }
        const auto& primitives = page.at("primitives");
        Require(primitives.is_array(), "도면 표시 요소 목록이 없습니다.");
        total += primitives.size();
        Require(total <= 12000, "도면 미리보기 요소 수가 표시 상한을 초과했습니다.");
        for (const auto& primitive : primitives)
        {
            Primitive(primitive);
        }
    }
}

DrawingSheet::Placement DrawingSheet::Fit(double paperWidth, double paperHeight, double width, double height,
                                          double margin)
{
    if (!std::isfinite(paperWidth) || !std::isfinite(paperHeight) || paperWidth <= 0 || paperHeight <= 0 ||
        !std::isfinite(width) || !std::isfinite(height) || !std::isfinite(margin) || margin < 0 ||
        width <= 2 * margin || height <= 2 * margin)
    {
        return {};
    }
    const double scale = std::min((width - 2 * margin) / paperWidth, (height - 2 * margin) / paperHeight);
    if (!std::isfinite(scale) || scale <= 0)
    {
        return {};
    }
    return {(width - paperWidth * scale) / 2, (height - paperHeight * scale) / 2, scale, paperWidth * scale,
            paperHeight * scale};
}
