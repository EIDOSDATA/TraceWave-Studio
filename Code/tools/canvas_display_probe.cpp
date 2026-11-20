/** @file @brief 실제 DesignCanvas 창에서 확대 입력과 합성 화면 시각을 함께 기록한다. */
#include "design_canvas.h"
#include "windows_display_marker.h"

#include <atomic>
#include <charconv>
#include <filesystem>
#include <iostream>
#include <string>
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
    ProbeFrame(unsigned shapes, HANDLE out, int& result)
        : wxFrame(nullptr, wxID_ANY, "TraceWave 2D display probe"), m_timer(this), m_shapes(shapes), m_out(out),
          m_result(result)
    {
        LARGE_INTEGER frequency{};
        QueryPerformanceFrequency(&frequency);
        m_frequency = frequency.QuadPart;
        SetClientSize(1000, 700);
        auto* sizer = new wxBoxSizer(wxVERTICAL);
        m_canvas = new DesignCanvas(this);
        sizer->Add(m_canvas, 1, wxEXPAND);
        SetSizer(sizer);
        Layout();
        m_canvas->SetScene(Fixture(shapes));
        m_canvas->FitView();
        m_canvas->onDrawDisplayMarker = [this](wxDC& dc)
        {
            DrawMarker(dc);
        };
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
        if (m_paints.empty() || m_paints.back().sequence != sequence)
        {
            m_paints.push_back({sequence, Counter()});
        }
    }

    void StartReader()
    {
        const auto frame = static_cast<HWND>(GetHandle());
        const auto canvas = static_cast<HWND>(m_canvas->GetHandle());
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
        m_canvas->Refresh(false);
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

    /** @brief 시스템 입력을 바꾸지 않고 평소 확대 입력 처리기에 같은 종류의 이벤트를 전달한다. */
    void OnInput(wxThreadEvent&)
    {
        m_pending.store(false);
        const auto now = Counter();
        if (m_finished || now >= m_end)
        {
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

    void OnTimer(wxTimerEvent&)
    {
        try
        {
            const auto now = Counter();
            if (!m_reader && !m_paints.empty() && GetForegroundWindow() == static_cast<HWND>(GetHandle()))
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
        const auto size = m_canvas->GetClientSize();
        const Json report{{"schema", "rfad.windows-canvas-display-trace/0.1"}, {"ok", success},
                          {"error", problem}, {"qpc_frequency", m_frequency},
                          {"display", {display.cx, display.cy}}, {"refresh_hz", m_reader ? m_reader->RefreshRate() : 0},
                          {"canvas", {size.x, size.y}}, {"dpi", m_canvas->GetDPI().x},
                          {"shapes", m_shapes}, {"layers", 4}, {"workload", "canvas-wheel-zoom"},
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
    if (argc == 3)
    {
        const std::string argument = argv[2];
        const auto number = std::from_chars(argument.data(), argument.data() + argument.size(), shapes);
        if (number.ec != std::errc{} || number.ptr != argument.data() + argument.size() || shapes == 0 || shapes > 4096)
        {
            return 2;
        }
    }
    if (argc != 2 && argc != 3)
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
            auto* window = new ProbeFrame(shapes, out.get(), result);
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
