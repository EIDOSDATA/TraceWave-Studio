/** @file @brief OpenGL의 SwapBuffers와 desktop 합성 표식을 대응한다. */
#include "studio_model_display_probe.h"
#include "model_view.h"
#include "../../tools/windows_display_marker.h"

#include <GL/gl.h>
#include <mmsystem.h>
#include <algorithm>
#include <atomic>
#include <climits>
#include <exception>
#include <stdexcept>
#include <thread>
#include <vector>
#include <wx/weakref.h>

namespace
{
namespace Marker = WindowsDisplayMarker;
constexpr POINT MarkerOrigin{8, 8};
constexpr int RunSeconds = 35;
constexpr int InputPeriodMs = 8;

std::int64_t Counter()
{
    LARGE_INTEGER value{};
    QueryPerformanceCounter(&value);
    return value.QuadPart;
}
}

struct StudioModelDisplayProbe::State
{
    explicit State(ModelView& view) : model(&view)
    {
        LARGE_INTEGER clock{};
        QueryPerformanceFrequency(&clock);
        frequency = clock.QuadPart;
        deadline = Counter() + 8 * frequency;
    }

    /** @brief 현재 back buffer의 작은 띠에 그리기와 대응되는 번호를 기록한다. */
    void Stamp(wxWindow& window)
    {
        surface = &window;
        const unsigned sequence = static_cast<unsigned>(inputs.size());
        const auto code = Marker::Signature | sequence;
        GLint viewport[4]{};
        glGetIntegerv(GL_VIEWPORT, viewport);
        glPushAttrib(GL_ENABLE_BIT | GL_SCISSOR_BIT | GL_COLOR_BUFFER_BIT);
        glEnable(GL_SCISSOR_TEST);
        glDisable(GL_DITHER);
        for (int cell = 0; cell < Marker::Cells; ++cell)
        {
            const auto shade = (code & (1u << cell)) != 0 ? 1.0f : 0.0f;
            glScissor(MarkerOrigin.x + cell * Marker::CellWidth, viewport[3] - MarkerOrigin.y - 4,
                      Marker::CellWidth, 4);
            glClearColor(shade, shade, shade, 1.0f);
            glClear(GL_COLOR_BUFFER_BIT);
        }
        glPopAttrib();
        if (sequence != lastPaint)
        {
            painted.push_back({sequence, Counter()});
            lastPaint = sequence;
        }
    }

    void ReadDesktop()
    {
        try
        {
            while (!stopped.load())
            {
                if (const auto frame = reader->Next())
                {
                    if (frames.size() >= 15000)
                    {
                        throw std::runtime_error("Studio 3D 합성 표본 상한을 초과했습니다.");
                    }
                    frames.push_back(*frame);
                    if (frame->sequence == 0)
                    {
                        ready.store(true);
                    }
                }
            }
        }
        catch (...)
        {
            captureError = std::current_exception();
            captureFailed.store(true);
        }
    }

    wxWeakRef<ModelView> model;
    wxWeakRef<wxWindow> surface;
    std::unique_ptr<Marker::Reader> reader;
    std::thread capture;
    std::atomic<bool> stopped{false}, ready{false}, captureFailed{false};
    std::exception_ptr captureError, inputError;
    std::vector<std::int64_t> inputs;
    std::vector<Marker::Frame> frames;
    Json painted = Json::array();
    unsigned lastPaint = UINT_MAX;
    std::int64_t frequency = 0, deadline = 0, start = 0, end = 0;
    bool finerTimer = false;
};

StudioModelDisplayProbe::StudioModelDisplayProbe(ModelView& model) : m_state(std::make_unique<State>(model))
{
    m_state->finerTimer = timeBeginPeriod(1) == TIMERR_NOERROR;
    model.SetDisplayMarker([state = m_state.get()](wxWindow& surface) { state->Stamp(surface); });
    if (!Start(InputPeriodMs))
    {
        m_state->inputError = std::make_exception_ptr(std::runtime_error("Studio 3D 입력 타이머를 시작하지 못했습니다."));
    }
}

StudioModelDisplayProbe::~StudioModelDisplayProbe()
{
    Stop();
    if (m_state->model)
    {
        m_state->model->SetDisplayMarker({});
    }
    m_state->stopped.store(true);
    if (m_state->capture.joinable())
    {
        m_state->capture.join();
    }
    if (m_state->finerTimer)
    {
        timeEndPeriod(1);
    }
}

