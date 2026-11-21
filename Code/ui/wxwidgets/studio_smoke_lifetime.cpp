/** @file @brief 같은 Windows Studio에서 대형 설계와 대기 프로젝트의 전환 자원을 측정한다. */
#include "studio_internal.h"
#include "studio_model_display_probe.h"
#include "studio_smoke_gpu.h"
#include "../../tools/large_display_fixture.h"
#include <windows.h>
#include <psapi.h>
#include <tlhelp32.h>
#include <algorithm>
#include <fstream>
#include <map>
#include <utility>
#include <vector>
#include <wx/glcanvas.h>

namespace
{
/** @brief Windows가 PID를 재사용해도 실제 생성 순서를 확인한다. */
std::optional<FILETIME> StartedAt(DWORD pid)
{
    const std::unique_ptr<void, decltype(&CloseHandle)> process(
        OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid), &CloseHandle);
    FILETIME started{}, ended{}, kernel{}, user{};
    if (!process || !GetProcessTimes(process.get(), &started, &ended, &kernel, &user))
    {
        return std::nullopt;
    }
    return started;
}

/** @brief Windows가 보고한 GDI 또는 USER 객체 수와 계측 실패를 구분한다. */
Json GuiObjectCount(HANDLE process, DWORD kind)
{
    SetLastError(ERROR_SUCCESS);
    const auto count = GetGuiResources(process, kind);
    if (count == 0 && GetLastError() != ERROR_SUCCESS)
    {
        return nullptr;
    }
    return count;
}

/** @brief 같은 Studio와 현재 하위 서비스의 CPU/GPU 이외 프로세스 자원을 기록한다. */
Json CurrentProcessSamples()
{
    const auto root = GetCurrentProcessId();
    const auto started = StartedAt(root);
    if (!started)
    {
        throw std::runtime_error("Studio 프로세스의 생성 시각을 읽지 못했습니다.");
    }
    std::map<DWORD, FILETIME> descendants{{root, *started}};
    std::vector<std::pair<DWORD, DWORD>> tree;
    const auto handle = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (handle == INVALID_HANDLE_VALUE)
    {
        throw std::runtime_error("Windows 프로세스 목록을 읽지 못했습니다.");
    }
    std::unique_ptr<void, decltype(&CloseHandle)> snapshot(handle, &CloseHandle);
    PROCESSENTRY32W entry{};
    entry.dwSize = sizeof(entry);
    if (!Process32FirstW(snapshot.get(), &entry))
    {
        throw std::runtime_error("Windows 프로세스 목록이 비어 있습니다.");
    }
    do
    {
        tree.emplace_back(entry.th32ProcessID, entry.th32ParentProcessID);
    } while (Process32NextW(snapshot.get(), &entry));

    bool changed = true;
    while (changed)
    {
        changed = false;
        for (const auto& [process, parent] : tree)
        {
            const auto owner = descendants.find(parent);
            if (owner == descendants.end() || descendants.count(process))
            {
                continue;
            }
            const auto childStarted = StartedAt(process);
            if (childStarted && CompareFileTime(&*childStarted, &owner->second) >= 0)
            {
                descendants.emplace(process, *childStarted);
                changed = true;
            }
        }
    }
    Json rows = Json::array();
    for (const auto& [process, creation] : descendants)
    {
        std::unique_ptr<void, decltype(&CloseHandle)> owner(
            OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, FALSE, process), &CloseHandle);
        PROCESS_MEMORY_COUNTERS_EX counters{};
        FILETIME current{}, ended{}, kernel{}, user{};
        DWORD handles = 0;
        if (!owner || !GetProcessTimes(owner.get(), &current, &ended, &kernel, &user) ||
            CompareFileTime(&current, &creation) != 0 ||
            !GetProcessMemoryInfo(owner.get(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&counters),
                                            sizeof(counters)) ||
            !GetProcessHandleCount(owner.get(), &handles))
        {
            throw std::runtime_error("Studio 하위 프로세스의 자원 표본을 읽지 못했습니다.");
        }
        Json row{{"pid", process}, {"gui", process == root}, {"private_commit_bytes", counters.PrivateUsage},
                 {"working_set_bytes", counters.WorkingSetSize}, {"handles", handles}};
        if (process == root)
        {
            row["gui_objects"] = {{"gdi", GuiObjectCount(owner.get(), GR_GDIOBJECTS)},
                                  {"user", GuiObjectCount(owner.get(), GR_USEROBJECTS)}};
        }
        rows.push_back(std::move(row));
    }
    if (rows.size() < 2)
    {
        throw std::runtime_error("실제 하위 프로젝트 서비스가 자원 표본에 없습니다.");
    }
    return rows;
}

