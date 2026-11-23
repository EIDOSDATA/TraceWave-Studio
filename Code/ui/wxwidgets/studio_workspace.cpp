/** @file @brief 작업별 이동, 표시 층과 실제 작업 상태를 기존 서비스 연결 위에 조립한다. */
#include "studio_internal.h"
#include "workspace_bar.h"
#include "studio_theme.h"
#include "drawing_rail.h"
#include "study_report_dialog.h"
#include <wx/artprov.h>
#include <wx/imaglist.h>

void StudioFrame::BuildWorkspacePages()
{
    const auto action = [this](wxWindow* parent, wxSizer* layout, int id, const std::string& label)
    {
        auto* button = new wxButton(parent, wxID_ANY, Display(label));
        StudioTheme::Button(*button, id == IdRunSolver);
        layout->Add(button, 0, wxALL, FromDIP(StudioTheme::InputGap));
        m_workspaceCommands.emplace_back(id, button);
        button->Bind(wxEVT_BUTTON,
                     [this, id](wxCommandEvent&)
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
        StudioTheme::Title(*heading);
        layout->Add(heading, 0, wxALL, FromDIP(StudioTheme::PanelPadding));
        auto* text = new wxStaticText(panel, wxID_ANY, Display(help));
        StudioTheme::BindSecondary(*text);
        text->Wrap(FromDIP(440));
        layout->Add(text, 0, wxALL, FromDIP(StudioTheme::PanelPadding));
        panel->SetSizer(layout);
        return panel;
    };
    auto* analysis = page(
        "해석 준비",
        "현재 설계의 재료/급전/수치 조건을 확인합니다.\n목표나 초기 길이를 저장해도 해석은 자동 실행되지 않습니다.");
    action(analysis, analysis->GetSizer(), IdValidate, "현재 설계 입력 검사");
    action(analysis, analysis->GetSizer(), IdRunSolver, "해석 조건 확인 및 실행");
    action(analysis, analysis->GetSizer(), IdProjectStudy, "수치 연구 설정");
    const auto summary = m_solverConfigured ? "해석 환경 구성됨 / 입력 검사와 해석 실행은 별도입니다."
                                            : "해석 환경이 구성되지 않았습니다. 편집/저장은 계속 사용할 수 있습니다.";
    m_analysisSummary = new wxStaticText(analysis, wxID_ANY, Display(summary));
    m_analysisSummary->Wrap(FromDIP(440));
    analysis->GetSizer()->Add(m_analysisSummary, 0, wxALL, FromDIP(StudioTheme::PanelPadding));
    auto* environment = new wxButton(analysis, wxID_ANY, Display("실행 환경 / 진단"));
    StudioTheme::Button(*environment);
    analysis->GetSizer()->Add(environment, 0, wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::PanelPadding));
    environment->Bind(wxEVT_BUTTON, [this](wxCommandEvent&) { ShowEnvironment(); });
    m_views->AddPage(analysis, Display("해석 준비"));
    auto* comparison = page("수렴 연구", "저장된 수렴 연구 보고서의 조건과 판정을 확인합니다.\n여러 원본의 RF 곡선은 "
                                         "결과 / 후보 비교 탭에서 비교합니다.");
    auto* open = new wxButton(comparison, wxID_ANY, Display("수렴 연구 보고서 열기"));
    StudioTheme::Button(*open);
    comparison->GetSizer()->Add(open, 0, wxALL, FromDIP(StudioTheme::PanelPadding));
    open->Bind(wxEVT_BUTTON,
               [this](wxCommandEvent&)
               {
                   ShowStudyReport(this);
               });
    m_views->AddPage(comparison, Display("수렴 연구"));
    BuildOutputInterface();
}

