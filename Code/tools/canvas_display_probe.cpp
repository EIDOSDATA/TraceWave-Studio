/** @file @brief 실제 2D/3D 제품 View의 입력과 Windows 합성 화면 시각을 함께 기록한다. */
#include "design_canvas.h"
#include "display_mesh.h"
#include "large_display_fixture.h"
#include "model_view.h"
#include "windows_display_marker.h"

#include <GL/gl.h>
#include <atomic>
#include <charconv>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

namespace
{
using Json = nlohmann::json;
namespace Marker = WindowsDisplayMarker;

constexpr int MarkerX = 16;
constexpr int MarkerY = 56;
constexpr int MarkerHeight = 8;
constexpr int PreparePollMs = 25;
constexpr int InputPeriodMs = 8;
constexpr int InputEventId = wxID_HIGHEST + 1;
constexpr int RunSeconds = 35;
constexpr std::size_t LargeModelTriangles = 1000000;
constexpr std::size_t GeneralModelTriangles = 100000;

std::int64_t Counter()
{
    LARGE_INTEGER counter{};
    QueryPerformanceCounter(&counter);
    return counter.QuadPart;
}

/** @brief 저장 프로젝트를 만들지 않고 표시 계약의 4개 층과 결정적 선/원호를 만든다. */
Json Fixture(unsigned shapes)
{
    Json scene{{"board", {{"width", 130.0}, {"height", 130.0}}},
               {"layers", Json::array()}, {"shapes", Json::array()}};
    for (unsigned index = 0; index < 4; ++index)
    {
        scene["layers"].push_back({{"id", "layer-" + std::to_string(index)}});
    }
    for (unsigned index = 0; index < shapes; ++index)
    {
        const double x = 1.0 + 2.0 * (index % 64);
        const double y = 1.0 + 2.0 * (index / 64);
        const bool line = index % 2 == 0;
        Json shape{{"id", "path-" + std::to_string(index)}, {"kind", line ? "line_path" : "arc_path"},
                   {"layer_id", "layer-" + std::to_string((index + index / 64) % 4)}, {"width", 0.25}};
        if (line)
        {
            shape["start"] = Json::array({x, y});
            shape["end"] = Json::array({x + 1.0, y + 0.75});
        }
        else
        {
            shape["center"] = Json::array({x, y});
            shape["radius"] = 0.7;
            shape["start_angle"] = 0.0;
            shape["sweep_angle"] = 180.0;
        }
        scene["shapes"].push_back(std::move(shape));
    }
    return scene;
}

struct Stamp
{
    unsigned sequence;
    std::int64_t counter;
};

/** @brief 제품의 캔버스는 그대로 쓰고 타이머, 시험 데이터, 계측만 주 창에서 소유한다. */
class ProbeFrame final : public wxFrame
{
public:
    ProbeFrame(unsigned shapes, const std::filesystem::path& directory, Json scene, bool pan, bool drag,
               std::size_t modelTriangles, HANDLE out, int& result)
        : wxFrame(nullptr, wxID_ANY, directory.empty() ? "TraceWave 2D display probe" : "TraceWave 3D display probe"),
          m_timer(this), m_pan(pan), m_drag(drag), m_modelTriangles(modelTriangles), m_shapes(shapes), m_out(out), m_result(result)
    {
        LARGE_INTEGER frequency{};
        QueryPerformanceFrequency(&frequency);
        m_frequency = frequency.QuadPart;
        m_size = directory.empty() ? wxSize(1000, 700) : wxSize(1920, 1080);
        SetClientSize(m_size);
        auto* sizer = new wxBoxSizer(wxVERTICAL);
        if (directory.empty())
        {
            m_canvas = new DesignCanvas(this);
            m_surface = m_canvas;
            sizer->Add(m_canvas, 1, wxEXPAND);
            m_canvas->onDrawDisplayMarker = [this](wxDC& dc)
            {
                DrawMarker(dc);
            };
        }
        else
        {
            const auto fixture = ReadLargeDisplayFixture(directory);
            const auto& artifact = fixture.at("artifact");
            m_knownPickingFixture = artifact.value("sha256", "") ==
                "89db886307ca72cf5ca2f43a8c97254a899d596ffea184d880c9a8667bc710d4";
            m_model = new ModelView(this);
            sizer->Add(m_model, 1, wxEXPAND);
            m_model->onDrawDisplayMarker = [this](wxWindow& surface)
            {
                DrawModelMarker(surface);
            };
            if (!m_model->LoadArtifact(wxString(directory.wstring()), artifact, fixture.at("snapshot"),
                                       artifact.at("run_id").get<std::string>()))
            {
                throw std::runtime_error("대형 표시 자료 로딩을 시작하지 못했습니다.");
            }
        }
        SetSizer(sizer);
        Layout();
        if (m_canvas != nullptr)
        {
            if (scene.is_null())
            {
                scene = Fixture(shapes);
            }
            m_layers = scene.at("layers").size();
            m_canvas->SetScene(scene);
            m_canvas->FitView();
            if (m_drag)
            {
                ChooseDragShape(scene);
            }
        }
        Bind(wxEVT_TIMER, &ProbeFrame::OnTimer, this);
        Bind(wxEVT_THREAD, &ProbeFrame::OnInput, this, InputEventId);
        Bind(wxEVT_CLOSE_WINDOW, &ProbeFrame::OnClose, this);
        Centre();
        m_prepare = Counter();
        m_timer.Start(PreparePollMs);
    }

