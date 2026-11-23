/** @file @brief 봉인된 평가에서 제안한 구간과 실제 후속 연구의 상태를 연결한다. */
#include "studio_internal.h"
#include "sweep_refinement_dialog.h"

SweepRefinementDialog::SweepRefinementDialog(wxWindow* parent, const Json& context, const std::string& seed,
                                             DialogGateway gateway)
    : ProjectSetupDialog(parent, "목표 기반 반복 탐색", context, std::move(gateway)), m_seed(seed), m_timer(this)
{
    const int gap = FromDIP(12);
    SetName("sweep.refinement.dialog");
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* guide = new wxStaticText(this, wxID_ANY, Display(
        "완료된 평가에서 구간을 골라 양 끝과 중점을 다시 계산합니다. 각 회차는 후보 3개와 원래 연구의 남은 탐색 예산을 사용합니다."));
    guide->Wrap(FromDIP(460));
    layout->Add(guide, 0, wxEXPAND | wxALL, gap);
    auto* row = new wxBoxSizer(wxHORIZONTAL);
    row->Add(new wxStaticText(this, wxID_ANY, Display("최대 탐색 횟수")), 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, gap);
    m_rounds = new wxSpinCtrl(this, wxID_ANY, "2", wxDefaultPosition, wxDefaultSize, wxSP_ARROW_KEYS, 1, 42, 2);
    row->Add(m_rounds);
    layout->Add(row, 0, wxALL, gap);
    m_untilTarget = new wxCheckBox(this, wxID_ANY, Display("한 후보가 모든 목표 표본을 통과하면 종료"));
    m_resume = new wxCheckBox(this, wxID_ANY, Display("이전에 중단된 후속 연구 재개"));
    layout->Add(m_untilTarget, 0, wxLEFT | wxRIGHT | wxBOTTOM, gap);
    layout->Add(m_resume, 0, wxLEFT | wxRIGHT | wxBOTTOM, gap);
    m_status = new wxStaticText(this, wxID_ANY, Display("닫으면 다음 회차의 자동 시작을 멈춥니다. 진행 중인 연구는 연구 목록에서 확인할 수 있습니다."));
    m_status->Wrap(FromDIP(460));
    layout->Add(m_status, 1, wxEXPAND | wxALL, gap);
    auto* buttons = new wxBoxSizer(wxHORIZONTAL);
    m_start = new wxButton(this, wxID_ANY, Display("탐색 시작"));
    auto* close = new wxButton(this, wxID_CLOSE, Display("닫기"));
    buttons->Add(m_start, 0, wxRIGHT, gap);
    buttons->Add(close);
    layout->Add(buttons, 0, wxALIGN_RIGHT | wxALL, gap);
    SetSizerAndFit(layout);
    CentreOnParent();
    m_start->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        m_running = true;
        m_resumed.clear();
        UpdateActions();
        Advance();
    });
    close->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        CloseDialog();
    });
    Bind(wxEVT_TIMER, [this](wxTimerEvent&)
    {
        if (Editable() && m_running && !m_pending)
        {
            Poll();
        }
    }, m_timer.GetId());
}

bool SweepRefinementDialog::HasDraft() const
{
    return false;
}

void SweepRefinementDialog::UpdateActions()
{
    const bool enable = Editable() && !m_running;
    m_rounds->Enable(enable);
    m_start->Enable(enable);
    m_untilTarget->Enable(enable);
    m_resume->Enable(enable);
}

void SweepRefinementDialog::ShowRequestFailure(const Json& error)
{
    Stop(DiagnosticMessage(error));
}

void SweepRefinementDialog::Stop(const std::string& message)
{
    m_timer.Stop();
    m_running = false;
    m_waiting.clear();
    SetStatus(message);
    UpdateActions();
}

void SweepRefinementDialog::Poll()
{
    Request("sweep.get", {{"study_id", m_waiting}}, false, [this](const Json& result)
    {
        const auto state = result.at("state").get<std::string>();
        if (state == "running" || state == "resuming" || state == "cancel_requested")
        {
            SetStatus(result.value("message", std::string()) + " / " + m_waiting);
            m_timer.StartOnce(2000);
            return;
        }
        Advance();
    });
}

void SweepRefinementDialog::Advance()
{
    const Json input = {{"study_id", m_seed}, {"rounds", m_rounds->GetValue()}, {"until_target", m_untilTarget->GetValue()},
                        {"resume", m_resume->GetValue()}};
    Request("sweep.refine_preview", input, false, [this](const Json& result)
    {
        const auto action = result.at("stop_reason").get<std::string>();
        const auto count = result.at("iterations").size();
        if (action == "wait")
        {
            m_waiting = result.at("input").at("study_id").get<std::string>();
            SetStatus("후속 연구 " + std::to_string(count) + "회차 실행 중 / " + m_waiting);
            m_timer.StartOnce(2000);
            return;
        }
        if (action == "create" || action == "start" || action == "resume")
        {
            const auto& command = result.at("input");
            if (action == "resume" && !m_resumed.insert(command.at("study_id").get<std::string>()).second)
            {
                Stop("재개한 연구가 다시 중단되었습니다. 실행 이력을 확인하세요.");
                return;
            }
            SetStatus("후속 연구 " + std::to_string(count + (action == "create" ? 1 : 0)) + "회차 준비 중");
            Request("sweep." + action, command, true, [this](const Json&)
            {
                Advance();
            });
            return;
        }
        const std::map<std::string, std::string> reasons = {
            {"round_limit", "지정한 회차 완료"}, {"sample_targets_met", "목표 표본 통과"},
            {"budget_exhausted", "탐색 예산 소진"}, {"native_solve_budget", "해석 횟수 예산 소진"},
            {"no_distinct_valid_bracket", "새 구간 없음"}, {"invalid_bracket", "구간 입력 오류"},
            {"incomplete_bracket", "완료한 후보 부족"}, {"failed", "실행 실패"}, {"blocked", "실행 차단"},
            {"interrupted", "실행 중단"}, {"cancelled", "사용자 취소"}};
        const auto reason = reasons.find(action);
        Stop("탐색 종료 / " + (reason == reasons.end() ? action : reason->second) + " / 후속 연구 " + std::to_string(count) + "개");
    });
}
