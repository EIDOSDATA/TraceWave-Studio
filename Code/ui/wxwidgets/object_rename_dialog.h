/** @file @brief 객체 이름 초안과 원자 이름 변경 명령을 연결한다. */
#pragma once
#include "project_setup_dialog.h"

class wxTextCtrl;
class wxButton;

/** @brief 실패한 이름 입력과 미확정 변경을 보존하는 D15 대화상자다. */
class ObjectRenameDialog final : public ProjectSetupDialog
{
public:
    ObjectRenameDialog(wxWindow* parent, const Json& context, DialogGateway gateway);

private:
    friend class StudioSmokeDriver;
    bool HasDraft() const override;
    void UpdateActions() override;
    Json m_selection;
    std::string m_original;
    wxTextCtrl* m_name = nullptr;
    wxButton* m_apply = nullptr;
};
