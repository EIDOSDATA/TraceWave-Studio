/** @file @brief 같은 Windows ModelView에서 대형 장면을 반복해 열고 리소스 회수를 관찰한다. */
#include "large_display_fixture.h"
#include "model_view.h"

#include <dxgi1_4.h>
#include <psapi.h>
#include <chrono>
#include <iostream>
#include <string_view>

namespace
{
using Json = nlohmann::json;
using Clock = std::chrono::steady_clock;
constexpr int ReleaseCycles = 30;
constexpr int ReleaseWaitMs = 30000;
constexpr int ModelTriangleCount = 1000000;

struct ComRelease
{
    void operator()(IUnknown* value) const
    {
        value->Release();
    }
};

template <class T>
using Com = std::unique_ptr<T, ComRelease>;

/** @brief 운영체제의 adapter node 0 사용량을 로컬/비로컬로 각각 관찰한다. */
class ResourceCounters final
{
public:
    ResourceCounters()
    {
        IDXGIFactory1* rawFactory = nullptr;
        if (FAILED(CreateDXGIFactory1(__uuidof(IDXGIFactory1), reinterpret_cast<void**>(&rawFactory))))
        {
            return;
        }
        const Com<IDXGIFactory1> factory(rawFactory);
        for (UINT ordinal = 0;; ++ordinal)
        {
            IDXGIAdapter1* rawAdapter = nullptr;
            if (FAILED(factory->EnumAdapters1(ordinal, &rawAdapter)))
            {
                break;
            }
            const Com<IDXGIAdapter1> adapter(rawAdapter);
            DXGI_ADAPTER_DESC1 description{};
            IDXGIAdapter3* candidate = nullptr;
            if (SUCCEEDED(adapter->GetDesc1(&description)) && (description.Flags & DXGI_ADAPTER_FLAG_SOFTWARE) == 0 &&
                SUCCEEDED(adapter->QueryInterface(__uuidof(IDXGIAdapter3), reinterpret_cast<void**>(&candidate))))
            {
                m_adapters.push_back({ordinal, Com<IDXGIAdapter3>(candidate)});
            }
        }
    }

    Json Read() const
    {
        PROCESS_MEMORY_COUNTERS_EX memory{};
        memory.cb = sizeof(memory);
        DWORD handles = 0;
        if (!GetProcessMemoryInfo(GetCurrentProcess(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&memory), sizeof(memory)) ||
            !GetProcessHandleCount(GetCurrentProcess(), &handles))
        {
            throw std::runtime_error("Windows ModelView 프로세스 자원을 읽을 수 없습니다.");
        }
        auto adapters = Json::array();
        for (const auto& entry : m_adapters)
        {
            adapters.push_back({{"ordinal", entry.ordinal}, {"node", 0},
                {"local_bytes", VideoUsage(*entry.adapter, DXGI_MEMORY_SEGMENT_GROUP_LOCAL)},
                {"nonlocal_bytes", VideoUsage(*entry.adapter, DXGI_MEMORY_SEGMENT_GROUP_NON_LOCAL)}});
        }
        return {{"private_commit_bytes", memory.PrivateUsage}, {"working_set_bytes", memory.WorkingSetSize},
            {"peak_working_set_bytes", memory.PeakWorkingSetSize}, {"handles", handles}, {"gpu_usage", adapters}};
    }

private:
    static Json VideoUsage(IDXGIAdapter3& adapter, DXGI_MEMORY_SEGMENT_GROUP group)
    {
        DXGI_QUERY_VIDEO_MEMORY_INFO value{};
        if (FAILED(adapter.QueryVideoMemoryInfo(0, group, &value)))
        {
            return nullptr;
        }
        return value.CurrentUsage;
    }

    struct Adapter
    {
        UINT ordinal;
        Com<IDXGIAdapter3> adapter;
    };

    std::vector<Adapter> m_adapters;
};

/** @brief 진행 표본을 새 JSONL 파일에 즉시 보존하고 실패와 종료를 구분한다. */
class LifetimeFrame final : public wxFrame
{
public:
    LifetimeFrame(const std::filesystem::path& workspace, HANDLE output, bool smoke, int& result)
        : wxFrame(nullptr, wxID_ANY, "TraceWave 3D lifetime probe"), m_timer(this), m_workspace(workspace),
          m_fixture(ReadLargeDisplayFixture(workspace)), m_model(new ModelView(this)), m_output(output),
          m_cycles(smoke ? 2 : ReleaseCycles), m_waitMs(smoke ? 300 : ReleaseWaitMs), m_result(result)
    {
        SetClientSize(1920, 1080);
        auto* layout = new wxBoxSizer(wxVERTICAL);
        layout->Add(m_model, 1, wxEXPAND);
        SetSizer(layout);
        Bind(wxEVT_TIMER, &LifetimeFrame::Tick, this);
        Bind(wxEVT_CLOSE_WINDOW, &LifetimeFrame::OnClose, this);
        m_timer.Start(25);
    }

private:
    void Write(Json row)
    {
        row["elapsed_ms"] = std::chrono::duration<double, std::milli>(Clock::now() - m_start).count();
        const auto bytes = row.dump() + "\n";
        DWORD written = 0;
        if (!WriteFile(m_output, bytes.data(), static_cast<DWORD>(bytes.size()), &written, nullptr) ||
            written != bytes.size() || !FlushFileBuffers(m_output))
        {
            throw std::runtime_error("3D 반복 회수 실행 기록을 저장하지 못했습니다.");
        }
    }

