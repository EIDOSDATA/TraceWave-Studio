#include "../ui/wxwidgets/canvas_geometry.h"
#include "../ui/wxwidgets/canvas_precision.h"
#include "../ui/wxwidgets/polygon_input.h"

#include <cstdio>
#include <cstdlib>
#include <limits>

/** @brief Release의 NDEBUG에서도 실패를 실제 종료 코드로 보고한다. */
void Check(bool condition)
{
    if (!condition)
    {
        std::fputs("Canvas geometry check failed.\n", stderr);
        std::exit(1);
    }
}

/** @brief GUI나 도메인 계산 없이 방향, 구간 선택과 경계 좌표를 검증한다. */
int main()
{
    using namespace CanvasGeometry;
    Check(InSweep(0.0, 350.0, 20.0));
    Check(!InSweep(180.0, 350.0, 20.0));
    Check(InSweep(0.0, 10.0, -20.0));
    Check(!InSweep(180.0, 10.0, -20.0));
    Check(InSweep(180.0, 10.0, -360.0));
    Check(std::abs(SweepDegrees({0, 0}, {1, 0}, {0, 1}, false) - 90.0) < 1e-10);
    Check(std::abs(SweepDegrees({0, 0}, {1, 0}, {0, 1}, true) + 270.0) < 1e-10);
    Check(SweepDegrees({0, 0}, {1, 0}, {2, 0}, false) == 0.0);
    Check(std::abs(SegmentDistance({2, 1}, {0, 0}, {1, 0}) - std::sqrt(2.0)) < 1e-10);
    Check(std::abs(SegmentDistance({1, 1}, {0, 0}, {0, 0}) - std::sqrt(2.0)) < 1e-10);
    Check(std::abs(ArcDistance({0, 1}, {0, 0}, 1, 0, 90)) < 1e-10);
    Check(ArcDistance({-1, 0}, {0, 0}, 1, 0, 90) > 1.4);
    Check(std::abs(ArcDistance({0, -1}, {0, 0}, 1, 0, -90)) < 1e-10);
    const CanvasPrecision::Circle circle{{1, 1}, 5};
    CanvasPrecision::Nearest nearest({1.2, 5.9}, 0.75, circle);
    nearest.Consider({1.2, 5.9}, CanvasPrecision::SnapKind::Endpoint);
    Check(!nearest.Result());
    nearest.Consider({1, 6}, CanvasPrecision::SnapKind::Endpoint);
    Check(nearest.Result() && nearest.Result()->point.y == 6);
    const auto tangent = CanvasPrecision::TangentPoint({2, 2}, {2, -1}, {6, -0.91}, 0.1);
    Check(tangent && tangent->x == 6 && tangent->y == -1);
    Check(!CanvasPrecision::TangentPoint({2, 2}, {2, -1}, {6, -0.88}, 0.1));
    Check(!CanvasPrecision::TangentPoint({2, 2}, {2, -1}, {2.15, -1}, 0.1));
    const auto grid = CanvasPrecision::GridPoint({-4.8, 5.15}, 5);
    Check(grid.x == -5 && grid.y == 5);
    CanvasScene::Shape preview;
    preview.kind = "arc_path";
    preview.center = {1, 1};
    preview.radius = 5;
    preview.startAngle = 0;
    preview.sweepAngle = -90;
    Check(CanvasPrecision::EndpointUnchanged(preview, CanvasPrecision::Endpoint::Start, {20, 1}));
    Check(CanvasPrecision::EndpointUnchanged(preview, CanvasPrecision::Endpoint::End, {1, -20}));
    Check(!CanvasPrecision::EndpointUnchanged(preview, CanvasPrecision::Endpoint::End, {1, 20}));
    Check(!CanvasPrecision::EndpointUnchanged(preview, CanvasPrecision::Endpoint::Start, {1, 1}));
    Check(CanvasPrecision::Preview(preview, CanvasPrecision::Endpoint::Start, {1, 20}));
    Check(std::abs(preview.startAngle - 90) < 1e-10 && std::abs(preview.sweepAngle + 180) < 1e-10);
    Check(preview.radius == 5 && preview.center.x == 1 && preview.center.y == 1);
    Check(!CanvasPrecision::Preview(preview, CanvasPrecision::Endpoint::End, {1, 1}));
    preview.startAngle = 350;
    preview.sweepAngle = 20;
    Check(CanvasPrecision::EndpointUnchanged(preview, CanvasPrecision::Endpoint::End, ArcPoint({1, 1}, 20, 10)));
    preview.sweepAngle = 360;
    Check(CanvasPrecision::EndpointUnchanged(preview, CanvasPrecision::Endpoint::End, ArcPoint({1, 1}, 20, 350)));
    preview.kind = "line_path";
    preview.start = {10, 20};
    preview.end = {20, 20};
    Check(CanvasPrecision::EndpointUnchanged(preview, CanvasPrecision::Endpoint::Start, {10, 20}));
    Check(!CanvasPrecision::EndpointUnchanged(preview, CanvasPrecision::Endpoint::Start, {10.0000000001, 20}));
    Check(!CanvasPrecision::EndpointUnchanged(preview, CanvasPrecision::Endpoint::End, {10, 20}));
    Check(!CanvasPrecision::EndpointUnchanged(preview, CanvasPrecision::Endpoint::End, {std::numeric_limits<double>::infinity(), 20}));
    Check(Valid({1e9, -1e9}));
    Check(!Valid({1e10, 0}));
    Check(!Valid({std::numeric_limits<double>::infinity(), 0}));
    Point start{-1e12, -1e12 + 1e6};
    Point end{1e12, 1e12 + 1e6};
    Check(!ClipSegment(start, end, -100, -100, 100, 100));
    start = {-1e10, -1e10};
    end = {1e10, 1e10};
    Check(ClipSegment(start, end, -100, -100, 100, 100));
    Check(std::abs(start.x + 100) < 1e-4 && std::abs(start.y + 100) < 1e-4);
    Check(std::abs(end.x - 100) < 1e-4 && std::abs(end.y - 100) < 1e-4);
    start = {50, -1000};
    end = {50, 1000};
    Check(ClipSegment(start, end, -100, -100, 100, 100));
    Check(start.x == 50 && start.y == -100 && end.x == 50 && end.y == 100);
    start = {101, -1000};
    end = {101, 1000};
    Check(!ClipSegment(start, end, -100, -100, 100, 100));
    const std::vector<std::vector<Point>> region{{{-10, -10}, {10, -10}, {10, 10}, {-10, 10}},
        {{-2, -2}, {2, -2}, {2, 2}, {-2, 2}}};
    Check(RegionDistance({5, 0}, region) == 0);
    Check(std::abs(RegionDistance({0, 0}, region) - 2) < 1e-10);
    Check(std::abs(RegionDistance({12, 12}, region) - std::sqrt(8.0)) < 1e-10);
    Check(RegionDistance({2, 0}, region) == 0);
    const auto rectangle = RectanglePoints({3, 4}, 4, 2, 90);
    Check(RegionDistance({3, 5.8}, {rectangle}) == 0);
    Check(RegionDistance({4.8, 4}, {rectangle}) > 0.79);
    const auto polygon = ParsePolygonInput("-10,-10\n10,-10\n10,10\n-10,10\n\n-2 -2\n2 -2\n2 2\n-2 2");
    Check(polygon.at("outer").size() == 4 && polygon.at("holes").size() == 1);
    for (const std::string text : {"0,0\n1,0", "0,0\n1,0\n0,1,2", "nan,0\n1,0\n0,1"})
    {
        bool rejected = false;
        try
        {
            ParsePolygonInput(text);
        }
        catch (const std::runtime_error&)
        {
            rejected = true;
        }
        Check(rejected);
    }
    return 0;
}
