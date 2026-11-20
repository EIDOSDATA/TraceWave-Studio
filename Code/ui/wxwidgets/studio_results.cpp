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
    if (!m_connected || m_closing || m_busy || m_project.empty())
    {
        Log("프로젝트를 연 뒤 대용량 결과를 등록하고 조회하십시오.");
        return;
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
    if (m_options.largeResultsSmoke)
    {
        try
        {
            std::ifstream input(workspace / "large-results-fixture.json", std::ios::binary);
            Json fixture;
            input >> fixture;
            dialog.StartSmoke(std::move(fixture));
        }
        catch (const std::exception&)
        {
            m_smoke->FinishSmoke(false, "대용량 결과 시험 자료를 읽을 수 없습니다.");
            return;
        }
    }
    const int result = dialog.ShowModal();
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
