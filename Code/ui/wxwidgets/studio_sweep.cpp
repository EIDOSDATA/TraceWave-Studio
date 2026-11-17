/** @file @brief 불변 연구의 목록/진행과 실제 제어 응답을 공통 작업 공간에 연결한다. */
#include "studio_internal.h"
#include "sweep_panel.h"
#include "sweep_model.h"
#include "studio_theme.h"
#include "studio_shell.h"

void StudioFrame::BuildSweepInterface()
{
    auto* navigation = m_tree->GetParent();
    m_sweepPanel = new SweepPanel(m_views, navigation, m_properties);
    navigation->GetSizer()->Add(m_sweepPanel->NavigationView(), 1, wxEXPAND);
    m_properties->GetSizer()->Add(m_sweepPanel->ConditionsView(), 1, wxEXPAND);
    m_sweepPanel->NavigationView()->Hide();
    m_sweepPanel->ConditionsView()->Hide();
    m_views->AddPage(m_sweepPanel, Display("연구"));
    m_views->SetGroups({0, 0, 2, 1, 3, 4, 2, 2, 1});
    m_views->SetDisplayOrder({0, 1, 6, 7, 2, 3, 8, 4, 5});
    m_workspaceJobs->InsertItem(2, Display("설계 연구"));
    ShowWorkspaceJob(2, "idle", "저장된 연구를 선택하고 실행합니다.");
    m_sweepPanel->onRefresh = [this]()
    {
        RefreshSweeps(m_sweepPanel->StudyId());
    };
    m_sweepPanel->onCreate = [this]()
    {
        OpenSweepSetup();
    };
    m_sweepPanel->onSelect = [this](const std::string& id)
    {
        LoadSweep(id);
    };
    m_sweepPanel->onPage = [this](int offset)
    {
        LoadSweep(m_sweepPanel->StudyId(), offset);
    };
    m_sweepPanel->onCommand = [this](const std::string& command)
    {
        SweepCommand(command);
    };
    m_sweepPanel->onResult = [this](int index)
    {
        OpenSweepResult(index);
    };
    m_sweepPanel->onAdopt = [this](int index)
    {
        OpenSweepSelection(index);
    };
    auto* analysis = GetMenuBar()->FindItem(IdProjectStudy)->GetMenu();
    analysis->Append(IdSweep, Display("설계 스윕 / 다축 연구"));
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            m_views->SetSelection(8);
        },
        IdSweep);
    auto* prepare = m_views->GetPage(3);
    auto* button = new wxButton(prepare, wxID_ANY, Display("설계 스윕 / 다축 연구"));
    StudioTheme::Button(*button);
    prepare->GetSizer()->Add(button, 0, wxALL, FromDIP(12));
    button->Bind(wxEVT_BUTTON,
                 [this](wxCommandEvent&)
                 {
                     m_views->SetSelection(8);
                 });
}

void StudioFrame::UpdateSweepViews()
{
    if (!m_sweepPanel)
    {
        return;
    }
    const bool active = m_views->GetSelection() == 8;
    m_sweepPanel->NavigationView()->Show(active);
    m_sweepPanel->ConditionsView()->Show(active);
    m_tree->GetParent()->Layout();
    m_properties->Layout();
    const bool available = m_connected && m_sweepSupported && !m_project.empty() && !m_closing;
    const bool busy = m_busy || m_sweepPending || m_setupDialog != nullptr;
    m_sweepPanel->SetEnabledState(available, busy, m_sweepUncertain);
    m_sweepPanel->SetSelectionSupported(m_sweepSelectionSupported);
    GetMenuBar()->Enable(IdSweep, available);
    if (active && available && !busy && !m_sweepRefreshQueued && m_sweepAttemptedRevision != m_revision)
    {
        m_sweepRefreshQueued = true;
        CallAfter(
            [this]()
            {
                m_sweepRefreshQueued = false;
                if (!m_closing && m_views->GetSelection() == 8 && m_sweepAttemptedRevision != m_revision)
                {
                    RefreshSweeps(m_sweepPanel->StudyId());
                }
            });
    }
    else if (active && !m_sweepSupported)
    {
        m_sweepPanel->SetStatus("현재 서비스는 설계 스윕을 제공하지 않습니다. 저장/편집 기능은 유지됩니다.");
    }
}

void StudioFrame::ResetSweeps()
{
    ++m_sweepGeneration;
    m_sweepPending = false;
    m_sweepUncertain = false;
    m_sweepRefreshQueued = false;
    m_sweepAttemptedRevision.clear();
    m_sweepNextPoll = Clock::time_point{};
    if (m_sweepPanel)
    {
        m_sweepPanel->Clear("현재 프로젝트의 저장 연구를 다시 읽어야 합니다.");
    }
}

void StudioFrame::RefreshSweeps(const std::string& preferred)
{
    if (!m_connected || !m_sweepSupported || m_closing || m_project.empty() || m_busy || m_sweepPending ||
        m_setupDialog)
    {
        return;
    }
    const auto project = m_project;
    const auto generation = ++m_sweepGeneration;
    m_sweepAttemptedRevision = m_revision;
    m_sweepPending = true;
    m_sweepPanel->SetStatus("저장 연구와 권위 상태를 조회하고 있습니다.");
    UpdateControls();
    Send(
        "sweep.list", Json::object(), false, Context(),
        [this, project, generation, preferred](const Json& result)
        {
            if (m_closing || project != m_project || generation != m_sweepGeneration)
            {
                return;
            }
            m_sweepPending = false;
            m_sweepPanel->SetStudies(result, preferred);
            if (m_sweepPanel->StudyId().empty())
            {
                m_sweepUncertain = false;
                m_sweepPanel->ClearSelection("저장된 연구가 없습니다. 새 연구를 검토하여 저장하세요.");
                UpdateControls();
            }
            else
            {
                LoadSweep(m_sweepPanel->StudyId());
            }
        },
        [this, project, generation](const Json& error)
        {
            if (m_closing || project != m_project || generation != m_sweepGeneration)
            {
                return;
            }
            m_sweepPending = false;
            m_sweepPanel->ClearSelection("연구 목록 조회 실패: " + DiagnosticMessage(error));
            UpdateControls();
        });
}

