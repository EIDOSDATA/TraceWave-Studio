/** @file @brief 해석 탭의 상태, 그래프와 펼쳐 보는 작업 기록이다. */
#include "studio_internal.h"
#include "studio_theme.h"
#include <wx/collpane.h>
#include <wx/wrapsizer.h>

/** @brief 해석 작업 상태와 결과 그래프를 기존 설계 탭과 분리하여 구성한다. */
void StudioFrame::BuildSolverInterface()
{
    auto* panel = new wxPanel(m_views);
    StudioTheme::BindSurface(*panel);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    auto* tools = new wxWrapSizer(wxHORIZONTAL);
    AddTool(panel, tools, IdRunSolver, "설정 및 해석 실행");
    AddTool(panel, tools, IdCancelSolver, "해석 취소");
    AddTool(panel, tools, IdReuseSolverConditions, "결과 조건 다시 사용");
    AddTool(panel, tools, IdRadiation, "방사 패턴 조회");
    AddTool(panel, tools, IdProjectStudy, "프로젝트 연구");
    layout->Add(tools, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::Space));
    m_solverMetric = new wxChoice(panel, wxID_ANY);
    m_solverMetric->SetName(Display("해석 그래프 항목"));
    for (const auto* name : {"반사계수 S11 (dB)", "정재파비 (VSWR)", "임피던스 (Ω)"})
    {
        m_solverMetric->Append(Display(name));
    }
    m_solverMetric->SetSelection(0);
    layout->Add(m_solverMetric, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::InputGap));
    m_solverStatus = new wxStaticText(panel, wxID_ANY, Display("해석 환경 연결을 확인하고 있습니다."),
                                      wxDefaultPosition, wxDefaultSize, wxST_NO_AUTORESIZE | wxST_ELLIPSIZE_END);
    m_solverStatus->SetName("solver.status");
    StudioTheme::Heading(*m_solverStatus);
    layout->Add(m_solverStatus, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::InputGap));
    m_solverViewState =
        new wxStaticText(panel, wxID_ANY, Display("표시할 해석 결과가 없습니다."),
                         wxDefaultPosition, wxDefaultSize, wxST_NO_AUTORESIZE | wxST_ELLIPSIZE_END);
    m_solverViewState->SetName("solver.result_summary");
    StudioTheme::BindSecondary(*m_solverViewState);
    layout->Add(m_solverViewState, 0, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(StudioTheme::InputGap));
    m_solverChart = new SolverChart(panel);
    layout->Add(m_solverChart, 1, wxEXPAND | wxALL, FromDIP(StudioTheme::Space));
    auto* history = new wxCollapsiblePane(panel, wxID_ANY, Display("작업 기록"), wxDefaultPosition,
                                           wxDefaultSize, wxCP_NO_TLW_RESIZE);
    auto* historyLayout = new wxBoxSizer(wxVERTICAL);
    m_solverDetails = new wxTextCtrl(history->GetPane(), wxID_ANY, wxEmptyString, wxDefaultPosition,
                                     FromDIP(wxSize(-1, 96)), wxTE_MULTILINE | wxTE_READONLY | wxTE_WORDWRAP);
    m_solverDetails->SetName(Display("해석 작업 기록"));
    historyLayout->Add(m_solverDetails, 1, wxEXPAND | wxTOP, FromDIP(StudioTheme::Space));
    history->GetPane()->SetSizer(historyLayout);
    layout->Add(history, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::InputGap));
    history->Bind(wxEVT_COLLAPSIBLEPANE_CHANGED,
                  [panel](wxCollapsiblePaneEvent&)
                  {
                      panel->Layout();
                  });
    panel->SetSizer(layout);
    m_views->AddPage(panel, Display("해석 결과"));
}

/** @brief 작업 기록의 표시 문구를 상태 기계 코드와 분리한다. */
void StudioFrame::SolverStatus(const std::string& state, const std::string& message)
{
    ShowWorkspaceJob(1, state, message);
    const auto label = Display(message);
    const bool repeated = m_solverState == state && m_solverStatus->GetLabel() == label;
    m_solverState = state;
    if (repeated)
    {
        return;
    }
    m_solverStatus->SetLabel(label);
    m_solverStatus->SetToolTip(label);
    m_solverStatus->GetParent()->Layout();
    m_solverDetails->AppendText(label + "\n");
    if (m_solverDetails->GetLastPosition() > 24000)
    {
        long rowIndex = 0;
        const long cutoff = m_solverDetails->GetLastPosition() - 16000;
        const long lineEnd = m_solverDetails->PositionToXY(cutoff, nullptr, &rowIndex)
            ? m_solverDetails->XYToPosition(0, rowIndex + 1) : -1;
        m_solverDetails->Remove(0, lineEnd > 0 ? lineEnd : cutoff);
    }
}

/** @brief 저장된 결과의 개정 차이와 아직 검증하지 않은 상태를 계속 표시한다. */
void StudioFrame::UpdateSolverView()
{
    if (m_solverSamples.empty())
    {
        return;
    }
    const bool stale = m_solverSamples.at("snapshot").at("revision_id") != m_revision;
    const auto label = Display((stale ? "이전 설계 결과 (" : "현재 설계 결과 (") +
                               std::to_string(m_solverChart->SampleCount()) + "개 주파수) · IFA·방사 정확도 검증 전");
    if (m_solverViewState->GetLabel() != label)
    {
        m_solverViewState->SetLabel(label);
        m_solverViewState->SetToolTip(label);
    }
}