    ~ProbeFrame() override
    {
        StopThreads();
    }

private:
    /** @brief 화면과 같은 버퍼에만 입력 번호를 기록한다. 평상시 제품 창에는 표식이 없다. */
    void DrawMarker(wxDC& dc)
    {
        const auto sequence = static_cast<unsigned>(m_inputs.size());
        const std::uint32_t code = Marker::Signature | sequence;
        dc.SetPen(*wxTRANSPARENT_PEN);
        for (int cell = 0; cell < Marker::Cells; ++cell)
        {
            dc.SetBrush((code & (1u << cell)) != 0 ? *wxWHITE_BRUSH : *wxBLACK_BRUSH);
            dc.DrawRectangle(MarkerX + cell * Marker::CellWidth, MarkerY, Marker::CellWidth, MarkerHeight);
        }
        StampPaint(sequence);
    }

    /** @brief 같은 ModelView의 SwapBuffers 직전에 작은 번호 표식을 그린다. */
    void DrawModelMarker(wxWindow& surface)
    {
        m_surface = &surface;
        if (!m_swapIntervalChecked)
        {
            m_swapIntervalChecked = true;
            const auto proc = wglGetProcAddress("wglGetSwapIntervalEXT");
            const auto raw = reinterpret_cast<std::uintptr_t>(proc);
            if (raw > 3 && raw != UINTPTR_MAX)
            {
                int (APIENTRY* interval)() = nullptr;
                static_assert(sizeof(interval) == sizeof(proc));
                std::memcpy(&interval, &proc, sizeof(interval));
                m_swapInterval = interval();
            }
        }
        const auto size = surface.GetClientSize();
        const double scale = surface.GetContentScaleFactor();
        const auto sequence = static_cast<unsigned>(m_inputs.size());
        const std::uint32_t code = Marker::Signature | sequence;
        glPushAttrib(GL_ENABLE_BIT | GL_CURRENT_BIT);
        glDisable(GL_DEPTH_TEST);
        glDisable(GL_DITHER);
        glMatrixMode(GL_PROJECTION);
        glPushMatrix();
        glLoadIdentity();
        glOrtho(0.0, size.x * scale, size.y * scale, 0.0, -1.0, 1.0);
        glMatrixMode(GL_MODELVIEW);
        glPushMatrix();
        glLoadIdentity();
        glBegin(GL_QUADS);
        for (int cell = 0; cell < Marker::Cells; ++cell)
        {
            const float shade = (code & (1u << cell)) != 0 ? 1.0f : 0.0f;
            const int left = MarkerX + cell * Marker::CellWidth;
            glColor3f(shade, shade, shade);
            glVertex2i(left, MarkerY);
            glVertex2i(left + Marker::CellWidth, MarkerY);
            glVertex2i(left + Marker::CellWidth, MarkerY + MarkerHeight);
            glVertex2i(left, MarkerY + MarkerHeight);
        }
        glEnd();
        glPopMatrix();
        glMatrixMode(GL_PROJECTION);
        glPopMatrix();
        glMatrixMode(GL_MODELVIEW);
        glPopAttrib();
        StampPaint(sequence);
    }

