/** @file @brief 주 창의 layout 책임을 구현한다. */
#include "studio_internal.h"
#include "study_report_dialog.h"
#include "project_evidence_dialog.h"
#include "studio_theme.h"
#include "workspace_bar.h"
#include "drawing_rail.h"
#include "studio_shell.h"
#include <wx/statline.h>
#include <wx/textdlg.h>
#include <wx/wrapsizer.h>

namespace
{
/** @brief 한글 동작 이름을 표시하는 프로젝트 입력 대화상자다. */
wxString ReadProjectText(wxWindow& parent, const char* title, const char* prompt,
                         const wxString& initial, const char* action)
{
    wxTextEntryDialog dialog(&parent, Display(prompt), Display(title), initial);
    auto* apply = wxDynamicCast(dialog.FindWindow(wxID_OK), wxButton);
    auto* cancel = wxDynamicCast(dialog.FindWindow(wxID_CANCEL), wxButton);
    if (apply && cancel)
    {
        apply->SetLabel(Display(action));
        cancel->SetLabel(Display("취소"));
        StudioTheme::Button(*apply, true);
        StudioTheme::Button(*cancel);
        dialog.SetMinSize(dialog.FromDIP(wxSize(375, -1)));
        dialog.Fit();
    }
    StudioTheme::BindSurface(dialog);
    dialog.CentreOnParent();
    return dialog.ShowModal() == wxID_OK ? dialog.GetValue() : wxString();
}
}

