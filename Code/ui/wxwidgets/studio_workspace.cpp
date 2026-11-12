/** @file @brief 작업별 이동, 표시 층과 실제 작업 상태를 기존 서비스 연결 위에 조립한다. */
#include "studio_internal.h"
#include "workspace_bar.h"
#include "studio_theme.h"
#include "study_report_dialog.h"
#include <wx/artprov.h>
#include <wx/imaglist.h>

void StudioFrame::BuildWorkspacePages()
{
    const auto action = [this](wxWindow* parent, wxSizer* layout, int id, const std::string& label)
    {
        auto* button = new wxButton(parent, wxID_ANY, Display(label));
        button->SetMinSize(FromDIP(wxSize(180, 34)));
        layout->Add(button, 0, wxALL, FromDIP(StudioTheme::InputGap));
        m_workspaceCommands.emplace_back(id, button);
        button->Bind(wxEVT_BUTTON, [this, id](wxCommandEvent&)
        {
            wxCommandEvent command(wxEVT_MENU, id);
            GetEventHandler()->ProcessEvent(command);
        });
    };
    const auto page = [this](const std::string& title, const std::string& help)
    {
        auto* panel = new wxPanel(m_views);
        StudioTheme::BindSurface(*panel);
        auto* layout = new wxBoxSizer(wxVERTICAL);
        auto* heading = new wxStaticText(panel, wxID_ANY, Display(title));
        StudioTheme::Heading(*heading);
        layout->Add(heading, 0, wxALL, FromDIP(StudioTheme::PanelPadding));
        auto* text = new wxStaticText(panel, wxID_ANY, Display(help));
        text->Wrap(FromDIP(440));
        layout->Add(text, 0, wxALL, FromDIP(StudioTheme::PanelPadding));
        panel->SetSizer(layout);
        return panel;
    };
    auto* analysis = page("해석 준비", "현재 설계의 재료/급전/수치 조건을 확인합니다.\n목표나 초기 길이를 저장해도 해석은 자동 실행되지 않습니다.");
    action(analysis, analysis->GetSizer(), IdValidate, "현재 설계 입력 검사");
    action(analysis, analysis->GetSizer(), IdRunSolver, "해석 조건 확인 및 실행");
    action(analysis, analysis->GetSizer(), IdProjectStudy, "수치 연구 설정");
    m_analysisSummary = new wxStaticText(analysis, wxID_ANY, wxEmptyString);
    analysis->GetSizer()->Add(m_analysisSummary, 0, wxALL, FromDIP(StudioTheme::PanelPadding));
    m_views->AddPage(analysis, Display("해석 준비"));
    auto* comparison = page("연구 비교", "저장된 수렴 연구 보고서의 조건과 판정을 비교합니다.\n일반 다중 RF 결과/측정 곡선 비교는 후속 범위입니다.");
    auto* open = new wxButton(comparison, wxID_ANY, Display("수렴 연구 보고서 열기"));
    comparison->GetSizer()->Add(open, 0, wxALL, FromDIP(StudioTheme::PanelPadding));
    open->Bind(wxEVT_BUTTON, [this](wxCommandEvent&)
    {
        ShowStudyReport(this);
    });
    m_views->AddPage(comparison, Display("연구 비교"));
    auto* output = page("출력", "현재 개정을 스냅샷으로 고정하여 STEP/3D 형상을 생성합니다.\n형상 생성 성공은 독립 교환 검수나 제조/RF/실측 합격을 뜻하지 않습니다.");
    action(output, output->GetSizer(), IdExportStep, "STEP 출력");
    action(output, output->GetSizer(), IdBuild3D, "현재 설계의 3D 갱신");
    action(output, output->GetSizer(), IdOutputFolder, "완료 출력 폴더 열기");
    m_outputSummary = new wxStaticText(output, wxID_ANY, wxEmptyString);
    output->GetSizer()->Add(m_outputSummary, 0, wxALL, FromDIP(StudioTheme::PanelPadding));
    m_views->AddPage(output, Display("출력"));
    m_workspaceJobs = new wxListCtrl(m_bottom, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT);
    m_workspaceJobs->SetName("workspace.jobs");
    m_workspaceJobs->AppendColumn(Display("작업"), wxLIST_FORMAT_LEFT, FromDIP(120));
    m_workspaceJobs->AppendColumn(Display("상태"), wxLIST_FORMAT_LEFT, FromDIP(110));
    m_workspaceJobs->AppendColumn(Display("내용"), wxLIST_FORMAT_LEFT, FromDIP(500));
    m_workspaceJobs->InsertItem(0, Display("CAD / STEP"));
    m_workspaceJobs->InsertItem(1, Display("해석"));
    ShowWorkspaceJob(0, "idle", "아직 작업을 실행하지 않았습니다.");
    ShowWorkspaceJob(1, "idle", "아직 작업을 실행하지 않았습니다.");
    m_bottom->AddPage(m_workspaceJobs, Display("작업"));
    m_bottom->SetSelection(3);
    m_views->Bind(wxEVT_NOTEBOOK_PAGE_CHANGED, [this](wxBookCtrlEvent& event)
    {
        const int page = event.GetSelection();
        m_workspaceBar->Select(page < 2 ? WorkspaceArea::Design : static_cast<WorkspaceArea>(page == 2 ? 2 : (page == 3 ? 1 : page - 1)));
        event.Skip();
    });
}