bool SameProcesses(const Json& before, const Json& after)
{
    return before.size() == after.size() &&
           std::equal(before.begin(), before.end(), after.begin(), [](const Json& left, const Json& right)
           {
               return left.at("pid") == right.at("pid");
           });
}

/** @brief 축소에서는 저해상도, 선택과 전체 맞춤에서는 원본을 실제 GL 프레임으로 확인한다. */
Json CheckDisplayQuality(ModelView& model)
{
    wxWindow* surface = nullptr;
    for (auto* child : model.GetChildren())
    {
        if (dynamic_cast<wxGLCanvas*>(child) != nullptr)
        {
            surface = child;
            break;
        }
    }
    if (surface == nullptr)
    {
        throw std::runtime_error("저해상도 검증에 사용할 3D 캔버스가 없습니다.");
    }
    model.SetSelection("");
    model.FitView();
    surface->Update();
    const auto full = model.SubmittedTriangleCount();
    wxMouseEvent wheel(wxEVT_MOUSEWHEEL);
    wheel.SetEventObject(surface);
    wheel.m_wheelDelta = 120;
    wheel.m_wheelRotation = -16 * wheel.m_wheelDelta;
    surface->GetEventHandler()->ProcessEvent(wheel);
    surface->Update();
    const auto coarse = model.SubmittedTriangleCount();
    const auto memory = model.VertexBufferDiagnostics();
    model.SetSelection("00000000-0000-0000-0000-000000000014");
    surface->Update();
    const auto selected = model.SubmittedTriangleCount();
    model.SetSelection("");
    model.FitView();
    surface->Update();
    const auto restored = model.SubmittedTriangleCount();
    if (full != model.TriangleCount() || coarse == 0 || coarse >= full / 3 ||
        selected != full || restored != full)
    {
        throw std::runtime_error("Studio 3D의 축소·선택·원본 복귀 삼각형 수가 예상과 다릅니다. " +
            std::to_string(full) + "/" + std::to_string(coarse) + "/" + std::to_string(selected) + "/" +
            std::to_string(restored) + " " + memory.dump());
    }
    return {{"fit_triangles", full}, {"coarse_triangles", coarse}, {"selected_triangles", selected},
            {"restored_triangles", restored}, {"buffers", memory}};
}
}

