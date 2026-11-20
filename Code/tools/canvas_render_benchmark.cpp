/** @file @brief 제품의 2D renderer를 같은 wxWidgets GDI 경로로 계측한다. */
#include "canvas_renderer.h"
#include <wx/app.h>
#include <wx/dcmemory.h>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <string_view>
#include <vector>
#include <windows.h>
#include <psapi.h>

/** @brief 표시 엔진을 실행할 최소 wx application이다. */
class BenchmarkApp final : public wxApp
{
public:
    bool OnInit() override
    {
        return true;
    }
};
wxIMPLEMENT_APP_NO_MAIN(BenchmarkApp);

/** @brief 같은 형상 수에서 전체 보기와 확대 후 이동의 표시 비용을 분리한다. */
struct RenderFixture
{
    const char* name;
    int count;
    double spacing;
    CanvasViewport viewport;
    double targetFps;
};

/** @brief 실제 표시 함수의 frame 비용을 기록하며 compositor FPS와 구분한다. */
int main(int argc, char** argv)
{
    const bool f1 = argc == 3 && std::string_view(argv[2]) == "--f1-render";
    if ((argc != 2 && !f1) || std::filesystem::exists(argv[1]))
    {
        return 2;
    }
    const std::string outputName = argv[1];
    const std::vector<RenderFixture> fixtures = f1
        ? std::vector<RenderFixture>{{"f1_overview", 10000, 4.0, {1000, 700, {200, 200}, 1.6}, 60.0},
                                     {"f1_zoom_pan", 10000, 4.0, {1000, 700, {200, 200}, 8.0}, 60.0}}
        : std::vector<RenderFixture>{{"small", 200, 1.0, {1000, 700, {50, 15}, 8.0}, 60.0},
                                     {"initial_large", 3000, 1.0, {1000, 700, {50, 15}, 8.0}, 30.0}};
    if (std::any_of(fixtures.begin(), fixtures.end(), [&](const auto& fixture)
        {
            return f1 && std::filesystem::exists(outputName + "." + fixture.name + ".rgb");
        }) || !wxEntryStart(argc, argv))
    {
        return 2;
    }
    wxTheApp->CallOnInit();
    auto* frame = new wxFrame(nullptr, wxID_ANY, "TraceWave renderer benchmark");
    nlohmann::json results = nlohmann::json::array();
    bool rasterWritten = true;
    for (const auto& fixture : fixtures)
    {
        std::vector<CanvasScene::Shape> shapes;
        shapes.reserve(static_cast<std::size_t>(fixture.count));
        for (int index = 0; index < fixture.count; ++index)
        {
            CanvasScene::Shape shape;
            shape.kind = index % 2 == 0 ? "line_path" : "arc_path";
            shape.width = 0.3;
            shape.start = {(index % 100) * fixture.spacing, (index / 100) * fixture.spacing};
            shape.end = {shape.start.x + 2, shape.start.y + 1};
            shape.center = shape.start;
            shape.radius = 1.0;
            shape.startAngle = 0;
            shape.sweepAngle = 180;
            if (f1 && index == 0)
            {
                // @brief 양 끝이 화면 밖이어도 화면을 가로지르는 선을 비교한다.
                shape.start = {0.0, 200.0};
                shape.end = {400.0, 200.0};
            }
            else if (f1 && index == 1)
            {
                // @brief 확대 화면 왼쪽 밖의 중심에서 도체와 선택 강조가 들어오는 원호이다.
                shape.center = {130.0, 201.0};
                shape.radius = 8.0;
                shape.width = 0.8;
            }
            shapes.push_back(shape);
        }
        wxBitmap bitmap(fixture.viewport.width, fixture.viewport.height);
        wxMemoryDC dc(bitmap);
        std::vector<double> times;
        for (int iteration = 0; iteration < 65; ++iteration)
        {
            auto viewport = fixture.viewport;
            if (f1)
            {
                viewport.center.x += (iteration % 21 - 10) * 0.5;
                viewport.center.y += (iteration % 17 - 8) * 0.4;
            }
            const auto begin = std::chrono::steady_clock::now();
            dc.SetBackground(*wxWHITE_BRUSH);
            dc.Clear();
            {
                CanvasRenderer renderer(*frame, dc, viewport);
                renderer.DrawGrid(true);
                for (const auto& shape : shapes)
                {
                    renderer.DrawShape(shape, {0, 0}, wxColour(100, 70, 160), f1 && &shape == &shapes[1]);
                }
            }
            if (iteration >= 5)
            {
                times.push_back(
                    std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - begin).count());
            }
        }
        auto orderedTimes = times;
        std::sort(orderedTimes.begin(), orderedTimes.end());
        const auto percentile = [&](std::size_t percent)
        {
            return orderedTimes[(orderedTimes.size() * percent + 99) / 100 - 1];
        };
        const double budget = 1000.0 / fixture.targetFps;
        const auto middle = orderedTimes.size() / 2;
        const double median = f1 ? (orderedTimes[middle - 1] + orderedTimes[middle]) / 2.0 : orderedTimes[middle];
        const double p95 = f1 ? percentile(95) : orderedTimes[orderedTimes.size() * 95 / 100];
        nlohmann::json result{{"fixture", fixture.name},
                              {"shapes", fixture.count},
                              {"samples", times.size()},
                              {"p50_render_ms", median},
                              {"p95_render_ms", p95},
                              {"target_render_budget_ms", budget},
                              {"render_budget_met", p95 <= budget}};
        if (f1)
        {
            result["render_times_ms"] = times;
            result["p99_render_ms"] = percentile(99);
            result["maximum_render_ms"] = orderedTimes.back();
            // @brief 마지막 화면의 실제 RGB 픽셀을 보존하고 그리기 시간에서는 제외한다.
            dc.SelectObject(wxNullBitmap);
            const wxImage pixels = bitmap.ConvertToImage();
            std::ofstream raster(outputName + "." + fixture.name + ".rgb", std::ios::binary);
            if (pixels.IsOk())
            {
                raster.write(reinterpret_cast<const char*>(pixels.GetData()),
                             static_cast<std::streamsize>(3) * pixels.GetWidth() * pixels.GetHeight());
            }
            rasterWritten = rasterWritten && pixels.IsOk() && raster.good();
        }
        results.push_back(std::move(result));
    }
    PROCESS_MEMORY_COUNTERS_EX memory{};
    memory.cb = sizeof(memory);
    GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&memory), sizeof(memory));
    const nlohmann::json report{{"schema", "rfad.canvas-render-benchmark/0.1"},
                                {"cases", results},
                                {"working_set_bytes", memory.WorkingSetSize},
                                {"private_bytes", memory.PrivateUsage},
                                {"scope", "Product 2D renderer in wxMemoryDC, 1000x700 pixels, one Windows host"},
                                {"interactive_fps_tested", false},
                                {"service_memory_included", false}};
    std::ofstream output(outputName);
    output << report.dump(2) << '\n';
    delete frame;
    wxTheApp->OnExit();
    wxEntryCleanup();
    return output && rasterWritten ? 0 : 3;
}