    void StampPaint(unsigned sequence)
    {
        if (m_paints.empty() || m_paints.back().sequence != sequence)
        {
            m_paints.push_back({sequence, Counter()});
        }
    }

    void StartReader()
    {
        const auto frame = static_cast<HWND>(GetHandle());
        const auto canvas = static_cast<HWND>(m_surface->GetHandle());
        m_reader = std::make_unique<Marker::Reader>(frame, canvas, POINT{MarkerX, MarkerY + MarkerHeight / 2});
        m_capture = std::thread([this]()
        {
            try
            {
                while (!m_stop.load())
                {
                    const auto frame = m_reader->Next();
                    if (frame)
                    {
                        if (m_presents.size() >= 65536)
                        {
                            throw std::runtime_error("합성 화면 표본 상한을 초과했습니다.");
                        }
                        m_presents.push_back(*frame);
                        if (frame->sequence == 0)
                        {
                            m_ready.store(true);
                        }
                    }
                }
            }
            catch (const std::exception& error)
            {
                m_readerError = error.what();
                m_failed.store(true);
            }
        });
        m_surface->Refresh(false);
    }

    /** @brief 고해상도 대기 타이머를 시험 프로세스 안에서 열고 대기 입력을 하나로 제한한다. */
    void StartInputs()
    {
        m_end = m_start + RunSeconds * m_frequency;
        m_source = std::thread([this]()
        {
            try
            {
                std::unique_ptr<void, decltype(&CloseHandle)> timer(
                    CreateWaitableTimerExW(nullptr, nullptr, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION,
                                           SYNCHRONIZE | TIMER_MODIFY_STATE), &CloseHandle);
                LARGE_INTEGER due{};
                due.QuadPart = -10000LL * InputPeriodMs;
                if (!timer || !SetWaitableTimer(timer.get(), &due, InputPeriodMs, nullptr, nullptr, FALSE))
                {
                    throw std::runtime_error("시험 입력용 고해상도 타이머를 시작하지 못했습니다.");
                }
                while (!m_stop.load())
                {
                    if (WaitForSingleObject(timer.get(), 150) != WAIT_OBJECT_0)
                    {
                        throw std::runtime_error("시험 입력용 타이머의 대기 시간이 초과됐습니다.");
                    }
                    const auto now = Counter();
                    if (now >= m_end || m_stop.load())
                    {
                        break;
                    }
                    m_offers.push_back(now);
                    if (!m_pending.exchange(true))
                    {
                        wxQueueEvent(this, new wxThreadEvent(wxEVT_THREAD, InputEventId));
                    }
                }
            }
            catch (const std::exception& error)
            {
                m_sourceError = error.what();
                m_sourceFailed.store(true);
            }
        });
    }

    void StopThreads()
    {
        m_stop.store(true);
        if (m_source.joinable())
        {
            m_source.join();
        }
        if (m_capture.joinable())
        {
            m_capture.join();
        }
    }