void StudioModelDisplayProbe::Notify()
{
    auto& state = *m_state;
    try
    {
        const auto now = Counter();
        if (!state.model)
        {
            throw std::runtime_error("합성 계측 중 3D 창이 닫혔습니다.");
        }
        if (!state.ready.load())
        {
            if (now >= state.deadline)
            {
                throw std::runtime_error("전체 Studio에서 초기 3D 합성 표식을 읽지 못했습니다.");
            }
            if (state.surface && !state.reader)
            {
                const auto root = static_cast<HWND>(wxGetTopLevelParent(state.surface)->GetHandle());
                if (GetForegroundWindow() == root)
                {
                    const auto canvas = static_cast<HWND>(state.surface->GetHandle());
                    state.reader = std::make_unique<Marker::Reader>(root, canvas, MarkerOrigin);
                    state.capture = std::thread([&state]() { state.ReadDesktop(); });
                }
            }
            state.model->RotateView(0, 0);
            return;
        }
        if (state.start == 0)
        {
            state.start = now;
            state.end = now + RunSeconds * state.frequency;
        }
        if (now >= state.end)
        {
            if (now >= state.end + state.frequency / 4)
            {
                Stop();
            }
            return;
        }
        if (state.inputs.size() >= 10000)
        {
            throw std::runtime_error("Studio 3D 조작 표본 상한을 초과했습니다.");
        }
        state.inputs.push_back(now);
        const double direction = state.inputs.size() % 120 < 60 ? 1.0 : -1.0;
        state.model->RotateView(1.5, direction * 0.35);
        state.model->PanView(direction * 0.4, 0);
    }
    catch (...)
    {
        Stop();
        state.inputError = std::current_exception();
    }
}

bool StudioModelDisplayProbe::Complete() const
{
    return !IsRunning() || m_state->captureFailed.load();
}

Json StudioModelDisplayProbe::Finish()
{
    Stop();
    auto& state = *m_state;
    state.stopped.store(true);
    if (state.capture.joinable())
    {
        state.capture.join();
    }
    const auto masked = std::count_if(state.frames.begin(), state.frames.end(), [](const Marker::Frame& frame)
    {
        return frame.protectedContent;
    });
    const auto decoded = std::count_if(state.frames.begin(), state.frames.end(), [](const Marker::Frame& frame)
    {
        return frame.sequence.has_value();
    });
    const Json capture{{"reader_opened", state.reader != nullptr}, {"desktop_updates", state.frames.size()},
                       {"protected_updates", masked}, {"decoded_updates", decoded}};
    if (state.inputError || state.captureError)
    {
        try
        {
            std::rethrow_exception(state.inputError ? state.inputError : state.captureError);
        }
        catch (const std::exception& error)
        {
            // @brief 실제 갱신이 오지 않은 경우와 OS가 보호한 화면을 실패 기록에서 구분한다.
            throw std::runtime_error(std::string(error.what()) + " DXGI " + capture.dump());
        }
    }
    if (!state.model || !state.surface || !state.reader)
    {
        throw std::runtime_error("Studio 3D 표시 계측을 마치지 못했습니다.");
    }
    Json frames = Json::array();
    for (const auto& frame : state.frames)
    {
        frames.push_back({frame.presented, frame.accumulated, frame.sequence ? Json(*frame.sequence) : Json()});
    }
    const auto size = state.surface->GetClientSize();
    const auto display = state.reader->OutputSize();
    return {{"schema", "rfad.windows-canvas-display-trace/0.1"}, {"ok", true},
            {"workload", "studio-model-rotate-pan"}, {"triangles", state.model->TriangleCount()},
            {"shapes", 10000}, {"layers", state.model->BodyCount()}, {"target_fps", 30},
            {"renderer", state.model->RendererDescription()}, {"vertex_buffer", state.model->VertexBufferDiagnostics()},
            {"dpi", state.surface->GetDPI().x}, {"canvas", {size.x, size.y}}, {"display", {display.cx, display.cy}},
            {"qpc_frequency", state.frequency}, {"start_qpc", state.start}, {"end_qpc", state.end},
            {"refresh_hz", state.reader->RefreshRate()}, {"timer", "wx-timer-1ms-resolution"},
            {"requested_timer_ms", InputPeriodMs}, {"inputs_qpc", state.inputs},
            {"painted", std::move(state.painted)}, {"desktop_updates", std::move(frames)},
            {"desktop_capture", capture}};
}
