/** @file @brief 제품의 2D renderer를 같은 wxWidgets GDI 경로로 계측한다. */
#include "canvas_renderer.h"
#include <wx/app.h>
#include <wx/dcmemory.h>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
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

/** @brief 실제 표시 함수의 frame 비용을 기록하며 compositor FPS와 구분한다. */
int main(int argc, char** argv)
{
    if (argc != 2 || std::filesystem::exists(argv[1]) || !wxEntryStart(argc, argv))
    {
        return 2;
    }
    wxTheApp->CallOnInit();
    auto* frame = new wxFrame(nullptr, wxID_ANY, "TraceWave renderer benchmark");
    nlohmann::json results = nlohmann::json::array();
    for (const int count : {200, 3000})
    {
        std::vector<CanvasScene::Shape> shapes;
        for (int index = 0; index < count; ++index)
        {
            CanvasScene::Shape shape;
            shape.kind = index % 2 == 0 ? "line_path" : "arc_path";
            shape.width = 0.3;
            shape.start = {static_cast<double>(index % 100), static_cast<double>(index / 100)};
            shape.end = {shape.start.x + 2, shape.start.y + 1};
            shape.center = shape.start;
            shape.radius = 1.0;
            shape.startAngle = 0;
            shape.sweepAngle = 180;
            shapes.push_back(shape);
        }
        wxBitmap bitmap(1000, 700);
        wxMemoryDC dc(bitmap);
        std::vector<double> times;
        for (int iteration = 0; iteration < 65; ++iteration)
        {
            const auto begin = std::chrono::steady_clock::now();
            dc.SetBackground(*wxWHITE_BRUSH);
            dc.Clear();
            {
                CanvasRenderer renderer(*frame, dc, {1000, 700, {50, 15}, 8.0});
                renderer.DrawGrid(true);
                for (const auto& shape : shapes)
                {
                    renderer.DrawShape(shape, {0, 0}, wxColour(100, 70, 160), false);
                }
            }
            if (iteration >= 5)
            {
                times.push_back(
                    std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - begin).count());
            }
        }
        std::sort(times.begin(), times.end());
        const double budget = count == 200 ? 1000.0 / 60 : 1000.0 / 30;
        results.push_back({{"shapes", count},
                           {"samples", times.size()},
                           {"p50_render_ms", times[times.size() / 2]},
                           {"p95_render_ms", times[times.size() * 95 / 100]},
                           {"target_render_budget_ms", budget},
                           {"render_budget_met", times[times.size() * 95 / 100] <= budget}});
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
    std::ofstream output(argv[1]);
    output << report.dump(2) << '\n';
    delete frame;
    wxTheApp->OnExit();
    wxEntryCleanup();
    return output ? 0 : 3;
}