    /** @brief 입력 타이머의 이벤트를 제품 확대, 이동 또는 3D 처리기에 전달한다. */
    void OnInput(wxThreadEvent&)
    {
        m_pending.store(false);
        const auto now = Counter();
        if (m_finished || now >= m_end)
        {
            return;
        }
        if (m_model != nullptr)
        {
            const auto step = m_inputs.size();
            m_inputs.push_back(now);
            if ((step / 120) % 2 == 0)
            {
                m_model->RotateView(1.2, 0.0);
            }
            else
            {
                m_model->PanView(step % 120 < 60 ? 0.75 : -0.75, 0.0);
            }
            return;
        }
        if (m_pan || m_drag)
        {
            MoveCanvas(now);
            return;
        }
        const auto size = m_canvas->GetClientSize();
        const bool zoomIn = m_inputs.size() % 2 == 0;
        wxMouseEvent event(wxEVT_MOUSEWHEEL);
        event.SetEventObject(m_canvas);
        event.SetPosition(wxPoint(size.x / 2, size.y / 2));
        event.m_wheelDelta = 120;
        event.m_wheelRotation = zoomIn ? 120 : -120;
        m_inputs.push_back(now);
        if (!m_canvas->GetEventHandler()->ProcessEvent(event))
        {
            Finish("확대 이벤트가 제품 캔버스에 전달되지 않았습니다.");
            Close();
        }
    }

    /** @brief 캔버스가 실제로 선택할 수 있는 움직이는 선을 시험 대상으로 찾는다. */
    void ChooseDragShape(const Json& scene)
    {
        m_canvas->SetEditingEnabled(true);
        const auto size = m_canvas->GetClientSize();
        std::set<std::string> movableLines;
        for (const auto& row : scene.at("shapes"))
        {
            if (row.value("kind", "") == "line_path" && row.value("movable", false))
            {
                movableLines.insert(row.at("id").get<std::string>());
            }
        }
        for (const auto& row : scene.at("shapes"))
        {
            if (row.value("kind", "") != "line_path" || !row.value("movable", false))
            {
                continue;
            }
            const auto& start = row.at("start");
            const auto& end = row.at("end");
            const wxPoint pixel = m_canvas->WorldToScreen({
                (start.at(0).get<double>() + end.at(0).get<double>()) / 2.0,
                (start.at(1).get<double>() + end.at(1).get<double>()) / 2.0});
            if (pixel.x > 90 && pixel.y > 90 && pixel.x < size.x - 90 && pixel.y < size.y - 90)
            {
                const auto hit = m_canvas->HitTest(pixel);
                if (movableLines.count(hit) != 0)
                {
                    m_dragAnchor = pixel;
                    m_dragIdentity = hit;
                    return;
                }
            }
        }
        throw std::runtime_error("표시 영역에서 드래그할 수 있는 시험 선을 찾지 못했습니다.");
    }

    /** @brief 실제 가운데 버튼 이동 또는 선택된 선의 드래그를 반복한다. */
    void MoveCanvas(std::int64_t now)
    {
        auto* handler = m_canvas->GetEventHandler();
        const auto size = m_canvas->GetClientSize();
        const wxPoint center = m_drag ? m_dragAnchor : wxPoint(size.x / 2, size.y / 2);
        if (m_inputs.empty())
        {
            wxMouseEvent down(m_drag ? wxEVT_LEFT_DOWN : wxEVT_MIDDLE_DOWN);
            down.SetEventObject(m_canvas);
            down.SetPosition(center);
            if (!handler->ProcessEvent(down) || !m_canvas->HasCapture() ||
                (m_drag && m_canvas->Selection() != m_dragIdentity))
            {
                Finish("캔버스 이동 또는 선택된 선의 드래그를 시작하지 못했습니다.");
                Close();
                return;
            }
        }
        const int step = static_cast<int>((m_inputs.size() + 1) % 120);
        const int distance = step <= 60 ? step : 120 - step;
        wxMouseEvent motion(wxEVT_MOTION);
        motion.SetEventObject(m_canvas);
        motion.SetPosition(center + wxPoint(distance + (m_drag ? 6 : 0), 0));
        motion.SetMiddleDown(!m_drag);
        motion.SetLeftDown(m_drag);
        m_inputs.push_back(now);
        if (!handler->ProcessEvent(motion) || !m_canvas->HasCapture())
        {
            Finish("캔버스 이동 또는 드래그가 끊겼습니다.");
            Close();
        }
    }