void StudioFrame::NavigateWorkspace(WorkspaceArea area)
{
    const int pages[] = {0, 3, 2, 4, 5};
    m_views->SetSelection(pages[static_cast<int>(area)]);
    m_workspaceBar->Select(area);
}

void StudioFrame::BuildWorkspaceLayers()
{
    auto* panel = new wxPanel(this);
    StudioTheme::BindSurface(*panel);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_workspaceBoard = new wxCheckBox(panel, wxID_ANY, Display("기판 외곽 / 2D 표시"));
    m_workspaceBoard->SetName("workspace.board");
    m_workspaceBoard->SetValue(true);
    layout->Add(m_workspaceBoard, 0, wxALL, FromDIP(StudioTheme::InputGap));
    m_workspaceBoard->Bind(wxEVT_CHECKBOX, [this](wxCommandEvent&)
    {
        m_canvas->SetBoardVisible(m_workspaceBoard->GetValue());
    });
    m_workspaceLayers = new wxCheckListBox(panel, wxID_ANY);
    m_workspaceLayers->SetName("workspace.layers");
    m_workspaceLayers->SetToolTip(Display("선택: 활성 도체층 / 체크: 도체층 2D 표시. 유전체 적층은 프로젝트 트리에서 편집합니다. 저장 원본과 해석 포함 여부는 변경하지 않습니다."));
    layout->Add(m_workspaceLayers, 1, wxEXPAND | wxALL, FromDIP(StudioTheme::Space));
    panel->SetSizer(layout);
    m_manager->AddPane(panel, wxAuiPaneInfo().Name("layers").Caption(Display("레이어 / 2D 표시")).Left().Layer(1).Position(1)
                          .BestSize(FromDIP(wxSize(235, 170))).MinSize(FromDIP(wxSize(180, 100))).CloseButton(false));
    m_workspaceLayers->Bind(wxEVT_CHECKLISTBOX, [this](wxCommandEvent& event)
    {
        const int index = event.GetInt();
        if (index >= 0 && static_cast<std::size_t>(index) < m_workspaceLayerIds.size())
        {
            m_canvas->SetLayerVisible(m_workspaceLayerIds[index], m_workspaceLayers->IsChecked(index));
        }
    });
    m_workspaceLayers->Bind(wxEVT_LISTBOX, [this](wxCommandEvent& event)
    {
        const int index = event.GetInt();
        if (index < 0 || static_cast<std::size_t>(index) >= m_workspaceLayerIds.size())
        {
            return;
        }
        const auto found = std::find(m_layerIds.begin(), m_layerIds.end(), m_workspaceLayerIds[index]);
        if (found != m_layerIds.end())
        {
            m_activeLayer = *found;
            m_layerChoice->SetSelection(static_cast<int>(found - m_layerIds.begin()));
            m_canvas->SetDrawingLayer(m_activeLayer);
        }
    });
    auto* icons = new wxImageList(FromDIP(16), FromDIP(16), true);
    icons->Add(wxArtProvider::GetBitmap(wxART_FOLDER, wxART_OTHER, FromDIP(wxSize(16, 16))));
    icons->Add(wxArtProvider::GetBitmap(wxART_NORMAL_FILE, wxART_OTHER, FromDIP(wxSize(16, 16))));
    m_tree->AssignImageList(icons);
}

