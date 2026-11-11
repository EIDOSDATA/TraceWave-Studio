/** @file @brief 주 창의 layout 책임을 구현한다. */
#include "studio_internal.h"
#include "study_report_dialog.h"

/** @brief 프로젝트 메타데이터와 선택 객체의 서비스 기반 입력 폼을 구성한다. */
void StudioFrame::BuildInterface()
{
    auto* menu = new wxMenu;
    menu->Append(IdCreate, Display("새 프로젝트(&N)\tCtrl+N"));
    menu->Append(IdOpen, Display("프로젝트 열기(&O)\tCtrl+O"));
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
    auto* bar = new wxMenuBar;
    bar->Append(menu, Display("프로젝트"));
    bar->Append(edit, Display("편집"));
    auto* design = new wxMenu;
    design->Append(IdBoard, Display("직사각 기판 만들기"));
    design->Append(IdCircularBoard, Display("원형 기판 만들기"));
    design->Append(IdPcbSelection, Display("기판 설정 / 제조업체 자료"));
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
    analysis->Append(IdCancelSolver, Display("해석 작업 취소"));
    analysis->Append(IdRadiation, Display("방사 패턴 조회"));
    analysis->Append(IdProjectStudy, Display("프로젝트 연구 / 격자·방사·손실"));
    Bind(wxEVT_MENU, [this](wxCommandEvent&) { OpenProjectStudy(); }, IdProjectStudy);
    const int studyReportId = wxWindow::NewControlId();
    analysis->Append(studyReportId, Display("수렴 연구 보고서 비교"));
    Bind(
        wxEVT_MENU,
        [this](wxCommandEvent&)
        {
            ShowStudyReport(this);
        },
        studyReportId);
    bar->Append(analysis, Display("해석"));
    auto* view = new wxMenu;
    view->Append(IdResetLayout, Display("기본 패널 배치 복원"));
    view->Append(IdFit, Display("전체 형상 맞춤"));
    view->Append(IdBuild3D, Display("현재 설계로 3D 갱신"));
    view->Append(IdOutputFolder, Display("STEP 출력 폴더 열기"));
    view->Append(IdCancelCad, Display("CAD 작업 취소"));
    bar->Append(view, Display("보기"));
    SetMenuBar(bar);
    CreateStatusBar(2);
    SetStatusText(Display("서비스 연결 중"), 0);
    SetStatusText(Display("Windows wxWidgets / 개발용"), 1);
    SetMinSize(FromDIP(wxSize(980, 680)));
    const wxRect workArea = wxGetClientDisplayRect();
    const wxSize preferred = FromDIP(wxSize(1360, 860));
    SetSize(wxSize(std::min(preferred.GetWidth(), workArea.GetWidth() - FromDIP(24)),
                   std::min(preferred.GetHeight(), workArea.GetHeight() - FromDIP(24))));
    Centre();
    m_manager = new wxAuiManager(this);
    auto* workspace = new wxPanel(this);
    auto* top = new wxBoxSizer(wxHORIZONTAL);
    auto* title = new wxStaticText(workspace, wxID_ANY, Display("TraceWave Studio / 설계"));
    title->SetFont(title->GetFont().Bold());
    top->Add(title, 1, wxALIGN_CENTER_VERTICAL | wxALL, 10);
    AddTool(workspace, top, IdCreate, "새 프로젝트");
    AddTool(workspace, top, IdOpen, "열기");
    AddTool(workspace, top, IdSave, "저장");
    AddTool(workspace, top, IdSnapshot, "스냅샷");
    AddTool(workspace, top, IdUndo, "실행 취소");
    AddTool(workspace, top, IdRedo, "다시 실행");
    AddTool(workspace, top, IdExportStep, "STEP 출력");
    workspace->SetSizer(top);
    m_manager->AddPane(workspace, wxAuiPaneInfo()
                                      .Name("workspace")
                                      .Top()
                                      .CaptionVisible(false)
                                      .CloseButton(false)
                                      .Resizable(false)
                                      .PaneBorder(false)
                                      .BestSize(wxSize(-1, FromDIP(44)))
                                      .MinSize(wxSize(-1, FromDIP(38))));

    auto* navigation = new wxPanel(this);
    auto* navigationSizer = new wxBoxSizer(wxVERTICAL);
    navigationSizer->Add(new wxStaticText(navigation, wxID_ANY, Display("설계 단계")), 0, wxALL, 8);
    m_steps = new wxListBox(navigation, wxID_ANY);
    for (const auto& label : {"1  기판", "2  패턴", "3  재료", "4  급전", "5  입력 검사"})
    {
        m_steps->Append(Display(label));
    }
    navigationSizer->Add(m_steps, 0, wxEXPAND | wxLEFT | wxRIGHT, 6);
    AddTool(navigation, navigationSizer, IdPcbSelection, "기판 설정 / 자료 선택");
    navigationSizer->Add(new wxStaticText(navigation, wxID_ANY, Display("객체 / 레이어")), 0, wxALL, 8);
    m_tree =
        new wxTreeCtrl(navigation, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxTR_HAS_BUTTONS | wxTR_LINES_AT_ROOT);
    m_tree->AddRoot(Display("프로젝트 없음"));
    navigationSizer->Add(m_tree, 1, wxEXPAND);
    navigation->SetSizer(navigationSizer);
    m_manager->AddPane(navigation, wxAuiPaneInfo()
                                       .Name("navigation")
                                       .Caption(Display("프로젝트 탐색"))
                                       .Left()
                                       .BestSize(FromDIP(wxSize(235, 600)))
                                       .MinSize(FromDIP(wxSize(180, 240)))
                                       .CloseButton(false));

    m_views = new wxNotebook(this, wxID_ANY);
    auto* center = new wxPanel(m_views);
    auto* centerSizer = new wxBoxSizer(wxVERTICAL);
    auto* drawingTools = new wxBoxSizer(wxHORIZONTAL);
    AddTool(center, drawingTools, IdSelect, "선택");
    AddTool(center, drawingTools, IdLine, "선");
    AddTool(center, drawingTools, IdArc, "원호");
    AddTool(center, drawingTools, IdCoordinates, "좌표 입력");
    AddTool(center, drawingTools, IdFit, "전체 보기");
    AddTool(center, drawingTools, IdDeleteShape, "삭제");
    centerSizer->Add(drawingTools, 0, wxEXPAND | wxALL, 4);
    auto* context = new wxBoxSizer(wxHORIZONTAL);
    AddTool(center, context, IdBoard, "사각 기판");
    AddTool(center, context, IdCircularBoard, "원형 기판");
    AddTool(center, context, IdLayer, "도체층");
    AddTool(center, context, IdDielectric, "유전체층");
    context->Add(new wxStaticText(center, wxID_ANY, Display("활성 층")), 0, wxALIGN_CENTER_VERTICAL | wxLEFT, 6);
    m_layerChoice = new wxChoice(center, wxID_ANY);
    context->Add(m_layerChoice, 1, wxALIGN_CENTER_VERTICAL | wxLEFT, 4);
    context->Add(new wxStaticText(center, wxID_ANY, Display("선폭")), 0, wxALIGN_CENTER_VERTICAL | wxLEFT, 6);
    m_width = new wxSpinCtrlDouble(center, wxID_ANY, "0.80", wxDefaultPosition, FromDIP(wxSize(90, -1)),
                                   wxSP_ARROW_KEYS, 0.001, 1000.0, 0.8, 0.05);
    m_width->SetDigits(3);
    context->Add(m_width, 0, wxALIGN_CENTER_VERTICAL | wxLEFT, 4);
    context->Add(new wxStaticText(center, wxID_ANY, "mm"), 0, wxALIGN_CENTER_VERTICAL | wxLEFT | wxRIGHT, 4);
    centerSizer->Add(context, 0, wxEXPAND | wxLEFT | wxRIGHT | wxBOTTOM, 4);
    m_canvas = new DesignCanvas(center);
    m_canvas->SetStrokeWidth(m_width->GetValue());
    centerSizer->Add(m_canvas, 1, wxEXPAND);
    m_canvasHint = new wxStaticText(center, wxID_ANY, Display("프로젝트를 열고 기판과 도체층을 만들어 시작하세요."));
    centerSizer->Add(m_canvasHint, 0, wxEXPAND | wxALL, 6);
    center->SetSizer(centerSizer);
    m_views->AddPage(center, Display("2D 편집"));
    auto* modelPanel = new wxPanel(m_views);
    auto* modelSizer = new wxBoxSizer(wxVERTICAL);
    auto* modelTools = new wxBoxSizer(wxHORIZONTAL);
    AddTool(modelPanel, modelTools, IdBuild3D, "3D 갱신");
    AddTool(modelPanel, modelTools, IdFit3D, "전체 보기");
    AddTool(modelPanel, modelTools, IdTop3D, "위에서");
    AddTool(modelPanel, modelTools, IdIso3D, "입체 보기");
    modelSizer->Add(modelTools, 0, wxEXPAND | wxALL, 4);
    m_modelState = new wxStaticText(modelPanel, wxID_ANY,
                                    Display("아직 생성한 3D 형상이 없습니다. 층 위치와 두께를 입력한 뒤 갱신하세요."));
    modelSizer->Add(m_modelState, 0, wxEXPAND | wxALL, 6);
    m_modelView = new ModelView(modelPanel);
    modelSizer->Add(m_modelView, 1, wxEXPAND);
    m_modelHint = new wxStaticText(modelPanel, wxID_ANY, Display("표시용 형상 / 실제 두께 / 제조 및 RF 검증 전"));
    modelSizer->Add(m_modelHint, 0, wxEXPAND | wxALL, 6);
    modelPanel->SetSizer(modelSizer);
    m_views->AddPage(modelPanel, Display("3D 형상"));
    BuildSolverInterface();
    m_manager->AddPane(m_views,
                       wxAuiPaneInfo().Name("canvas").Caption(Display("설계 / mm")).CenterPane().PaneBorder(false));

    m_properties = new wxPanel(this);
    auto* form = new wxBoxSizer(wxVERTICAL);
    m_selectionLabel = new wxStaticText(m_properties, wxID_ANY, Display("프로젝트 속성"));
    m_selectionLabel->SetFont(m_selectionLabel->GetFont().Bold());
    form->Add(m_selectionLabel, 0, wxALL, 10);
    m_metadataPanel = new wxPanel(m_properties);
    auto* fields = new wxFlexGridSizer(2, 8, 8);
    fields->AddGrowableCol(1);
    fields->Add(new wxStaticText(m_metadataPanel, wxID_ANY, Display("이름")), 0, wxALIGN_CENTER_VERTICAL);
    m_name = new wxTextCtrl(m_metadataPanel, wxID_ANY);
    fields->Add(m_name, 1, wxEXPAND);
    fields->Add(new wxStaticText(m_metadataPanel, wxID_ANY, Display("설명")), 0, wxALIGN_TOP);
    m_description = new wxTextCtrl(m_metadataPanel, wxID_ANY, wxEmptyString, wxDefaultPosition,
                                   FromDIP(wxSize(-1, 100)), wxTE_MULTILINE);
    fields->Add(m_description, 1, wxEXPAND);
    m_metadataPanel->SetSizer(fields);
    form->Add(m_metadataPanel, 0, wxEXPAND | wxALL, 10);
    m_editorPanel = new EditorPanel(m_properties);
    form->Add(m_editorPanel, 1, wxEXPAND | wxLEFT | wxRIGHT, 4);
    m_editorPanel->Hide();
    m_apply = new wxButton(m_properties, IdApply, Display("변경 적용"));
    form->Add(m_apply, 0, wxALL | wxALIGN_RIGHT, 10);
    m_revisionLabel = new wxStaticText(m_properties, wxID_ANY, Display("프로젝트를 만들거나 열어 시작하세요."));
    form->Add(m_revisionLabel, 0, wxEXPAND | wxALL, 10);
    m_properties->SetSizer(form);
    m_manager->AddPane(m_properties, wxAuiPaneInfo()
                                         .Name("properties")
                                         .Caption(Display("선택 속성"))
                                         .Right()
                                         .BestSize(FromDIP(wxSize(380, 600)))
                                         .MinSize(FromDIP(wxSize(320, 220)))
                                         .CloseButton(false));

    m_bottom = new wxNotebook(this, wxID_ANY);
    auto* problemPanel = new wxPanel(m_bottom);
    auto* problemSizer = new wxBoxSizer(wxVERTICAL);
    auto* problemHeader = new wxBoxSizer(wxHORIZONTAL);
    m_problemSummary = new wxStaticText(problemPanel, wxID_ANY, Display("입력 검사를 실행하지 않았습니다."));
    problemHeader->Add(m_problemSummary, 1, wxALL | wxALIGN_CENTER_VERTICAL, 6);
    AddTool(problemPanel, problemHeader, IdValidate, "해석 입력 검사");
    problemSizer->Add(problemHeader, 0, wxEXPAND);
    m_problems =
        new wxListCtrl(problemPanel, wxID_ANY, wxDefaultPosition, wxDefaultSize, wxLC_REPORT | wxLC_SINGLE_SEL);
    m_problems->AppendColumn(Display("상태"), wxLIST_FORMAT_LEFT, FromDIP(110));
    m_problems->AppendColumn(Display("내용 / 두 번 눌러 위치로 이동"), wxLIST_FORMAT_LEFT, FromDIP(650));
    problemSizer->Add(m_problems, 1, wxEXPAND);
    problemPanel->SetSizer(problemSizer);
    m_bottom->AddPage(problemPanel, Display("문제"));
    m_log = new wxTextCtrl(m_bottom, wxID_ANY, wxEmptyString, wxDefaultPosition, wxDefaultSize,
                           wxTE_MULTILINE | wxTE_READONLY);
    m_bottom->AddPage(m_log, Display("로그"));
    auto* cadPanel = new wxPanel(m_bottom);
    auto* cadSizer = new wxBoxSizer(wxVERTICAL);
    auto* cadTools = new wxBoxSizer(wxHORIZONTAL);
    m_cadStatus = new wxStaticText(cadPanel, wxID_ANY, Display("CAD 환경 연결을 확인하고 있습니다."));
    cadTools->Add(m_cadStatus, 1, wxALL | wxALIGN_CENTER_VERTICAL, 6);
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
                                     .Caption(Display("문제 / 작업 기록"))
                                     .Bottom()
                                     .BestSize(FromDIP(wxSize(900, 180)))
                                     .MinSize(FromDIP(wxSize(300, 110)))
                                     .CloseButton(false));
    m_manager->Update();
    m_defaultLayout = m_manager->SavePerspective();
    BindCanvas();
    BindCad();
    BindSolver();
    m_name->Bind(wxEVT_TEXT,
                 [this](wxCommandEvent&)
                 {
                     UpdateDraftState();
                 });
    m_description->Bind(wxEVT_TEXT,
                        [this](wxCommandEvent&)
                        {
                            UpdateDraftState();
                        });
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
            const wxString name =
                wxGetTextFromUser(Display("새 프로젝트 이름"), Display("프로젝트 만들기"), Display("새 안테나"), this);
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
            const wxString path =
                wxGetTextFromUser(Display("작업 영역에 등록된 경로 (projects/이름)"), Display("프로젝트 열기"),
                                  Display(m_path.empty() ? "projects/새 안테나" : m_path), this);
            if (!path.empty())
            {
                OpenProject("open", Utf8(path));
            }
        },
        IdOpen);
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
    UpdateControls();
}

/** @brief 메뉴와 도구 버튼이 같은 명령 처리기를 사용하도록 연결한다. */
void StudioFrame::AddTool(wxWindow* parent, wxSizer* sizer, int id, const std::string& label)
{
    auto* button = new wxButton(parent, id, Display(label), wxDefaultPosition, wxDefaultSize, wxBU_EXACTFIT);
    sizer->Add(button, 0, wxALL | wxALIGN_CENTER_VERTICAL, 3);
    m_tools[id] = button;
    button->Bind(wxEVT_BUTTON,
                 [this, id](wxCommandEvent&)
                 {
                     wxCommandEvent command(wxEVT_MENU, id);
                     GetEventHandler()->ProcessEvent(command);
                 });
}