    /** @brief 합성 구간 종료 뒤 실제 wxGLCanvas 클릭으로 두 바디와 숨긴 층을 확인한다. */
    void CheckModelClicks()
    {
        m_model->SetView("top");
        m_model->FitView();
        const auto size = m_surface->GetClientSize();
        const auto click = [this](const wxPoint& point, const std::string& expected)
        {
            wxMouseEvent down(wxEVT_LEFT_DOWN);
            wxMouseEvent up(wxEVT_LEFT_UP);
            const auto start = Counter();
            for (auto* event : {&down, &up})
            {
                event->SetEventObject(m_surface);
                event->SetPosition(point);
                DisplayMesh::Require(m_surface->GetEventHandler()->ProcessEvent(*event),
                    "3D 클릭이 제품 캔버스에 전달되지 않았습니다.");
            }
            const auto end = Counter();
            const auto actual = m_model->Selection();
            DisplayMesh::Require(actual == expected, "3D 클릭의 실제 원본 ID가 예상과 다릅니다.");
            m_modelClicks.push_back({{"x", point.x}, {"y", point.y}, {"source_id", actual},
                {"input_handler_ms", 1000.0 * (end - start) / m_frequency}});
        };
        const wxPoint top(size.x / 2, size.y / 4);
        click({size.x / 2, size.y * 3 / 4}, "00000000-0000-0000-0000-000000000014");
        click(top, "00000000-0000-0000-0000-000000000015");
        m_model->SetLayerVisible("00000000-0000-0000-0000-00000000001f", false);
        click(top, "");
        m_model->SetLayerVisible("00000000-0000-0000-0000-00000000001f", true);
        click(top, "00000000-0000-0000-0000-000000000015");
        click({size.x / 8, size.y / 2}, "");
        m_surface->Update();
        const auto fit = m_model->SubmittedTriangleCount();
        m_model->PanView(2.0 * size.x, 0.0);
        m_surface->Update();
        const auto outside = m_model->SubmittedTriangleCount();
        m_model->FitView();
        m_surface->Update();
        const auto restored = m_model->SubmittedTriangleCount();
        DisplayMesh::Require(fit == m_model->TriangleCount() && outside == 0 && restored == fit,
            "3D 화면 범위 최적화가 보이는 삼각형을 빼거나 화면 밖 바디를 그렸습니다.");
        m_modelVisibleTriangles = {fit, outside, restored};
    }

    void OnTimer(wxTimerEvent&)
    {
        try
        {
            const auto now = Counter();
            if (m_model != nullptr && !m_model->Error().empty())
            {
                throw std::runtime_error(m_model->Error());
            }
            if (m_model != nullptr && m_model->HasMesh() && m_model->TriangleCount() != m_modelTriangles)
            {
                throw std::runtime_error("3D 합성 시험의 삼각형 수가 지정한 자료와 다릅니다.");
            }
            if (!m_reader && m_surface != nullptr && m_surface->GetClientSize() == m_size && !m_paints.empty() &&
                (m_model == nullptr || m_model->HasMesh()) &&
                GetForegroundWindow() == static_cast<HWND>(GetHandle()))
            {
                StartReader();
            }
            if (m_failed.load())
            {
                throw std::runtime_error(m_readerError);
            }
            if (m_sourceFailed.load())
            {
                throw std::runtime_error(m_sourceError);
            }
            if (m_start == 0)
            {
                if (m_ready.load())
                {
                    m_start = Counter();
                    StartInputs();
                }
                else if (now - m_prepare > 8 * m_frequency)
                {
                    throw std::runtime_error("시험 창의 초기 화면 표식을 읽지 못했습니다.");
                }
                return;
            }
            if (now - m_end >= m_frequency / 4)
            {
                if (m_knownPickingFixture)
                {
                    StopThreads();
                    CheckModelClicks();
                }
                Finish("");
                Close();
            }
        }
        catch (const std::exception& error)
        {
            Finish(error.what());
            Close();
        }
    }

