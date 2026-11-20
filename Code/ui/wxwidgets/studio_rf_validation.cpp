/** @file @brief 읽기 전용 검증 기록을 기존 결과와 비교 작업 흐름에 연결한다. */
#include "studio_internal.h"
#include "rf_validation_controller.h"
#include "result_workspace.h"
#include "studio_shell.h"
#include "study_report_dialog.h"

void StudioFrame::BuildValidationInterface()
{
    DialogGateway gateway = [this](const std::string& method, const Json& input, bool mutation,
                                   std::function<void(const Json&)> success, std::function<void(const Json&)> failure)
    {
        if (mutation || !m_connected || m_closing || m_project.empty())
        {
            failure({{"code", "E_STATE"}, {"message", "현재 프로젝트의 검증 기록을 조회할 수 없습니다."}});
            return;
        }
        Send(method, input, false, Context(), std::move(success), std::move(failure));
    };
    m_validation =
        std::make_unique<RfValidationController>(m_views, m_tree->GetParent(), m_properties, std::move(gateway));
    m_validation->onOpenResult = [this](const Json& source, const Json& pin)
    {
        m_views->SetSelection(9);
        m_results->OpenPinned(source, pin);
    };
    m_validation->onLegacyReport = [this]()
    {
        ShowStudyReport(this);
    };
    m_results->onOpenValidation = [this]()
    {
        OpenValidationRecords();
    };
}

void StudioFrame::UpdateValidationViews()
{
    if (!m_validation)
    {
        return;
    }
    const bool available = m_connected && !m_closing && !m_busy && m_setupDialog == nullptr;
    m_validation->Update(m_project, m_epoch, m_connected, m_validationSupported, available, m_views->GetSelection());
    m_results->SetValidationAvailable(available && m_validationSupported && !m_project.empty());
    m_tree->GetParent()->Layout();
    m_properties->Layout();
}

void StudioFrame::OpenValidationRecords()
{
    m_views->SetSelection(15);
    if (m_shell)
    {
        m_shell->ShowNavigation(true);
    }
}
