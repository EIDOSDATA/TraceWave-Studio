/** @file @brief 공통 결과 컨트롤러를 현재 프로젝트와 Studio 도킹에 연결한다. */
#include "studio_internal.h"
#include "result_workspace.h"
#include "network_export.h"
#include "studio_shell.h"
#include "large_result_dialog.h"
#include <fstream>

/** @brief 선택한 원문을 현재 프로젝트의 결과 보관 영역으로 연결한다. */
void StudioFrame::ShowLargeResultLibrary()
{
    Json fixture;
    if (m_options.largeResultsSmoke)
    {
        try
        {
            const auto workspace = std::filesystem::path(m_options.workspace.ToStdWstring());
            std::ifstream input(workspace / "large-results-fixture.json", std::ios::binary);
            input >> fixture;
        }
        catch (const std::exception&)
        {
            m_smoke->FinishSmoke(false, "대용량 결과 시험 자료를 읽을 수 없습니다.");
            return;
        }
    }
    const int result = RunLargeResultLibrary(std::move(fixture));
    if (m_options.largeResultsSmoke)
    {
        if (result == wxID_OK)
        {
            wxCommandEvent save(wxEVT_MENU, IdSave);
            GetEventHandler()->ProcessEvent(save);
        }
        else
        {
            m_smoke->FinishSmoke(false, "대용량 결과 화면의 검증이 완료되지 않았습니다.");
        }
    }
}

/** @brief 같은 View 수명과 실제 서비스 게이트웨이로 사용자 입력과 통합 시험을 연다. */
int StudioFrame::RunLargeResultLibrary(Json fixture)
{
    if (!m_connected || m_closing || m_busy || m_project.empty())
    {
        Log("프로젝트를 연 뒤 대용량 결과를 등록하고 조회하십시오.");
        return wxID_CANCEL;
    }
    const auto project = m_project;
    const auto epoch = m_epoch;
    const auto workspace = std::filesystem::path(m_options.workspace.ToStdWstring());
    const auto projectPath = workspace / std::filesystem::path(Display(m_path).ToStdWstring());
    DialogGateway gateway = [this, project, epoch](const std::string& method, const Json& input, bool mutation,
                                                  std::function<void(const Json&)> success,
                                                  std::function<void(const Json&)> failure)
    {
        if (!m_connected || m_closing || m_project != project || m_epoch != epoch)
        {
            failure({{"message", "프로젝트 연결이 바뀌었습니다. 상태를 확인한 뒤 다시 여십시오."}});
            return;
        }
        Send(method, input, mutation, method == "job.status" ? Json::object() : Context(),
             std::move(success), std::move(failure));
    };
    LargeResultDialog dialog(this, projectPath, m_revision, std::move(gateway));
    if (!fixture.is_null())
    {
        dialog.StartSmoke(std::move(fixture));
    }
    return dialog.ShowModal();
}
void StudioFrame::BuildResultInterface()
{
    DialogGateway gateway = [this](const std::string& method, const Json& input, bool mutation,
                                   std::function<void(const Json&)> success, std::function<void(const Json&)> failure)
    {
        if (mutation || !m_connected || m_closing || m_project.empty())
        {
            failure({{"code", "E_STATE"}, {"message", "현재 프로젝트의 읽기 전용 결과 조회를 사용할 수 없습니다."}});
            return;
        }
        Send(method, input, false, Context(), std::move(success), std::move(failure));
    };
    m_results = std::make_unique<ResultWorkspace>(m_views, m_tree->GetParent(), m_properties, std::move(gateway));
    m_results->onSolverEvidence = [this](const std::string& artifact)
    {
        OpenSolverEvidence(artifact, this);
    };
    m_results->onFieldRefinement = [this](const Json& proposal)
    {
        if (m_project != proposal.at("project_id").get<std::string>() ||
            m_revision != proposal.at("revision_id").get<std::string>())
        {
            Log("전계가 계산된 설계 개정을 연 뒤 해당 격자를 적용하십시오.");
            return;
        }
        ConfigureSolver({}, proposal.at("settings"));
    };
    m_results->onFieldStudy = [this](const Json& options)
    {
        if (!m_connected || m_closing || m_busy || m_project.empty())
        {
            return;
        }
        const auto project = m_project, epoch = m_epoch;
        auto input = options;
        input["expected_revision"] = m_revision;
        Send("study.create_field", input, true, Context(), [this, project, epoch](const Json& created)
        {
            if (!m_closing && m_project == project && m_epoch == epoch)
            {
                const std::string identity = created.at("study_id");
                Send("study.start", {{"study_id", identity}}, true, Context(),
                     [this, project, epoch, identity](const Json&)
                     {
                         if (!m_closing && m_project == project && m_epoch == epoch)
                         {
                             OpenProjectStudy(identity);
                         }
                     });
            }
        });
    };
    m_results->onFocusSource = [this]()
    {
        if (m_shell)
        {
            m_shell->ShowNavigation(true);
        }
        m_results->NavigationView()->SetFocus();
    };
    m_results->onOpenTools = [this]()
    {
        m_views->SetSelection(6);
    };
    m_results->onConfigureField = [this]()
    {
        if (!m_solverConfigured)
        {
            wxMessageBox(Display("Windows 해석 환경을 연결한 뒤 기록 설정을 열 수 있습니다."),
                         Display("필드 기록 설정"), wxOK | wxICON_INFORMATION, this);
            return;
        }
        ConfigureSolver({}, nullptr, true);
    };
    m_results->onExportResult = [this](const Json& result)
    {
        const auto project = m_project, epoch = m_epoch;
        CallAfter(
            [this, result, project, epoch]()
            {
                if (!m_closing && m_connected && m_project == project && m_epoch == epoch)
                {
                    SaveNetworkExport(this, result, m_options.workspace);
                }
            });
    };
    m_views->SetPageText(6, Display("자료 / 정합"));
}
void StudioFrame::UpdateResultViews()
{
    if (!m_results)
    {
        return;
    }
    m_results->SetMeasurementAvailable(m_measurementSupported);
    m_results->Update(m_project, m_epoch, m_revision,
                      m_connected && m_resultsSupported && !m_project.empty() && !m_closing && !m_busy &&
                          m_setupDialog == nullptr,
                      m_views->GetSelection());
    m_tree->GetParent()->Layout();
    m_properties->Layout();
}