/** @brief 프로젝트를 열어 편집을 확인하고 대기 프로젝트에서 30초씩 자원을 관찰한다. */
void StudioSmokeDriver::ProjectSwitchSmokeTick()
{
    if (!m_frame.m_options.projectSwitchSmoke || m_frame.m_finishing)
    {
        return;
    }
    try
    {
        const auto now = Clock::now();
        if (m_projectSwitchFixture.empty())
        {
            const auto base = std::filesystem::path(m_frame.m_options.workspace.ToStdWstring());
            std::ifstream stream(base / "project-switch-smoke-fixture.json", std::ios::binary);
            stream >> m_projectSwitchFixture;
            const auto rounds = m_projectSwitchFixture.at("cycles").get<int>();
            CanvasAssert(rounds >= 1 && rounds <= 30, "프로젝트 전환의 회차가 지원 범위를 벗어났습니다.");
            const bool idle = m_projectSwitchFixture.value("idle", false);
            const auto diagnostic = m_projectSwitchFixture.value("diagnostic", std::string());
            CanvasAssert(diagnostic.empty() || ((diagnostic == "display" || diagnostic == "results") && !idle &&
                         rounds < 30 && m_projectSwitchFixture.value("combined", false)),
                         "원인 진단은 정식 반복 회수와 분리해야 합니다.");
            const int settle = diagnostic.empty() ? (idle ? 150 : 30) : 1;
            if (m_projectSwitchFixture.value("combined", false) && !idle)
            {
                m_frame.m_modelView->KeepContextForMeasurement();
            }
            m_projectSwitchRecord["settle_seconds"] = settle;
            m_projectSwitchRecord["policy"] = idle ? "idle" : "warm";
            m_projectSwitchRecord["diagnostic"] = diagnostic;
            m_projectSwitchExpires = now + std::chrono::seconds(90 + rounds * (settle + 100));
            m_projectSwitchStage = 1;
        }
        CanvasAssert(now < m_projectSwitchExpires, "대형 프로젝트 반복 전환의 제한 시간을 초과했습니다.");
        if (!m_frame.m_connected || m_frame.m_busy || m_frame.m_project.empty() || m_frame.m_cadRestoring ||
            m_frame.m_solverRestoring || m_frame.m_requests.Size() != 0)
        {
            return;
        }
        CanvasAssert(m_serviceSessions == 1, "warm 전환 중 프로젝트 서비스가 다시 연결되었습니다.");
        const auto standby = m_projectSwitchFixture.at("standby_path").get<std::string>();
        const auto large = m_projectSwitchFixture.at("large_path").get<std::string>();
        const bool combined = m_projectSwitchFixture.value("combined", false);
        const auto diagnostic = m_projectSwitchFixture.value("diagnostic", std::string());
        const bool openDisplay = combined && diagnostic != "results";
        const bool openResults = combined && diagnostic != "display";
        const auto workspace = std::filesystem::path(m_frame.m_options.workspace.ToStdWstring());
        const auto readOpenState = [this, combined, &standby]()
        {
            m_projectSwitchOpen = CurrentProcessSamples();
            if (combined)
            {
                m_projectSwitchRecord["current_open_gpu"] = StudioSmoke::GpuMemorySamples();
            }
            m_projectSwitchStage = 3;
            m_frame.OpenProject("open", standby);
        };
        if (m_projectSwitchStage == 1 && m_frame.m_path == standby)
        {
            m_projectSwitchRecord["baseline"] = CurrentProcessSamples();
            if (combined)
            {
                m_projectSwitchRecord["baseline_gpu"] = StudioSmoke::GpuMemorySamples();
            }
            m_projectSwitchStage = 2;
            m_frame.OpenProject("open", large);
        }
        else if (m_projectSwitchStage == 2 && m_frame.m_path == large)
        {
            const auto parameters = std::count_if(m_frame.m_editor.at("items").begin(), m_frame.m_editor.at("items").end(),
                [](const Json& item)
                {
                    return item.at("kind") == "parameter";
                });
            CanvasAssert(m_frame.m_scene.at("shapes").size() == 10000 && parameters == 1000 &&
                             m_frame.m_editor.at("saved_revision") == m_frame.m_revision &&
                             m_frame.m_canvas->DisplayOmissionCount() == 0,
                         "반복 전환에서 대형 설계 또는 저장된 개정을 읽지 못했습니다.");
            if (openDisplay)
            {
                const auto folder = workspace / "combined-display";
                const auto fixture = ReadLargeDisplayFixture(folder);
                const auto& artifact = fixture.at("artifact");
                m_frame.m_views->SetSelection(1);
                CanvasAssert(m_frame.m_modelView->LoadArtifact(wxString(folder.wstring()), artifact,
                             fixture.at("snapshot"), artifact.at("run_id").get<std::string>()),
                             "Studio에서 대형 3D 표시 원문을 열 수 없습니다.");
                m_projectSwitchStage = 5;
            }
            else if (openResults)
            {
                m_projectSwitchStage = 8;
            }
            else
            {
                readOpenState();
            }
        }
        else if (m_projectSwitchStage == 5 && !m_frame.m_modelView->IsLoading())
        {
            CanvasAssert(m_frame.m_modelView->TriangleCount() == 1000000,
                         "전체 Studio의 대형 3D 장면을 표시하지 못했습니다.");
            if (m_projectSwitchFixture.value("profile_3d", false))
            {
                m_projectModelDisplay = std::make_shared<StudioModelDisplayProbe>(*m_frame.m_modelView);
                m_projectSwitchStage = 7;
                return;
            }
            if (m_projectSwitchFixture.value("quality_3d", false))
            {
                m_projectSwitchRecord["display_quality"] = CheckDisplayQuality(*m_frame.m_modelView);
            }
            if (openResults)
            {
                m_projectSwitchStage = 8;
            }
            else
            {
                readOpenState();
            }
        }
        else if (m_projectSwitchStage == 7 && m_projectModelDisplay->Complete())
        {
            m_projectSwitchRecord["display_trace"] = m_projectModelDisplay->Finish();
            m_projectModelDisplay.reset();
            m_projectSwitchRecord["display_quality"] = CheckDisplayQuality(*m_frame.m_modelView);
            m_projectSwitchStage = 8;
        }
        else if (m_projectSwitchStage == 8)
        {
            m_projectSwitchStage = 6;
            const auto ready = Utf8(wxString((workspace / "f5-results-progress.txt").wstring()));
            const auto evidence = Utf8(wxString((workspace / "f5-results-view.json").wstring()));
            CanvasAssert(m_frame.RunLargeResultLibrary({{"mode", "reopen"}, {"phases", ready},
                                                        {"evidence", evidence}}) == wxID_OK,
                         "같은 Studio에서 대용량 필드와 곡선 조회를 완료하지 못했습니다.");
            readOpenState();
        }
        else if (m_projectSwitchStage == 3 && m_frame.m_path == standby)
        {
            CanvasAssert(m_frame.m_scene.at("shapes").empty(), "대기 화면에 이전 형상이 남았습니다.");
            m_projectSwitchSettled = now + std::chrono::seconds(m_projectSwitchRecord.at("settle_seconds").get<int>());
            m_projectSwitchStage = 4;
        }
        else if (m_projectSwitchStage == 4 && now >= m_projectSwitchSettled)
        {
            const auto settled = CurrentProcessSamples();
            CanvasAssert(SameProcesses(m_projectSwitchRecord.at("baseline"), settled),
                         "warm 전환 중 GUI 또는 서비스 프로세스가 바뀌었습니다.");
            auto& samples = m_projectSwitchRecord.at("cycles");
            Json sample{{"cycle", samples.size() + 1}, {"opened", std::move(m_projectSwitchOpen)},
                        {"settled_after_switch", settled}};
            if (combined)
            {
                CanvasAssert(m_frame.m_modelView->TriangleCount() == 0,
                             "대기 프로젝트로 이동한 뒤 대형 3D 장면이 남았습니다.");
                const bool context = !m_frame.m_modelView->RendererDescription().empty();
                CanvasAssert(context == (openDisplay && !m_projectSwitchFixture.value("idle", false)),
                             "설정한 유지/유휴 정책과 실제 OpenGL context의 상태가 다릅니다.");
                sample["opened_gpu"] = m_projectSwitchRecord.at("current_open_gpu");
                sample["settled_gpu"] = StudioSmoke::GpuMemorySamples();
                sample["context_retained"] = context;
                sample["display_triangles"] = openDisplay ? 1000000 : 0;
                sample["field_slices"] = openResults ? 10 : 0;
                sample["complex_curves"] = openResults ? 8 : 0;
            }
            samples.push_back(sample);
            auto output = std::filesystem::path(m_frame.m_options.smokeReport.ToStdWstring());
            output += ".progress.jsonl";
            std::ofstream progress(output, std::ios::binary | std::ios::app);
            progress << sample.dump() << '\n';
            CanvasAssert(progress.good(), "프로젝트 전환의 실제 표본을 기록하지 못했습니다.");
            if (samples.size() == m_projectSwitchFixture.at("cycles").get<std::size_t>())
            {
                FinishSmoke(true, "");
            }
            else
            {
                m_projectSwitchStage = 2;
                m_frame.OpenProject("open", large);
            }
        }
    }
    catch (const std::exception& error)
    {
        m_projectModelDisplay.reset();
        FinishSmoke(false, error.what());
    }
}
