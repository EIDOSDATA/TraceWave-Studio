/** @file @brief 스크롤 직후 그린 시험 번호를 Windows 합성 화면에서 판독한다. */
#include "studio_catalog_display_probe.h"
#include "pcb_catalog_table.h"
#include "../../tools/windows_display_marker.h"
#include <atomic>
#include <exception>
#include <mmsystem.h>
#include <thread>
#include <vector>
#include <wx/utils.h>
#include <wx/weakref.h>
#include <wx/window.h>

namespace
{
namespace Marker = WindowsDisplayMarker;
constexpr int InputPeriodMs = 10;
constexpr int RunSeconds = 35;
constexpr int ScrollEventId = wxID_HIGHEST + 2;

std::int64_t Counter()
{
    LARGE_INTEGER value{};
    QueryPerformanceCounter(&value);
    return value.QuadPart;
}
}

struct StudioCatalogDisplayProbe::State
{
    State(PcbCatalogTable& control, HWND surface, POINT stamp)
        : table(&control), window(surface), origin(stamp),
          reader(static_cast<HWND>(wxGetTopLevelParent(&control)->GetHandle()), surface, stamp)
    {
        LARGE_INTEGER rate{};
        QueryPerformanceFrequency(&rate);
        frequency = rate.QuadPart;
        readerDeadline = Counter() + 5 * frequency;
    }

    /** @brief 다음 native paint가 덮어쓸 수 있는 시험용 띠를 갱신한다. */
    void PaintMarker(unsigned sequence)
    {
        const auto dc = GetDC(window);
        if (dc == nullptr)
        {
            throw std::runtime_error("스크롤 화면의 시험 표시 영역을 그리지 못했습니다.");
        }
        const auto code = Marker::Signature | sequence;
        for (int cell = 0; cell < Marker::Cells; ++cell)
        {
            const long x = origin.x + cell * Marker::CellWidth;
            RECT bounds{x, origin.y, x + Marker::CellWidth, origin.y + 4};
            const auto color = code & (1u << cell) ? WHITE_BRUSH : BLACK_BRUSH;
            FillRect(dc, &bounds, static_cast<HBRUSH>(GetStockObject(color)));
        }
        GdiFlush();
        ReleaseDC(window, dc);
    }