void StudioFrame::BuildWorkspaceJobs()
{
    m_workspaceJobs = new wxListCtrl(m_bottom, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_HRULES);
    StudioTheme::Table(*m_workspaceJobs);
    m_workspaceJobs->SetName("workspace.jobs");
    m_workspaceJobs->AppendColumn(Display("작업"), wxLIST_FORMAT_LEFT, FromDIP(120));
    m_workspaceJobs->AppendColumn(Display("상태"), wxLIST_FORMAT_LEFT, FromDIP(110));
    m_workspaceJobs->AppendColumn(Display("내용"), wxLIST_FORMAT_LEFT, FromDIP(500));
    m_workspaceJobs->InsertItem(0, Display("CAD / STEP"));
    m_workspaceJobs->InsertItem(1, Display("해석"));
    m_workspaceJobs->InsertItem(2, Display("설계 연구"));
    m_workspaceJobs->InsertItem(3, Display("도면 / 출력 검수"));
    m_workspaceJobs->Bind(wxEVT_SIZE,
                          [this](wxSizeEvent& event)
                          {
                              m_workspaceJobs->SetColumnWidth(
                                  2, std::max(FromDIP(240), m_workspaceJobs->GetClientSize().x - FromDIP(236)));
                              event.Skip();
                          });
    ShowWorkspaceJob(0, "idle", "아직 작업을 실행하지 않았습니다.");
    ShowWorkspaceJob(1, "idle", "아직 작업을 실행하지 않았습니다.");
    ShowWorkspaceJob(2, "idle", "저장된 연구를 선택하고 실행합니다.");
    ShowWorkspaceJob(3, "idle", "고정 입력의 생성과 새 읽기 검수는 별도 단계입니다.");
    m_bottom->AddPage(m_workspaceJobs, Display("작업"));
    m_bottom->SetSelection(3);
    m_bottom->SetDisplayOrder({0, 3, 1, 2});
    m_views->SetPageText(2, Display("해석 결과"));
    m_views->onSelectionChanged = [this](int page)
    {
        if (page != 0)
        {
            EndPortPick(false);
        }
        m_workspaceBar->Select(page < 2                                              ? WorkspaceArea::Design
                               : page == 3 || page == 8                              ? WorkspaceArea::Analysis
                               : page == 4 || page == 14 || page == 15 || page == 16 ? WorkspaceArea::Comparison
                               : page == 5                                           ? WorkspaceArea::Output
                                                                                     : WorkspaceArea::Results);
        UpdateNetworkViews();
        UpdateSweepViews();
        UpdateResultViews();
        UpdateValidationViews();
        UpdateOutputViews();
    };
}

void StudioFrame::PrepareExtendedWorkspaces(std::size_t page)
{
    if (page < 2 || m_analysisSummary != nullptr)
    {
        return;
    }
    auto* navigation = m_tree->GetParent();
    const auto navigationChildren = navigation->GetChildren().GetCount();
    const auto propertiesChildren = m_properties->GetChildren().GetCount();
    const auto firstNewPage = m_views->GetPageCount();
    BuildWorkspacePages();
    BuildNetworkInterface();
    BuildSweepInterface();
    BuildResultInterface();
    BuildValidationInterface();
    BuildMeasurementInterface();
    StudioTheme::BindNativeControls(*navigation, navigationChildren);
    StudioTheme::BindNativeControls(*m_properties, propertiesChildren);
    for (std::size_t index = firstNewPage; index < m_views->GetPageCount(); ++index)
    {
        StudioTheme::BindNativeControls(*m_views->GetPage(index));
    }
    for (const auto& item : m_workspaceCommands)
    {
        item.second->Enable(m_tools.at(item.first)->IsEnabled());
    }
}

void StudioFrame::NavigateWorkspace(WorkspaceArea area)
{
    const int pages[] = {0, 3, 9, 14, 5};
    m_views->SetSelection(pages[static_cast<int>(area)]);
    m_workspaceBar->Select(area);
}

