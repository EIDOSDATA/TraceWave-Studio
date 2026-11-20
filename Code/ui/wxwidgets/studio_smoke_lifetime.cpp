/** @file @brief 같은 Windows Studio에서 대형 설계와 대기 프로젝트의 전환 자원을 측정한다. */
#include "studio_internal.h"
#include <windows.h>
#include <psapi.h>
#include <tlhelp32.h>
#include <algorithm>
#include <fstream>
#include <set>
#include <utility>
#include <vector>

namespace
{
/** @brief 같은 Studio와 현재 하위 서비스의 CPU/GPU 이외 프로세스 자원을 기록한다. */
Json CurrentProcessSamples()
{
    const auto root = GetCurrentProcessId();
    std::set<DWORD> descendants{root};
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
            if (descendants.count(parent) && descendants.insert(process).second)
            {
                changed = true;
            }
        }
    }
    Json rows = Json::array();
    for (const auto process : descendants)
    {
        std::unique_ptr<void, decltype(&CloseHandle)> owner(
            OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, FALSE, process), &CloseHandle);
        PROCESS_MEMORY_COUNTERS_EX counters{};
        DWORD handles = 0;
        if (!owner || !GetProcessMemoryInfo(owner.get(), reinterpret_cast<PROCESS_MEMORY_COUNTERS*>(&counters),
                                            sizeof(counters)) ||
            !GetProcessHandleCount(owner.get(), &handles))
        {
            throw std::runtime_error("Studio 하위 프로세스의 자원 표본을 읽지 못했습니다.");
        }
        rows.push_back({{"pid", process}, {"gui", process == root}, {"private_commit_bytes", counters.PrivateUsage},
                        {"working_set_bytes", counters.WorkingSetSize}, {"handles", handles}});
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
            m_projectSwitchExpires = now + std::chrono::seconds(90 + rounds * 100);
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
        if (m_projectSwitchStage == 1 && m_frame.m_path == standby)
        {
            m_projectSwitchRecord["baseline"] = CurrentProcessSamples();
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
            m_projectSwitchOpen = CurrentProcessSamples();
            m_projectSwitchStage = 3;
            m_frame.OpenProject("open", standby);
        }
        else if (m_projectSwitchStage == 3 && m_frame.m_path == standby)
        {
            CanvasAssert(m_frame.m_scene.at("shapes").empty(), "대기 화면에 이전 형상이 남았습니다.");
            m_projectSwitchSettled = now + std::chrono::seconds(30);
            m_projectSwitchStage = 4;
        }
        else if (m_projectSwitchStage == 4 && now >= m_projectSwitchSettled)
        {
            const auto settled = CurrentProcessSamples();
            CanvasAssert(SameProcesses(m_projectSwitchRecord.at("baseline"), settled),
                         "warm 전환 중 GUI 또는 서비스 프로세스가 바뀌었습니다.");
            auto& samples = m_projectSwitchRecord.at("cycles");
            const Json sample{{"cycle", samples.size() + 1}, {"opened", std::move(m_projectSwitchOpen)},
                              {"settled_after_switch", settled}};
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
        FinishSmoke(false, error.what());
    }
}