/** @brief 프로젝트 메타데이터와 선택 객체의 서비스 기반 입력 폼을 구성한다. */
void StudioFrame::BuildInterface()
{
    const auto addEvidence = [this](wxMenu& menu, const char* label, std::size_t page)
    {
        const int id = wxWindow::NewControlId();
        menu.Append(id, Display(label));
        Bind(wxEVT_MENU, [this, page](wxCommandEvent&)
        {
            if (!m_connected || m_busy || m_project.empty() || m_setupDialog)
            {
                return;
            }
            const auto project = m_project;
            const auto revision = m_revision;
            Send("project.evidence", Json{{"expected_revision", revision}}, false, Context(),
                 [this, project, revision, page](const Json& result)
                 {
                     CallAfter([this, project, revision, page, result]()
                     {
                         if (m_closing || !m_connected || m_project != project || m_revision != revision)
                         {
                             return;
                         }
                         const int selected = ShowProjectEvidence(this, result, page);
                         if (selected == wxID_OK)
                         {
                             wxCommandEvent command(wxEVT_MENU, IdRefresh);
                             ProcessWindowEvent(command);
                         }
                         else if (selected == wxID_APPLY)
                         {
                             OpenArchiveRestore();
                         }
                     });
                 },
                 [this](const Json& error) { Log("출처 조회 실패: " + DiagnosticMessage(error)); });
        }, id);
        Bind(wxEVT_UPDATE_UI, [this](wxUpdateUIEvent& event)
        {
            event.Enable(m_connected && !m_busy && !m_project.empty() && m_setupDialog == nullptr);
        }, id);
    };
    auto* menu = new wxMenu;
    menu->Append(IdCreate, Display("새 프로젝트(&N)\tCtrl+N"));
    menu->Append(IdOpen, Display("프로젝트 열기(&O)\tCtrl+O"));
    addEvidence(*menu, "저장본 / 복구 후보 검토...", 3);
    menu->Append(IdArchiveRestore, Display("프로젝트 보존 묶음 복원..."));
    menu->AppendSeparator();
    menu->Append(IdSave, Display("저장(&S)\tCtrl+S"));
    menu->Append(IdSnapshot, Display("스냅샷 만들기"));
    menu->Append(IdExportStep, Display("STEP 출력 / 3D 갱신"));
    menu->Append(IdRefresh, Display("저장된 상태 다시 읽기\tF5"));
    menu->AppendSeparator();
    menu->Append(wxID_EXIT, Display("종료"));
    auto* edit = new wxMenu;
    edit->Append(IdUndo, Display("실행 취소\tCtrl+Z"));
    auto* redo = edit->Append(IdRedo, Display("다시 실행\tCtrl+Y"), Display("Ctrl+Y 또는 Ctrl+Shift+Z"));
    redo->AddExtraAccel(wxAcceleratorEntry(wxACCEL_CTRL | wxACCEL_SHIFT, 'Z', IdRedo));
    edit->AppendSeparator();
    edit->Append(IdNewParameter, Display("매개변수 추가"));
    edit->AppendSeparator();
    edit->Append(IdFindObject, Display("프로젝트 객체 찾기\tCtrl+F"));
    edit->Append(IdFindCommand, Display("명령 찾기\tCtrl+Shift+P"));
    Bind(wxEVT_MENU, [this](wxCommandEvent&) { FocusObjectSearch(); }, IdFindObject);
    Bind(wxEVT_MENU, [this](wxCommandEvent&) { ShowCommandSearch(); }, IdFindCommand);
    auto* bar = new wxMenuBar;
    bar->Append(menu, Display("파일(&F)"));
    bar->Append(edit, Display("편집"));
    auto* design = new wxMenu;
    design->Append(IdTargets, Display("목표 / 대역 설정"));
    design->Append(IdTemplates, Display("문헌 / 형상 / 초기 후보"));
    design->Append(IdDesignRules, Display("목표 제약 / 연결 / 기본 DRC"));
    design->AppendSeparator();
    design->Append(IdBoard, Display("직사각 기판 만들기"));
    design->Append(IdCircularBoard, Display("원형 기판 만들기"));
    design->Append(IdPcbSelection, Display("기판 설정 / 제조업체 자료"));
    design->Append(IdPhysicalSetup, Display("PCB / 적층과 외부 환경"));
    design->Append(IdPcbFeatures, Display("PCB 형상 / 풋프린트 / 제조 입력"));
    design->Append(IdPcbImport, Display("PCB / CAM 원문 가져오기"));
    design->Append(IdNewMaterial, Display("재료 추가"));
    design->Append(IdNewNet, Display("네트 추가"));
    design->Append(IdNewPort, Display("급전 포트 추가"));
    design->Append(IdLayer, Display("도체층 추가"));
    design->Append(IdDielectric, Display("유전체층 추가"));
    design->AppendSeparator();
    design->Append(IdCoordinates, Display("좌표로 선 / 원호 추가"));
    design->Append(IdPolygon, Display("다각형 도체 면 추가"));
    design->Append(IdCirclePad, Display("원형 패드 추가"));
    design->Append(IdRectanglePad, Display("직사각 패드 추가"));
    design->Append(IdVia, Display("도금 비아 추가"));
    design->Append(IdDeleteShape, Display("선택 형상 삭제"));
    design->Append(IdValidate, Display("해석 입력 검사"));
    bar->Append(design, Display("설계"));
    auto* analysis = new wxMenu;
    analysis->Append(IdRunSolver, Display("설정 및 해석 실행"));
    analysis->Append(IdReuseSolverConditions, Display("결과 조건 다시 사용"));
    analysis->Append(IdCancelSolver, Display("해석 작업 취소"));
    analysis->Append(IdRadiation, Display("방사 패턴 조회"));
    analysis->Append(IdProjectStudy, Display("프로젝트 연구 / 격자·방사·손실"));
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            OpenProjectStudy();
        },
        IdProjectStudy);
    const int studyReportId = wxWindow::NewControlId();
    analysis->Append(studyReportId, Display("수렴 연구 보고서 비교"));
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            ShowStudyReport(this);
        },
        studyReportId);
    const int largeResultsId = wxWindow::NewControlId();
    analysis->Append(largeResultsId, Display("대용량 결과 / 등록과 비교"));
    Bind(wxEVT_MENU, [this](wxCommandEvent&) { ShowLargeResultLibrary(); }, largeResultsId);
    analysis->Append(IdSweep, Display("설계 스윕 / 다축 연구"));
    Bind(wxEVT_MENU, [this](wxCommandEvent&) { m_views->SetSelection(8); }, IdSweep);
    bar->Append(analysis, Display("해석"));
    auto* view = new wxMenu;
    addEvidence(*view, "출처와 채택 이력...", 0);
    view->Append(IdResetLayout, Display("기본 패널 배치 복원"), Display("패널 이동: F6 / 이전 패널: Shift+F6"));
    view->Append(IdFit, Display("전체 형상 맞춤"));
    view->Append(IdBuild3D, Display("현재 설계로 3D 갱신"));
    view->Append(IdOutputFolder, Display("STEP 출력 폴더 열기"));
    view->Append(IdCancelCad, Display("CAD 작업 취소"));
    view->AppendSeparator();
    const int preferences = wxWindow::NewControlId();
    view->Append(preferences, Display("환경설정..."));
    Bind(wxEVT_MENU, [this](wxCommandEvent&) { ShowDisplayPreferences(); }, preferences);
    const int environmentHelp = wxWindow::NewControlId();
    view->Append(environmentHelp, Display("실행 환경 / 진단..."));
    Bind(wxEVT_MENU, [this](wxCommandEvent&) { ShowEnvironment(); }, environmentHelp);
    bar->Append(view, Display("보기"));
    SetMenuBar(bar);
    CreateStatusBar(3);
    const int statusWidths[] = {-2, -1, FromDIP(123)};
    SetStatusWidths(3, statusWidths);
    SetStatusText(Display("mm / 스냅 끔"), 2);
    SetStatusText(Display("서비스 연결 중"), 0);
    SetStatusText(Display("Windows wxWidgets / 개발용"), 1);
    SetMinSize(FromDIP(wxSize(980, 680)));
    const wxRect workArea = wxGetClientDisplayRect();
    const wxSize preferred = FromDIP(wxSize(1660, 960));
    SetSize(wxSize(std::min(preferred.GetWidth(), workArea.GetWidth() - FromDIP(24)),
                   std::min(preferred.GetHeight(), workArea.GetHeight() - FromDIP(24))));
    Centre();
    StudioTheme::BindSurface(*this, StudioTheme::Surface::Workspace);
    m_manager = new wxAuiManager(this);
    StudioTheme::ConfigureDocking(*m_manager, *this);
    Bind(wxEVT_SYS_COLOUR_CHANGED,
         [this](wxSysColourChangedEvent& event)
         {
             StudioTheme::ConfigureDocking(*m_manager, *this);
             if (m_tools.count(IdDeleteShape) != 0)
             {
                 StyleDrawingRail({m_tools.at(IdSelect), m_tools.at(IdLine), m_tools.at(IdArc),
                                   m_tools.at(IdCoordinates), m_tools.at(IdFit), m_tools.at(IdDeleteShape)});
                 SelectDrawingRail({m_tools.at(IdSelect), m_tools.at(IdLine), m_tools.at(IdArc)},
                                   m_drawTool == "line" ? 1 : (m_drawTool == "arc" ? 2 : 0));
             }
             m_manager->Update();
             event.Skip();
         });
    auto* workspace = new wxPanel(this);
    StudioTheme::BindSurface(*workspace);
    auto* top = new wxBoxSizer(wxVERTICAL);
    m_workspaceBar = new WorkspaceBar(workspace);
    m_workspaceBar->onNavigate = [this](WorkspaceArea area)
    {
        NavigateWorkspace(area);
    };
    m_workspaceBar->onCommand = [this](int action)
    {
        const int commands[] = {IdSave, IdRunSolver, IdExportStep};
        wxCommandEvent command(wxEVT_MENU, commands[action]);
        GetEventHandler()->ProcessEvent(command);
    };
    top->Add(m_workspaceBar, 0, wxEXPAND);
    // @brief 메뉴와 트리에서 실행하는 명령도 기존 활성 조건을 공유한다.
    auto* commandHost = new wxPanel(this);
    commandHost->SetName("workspace.command-state");
    auto* commandSizer = new wxBoxSizer(wxVERTICAL);
    for (const auto& command : std::vector<std::pair<int, std::string>>{{IdCreate, "새 프로젝트"},
                                                                        {IdOpen, "열기"},
                                                                        {IdSave, "저장"},
                                                                        {IdSnapshot, "스냅샷"},
                                                                        {IdUndo, "실행 취소"},
                                                                        {IdRedo, "다시 실행"},
                                                                        {IdExportStep, "STEP 출력"},
                                                                        {IdTargets, "목표 / 대역 설정"},
                                                                        {IdTemplates, "문헌 / 형상 / 초기 후보"},
                                                                        {IdPcbSelection, "기판 설정 / 자료 선택"},
                                                                        {IdPhysicalSetup, "적층 / 외부 환경"},
                                                                        {IdBoard, "사각 기판"},
                                                                        {IdCircularBoard, "원형 기판"},
                                                                        {IdLayer, "도체층"},
                                                                        {IdDielectric, "유전체층"}})
    {
        AddTool(commandHost, commandSizer, command.first, command.second);
    }
    m_steps = new wxListBox(commandHost, wxID_ANY);
    for (const auto& label : {"1  기판", "2  패턴", "3  재료", "4  급전", "5  입력 검사"})
    {
        m_steps->Append(Display(label));
    }
    commandSizer->Add(m_steps, 0, wxEXPAND);
    commandHost->SetSizerAndFit(commandSizer);
    commandHost->Hide();
    workspace->SetSizer(top);
    m_manager->AddPane(workspace, wxAuiPaneInfo()
                                      .Name("workspace")
                                      .Top()
                                      .Layer(2)
                                      .CaptionVisible(false)
                                      .CloseButton(false)
                                      .Resizable(false)
                                      .PaneBorder(false)
                                      .BestSize(wxSize(-1, top->GetMinSize().GetHeight()))
                                      .MinSize(wxSize(-1, top->GetMinSize().GetHeight())));

    auto* navigation = new wxPanel(this);
    StudioTheme::BindSurface(*navigation);
    auto* navigationSizer = new wxBoxSizer(wxVERTICAL);
    auto* navigationTabs = new wxNotebook(navigation, wxID_ANY);
    navigationTabs->SetPadding(FromDIP(wxSize(16, 8)));
    navigationTabs->SetName("workspace.navigation-tabs");
    auto* navigationContent = new wxPanel(navigationTabs);
    StudioTheme::BindSurface(*navigationContent);
    auto* navigationContents = new wxBoxSizer(wxVERTICAL);
    BuildNavigation(navigationContent, navigationContents);
    navigationContent->SetSizer(navigationContents);
    navigationTabs->AddPage(navigationContent, Display("탐색"));
    navigationSizer->Add(navigationTabs, 1, wxEXPAND);
    navigation->SetSizer(navigationSizer);
    m_manager->AddPane(navigation, wxAuiPaneInfo()
                                       .Name("navigation")
                                       .Caption(Display("프로젝트"))
                                       .Left()
                                       .Layer(1)
                                       .Position(0)
                                       .BestSize(FromDIP(wxSize(280, 600)))
                                       .MinSize(FromDIP(wxSize(220, 240)))
                                       .CloseButton(true));
    m_manager->GetPane("navigation").dock_proportion = 2;

    m_views = new StudioNotebook(this);
    m_views->ConfigurePages({0, 0, 2, 1, 3, 4, 2, 2, 1, 2, 2, 2, 2, 2, 3, 3, 3},
                            {0, 1, 9, 10, 11, 12, 13, 7, 6, 2, 3, 8, 14, 16, 4, 15, 5});
    auto* center = new wxPanel(m_views);
    StudioTheme::BindSurface(*center);
    auto* centerSizer = new wxBoxSizer(wxVERTICAL);
    m_startActions = new wxPanel(center);
    StudioTheme::BindSurface(*m_startActions);
    auto* startLayout = new wxBoxSizer(wxHORIZONTAL);
    auto* startTitle = new wxStaticText(m_startActions, wxID_ANY, Display("프로젝트 시작"));
    StudioTheme::Heading(*startTitle);
    startLayout->Add(startTitle, 0, wxALIGN_CENTER_VERTICAL | wxRIGHT, FromDIP(StudioTheme::GroupGap));
    const auto startButton = [&](int id, const char* label, bool primary)
    {
        auto* button = new wxButton(m_startActions, wxID_ANY, Display(label));
        StudioTheme::Button(*button, primary);
        startLayout->Add(button, 0, wxRIGHT, FromDIP(StudioTheme::InputGap));
        button->Bind(wxEVT_BUTTON, [this, id](wxCommandEvent&)
        {
            wxCommandEvent command(wxEVT_MENU, id);
            ProcessWindowEvent(command);
        });
        return button;
    };
    m_startCreate = startButton(IdCreate, "새 프로젝트", true);
    m_startOpen = startButton(IdOpen, "프로젝트 열기", false);
    m_startActions->SetSizer(startLayout);
    centerSizer->Add(m_startActions, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::PanelPadding));
    auto* drawingTools = new wxWrapSizer(wxHORIZONTAL);
    AddTool(center, drawingTools, IdSelect, "선택");
    AddTool(center, drawingTools, IdLine, "선");
    AddTool(center, drawingTools, IdArc, "원호");
    AddTool(center, drawingTools, IdCoordinates, "좌표 입력");
    AddTool(center, drawingTools, IdFit, "전체 보기");
    AddTool(center, drawingTools, IdDeleteShape, "삭제");
    StyleDrawingRail({m_tools.at(IdSelect), m_tools.at(IdLine), m_tools.at(IdArc), m_tools.at(IdCoordinates),
                      m_tools.at(IdFit), m_tools.at(IdDeleteShape)});
    centerSizer->Add(drawingTools, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::Space));
    auto* context = new wxWrapSizer(wxHORIZONTAL);
    auto* layerTools = new wxBoxSizer(wxHORIZONTAL);
    layerTools->Add(new wxStaticText(center, wxID_ANY, Display("활성 층")), 0, wxALIGN_CENTER_VERTICAL | wxRIGHT,
                    FromDIP(StudioTheme::Space));
    m_layerChoice = new wxChoice(center, wxID_ANY);
    m_layerChoice->SetMinSize(FromDIP(wxSize(140, -1)));
    layerTools->Add(m_layerChoice, 0, wxALIGN_CENTER_VERTICAL);
    context->Add(layerTools, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(StudioTheme::Space));
    auto* widthTools = new wxBoxSizer(wxHORIZONTAL);
    widthTools->Add(new wxStaticText(center, wxID_ANY, Display("선폭")), 0, wxALIGN_CENTER_VERTICAL | wxRIGHT,
                    FromDIP(StudioTheme::Space));
    m_width = new wxSpinCtrlDouble(center, wxID_ANY, "0.80", wxDefaultPosition, FromDIP(wxSize(90, -1)),
                                   wxSP_ARROW_KEYS, 0.001, 1000.0, 0.8, 0.05);
    m_width->SetDigits(3);
    widthTools->Add(m_width, 0, wxALIGN_CENTER_VERTICAL);
    widthTools->Add(new wxStaticText(center, wxID_ANY, "mm"), 0, wxALIGN_CENTER_VERTICAL | wxLEFT,
                    FromDIP(StudioTheme::Space));
    context->Add(widthTools, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(StudioTheme::Space));
    m_snapCheck = new wxCheckBox(center, wxID_ANY, Display("스냅"));
    m_snapCheck->SetName("canvas.snap");
    m_snapCheck->SetToolTip(Display("같은 층의 보이는 선·원호 끝점에 우선 맞춥니다. 십자 표시는 격자 스냅입니다."));
    drawingTools->Add(m_snapCheck, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(StudioTheme::InputGap));
    m_drawingRelations = new wxCheckBox(center, wxID_ANY, Display("그리기 구속"));
    m_drawingRelations->SetName("canvas.drawing_relations");
    m_drawingRelations->SetToolTip(Display("켜고 관계 후보를 클릭하면 수평, 수직, 일치, 중점 또는 원호 끝점 접선을 형상과 함께 저장합니다."));
    drawingTools->Add(m_drawingRelations, 0, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(StudioTheme::InputGap));
    BuildPrecisionTools(center, context);
    centerSizer->Add(context, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, FromDIP(StudioTheme::Space));
    m_canvas = new DesignCanvas(center);
    m_canvas->SetStrokeWidth(m_width->GetValue());
    centerSizer->Add(m_canvas, 1, wxEXPAND);
    m_canvasHint = new wxStaticText(center, wxID_ANY, Display("프로젝트를 열고 기판과 도체층을 만들어 시작하세요."));
    StudioTheme::BindSecondary(*m_canvasHint);
    centerSizer->Add(m_canvasHint, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::InputGap));
    center->SetSizer(centerSizer);
    m_views->AddPage(center, Display("2D 편집"));
    auto* modelPanel = new wxPanel(m_views);
    StudioTheme::BindSurface(*modelPanel);
    auto* modelSizer = new wxBoxSizer(wxVERTICAL);
    auto* modelTools = new wxWrapSizer(wxHORIZONTAL);
    AddTool(modelPanel, modelTools, IdBuild3D, "3D 갱신");
    AddTool(modelPanel, modelTools, IdFit3D, "전체 보기");
    AddTool(modelPanel, modelTools, IdTop3D, "위에서");
    AddTool(modelPanel, modelTools, IdIso3D, "입체 보기");
    modelSizer->Add(modelTools, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::Space));
    m_modelState = new wxStaticText(modelPanel, wxID_ANY,
                                    Display("아직 생성한 3D 형상이 없습니다. 층 위치와 두께를 입력한 뒤 갱신하세요."));
    modelSizer->Add(m_modelState, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::InputGap));
    m_modelView = new ModelView(modelPanel);
    m_modelView->EnableSections();
    modelSizer->Add(m_modelView, 1, wxEXPAND);
    m_modelHint = new wxStaticText(modelPanel, wxID_ANY, Display("표시용 형상 / 실제 두께 / 제조 및 RF 검증 전"));
    StudioTheme::BindSecondary(*m_modelHint);
    modelSizer->Add(m_modelHint, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::InputGap));
    modelPanel->SetSizer(modelSizer);
    m_views->AddPage(modelPanel, Display("3D 형상"));
    BuildSolverInterface();
    m_manager->AddPane(m_views,
                       wxAuiPaneInfo().Name("canvas").Caption(Display("설계 / mm")).CenterPane().PaneBorder(false));

    auto* propertiesHost = new wxPanel(this);
    StudioTheme::BindSurface(*propertiesHost);
    propertiesHost->SetSizer(new wxBoxSizer(wxVERTICAL));
    m_properties = new wxPanel(propertiesHost);
    StudioTheme::BindSurface(*m_properties);
    auto* form = new wxBoxSizer(wxVERTICAL);
    const int metadataGap = FromDIP(StudioTheme::InputGap);
    m_selectionLabel = new wxStaticText(m_properties, wxID_ANY, Display("프로젝트 속성"),
        wxDefaultPosition, wxDefaultSize, wxST_ELLIPSIZE_END | wxST_NO_AUTORESIZE);
    m_selectionLabel->SetName("project.properties.heading");
    StudioTheme::Title(*m_selectionLabel);
    form->Add(m_selectionLabel, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::PanelPadding));
    BuildPortLinks(*form);
    m_metadataPanel = new wxPanel(m_properties);
    StudioTheme::BindSurface(*m_metadataPanel);
    auto* metadataForm = new wxBoxSizer(wxVERTICAL);
    auto* nameLabel = new wxStaticText(m_metadataPanel, wxID_ANY, Display("이름"));
    metadataForm->Add(nameLabel, 0, wxBOTTOM, metadataGap);
    m_name = new wxTextCtrl(m_metadataPanel, wxID_ANY, wxEmptyString, wxDefaultPosition,
                            FromDIP(wxSize(-1, 56)), wxTE_MULTILINE | wxTE_WORDWRAP);
    m_name->SetName(Display("이름"));
    m_name->SetToolTip(Display("프로젝트 이름"));
    m_name->Bind(wxEVT_CHAR, [](wxKeyEvent& event)
    {
        if (event.GetKeyCode() != WXK_RETURN && event.GetKeyCode() != WXK_NUMPAD_ENTER)
        {
            event.Skip();
        }
    });
    metadataForm->Add(m_name, 0, wxEXPAND | wxBOTTOM, 2 * metadataGap);
    auto* descriptionLabel = new wxStaticText(m_metadataPanel, wxID_ANY, Display("설명"));
    metadataForm->Add(descriptionLabel, 0, wxBOTTOM, metadataGap);
    m_description = new wxTextCtrl(m_metadataPanel, wxID_ANY, wxEmptyString, wxDefaultPosition,
                                   FromDIP(wxSize(-1, 156)), wxTE_MULTILINE | wxTE_WORDWRAP);
    m_description->SetName(Display("설명"));
    m_description->SetToolTip(Display("프로젝트 설명"));
    metadataForm->Add(m_description, 0, wxEXPAND);
    m_metadataDiagnostic = new wxStaticText(m_metadataPanel, wxID_ANY, wxEmptyString);
    metadataForm->Add(m_metadataDiagnostic, 0, wxEXPAND | wxTOP, FromDIP(StudioTheme::InputGap));
    m_metadataDiagnostic->Hide();
    m_metadataPanel->SetSizer(metadataForm);
    form->Add(m_metadataPanel, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::PanelPadding));
    m_editorPanel = new EditorPanel(m_properties);
    form->Add(m_editorPanel, 1, wxEXPAND | wxLEFT | wxRIGHT, FromDIP(StudioTheme::Space));
    m_editorPanel->Hide();
    m_apply = new wxButton(m_properties, IdApply, Display("변경 적용"));
    StudioTheme::Button(*m_apply, true);
    form->Add(m_apply, 0, wxALL | wxALIGN_RIGHT, FromDIP(StudioTheme::PanelPadding));
    m_solverRepairBack = new wxButton(m_properties, wxID_ANY, Display("해석 검토로 돌아가기"));
    m_solverRepairBack->SetName("solver.repair.resume");
    StudioTheme::Button(*m_solverRepairBack);
    m_solverRepairBack->Hide();
    form->Add(m_solverRepairBack, 0, wxLEFT | wxRIGHT | wxBOTTOM | wxALIGN_RIGHT, FromDIP(StudioTheme::PanelPadding));
    m_revisionLabel = new wxStaticText(m_properties, wxID_ANY, Display("프로젝트를 만들거나 열어 시작하세요."));
    StudioTheme::BindSecondary(*m_revisionLabel);
    form->Add(m_revisionLabel, 0, wxEXPAND | wxALL, FromDIP(StudioTheme::PanelPadding));
    m_properties->SetSizer(form);
    propertiesHost->GetSizer()->Add(m_properties, 1, wxEXPAND);
    m_manager->AddPane(propertiesHost, wxAuiPaneInfo()
                                           .Name("properties")
                                           .Caption(Display("속성"))
                                           .Right()
                                           .Layer(1)
                                           .BestSize(FromDIP(wxSize(342, 600)))
                                           .MinSize(FromDIP(wxSize(320, 220)))
                                           .CloseButton(true));

    m_bottom = new StudioNotebook(this);
    auto* problemPanel = new wxPanel(m_bottom);
    StudioTheme::BindSurface(*problemPanel);
    auto* problemSizer = new wxBoxSizer(wxVERTICAL);
    auto* problemHeader = new wxBoxSizer(wxHORIZONTAL);
    m_problemSummary = new wxStaticText(problemPanel, wxID_ANY, Display("입력 검사를 실행하지 않았습니다."));
    problemHeader->Add(m_problemSummary, 1, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(StudioTheme::InputGap));
    AddTool(problemPanel, problemHeader, IdValidate, "해석 입력 검사");
    AddTool(problemPanel, problemHeader, IdDesignRules, "제약 / 연결 / DRC");
    problemSizer->Add(problemHeader, 0, wxEXPAND);
    m_problems =
        new wxListCtrl(problemPanel, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL);
    StudioTheme::Table(*m_problems);
    m_problems->AppendColumn(Display("상태"), wxLIST_FORMAT_LEFT, FromDIP(110));
    m_problems->AppendColumn(Display("내용 / 두 번 눌러 위치로 이동"), wxLIST_FORMAT_LEFT, FromDIP(650));
    problemSizer->Add(m_problems, 1, wxEXPAND);
    problemPanel->SetSizer(problemSizer);
    m_bottom->AddPage(problemPanel, Display("문제"));
    m_log = new wxTextCtrl(m_bottom, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize,
                           wxTE_MULTILINE | wxTE_READONLY);
    m_bottom->AddPage(m_log, Display("로그"));
    auto* cadPanel = new wxPanel(m_bottom);
    StudioTheme::BindSurface(*cadPanel);
    auto* cadSizer = new wxBoxSizer(wxVERTICAL);
    auto* cadTools = new wxBoxSizer(wxHORIZONTAL);
    m_cadStatus = new wxStaticText(cadPanel, wxID_ANY, Display("CAD 환경 연결을 확인하고 있습니다."));
    cadTools->Add(m_cadStatus, 1, wxALL | wxALIGN_CENTER_VERTICAL, FromDIP(StudioTheme::InputGap));
    AddTool(cadPanel, cadTools, IdCancelCad, "작업 취소");
    AddTool(cadPanel, cadTools, IdOutputFolder, "출력 폴더 열기");
    cadSizer->Add(cadTools, 0, wxEXPAND);
    m_cadDetails = new wxTextCtrl(cadPanel, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize,
                                  wxTE_MULTILINE | wxTE_READONLY);
    cadSizer->Add(m_cadDetails, 1, wxEXPAND);
    cadPanel->SetSizer(cadSizer);
    m_bottom->AddPage(cadPanel, Display("CAD 출력"));
    m_manager->AddPane(m_bottom, wxAuiPaneInfo()
                                     .Name("problems")
                                     .CaptionVisible(false)
                                     .Bottom()
                                     .BestSize(FromDIP(wxSize(900, 192)))
                                     .MinSize(FromDIP(wxSize(300, 110)))
                                     .CloseButton(true));
    BuildWorkspaceJobs();
    BuildWorkspaceLayers();
    m_views->onPrepareSelection = [this](std::size_t page)
    {
        PrepareExtendedWorkspaces(page);
    };
    m_manager->Update();
    m_defaultLayout = m_manager->SavePerspective();
    m_shell = std::make_unique<StudioShell>(*this, *m_manager, *navigationTabs, *m_tree, *propertiesHost, *m_properties,
                                            *m_views, *m_bottom, *m_workspaceBar, *view, !m_options.smoke);
    BindCanvas();
    BindCad();
    BindSolver();
    /** @brief 사용자가 값을 다시 편집하면 직전 거절 안내를 지운다. */
    const auto metadataChanged = [this](wxCommandEvent&)
    {
        if (m_metadataDiagnostic->IsShown())
        {
            m_metadataDiagnostic->Hide();
            m_properties->Layout();
        }
        UpdateDraftState();
    };
    m_name->Bind(wxEVT_TEXT, metadataChanged);
    m_description->Bind(wxEVT_TEXT, metadataChanged);
    m_editorPanel->Bind(wxEVT_RFAD_EDITOR_CHANGED,
                        [this](wxCommandEvent&)
                        {
                            UpdateDraftState();
                        });
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            if (!ConfirmDiscard())
            {
                return;
            }
            const wxString name = ReadProjectText(*this, "프로젝트 만들기", "새 프로젝트 이름",
                                                  Display("새 안테나"), "만들기");
            if (!name.empty())
            {
                OpenProject("create", "projects/" + Utf8(name), Utf8(name));
            }
        },
        IdCreate);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            if (!ConfirmDiscard())
            {
                return;
            }
            const wxString path = ReadProjectText(*this, "프로젝트 열기", "작업 영역에 등록된 경로 (projects/이름)",
                                                  Display(m_path.empty() ? "projects/새 안테나" : m_path), "열기");
            if (!path.empty())
            {
                OpenProject("open", Utf8(path));
            }
        },
        IdOpen);
    Bind(wxEVT_MENU, [this](wxCommandEvent&) { OpenArchiveRestore(); }, IdArchiveRestore);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            SaveProject();
        },
        IdSave);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            Snapshot();
        },
        IdSnapshot);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            Close();
        },
        wxID_EXIT);
    Bind(
        wxEVT_BUTTON,
        [this](wxCommandEvent&)
        {
            ApplyProperties();
        },
        IdApply);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            History("project.undo");
        },
        IdUndo);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            History("project.redo");
        },
        IdRedo);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            if (ConfirmDiscard())
            {
                SelectObject(Json{{"kind", "new_parameter"}, {"id", Uuid()}});
            }
        },
        IdNewParameter);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            if (ConfirmDiscard())
            {
                OpenProject("open", m_path);
            }
        },
        IdRefresh);
    m_tree->Bind(wxEVT_TREE_SEL_CHANGING,
                 [this](wxTreeEvent& event)
                 {
                     if (!m_refreshing && (m_busy || !ConfirmDiscard()))
                     {
                         event.Veto();
                     }
                 });
    m_tree->Bind(wxEVT_TREE_SEL_CHANGED,
                 [this](wxTreeEvent& event)
                 {
                     if (m_refreshing)
                     {
                         return;
                     }
                     auto* data = dynamic_cast<SelectionData*>(m_tree->GetItemData(event.GetItem()));
                     if (data != nullptr)
                     {
                         SelectObject(data->selection, true);
                     }
                 });
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            OpenPcbSelection();
        },
        IdPcbSelection);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            OpenDesignSetup(DesignSetup::Targets);
        },
        IdTargets);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            OpenDesignSetup(DesignSetup::Templates);
        },
        IdTemplates);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            OpenDesignSetup(DesignSetup::Rules);
        },
        IdDesignRules);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            OpenDesignSetup(DesignSetup::Physical);
        },
        IdPhysicalSetup);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            OpenPcbFeatures();
        },
        IdPcbFeatures);
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            OpenPcbImport();
        },
        IdPcbImport);
    UpdateControls();
}

/** @brief 메뉴와 도구 버튼이 같은 명령 처리기를 사용하도록 연결한다. */
void StudioFrame::AddTool(wxWindow* parent, wxSizer* sizer, int id, const std::string& label)
{
    auto* button = new wxButton(parent, id, Display(label), wxDefaultPosition, wxDefaultSize, wxBU_EXACTFIT);
    if (id != IdSelect && id != IdLine && id != IdArc)
    {
        StudioTheme::Button(*button);
    }
    sizer->Add(button, 0, wxALL | wxALIGN_CENTER_VERTICAL, parent->FromDIP(StudioTheme::Space));
    m_tools[id] = button;
    button->Bind(wxEVT_BUTTON,
                 [this, id](wxCommandEvent&)
                 {
                     wxCommandEvent command(wxEVT_MENU, id);
                     GetEventHandler()->ProcessEvent(command);
                 });
}
