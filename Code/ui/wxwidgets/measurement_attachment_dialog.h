/** @file @brief 근거 원문 보관과 측정 기록 연결을 분리하는 유한 파일 전송 창이다. */
#pragma once
#include "project_setup_dialog.h"
#include "measurement_recovery.h"
#include <memory>
class wxTextCtrl;
class wxChoice;
class wxButton;

class MeasurementAttachmentDialog final : public ProjectSetupDialog
{
public:
    MeasurementAttachmentDialog(wxWindow* parent, const Json& context, DialogGateway gateway,
                                std::shared_ptr<MeasurementRecovery> recovery);
    const Json& Attachment() const;

private:
    friend class StudioSmokeDriver;
    bool HasDraft() const override;
    void UpdateActions() override;
    void Browse();
    void Upload();
    void Recover();
    void Accept(const Json& response);
    Json m_attachment = nullptr;
    std::string m_name, m_encoded, m_sha256;
    std::size_t m_bytes = 0;
    DialogGateway m_gateway;
    std::shared_ptr<MeasurementRecovery> m_recovery;
    bool m_recovering = false;
    wxTextCtrl* m_path = nullptr;
    wxChoice* m_role = nullptr;
    wxChoice* m_media = nullptr;
    wxButton* m_browse = nullptr;
    wxButton* m_upload = nullptr;
    wxButton* m_recover = nullptr;
};