void StudioFrame::BuildWorkspaceLayers()
{
    auto* host = new wxPanel(this);
    StudioTheme::BindSurface(*host);
    host->SetSizer(new wxBoxSizer(wxVERTICAL));
    auto* panel = new wxPanel(host);
    panel->SetName("workspace.layer-content");
    StudioTheme::BindSurface(*panel);
    auto* layout = new wxBoxSizer(wxVERTICAL);
    m_workspaceBoard = new wxCheckBox(panel, wxID_ANY, Display("기판 외곽 / 2D 표시"));
    m_workspaceBoard->SetName("workspace.board");
    m_workspaceBoard->SetValue(true);
    layout->Add(m_workspaceBoard, 0, wxALL, FromDIP(StudioTheme::InputGap));
    m_workspaceBoard->Bind(wxEVT_CHECKBOX,
                           [this](wxCommandEvent&)
                           {
                               m_canvas->SetBoardVisible(m_workspaceBoard->GetValue());
                           });
    m_workspaceLayers = new wxCheckListBox(panel, wxID_ANY);
    m_workspaceLayers->SetName("workspace.layers");
    m_workspaceLayers->SetToolTip(Display("선택: 활성 도체층 / 체크: 도체층 2D 표시. 유전체 적층은 프로젝트 트리에서 "
                                          "편집합니다. 저장 원본과 해석 포함 여부는 변경하지 않습니다."));
    layout->Add(m_workspaceLayers, 1, wxEXPAND | wxALL, FromDIP(StudioTheme::Space));
    panel->SetSizer(layout);
    host->GetSizer()->Add(panel, 1, wxEXPAND);
    m_manager->AddPane(host, wxAuiPaneInfo()
                                 .Name("layers")
                                 .Caption(Display("레이어 / 2D 표시"))
                                 .Left()
                                 .Layer(1)
                                 .Position(1)
                                 .BestSize(FromDIP(wxSize(280, 170)))
                                 .MinSize(FromDIP(wxSize(220, 100)))
                                 .CloseButton(true));
    m_manager->GetPane("layers").dock_proportion = 1;
    m_workspaceLayers->Bind(wxEVT_CHECKLISTBOX,
                            [this](wxCommandEvent& event)
                            {
                                const int index = event.GetInt();
                                if (index >= 0 && static_cast<std::size_t>(index) < m_workspaceLayerIds.size())
                                {
                                    m_canvas->SetLayerVisible(m_workspaceLayerIds[index],
                                                              m_workspaceLayers->IsChecked(index));
                                    UpdatePortLinks();
                                }
                            });
    m_workspaceLayers->Bind(wxEVT_LISTBOX,
                            [this](wxCommandEvent& event)
                            {
                                const int index = event.GetInt();
                                if (index < 0 || static_cast<std::size_t>(index) >= m_workspaceLayerIds.size())
                                {
                                    return;
                                }
                                const auto found =
                                    std::find(m_layerIds.begin(), m_layerIds.end(), m_workspaceLayerIds[index]);
                                if (found != m_layerIds.end())
                                {
                                    m_activeLayer = *found;
                                    m_layerChoice->SetSelection(static_cast<int>(found - m_layerIds.begin()));
                                    m_canvas->SetDrawingLayer(m_activeLayer);
                                }
                            });
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
        const std::map<std::string, std::string> labels{
            {"idle", "대기"},         {"unavailable", "환경 필요"}, {"queued", "대기열"},
            {"preparing", "준비 중"}, {"running", "실행 중"},       {"postprocessing", "후처리 중"},
            {"completed", "완료"},    {"failed", "실패"},           {"cancel_requested", "취소 요청 중"},
            {"cancelled", "취소됨"},  {"interrupted", "중단됨"}};
        const auto found = labels.find(state);
        const bool needsCad = row == 0 && !m_cadConfigured && (state == "idle" || state == "unavailable");
        m_workspaceJobs->SetItem(row, 1,
                                 Display(needsCad ? "환경 필요" : (found == labels.end() ? state : found->second)));
        m_workspaceJobs->SetItem(
            row, 2, Display(needsCad ? "CAD 환경 연결 필요. 보기 > 실행 환경 / 진단에서 확인하세요." : message));
    }
}

void StudioFrame::UpdateWorkspace()
{
    SelectDrawingRail({m_tools.at(IdSelect), m_tools.at(IdLine), m_tools.at(IdArc), m_tools.at(IdRoute)},
                      m_drawTool == "line" ? 1 : (m_drawTool == "arc" ? 2 : (m_drawTool == "route" ? 3 : 0)));
    if (m_workspaceBar == nullptr || m_workspaceJobs == nullptr)
    {
        return;
    }
    m_workspaceBar->SetCommandState(m_tools.at(IdSave)->IsEnabled(), m_tools.at(IdRunSolver)->IsEnabled(),
                                    m_tools.at(IdExportStep)->IsEnabled());
    for (const auto& item : m_workspaceCommands)
    {
        item.second->Enable(m_tools.at(item.first)->IsEnabled());
    }
    m_workspaceLayers->Enable(m_connected && !m_busy && !m_project.empty());
    m_workspaceBoard->Enable(m_connected && !m_busy && !m_project.empty());
    if (m_analysisSummary != nullptr)
    {
        const auto summary = m_solverConfigured ? "해석 환경 구성됨 / 입력 검사와 해석 실행은 별도입니다."
                                                : "해석 환경이 구성되지 않았습니다. 편집/저장은 계속 사용할 수 있습니다.";
        m_analysisSummary->SetLabel(Display(summary));
        m_analysisSummary->Wrap(FromDIP(440));
    }
    UpdateNetworkViews();
    UpdateSweepViews();
    UpdateResultViews();
    UpdateValidationViews();
    UpdateOutputViews();
}
