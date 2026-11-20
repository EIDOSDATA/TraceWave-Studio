/** @file @brief 파일 메뉴의 복원 검토와 권위 서비스 적용을 연결한다. */
#include "studio_internal.h"
#include "archive_restore_dialog.h"

void StudioFrame::OpenArchiveRestore()
{
    if (!m_connected || m_closing || !m_archiveRestoreSupported || !GetMenuBar()->IsEnabled(IdArchiveRestore))
    {
        return;
    }
    DialogGateway gateway = [this](const std::string& method, const Json& input, bool mutation,
                                   std::function<void(const Json&)> success, std::function<void(const Json&)> failure)
    {
        if (!m_connected || m_closing)
        {
            failure({{"code", "E_CONNECTION"}, {"message", "수신 작업 영역에 연결하지 못했습니다."}});
            return;
        }
        Send(method, input, mutation, Json::object(), std::move(success), std::move(failure));
    };
    ArchiveRestoreDialog dialog(this, m_options.workspace, std::move(gateway));
    if (dialog.ShowModal() == wxID_OK && !dialog.OpenPath().empty() && ConfirmDiscard())
    {
        OpenProject("open", dialog.OpenPath());
    }
}