    void OnClose(wxCloseEvent& event)
    {
        if (!m_finished)
        {
            Finish("표본 수집 중 시험 창이 닫혔습니다.");
        }
        event.Skip();
    }

    void Finish(const std::string& error)
    {
        m_finished = true;
        m_timer.Stop();
        StopThreads();
        if (m_pan || m_drag)
        {
            m_canvas->CancelGesture();
        }
        const auto& problem = !error.empty() ? error : (!m_readerError.empty() ? m_readerError : m_sourceError);
        const bool success = problem.empty();
        Json paints = Json::array(), presents = Json::array();
        for (const auto& stamp : m_paints)
        {
            paints.push_back({stamp.sequence, stamp.counter});
        }
        for (const auto& frame : m_presents)
        {
            presents.push_back({frame.presented, frame.accumulated,
                                frame.sequence ? Json(*frame.sequence) : Json(nullptr)});
        }
        const auto display = m_reader ? m_reader->OutputSize() : SIZE{};
        const auto size = m_surface != nullptr ? m_surface->GetClientSize() : wxSize{};
        const bool model = m_model != nullptr;
        const Json report{{"schema", "rfad.windows-canvas-display-trace/0.1"}, {"ok", success},
                          {"error", problem}, {"qpc_frequency", m_frequency},
                          {"display", {display.cx, display.cy}}, {"refresh_hz", m_reader ? m_reader->RefreshRate() : 0},
                          {"canvas", {size.x, size.y}}, {"dpi", m_surface != nullptr ? m_surface->GetDPI().x : GetDPI().x},
                          {"shapes", model ? 0 : m_shapes}, {"layers", model ? m_model->BodyCount() : m_layers},
                          {"model_clicks_after_navigation", m_modelClicks},
                          {"model_visible_triangles", m_modelVisibleTriangles},
                          {"triangles", model ? m_model->TriangleCount() : 0}, {"target_fps", m_modelTriangles == LargeModelTriangles ? 30 : 60},
                          {"workload", model ? "model-rotate-pan" : (m_pan ? "canvas-middle-pan" : (m_drag ? "canvas-geometry-drag" : "canvas-wheel-zoom"))},
                          {"renderer", model ? m_model->RendererDescription() : "wxGraphicsContext"},
                          {"swap_interval", m_swapInterval ? Json(*m_swapInterval) : Json(nullptr)},
                          {"vertex_buffer", model ? m_model->VertexBufferDiagnostics() : Json(nullptr)},
                          {"start_qpc", m_start}, {"end_qpc", m_end}, {"requested_timer_ms", InputPeriodMs},
                          {"timer", "high-resolution-waitable"}, {"offers_qpc", m_offers},
                          {"inputs_qpc", m_inputs}, {"painted", paints}, {"desktop_updates", presents}};
        const std::string line = report.dump() + "\n";
        DWORD written{};
        const bool saved = WriteFile(m_out, line.data(), static_cast<DWORD>(line.size()), &written, nullptr) &&
            written == line.size();
        m_result = success && saved ? 0 : 3;
    }

