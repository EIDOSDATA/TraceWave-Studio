/** @file @brief 공통 결과 컨트롤러를 현재 프로젝트와 Studio 도킹에 연결한다. */
#include "studio_internal.h"
#include "result_workspace.h"
#include "network_export.h"
#include "studio_shell.h"
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
    m_views->SetGroups({0, 0, 2, 1, 3, 4, 2, 2, 1, 2, 2, 2, 2, 2, 3});
    m_views->SetDisplayOrder({0, 1, 9, 10, 11, 12, 13, 7, 6, 2, 3, 8, 14, 4, 5});
}
void StudioFrame::UpdateResultViews()
{
    if (!m_results)
    {
        return;
    }
    m_results->Update(m_project, m_epoch, m_revision,
                      m_connected && m_resultsSupported && !m_project.empty() && !m_closing && !m_busy &&
                          m_setupDialog == nullptr,
                      m_views->GetSelection());
    m_tree->GetParent()->Layout();
    m_properties->Layout();
}