void StudioFrame::LoadSweep(const std::string& id, int offset)
{
    if (!m_connected || !m_sweepSupported || m_closing || m_project.empty() || m_busy || m_sweepPending ||
        m_setupDialog || id.empty())
    {
        return;
    }
    const auto project = m_project;
    const auto generation = ++m_sweepGeneration;
    m_sweepPending = true;
    m_sweepPanel->BeginRead(id);
    UpdateControls();
    const auto failed = [this, project, generation](const Json& error)
    {
        if (m_closing || project != m_project || generation != m_sweepGeneration)
        {
            return;
        }
        m_sweepPending = false;
        m_sweepNextPoll = Clock::now() + std::chrono::seconds(3);
        m_sweepPanel->ClearSelection("연구 조회 실패: " + DiagnosticMessage(error));
        UpdateControls();
    };
    Send(
        "sweep.get", {{"study_id", id}}, false, Context(),
        [this, project, generation, id, offset, failed](const Json& result)
        {
            if (m_closing || project != m_project || generation != m_sweepGeneration)
            {
                return;
            }
            if (result.at("study_id") != id)
            {
                failed({{"message", "다른 연구의 조회 응답을 폐기했습니다."}});
                return;
            }
            m_sweepPanel->SetStudy(result);
            ShowWorkspaceJob(2, result.at("state"),
                             result.at("name").get<std::string>() + " / " + result.value("message", ""));
            Send(
                "sweep.page", {{"study_id", id}, {"offset", offset}, {"limit", 25}}, false, Context(),
                [this, project, generation, id](const Json& page)
                {
                    if (m_closing || project != m_project || generation != m_sweepGeneration)
                    {
                        return;
                    }
                    m_sweepPending = false;
                    m_sweepNextPoll = Clock::now() + std::chrono::seconds(2);
                    if (page.at("study_id") == id && m_sweepPanel->StudyId() == id)
                    {
                        m_sweepPanel->SetPage(page);
                        m_sweepUncertain = false;
                    }
                    else
                    {
                        m_sweepPanel->ClearSelection("현재 연구와 다른 후보 페이지를 폐기했습니다.");
                    }
                    UpdateControls();
                },
                failed);
        },
        failed);
}

void StudioFrame::SweepCommand(const std::string& action)
{
    if (!m_connected || m_closing || m_busy || m_sweepPending || m_sweepUncertain || m_setupDialog || !m_sweepPanel)
    {
        return;
    }
    const auto& selected = m_sweepPanel->Selection();
    if (!selected.is_object() || !selected.value("allowed_actions", Json::object()).value(action, false))
    {
        return;
    }
    const auto id = m_sweepPanel->StudyId();
    const auto project = m_project;
    const auto generation = ++m_sweepGeneration;
    m_sweepPending = true;
    m_sweepPanel->SetStatus(action == "cancel"
                                ? "취소를 요청합니다. 실제 종료를 확인하기 전에는 취소 완료로 표시하지 않습니다."
                                : "연구 제어 응답을 기다리고 있습니다.");
    UpdateControls();
    Send(
        "sweep." + action, {{"study_id", id}}, true, Context(),
        [this, project, generation, id](const Json& result)
        {
            if (m_closing || project != m_project || generation != m_sweepGeneration)
            {
                return;
            }
            m_sweepPending = false;
            if (result.at("study_id") != id)
            {
                m_sweepUncertain = true;
                m_sweepPanel->SetStatus("제어 응답이 선택 연구와 다릅니다. 다시 실행하지 말고 상태를 조회하세요.");
                UpdateControls();
                return;
            }
            LoadSweep(id, m_sweepPanel->Offset());
        },
        [this, project, generation](const Json& error)
        {
            if (m_closing || project != m_project || generation != m_sweepGeneration)
            {
                return;
            }
            m_sweepPending = false;
            const auto code =
                error.value("data", Json::object())
                    .value("domain_code",
                           error.value("code", Json(nullptr)).is_string() ? error.at("code").get<std::string>() : "");
            m_sweepUncertain = code != "E_SCHEMA" && code != "E_CONFLICT" && code != "E_RESOURCE" &&
                               code != "E_VERSION" && code != "E_UNSUPPORTED";
            m_sweepPanel->SetStatus(
                (m_sweepUncertain ? "적용 결과가 미확정입니다. 다시 실행하지 말고 목록 / 현재 상태를 새로 읽으세요.\n"
                                  : "") +
                DiagnosticMessage(error));
            UpdateControls();
        });
}

void StudioFrame::PollSweep(Clock::time_point now)
{
    if (!m_sweepPanel || m_views->GetSelection() != 8 || m_sweepUncertain || now < m_sweepNextPoll ||
        m_sweepPanel->Selection().is_null())
    {
        return;
    }
    const auto state = m_sweepPanel->Selection().value("state", "");
    if (state == "running" || state == "resuming" || state == "cancel_requested")
    {
        LoadSweep(m_sweepPanel->StudyId(), m_sweepPanel->Offset());
    }
}