    wxTimer m_timer;
    DesignCanvas* m_canvas = nullptr;
    ModelView* m_model = nullptr;
    std::size_t m_layers = 0;
    wxWindow* m_surface = nullptr;
    wxSize m_size;
    std::optional<int> m_swapInterval;
    bool m_swapIntervalChecked = false;
    bool m_knownPickingFixture = false;
    Json m_modelClicks = Json::array();
    Json m_modelVisibleTriangles = Json::array();
    bool m_pan;
    bool m_drag;
    wxPoint m_dragAnchor;
    std::string m_dragIdentity;
    std::size_t m_modelTriangles;
    unsigned m_shapes;
    HANDLE m_out;
    int& m_result;
    std::unique_ptr<Marker::Reader> m_reader;
    std::thread m_capture, m_source;
    std::atomic<bool> m_ready{false}, m_stop{false}, m_failed{false};
    std::atomic<bool> m_sourceFailed{false}, m_pending{false};
    std::string m_readerError, m_sourceError;
    std::vector<std::int64_t> m_offers;
    std::vector<std::int64_t> m_inputs;
    std::vector<Stamp> m_paints;
    std::vector<Marker::Frame> m_presents;
    std::int64_t m_frequency = 0;
    std::int64_t m_prepare = 0, m_start = 0, m_end = 0;
    bool m_finished = false;
};

class ProbeApp final : public wxApp
{
public:
    bool OnInit() override
    {
        return true;
    }
};
}

wxIMPLEMENT_APP_NO_MAIN(ProbeApp);

int main(int argc, char** argv)
{
    unsigned shapes = 4096;
    std::filesystem::path directory;
    const bool largeModel = argc == 4 && std::string_view(argv[2]) == "--model";
    const bool generalModel = argc == 4 && std::string_view(argv[2]) == "--model-general";
    const bool model = largeModel || generalModel;
    if (model)
    {
        directory = std::filesystem::absolute(std::filesystem::path(argv[3]));
    }
    if (argc == 3)
    {
        const std::string argument = argv[2];
        const auto number = std::from_chars(argument.data(), argument.data() + argument.size(), shapes);
        if (number.ec != std::errc{} || number.ptr != argument.data() + argument.size() || shapes == 0 || shapes > 4096)
        {
            return 2;
        }
    }
    const bool pan = argc == 4 && std::string_view(argv[2]) == "--scene-pan";
    const bool drag = argc == 4 && std::string_view(argv[2]) == "--scene-drag";
    const bool projectedScene = pan || drag || (argc == 4 && std::string_view(argv[2]) == "--scene");
    if (argc != 2 && argc != 3 && !model && !projectedScene)
    {
        return 2;
    }
    const auto path = std::filesystem::path(argv[1]);
    const HANDLE handle = CreateFileW(path.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr, CREATE_NEW,
                                      FILE_ATTRIBUTE_NORMAL, nullptr);
    if (handle == INVALID_HANDLE_VALUE)
    {
        return 2;
    }
    const std::unique_ptr<void, decltype(&CloseHandle)> out(handle, &CloseHandle);
    if (!wxEntryStart(argc, argv))
    {
        return 2;
    }
    int result = 3;
    try
    {
        if (wxTheApp->CallOnInit())
        {
            Json scene;
            if (projectedScene)
            {
                const std::filesystem::path source(argv[3]);
                if (std::filesystem::file_size(source) > 24 * 1024 * 1024)
                {
                    throw std::runtime_error("표시 시험 입력이 24 MiB를 초과했습니다.");
                }
                std::ifstream stream(source, std::ios::binary);
                scene = Json::parse(stream);
                shapes = static_cast<unsigned>(scene.at("shapes").size());
            }
            const std::size_t triangles = largeModel ? LargeModelTriangles : generalModel ? GeneralModelTriangles : 0;
            auto* window = new ProbeFrame(shapes, directory, std::move(scene), pan, drag, triangles, out.get(), result);
            wxTheApp->SetTopWindow(window);
            window->Show();
            wxTheApp->OnRun();
            wxTheApp->OnExit();
        }
    }
    catch (const std::exception& error)
    {
        std::cerr << error.what() << '\n';
    }
    wxEntryCleanup();
    return result;
}
