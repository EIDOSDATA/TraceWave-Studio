/** @file @brief 목표 평가를 참조하는 후속 연구의 시작 및 진행을 표시한다. */
#pragma once
#include "project_setup_dialog.h"
#include <wx/timer.h>
#include <set>

class wxSpinCtrl;
class wxCheckBox;
class wxButton;

/** @brief 기존 연구 예산으로 후속 연구를 순차 실행하는 화면이다. */
class SweepRefinementDialog final : public ProjectSetupDialog
{
public:
    SweepRefinementDialog(wxWindow* parent, const Json& context, const std::string& seed, DialogGateway gateway);

private:
    void Advance();
    void Poll();
    void Stop(const std::string& message);
    bool HasDraft() const override;
    void UpdateActions() override;
    void ShowRequestFailure(const Json& error) override;
    std::string m_seed;
    std::string m_waiting;
    wxTimer m_timer;
    std::set<std::string> m_resumed;
    wxSpinCtrl* m_rounds;
    wxCheckBox* m_untilTarget;
    wxCheckBox* m_resume;
    wxButton* m_start;
    bool m_running = false;
};