    void StartLoad()
    {
        ++m_cycle;
        m_loadStart = Clock::now();
        m_beforeFrame = m_model->RenderedFrameCount();
        const auto& artifact = m_fixture.at("artifact");
        if (!m_model->LoadArtifact(wxString(m_workspace.wstring()), artifact, m_fixture.at("snapshot"),
                artifact.at("run_id").get<std::string>()))
        {
            throw std::runtime_error("검증할 대형 표시 장면을 열지 못했습니다.");
        }
        m_loading = true;
    }

    void Sample(const char* phase, const Json& buffer)
    {
        auto row = m_counters.Read();
        row["event"] = phase;
        row["cycle"] = m_cycle;
        row["vertex_buffer"] = buffer;
        Write(std::move(row));
    }

    void Tick(wxTimerEvent&)
    {
        try
        {
            if (!m_model->Error().empty())
            {
                throw std::runtime_error(m_model->Error());
            }
            if (m_cycle == 0)
            {
                const auto size = m_model->GetClientSize();
                Write({{"event", "start"}, {"expected_cycles", m_cycles}, {"minimum_closed_ms", m_waitMs},
                    {"canvas", {size.x, size.y}}, {"artifact", m_fixture.at("artifact")}});
                Sample("baseline", m_model->VertexBufferDiagnostics());
                StartLoad();
                return;
            }
            if (m_loading)
            {
                if (Clock::now() - m_loadStart > std::chrono::seconds(15))
                {
                    throw std::runtime_error("3D 첫 프레임을 제한 시간 안에 관찰하지 못했습니다.");
                }
                if (m_model->HasMesh() && m_model->RenderedFrameCount() > m_beforeFrame)
                {
                    const auto vertex = m_model->VertexBufferDiagnostics();
                    if (m_model->TriangleCount() != ModelTriangleCount || vertex.value("bytes", 0u) != 72000000u)
                    {
                        throw std::runtime_error("GPU에 올린 100만 삼각형 장면이 필요합니다.");
                    }
                    Sample("open", vertex);
                    m_model->Clear();
                    m_closedAt = Clock::now();
                    m_loading = false;
                }
                return;
            }
            if (Clock::now() - m_closedAt < std::chrono::milliseconds(m_waitMs))
            {
                return;
            }
            const auto vertex = m_model->VertexBufferDiagnostics();
            if (m_model->HasMesh() || vertex.value("bytes", 1u) != 0u)
            {
                throw std::runtime_error("장면을 닫은 뒤 제품 정점 버퍼가 남았습니다.");
            }
            Sample("closed", vertex);
            if (m_cycle < m_cycles)
            {
                StartLoad();
                return;
            }
            Write({{"event", "complete"}, {"cycles", m_cycle}});
            m_result = 0;
            m_timer.Stop();
            Close();
        }
        catch (const std::exception& error)
        {
            std::cerr << error.what() << '\n';
            m_timer.Stop();
            Close();
        }
    }

    void OnClose(wxCloseEvent& event)
    {
        m_timer.Stop();
        event.Skip();
    }

    wxTimer m_timer;
    const std::filesystem::path m_workspace;
    const Json m_fixture;
    ModelView* const m_model;
    HANDLE m_output;
    const int m_cycles;
    const int m_waitMs;
    int& m_result;
    ResourceCounters m_counters;
    Clock::time_point m_start = Clock::now();
    Clock::time_point m_loadStart, m_closedAt;
    std::uint64_t m_beforeFrame = 0;
    int m_cycle = 0;
    bool m_loading = false;
};

class LifetimeApp final : public wxApp
{
public:
    bool OnInit() override
    {
        return true;
    }
};
}

wxIMPLEMENT_APP_NO_MAIN(LifetimeApp);

int main(int argc, char** argv)
{
    const bool smoke = argc == 4 && std::string_view(argv[3]) == "--smoke";
    if ((argc != 3 && !smoke) || !wxEntryStart(argc, argv))
    {
        return 2;
    }
    int result = 2;
    try
    {
        const auto output = std::filesystem::path(argv[2]);
        const auto closer = [](void* file)
        {
            CloseHandle(file);
        };
        const HANDLE handle = CreateFileW(output.c_str(), GENERIC_WRITE, FILE_SHARE_READ, nullptr,
            CREATE_NEW, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (handle == INVALID_HANDLE_VALUE)
        {
            throw std::runtime_error("새 3D 회수 기록 경로가 필요합니다.");
        }
        const std::unique_ptr<void, decltype(closer)> trackedFile(handle, closer);
        if (wxTheApp->CallOnInit())
        {
            auto* window = new LifetimeFrame(std::filesystem::absolute(std::filesystem::path(argv[1])), handle, smoke, result);
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