void StudioFrame::RefreshLayerList()
{
    if (m_workspaceLayers == nullptr)
    {
        return;
    }
    m_workspaceLayers->Freeze();
    m_workspaceLayers->Clear();
    m_workspaceLayerIds.clear();
    for (const auto& layer : m_scene.value("layers", Json::array()))
    {
        if (layer.at("role") != "conductor")
        {
            continue;
        }
        const std::string id = layer.at("id");
        const int index = m_workspaceLayers->Append(Display(layer.at("label").get<std::string>()));
        m_workspaceLayerIds.push_back(id);
        m_workspaceLayers->Check(index, m_canvas->IsLayerVisible(id));
        if (id == m_activeLayer)
        {
            m_workspaceLayers->SetSelection(index);
        }
    }
    m_workspaceLayers->Thaw();
}

void StudioFrame::ShowWorkspaceJob(long row, const std::string& state, const std::string& message)
{
    if (m_workspaceJobs != nullptr)
    {
        const std::map<std::string, std::string> labels{{"idle", "대기"}, {"unavailable", "환경 필요"}, {"queued", "대기열"},
            {"preparing", "준비 중"}, {"running", "실행 중"}, {"postprocessing", "후처리 중"}, {"completed", "완료"},
            {"failed", "실패"}, {"cancel_requested", "취소 요청 중"}, {"cancelled", "취소됨"}, {"interrupted", "중단됨"}};
        const auto found = labels.find(state);
        m_workspaceJobs->SetItem(row, 1, Display(found == labels.end() ? state : found->second));
        m_workspaceJobs->SetItem(row, 2, Display(message));
    }
}

void StudioFrame::UpdateWorkspace()
{
    if (m_workspaceBar == nullptr || m_workspaceJobs == nullptr)
    {
        return;
    }
    m_workspaceBar->SetCommandState(m_tools.at(IdSave)->IsEnabled(), m_tools.at(IdRunSolver)->IsEnabled(), m_tools.at(IdExportStep)->IsEnabled());
    for (const auto& item : m_workspaceCommands)
    {
        item.second->Enable(m_tools.at(item.first)->IsEnabled());
    }
    m_workspaceLayers->Enable(m_connected && !m_busy && !m_project.empty());
    m_workspaceBoard->Enable(m_connected && !m_busy && !m_project.empty());
    m_analysisSummary->SetLabel(Display(m_solverConfigured ? "해석 환경 구성됨 / 입력 검사와 해석 실행은 별도입니다." : "해석 환경이 구성되지 않았습니다. 편집/저장은 계속 사용할 수 있습니다."));
    m_analysisSummary->Wrap(FromDIP(440));
    m_outputSummary->SetLabel(Display(m_cadConfigured ? "CAD 환경 구성됨 / 출력 상태는 하단 작업/CAD 출력에서 확인합니다." : "CAD 환경이 구성되지 않았습니다. 기존 형상/출처와 저장은 유지합니다."));
    m_outputSummary->Wrap(FromDIP(440));
}