    void ReadDesktop()
    {
        try
        {
            while (!stop.load())
            {
                if (const auto frame = reader.Next())
                {
                    if (frames.size() >= 15000)
                    {
                        throw std::runtime_error("표 스크롤의 합성 표본 상한을 초과했습니다.");
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
            readerError = std::current_exception();
            readerFailed.store(true);
        }
    }

    wxWeakRef<PcbCatalogTable> table;
    HWND window;
    POINT origin;
    Marker::Reader reader;
    std::thread capture, source;
    std::atomic<bool> stop{false}, ready{false}, readerFailed{false};
    std::atomic<bool> pending{false}, sourceFailed{false};
    std::exception_ptr readerError, inputError, sourceError;
    std::int64_t frequency = 0, readerDeadline = 0, start = 0, end = 0;
    bool fineTimer = false, useWaitableTimer = false;
    unsigned unloaded = 0;
    std::vector<std::int64_t> offers, inputs;
    std::vector<Marker::Frame> frames;
    Json painted = Json::array();
};

StudioCatalogDisplayProbe::StudioCatalogDisplayProbe(PcbCatalogTable& table)
{
    const auto window = static_cast<HWND>(table.GetHandle());
    RECT bounds{};
    if (!GetClientRect(window, &bounds) || bounds.right < Marker::Width + 10 || bounds.bottom < 16)
    {
        throw std::runtime_error("자료 표에서 스크롤 시험의 표시 영역을 확보하지 못했습니다.");
    }
    m_state = std::make_unique<State>(table, window, POINT{bounds.right - Marker::Width - 5, bounds.bottom - 7});
    wxString timer;
    m_state->useWaitableTimer = wxGetEnv("RFAD_TEST_CATALOG_WAITABLE_TIMER", &timer) && timer == "1";
    Bind(wxEVT_THREAD, [this](wxThreadEvent&)
    {
        auto& state = *m_state;
        state.pending.store(false);
        const auto now = Counter();
        if (IsRunning() && now < state.end)
        {
            Scroll(now);
        }
    }, ScrollEventId);
    m_state->painted.push_back({0, Counter()});
    m_state->PaintMarker(0);
    m_state->capture = std::thread([state = m_state.get()]() { state->ReadDesktop(); });
    m_state->fineTimer = timeBeginPeriod(1) == TIMERR_NOERROR;
    if (!Start(InputPeriodMs))
    {
        m_state->inputError = std::make_exception_ptr(std::runtime_error("표 스크롤 타이머를 시작하지 못했습니다."));
    }
}

StudioCatalogDisplayProbe::~StudioCatalogDisplayProbe()
{
    Stop();
    m_state->stop.store(true);
    if (m_state->source.joinable())
    {
        m_state->source.join();
    }
    if (m_state->capture.joinable())
    {
        m_state->capture.join();
    }
    if (m_state->fineTimer)
    {
        timeEndPeriod(1);
    }
}

/** @brief 화면 스레드와 독립된 제안을 기록하면서 대기 중인 입력은 하나만 유지한다. */
void StudioCatalogDisplayProbe::StartInputOffers()
{
    auto& state = *m_state;
    state.source = std::thread([this, &state]()
    {
        try
        {
            const std::unique_ptr<void, decltype(&CloseHandle)> timer(
                CreateWaitableTimerExW(nullptr, nullptr, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION,
                                       SYNCHRONIZE | TIMER_MODIFY_STATE), &CloseHandle);
            LARGE_INTEGER due{};
            due.QuadPart = -10000LL * InputPeriodMs;
            if (!timer || !SetWaitableTimer(timer.get(), &due, InputPeriodMs, nullptr, nullptr, FALSE))
            {
                throw std::runtime_error("표 스크롤용 고해상도 타이머를 열지 못했습니다.");
            }
            while (!state.stop.load())
            {
                if (WaitForSingleObject(timer.get(), 150) != WAIT_OBJECT_0)
                {
                    throw std::runtime_error("표 스크롤 타이머의 대기 시간이 초과됐습니다.");
                }
                const auto now = Counter();
                if (now >= state.end || state.stop.load())
                {
                    break;
                }
                state.offers.push_back(now);
                if (!state.pending.exchange(true))
                {
                    wxQueueEvent(this, new wxThreadEvent(wxEVT_THREAD, ScrollEventId));
                }
            }
        }
        catch (...)
        {
            state.sourceError = std::current_exception();
            state.sourceFailed.store(true);
        }
    });
}

void StudioCatalogDisplayProbe::Notify()
{
    auto& state = *m_state;
    try
    {
        const auto now = Counter();
        if (!state.table)
        {
            throw std::runtime_error("계측 중 자료 표가 닫혔습니다.");
        }
        if (!state.ready.load())
        {
            if (now >= state.readerDeadline)
            {
                throw std::runtime_error("초기 자료 표의 실제 합성 표시를 관찰하지 못했습니다.");
            }
            state.PaintMarker(0);
            return;
        }
        if (state.start == 0)
        {
            state.start = now;
            state.end = now + RunSeconds * state.frequency;
            if (state.useWaitableTimer)
            {
                StartInputOffers();
            }
        }
        if (now >= state.end)
        {
            Stop();
            return;
        }
        if (!state.useWaitableTimer)
        {
            Scroll(now);
        }
    }
    catch (...)
    {
        Stop();
        state.inputError = std::current_exception();
    }
}

/** @brief 같은 native 목록에서 행을 한 줄 이동하고 그리기 및 표식 시각을 기록한다. */
void StudioCatalogDisplayProbe::Scroll(std::int64_t now)
{
    auto& state = *m_state;
    try
    {
        if (!state.table)
        {
            throw std::runtime_error("계측 중 자료 표가 닫혔습니다.");
        }
        if (state.inputs.size() >= 6000)
        {
            throw std::runtime_error("표 스크롤 입력 표본 상한을 초과했습니다.");
        }
        const long before = state.table->GetTopItem();
        SendMessageW(state.window, WM_VSCROLL, SB_LINEUP, 0);
        const long top = state.table->GetTopItem();
        if (top != before - 1)
        {
            throw std::runtime_error("native 자료 표가 한 행만큼 스크롤되지 않았습니다.");
        }
        state.inputs.push_back(now);
        if (state.table->Row(top) == nullptr)
        {
            ++state.unloaded;
        }
        UpdateWindow(state.window);
        state.painted.push_back({state.inputs.size(), Counter()});
        state.PaintMarker(static_cast<unsigned>(state.inputs.size()));
    }
    catch (...)
    {
        Stop();
        state.inputError = std::current_exception();
    }
}

bool StudioCatalogDisplayProbe::Complete() const
{
    return !IsRunning() || m_state->readerFailed.load() || m_state->sourceFailed.load();
}

Json StudioCatalogDisplayProbe::Finish()
{
    Stop();
    auto& state = *m_state;
    state.stop.store(true);
    state.capture.join();
    if (state.source.joinable())
    {
        state.source.join();
    }
    if (state.readerError)
    {
        std::rethrow_exception(state.readerError);
    }
    if (state.inputError)
    {
        std::rethrow_exception(state.inputError);
    }
    if (state.sourceError)
    {
        std::rethrow_exception(state.sourceError);
    }
    if (!state.table)
    {
        throw std::runtime_error("자료 표가 닫혀 합성 기록의 표시 범위를 확인하지 못했습니다.");
    }
    const auto bounds = state.table->GetClientSize();
    const auto display = state.reader.OutputSize();
    Json frames = Json::array();
    for (const auto& frame : state.frames)
    {
        frames.push_back({frame.presented, frame.accumulated, frame.sequence ? Json(*frame.sequence) : Json()});
    }
    Json trace = {{"schema", "rfad.windows-canvas-display-trace/0.1"}, {"ok", true}, {"workload", "catalog_scroll"},
            {"shapes", 10000}, {"layers", 4}, {"catalog_rows", state.table->GetItemCount()},
            {"top_rows_not_yet_loaded", state.unloaded}, {"qpc_frequency", state.frequency},
            {"start_qpc", state.start}, {"end_qpc", state.end}, {"requested_timer_ms", InputPeriodMs},
            {"timer", state.useWaitableTimer ? "high-resolution-waitable" : "wx-timer-1ms-resolution"},
            {"refresh_hz", state.reader.RefreshRate()},
            {"dpi", state.table->GetDPI().x}, {"canvas", {bounds.x, bounds.y}}, {"display", {display.cx, display.cy}},
            {"inputs_qpc", state.inputs}, {"painted", std::move(state.painted)}, {"desktop_updates", std::move(frames)}};
    if (state.useWaitableTimer)
    {
        trace["offers_qpc"] = std::move(state.offers);
    }
    return trace;
}
